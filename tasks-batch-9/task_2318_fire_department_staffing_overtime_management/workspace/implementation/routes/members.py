"""Firefighters, availability changes and FLSA work periods."""

import calc
import domain
import validation as V
from auth import ALL_ROLES, authenticate
from envelope import created_object, ok_list, ok_object
from errors import ApiError
from flask import Blueprint
from store import db

bp = Blueprint("members", __name__)


# --------------------------------------------------------------- firefighters
@bp.route("/fire-ops/firefighters", methods=["POST"])
def create_firefighter():
    authenticate(("StaffingOfficer",))
    body = V.parse_body()
    data = V.validate(
        body,
        [
            V.spec("station_id", "id"),
            V.spec("full_name", "string"),
            V.spec("rank", "enum", values=V.RANKS),
            V.spec("platoon", "enum", values=V.PLATOONS),
            V.spec("seniority_rank", "integer", minimum=1),
            V.spec("kelly_day_cycle_position", "integer", minimum=1, maximum=8),
            V.spec("certifications", "array_enum", required=False,
                   values=V.CERTIFICATIONS, default=[]),
            V.spec("hourly_rate_cents", "integer", minimum=1),
            V.spec("acting_supervisor_id", "id", required=False, default=None),
            V.spec("employment_status", "enum", required=False,
                   values=V.EMPLOYMENT_STATUSES, default="ACTIVE"),
            V.spec("roster_standing", "enum", required=False,
                   values=V.ROSTER_STANDINGS, default="AVAILABLE"),
        ],
    )
    domain.require(db.stations, data["station_id"], "ERR_STATION_NOT_FOUND")
    if data["acting_supervisor_id"] is not None:
        domain.require(
            db.firefighters, data["acting_supervisor_id"], "ERR_FIREFIGHTER_NOT_FOUND"
        )
    for member in db.firefighters.values():
        if int(member["seniority_rank"]) == data["seniority_rank"]:
            raise ApiError(
                "ERR_INVALID_REQUEST", "seniority_rank must be unique department-wide."
            )

    member = db.new(
        {
            "station_id": data["station_id"],
            "acting_supervisor_id": data["acting_supervisor_id"],
            "full_name": data["full_name"],
            "rank": data["rank"],
            "platoon": data["platoon"],
            "seniority_rank": data["seniority_rank"],
            "kelly_day_cycle_position": data["kelly_day_cycle_position"],
            "certifications": list(data["certifications"] or []),
            "hourly_rate_cents": data["hourly_rate_cents"],
            "employment_status": data["employment_status"] or "ACTIVE",
            "roster_standing": data["roster_standing"] or "AVAILABLE",
            "voluntary_ot_hours_charged": 0,
            "mandatory_holdover_count": 0,
            "callback_count": 0,
            "ot_pass_count": 0,
            "pending_offer_count": 0,
        }
    )
    db.firefighters[member["id"]] = member
    domain.create_work_period(member["id"], db.today())
    return created_object(member)


@bp.route("/fire-ops/firefighters/<firefighter_id>", methods=["GET"])
def get_firefighter(firefighter_id):
    authenticate(ALL_ROLES)
    member = domain.require(db.firefighters, firefighter_id, "ERR_FIREFIGHTER_NOT_FOUND")
    return ok_object(member)


@bp.route("/fire-ops/firefighters", methods=["GET"])
def list_firefighters():
    authenticate(ALL_ROLES)
    from routes.common import apply_filters, f, sorted_by

    items = list(db.firefighters.values())
    items = apply_filters(
        items,
        {
            "station_id": f("station_id"),
            "acting_supervisor_id": f("acting_supervisor_id"),
            "platoon": f("platoon"),
            "rank": f("rank"),
            "employment_status": f("employment_status"),
            "roster_standing": f("roster_standing"),
        },
    )
    items = sorted_by(items, lambda e: (int(e["seniority_rank"]),))
    return ok_list(items)


