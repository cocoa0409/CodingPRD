"""Induction bookings (PRD 3.5): 9 endpoints."""

from flask import Blueprint

import calc
import clock
import common
import const
import rev
import store
from fields import q_enum, q_str, s_dt, s_enum, s_int, s_str
from pipeline import begin, need, run_checks
from store import S

bp = Blueprint("bookings", __name__)

READ_ROLES = ["PatientAccessCoordinator", "ChargeNurse", "ObstetricianAttending",
              "PerinatalSafetyOfficer"]


@bp.post("/induction-bookings")
def create_booking():
    ctx = begin(
        roles=["PatientAccessCoordinator", "ObstetricianAttending"],
        body_refs=[("unit_id", "unit")],
        specs=[s_str("unit_id", required=True),
               s_str("patient_record_code", required=True, min_len=1, max_len=60),
               s_int("gestational_age_weeks", required=True, min=20, max=44),
               s_enum("indication_code", const.INDICATIONS, required=True),
               s_dt("requested_start_utc", required=True),
               s_int("expected_labor_minutes", min=60, max=2160, default=720)],
    )
    unit = ctx.r["unit"]

    def future():
        need(ctx.v["requested_start_utc"] > clock.now(), "ERR_BOOKING_START_IN_PAST")

    run_checks([(14.2, future)])
    booking = store.new_record({
        "unit_id": unit["id"],
        "patient_record_code": ctx.v["patient_record_code"],
        "gestational_age_weeks": ctx.v["gestational_age_weeks"],
        "indication_code": ctx.v["indication_code"],
        "priority_class": "PATIENT_REQUEST",
        "requested_start_utc": ctx.v["requested_start_utc"],
        "expected_labor_minutes": ctx.v["expected_labor_minutes"],
        "projected_occupancy_minutes": None,
        "bed_id": None,
        "encounter_id": None,
        "status": "REQUESTED",
        "hold_expires_at": None,
        "bump_count": 0,
    })
    booking["priority_class"] = calc.booking_priority_class(booking)
    S.bookings[booking["id"]] = booking
    return common.created("bookings", booking)


@bp.get("/induction-bookings")
def list_bookings():
    begin(roles=READ_ROLES)
    unit_id = q_str("unit_id")
    bed_id = q_str("bed_id")
    encounter_id = q_str("encounter_id")
    status = q_enum("status", const.BOOKING_STATUSES)
    priority = q_enum("priority_class", const.PRIORITY_CLASSES)
    day = q_str("requested_day")
    found = [b for b in S.bookings.values()
             if common.match(b, "unit_id", unit_id)
             and common.match(b, "bed_id", bed_id)
             and common.match(b, "encounter_id", encounter_id)
             and common.match(b, "status", status)
             and common.match(b, "priority_class", priority)
             and (day is None or calc.booking_day(b) == day)]
    return common.listing_rows("bookings", calc.promotion_order(found))


@bp.get("/induction-bookings/<booking_id>")
def read_booking(booking_id):
    ctx = begin(roles=READ_ROLES, path=[("booking", booking_id)])
    return common.single("bookings", ctx.p["booking"])


