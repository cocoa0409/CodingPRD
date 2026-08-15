"""TripRequest endpoints with the five-gate scheduling stack."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (
    validation, ApiError,
    ERR_TRIP_INVALID_STATE, ERR_AGREEMENT_INVALID_STATE,
    ERR_MAINTENANCE_OVERDUE, ERR_INSURANCE_NOT_CURRENT,
    ERR_CREW_COMPLEMENT_INCOMPLETE, ERR_AIRCRAFT_OVERLAP,
    ERR_QUOTE_REQUIRED, ERR_EXPENSE_NOT_POSTED,
)
from middleware import require_roles, require_read, require_owner_of
from response import success_object, success_list
from serializers import trip_view
from services.core import (
    make_record, touch, require_exists, get_pagination, paginate,
    current_agreement_for_aircraft,
)
from services.trips import complete_trip, void_trip, cancel_trip
from util import parse_datetime, parse_date

bp = Blueprint("trips", __name__)

TRIP_USES = {"OWNER_USE", "CHARTER"}
TURNAROUND_BUFFER_HOURS = Decimal("1")


def _positive_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise validation(f"{field} must be a number > 0")


@bp.route("/trips", methods=["POST"])
def create_trip():
    require_roles("FlightOpsManager", "Owner")
    body = request.get_json(silent=True) or {}

    aircraft_id = body.get("aircraft_id")
    if aircraft_id is not None:
        require_exists(db.aircraft, aircraft_id, "aircraft_id does not resolve")
    if not isinstance(aircraft_id, str) or not aircraft_id:
        raise validation("aircraft_id is required")

    trip_use = body.get("trip_use")
    if trip_use not in TRIP_USES:
        raise validation("trip_use must be OWNER_USE or CHARTER")

    depart_icao = body.get("depart_icao")
    if not isinstance(depart_icao, str) or not depart_icao:
        raise validation("depart_icao is required")
    arrive_icao = body.get("arrive_icao")
    if not isinstance(arrive_icao, str) or not arrive_icao:
        raise validation("arrive_icao is required")

    departure_at = body.get("departure_at")
    parse_datetime(departure_at, "departure_at")

    block_hours_est = body.get("block_hours_est")
    _positive_number(block_hours_est, "block_hours_est")

    charter_quote_cents = body.get("charter_quote_cents")
    if charter_quote_cents is not None:
        if isinstance(charter_quote_cents, bool) or not isinstance(charter_quote_cents, int) or charter_quote_cents < 0:
            raise validation("charter_quote_cents must be a non-negative integer")

    if trip_use == "CHARTER" and charter_quote_cents is None:
        raise ApiError(ERR_QUOTE_REQUIRED, "CHARTER trips must carry charter_quote_cents", 422)

    rec = make_record({
        "aircraft_id": aircraft_id,
        "trip_use": trip_use,
        "depart_icao": depart_icao,
        "arrive_icao": arrive_icao,
        "departure_at": departure_at,
        "block_hours_est": block_hours_est,
        "block_hours_actual": None,
        "charter_quote_cents": charter_quote_cents,
        "owner_credit_cents": None,
        "charter_shortfall_cents": None,
        "decline_reason": None,
        "status": "REQUESTED",
        "_completed_at": None,
        "_accrual_expense_id": None,
    })
    db.trips[rec["id"]] = rec

    # OWNER_USE auto-approves at creation
    if trip_use == "OWNER_USE":
        rec["status"] = "APPROVED"

    return success_object(trip_view(rec), 201)


@bp.route("/trips/<trip_id>", methods=["GET"])
def get_trip(trip_id):
    require_read()
    rec = require_exists(db.trips, trip_id)
    return success_object(trip_view(rec))


@bp.route("/aircraft/<aircraft_id>/trips", methods=["GET"])
def list_trips(aircraft_id):
    require_read()
    require_exists(db.aircraft, aircraft_id)
    limit, offset = get_pagination(request.args)
    records = [t for t in db.trips.values() if t["aircraft_id"] == aircraft_id]
    page, total = paginate(records, limit, offset)
    return success_list([trip_view(r) for r in page], limit, offset, total)


@bp.route("/trips/<trip_id>/approve", methods=["POST"])
def approve_trip(trip_id):
    user_id, role = require_roles("Owner")
    rec = require_exists(db.trips, trip_id)
    agreement = current_agreement_for_aircraft(rec["aircraft_id"])
    owner_id = agreement["owner_id"] if agreement is not None else None
    require_owner_of(user_id, role, owner_id)
    if rec["status"] != "REQUESTED":
        raise ApiError(ERR_TRIP_INVALID_STATE, "Trip must be in REQUESTED", 409)
    rec["status"] = "APPROVED"
    touch(rec, bump_version=True)
    return success_object(trip_view(rec))


@bp.route("/trips/<trip_id>/decline", methods=["POST"])
def decline_trip(trip_id):
    user_id, role = require_roles("Owner")
    rec = require_exists(db.trips, trip_id)
    agreement = current_agreement_for_aircraft(rec["aircraft_id"])
    owner_id = agreement["owner_id"] if agreement is not None else None
    require_owner_of(user_id, role, owner_id)
    body = request.get_json(silent=True) or {}
    if rec["status"] != "REQUESTED" or rec["trip_use"] != "CHARTER":
        raise ApiError(ERR_TRIP_INVALID_STATE,
                       "Only a REQUESTED CHARTER trip may be declined", 409)
    rec["status"] = "DECLINED"
    rec["decline_reason"] = body.get("reason")
    touch(rec, bump_version=True)
    return success_object(trip_view(rec))


@bp.route("/trips/<trip_id>/resubmit", methods=["POST"])
def resubmit_trip(trip_id):
    require_roles("FlightOpsManager", "Owner")
    rec = require_exists(db.trips, trip_id)
    body = request.get_json(silent=True) or {}

    if "departure_at" in body and body["departure_at"] is not None:
        parse_datetime(body["departure_at"], "departure_at")
    if "block_hours_est" in body and body["block_hours_est"] is not None:
        _positive_number(body["block_hours_est"], "block_hours_est")
    if "charter_quote_cents" in body and body["charter_quote_cents"] is not None:
        v = body["charter_quote_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise validation("charter_quote_cents must be a non-negative integer")

    if rec["status"] != "DECLINED":
        raise ApiError(ERR_TRIP_INVALID_STATE, "Trip must be in DECLINED", 409)

    if "departure_at" in body and body["departure_at"] is not None:
        rec["departure_at"] = body["departure_at"]
    if "block_hours_est" in body and body["block_hours_est"] is not None:
        rec["block_hours_est"] = body["block_hours_est"]
    if "charter_quote_cents" in body and body["charter_quote_cents"] is not None:
        rec["charter_quote_cents"] = body["charter_quote_cents"]
    rec["decline_reason"] = None
    rec["status"] = "REQUESTED"
    touch(rec, bump_version=True)
    return success_object(trip_view(rec))


@bp.route("/trips/<trip_id>/schedule", methods=["POST"])
def schedule_trip(trip_id):
    require_roles("FlightOpsManager")
    rec = require_exists(db.trips, trip_id)
    if rec["status"] != "APPROVED":
        raise ApiError(ERR_TRIP_INVALID_STATE, "Trip must be in APPROVED", 409)

    aircraft = db.aircraft[rec["aircraft_id"]]

    # Gate 1: agreement must be ACTIVE
    agreement = current_agreement_for_aircraft(rec["aircraft_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE,
                       "The aircraft's ManagementAgreement must be ACTIVE", 409)

    # Gate 2: no overdue maintenance event (due AT current hours is overdue)
    total_hours = Decimal(str(aircraft["total_time_hours"]))
    for e in db.events.values():
        if e["aircraft_id"] != rec["aircraft_id"]:
            continue
        if e["status"] in ("FORECAST", "SCHEDULED"):
            if Decimal(str(e["due_at_aircraft_hours"])) <= total_hours:
                raise ApiError(ERR_MAINTENANCE_OVERDUE,
                               "A FORECAST or SCHEDULED maintenance event is due at or below the aircraft's current total_time_hours", 409)

    # Gate 3: ACCEPTED INSURANCE_COI valid through the departure date
    departure_date = parse_datetime(rec["departure_at"], "departure_at").date()
    insurance_ok = False
    for f in db.filings.values():
        if (f["aircraft_id"] == rec["aircraft_id"]
                and f["filing_kind"] == "INSURANCE_COI"
                and f["status"] == "ACCEPTED"):
            valid_until = parse_date(f["valid_until"], "valid_until")
            if valid_until >= departure_date:
                insurance_ok = True
                break
    if not insurance_ok:
        raise ApiError(ERR_INSURANCE_NOT_CURRENT,
                       "No ACCEPTED INSURANCE_COI filing valid through the departure date", 409)

    # Gate 4: crew complement
    pic_ok = False
    sic_ok = False
    for a in db.assignments.values():
        if a["trip_id"] != rec["id"] or a["status"] != "ASSIGNED":
            continue
        member = db.crew.get(a["crew_member_id"])
        if member is None or member["status"] != "QUALIFIED":
            continue
        if a["duty_role"] == "PIC" and member["crew_role"] == "CAPTAIN":
            pic_ok = True
        if a["duty_role"] == "SIC" and member["crew_role"] == "FIRST_OFFICER":
            sic_ok = True
    if not (pic_ok and sic_ok):
        raise ApiError(ERR_CREW_COMPLEMENT_INCOMPLETE,
                       "Trip requires an ASSIGNED QUALIFIED CAPTAIN as PIC and QUALIFIED FIRST_OFFICER as SIC", 409)

    # Gate 5: aircraft occupancy with turnaround buffer
    dep = parse_datetime(rec["departure_at"], "departure_at")
    c_start = dep
    c_end = dep + timedelta(hours=float(rec["block_hours_est"]))
    buffer = timedelta(hours=float(TURNAROUND_BUFFER_HOURS))
    for other in db.trips.values():
        if other["id"] == rec["id"] or other["aircraft_id"] != rec["aircraft_id"]:
            continue
        if other["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        o_start = parse_datetime(other["departure_at"], "departure_at")
        o_end = o_start + timedelta(hours=float(other["block_hours_est"]))
        if c_start >= o_end + buffer or c_end + buffer <= o_start:
            continue
        raise ApiError(ERR_AIRCRAFT_OVERLAP,
                       "Aircraft occupancy would leave < 1h turnaround gap to another SCHEDULED/COMPLETED trip", 409)

    rec["status"] = "SCHEDULED"
    touch(rec, bump_version=True)
    return success_object(trip_view(rec))


@bp.route("/trips/<trip_id>/complete", methods=["POST"])
def complete_trip_endpoint(trip_id):
    require_roles("FlightOpsManager")
    rec = require_exists(db.trips, trip_id)
    body = request.get_json(silent=True) or {}
    if "block_hours_actual" in body and body["block_hours_actual"] is not None:
        _positive_number(body["block_hours_actual"], "block_hours_actual")

    if rec["status"] != "SCHEDULED":
        raise ApiError(ERR_TRIP_INVALID_STATE, "Trip must be in SCHEDULED", 409)

    block_hours_actual = body.get("block_hours_actual")
    _positive_number(block_hours_actual, "block_hours_actual")

    complete_trip(rec, block_hours_actual)
    return success_object(trip_view(rec))


@bp.route("/trips/<trip_id>/cancel", methods=["POST"])
def cancel_trip_endpoint(trip_id):
    require_roles("FlightOpsManager", "Owner")
    rec = require_exists(db.trips, trip_id)
    if rec["status"] not in ("REQUESTED", "APPROVED", "SCHEDULED"):
        raise ApiError(ERR_TRIP_INVALID_STATE,
                       "Trip must be in REQUESTED, APPROVED, or SCHEDULED", 409)
    cancel_trip(rec)
    rec["version"] += 1  # cancel bumps version (touch inside cancel_trip did not)
    return success_object(trip_view(rec))


@bp.route("/trips/<trip_id>/void", methods=["POST"])
def void_trip_endpoint(trip_id):
    require_roles("FlightOpsManager")
    rec = require_exists(db.trips, trip_id)
    if rec["status"] != "COMPLETED":
        raise ApiError(ERR_TRIP_INVALID_STATE, "Trip must be in COMPLETED", 409)
    accrual_id = rec.get("_accrual_expense_id")
    if accrual_id is not None:
        expense = db.expenses.get(accrual_id)
        if expense is not None and expense["status"] != "POSTED":
            raise ApiError(ERR_EXPENSE_NOT_POSTED,
                           "The completion-created PROGRAM_ACCRUAL expense is no longer POSTED", 409)
    void_trip(rec)
    rec["version"] += 1
    return success_object(trip_view(rec))
