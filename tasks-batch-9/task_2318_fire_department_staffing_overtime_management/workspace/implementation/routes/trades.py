"""Trade requests: propose, countersign, decide."""

import calc
import domain
import validation as V
from auth import ALL_ROLES, authenticate
from envelope import created_object, ok_list, ok_object
from errors import ApiError
from flask import Blueprint
from store import db

bp = Blueprint("trades", __name__)


def _check_trade_window(shift_date):
    start = calc.shift_start_instant(shift_date)
    lead_seconds = (start - db.clock).total_seconds()
    if lead_seconds < calc.TRADE_LEAD_TIME_HOURS * 3600:
        raise ApiError("ERR_TRADE_WINDOW_CLOSED")


def _requester_seat(trade):
    for asg in domain.assignments_of_shift(trade["duty_shift_id"], ("SCHEDULED",)):
        if asg["firefighter_id"] == trade["requesting_firefighter_id"]:
            return asg
    return None


@bp.route("/fire-ops/trade-requests", methods=["POST"])
def create_trade_request():
    user_id, _role = authenticate(("Firefighter",))
    body = V.parse_body()
    data = V.validate(
        body,
        [
            V.spec("requesting_firefighter_id", "id"),
            V.spec("counterparty_firefighter_id", "id"),
            V.spec("duty_shift_id", "id"),
        ],
    )
    requester = domain.require(
        db.firefighters, data["requesting_firefighter_id"], "ERR_FIREFIGHTER_NOT_FOUND"
    )
    counterparty = domain.require(
        db.firefighters, data["counterparty_firefighter_id"], "ERR_FIREFIGHTER_NOT_FOUND"
    )
    shift = domain.require(db.duty_shifts, data["duty_shift_id"], "ERR_DUTY_SHIFT_NOT_FOUND")

    if user_id != requester["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if (
        requester["station_id"] != shift["station_id"]
        or counterparty["station_id"] != shift["station_id"]
    ):
        raise ApiError("ERR_STATION_SCOPE_MISMATCH")
    _check_trade_window(shift["shift_date"])

    trade = db.new(
        {
            "requesting_firefighter_id": requester["id"],
            "counterparty_firefighter_id": counterparty["id"],
            "duty_shift_id": shift["id"],
            "traded_assignment_id": None,
            "status": "PROPOSED",
            "revision_count": 0,
            "decided_by_user_id": None,
        }
    )
    db.trade_requests[trade["id"]] = trade
    return created_object(trade)


@bp.route("/fire-ops/trade-requests/<trade_request_id>", methods=["GET"])
def get_trade_request(trade_request_id):
    authenticate(ALL_ROLES)
    trade = domain.require(db.trade_requests, trade_request_id, "ERR_TRADE_REQUEST_NOT_FOUND")
    return ok_object(trade)


@bp.route("/fire-ops/trade-requests", methods=["GET"])
def list_trade_requests():
    authenticate(ALL_ROLES)
    from routes.common import apply_filters, f, sorted_by

    items = list(db.trade_requests.values())
    items = apply_filters(
        items,
        {
            "requesting_firefighter_id": f("requesting_firefighter_id"),
            "counterparty_firefighter_id": f("counterparty_firefighter_id"),
            "duty_shift_id": f("duty_shift_id"),
            "traded_assignment_id": f("traded_assignment_id"),
            "status": f("status"),
        },
    )
    items = sorted_by(items, lambda e: ())
    return ok_list(items)


