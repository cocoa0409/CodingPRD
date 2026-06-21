"""WarrantyClaim routes (PRD §3.9, §4) — submit, list, fetch, approve, deny."""
from flask import Blueprint, request

import db
import errors
import serialize
from middleware import authenticate, authorize, get_json_body
from helpers import require_str, require_enum, opt_str, parse_pagination, paginate
from response import object_response, array_response
from services import calc

bp = Blueprint("warranty_claims", __name__)

CLAIM_TYPES = {"REPLACEMENT", "REPAIR"}


@bp.post("/warranty-claims")
def create_claim():
    _, role = authenticate()
    authorize(role, ["WarrantyAdmin", "MaintenanceManager"])
    body = get_json_body()
    asset_id = require_str(body, "asset_id")
    work_order_id = require_str(body, "work_order_id")
    claim_type = require_enum(body, "claim_type", CLAIM_TYPES)
    with db.LOCK:
        if asset_id not in db.assets:
            raise errors.reference_not_found("asset_id does not reference an existing asset.")
        if work_order_id not in db.work_orders:
            raise errors.reference_not_found("work_order_id does not reference an existing work order.")
        rec = db.new_record()
        rec.update({
            "asset_id": asset_id,
            "work_order_id": work_order_id,
            "claim_type": claim_type,
            "claimed_cost_cents": 0,
            "payable_cost_cents": 0,
            "status": "SUBMITTED",
            "decision_reason": None,
        })
        db.warranty_claims[rec["id"]] = rec
        return object_response(serialize.warranty_claim(rec), 201)


@bp.get("/warranty-claims/<cid>")
def get_claim(cid):
    _, role = authenticate()
    authorize(role, ["WarrantyAdmin", "MaintenanceManager", "Planner"])
    with db.LOCK:
        rec = db.warranty_claims.get(cid)
        if rec is None:
            raise errors.not_found()
        return object_response(serialize.warranty_claim(rec), 200)


@bp.get("/warranty-claims")
def list_claims():
    _, role = authenticate()
    authorize(role, ["WarrantyAdmin", "MaintenanceManager", "Planner"])
    limit, offset = parse_pagination()
    asset_id = request.args.get("asset_id")
    work_order_id = request.args.get("work_order_id")
    with db.LOCK:
        items = sorted(db.warranty_claims.values(), key=lambda c: c["_seq"])
        if asset_id is not None:
            items = [c for c in items if c["asset_id"] == asset_id]
        if work_order_id is not None:
            items = [c for c in items if c["work_order_id"] == work_order_id]
        total = len(items)
        page = paginate(items, limit, offset)
        return array_response([serialize.warranty_claim(c) for c in page],
                              limit, offset, total)


@bp.post("/warranty-claims/<cid>/approve")
def approve_claim(cid):
    _, role = authenticate()
    authorize(role, ["WarrantyAdmin"])
    body = get_json_body()
    decision_reason = opt_str(body, "decision_reason", default=None)
    with db.LOCK:
        claim = db.warranty_claims.get(cid)
        if claim is None:
            raise errors.not_found()
        # State (priority 6): claim must be SUBMITTED.
        if claim["status"] != "SUBMITTED":
            raise errors.invalid_state("Claim is not SUBMITTED.")
        wo = db.work_orders.get(claim["work_order_id"])
        asset = db.assets.get(claim["asset_id"])
        # Referenced WO must be CLOSED (no dedicated error -> ERR_INVALID_STATE).
        if wo is None or wo["execution_status"] != "CLOSED":
            raise errors.invalid_state("Referenced work order is not CLOSED.")
        # Warranty coverage (priority 15): closed_at strictly before expiry.
        expires = asset["warranty_expires_at"] if asset else None
        if expires is None:
            raise errors.ApiError(errors.ERR_WARRANTY_EXPIRED,
                                  "Asset has no warranty coverage.", 422)
        closed_at = db.parse_stored_dt(wo["closed_at"])
        if not (closed_at < db.parse_stored_dt(expires)):
            raise errors.ApiError(errors.ERR_WARRANTY_EXPIRED,
                                  "Work order closed_at is not before the asset's warranty expiry.", 422)
        # Asset not RETIRED (no dedicated error -> ERR_INVALID_STATE).
        if asset["status"] == "RETIRED":
            raise errors.invalid_state("Asset is RETIRED.")

        claimed, payable = calc.warranty_payable(claim, asset, wo)
        claim["claimed_cost_cents"] = claimed
        claim["payable_cost_cents"] = payable
        claim["status"] = "APPROVED"
        claim["decision_reason"] = decision_reason
        db.touch(claim)
        # Link the work order to this claim.
        wo["warranty_claim_id"] = claim["id"]
        db.touch(wo)
        # Reimburse the site budget (recompute keeps it consistent, PRD §3.1/§3.9).
        site = db.sites.get(asset["site_id"])
        if site is not None:
            calc.recompute_site_budget(site)
        return object_response(serialize.warranty_claim(claim), 200)


@bp.post("/warranty-claims/<cid>/deny")
def deny_claim(cid):
    _, role = authenticate()
    authorize(role, ["WarrantyAdmin"])
    body = get_json_body()
    decision_reason = opt_str(body, "decision_reason", default=None)
    with db.LOCK:
        claim = db.warranty_claims.get(cid)
        if claim is None:
            raise errors.not_found()
        if claim["status"] != "SUBMITTED":
            raise errors.invalid_state("Claim is not SUBMITTED.")
        claim["status"] = "DENIED"
        claim["payable_cost_cents"] = 0
        claim["decision_reason"] = decision_reason
        db.touch(claim)
        # Budget unchanged: the close-time charge stands. Recompute is a no-op
        # for the denied claim but keeps the site consistent if it was already
        # reflecting this work order.
        return object_response(serialize.warranty_claim(claim), 200)
