"""Payment endpoints (PRD §3.8). Settles final commission, escrow, net pay."""
from flask import Blueprint, request

from db import db, lock
from errors import ApiError
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import (
    mint_common,
    touch,
    public,
    get_json_body,
    require_str,
    require_int,
    lookup,
    paginate,
)
from services.calc import commission_cents, net_to_talent
from services.reconcile import reconcile_agency

bp = Blueprint("payments", __name__)


@bp.route("/payments", methods=["POST"])
def create_payment():
    _, role = get_identity()
    require_role(role, {"Agent"})
    body = get_json_body()
    booking_id = require_str(body, "booking_id")
    talent_id = require_str(body, "talent_id")
    gross_amount_cents = require_int(body, "gross_amount_cents", minimum=0)
    with lock:
        # Existence (priority 3), declaration order.
        booking = lookup("Booking", booking_id)
        talent = lookup("Talent", talent_id)

        # Cross-entity gate (priority 7): booking COMPLETED.
        if booking["booking_status"] != "COMPLETED":
            raise ApiError("ERR_BOOKING_NOT_COMPLETED")

        # Business safety (priority 8): talent match.
        if talent_id != booking["talent_id"]:
            raise ApiError("ERR_TALENT_MISMATCH")

        agency = lookup("Agency", talent["agency_id"])

        # Find the booking's HELD commission entry.
        held_entry = None
        for entry in db.commission_entries.values():
            if entry["booking_id"] == booking_id and entry["status"] == "HELD":
                held_entry = entry
                break

        held_amount = held_entry["held_cents"] if held_entry is not None else 0

        # Business fiscal (priority 13): escrow sufficiency (>= boundary).
        if agency["escrow_balance_cents"] < held_amount:
            raise ApiError("ERR_ESCROW_INSUFFICIENT")

        union_snapshot = talent["union_status"]

        # final commission on actual remitted gross.
        final_commission = commission_cents(gross_amount_cents, agency["commission_rate_bps"])
        commission_withheld, ph_cents, net = net_to_talent(
            gross_amount_cents, agency["commission_rate_bps"], union_snapshot
        )

        record = mint_common({
            "booking_id": booking_id,
            "talent_id": talent_id,
            "gross_amount_cents": gross_amount_cents,
            "union_status_snapshot": union_snapshot,
            "commission_withheld_cents": commission_withheld,
            "net_to_talent_cents": net,
            "status": "POSTED",
        })
        db.payments[record["id"]] = record

        # Booking side effects.
        booking["payment_status"] = "PAID"
        booking["final_commission_cents"] = final_commission
        touch(booking)

        # Commission entry HELD -> RELEASED.
        if held_entry is not None:
            held_entry["status"] = "RELEASED"
            held_entry["earned_cents"] = final_commission
            held_entry["held_cents"] = 0
            touch(held_entry)

        # Reconcile escrow down.
        reconcile_agency(agency)

        return object_response(public(record), status=201)


@bp.route("/payments", methods=["GET"])
def list_payments():
    _, role = get_identity()
    require_role(role, {"Agent", "Talent"})
    with lock:
        items = list(db.payments.values())
        for field in ("booking_id", "talent_id"):
            val = request.args.get(field)
            if val is not None:
                items = [p for p in items if p[field] == val]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    _, role = get_identity()
    require_role(role, {"Agent", "Talent"})
    with lock:
        record = lookup("Payment", payment_id)
        return object_response(public(record), status=200)
