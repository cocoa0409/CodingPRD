"""Brand registration (PRD section 3.2)."""

from flask import Blueprint

from auth import (
    ALL_ROLES,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FILING_AGENT,
    authenticate,
    require_scope,
)
from envelope import object_response
from errors import raise_err
from serialize import out
from store import bump, db, dt_of, new_record
from validators import Field, collection_response, must_find, require_interval, validate_body

bp = Blueprint("brands", __name__)

BEVERAGE_CLASSES = ("SPIRITS", "WINE", "MALT")
REGISTRATION_STATUSES = ("PENDING", "APPROVED", "REJECTED")


@bp.post("/brands")
def create_brand():
    actor = authenticate([ROLE_FILING_AGENT])
    values = validate_body(
        [
            Field("wholesaler_id", "string"),
            Field("brand_name", "string"),
            Field("supplier_name", "string"),
            Field("beverage_class", "string", enum=BEVERAGE_CLASSES),
            Field("registration_effective_from", "datetime"),
            Field("registration_expires_on", "datetime"),
        ]
    )
    require_interval(values, "registration_effective_from", "registration_expires_on")
    must_find("wholesaler", values["wholesaler_id"])
    require_scope(actor, values["wholesaler_id"])

    # Priority 13 -- closed registration intervals may not overlap for the same
    # wholesaler, brand name and beverage class. REJECTED registrations do not occupy
    # the timeline.
    requested_from = dt_of(values["registration_effective_from"])
    requested_to = dt_of(values["registration_expires_on"])
    for existing in db.brands.values():
        if existing["wholesaler_id"] != values["wholesaler_id"]:
            continue
        if existing["brand_name"] != values["brand_name"]:
            continue
        if existing["beverage_class"] != values["beverage_class"]:
            continue
        if existing["registration_status"] == "REJECTED":
            continue
        existing_from = dt_of(existing["registration_effective_from"])
        existing_to = dt_of(existing["registration_expires_on"])
        if requested_from <= existing_to and existing_from <= requested_to:
            raise_err("ERR_BRAND_REGISTRATION_OVERLAP")

    record = new_record(
        {
            "wholesaler_id": values["wholesaler_id"],
            "brand_name": values["brand_name"],
            "supplier_name": values["supplier_name"],
            "beverage_class": values["beverage_class"],
            "registration_status": "PENDING",
            "registration_effective_from": values["registration_effective_from"],
            "registration_expires_on": values["registration_expires_on"],
            "rejection_reason": None,
        }
    )
    db.brands[record["id"]] = record
    return object_response(out(record), 201)


@bp.post("/brands/<record_id>/approve")
def approve_brand(record_id):
    authenticate([ROLE_COMPLIANCE_OFFICER])
    brand = must_find("brand", record_id)
    if brand["registration_status"] != "PENDING":
        raise_err("ERR_INVALID_STATE")
    brand["registration_status"] = "APPROVED"
    bump(brand)
    return object_response(out(brand))


@bp.post("/brands/<record_id>/reject")
def reject_brand(record_id):
    authenticate([ROLE_COMPLIANCE_OFFICER])
    brand = must_find("brand", record_id)
    values = validate_body([Field("rejection_reason", "string")])
    if brand["registration_status"] != "PENDING":
        raise_err("ERR_INVALID_STATE")
    brand["registration_status"] = "REJECTED"
    brand["rejection_reason"] = values["rejection_reason"]
    bump(brand)
    return object_response(out(brand))


@bp.get("/brands/<record_id>")
def get_brand(record_id):
    authenticate(ALL_ROLES)
    return object_response(out(must_find("brand", record_id)))


@bp.get("/brands")
def list_brands():
    authenticate(ALL_ROLES)
    return collection_response(
        list(db.brands.values()),
        {
            "wholesaler_id": None,
            "registration_status": REGISTRATION_STATUSES,
            "beverage_class": BEVERAGE_CLASSES,
        },
        out,
    )
