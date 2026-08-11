"""The device catalog (PRD 3.3) -- a configuration entity with no version."""

from flask import Blueprint

import serializers as S
from envelope import created, ok
from ladder import (bad_request, begin, req_bool, req_enum, req_int, req_str,
                    resolve)
from store import db, new_row

bp = Blueprint("catalog", __name__)
PREFIX = "/smart-home-support"

CATALOG_READ_ROLES = ("PlatformAdmin", "SupportAgent", "Owner", "BillingAdmin")


@bp.post(PREFIX + "/device-catalog")
def create_catalog_entry():
    ctx = begin(("PlatformAdmin",))
    body = ctx.body
    model_code = req_str(body, "model_code", 1, 40)
    display_name = req_str(body, "display_name", 1)
    device_class = req_enum(body, "device_class")
    serial_prefix = req_str(body, "serial_prefix", 2, 8)
    if not serial_prefix.isalnum() or serial_prefix != serial_prefix.upper():
        bad_request("serial_prefix must be 2-8 uppercase alphanumeric characters.")
    for existing in db.device_catalog.values():
        if existing["model_code"] == model_code:
            bad_request("model_code must be unique across all catalog rows.")

    row = new_row(versioned=False)
    row.update({
        "model_code": model_code,
        "display_name": display_name,
        "device_class": device_class,
        "serial_prefix": serial_prefix,
        "base_warranty_months": req_int(body, "base_warranty_months", 0),
        "requires_install": req_bool(body, "requires_install"),
        "manufacturer_service_only": req_bool(body, "manufacturer_service_only"),
        "msrp_cents": req_int(body, "msrp_cents", 0),
        "current_firmware_version": req_str(body, "current_firmware_version", 1),
    })
    db.device_catalog[row["id"]] = row
    return created(S.device_catalog_entry(row))


@bp.get(PREFIX + "/device-catalog/<cid>")
def read_catalog_entry(cid):
    begin(CATALOG_READ_ROLES)
    found = resolve(catalog=cid)
    return ok(S.device_catalog_entry(found["catalog"]))
