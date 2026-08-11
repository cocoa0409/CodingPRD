"""Validation priority pairs (PRD §2.5)."""
from test_helpers import (
    api_client, validate_error, get_success_data,
    create_active_program, create_program, create_and_approve_charter,
    create_and_approve_baseline, create_contract, begin_negotiation,
    create_stakeholder_group, create_occupancy_plan, coordinate_occupancy_plan,
    create_move_in_wave, create_change_order,
    pm_headers, exec_headers, owner_headers,
    ApiErrorId,
)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / state_beats_fiscal_on_contract_execute
# ---------------------------------------------------------------------------

def test_state_beats_fiscal_on_contract_execute_wrong_state(api):
    """PRD §2.5: "Every request is evaluated against an ordered pipeline of
    checks, and the first failing check determines the rejection — a later rule
    can never mask an earlier failure with its own error code." Priority 5
    (state gates) precedes priority 10 (fiscal limits).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_contract_execute
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}],
        name="P-P1",
    )
    pid = prog["id"]
    ct1 = create_contract(pid, solicitation_estimate_cents=500_000,
                           vendor_name="V1", contract_type="CONTRACTOR")
    # Never begin negotiation; contract stays SOLICITED. Award 2_000_000 exceeds budget too.
    resp = api_client.execute_contract(ct1["id"], {"awarded_amount_cents": 2_000_000},
                                        exec_headers())
    # State error wins (priority 5 before priority 10)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


def test_state_beats_fiscal_on_contract_execute_fiscal_would_also_fail(api):
    """PRD §3.2: "the fiscal check requires the award to fit within the
    program's uncommitted budget — awarded_amount_cents may not exceed
    current_budget_cents minus the sum of current_commitment_cents over the
    program's already-EXECUTED contracts (else ERR_AWARD_EXCEEDS_BUDGET, 402)."
    When the state gate passes, the fiscal check fires.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_contract_execute
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}],
        name="P-P1B",
    )
    pid = prog["id"]
    ct1 = create_contract(pid, solicitation_estimate_cents=500_000,
                           vendor_name="V1", contract_type="CONTRACTOR")
    begin_negotiation(ct1["id"])
    resp = api_client.execute_contract(ct1["id"], {"awarded_amount_cents": 2_000_000},
                                        exec_headers())
    # Now state passes; fiscal should fire
    validate_error(resp, ApiErrorId.ERR_AWARD_EXCEEDS_BUDGET)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / referential_beats_temporal_on_wave_create
# ---------------------------------------------------------------------------

def test_referential_beats_temporal_on_wave_create(api):
    """PRD §3.8: "Three guards apply at creation, in pipeline order: the plan
    must be in COORDINATING, READY, or EXECUTING (else
    ERR_PLAN_NOT_ACCEPTING_WAVES, 409); the stakeholder group must belong to
    the same program as the plan (else ERR_CROSS_PROGRAM_REFERENCE, 409); and
    the dock must be free under the occupation rule below (else
    ERR_DOCK_OVERLAP, 409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_wave_create
    """
    # Program PA with plan and a wave occupying DOCK_A 08:00-12:00
    pa = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="PA",
    )
    paid = pa["id"]
    ga = create_stakeholder_group(paid, group_name="GA", contact_email="ga@x.com")
    pla = create_occupancy_plan(paid, plan_name="PLA", target_move_month="2026-10")
    coordinate_occupancy_plan(pla["id"])
    create_move_in_wave(pla["id"], ga["id"], wave_name="WA", dock_resource="DOCK_A",
                         move_start="2026-10-01T08:00:00Z", move_end="2026-10-01T12:00:00Z",
                         criticality_weight=1)

    # Program PB with foreign group
    pb = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="PB",
    )
    pbid = pb["id"]
    gb = create_stakeholder_group(pbid, group_name="GB", group_type="COMMUNITY",
                                    contact_email="gb@x.com")

    # Wave on PA's plan with PB's group AND overlapping dock window:
    # referential (priority 7) beats temporal (priority 8)
    resp = api_client.create_move_in_wave(
        {
            "occupancy_plan_id": pla["id"],
            "stakeholder_group_id": gb["id"],
            "wave_name": "WX",
            "dock_resource": "DOCK_A",
            "move_start": "2026-10-01T10:00:00Z",
            "move_end": "2026-10-01T12:00:00Z",
            "criticality_weight": 1,
        },
        pm_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE)


