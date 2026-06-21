"""Requisition + ApprovalStep endpoints (PRD §3.1)."""
from flask import Blueprint, request, g

import errors
from errors import ApiError
from db import db
from middleware import require_roles, ALL_ROLES
from response import object_response, list_response
from services.common import (
    init_common, touch, public, get_body, require_fields, require_positive_int,
    invalid, parse_pagination, paginate, resolve,
)
from services.calculations import (
    estimated_total, required_levels_for, ROLE_FOR_LEVEL,
)
from services.cascades import cancel_open_rfqs_for_requisition

bp = Blueprint("requisitions", __name__)


def _validate_lines(lines):
    if not isinstance(lines, list) or len(lines) == 0:
        invalid("lines must be a non-empty array")
    for l in lines:
        if not isinstance(l, dict):
            invalid("each line must be an object")
        if "sku" not in l or not isinstance(l["sku"], str) or l["sku"] == "":
            invalid("each line requires a sku")
        if "quantity" not in l:
            invalid("each line requires a quantity")
        require_positive_int(l["quantity"], "quantity")
        if "estimated_unit_price_cents" not in l:
            invalid("each line requires estimated_unit_price_cents")
        require_positive_int(l["estimated_unit_price_cents"],
                             "estimated_unit_price_cents")


@bp.route("/procurement/requisitions", methods=["POST"])
@require_roles("Buyer")
def create_requisition():
    body = get_body()
    require_fields(body, ["spend_category_id", "title", "lines"])
    spend_category_id = body["spend_category_id"]
    title = body["title"]
    if not isinstance(title, str) or title == "":
        invalid("title must be a non-empty string")
    _validate_lines(body["lines"])

    resolve(db.spend_categories, spend_category_id)

    lines = [
        {
            "sku": l["sku"],
            "description": l.get("description"),
            "quantity": l["quantity"],
            "estimated_unit_price_cents": l["estimated_unit_price_cents"],
        }
        for l in body["lines"]
    ]

    rec = {
        "requester_id": g.user_id,
        "spend_category_id": spend_category_id,
        "title": title,
        "lines": lines,
        "estimated_total_cents": None,
        "committed_total_cents": None,
        "required_levels": None,
        "revision_count": 0,
        "status": "DRAFT",
    }
    init_common(rec)
    db.requisitions[rec["id"]] = rec
    return object_response(public(rec), status=201)


