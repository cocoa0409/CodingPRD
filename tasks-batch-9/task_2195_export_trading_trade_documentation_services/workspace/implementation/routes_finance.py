"""Credit insurance policies, claims, disputes and the settlement waterfall."""
from decimal import Decimal

import calc
import ledgers
import valid
from authz import apply_page, authenticate, buyer_scope, pagination
from core import ApiError, dq, ok, ok_list
from db import insert, ordered, require, serialize, serialize_all, store, touch

from flask import Blueprint, request

bp = Blueprint("finance", __name__)

D = Decimal
POLICY_READ = ("FinanceCollectionsOfficer", "ExportOpsCoordinator", "PlatformAdmin")
DISPUTE_READ = ("ForeignBuyer", "FinanceCollectionsOfficer", "ExportOpsCoordinator",
                "PlatformAdmin")
DISPUTE_TYPES = ("SHORT_SHIPMENT", "QUALITY", "NON_PAYMENT")
BUYER_TYPES = ("SHORT_SHIPMENT", "QUALITY")
ACCEPT_ACTOR = {"OFFERED": "ForeignBuyer", "COUNTERED": "FinanceCollectionsOfficer",
                "ESCALATED": "PlatformAdmin"}


def dispute_state_invalid(message="the dispute state does not permit this"):
    raise ApiError("ERR_DISPUTE_STATE_INVALID", 409, message)


def role_not_permitted(message="this role may not perform the operation"):
    raise ApiError("ERR_ROLE_NOT_PERMITTED", 403, message)


def offer_amount_invalid(message="the amount is outside the permitted band"):
    raise ApiError("ERR_OFFER_AMOUNT_INVALID", 422, message)


@bp.post("/credit-insurance-policies")
def write_policy():
    authenticate(("FinanceCollectionsOfficer",))
    body = valid.body()
    buyer = valid.fk(body, "buyer_id", store.buyers, "ERR_BUYER_NOT_FOUND")
    number = valid.string(body, "policy_number", max_len=100)
    credit_limit = valid.decimal(body, "credit_limit_usd", 2, minimum=0,
                                 exclusive_min=True)
    insured_pct = valid.decimal(body, "insured_pct", 2, minimum=50, maximum=95)
    deductible = valid.decimal(body, "deductible_usd", 2, minimum=0)
    from_raw, from_dt = valid.instant(body, "effective_from")
    to_raw, to_dt = valid.instant(body, "effective_to")

    if to_dt <= from_dt:
        valid.inconsistent("effective_to must be strictly after effective_from")
    if any(p["policy_number"] == number for p in store.policies.values()):
        raise ApiError("ERR_DUPLICATE_POLICY_NUMBER", 409,
                       "policy_number already exists")

    prior = ledgers.recompute_buyer_exposure(buyer, bump=False)
    tier, premium = calc.price_premium(buyer, credit_limit, insured_pct, deductible,
                                      prior)
    row = insert(store.policies, {
        "buyer_id": buyer["id"],
        "policy_number": number,
        "credit_limit_usd": dq(credit_limit, 2),
        "insured_pct": dq(insured_pct, 2),
        "deductible_usd": dq(deductible, 2),
        "effective_from": from_raw,
        "effective_to": to_raw,
        "exposure_tier": tier,
        "premium_usd": premium,
        "utilized_usd": D("0.00"),
        "available_limit_usd": dq(credit_limit, 2),
        "indemnified_total_usd": D("0.00"),
        "status": "ACTIVE",
        "_from_dt": from_dt,
        "_to_dt": to_dt,
    })
    ledgers.recompute_buyer_exposure(buyer, bump=False)
    touch(buyer)
    return ok(serialize(row), 201)


