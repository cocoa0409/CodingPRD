"""GroupBooking endpoints (PRD §3.5)."""
from flask import Blueprint, request

from db import db, new_record, touch
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_SHOW_CAPACITY_EXCEEDED,
    ERR_VALIDATION,
)
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_body,
    require_string,
    require_int,
    parse_pagination,
    paginate,
)
from services.lookups import get_show, get_group_booking
from services.serialize import group_booking_view
from services.calculations import group_deposit, group_balance
from services.show_logic import (
    recompute_seats_sold,
    bubble_after_recompute,
    capacity_of,
)

bp = Blueprint("group_bookings", __name__)


@bp.route("/group-bookings", methods=["POST"])
def create_group_booking():
    _, role = authenticate()
    require_role(role, {"GroupSalesAgent"})
    body = get_body()
    require_string(body, "show_event_id")
    show_id = body["show_event_id"]
    organization_name = require_string(body, "organization_name")
    student_count = require_int(body, "student_count")
    chaperone_count = require_int(body, "chaperone_count")

    with db.lock:
        show = get_show(show_id)
        # Field-range checks.
        if student_count < 1:
            raise err(ERR_VALIDATION, "student_count must be >= 1")
        if chaperone_count < 0:
            raise err(ERR_VALIDATION, "chaperone_count must be >= 0")

        total_seats = student_count + chaperone_count
        deposit = group_deposit(show, student_count, chaperone_count)

        rec = new_record(with_version=True)
        rec.update({
            "show_event_id": show_id,
            "organization_name": organization_name,
            "student_count": student_count,
            "chaperone_count": chaperone_count,
            "actual_student_count": None,
            "actual_chaperone_count": None,
            "total_seats": total_seats,
            "deposit_cents": deposit,
            "balance_cents": None,
            "status": "REQUESTED",
        })
        db.group_bookings[rec["id"]] = rec
    return success(group_booking_view(rec), status=201)


@bp.route("/group-bookings", methods=["GET"])
def list_group_bookings():
    _, role = authenticate()
    require_role(role, {"GroupSalesAgent", "BoxOfficeOperator"})
    limit, offset = parse_pagination()
    show_event_id = request.args.get("show_event_id")
    status = request.args.get("status")
    with db.lock:
        records = list(db.group_bookings.values())
        if show_event_id is not None:
            records = [g for g in records if g["show_event_id"] == show_event_id]
        if status is not None:
            records = [g for g in records if g["status"] == status]
        page, meta = paginate(records, limit, offset)
        data = [group_booking_view(g) for g in page]
    return success(data, status=200, pagination=meta)


@bp.route("/group-bookings/<gid>", methods=["GET"])
def get_one_group_booking(gid):
    _, role = authenticate()
    require_role(role, {"GroupSalesAgent"})
    with db.lock:
        g = get_group_booking(gid)
        return success(group_booking_view(g), status=200)


@bp.route("/group-bookings/<gid>/pay-deposit", methods=["POST"])
def pay_deposit(gid):
    _, role = authenticate()
    require_role(role, {"GroupSalesAgent"})
    with db.lock:
        g = get_group_booking(gid)
        # State (priority 5): must be REQUESTED.
        if g["status"] != "REQUESTED":
            raise err(ERR_INVALID_STATE, "Group booking is not REQUESTED")
        show = get_show(g["show_event_id"])
        # Linked show must be OPEN.
        if show["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "Linked show is not OPEN")
        # Capacity (priority 15): seats_sold + total_seats <= seated_capacity.
        if show["seats_sold"] + g["total_seats"] > capacity_of(show):
            raise err(ERR_SHOW_CAPACITY_EXCEEDED, "Show capacity exceeded for group block")
        g["status"] = "DEPOSIT_PAID"
        touch(g)
        # Reserve block: recompute seats_sold (now includes this group), bubble.
        recompute_seats_sold(show)
        bubble_after_recompute(show)
        touch(show)
        return success(group_booking_view(g), status=200)


@bp.route("/group-bookings/<gid>/confirm", methods=["POST"])
def confirm_group_booking(gid):
    _, role = authenticate()
    require_role(role, {"GroupSalesAgent"})
    body = get_body()
    actual_student = require_int(body, "actual_student_count")
    actual_chaperone = require_int(body, "actual_chaperone_count")
    with db.lock:
        g = get_group_booking(gid)
        # Permitted only from DEPOSIT_PAID.
        if g["status"] != "DEPOSIT_PAID":
            raise err(ERR_INVALID_STATE, "Group booking is not DEPOSIT_PAID")
        if actual_student < 0 or actual_chaperone < 0:
            raise err(ERR_VALIDATION, "actual head-counts must be >= 0")
        show = get_show(g["show_event_id"])
        g["actual_student_count"] = actual_student
        g["actual_chaperone_count"] = actual_chaperone
        g["balance_cents"] = group_balance(show, actual_student, actual_chaperone, g["deposit_cents"])
        g["status"] = "CONFIRMED"
        touch(g)
        return success(group_booking_view(g), status=200)


@bp.route("/group-bookings/<gid>/cancel", methods=["POST"])
def cancel_group_booking(gid):
    _, role = authenticate()
    require_role(role, {"GroupSalesAgent"})
    with db.lock:
        g = get_group_booking(gid)
        if g["status"] not in ("REQUESTED", "DEPOSIT_PAID"):
            raise err(ERR_INVALID_STATE, "Group booking not in a cancellable state")
        was_deposit_paid = g["status"] == "DEPOSIT_PAID"
        g["status"] = "CANCELLED"
        touch(g)
        if was_deposit_paid:
            # Release the reserved block.
            show = get_show(g["show_event_id"])
            recompute_seats_sold(show)
            bubble_after_recompute(show)
            touch(show)
        return success(group_booking_view(g), status=200)