def test_referential_beats_temporal_passes_referential_then_fires_dock(api):
    """PRD §3.8 dock overlap error path when referential passes:
    "the dock must be free under the occupation rule below (else
    ERR_DOCK_OVERLAP, 409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_wave_create
    """
    pa = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="PA2",
    )
    paid = pa["id"]
    ga = create_stakeholder_group(paid, group_name="GA", contact_email="ga@x.com")
    pla = create_occupancy_plan(paid, plan_name="PLA", target_move_month="2026-10")
    coordinate_occupancy_plan(pla["id"])
    create_move_in_wave(pla["id"], ga["id"], wave_name="WA", dock_resource="DOCK_A",
                         move_start="2026-10-01T08:00:00Z", move_end="2026-10-01T12:00:00Z",
                         criticality_weight=1)
    # Same program, same group, overlapping dock: only temporal fails
    resp = api_client.create_move_in_wave(
        {
            "occupancy_plan_id": pla["id"],
            "stakeholder_group_id": ga["id"],
            "wave_name": "WX",
            "dock_resource": "DOCK_A",
            "move_start": "2026-10-01T10:00:00Z",
            "move_end": "2026-10-01T12:00:00Z",
            "criticality_weight": 1,
        },
        pm_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_DOCK_OVERLAP)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / sod_beats_fiscal_on_contract_execute
# ---------------------------------------------------------------------------

def test_sod_beats_fiscal_on_contract_execute_same_user(api):
    """PRD §3.2: "Two checks guard this step, in pipeline order: the
    segregation check requires the executor's X-User-ID to differ from the
    recorded negotiator_user_id (else ERR_SEGREGATION_OF_DUTIES, 403), and the
    fiscal check requires the award to fit within the program's uncommitted
    budget — awarded_amount_cents may not exceed current_budget_cents minus
    the sum of current_commitment_cents over the program's already-EXECUTED
    contracts (else ERR_AWARD_EXCEEDS_BUDGET, 402)."

    Design: Difficulty/priority_pair_validation_conflict/sod_beats_fiscal_on_contract_execute
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-P3",
    )
    pid = prog["id"]
    ct1 = create_contract(pid, solicitation_estimate_cents=500_000,
                           vendor_name="V1", contract_type="CONTRACTOR")
    begin_negotiation(ct1["id"], pm_id="pm-1")  # negotiator is pm-1
    # Execute as exec role but with pm-1 user id (SoD violation); award also exceeds budget
    resp1 = api_client.execute_contract(ct1["id"], {"awarded_amount_cents": 2_000_000},
                                         exec_headers("pm-1"))
    validate_error(resp1, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_sod_beats_fiscal_on_contract_execute_fiscal_fires_after_sod_passes(api):
    """PRD §3.2: "the fiscal check requires the award to fit within the
    program's uncommitted budget — awarded_amount_cents may not exceed
    current_budget_cents minus the sum of current_commitment_cents over the
    program's already-EXECUTED contracts (else ERR_AWARD_EXCEEDS_BUDGET, 402)."

    Design: Difficulty/priority_pair_validation_conflict/sod_beats_fiscal_on_contract_execute
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-P3B",
    )
    pid = prog["id"]
    ct1 = create_contract(pid, solicitation_estimate_cents=500_000,
                           vendor_name="V1", contract_type="CONTRACTOR")
    begin_negotiation(ct1["id"], pm_id="pm-1")
    # Distinct exec user; only the fiscal check can fire
    resp = api_client.execute_contract(ct1["id"], {"awarded_amount_cents": 2_000_000},
                                        exec_headers("exec-1"))
    validate_error(resp, ApiErrorId.ERR_AWARD_EXCEEDS_BUDGET)
