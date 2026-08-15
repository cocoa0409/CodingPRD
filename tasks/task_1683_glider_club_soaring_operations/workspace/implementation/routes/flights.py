"""Flight (launch log) endpoints: post, land, reconcile, void."""

import uuid
from fractions import Fraction

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_AIRCRAFT_NOT_AIRWORTHY,
    ERR_FLIGHT_NOT_IN_FLIGHT,
    ERR_FLIGHT_NOT_LANDED,
    ERR_INVALID_FLIGHT_TIMES,
    ERR_MEMBER_NOT_ACTIVE,
    ERR_REFERENTIAL_INTEGRITY,
    ERR_RESOURCE_NOT_FOUND,
    ERR_STALE_TOW_SLOT_VERSION,
    ERR_TOW_SLOT_FULL,
    ERR_TOW_SLOT_MISMATCH,
)
from middleware import auth, forbid, require_role
from response import success
from services import (
    TOW_SORTIE_HOURS,
    currency_failure_reason,
    currency_ok,
    final_tow_fee_cents,
    ground_aircraft,
    member_tier,
    provisional_tow_fee_cents,
    ser_flight,
    touch,
)
from util import ceil_minutes, get_body, need_dt, need_int, need_str, paginate, sort_items

bp = Blueprint("flights", __name__)


def _get_flight_or_404(fid):
    flight = db.STORE["flights"].get(fid)
    if flight is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Flight not found")
    return flight


def _recheck_currency(aircraft):
    """In-request grounding after hour accrual (PRD section 3.6)."""
    if aircraft["status"] != "AIRWORTHY":
        return
    reason = currency_failure_reason(aircraft, db.now())
    if reason is not None:
        ground_aircraft(aircraft, reason)


