"""Assessor registry, scanning-vendor registry and the logical clock."""

from flask import Blueprint

import middleware as mw
from db import db, ordered
from errors import ApiError
from response import collection, single
from services import derive, serialize

bp = Blueprint("registry", __name__)

ASSESSOR_STATUSES = ("ACTIVE", "SUSPENDED")
APPROVAL_STATUSES = ("APPROVED", "REVOKED")


# --------------------------------------------------------------------------- #
# Assessors
# --------------------------------------------------------------------------- #
@bp.post("/assessors")
def create_assessor():
    mw.authenticate((mw.ROLE_ADMIN,))
    body = mw.json_body()
    full_name = mw.v_str(body, "full_name", allow_empty=False)
    email = mw.v_str(body, "email", allow_empty=False)
    certification_expires_at, _ = mw.v_instant(body, "certification_expires_at")
    qa_qualified = mw.v_bool(body, "qa_qualified", required=False, default=False)

    for row in db.assessors.values():
        if row.get("email") == email:
            raise ApiError("ERR_DUPLICATE_ASSESSOR_EMAIL")

    row = {
        "full_name": full_name,
        "email": email,
        "certification_expires_at": certification_expires_at,
        "qa_qualified": qa_qualified,
        "status": "ACTIVE",
    }
    db.stamp_new(row)
    db.assessors[row["id"]] = row
    return single(serialize.assessor(row), 201)


@bp.get("/assessors")
def list_assessors():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    rows = ordered(db.assessors.values())
    payload = [serialize.assessor(row) for row in rows]
    payload = mw.apply_filters(payload, {
        "status": ("status", "str"),
        "certification_status": ("certification_status", "str"),
        "qa_qualified": ("qa_qualified", "bool"),
    })
    return collection(mw.page(payload, limit, offset), limit, offset, len(payload))


@bp.get("/assessors/<row_id>")
def get_assessor(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.assessors, row_id, "ERR_ASSESSOR_NOT_FOUND")
    return single(serialize.assessor(row))


@bp.patch("/assessors/<row_id>")
def patch_assessor(row_id):
    mw.authenticate((mw.ROLE_ADMIN,))
    body = mw.json_body()
    full_name = mw.v_str(body, "full_name", required=False, allow_empty=False)
    email = mw.v_str(body, "email", required=False, allow_empty=False)
    certification_expires_at, _ = mw.v_instant(body, "certification_expires_at", required=False)
    qa_qualified = mw.v_bool(body, "qa_qualified", required=False)
    status = mw.v_enum(body, "status", ASSESSOR_STATUSES, required=False)

    row = mw.fetch(db.assessors, row_id, "ERR_ASSESSOR_NOT_FOUND")

    if email is not None and email != row.get("email"):
        for other in db.assessors.values():
            if other["id"] != row["id"] and other.get("email") == email:
                raise ApiError("ERR_DUPLICATE_ASSESSOR_EMAIL")

    if full_name is not None:
        row["full_name"] = full_name
    if email is not None:
        row["email"] = email
    if certification_expires_at is not None:
        row["certification_expires_at"] = certification_expires_at
    if qa_qualified is not None:
        row["qa_qualified"] = qa_qualified
    if status is not None:
        row["status"] = status
    db.touch(row)
    return single(serialize.assessor(row))


# --------------------------------------------------------------------------- #
# Approved scanning vendors
# --------------------------------------------------------------------------- #
@bp.post("/asv-vendors")
def create_vendor():
    mw.authenticate((mw.ROLE_ADMIN,))
    body = mw.json_body()
    name = mw.v_str(body, "name", allow_empty=False)
    approval_expires_at, _ = mw.v_instant(body, "approval_expires_at")

    for row in db.asv_vendors.values():
        if row.get("name") == name:
            raise ApiError("ERR_DUPLICATE_VENDOR_NAME")

    row = {
        "name": name,
        "approval_expires_at": approval_expires_at,
        "approval_status": "APPROVED",
    }
    db.stamp_new(row)
    db.asv_vendors[row["id"]] = row
    return single(serialize.asv_vendor(row), 201)


@bp.get("/asv-vendors")
def list_vendors():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    rows = ordered(db.asv_vendors.values())
    payload = [serialize.asv_vendor(row) for row in rows]
    payload = mw.apply_filters(payload, {
        "approval_status": ("approval_status", "str"),
        "effective_approval": ("effective_approval", "str"),
    })
    return collection(mw.page(payload, limit, offset), limit, offset, len(payload))


@bp.get("/asv-vendors/<row_id>")
def get_vendor(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.asv_vendors, row_id, "ERR_ASV_VENDOR_NOT_FOUND")
    return single(serialize.asv_vendor(row))


@bp.patch("/asv-vendors/<row_id>")
def patch_vendor(row_id):
    mw.authenticate((mw.ROLE_ADMIN,))
    body = mw.json_body()
    name = mw.v_str(body, "name", required=False, allow_empty=False)
    approval_expires_at, _ = mw.v_instant(body, "approval_expires_at", required=False)
    approval_status = mw.v_enum(body, "approval_status", APPROVAL_STATUSES, required=False)

    row = mw.fetch(db.asv_vendors, row_id, "ERR_ASV_VENDOR_NOT_FOUND")

    if name is not None and name != row.get("name"):
        for other in db.asv_vendors.values():
            if other["id"] != row["id"] and other.get("name") == name:
                raise ApiError("ERR_DUPLICATE_VENDOR_NAME")

    if name is not None:
        row["name"] = name
    if approval_expires_at is not None:
        row["approval_expires_at"] = approval_expires_at
    if approval_status is not None:
        row["approval_status"] = approval_status
    db.touch(row)
    return single(serialize.asv_vendor(row))


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
@bp.post("/_clock/set_current_utc")
def set_clock():
    mw.authenticate((mw.ROLE_ADMIN,))
    body = mw.json_body()
    raw, moment = mw.v_instant(body, "to_iso8601")
    db.set_clock(moment, raw)
    return single({"current_utc": db.current_utc()})


_ = derive  # imported for module symmetry with the other route modules
