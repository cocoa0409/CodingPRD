"""RegulatoryAsset endpoints (PRD 3.7): proposal, Controller decision with SoD."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES
from middleware import authorized
from response import success_object
from services.core import new_record, touch, serialize_reg_asset
from validate import (
    get_body, req_str, req_int, opt_body_ref, require_path_resource,
)
from routes.helpers import list_response, get_one

bp = Blueprint("regulatory_assets", __name__)


@bp.route("/ucp/regulatory-assets", methods=["POST"])
def create_reg_asset():
    caller = authorized(["RateAnalyst"])
    body = get_body()
    # Priority 3 — optional body FK existence.
    source_wo = opt_body_ref(body, "source_work_order_id", "work_orders")
    # Priority 4 — shape.
    description = req_str(body, "description")
    original_cents = req_int(body, "original_cents", positive=True)
    amortization_months = req_int(body, "amortization_months", minimum=1)

    rec = new_record()
    rec.update({
        "description": description,
        "source_work_order_id": source_wo["id"] if source_wo is not None else None,
        "original_cents": original_cents,
        "amortization_months": amortization_months,
        "status": "PROPOSED",
        "proposed_by_user_id": caller.user_id,
        "approved_by_user_id": None,
    })
    db["regulatory_assets"][rec["id"]] = rec
    return success_object(serialize_reg_asset(rec), status=201)


@bp.route("/ucp/regulatory-assets/<reg_asset_id>", methods=["GET"])
def get_reg_asset(reg_asset_id):
    return get_one("regulatory_assets", serialize_reg_asset, reg_asset_id)


@bp.route("/ucp/regulatory-assets", methods=["GET"])
def list_reg_assets():
    filters = {
        "source_work_order_id": request.args.get("source_work_order_id"),
        "status": request.args.get("status"),
    }
    return list_response("regulatory_assets", serialize_reg_asset, filters)


def _decide(reg_asset_id, approve: bool):
    caller = authorized(["Controller"])
    asset = require_path_resource("regulatory_assets", reg_asset_id)
    # Priority 7 — from-state.
    if asset["status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE, f"regulatory asset is {asset['status']}")
    # Priority 8 — the decider is never the proposer.
    if caller.user_id == asset["proposed_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "decider must differ from proposer")
    if approve:
        asset["status"] = "APPROVED"
        asset["approved_by_user_id"] = caller.user_id
    else:
        asset["status"] = "REJECTED"
    touch(asset)
    return success_object(serialize_reg_asset(asset))


@bp.route("/ucp/regulatory-assets/<reg_asset_id>/approve", methods=["POST"])
def approve_reg_asset(reg_asset_id):
    return _decide(reg_asset_id, approve=True)


@bp.route("/ucp/regulatory-assets/<reg_asset_id>/reject", methods=["POST"])
def reject_reg_asset(reg_asset_id):
    return _decide(reg_asset_id, approve=False)
