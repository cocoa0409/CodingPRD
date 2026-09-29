"""Monitoring visit endpoints (PRD §3.6)."""

from flask import Blueprint

import clock
import config as C
import envelope
import models
import services
import validators
from auth import authenticate
from errors import ApiError
from routes.common import body_fk, listing, need
from store import db, ordered, touch

bp = Blueprint("monitoring", __name__)

STAFF_ROLES = (C.ROLE_ANALYST, C.ROLE_SUPERVISOR, C.ROLE_INVESTIGATOR)
WRITE_ROLES = (C.ROLE_ANALYST, C.ROLE_INVESTIGATOR)


@bp.post("/monitoring-visits")
def create_visit():
    caller = authenticate(*WRITE_ROLES)
    payload = validators.body()
    if payload.get("visit_type") == "COMPLIANCE_BUY" and caller.role != C.ROLE_INVESTIGATOR:
        raise ApiError("ERR_FORBIDDEN_VISIT_TYPE")

    vendor = body_fk(payload, "vendor_id", db.vendors, "ERR_VENDOR_NOT_FOUND")
    vendor_id = validators.req_string(payload, "vendor_id")
    visit_type = validators.req_enum(payload, "visit_type", C.VISIT_TYPES)
    scheduled_for = validators.req_instant(payload, "scheduled_for")

    if vendor["authorization_status"] not in C.MONITORABLE_STATUSES:
        raise ApiError("ERR_VENDOR_NOT_MONITORABLE")
    if visit_type == "COMPLIANCE_BUY" and not (
        vendor["compliance_buy_required"] or vendor["risk_tier"] == "HIGH"
    ):
        raise ApiError("ERR_COMPLIANCE_BUY_NOT_WARRANTED")
    if scheduled_for < clock.now():
        raise ApiError("ERR_VISIT_DATE_IN_PAST")
    buffer_seconds = C.MONITORING_BLACKOUT_DAYS * 86400
    for existing in db.monitoring_visits.values():
        if existing["vendor_id"] != vendor_id or existing["status"] != "SCHEDULED":
            continue
        gap = abs((existing["scheduled_for"] - scheduled_for).total_seconds())
        if gap <= buffer_seconds:
            raise ApiError("ERR_VISIT_BLACKOUT_CONFLICT")

    record = models.monitoring_visit(
        vendor_id=vendor_id,
        visit_type=visit_type,
        scheduled_for=scheduled_for,
        auto_generated=False,
    )
    db.monitoring_visits[record["id"]] = record
    if visit_type == "COMPLIANCE_BUY":
        services.update(vendor, reauthorization_hold=True)
    return envelope.success(record, 201)


@bp.get("/monitoring-visits/<entity_id>")
def read_visit(entity_id):
    authenticate(*STAFF_ROLES)
    return envelope.success(need(db.monitoring_visits, entity_id, "ERR_VISIT_NOT_FOUND"))


@bp.get("/monitoring-visits")
def list_visits():
    authenticate(*STAFF_ROLES)
    return listing(
        ordered(db.monitoring_visits),
        {"vendor_id": "vendor_id", "status": "status", "visit_type": "visit_type"},
    )


@bp.post("/monitoring-visits/<entity_id>/observations")
def record_observation(entity_id):
    authenticate(*WRITE_ROLES)
    visit = need(db.monitoring_visits, entity_id, "ERR_VISIT_NOT_FOUND")
    payload = validators.body()
    body_fk(payload, "food_category_id", db.food_categories, "ERR_FOOD_CATEGORY_NOT_FOUND")
    category_id = validators.req_string(payload, "food_category_id")
    observed_units = validators.req_int(payload, "observed_units", minimum=0)
    observed_variety = validators.req_int(payload, "observed_variety_count", minimum=0)

    if visit["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_VISIT_STATE")
    for entry in visit["stock_findings"]:
        if entry.get("food_category_id") == category_id:
            raise ApiError("ERR_DUPLICATE_OBSERVATION")

    visit["stock_findings"].append(
        {
            "food_category_id": category_id,
            "observed_units": observed_units,
            "observed_variety_count": observed_variety,
            "required_units": None,
            "verdict": None,
        }
    )
    touch(visit)
    return envelope.success(visit)


@bp.post("/monitoring-visits/<entity_id>/conduct")
def conduct_visit(entity_id):
    authenticate(*WRITE_ROLES)
    visit = need(db.monitoring_visits, entity_id, "ERR_VISIT_NOT_FOUND")
    payload = validators.body()

    buy_items = []
    raw_items = payload.get("buy_items")
    if raw_items is not None:
        if not isinstance(raw_items, list):
            raise validators.invalid("Field 'buy_items' must be an array.")
        for index, entry in enumerate(raw_items):
            if not isinstance(entry, dict):
                raise validators.invalid("Each 'buy_items' entry must be an object.")
            upc = validators.req_string(entry, "upc")
            quantity = validators.req_int(entry, "quantity", minimum=0)
            charged = validators.req_int(entry, "charged_unit_price_cents", minimum=0)
            buy_items.append(
                {
                    "upc": upc,
                    "quantity": quantity,
                    "charged_unit_price_cents": charged,
                }
            )

    if visit["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_VISIT_STATE")
    vendor = db.vendors.get(visit["vendor_id"])
    if vendor is None or vendor["authorization_status"] not in C.MONITORABLE_STATUSES:
        raise ApiError("ERR_VENDOR_NOT_MONITORABLE")

    services.conduct_visit(visit, vendor, buy_items)
    return envelope.success(visit)
