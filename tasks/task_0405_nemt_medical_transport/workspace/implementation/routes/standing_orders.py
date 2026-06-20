"""StandingOrder endpoints incl. idempotent rolling-horizon generation (PRD 3.6)."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint

from db import db, new_common, touch
from errors import err
from helpers import (get_json_body, parse_dt, require_enum, require_int,
                     require_number)
from middleware import require_roles
from response import ok_object
from serializers import serialize

bp = Blueprint("standing_orders", __name__)

MODALITY = {"AMBULATORY", "WHEELCHAIR", "STRETCHER"}
LOS = {"ROUTINE", "URGENT", "BARIATRIC"}


def get_so_or_404(so_id):
    s = db.standing_orders.get(so_id)
    if s is None:
        raise err("ERR_NOT_FOUND", "StandingOrder not found")
    return s


@bp.route("/standing-orders", methods=["POST"])
def create_standing_order():
    require_roles("Coordinator")
    body = get_json_body()
    if "member_id" not in body or body["member_id"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: member_id")
    member_id = body["member_id"]
    if member_id not in db.members:
        raise err("ERR_FK_NOT_FOUND", "member_id does not reference an existing Member")
    modality = require_enum(body, "modality", MODALITY)
    level_of_service = require_enum(body, "level_of_service", LOS)
    weekday_mask = require_int(body, "weekday_mask")
    appointment_time_utc = body.get("appointment_time_utc")
    if not isinstance(appointment_time_utc, str) or not _valid_time(appointment_time_utc):
        raise err("ERR_INVALID_REQUEST", "appointment_time_utc must be HH:MM:SS")
    scheduled_loaded_miles = require_number(body, "scheduled_loaded_miles")

    so = new_common()
    so.update({
        "member_id": member_id,
        "modality": modality,
        "level_of_service": level_of_service,
        "weekday_mask": weekday_mask,
        "appointment_time_utc": appointment_time_utc,
        "scheduled_loaded_miles": scheduled_loaded_miles,
        "horizon_through": None,
        "status": "ACTIVE",
    })
    db.standing_orders[so["id"]] = so
    return ok_object(serialize(so), status=201)


def _valid_time(s):
    try:
        datetime.strptime(s, "%H:%M:%S")
        return True
    except ValueError:
        return False


@bp.route("/standing-orders/<so_id>", methods=["GET"])
def get_standing_order(so_id):
    require_roles("Coordinator")
    return ok_object(serialize(get_so_or_404(so_id)))


@bp.route("/standing-orders/<so_id>/generate", methods=["POST"])
def generate(so_id):
    require_roles("Coordinator")
    so = get_so_or_404(so_id)
    body = get_json_body()
    if "generate_from" not in body or body["generate_from"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: generate_from")
    if "generate_through" not in body or body["generate_through"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: generate_through")
    generate_from = parse_dt(body["generate_from"])
    generate_through = parse_dt(body["generate_through"])

    member = db.members.get(so["member_id"])

    # Effective start: later of generate_from and current horizon_through.
    horizon = parse_dt(so["horizon_through"]) if so["horizon_through"] else None
    effective_from = generate_from
    if horizon is not None and horizon > effective_from:
        effective_from = horizon

    suppressed = (so["status"] != "ACTIVE") or (member is not None and member["standing_orders_paused"])

    if not suppressed:
        # Walk whole calendar dates [effective_from_date, generate_through_date).
        cur_date = effective_from.date()
        end_date = generate_through.date()
        hh, mm, ss = [int(x) for x in so["appointment_time_utc"].split(":")]
        while cur_date < end_date:
            # weekday(): Monday=0 .. Sunday=6, matches bit indexing.
            bit = cur_date.weekday()
            if (so["weekday_mask"] >> bit) & 1:
                appt = datetime(cur_date.year, cur_date.month, cur_date.day,
                                hh, mm, ss, tzinfo=timezone.utc)
                _create_generated_trip(so, member, appt)
            cur_date = cur_date + timedelta(days=1)

    # Horizon advances to generate_through regardless (idempotent rolling horizon).
    so["horizon_through"] = body["generate_through"]
    touch(so)
    return ok_object(serialize(so))


def _create_generated_trip(so, member, appt_dt):
    from clock import now_iso
    trip = new_common()
    trip.update({
        "member_id": so["member_id"],
        "standing_order_id": so["id"],
        "modality": so["modality"],
        "requested_level_of_service": so["level_of_service"],
        "appointment_at": appt_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "is_round_trip": True,
        "return_is_will_call": False,
        "trip_status": "DRAFT",
        "billing_status": "UNBILLED",
        "assigned_broker_id": None,
        "assigned_driver_id": None,
        "scheduled_loaded_miles": so["scheduled_loaded_miles"],
        "claimed_cost_cents": 0,
        "encounter_cost_cents": 0,
        "reconciliation_variance_cents": 0,
    })
    db.trips[trip["id"]] = trip
    return trip


@bp.route("/standing-orders/<so_id>/pause", methods=["POST"])
def pause(so_id):
    require_roles("Coordinator")
    so = get_so_or_404(so_id)
    if so["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "StandingOrder is not ACTIVE")
    so["status"] = "PAUSED"
    touch(so)
    return ok_object(serialize(so))


@bp.route("/standing-orders/<so_id>/resume", methods=["POST"])
def resume(so_id):
    require_roles("Coordinator")
    so = get_so_or_404(so_id)
    if so["status"] != "PAUSED":
        raise err("ERR_INVALID_STATE", "StandingOrder is not PAUSED")
    so["status"] = "ACTIVE"
    touch(so)
    return ok_object(serialize(so))
