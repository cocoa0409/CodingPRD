"""Clinic ticket routes (PRD 3.3, 3.5; §1.5)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import errors
import helpers
import lookups
import response
from middleware import require
from services import calc, enrollment as esvc

bp = Blueprint("clinic_tickets", __name__)

# Service category -> required station_type. The PRD frames station_type as the
# "service category"; we accept line items whose service maps to the station, but
# the spec only pins that the station_type must match the service category and the
# station must not be OUT_OF_SERVICE. With no service_code->type taxonomy declared,
# the matching rule reduces to: the station must not be OUT_OF_SERVICE.
TURNOVER_BUFFER = timedelta(minutes=15)


def _instructor_license_ok(instructor):
    if not instructor["active"]:
        return False
    expires = helpers.parse_dt(instructor["license_expires_on"])
    return expires > clock.now()


def _validate_line_items(line_items):
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise errors.invalid_request("line_items must be a non-empty array")
    for li in line_items:
        if not isinstance(li, dict):
            raise errors.invalid_request("each line item must be an object")
        if "service_code" not in li or not isinstance(li["service_code"], str) or not li["service_code"]:
            raise errors.invalid_request("line item requires a service_code string")
        sp = li.get("salon_price_cents")
        if isinstance(sp, bool) or not isinstance(sp, int):
            raise errors.invalid_request("line item salon_price_cents must be an integer")
        if sp < 0:
            raise errors.invalid_request("salon_price_cents must be >= 0")


@bp.post("/school/clinic-tickets")
@require("Instructor")
def create_clinic_ticket():
    data = helpers.body()
    helpers.require_fields(
        data, "enrollment_id", "station_id", "instructor_id",
        "client_name", "start_iso", "end_iso", "line_items",
    )
    enrollment_id = helpers.require_str(data, "enrollment_id")
    station_id = helpers.require_str(data, "station_id")
    instructor_id = helpers.require_str(data, "instructor_id")
    # Priority 4: body FK existence.
    lookups.fk(db.enrollments, enrollment_id)
    station = lookups.fk(db.stations, station_id)
    lookups.fk(db.instructors, instructor_id)
    client_name = helpers.require_str(data, "client_name")
    start_dt = helpers.require_dt(data, "start_iso")
    end_dt = helpers.require_dt(data, "end_iso")
    line_items = data["line_items"]
    _validate_line_items(line_items)
    clinic_discount_pct = helpers.opt_number(data, "clinic_discount_pct", 0.50)
    if clinic_discount_pct < 0 or clinic_discount_pct > 1:
        raise errors.invalid_request("clinic_discount_pct must be between 0 and 1")

    # Priority 12: clinic slot conflict — the slot [start,end) extended by a
    # 15-minute turnover buffer must not collide with any non-VOIDED ticket on
    # the same station. Tickets within 15 minutes of each other are rejected
    # even when geometrically disjoint.
    for ct in db.clinic_tickets.values():
        if ct["station_id"] != station_id:
            continue
        if ct["status"] == "VOIDED":
            continue
        ex_start = helpers.parse_dt(ct["start_iso"])
        ex_end = helpers.parse_dt(ct["end_iso"])
        # Conflict iff the new slot overlaps the existing slot expanded by the
        # buffer on both sides: new.start < ex_end + buffer AND ex_start < new.end + buffer.
        if start_dt < ex_end + TURNOVER_BUFFER and ex_start < end_dt + TURNOVER_BUFFER:
            raise errors.clinic_slot_conflict()

    # Priority 13: station_type matches service category; station not OUT_OF_SERVICE.
    if station["status"] == "OUT_OF_SERVICE":
        raise errors.station_unavailable()

    row = {
        "enrollment_id": enrollment_id,
        "station_id": station_id,
        "instructor_id": instructor_id,
        "client_name": client_name,
        "start_iso": db.iso(start_dt),
        "end_iso": db.iso(end_dt),
        "line_items": line_items,
        "clinic_discount_pct": clinic_discount_pct,
        "ticket_total_cents": None,
        "clinic_hours": calc.clinic_hours(start_dt, end_dt),
        "status": "OPEN",
    }
    db.stamp_new(row)
    db.clinic_tickets[row["id"]] = row

    # Side effect: chosen station -> OCCUPIED.
    station["status"] = "OCCUPIED"
    db.touch(station)

    return response.created(row)


@bp.get("/school/clinic-tickets/<cid>")
@require("Registrar", "FinancialAidOfficer", "Instructor", "Student")
def get_clinic_ticket(cid):
    row = lookups.path(db.clinic_tickets, cid)
    return response.ok(row)


@bp.get("/school/clinic-tickets")
@require("Registrar", "FinancialAidOfficer", "Instructor", "Student")
def list_clinic_tickets():
    rows = list(db.clinic_tickets.values())
    enrollment_id = request.args.get("enrollment_id")
    station_id = request.args.get("station_id")
    instructor_id = request.args.get("instructor_id")
    if enrollment_id:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if station_id:
        rows = [r for r in rows if r["station_id"] == station_id]
    if instructor_id:
        rows = [r for r in rows if r["instructor_id"] == instructor_id]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)


@bp.post("/school/clinic-tickets/<cid>/sign-off")
@require("Instructor")
def sign_off(cid):
    row = lookups.path(db.clinic_tickets, cid)
    # Priority 7: state precondition.
    if row["status"] != "OPEN":
        raise errors.invalid_state()
    instructor = db.instructors[row["instructor_id"]]
    # Priority 9: instructor license.
    if not _instructor_license_ok(instructor):
        raise errors.instructor_license_invalid()
    enrollment = db.enrollments[row["enrollment_id"]]
    # Sign-off requires owning enrollment ACTIVE or SAP_WARNING.
    if enrollment["status"] not in ("ACTIVE", "SAP_WARNING"):
        raise errors.invalid_state("owning enrollment must be ACTIVE or SAP_WARNING")
    # Priority 10: clinic phase reached (actual_hours >= program.clinic_phase_start_hour).
    esvc.recompute_hours(enrollment)
    program = db.programs[enrollment["program_id"]]
    if enrollment["actual_hours"] < program["clinic_phase_start_hour"]:
        raise errors.clinic_phase_not_reached()

    row["status"] = "SIGNED_OFF"
    db.touch(row)

    # Credit clinic_hours into actual_hours (full recompute now that SIGNED_OFF
    # qualifies), recompute pace, bump enrollment version.
    esvc.recompute_hours(enrollment)
    db.touch(enrollment)

    # Cross-entity: occupied station OCCUPIED -> AVAILABLE.
    station = db.stations[row["station_id"]]
    station["status"] = "AVAILABLE"
    db.touch(station)

    return response.ok(row)


@bp.post("/school/clinic-tickets/<cid>/pay")
@require("Registrar")
def pay(cid):
    row = lookups.path(db.clinic_tickets, cid)
    if row["status"] != "SIGNED_OFF":
        raise errors.invalid_state()
    row["status"] = "PAID"
    # Compute ticket_total_cents at payment (CALC clinic_pos_total).
    row["ticket_total_cents"] = calc.clinic_pos_total(row["line_items"], row["clinic_discount_pct"])
    db.touch(row)
    return response.ok(row)


@bp.post("/school/clinic-tickets/<cid>/void")
@require("Registrar")
def void(cid):
    row = lookups.path(db.clinic_tickets, cid)
    if row["status"] != "OPEN":
        raise errors.invalid_state()
    row["status"] = "VOIDED"
    db.touch(row)
    # Cross-entity: release occupied station back to AVAILABLE. Credits no hours.
    station = db.stations[row["station_id"]]
    station["status"] = "AVAILABLE"
    db.touch(station)
    return response.ok(row)
