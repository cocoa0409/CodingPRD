"""Departure cascade and the unit occupancy cycle: early-departure depth-3 chain,
the AVAILABLE->OCCUPIED->TURNOVER->AVAILABLE cycle, and the invalid depart guard."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    book_retail_stay, checkin_retail_stay, TEST_USERS,
)

PM = TEST_USERS["property_manager_headers"]


def _turnover_for_unit(api, unit_id):
    data, _ = _paginate(api, unit_id)
    assert data, f"no turnover found for unit {unit_id}"
    return data[0]


def _paginate(api, unit_id):
    resp = api.list_turnovers(PM, params={"unit_id": unit_id})
    body = resp.json()
    return body["data"], body["meta"]


# --- Unit occupancy cycle returns to AVAILABLE ---

def test_complete_turnover_returns_unit_to_available(api):
    """PRD §3.6: "Turnover is closed by a `PropertyManager`, who marks a scheduled
    turnover `COMPLETED`; this is admissible only when the unit is in `TURNOVER` and
    its turnover record is `SCHEDULED`, and it drives the unit `TURNOVER` →
    `AVAILABLE` while advancing the turnover `SCHEDULED` → `COMPLETED`, closing the
    unit's occupancy cycle."

    Design: Difficulty/non_linear_state_machine/unit_availability_cycle
    """
    ctx = checkin_retail_stay(api, deposit_held_cents=0)
    unit_id = ctx["unit"]["id"]
    validate_success(api.depart_stay(ctx["stay"]["id"],
                                    {"actual_move_out": "2026-06-30T00:00:00Z"}, PM))
    turnover = _turnover_for_unit(api, unit_id)
    completed = validate_success(api.complete_turnover(turnover["id"], PM))
    assert completed["status"] == "COMPLETED"
    unit = validate_success(api.get_unit(unit_id, PM))
    assert unit["status"] == "AVAILABLE"


def test_unit_traverses_full_occupancy_cycle(api):
    """PRD §3.1: "Every unit is created in `AVAILABLE` status and moves through the
    cycle `AVAILABLE` → `OCCUPIED` → `TURNOVER` → `AVAILABLE` as stays come and go"

    Design: Difficulty/non_linear_state_machine/unit_availability_cycle
    """
    ctx = checkin_retail_stay(api, deposit_held_cents=0)
    unit_id = ctx["unit"]["id"]
    # After check-in the unit is OCCUPIED.
    assert validate_success(api.get_unit(unit_id, PM))["status"] == "OCCUPIED"
    # Departure drives it into TURNOVER.
    validate_success(api.depart_stay(ctx["stay"]["id"],
                                    {"actual_move_out": "2026-06-30T00:00:00Z"}, PM))
    assert validate_success(api.get_unit(unit_id, PM))["status"] == "TURNOVER"
    # Completing the turnover returns it to AVAILABLE.
    turnover = _turnover_for_unit(api, unit_id)
    validate_success(api.complete_turnover(turnover["id"], PM))
    assert validate_success(api.get_unit(unit_id, PM))["status"] == "AVAILABLE"


# --- Early-departure depth-3 cascade ---

def test_early_departure_completes_stay_and_turns_unit_over(api):
    """PRD §3.6: "When `actual_move_out` is earlier than `planned_move_out`, the
    guest has left early: the stay advances `ACTIVE` → `COMPLETED_EARLY`, and
    `billable_nights` reflects the shortened, prorated term."
    PRD §3.6: "The occupied unit advances `OCCUPIED` → `TURNOVER`."

    Design: Difficulty/transitive_cascade/early_departure_unit_turnover_cascade
    """
    ctx = checkin_retail_stay(api, deposit_held_cents=0)
    validate_success(api.depart_stay(ctx["stay"]["id"],
                                    {"actual_move_out": "2026-05-30T00:00:00Z"}, PM))
    stay = validate_success(api.get_stay(ctx["stay"]["id"], PM))
    assert stay["status"] == "COMPLETED_EARLY"
    unit = validate_success(api.get_unit(ctx["unit"]["id"], PM))
    assert unit["status"] == "TURNOVER"


def test_early_departure_creates_scheduled_turnover_for_stay(api):
    """PRD §3.6: "a **turnover** record is created in `SCHEDULED` status, capturing
    the `unit_id` being turned over, the `stay_id` of the outgoing stay that
    triggered it, and a `scheduled_date` equal to that stay's `actual_move_out`."

    Design: Difficulty/transitive_cascade/early_departure_unit_turnover_cascade
    """
    ctx = checkin_retail_stay(api, deposit_held_cents=0)
    stay_id = ctx["stay"]["id"]
    validate_success(api.depart_stay(stay_id,
                                    {"actual_move_out": "2026-05-30T00:00:00Z"}, PM))
    turnover = _turnover_for_unit(api, ctx["unit"]["id"])
    assert turnover["status"] == "SCHEDULED"
    assert turnover["stay_id"] == stay_id


# --- Corner: departing a never-checked-in stay ---

def test_depart_reserved_stay_rejected_no_side_effects(api):
    """PRD §3.6: "It is admissible only when the stay is `ACTIVE` and
    `actual_move_out` is on or after `move_in`; a stay that is not `ACTIVE` yields
    `ERR_INVALID_STATE`"

    Design: Corner/state_machines/depart_reserved_stay_returns_invalid_state
    """
    ctx = book_retail_stay(api, deposit_held_cents=0)  # RESERVED, never checked in
    resp = api.depart_stay(ctx["stay"]["id"],
                           {"actual_move_out": "2026-05-20T00:00:00Z"}, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    unit = validate_success(api.get_unit(ctx["unit"]["id"], PM))
    assert unit["status"] == "AVAILABLE"