@bp.post("/induction-bookings/<booking_id>/hold-capacity")
def hold_capacity(booking_id):
    ctx = begin(roles=["PatientAccessCoordinator"], path=[("booking", booking_id)],
                body_refs=[("bed_id", "bed")],
                specs=[s_str("bed_id", required=True),
                       s_int("expected_unit_version", required=True)],
                occ=("expected_unit_version", "ERR_STALE_UNIT_VERSION",
                     lambda c: S.units.get(c.p["booking"]["unit_id"])))
    booking = ctx.p["booking"]
    bed = ctx.r["bed"]
    unit = S.units.get(booking["unit_id"])
    projection = (booking["expected_labor_minutes"]
                  + (unit.get("turnover_buffer_minutes") or 0))
    day = calc.booking_day(booking)

    def declared():
        need(booking["status"] == "REQUESTED", "ERR_INVALID_STATE_TRANSITION")

    def posture():
        need(unit["staffing_posture"] in ("OPEN", "RATIO_STRAINED"),
             "ERR_UNIT_POSTURE_BLOCKS_OPERATION")
        if booking["priority_class"] == "PATIENT_REQUEST":
            need(unit["staffing_posture"] == "OPEN",
                 "ERR_UNIT_POSTURE_BLOCKS_OPERATION")

    def elective():
        if booking["priority_class"] == "ELECTIVE_39_WEEK":
            need(booking["gestational_age_weeks"] >= 39,
                 "ERR_ELECTIVE_INDUCTION_GESTATIONAL_AGE")

    def eligible():
        need(bed["bed_type"] == "LDR", "ERR_BED_TYPE_NOT_ELIGIBLE")

    def conflict():
        need(bed["status"] == "AVAILABLE", "ERR_BED_TURNOVER_CONFLICT")
        need(not calc.bed_reservation_conflict(bed["id"], booking["requested_start_utc"],
                                              projection, exclude_id=booking["id"]),
             "ERR_BED_TURNOVER_CONFLICT")

    def capacity():
        need(calc.day_load(unit, day) + projection
             <= unit["max_daily_induction_bed_minutes"],
             "ERR_INDUCTION_CAPACITY_EXCEEDED")

    run_checks([(8, declared), (8.02, posture), (11.8, elective),
                (13.31, eligible), (13.32, conflict), (15, capacity)])

    booking["projected_occupancy_minutes"] = projection
    booking["status"] = "CAPACITY_HELD"
    booking["bed_id"] = bed["id"]
    booking["hold_expires_at"] = clock.plus_minutes(clock.now(),
                                                    const.HOLD_TTL_MINUTES)
    rev.touch(booking)
    bed["status"] = "HELD"
    bed["held_booking_id"] = booking["id"]
    rev.touch(bed)
    calc.ledger_move(unit, "held_bed_minutes_by_day", day, projection)
    calc.rederive_unit(unit)
    return common.single("bookings", booking)


