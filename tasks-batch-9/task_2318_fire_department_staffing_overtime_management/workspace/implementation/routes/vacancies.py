"""Vacancies and the overtime hiring order dispatch."""

import calc
import domain
import validation as V
from auth import ALL_ROLES, authenticate
from envelope import created_object, ok_list, ok_object
from errors import ApiError
from flask import Blueprint
from store import add_minutes, db, iso

bp = Blueprint("vacancies", __name__)


@bp.route("/fire-ops/vacancies/<vacancy_id>", methods=["GET"])
def get_vacancy(vacancy_id):
    authenticate(ALL_ROLES)
    vacancy = domain.require(db.vacancies, vacancy_id, "ERR_VACANCY_NOT_FOUND")
    return ok_object(vacancy)


@bp.route("/fire-ops/vacancies", methods=["GET"])
def list_vacancies():
    authenticate(ALL_ROLES)
    from routes.common import apply_filters, closure_priority_of, f, shift_date_of, sorted_by

    items = list(db.vacancies.values())
    items = apply_filters(
        items,
        {
            "duty_shift_id": f("duty_shift_id"),
            "apparatus_id": f("apparatus_id"),
            "filled_by_assignment_id": f("filled_by_assignment_id"),
            "driver": f("driver"),
            "driver_source_id": f("driver_source_id"),
            "required_certification": f("required_certification"),
            "status": f("status"),
        },
    )
    items = sorted_by(
        items,
        lambda e: (shift_date_of(e), closure_priority_of(e), int(e["seat_index"])),
    )
    return ok_list(items)


@bp.route("/fire-ops/vacancies/<vacancy_id>/offer", methods=["POST"])
def dispatch_offer(vacancy_id):
    authenticate(("StaffingOfficer",))
    body = V.parse_body()
    data = V.validate(
        body,
        [
            V.spec("hiring_mode", "enum", values=V.HIRING_MODES),
            V.spec("offer_hours", "number"),
        ],
    )
    vacancy = domain.require(db.vacancies, vacancy_id, "ERR_VACANCY_NOT_FOUND")
    shift = db.duty_shifts.get(vacancy["duty_shift_id"])
    if shift is None:
        raise ApiError("ERR_DUTY_SHIFT_NOT_FOUND")

    hiring_mode = data["hiring_mode"]

    # 8 - state admissibility.
    if vacancy["status"] != "OPEN":
        raise ApiError("ERR_VACANCY_NOT_OFFERABLE")
    if vacancy["apparatus_id"] in (shift.get("closed_apparatus_ids") or []):
        raise ApiError("ERR_VACANCY_NOT_OFFERABLE")
    domain.require_active_shift(shift)

    # 9 - roster resolution.
    roster = domain.resolve_roster(
        shift, calc.ROSTER_TYPE_FOR_MODE[hiring_mode], vacancy["required_certification"]
    )
    if roster is None:
        raise ApiError("ERR_ROSTER_NOT_CONFIGURED")

    payable_hours = calc.effective_offer_hours(hiring_mode, data["offer_hours"])
    unit = db.apparatus.get(vacancy["apparatus_id"])
    if unit is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    candidate = domain.select_candidate(shift, vacancy, hiring_mode, payable_hours)
    prospective = calc.interval_for(shift["shift_date"], payable_hours)

    if candidate is None:
        domain.check_seat_capacity(shift["id"], unit)                       # 15
        raise ApiError("ERR_NO_ELIGIBLE_CANDIDATE")                         # 17

    _hours, fatigue = domain.check_rest_period(candidate["id"], prospective)  # 12
    domain.check_seat_capacity(shift["id"], unit)                             # 15

    effective_rate_cents, effective_hours, projected_cost_cents = calc.price_offer(
        candidate["hourly_rate_cents"],
        vacancy["required_certification"],
        hiring_mode,
        payable_hours,
        fatigue,
    )

    station = domain.station_of_shift(shift)
    if hiring_mode != "MANDATORY_HOLDOVER" and station is not None:
        prospective_total = (
            int(station["ot_actual_cents"])
            + int(station["ot_committed_cents"])
            + projected_cost_cents
        )
        if prospective_total > int(station["fiscal_ot_budget_cents"]):
            raise ApiError("ERR_OT_BUDGET_WOULD_EXCEED")                    # 18

    mandated = hiring_mode == "MANDATORY_HOLDOVER"
    offer = db.new(
        {
            "vacancy_id": vacancy["id"],
            "firefighter_id": candidate["id"],
            "roster_id": roster["id"],
            "hiring_mode": hiring_mode,
            "offer_hours": effective_hours,
            "projected_cost_cents": projected_cost_cents,
            "expires_at": None
            if mandated
            else iso(add_minutes(db.clock, calc.OFFER_RESPONSE_WINDOW_MINUTES)),
            "status": "MANDATED" if mandated else "OFFERED",
        }
    )
    db.overtime_offers[offer["id"]] = offer

    roster["dispatch_count"] = int(roster["dispatch_count"]) + 1
    db.touch(roster)

    if not mandated:
        candidate["pending_offer_count"] = int(candidate["pending_offer_count"]) + 1
        db.touch(candidate)
        vacancy["status"] = "OFFERING"
        db.touch(vacancy)
    else:
        assignment = db.new(
            {
                "duty_shift_id": shift["id"],
                "firefighter_id": candidate["id"],
                "apparatus_id": vacancy["apparatus_id"],
                "source_offer_id": offer["id"],
                "relieved_by_leave_request_id": None,
                "assignment_type": "HOLDOVER",
                "seat_certification": vacancy["required_certification"],
                "scheduled_hours": effective_hours,
                "actual_hours": None,
                "projected_premium_cents": projected_cost_cents,
                "status": "SCHEDULED",
            }
        )
        db.shift_assignments[assignment["id"]] = assignment
        vacancy["status"] = "FILLED"
        vacancy["filled_by_assignment_id"] = assignment["id"]
        db.touch(vacancy)
        candidate["mandatory_holdover_count"] = (
            int(candidate["mandatory_holdover_count"]) + 1
        )
        db.touch(candidate)
        domain.recompute_member_work_periods(candidate["id"])
        domain.recompute_shift(shift)

    if station is not None:
        domain.recompute_station(station)
    return created_object(offer)
