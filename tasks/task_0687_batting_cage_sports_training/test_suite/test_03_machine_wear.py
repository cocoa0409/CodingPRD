"""Pitching-machine wear: pitch_count accrues on COMPLETED sessions, status threshold
at DEGRADE_AT=5000 and OOS_AT=10000 (inclusive), reset on maintenance resolve.

Covers Difficulty rule dual_variant_calc (machine-wear instance) and
boundary_precision_check (degrade boundary), plus the maintenance-resolve reset
corner instance.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_member_headers,
    setup_member_ready,
    run_n_completed_sessions,
    run_completed_session,
    open_maintenance,
)

MANAGER = {"X-User-ID": "test-manager-1", "X-User-Role": "FacilityManager", "Content-Type": "application/json"}


# ─── dual_variant_calc / machine_wear_status_threshold_distinct_from_cost ──────

def test_five_completed_sessions_flip_machine_to_degraded(api):
    """PRD §3.6: "completion increases that machine's pitch_count by 1000 pitches per
    session". PRD §3.6: "a machine that reaches exactly 5000 pitches (for example after
    five completed sessions of 1000 pitches each) flips to DEGRADED at 5000 rather than
    at 5001".

    Design: Difficulty/dual_variant_calc/machine_wear_status_threshold_distinct_from_cost
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=200)
    machine = get_success_data(
        api.create_machine(
            {"facility_id": facility["id"], "lane_id": lane["id"], "model": "WHEEL"}, MANAGER
        )
    )
    run_n_completed_sessions(facility, lane, member, machine["id"], 5)
    after = get_success_data(api.get_machine(machine["id"], MANAGER))
    assert after["pitch_count"] == 5000
    assert after["status"] == "DEGRADED"


def test_pitch_count_accrues_one_thousand_per_session(api):
    """PRD §3.6: "If the booking named a machine_id, completion increases that machine's
    pitch_count by 1000 pitches per session and recomputes the machine's status from the
    new count." PRD §3.6: "otherwise at a count of at least 5000 the machine is DEGRADED;
    otherwise it is OPERATIONAL."

    Design: Difficulty/dual_variant_calc/machine_wear_status_threshold_distinct_from_cost
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=200)
    machine = get_success_data(
        api.create_machine(
            {"facility_id": facility["id"], "lane_id": lane["id"], "model": "WHEEL"}, MANAGER
        )
    )
    run_completed_session(
        facility, lane, member, "2026-04-01T09:00:00Z", "2026-04-01T09:10:00Z",
        machine_id=machine["id"],
    )
    after = get_success_data(api.get_machine(machine["id"], MANAGER))
    assert after["pitch_count"] == 1000
    assert after["status"] == "OPERATIONAL"


# ─── boundary_precision_check / machine_degrade_at_exactly_5000_pitches ────────

def test_machine_operational_at_4000_then_degraded_at_5000(api):
    """PRD §3.6: "otherwise at a count of at least 5000 the machine is DEGRADED;
    otherwise it is OPERATIONAL." PRD §3.6: "a machine that reaches exactly 5000 pitches
    (for example after five completed sessions of 1000 pitches each) flips to DEGRADED at
    5000 rather than at 5001".

    Design: Difficulty/boundary_precision_check/machine_degrade_at_exactly_5000_pitches
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=200)
    machine = get_success_data(
        api.create_machine(
            {"facility_id": facility["id"], "lane_id": lane["id"], "model": "WHEEL"}, MANAGER
        )
    )
    # Four sessions: 4000 pitches, still OPERATIONAL (below the 5000 boundary).
    run_n_completed_sessions(facility, lane, member, machine["id"], 4)
    at_four = get_success_data(api.get_machine(machine["id"], MANAGER))
    assert at_four["pitch_count"] == 4000
    assert at_four["status"] == "OPERATIONAL"

    # Fifth session: exactly 5000 -> DEGRADED at the boundary.
    run_completed_session(
        facility, lane, member, "2026-04-01T09:40:00Z", "2026-04-01T09:50:00Z",
        machine_id=machine["id"],
    )
    at_five = get_success_data(api.get_machine(machine["id"], MANAGER))
    assert at_five["pitch_count"] == 5000
    assert at_five["status"] == "DEGRADED"


def test_machine_below_boundary_remains_operational(api):
    """PRD §3.6: "A machine's status is purely a threshold over pitch_count: at a count
    of at least 10000 the machine is OUT_OF_SERVICE; otherwise at a count of at least
    5000 the machine is DEGRADED; otherwise it is OPERATIONAL."

    Design: Difficulty/boundary_precision_check/machine_degrade_at_exactly_5000_pitches
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=200)
    machine = get_success_data(
        api.create_machine(
            {"facility_id": facility["id"], "lane_id": lane["id"], "model": "WHEEL"}, MANAGER
        )
    )
    run_n_completed_sessions(facility, lane, member, machine["id"], 4)
    after = get_success_data(api.get_machine(machine["id"], MANAGER))
    assert after["pitch_count"] == 4000
    assert after["status"] == "OPERATIONAL"


# ─── cross_cutting corner: machine_pitch_count_reset_on_maintenance_resolve ────

def test_maintenance_resolve_resets_machine_pitch_count(api):
    """PRD §3.3: "When the last open window on a lane is resolved, the lane returns to
    AVAILABLE from either UNDER_MAINTENANCE or CLOSED; if that lane had a machine
    installed, the machine's pitch_count is reset to 0 and its status recomputed to
    OPERATIONAL".

    Design: Corner/cross_cutting_complexity_layers/machine_pitch_count_reset_on_maintenance_resolve
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=200)
    machine = get_success_data(
        api.create_machine(
            {"facility_id": facility["id"], "lane_id": lane["id"], "model": "WHEEL"}, MANAGER
        )
    )
    run_n_completed_sessions(facility, lane, member, machine["id"], 5)
    degraded = get_success_data(api.get_machine(machine["id"], MANAGER))
    assert degraded["pitch_count"] == 5000 and degraded["status"] == "DEGRADED"

    window = open_maintenance(
        facility, lane["id"], "2026-04-01T20:00:00Z", "2026-04-01T21:00:00Z", "ROUTINE"
    )
    validate_success(api.resolve_maintenance(window["id"], MANAGER), 200)

    reset = get_success_data(api.get_machine(machine["id"], MANAGER))
    assert reset["pitch_count"] == 0
    assert reset["status"] == "OPERATIONAL"
    lane_after = get_success_data(api.get_lane(lane["id"], MANAGER))
    assert lane_after["maint_status"] == "AVAILABLE"
