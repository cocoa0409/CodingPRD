"""Parcel endpoints and the record-sale transition (PRD §3.2)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_roles
from response import object_response, array_response
from services.common import (
    get_body, require_fields, lookup, parse_pagination, paginate,
)
from services.serialize import serialize, serialize_list

bp = Blueprint("parcels", __name__)


@bp.post("/parcels")
def create_parcel():
    require_roles(["Assessor"])
    body = get_body()
    require_fields(body, ["owner_id", "apn", "situs_address"])

    owner_id = body["owner_id"]
    apn = body["apn"]
    situs_address = body["situs_address"]
    if not isinstance(owner_id, str) or not isinstance(apn, str) \
            or not isinstance(situs_address, str):
        raise err("ERR_INVALID_REQUEST", "owner_id/apn/situs_address must be strings")

    is_primary_residence = body.get("is_primary_residence", False)
    if not isinstance(is_primary_residence, bool):
        raise err("ERR_INVALID_REQUEST", "is_primary_residence must be a boolean")

    lookup(db.owners, owner_id)  # existence (ERR_NOT_FOUND)

    # apn unique among parcels
    for p in db.parcels.values():
        if p["apn"] == apn:
            raise err("ERR_INVALID_REQUEST", "apn must be unique among parcels")

    record = {
        "owner_id": owner_id,
        "apn": apn,
        "situs_address": situs_address,
        "is_primary_residence": is_primary_residence,
        "last_certified_capped_base": 0,
        "status": "ACTIVE",
    }
    db.init_common(record)
    with db.LOCK:
        db.parcels[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/parcels")
def list_parcels():
    require_roles(["Assessor", "Reviewer", "HearingOfficer"])
    limit, offset = parse_pagination()
    owner_id = request.args.get("owner_id")
    items = list(db.parcels.values())
    if owner_id is not None:
        items = [p for p in items if p["owner_id"] == owner_id]
    window, total = paginate(items, limit, offset)
    return array_response(serialize_list(window), limit, offset, total, 200)


@bp.get("/parcels/<parcel_id>")
def get_parcel(parcel_id):
    require_roles(["Assessor", "Reviewer", "HearingOfficer", "Taxpayer"])
    return object_response(serialize(lookup(db.parcels, parcel_id)), 200)


@bp.post("/parcels/<parcel_id>/record-sale")
def record_sale(parcel_id):
    require_roles(["Assessor"])
    body = get_body()
    require_fields(body, ["new_owner_id"])
    new_owner_id = body["new_owner_id"]
    if not isinstance(new_owner_id, str):
        raise err("ERR_INVALID_REQUEST", "new_owner_id must be a string")

    with db.LOCK:
        parcel = lookup(db.parcels, parcel_id)
        if parcel["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Parcel is not ACTIVE")
        # ERR_OWNER_NOT_FOUND is the distinct code for an unresolved new owner.
        if new_owner_id not in db.owners:
            raise err("ERR_OWNER_NOT_FOUND", "new_owner_id does not resolve to an Owner")
        parcel["owner_id"] = new_owner_id
        parcel["last_certified_capped_base"] = 0
        parcel["status"] = "SOLD"
        db.touch(parcel)
    return object_response(serialize(parcel), 200)


@bp.get("/parcels/<parcel_id>/assessments")
def list_parcel_assessments(parcel_id):
    require_roles(["Assessor", "Reviewer", "HearingOfficer", "Taxpayer"])
    lookup(db.parcels, parcel_id)
    limit, offset = parse_pagination()
    items = [a for a in db.assessments.values() if a["parcel_id"] == parcel_id]
    window, total = paginate(items, limit, offset)
    return array_response(serialize_list(window), limit, offset, total, 200)


@bp.get("/parcels/<parcel_id>/deferrals")
def list_parcel_deferrals(parcel_id):
    require_roles(["Assessor", "Reviewer", "Taxpayer"])
    lookup(db.parcels, parcel_id)
    limit, offset = parse_pagination()
    items = [d for d in db.deferral_agreements.values()
             if d["parcel_id"] == parcel_id]
    window, total = paginate(items, limit, offset)
    return array_response(serialize_list(window), limit, offset, total, 200)