@bp.route("/procurement/requisitions/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_requisition(rid):
    rec = resolve(db.requisitions, rid)
    return object_response(public(rec))


@bp.route("/procurement/requisitions", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_requisitions():
    limit, offset = parse_pagination(request.args)
    spend_category_id = request.args.get("spend_category_id")
    status = request.args.get("status")
    requester_id = request.args.get("requester_id")
    items = []
    for rec in db.requisitions.values():
        if spend_category_id is not None and rec["spend_category_id"] != spend_category_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        if requester_id is not None and rec["requester_id"] != requester_id:
            continue
        items.append(rec)
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


def _steps_for(requisition_id):
    return [s for s in db.approval_steps.values()
            if s["requisition_id"] == requisition_id]


def _sod_requester(rec):
    if g.user_id == rec["requester_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "Acting user must not be the requisition requester")


@bp.route("/procurement/requisitions/<rid>/submit", methods=["POST"])
@require_roles("Buyer")
def submit_requisition(rid):
    rec = resolve(db.requisitions, rid)
    # SOD: acting buyer must equal requester (priority 5, before state check).
    if g.user_id != rec["requester_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "Only the requester may submit")
    if rec["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Requisition is not in DRAFT")
    if not rec["lines"]:
        invalid("lines must be non-empty")
    category = db.spend_categories.get(rec["spend_category_id"])
    if category is None or category["status"] != "ACTIVE":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Spend category is not ACTIVE")

    est = estimated_total(rec["lines"])
    rec["estimated_total_cents"] = est
    levels = required_levels_for(
        est, category["approval_threshold_cents"],
        category["director_threshold_cents"],
    )
    rec["required_levels"] = levels

    for level in range(1, levels + 1):
        step = {
            "requisition_id": rec["id"],
            "level": level,
            "required_role": ROLE_FOR_LEVEL[level],
            "decided_by_id": None,
            "decided_at": None,
            "status": "PENDING",
        }
        init_common(step)
        db.approval_steps[step["id"]] = step

    rec["status"] = "PENDING_APPROVAL"
    touch(rec)
    return object_response(public(rec))


def _do_reject(rec):
    """Reject at the current pending step: decided step REJECTED, remaining
    PENDING -> SKIPPED, requisition REJECTED, cascade-cancel OPEN RFQs."""
    from db import now_iso
    steps = sorted(_steps_for(rec["id"]), key=lambda s: s["level"])
    current = next((s for s in steps if s["status"] == "PENDING"), None)
    if current is not None:
        current["decided_by_id"] = g.user_id
        current["decided_at"] = now_iso()
        current["status"] = "REJECTED"
        touch(current)
    for s in steps:
        if s["status"] == "PENDING":
            s["status"] = "SKIPPED"
            touch(s)
    rec["status"] = "REJECTED"
    touch(rec)
    cancel_open_rfqs_for_requisition(rec["id"])


@bp.route("/procurement/requisitions/<rid>/approve", methods=["POST"])
@require_roles("Approver")
def approve_requisition(rid):
    from db import now_iso
    rec = resolve(db.requisitions, rid)
    body = get_body()
    decision = body.get("decision")
    # SOD: approver may never decide a requisition they raised.
    _sod_requester(rec)
    if rec["status"] != "PENDING_APPROVAL":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Requisition is not PENDING_APPROVAL")

    if decision is not None and str(decision).upper() == "REJECT":
        _do_reject(rec)
        return object_response(public(rec))

    steps = sorted(_steps_for(rec["id"]), key=lambda s: s["level"])
    current = next((s for s in steps if s["status"] == "PENDING"), None)
    if current is None:
        # No pending step to decide, yet requisition is not APPROVED.
        raise ApiError(errors.ERR_APPROVAL_INCOMPLETE, 409,
                       "No pending approval step to decide")

    # Decide the current (lowest-level) pending step.
    current["decided_by_id"] = g.user_id
    current["decided_at"] = now_iso()
    current["status"] = "APPROVED"
    touch(current)

    # Requisition advances to APPROVED only when every step is APPROVED.
    if all(s["status"] == "APPROVED" for s in steps):
        rec["status"] = "APPROVED"
        touch(rec)
    return object_response(public(rec))


@bp.route("/procurement/requisitions/<rid>/reject", methods=["POST"])
@require_roles("Approver")
def reject_requisition(rid):
    rec = resolve(db.requisitions, rid)
    _sod_requester(rec)
    if rec["status"] != "PENDING_APPROVAL":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Requisition is not PENDING_APPROVAL")
    _do_reject(rec)
    return object_response(public(rec))


@bp.route("/procurement/requisitions/<rid>/revise", methods=["POST"])
@require_roles("Buyer")
def revise_requisition(rid):
    rec = resolve(db.requisitions, rid)
    if g.user_id != rec["requester_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "Only the requester may revise")
    if rec["status"] != "REJECTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Requisition is not REJECTED")
    rec["revision_count"] += 1
    # Clear prior ApprovalStep rows so a fresh cycle can begin.
    for sid in [s["id"] for s in _steps_for(rec["id"])]:
        del db.approval_steps[sid]
    rec["status"] = "DRAFT"
    touch(rec)
    return object_response(public(rec))


@bp.route("/procurement/requisitions/<rid>/cancel", methods=["POST"])
@require_roles("Buyer")
def cancel_requisition(rid):
    rec = resolve(db.requisitions, rid)
    if g.user_id != rec["requester_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "Only the requester may cancel")
    if rec["status"] not in ("DRAFT", "PENDING_APPROVAL"):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Requisition cannot be cancelled from its current state")
    if rec["status"] == "PENDING_APPROVAL":
        for s in _steps_for(rec["id"]):
            if s["status"] == "PENDING":
                s["status"] = "SKIPPED"
                touch(s)
    rec["status"] = "CANCELLED"
    touch(rec)
    cancel_open_rfqs_for_requisition(rec["id"])
    return object_response(public(rec))


# --- ApprovalStep reads ---
@bp.route("/procurement/approval-steps/<sid>", methods=["GET"])
@require_roles("ProcurementAdmin", "Buyer", "Approver")
def get_approval_step(sid):
    rec = resolve(db.approval_steps, sid)
    return object_response(public(rec))


@bp.route("/procurement/approval-steps", methods=["GET"])
@require_roles("ProcurementAdmin", "Buyer", "Approver")
def list_approval_steps():
    limit, offset = parse_pagination(request.args)
    requisition_id = request.args.get("requisition_id")
    status = request.args.get("status")
    items = []
    for rec in db.approval_steps.values():
        if requisition_id is not None and rec["requisition_id"] != requisition_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        items.append(rec)
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)
