"""Assignment endpoints."""
from flask import Blueprint, request, g

import store
import validators
import serializers
import responses
from auth import require_roles
from errors import raise_error
from clock import get_now, parse_iso
from services import faa_service, counters, pay_credit, reserve_service


bp = Blueprint("assignments", __name__)


@bp.post("/assignments")
@require_roles("CrewScheduler")
def create_assignment():
    body = request.get_json(silent=True)
    validators.require_dict(body)
    validators.require_fields(body, "pairing_id", "crew_member_id", "assigned_rank_slot")

    pairing_id = validators.require_string(body, "pairing_id")
    crew_id = validators.require_string(body, "crew_member_id")
    slot = validators.require_rank(body["assigned_rank_slot"], "assigned_rank_slot")

    pairing = store.pairings.get(pairing_id)
    if pairing is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Pairing not found.")
    crew = store.crew_members.get(crew_id)
    if crew is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Crew member not found.")

    if pairing["status"] in {"DRAFT", "CLOSED", "CANCELLED"}:
        raise_error("ERR_PAIRING_INVALID_STATE",
                    "Pairing state does not permit admin override.")

    # Slot already covered
    for a in store.assignments.values():
        if (a["pairing_id"] == pairing_id
                and a["assigned_rank_slot"] == slot
                and a["status"] in {"SCHEDULED", "IN_PROGRESS", "COMPLETED"}):
            raise_error("ERR_SLOT_ALREADY_COVERED",
                        "This pairing slot already has an assignment.")

    # FAA check
    faa_service.faa_duty_rest_check(crew, pairing, raise_on_fail=True)

    if crew.get("status") != "ACTIVE":
        raise_error("ERR_CREW_NOT_AVAILABLE",
                    "Crew member is not ACTIVE.")
    if crew.get("rank") != slot:
        raise_error("ERR_TRADE_RULE_VIOLATION",
                    "Crew member rank does not match slot.")

    row = {
        "pairing_id": pairing_id,
        "crew_member_id": crew_id,
        "assigned_rank_slot": slot,
        "source": "ADMIN_OVERRIDE",
        "status": "SCHEDULED",
        "scheduled_block_minutes": int(pairing.get("total_block_minutes", 0) or 0),
        "actual_block_minutes": 0,
        "pay_credit_minutes": 0,
    }
    store.init_common(row)
    store.assignments[row["id"]] = row

    counters.increment_30d(crew, int(pairing.get("total_block_minutes", 0) or 0))

    return responses.success(serializers.assignment(row), http_status=201)


@bp.post("/assignments/<a_id>/release")
@require_roles("CrewScheduler")
def release_assignment(a_id):
    a = store.assignments.get(a_id)
    if a is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Assignment not found.")
    if a["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_ASSIGNMENT_STATE",
                    "Only SCHEDULED assignments may be released.")
    pairing = store.pairings.get(a["pairing_id"])
    crew = store.crew_members.get(a["crew_member_id"])
    a["status"] = "RELEASED"
    store.touch(a)
    if pairing and crew:
        counters.debit_for_release(crew, pairing, a)
    return responses.success(serializers.assignment(a))


@bp.post("/assignments/<a_id>/mark-no-show")
@require_roles("CrewScheduler")
def mark_no_show(a_id):
    a = store.assignments.get(a_id)
    if a is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Assignment not found.")
    # PRD §3.4: mark no-show fires at Pairing.start_at when the crew
    # member has not checked in. By then the clock-driven SCHEDULED ->
    # IN_PROGRESS transition (PRD §3.6) may already have flipped the
    # assignment; accept both states as the eligible pre-condition.
    if a["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise_error("ERR_INVALID_ASSIGNMENT_STATE",
                    "Only SCHEDULED assignments may be marked no-show.")
    pairing = store.pairings.get(a["pairing_id"])
    if pairing is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Pairing not found.")
    now = get_now()
    start_at = parse_iso(pairing["start_at"]) if pairing.get("start_at") else None
    if start_at is None or now < start_at:
        raise_error("ERR_INVALID_ASSIGNMENT_STATE",
                    "Cannot mark no-show before pairing start.")

    a["status"] = "NO_SHOW"
    store.touch(a)
    # Reserve selection to recover slot
    selected = reserve_service.select_reserve(pairing, a["assigned_rank_slot"])
    if selected is not None:
        rp, candidate = selected
        new_assignment = {
            "pairing_id": pairing["id"],
            "crew_member_id": candidate["id"],
            "assigned_rank_slot": a["assigned_rank_slot"],
            "source": "RESERVE_CALLOUT",
            "status": "SCHEDULED",
            "scheduled_block_minutes": int(pairing.get("total_block_minutes", 0) or 0),
            "actual_block_minutes": 0,
            "pay_credit_minutes": 0,
        }
        store.init_common(new_assignment)
        store.assignments[new_assignment["id"]] = new_assignment
        rp["state"] = "CALLED_OUT"
        store.touch(rp)
        counters.increment_30d(candidate, int(pairing.get("total_block_minutes", 0) or 0))

    return responses.success(serializers.assignment(a))


@bp.get("/assignments/<a_id>")
@require_roles("CrewScheduler", "Pilot", "FlightAttendant")
def get_assignment(a_id):
    a = store.assignments.get(a_id)
    if a is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Assignment not found.")
    if g.role in ("Pilot", "FlightAttendant"):
        if a["crew_member_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN", "Cannot view another crew member's assignment.")
    return responses.success(serializers.assignment(a))


@bp.get("/assignments/<a_id>/pay-credit-estimate")
@require_roles("CrewScheduler", "Pilot", "FlightAttendant")
def pay_credit_estimate(a_id):
    a = store.assignments.get(a_id)
    if a is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Assignment not found.")
    if g.role in ("Pilot", "FlightAttendant"):
        if a["crew_member_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN", "Cannot view another crew member's estimate.")
    est = pay_credit.compute_scheduled(a["pairing_id"])
    return responses.success({"scheduled_pay_credit_minutes": int(est)})


@bp.get("/assignments")
@require_roles("CrewScheduler", "Pilot", "FlightAttendant")
def list_assignments():
    limit, offset = validators.parse_pagination(request.args)
    crew_id = request.args.get("crew_member_id")
    pairing_id = request.args.get("pairing_id")
    status = request.args.get("status")
    rows = list(store.assignments.values())
    if g.role in ("Pilot", "FlightAttendant"):
        rows = [r for r in rows if r["crew_member_id"] == g.user_id]
    if crew_id:
        rows = [r for r in rows if r["crew_member_id"] == crew_id]
    if pairing_id:
        rows = [r for r in rows if r["pairing_id"] == pairing_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    page, pag = validators.paginate(rows, limit, offset)
    return responses.success([serializers.assignment(r) for r in page],
                             response_type="array", pagination=pag)
