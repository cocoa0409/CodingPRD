"""Device catalog endpoints (ClinicAdmin-owned)."""

from flask import Blueprint, request

from db import db
import serialize
import validate
import errors
from middleware import require_auth, require_role, get_json_body
from response import object_response, array_response
from services.domain import get_or_404
from services.listing import list_page

bp = Blueprint("device_models", __name__)

SEVERITY_CHOICES = {"MILD", "MODERATE", "SEVERE", "PROFOUND"}
MODEL_STATUS_CHOICES = {"ACTIVE", "DISCONTINUED"}


@bp.post("/clinic/device-models")
def create_device_model():
    auth = require_auth()
    require_role(auth, {"ClinicAdmin"})
    body = get_json_body()
    model_code = validate.require_str(body, "model_code")
    name = validate.require_str(body, "name")
    list_price = validate.require_int(body, "list_price_cents", minimum=1)
    restock_fee = validate.require_int(body, "restock_fee_cents", minimum=0)
    min_severity = validate.require_enum(body, "min_severity", SEVERITY_CHOICES)
    firmware_version = validate.require_str(body, "firmware_version")
    warranty_months = validate.require_int(body, "warranty_months", minimum=1)

    with db.lock:
        # model_code must be globally unique among non-DISCONTINUED models.
        for m in db.device_models.values():
            if m["model_code"] == model_code and m["status"] != "DISCONTINUED":
                raise errors.ApiError(errors.ERR_DUPLICATE_MODEL_CODE, 409,
                                      "model_code already used by a non-discontinued model.")
        obj = {
            "model_code": model_code,
            "name": name,
            "list_price_cents": list_price,
            "restock_fee_cents": restock_fee,
            "min_severity": min_severity,
            "firmware_version": firmware_version,
            "warranty_months": warranty_months,
            "status": "ACTIVE",
        }
        db.stamp_create(obj)
        db.device_models[obj["id"]] = obj
    return object_response(serialize.device_model(obj), 201)


@bp.get("/clinic/device-models/<mid>")
def get_device_model(mid):
    auth = require_auth()
    require_role(auth, {"ClinicAdmin", "BillingClerk", "Audiologist"})
    obj = get_or_404(db.device_models, mid)
    return object_response(serialize.device_model(obj))


@bp.get("/clinic/device-models")
def list_device_models():
    auth = require_auth()
    require_role(auth, {"ClinicAdmin", "BillingClerk", "Audiologist"})
    status = request.args.get("status")
    min_severity = request.args.get("min_severity")
    items = [m for m in db.device_models.values()
             if (status is None or m["status"] == status)
             and (min_severity is None or m["min_severity"] == min_severity)]
    page, limit, offset, total = list_page(request.args, items, serialize.device_model)
    return array_response(page, limit, offset, total)


@bp.patch("/clinic/device-models/<mid>")
def edit_device_model(mid):
    auth = require_auth()
    require_role(auth, {"ClinicAdmin"})
    obj = get_or_404(db.device_models, mid)
    body = get_json_body()

    # Validate any provided fields; absent fields are left unchanged.
    new_firmware = None
    new_price = None
    new_status = None
    if "firmware_version" in body and body["firmware_version"] is not None:
        new_firmware = validate.require_str(body, "firmware_version")
    if "list_price_cents" in body and body["list_price_cents"] is not None:
        new_price = validate.require_int(body, "list_price_cents", minimum=1)
    if "status" in body and body["status"] is not None:
        new_status = validate.require_enum(body, "status", MODEL_STATUS_CHOICES)

    with db.lock:
        if new_firmware is not None:
            obj["firmware_version"] = new_firmware
        if new_price is not None:
            obj["list_price_cents"] = new_price
        if new_status is not None:
            obj["status"] = new_status
        db.touch(obj)
    return object_response(serialize.device_model(obj))
