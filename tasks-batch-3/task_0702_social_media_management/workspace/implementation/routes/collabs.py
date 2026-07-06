"""Influencer collaboration + UGC asset routes (PRD §3.6)."""
from flask import Blueprint, request

import db
import response
from errors import (
    err, ERR_INVALID_STATE, ERR_DELIVERABLES_NOT_MET,
)
from middleware import (
    get_user_context, require_role, get_json_body, get_pagination,
    require_string, require_positive_int, require_min_int,
)
from services import lookup, listing, calc
from services.serialize import collab_out, ugc_out

bp = Blueprint("collabs", __name__)


def _recount_cleared(collab_id):
    return sum(
        1 for a in db.ugc_assets.values()
        if a["collab_id"] == collab_id and a["status"] == "RIGHTS_CLEARED"
    )


# ---------------- Influencer collabs ----------------

@bp.post("/influencer-collabs")
def create_collab():
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    body = get_json_body()
    client_id = require_string(body, "client_id")
    with db.LOCK:
        lookup.get_client(client_id)
        influencer_handle = require_string(body, "influencer_handle")
        offer_fee_cents = require_positive_int(body, "offer_fee_cents")
        deliverable_count = require_min_int(body, "deliverable_count", 1)
        c = {
            "id": db.new_id(),
            "client_id": client_id,
            "influencer_handle": influencer_handle,
            "offer_fee_cents": offer_fee_cents,
            "deliverable_count": deliverable_count,
            "status": "PROPOSED",
            "negotiation_round": 0,
            "approved_asset_count": 0,
        }
        db.stamp_create(c, full=True)
        db.influencer_collabs[c["id"]] = c
        return response.created(collab_out(c))


@bp.get("/influencer-collabs")
def list_collabs():
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin", "FinanceController"})
    limit, offset = get_pagination()
    with db.LOCK:
        rows = listing.apply_filters(list(db.influencer_collabs.values()), {
            "client_id": request.args.get("client_id"),
            "status": request.args.get("status"),
        })
        rows = listing.sort_by_created(rows)
        window, total = listing.paginate(rows, limit, offset)
        return response.list_ok([collab_out(c) for c in window], limit, offset, total)