@bp.post("/soaring/flights")
def post_flight():
    user_id, role = auth()
    require_role(role, ["Member", "DutyOfficer", "TowPilot"])
    body = get_body()
    reservation_id = need_str(body, "reservation_id")
    tow_slot_id = need_str(body, "tow_slot_id")
    release_altitude_ft = need_int(body, "release_altitude_ft")
    takeoff_at = need_dt(body, "takeoff_at")
    # Existence.
    reservation = db.STORE["reservations"].get(reservation_id)
    if reservation is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Reservation not found")
    slot = db.STORE["tow_slots"].get(tow_slot_id)
    if slot is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "TowSlot not found")
    # Ownership: the piloting Member or the slot's TowPilot; DutyOfficer any.
    if role == "Member" and reservation["member_id"] != user_id:
        forbid("A Member may only post launches for their own reservations")
    if role == "TowPilot" and slot["tow_pilot_id"] != user_id:
        forbid("A TowPilot may only post launches against their own slots")
    # OCC: expected_tow_slot_version must match the slot's current version.
    expected = body.get("expected_tow_slot_version")
    if (
        isinstance(expected, bool)
        or not isinstance(expected, int)
        or expected != slot["version"]
    ):
        raise ApiError(
            ERR_STALE_TOW_SLOT_VERSION, 412,
            "expected_tow_slot_version does not match the current TowSlot.version",
        )
    # Member-side gates: pilot and any instructor must be ACTIVE.
    member = db.STORE["members"].get(reservation["member_id"])
    if member is None or member["status"] != "ACTIVE":
        raise ApiError(ERR_MEMBER_NOT_ACTIVE, 409, "The pilot is not ACTIVE")
    if reservation.get("instructor_id"):
        instructor = db.STORE["members"].get(reservation["instructor_id"])
        if instructor is None or instructor["status"] != "ACTIVE":
            raise ApiError(
                ERR_MEMBER_NOT_ACTIVE, 409, "The instructor is not ACTIVE"
            )
    # Inline airworthiness gate on the reserved glider.
    glider = db.STORE["aircraft"].get(reservation["aircraft_id"])
    at = db.now()
    if (
        glider is None
        or glider["status"] != "AIRWORTHY"
        or not currency_ok(glider, at)
    ):
        raise ApiError(
            ERR_AIRCRAFT_NOT_AIRWORTHY, 409,
            "Glider is not AIRWORTHY or fails the inline currency check",
        )
    # Capacity: strict <.
    if slot["confirmed_count"] >= slot["capacity"]:
        raise ApiError(ERR_TOW_SLOT_FULL, 409, "Tow slot is at capacity")
    # Coherence: reservation CHECKED_OUT, slot SCHEDULED, takeoff in window.
    if (
        reservation["status"] != "CHECKED_OUT"
        or slot["status"] != "SCHEDULED"
        or not (slot["start_at"] <= takeoff_at <= slot["end_at"])
    ):
        raise ApiError(
            ERR_TOW_SLOT_MISMATCH, 409,
            "Reservation must be CHECKED_OUT, the slot SCHEDULED, and "
            "takeoff_at within the slot window",
        )
    if release_altitude_ft < 500:
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422,
            "release_altitude_ft must be at least 500",
        )
    tier = member_tier(member)
    provisional = provisional_tow_fee_cents(tier, release_altitude_ft)
    record = {
        "id": str(uuid.uuid4()),
        "reservation_id": reservation_id,
        "tow_slot_id": tow_slot_id,
        "release_altitude_ft": release_altitude_ft,
        "takeoff_at": takeoff_at,
        "landed_at": None,
        "status": "IN_FLIGHT",
        "flight_minutes": None,
        "provisional_fee_cents": provisional,
        "final_fee_cents": None,
        "retrieve_id": None,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.STORE["flights"][record["id"]] = record
    # Provisional debit; slot load and slot version advance.
    member["account_balance_cents"] += provisional
    touch(member)
    slot["confirmed_count"] += 1
    touch(slot)
    return success(ser_flight(record), "object", 201)


@bp.get("/soaring/flights")
def list_flights():
    auth()
    items = list(db.STORE["flights"].values())
    for param in ("reservation_id", "tow_slot_id", "retrieve_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [f for f in items if f.get(param) == value]
    page, meta = paginate(sort_items(items))
    return success([ser_flight(f) for f in page], "array", 200, meta)


@bp.get("/soaring/flights/<fid>")
def get_flight(fid):
    auth()
    return success(ser_flight(_get_flight_or_404(fid)), "object", 200)


@bp.post("/soaring/flights/<fid>/land")
def land_flight(fid):
    user_id, role = auth()
    require_role(role, ["Member", "DutyOfficer"])
    flight = _get_flight_or_404(fid)
    reservation = db.STORE["reservations"].get(flight["reservation_id"])
    if role == "Member" and (reservation is None or reservation["member_id"] != user_id):
        forbid("A Member may only land their own flights")
    if flight["status"] != "IN_FLIGHT":
        raise ApiError(
            ERR_FLIGHT_NOT_IN_FLIGHT, 409,
            "Landing requires flight status IN_FLIGHT",
        )
    body = get_body()
    landed_at = need_dt(body, "landed_at")
    if landed_at <= flight["takeoff_at"]:
        raise ApiError(
            ERR_INVALID_FLIGHT_TIMES, 422,
            "landed_at must be strictly after takeoff_at",
        )
    flight_minutes = ceil_minutes(landed_at - flight["takeoff_at"])
    member = db.STORE["members"].get(reservation["member_id"])
    tier = member_tier(member)
    final_fee = final_tow_fee_cents(member, tier, flight, flight_minutes)
    # Balance absorbs only the delta between provisional and final.
    member["account_balance_cents"] += final_fee - flight["provisional_fee_cents"]
    touch(member)
    # Airframe hour accrual: glider gains the flight time; the tow plane
    # gains a fixed twelve-minute sortie regardless of soaring duration.
    glider_hours = Fraction(flight_minutes, 60)
    glider = db.STORE["aircraft"].get(reservation["aircraft_id"])
    slot = db.STORE["tow_slots"].get(flight["tow_slot_id"])
    tow_plane = db.STORE["aircraft"].get(slot["tow_plane_id"]) if slot else None
    if glider is not None:
        glider["total_time_hours"] += glider_hours
        glider["hours_since_inspection"] += glider_hours
        touch(glider)
    if tow_plane is not None:
        tow_plane["total_time_hours"] += TOW_SORTIE_HOURS
        tow_plane["hours_since_inspection"] += TOW_SORTIE_HOURS
        touch(tow_plane)
    flight["landed_at"] = landed_at
    flight["flight_minutes"] = flight_minutes
    flight["final_fee_cents"] = final_fee
    flight["status"] = "LANDED"
    touch(flight)
    # Immediate currency re-check on both airframes; failures ground in-request.
    if glider is not None:
        _recheck_currency(glider)
    if tow_plane is not None:
        _recheck_currency(tow_plane)
    return success(ser_flight(flight), "object", 200)


@bp.post("/soaring/flights/<fid>/reconcile")
def reconcile_flight(fid):
    _, role = auth()
    require_role(role, ["DutyOfficer", "ClubAdmin"])
    flight = _get_flight_or_404(fid)
    if flight["status"] != "LANDED":
        raise ApiError(
            ERR_FLIGHT_NOT_LANDED, 409,
            "Reconcile requires flight status LANDED",
        )
    flight["status"] = "RECONCILED"
    touch(flight)
    reservation = db.STORE["reservations"].get(flight["reservation_id"])
    if reservation is not None and reservation["status"] == "CHECKED_OUT":
        reservation["status"] = "CLOSED"
        touch(reservation)
    return success(ser_flight(flight), "object", 200)


@bp.post("/soaring/flights/<fid>/void")
def void_flight(fid):
    _, role = auth()
    require_role(role, ["DutyOfficer", "ClubAdmin"])
    flight = _get_flight_or_404(fid)
    if flight["status"] != "IN_FLIGHT":
        raise ApiError(
            ERR_FLIGHT_NOT_IN_FLIGHT, 409,
            "Void requires flight status IN_FLIGHT",
        )
    flight["status"] = "VOIDED"
    touch(flight)
    reservation = db.STORE["reservations"].get(flight["reservation_id"])
    member = db.STORE["members"].get(reservation["member_id"]) if reservation else None
    if member is not None:
        member["account_balance_cents"] -= flight["provisional_fee_cents"]
        touch(member)
    slot = db.STORE["tow_slots"].get(flight["tow_slot_id"])
    if slot is not None:
        slot["confirmed_count"] -= 1
        if slot["confirmed_count"] == 0 and slot["start_at"] > db.now():
            slot["status"] = "CANCELLED"
        touch(slot)
    # The linked reservation stays CHECKED_OUT (the pilot may re-launch).
    return success(ser_flight(flight), "object", 200)
