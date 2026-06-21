"""Seller endpoints (PRD §3.1, §3.2 and read paths)."""
from flask import Blueprint

from common import (
    parse_pagination, paginate, sort_by_created, get_json_body,
)
from errors import (
    err, ERR_INVALID_STATE, ERR_INVALID_REQUEST, ERR_OPEN_BALANCE_BLOCKS_CLOSE,
)
from db import db
from middleware import (
    get_identity, require_roles, ROLE_SELLER, ROLE_REVIEWER, ROLE_FINANCE,
)
from response import success
from routes.helpers import fetch, ensure_seller_owns
from services.entity import touch
from services.seller import (
    create_seller, recompute_account_status, serialize_seller,
    refresh_seller_derived, open_initial_reserve,
)
from services.ledger import reconcile_balances

bp = Blueprint("sellers", __name__)


@bp.post("/sellers")
def post_sellers():
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER])
    body = get_json_body()
    seller = create_seller(body)
    return success(serialize_seller(seller), status=201)


@bp.get("/sellers/<seller_id>")
def get_seller(seller_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER, ROLE_FINANCE, ROLE_SELLER])
    seller = fetch(db.sellers, seller_id)
    ensure_seller_owns(role, user_id, seller["id"])
    return success(serialize_seller(seller))


@bp.get("/sellers")
def list_sellers():
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER, ROLE_FINANCE])
    from flask import request
    limit, offset = parse_pagination()
    account_status = request.args.get("account_status")
    kyc_status = request.args.get("kyc_status")
    items = list(db.sellers.values())
    for s in items:
        refresh_seller_derived(s)
    if account_status is not None:
        items = [s for s in items if s["account_status"] == account_status]
    if kyc_status is not None:
        items = [s for s in items if s["kyc_status"] == kyc_status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, pagination=meta)


@bp.post("/sellers/<seller_id>/kyc/submit")
def kyc_submit(seller_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_SELLER])
    seller = fetch(db.sellers, seller_id)
    ensure_seller_owns(role, user_id, seller["id"])
    if seller["kyc_status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "KYC must be PENDING to submit.")
    seller["kyc_status"] = "IN_REVIEW"
    touch(seller)
    return success(serialize_seller(seller))


@bp.post("/sellers/<seller_id>/kyc/decision")
def kyc_decision(seller_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER])
    seller = fetch(db.sellers, seller_id)
    body = get_json_body()
    decision = body.get("decision")
    if not isinstance(decision, str):
        raise err(ERR_INVALID_REQUEST, "decision is required.")
    norm = decision.strip().upper()
    approve_vals = {"APPROVE", "APPROVED"}
    reject_vals = {"REJECT", "REJECTED"}
    if norm not in approve_vals | reject_vals:
        raise err(ERR_INVALID_REQUEST, "decision must approve or reject KYC.")
    if seller["kyc_status"] != "IN_REVIEW":
        raise err(ERR_INVALID_STATE, "KYC must be IN_REVIEW to decide.")
    if norm in approve_vals:
        seller["kyc_status"] = "APPROVED"
        seller["kyc_reviewer_id"] = user_id
    else:
        seller["kyc_status"] = "REJECTED"
    recompute_account_status(seller)
    touch(seller)
    return success(serialize_seller(seller))


@bp.post("/sellers/<seller_id>/w9/submit")
def w9_submit(seller_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_SELLER])
    seller = fetch(db.sellers, seller_id)
    ensure_seller_owns(role, user_id, seller["id"])
    if seller["w9_status"] != "NOT_SUBMITTED":
        raise err(ERR_INVALID_STATE, "W-9 must be NOT_SUBMITTED to submit.")
    seller["w9_status"] = "SUBMITTED"
    touch(seller)
    return success(serialize_seller(seller))


@bp.post("/sellers/<seller_id>/w9/approve")
def w9_approve(seller_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER])
    seller = fetch(db.sellers, seller_id)
    # W-9 approval permitted only when kyc APPROVED, w9 SUBMITTED, and a VERIFIED
    # payout method exists (PRD §3.1). w9_status must be SUBMITTED -> state guard.
    if seller["w9_status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "W-9 must be SUBMITTED to approve.")
    if seller["kyc_status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "KYC must be APPROVED before W-9 approval.")
    from services.seller import has_verified_method
    if not has_verified_method(seller["id"]):
        raise err(ERR_INVALID_STATE,
                  "A VERIFIED payout method is required before W-9 approval.")
    seller["w9_status"] = "APPROVED"
    activated = recompute_account_status(seller)
    if activated:
        open_initial_reserve(seller)
    touch(seller)
    return success(serialize_seller(seller))


@bp.post("/sellers/<seller_id>/suspend")
def suspend(seller_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER])
    seller = fetch(db.sellers, seller_id)
    if seller["account_status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Only an ACTIVE seller may be suspended.")
    seller["account_status"] = "SUSPENDED"
    touch(seller)
    return success(serialize_seller(seller))


@bp.post("/sellers/<seller_id>/reinstate")
def reinstate(seller_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER])
    seller = fetch(db.sellers, seller_id)
    if seller["account_status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Only a SUSPENDED seller may be reinstated.")
    seller["account_status"] = "ACTIVE"
    touch(seller)
    return success(serialize_seller(seller))


@bp.post("/sellers/<seller_id>/close")
def close(seller_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER])
    seller = fetch(db.sellers, seller_id)
    # Close permitted from ACTIVE or SUSPENDED (PRD §3.2) -> state guard first.
    if seller["account_status"] not in ("ACTIVE", "SUSPENDED"):
        raise err(ERR_INVALID_STATE, "Seller must be ACTIVE or SUSPENDED to close.")
    # Open-balance close guard (PRD §3.2): no order PENDING or AVAILABLE.
    for o in db.orders.values():
        if o["seller_id"] == seller["id"] and o["settlement_status"] in ("PENDING", "AVAILABLE"):
            raise err(ERR_OPEN_BALANCE_BLOCKS_CLOSE,
                      "Cannot close a seller with open order balances.")
    seller["account_status"] = "CLOSED"
    # Cascade: release any OPEN reserve.
    from services.reserve import release_reserve_row
    for r in list(db.reserves.values()):
        if r["seller_id"] == seller["id"] and r["reserve_status"] == "OPEN":
            release_reserve_row(seller, r)
    reconcile_balances(seller)
    touch(seller)
    return success(serialize_seller(seller))


@bp.get("/sellers/<seller_id>/ledger-entries")
def seller_ledger(seller_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER, ROLE_FINANCE, ROLE_SELLER])
    seller = fetch(db.sellers, seller_id)
    ensure_seller_owns(role, user_id, seller["id"])
    from flask import request
    limit, offset = parse_pagination()
    hold_state = request.args.get("hold_state")
    source_type = request.args.get("source_type")
    items = [e for e in db.ledger_entries.values() if e["seller_id"] == seller["id"]]
    if hold_state is not None:
        items = [e for e in items if e["hold_state"] == hold_state]
    if source_type is not None:
        items = [e for e in items if e["source_type"] == source_type]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, pagination=meta)


@bp.get("/sellers/<seller_id>/reserves")
def seller_reserves(seller_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER, ROLE_FINANCE, ROLE_SELLER])
    seller = fetch(db.sellers, seller_id)
    ensure_seller_owns(role, user_id, seller["id"])
    from flask import request
    limit, offset = parse_pagination()
    reserve_status = request.args.get("reserve_status")
    items = [r for r in db.reserves.values() if r["seller_id"] == seller["id"]]
    if reserve_status is not None:
        items = [r for r in items if r["reserve_status"] == reserve_status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, pagination=meta)
