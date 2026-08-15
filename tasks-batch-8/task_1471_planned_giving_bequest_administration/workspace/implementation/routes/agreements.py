"""Gift agreements: create/list/read, amend (OCC), execute (gate chain),
SUSPEND/RESUME/WITHDRAW/RESCIND, terminate, settle, schedule (PRD 3.3, 3.6)."""
from flask import Blueprint, g

import store
from calc import FREQ_DIVISOR, oldest_age, reserve_requirement
from domain import (
    FREQUENCIES,
    RESTRICTIONS,
    VEHICLES,
    active_table_covering,
    agreement_assets,
    agreement_view,
    compute_reserve_derived,
    lookup,
    matches,
    paginate,
    received_value_cents,
    sort_created,
    table_window,
    update_reserve,
)
from envelope import success
from errors import ApiError
from giftcalc import (
    check_exhaustion_test,
    check_remainder_test,
    check_vehicle_fields,
    economics,
)
from security import ALL_ROLES, require_roles
from store import base_fields, iso, now, touch
from validate import funding_month_start, get_body, validate_body
from datetime import datetime, timezone

bp = Blueprint("agreements", __name__)

TRANSITION_ACTIONS = ("SUSPEND", "RESUME", "WITHDRAW", "RESCIND")


def _pin_rate_table(funding_month):
    table = active_table_covering(funding_month_start(funding_month))
    if table is None:
        raise ApiError(
            "ERR_RATE_TABLE_NOT_ACTIVE",
            409,
            "No ACTIVE rate table covers funding_month",
        )
    return table


@bp.post("/giving/gift-agreements")
@require_roles("GiftOfficer")
def create_agreement():
    body = get_body()
    validate_body(
        body,
        {
            "donor_id": ("str", True, None),
            "vehicle_type": ("str", True, VEHICLES),
            "gift_amount_cents": ("int", True, None),
            "payout_rate_bps": ("int", False, None),
            "payment_frequency": ("str", False, FREQUENCIES),
            "lives": ("int", False, None),
            "annuitant_1_age": ("int", False, None),
            "annuitant_2_age": ("int", False, None),
            "funding_month": ("funding_month", True, None),
            "restriction_type": ("str", False, RESTRICTIONS),
            "restriction_text": ("str", False, None),
            "fund_id": ("str", False, None),
        },
    )
    donor = lookup(store.donors, body["donor_id"], "Donor")
    if body.get("fund_id") is not None:
        lookup(store.funds, body["fund_id"], "Fund")
    if donor["vital_status"] != "LIVING":
        raise ApiError(
            "ERR_DONOR_STATE_MISMATCH", 409, "Donor must be LIVING"
        )

    lives = body.get("lives", 1)
    if lives not in (1, 2):
        raise ApiError("ERR_INVALID_REQUEST", 400, "lives must be 1 or 2")
    check_vehicle_fields(
        body["vehicle_type"],
        {
            "payout_rate_bps": body.get("payout_rate_bps"),
            "lives": lives,
            "annuitant_1_age": body.get("annuitant_1_age"),
            "annuitant_2_age": body.get("annuitant_2_age"),
        },
    )
    table = _pin_rate_table(body["funding_month"])

    agreement = base_fields()
    agreement.update(
        {
            "donor_id": donor["id"],
            "illustration_id": None,
            "vehicle_type": body["vehicle_type"],
            "gift_amount_cents": body["gift_amount_cents"],
            "payout_rate_bps": body.get("payout_rate_bps"),
            "payment_frequency": body.get("payment_frequency", "QUARTERLY"),
            "lives": lives,
            "annuitant_1_age": body.get("annuitant_1_age"),
            "annuitant_2_age": body.get("annuitant_2_age"),
            "funding_month": body["funding_month"],
            "rate_table_id": table["id"],
            "status": "DRAFT",
            "executed_at": None,
            "executed_by_user_id": None,
            "annual_annuity_cents": None,
            "booked_deduction_cents": None,
            "corpus_value_cents": None,
            "actuarial_liability_cents": None,
            "remainder_value_cents": None,
            "reserve_requirement_cents": 0,
            "surrender_value_cents": None,
            "fund_id": body.get("fund_id"),
            "restriction_type": body.get("restriction_type", "UNRESTRICTED"),
            "restriction_text": body.get("restriction_text"),
        }
    )
    store.agreements[agreement["id"]] = agreement
    return success(agreement_view(agreement), 201)


