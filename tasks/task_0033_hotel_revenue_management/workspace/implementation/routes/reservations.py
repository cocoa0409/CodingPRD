"""Reservation routes — the largest workflow."""
from flask import Blueprint, request, g

from db import (
    reservations, room_types, rate_plans, channels, rooms,
    channel_rate_plan_mappings, overbooking_policies,
    stamp_create, stamp_update, lock,
)
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services.projections import project_reservation
from services.validation import require_dict, required_str
from services.listing import list_resource
from services.pricing import (
    compute_booked_total_cents, compute_refund_amount_cents,
    compute_no_show_charge_cents, compute_commission_settlement,
    find_active_policy,
)
from services.inventory import (
    find_mapping, check_channel_inventory_remaining,
    check_overbooking_limit, physical_room_available_for_check_in,
    date_overlaps_any_block,
)
from services.audit import emit
from services.occ import check_version
from clock import parse_date, now as clock_now, today_utc, iso, daterange

from datetime import timedelta


bp = Blueprint("reservations", __name__)


_LIST_ROLES = ["ReservationsAgent", "FrontDeskClerk", "RevenueAnalyst",
               "RevenueManager", "PlatformAdmin"]


def _check_distribution(reservation: dict):
    """ERR_RATE_PLAN_NOT_DISTRIBUTED check: rate_plan.room_type_id == res.room_type_id AND
    a ChannelRatePlanMapping exists with enabled == true."""
    rp = rate_plans.get(reservation["rate_plan_id"])
    ch = channels.get(reservation["channel_id"])
    rt = room_types.get(reservation["room_type_id"])
    if rt is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "RoomType not found")
    if rp is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "RatePlan not found")
    if ch is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Channel not found")
    if rp.get("status") != "ACTIVE":
        raise err("ERR_RATE_PLAN_NOT_DISTRIBUTED", "RatePlan is not ACTIVE")
    if ch.get("status") != "ACTIVE":
        raise err("ERR_RATE_PLAN_NOT_DISTRIBUTED", "Channel is not ACTIVE")
    if rp.get("room_type_id") != reservation["room_type_id"]:
        raise err("ERR_RATE_PLAN_NOT_DISTRIBUTED", "RatePlan does not apply to this RoomType")
    mapping = find_mapping(reservation["channel_id"], reservation["rate_plan_id"])
    if mapping is None or not mapping.get("enabled", True):
        raise err("ERR_RATE_PLAN_NOT_DISTRIBUTED", "RatePlan not distributed on this channel")
    return rp, ch, rt, mapping


@bp.route("/hotel/reservations", methods=["POST"])
@require_auth(roles=["ReservationsAgent", "Guest"])
def create_reservation():
    body = require_dict(request.get_json(silent=True))
    guest_name = required_str(body, "guest_name")
    room_type_id = required_str(body, "room_type_id")
    rate_plan_id = required_str(body, "rate_plan_id")
    channel_id = required_str(body, "channel_id")
    ci_raw = required_str(body, "check_in_date")
    co_raw = required_str(body, "check_out_date")
    try:
        ci = parse_date(ci_raw)
        co = parse_date(co_raw)
    except ValueError as e:
        raise err("ERR_INVALID_INPUT", str(e))
    if not (co > ci):
        raise err("ERR_INVALID_INPUT", "check_out_date must be strictly later than check_in_date")
    nights = (co - ci).days

    with lock():
        # Reference existence + distribution check (priority 4 + 10)
        provisional = {
            "room_type_id": room_type_id,
            "rate_plan_id": rate_plan_id,
            "channel_id": channel_id,
            "check_in_date": ci.isoformat(),
            "check_out_date": co.isoformat(),
        }
        _check_distribution(provisional)

        row = {
            "guest_name": guest_name,
            "room_type_id": room_type_id,
            "rate_plan_id": rate_plan_id,
            "channel_id": channel_id,
            "assigned_room_id": None,
            "check_in_date": ci.isoformat(),
            "check_out_date": co.isoformat(),
            "nights": nights,
            "booking_status": "PENDING",
            "payment_status": "UNPAID",
            "booked_total_cents": 0,
            "refund_amount_cents": 0,
            "no_show_charge_cents": 0,
            "walkout_compensation_cents": 0,
            "cancelled_at": None,
            "dispute_status": "NONE",
        }
        stamp_create(row, common_fields=True)
        reservations[row["id"]] = row
    return success(project_reservation(row), 201)


