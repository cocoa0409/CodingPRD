import uuid

from flask import Blueprint, request

import errors
from db import db
from middleware import authenticate, require_roles
from response import success, list_success
from services import validate as V
from services.common import new_common, touch, paginate, page_slice
from services.cascade import cancel_reserved_buddy_tickets, recompute_buddy_remaining
from services.scan_decision import decide
from services.serialize import (
    pass_out, lift_scan_out, buddy_ticket_out, refund_request_out,
    compute_scan_count, compute_buddy_remaining,
)

bp = Blueprint("passes", __name__)

READ_ROLES = {"NetworkAdmin", "ResortOps", "RefundAdmin"}


@bp.post("/passes")
def issue_pass():
    _, role = authenticate()
    require_roles(role, {"ResortOps"})
    body = V.get_body(request)
    pass_product_id = V.require_str(body, "pass_product_id")
    holder_name = V.require_str(body, "holder_name")
    # existence of referenced product (ERR_NOT_FOUND, priority 3 before ERR_VALIDATION
    # of other fields — but both required fields are strings here; existence checked
    # after body well-typedness per left-to-right reference order).
    product = db.pass_products.get(pass_product_id)
    if product is None:
        raise errors.not_found("Pass product not found")
    rec = new_common({
        "pass_product_id": pass_product_id,
        "holder_name": holder_name,
        "magnetic_token": uuid.uuid4().hex,
        "status": "ISSUED",
        "activated_on": None,
        "scan_count": 0,
        "buddy_tickets_remaining": 0,
        "refund_basis_cents": 0,
    })
    db.passes[rec["id"]] = rec
    return success(pass_out(rec), status=201)


@bp.get("/passes")
def list_passes():
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    limit, offset = paginate(request.args)
    pass_product_id = request.args.get("pass_product_id")
    records = list(db.passes.values())
    if pass_product_id is not None:
        records = [p for p in records if p["pass_product_id"] == pass_product_id]
    window, total = page_slice(records, limit, offset)
    return list_success([pass_out(p) for p in window], limit, offset, total)


@bp.get("/passes/<pid>")
def get_pass(pid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.passes.get(pid)
    if rec is None:
        raise errors.not_found("Pass not found")
    return success(pass_out(rec))


@bp.post("/passes/<pid>/activate")
def activate_pass(pid):
    _, role = authenticate()
    require_roles(role, {"ResortOps"})
    rec = db.passes.get(pid)
    if rec is None:
        raise errors.not_found("Pass not found")
    if rec["status"] == "ISSUED":
        # First activation.
        product = db.pass_products.get(rec["pass_product_id"])
        rec["status"] = "ACTIVE"
        rec["activated_on"] = db.clock_iso()
        rec["refund_basis_cents"] = product["price_cents"] if product else 0
        rec["buddy_tickets_remaining"] = product["buddy_ticket_allotment"] if product else 0
        touch(rec)
    elif rec["status"] == "SUSPENDED":
        # Reinstatement; activated_on and refund_basis_cents unchanged.
        rec["status"] = "ACTIVE"
        touch(rec)
    else:
        raise errors.invalid_state("Pass is neither ISSUED nor SUSPENDED")
    return success(pass_out(rec))


@bp.post("/passes/<pid>/suspend")
def suspend_pass(pid):
    _, role = authenticate()
    require_roles(role, {"ResortOps"})
    rec = db.passes.get(pid)
    if rec is None:
        raise errors.not_found("Pass not found")
    if rec["status"] != "ACTIVE":
        raise errors.invalid_state("Pass is not ACTIVE")
    cancel_reserved_buddy_tickets(rec["id"])
    recompute_buddy_remaining(rec)
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(pass_out(rec))


@bp.post("/passes/<pid>/scan")
def scan_pass(pid):
    _, role = authenticate()
    require_roles(role, {"ResortOps"})
    rec = db.passes.get(pid)
    if rec is None:
        raise errors.not_found("Pass not found")
    body = V.get_body(request)
    # Referenced-resource existence (priority 3) precedes other body-field
    # validity (priority 4): validate the resort_id identifier, resolve the
    # resort, then validate the remaining fields.
    resort_id = V.require_str(body, "resort_id")
    resort = db.resorts.get(resort_id)
    if resort is None:
        raise errors.not_found("Resort not found")
    presented_token = V.require_str(body, "presented_token")

    product = db.pass_products.get(rec["pass_product_id"])
    scan_at = db.clock
    scan_date = db.clock_date()

    result, denial_reason = decide(rec, product, resort, presented_token, scan_at, scan_date)

    scan = new_common({
        "pass_id": rec["id"],
        "resort_id": resort_id,
        "presented_token": presented_token,
        "scan_at": db.clock_iso(),     # ISO string for output
        "_scan_at_dt": scan_at,         # internal datetime for anti-passback math
        "scan_date": scan_date,
        "result": result,
        "denial_reason": denial_reason,
    })
    # LiftScan is immutable: only id + created_at (PRD §2.4). Drop version/updated_at.
    scan.pop("version", None)
    scan.pop("updated_at", None)
    db.lift_scans[scan["id"]] = scan

    if result == "GRANTED":
        rec["scan_count"] = compute_scan_count(rec["id"])
        touch(rec)
        return success(lift_scan_out(scan), status=201)

    # Denied: persist the row (already stored) and surface the matching error
    # for token/anti-passback/interchange denials. Other denials (NOT_ACTIVE,
    # RESORT_SUSPENDED, BLACKOUT) return the created LiftScan with 201.
    if denial_reason == "TOKEN_MISMATCH":
        raise errors.ApiError(errors.ERR_TOKEN_MISMATCH, 409,
                              "presented_token does not match the pass magnetic_token")
    if denial_reason == "ANTI_PASSBACK":
        raise errors.ApiError(errors.ERR_ANTI_PASSBACK, 409,
                              "A prior granted scan falls within the anti-passback window")
    if denial_reason == "NO_INTERCHANGE":
        raise errors.ApiError(errors.ERR_INTERCHANGE_DENIED, 409,
                              "Interchange not permitted for this scan")
    return success(lift_scan_out(scan), status=201)


# ---- FK reverse-reachability GETs scoped by pass ----

@bp.get("/passes/<pid>/lift-scans")
def pass_lift_scans(pid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    if db.passes.get(pid) is None:
        raise errors.not_found("Pass not found")
    limit, offset = paginate(request.args)
    resort_id = request.args.get("resort_id")
    records = [s for s in db.lift_scans.values() if s["pass_id"] == pid]
    if resort_id is not None:
        records = [s for s in records if s["resort_id"] == resort_id]
    window, total = page_slice(records, limit, offset)
    return list_success([lift_scan_out(s) for s in window], limit, offset, total)


@bp.get("/passes/<pid>/buddy-tickets")
def pass_buddy_tickets(pid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    if db.passes.get(pid) is None:
        raise errors.not_found("Pass not found")
    limit, offset = paginate(request.args)
    records = [b for b in db.buddy_tickets.values() if b["pass_id"] == pid]
    window, total = page_slice(records, limit, offset)
    return list_success([buddy_ticket_out(b) for b in window], limit, offset, total)


@bp.get("/passes/<pid>/refund-requests")
def pass_refund_requests(pid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    if db.passes.get(pid) is None:
        raise errors.not_found("Pass not found")
    limit, offset = paginate(request.args)
    records = [r for r in db.refund_requests.values() if r["pass_id"] == pid]
    window, total = page_slice(records, limit, offset)
    return list_success([refund_request_out(r) for r in window], limit, offset, total)
