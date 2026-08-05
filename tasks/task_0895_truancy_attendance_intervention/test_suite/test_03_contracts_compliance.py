"""Attendance contracts: dual-variant compliance scoring, the pinned rounding order,
the breach/cure cycle, the compliance-check -> breach -> tier cascade, the held-conference
activation gate, OCC on contract creation, and validation-priority ordering."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, fixtures as fx, make_goal, TEST_USERS,
)

ADMIN = TEST_USERS["administrator_headers"]


def test_compliance_score_actual_uses_real_ratios(api):
    """PRD §3.6: "The **actual** score uses each goal's real ratio."

    Design: Difficulty/dual_variant_calc/contract_score_actual_vs_projected
    """
    school, student, case = fx.make_school_student_case(api)
    goals = [
        make_goal(description="Daily attendance", weight=1, target_value=10, met_value=0),
        make_goal(description="Tutoring sessions", weight=1, target_value=4, met_value=2),
    ]
    contract = fx.create_contract(api, case["id"], goals)
    # line1 round(0*0.5*100)=0.00 + line2 round(0.5*0.5*100)=25.00
    assert contract["compliance_score_actual"] == 25.00


def test_compliance_score_projected_treats_unstarted_as_met(api):
    """PRD §3.6: "The **projected** score is forward-looking: for any goal that has not
    yet been started — one whose `met_value` is exactly 0 — the projected ratio is taken
    as fully met (1.0), while a goal with any nonzero progress uses its real ratio
    unchanged."

    Design: Difficulty/dual_variant_calc/contract_score_actual_vs_projected
    """
    school, student, case = fx.make_school_student_case(api)
    goals = [
        make_goal(description="Daily attendance", weight=1, target_value=10, met_value=0),
        make_goal(description="Tutoring sessions", weight=1, target_value=4, met_value=2),
    ]
    contract = fx.create_contract(api, case["id"], goals)
    # line1 round(1*0.5*100)=50.00 + line2 25.00
    assert contract["compliance_score_projected"] == 75.00


def test_rounding_order_per_line_then_sum_actual(api):
    """PRD §3.6: "for each goal, multiply its ratio by its weight share ... and by 100,
    and round that per-goal contribution to 2 decimal places; then sum the rounded
    per-goal contributions and round the total to 2 decimal places, half-up. ... This
    per-line-then-sum order is deliberate and can differ in the last cent from a naive
    sum-then-round."

    Design: Difficulty/combinatorial_formula/contract_score_rounding_order
    """
    school, student, case = fx.make_school_student_case(api)
    goals = [
        make_goal(description="Goal one", weight=1, target_value=1, met_value=1),
        make_goal(description="Goal two", weight=1, target_value=1, met_value=1),
        make_goal(description="Goal three", weight=1, target_value=1, met_value=1),
    ]
    contract = fx.create_contract(api, case["id"], goals)
    # 3 x round(100/3, 2) = 3 x 33.33 = 99.99 (NOT the sum-then-round 100.00)
    assert contract["compliance_score_actual"] == 99.99


def test_rounding_order_per_line_then_sum_projected(api):
    """PRD §3.6: "then sum the rounded per-goal contributions and round the total to 2
    decimal places, half-up. `compliance_score_actual` is produced from the actual ratios
    and `compliance_score_projected` from the projected ratios."

    Design: Difficulty/combinatorial_formula/contract_score_rounding_order
    """
    school, student, case = fx.make_school_student_case(api)
    goals = [
        make_goal(description="Goal one", weight=1, target_value=1, met_value=1),
        make_goal(description="Goal two", weight=1, target_value=1, met_value=1),
        make_goal(description="Goal three", weight=1, target_value=1, met_value=1),
    ]
    contract = fx.create_contract(api, case["id"], goals)
    # each goal has nonzero progress so projected ratio == actual ratio == 1.0 -> 99.99
    assert contract["compliance_score_projected"] == 99.99


def test_active_contract_can_be_breached(api):
    """PRD §3.6: "The machine is cyclic around breach and cure: an `ACTIVE` contract can
    become `BREACHED`, and a `BREACHED` contract can be returned to `ACTIVE` — the cure
    loop, which changes no tier."

    Design: Difficulty/non_linear_state_machine/contract_breach_cure_cycle
    """
    school, staff, student, case, conf, contract = fx.make_case_with_active_contract(api)
    res = api.transition_contract(case["id"], contract["id"], {"to_status": "BREACHED"}, ADMIN)
    data = validate_success(res, 200)
    assert data["status"] == "BREACHED"


def test_breached_contract_can_be_cured_to_active(api):
    """PRD §3.6: "a `BREACHED` contract can be returned to `ACTIVE` — the cure loop,
    which changes no tier."

    Design: Difficulty/non_linear_state_machine/contract_breach_cure_cycle
    """
    school, staff, student, case, conf, contract = fx.make_case_with_active_contract(api)
    api.transition_contract(case["id"], contract["id"], {"to_status": "BREACHED"}, ADMIN)
    res = api.transition_contract(case["id"], contract["id"], {"to_status": "ACTIVE"}, ADMIN)
    data = validate_success(res, 200)
    assert data["status"] == "ACTIVE"


def _setup_tier1_case_with_active_contract(api):
    """Low-threshold assigned case at TIER_1 (one UNEXCUSED) with a HELD conference and
    an ACTIVE contract. Returns (case, contract)."""
    school, staff, student, case, conf = fx.make_case_with_held_conference(api, low_thresholds=True)
    fx.record_attendance(api, student["id"], "2026-09-01", "UNEXCUSED")  # TIER_1
    contract = fx.create_contract(api, case["id"], [make_goal(target_value=1, met_value=0)])
    contract = get_success_data(
        api.transition_contract(case["id"], contract["id"], {"to_status": "ACTIVE"}, ADMIN)
    )
    return case, contract


def test_non_compliant_check_breaches_contract_and_raises_tier(api):
    """PRD §3.9: "A `NON_COMPLIANT` result carries a consequence: if the case has a
    contract currently in `ACTIVE`, that contract is automatically driven to `BREACHED`,
    which — as in §3.6 — bumps the case's `breach_count` and advances the case's tier
    one step."

    Design: Difficulty/transitive_cascade/compliance_to_breach_to_tier
    """
    case, contract = _setup_tier1_case_with_active_contract(api)
    api.create_compliance_check(case["id"], {"check_date": "2026-09-15", "result": "NON_COMPLIANT"}, ADMIN)
    contract_after = validate_paginated(api.list_contracts(case["id"], ADMIN))[0][0]
    case_after = validate_success(api.get_case(case["id"], ADMIN), 200)
    assert contract_after["status"] == "BREACHED"
    assert case_after["tier"] == "TIER_2"


def test_breach_recomputes_breach_count(api):
    """PRD §3.6: "Whenever a contract enters `BREACHED`, the case's `breach_count` is
    recomputed upward by one and the case's `tier` advances exactly one step, capped at
    `COURT_REFERRED`."

    Design: Difficulty/transitive_cascade/compliance_to_breach_to_tier
    """
    case, contract = _setup_tier1_case_with_active_contract(api)
    api.create_compliance_check(case["id"], {"check_date": "2026-09-15", "result": "NON_COMPLIANT"}, ADMIN)
    case_after = validate_success(api.get_case(case["id"], ADMIN), 200)
    assert case_after["breach_count"] == 1


def test_contract_activates_with_held_conference(api):
    """PRD §3.6: "Moving `PROPOSED → ACTIVE` requires that the case already have a
    conference in `HELD`; without one the activation is rejected with
    `ERR_NO_CONFERENCE_HELD`."

    Design: Difficulty/cross_entity_state_dependency/contract_active_requires_held_conference
    """
    school, staff, student, case, conf = fx.make_case_with_held_conference(api)
    contract = fx.create_contract(api, case["id"], [make_goal(target_value=1, met_value=0)])
    res = api.transition_contract(case["id"], contract["id"], {"to_status": "ACTIVE"}, ADMIN)
    data = validate_success(res, 200)
    assert data["status"] == "ACTIVE"


def test_contract_activation_without_held_conference_rejected(api):
    """PRD §3.6: "Moving `PROPOSED → ACTIVE` requires that the case already have a
    conference in `HELD`; without one the activation is rejected with
    `ERR_NO_CONFERENCE_HELD`."

    Design: Difficulty/cross_entity_state_dependency/contract_active_requires_held_conference
    """
    school, staff, student, case = fx.make_assigned_case(api)
    contract = fx.create_contract(api, case["id"], [make_goal(target_value=1, met_value=0)])
    res = api.transition_contract(case["id"], contract["id"], {"to_status": "ACTIVE"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_NO_CONFERENCE_HELD.value)


def test_state_check_beats_conference_gate_on_cancelled_contract(api):
    """PRD §2.9: "7. State admissibility — the target resource is in a state that admits
    the requested transition ... and other inadmissible transitions yield
    `ERR_INVALID_STATE` (409). 8. Cross-entity gates — ... activating a contract or moving
    a case out of `OPEN` requires a held conference (`ERR_NO_CONFERENCE_HELD`, 409)."

    Design: Difficulty/priority_pair_validation_conflict/contract_activate_invalid_state_beats_no_conference
    """
    school, student, case = fx.make_school_student_case(api)
    contract = fx.create_contract(api, case["id"], [make_goal(target_value=1, met_value=0)])
    api.transition_contract(case["id"], contract["id"], {"to_status": "CANCELLED"}, ADMIN)
    res = api.transition_contract(case["id"], contract["id"], {"to_status": "ACTIVE"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_check_beats_conference_gate_even_when_conference_held(api):
    """PRD §3.6: "`FULFILLED` and `CANCELLED` are terminal." PRD §2.9: "When more than one
    rule could reject a request, checks are evaluated in a fixed priority order, and the
    first failing check determines the returned error."

    Design: Difficulty/priority_pair_validation_conflict/contract_activate_invalid_state_beats_no_conference
    """
    school, staff, student, case, conf = fx.make_case_with_held_conference(api)
    contract = fx.create_contract(api, case["id"], [make_goal(target_value=1, met_value=0)])
    api.transition_contract(case["id"], contract["id"], {"to_status": "CANCELLED"}, ADMIN)
    # The conference gate (p8) is satisfied, yet the terminal-state check (p7) still fires.
    res = api.transition_contract(case["id"], contract["id"], {"to_status": "ACTIVE"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_goal_progress_unknown_goal_not_found(api):
    """PRD §2.5: "The embedded `goal_id` referenced by a progress update is resolved after
    the path identifiers; if the goal is not embedded in the target contract, the update
    is rejected with `ERR_GOAL_NOT_FOUND`."

    Design: Corner/endpoints/goal_progress_goal_not_found
    """
    school, student, case = fx.make_school_student_case(api)
    contract = fx.create_contract(api, case["id"], [make_goal(description="Only goal", target_value=5, met_value=0)])
    res = api.update_goal_progress(
        case["id"], contract["id"], "00000000-0000-0000-0000-000000000000", {"met_value": 3}, ADMIN
    )
    validate_error(res, ApiErrorId.ERR_GOAL_NOT_FOUND.value)


def test_contract_create_stale_case_version_rejected(api):
    """PRD §2.8: "If `expected_case_version` does not equal the case's current `version`,
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because a case admits at
    most one non-terminal contract and each successful create both supersedes any prior
    contract and advances the case's `version`, a second create that still carries the
    pre-supersede version is operating on a stale view of the case and is refused on that
    basis."

    Design: Corner/cross_cutting/contract_create_stale_case_version_conflict
    """
    school, student, case = fx.make_school_student_case(api)
    stale_version = case["version"]
    first = api.create_contract(
        case["id"],
        {"start_date": "2026-09-01", "end_date": "2026-12-01",
         "goals": [make_goal(description="First plan", target_value=1, met_value=0)],
         "expected_case_version": stale_version},
        ADMIN,
    )
    validate_success(first, 201)
    second = api.create_contract(
        case["id"],
        {"start_date": "2026-09-02", "end_date": "2026-12-02",
         "goals": [make_goal(description="Second plan", target_value=1, met_value=0)],
         "expected_case_version": stale_version},
        ADMIN,
    )
    validate_error(second, ApiErrorId.ERR_STALE_VERSION.value)