@bp.route("/hotel/reservations", methods=["GET"])
@require_auth(roles=_LIST_ROLES)
def list_reservations():
    limit, offset = get_pagination()
    booking_status = request.args.get("booking_status")
    channel_id = request.args.get("channel_id")
    room_type_id = request.args.get("room_type_id")
    ci_from = request.args.get("check_in_date_from")
    ci_to = request.args.get("check_in_date_to")

    rows = list(reservations.values())
    if booking_status:
        rows = [r for r in rows if r.get("booking_status") == booking_status]
    if channel_id:
        rows = [r for r in rows if r.get("channel_id") == channel_id]
    if room_type_id:
        rows = [r for r in rows if r.get("room_type_id") == room_type_id]
    if ci_from:
        try:
            d = parse_date(ci_from)
        except ValueError as e:
            raise err("ERR_INVALID_INPUT", str(e))
        rows = [r for r in rows if parse_date(r["check_in_date"]) >= d]
    if ci_to:
        try:
            d = parse_date(ci_to)
        except ValueError as e:
            raise err("ERR_INVALID_INPUT", str(e))
        rows = [r for r in rows if parse_date(r["check_in_date"]) < d]

    rows.sort(key=lambda r: r.get("_seq", 0))
    total = len(rows)
    page = rows[offset: offset + limit]
    return success_list([project_reservation(r) for r in page], limit, offset, total)


@bp.route("/hotel/reservations/<rid>", methods=["GET"])
@require_auth(roles=_LIST_ROLES + ["Guest"])
def get_reservation(rid):
    r = reservations.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Reservation not found")
    return success(project_reservation(r))


@bp.route("/hotel/reservations/<rid>/confirm", methods=["POST"])
@require_auth(roles=["ReservationsAgent"])
def confirm_reservation(rid):
    with lock():
        r = reservations.get(rid)
        if r is None:
            raise err("ERR_NOT_FOUND", "Reservation not found")
        if r.get("booking_status") != "PENDING":
            raise err("ERR_INVALID_STATE", "Reservation is not PENDING")

        # Distribution check (rate plan still active and mapped)
        _check_distribution(r)

        # Per-channel inventory share
        if not check_channel_inventory_remaining(r):
            raise err("ERR_INVENTORY_EXHAUSTED",
                      "Per-channel inventory is exhausted for at least one night")

        # Overbooking ceiling check
        ok, hit_overbooking = check_overbooking_limit(r)
        if not ok:
            raise err("ERR_OVERBOOKING_LIMIT_EXCEEDED",
                      "Cumulative reservations exceed overbooking ceiling for at least one night")

        # All passes — compute booked total, lock rate, advance status
        r["booked_total_cents"] = compute_booked_total_cents(r)
        r["booking_status"] = "CONFIRMED"
        r["payment_status"] = "AUTHORIZED"
        stamp_update(r)

        if hit_overbooking:
            emit(
                event_type="OVERBOOKING_ACCEPTED",
                actor_role=g.user_role,
                actor_id=g.user_id,
                subject_entity="Reservation",
                subject_id=r["id"],
                payload={
                    "room_type_id": r["room_type_id"],
                    "channel_id": r["channel_id"],
                    "check_in_date": r["check_in_date"],
                    "check_out_date": r["check_out_date"],
                },
            )
    return success(project_reservation(r))


