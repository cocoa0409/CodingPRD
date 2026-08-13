"""WalkthroughReport endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import *
from db import store
from services.helpers import (
    require_fields, require_str, require_int, require_enum,
    optional_int, optional_bool,
    make_entity, touch, get_production, get_location, get_scoped,
    list_filtered, paginate, get_pagination_params,
)

bp = Blueprint("walkthroughs", __name__)


@bp.route("/productions/<pid>/walkthrough-reports", methods=["POST"])
def create_walkthrough(pid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["location_id", "kind"])
    loc_id = require_str(payload, "location_id")
    get_location(loc_id)
    kind = require_enum(payload, "kind", ["PRE", "POST"])
    entity = make_entity({
        "production_id": pid,
        "location_id": loc_id,
        "kind": kind,
        "damage_item_count": optional_int(payload, "damage_item_count", 0),
        "damage_claim_cents": optional_int(payload, "damage_claim_cents", 0),
        "signed_by_owner": optional_bool(payload, "signed_by_owner", False),
        "signed_by_manager": optional_bool(payload, "signed_by_manager", False),
        "status": "DRAFT",
    })
    store.walkthrough_reports[entity["id"]] = entity
    return success_object(entity, 201)


@bp.route("/productions/<pid>/walkthrough-reports", methods=["GET"])
def list_walkthroughs(pid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    limit, offset = get_pagination_params(request.args)
    filters = {}
    for f in ("location_id", "kind", "status"):
        v = request.args.get(f)
        if v:
            filters[f] = v
    items = list_filtered(store.walkthrough_reports, filters, production_id=pid)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/productions/<pid>/walkthrough-reports/<rid>/sign", methods=["POST"])
def sign_walkthrough(pid, rid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    wt = get_scoped(store.walkthrough_reports, rid, pid, "WalkthroughReport")
    if wt["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError(ERR_INVALID_STATE, "WalkthroughReport must be DRAFT or DISPUTED to sign", 409)
    if not wt.get("signed_by_owner") or not wt.get("signed_by_manager"):
        raise ApiError(ERR_SIGNATURE_MISSING, "Both signature flags must be true", 422)
    if wt["kind"] == "PRE" and wt["status"] == "DRAFT":
        # Check no other SIGNED PRE for this location
        for other in store.walkthrough_reports.values():
            if (other["id"] != wt["id"]
                    and other.get("location_id") == wt["location_id"]
                    and other.get("production_id") == pid
                    and other.get("kind") == "PRE"
                    and other["status"] == "SIGNED"):
                raise ApiError(ERR_DUPLICATE_PRE_WALKTHROUGH,
                               "A SIGNED PRE walkthrough already exists for this location", 422)
    was_disputed = wt["status"] == "DISPUTED"
    wt["status"] = "SIGNED"
    touch(wt)
    # Side effects for POST sign
    if wt["kind"] == "POST":
        # Deposit account -> SETTLING
        for da in store.deposit_accounts.values():
            if (da.get("production_id") == pid
                    and da.get("location_id") == wt["location_id"]
                    and da["status"] in ("OPEN", "FUNDED")):
                da["status"] = "SETTLING"
                touch(da)
        # PRE report -> FINAL (if not already final)
        for other in store.walkthrough_reports.values():
            if (other["id"] != wt["id"]
                    and other.get("location_id") == wt["location_id"]
                    and other.get("production_id") == pid
                    and other.get("kind") == "PRE"
                    and other["status"] == "SIGNED"):
                other["status"] = "FINAL"
                touch(other)
    return success_object(wt)


@bp.route("/productions/<pid>/walkthrough-reports/<rid>/dispute", methods=["POST"])
def dispute_walkthrough(pid, rid):
    user_id, role = require_role("OwnerRep")
    p = get_production(pid)
    wt = get_scoped(store.walkthrough_reports, rid, pid, "WalkthroughReport")
    if wt["kind"] != "POST":
        raise ApiError(ERR_INVALID_STATE, "Only POST walkthroughs can be disputed", 409)
    if wt["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "WalkthroughReport must be DRAFT to dispute", 409)
    wt["status"] = "DISPUTED"
    touch(wt)
    # Deposit account -> SETTLING
    for da in store.deposit_accounts.values():
        if (da.get("production_id") == pid
                and da.get("location_id") == wt["location_id"]
                and da["status"] in ("OPEN", "FUNDED")):
            da["status"] = "SETTLING"
            touch(da)
    return success_object(wt)
