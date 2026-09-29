"""Policy issuance and carrier statement postings (PRD 3.4, 3.5)."""

from decimal import Decimal

from flask import Blueprint

import calc
from cascades import flag_watch_list, rerate_carrier
from errors import ApiError
from response import collection_response, resource_response
from store import create_record, db, ordered, touch
from validation import (
    actor,
    authorize,
    find_policy,
    find_purchase_request,
    find_valuation,
    get_datetime,
    get_id,
    get_int,
    get_money,
    get_string,
    guard_terminal,
    guard_transition,
    is_liaison,
    json_body,
    liaison_carrier_id,
    pagination,
    query_enum,
    query_str,
    scope_check,
)

bp = Blueprint("policies", __name__)

POLICY_STATUSES = (
    "IN_FORCE",
    "PENDING_EXCHANGE",
    "CLAIM_PENDING",
    "EXCHANGED",
    "SURRENDERED",
    "PAID_OUT",
)
POLICY_READ_ROLES = (
    "BenefitsAnalyst",
    "RiskOfficer",
    "TreasuryController",
    "ClaimsAdministrator",
    "CarrierLiaison",
)
VALUATION_ROLES = ("TreasuryController", "RiskOfficer", "CarrierLiaison")
ZERO = Decimal("0.00")


def latest_product_valuation(product_type_id):
    """Greatest as_of_date over every posting of the product's policies,
    ties broken by created_at ascending (PRD 3.5)."""
    rows = []
    for valuation in db.policy_valuations.values():
        policy = db.policies.get(valuation["policy_id"])
        if policy is None or policy["product_type_id"] != product_type_id:
            continue
        rows.append(valuation)
    if not rows:
        return None
    best = ordered(rows)[0]
    for row in ordered(rows)[1:]:
        if row["_as_of_date"] > best["_as_of_date"]:
            best = row
    return best


# ---- policies -----------------------------------------------------------


@bp.post("/policies")
def issue_policy():
    authorize(("BenefitsAnalyst",))
    body = json_body()
    purchase_request_id = get_id(body, "purchase_request_id")
    policy_number = get_string(body, "policy_number")
    raw_issue_date, issue_date = get_datetime(body, "issue_date")

    request = find_purchase_request(purchase_request_id)
    guard_terminal(request["status"], ("ISSUED", "REJECTED", "WITHDRAWN"))
    guard_transition(request["status"] == "APPROVED")
    if any(p["purchase_request_id"] == request["id"] for p in db.policies.values()):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    carrier = db.carriers.get(request["carrier_id"])
    if carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND")
    product = db.product_types.get(request["product_type_id"])
    if product is None:
        raise ApiError("ERR_PRODUCT_TYPE_NOT_FOUND")
    if carrier["status"] != "AUTHORIZED":
        raise ApiError("ERR_CARRIER_RESTRICTED")
    if product["status"] == "CLOSED_TO_NEW":
        raise ApiError("ERR_PRODUCT_CLOSED_TO_NEW")

    premium = request["single_premium_usd"]
    policy = create_record(
        db.policies,
        {
            "purchase_request_id": request["id"],
            "carrier_id": request["carrier_id"],
            "product_type_id": request["product_type_id"],
            "employee_id": request["employee_id"],
            "exchanged_from_policy_id": None,
            "policy_number": policy_number,
            "issue_date": raw_issue_date,
            "_issue_date": issue_date,
            "single_premium_usd": premium,
            "face_amount_usd": request["face_amount_usd"],
            "cost_basis_usd": premium,
            "cash_surrender_value_usd": premium,
            "policy_year": 1,
            "status": "IN_FORCE",
        },
    )

    request["status"] = "ISSUED"
    request["reserved_premium_usd"] = ZERO
    touch(request)

    # the premium moves from reserved to in-force; both totals are recomputed
    # from the member rows so the reserved-premium invariant holds exactly.
    rerate_carrier(carrier)
    return resource_response(policy, 201)


@bp.get("/policies")
def list_policies():
    authorize(POLICY_READ_ROLES)
    limit, offset = pagination()
    carrier_id = query_str("carrier_id")
    product_type_id = query_str("product_type_id")
    employee_id = query_str("employee_id")
    purchase_request_id = query_str("purchase_request_id")
    exchanged_from_policy_id = query_str("exchanged_from_policy_id")
    status = query_enum("status", POLICY_STATUSES)
    if is_liaison():
        scope_check(carrier_id)
        carrier_id = liaison_carrier_id()
    rows = []
    for policy in db.policies.values():
        if carrier_id is not None and policy["carrier_id"] != carrier_id:
            continue
        if product_type_id is not None and policy["product_type_id"] != product_type_id:
            continue
        if employee_id is not None and policy["employee_id"] != employee_id:
            continue
        if purchase_request_id is not None and policy["purchase_request_id"] != purchase_request_id:
            continue
        if (
            exchanged_from_policy_id is not None
            and policy.get("exchanged_from_policy_id") != exchanged_from_policy_id
        ):
            continue
        if status is not None and policy["status"] != status:
            continue
        rows.append(policy)
    return collection_response(rows, limit, offset)


