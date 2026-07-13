from datetime import datetime, timezone

from flask import Blueprint

import db
import core
import ser
import find
import cascade
from core import ApiError

bp = Blueprint("clients", __name__)


@bp.post("/clients")
@core.require_auth(["IntakeCoordinator"])
def create_client():
    body = core.get_body()
    full_name = core.require_field(body, "full_name", "str")
    birth_date = core.require_field(body, "birth_date", "str")
    household_size = core.require_field(body, "household_size", "int")
    monthly_income_cents = core.require_field(body, "monthly_income_cents", "int")
    address_zone = core.require_field(body, "address_zone", "str")
    phone = core.require_field(body, "phone", "str")

    # field-value validation
    if household_size < 1:
        core.invalid_value("household_size must be >= 1")
    if monthly_income_cents < 0:
        core.invalid_value("monthly_income_cents must be >= 0")
    bd = core.parse_date(birth_date)
    if bd is None:
        core.invalid_value("birth_date is not a valid date")
    created_dt = db.now()
    birth_dt = datetime(bd.year, bd.month, bd.day, tzinfo=timezone.utc)
    if birth_dt >= created_dt:
        core.invalid_value("birth_date must be strictly before the creation moment")

    rec = db.base_record()
    rec.update({
        "full_name": full_name,
        "birth_date": birth_date,
        "household_size": household_size,
        "monthly_income_cents": monthly_income_cents,
        "address_zone": address_zone,
        "phone": phone,
        "enrollment_status": "INTAKE",
        "oaa_eligible": core.compute_oaa_eligible(bd, created_dt),
        "income_tier": core.compute_income_tier(monthly_income_cents, household_size),
        "consecutive_no_answer": 0,
    })
    db.clients[rec["id"]] = rec
    return core.ok_object(ser.client(rec), 201)


@bp.get("/clients/<cid>")
@core.require_auth(core.ALL_ROLES)
def get_client(cid):
    c = find.client(cid)
    return core.ok_object(ser.client(c))


@bp.patch("/clients/<cid>")
@core.require_auth(["IntakeCoordinator"])
def update_client(cid):
    body = core.get_body()
    expected = core.require_field(body, "expected_client_version", "int")
    household_size = core.optional_field(body, "household_size", "int")
    monthly_income_cents = core.optional_field(body, "monthly_income_cents", "int")
    address_zone = core.optional_field(body, "address_zone", "str")
    phone = core.optional_field(body, "phone", "str")

    if household_size is not None and household_size < 1:
        core.invalid_value("household_size must be >= 1")
    if monthly_income_cents is not None and monthly_income_cents < 0:
        core.invalid_value("monthly_income_cents must be >= 0")

    c = find.client(cid)

    if expected != c["version"]:
        raise ApiError("ERR_STALE_CLIENT_VERSION", 412, "expected_client_version does not match")

    if household_size is not None:
        c["household_size"] = household_size
    if monthly_income_cents is not None:
        c["monthly_income_cents"] = monthly_income_cents
    if address_zone is not None:
        c["address_zone"] = address_zone
    if phone is not None:
        c["phone"] = phone

    # tier is fully determined by income + household -> recompute (reconciliation)
    c["income_tier"] = core.compute_income_tier(c["monthly_income_cents"], c["household_size"])
    db.touch(c)
    return core.ok_object(ser.client(c))


@bp.post("/clients/<cid>/activate")
@core.require_auth(["IntakeCoordinator"])
def activate_client(cid):
    c = find.client(cid)
    if c["enrollment_status"] != "ASSESSED":
        raise ApiError("ERR_CLIENT_NOT_ASSESSED", 409, "Client must be ASSESSED to activate")
    if ser.count_active_meal_plans(cid) != 1:
        raise ApiError("ERR_INVALID_STATE", 409, "Client must have exactly one ACTIVE meal plan")
    c["enrollment_status"] = "ACTIVE"
    db.touch(c)
    return core.ok_object(ser.client(c))


@bp.post("/clients/<cid>/discharge")
@core.require_auth(["IntakeCoordinator"])
def discharge_client(cid):
    c = find.client(cid)
    if c["enrollment_status"] not in ("ASSESSED", "ACTIVE", "ON_HOLD"):
        raise ApiError("ERR_INVALID_STATE", 409, "Client cannot be discharged from its current state")

    # cancel the ACTIVE or SUSPENDED meal plan (if any)
    for mp in db.meal_plans.values():
        if mp["client_id"] == cid and mp["status"] in ("ACTIVE", "SUSPENDED"):
            mp["status"] = "CANCELLED"
            db.touch(mp)

    # cancel every SCHEDULED delivery for the client
    cascade.cancel_scheduled_deliveries_of_client(cid)

    # cancel every ACTIVE vacation hold for the client
    for h in db.vacation_holds.values():
        if h["client_id"] == cid and h["status"] == "ACTIVE":
            h["status"] = "CANCELLED"
            db.touch(h)

    c["enrollment_status"] = "DISCHARGED"
    db.touch(c)
    return core.ok_object(ser.client(c))


@bp.get("/clients/<cid>/summary")
@core.require_auth(core.ALL_ROLES)
def client_summary(cid):
    c = find.client(cid)
    return core.ok_object(ser.client_summary(c))