@bp.get("/giving/gift-agreements")
@require_roles(*ALL_ROLES)
def list_agreements():
    items = [
        a
        for a in sort_created(store.agreements.values())
        if matches(
            a,
            {
                "donor_id": None,
                "fund_id": None,
                "illustration_id": None,
                "rate_table_id": None,
                "status": None,
                "vehicle_type": None,
            },
        )
    ]
    page, meta = paginate(items)
    return success([agreement_view(a) for a in page], 200, meta)


@bp.get("/giving/gift-agreements/<agreement_id>")
@require_roles(*ALL_ROLES)
def get_agreement(agreement_id):
    return success(
        agreement_view(lookup(store.agreements, agreement_id, "GiftAgreement")), 200
    )


@bp.post("/giving/gift-agreements/<agreement_id>/amend")
@require_roles("GiftAdministrator")
def amend_agreement(agreement_id):
    agreement = lookup(store.agreements, agreement_id, "GiftAgreement")
    body = get_body()
    validate_body(
        body,
        {
            "expected_gift_agreement_version": ("int", True, None),
            "gift_amount_cents": ("int", False, None),
            "payout_rate_bps": ("int", False, None),
            "payment_frequency": ("str", False, FREQUENCIES),
            "restriction_type": ("str", False, RESTRICTIONS),
            "restriction_text": ("str", False, None),
            "fund_id": ("str", False, None),
        },
    )
    if body.get("fund_id") is not None:
        lookup(store.funds, body["fund_id"], "Fund")
    # OCC guard (§2.9)
    if body["expected_gift_agreement_version"] != agreement["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale gift agreement version")
    if agreement["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a DRAFT agreement may be amended"
        )
    # vehicle/field consistency + payout bounds on supplied fields
    if agreement["vehicle_type"] == "BEQUEST" and body.get("payout_rate_bps") is not None:
        raise ApiError(
            "ERR_BEQUEST_VEHICLE_MISMATCH",
            422,
            "BEQUEST must not carry payout_rate_bps",
        )
    payout = body.get("payout_rate_bps")
    if (
        agreement["vehicle_type"] != "BEQUEST"
        and payout is not None
        and not (500 <= payout <= 5000)
    ):
        raise ApiError(
            "ERR_PAYOUT_RATE_OUT_OF_RANGE",
            422,
            "payout_rate_bps must be within [500, 5000]",
        )

    for field in (
        "gift_amount_cents",
        "payout_rate_bps",
        "payment_frequency",
        "restriction_type",
        "restriction_text",
    ):
        if field in body and body[field] is not None:
            agreement[field] = body[field]
    if "fund_id" in body:
        agreement["fund_id"] = body["fund_id"]  # explicit null detaches
    # economic recomputation is deferred to EXECUTE (PRD 3.3)
    touch(agreement)
    return success(agreement_view(agreement), 200)