@bp.route("/hotel/reservations/<rid>/modify", methods=["POST"])
@require_auth(roles=["ReservationsAgent", "Guest"])
def modify_reservation(rid):
    body = require_dict(request.get_json(silent=True))
    ci_raw = required_str(body, "check_in_date")
    co_raw = required_str(body, "check_out_date")
    try:
        new_ci = parse_date(ci_raw)
        new_co = parse_date(co_raw)
    except ValueError as e:
        raise err("ERR_INVALID_INPUT", str(e))
    if not (new_co > new_ci):
        raise err("ERR_INVALID_INPUT", "check_out_date must be strictly later than check_in_date")

    with lock():
        r = reservations.get(rid)
        if r is None:
            raise err("ERR_NOT_FOUND", "Reservation not found")
        if r.get("booking_status") != "CONFIRMED":
            raise err("ERR_INVALID_STATE", "Reservation is not CONFIRMED")

        # Priority 6: rate plan modification_allowed
        rp = rate_plans.get(r["rate_plan_id"])
        if rp is None or not rp.get("modification_allowed", True):
            raise err("ERR_MODIFICATION_NOT_ALLOWED",
                      "RatePlan does not allow modifications")

        # Distribution still valid
        _check_distribution(r)

        # Priority 17: ERR_MODIFICATION_TOO_LATE — original check_in_date <= now+24h
        # AND channel_type != DIRECT
        ch = channels.get(r["channel_id"])
        orig_ci_date = parse_date(r["check_in_date"])
        from datetime import datetime, timezone
        orig_ci_midnight = datetime.combine(orig_ci_date, datetime.min.time(), tzinfo=timezone.utc)
        now_dt = clock_now()
        delta_h = (orig_ci_midnight - now_dt).total_seconds() / 3600.0
        if delta_h <= 24 and (ch is None or ch.get("channel_type") != "DIRECT"):
            raise err("ERR_MODIFICATION_TOO_LATE",
                      "Original check_in_date is within 24h of now and channel is not DIRECT")

        # Build a virtual candidate with new dates and check inventory + overbooking
        virtual = dict(r)
        virtual["check_in_date"] = new_ci.isoformat()
        virtual["check_out_date"] = new_co.isoformat()

        if not check_channel_inventory_remaining(virtual, exclude_reservation_id=r["id"]):
            raise err("ERR_INVENTORY_EXHAUSTED",
                      "Per-channel inventory is exhausted for at least one night in new window")
        ok, _ = check_overbooking_limit(virtual, exclude_reservation_id=r["id"])
        if not ok:
            raise err("ERR_OVERBOOKING_LIMIT_EXCEEDED",
                      "Cumulative reservations would exceed overbooking ceiling for at least one night")

        # OCC
        check_version(body, r)

        # Apply
        r["check_in_date"] = new_ci.isoformat()
        r["check_out_date"] = new_co.isoformat()
        r["nights"] = (new_co - new_ci).days
        r["booked_total_cents"] = compute_booked_total_cents(r)
        stamp_update(r)
    return success(project_reservation(r))


@bp.route("/hotel/reservations/<rid>/cancel", methods=["POST"])
@require_auth(roles=["ReservationsAgent", "Guest"])
def cancel_reservation(rid):
    with lock():
        r = reservations.get(rid)
        if r is None:
            raise err("ERR_NOT_FOUND", "Reservation not found")
        status = r.get("booking_status")
        if status not in ("PENDING", "CONFIRMED"):
            raise err("ERR_INVALID_STATE", "Reservation is not cancellable in its current state")

        cancelled_at_dt = clock_now()
        r["cancelled_at"] = iso(cancelled_at_dt)
        if status == "PENDING":
            r["refund_amount_cents"] = 0
            if r.get("payment_status") == "AUTHORIZED":
                r["payment_status"] = "REFUNDED_FULL"
        else:  # CONFIRMED
            rp = rate_plans.get(r["rate_plan_id"])
            if rp is None:
                raise err("ERR_REFERENCE_NOT_FOUND", "RatePlan not found")
            refund = compute_refund_amount_cents(r, rp, cancelled_at_dt)
            r["refund_amount_cents"] = refund
            booked = r["booked_total_cents"]
            if refund > 0:
                if refund < booked:
                    r["payment_status"] = "REFUNDED_PARTIAL"
                else:
                    r["payment_status"] = "REFUNDED_FULL"
            else:
                r["payment_status"] = "CAPTURED"
        r["booking_status"] = "CANCELLED"
        stamp_update(r)
    return success(project_reservation(r))