@bp.route("/fire-ops/firefighters/<firefighter_id>/availability", methods=["POST"])
def set_availability(firefighter_id):
    authenticate(("StaffingOfficer",))
    body = V.parse_body()
    data = V.validate(
        body,
        [
            V.spec("expected_firefighter_version", "integer"),
            V.spec("effective_date", "date"),
            V.spec("employment_status", "enum", required=False,
                   values=V.EMPLOYMENT_STATUSES, default=None),
            V.spec("roster_standing", "enum", required=False,
                   values=V.ROSTER_STANDINGS, default=None),
        ],
    )
    member = domain.require(db.firefighters, firefighter_id, "ERR_FIREFIGHTER_NOT_FOUND")
    if data["expected_firefighter_version"] != int(member["version"]):
        raise ApiError("ERR_STALE_VERSION")

    effective = data["effective_date"]
    new_status = data["employment_status"]
    new_standing = data["roster_standing"]

    touched_shifts = {}
    touched_stations = {}

    if new_status is not None:
        member["employment_status"] = new_status
        if new_status == "INJURY_LEAVE":
            for asg in domain.assignments_of_member(firefighter_id, ("SCHEDULED",)):
                shift = db.duty_shifts.get(asg["duty_shift_id"])
                if shift is None or shift["shift_date"] < effective:
                    continue
                asg["status"] = "CANCELLED"
                db.touch(asg)
                for vacancy in db.vacancies.values():
                    if vacancy["filled_by_assignment_id"] == asg["id"]:
                        vacancy["filled_by_assignment_id"] = None
                        vacancy["status"] = "OPEN"
                        db.touch(vacancy)
                domain.create_vacancy(
                    shift,
                    asg["apparatus_id"],
                    "INJURY",
                    firefighter_id,
                    asg["seat_certification"],
                    domain.next_seat_index(shift["id"], asg["apparatus_id"]),
                )
                touched_shifts[shift["id"]] = shift
        elif new_status == "ACTIVE":
            for vacancy in list(db.vacancies.values()):
                if vacancy["status"] != "OPEN":
                    continue
                if vacancy["driver"] != "INJURY":
                    continue
                if vacancy["driver_source_id"] != firefighter_id:
                    continue
                shift = db.duty_shifts.get(vacancy["duty_shift_id"])
                if shift is None or shift["shift_date"] < effective:
                    continue
                vacancy["status"] = "CANCELLED"
                db.touch(vacancy)
                touched_shifts[shift["id"]] = shift

    if new_standing is not None:
        member["roster_standing"] = new_standing
        if new_standing == "AVAILABLE":
            member["ot_pass_count"] = 0

    db.touch(member)
    domain.recompute_member_work_periods(firefighter_id)
    for shift in touched_shifts.values():
        domain.recompute_shift(shift)
        station = domain.station_of_shift(shift)
        if station is not None:
            touched_stations[station["id"]] = station
    for station in touched_stations.values():
        domain.recompute_station(station)
    return ok_object(member)


# --------------------------------------------------------------- work periods
@bp.route("/fire-ops/work-periods/<work_period_id>", methods=["GET"])
def get_work_period(work_period_id):
    authenticate(ALL_ROLES)
    wp = domain.require(db.work_periods, work_period_id, "ERR_RESOURCE_NOT_FOUND")
    return ok_object(wp)


@bp.route("/fire-ops/work-periods", methods=["GET"])
def list_work_periods():
    authenticate(ALL_ROLES)
    from routes.common import apply_filters, f, sorted_by

    items = list(db.work_periods.values())
    items = apply_filters(
        items, {"firefighter_id": f("firefighter_id"), "status": f("status")}
    )
    items = sorted_by(items, lambda e: (e["period_start_date"],))
    return ok_list(items)


@bp.route("/fire-ops/work-periods/<work_period_id>/hour-adjustment", methods=["POST"])
def hour_adjustment(work_period_id):
    authenticate(("PayrollAnalyst",))
    body = V.parse_body()
    data = V.validate(
        body,
        [
            V.spec("adjustment_hours", "number"),
            V.spec("adjustment_basis", "enum", values=V.ADJUSTMENT_BASES),
            V.spec("reason", "string"),
        ],
    )
    wp = domain.require(db.work_periods, work_period_id, "ERR_RESOURCE_NOT_FOUND")
    hours = float(data["adjustment_hours"])

    if data["adjustment_basis"] == "SCHEDULED":
        if float(wp["scheduled_hours"] or 0) + hours > calc.FLSA_MAX_PERIOD_HOURS:
            raise ApiError("ERR_FLSA_WORK_PERIOD_CAP_EXCEEDED")
        wp["adjusted_scheduled_hours"] = calc.num(
            float(wp["adjusted_scheduled_hours"] or 0) + hours
        )
    else:
        wp["adjusted_worked_hours"] = calc.num(
            float(wp["adjusted_worked_hours"] or 0) + hours
        )

    db.touch(wp)
    domain.recompute_work_period(wp)
    return ok_object(wp)