@bp.post("/giving/gift-agreements/<agreement_id>/execute")
@require_roles("GiftAdministrator")
def execute_agreement(agreement_id):
    agreement = lookup(store.agreements, agreement_id, "GiftAgreement")
    validate_body(get_body(), {})  # no input fields

    # SoD (priority 3): executor differs from the source illustration's creator
    if agreement.get("illustration_id"):
        illustration = store.illustrations.get(agreement["illustration_id"])
        if illustration and illustration["created_by_user_id"] == g.user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                403,
                "Executor must differ from the illustration creator",
            )
    # state (6)
    if agreement["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only a DRAFT agreement may be executed",
        )
    # donor vital (7)
    donor = store.donors.get(agreement["donor_id"])
    if donor is None or donor["vital_status"] != "LIVING":
        raise ApiError("ERR_DONOR_STATE_MISMATCH", 409, "Donor must be LIVING")

    # booked economics under the pinned rate table
    table = store.rate_tables.get(agreement["rate_table_id"])
    rate_bps = table["discount_rate_bps"] if table else 0
    annual, pv, deduction = economics(
        agreement["vehicle_type"],
        agreement["gift_amount_cents"],
        agreement.get("payout_rate_bps"),
        agreement.get("lives", 1),
        agreement.get("annuitant_1_age"),
        agreement.get("annuitant_2_age"),
        rate_bps,
    )
    # remainder test (8) then exhaustion test (9) — PRD 2.10 pinned order
    check_remainder_test(agreement["vehicle_type"], agreement["gift_amount_cents"], deduction)
    check_exhaustion_test(agreement["vehicle_type"], agreement["gift_amount_cents"], pv)
    # documentation gate (10)
    verified_primary = any(
        d["gift_agreement_id"] == agreement["id"]
        and d["slot"] == "PRIMARY_1"
        and d["status"] == "VERIFIED"
        for d in store.designations.values()
    )
    if not verified_primary:
        raise ApiError(
            "ERR_DESIGNATION_NOT_VERIFIED",
            409,
            "A VERIFIED PRIMARY_1 beneficiary designation is required",
        )
    # vehicle/field consistency (12)
    if agreement["vehicle_type"] == "BEQUEST" and agreement.get("payout_rate_bps") is not None:
        raise ApiError(
            "ERR_BEQUEST_VEHICLE_MISMATCH",
            422,
            "BEQUEST must not carry payout_rate_bps",
        )
    # pinned rate table still ACTIVE and covering funding_month (18)
    fm_start = funding_month_start(agreement["funding_month"])
    if table is None or table["status"] != "ACTIVE":
        raise ApiError(
            "ERR_RATE_TABLE_NOT_ACTIVE", 409, "Pinned rate table is not ACTIVE"
        )
    w_start, w_end = table_window(table)
    if not (w_start <= fm_start and (w_end is None or fm_start < w_end)):
        raise ApiError(
            "ERR_RATE_TABLE_NOT_ACTIVE",
            409,
            "Pinned rate table window no longer covers funding_month",
        )
    # CGA reserve gate (25): balance >= booked + other EXECUTED CGA + candidate
    rr = 0
    if agreement["vehicle_type"] == "CGA":
        rr = reserve_requirement(
            annual,
            agreement.get("annuitant_1_age"),
            agreement.get("annuitant_2_age"),
            agreement.get("lives", 1),
        )
        booked = compute_reserve_derived()[0]
        other_executed = sum(
            a.get("reserve_requirement_cents") or 0
            for a in store.agreements.values()
            if a["vehicle_type"] == "CGA"
            and a["status"] == "EXECUTED"
            and a["id"] != agreement["id"]
        )
        if store.reserve_fund["balance_cents"] < booked + other_executed + rr:
            raise ApiError(
                "ERR_RESERVE_DEFICIENT",
                409,
                "Reserve balance cannot cover the projected requirement",
            )

    # commit the execution
    agreement["annual_annuity_cents"] = annual
    agreement["booked_deduction_cents"] = deduction
    agreement["actuarial_liability_cents"] = pv
    agreement["corpus_value_cents"] = agreement["gift_amount_cents"]
    # remainder: bequest value arrives via the estate residual, so a BEQUEST
    # carries a zero agreement-level remainder (PRD 3.3)
    if agreement["vehicle_type"] == "BEQUEST":
        agreement["remainder_value_cents"] = 0
    else:
        agreement["remainder_value_cents"] = max(
            0, agreement["corpus_value_cents"] - pv
        )
    agreement["reserve_requirement_cents"] = rr
    agreement["executed_at"] = iso(now())
    agreement["executed_by_user_id"] = g.user_id
    agreement["status"] = "EXECUTED"
    touch(agreement)
    update_reserve()  # EXECUTED CGA joins the projected set
    return success(agreement_view(agreement), 200)


@bp.post("/giving/gift-agreements/<agreement_id>/transition")
@require_roles("GiftAdministrator", "ComplianceOfficer")
def agreement_transition(agreement_id):
    body = get_body()
    validate_body(body, {"action": ("str", True, TRANSITION_ACTIONS)})
    action = body["action"]
    # per-action role restriction (PRD 2.1): SUSPEND/RESUME are ComplianceOfficer,
    # WITHDRAW/RESCIND are GiftAdministrator
    required = (
        "ComplianceOfficer" if action in ("SUSPEND", "RESUME") else "GiftAdministrator"
    )
    if g.role != required:
        raise ApiError(
            "ERR_UNAUTHORIZED", 403, "Action %s requires %s" % (action, required)
        )
    agreement = lookup(store.agreements, agreement_id, "GiftAgreement")
    status = agreement["status"]

    if action == "SUSPEND":
        if status != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot SUSPEND from %s" % status)
        agreement["status"] = "SUSPENDED"
    elif action == "RESUME":
        if status != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot RESUME from %s" % status)
        agreement["status"] = "ACTIVE"
    elif action == "WITHDRAW":
        if status != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot WITHDRAW from %s" % status)
        agreement["status"] = "WITHDRAWN"
    else:  # RESCIND
        if status != "EXECUTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot RESCIND from %s" % status)
        received = any(
            x["status"] in ("RECEIVED", "APPRAISED", "LIQUIDATED", "DISTRIBUTED")
            for x in agreement_assets(agreement["id"])
        )
        if received:
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Cannot rescind once assets have been received",
            )
        agreement["status"] = "RESCINDED"

    touch(agreement)
    update_reserve()  # CGA may leave the projected set (RESCIND)
    return success(agreement_view(agreement), 200)


