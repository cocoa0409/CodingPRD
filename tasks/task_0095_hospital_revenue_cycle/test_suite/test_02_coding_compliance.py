"""Coding compliance-risk scoring, the AUDIT_HOLD threshold fork, the recode loop,
and the discharge empty-charge-set boundary.

Queue A (difficulty) instances:
  combinatorial_formula / coding_risk_three_factor_nonlinear_score
  non_linear_state_machine / coding_audit_hold_recode_loop
  boundary_precision_check / coding_risk_threshold_exact_50_is_audit_hold
  boundary_precision_check / discharge_requires_at_least_one_posted_charge_empty_set
"""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, ApiErrorId,
    create_active_policy, create_encounter, add_charge, run_eligibility,
    setup_charges_captured_encounter,
    create_coding_payload,
)

REGISTRAR = TEST_USERS["registrar_headers"]
CODER = TEST_USERS["coder_headers"]
BILLING = TEST_USERS["billing_headers"]


# ===========================================================================
# combinatorial_formula / coding_risk_three_factor_nonlinear_score
# ===========================================================================
def test_coding_risk_unspecified_plus_excess_secondary_scores_50(api):
    """PRD §3.5: "First, an unspecified principal diagnosis carries documentation risk: if
    the principal_icd10 contains no decimal point, or if it ends in ".9", the score gains 40
    points. Second, an excess of secondary codes inflates the case weight: the score gains 10
    points for each secondary code beyond the first three - concretely, 10 points multiplied
    by the count of entries in secondary_icd10 minus 3, with that multiplier floored at 0 so
    that three or fewer secondary codes add nothing."

    principal 'R69' (no decimal => 40) + 4 secondaries (1 over free => 10) + single distinct
    CPT (no mismatch) => 50.

    Design: Difficulty/combinatorial_formula/coding_risk_three_factor_nonlinear_score
    """
    payer, patient, policy, encounter, coding = setup_charges_captured_encounter(
        principal_icd10="R69", secondary_icd10=["I10", "E78.5", "Z79.4", "F17.210"],
    )
    data = validate_success(api.finalize_coding(coding["id"], CODER))
    assert data["compliance_risk_score"] == 50, (
        f"score should be 50, got {data['compliance_risk_score']}"
    )


def test_coding_risk_at_threshold_routes_to_audit_hold(api):
    """PRD §3.5: "if the score reaches or exceeds the audit threshold the very same finalize
    operation instead routes the assignment to DRAFT -> AUDIT_HOLD. The audit threshold is 50,
    and the comparison is inclusive - a score of exactly 50 routes to AUDIT_HOLD."

    Design: Difficulty/combinatorial_formula/coding_risk_three_factor_nonlinear_score
    """
    payer, patient, policy, encounter, coding = setup_charges_captured_encounter(
        principal_icd10="R69", secondary_icd10=["I10", "E78.5", "Z79.4", "F17.210"],
    )
    data = validate_success(api.finalize_coding(coding["id"], CODER))
    assert data["status"] == "AUDIT_HOLD", f"expected AUDIT_HOLD, got {data['status']}"


# ===========================================================================
# non_linear_state_machine / coding_audit_hold_recode_loop
# ===========================================================================
def test_audit_hold_can_be_returned_for_recode(api):
    """PRD §3.5: "A Coder may return it for recoding, which is defined only from AUDIT_HOLD
    status; this clears finalized_by_user_id back to null and transitions the assignment
    AUDIT_HOLD -> DRAFT, letting the coder amend the codes and finalize again."

    Design: Difficulty/non_linear_state_machine/coding_audit_hold_recode_loop
    """
    payer, patient, policy, encounter, coding = setup_charges_captured_encounter(
        principal_icd10="R69", secondary_icd10=["I10", "E78.5", "Z79.4", "F17.210"],
    )
    held = validate_success(api.finalize_coding(coding["id"], CODER))
    assert held["status"] == "AUDIT_HOLD"
    recoded = validate_success(api.return_coding_for_recode(coding["id"], CODER))
    assert recoded["status"] == "DRAFT", f"expected DRAFT after recode, got {recoded['status']}"
    assert recoded["finalized_by_user_id"] is None, (
        "return-for-recode must clear finalized_by_user_id to null"
    )


