"""Duty shifts: open, publish, ops-run checkpoint, leave batch, closure, close-out."""

import calc
import domain
import validation as V
from auth import ALL_ROLES, authenticate
from envelope import created_object, ok_list, ok_object, ok_raw
from errors import ApiError
from flask import Blueprint
from store import db, order_key

bp = Blueprint("duty_shifts", __name__)


@bp.route("/fire-ops/duty-shifts", methods=["POST"])
def create_duty_shift():
    authenticate(("StaffingOfficer",))
    body = V.parse_body()
    data = V.validate(
        body,
        [
            V.spec("station_id", "id"),
            V.spec("shift_date", "date"),
            V.spec("platoon", "enum", values=V.PLATOONS),
        ],
    )
    domain.require(db.stations, data["station_id"], "ERR_STATION_NOT_FOUND")
    for shift in db.duty_shifts.values():
        if (
            shift["station_id"] == data["station_id"]
            and shift["shift_date"] == data["shift_date"]
        ):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "A duty shift already exists for this station and date.",
            )
    if calc.platoon_on_duty(data["shift_date"]) != data["platoon"]:
        raise ApiError("ERR_PLATOON_ROTATION_VIOLATION")

    shift = db.new(
        {
            "station_id": data["station_id"],
            "shift_date": data["shift_date"],
            "platoon": data["platoon"],
            "status": "DRAFT",
            "required_staffing": 0,
            "assigned_headcount": 0,
            "certification_gap_count": 0,
            "staffing_gap": 0,
            "leave_floor_headcount": 0,
            "staffing_posture": "FULLY_STAFFED",
            "closed_apparatus_ids": [],
            "open_vacancy_count": 0,
            "ops_run_index": 0,
        }
    )
    db.duty_shifts[shift["id"]] = shift
    domain.recompute_shift(shift, auto_transition=False)
    db.untouch(shift)
    return created_object(shift)


@bp.route("/fire-ops/duty-shifts/<duty_shift_id>", methods=["GET"])
def get_duty_shift(duty_shift_id):
    authenticate(ALL_ROLES)
    shift = domain.require(db.duty_shifts, duty_shift_id, "ERR_DUTY_SHIFT_NOT_FOUND")
    return ok_object(shift)


@bp.route("/fire-ops/duty-shifts", methods=["GET"])
def list_duty_shifts():
    authenticate(ALL_ROLES)
    from routes.common import apply_filters, f, sorted_by

    items = list(db.duty_shifts.values())
    items = apply_filters(
        items,
        {
            "station_id": f("station_id"),
            "platoon": f("platoon"),
            "status": f("status"),
            "shift_date": f("shift_date"),
            "staffing_posture": f("staffing_posture"),
        },
    )
    items = sorted_by(items, lambda e: (e["shift_date"], e["platoon"]))
    return ok_list(items)


@bp.route("/fire-ops/duty-shifts/<duty_shift_id>/publish", methods=["POST"])
def publish(duty_shift_id):
    authenticate(("StaffingOfficer",))
    shift = domain.require(db.duty_shifts, duty_shift_id, "ERR_DUTY_SHIFT_NOT_FOUND")
    if shift["status"] != "DRAFT":
        raise ApiError("ERR_SHIFT_NOT_DRAFT")

    domain.generate_vacancies(shift)
    domain.recompute_shift(shift, auto_transition=False)
    shift["status"] = "HIRING" if shift["open_vacancy_count"] > 0 else "STAFFED"
    db.touch(shift)
    return ok_object(shift)


