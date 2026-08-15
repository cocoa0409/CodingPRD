from flask import Blueprint, request

from db import DB
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_already_terminal,
    err_case_not_open, err_invalid_dates, err_housing_overlap, err_cap_exceeded,
    err_nights_limit, err_forbidden,
)
from middleware import get_actor, require_role, check_employee_owns_case
from response import success_object, success_list
from serializers import serialize_booking
from util import (
    require_fields, require_enum, require_string, require_positive_int,
    parse_datetime_field, get_pagination,
)
from services.caps import remaining_headroom
from services.ledger import touch_entity, commit, release, pay

bp = Blueprint("service_bookings", __name__)

ALL_ROLES = ["MobilityCoordinator", "FinanceSpecialist", "ProgramManager", "Employee", "Vendor"]

TERMINAL = {"COMPLETED", "CANCELLED"}
KINDS = {"TEMP_HOUSING", "TRAVEL"}


def _get_or_404(id):
    b = DB.service_bookings.get(id)
    if b is None:
        raise err_not_found("ServiceBooking not found")
    return b


@bp.route("/service-bookings", methods=["POST"])
def create_booking():
    actor = get_actor()
    require_role(actor, ["Employee", "MobilityCoordinator"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["case_id", "kind", "start_date", "amount_cents"])
    case_id = require_string(payload, "case_id")
    kind = require_enum(payload, "kind", KINDS)
    start_date = parse_datetime_field(payload, "start_date", required=True)
    end_date = parse_datetime_field(payload, "end_date", required=False)
    amount_cents = require_positive_int(payload, "amount_cents")

    with DB.lock:
        case = DB.cases.get(case_id)
        if case is None:
            raise err_not_found("Case not found")
        # ownership: Employee may only book against own case
        if actor.role == "Employee":
            check_employee_owns_case(actor, case)
        if case["status"] != "IN_PROGRESS":
            raise err_case_not_open("Case is not IN_PROGRESS")
        policy = DB.policies.get(case["policy_id"])

        if kind == "TEMP_HOUSING":
            if end_date is None:
                raise err_invalid_request("end_date is required for TEMP_HOUSING")
            if end_date <= start_date:
                raise err_invalid_dates("end_date must be after start_date")
            nights = (end_date.date() - start_date.date()).days
            if nights < 1:
                raise err_invalid_dates("TEMP_HOUSING stay must be at least 1 night")
            # overlap: half-open [start, end) vs existing non-CANCELLED TEMP_HOUSING of same case
            for other in DB.service_bookings.values():
                if (
                    other["case_id"] == case_id
                    and other["kind"] == "TEMP_HOUSING"
                    and other["status"] != "CANCELLED"
                ):
                    o_start = other["start_date"]
                    o_end = other["end_date"]
                    if o_start is None or o_end is None:
                        continue
                    # overlap iff start < o_end AND o_start < end  (touching is allowed)
                    if start_date < o_end and o_start < end_date:
                        raise err_housing_overlap("TEMP_HOUSING overlaps existing booking")
            if nights > policy["temp_housing_max_nights"]:
                raise err_nights_limit("TEMP_HOUSING nights exceed policy max")
            total_cents = nights * amount_cents
        else:  # TRAVEL
            if end_date is None:
                end_date = start_date
            else:
                if end_date < start_date:
                    raise err_invalid_dates("end_date must not be before start_date")
            nights = 0
            total_cents = amount_cents

        # cap headroom against the corresponding component
        component = "TEMP_HOUSING" if kind == "TEMP_HOUSING" else "TRAVEL"
        headroom = remaining_headroom(case, policy, component)
        if total_cents > headroom:
            raise err_cap_exceeded("Booking exceeds remaining cap headroom")

        now = DB.now()
        b = {
            "id": DB.new_id(),
            "case_id": case_id,
            "kind": kind,
            "start_date": start_date,
            "end_date": end_date,
            "amount_cents": amount_cents,
            "nights": nights,
            "total_cents": total_cents,
            "status": "HELD",
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": DB.next_seq(),
        }
        DB.service_bookings[b["id"]] = b
        return success_object(serialize_booking(b), status=201)


@bp.route("/service-bookings/<id>", methods=["GET"])
def get_booking(id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    with DB.lock:
        b = _get_or_404(id)
        return success_object(serialize_booking(b))


@bp.route("/relocation-cases/<case_id>/service-bookings", methods=["GET"])
def list_case_bookings(case_id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    limit, offset = get_pagination(request.args)
    kind = request.args.get("kind")
    status = request.args.get("status")
    with DB.lock:
        case = DB.cases.get(case_id)
        if case is None:
            raise err_not_found("Case not found")
        items = [b for b in DB.service_bookings.values() if b["case_id"] == case_id]
        if kind is not None:
            items = [b for b in items if b["kind"] == kind]
        if status is not None:
            items = [b for b in items if b["status"] == status]
        items.sort(key=lambda b: (b["created_at"], b.get("_seq", 0)))
        total_count = len(items)
        page = items[offset:offset + limit]
        return success_list([serialize_booking(b) for b in page], limit, offset, total_count)


@bp.route("/service-bookings/<id>/confirm", methods=["POST"])
def confirm_booking(id):
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    with DB.lock:
        b = _get_or_404(id)
        if b["status"] in TERMINAL:
            raise err_already_terminal("Booking is terminal")
        if b["status"] != "HELD":
            raise err_invalid_state("Booking is not HELD")
        case = DB.cases.get(b["case_id"])
        if case is None or case["status"] != "IN_PROGRESS":
            raise err_case_not_open("Case is not IN_PROGRESS")
        b["status"] = "CONFIRMED"
        touch_entity(b)
        commit(case, b["total_cents"])
        return success_object(serialize_booking(b))


@bp.route("/service-bookings/<id>/cancel", methods=["POST"])
def cancel_booking(id):
    actor = get_actor()
    require_role(actor, ["Employee", "MobilityCoordinator"])
    with DB.lock:
        b = _get_or_404(id)
        if b["status"] in TERMINAL:
            raise err_already_terminal("Booking is terminal")
        if b["status"] not in ("HELD", "CONFIRMED"):
            raise err_invalid_state("Booking cannot be cancelled from this state")
        case = DB.cases.get(b["case_id"])
        if actor.role == "Employee":
            check_employee_owns_case(actor, case)
        was_confirmed = b["status"] == "CONFIRMED"
        b["status"] = "CANCELLED"
        touch_entity(b)
        if was_confirmed and case is not None:
            release(case, b["total_cents"])
        return success_object(serialize_booking(b))


@bp.route("/service-bookings/<id>/complete", methods=["POST"])
def complete_booking(id):
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    with DB.lock:
        b = _get_or_404(id)
        if b["status"] in TERMINAL:
            raise err_already_terminal("Booking is terminal")
        if b["status"] != "CONFIRMED":
            raise err_invalid_state("Booking is not CONFIRMED")
        case = DB.cases.get(b["case_id"])
        if case is None:
            raise err_not_found("Case not found")
        b["status"] = "COMPLETED"
        touch_entity(b)
        pay(case, b["total_cents"], b["total_cents"])
        return success_object(serialize_booking(b))
