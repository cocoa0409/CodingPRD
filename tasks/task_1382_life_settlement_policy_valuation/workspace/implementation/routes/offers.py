"""Provider offers and the negotiation loop (PRD §3.3)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
from cascade import CASE_TERMINAL, OFFER_TERMINAL, acceptance_cascade
from db import stamp, store, touch
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_CASE_NOT_MARKETED,
    ERR_CASE_ON_COMPLIANCE_HOLD,
    ERR_COMMISSION_CAP_EXCEEDED,
    ERR_COUNTER_INCREMENT_TOO_SMALL,
    ERR_DISCLOSURES_INCOMPLETE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MAX_NEGOTIATION_ROUNDS_REACHED,
    ERR_NOT_CASE_OWNER,
    ERR_STALE_VERSION,
)
from middleware import (
    READ_ALL,
    auth,
    get_body,
    lookup,
    opt,
    page_args,
    req,
    require_role,
    v_enum,
    v_int,
)
from response import ok, ok_list
from serialize import ser_offer

bp = Blueprint("offers", __name__)


def _sorted(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def _offer_not_terminal(offer):
    if offer["status"] in OFFER_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Offer is in terminal state %s" % offer["status"])


def _case_marketed(case):
    if case["status"] != "MARKETED":
        raise ApiError(ERR_CASE_NOT_MARKETED, 409, "Case is not MARKETED")


def _own_case(uid, case):
    if case["broker_id"] != uid:
        raise ApiError(ERR_NOT_CASE_OWNER, 403, "Caller broker does not own the case")


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------


@bp.post("/api/cases/<cid>/offers")
def create_offer(cid):
    uid, role = auth()
    require_role(role, ["Underwriter"])
    body = get_body()
    amount = v_int(req(body, "amount_cents"), "amount_cents", min_v=1)
    expires_in = v_int(
        opt(body, "expires_in_days", calc.OFFER_EXPIRES_DEFAULT_DAYS),
        "expires_in_days",
        min_v=1,
        max_v=calc.OFFER_EXPIRES_MAX_DAYS,
    )
    case = lookup(store.cases, cid, "PolicyCase")
    if case["status"] in CASE_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Case is in terminal state %s" % case["status"])
    _case_marketed(case)
    offer = {
        "case_id": cid,
        "amount_cents": amount,
        "counter_amount_cents": None,
        "round_number": 1,
        "expires_at": store.clock + timedelta(days=expires_in),
        "effective_price_cents": None,
        "status": "PENDING",
    }
    stamp(offer)
    store.offers[offer["id"]] = offer
    return ok(ser_offer(offer), 201)


@bp.get("/api/cases/<cid>/offers")
def list_offers(cid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.cases, cid, "PolicyCase")
    items = [o for o in store.offers.values() if o["case_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    limit, offset = page_args()
    items = _sorted(items)
    page = items[offset : offset + limit]
    return ok_list([ser_offer(o) for o in page], len(items), limit, offset)


@bp.get("/api/offers/<oid>")
def get_offer(oid):
    uid, role = auth()
    require_role(role, READ_ALL)
    return ok(ser_offer(lookup(store.offers, oid, "Offer")))


@bp.post("/api/offers/<oid>/counter")
def counter_offer(oid):
    uid, role = auth()
    require_role(role, ["Broker"])
    body = get_body()
    counter = v_int(req(body, "counter_amount_cents"), "counter_amount_cents", min_v=1)
    expected_version = v_int(req(body, "expected_offer_version"), "expected_offer_version")
    offer = lookup(store.offers, oid, "Offer")
    case = store.cases[offer["case_id"]]
    _own_case(uid, case)
    _offer_not_terminal(offer)
    _case_marketed(case)
    if offer["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Only a PENDING offer can be countered")
    if offer["round_number"] >= calc.MAX_NEGOTIATION_ROUND:
        raise ApiError(ERR_MAX_NEGOTIATION_ROUNDS_REACHED, 409, "Negotiation round ceiling reached")
    minimum = calc.rhu_div(offer["amount_cents"] * 101, 100)
    if counter < minimum:
        raise ApiError(
            ERR_COUNTER_INCREMENT_TOO_SMALL,
            422,
            "Counter must be at least the one-percent minimum increment",
        )
    if expected_version != offer["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Offer version has advanced")
    offer["counter_amount_cents"] = counter
    offer["round_number"] += 1
    offer["status"] = "COUNTERED"
    touch(offer)
    return ok(ser_offer(offer))


@bp.post("/api/offers/<oid>/respond")
def respond_offer(oid):
    uid, role = auth()
    require_role(role, ["Underwriter"])
    body = get_body()
    action = v_enum(req(body, "action"), "action", ["RE_OFFER", "ACCEPT_COUNTER", "REJECT"])
    amount = None
    if action == "RE_OFFER":
        amount = v_int(req(body, "amount_cents"), "amount_cents", min_v=1)
    commission_bps = None
    if "broker_commission_bps" in body and body["broker_commission_bps"] is not None:
        commission_bps = v_int(body["broker_commission_bps"], "broker_commission_bps", min_v=0)
    offer = lookup(store.offers, oid, "Offer")
    _offer_not_terminal(offer)
    case = store.cases[offer["case_id"]]
    _case_marketed(case)
    if offer["status"] != "COUNTERED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Only a COUNTERED offer can be responded to")
    if action == "RE_OFFER":
        if amount <= offer["amount_cents"] or amount > offer["counter_amount_cents"]:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "Re-offer amount must exceed the previous amount and not exceed the counter",
            )
        if offer["round_number"] >= calc.MAX_NEGOTIATION_ROUND:
            raise ApiError(ERR_MAX_NEGOTIATION_ROUNDS_REACHED, 409, "Negotiation round ceiling reached")
        offer["amount_cents"] = amount
        offer["counter_amount_cents"] = None
        offer["round_number"] += 1
        offer["status"] = "PENDING"
        touch(offer)
        return ok(ser_offer(offer))
    if action == "REJECT":
        offer["status"] = "REJECTED"
        touch(offer)
        return ok(ser_offer(offer))
    # ACCEPT_COUNTER
    if not case["disclosures_delivered"]:
        raise ApiError(ERR_DISCLOSURES_INCOMPLETE, 422, "Disclosures have not been delivered")
    if case["hold_status"] != "CLEAR":
        raise ApiError(ERR_CASE_ON_COMPLIANCE_HOLD, 409, "Case is on compliance hold")
    acceptance_cascade(
        offer,
        case,
        offer["counter_amount_cents"],
        commission_bps if commission_bps is not None else 0,
    )
    return ok(ser_offer(offer))


@bp.post("/api/offers/<oid>/accept")
def accept_offer_endpoint(oid):
    uid, role = auth()
    require_role(role, ["Broker"])
    body = get_body()
    commission_bps = v_int(req(body, "broker_commission_bps"), "broker_commission_bps", min_v=0)
    offer = lookup(store.offers, oid, "Offer")
    case = store.cases[offer["case_id"]]
    _own_case(uid, case)
    _offer_not_terminal(offer)
    _case_marketed(case)
    if offer["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Only a PENDING offer can be accepted")
    if not case["disclosures_delivered"]:
        raise ApiError(ERR_DISCLOSURES_INCOMPLETE, 422, "Disclosures have not been delivered")
    if case["hold_status"] != "CLEAR":
        raise ApiError(ERR_CASE_ON_COMPLIANCE_HOLD, 409, "Case is on compliance hold")
    if commission_bps > calc.COMMISSION_ACCEPT_CAP_BPS:
        raise ApiError(ERR_COMMISSION_CAP_EXCEEDED, 422, "Broker commission exceeds the 600 bps cap")
    acceptance_cascade(offer, case, offer["amount_cents"], commission_bps)
    return ok(ser_offer(offer))


@bp.post("/api/offers/<oid>/reject")
def reject_offer(oid):
    uid, role = auth()
    require_role(role, ["Broker"])
    offer = lookup(store.offers, oid, "Offer")
    case = store.cases[offer["case_id"]]
    _own_case(uid, case)
    _offer_not_terminal(offer)
    if offer["status"] not in ("PENDING", "COUNTERED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Offer cannot be rejected from %s" % offer["status"])
    offer["status"] = "REJECTED"
    touch(offer)
    return ok(ser_offer(offer))


@bp.post("/api/offers/<oid>/withdraw")
def withdraw_offer(oid):
    uid, role = auth()
    require_role(role, ["Underwriter"])
    offer = lookup(store.offers, oid, "Offer")
    _offer_not_terminal(offer)
    if offer["status"] not in ("PENDING", "COUNTERED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Offer cannot be withdrawn from %s" % offer["status"])
    offer["status"] = "WITHDRAWN"
    touch(offer)
    return ok(ser_offer(offer))
