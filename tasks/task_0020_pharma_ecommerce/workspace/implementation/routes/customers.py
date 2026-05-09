"""Customers — create, get, patch."""

from __future__ import annotations

from flask import Blueprint, g, request

from db import db, serialize, stamp_create, stamp_update
from errors import err
from lookups import get_customer, get_platform
from middleware import require_roles
from response import success_object
from validate import (
    occ_check,
    optional_field,
    require_field,
    require_json,
    require_str_array,
)

bp = Blueprint("customers", __name__)

ALLOWED_FLAGS = {"PREGNANCY", "MINOR", "RENAL_FAILURE", "GERIATRIC"}


def _validate_flags(flags: list[str]) -> list[str]:
    for f in flags:
        if f not in ALLOWED_FLAGS:
            raise err("ERR_INVALID_REQUEST", f"Unknown special_population_flag: {f}")
    return flags


@bp.post("/pharma-platforms/<pid>/customers")
@require_roles("PlatformAdmin")
def create_customer(pid: str):
    platform = get_platform(pid)
    body = require_json(request.get_json(silent=True))
    real_name = require_field(body, "real_name", kind=str)
    id_doc = require_field(body, "id_document_no", kind=str)
    flags = _validate_flags(require_str_array(body, "special_population_flags", allow_empty=True))
    real_name_verified = optional_field(body, "real_name_verified", kind=bool, default=False)
    row = {
        "platform_id": pid,
        "real_name": real_name,
        "id_document_no": id_doc,
        "special_population_flags": flags,
        "real_name_verified": bool(real_name_verified),
    }
    stamp_create(row, platform)
    db.customers[row["id"]] = row
    return success_object(serialize(row)), 201


@bp.get("/pharma-platforms/<pid>/customers/<customer_id>")
@require_roles("PlatformAdmin", "Customer")
def get_customer_route(pid: str, customer_id: str):
    _, c = get_customer(pid, customer_id)
    if g.user_role == "Customer" and g.user_id != c["id"]:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "Customer can only view their own record.")
    return success_object(serialize(c)), 200


@bp.patch("/pharma-platforms/<pid>/customers/<customer_id>")
@require_roles("PlatformAdmin")
def patch_customer(pid: str, customer_id: str):
    platform, c = get_customer(pid, customer_id)
    body = require_json(request.get_json(silent=True))
    occ_check(body, c)
    changed = False
    if "special_population_flags" in body and body["special_population_flags"] is not None:
        if not isinstance(body["special_population_flags"], list):
            raise err("ERR_INVALID_REQUEST", "special_population_flags must be array.")
        flags = _validate_flags([str(f) for f in body["special_population_flags"]])
        c["special_population_flags"] = flags
        changed = True
    if "real_name_verified" in body and body["real_name_verified"] is not None:
        if not isinstance(body["real_name_verified"], bool):
            raise err("ERR_INVALID_REQUEST", "real_name_verified must be bool.")
        c["real_name_verified"] = body["real_name_verified"]
        changed = True
    if changed:
        stamp_update(c, platform)
    return success_object(serialize(c)), 200