def test_recode_loop_refinalize_rescores_same_codes(api):
    """PRD §3.5: "This revision loop means an encounter's coding may pass through finalize
    more than once before it clears."
    PRD §3.5: "The audit threshold is 50, and the comparison is inclusive - a score of
    exactly 50 routes to AUDIT_HOLD."

    Re-finalizing without amending the codes recomputes the same score (50) and routes to
    AUDIT_HOLD again.

    Design: Difficulty/non_linear_state_machine/coding_audit_hold_recode_loop
    """
    payer, patient, policy, encounter, coding = setup_charges_captured_encounter(
        principal_icd10="R69", secondary_icd10=["I10", "E78.5", "Z79.4", "F17.210"],
    )
    validate_success(api.finalize_coding(coding["id"], CODER))
    validate_success(api.return_coding_for_recode(coding["id"], CODER))
    data = validate_success(api.finalize_coding(coding["id"], CODER))
    assert data["status"] == "AUDIT_HOLD", f"expected AUDIT_HOLD again, got {data['status']}"
    assert data["compliance_risk_score"] == 50, (
        f"re-finalize should rescore to 50, got {data['compliance_risk_score']}"
    )


# ===========================================================================
# boundary_precision_check / coding_risk_threshold_exact_50_is_audit_hold
# ===========================================================================
def test_score_exactly_50_is_audit_hold(api):
    """PRD §3.5: "The audit threshold is 50, and the comparison is inclusive - a score of
    exactly 50 routes to AUDIT_HOLD."

    R69 (40) + 4 secondaries (10) => exactly 50 => AUDIT_HOLD.

    Design: Difficulty/boundary_precision_check/coding_risk_threshold_exact_50_is_audit_hold
    """
    payer, patient, policy, encounter, coding = setup_charges_captured_encounter(
        principal_icd10="R69", secondary_icd10=["I10", "E78.5", "Z79.4", "F17.210"],
    )
    data = validate_success(api.finalize_coding(coding["id"], CODER))
    assert data["compliance_risk_score"] == 50
    assert data["status"] == "AUDIT_HOLD", f"score 50 must route to AUDIT_HOLD, got {data['status']}"


def test_score_40_below_threshold_finalizes(api):
    """PRD §3.5: "if the score is below the audit threshold the assignment transitions
    DRAFT -> FINALIZED, but if the score reaches or exceeds the audit threshold the very same
    finalize operation instead routes the assignment to DRAFT -> AUDIT_HOLD."

    R69 (40) + 1 secondary (0 over free) => 40, below 50 => FINALIZED.

    Design: Difficulty/boundary_precision_check/coding_risk_threshold_exact_50_is_audit_hold
    """
    payer, patient, policy, encounter, coding = setup_charges_captured_encounter(
        principal_icd10="R69", secondary_icd10=["I10"],
    )
    data = validate_success(api.finalize_coding(coding["id"], CODER))
    assert data["compliance_risk_score"] == 40, (
        f"score should be 40, got {data['compliance_risk_score']}"
    )
    assert data["status"] == "FINALIZED", f"score 40 must FINALIZE, got {data['status']}"


# ===========================================================================
# boundary_precision_check / discharge_requires_at_least_one_posted_charge_empty_set
# ===========================================================================
def test_discharge_with_zero_posted_charges_rejected(api):
    """PRD §3.3: "Discharge is defined only from ELIGIBILITY_VERIFIED status and requires
    that at least one charge with status POSTED exists for the encounter; a discharge attempt
    with no posted charges is rejected with ERR_NO_CHARGES."

    The single charge is VOIDED, leaving zero POSTED charges.

    Design: Difficulty/boundary_precision_check/discharge_requires_at_least_one_posted_charge_empty_set
    """
    payer, patient, policy = create_active_policy()
    encounter = create_encounter(patient["id"], policy["id"])
    charge = add_charge(encounter["id"], unit_price_cents=300000)
    run_eligibility(encounter["id"])
    validate_success(api.void_charge(charge["id"], REGISTRAR))
    resp = api.discharge_encounter(encounter["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_NO_CHARGES.value, expected_status=409)


def test_discharge_with_one_posted_charge_succeeds(api):
    """PRD §3.3: "On discharge the server sets the encounter's discharge_at to the current
    clock time, recomputes total_charges_cents from the posted charges, and advances the
    encounter ELIGIBILITY_VERIFIED -> CHARGES_CAPTURED."

    Boundary at exactly one POSTED charge: discharge succeeds.

    Design: Difficulty/boundary_precision_check/discharge_requires_at_least_one_posted_charge_empty_set
    """
    payer, patient, policy = create_active_policy()
    encounter = create_encounter(patient["id"], policy["id"])
    add_charge(encounter["id"], unit_price_cents=300000)
    run_eligibility(encounter["id"])
    data = validate_success(api.discharge_encounter(encounter["id"], REGISTRAR))
    assert data["status"] == "CHARGES_CAPTURED", (
        f"expected CHARGES_CAPTURED, got {data['status']}"
    )
