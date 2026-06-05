"""Booking-series routes: create, read, list, generate (OCC), pause, resume,
cancel (with cascade).
"""
from datetime import timedelta

from flask import Blueprint, request

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (get_json_body, require_resource, require_fields,
                     parse_pagination, paginate, ownership_customer)
from response import success, list_success
from constants import ADDON_CODES, SUPPLIES, CADENCES, CADENCE_DAYS
from clock import clock
from util import parse_iso
from services import booking_ops

bp = Blueprint("booking_series", __name__)


def _validate_add_ons(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise err("ERR_INVALID_REQUEST", "add_ons must be a list")
    for a in value:
        if a not in ADDON_CODES:
            raise err("ERR_INVALID_REQUEST", "invalid add-on: %s" % a)
    return list(value)


@bp.route("/cleaning/booking-series", methods=["POST"])
def create_series():
    principal = authenticate()
    authorize(principal, {"Customer"})
    body = get_json_body()
    require_fields(body, ["customer_id", "address_id", "pricing_plan_id",
                          "cadence", "first_occurrence_date"])
    # Existence left-to-right: customer, address, pricing_plan, then optional
    # preferred_cleaner_id.
    customer = require_resource(db.customers, body["customer_id"], "customer")
    address = require_resource(db.addresses, body["address_id"], "address")
    plan = require_resource(db.pricing_plans, body["pricing_plan_id"], "pricing_plan")
    preferred_cleaner_id = body.get("preferred_cleaner_id")
    if preferred_cleaner_id is not None:
        require_resource(db.cleaners, preferred_cleaner_id, "cleaner")

    ownership_customer(principal, customer["id"])

    cadence = body["cadence"]
    if cadence not in CADENCES:
        raise err("ERR_INVALID_REQUEST", "cadence must be WEEKLY or BIWEEKLY")
    add_ons = _validate_add_ons(body.get("add_ons"))
    supplies = body.get("supplies_provided_by")
    if supplies is None:
        supplies = "CUSTOMER"
    elif supplies not in SUPPLIES:
        raise err("ERR_INVALID_REQUEST", "invalid supplies_provided_by")

    # ERR_ADDON_NOT_ALLOWED (priority 9) before ERR_ADDRESS_ARCHIVED (priority 10).
    if "MOVE_OUT" in add_ons:
        raise err("ERR_ADDON_NOT_ALLOWED", "MOVE_OUT not allowed on a recurring series")
    if address.get("archived"):
        raise err("ERR_ADDRESS_ARCHIVED", "address is archived")

    first_date = parse_iso(body["first_occurrence_date"])
    rec = {
        "customer_id": customer["id"],
        "address_id": address["id"],
        "pricing_plan_id": plan["id"],
        "cadence": cadence,
        "add_ons": add_ons,
        "supplies_provided_by": supplies,
        "preferred_cleaner_id": preferred_cleaner_id,
        "status": "ACTIVE",
        "next_occurrence_date": first_date,
    }
    db.insert(db.booking_series, rec)
    return success(S.booking_series(rec), status=201)


@bp.route("/cleaning/booking-series/<sid>", methods=["GET"])
def get_series(sid):
    principal = authenticate()
    authorize(principal, {"Customer", "PlatformAdmin"})
    rec = require_resource(db.booking_series, sid, "booking_series")
    ownership_customer(principal, rec["customer_id"])
    return success(S.booking_series(rec), status=200)


@bp.route("/cleaning/booking-series", methods=["GET"])
def list_series():
    principal = authenticate()
    authorize(principal, {"Customer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    records = list(db.booking_series.values())
    for key in ("customer_id", "address_id", "pricing_plan_id", "preferred_cleaner_id"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r.get(key) == val]
    if principal.role == "Customer":
        records = [r for r in records if r["customer_id"] == principal.user_id]
    page, total = paginate(records, limit, offset)
    return list_success([S.booking_series(r) for r in page], limit, offset, total)


@bp.route("/cleaning/booking-series/<sid>/generate", methods=["POST"])
def generate_occurrence(sid):
    principal = authenticate()
    authorize(principal, {"PlatformAdmin"})
    series = require_resource(db.booking_series, sid, "booking_series")
    # State gate: series must be ACTIVE.
    if series["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "series is not ACTIVE")
    body = get_json_body()

    customer = db.customers.get(series["customer_id"])
    address = db.addresses.get(series["address_id"])
    plan = db.pricing_plans.get(series["pricing_plan_id"])

    # Business checks. Address-archived (priority 10) before availability and
    # collisions; OCC version (priority 15) is checked after the lower-numbered
    # business gates per §2.6 but before request-body validation. We resolve the
    # cleaner (availability/clearance) after archived, then OCC, then commit.
    if address.get("archived"):
        raise err("ERR_ADDRESS_ARCHIVED", "address is archived")

    # next_occurrence_date must be at or before the current clock.
    next_date = series.get("next_occurrence_date")
    if next_date is None or next_date > clock.now():
        raise err("ERR_INVALID_STATE", "next occurrence is not yet due")

    # OCC check (priority 15).
    require_fields(body, ["expected_series_version"])
    expected = body["expected_series_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_series_version must be an integer")
    if expected != series.get("version"):
        raise err("ERR_STALE_VERSION", "series version mismatch")

    # Resolve cleaner (pinned preferred_cleaner_id or auto-assign).
    cleaner = booking_ops.resolve_cleaner_for_booking(
        customer["id"], address["postal_code"], series.get("preferred_cleaner_id"))

    booking = booking_ops.create_booking_record(
        customer=customer, address=address, plan=plan,
        scheduled_start=next_date, add_ons=list(series.get("add_ons", [])),
        supplies_provided_by=series.get("supplies_provided_by", "CUSTOMER"),
        cleaner_id=cleaner["id"], series_id=series["id"])

    # Advance next_occurrence_date by the cadence step and bump series version.
    step = CADENCE_DAYS[series["cadence"]]
    series["next_occurrence_date"] = next_date + timedelta(days=step)
    db.touch(series)
    return success(S.booking(booking), status=201)


@bp.route("/cleaning/booking-series/<sid>/pause", methods=["POST"])
def pause_series(sid):
    principal = authenticate()
    authorize(principal, {"Customer"})
    series = require_resource(db.booking_series, sid, "booking_series")
    ownership_customer(principal, series["customer_id"])
    if series["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "only ACTIVE series can be paused")
    series["status"] = "PAUSED"
    db.touch(series)
    return success(S.booking_series(series), status=200)


@bp.route("/cleaning/booking-series/<sid>/resume", methods=["POST"])
def resume_series(sid):
    principal = authenticate()
    authorize(principal, {"Customer"})
    series = require_resource(db.booking_series, sid, "booking_series")
    ownership_customer(principal, series["customer_id"])
    if series["status"] != "PAUSED":
        raise err("ERR_INVALID_STATE", "only PAUSED series can be resumed")
    series["status"] = "ACTIVE"
    db.touch(series)
    return success(S.booking_series(series), status=200)


@bp.route("/cleaning/booking-series/<sid>/cancel", methods=["POST"])
def cancel_series(sid):
    principal = authenticate()
    authorize(principal, {"Customer"})
    series = require_resource(db.booking_series, sid, "booking_series")
    ownership_customer(principal, series["customer_id"])
    if series["status"] not in ("ACTIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "series is not cancellable")

    # Cascade: cancel every child booking still in SCHEDULED/RESCHEDULED, each
    # running its own refund-and-fee settlement transitively.
    children = [b for b in db.bookings.values()
                if b.get("series_id") == series["id"]
                and b.get("status") in ("SCHEDULED", "RESCHEDULED")]
    children.sort(key=lambda b: b.get("_seq", 0))
    for child in children:
        customer = db.customers.get(child["customer_id"])
        booking_ops.settle_cancellation(child, customer)
        child["status"] = "CANCELLED"
        db.touch(child)

    series["status"] = "CANCELLED"
    series["next_occurrence_date"] = None
    db.touch(series)
    return success(S.booking_series(series), status=200)
