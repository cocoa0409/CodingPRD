"""Booking hub: create, fetch, list, confirm, cancel, close (PRD §3.2, §3.4, §3.8)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_STATE,
    ERR_PACKAGE_INACTIVE,
    ERR_CONTRACT_NOT_SIGNED,
    ERR_MODEL_RELEASE_REQUIRED,
)
from middleware import (
    require_auth, ROLE_CLIENT, ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN,
)
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_str, require_number, serialize, serialize_list,
    parse_pagination, paginate, order_by_created_at, assert_client_owns,
)
from services import calculations as calc
from services.common import (
    stamp_create, touch, recompute_total_fee, recompute_amount_paid_and_balance,
    contract_for_booking, active_schedule_for_booking, assignments_for_schedule,
)

bp = Blueprint("bookings", __name__)


def _find_booking_or_404(id):
    b = db.bookings.get(id)
    if b is None:
        raise APIError(ERR_NOT_FOUND, 404, "Booking not found")
    return b


@bp.post("/studio/bookings")
def create_booking():
    require_auth([ROLE_CLIENT, ROLE_STUDIO_ADMIN])
    body = get_body()
    client_id = require_str(body, "client_id")
    package_id = require_str(body, "package_id")
    lead_photographer_id = require_str(body, "lead_photographer_id")
    requested_shoot_hours = require_number(body, "requested_shoot_hours", gt=0)

    # Ownership (priority 4): a Client may only open a booking for itself.
    if request.headers.get("X-User-Role") == ROLE_CLIENT:
        # g.user_id already set by require_auth
        from flask import g
        if g.user_id != client_id:
            from errors import ERR_NOT_RESOURCE_OWNER
            raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Client may only book for itself")

    # Body FK existence (priority 5).
    client = db.clients.get(client_id)
    package = db.session_packages.get(package_id)
    photographer = db.photographers.get(lead_photographer_id)
    if client is None or package is None or photographer is None:
        raise APIError(ERR_INVALID_REFERENCE, 422, "Referenced entity does not exist")

    # Package must be bookable (priority 19).
    if not package["active"]:
        raise APIError(ERR_PACKAGE_INACTIVE, 422, "Package is not active")

    booking = {
        "client_id": client_id,
        "package_id": package_id,
        "lead_photographer_id": lead_photographer_id,
        "requested_shoot_hours": requested_shoot_hours,
        "workflow_status": "DRAFT",
        "payment_status": "UNPAID",
        "total_fee_cents": 0,
        "deposit_due_cents": 0,
        "amount_paid_cents": 0,
        "balance_due_cents": 0,
        "cancellation_fee_cents": 0,
    }
    stamp_create(booking)
    db.bookings[booking["id"]] = booking
    return ok_object(serialize(booking), 201)


@bp.get("/studio/bookings/<id>")
def get_booking(id):
    require_auth([ROLE_CLIENT, ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN])
    b = _find_booking_or_404(id)
    # Ownership: Client via client_id, Photographer via lead_photographer_id.
    _assert_read_owner(b)
    return ok_object(serialize(b), 200)


def _assert_read_owner(booking):
    from flask import g
    from errors import ERR_NOT_RESOURCE_OWNER
    if g.user_role == ROLE_CLIENT and g.user_id != booking["client_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller does not own this booking")
    if g.user_role == ROLE_PHOTOGRAPHER and g.user_id != booking["lead_photographer_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller is not the lead photographer")


@bp.get("/studio/bookings")
def list_bookings():
    require_auth([ROLE_CLIENT, ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN])
    limit, offset = parse_pagination()
    items = list(db.bookings.values())

    for field in ("client_id", "lead_photographer_id", "package_id",
                  "workflow_status", "payment_status"):
        val = request.args.get(field)
        if val is not None:
            items = [b for b in items if b[field] == val]

    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/studio/bookings/<id>/confirm")
def confirm_booking(id):
    require_auth([ROLE_CLIENT, ROLE_STUDIO_ADMIN])
    b = _find_booking_or_404(id)
    assert_client_owns(b)

    # State legality (priority 6).
    if b["workflow_status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Booking is not in DRAFT")

    # Model-release gate (priority 8) precedes signed-contract gate (priority 9)
    # per the validations table ordering.
    package = db.session_packages[b["package_id"]]
    contract = contract_for_booking(b["id"])

    if package["requires_model_release"]:
        if contract is None or not contract.get("includes_model_release", False):
            raise APIError(ERR_MODEL_RELEASE_REQUIRED, 422,
                           "Package requires a model release")

    # Signed-contract gate (priority 9).
    if contract is None or contract["status"] != "SIGNED":
        raise APIError(ERR_CONTRACT_NOT_SIGNED, 422, "Contract must be SIGNED")

    # A ShootSchedule must exist in SCHEDULED status.
    sched = _scheduled_schedule(b["id"])
    if sched is None:
        raise APIError(ERR_INVALID_STATE, 409, "No SCHEDULED shoot schedule exists")

    # Side effects: recompute total, pin deposit, recompute balance, bump version.
    recompute_total_fee(b)
    b["deposit_due_cents"] = calc.deposit_due(b["total_fee_cents"], package["deposit_pct"])
    recompute_amount_paid_and_balance(b)
    b["workflow_status"] = "CONFIRMED"
    touch(b)
    return ok_object(serialize(b), 200)


def _scheduled_schedule(booking_id):
    scheds = [s for s in db.shoot_schedules.values()
              if s["booking_id"] == booking_id and s["status"] == "SCHEDULED"]
    return sorted(scheds, key=lambda s: s["_seq"])[-1] if scheds else None


@bp.post("/studio/bookings/<id>/cancel")
def cancel_booking(id):
    require_auth([ROLE_CLIENT, ROLE_STUDIO_ADMIN])
    b = _find_booking_or_404(id)
    assert_client_owns(b)

    status = b["workflow_status"]
    if status == "DRAFT":
        # DRAFT -> CANCELLED: fee 0, VOID contract if exists.
        b["cancellation_fee_cents"] = 0
        contract = contract_for_booking(b["id"])
        if contract is not None and contract["status"] in ("DRAFT", "SENT"):
            contract["status"] = "VOID"
            touch(contract)
        b["workflow_status"] = "CANCELLED"
        touch(b)
        return ok_object(serialize(b), 200)

    if status == "CONFIRMED":
        # Cancellation fee from the live clock against the active schedule.
        sched = active_schedule_for_booking(b["id"])
        # Compute fee (uses the active schedule's start_utc).
        if sched is not None:
            b["cancellation_fee_cents"] = calc.cancellation_fee(
                b["deposit_due_cents"], sched["start_utc"], db.get_clock_iso()
            )
        else:
            b["cancellation_fee_cents"] = calc.cancellation_fee(
                b["deposit_due_cents"], db.get_clock_iso(), db.get_clock_iso()
            )

        # CASCADE: the SCHEDULED/RESCHEDULED schedule -> CANCELLED.
        if sched is not None and sched["status"] in ("SCHEDULED", "RESCHEDULED"):
            sched["status"] = "CANCELLED"
            touch(sched)
            # CASCADE: release each ASSIGNED second-shooter assignment on it.
            for a in assignments_for_schedule(sched["id"]):
                if a["status"] == "ASSIGNED":
                    a["status"] = "RELEASED"
                    touch(a)

        # After releases settle, recompute total then balance.
        recompute_total_fee(b)
        recompute_amount_paid_and_balance(b)

        # Refund pending if overpaid relative to the cancellation fee.
        if b["amount_paid_cents"] > b["cancellation_fee_cents"]:
            b["payment_status"] = "REFUND_PENDING"

        b["workflow_status"] = "CANCELLED"
        touch(b)
        return ok_object(serialize(b), 200)

    raise APIError(ERR_INVALID_STATE, 409, "Booking cannot be cancelled from its current state")


@bp.post("/studio/bookings/<id>/close")
def close_booking(id):
    require_auth([ROLE_STUDIO_ADMIN])
    b = _find_booking_or_404(id)
    if b["workflow_status"] != "DELIVERED":
        raise APIError(ERR_INVALID_STATE, 409, "Booking is not DELIVERED")
    if b["payment_status"] != "PAID_IN_FULL":
        raise APIError(ERR_INVALID_STATE, 409, "Booking is not PAID_IN_FULL")
    b["workflow_status"] = "CLOSED"
    touch(b)
    return ok_object(serialize(b), 200)
