"""Disposal record endpoints (PRD 3.9): used-media manifests, hazard obligations,
monthly hazard-mass threshold. Append-only events."""
from decimal import Decimal

from flask import Blueprint

from errors import (
    raise_error, ERR_HAZARD_DISPOSAL_METHOD_REQUIRED, ERR_INVALID_REQUEST,
    ERR_MANIFEST_FIELDS_REQUIRED, ERR_REGULATOR_REPORT_REQUIRED,
)
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.calc import HAZARD_MONTH_THRESHOLD_KG, hazard_month_mass
from services.core import new_record, serialize
from util import parse_date, round2
from validate import (
    get_body, opt_str, req_date, req_decimal, req_enum, req_int, req_str,
    require_fk,
)

bp = Blueprint("disposal_records", __name__)

DISPOSAL_METHODS = {"RECYCLING", "INCINERATION", "LANDFILL", "HAZARDOUS_WASTE_FACILITY"}


@bp.post("/api/disposal-records")
def create_disposal_record():
    authorized(["EHSOfficer"])
    # Priority 3: request shape.
    body = get_body()
    customer_ref = req_str(body, "customer_ref")
    product_id = req_str(body, "product_id")
    qty_disposed = req_int(body, "qty_disposed", min_value=1)
    weight = req_decimal(body, "gross_weight_kg", gt=Decimal("0"))
    weight = round2(weight)
    method = req_enum(body, "disposal_method", DISPOSAL_METHODS)
    disposed_at = req_date(body, "disposed_at")
    lot_id = opt_str(body, "lot_id", default=None)
    manifest_number = opt_str(body, "manifest_number", default=None)
    certified_facility_ref = opt_str(body, "certified_facility_ref", default=None)
    regulator_report_ref = opt_str(body, "regulator_report_ref", default=None)
    # Priority 4: product FK, then optional lot FK; lot-product mismatch is 400.
    product = require_fk("products", product_id, "product")
    if lot_id is not None:
        lot = require_fk("lots", lot_id, "lot")
        if lot["product_id"] != product_id:
            raise_error(ERR_INVALID_REQUEST, "lot does not belong to the referenced product")
    # Priority 7: escalating hazard obligations, in order.
    if product["used_media_hazard_class"] != "NONE":
        if method != "HAZARDOUS_WASTE_FACILITY":
            raise_error(
                ERR_HAZARD_DISPOSAL_METHOD_REQUIRED,
                "hazard-class media must be disposed via HAZARDOUS_WASTE_FACILITY",
            )
        if manifest_number is None or certified_facility_ref is None:
            raise_error(
                ERR_MANIFEST_FIELDS_REQUIRED,
                "hazard-class disposal requires manifest_number and certified_facility_ref",
            )
        month_mass = hazard_month_mass(customer_ref, parse_date(disposed_at), weight)
        if month_mass >= HAZARD_MONTH_THRESHOLD_KG and regulator_report_ref is None:
            raise_error(
                ERR_REGULATOR_REPORT_REQUIRED,
                "calendar-month hazard mass >= 1000.00 kg requires regulator_report_ref",
            )
    rec = new_record("disposal_records", {
        "customer_ref": customer_ref,
        "product_id": product_id,
        "lot_id": lot_id,
        "qty_disposed": qty_disposed,
        "gross_weight_kg": weight,
        "disposal_method": method,
        "manifest_number": manifest_number,
        "certified_facility_ref": certified_facility_ref,
        "regulator_report_ref": regulator_report_ref,
        "disposed_at": disposed_at,
    }, common_fields=False)  # append-only event: id + created_at only
    return success_object(serialize(rec), status=201)


@bp.get("/api/disposal-records/<rid>")
def get_disposal_record(rid):
    return get_one("disposal_records", rid, "disposal record")


@bp.get("/api/disposal-records")
def list_disposal_records():
    return list_response("disposal_records", {
        "product_id": arg("product_id"),
        "lot_id": arg("lot_id"),
    })
