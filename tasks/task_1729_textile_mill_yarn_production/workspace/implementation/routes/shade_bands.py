"""ShadeBand endpoints."""

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import err_not_found
from middleware import require_roles
from response import success_list, success_object
from serializers import serialize_shade_band
from validators import (
    apply_filters,
    get_json_body,
    get_pagination,
    req_decimal,
    req_string,
    round3,
    sort_and_paginate,
)

bp = Blueprint("shade_bands", __name__)

ROLES = ("CustomerServiceRep", "DyeHouseOperator", "QualityInspector")


@bp.post("/mill/shade-bands")
def create_shade_band():
    require_roles("CustomerServiceRep")
    body = get_json_body()
    customer_code = req_string(body, "customer_code")
    color_code = req_string(body, "color_code")
    centroid_l = req_decimal(body, "centroid_l")
    centroid_a = req_decimal(body, "centroid_a")
    centroid_b = req_decimal(body, "centroid_b")
    tolerance = req_decimal(body, "delta_e_tolerance", min_value=0, min_exclusive=True)
    ts = now_iso()
    record = {
        "id": new_id(),
        "customer_code": customer_code,
        "color_code": color_code,
        "centroid_l": centroid_l,
        "centroid_a": centroid_a,
        "centroid_b": centroid_b,
        "delta_e_tolerance": round3(tolerance),
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.shade_bands[record["id"]] = record
    return success_object(serialize_shade_band(record), 201)


@bp.get("/mill/shade-bands")
def list_shade_bands():
    require_roles(*ROLES)
    limit, offset = get_pagination()
    items = apply_filters(
        list(db.shade_bands.values()),
        {
            "customer_code": request.args.get("customer_code"),
            "color_code": request.args.get("color_code"),
            "status": request.args.get("status"),
        },
    )
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([serialize_shade_band(r) for r in page], limit, offset, total)


@bp.get("/mill/shade-bands/<sid>")
def get_shade_band(sid):
    require_roles(*ROLES)
    record = db.shade_bands.get(sid)
    if record is None:
        raise err_not_found("Shade band not found")
    return success_object(serialize_shade_band(record))