@bp.get("/credit-insurance-policies")
def list_policies():
    authenticate(POLICY_READ)
    limit, offset = pagination()
    rows = ordered(store.policies)
    for field in ("buyer_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    page, total = apply_page(rows, limit, offset)
    return ok_list(serialize_all(page), limit, offset, total)


@bp.get("/credit-insurance-policies/<policy_id>")
def read_policy(policy_id):
    authenticate(POLICY_READ)
    row = require(store.policies, policy_id, "ERR_POLICY_NOT_FOUND")
    return ok(serialize(row))


@bp.post("/credit-insurance-policies/<policy_id>/claims")
def file_claim(policy_id):
    authenticate(("FinanceCollectionsOfficer",))
    policy = require(store.policies, policy_id, "ERR_POLICY_NOT_FOUND")
    body = valid.body()
    dispute = valid.fk(body, "dispute_case_id", store.disputes, "ERR_DISPUTE_NOT_FOUND")
    expected = valid.integer(body, "expected_credit_insurance_policy_version",
                             minimum=0)
    order = store.orders[dispute["export_order_id"]]

    ledgers.require_settlement(order, ("DISHONORED",))
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", 409, "the policy is not ACTIVE")
    if expected != policy["version"]:
        raise ApiError("ERR_STALE_POLICY_VERSION", 412,
                       "expected_credit_insurance_policy_version is stale")
    if order["insured_exposure_usd"] <= 0:
        ledgers.order_state_invalid()
    if dispute["dispute_type"] != "NON_PAYMENT" \
            or dispute["status"] not in ledgers.LIVE_DISPUTES:
        dispute_state_invalid("a live NON_PAYMENT dispute is required")
    net = dq(order["insured_exposure_usd"] - policy["deductible_usd"], 2)
    if net < 0:
        net = D("0.00")
    implied = dq(net * policy["insured_pct"] / D(100), 2)
    if implied > dq(policy["credit_limit_usd"] - policy["indemnified_total_usd"], 2):
        raise ApiError("ERR_CLAIM_EXCEEDS_COVERAGE", 409,
                       "the implied indemnity exceeds the remaining coverage")

    dispute["credit_insurance_policy_id"] = policy["id"]
    touch(dispute)
    order["settlement_status"] = "CLAIM_FILED"
    touch(order)
    touch(policy)
    return ok(serialize(dispute))


@bp.post("/dispute-cases")
def open_dispute():
    caller = authenticate(("ForeignBuyer", "FinanceCollectionsOfficer"))
    body = valid.body()
    order = valid.fk(body, "export_order_id", store.orders, "ERR_ORDER_NOT_FOUND")
    if caller.is_buyer:
        buyer_scope(caller, order)
    dispute_type = valid.enum(body, "dispute_type", DISPUTE_TYPES)
    claimed = valid.decimal(body, "claimed_amount_usd", 2, minimum=0,
                            exclusive_min=True)

    if caller.is_buyer and dispute_type not in BUYER_TYPES:
        role_not_permitted("a buyer may not open a %s case" % dispute_type)
    if not caller.is_buyer and dispute_type in BUYER_TYPES:
        role_not_permitted("collections may only open a NON_PAYMENT case")
    if claimed > order["ordered_goods_value_usd"]:
        raise ApiError("ERR_CLAIM_AMOUNT_INVALID", 422,
                       "claimed_amount_usd exceeds the ordered goods value")
    if dispute_type == "SHORT_SHIPMENT" and claimed > order["short_shipped_value_usd"]:
        raise ApiError("ERR_CLAIM_AMOUNT_INVALID", 422,
                       "claimed_amount_usd exceeds the short-shipped value")

    row = insert(store.disputes, {
        "export_order_id": order["id"],
        "credit_insurance_policy_id": None,
        "dispute_type": dispute_type,
        "opened_by_role": caller.role,
        "claimed_amount_usd": dq(claimed, 2),
        "current_offer_usd": None,
        "settlement_amount_usd": None,
        "negotiation_round": 0,
        "receivable_offset_usd": D("0.00"),
        "insurance_indemnity_usd": D("0.00"),
        "seller_credit_note_usd": D("0.00"),
        "status": "OPEN",
    })
    return ok(serialize(row), 201)


@bp.get("/dispute-cases")
def list_disputes():
    caller = authenticate(DISPUTE_READ)
    limit, offset = pagination()
    rows = ordered(store.disputes)
    if caller.is_buyer:
        rows = [r for r in rows
                if store.orders[r["export_order_id"]]["buyer_id"] == caller.user_id]
    for field in ("export_order_id", "credit_insurance_policy_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    page, total = apply_page(rows, limit, offset)
    return ok_list(serialize_all(page), limit, offset, total)


@bp.get("/dispute-cases/<dispute_id>")
def read_dispute(dispute_id):
    authenticate(DISPUTE_READ)
    row = require(store.disputes, dispute_id, "ERR_DISPUTE_NOT_FOUND")
    return ok(serialize(row))


@bp.post("/dispute-cases/<dispute_id>/offers")
def make_offer(dispute_id):
    authenticate(("FinanceCollectionsOfficer",))
    dispute = require(store.disputes, dispute_id, "ERR_DISPUTE_NOT_FOUND")
    body = valid.body()
    amount = valid.decimal(body, "offer_amount_usd", 2, minimum=0)
    order = store.orders[dispute["export_order_id"]]

    if dispute["status"] not in ("OPEN", "COUNTERED"):
        dispute_state_invalid("an offer may only be made from OPEN or COUNTERED")
    if dispute["status"] == "COUNTERED" \
            and dispute["negotiation_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED", 409,
                       "the negotiation round bound has been reached")
    if amount > dispute["claimed_amount_usd"]:
        offer_amount_invalid("the offer exceeds claimed_amount_usd")
    if dispute["status"] == "OPEN" and dispute["dispute_type"] == "SHORT_SHIPMENT" \
            and amount > order["short_shipped_value_usd"]:
        offer_amount_invalid("the offer exceeds the short-shipped value")
    if dispute["status"] == "COUNTERED" and dispute["current_offer_usd"] is not None \
            and amount > dispute["current_offer_usd"]:
        offer_amount_invalid("the offer may not rise above the standing offer")

    dispute["current_offer_usd"] = dq(amount, 2)
    dispute["status"] = "OFFERED"
    touch(dispute)
    return ok(serialize(dispute))


@bp.post("/dispute-cases/<dispute_id>/counter")
def counter_offer(dispute_id):
    caller = authenticate(("ForeignBuyer",))
    dispute = require(store.disputes, dispute_id, "ERR_DISPUTE_NOT_FOUND")
    order = store.orders[dispute["export_order_id"]]
    buyer_scope(caller, order)
    body = valid.body()
    amount = valid.decimal(body, "counter_amount_usd", 2, minimum=0)

    if dispute["status"] == "ESCALATED":
        dispute_state_invalid("ESCALATED is not a state a counter is declared from")
    if dispute["status"] == "COUNTERED" \
            and dispute["negotiation_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
        dispute["status"] = "ESCALATED"
        touch(dispute)
        return ok(serialize(dispute))
    if dispute["status"] != "OFFERED":
        dispute_state_invalid("a counter may only be made from OFFERED")
    if dispute["negotiation_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
        dispute["status"] = "ESCALATED"
        touch(dispute)
        return ok(serialize(dispute))

    standing = dispute["current_offer_usd"] or D("0.00")
    if amount <= standing:
        offer_amount_invalid("the counter must be strictly above the standing offer")
    if amount > dispute["claimed_amount_usd"]:
        offer_amount_invalid("the counter exceeds claimed_amount_usd")

    dispute["current_offer_usd"] = dq(amount, 2)
    dispute["negotiation_round"] = dispute["negotiation_round"] + 1
    dispute["status"] = "COUNTERED"
    touch(dispute)
    return ok(serialize(dispute))


@bp.post("/dispute-cases/<dispute_id>/accept")
def accept_offer(dispute_id):
    caller = authenticate(("ForeignBuyer", "FinanceCollectionsOfficer", "PlatformAdmin"))
    dispute = require(store.disputes, dispute_id, "ERR_DISPUTE_NOT_FOUND")
    order = store.orders[dispute["export_order_id"]]
    if caller.is_buyer:
        buyer_scope(caller, order)

    if dispute["status"] not in ACCEPT_ACTOR:
        dispute_state_invalid("the case carries no offer to accept")
    if caller.role != ACCEPT_ACTOR[dispute["status"]]:
        role_not_permitted("only a %s may accept from %s"
                           % (ACCEPT_ACTOR[dispute["status"]], dispute["status"]))
    if dispute["current_offer_usd"] is None:
        dispute_state_invalid("the case carries no offer to accept")

    settlement = dq(dispute["current_offer_usd"], 2)
    policy = store.policies.get(dispute["credit_insurance_policy_id"]) \
        if dispute["credit_insurance_policy_id"] else None
    bucket1, bucket2, bucket3 = calc.settlement_waterfall(settlement, order, policy)
    dispute["settlement_amount_usd"] = settlement
    dispute["receivable_offset_usd"] = bucket1
    dispute["insurance_indemnity_usd"] = bucket2
    dispute["seller_credit_note_usd"] = bucket3
    dispute["status"] = "SETTLED"
    touch(dispute)

    order["outstanding_receivable_usd"] = dq(
        order["outstanding_receivable_usd"] - bucket1, 2)
    if policy is not None:
        policy["indemnified_total_usd"] = dq(
            policy["indemnified_total_usd"] + bucket2, 2)
        if order["settlement_status"] == "CLAIM_FILED":
            order["settlement_status"] = "INDEMNIFIED"
            ledgers.release_exposure(order)
            ledgers.auto_close(order)
        else:
            ledgers.recompute_policy(policy, bump=False)
        touch(policy)
    else:
        ledgers.auto_close(order)
    touch(order)
    return ok(serialize(dispute))


@bp.post("/dispute-cases/<dispute_id>/close")
def close_dispute(dispute_id):
    authenticate(("PlatformAdmin",))
    dispute = require(store.disputes, dispute_id, "ERR_DISPUTE_NOT_FOUND")
    body = valid.body()
    valid.string(body, "reason", max_len=1000)

    if dispute["status"] != "ESCALATED":
        dispute_state_invalid("only an ESCALATED case may be closed without settlement")

    dispute["receivable_offset_usd"] = D("0.00")
    dispute["insurance_indemnity_usd"] = D("0.00")
    dispute["seller_credit_note_usd"] = D("0.00")
    dispute["status"] = "CLOSED_NO_SETTLEMENT"
    touch(dispute)
    order = store.orders.get(dispute["export_order_id"])
    if order is not None and ledgers.auto_close(order):
        touch(order)
    return ok(serialize(dispute))