@bp.route("/fire-ops/duty-shifts/<duty_shift_id>/staffing-run", methods=["POST"])
def staffing_run(duty_shift_id):
    authenticate(("StaffingOfficer",))
    shift = domain.require(db.duty_shifts, duty_shift_id, "ERR_DUTY_SHIFT_NOT_FOUND")
    domain.require_active_shift(shift)

    shift["ops_run_index"] = int(shift["ops_run_index"]) + 1
    db.touch(shift)

    # Step 1 - expire due offers.
    now = db.clock
    due = []
    for offer in domain.offers_of_shift(shift["id"], ("OFFERED",)):
        expires_at = offer.get("expires_at")
        if not expires_at:
            continue
        parsed = V.parse_datetime(expires_at)
        if parsed is not None and parsed <= now:
            due.append((expires_at, order_key(offer), offer))
    due.sort(key=lambda row: (row[0], row[1]))
    for _stamp, _key, offer in due:
        domain.charge_pass(offer, "EXPIRED")

    # Step 2 - recompute the staffing picture.
    domain.recompute_shift(shift)

    # Step 3 - requeue floor-denied leave when the shift is whole again.
    if shift["staffing_posture"] == "FULLY_STAFFED":
        for leave_request in domain.leave_requests_of_shift(shift["id"], ("DENIED",)):
            leave_request["status"] = "QUEUED"
            leave_request["denial_reason"] = None
            db.touch(leave_request)

    # Step 4 - recompute the station's budget posture.
    station = domain.station_of_shift(shift)
    if station is not None:
        domain.recompute_station(station)

    return ok_object(shift)


@bp.route("/fire-ops/duty-shifts/<duty_shift_id>/leave-adjudication", methods=["POST"])
def leave_adjudication(duty_shift_id):
    authenticate(("CompanyOfficer",))
    shift = domain.require(db.duty_shifts, duty_shift_id, "ERR_DUTY_SHIFT_NOT_FOUND")
    domain.require_active_shift(shift)

    domain.recompute_shift(shift)
    floor = int(shift["leave_floor_headcount"])
    running = int(shift["assigned_headcount"])

    queued = domain.leave_requests_of_shift(shift["id"], ("QUEUED",))

    def rank(leave_request):
        member = db.firefighters.get(leave_request["firefighter_id"])
        seniority = int(member["seniority_rank"]) if member else 0
        return (
            calc.LEAVE_TYPE_PRIORITY.get(leave_request["leave_type"], 99),
            seniority,
        ) + order_key(leave_request)

    queued.sort(key=rank)

    approved_ids = []
    denied_ids = []
    created_vacancy_count = 0
    members_touched = set()

    for index, leave_request in enumerate(queued, start=1):
        leave_request["decision_order_index"] = index
        db.touch(leave_request)
        seat = None
        for asg in domain.assignments_of_shift(shift["id"], ("SCHEDULED",)):
            if asg["firefighter_id"] == leave_request["firefighter_id"]:
                seat = asg
                break
        releases = 1 if seat is not None else 0
        discretionary = leave_request["leave_type"] not in calc.NON_DISCRETIONARY

        if discretionary and running - releases < floor:
            leave_request["status"] = "DENIED"
            leave_request["denial_reason"] = "STAFFING_FLOOR"
            denied_ids.append(leave_request["id"])
            continue

        leave_request["status"] = "APPROVED"
        leave_request["denial_reason"] = None
        approved_ids.append(leave_request["id"])
        if seat is not None:
            seat["status"] = "RELIEVED"
            seat["relieved_by_leave_request_id"] = leave_request["id"]
            db.touch(seat)
            vacancy = domain.create_vacancy(
                shift,
                seat["apparatus_id"],
                "LEAVE",
                leave_request["id"],
                seat["seat_certification"],
                domain.next_seat_index(shift["id"], seat["apparatus_id"]),
            )
            leave_request["backfill_vacancy_id"] = vacancy["id"]
            created_vacancy_count += 1
            running -= 1
        members_touched.add(leave_request["firefighter_id"])

    for firefighter_id in members_touched:
        domain.recompute_member_work_periods(firefighter_id)

    domain.recompute_shift(shift)
    db.touch(shift)

    return ok_raw(
        {
            "duty_shift_id": shift["id"],
            "leave_floor_headcount": floor,
            "considered_count": len(queued),
            "approved_count": len(approved_ids),
            "denied_count": len(denied_ids),
            "approved_leave_request_ids": approved_ids,
            "denied_leave_request_ids": denied_ids,
            "resulting_assigned_headcount": int(shift["assigned_headcount"]),
            "resulting_staffing_posture": shift["staffing_posture"],
            "created_vacancy_count": created_vacancy_count,
        }
    )


