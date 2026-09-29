"""Shift assignments: seating a crew and un-seating a member."""

import calc
import domain
import validation as V
from auth import ALL_ROLES, authenticate
from envelope import created_object, ok_list, ok_object
from errors import ApiError
from flask import Blueprint
from store import db

bp = Blueprint("assignments", __name__)


def _match_vacancy(shift_id, apparatus_id, seat_certification):
    candidates = [
        v
        for v in domain.vacancies_of_shift(shift_id, ("OPEN",))
        if v["apparatus_id"] == apparatus_id
        and v["required_certification"] == seat_certification
    ]
    candidates.sort(key=lambda v: (int(v["seat_index"]), v["created_at"], v["_seq"]))
    return candidates[0] if candidates else None


@bp.route("/fire-ops/shift-assignments", methods=["POST"])
def create_assignment():
    authenticate(("CompanyOfficer",))
    body = V.parse_body()
    data = V.validate(
        body,
        [
            V.spec("duty_shift_id", "id"),
            V.spec("firefighter_id", "id"),
            V.spec("apparatus_id", "id"),
            V.spec("assignment_type", "enum", values=V.ASSIGNMENT_TYPES),
            V.spec("seat_certification", "enum", required=False,
                   values=V.SEAT_CERTIFICATIONS, default="NONE"),
            V.spec("scheduled_hours", "number", exclusive_minimum=0, maximum=24),
            V.spec("expected_duty_shift_version", "integer"),
        ],
    )
    shift = domain.require(db.duty_shifts, data["duty_shift_id"], "ERR_DUTY_SHIFT_NOT_FOUND")
    member = domain.require(
        db.firefighters, data["firefighter_id"], "ERR_FIREFIGHTER_NOT_FOUND"
    )
    unit = domain.require(db.apparatus, data["apparatus_id"], "ERR_RESOURCE_NOT_FOUND")

    if data["expected_duty_shift_version"] != int(shift["version"]):
        raise ApiError("ERR_STALE_VERSION")
    if shift["status"] == "COMPLETED":
        raise ApiError("ERR_SHIFT_NOT_HIRING")

    seat_certification = data["seat_certification"] or "NONE"
    assignment_type = data["assignment_type"]
    hours = data["scheduled_hours"]
    shift_date = shift["shift_date"]

    # 9 - cross-entity coherence.
    if member["station_id"] != shift["station_id"] or unit["station_id"] != shift["station_id"]:
        raise ApiError("ERR_STATION_SCOPE_MISMATCH")
    if seat_certification != "NONE" and seat_certification not in (
        member.get("certifications") or []
    ):
        raise ApiError("ERR_CERTIFICATION_NOT_HELD")

    # 10 - rotation compatibility.
    if assignment_type in ("REGULAR", "KELLY_RELIEF"):
        if member["platoon"] != calc.platoon_on_duty(shift_date):
            raise ApiError("ERR_PLATOON_ROTATION_VIOLATION")
    if assignment_type not in ("KELLY_RELIEF", "CALLBACK"):
        if calc.is_kelly_day(member, shift_date):
            raise ApiError("ERR_KELLY_DAY_CONFLICT")

    prospective = calc.interval_for(shift_date, hours)
    domain.check_double_booking(member["id"], prospective)          # 11
    domain.check_rest_period(member["id"], prospective)             # 12
    domain.check_seat_capacity(shift["id"], unit)                   # 15
    domain.check_flsa_cap(member["id"], shift_date, hours)          # 16

    assignment = db.new(
        {
            "duty_shift_id": shift["id"],
            "firefighter_id": member["id"],
            "apparatus_id": unit["id"],
            "source_offer_id": None,
            "relieved_by_leave_request_id": None,
            "assignment_type": assignment_type,
            "seat_certification": seat_certification,
            "scheduled_hours": calc.num(hours),
            "actual_hours": None,
            "projected_premium_cents": 0,
            "status": "SCHEDULED",
        }
    )
    db.shift_assignments[assignment["id"]] = assignment

    vacancy = _match_vacancy(shift["id"], unit["id"], seat_certification)
    if vacancy is not None:
        vacancy["status"] = "FILLED"
        vacancy["filled_by_assignment_id"] = assignment["id"]
        db.touch(vacancy)

    domain.recompute_member_work_periods(member["id"])
    domain.recompute_shift(shift)
    station = domain.station_of_shift(shift)
    if station is not None:
        domain.recompute_station(station)
    return created_object(assignment)


@bp.route("/fire-ops/shift-assignments/<shift_assignment_id>", methods=["GET"])
def get_assignment(shift_assignment_id):
    authenticate(ALL_ROLES)
    assignment = domain.require(
        db.shift_assignments, shift_assignment_id, "ERR_RESOURCE_NOT_FOUND"
    )
    return ok_object(assignment)


@bp.route("/fire-ops/shift-assignments", methods=["GET"])
def list_assignments():
    authenticate(ALL_ROLES)
    from routes.common import apply_filters, closure_priority_of, f, shift_date_of, sorted_by

    items = list(db.shift_assignments.values())
    items = apply_filters(
        items,
        {
            "duty_shift_id": f("duty_shift_id"),
            "firefighter_id": f("firefighter_id"),
            "apparatus_id": f("apparatus_id"),
            "source_offer_id": f("source_offer_id"),
            "relieved_by_leave_request_id": f("relieved_by_leave_request_id"),
            "assignment_type": f("assignment_type"),
            "status": f("status"),
        },
    )
    items = sorted_by(items, lambda e: (shift_date_of(e), closure_priority_of(e)))
    return ok_list(items)


@bp.route("/fire-ops/shift-assignments/<shift_assignment_id>/cancel", methods=["POST"])
def cancel_assignment(shift_assignment_id):
    authenticate(("CompanyOfficer",))
    body = V.parse_body()
    V.validate(body, [V.spec("reason", "string")])
    assignment = domain.require(
        db.shift_assignments, shift_assignment_id, "ERR_RESOURCE_NOT_FOUND"
    )
    if assignment["status"] != "SCHEDULED":
        raise ApiError("ERR_ASSIGNMENT_NOT_SCHEDULED")
    shift = db.duty_shifts.get(assignment["duty_shift_id"])
    if shift is None:
        raise ApiError("ERR_DUTY_SHIFT_NOT_FOUND")
    domain.require_active_shift(shift)

    if int(shift["assigned_headcount"]) - 1 < int(shift["leave_floor_headcount"]):
        raise ApiError("ERR_STAFFING_FLOOR_BREACH")

    assignment["status"] = "CANCELLED"
    db.touch(assignment)

    for vacancy in db.vacancies.values():
        if vacancy["filled_by_assignment_id"] == assignment["id"]:
            vacancy["filled_by_assignment_id"] = None
            vacancy["status"] = "OPEN"
            db.touch(vacancy)

    domain.recompute_member_work_periods(assignment["firefighter_id"])
    domain.recompute_shift(shift)
    station = domain.station_of_shift(shift)
    if station is not None:
        domain.recompute_station(station)
    return ok_object(assignment)
