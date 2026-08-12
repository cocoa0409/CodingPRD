"""Warranty claim endpoints."""
from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import get_auth, require_role
from response import success_response, parse_pagination, apply_pagination
from services.calculations import warranty_coverage, recompute_credit_balance
from services.common import (
    new_entity, touch, get_claim, get_spec, get_ticket, check_ownership,
    append_ledger_entry,
)
from services.serializers import serialize_warranty_claim

bp = Blueprint("claims", __name__)

READ_ROLES = {"Customer", "ShopManager"}


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/warranty-claims")
def create_claim():
    user_id, role = get_auth()
    require_role(role, {"Customer"})
    data = _body()
    description = data.get("description")
    build_spec_id = data.get("build_spec_id")
    repair_ticket_id = data.get("repair_ticket_id")

    # Body shape (priority 3): xor constraint on the subject
    if not isinstance(description, str):
        raise_err("ERR_VALIDATION", "description is required")
    has_spec = build_spec_id is not None
    has_ticket = repair_ticket_id is not None
    if has_spec == has_ticket:
        raise_err("ERR_VALIDATION",
                  "exactly one of build_spec_id / repair_ticket_id must be present")
    if has_spec and (not isinstance(build_spec_id, str) or not build_spec_id.strip()):
        raise_err("ERR_VALIDATION", "build_spec_id must be a string id")
    if has_ticket and (not isinstance(repair_ticket_id, str) or not repair_ticket_id.strip()):
        raise_err("ERR_VALIDATION", "repair_ticket_id must be a string id")

    # Existence (priority 4)
    if has_spec:
        subject = get_spec(build_spec_id)
        subject_type = "spec"
    else:
        subject = get_ticket(repair_ticket_id)
        subject_type = "ticket"

    # Ownership (priority 5): the claim is owned by the subject's customer
    check_ownership(subject, user_id, role)

    # State guard (priority 7): subject must be claimable
    if subject_type == "spec":
        if subject["status"] != "DELIVERED":
            raise_err("ERR_SUBJECT_NOT_CLAIMABLE", "build spec is not DELIVERED")
        anchor = subject["delivered_at"]
        subject_price = subject["final_price_cents"]
    else:
        if subject["work_status"] != "PICKED_UP":
            raise_err("ERR_SUBJECT_NOT_CLAIMABLE", "repair ticket is not PICKED_UP")
        anchor = subject["picked_up_at"]
        subject_price = subject["quoted_total_cents"]

    # Temporal rule (priority 9): warranty window
    result = warranty_coverage(subject_type, anchor, db.logical_now, subject_price)
    if result is None:
        raise_err("ERR_CLAIM_WINDOW_EXPIRED", "warranty claim window has expired")
    coverage_pct, covered_estimate_cents = result

    # Structural constraint (priority 11): duplicate open claim on same subject
    for existing in db.warranty_claims.values():
        if existing["status"] not in ("SUBMITTED", "APPROVED"):
            continue
        if subject_type == "spec" and existing["build_spec_id"] == build_spec_id:
            raise_err("ERR_DUPLICATE_CLAIM",
                      "an open claim already exists for this subject")
        if subject_type == "ticket" and existing["repair_ticket_id"] == repair_ticket_id:
            raise_err("ERR_DUPLICATE_CLAIM",
                      "an open claim already exists for this subject")

    c = new_entity()
    c.update({
        "customer_id": subject["customer_id"],
        "build_spec_id": build_spec_id,
        "repair_ticket_id": repair_ticket_id,
        "description": description,
        "coverage_pct": coverage_pct,
        "covered_estimate_cents": covered_estimate_cents,
        "status": "SUBMITTED",
        "appeal_count": 0,
        "denial_reason": None,
    })
    db.warranty_claims[c["id"]] = c
    return success_response(serialize_warranty_claim(c), status=201)


@bp.get("/warranty-claims/<cid>")
def read_claim(cid):
    user_id, role = get_auth()
    require_role(role, READ_ROLES)
    c = get_claim(cid)
    check_ownership(c, user_id, role)
    return success_response(serialize_warranty_claim(c))


@bp.get("/warranty-claims")
def list_claims():
    user_id, role = get_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.warranty_claims.values())
    if role == "Customer":
        items = [c for c in items if c["customer_id"] == user_id]
    for field in ("build_spec_id", "repair_ticket_id", "customer_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [c for c in items if c.get(field) == val]
    items.sort(key=lambda c: c["created_at"])
    page, pagination = apply_pagination(items, limit, offset)
    return success_response(
        [serialize_warranty_claim(c) for c in page],
        response_type="array", pagination=pagination,
    )


@bp.post("/warranty-claims/<cid>/decide")
def decide_claim(cid):
    user_id, role = get_auth()
    require_role(role, {"ShopManager"})
    data = _body()
    decision = data.get("decision")
    denial_reason = data.get("denial_reason")
    if decision not in ("APPROVED", "DENIED"):
        raise_err("ERR_VALIDATION", "decision must be APPROVED or DENIED")
    if decision == "DENIED" and (
            not isinstance(denial_reason, str) or not denial_reason.strip()):
        raise_err("ERR_VALIDATION", "denial_reason is required when decision is DENIED")
    c = get_claim(cid)
    if c["status"] != "SUBMITTED":
        raise_err("ERR_CLAIM_NOT_SUBMITTED", "decide called on a claim not in SUBMITTED")
    if decision == "APPROVED":
        c["status"] = "APPROVED"
    else:
        c["status"] = "DENIED"
        c["denial_reason"] = denial_reason
    touch(c)
    return success_response(serialize_warranty_claim(c))


@bp.post("/warranty-claims/<cid>/resolve")
def resolve_claim(cid):
    user_id, role = get_auth()
    require_role(role, {"ShopManager"})
    c = get_claim(cid)
    if c["status"] != "APPROVED":
        raise_err("ERR_CLAIM_NOT_APPROVED", "resolve called on a claim not in APPROVED")
    append_ledger_entry(c["customer_id"], c["covered_estimate_cents"],
                        "WARRANTY_RESOLUTION", c["id"])
    recompute_credit_balance(c["customer_id"])
    touch(db.customers[c["customer_id"]])
    c["status"] = "RESOLVED"
    touch(c)
    return success_response(serialize_warranty_claim(c))


@bp.post("/warranty-claims/<cid>/appeal")
def appeal_claim(cid):
    user_id, role = get_auth()
    require_role(role, {"Customer"})
    c = get_claim(cid)
    check_ownership(c, user_id, role)
    if c["status"] != "DENIED":
        raise_err("ERR_CLAIM_NOT_DENIED", "appeal called on a claim not in DENIED")
    if c["appeal_count"] >= 2:
        raise_err("ERR_APPEAL_LIMIT_REACHED", "appeal limit reached")
    c["status"] = "SUBMITTED"
    c["appeal_count"] += 1
    c["denial_reason"] = None
    touch(c)
    return success_response(serialize_warranty_claim(c))
