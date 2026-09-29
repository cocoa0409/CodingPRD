"""Cancellation orders and refund claims (PRD section 3.7)."""
from flask import Blueprint, request

from authz import (ALL_ROLES, FIDUCIARY, PLATFORM_COMPLIANCE, authenticate,
                   require_action_role, require_fiduciary_estate,
                   require_platform_scope, require_role)
from clock import CLOCK, parse_date
from db import DB, bump, sorted_records, stamp_new
from errors import ApiError
from response import public, single
from routes.common import paged
from services import lookup, refund
from services import authority
from services import estate as estate_svc
from validation import (parse_body, v_bool, v_date, v_enum, v_int, v_text,
                        validate)

bp = Blueprint("refunds", __name__)

ORDER_ACTIONS = ("REQUEST", "CONFIRM", "FAIL")
ORDER_ACTION_OWNERS = {
    "REQUEST": FIDUCIARY,
    "CONFIRM": PLATFORM_COMPLIANCE,
    "FAIL": PLATFORM_COMPLIANCE,
}

CLAIM_ACTIONS = ("START_REVIEW", "ESCALATE", "CREDIT", "DENY", "CHARGE_BACK")
CLAIM_ACTION_OWNERS = {
    "START_REVIEW": PLATFORM_COMPLIANCE,
    "ESCALATE": FIDUCIARY,
    "CREDIT": PLATFORM_COMPLIANCE,
    "DENY": PLATFORM_COMPLIANCE,
    "CHARGE_BACK": PLATFORM_COMPLIANCE,
}

LIVE_CLAIM_STATUSES = ("FILED", "PLATFORM_REVIEW", "ESCALATED", "CREDITED")
MAX_CENTS = 100000000


def _asset_term(asset_id):
    terms = sorted_records(lookup.asset_terms(asset_id))
    return terms[0] if terms else None


def _asset_claims(asset_id):
    out = []
    for claim in DB.claims.values():
        order = DB.orders.get(claim["cancellation_order_id"])
        if order is not None and order["asset_id"] == asset_id:
            out.append(claim)
    return sorted_records(out)


def _recompute_claimed_days_total(asset_id):
    term = _asset_term(asset_id)
    if term is None:
        return
    total = sum(c["claimed_days"] for c in _asset_claims(asset_id)
                if c["status"] in LIVE_CLAIM_STATUSES)
    if term["claimed_days_total"] != total:
        term["claimed_days_total"] = total
        bump(term)


# ------------------------------------------------------ CancellationOrder

@bp.route("/cancellation-orders/<order_id>", methods=["GET"])
def read_order(order_id):
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return single(public(lookup.get_order(order_id)), 200)


@bp.route("/cancellation-orders", methods=["GET"])
def list_orders():
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return paged(DB.orders.values(), request.args, {
        "asset_id": "asset_id",
        "status": "status",
        "refund_policy_snapshot": "refund_policy_snapshot",
    })


