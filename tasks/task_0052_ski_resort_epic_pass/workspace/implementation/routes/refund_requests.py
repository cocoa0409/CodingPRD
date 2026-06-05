from flask import Blueprint, request

import errors
from db import db
from middleware import authenticate, require_roles
from response import success, list_success
from services import validate as V
from services.common import new_common, touch, paginate, page_slice
from services.cascade import cancel_reserved_buddy_tickets, recompute_buddy_remaining
from services.refund_calc import compute_refund, MAX_SCANS_FOR_REFUND
from services.serialize import refund_request_out, compute_scan_count

bp = Blueprint("refund_requests", __name__)

READ_ROLES = {"NetworkAdmin", "ResortOps", "RefundAdmin"}
REASONS = {"INJURY", "RELOCATION", "DISSATISFIED"}


@bp.post("/refund-requests")
def open_refund_request():
    _, role = authenticate()
    require_roles(role, {"ResortOps", "RefundAdmin"})
    body = V.get_body(request)
    pass_id = V.require_str(body, "pass_id")
    reason = V.require_enum(body, "reason", REASONS)
    pass_rec = db.passes.get(pass_id)
    if pass_rec is None:
        raise errors.not_found("Pass not found")
    snapshot = compute_scan_count(pass_id)
    rec = new_common({
        "pass_id": pass_id,
        "reason": reason,
        "scan_count_at_request": snapshot,
        "refund_amount_cents": 0,
        "status": "PENDING",
    })
    db.refund_requests[rec["id"]] = rec
    return success(refund_request_out(rec), status=201)


@bp.get("/refund-requests")
def list_refund_requests():
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    limit, offset = paginate(request.args)
    pass_id = request.args.get("pass_id")
    records = list(db.refund_requests.values())
    if pass_id is not None:
        records = [r for r in records if r["pass_id"] == pass_id]
    window, total = page_slice(records, limit, offset)
    return list_success([refund_request_out(r) for r in window], limit, offset, total)


@bp.get("/refund-requests/<rid>")
def get_refund_request(rid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.refund_requests.get(rid)
    if rec is None:
        raise errors.not_found("Refund request not found")
    return success(refund_request_out(rec))


@bp.post("/refund-requests/<rid>/approve")
def approve_refund_request(rid):
    _, role = authenticate()
    require_roles(role, {"RefundAdmin"})
    rec = db.refund_requests.get(rid)
    if rec is None:
        raise errors.not_found("Refund request not found")
    # Existence of referenced resources (priority 3) precedes body-field validity
    # (priority 4), per PRD §2.5.
    pass_rec = db.passes.get(rec["pass_id"])
    if pass_rec is None:
        raise errors.not_found("Referenced pass not found")

    body = V.get_body(request)
    # OCC field is required on approval (PRD §2.9). Missing/wrong type -> ERR_VALIDATION.
    expected_version = V.require_int(body, "expected_pass_version")

    # Priority order: state (PENDING) -> eligibility -> stale version.
    if rec["status"] != "PENDING":
        raise errors.invalid_state("Refund request is not PENDING")

    # Eligibility (ERR_REFUND_INELIGIBLE, priority 10): ACTIVE and lightly used.
    live_scan_count = compute_scan_count(pass_rec["id"])
    if pass_rec["status"] != "ACTIVE" or live_scan_count > MAX_SCANS_FOR_REFUND:
        raise errors.ApiError(errors.ERR_REFUND_INELIGIBLE, 409,
                              "Pass is not ACTIVE or has been scanned too many times")

    # OCC (ERR_STALE_VERSION, priority 11, HTTP 412).
    if expected_version != pass_rec["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412,
                              "expected_pass_version does not match the pass version")

    # Compute payout from the snapshot, not the live scan count.
    rec["refund_amount_cents"] = compute_refund(
        pass_rec["refund_basis_cents"], rec["scan_count_at_request"], rec["reason"]
    )
    rec["status"] = "APPROVED"
    touch(rec)

    # Cascade: pass ACTIVE -> REFUNDED, cancelling RESERVED buddy tickets.
    cancel_reserved_buddy_tickets(pass_rec["id"])
    recompute_buddy_remaining(pass_rec)
    pass_rec["status"] = "REFUNDED"
    touch(pass_rec)

    return success(refund_request_out(rec))


@bp.post("/refund-requests/<rid>/reject")
def reject_refund_request(rid):
    _, role = authenticate()
    require_roles(role, {"RefundAdmin"})
    rec = db.refund_requests.get(rid)
    if rec is None:
        raise errors.not_found("Refund request not found")
    if rec["status"] != "PENDING":
        raise errors.invalid_state("Refund request is not PENDING")
    rec["refund_amount_cents"] = 0
    rec["status"] = "REJECTED"
    touch(rec)
    return success(refund_request_out(rec))
