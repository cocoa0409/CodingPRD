"""Appointment routes: book, list, get, attach add-on, list add-ons,
check-in, start, complete, no-show, cancel, settle."""

from flask import Blueprint, request

import errors
from common import (
    as_enum, as_int, get_json_body, paginate, sort_by_created, stamp_new, touch,
)
from db import db
from errors import err
from lookup import (
    get_add_on, get_appointment, get_chair, get_event_block, get_member,
    get_style_service, get_stylist,
)
from middleware import get_auth, require_role
from response import success_list, success_object
from serialize import public, public_list
from services.reconcile import (
    compute_appointment_pricing, compute_commission_split, compute_late_fee,
    compute_tip_split, reconcile_member, recompute_stylist_earnings,
)
from services.scheduling import (
    chair_conflict, chair_reserved_by_confirmed_block, stylist_conflict,
)

bp = Blueprint("appointments", __name__)

ALL_ROLES = {"FrontDesk", "FinanceManager", "Stylist", "Member"}
TERMINAL_LIFECYCLE = {"COMPLETED", "NO_SHOW", "CANCELLED"}


# ===========================================================================
# Book an appointment (PRD §3.4, §3.5)
# ===========================================================================
@bp.post("/appointments")
def book_appointment():
    user_id, role = get_auth()
    require_role(role, {"FrontDesk", "Member"})
    body = get_json_body()

    # ---- well-formedness of ids/enums first (priority 4 for body shape) ----
    member_id = body.get("member_id")
    chair_id = body.get("chair_id")
    stylist_id = body.get("stylist_id")
    style_service_id = body.get("style_service_id")
    if member_id is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: member_id")
    if chair_id is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: chair_id")
    if stylist_id is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: stylist_id")
    if style_service_id is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: style_service_id")
    event_block_id = body.get("event_block_id")

    # ---- existence: left-to-right member, chair, stylist, style_service, event_block ----
    member = get_member(member_id)
    chair = get_chair(chair_id)
    stylist = get_stylist(stylist_id)
    service = get_style_service(style_service_id)
    block = None
    if event_block_id is not None:
        block = get_event_block(event_block_id)

    # ---- well-formedness of remaining fields ----
    start_minute = as_int(body, "start_minute")
    payment_method = as_enum(body, "payment_method", {"CREDIT", "PREPAY"})
    if start_minute < 0 or start_minute >= 1440:
        raise err(errors.ERR_INVALID_REQUEST, "start_minute must be in [0,1440)")

    # ---- ownership (priority 5): Member books only own member_id ----
    if role == "Member" and user_id != member_id:
        raise err(errors.ERR_NOT_OWNER, "Member may only book their own appointments")

    # ---- OCC on event block (priority before business rules per §2.8/§2.9 placement);
    # the version check is part of booking into a block. ----
    if event_block_id is not None:
        expected = body.get("expected_event_block_version")
        if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
            raise err(errors.ERR_INVALID_REQUEST, "expected_event_block_version is required for event-block bookings")
        if expected != block["version"]:
            raise err(errors.ERR_STALE_VERSION, "expected_event_block_version does not match current version")

    # ---- business rules (§2.9 priorities 7..12) ----
    # service/member bookability (priority 12)
    if not service["active"]:
        raise err(errors.ERR_SERVICE_OR_ADDON_INACTIVE, "Style service is inactive")
    if member["status"] != "ACTIVE":
        raise err(errors.ERR_MEMBER_SUSPENDED, "Member is suspended")

    # compute schedule (duration only from service at booking; no add-ons yet)
    scheduled_duration = service["base_duration_minutes"]
    end_minute = start_minute + scheduled_duration

    # operating window (priority 7): chair [open,close), stylist [shift_start,shift_end)
    if not (chair["open_minute"] <= start_minute and end_minute <= chair["close_minute"]):
        raise err(errors.ERR_OUTSIDE_OPERATING_WINDOW, "Appointment outside chair operating hours")
    if not (stylist["shift_start_minute"] <= start_minute and end_minute <= stylist["shift_end_minute"]):
        raise err(errors.ERR_OUTSIDE_OPERATING_WINDOW, "Appointment outside stylist shift")

    # chair overlap (priority 8)
    if chair_conflict(chair, start_minute, end_minute):
        raise err(errors.ERR_CHAIR_DOUBLE_BOOKED, "Chair is double-booked")

    # stylist overlap (priority 9)
    if stylist_conflict(stylist_id, start_minute, end_minute):
        raise err(errors.ERR_STYLIST_DOUBLE_BOOKED, "Stylist is double-booked")

    # event-block membership rules (priority 10)
    if event_block_id is not None:
        in_chairs = chair_id in block["reserved_chair_ids"]
        in_window = (block["window_start_minute"] <= start_minute
                     and end_minute <= block["window_end_minute"])
        block_ok_state = block["status"] in {"HOLD", "CONFIRMED"}
        if not (in_chairs and in_window and block_ok_state):
            raise err(errors.ERR_BLOCK_CHAIR_OR_WINDOW_MISMATCH,
                      "Event-block chair not reserved or window mismatch")
    else:
        # standalone booking on a chair reserved by a CONFIRMED block (priority 11)
        if chair_reserved_by_confirmed_block(chair_id, start_minute, end_minute):
            raise err(errors.ERR_CHAIR_RESERVED_FOR_BLOCK,
                      "Chair reserved for a confirmed event block")

    # ---- create appointment ----
    appt = stamp_new({
        "member_id": member_id,
        "chair_id": chair_id,
        "stylist_id": stylist_id,
        "style_service_id": style_service_id,
        "event_block_id": event_block_id,
        "start_minute": start_minute,
        "scheduled_duration_minutes": scheduled_duration,
        "end_minute": end_minute,
        "payment_method": payment_method,
        "list_amount_cents": 0,
        "discount_cents": 0,
        "service_charge_cents": 0,
        "credits_applied": 0,
        "tip_cents": 0,
        "tip_pool_cents": 0,
        "stylist_tip_cents": 0,
        "commission_amount_cents": 0,
        "house_amount_cents": 0,
        "arrival_status": "ON_TIME",
        "late_minutes": 0,
        "lifecycle_status": "BOOKED",
        "settlement_status": "UNSETTLED",
        "_late_fee_cents": 0,
    })
    db.appointments[appt["id"]] = appt
    # pricing (consumes credits via balance reflected in reconcile)
    compute_appointment_pricing(appt)

    # reconcile member balances (credit draw reflected; prepay hold for PREPAY)
    reconcile_member(member)
    touch(member)

    # event-block version increment on successful attach
    if event_block_id is not None:
        touch(block)

    return success_object(public(appt), 201)


