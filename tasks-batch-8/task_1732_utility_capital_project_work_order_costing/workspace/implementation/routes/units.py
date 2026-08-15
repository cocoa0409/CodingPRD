"""FixedAssetUnit endpoints (PRD 3.8): listing and retirement."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_UNIT_ALREADY_RETIRED, ERR_RETIREMENT_PERIOD_NOT_OPEN
from middleware import authorized
from response import success_object
from services.core import new_record, touch, serialize_unit, current_open_period
from util import parse_date
from validate import get_body, req_date, require_path_resource
from routes.helpers import list_response, get_one

bp = Blueprint("fixed_asset_units", __name__)


@bp.route("/ucp/fixed-asset-units/<unit_id>", methods=["GET"])
def get_unit(unit_id):
    return get_one("fixed_asset_units", serialize_unit, unit_id)


@bp.route("/ucp/fixed-asset-units", methods=["GET"])
def list_units():
    filters = {
        "work_order_id": request.args.get("work_order_id"),
        "unit_catalog_id": request.args.get("unit_catalog_id"),
        "status": request.args.get("status"),
    }
    # Units additionally break created_at ties by line_no ascending (PRD 2.3).
    return list_response(
        "fixed_asset_units", serialize_unit, filters,
        sort_key=lambda r: (r["created_at"], r["line_no"], r["_seq"]),
    )


@bp.route("/ucp/fixed-asset-units/<unit_id>/retire", methods=["POST"])
def retire_unit(unit_id):
    authorized(["Controller"])
    unit = require_path_resource("fixed_asset_units", unit_id)
    body = get_body()
    retirement_date = req_date(body, "retirement_date")
    # Priority 7 — already retired.
    if unit["status"] == "RETIRED":
        raise_error(ERR_UNIT_ALREADY_RETIRED, "unit is already RETIRED")
    # Priority 9 — the retirement date must fall inside the single
    # OPEN/REOPENED period; that period's close posts the final half-month entry.
    d = parse_date(retirement_date)
    period = current_open_period()
    if period is None or not (period["_start"] <= d <= period["_end"]):
        raise_error(ERR_RETIREMENT_PERIOD_NOT_OPEN, "retirement_date is not inside the current OPEN or REOPENED period")
    unit["status"] = "RETIRED"
    unit["retirement_period_id"] = period["id"]
    touch(unit)
    return success_object(serialize_unit(unit))
