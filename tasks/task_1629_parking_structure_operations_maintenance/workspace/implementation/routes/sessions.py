"""Parking session endpoints: entry, quote, pay, comp, exit, lost-ticket, refund (PRD 3.3)."""
from flask import Blueprint, request

import db
from errors import (
    err_invalid_state, err_device_identity, err_ref_not_found,
    err_device_not_online, err_posture_blocks, err_no_published_rate,
    err_duplicate_ticket, err_credential_not_valid, err_shift_not_open,
    err_exit_unpaid, err_comp_limit, err_refund_exceeds,
)
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    body, require_string, require_enum, require_int, require_ref, optional_ref,
    parse_pagination, paginate, get_session, public_view,
)
from services.fees import compute_fee, refresh_shift_expected, COMP_CAP_PER_SHIFT_CENTS

bp = Blueprint("sessions", __name__)

TENDERS = {"CASH", "CARD"}


def _session_view(s):
    return public_view(s)


def _resolve_shift_ref(shift_id):
    """Stage 6 body-reference resolution: present-but-unknown shift_id -> 404."""
    if shift_id is None:
        return None
    shift = db.shifts.get(shift_id)
    if shift is None:
        raise err_ref_not_found("shift_id not found")
    return shift


def _check_shift_open(actor, shift, facility_id):
    """Stage 14: shift must be OPEN, at this facility, owned by the caller."""
    if shift is None:
        raise err_shift_not_open("shift_id is required for CASH tender / comp")
    if (shift["shift_status"] != "OPEN"
            or shift["facility_id"] != facility_id
            or shift["attendant_user_id"] != actor.user_id):
        raise err_shift_not_open()
    return shift


@bp.post("/ops/parking-sessions")
def create_session():
    actor = get_actor()
    require_roles(actor, ["GateDevice"])
    payload = body()
    entry_device_id = payload.get("entry_device_id")
    # identity binding (stage 3): X-User-ID must equal the body's entry_device_id
    if entry_device_id is not None and actor.user_id != entry_device_id:
        raise err_device_identity()
    facility = require_ref(payload, db.facilities, "facility_id")
    device = require_ref(payload, db.access_devices, "entry_device_id")
    credential = optional_ref(payload, db.credentials, "credential_id")
    ticket_barcode = require_string(payload, "ticket_barcode")

    # Business checks in the PRD 3.3 order:
    # 1. device ONLINE and of this facility
    if device["device_status"] != "ONLINE" or device["facility_id"] != facility["id"]:
        raise err_device_not_online()
    # 2. posture gate: transient only NORMAL/EVENT_SURGE; credentialed also RESTRICTED
    if credential is not None:
        if facility["posture"] in ("CLOSED_TEMPORARY", "DECOMMISSIONED"):
            raise err_posture_blocks()
    else:
        if facility["posture"] not in ("NORMAL", "EVENT_SURGE"):
            raise err_posture_blocks()
    # 3. PUBLISHED rate schedule with effective_from <= now
    now = db.now_dt()
    published = None
    for sched in db.rate_schedules.values():
        if sched["facility_id"] == facility["id"] and sched["schedule_status"] == "PUBLISHED":
            if db.parse_iso(sched["effective_from"]) <= now:
                if published is None or db.parse_iso(sched["effective_from"]) > db.parse_iso(published["effective_from"]):
                    published = sched
    if published is None:
        raise err_no_published_rate()
    # 4. barcode unique among PARKED sessions of this facility
    for s in db.parking_sessions.values():
        if (s["facility_id"] == facility["id"]
                and s["occupancy_state"] == "PARKED"
                and s["ticket_barcode"] == ticket_barcode):
            raise err_duplicate_ticket()
    # 5. credential validity: credential ACTIVE and agreement ACTIVE
    if credential is not None:
        agreement = db.monthly_agreements.get(credential["agreement_id"])
        if (credential["credential_status"] != "ACTIVE"
                or agreement is None
                or agreement["agreement_status"] != "ACTIVE"):
            raise err_credential_not_valid()

    if credential is not None:
        fee_mode = "MONTHLY"
    elif device["device_mode"] == "EVENT":
        fee_mode = "EVENT_FLAT"
    else:
        fee_mode = "STANDARD"

    ent = {
        "id": db.new_id(),
        "facility_id": facility["id"],
        "rate_schedule_id": published["id"],
        "entry_device_id": device["id"],
        "credential_id": credential["id"] if credential else None,
        "paid_in_shift_id": None,
        "ticket_barcode": ticket_barcode,
        "occupancy_state": "PARKED",
        "billing_state": "OPEN",
        "fee_mode": fee_mode,
        "entry_at": db.now_iso(),
        "exit_at": None,
        "quoted_fee_cents": None,
        "settled_fee_cents": None,
        "refunded_cents": None,
        "refunded_at": None,
        "tender_type": None,
        "_settled_at": None,
    }
    db.stamp_new(ent)
    db.parking_sessions[ent["id"]] = ent
    return success_object(_session_view(ent), status=201)


