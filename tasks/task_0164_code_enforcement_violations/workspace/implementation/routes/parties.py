"""Owner and Property endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import db, common_fields
from errors import err
from middleware import require_roles
from response import success, list_success
from services import serialize
from services.helpers import (
    get_body,
    lookup,
    pagination_params,
    paginate,
    require_enum,
    require_fields,
    resolve_ref,
    sort_by_created,
)

bp = Blueprint("parties", __name__)

OCCUPANCY = {"OCCUPIED", "VACANT"}


# ---------------------------------------------------------------------------
# Owner
# ---------------------------------------------------------------------------

@bp.post("/owners")
@require_roles("PlatformAdmin", "CodeOfficer")
def create_owner():
    body = get_body()
    require_fields(body, "full_name", "mailing_email")
    record = common_fields()
    record.update({
        "full_name": body["full_name"],
        "mailing_email": body["mailing_email"],
    })
    db.owners[record["id"]] = record
    return success(serialize.owner_out(record), status=201)


@bp.get("/owners/<oid>")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk", "Registrant")
def get_owner(oid):
    record = lookup(db.owners, oid)
    return success(serialize.owner_out(record), status=200)


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------

@bp.post("/properties")
@require_roles("PlatformAdmin", "CodeOfficer")
def create_property():
    body = get_body()
    require_fields(body, "owner_id", "parcel_number", "street_address")
    require_enum(body, "occupancy", OCCUPANCY)
    # FK resolution before business rules (PRD §2.8).
    resolve_ref(db.owners, body["owner_id"])
    # parcel_number unique among non-ARCHIVED Property (PRD §3.1).
    for p in db.properties.values():
        if p["status"] != "ARCHIVED" and p["parcel_number"] == body["parcel_number"]:
            raise err("ERR_DUPLICATE_PARCEL", "parcel_number already in use")

    record = common_fields()
    record.update({
        "owner_id": body["owner_id"],
        "parcel_number": body["parcel_number"],
        "street_address": body["street_address"],
        "occupancy": body["occupancy"],
        "status": "ACTIVE",
    })
    db.properties[record["id"]] = record
    return success(serialize.property_out(record), status=201)


@bp.get("/properties/<pid>")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk", "Registrant")
def get_property(pid):
    record = lookup(db.properties, pid)
    return success(serialize.property_out(record), status=200)


@bp.get("/properties")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk")
def list_properties():
    limit, offset = pagination_params()
    items = list(db.properties.values())
    owner_id = request.args.get("owner_id")
    if owner_id is not None:
        items = [p for p in items if p["owner_id"] == owner_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize.property_out(p) for p in page], limit, offset, total)