@bp.get("/influencer-collabs/<collab_id>")
def get_collab(collab_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin", "FinanceController"})
    with db.LOCK:
        c = lookup.get_collab(collab_id)
        return response.ok(collab_out(c))


@bp.post("/influencer-collabs/<collab_id>/counter")
def counter_collab(collab_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    body = get_json_body()
    with db.LOCK:
        c = lookup.get_collab(collab_id)
        if c["status"] not in ("PROPOSED", "COUNTERED"):
            raise err(ERR_INVALID_STATE, "Collab cannot be countered from its current state")
        counter_fee = require_positive_int(body, "counter_fee_cents")
        c["status"] = "COUNTERED"
        c["offer_fee_cents"] = counter_fee
        c["negotiation_round"] += 1
        db.touch(c)
        return response.ok(collab_out(c))


@bp.post("/influencer-collabs/<collab_id>/accept")
def accept_collab(collab_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    with db.LOCK:
        c = lookup.get_collab(collab_id)
        if c["status"] not in ("PROPOSED", "COUNTERED"):
            raise err(ERR_INVALID_STATE, "Collab cannot be accepted from its current state")
        c["status"] = "ACCEPTED"
        db.touch(c)
        return response.ok(collab_out(c))


@bp.post("/influencer-collabs/<collab_id>/mark-delivered")
def mark_delivered(collab_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    with db.LOCK:
        c = lookup.get_collab(collab_id)
        if c["status"] != "ACCEPTED":
            raise err(ERR_INVALID_STATE, "Collab must be ACCEPTED to mark delivered")
        if c["approved_asset_count"] < c["deliverable_count"]:
            raise err(ERR_DELIVERABLES_NOT_MET,
                      "approved_asset_count is below deliverable_count")
        c["status"] = "DELIVERED"
        db.touch(c)
        return response.ok(collab_out(c))


@bp.post("/influencer-collabs/<collab_id>/close")
def close_collab(collab_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    with db.LOCK:
        c = lookup.get_collab(collab_id)
        if c["status"] != "DELIVERED":
            raise err(ERR_INVALID_STATE, "Collab must be DELIVERED to close")
        c["status"] = "CLOSED"
        db.touch(c)
        return response.ok(collab_out(c))


@bp.post("/influencer-collabs/<collab_id>/cancel")
def cancel_collab(collab_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    with db.LOCK:
        c = lookup.get_collab(collab_id)
        if c["status"] not in ("PROPOSED", "COUNTERED", "ACCEPTED"):
            raise err(ERR_INVALID_STATE, "Collab cannot be cancelled from its current state")
        c["status"] = "CANCELLED"
        db.touch(c)
        # cascade: SUBMITTED assets -> REJECTED
        for a in db.ugc_assets.values():
            if a["collab_id"] == collab_id and a["status"] == "SUBMITTED":
                a["status"] = "REJECTED"
                db.touch(a)
        return response.ok(collab_out(c))


@bp.get("/influencer-collabs/<collab_id>/settlement-quote")
def settlement_quote(collab_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin", "FinanceController"})
    with db.LOCK:
        c = lookup.get_collab(collab_id)
        amount = calc.collab_settlement_amount_cents(
            c["offer_fee_cents"], c["deliverable_count"], c["approved_asset_count"]
        )
        return response.ok({"settlement_amount_cents": amount})


# ---------------- UGC assets ----------------

@bp.post("/ugc-assets")
def create_ugc_asset():
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    body = get_json_body()
    collab_id = require_string(body, "collab_id")
    with db.LOCK:
        lookup.get_collab(collab_id)
        asset_url = require_string(body, "asset_url")
        a = {
            "id": db.new_id(),
            "collab_id": collab_id,
            "asset_url": asset_url,
            "status": "SUBMITTED",
        }
        db.stamp_create(a, full=True)
        db.ugc_assets[a["id"]] = a
        return response.created(ugc_out(a))


@bp.get("/ugc-assets")
def list_ugc_assets():
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin"})
    limit, offset = get_pagination()
    with db.LOCK:
        rows = listing.apply_filters(list(db.ugc_assets.values()), {
            "collab_id": request.args.get("collab_id"),
            "status": request.args.get("status"),
        })
        rows = listing.sort_by_created(rows)
        window, total = listing.paginate(rows, limit, offset)
        return response.list_ok([ugc_out(a) for a in window], limit, offset, total)


@bp.get("/ugc-assets/<asset_id>")
def get_ugc_asset(asset_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin"})
    with db.LOCK:
        a = lookup.get_asset(asset_id)
        return response.ok(ugc_out(a))


@bp.post("/ugc-assets/<asset_id>/clear-rights")
def clear_rights(asset_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    with db.LOCK:
        a = lookup.get_asset(asset_id)
        if a["status"] != "SUBMITTED":
            raise err(ERR_INVALID_STATE, "Asset must be SUBMITTED to clear rights")
        collab = lookup.get_collab(a["collab_id"])
        if collab["status"] not in ("ACCEPTED", "DELIVERED"):
            raise err(ERR_INVALID_STATE,
                      "Parent collab must be ACCEPTED or DELIVERED to clear rights")
        a["status"] = "RIGHTS_CLEARED"
        db.touch(a)
        collab["approved_asset_count"] = _recount_cleared(collab["id"])
        db.touch(collab)
        return response.ok(ugc_out(a))


@bp.post("/ugc-assets/<asset_id>/reject")
def reject_asset(asset_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    with db.LOCK:
        a = lookup.get_asset(asset_id)
        if a["status"] != "SUBMITTED":
            raise err(ERR_INVALID_STATE, "Asset must be SUBMITTED to reject")
        a["status"] = "REJECTED"
        db.touch(a)
        return response.ok(ugc_out(a))
