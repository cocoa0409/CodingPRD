"""Insurance claim lifecycle, payout invariant, cross-entity rule
(PRD §3.11).

Difficulty-design instances exercised:
- # difficulty: compensating_invariant/insurer_outflow_pay_then_subrogate
- # difficulty: non_linear_state_machine/insurance_claim_assessment_negotiation_cycle
- # difficulty: cross_entity_state_dependency/insurance_claim_report_requires_finalized_decision
- # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_claim_report
"""
from __future__ import annotations

import pytest

from test_helpers import (
    INSURANCE,
    ApiErrorId,
    TaskParties,
    assert_insurance_claim,
    assert_payout_invariant,
    assess_claim_payload,
    create_damage_assessment,
    create_insurance_claim_payload,
    create_responsibility_decision_payload,
    parse_iso,
    setup_assessment_claim,
    setup_delivered_with_alert,
    setup_finalized_assessment,
    setup_paid_out_claim,
    setup_reported_claim,
    setup_drafted_decision,
    subrogate_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Cross-entity rule — finalized decision required (difficulty)
# ===========================================================================
def test_report_claim_requires_finalized_decision(api):
    """PRD §3.11: 'The payload carries task_id, decision_id (pointing
    to a FINALIZED responsibility decision on the same task — a
    non-finalised decision is rejected with ERR_DECISION_NOT_FINALIZED).'

    # difficulty: cross_entity_state_dependency/insurance_claim_report_requires_finalized_decision
    """
    scenario = setup_drafted_decision()  # decision in DRAFT (not FINALIZED)
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    decision = scenario["decision"]
    payload = create_insurance_claim_payload(
        task_id=task["id"], decision_id=decision["id"],
        requested_amount_cents=100,
    )
    resp = api.create_insurance_claim(payload, parties.carrier_h())
    validate_error(resp, ApiErrorId.ERR_DECISION_NOT_FINALIZED.value)


def test_priority_business_safety_vs_business_fiscal_on_claim_report(api):
    """PRD §2.6: 'business-safety, business-referential,
    business-constraint, business-temporal and business-fiscal checks
    fire in scaffold-priority order — segregation of duties on
    finalize (ERR_SEGREGATION_VIOLATION, 403); the cross-entity check
    that an alert can only be resolved while its parent task is
    IN_TRANSIT, AT_STOP, or DELIVERED (ERR_TASK_NOT_RESOLVABLE, 409);
    the requirement that the linked responsibility decision is
    FINALIZED before an insurance claim can be reported
    (ERR_DECISION_NOT_FINALIZED, 409); the evidence-chain requirement
    on damage assessments (ERR_EVIDENCE_REQUIRED, 422) ... the
    insurance-cap check on claim reporting (ERR_INSURANCE_CAP_EXCEEDED,
    422)'.

    Construct a request that simultaneously violates (a) business_safety
    — linked decision not FINALIZED — AND (b) business_fiscal —
    requested_amount_cents exceeds Vehicle.insured_cap_cents. The
    business_safety error fires first.

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_claim_report
    """
    scenario = setup_drafted_decision(insured_cap_cents=10_000)
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    decision = scenario["decision"]
    payload = create_insurance_claim_payload(
        task_id=task["id"], decision_id=decision["id"],
        requested_amount_cents=50_000,  # well above 10_000 cap
    )
    resp = api.create_insurance_claim(payload, parties.carrier_h())
    # business_safety (DECISION_NOT_FINALIZED) must fire BEFORE
    # business_fiscal (INSURANCE_CAP_EXCEEDED).
    validate_error(resp, ApiErrorId.ERR_DECISION_NOT_FINALIZED.value)


def test_insurance_cap_exceeded_on_report(api):
    """PRD §3.11: 'The requested amount must not exceed the task's
    vehicle insured_cap_cents; a violation is reported as
    ERR_INSURANCE_CAP_EXCEEDED.'"""
    scenario = setup_reported_claim(
        requested_amount_cents=500, insured_cap_cents=1_000,
    )
    # Already reported successfully; now try a 2nd over-cap on same task.
    # Use a fresh task entirely.
    from test_helpers import setup_finalized_decision
    scenario2 = setup_finalized_decision(insured_cap_cents=1_000)
    parties: TaskParties = scenario2["parties"]
    task = scenario2["task"]
    decision = scenario2["decision"]
    payload = create_insurance_claim_payload(
        task_id=task["id"], decision_id=decision["id"],
        requested_amount_cents=10_000,  # > cap 1_000
    )
    resp = api.create_insurance_claim(payload, parties.carrier_h())
    validate_error(resp, ApiErrorId.ERR_INSURANCE_CAP_EXCEEDED.value)


def test_assess_amount_above_requested_rejected(api):
    """PRD §3.11: 'The insurance adjuster then assesses, supplying
    assessed_amount_cents (an integer in the range from zero through
    requested_amount_cents, with out-of-range values reported as
    ERR_AMOUNT_INVALID).'"""
    scenario = setup_reported_claim(requested_amount_cents=1_000)
    parties: TaskParties = scenario["parties"]
    claim = scenario["claim"]
    # advance to EVIDENCE_PREP
    claim = validate_success(
        api.prepare_evidence(claim["id"], parties.carrier_h())
    )
    resp = api.assess_claim(
        claim["id"], assess_claim_payload(1_001), INSURANCE,
    )
    validate_error(resp, ApiErrorId.ERR_AMOUNT_INVALID.value)


# ===========================================================================
# Payout invariant — difficulty
# ===========================================================================
def test_pay_sets_payout_to_assessed(api):
    """PRD §3.11: 'Paying out advances the claim to PAID_OUT, and as a
    side effect payout_amount_cents is set to assessed_amount_cents.'

    # difficulty: compensating_invariant/insurer_outflow_pay_then_subrogate
    """
    scenario = setup_paid_out_claim(
        assessed_amount_cents=15_000, requested_amount_cents=20_000,
        insured_cap_cents=20_000,
    )
    claim = scenario["claim"]
    assert claim["status"] == "PAID_OUT"
    assert claim["payout_amount_cents"] == 15_000


def test_subrogation_reduces_payout(api):
    """PRD §3.11: 'subrogation_recovered_cents is recorded and
    payout_amount_cents is set to the previous payout amount minus
    subrogation_recovered_cents, with a floor of zero applied.'

    # difficulty: compensating_invariant/insurer_outflow_pay_then_subrogate
    """
    scenario = setup_paid_out_claim(
        assessed_amount_cents=15_000, requested_amount_cents=20_000,
        insured_cap_cents=20_000,
    )
    claim = scenario["claim"]
    claim = validate_success(
        api.subrogate_claim(
            claim["id"], subrogate_payload(4_000), INSURANCE,
        )
    )
    assert claim["status"] == "SUBROGATION"
    assert claim["subrogation_recovered_cents"] == 4_000
    assert claim["payout_amount_cents"] == 11_000, (
        "PRD §3.11: payout_amount_cents := previous payout - subrogation; "
        "15_000 - 4_000 = 11_000"
    )
    assert_payout_invariant(claim, expected_assessed=15_000,
                            expected_subrogation=4_000)


def test_subrogation_recovered_above_payout_rejected(api):
    """PRD §3.11: 'The payload supplies subrogation_recovered_cents (an
    integer in the range from zero through the current
    payout_amount_cents, with out-of-range values reported as
    ERR_AMOUNT_INVALID).'"""
    scenario = setup_paid_out_claim(
        assessed_amount_cents=1_000, requested_amount_cents=2_000,
        insured_cap_cents=2_000,
    )
    claim = scenario["claim"]
    resp = api.subrogate_claim(
        claim["id"], subrogate_payload(1_001), INSURANCE,
    )
    validate_error(resp, ApiErrorId.ERR_AMOUNT_INVALID.value)


def test_pay_zero_assessment_rejected(api):
    """PRD §3.11: 'Paying requires assessed_amount_cents strictly greater
    than zero; an attempt to pay a zero-assessment claim is rejected.'"""
    scenario = setup_assessment_claim(
        assessed_amount_cents=0, requested_amount_cents=1_000,
    )
    claim = scenario["claim"]
    resp = api.pay_claim(claim["id"], INSURANCE)
    # PRD names the precondition without committing to a specific
    # error_id; assert it fails with 4xx (ERR_INVALID_STATE or similar).
    assert resp.status_code >= 400


def test_reject_sets_payout_to_zero(api):
    """PRD §3.11: 'Rejecting the claim advances it to REJECTED, with
    reason supplied in the body, and as a side effect
    payout_amount_cents is set to zero.'"""
    scenario = setup_assessment_claim(
        assessed_amount_cents=500, requested_amount_cents=1_000,
    )
    claim = scenario["claim"]
    rejected = validate_success(
        api.reject_claim(claim["id"], {"reason": "fraud"}, INSURANCE)
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["payout_amount_cents"] == 0


# ===========================================================================
# Assessment <-> Negotiating cycle — difficulty
# ===========================================================================
def test_assessment_negotiating_cycle_revises_assessed_amount(api):
    """PRD §3.11: 'From ASSESSMENT the carrier or insurance adjuster
    may negotiate, advancing to NEGOTIATING, after which the adjuster
    reassesses (cycling back to ASSESSMENT with a revised
    assessed_amount_cents).'

    # difficulty: non_linear_state_machine/insurance_claim_assessment_negotiation_cycle
    """
    scenario = setup_assessment_claim(
        assessed_amount_cents=15_000, requested_amount_cents=20_000,
        insured_cap_cents=20_000,
    )
    parties: TaskParties = scenario["parties"]
    claim = scenario["claim"]
    assert claim["status"] == "ASSESSMENT"
    assert claim["assessed_amount_cents"] == 15_000
    # Negotiate.
    claim = validate_success(
        api.negotiate_claim(claim["id"], parties.carrier_h())
    )
    assert claim["status"] == "NEGOTIATING"
    # Reassess with revised amount.
    claim = validate_success(
        api.assess_claim(claim["id"], assess_claim_payload(12_000), INSURANCE)
    )
    assert claim["status"] == "ASSESSMENT", (
        "PRD §3.11: 'cycling back to ASSESSMENT with a revised "
        "assessed_amount_cents'"
    )
    assert claim["assessed_amount_cents"] == 12_000
    # Version must have advanced at least 2x (negotiate + reassess).
    assert claim["version"] >= 4


def test_multiple_negotiation_rounds_each_revise_assessment(api):
    """PRD §3.11: 'From ASSESSMENT the carrier or insurance adjuster
    may negotiate, advancing to NEGOTIATING, after which the adjuster
    reassesses (cycling back to ASSESSMENT with a revised
    assessed_amount_cents).'

    Two rounds of negotiate + reassess produce two ASSESSMENT arrivals
    with two distinct assessed_amount_cents values.

    # difficulty: non_linear_state_machine/insurance_claim_assessment_negotiation_cycle
    """
    scenario = setup_assessment_claim(
        assessed_amount_cents=15_000, requested_amount_cents=20_000,
        insured_cap_cents=20_000,
    )
    parties: TaskParties = scenario["parties"]
    claim = scenario["claim"]
    # Round 1.
    claim = validate_success(
        api.negotiate_claim(claim["id"], parties.carrier_h())
    )
    claim = validate_success(
        api.assess_claim(claim["id"], assess_claim_payload(13_000), INSURANCE)
    )
    assert claim["status"] == "ASSESSMENT"
    assert claim["assessed_amount_cents"] == 13_000
    # Round 2.
    claim = validate_success(
        api.negotiate_claim(claim["id"], parties.carrier_h())
    )
    claim = validate_success(
        api.assess_claim(claim["id"], assess_claim_payload(11_500), INSURANCE)
    )
    assert claim["status"] == "ASSESSMENT"
    assert claim["assessed_amount_cents"] == 11_500


def test_priority_decision_finalized_vs_cap_zero_above_cap_zero(api):
    """PRD §2.6 + §3.11: 'the requirement that the linked responsibility
    decision is FINALIZED before an insurance claim can be reported
    (ERR_DECISION_NOT_FINALIZED, 409); ... the insurance-cap check on
    claim reporting (ERR_INSURANCE_CAP_EXCEEDED, 422).'

    A second priority-pair instance: very small insured_cap_cents
    paired with a non-finalized decision; the business_safety error
    (DECISION_NOT_FINALIZED, priority 8) must fire before the
    business_fiscal cap error (priority 15).

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_claim_report
    """
    scenario = setup_drafted_decision(insured_cap_cents=1)
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    decision = scenario["decision"]
    payload = create_insurance_claim_payload(
        task_id=task["id"], decision_id=decision["id"],
        requested_amount_cents=2,  # > cap=1
    )
    resp = api.create_insurance_claim(payload, parties.carrier_h())
    validate_error(resp, ApiErrorId.ERR_DECISION_NOT_FINALIZED.value)


def test_cross_entity_unfinalized_decision_blocks_claim_dispute_state(api):
    """PRD §3.11: 'task_id, decision_id (pointing to a FINALIZED
    responsibility decision on the same task — a non-finalised decision
    is rejected with ERR_DECISION_NOT_FINALIZED).'

    Decision in DISPUTED (not FINALIZED) is also rejected — covers a
    different non-FINALIZED state branch from setup_drafted_decision.

    # difficulty: cross_entity_state_dependency/insurance_claim_report_requires_finalized_decision
    """
    from test_helpers import setup_mediation_cycle_decision
    scenario = setup_mediation_cycle_decision()  # decision in MEDIATION
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    decision = scenario["decision"]
    payload = create_insurance_claim_payload(
        task_id=task["id"], decision_id=decision["id"],
        requested_amount_cents=100,
    )
    resp = api.create_insurance_claim(payload, parties.carrier_h())
    validate_error(resp, ApiErrorId.ERR_DECISION_NOT_FINALIZED.value)


def test_payout_invariant_after_full_subrogation(api):
    """PRD §3.11: 'subrogation_recovered_cents is recorded and
    payout_amount_cents is set to the previous payout amount minus
    subrogation_recovered_cents, with a floor of zero applied.'

    Full subrogation (recovered == payout) reduces payout to zero.

    # difficulty: compensating_invariant/insurer_outflow_pay_then_subrogate
    """
    scenario = setup_paid_out_claim(
        assessed_amount_cents=5_000, requested_amount_cents=5_000,
        insured_cap_cents=10_000,
    )
    claim = scenario["claim"]
    claim = validate_success(
        api.subrogate_claim(
            claim["id"], subrogate_payload(5_000), INSURANCE,
        )
    )
    assert claim["payout_amount_cents"] == 0
    assert_payout_invariant(claim, expected_assessed=5_000,
                            expected_subrogation=5_000)