@bp.get("/ops/parking-sessions/<parking_session_id>")
def get_session_route(parking_session_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(_session_view(get_session(parking_session_id)))


@bp.get("/ops/parking-sessions")
def list_sessions():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.parking_sessions.values())
    for key in ("facility_id", "credential_id", "rate_schedule_id",
                "entry_device_id", "paid_in_shift_id", "occupancy_state", "billing_state"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s.get(key) == val]
    page, total = paginate(items, limit, offset)
    return success_list([_session_view(s) for s in page], limit, offset, total)


@bp.post("/ops/parking-sessions/<parking_session_id>/quote")
def quote_session(parking_session_id):
    actor = get_actor()
    require_roles(actor, ["GateDevice", "ParkingAttendant"])
    s = get_session(parking_session_id)
    if s["billing_state"] not in ("OPEN", "QUOTED"):
        raise err_invalid_state("quote requires billing OPEN or QUOTED")
    if s["occupancy_state"] != "PARKED":
        raise err_invalid_state("quote requires the session still PARKED")
    now = db.now_dt()
    fee = compute_fee(s, now)
    s["billing_state"] = "QUOTED"
    s["quoted_fee_cents"] = fee
    db.touch(s)
    return success_object({
        "fee_cents": fee,
        "as_of": db.format_iso(now),
        "fee_mode": s["fee_mode"],
    })


@bp.post("/ops/parking-sessions/<parking_session_id>/pay")
def pay_session(parking_session_id):
    actor = get_actor()
    require_roles(actor, ["ParkingAttendant"])
    s = get_session(parking_session_id)
    payload = body()
    shift = _resolve_shift_ref(payload.get("shift_id"))
    tender = require_enum(payload, "tender_type", TENDERS)
    if s["billing_state"] not in ("OPEN", "QUOTED"):
        raise err_invalid_state("pay requires billing OPEN or QUOTED")
    if s["occupancy_state"] != "PARKED":
        raise err_invalid_state("pay requires the session still PARKED")
    if tender == "CASH":
        _check_shift_open(actor, shift, s["facility_id"])
    else:
        shift = None
    now = db.now_dt()
    fee = compute_fee(s, now)
    s["billing_state"] = "SETTLED"
    s["settled_fee_cents"] = fee
    s["tender_type"] = tender
    s["_settled_at"] = db.format_iso(now)
    if shift is not None:
        s["paid_in_shift_id"] = shift["id"]
    db.touch(s)
    facility = db.facilities[s["facility_id"]]
    facility["cumulative_collected_cents"] += fee
    db.touch_ledger(facility)
    if shift is not None:
        refresh_shift_expected(shift)
        db.touch(shift)
    return success_object(_session_view(s))


