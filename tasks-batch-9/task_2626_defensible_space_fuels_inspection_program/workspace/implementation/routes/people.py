"""The inspector roster (PRD section 3.3) and the contractor roster (section 3.7)."""

from decimal import Decimal

from flask import Blueprint

from auth import auth
from db import db, insert
from errors import fail
from response import created, jsonable, ok, touch
from validate import body, get_dt, get_enum, get_int, get_str, lookup

bp = Blueprint("people", __name__, url_prefix="/fire-district")

CERTIFICATION_LEVELS = ("BASIC", "ADVANCED", "WUI_SPECIALIST")
INSPECTOR_STATUSES = ("ACTIVE", "SUSPENDED")
LICENSE_STATUSES = ("ACTIVE", "SUSPENDED", "REVOKED")


@bp.post("/inspectors")
def create_inspector():
    auth("ProgramAdmin")
    b = body()
    full_name = get_str(b, "full_name")
    certification_level = get_enum(b, "certification_level", CERTIFICATION_LEVELS)
    status = get_enum(b, "status", INSPECTOR_STATUSES, required=False, default="ACTIVE")
    inspector = insert(db.inspectors, {
        "full_name": full_name,
        "certification_level": certification_level,
        "status": status,
        "assigned_open_count": 0,
    })
    return created(jsonable(inspector))


@bp.get("/inspectors/<inspector_id>")
def read_inspector(inspector_id):
    auth("ProgramAdmin", "FireMarshal")
    return ok(jsonable(lookup("inspectors", inspector_id, "ERR_INSPECTOR_NOT_FOUND")))


@bp.post("/contractors")
def create_contractor():
    auth("ProgramAdmin")
    b = body()
    business_name = get_str(b, "business_name", allow_empty=False)
    hourly_rate_cents = get_int(b, "hourly_rate_cents", minimum=1)
    mobilization_fee_cents = get_int(b, "mobilization_fee_cents", minimum=0)
    insurance_expiry_utc = get_dt(b, "insurance_expiry_utc")
    license_status = get_enum(
        b, "license_status", LICENSE_STATUSES, required=False, default="ACTIVE"
    )
    max_daily_orders = get_int(b, "max_daily_orders", required=False, minimum=1, default=2)
    for existing in db.contractors.values():
        if existing["business_name"] == business_name:
            fail(
                "ERR_APN_ALREADY_REGISTERED",
                "Business name %r is already on the roster." % business_name,
            )
    contractor = insert(db.contractors, {
        "business_name": business_name,
        "hourly_rate_cents": hourly_rate_cents,
        "mobilization_fee_cents": mobilization_fee_cents,
        "license_status": license_status,
        "insurance_expiry_utc": insurance_expiry_utc,
        "max_daily_orders": max_daily_orders,
        "committed_crew_hours": Decimal("0.0"),
        "completed_crew_hours": Decimal("0.0"),
    })
    return created(jsonable(contractor))


@bp.get("/contractors/<contractor_id>")
def read_contractor(contractor_id):
    auth("ProgramAdmin", "FireMarshal", "Contractor")
    return ok(jsonable(lookup("contractors", contractor_id, "ERR_CONTRACTOR_NOT_FOUND")))


@bp.patch("/contractors/<contractor_id>")
def update_contractor(contractor_id):
    auth("ProgramAdmin")
    contractor = lookup("contractors", contractor_id, "ERR_CONTRACTOR_NOT_FOUND")
    b = body()
    if "license_status" in b:
        contractor["license_status"] = get_enum(b, "license_status", LICENSE_STATUSES)
    if "insurance_expiry_utc" in b:
        contractor["insurance_expiry_utc"] = get_dt(b, "insurance_expiry_utc")
    if "hourly_rate_cents" in b:
        contractor["hourly_rate_cents"] = get_int(b, "hourly_rate_cents", minimum=1)
    if "mobilization_fee_cents" in b:
        contractor["mobilization_fee_cents"] = get_int(b, "mobilization_fee_cents", minimum=0)
    if "max_daily_orders" in b:
        contractor["max_daily_orders"] = get_int(b, "max_daily_orders", minimum=1)
    touch(contractor)
    return ok(jsonable(contractor))
