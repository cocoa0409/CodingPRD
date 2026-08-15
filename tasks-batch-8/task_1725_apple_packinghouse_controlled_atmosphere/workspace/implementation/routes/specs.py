"""Packaging spec endpoints (PRD 3.4): creation supersedes the prior ACTIVE spec."""
from flask import Blueprint

from db import db
from middleware import authorized, ALL_ROLES
from response import success_object
from routes.helpers import public
from services.core import new_record, touch
from validate import get_body, req_enum, req_int, req_str, require_path_resource

bp = Blueprint("specs", __name__)

GRADE_CLASSES = {"EXTRA_FANCY", "FANCY", "UTILITY"}
SIZE_CLASSES = {"SMALL", "MEDIUM", "LARGE"}
PACK_STYLES = {"TRAY", "BAG", "POUCH"}


@bp.post("/specs")
def create_spec():
    authorized(["Admin", "PoolManager"])
    body = get_body()
    customer_name = req_str(body, "customer_name")
    label_code = req_str(body, "label_code")
    grade_min = req_enum(body, "grade_min", GRADE_CLASSES)
    color_min_pct = req_int(body, "color_min_pct", minimum=0, maximum=100)
    size_class = req_enum(body, "size_class", SIZE_CLASSES)
    pack_style = req_enum(body, "pack_style", PACK_STYLES)
    # Versioned by replacement: the prior ACTIVE spec in the same
    # (customer_name, size_class, pack_style) scope becomes SUPERSEDED.
    for s in db["specs"].values():
        if (s["status"] == "ACTIVE"
                and s["customer_name"] == customer_name
                and s["size_class"] == size_class
                and s["pack_style"] == pack_style):
            s["status"] = "SUPERSEDED"
            touch(s)
    rec = new_record("specs", {
        "customer_name": customer_name,
        "label_code": label_code,
        "grade_min": grade_min,
        "color_min_pct": color_min_pct,
        "size_class": size_class,
        "pack_style": pack_style,
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/specs/<specId>")
def get_spec(specId):
    authorized(list(ALL_ROLES))
    spec = require_path_resource("specs", specId)
    return success_object(public(spec))