@bp.route("/hotel/reservations/<rid>/check-in", methods=["POST"])
@require_auth(roles=["FrontDeskClerk"])
def check_in_reservation(rid):
    body = require_dict(request.get_json(silent=True))
    room_id = required_str(body, "room_id")

    with lock():
        r = reservations.get(rid)
        if r is None:
            raise err("ERR_NOT_FOUND", "Reservation not found")
        rm = rooms.get(room_id)
        if rm is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "Room not found")

        # Priority 5: state
        if r.get("booking_status") != "CONFIRMED":
            raise err("ERR_INVALID_STATE", "Reservation is not CONFIRMED")

        # today >= check_in_date
        ci_date = parse_date(r["check_in_date"])
        if today_utc() < ci_date:
            raise err("ERR_INVALID_STATE", "Today is before check_in_date")

        co_date = parse_date(r["check_out_date"])

        # Priority 8: Room operationally available + no maintenance overlap
        if rm.get("operational_status") != "IN_SERVICE":
            raise err("ERR_ROOM_UNAVAILABLE", "Room is not IN_SERVICE")
        if rm.get("lifecycle_status") != "ACTIVE":
            raise err("ERR_ROOM_UNAVAILABLE", "Room is not ACTIVE")
        if date_overlaps_any_block(rm["id"], ci_date, co_date):
            raise err("ERR_ROOM_UNAVAILABLE", "Room has overlapping maintenance block")

        # Priority 9: room_type match
        if rm.get("room_type_id") != r["room_type_id"]:
            raise err("ERR_ROOM_TYPE_MISMATCH", "Room.room_type_id does not match Reservation.room_type_id")

        # Housekeeping must be VACANT_CLEAN (also part of room availability per PRD §3.6)
        if rm.get("housekeeping_status") != "VACANT_CLEAN":
            raise err("ERR_ROOM_UNAVAILABLE", "Room is not VACANT_CLEAN")

        # Apply
        r["assigned_room_id"] = rm["id"]
        r["booking_status"] = "CHECKED_IN"
        r["payment_status"] = "CAPTURED"
        stamp_update(r)
        rm["housekeeping_status"] = "OCCUPIED"
        rm["current_reservation_id"] = r["id"]
        stamp_update(rm)
    return success(project_reservation(r))


@bp.route("/hotel/reservations/<rid>/check-out", methods=["POST"])
@require_auth(roles=["FrontDeskClerk"])
def check_out_reservation(rid):
    with lock():
        r = reservations.get(rid)
        if r is None:
            raise err("ERR_NOT_FOUND", "Reservation not found")
        if r.get("booking_status") != "CHECKED_IN":
            raise err("ERR_INVALID_STATE", "Reservation is not CHECKED_IN")
        ch = channels.get(r["channel_id"])
        if ch is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "Channel not found")

        r["booking_status"] = "CHECKED_OUT"
        # commission settlement (computed; not stored on reservation per scaffold,
        # but we record it for completeness in the stored row)
        settlement = compute_commission_settlement(r, ch)
        r["commission_amount_cents"] = settlement["commission_amount_cents"]
        r["net_to_hotel_cents"] = settlement["net_to_hotel_cents"]

        # Cascade room
        room_id = r.get("assigned_room_id")
        if room_id:
            rm = rooms.get(room_id)
            if rm is not None:
                rm["housekeeping_status"] = "DIRTY"
                rm["current_reservation_id"] = None
                stamp_update(rm)
        stamp_update(r)
    return success(project_reservation(r))