@bp.route("/cancellation-orders/<order_id>/transitions", methods=["POST"])
def order_transition(order_id):
    user_id, role = authenticate(request)
    require_role(role, (FIDUCIARY, PLATFORM_COMPLIANCE))
    payload = parse_body(request)
    body = validate(payload, required={"action": v_enum(ORDER_ACTIONS)}, optional={
        "effective_date": v_date(),
        "platform_reference": v_text(),
        "auto_renew_stopped": v_bool(),
        "reason": v_text(),
        "failure_reason": v_text(),
    })
    action = body["action"]
    require_action_role(role, action, ORDER_ACTION_OWNERS)
    if action == "REQUEST" and "effective_date" not in body:
        raise ApiError("ERR_INVALID_REQUEST",
                       "effective_date is required for the REQUEST action.")

    order = lookup.get_order(order_id)
    asset = lookup.asset_of_order(order)
    estate = lookup.estate_of_asset(asset)
    require_fiduciary_estate(user_id, role, asset["estate_id"])
    require_platform_scope(user_id, role, asset["platform_id"])
    estate_svc.require_open(estate)

    status = order["status"]

    if action == "REQUEST":
        if status not in ("PENDING", "FAILED"):
            raise ApiError("ERR_INVALID_ORDER_STATE")
        if not authority.has_active_authority(asset):
            raise ApiError("ERR_NO_ACTIVE_AUTHORITY")
        effective_date = body["effective_date"]
        if parse_date(effective_date) < parse_date(estate["date_of_death"]):
            raise ApiError("ERR_EFFECTIVE_DATE_BEFORE_DEATH")
        order["status"] = "REQUESTED"
        order["effective_date"] = effective_date
        order["failure_reason"] = None
        order["requested_at"] = CLOCK.iso()
        bump(order)
        estate_svc.recompute(estate)
        return single(public(order), 200)

    if action == "CONFIRM":
        if status != "REQUESTED":
            raise ApiError("ERR_INVALID_ORDER_STATE")
        order["status"] = "CONFIRMED"
        order["platform_reference"] = body.get("platform_reference")
        order["auto_renew_stopped"] = bool(body.get("auto_renew_stopped", False))
        order["confirmed_at"] = CLOCK.iso()
        bump(order)
        # hop 1 -- the account's subscription term is cancelled.
        term = _asset_term(asset["id"])
        if term is not None:
            term["state"] = "CANCELLED"
            term["auto_renew"] = False
            term["cancelled_effective_date"] = order["effective_date"]
            bump(term)
        # hop 2 -- caused by hop 1.
        if asset["subscription_billing_state"] != "CANCELLED":
            asset["subscription_billing_state"] = "CANCELLED"
            bump(asset)
        # hop 3 -- caused by hops 1-2.
        estate_svc.recompute(estate)
        return single(public(order), 200)

    # FAIL -- nothing else changes; the term stays ACTIVE.
    if status != "REQUESTED":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    order["status"] = "FAILED"
    order["failure_reason"] = (
        body.get("failure_reason") if "failure_reason" in body else body.get("reason"))
    bump(order)
    estate_svc.recompute(estate)
    return single(public(order), 200)


# ------------------------------------------------------------- RefundClaim

@bp.route("/cancellation-orders/<order_id>/refund-claims", methods=["POST"])
def create_claim(order_id):
    user_id, role = authenticate(request)
    require_role(role, (FIDUCIARY,))
    body = validate(parse_body(request), required={
        "claimed_period_start": v_date(),
        "claimed_period_end": v_date(),
        "pursuit_cost_cents": v_int(0, MAX_CENTS),
    })

    order = lookup.get_order(order_id)
    asset = lookup.asset_of_order(order)
    estate = lookup.estate_of_asset(asset)
    require_fiduciary_estate(user_id, role, asset["estate_id"])
    estate_svc.require_open(estate)

    if order["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_ORDER_STATE")

    term = _asset_term(asset["id"])
    if term is None:
        raise ApiError("ERR_SUBSCRIPTION_TERM_MISSING")
    if order["refund_policy_snapshot"] == "NONE":
        raise ApiError("ERR_REFUND_NOT_OFFERED")

    start = parse_date(body["claimed_period_start"])
    end = parse_date(body["claimed_period_end"])
    if (start < parse_date(term["term_start_date"])
            or end > parse_date(term["term_end_date"])
            or start > end):
        raise ApiError("ERR_CLAIM_PERIOD_OUT_OF_TERM")

    # The claimed interval is CLOSED, so touching endpoints overlap.
    for other in _asset_claims(asset["id"]):
        if other["status"] not in LIVE_CLAIM_STATUSES:
            continue
        o_start = parse_date(other["claimed_period_start"])
        o_end = parse_date(other["claimed_period_end"])
        if start <= o_end and o_start <= end:
            raise ApiError("ERR_CLAIM_PERIOD_OVERLAP")

    claimed_days = (end - start).days + 1
    if claimed_days < refund.REFUND_MIN_CLAIM_DAYS:
        raise ApiError("ERR_REFUND_WINDOW_TOO_SHORT")

    method = order["refund_policy_snapshot"]
    claimed_cents = refund.entitlement(
        method, term["period_fee_cents"], term["term_days"], claimed_days)

    record = {
        "cancellation_order_id": order_id,
        "claimed_period_start": body["claimed_period_start"],
        "claimed_period_end": body["claimed_period_end"],
        "pursuit_cost_cents": body["pursuit_cost_cents"],
        "claimed_days": claimed_days,
        "method": method,
        "claimed_cents": claimed_cents,
        "credited_cents": 0,
        "status": "FILED",
        "escalation_reason": None,
        "denial_reason": None,
        "chargeback_reason": None,
    }
    stamp_new(record)
    DB.claims[record["id"]] = record

    _recompute_claimed_days_total(asset["id"])
    estate_svc.recompute(estate)
    return single(public(record), 201)