@bp.post("/induction-bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    ctx = begin(roles=["ObstetricianAttending"], path=[("booking", booking_id)])
    booking = ctx.p["booking"]
    unit = S.units.get(booking["unit_id"])
    day = calc.booking_day(booking)
    minutes = booking.get("projected_occupancy_minutes") or 0

    def declared():
        need(booking["status"] == "CAPACITY_HELD", "ERR_INVALID_STATE_TRANSITION")

    def posture():
        need(unit["staffing_posture"] in ("OPEN", "RATIO_STRAINED"),
             "ERR_UNIT_POSTURE_BLOCKS_OPERATION")

    def hold_alive():
        need(booking.get("hold_expires_at") is not None
             and clock.now() < booking["hold_expires_at"],
             "ERR_INDUCTION_HOLD_EXPIRED")

    def readiness():
        need(unit["cesarean_readiness_state"] in ("READY", "DEGRADED"),
             "ERR_CESAREAN_READINESS_NOT_MET")

    def elective():
        if booking["priority_class"] == "ELECTIVE_39_WEEK":
            need(booking["gestational_age_weeks"] >= 39,
                 "ERR_ELECTIVE_INDUCTION_GESTATIONAL_AGE")

    def capacity():
        committed = (unit.get("committed_bed_minutes_by_day") or {}).get(day) or 0
        need(committed + minutes <= unit["max_daily_induction_bed_minutes"],
             "ERR_INDUCTION_CAPACITY_EXCEEDED")

    run_checks([(8, declared), (8.02, posture), (8.09, hold_alive),
                (11.4, readiness), (11.8, elective), (15, capacity)])

    calc.ledger_move(unit, "held_bed_minutes_by_day", day, -minutes)
    calc.ledger_move(unit, "committed_bed_minutes_by_day", day, minutes)
    booking["status"] = "CONFIRMED"
    booking["hold_expires_at"] = None
    rev.touch(booking)
    calc.rederive_unit(unit)
    return common.single("bookings", booking)


@bp.post("/induction-bookings/<booking_id>/admit")
def admit_booking(booking_id):
    ctx = begin(roles=["ChargeNurse"], path=[("booking", booking_id)])
    booking = ctx.p["booking"]
    unit = S.units.get(booking["unit_id"])
    bed = S.beds.get(booking.get("bed_id") or "")

    def declared():
        need(booking["status"] == "CONFIRMED", "ERR_INVALID_STATE_TRANSITION")

    def posture():
        need(unit["staffing_posture"] != "DIVERT", "ERR_UNIT_POSTURE_BLOCKS_OPERATION")

    def hold():
        need(bed is not None and bed["status"] == "HELD"
             and bed.get("held_booking_id") == booking["id"], "ERR_BED_HOLD_MISMATCH")

    def unique_code():
        for other in calc.encounters_of_unit(unit["id"]):
            if (other["labor_phase"] not in const.TERMINAL_PHASES
                    and other["patient_record_code"] == booking["patient_record_code"]):
                need(False, "ERR_DUPLICATE_PATIENT_RECORD_CODE")

    def not_early():
        earliest = clock.plus_minutes(booking["requested_start_utc"],
                                      -const.ADMIT_EARLY_MINUTES)
        need(clock.now() >= earliest, "ERR_INDUCTION_ADMIT_TOO_EARLY")

    run_checks([(8, declared), (8.02, posture), (8.07, hold), (13.1, unique_code),
                (14.2, not_early)])

    enc = store.new_record({
        "unit_id": unit["id"],
        "patient_record_code": booking["patient_record_code"],
        "source_booking_id": booking["id"],
        "bed_id": bed["id"],
        "admitted_at": clock.now(),
        "parity": 0,
        "gestational_age_weeks": booking["gestational_age_weeks"],
        "prior_cesarean": False,
        "fetus_count": 1,
        "presentation": "VERTEX",
        "is_ntsv": booking["gestational_age_weeks"] >= 37,
        "labor_phase": "ANTEPARTUM",
        "staffing_state": "UNASSIGNED",
        "acuity_tier": "TIER_I",
        "one_to_one_required": False,
        "required_coverage_units": 0.0,
        "assigned_coverage_units": 0.0,
        "magnesium_infusion_active": False,
        "delivery_mode": None,
        "episiotomy_performed": False,
        "delivery_recorded_at": None,
        "review_required": False,
    })
    S.encounters[enc["id"]] = enc
    bed["status"] = "OCCUPIED"
    bed["held_booking_id"] = None
    bed["current_encounter_id"] = enc["id"]
    rev.touch(bed)
    booking["status"] = "ADMITTED"
    booking["encounter_id"] = enc["id"]
    rev.touch(booking)
    calc.rederive_encounter(enc)
    return common.single("bookings", booking)


@bp.post("/induction-bookings/<booking_id>/bump")
def bump_booking(booking_id):
    ctx = begin(roles=["ChargeNurse", "PatientAccessCoordinator"],
                path=[("booking", booking_id)])
    booking = ctx.p["booking"]
    unit = S.units.get(booking["unit_id"])

    def declared():
        need(booking["status"] in ("CAPACITY_HELD", "CONFIRMED"),
             "ERR_INVALID_STATE_TRANSITION")

    def hold():
        bed = S.beds.get(booking.get("bed_id") or "")
        need(bed is not None and bed.get("held_booking_id") == booking["id"],
             "ERR_BED_HOLD_MISMATCH")

    def limit():
        need((booking.get("bump_count") or 0) < const.BUMP_ESCALATION_LIMIT,
             "ERR_INDUCTION_BUMP_LIMIT_REACHED")

    def bumpable():
        need(booking["priority_class"] != "MEDICALLY_INDICATED",
             "ERR_INDUCTION_NOT_BUMPABLE")

    run_checks([(8, declared), (8.07, hold), (8.091, limit), (8.092, bumpable)])
    calc.bump_booking(booking, unit)
    calc.rederive_unit(unit)
    return common.single("bookings", booking)


@bp.post("/induction-bookings/<booking_id>/requeue")
def requeue_booking(booking_id):
    ctx = begin(roles=["PatientAccessCoordinator"], path=[("booking", booking_id)])
    booking = ctx.p["booking"]

    def declared():
        need(booking["status"] == "BUMPED", "ERR_INVALID_STATE_TRANSITION")

    def window():
        need(booking["requested_start_utc"] > clock.now(),
             "ERR_INDUCTION_WINDOW_PASSED")

    run_checks([(8, declared), (8.09, window)])
    booking["status"] = "REQUESTED"
    booking["priority_class"] = calc.booking_priority_class(booking)
    rev.touch(booking)
    return common.single("bookings", booking)


@bp.post("/induction-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    ctx = begin(roles=["PatientAccessCoordinator"], path=[("booking", booking_id)])
    booking = ctx.p["booking"]
    unit = S.units.get(booking["unit_id"])

    def declared():
        need(booking["status"] in ("REQUESTED", "CAPACITY_HELD", "CONFIRMED",
                                   "ADMITTED"), "ERR_INVALID_STATE_TRANSITION")

    def admitted():
        need(booking["status"] != "ADMITTED", "ERR_INDUCTION_ALREADY_ADMITTED")

    run_checks([(8, declared), (8.09, admitted)])
    calc.release_booking_minutes(unit, booking)
    calc.release_booking_bed(booking)
    booking["status"] = "CANCELLED"
    booking["bed_id"] = None
    booking["hold_expires_at"] = None
    rev.touch(booking)
    calc.rederive_unit(unit)
    return common.single("bookings", booking)