@bp.route("/hotel/reservations/<rid>/walk-out", methods=["POST"])
@require_auth(roles=["FrontDeskClerk"])
def walk_out_reservation(rid):
    with lock():
        r = reservations.get(rid)
        if r is None:
            raise err("ERR_NOT_FOUND", "Reservation not found")
        if r.get("booking_status") != "CONFIRMED":
            raise err("ERR_INVALID_STATE", "Reservation is not CONFIRMED")
        ci_date = parse_date(r["check_in_date"])
        if today_utc() != ci_date:
            raise err("ERR_INVALID_STATE", "Walk-out only at intended arrival date")
        co_date = parse_date(r["check_out_date"])
        if physical_room_available_for_check_in(r["room_type_id"], ci_date, co_date) > 0:
            raise err("ERR_INVALID_STATE",
                      "Physical room of this room_type is available; cannot walk out")

        # Compute walkout compensation: policy.walkout_compensation_cents * nights
        policy = find_active_policy(r["room_type_id"], r["check_in_date"])
        per_night_comp = policy["walkout_compensation_cents"] if policy else 0
        comp = per_night_comp * r["nights"]
        r["booking_status"] = "WALKED_OUT"
        r["walkout_compensation_cents"] = comp
        r["payment_status"] = "REFUNDED_FULL"
        stamp_update(r)
        emit(
            event_type="WALKOUT_EXECUTED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            subject_entity="Reservation",
            subject_id=r["id"],
            payload={
                "compensation_cents": comp,
                "reason": "no_room_available",
            },
        )
    return success(project_reservation(r))


@bp.route("/hotel/reservations/<rid>/dispute", methods=["POST"])
@require_auth(roles=["Guest", "ReservationsAgent"])
def open_dispute(rid):
    with lock():
        r = reservations.get(rid)
        if r is None:
            raise err("ERR_NOT_FOUND", "Reservation not found")
        if r.get("booking_status") not in ("NO_SHOW", "CANCELLED"):
            raise err("ERR_INVALID_STATE", "Disputes only for NO_SHOW or CANCELLED reservations")
        if r.get("dispute_status") != "NONE":
            raise err("ERR_INVALID_STATE", "Dispute already opened or resolved")
        # CANCELLED with residual penalty: refund < booked_total OR no_show_charge > 0
        if r.get("booking_status") == "CANCELLED":
            if r.get("refund_amount_cents", 0) >= r.get("booked_total_cents", 0):
                raise err("ERR_INVALID_STATE", "No residual penalty to dispute")
        r["dispute_status"] = "OPEN"
        stamp_update(r)
    return success(project_reservation(r))


@bp.route("/hotel/reservations/<rid>/resolve-dispute", methods=["POST"])
@require_auth(roles=["PlatformAdmin"])
def resolve_dispute(rid):
    body = require_dict(request.get_json(silent=True))
    resolution = required_str(body, "resolution")
    if resolution not in ("GUEST", "HOTEL"):
        raise err("ERR_INVALID_INPUT", "resolution must be GUEST or HOTEL")

    with lock():
        r = reservations.get(rid)
        if r is None:
            raise err("ERR_NOT_FOUND", "Reservation not found")
        if r.get("dispute_status") != "OPEN":
            raise err("ERR_INVALID_STATE", "Dispute is not OPEN")
        if resolution == "GUEST":
            if r.get("booking_status") == "NO_SHOW":
                r["refund_amount_cents"] = r.get("no_show_charge_cents", 0)
            else:  # CANCELLED — full booked_total refunded
                r["refund_amount_cents"] = r.get("booked_total_cents", 0)
            r["payment_status"] = "REFUNDED_FULL"
            r["dispute_status"] = "RESOLVED_GUEST"
        else:
            r["dispute_status"] = "RESOLVED_HOTEL"
        stamp_update(r)
    return success(project_reservation(r))