@bp.route("/refund-claims/<claim_id>", methods=["GET"])
def read_claim(claim_id):
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return single(public(lookup.get_claim(claim_id)), 200)


@bp.route("/refund-claims", methods=["GET"])
def list_claims():
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return paged(DB.claims.values(), request.args, {
        "cancellation_order_id": "cancellation_order_id",
        "status": "status",
        "method": "method",
    })


@bp.route("/refund-claims/<claim_id>/transitions", methods=["POST"])
def claim_transition(claim_id):
    user_id, role = authenticate(request)
    require_role(role, (FIDUCIARY, PLATFORM_COMPLIANCE))
    body = validate(parse_body(request),
                    required={"action": v_enum(CLAIM_ACTIONS)},
                    optional={
                        "credited_cents": v_int(0, MAX_CENTS),
                        "escalation_reason": v_text(),
                        "denial_reason": v_text(),
                        "chargeback_reason": v_text(),
                        "reason": v_text(),
                    })
    action = body["action"]
    require_action_role(role, action, CLAIM_ACTION_OWNERS)
    if action == "CREDIT" and "credited_cents" not in body:
        raise ApiError("ERR_INVALID_REQUEST",
                       "credited_cents is required for the CREDIT action.")
    reason = body.get("reason")

    claim = lookup.get_claim(claim_id)
    order = lookup.order_of_claim(claim)
    asset = lookup.asset_of_order(order)
    estate = lookup.estate_of_asset(asset)
    require_fiduciary_estate(user_id, role, asset["estate_id"])
    require_platform_scope(user_id, role, asset["platform_id"])
    estate_svc.require_open(estate)

    status = claim["status"]

    if action == "START_REVIEW":
        if status != "FILED":
            raise ApiError("ERR_INVALID_CLAIM_STATE")
        claim["status"] = "PLATFORM_REVIEW"
        bump(claim)
        return single(public(claim), 200)

    if action == "ESCALATE":
        if status != "PLATFORM_REVIEW":
            raise ApiError("ERR_INVALID_CLAIM_STATE")
        claim["status"] = "ESCALATED"
        claim["escalation_reason"] = (
            body.get("escalation_reason") if "escalation_reason" in body else reason)
        bump(claim)
        return single(public(claim), 200)

    if action == "CREDIT":
        if status not in ("PLATFORM_REVIEW", "ESCALATED"):
            raise ApiError("ERR_INVALID_CLAIM_STATE")
        credited = body["credited_cents"]
        if credited > claim["claimed_cents"]:
            raise ApiError("ERR_CREDIT_EXCEEDS_CLAIM")
        claim["status"] = "CREDITED"
        claim["credited_cents"] = credited
        bump(claim)
        # The claim stays live, so the term's claimed_days_total is unchanged.
        estate_svc.recompute(estate)
        return single(public(claim), 200)

    if action == "DENY":
        if status not in ("PLATFORM_REVIEW", "ESCALATED"):
            raise ApiError("ERR_INVALID_CLAIM_STATE")
        claim["status"] = "DENIED"
        claim["denial_reason"] = (
            body.get("denial_reason") if "denial_reason" in body else reason)
        bump(claim)
        _recompute_claimed_days_total(asset["id"])
        estate_svc.recompute(estate)
        return single(public(claim), 200)

    # CHARGE_BACK -- compensates the credit exactly.
    if status != "CREDITED":
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    claim["status"] = "CHARGED_BACK"
    claim["chargeback_reason"] = (
        body.get("chargeback_reason") if "chargeback_reason" in body else reason)
    bump(claim)
    _recompute_claimed_days_total(asset["id"])
    estate_svc.recompute(estate)
    return single(public(claim), 200)