@bp.post("/giving/gift-agreements/<agreement_id>/terminate")
@require_roles("GiftAdministrator")
def terminate_agreement(agreement_id):
    agreement = lookup(store.agreements, agreement_id, "GiftAgreement")
    validate_body(get_body(), {})  # no input fields
    if agreement["status"] not in ("EXECUTED", "FUNDED", "ACTIVE", "SUSPENDED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Cannot TERMINATE from %s" % agreement["status"],
        )

    paid = sum(
        p["amount_cents"]
        for p in store.payments.values()
        if p["gift_agreement_id"] == agreement["id"] and p["status"] == "PAID"
    )
    surrender = max(0, received_value_cents(agreement["id"]) - paid)

    new_balance = None
    if agreement["vehicle_type"] == "CGA":
        # no floor at zero: insufficient balance rejects the termination
        if surrender > store.reserve_fund["balance_cents"]:
            raise ApiError(
                "ERR_INSUFFICIENT_RESERVE_BALANCE",
                422,
                "Surrender value exceeds the reserve balance",
            )
        new_balance = store.reserve_fund["balance_cents"] - surrender

    agreement["surrender_value_cents"] = surrender
    agreement["status"] = "TERMINATED"
    touch(agreement)
    for p in store.payments.values():
        if p["gift_agreement_id"] == agreement["id"] and p["status"] in (
            "SCHEDULED",
            "DUE",
            "DEFERRED",
        ):
            p["status"] = "LAPSED"
            p["lapse_reason"] = "TERMINATION"
            touch(p)
    update_reserve(new_balance=new_balance)
    return success(agreement_view(agreement), 200)


@bp.post("/giving/gift-agreements/<agreement_id>/settle")
@require_roles("FinanceSteward")
def settle_agreement(agreement_id):
    agreement = lookup(store.agreements, agreement_id, "GiftAgreement")
    validate_body(get_body(), {})  # no input fields
    if agreement["status"] != "MATURED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only a MATURED agreement may be settled",
        )
    fund = store.funds.get(agreement.get("fund_id") or "")
    if fund is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Agreement has no existing fund_id")
    if fund["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Fund is CLOSED")

    # remainder credit (0 for BEQUEST); inclusive endowment boundary
    fund["balance_cents"] += agreement.get("remainder_value_cents") or 0
    if (
        fund["status"] == "PROPOSED"
        and fund["balance_cents"] >= fund["minimum_endowment_cents"]
    ):
        fund["status"] = "ENDOWED"
    touch(fund)

    agreement["status"] = "SETTLED"
    touch(agreement)
    return success(agreement_view(agreement), 200)


def _add_months(year, month, months):
    total = year * 12 + (month - 1) + months
    return total // 12, total % 12 + 1


@bp.post("/giving/gift-agreements/<agreement_id>/generate-payment-schedule")
@require_roles("GiftAdministrator")
def generate_payment_schedule(agreement_id):
    agreement = lookup(store.agreements, agreement_id, "GiftAgreement")
    validate_body(get_body(), {})  # no input fields
    if agreement["status"] != "FUNDED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only a FUNDED agreement can generate a schedule",
        )
    if agreement["vehicle_type"] == "BEQUEST":
        raise ApiError(
            "ERR_BEQUEST_VEHICLE_MISMATCH",
            422,
            "BEQUEST agreements carry no payment schedule",
        )

    divisor = FREQ_DIVISOR[agreement.get("payment_frequency", "QUARTERLY")]
    oldest = oldest_age(
        agreement.get("annuitant_1_age"),
        agreement.get("annuitant_2_age"),
        agreement.get("lives", 1),
    )
    n_payments = divisor * max(1, 100 - oldest)
    months_per_period = 12 // divisor
    fy, fm = int(agreement["funding_month"][:4]), int(agreement["funding_month"][5:7])

    # per-payment amount independently rounded; NO cumulative true-up (PRD 2.6)
    from calc import div_rhu

    amount = div_rhu(agreement["annual_annuity_cents"], divisor)
    created = []
    for i in range(1, n_payments + 1):
        y, m = _add_months(fy, fm, i * months_per_period)
        due = datetime(y, m, 1, tzinfo=timezone.utc)
        payment = base_fields()
        payment.update(
            {
                "gift_agreement_id": agreement["id"],
                "period_index": i,
                "due_date": iso(due),
                "amount_cents": amount,
                "status": "SCHEDULED",
                "paid_at": None,
                "defer_until": None,
                "lapse_reason": None,
            }
        )
        store.payments[payment["id"]] = payment
        created.append(payment)

    agreement["status"] = "ACTIVE"
    touch(agreement)
    update_reserve()  # CGA requirement is already in the booked set; keep current
    from domain import view

    return success([view(p) for p in created], 201)
