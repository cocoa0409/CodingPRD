"""Logical clock endpoints — advance and now."""
from datetime import timedelta

from flask import Blueprint, request

import store
import validators
import responses
from auth import require_roles
from errors import raise_error
from clock import get_now, set_now, parse_iso, format_iso
from services import pay_credit, counters


bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/advance")
@require_roles("CrewScheduler")
def advance_clock():
    body = request.get_json(silent=True)
    validators.require_dict(body)
    validators.require_fields(body, "target_at")
    target = validators.parse_dt(body["target_at"], "target_at")
    set_now(target)

    # Run time-gated transitions in pinned order
    now = get_now()

    # 1) Pairing AWARDED -> IN_PROGRESS
    for pairing in list(store.pairings.values()):
        if pairing["status"] != "AWARDED":
            continue
        start_at = parse_iso(pairing["start_at"]) if pairing.get("start_at") else None
        if start_at is None or now < start_at:
            continue
        # All required rank slots must have SCHEDULED assignments
        comp = pairing.get("required_rank_composition") or {}
        required = {}
        for k, v in comp.items():
            if k == "mode":
                continue
            if isinstance(v, int) and v > 0:
                required[k] = v
        slot_counts = {}
        for a in store.assignments.values():
            if a["pairing_id"] == pairing["id"] and a["status"] == "SCHEDULED":
                slot_counts[a["assigned_rank_slot"]] = (
                    slot_counts.get(a["assigned_rank_slot"], 0) + 1
                )
        all_filled = all(slot_counts.get(k, 0) >= v for k, v in required.items())
        if not all_filled:
            continue
        pairing["status"] = "IN_PROGRESS"
        store.touch(pairing)
        for a in store.assignments.values():
            if a["pairing_id"] == pairing["id"] and a["status"] == "SCHEDULED":
                a["status"] = "IN_PROGRESS"
                store.touch(a)

    # 2) Pairing IN_PROGRESS -> CLOSED (and Assignment IN_PROGRESS -> COMPLETED)
    for pairing in list(store.pairings.values()):
        if pairing["status"] != "IN_PROGRESS":
            continue
        end_at = parse_iso(pairing["end_at"]) if pairing.get("end_at") else None
        if end_at is None or now < end_at:
            continue
        pairing["status"] = "CLOSED"
        store.touch(pairing)
        for a in store.assignments.values():
            if a["pairing_id"] == pairing["id"] and a["status"] == "IN_PROGRESS":
                a["status"] = "COMPLETED"
                a["actual_block_minutes"] = int(
                    pay_credit.compute_actual_block_minutes(pairing["id"], pairing["end_at"])
                )
                a["pay_credit_minutes"] = int(
                    pay_credit.compute_actual(pairing["id"], pairing["end_at"])
                )
                store.touch(a)
                crew = store.crew_members.get(a["crew_member_id"])
                if crew and end_at is not None:
                    cur = crew.get("last_duty_end_at")
                    if cur is None or parse_iso(cur) < end_at:
                        crew["last_duty_end_at"] = format_iso(end_at)
                        store.touch(crew)

    # 3) ReservePool AVAILABLE -> EXPIRED
    for rp in store.reserve_pool.values():
        if rp["state"] != "AVAILABLE":
            continue
        send = parse_iso(rp["standby_end_at"])
        if now > send:
            rp["state"] = "EXPIRED"
            store.touch(rp)

    # 4) TradeRequest PROPOSED/COUNTER_PROPOSED -> EXPIRED (24h after created_at)
    for t in store.trade_requests.values():
        if t["state"] not in {"PROPOSED", "COUNTER_PROPOSED"}:
            continue
        created = parse_iso(t["created_at"])
        if now >= created + timedelta(hours=24):
            t["state"] = "EXPIRED"
            store.touch(t)

    return responses.success({"now": format_iso(now)})


@bp.post("/_clock/now")
@require_roles("CrewScheduler", "Pilot", "FlightAttendant", "UnionSteward")
def clock_now():
    return responses.success({"now": format_iso(get_now())})
