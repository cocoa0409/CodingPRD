"""UnitCatalog endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_VALIDATION
from middleware import authorized
from response import success_object
from services.core import new_record, serialize_catalog
from validate import get_body, req_enum, req_int, req_num
from routes.helpers import list_response, get_one

bp = Blueprint("unit_catalog", __name__)

ASSET_CLASSES = ["POLE", "TRANSFORMER", "CONDUCTOR", "METER", "REGULATOR"]


@bp.route("/ucp/unit-catalog", methods=["POST"])
def create_catalog_entry():
    authorized(["SystemAdmin"])
    body = get_body()
    asset_class = req_enum(body, "asset_class", ASSET_CLASSES)
    standard_cost_cents = req_int(body, "standard_cost_cents", non_negative=True)
    rate = req_num(body, "annual_depreciation_rate_pct", positive=True)
    for c in db["unit_catalog"].values():
        if c["asset_class"] == asset_class:
            raise_error(ERR_VALIDATION, f"duplicate asset_class: {asset_class}")

    rec = new_record()
    rec.update({
        "asset_class": asset_class,
        "standard_cost_cents": standard_cost_cents,
        "annual_depreciation_rate_pct": rate,
    })
    db["unit_catalog"][rec["id"]] = rec
    return success_object(serialize_catalog(rec), status=201)


@bp.route("/ucp/unit-catalog/<catalog_id>", methods=["GET"])
def get_catalog_entry(catalog_id):
    return get_one("unit_catalog", serialize_catalog, catalog_id)


@bp.route("/ucp/unit-catalog", methods=["GET"])
def list_catalog():
    filters = {"asset_class": request.args.get("asset_class")}
    return list_response("unit_catalog", serialize_catalog, filters)
