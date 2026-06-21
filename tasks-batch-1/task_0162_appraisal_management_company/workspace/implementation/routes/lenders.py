"""Lender endpoints."""
from flask import Blueprint

import db
import errors
import middleware
import response
from services import domain, serialize, validate

bp = Blueprint("lenders", __name__)


@bp.route("/amc/lenders", methods=["POST"])
def create_lender():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin"})
    data = validate.body()

    name = validate.require_str(data, "name")
    budget = validate.require_int(data, "monthly_fee_budget_cents")
    if budget < 0:
        raise errors.invalid_request("monthly_fee_budget_cents must be >= 0.")

    panel = data.get("approved_panel_appraiser_ids")
    if panel is None:
        panel = []
    if not isinstance(panel, list) or not all(isinstance(x, str) for x in panel):
        raise errors.invalid_request("approved_panel_appraiser_ids must be a list of strings.")

    lender = {
        "name": name,
        "approved_panel_appraiser_ids": list(panel),
        "monthly_fee_budget_cents": budget,
        "committed_fee_cents": 0,
    }
    db.stamp_create(lender)
    db.lenders[lender["id"]] = lender
    return response.ok_object(serialize.public(lender), 201)


@bp.route("/amc/lenders/<lid>", methods=["GET"])
def get_lender(lid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin", "LenderUser"})
    lender = db.lenders.get(lid)
    if lender is None:
        raise errors.not_found("Lender not found.")
    domain.recompute_committed_fee(lender)
    return response.ok_object(serialize.public(lender), 200)


@bp.route("/amc/lenders/<lid>/panel", methods=["PATCH"])
def set_panel(lid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin"})
    lender = db.lenders.get(lid)
    if lender is None:
        raise errors.not_found("Lender not found.")
    data = validate.body()
    panel = validate.require(data, "approved_panel_appraiser_ids")
    if not isinstance(panel, list) or not all(isinstance(x, str) for x in panel):
        raise errors.invalid_request("approved_panel_appraiser_ids must be a list of strings.")
    lender["approved_panel_appraiser_ids"] = list(panel)
    db.touch(lender)
    return response.ok_object(serialize.public(lender), 200)
