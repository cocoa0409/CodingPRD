"""Calculation and scoring tests (Queue A difficulty rules + Queue B calculations).

Covers length-of-stay live/frozen, unit posture derived-vs-effective, placement
match scoring, ED boarding SLA, discharge-delay anchoring, and the EVS / occupancy
breadth calculations.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    set_clock, create_unit, add_clean_bed, add_bed,
    create_unit_with_clean_bed, register_and_admit, register_encounter,
    create_queued_request, assign_request, confirm_request,
    setup_placed_encounter, declare_surge, create_evs_task,
    create_block_payload, create_bed_request_payload,
    create_assign_payload, create_confirm_payload, create_evs_task_payload,
    create_bed_payload,
)
from test_helpers import api_client
from test_helpers.fixtures import ADMIN, BCC, NURSE, TCA, CM


# ============================================================================
# Difficulty: dual_variant_calc / los_live_vs_frozen_on_encounter
# ============================================================================

def test_los_live_value_grows_with_clock(api, bed_control_headers):
    """PRD §3.7: "While a patient is admitted and not yet discharged,
    length_of_stay_hours is the difference between the current clock and
    admitted_at, expressed in hours and rounded half-up to two decimal places".

    Design: Difficulty/dual_variant_calc/los_live_vs_frozen_on_encounter
    """
    set_clock("2026-06-01T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(
        unit_name="5 West", unit_type="TELEMETRY", gmlos_days=3,
        bed_label="501-A", telemetry_capable=True)
    enc = register_and_admit(mrn="M001", sex="MALE",
                             requires_telemetry=True, origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])

    set_clock("2026-06-06T00:00:00Z")
    placed = validate_success(api.get_encounter(enc["id"], bed_control_headers), 200)
    assert placed["status"] == "PLACED"
    assert placed["length_of_stay_hours"] == pytest.approx(112.0, abs=0.01), \
        f"admitted 2026-06-01T08:00Z, clock 2026-06-06T00:00Z = 112.0h, got {placed['length_of_stay_hours']}"


def test_los_long_stay_flag_set_past_threshold(api, bed_control_headers):
    """PRD §3.7: "A long_stay_flag is raised when the patient has actually been
    admitted (admitted_at is not null) and length_of_stay_hours has reached the
    unit's long-stay threshold, computed as the placement unit's gmlos_days
    multiplied by 24 and then by 1.5; the comparison is inclusive".

    Design: Difficulty/dual_variant_calc/los_live_vs_frozen_on_encounter
    """
    set_clock("2026-06-01T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(
        unit_name="5 West", unit_type="TELEMETRY", gmlos_days=3,
        bed_label="501-A", telemetry_capable=True)
    enc = register_and_admit(mrn="M001", sex="MALE",
                             requires_telemetry=True, origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])

    # gmlos 3 * 24 * 1.5 = 108h threshold; LOS at 112h >= 108 -> flag set.
    set_clock("2026-06-06T00:00:00Z")
    placed = validate_success(api.get_encounter(enc["id"], bed_control_headers), 200)
    assert placed["long_stay_flag"] is True


# ============================================================================
# Difficulty: dual_variant_calc / posture_derived_vs_effective_on_unit
# ============================================================================

def _setup_half_occupied_unit():
    """Unit with 2 staffed beds, 1 OCCUPIED (occupancy 50%, derived GREEN)."""
    set_clock("2026-06-02T00:00:00Z")
    unit = create_unit(name="ICU-A", unit_type="ICU", gmlos_days=4)
    bed_a = add_clean_bed(unit["id"], label="A1")
    add_clean_bed(unit["id"], label="A2")
    enc = register_and_admit(mrn="M050", sex="FEMALE", origin="DIRECT")
    req = create_queued_request(enc["id"])
    assign_request(req["id"], bed_a["id"])
    confirm_request(req["id"], bed_a["version"])
    return unit


def test_unit_derived_posture_green_at_fifty_percent(api, bed_control_headers):
    """PRD §2.7: "the system compares occupancy_pct against two inclusive thresholds:
    at 95.00 percent or above, posture is RED; at 85.00 percent or above but below
    95.00 percent, posture is YELLOW; below 85.00 percent, posture is GREEN."

    Design: Difficulty/dual_variant_calc/posture_derived_vs_effective_on_unit
    """
    unit = _setup_half_occupied_unit()
    declare_surge(unit["id"], "RED", reason="mass casualty")
    fetched = validate_success(api.get_unit(unit["id"], bed_control_headers), 200)
    assert fetched["occupancy_pct"] == pytest.approx(50.0, abs=0.01)
    assert fetched["derived_posture"] == "GREEN"


def test_unit_effective_posture_rises_to_red_under_surge(api, bed_control_headers):
    """PRD §2.7: "The unit's effective_posture is then the more severe of
    derived_posture and declared_surge_level, where severity ranks GREEN below
    YELLOW, YELLOW below RED, and RED below CLOSED."

    Design: Difficulty/dual_variant_calc/posture_derived_vs_effective_on_unit
    """
    unit = _setup_half_occupied_unit()
    declare_surge(unit["id"], "RED", reason="mass casualty")
    fetched = validate_success(api.get_unit(unit["id"], bed_control_headers), 200)
    assert fetched["declared_surge_level"] == "RED"
    assert fetched["effective_posture"] == "RED", \
        "GREEN derived + RED declared -> RED effective"


# ============================================================================
# Difficulty: combinatorial_formula / placement_score_multi_input_nonlinear
# ============================================================================

def test_auto_place_selects_higher_scoring_preferred_bed(api, bed_control_headers):
    """PRD §3.4: "Among eligible beds the server picks the one with the highest
    match_score" — "if the request named a preferred_unit_id and the bed's unit_id
    equals it, 50 is added."

    Design: Difficulty/combinatorial_formula/placement_score_multi_input_nonlinear
    """
    set_clock("2026-06-03T09:00:00Z")
    u1 = create_unit(name="U1", unit_type="TELEMETRY", gmlos_days=3)
    u2 = create_unit(name="U2", unit_type="TELEMETRY", gmlos_days=3)
    b1 = add_clean_bed(u1["id"], label="B1", telemetry_capable=True)
    add_clean_bed(u2["id"], label="B2", isolation_capable=True, telemetry_capable=True)
    enc = register_and_admit(mrn="M100", sex="MALE",
                             requires_telemetry=True, origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=u1["id"])

    res = api.auto_place(req["id"], bed_control_headers)
    placed = validate_success(res, 200)
    assert placed["assigned_bed_id"] == b1["id"], "preferred telemetry bed B1 wins"
    assert placed["status"] == "ASSIGNED"


def test_auto_place_match_score_value(api, bed_control_headers):
    """PRD §3.4: "A posture bonus is then added based on the bed's unit
    effective_posture: 20 for GREEN" — "if the request named a preferred_unit_id
    and the bed's unit_id equals it, 50 is added."

    Design: Difficulty/combinatorial_formula/placement_score_multi_input_nonlinear
    """
    set_clock("2026-06-03T09:00:00Z")
    u1 = create_unit(name="U1", unit_type="TELEMETRY", gmlos_days=3)
    u2 = create_unit(name="U2", unit_type="TELEMETRY", gmlos_days=3)
    add_clean_bed(u1["id"], label="B1", telemetry_capable=True)
    add_clean_bed(u2["id"], label="B2", isolation_capable=True, telemetry_capable=True)
    enc = register_and_admit(mrn="M100", sex="MALE",
                             requires_telemetry=True, origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=u1["id"])

    placed = validate_success(api.auto_place(req["id"], bed_control_headers), 200)
    # tele bed, patient needs tele -> no tele-waste; GREEN posture +20; preferred +50 = 70.
    assert placed["match_score"] == 70, f"expected 70, got {placed['match_score']}"


# ============================================================================
# Difficulty: combinatorial_formula / discharge_delay_round_then_floor_order
# ============================================================================

def test_discharge_order_at_anchored_on_order(api, case_manager_headers):
    """PRD §3.6: "A CaseManager or BedControlCoordinator first orders discharge on
    a PLACED patient, advancing PLACED → DISCHARGE_ORDERED, stamping
    discharge_order_at with the current clock".

    Design: Difficulty/combinatorial_formula/discharge_delay_round_then_floor_order
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS1", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="M1")
    enc = register_and_admit(mrn="M200", sex="FEMALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])
    set_clock("2026-06-05T10:00:00Z")
    api.discharge_order(enc["id"], case_manager_headers)

    set_clock("2026-06-07T12:00:00Z")
    fetched = validate_success(api.get_encounter(enc["id"], case_manager_headers), 200)
    assert fetched["status"] == "DISCHARGE_ORDERED"
    assert fetched["discharge_order_at"] == "2026-06-05T10:00:00.000Z", \
        f"expected order stamp 2026-06-05T10:00:00.000Z, got {fetched['discharge_order_at']}"


def test_discharge_order_keeps_patient_in_bed(api, case_manager_headers):
    """PRD §3.6: "A CaseManager or BedControlCoordinator first orders discharge on a
    PLACED patient, advancing PLACED → DISCHARGE_ORDERED, stamping discharge_order_at
    with the current clock, and appending a discharge-order ADT event."

    Design: Difficulty/combinatorial_formula/discharge_delay_round_then_floor_order
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS1", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="M1")
    enc = register_and_admit(mrn="M200", sex="FEMALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])
    set_clock("2026-06-05T10:00:00Z")
    ordered = validate_success(api.discharge_order(enc["id"], case_manager_headers), 200)
    assert ordered["status"] == "DISCHARGE_ORDERED"
    assert ordered["current_bed_id"] == bed["id"], "patient remains in bed after order"


# ============================================================================
# Difficulty: boundary_precision_check / ed_boarding_sla_inclusive_at_four_hours
# ============================================================================

def test_boarding_hours_frozen_at_four_on_placement(api, bed_control_headers):
    """PRD §3.5: "For a BOARDING ED patient, boarding_hours is frozen at the
    difference between the current clock and admit_decision_at".

    Design: Difficulty/boundary_precision_check/ed_boarding_sla_inclusive_at_four_hours
    """
    set_clock("2026-06-02T06:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="EDU", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="E1B")
    enc = register_and_admit(mrn="M900", sex="FEMALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    set_clock("2026-06-02T10:00:00Z")  # exactly 4.00h after admit
    confirm_request(req["id"], bed["version"])

    fetched = validate_success(api.get_encounter(enc["id"], bed_control_headers), 200)
    assert fetched["boarding_hours"] == pytest.approx(4.0, abs=0.01), \
        f"06:00 admit, 10:00 placed = 4.00h, got {fetched['boarding_hours']}"


def test_boarding_breached_inclusive_at_sla(api, bed_control_headers):
    """PRD §3.3: "A companion flag, boarding_breached, is true exactly when
    boarding_hours is at least 4.0 hours — the ED boarding service-level threshold
    — and false otherwise."

    Design: Difficulty/boundary_precision_check/ed_boarding_sla_inclusive_at_four_hours
    """
    set_clock("2026-06-02T06:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="EDU", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="E1B")
    enc = register_and_admit(mrn="M900", sex="FEMALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    set_clock("2026-06-02T10:00:00Z")  # exactly 4.00h
    confirm_request(req["id"], bed["version"])

    fetched = validate_success(api.get_encounter(enc["id"], bed_control_headers), 200)
    assert fetched["boarding_breached"] is True, "4.00h >= 4.0 SLA is inclusive -> breached"


# ============================================================================
# Difficulty: boundary_precision_check / auto_place_empty_eligible_pool_zero_set
# ============================================================================

def test_auto_place_empty_pool_returns_no_eligible_bed(api, bed_control_headers):
    """PRD §3.4: "If the eligible pool is empty, auto-place selects nothing, leaves
    the request in QUEUED, and returns ERR_NO_ELIGIBLE_BED (HTTP 409)."

    Design: Difficulty/boundary_precision_check/auto_place_empty_eligible_pool_zero_set
    """
    set_clock("2026-06-03T07:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS6", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="N1",
                                           isolation_capable=False)
    enc = register_and_admit(mrn="M950", sex="MALE",
                             requires_isolation=True, origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])

    res = api.auto_place(req["id"], bed_control_headers)
    validate_error(res, "ERR_NO_ELIGIBLE_BED")


def test_auto_place_empty_pool_leaves_request_queued(api, bed_control_headers, transfer_agent_headers):
    """PRD §3.4: "If the eligible pool is empty, auto-place selects nothing, leaves
    the request in QUEUED, and returns ERR_NO_ELIGIBLE_BED (HTTP 409)."

    Design: Difficulty/boundary_precision_check/auto_place_empty_eligible_pool_zero_set
    """
    set_clock("2026-06-03T07:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS6", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="N1",
                                           isolation_capable=False)
    enc = register_and_admit(mrn="M950", sex="MALE",
                             requires_isolation=True, origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    api.auto_place(req["id"], bed_control_headers)

    fetched = validate_success(api.get_bed_request(req["id"], transfer_agent_headers), 200)
    assert fetched["status"] == "QUEUED"
    assert fetched["assigned_bed_id"] is None


# ============================================================================
# Corner: calculations / evs_priority_score_isolation_base_green
# ============================================================================

def test_evs_priority_score_isolation_green_unit(api, charge_nurse_headers):
    """PRD §3.9: "The base comes from task_type: 100 for STAT, 70 for ISOLATION,
    40 for ROUTINE. A surge component is added from the bed's unit
    effective_posture: 30 for RED, 15 for YELLOW, and 0 for GREEN or CLOSED."

    Design: Corner/calculations/evs_priority_score_isolation_base_green
    """
    set_clock("2026-06-05T08:00:00Z")
    unit = create_unit(name="PsWard", unit_type="MEDSURG")
    bed = add_bed(unit["id"], label="PS1")  # DIRTY
    task = create_evs_task(bed["id"], task_type="ISOLATION")

    fetched = validate_success(api.get_evs_task(task["id"], charge_nurse_headers), 200)
    # base 70 + surge 0 (GREEN) + aging 0 (0 wait) = 70.
    assert fetched["priority_score"] == 70, f"expected 70, got {fetched['priority_score']}"


# ============================================================================
# Corner: calculations / occupancy_pct_zero_when_no_staffed_beds
# ============================================================================

def test_occupancy_zero_and_closed_when_no_staffed_beds(api, bed_control_headers):
    """PRD §2.7: "when a unit has zero staffed beds, occupancy_pct is 0.00." —
    "If the unit has no staffed beds at all, derived_posture is CLOSED."

    Design: Corner/calculations/occupancy_pct_zero_when_no_staffed_beds
    """
    unit = create_unit(name="ZWard", unit_type="MEDSURG")
    bed = add_bed(unit["id"], label="Z1")  # DIRTY -> staffed
    # PRD §4: block is authorized for ChargeNurse, FlowAdmin (not BedControlCoordinator).
    api.block_bed(unit["id"], bed["id"], create_block_payload("MAINTENANCE"), NURSE)

    fetched = validate_success(api.get_unit(unit["id"], bed_control_headers), 200)
    assert fetched["staffed_bed_count"] == 0
    assert fetched["occupancy_pct"] == pytest.approx(0.0, abs=0.01)
    assert fetched["derived_posture"] == "CLOSED"


# ============================================================================
# Corner: calculations / occupancy_pct_25_derived_green
# ============================================================================

def test_occupancy_twenty_five_pct_derived_green(api, bed_control_headers):
    """PRD §2.7: "occupancy_pct is the number of OCCUPIED beds divided by the number
    of staffed beds, multiplied by 100 and rounded half-up to two decimal places" —
    "below 85.00 percent, posture is GREEN."

    Design: Corner/calculations/occupancy_pct_25_derived_green
    """
    set_clock("2026-06-05T08:00:00Z")
    unit = create_unit(name="QWard", unit_type="MEDSURG")
    b1 = add_clean_bed(unit["id"], label="Q1")
    add_clean_bed(unit["id"], label="Q2")
    add_clean_bed(unit["id"], label="Q3")
    add_clean_bed(unit["id"], label="Q4")
    enc = register_and_admit(mrn="MS11", sex="MALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], b1["id"])
    confirm_request(req["id"], b1["version"])

    fetched = validate_success(api.get_unit(unit["id"], bed_control_headers), 200)
    assert fetched["occupancy_pct"] == pytest.approx(25.0, abs=0.01)
    assert fetched["derived_posture"] == "GREEN"


# ============================================================================
# Corner: calculations / capacity_huddle_aggregates_house_snapshot
# ============================================================================

def test_capacity_huddle_snapshot_counts(api, bed_control_headers):
    """PRD §3.10: "boarding_encounter_count is the number of encounters in BOARDING;
    queued_request_count is the number of bed requests in QUEUED" — "total_staffed_beds
    is the sum of every unit's staffed_bed_count".

    Design: Corner/calculations/capacity_huddle_aggregates_house_snapshot
    """
    set_clock("2026-06-05T09:00:00Z")
    enc = register_and_admit(mrn="MS12", sex="FEMALE", origin="ED")  # -> BOARDING
    create_queued_request(enc["id"])  # QUEUED

    res = api.create_capacity_huddle(bed_control_headers)
    huddle = validate_success(res, 201)
    assert huddle["boarding_encounter_count"] == 1
    assert huddle["queued_request_count"] == 1
    assert huddle["total_staffed_beds"] == 0
