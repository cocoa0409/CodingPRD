"""Charge-session lifecycle: estimated/final energy cost, the ACTIVE fork, the
charger-fault interruption cascade, and reserved-load conservation.

Difficulty (queue A): dual-variant session cost, branching fork, transitive
charger cascade, compensating reserved-power invariant.
Corner (queue B): completing a SCHEDULED session, cancelling a COMPLETED one.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    fm_headers, op_headers, mt_headers, TOU_WINDOWS_FOUR,
)
import test_helpers.factories as fac
import test_helpers.fixtures as fx


# ---------------------------------------------------------------------------
# Difficulty: dual-variant session energy cost (estimated vs final)
# ---------------------------------------------------------------------------

def _tou_scheduled_session(api):
    """Depot with a 4-window TOU tariff; vehicle SOC 50; session [08:00,10:00)
    target 90 power 100. Returns (depot, session)."""
    depot = fx.new_depot(api, max_load_kw=500, contracted_capacity_kw=300,
                         demand_rate_cents_per_kw=1000, overage_rate_cents_per_kw=2500,
                         tariff_windows=[dict(w) for w in TOU_WINDOWS_FOUR])
    c1 = fx.new_charger(api, depot["id"], name="C1", connector_type="CCS", max_power_kw=150)
    v1 = fx.new_vehicle(api, depot["id"], vin="V1", connector_type="CCS",
                        battery_capacity_kwh=100, current_soc_pct=50)
    session = fx.schedule_session(api, depot["id"], c1["id"], v1["id"], fx.depot_version(api, depot["id"]),
                                  scheduled_start="2026-05-10T08:00:00Z", scheduled_end="2026-05-10T10:00:00Z",
                                  target_soc_pct=90, power_kw=100)
    return depot, session


def test_session_estimated_cost_single_window_rate(api):
    """PRD §3.3: "take the estimated energy to be delivered as the target rise in
    charge over the current charge, expressed as a fraction of the battery — that
    is, `target_soc_pct` minus the vehicle's `current_soc_pct`, divided by 100,
    multiplied by the vehicle's `battery_capacity_kwh`, and floored at zero so a
    non-positive delta yields zero energy — then multiply that energy by the
    depot tariff rate for the clock hour of `scheduled_start`, and round half up
    to whole cents."

    Design: Difficulty/dual_variant_calc/session_energy_cost_estimated_vs_final
    """
    _, session = _tou_scheduled_session(api)
    # (90-50)/100 * 100 kWh = 40 kWh; hour 8 -> MID rate 20 => 800c.
    assert session["estimated_cost_cents"] == 800, f"got {session['estimated_cost_cents']}"


def test_session_final_cost_tou_allocation_diverges_from_estimate(api):
    """PRD §3.4: "Otherwise the energy is treated as delivered at constant power
    across the half-open interval `[actual_start, actual_end)` and allocated to
    each tariff window in proportion to the number of seconds the interval spends
    inside that window: for each window the interval overlaps, take the final
    energy multiplied by that window's overlap seconds divided by the total
    duration, multiplied by that window's `rate_cents_per_kwh`; sum these
    contributions across all overlapped windows and round the total half up to
    whole cents."

    Design: Difficulty/dual_variant_calc/session_energy_cost_estimated_vs_final
    """
    _, session = _tou_scheduled_session(api)
    fx.start_session(api, session["id"], actual_start="2026-05-10T15:00:00Z")
    done = fx.complete_session(api, session["id"], 90, actual_end="2026-05-10T17:00:00Z")
    # 40 kWh over [15:00,17:00): 1h MID(20) + 1h PEAK(40) => 40*0.5*20 + 40*0.5*40 = 1200c.
    assert done["final_cost_cents"] == 1200, f"got {done['final_cost_cents']}"
    assert done["estimated_cost_cents"] != done["final_cost_cents"], "estimate and final must diverge"


# ---------------------------------------------------------------------------
# Difficulty: the ACTIVE fork — complete branch
# ---------------------------------------------------------------------------

def _flat_active_session(api, soc=50, power=100, target=80):
    depot = fx.new_depot(api)
    c1 = fx.new_charger(api, depot["id"], name="C1", connector_type="CCS", max_power_kw=150)
    v1 = fx.new_vehicle(api, depot["id"], vin="V1", connector_type="CCS",
                        battery_capacity_kwh=100, current_soc_pct=soc)
    session = fx.schedule_session(api, depot["id"], c1["id"], v1["id"], fx.depot_version(api, depot["id"]),
                                  scheduled_start="2026-05-10T10:00:00Z", scheduled_end="2026-05-10T11:00:00Z",
                                  target_soc_pct=target, power_kw=power)
    started = fx.start_session(api, session["id"], actual_start="2026-05-10T10:00:00Z")
    return depot, c1, v1, started


def test_active_session_completes_with_final_cost(api):
    """PRD §3.4: "**Completing** a session moves it `ACTIVE → COMPLETED` and is
    the normal, metered end of charging."
    PRD §3.4: "If that duration is zero or negative, the entire final energy is
    priced at the single tariff rate for the clock hour of `actual_start`,
    rounded half up to whole cents."

    Design: Difficulty/non_linear_state_machine/charge_session_active_branching_fork
    """
    depot, _, _, session = _flat_active_session(api)
    done = fx.complete_session(api, session["id"], 80, actual_end="2026-05-10T11:00:00Z")
    assert done["status"] == "COMPLETED"
    # (80-50)/100 * 100 kWh = 30 kWh at flat 20 c/kWh over [10:00,11:00) => 600c.
    assert done["final_cost_cents"] == 600, f"got {done['final_cost_cents']}"


def test_active_session_complete_raises_soc_and_releases_load(api):
    """PRD §3.4: "the vehicle's `current_soc_pct` is set to `end_soc_pct` and its
    `readiness_status` recomputed, and the depot's `reserved_load_kw` is credited
    by the session's `power_kw`."

    Design: Difficulty/non_linear_state_machine/charge_session_active_branching_fork
    """
    depot, _, vehicle, session = _flat_active_session(api)
    fx.complete_session(api, session["id"], 80, actual_end="2026-05-10T11:00:00Z")
    v_after = get_success_data(api.get_vehicle(vehicle["id"], fm_headers()))
    assert v_after["current_soc_pct"] == 80, f"soc must become end_soc 80, got {v_after['current_soc_pct']}"
    assert fx.get_depot(api, depot["id"])["reserved_load_kw"] == 0, "reserved load released on complete"


# ---------------------------------------------------------------------------
# Difficulty: charger work-order interrupts the ACTIVE session (depth-3 cascade)
# ---------------------------------------------------------------------------

def test_charger_workorder_downs_charger_and_interrupts_session(api):
    """PRD §3.5: "the charger's `service_status` is set to `DOWN`, and every
    session currently `ACTIVE` on that charger is driven `ACTIVE → INTERRUPTED`".

    Design: Difficulty/transitive_cascade/charger_workorder_interrupts_session_releases_load
    """
    depot, charger, _, session = _flat_active_session(api, soc=30)
    fx.open_work_order(api, "CHARGER", charger_id=charger["id"], issue="connector fault", severity="HIGH")
    c_after = get_success_data(api.get_charger(charger["id"], fm_headers()))
    s_after = get_success_data(api.get_session(session["id"], fm_headers()))
    assert c_after["service_status"] == "DOWN"
    assert s_after["status"] == "INTERRUPTED"


def test_interrupted_session_zeroes_cost_and_releases_load(api):
    """PRD §3.4: "An interrupted session records no gain and no cost — its
    `end_soc_pct` is set equal to its `start_soc_pct`, its `energy_kwh_delivered`
    is set to 0, and its `final_cost_cents` is set to 0 — its `actual_end` is
    stamped from the logical clock, the depot's `reserved_load_kw` is credited by
    the session's `power_kw`, and the vehicle's `readiness_status` is recomputed."

    Design: Difficulty/transitive_cascade/charger_workorder_interrupts_session_releases_load
    """
    depot, charger, _, session = _flat_active_session(api, soc=30)
    fx.open_work_order(api, "CHARGER", charger_id=charger["id"], issue="fault", severity="HIGH")
    s_after = get_success_data(api.get_session(session["id"], fm_headers()))
    assert s_after["final_cost_cents"] == 0, "interrupted session has no cost"
    assert fx.get_depot(api, depot["id"])["reserved_load_kw"] == 0, "reserved load released on interrupt"


# ---------------------------------------------------------------------------
# Difficulty: reserved-load conservation across schedule then cancel
# ---------------------------------------------------------------------------

def test_schedule_debits_reserved_load(api):
    """PRD §3.3: "the depot's `reserved_load_kw` is debited by the session's
    `power_kw`, and the depot's `version` is incremented by 1."

    Design: Difficulty/compensating_invariant/reserved_load_conserved_schedule_then_cancel
    """
    depot = fx.new_depot(api)
    charger = fx.new_charger(api, depot["id"], connector_type="CCS", max_power_kw=150)
    vehicle = fx.new_vehicle(api, depot["id"], connector_type="CCS", current_soc_pct=20)
    fx.schedule_session(api, depot["id"], charger["id"], vehicle["id"], fx.depot_version(api, depot["id"]),
                        target_soc_pct=50, power_kw=120)
    assert fx.get_depot(api, depot["id"])["reserved_load_kw"] == 120


def test_cancel_credits_reserved_load_back_to_zero(api):
    """PRD §3.4: "Cancelling delivers no energy and releases the reservation: the
    depot's `reserved_load_kw` is credited (reduced) by the session's `power_kw`."

    Design: Difficulty/compensating_invariant/reserved_load_conserved_schedule_then_cancel
    """
    depot = fx.new_depot(api)
    charger = fx.new_charger(api, depot["id"], connector_type="CCS", max_power_kw=150)
    vehicle = fx.new_vehicle(api, depot["id"], connector_type="CCS", current_soc_pct=20)
    session = fx.schedule_session(api, depot["id"], charger["id"], vehicle["id"],
                                  fx.depot_version(api, depot["id"]), target_soc_pct=50, power_kw=120)
    cancelled = fx.cancel_session(api, session["id"])
    assert cancelled["status"] == "CANCELLED"
    assert fx.get_depot(api, depot["id"])["reserved_load_kw"] == 0, "schedule +120 then cancel -120 conserve to 0"


# ---------------------------------------------------------------------------
# Corner: invalid-state transitions on a session
# ---------------------------------------------------------------------------

def test_complete_scheduled_session_returns_not_active(api):
    """PRD §3.4: "It requires the session to be `ACTIVE` (otherwise
    `ERR_SESSION_NOT_ACTIVE`, HTTP 409)."

    Design: Corner/state_machines/complete_scheduled_session_returns_not_active
    """
    _, _, _, session = fx.scheduled_session(api, vehicle_overrides={"current_soc_pct": 40})
    resp = api.complete_session(session["id"], {"end_soc_pct": 80}, op_headers())
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_ACTIVE.value)


def test_cancel_completed_session_returns_not_scheduled(api):
    """PRD §3.4: "**Cancelling** a session that is still `SCHEDULED` moves it
    `SCHEDULED → CANCELLED`; if the session is not in `SCHEDULED` the request is
    rejected with `ERR_SESSION_NOT_SCHEDULED`."

    Design: Corner/state_machines/cancel_completed_session_terminal_lockdown_returns_not_scheduled
    """
    depot, _, _, session = _flat_active_session(api, soc=50, target=60)
    fx.complete_session(api, session["id"], 60, actual_end="2026-05-10T11:00:00Z")
    resp = api.cancel_session(session["id"], op_headers())
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_SCHEDULED.value)