@bp.route("/fire-ops/trade-requests/<trade_request_id>/countersign", methods=["POST"])
def countersign(trade_request_id):
    user_id, _role = authenticate(("Firefighter",))
    trade = domain.require(db.trade_requests, trade_request_id, "ERR_TRADE_REQUEST_NOT_FOUND")
    if user_id != trade["counterparty_firefighter_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if trade["status"] != "PROPOSED":
        raise ApiError("ERR_TRADE_STATE_INVALID")

    counterparty = db.firefighters.get(trade["counterparty_firefighter_id"])
    shift = db.duty_shifts.get(trade["duty_shift_id"])
    if counterparty is None:
        raise ApiError("ERR_FIREFIGHTER_NOT_FOUND")
    if shift is None:
        raise ApiError("ERR_DUTY_SHIFT_NOT_FOUND")

    shift_date = shift["shift_date"]
    seat = _requester_seat(trade)
    seat_certification = seat["seat_certification"] if seat else "NONE"
    seat_hours = seat["scheduled_hours"] if seat else calc.SHIFT_HOURS

    # 9 - cross-entity coherence.
    if counterparty["employment_status"] != "ACTIVE":
        raise ApiError("ERR_STATION_SCOPE_MISMATCH")
    if seat_certification != "NONE" and seat_certification not in (
        counterparty.get("certifications") or []
    ):
        raise ApiError("ERR_CERTIFICATION_NOT_HELD")

    # 10 - rotation compatibility.
    if counterparty["platoon"] != calc.platoon_on_duty(shift_date):
        raise ApiError("ERR_PLATOON_ROTATION_VIOLATION")
    if calc.is_kelly_day(counterparty, shift_date):
        raise ApiError("ERR_KELLY_DAY_CONFLICT")

    # 11 - double booking against the shift's whole duty period.
    prospective = calc.interval_for(shift_date, calc.SHIFT_HOURS)
    domain.check_double_booking(counterparty["id"], prospective)

    # 13 - lead time.
    _check_trade_window(shift_date)

    # 16 - FLSA work-period cap.
    domain.check_flsa_cap(counterparty["id"], shift_date, seat_hours)

    trade["status"] = "COUNTERSIGNED"
    db.touch(trade)
    return ok_object(trade)


@bp.route("/fire-ops/trade-requests/<trade_request_id>/decision", methods=["POST"])
def decide(trade_request_id):
    user_id, _role = authenticate(("CompanyOfficer",))
    body = V.parse_body()
    data = V.validate(
        body,
        [
            V.spec("decision", "enum", values=V.TRADE_DECISIONS),
            V.spec("note", "string", required=False, default=None, nonempty=False),
        ],
    )
    trade = domain.require(db.trade_requests, trade_request_id, "ERR_TRADE_REQUEST_NOT_FOUND")
    if user_id in (
        trade["requesting_firefighter_id"],
        trade["counterparty_firefighter_id"],
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if trade["status"] != "COUNTERSIGNED":
        raise ApiError("ERR_TRADE_STATE_INVALID")

    decision = data["decision"]
    if decision == "REJECT":
        trade["status"] = "REJECTED"
        trade["decided_by_user_id"] = user_id
        db.touch(trade)
        return ok_object(trade)

    if decision == "RETURN_FOR_REVISION":
        trade["status"] = "PROPOSED"
        trade["revision_count"] = int(trade["revision_count"]) + 1
        trade["decided_by_user_id"] = user_id
        db.touch(trade)
        return ok_object(trade)

    seat = _requester_seat(trade)
    if seat is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_SCHEDULED")

    shift = db.duty_shifts.get(trade["duty_shift_id"])
    requester_id = trade["requesting_firefighter_id"]
    counterparty_id = trade["counterparty_firefighter_id"]

    trade["status"] = "APPROVED"
    trade["traded_assignment_id"] = seat["id"]
    trade["decided_by_user_id"] = user_id
    db.touch(trade)

    seat["firefighter_id"] = counterparty_id
    seat["assignment_type"] = "TRADE"
    seat["projected_premium_cents"] = 0
    db.touch(seat)

    domain.recompute_member_work_periods(requester_id)
    domain.recompute_member_work_periods(counterparty_id)
    if shift is not None:
        domain.recompute_shift(shift)
        station = domain.station_of_shift(shift)
        if station is not None:
            domain.recompute_station(station)
    return ok_object(trade)
