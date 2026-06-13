"""SeatAssignment: create (initial seating), fetch, list."""
from flask import Blueprint, request

import db
import services
from errors import err
from helpers import (
    get_json_body,
    get_or_404,
    paginate,
    require_str,
    seat_assignment_view,
)
from middleware import get_auth, require_role
from response import success, success_list
from routes.subscriptions import _check_seat_window_conflict

bp = Blueprint("seat_assignments", __name__)

ALL_ROLES = {"BoxOfficeAgent", "AccountHolder", "FinanceClerk"}


@bp.route("/seat-assignments", methods=["POST"])
def create_seat_assignment():
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    body = get_json_body()
    subscription_id = require_str(body, "subscription_id")
    seat_id = require_str(body, "seat_id")
    with db.lock:
        sub = db.subscriptions.get(subscription_id)
        if sub is None:
            raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "subscription_id not found")
        seat = db.seats.get(seat_id)
        if seat is None:
            raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "seat_id not found")

        # Initial assignment is against a PENDING subscription.
        if sub["status"] != "PENDING":
            from routes.subscriptions import _state_error, SUB_TERMINAL

            _state_error(sub["status"], SUB_TERMINAL)

        # Window-overlap guard against existing ASSIGNED assignments on this seat.
        _check_seat_window_conflict(seat)

        sa = db.new_common()
        sa.update(
            {
                "subscription_id": subscription_id,
                "seat_id": seat_id,
                "assigned_price_cents": 0,
                "status": "ASSIGNED",
            }
        )
        db.seat_assignments[sa["id"]] = sa
        seat["status"] = "SOLD"
        db.touch(seat)
        db.touch(db.sections[seat["section_id"]])
        services.set_seat_count(sub)
        db.touch(sub)
        return success(seat_assignment_view(sa), 201)


@bp.route("/seat-assignments/<rid>", methods=["GET"])
def get_seat_assignment(rid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        row = get_or_404(db.seat_assignments, rid)
        return success(seat_assignment_view(row))


@bp.route("/seat-assignments", methods=["GET"])
def list_seat_assignments():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    subscription_id = request.args.get("subscription_id")
    seat_id = request.args.get("seat_id")
    status = request.args.get("status")
    with db.lock:
        rows = [
            sa
            for sa in db.seat_assignments.values()
            if (subscription_id is None or sa["subscription_id"] == subscription_id)
            and (seat_id is None or sa["seat_id"] == seat_id)
            and (status is None or sa["status"] == status)
        ]
        page, limit, offset, total = paginate(rows)
        return success_list([seat_assignment_view(r) for r in page], limit, offset, total)