# ===========================================================================
# List / get appointments
# ===========================================================================
@bp.get("/appointments")
def list_appointments():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    items = list(db.appointments.values())
    for key in ("member_id", "chair_id", "stylist_id", "style_service_id", "event_block_id"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a.get(key) == val]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return success_list(public_list(page), limit, offset, total, 200)


@bp.get("/appointments/<aid>")
def get_one_appointment(aid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    appt = get_appointment(aid)
    return success_object(public(appt), 200)


# ===========================================================================
# Attach add-on (PRD §3.6)
# ===========================================================================
@bp.post("/appointments/<aid>/add-ons")
def attach_add_on(aid):
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    appt = get_appointment(aid)
    body = get_json_body()
    add_on_id = body.get("add_on_id")
    if add_on_id is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: add_on_id")
    add_on = get_add_on(add_on_id)
    # must be BOOKED to attach
    if appt["lifecycle_status"] != "BOOKED":
        raise err(errors.ERR_APPOINTMENT_NOT_BOOKED, "Appointment is not BOOKED")
    if not add_on["active"]:
        raise err(errors.ERR_SERVICE_OR_ADDON_INACTIVE, "Add-on is inactive")

    # snapshot
    attach = stamp_new({
        "appointment_id": appt["id"],
        "add_on_id": add_on_id,
        "captured_price_cents": add_on["price_cents"],
        "captured_duration_minutes": add_on["extra_duration_minutes"],
        "discount_applied_cents": 0,
    })
    db.appointment_add_ons[attach["id"]] = attach

    # recompute schedule + pricing (also re-validate chair overlap on new end)
    compute_appointment_pricing(appt)
    chair = db.chairs[appt["chair_id"]]
    if chair_conflict(chair, appt["start_minute"], appt["end_minute"], exclude_appt_id=appt["id"]):
        # roll back the attachment
        del db.appointment_add_ons[attach["id"]]
        compute_appointment_pricing(appt)
        raise err(errors.ERR_CHAIR_DOUBLE_BOOKED, "Add-on extends service into a chair conflict")

    touch(appt)
    # member balance may shift if credit coverage changed
    member = db.members[appt["member_id"]]
    reconcile_member(member)
    touch(member)
    return success_object(public(attach), 201)


@bp.get("/appointments/<aid>/add-ons")
def list_appointment_add_ons(aid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    appt = get_appointment(aid)
    items = [a for a in db.appointment_add_ons.values() if a["appointment_id"] == appt["id"]]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return success_list(public_list(page), limit, offset, total, 200)


# ===========================================================================
# Check-in (PRD §3.7)
# ===========================================================================
@bp.post("/appointments/<aid>/check-in")
def check_in(aid):
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    appt = get_appointment(aid)
    body = get_json_body()
    arrival_status = as_enum(body, "arrival_status", {"ON_TIME", "LATE"})
    late_minutes = as_int(body, "late_minutes", required=False, default=0)
    if late_minutes < 0:
        raise err(errors.ERR_INVALID_REQUEST, "late_minutes must be >= 0")
    if appt["lifecycle_status"] != "BOOKED":
        raise err(errors.ERR_APPOINTMENT_NOT_BOOKED, "Appointment is not BOOKED")
    member = db.members[appt["member_id"]]
    if member["status"] != "ACTIVE":
        raise err(errors.ERR_MEMBER_SUSPENDED, "Member is suspended")

    appt["arrival_status"] = arrival_status
    appt["late_minutes"] = late_minutes
    # late fee added on top of base service charge
    fee = compute_late_fee(arrival_status, late_minutes)
    prev_fee = appt.get("_late_fee_cents", 0)
    appt["service_charge_cents"] = appt["service_charge_cents"] - prev_fee + fee
    appt["_late_fee_cents"] = fee
    appt["lifecycle_status"] = "CHECKED_IN"
    touch(appt)

    # cascade: if block appointment, CONFIRMED -> CHECKED_IN
    if appt.get("event_block_id") is not None:
        block = db.event_blocks.get(appt["event_block_id"])
        if block is not None and block["status"] == "CONFIRMED":
            block["status"] = "CHECKED_IN"
            touch(block)

    return success_object(public(appt), 200)


# ===========================================================================
# Start service (PRD §3.7)
# ===========================================================================
@bp.post("/appointments/<aid>/start")
def start_service(aid):
    user_id, role = get_auth()
    require_role(role, {"Stylist"})
    appt = get_appointment(aid)
    if appt["lifecycle_status"] != "CHECKED_IN":
        # assignment check vs state: ownership (priority 5) before state (priority 6)
        if user_id != appt["stylist_id"]:
            raise err(errors.ERR_NOT_ASSIGNED_STYLIST, "Stylist not assigned to this appointment")
        raise err(errors.ERR_APPOINTMENT_NOT_CHECKED_IN, "Appointment is not CHECKED_IN")
    if user_id != appt["stylist_id"]:
        raise err(errors.ERR_NOT_ASSIGNED_STYLIST, "Stylist not assigned to this appointment")
    appt["lifecycle_status"] = "IN_SERVICE"
    touch(appt)
    return success_object(public(appt), 200)


# ===========================================================================
# Complete service (PRD §3.7)
# ===========================================================================
@bp.post("/appointments/<aid>/complete")
def complete_service(aid):
    user_id, role = get_auth()
    require_role(role, {"Stylist"})
    appt = get_appointment(aid)
    if appt["lifecycle_status"] != "IN_SERVICE":
        if user_id != appt["stylist_id"]:
            raise err(errors.ERR_NOT_ASSIGNED_STYLIST, "Stylist not assigned to this appointment")
        raise err(errors.ERR_APPOINTMENT_NOT_IN_SERVICE, "Appointment is not IN_SERVICE")
    if user_id != appt["stylist_id"]:
        raise err(errors.ERR_NOT_ASSIGNED_STYLIST, "Stylist not assigned to this appointment")
    appt["lifecycle_status"] = "COMPLETED"
    touch(appt)
    return success_object(public(appt), 200)


# ===========================================================================
# No-show (PRD §3.8)
# ===========================================================================
@bp.post("/appointments/<aid>/no-show")
def no_show(aid):
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    appt = get_appointment(aid)
    if appt["lifecycle_status"] != "BOOKED":
        raise err(errors.ERR_APPOINTMENT_NOT_BOOKED, "Appointment is not BOOKED")
    if db.current_minute < appt["start_minute"]:
        raise err(errors.ERR_NO_SHOW_TOO_EARLY, "Logical clock has not reached appointment start")
    appt["arrival_status"] = "NO_SHOW"
    appt["lifecycle_status"] = "NO_SHOW"
    appt["settlement_status"] = "VOIDED"
    # credits_applied retained as forfeited (still consumed) — leave credits_applied as-is
    touch(appt)
    member = db.members[appt["member_id"]]
    reconcile_member(member)  # increments strikes, cascades to SUSPENDED at threshold
    touch(member)
    return success_object(public(appt), 200)


# ===========================================================================
# Cancel (PRD §3.9)
# ===========================================================================
@bp.post("/appointments/<aid>/cancel")
def cancel(aid):
    user_id, role = get_auth()
    require_role(role, {"FrontDesk", "Member"})
    appt = get_appointment(aid)
    if role == "Member" and user_id != appt["member_id"]:
        raise err(errors.ERR_NOT_OWNER, "Member may only cancel their own appointments")
    if appt["lifecycle_status"] not in {"BOOKED", "CHECKED_IN"}:
        raise err(errors.ERR_APPOINTMENT_NOT_CANCELLABLE, "Appointment is not cancellable")
    _cancel_appointment(appt)
    return success_object(public(appt), 200)


def _cancel_appointment(appt):
    """Compensating cancel: refund credits, release prepay hold, void settlement,
    release chair time. credits/prepay refunds happen via reconcile (CANCELLED
    appointments drop out of consumed/charged totals)."""
    appt["lifecycle_status"] = "CANCELLED"
    appt["settlement_status"] = "VOIDED"
    touch(appt)
    member = db.members[appt["member_id"]]
    reconcile_member(member)
    touch(member)


# ===========================================================================
# Settle (PRD §3.10)
# ===========================================================================
@bp.post("/appointments/<aid>/settle")
def settle(aid):
    _, role = get_auth()
    require_role(role, {"FinanceManager"})
    appt = get_appointment(aid)
    body = get_json_body()
    tip_cents = as_int(body, "tip_cents", required=False, default=0)
    if tip_cents < 0:
        raise err(errors.ERR_INVALID_REQUEST, "tip_cents must be >= 0")

    # cross-axis: lifecycle must be COMPLETED, settlement must be UNSETTLED
    if appt["lifecycle_status"] != "COMPLETED":
        raise err(errors.ERR_APPOINTMENT_NOT_COMPLETED, "Appointment is not COMPLETED")
    if appt["settlement_status"] != "UNSETTLED":
        raise err(errors.ERR_ALREADY_SETTLED, "Appointment is already settled")

    member = db.members[appt["member_id"]]
    if appt["payment_method"] == "PREPAY":
        if member["prepay_balance_cents"] < appt["service_charge_cents"]:
            raise err(errors.ERR_INSUFFICIENT_PREPAY, "Insufficient prepay balance")

    # tip split
    appt["tip_cents"] = tip_cents
    stylist_tip, tip_pool = compute_tip_split(appt, tip_cents)
    appt["stylist_tip_cents"] = stylist_tip
    appt["tip_pool_cents"] = tip_pool

    # commission split
    stylist = db.stylists[appt["stylist_id"]]
    commission, house = compute_commission_split(appt, stylist)
    appt["commission_amount_cents"] = commission
    appt["house_amount_cents"] = house

    appt["settlement_status"] = "SETTLED"
    touch(appt)

    # prepay debit (reflected via reconcile: SETTLED PREPAY subtracts charge)
    if appt["payment_method"] == "PREPAY":
        reconcile_member(member)
        touch(member)

    # stylist earnings reconciliation
    recompute_stylist_earnings(stylist)
    touch(stylist)

    return success_object(public(appt), 200)


# ===========================================================================
# AppointmentAddOn collection reads
# ===========================================================================
@bp.get("/appointment-add-ons")
def list_all_appointment_add_ons():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    items = list(db.appointment_add_ons.values())
    appt_id = request.args.get("appointment_id")
    if appt_id is not None:
        items = [a for a in items if a["appointment_id"] == appt_id]
    add_on_id = request.args.get("add_on_id")
    if add_on_id is not None:
        items = [a for a in items if a["add_on_id"] == add_on_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return success_list(public_list(page), limit, offset, total, 200)


@bp.get("/appointment-add-ons/<aaid>")
def get_one_appointment_add_on(aaid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    attach = db.appointment_add_ons.get(aaid)
    if attach is None:
        raise err(errors.ERR_ADD_ON_NOT_FOUND, "Appointment add-on not found")
    return success_object(public(attach), 200)
