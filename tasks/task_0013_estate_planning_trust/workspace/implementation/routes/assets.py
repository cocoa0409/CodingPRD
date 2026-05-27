"""Asset routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from common import (
    get_body,
    optional_string,
    pagination_params,
    require_enum,
    require_int,
    require_string,
    stamp_common_fields,
    touch,
)
from errors import invalid_state, not_found
from middleware import require_roles
from response import created, list_response, success
from services.calculations import recompute_and_store_gross, recompute_and_store_net
from views import view_asset


bp = Blueprint("assets", __name__)

CATEGORIES = {
    "REAL_ESTATE",
    "BROKERAGE",
    "BANK_ACCOUNT",
    "RETIREMENT_IRA",
    "LIFE_INSURANCE",
    "PERSONAL_PROPERTY",
    "BUSINESS_INTEREST",
}


@bp.post("/assets")
@require_roles("EstatePlanner")
def create_asset():
    body = get_body()
    estate_id = require_string(body, "estate_id")
    if estate_id not in db.estates:
        raise not_found("Estate")

    category = require_enum(body, "category", CATEGORIES)
    description = require_string(body, "description")
    appraised = require_int(body, "appraised_value_cents", min_value=0)
    designation_id = optional_string(body, "beneficiary_designation_id")
    if designation_id is not None and designation_id not in db.beneficiary_designations:
        raise not_found("BeneficiaryDesignation")

    now = db.now_utc()
    asset = {
        "estate_id": estate_id,
        "category": category,
        "description": description,
        "appraised_value_cents": appraised,
        "status": "DRAFT",
        "beneficiary_designation_id": designation_id,
    }
    stamp_common_fields(asset, now)
    db.assets[asset["id"]] = asset
    return created(view_asset(asset))


@bp.get("/assets/<asset_id>")
@require_roles("EstatePlanner", "Executor", "Judge")
def get_asset(asset_id: str):
    a = db.assets.get(asset_id)
    if a is None:
        raise not_found("Asset")
    return success(view_asset(a))


@bp.get("/assets")
@require_roles("EstatePlanner", "Executor", "Judge")
def list_assets():
    limit, offset = pagination_params()
    estate_id = request.args.get("estate_id")
    status = request.args.get("status")
    designation_id = request.args.get("beneficiary_designation_id")

    items = list(db.assets.values())
    if estate_id is not None:
        items = [a for a in items if a["estate_id"] == estate_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if designation_id is not None:
        items = [a for a in items if a.get("beneficiary_designation_id") == designation_id]

    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = [view_asset(a) for a in items[offset:offset + limit]]
    return list_response(page, limit=limit, offset=offset, total_count=total)


@bp.patch("/assets/<asset_id>")
@require_roles("EstatePlanner", "Executor")
def update_asset(asset_id: str):
    a = db.assets.get(asset_id)
    if a is None:
        raise not_found("Asset")
    body = get_body()
    new_val = require_int(body, "appraised_value_cents", min_value=0)
    now = db.now_utc()
    a["appraised_value_cents"] = new_val
    touch(a, now)

    estate = db.estates.get(a["estate_id"])
    if estate is not None and a["status"] == "INCLUDED":
        # PRD §3.9: re-appraisals only affect provisional variant.
        recompute_and_store_gross(estate)
        recompute_and_store_net(estate)
        touch(estate, now)
    return success(view_asset(a))


@bp.post("/assets/<asset_id>/liquidate")
@require_roles("Executor")
def liquidate_asset(asset_id: str):
    a = db.assets.get(asset_id)
    if a is None:
        raise not_found("Asset")
    if a["status"] != "INCLUDED":
        raise invalid_state("Asset must be INCLUDED to liquidate.")

    estate = db.estates.get(a["estate_id"])
    if estate is None:
        raise not_found("Estate")

    # Ownership: caller must be the estate's confirmed executor.
    from flask import g
    if estate.get("executor_user_id") != g.user_id:
        from errors import forbidden
        raise forbidden("Only the estate's executor may liquidate assets.")

    now = db.now_utc()
    a["status"] = "LIQUIDATED"
    touch(a, now)
    recompute_and_store_gross(estate)
    recompute_and_store_net(estate)
    touch(estate, now)
    return success(view_asset(a))