@bp.route("/fire-ops/duty-shifts/<duty_shift_id>/company-closure", methods=["POST"])
def company_closure(duty_shift_id):
    authenticate(("StaffingOfficer",))
    body = V.parse_body()
    data = V.validate(
        body,
        [
            V.spec("expected_duty_shift_version", "integer"),
            V.spec("justification", "string"),
        ],
    )
    shift = domain.require(db.duty_shifts, duty_shift_id, "ERR_DUTY_SHIFT_NOT_FOUND")
    if data["expected_duty_shift_version"] != int(shift["version"]):
        raise ApiError("ERR_STALE_VERSION")
    domain.require_active_shift(shift)

    if shift["staffing_posture"] != "CRITICAL":
        raise ApiError("ERR_CLOSURE_NOT_JUSTIFIED")
    company = domain.select_closure_company(shift)
    if company is None:
        raise ApiError("ERR_NO_CLOSURE_ELIGIBLE_COMPANY")

    closed = list(shift.get("closed_apparatus_ids") or [])
    closed.append(company["id"])
    shift["closed_apparatus_ids"] = closed
    db.touch(shift)

    for vacancy in domain.vacancies_of_shift(shift["id"], ("OPEN", "OFFERING")):
        if vacancy["apparatus_id"] != company["id"]:
            continue
        domain.cancel_vacancy_and_rescind(vacancy, "CLOSED_BY_COMPANY_CLOSURE")

    domain.recompute_shift(shift)
    station = domain.station_of_shift(shift)
    if station is not None:
        domain.recompute_station(station)
    return ok_object(shift)


@bp.route("/fire-ops/duty-shifts/<duty_shift_id>/complete", methods=["POST"])
def complete(duty_shift_id):
    authenticate(("PayrollAnalyst",))
    shift = domain.require(db.duty_shifts, duty_shift_id, "ERR_DUTY_SHIFT_NOT_FOUND")
    domain.require_active_shift(shift)
    if shift["shift_date"] > calc.date_str(db.today()):
        raise ApiError("ERR_SHIFT_NOT_ELAPSED")

    shift["status"] = "COMPLETED"
    db.touch(shift)

    members = set()
    premium_total = 0
    for asg in domain.assignments_of_shift(shift["id"]):
        members.add(asg["firefighter_id"])
        if asg["status"] != "SCHEDULED":
            continue
        asg["status"] = "WORKED"
        asg["actual_hours"] = asg["scheduled_hours"]
        db.touch(asg)
        if asg["assignment_type"] in ("OVERTIME", "HOLDOVER", "CALLBACK"):
            premium_total += int(asg["projected_premium_cents"] or 0)

    for vacancy in domain.vacancies_of_shift(shift["id"], ("OPEN", "OFFERING")):
        domain.cancel_vacancy_and_rescind(vacancy, "CANCELLED")

    station = domain.station_of_shift(shift)
    if station is not None:
        station["ot_actual_cents"] = int(station["ot_actual_cents"]) + premium_total
        db.touch(station)

    for firefighter_id in members:
        domain.recompute_member_work_periods(firefighter_id)

    successors = []
    for firefighter_id in sorted(members):
        periods = [
            wp for wp in db.work_periods.values() if wp["firefighter_id"] == firefighter_id
        ]
        periods.sort(key=order_key)
        for wp in periods:
            if wp["status"] != "OPEN":
                continue
            if wp["period_end_date"] > shift["shift_date"]:
                continue
            wp["status"] = "CLOSED"
            db.touch(wp)
            domain.recompute_work_period(wp)
            successors.append(
                (firefighter_id, calc.add_days(wp["period_end_date"], 1))
            )

    for firefighter_id, start in successors:
        successor = domain.create_work_period(firefighter_id, start)
        domain.recompute_work_period(successor)
        db.untouch(successor)

    if station is not None:
        domain.recompute_station(station)
    return ok_object(shift)
