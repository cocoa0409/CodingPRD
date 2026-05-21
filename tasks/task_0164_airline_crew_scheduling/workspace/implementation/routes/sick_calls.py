"""SickCall endpoints."""
from flask import Blueprint, request, g

import store
import validators
import serializers
import responses
from auth import require_roles
from errors import raise_error
from clock import format_iso, get_now
from services import reserve_service, counters, pairing_service


bp = Blueprint("sick_calls", __name__)


@bp.post("/sick-calls")
@require_roles("Pilot", "FlightAttendant", "CrewScheduler")
def create_sick_call():
    body = request.get_json(silent=True)
    validators.require_dict(body)
    validators.require_fields(body, "crew_member_id", "effective_from", "expected_return_at")

    crew_id = validators.require_string(body, "crew_member_id")
    crew = store.crew_members.get(crew_id)
    if crew is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Crew member not found.")

    if g.role in ("Pilot", "FlightAttendant"):
        if g.user_id != crew_id:
            raise_error("ERR_FORBIDDEN",
                        "Cannot file a sick call for another crew member.")

    effective_from = validators.parse_dt(body["effective_from"], "effective_from")
    expected_return = validators.parse_dt(body["expected_return_at"], "expected_return_at")

    assignment_id = body.get("assignment_id")
    assignment_row = None
    if assignment_id is not None and assignment_id != "":
        assignment_row = store.assignments.get(assignment_id)
        if assignment_row is None:
            raise_error("ERR_REFERENCE_NOT_FOUND", "Assignment not found.")

    now = get_now()
    sick_row = {
        "crew_member_id": crew_id,
        "assignment_id": assignment_id if assignment_id else None,
        "reported_at": format_iso(now),
        "effective_from": format_iso(effective_from),
        "expected_return_at": format_iso(expected_return),
        "covered_by_assignment_id": None,
    }
    store.init_common(sick_row, with_top_level=False)
    store.sick_calls[sick_row["id"]] = sick_row

    # Crew member status -> ON_SICK_CALL
    crew["status"] = "ON_SICK_CALL"
    store.touch(crew)

    no_reserve = False
    if assignment_row is not None and assignment_row["status"] == "SCHEDULED":
        # Release the assignment
        pairing = store.pairings.get(assignment_row["pairing_id"])
        assignment_row["status"] = "RELEASED"
        store.touch(assignment_row)
        if pairing:
            counters.debit_for_release(crew, pairing, assignment_row)

            # Try auto-cover via reserve_selection_calc
            slot = assignment_row["assigned_rank_slot"]
            selected = reserve_service.select_reserve(pairing, slot)
            if selected is not None:
                rp, candidate_crew = selected
                new_assignment = {
                    "pairing_id": pairing["id"],
                    "crew_member_id": candidate_crew["id"],
                    "assigned_rank_slot": slot,
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

                sick_row["covered_by_assignment_id"] = new_assignment["id"]

                counters.increment_30d(candidate_crew,
                                       int(pairing.get("total_block_minutes", 0) or 0))
            else:
                no_reserve = True

    # PRD §3.4: when no covering candidate exists the sick call is still
    # recorded (HTTP 201) but the response body's error_id is
    # ERR_NO_RESERVE_AVAILABLE.
    payload = serializers.sick_call(sick_row)
    if no_reserve:
        payload["error_id"] = "ERR_NO_RESERVE_AVAILABLE"
    return responses.success(payload, http_status=201)


@bp.get("/sick-calls/<sc_id>")
@require_roles("CrewScheduler", "Pilot", "FlightAttendant")
def get_sick_call(sc_id):
    row = store.sick_calls.get(sc_id)
    if row is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Sick call not found.")
    if g.role in ("Pilot", "FlightAttendant"):
        if row["crew_member_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN",
                        "Cannot view another crew member's sick call.")
    return responses.success(serializers.sick_call(row))
