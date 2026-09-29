"""Overtime offers: reads and the member's response."""

import calc
import domain
import validation as V
from auth import ALL_ROLES, authenticate
from envelope import ok_list, ok_object
from errors import ApiError
from flask import Blueprint
from store import db

bp = Blueprint("offers", __name__)


@bp.route("/fire-ops/overtime-offers/<overtime_offer_id>", methods=["GET"])
def get_offer(overtime_offer_id):
    authenticate(ALL_ROLES)
    offer = domain.require(db.overtime_offers, overtime_offer_id, "ERR_OFFER_NOT_FOUND")
    return ok_object(offer)


@bp.route("/fire-ops/overtime-offers", methods=["GET"])
def list_offers():
    authenticate(ALL_ROLES)
    from routes.common import apply_filters, f, sorted_by

    items = list(db.overtime_offers.values())
    items = apply_filters(
        items,
        {
            "vacancy_id": f("vacancy_id"),
            "firefighter_id": f("firefighter_id"),
            "roster_id": f("roster_id"),
            "hiring_mode": f("hiring_mode"),
            "status": f("status"),
        },
    )
    items = sorted_by(items, lambda e: ())
    return ok_list(items)


@bp.route("/fire-ops/overtime-offers/<overtime_offer_id>/response", methods=["POST"])
def respond(overtime_offer_id):
    user_id, _role = authenticate(("Firefighter",))
    body = V.parse_body()
    data = V.validate(body, [V.spec("response", "enum", values=V.OFFER_RESPONSES)])
    offer = domain.require(db.overtime_offers, overtime_offer_id, "ERR_OFFER_NOT_FOUND")
    if user_id != offer["firefighter_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if offer["status"] != "OFFERED":
        raise ApiError("ERR_OFFER_NOT_PENDING")

    vacancy = db.vacancies.get(offer["vacancy_id"])
    if vacancy is None:
        raise ApiError("ERR_VACANCY_NOT_FOUND")
    shift = db.duty_shifts.get(vacancy["duty_shift_id"])
    if shift is None:
        raise ApiError("ERR_DUTY_SHIFT_NOT_FOUND")
    domain.require_active_shift(shift)

    member = db.firefighters.get(offer["firefighter_id"])
    station = domain.station_of_shift(shift)

    if data["response"] == "DECLINE":
        domain.charge_pass(offer, "DECLINED")
        domain.recompute_shift(shift)
        db.touch(shift)
        if station is not None:
            domain.recompute_station(station)
        return ok_object(offer)

    unit = db.apparatus.get(vacancy["apparatus_id"])
    if unit is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    hours = offer["offer_hours"]
    required_certification = vacancy["required_certification"]

    # 9 - the member must still hold the specialty.
    if required_certification != "NONE" and required_certification not in (
        member.get("certifications") or []
    ):
        raise ApiError("ERR_CERTIFICATION_NOT_HELD")

    prospective = calc.interval_for(shift["shift_date"], hours)
    domain.check_double_booking(member["id"], prospective)          # 11
    domain.check_rest_period(member["id"], prospective)             # 12
    domain.check_seat_capacity(shift["id"], unit)                   # 15
    domain.check_flsa_cap(member["id"], shift["shift_date"], hours)  # 16

    offer["status"] = "ACCEPTED"
    db.touch(offer)

    assignment_type = "CALLBACK" if offer["hiring_mode"] == "CALLBACK" else "OVERTIME"
    assignment = db.new(
        {
            "duty_shift_id": shift["id"],
            "firefighter_id": member["id"],
            "apparatus_id": vacancy["apparatus_id"],
            "source_offer_id": offer["id"],
            "relieved_by_leave_request_id": None,
            "assignment_type": assignment_type,
            "seat_certification": required_certification,
            "scheduled_hours": hours,
            "actual_hours": None,
            "projected_premium_cents": int(offer["projected_cost_cents"]),
            "status": "SCHEDULED",
        }
    )
    db.shift_assignments[assignment["id"]] = assignment

    vacancy["status"] = "FILLED"
    vacancy["filled_by_assignment_id"] = assignment["id"]
    db.touch(vacancy)

    if offer["hiring_mode"] == "CALLBACK":
        member["callback_count"] = int(member["callback_count"]) + 1
    else:
        member["voluntary_ot_hours_charged"] = calc.num(
            float(member["voluntary_ot_hours_charged"] or 0) + float(hours)
        )
    member["ot_pass_count"] = 0
    member["pending_offer_count"] = max(0, int(member["pending_offer_count"]) - 1)
    db.touch(member)

    domain.recompute_member_work_periods(member["id"])
    domain.recompute_shift(shift)
    db.touch(shift)
    if station is not None:
        domain.recompute_station(station)
    return ok_object(offer)