@bp.post("/ops/parking-sessions/<parking_session_id>/comp")
def comp_session(parking_session_id):
    actor = get_actor()
    require_roles(actor, ["ParkingAttendant"])
    s = get_session(parking_session_id)
    payload = body()
    shift = _resolve_shift_ref(payload.get("shift_id"))
    require_string(payload, "reason")
    if shift is None:
        raise err_shift_not_open("shift_id is required for comp")
    if s["billing_state"] not in ("OPEN", "QUOTED"):
        raise err_invalid_state("comp requires billing OPEN or QUOTED")
    if s["occupancy_state"] != "PARKED":
        raise err_invalid_state("comp requires the session still PARKED")
    _check_shift_open(actor, shift, s["facility_id"])
    now = db.now_dt()
    fee = compute_fee(s, now)
    if shift["comp_total_cents"] + fee > COMP_CAP_PER_SHIFT_CENTS:
        raise err_comp_limit()
    s["billing_state"] = "COMPED"
    s["settled_fee_cents"] = 0
    s["tender_type"] = "NONE"
    s["_settled_at"] = db.format_iso(now)
    db.touch(s)
    shift["comp_total_cents"] += fee
    db.touch(shift)
    return success_object(_session_view(s))


@bp.post("/ops/parking-sessions/<parking_session_id>/exit")
def exit_session(parking_session_id):
    actor = get_actor()
    require_roles(actor, ["GateDevice"])
    s = get_session(parking_session_id)
    if s["occupancy_state"] != "PARKED":
        raise err_invalid_state("exit requires the session still PARKED")
    now = db.now_dt()
    if s["billing_state"] not in ("SETTLED", "COMPED"):
        fee = compute_fee(s, now)
        if fee > 0:
            raise err_exit_unpaid()
        # zero-fee auto-settle
        s["billing_state"] = "SETTLED"
        s["settled_fee_cents"] = 0
        s["tender_type"] = "NONE"
        s["_settled_at"] = db.format_iso(now)
    s["occupancy_state"] = "EXITED"
    s["exit_at"] = db.format_iso(now)
    db.touch(s)
    return success_object(_session_view(s))


@bp.post("/ops/parking-sessions/<parking_session_id>/lost-ticket")
def lost_ticket(parking_session_id):
    actor = get_actor()
    require_roles(actor, ["ParkingAttendant"])
    s = get_session(parking_session_id)
    if s["billing_state"] not in ("OPEN", "QUOTED"):
        raise err_invalid_state("lost-ticket requires billing OPEN or QUOTED")
    now = db.now_dt()
    s["fee_mode"] = "LOST_TICKET"
    s["quoted_fee_cents"] = compute_fee(s, now)
    db.touch(s)
    return success_object(_session_view(s))


@bp.post("/ops/parking-sessions/<parking_session_id>/refund")
def refund_session(parking_session_id):
    actor = get_actor()
    require_roles(actor, ["RevenueAuditor"])
    s = get_session(parking_session_id)
    payload = body()
    amount = require_int(payload, "amount_cents", minimum=0, exclusive_min=True)
    require_string(payload, "reason")
    if s["billing_state"] != "SETTLED":
        raise err_invalid_state("refund requires billing SETTLED")
    if amount > s["settled_fee_cents"]:
        raise err_refund_exceeds()
    now = db.now_dt()
    s["billing_state"] = "REFUNDED"
    s["refunded_cents"] = amount
    s["refunded_at"] = db.format_iso(now)
    db.touch(s)
    facility = db.facilities[s["facility_id"]]
    facility["cumulative_collected_cents"] -= amount
    db.touch_ledger(facility)
    if s["tender_type"] == "CASH" and s.get("paid_in_shift_id"):
        shift = db.shifts.get(s["paid_in_shift_id"])
        if shift is not None and shift["shift_status"] != "RECONCILED":
            refresh_shift_expected(shift)
            db.touch(shift)
    return success_object(_session_view(s))
