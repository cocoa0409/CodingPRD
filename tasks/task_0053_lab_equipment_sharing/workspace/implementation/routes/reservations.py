"""Reservation endpoints (create, list, get, check-in, check-out, cancel)."""
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request, g

import db
from clock import iso, now, parse_iso
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services import audit, calc, reservation_ops


bp = Blueprint("reservations", __name__)


def _get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        raise err("ERR_BAD_REQUEST", "JSON body required")
    if not isinstance(body, dict):
        raise err("ERR_BAD_REQUEST", "JSON object required")
    return body


def _peak_overlap_for_eq(eq, start_at, end_at) -> int:
    return calc.peak_overlap_minutes(
        start_at, end_at,
        eq["peak_window_start_hour"], eq["peak_window_end_hour"])


@bp.post("/equipment/<equipment_id>/reservations")
@require_auth(roles={"User"})
def create_reservation(equipment_id):
    eq = db.equipment.get(equipment_id)
    if eq is None:
        raise err("ERR_NOT_FOUND", "equipment not found")
    body = _get_body()
    user_id = body.get("user_id")
    authorization_id = body.get("authorization_id")
    start_raw = body.get("start_at")
    end_raw = body.get("end_at")
    requested_sample_count = body.get("requested_sample_count", 0)
    if not isinstance(user_id, str) or not user_id:
        raise err("ERR_BAD_REQUEST", "user_id is required")
    if not isinstance(authorization_id, str) or not authorization_id:
        raise err("ERR_BAD_REQUEST", "authorization_id is required")
    if user_id != g.user_id:
        raise err("ERR_FORBIDDEN", "user_id must match X-User-ID")
    if not isinstance(requested_sample_count, int) or isinstance(requested_sample_count, bool) or requested_sample_count < 0:
        raise err("ERR_BAD_REQUEST", "requested_sample_count must be a non-negative integer")
    if not start_raw or not end_raw:
        raise err("ERR_BAD_REQUEST", "start_at and end_at are required")
    try:
        start_at = parse_iso(start_raw)
        end_at = parse_iso(end_raw)
    except ValueError:
        raise err("ERR_BAD_REQUEST", "invalid ISO timestamp")

    # Priority 4: foreign key existence
    user = db.users.get(user_id)
    if user is None:
        raise err("ERR_NOT_FOUND", "user not found")
    auth = db.authorizations.get(authorization_id)
    if auth is None:
        raise err("ERR_NOT_FOUND", "authorization not found")

    # Priority 6: equipment must be AVAILABLE
    if eq["status"] != "AVAILABLE":
        raise err("ERR_EQUIPMENT_UNAVAILABLE",
                  f"equipment is in state {eq['status']}")

    # Priority 7: authorization must be APPROVED, not expired/revoked, matching context
    if auth["status"] != "APPROVED":
        raise err("ERR_AUTHORIZATION_INVALID",
                  f"authorization is in state {auth['status']}")
    if auth["equipment_id"] != equipment_id or auth["user_id"] != user_id:
        raise err("ERR_AUTHORIZATION_INVALID",
                  "authorization scope mismatch")
    if auth.get("expires_at") and parse_iso(auth["expires_at"]) <= now():
        raise err("ERR_AUTHORIZATION_INVALID", "authorization expired")

    # Priority 8: certificates fresh
    if parse_iso(eq["calibration_expires_at"]) <= now() or \
       parse_iso(eq["safety_inspection_expires_at"]) <= now():
        raise err("ERR_CERTIFICATE_EXPIRED", "equipment certificate expired")

    # Priority 11: lead time
    lead_minutes_required = eq["lead_time_hours"] * 60
    delta_minutes = (start_at - now()).total_seconds() / 60.0
    if delta_minutes < lead_minutes_required:
        raise err("ERR_LEAD_TIME_VIOLATED",
                  "start_at does not meet lead_time_hours")

    # Priority 12: slot grid alignment
    if not calc.aligned_to_grid(start_at, eq["slot_granularity"]) or \
       not calc.aligned_to_grid(end_at, eq["slot_granularity"]):
        raise err("ERR_SLOT_GRID_VIOLATION", "timestamps not on slot grid")
    if end_at <= start_at:
        raise err("ERR_SLOT_GRID_VIOLATION", "end_at must be > start_at")
    grid_secs = calc.grid_seconds(eq["slot_granularity"])
    duration_secs = int((end_at - start_at).total_seconds())
    if grid_secs == 0 or duration_secs % grid_secs != 0:
        raise err("ERR_SLOT_GRID_VIOLATION",
                  "duration not a positive multiple of slot granularity")

    # Priority 13: duration limit
    duration_hours = duration_secs / 3600.0
    if duration_hours > eq["single_user_duration_limit_hours"]:
        raise err("ERR_DURATION_LIMIT_EXCEEDED",
                  "duration exceeds single_user_duration_limit_hours")

    # Priority 14: maintenance window block
    for mw in db.maintenance_windows.values():
        if mw["equipment_id"] != equipment_id:
            continue
        if mw["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        mws = parse_iso(mw["start_at"])
        mwe = parse_iso(mw["end_at"])
        if reservation_ops.overlaps(start_at, end_at, mws, mwe):
            raise err("ERR_MAINTENANCE_BLOCK",
                      "requested slot overlaps maintenance window")

    # Compute priority_tier
    peak_overlap = _peak_overlap_for_eq(eq, start_at, end_at)
    priority_tier = "PEAK" if peak_overlap > 0 else "OFF_PEAK"

    # Priority 15 + 16: overlap + peak preemption
    overlapping = []
    for r in db.reservations.values():
        if r["equipment_id"] != equipment_id:
            continue
        if r["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        rs = parse_iso(r["start_at"])
        re_ = parse_iso(r["end_at"])
        if reservation_ops.overlaps(start_at, end_at, rs, re_):
            overlapping.append(r)
    if overlapping:
        # Determine if all overlaps are OFF_PEAK BOOKED reservations and the
        # candidate is PEAK → preempt those reservations.
        all_off_peak_booked = all(
            r["status"] == "BOOKED" and r.get("priority_tier") == "OFF_PEAK"
            for r in overlapping
        )
        any_peak_conflict = any(
            r.get("priority_tier") == "PEAK"
            for r in overlapping
        )
        any_checked_in = any(r["status"] == "CHECKED_IN" for r in overlapping)
        if priority_tier == "PEAK" and all_off_peak_booked and not any_checked_in:
            # Preempt: cancel each overlapping reservation with full refund
            for r in overlapping:
                reservation_ops.cancel_reservation(
                    r, actor_role="system", actor_user_id="system",
                    refund_bps=10000, reason="peak_preemption")
        elif priority_tier == "OFF_PEAK" and any_peak_conflict:
            raise err("ERR_PEAK_PRIORITY_VIOLATION",
                      "OFF_PEAK request cannot preempt PEAK reservation")
        else:
            raise err("ERR_RESERVATION_OVERLAP",
                      "requested slot overlaps existing reservation")

    # Pin billing rule
    pinned_rule_id = eq.get("active_billing_rule_id")
    if pinned_rule_id is None:
        raise err("ERR_INVALID_STATE",
                  "equipment has no active billing rule")
    rule = db.billing_rules.get(pinned_rule_id)
    if rule is None:
        raise err("ERR_INVALID_STATE", "active billing rule missing")

    lab = db.labs[eq["lab_id"]]
    fees = calc.estimated_fee(
        rule, lab, user, start_at, end_at, requested_sample_count,
        eq["peak_window_start_hour"], eq["peak_window_end_hour"])

    reservation = {
        "equipment_id": equipment_id,
        "user_id": user_id,
        "authorization_id": authorization_id,
        "start_at": iso(start_at),
        "end_at": iso(end_at),
        "requested_sample_count": requested_sample_count,
        "priority_tier": priority_tier,
        "status": "BOOKED",
        "billing_rule_id_pinned": pinned_rule_id,
        "estimated_fee_cents": fees["estimated_fee_cents"],
        "final_fee_cents": 0,
        "estimated_platform_fee_cents": fees["estimated_platform_fee_cents"],
        "final_platform_fee_cents": 0,
        "estimated_owner_share_cents": fees["estimated_owner_share_cents"],
        "final_owner_share_cents": 0,
        "cancelled_at": None,
        "cancellation_refund_bps": 0,
    }
    db.stamp_create(reservation)
    db.reservations[reservation["id"]] = reservation

    # Accrue owner share
    lab["settlement_balance_cents"] = int(lab["settlement_balance_cents"]) + int(fees["estimated_owner_share_cents"])
    db.stamp_update(lab)

    audit.record(
        subject_type="RESERVATION",
        subject_id=reservation["id"],
        actor_role=g.user_role,
        actor_user_id=g.user_id,
        action="CREATE",
        from_state=None,
        to_state="BOOKED",
        payload_json={
            "start_at": reservation["start_at"],
            "end_at": reservation["end_at"],
            "priority_tier": priority_tier,
            "estimated_fee_cents": reservation["estimated_fee_cents"],
        },
    )

    return success(db.public(reservation), status=201)


@bp.get("/reservations/<reservation_id>")
@require_auth(roles={"PlatformAdmin", "LabOwner", "User"})
def get_reservation(reservation_id):
    r = db.reservations.get(reservation_id)
    if r is None:
        raise err("ERR_NOT_FOUND", "reservation not found")
    # User can only see own; LabOwner only if they own the equipment's lab
    if g.user_role == "User" and r["user_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "User can only see own reservations")
    if g.user_role == "LabOwner":
        eq = db.equipment.get(r["equipment_id"])
        lab = db.labs.get(eq["lab_id"]) if eq else None
        if lab is None or lab["contact_user_id"] != g.user_id:
            raise err("ERR_FORBIDDEN", "not the lab owner")
    return success(db.public(r))


@bp.get("/reservations")
@require_auth(roles={"PlatformAdmin", "LabOwner", "User"})
def list_reservations():
    limit, offset = get_pagination()
    equipment_id_f = request.args.get("equipment_id")
    user_id_f = request.args.get("user_id")
    status_f = request.args.get("status")
    saf = request.args.get("start_at_from")
    sat = request.args.get("start_at_to")
    sa_from = None
    sa_to = None
    if saf:
        try:
            sa_from = parse_iso(saf)
        except ValueError:
            raise err("ERR_BAD_REQUEST", "start_at_from invalid")
    if sat:
        try:
            sa_to = parse_iso(sat)
        except ValueError:
            raise err("ERR_BAD_REQUEST", "start_at_to invalid")
    items = []
    for r in db.reservations.values():
        if equipment_id_f and r["equipment_id"] != equipment_id_f:
            continue
        if user_id_f and r["user_id"] != user_id_f:
            continue
        if status_f and r["status"] != status_f:
            continue
        rs = parse_iso(r["start_at"])
        if sa_from and rs < sa_from:
            continue
        if sa_to and rs > sa_to:
            continue
        # Role-based filter
        if g.user_role == "User" and r["user_id"] != g.user_id:
            continue
        if g.user_role == "LabOwner":
            eq = db.equipment.get(r["equipment_id"])
            lab = db.labs.get(eq["lab_id"]) if eq else None
            if lab is None or lab["contact_user_id"] != g.user_id:
                continue
        items.append(r)
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([db.public(x) for x in page], limit, offset, total)


def _check_reservation_actor(r):
    """Validate actor for cancel/check-in/check-out: must be User=Reservation.user_id
    OR LabOwner of equipment's lab.
    """
    if g.user_role == "User":
        if r["user_id"] != g.user_id:
            raise err("ERR_FORBIDDEN", "not the reservation user")
    elif g.user_role == "LabOwner":
        eq = db.equipment.get(r["equipment_id"])
        lab = db.labs.get(eq["lab_id"]) if eq else None
        if lab is None or lab["contact_user_id"] != g.user_id:
            raise err("ERR_FORBIDDEN", "not the lab owner of this equipment")
    else:
        raise err("ERR_FORBIDDEN", "role not permitted")


@bp.post("/reservations/<reservation_id>/check-in")
@require_auth(roles={"User"})
def check_in(reservation_id):
    r = db.reservations.get(reservation_id)
    if r is None:
        raise err("ERR_NOT_FOUND", "reservation not found")
    if r["user_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "not the reservation user")
    if r["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", f"reservation is in state {r['status']}")
    start_at = parse_iso(r["start_at"])
    end_at = parse_iso(r["end_at"])
    if now() < (start_at - timedelta(minutes=15)):
        raise err("ERR_INVALID_STATE", "too early to check in")
    if now() >= end_at:
        raise err("ERR_INVALID_STATE", "reservation has already ended")
    eq = db.equipment.get(r["equipment_id"])
    if eq is None:
        raise err("ERR_NOT_FOUND", "equipment not found")
    if eq["status"] != "AVAILABLE":
        raise err("ERR_EQUIPMENT_UNAVAILABLE",
                  f"equipment in state {eq['status']}")
    auth = db.authorizations.get(r["authorization_id"])
    if auth is None or auth["status"] != "APPROVED":
        raise err("ERR_AUTHORIZATION_INVALID", "authorization not APPROVED")
    if auth.get("expires_at") and parse_iso(auth["expires_at"]) <= now():
        raise err("ERR_AUTHORIZATION_INVALID", "authorization expired")

    prev = r["status"]
    r["status"] = "CHECKED_IN"
    db.stamp_update(r)

    usage_log = {
        "id": db.gen_id(),
        "reservation_id": r["id"],
        "check_in_at": iso(now()),
        "check_out_at": None,
        "actual_duration_minutes": 0,
        "actual_sample_count": 0,
        "abnormal_event_code": None,
        "status_handover": None,
        "created_at": iso(now()),
        "_seq": db.next_seq(),
    }
    db.usage_logs[usage_log["id"]] = usage_log

    audit.record(
        subject_type="RESERVATION",
        subject_id=r["id"],
        actor_role=g.user_role,
        actor_user_id=g.user_id,
        action="CHECK_IN",
        from_state=prev,
        to_state="CHECKED_IN",
        payload_json={"usage_log_id": usage_log["id"]},
    )
    return success(db.public(r))


@bp.post("/reservations/<reservation_id>/check-out")
@require_auth(roles={"User"})
def check_out(reservation_id):
    r = db.reservations.get(reservation_id)
    if r is None:
        raise err("ERR_NOT_FOUND", "reservation not found")
    if r["user_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "not the reservation user")
    if r["status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", f"reservation is in state {r['status']}")
    body = _get_body()
    actual_sample_count = body.get("actual_sample_count")
    status_handover = body.get("status_handover")
    abnormal_event_code = body.get("abnormal_event_code")
    if not isinstance(actual_sample_count, int) or isinstance(actual_sample_count, bool) or actual_sample_count < 0:
        raise err("ERR_BAD_REQUEST", "actual_sample_count must be a non-negative integer")
    if status_handover not in ("NORMAL", "ABNORMAL"):
        raise err("ERR_BAD_REQUEST", "status_handover must be NORMAL or ABNORMAL")
    if abnormal_event_code is not None:
        if not isinstance(abnormal_event_code, str) or not abnormal_event_code:
            raise err("ERR_BAD_REQUEST", "abnormal_event_code must be a string")
        if status_handover != "ABNORMAL":
            raise err("ERR_BAD_REQUEST", "abnormal_event_code requires status_handover=ABNORMAL")

    # Find usage log
    usage_log = None
    for u in db.usage_logs.values():
        if u["reservation_id"] == r["id"]:
            usage_log = u
            break
    if usage_log is None:
        raise err("ERR_INVALID_STATE", "no usage log found")

    eq = db.equipment.get(r["equipment_id"])
    user = db.users.get(r["user_id"])
    lab = db.labs.get(eq["lab_id"])
    rule = db.billing_rules.get(r["billing_rule_id_pinned"])

    usage_log["check_out_at"] = iso(now())
    check_in_at = parse_iso(usage_log["check_in_at"])
    check_out_at = now()
    usage_log["actual_sample_count"] = actual_sample_count
    usage_log["status_handover"] = status_handover
    if abnormal_event_code is not None:
        usage_log["abnormal_event_code"] = abnormal_event_code

    fees = calc.final_fee(
        rule, lab, user, check_in_at, check_out_at, actual_sample_count,
        eq["peak_window_start_hour"], eq["peak_window_end_hour"])
    usage_log["actual_duration_minutes"] = fees["actual_duration_minutes"]

    estimated_owner = int(r.get("estimated_owner_share_cents", 0))
    r["final_fee_cents"] = fees["final_fee_cents"]
    r["final_platform_fee_cents"] = fees["final_platform_fee_cents"]
    r["final_owner_share_cents"] = fees["final_owner_share_cents"]
    prev = r["status"]
    r["status"] = "COMPLETED"
    db.stamp_update(r)

    # Adjust settlement balance by (final - estimated)
    delta = fees["final_owner_share_cents"] - estimated_owner
    lab["settlement_balance_cents"] = int(lab["settlement_balance_cents"]) + delta
    db.stamp_update(lab)

    audit.record(
        subject_type="RESERVATION",
        subject_id=r["id"],
        actor_role=g.user_role,
        actor_user_id=g.user_id,
        action="CHECK_OUT",
        from_state=prev,
        to_state="COMPLETED",
        payload_json={
            "final_fee_cents": r["final_fee_cents"],
            "status_handover": status_handover,
        },
    )

    if status_handover == "ABNORMAL":
        # Spawn AD_HOC MaintenanceWindow now..now+24h, equipment AVAILABLE -> MAINTENANCE
        from datetime import timedelta as _td
        start_at = now()
        end_at = start_at + _td(hours=24)
        mw = {
            "equipment_id": eq["id"],
            "kind": "AD_HOC",
            "start_at": iso(start_at),
            "end_at": iso(end_at),
            "status": "IN_PROGRESS",
            "maintenance_notes": f"abnormal:{abnormal_event_code or 'unspecified'}",
            "acceptance_notes": "",
            "archived_record_uri": None,
        }
        db.stamp_create(mw)
        db.maintenance_windows[mw["id"]] = mw
        if eq["status"] == "AVAILABLE":
            eq["status"] = "MAINTENANCE"
            db.stamp_update(eq)
        # Cascade cancel future BOOKED reservations overlapping
        overlapping = reservation_ops.find_overlapping_reservations(
            eq["id"], start_at, end_at, statuses=("BOOKED",))
        for rr in overlapping:
            if rr["id"] == r["id"]:
                continue
            reservation_ops.cancel_reservation(
                rr, actor_role="system", actor_user_id="system",
                refund_bps=10000, reason="abnormal_handover")
    return success(db.public(r))


@bp.post("/reservations/<reservation_id>/cancel")
@require_auth(roles={"User", "LabOwner"})
def cancel(reservation_id):
    r = db.reservations.get(reservation_id)
    if r is None:
        raise err("ERR_NOT_FOUND", "reservation not found")
    _check_reservation_actor(r)
    if r["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", f"reservation is in state {r['status']}")
    start_at = parse_iso(r["start_at"])
    if now() >= start_at:
        raise err("ERR_INVALID_STATE",
                  "reservation has already started; cannot cancel")
    refund_bps = calc.cancellation_refund_bps(start_at, now())
    reservation_ops.cancel_reservation(
        r, actor_role=g.user_role, actor_user_id=g.user_id,
        refund_bps=refund_bps, reason="user_cancel")
    return success(db.public(r))
