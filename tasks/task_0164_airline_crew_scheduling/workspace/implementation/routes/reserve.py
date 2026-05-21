"""ReservePool endpoints."""
from flask import Blueprint, request, g

import store
import validators
import serializers
import responses
from auth import require_roles
from errors import raise_error
from clock import get_now, parse_iso, format_iso
from services import faa_service, counters


bp = Blueprint("reserve", __name__)


@bp.post("/reserve-pool")
@require_roles("CrewScheduler")
def create_reserve():
    body = request.get_json(silent=True)
    validators.require_dict(body)
    validators.require_fields(body, "crew_member_id", "reserve_date",
                              "standby_start_at", "standby_end_at")

    crew_id = validators.require_string(body, "crew_member_id")
    crew = store.crew_members.get(crew_id)
    if crew is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Crew member not found.")

    reserve_date = validators.parse_dt(body["reserve_date"], "reserve_date")
    sstart = validators.parse_dt(body["standby_start_at"], "standby_start_at")
    send = validators.parse_dt(body["standby_end_at"], "standby_end_at")
    if send <= sstart:
        raise_error("ERR_VALIDATION_FAILED",
                    "standby_end_at must be after standby_start_at.")

    # Unique (crew_member_id, reserve_date)
    for rp in store.reserve_pool.values():
        if (rp["crew_member_id"] == crew_id
                and rp["reserve_date"] == format_iso(reserve_date)):
            raise_error("ERR_VALIDATION_FAILED",
                        "Crew member already has a reserve entry for this date.")

    row = {
        "crew_member_id": crew_id,
        "reserve_date": format_iso(reserve_date),
        "standby_start_at": format_iso(sstart),
        "standby_end_at": format_iso(send),
        "state": "AVAILABLE",
    }
    store.init_common(row)
    store.reserve_pool[row["id"]] = row
    return responses.success(serializers.reserve_pool(row), http_status=201)


@bp.post("/reserve-pool/<reserve_id>/call-out")
@require_roles("CrewScheduler")
def call_out_reserve(reserve_id):
    rp = store.reserve_pool.get(reserve_id)
    if rp is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Reserve entry not found.")

    body = request.get_json(silent=True)
    validators.require_dict(body)
    validators.require_fields(body, "pairing_id", "assigned_rank_slot")

    pairing_id = validators.require_string(body, "pairing_id")
    pairing = store.pairings.get(pairing_id)
    if pairing is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Pairing not found.")

    slot = validators.require_rank(body["assigned_rank_slot"], "assigned_rank_slot")
    sick_call_id = body.get("sick_call_id")
    sick_call_row = None
    if sick_call_id:
        sick_call_row = store.sick_calls.get(sick_call_id)
        if sick_call_row is None:
            raise_error("ERR_REFERENCE_NOT_FOUND", "Sick call not found.")

    crew = store.crew_members.get(rp["crew_member_id"])
    if crew is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Reserve crew member not found.")

    # State check on ReservePool
    if rp["state"] != "AVAILABLE":
        raise_error("ERR_INVALID_ASSIGNMENT_STATE",
                    "Reserve entry is not AVAILABLE.")

    # Slot already covered check
    for a in store.assignments.values():
        if (a["pairing_id"] == pairing_id
                and a["assigned_rank_slot"] == slot
                and a["status"] in {"SCHEDULED", "IN_PROGRESS", "COMPLETED"}):
            raise_error("ERR_SLOT_ALREADY_COVERED",
                        "This pairing slot already has an assignment.")

    # Standby window check (start inclusive, end exclusive)
    now = get_now()
    sstart = parse_iso(rp["standby_start_at"])
    send = parse_iso(rp["standby_end_at"])
    if not (sstart <= now < send):
        raise_error("ERR_RESERVE_OUTSIDE_WINDOW",
                    "Reserve callout outside standby window.")

    # FAA check
    faa_service.faa_duty_rest_check(crew, pairing, raise_on_fail=True)

    # Crew availability
    if crew.get("status") != "ACTIVE":
        raise_error("ERR_CREW_NOT_AVAILABLE",
                    "Reserve crew member is not ACTIVE.")
    if crew.get("rank") != slot:
        raise_error("ERR_TRADE_RULE_VIOLATION",
                    "Crew member rank does not match slot.")

    # Create assignment
    assignment_row = {
        "pairing_id": pairing_id,
        "crew_member_id": crew["id"],
        "assigned_rank_slot": slot,
        "source": "RESERVE_CALLOUT",
        "status": "SCHEDULED",
        "scheduled_block_minutes": int(pairing.get("total_block_minutes", 0) or 0),
        "actual_block_minutes": 0,
        "pay_credit_minutes": 0,
    }
    store.init_common(assignment_row)
    store.assignments[assignment_row["id"]] = assignment_row

    rp["state"] = "CALLED_OUT"
    store.touch(rp)

    if sick_call_row is not None:
        sick_call_row["covered_by_assignment_id"] = assignment_row["id"]

    counters.increment_30d(crew, int(pairing.get("total_block_minutes", 0) or 0))

    return responses.success(serializers.assignment(assignment_row), http_status=201)


@bp.post("/reserve-pool/<reserve_id>/release")
@require_roles("CrewScheduler")
def release_reserve(reserve_id):
    rp = store.reserve_pool.get(reserve_id)
    if rp is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Reserve entry not found.")
    if rp["state"] != "AVAILABLE":
        raise_error("ERR_INVALID_ASSIGNMENT_STATE",
                    "Reserve entry is not AVAILABLE.")
    rp["state"] = "RELEASED"
    store.touch(rp)
    return responses.success(serializers.reserve_pool(rp))


@bp.get("/reserve-pool")
@require_roles("CrewScheduler")
def list_reserve():
    limit, offset = validators.parse_pagination(request.args)
    reserve_date = request.args.get("reserve_date")
    state = request.args.get("state")
    rows = list(store.reserve_pool.values())
    if reserve_date:
        rows = [r for r in rows if r["reserve_date"].startswith(reserve_date)]
    if state:
        rows = [r for r in rows if r["state"] == state]
    rows.sort(key=lambda r: r["created_at"])
    page, pag = validators.paginate(rows, limit, offset)
    return responses.success([serializers.reserve_pool(r) for r in page],
                             response_type="array", pagination=pag)