@bp.get("/policies/<policy_id>")
def read_policy(policy_id):
    authorize(POLICY_READ_ROLES)
    policy = find_policy(policy_id)
    scope_check(policy["carrier_id"])
    return resource_response(policy)


# ---- carrier statement postings ----------------------------------------


@bp.post("/policy-valuations")
def post_valuation():
    authorize(("TreasuryController",))
    body = json_body()
    policy_id = get_id(body, "policy_id")
    raw_start, period_start = get_datetime(body, "period_start_date")
    raw_as_of, as_of = get_datetime(body, "as_of_date")
    credited_interest = get_money(body, "credited_interest_usd")
    me_charge = get_money(body, "mortality_expense_charge_usd")
    mva = get_money(
        body, "market_value_adjustment_usd", required=False, default=ZERO, allow_negative=True
    )
    gross_crediting_rate_bps = get_int(body, "gross_crediting_rate_bps", minimum=0)

    policy = find_policy(policy_id)
    if calc.valuation_period_conflicts(policy["id"], period_start, as_of):
        raise ApiError("ERR_VALUATION_PERIOD_OVERLAP")

    product = db.product_types.get(policy["product_type_id"])
    if product is None:
        raise ApiError("ERR_PRODUCT_TYPE_NOT_FOUND")
    carrier = db.carriers.get(policy["carrier_id"])
    if carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND")

    prior_cash_value = policy["cash_surrender_value_usd"]
    figures = calc.valuation_figures(prior_cash_value, credited_interest, me_charge, mva, product)

    # step 1 - persist the statement period
    valuation = create_record(
        db.policy_valuations,
        {
            "policy_id": policy["id"],
            "period_start_date": raw_start,
            "_period_start_date": period_start,
            "as_of_date": raw_as_of,
            "_as_of_date": as_of,
            "prior_cash_value_usd": prior_cash_value,
            "credited_interest_usd": credited_interest,
            "mortality_expense_charge_usd": me_charge,
            "market_value_adjustment_usd": mva,
            "gross_crediting_rate_bps": gross_crediting_rate_bps,
            "cash_value_usd": figures["cash_value_usd"],
            "net_yield_bps": figures["net_yield_bps"],
            "me_charge_bps": figures["me_charge_bps"],
            "me_drift_bps": figures["me_drift_bps"],
            "recorded_by_user_id": actor(),
        },
        versioned=False,
    )

    # step 2 - the policy takes the new cash value
    policy["cash_surrender_value_usd"] = figures["cash_value_usd"]
    touch(policy)

    # step 3 - carrier totals, concentration and the hysteresis
    rerate_carrier(carrier)

    # step 4 - the product's latest mortality-and-expense figures
    latest = latest_product_valuation(product["id"]) or valuation
    product["latest_me_charge_bps"] = latest["me_charge_bps"]
    product["latest_me_drift_bps"] = latest["me_drift_bps"]
    if latest["me_drift_bps"] > calc.ME_DRIFT_TOLERANCE_BPS and product["status"] == "OPEN":
        product["status"] = "ON_WATCH"

    # step 5 - the low-yield streak
    if figures["net_yield_bps"] < calc.MIN_ACCEPTABLE_NET_YIELD_BPS:
        product["consecutive_low_yield_count"] = int(product["consecutive_low_yield_count"]) + 1
    else:
        product["consecutive_low_yield_count"] = 0

    # step 6 / 7 - closure, the carrier watch list and the reopened files
    closed = False
    if int(product["consecutive_low_yield_count"]) >= calc.CONSECUTIVE_LOW_YIELD_LIMIT:
        if product["status"] in ("OPEN", "ON_WATCH"):
            product["status"] = "CLOSED_TO_NEW"
            closed = True
    touch(product)
    if closed:
        flag_watch_list(carrier)

    return resource_response(valuation, 201)


@bp.get("/policy-valuations")
def list_valuations():
    authorize(VALUATION_ROLES)
    limit, offset = pagination()
    policy_id = query_str("policy_id")
    if policy_id is not None and is_liaison():
        policy = db.policies.get(policy_id)
        if policy is not None:
            scope_check(policy["carrier_id"])
    rows = []
    for valuation in db.policy_valuations.values():
        if policy_id is not None and valuation["policy_id"] != policy_id:
            continue
        if is_liaison():
            policy = db.policies.get(valuation["policy_id"])
            if policy is None or policy["carrier_id"] != liaison_carrier_id():
                continue
        rows.append(valuation)
    return collection_response(rows, limit, offset)


@bp.get("/policy-valuations/<valuation_id>")
def read_valuation(valuation_id):
    authorize(VALUATION_ROLES)
    valuation = find_valuation(valuation_id)
    policy = db.policies.get(valuation["policy_id"])
    if policy is not None:
        scope_check(policy["carrier_id"])
    return resource_response(valuation)
