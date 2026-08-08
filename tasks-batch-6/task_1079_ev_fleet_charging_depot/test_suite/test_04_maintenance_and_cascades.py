"""Maintenance work orders: the non-linear hold/resume cycle, asset restoration,
the vehicle-grounding cascade, and the charger-operational start gate.

Difficulty (queue A): cyclic work-order state machine, depth-3 vehicle cascade,
ChargeSession->Charger cross-entity dependency.
Corner (queue B): illegal work-order transition, asset_type/id mismatch.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    fm_headers, op_headers, mt_headers,
)
import test_helpers.factories as fac
import test_helpers.fixtures as fx


# ---------------------------------------------------------------------------
# Difficulty: work-order IN_PROGRESS <-> ON_HOLD cycle then RESOLVED restores
# ---------------------------------------------------------------------------

def _cycled_charger_workorder(api):
    """Charger work order advanced OPEN->IN_PROGRESS->ON_HOLD->IN_PROGRESS (loop
    closed). Returns (depot, charger, wo)."""
    depot = fx.new_depot(api)
    charger = fx.new_charger(api, depot["id"], name="C1", max_power_kw=150)
    wo = fx.open_work_order(api, "CHARGER", charger_id=charger["id"], issue="coolant leak", severity="HIGH")
    fx.transition_work_order(api, wo["id"], "IN_PROGRESS")
    fx.transition_work_order(api, wo["id"], "ON_HOLD")
    fx.transition_work_order(api, wo["id"], "IN_PROGRESS")
    return depot, charger, wo


def test_workorder_hold_resume_cycle_resolves_and_restores_charger(api):
    """PRD §3.5: "The legal path is `OPEN → IN_PROGRESS`, then a non-linear loop
    of `IN_PROGRESS → ON_HOLD` and `ON_HOLD → IN_PROGRESS`, then
    `IN_PROGRESS → RESOLVED`, and finally `RESOLVED → CLOSED`."
    PRD §3.5: "If the order's `asset_type` is `CHARGER` and no other work order on
    that charger remains in a non-terminal state (any state other than `CLOSED`),
    the charger's `service_status` returns to `OPERATIONAL`."

    Design: Difficulty/non_linear_state_machine/work_order_hold_resume_cycle
    """
    depot, charger, wo = _cycled_charger_workorder(api)
    resolved = fx.transition_work_order(api, wo["id"], "RESOLVED")
    assert resolved["status"] == "RESOLVED"
    c_after = get_success_data(api.get_charger(charger["id"], fm_headers()))
    assert c_after["service_status"] == "OPERATIONAL", "resolving the only order restores the charger"


def test_workorder_resolved_downtime_is_zero_at_default_clock(api):
    """PRD §3.5: "its `downtime_minutes` is computed as the whole number of
    minutes from `opened_at` to `resolved_at` — the elapsed time in seconds
    divided by 60 and floored to an integer."

    Design: Difficulty/non_linear_state_machine/work_order_hold_resume_cycle
    """
    _, _, wo = _cycled_charger_workorder(api)
    resolved = fx.transition_work_order(api, wo["id"], "RESOLVED")
    # No clock advance between open and resolve => 0 elapsed minutes.
    assert resolved["downtime_minutes"] == 0, f"got {resolved['downtime_minutes']}"


# ---------------------------------------------------------------------------
# Difficulty: vehicle work order grounds vehicle and reverts its route (depth-3)
# ---------------------------------------------------------------------------

def test_vehicle_workorder_grounds_vehicle_and_forces_not_ready(api):
    """PRD §3.5: "For a **vehicle** order, the vehicle's `status` is set to
    `GROUNDED` and its `readiness_status` to `NOT_READY`; and if that vehicle
    currently holds a route in the `ASSIGNED` state, that route is reverted
    `ASSIGNED → PLANNED`."

    Design: Difficulty/transitive_cascade/vehicle_workorder_grounds_and_reverts_route
    """
    depot, vehicle, driver, route = fx.assigned_route(api, vehicle_soc=90, required_soc=80)
    fx.open_work_order(api, "VEHICLE", vehicle_id=vehicle["id"], issue="brake service", severity="HIGH")
    v_after = get_success_data(api.get_vehicle(vehicle["id"], fm_headers()))
    assert v_after["status"] == "GROUNDED"
    assert v_after["readiness_status"] == "NOT_READY"


def test_vehicle_workorder_reverts_assigned_route_to_planned(api):
    """PRD §3.5: "if that vehicle currently holds a route in the `ASSIGNED` state,
    that route is reverted `ASSIGNED → PLANNED`."

    Design: Difficulty/transitive_cascade/vehicle_workorder_grounds_and_reverts_route
    """
    depot, vehicle, driver, route = fx.assigned_route(api, vehicle_soc=90, required_soc=80)
    assert route["status"] == "ASSIGNED"
    fx.open_work_order(api, "VEHICLE", vehicle_id=vehicle["id"], issue="brake service", severity="HIGH")
    r_after = get_success_data(api.get_route(route["id"], fm_headers()))
    assert r_after["status"] == "PLANNED", "grounding the vehicle reverts its assigned route"


# ---------------------------------------------------------------------------
# Difficulty: start gated on charger OPERATIONAL (cross-entity)
# ---------------------------------------------------------------------------

def _downed_charger_scheduled_session(api):
    depot, charger, vehicle, session = fx.scheduled_session(
        api, vehicle_overrides={"current_soc_pct": 40})
    fx.open_work_order(api, "CHARGER", charger_id=charger["id"], issue="display fault", severity="MEDIUM")
    return depot, charger, vehicle, session


def test_start_on_downed_charger_returns_charger_down(api):
    """PRD §3.4: "It is permitted only when the session is in `SCHEDULED`
    (otherwise `ERR_SESSION_NOT_SCHEDULED`, HTTP 409) and the charger it occupies
    is currently `OPERATIONAL` (otherwise `ERR_CHARGER_DOWN`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/start_requires_charger_operational
    """
    _, _, _, session = _downed_charger_scheduled_session(api)
    resp = api.start_session(session["id"], {"actual_start": "2026-05-10T10:00:00Z"}, op_headers())
    validate_error(resp, ApiErrorId.ERR_CHARGER_DOWN.value)


def test_start_on_downed_charger_leaves_session_scheduled(api):
    """PRD §3.4: "**Beginning to charge** moves the session `SCHEDULED → ACTIVE`.
    It is permitted only when the session is in `SCHEDULED` (otherwise
    `ERR_SESSION_NOT_SCHEDULED`, HTTP 409) and the charger it occupies is
    currently `OPERATIONAL` (otherwise `ERR_CHARGER_DOWN`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/start_requires_charger_operational
    """
    _, _, _, session = _downed_charger_scheduled_session(api)
    api.start_session(session["id"], {"actual_start": "2026-05-10T10:00:00Z"}, op_headers())
    s_after = get_success_data(api.get_session(session["id"], fm_headers()))
    assert s_after["status"] == "SCHEDULED", "a rejected start must not advance the session"


# ---------------------------------------------------------------------------
# Corner: work-order transition legality and asset targeting
# ---------------------------------------------------------------------------

def test_workorder_open_to_resolved_skip_is_invalid(api):
    """PRD §3.5: "Any requested transition that is not one of these edges from
    the order's current status is rejected with `ERR_WORK_ORDER_INVALID_TRANSITION`
    (HTTP 409)".

    Design: Corner/state_machines/workorder_open_to_resolved_skip_returns_invalid_transition
    """
    depot = fx.new_depot(api)
    charger = fx.new_charger(api, depot["id"], name="C1", max_power_kw=150)
    wo = fx.open_work_order(api, "CHARGER", charger_id=charger["id"], issue="x", severity="LOW")
    resp = api.transition_work_order(wo["id"], {"target_status": "RESOLVED"}, mt_headers())
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_INVALID_TRANSITION.value)


def test_workorder_asset_type_id_mismatch_returns_invalid(api):
    """PRD §3.5: "A mismatch — the wrong id field for the declared `asset_type`,
    or both supplied — is rejected with `ERR_ASSET_TARGET_INVALID` (HTTP 422)."

    Design: Corner/validations/workorder_asset_type_id_mismatch_returns_invalid
    """
    depot = fx.new_depot(api)
    vehicle = fx.new_vehicle(api, depot["id"], current_soc_pct=40)
    payload = fac.create_work_order_payload("CHARGER", issue="x", severity="LOW", vehicle_id=vehicle["id"])
    resp = api.create_work_order(payload, mt_headers())
    validate_error(resp, ApiErrorId.ERR_ASSET_TARGET_INVALID.value)
