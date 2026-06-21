"""Brand-standard audit scoring, grade banding, and the compliance cascades it drives.

Covers audit-score boundary precision, the parallel operational/compliance Unit
dimensions, the depth-3 audit→suspend→strike→default cascade, the strike-conservation
compensating invariant, and the audit side-effect corner instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    setup_in_progress_audit,
    create_unit,
    open_unit,
    create_in_progress_audit,
    finalize_audit,
    setup_suspended_unit,
    setup_brand_franchisee_territory,
    create_territory,
    assign_territory,
)

AUDITOR = TEST_USERS["compliance_auditor_headers"]
FRANCHISOR = TEST_USERS["franchisor_headers"]
CLERK = TEST_USERS["finance_clerk_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: boundary_precision_check / audit_overall_score_pass_floor_ge_90
# ═══════════════════════════════════════════════════════════════════════════
def test_audit_overall_score_exactly_90_grades_pass():
    """PRD §3.7: "it is PASS when the overall score is at least 90.0, CONDITIONAL when
    the overall score is at least 70.0 but below 90.0, and FAIL otherwise (any overall
    score below 70.0)."

    Design: Difficulty/boundary_precision_check/audit_overall_score_pass_floor_ge_90
    """
    _, _, _, unit, audit = setup_in_progress_audit(owner_user_id="u_p90", territory_code="P90")
    finalized = finalize_audit(audit["id"], 90, 90, 90, 90)
    assert finalized["overall_score"] == 90.0
    assert finalized["grade"] == "PASS", "overall 90.0 is >= 90.0 inclusive → PASS"


def test_audit_pass_leaves_good_standing_unchanged():
    """PRD §3.5: "a finalized audit graded PASS moves a unit from PROBATION back to
    GOOD_STANDING."
    PRD §3.7: "it is PASS when the overall score is at least 90.0."

    Design: Difficulty/boundary_precision_check/audit_overall_score_pass_floor_ge_90
    """
    _, _, _, unit, audit = setup_in_progress_audit(owner_user_id="u_p90b", territory_code="P9B")
    finalize_audit(audit["id"], 90, 90, 90, 90)
    refreshed = get_success_data(api_client.get_unit(unit["id"], FRANCHISOR))
    # PASS on a GOOD_STANDING unit only moves PROBATION→GOOD_STANDING; a GOOD_STANDING
    # unit therefore stays GOOD_STANDING (no transition is defined out of it on PASS).
    assert refreshed["compliance_status"] == "GOOD_STANDING"


def test_audit_score_just_below_pass_floor_is_conditional():
    """PRD §3.7: "CONDITIONAL when the overall score is at least 70.0 but below 90.0."

    Design: Difficulty/boundary_precision_check/audit_overall_score_pass_floor_ge_90
    """
    # 89/90/90/90 → 0.40*89 + 0.25*90 + 0.20*90 + 0.15*90 = 35.6+22.5+18+13.5 = 89.6
    _, _, _, unit, audit = setup_in_progress_audit(owner_user_id="u_p89", territory_code="P89")
    finalized = finalize_audit(audit["id"], 89, 90, 90, 90)
    assert finalized["overall_score"] == 89.6
    assert finalized["grade"] == "CONDITIONAL", "89.6 < 90.0 → CONDITIONAL, not PASS"


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: non_linear_state_machine / unit_parallel_operational_and_compliance
# ═══════════════════════════════════════════════════════════════════════════
def test_fail_audit_suspends_compliance_leaves_operational_open():
    """PRD §3.5: "a finalized audit graded FAIL moves a unit from either GOOD_STANDING
    or PROBATION to SUSPENDED."
    PRD §3.5: "The two never disturb one another — an operational transition leaves
    compliance untouched and vice versa."

    Design: Difficulty/non_linear_state_machine/unit_parallel_operational_and_compliance_dimensions
    """
    _, _, _, unit, audit = setup_in_progress_audit(owner_user_id="u_par", territory_code="PAR")
    finalized = finalize_audit(audit["id"], 50, 50, 50, 50)  # overall 50.0 → FAIL
    assert finalized["grade"] == "FAIL"
    refreshed = get_success_data(api_client.get_unit(unit["id"], FRANCHISOR))
    assert refreshed["compliance_status"] == "SUSPENDED", "FAIL drives compliance axis"
    assert refreshed["operational_status"] == "OPEN", "operational axis unchanged"


def test_parallel_dimensions_independent_after_fail():
    """PRD §3.5: "a unit lives two independent lives on the same record: an operational
    dimension in operational_status and a compliance dimension in compliance_status."
    PRD §3.7: "If the grade is FAIL, the unit moves from GOOD_STANDING or PROBATION to
    SUSPENDED."

    Design: Difficulty/non_linear_state_machine/unit_parallel_operational_and_compliance_dimensions
    """
    _, _, _, unit, audit = setup_in_progress_audit(owner_user_id="u_par2", territory_code="PA2")
    finalize_audit(audit["id"], 40, 40, 40, 40)
    refreshed = get_success_data(api_client.get_unit(unit["id"], FRANCHISOR))
    # operational dimension is still OPEN and reachable (CLOSE would work), while the
    # compliance dimension has moved to SUSPENDED — the two evolved independently.
    assert refreshed["operational_status"] == "OPEN"
    assert refreshed["compliance_status"] == "SUSPENDED"


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: transitive_cascade / audit_fail_suspends_unit_strikes_default_depth3
# ═══════════════════════════════════════════════════════════════════════════
def _setup_two_open_units(owner="u_casc"):
    brand, franchisee, terr1 = setup_brand_franchisee_territory(
        owner_user_id=owner, territory_code="C1"
    )
    terr2 = create_territory(brand["id"], code="C2")
    assign_territory(terr2["id"], franchisee["id"])
    unit1 = create_unit(franchisee["id"], terr1["id"], address="U1")
    unit1 = open_unit(unit1["id"], owner)
    unit2 = create_unit(franchisee["id"], terr2["id"], address="U2")
    unit2 = open_unit(unit2["id"], owner)
    return brand, franchisee, unit1, unit2


def test_second_fail_audit_defaults_franchisee_via_strikes():
    """PRD §3.5: "Whenever a unit enters SUSPENDED, the owning franchisee's
    open_compliance_strikes is incremented by one; if that count reaches 2 and the
    franchisee is ACTIVE, the franchisee is moved ACTIVE → DEFAULTED."

    Design: Difficulty/transitive_cascade/audit_fail_suspends_unit_strikes_default_franchisee_depth3
    """
    brand, franchisee, unit1, unit2 = _setup_two_open_units(owner="u_casc")
    # Suspend unit1 first → strikes = 1.
    a1 = create_in_progress_audit(unit1["id"])
    finalize_audit(a1["id"], 40, 40, 40, 40)
    # Suspend unit2 → strikes = 2 → franchisee DEFAULTED.
    a2 = create_in_progress_audit(unit2["id"])
    finalize_audit(a2["id"], 40, 40, 40, 40)
    u2 = get_success_data(api_client.get_unit(unit2["id"], FRANCHISOR))
    fz = get_success_data(api_client.get_franchisee(franchisee["id"], FRANCHISOR))
    assert u2["compliance_status"] == "SUSPENDED"  # hop 1
    assert fz["open_compliance_strikes"] == 2  # hop 2
    assert fz["status"] == "DEFAULTED"  # hop 3


def test_first_fail_audit_increments_strikes_without_default():
    """PRD §3.5: "Whenever a unit enters SUSPENDED, the owning franchisee's
    open_compliance_strikes is incremented by one; if that count reaches 2 and the
    franchisee is ACTIVE, the franchisee is moved ACTIVE → DEFAULTED."

    Design: Difficulty/transitive_cascade/audit_fail_suspends_unit_strikes_default_franchisee_depth3
    """
    brand, franchisee, unit1, unit2 = _setup_two_open_units(owner="u_casc2")
    a1 = create_in_progress_audit(unit1["id"])
    finalize_audit(a1["id"], 40, 40, 40, 40)
    fz = get_success_data(api_client.get_franchisee(franchisee["id"], FRANCHISOR))
    assert fz["open_compliance_strikes"] == 1, "one suspension → one strike"
    assert fz["status"] == "ACTIVE", "one strike (< 2) does not default the franchisee"


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: compensating_invariant / compliance_strike_conservation
# ═══════════════════════════════════════════════════════════════════════════
def test_reinstate_restores_strike_count_to_zero():
    """PRD §3.6: "Reinstatement reverses the strike that suspension imposed: the owning
    franchisee's open_compliance_strikes is decremented by one, and if that count drops
    below 2 while the franchisee is DEFAULTED, the franchisee recovers DEFAULTED →
    ACTIVE."

    Design: Difficulty/compensating_invariant/compliance_strike_conservation_suspend_then_reinstate
    """
    # FAIL audit suspends the unit (strikes 1); a later PASS audit provides the
    # remediation evidence; reinstate then restores strikes to 0.
    brand, franchisee, terr, unit, fail_audit = setup_suspended_unit(
        owner_user_id="u_inv", territory_code="INV"
    )
    pass_audit = create_in_progress_audit(unit["id"])
    finalize_audit(pass_audit["id"], 95, 95, 95, 95)
    reinstated = validate_success(
        api_client.reinstate_unit(unit["id"], FRANCHISOR), expected_status=200
    )
    assert reinstated["compliance_status"] == "PROBATION"
    fz = get_success_data(api_client.get_franchisee(franchisee["id"], FRANCHISOR))
    assert fz["open_compliance_strikes"] == 0, (
        "strikes must equal count(SUSPENDED units)==0 after compensation"
    )


def test_suspend_then_reinstate_strike_matches_suspended_unit_count():
    """PRD §3.5: "open_compliance_strikes is a running count of how many of the
    franchisee's units currently sit in compliance suspension."
    PRD §3.6: "the owning franchisee's open_compliance_strikes is decremented by one."

    Design: Difficulty/compensating_invariant/compliance_strike_conservation_suspend_then_reinstate
    """
    brand, franchisee, terr, unit, fail_audit = setup_suspended_unit(
        owner_user_id="u_inv2", territory_code="IN2"
    )
    fz_after_suspend = get_success_data(
        api_client.get_franchisee(franchisee["id"], FRANCHISOR)
    )
    assert fz_after_suspend["open_compliance_strikes"] == 1  # one SUSPENDED unit
    pass_audit = create_in_progress_audit(unit["id"])
    finalize_audit(pass_audit["id"], 95, 95, 95, 95)
    validate_success(
        api_client.reinstate_unit(unit["id"], FRANCHISOR), expected_status=200
    )
    fz_after_reinstate = get_success_data(
        api_client.get_franchisee(franchisee["id"], FRANCHISOR)
    )
    assert fz_after_reinstate["open_compliance_strikes"] == 0  # zero SUSPENDED units


# ═══════════════════════════════════════════════════════════════════════════
# Corner: state_machines / conditional_audit_drives_unit_probation_side_effect
# ═══════════════════════════════════════════════════════════════════════════
def test_conditional_audit_moves_unit_to_probation_and_sets_score():
    """PRD §3.5: "a finalized audit graded CONDITIONAL moves a unit from GOOD_STANDING
    to PROBATION."
    PRD §3.7: "The unit's latest_audit_score is set to the audit's overall_score."

    Design: Corner/state_machines/conditional_audit_drives_unit_probation_side_effect
    """
    _, _, _, unit, audit = setup_in_progress_audit(owner_user_id="u_cond", territory_code="CON")
    finalized = finalize_audit(audit["id"], 80, 80, 80, 80)  # overall 80.0 → CONDITIONAL
    assert finalized["overall_score"] == 80.0
    assert finalized["grade"] == "CONDITIONAL"
    refreshed = get_success_data(api_client.get_unit(unit["id"], FRANCHISOR))
    assert refreshed["compliance_status"] == "PROBATION"
    assert refreshed["operational_status"] == "OPEN"
    assert refreshed["latest_audit_score"] == 80.0


# ═══════════════════════════════════════════════════════════════════════════
# Corner: state_machines / audit_finalize_critical_food_safety_cap_to_59
# ═══════════════════════════════════════════════════════════════════════════
def test_critical_food_safety_cap_to_59():
    """PRD §3.7: "if food_safety_score is below 70, the overall score is the smaller of
    the weighted score and 59.0; otherwise the overall score equals the weighted
    score."

    Design: Corner/state_machines/audit_finalize_critical_food_safety_cap_to_59
    """
    # 69/99/99/99 → weighted = 0.40*69 + 0.25*99 + 0.20*99 + 0.15*99 = 27.6+24.75+19.8+14.85 = 87.0
    _, _, _, unit, audit = setup_in_progress_audit(owner_user_id="u_cap", territory_code="CAP")
    finalized = finalize_audit(audit["id"], 69, 99, 99, 99)
    assert finalized["weighted_score"] == 87.0
    assert finalized["overall_score"] == 59.0, "critical-fail cap applied"
    assert finalized["grade"] == "FAIL"


# ═══════════════════════════════════════════════════════════════════════════
# Corner: state_machines / food_safety_70_boundary_no_critical_cap
# ═══════════════════════════════════════════════════════════════════════════
def test_food_safety_exactly_70_avoids_critical_cap():
    """PRD §3.7: "if food_safety_score is below 70, the overall score is the smaller of
    the weighted score and 59.0; otherwise the overall score equals the weighted
    score."

    Design: Corner/state_machines/food_safety_70_boundary_no_critical_cap
    """
    # 70/90/90/90 → weighted = 0.40*70 + 0.25*90 + 0.20*90 + 0.15*90 = 28+22.5+18+13.5 = 82.0
    _, _, _, unit, audit = setup_in_progress_audit(owner_user_id="u_b70", territory_code="B70")
    finalized = finalize_audit(audit["id"], 70, 90, 90, 90)
    assert finalized["weighted_score"] == 82.0
    assert finalized["overall_score"] == 82.0, "food_safety 70 is not < 70 → no cap"
    assert finalized["grade"] == "CONDITIONAL"
