"""DamageClaim endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from serialize import ser_claim
from services import CLAIM_CAPS
from util import (
    caller, require_role, forbid, get_body, respond, paginate, req_str,
    req_int, req_enum, opt_int, stamp_new, touch, now, ApiError,
)
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_CLAIM_WINDOW_EXPIRED,
    ERR_PRE_EXISTING_CONDITION_DOCUMENTED, ERR_CLAIM_CAP_EXCEEDED,
    ERR_SEGREGATION_OF_DUTIES,
)

bp = Blueprint("claims", __name__)

AREAS = {"EXTERIOR_BODY", "GLASS", "WHEELS", "INTERIOR", "TRIM"}


@bp.post("/fleet-wash/damage-claims")
def create_claim():
    uid, role = caller()
    require_role(role, {"Customer"})
    body = get_body()
    wash_order_id = req_str(body, "wash_order_id")
    order = store.orders.get(wash_order_id)
    if order is None:
        raise ApiError(ERR_NOT_FOUND, "WashOrder %s not found" % wash_order_id)
    if order["customer_id"] != uid:
        forbid("Customers may only file claims on their own wash orders")
    area = req_enum(body, "area", AREAS)
    amount = req_int(body, "claimed_amount_cents")
    if amount <= 0:
        raise ApiError(ERR_VALIDATION, "claimed_amount_cents must be > 0")
    description = req_str(body, "description")
    if order["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, "WashOrder is not COMPLETED")
    if now() > order["completed_at"] + timedelta(hours=72):
        raise ApiError(ERR_CLAIM_WINDOW_EXPIRED,
                       "More than 72 hours have passed since completion")
    rec = {
        "wash_order_id": wash_order_id,
        "customer_id": order["customer_id"],
        "area": area,
        "claimed_amount_cents": amount,
        "description": description,
        "status": "FILED",
        "approved_amount_cents": None,
        "filed_at": now(),
        "reviewed_by": None,
        "paid_by": None,
        "deny_reason": None,
    }
    stamp_new(rec)
    store.claims[rec["id"]] = rec
    return respond(ser_claim(rec), 201)


@bp.get("/fleet-wash/damage-claims/<cid>")
def get_claim(cid):
    uid, role = caller()
    rec = store.claims.get(cid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "DamageClaim %s not found" % cid)
    if role == "Customer" and rec["customer_id"] != uid:
        forbid("Customers may only access their own damage claims")
    return respond(ser_claim(rec), 200)


@bp.get("/fleet-wash/damage-claims")
def list_claims():
    uid, role = caller()
    wash_order_id = request.args.get("wash_order_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    if role == "Customer":
        if customer_id is not None and customer_id != uid:
            forbid("Customers may only list their own damage claims")
        customer_id = uid
    recs = list(store.claims.values())
    if wash_order_id is not None:
        recs = [c for c in recs if c["wash_order_id"] == wash_order_id]
    if customer_id is not None:
        recs = [c for c in recs if c["customer_id"] == customer_id]
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return paginate(recs, ser_claim)


@bp.post("/fleet-wash/damage-claims/<cid>/events")
def claim_event(cid):
    uid, role = caller()
    require_role(role, {"QualityAuditor"})
    rec = store.claims.get(cid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "DamageClaim %s not found" % cid)
    body = get_body()
    event = req_str(body, "event_type")
    if event not in ("START_REVIEW", "APPROVE", "DENY", "MARK_PAID"):
        raise ApiError(ERR_VALIDATION,
                       "event_type must be START_REVIEW, APPROVE, DENY, or MARK_PAID")
    if event == "START_REVIEW":
        if rec["status"] != "FILED":
            raise ApiError(ERR_INVALID_STATE, "DamageClaim is not FILED")
        rec["status"] = "UNDER_REVIEW"
    elif event == "APPROVE":
        explicit = opt_int(body, "approved_amount_cents")
        if explicit is not None and explicit < 0:
            raise ApiError(ERR_VALIDATION, "approved_amount_cents must be >= 0")
        if rec["status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE, "DamageClaim is not UNDER_REVIEW")
        order = store.orders.get(rec["wash_order_id"])
        for report in store.reports.values():
            if report["wash_order_id"] == rec["wash_order_id"] \
                    and report["status"] == "SUBMITTED":
                for entry in report["areas"]:
                    if entry["area"] == rec["area"] and entry["pre_existing_damage"]:
                        raise ApiError(
                            ERR_PRE_EXISTING_CONDITION_DOCUMENTED,
                            "A submitted inspection report documents pre-existing damage on this area")
        first_class = store.vehicles[order["vehicle_ids"][0]]["vehicle_class"]
        cap = CLAIM_CAPS[first_class]
        ceiling = min(rec["claimed_amount_cents"], cap)
        if explicit is not None and explicit > ceiling:
            raise ApiError(ERR_CLAIM_CAP_EXCEEDED,
                           "approved_amount_cents exceeds min(claimed_amount_cents, class cap)")
        rec["approved_amount_cents"] = explicit if explicit is not None else ceiling
        rec["reviewed_by"] = uid
        rec["status"] = "APPROVED"
    elif event == "DENY":
        if rec["status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE, "DamageClaim is not UNDER_REVIEW")
        reason = req_str(body, "deny_reason")
        rec["deny_reason"] = reason
        rec["reviewed_by"] = uid
        rec["status"] = "DENIED"
    else:  # MARK_PAID
        if rec["status"] != "APPROVED":
            raise ApiError(ERR_INVALID_STATE, "DamageClaim is not APPROVED")
        if uid == rec["reviewed_by"]:
            raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                           "The approving auditor may not mark the same claim paid")
        rec["paid_by"] = uid
        rec["status"] = "PAID"
    touch(rec)
    return respond(ser_claim(rec), 200)
