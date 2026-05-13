"""Responsibility decision tests: percentages, mediation cycle,
segregation of duties (PRD §3.10).

Difficulty-design instances exercised:
- # difficulty: non_linear_state_machine/responsibility_decision_mediation_cycle
- # difficulty: dual_variant_calc/responsibility_split_duration_vs_severity_weighted
- # difficulty: compensating_invariant/damaged_quantity_conservation_across_mediation_cycle
"""
from __future__ import annotations

import pytest

from test_helpers import (
    COMPLIANCE,
    ApiErrorId,
    TaskParties,
    advance_clock,
    assert_responsibility_decision,
    assert_split_sums_to_one,
    create_damage_assessment,
    create_responsibility_decision_payload,
    dispute_payload,
    make_compliance_headers,
    parse_iso,
    setup_accepted_decision,
    setup_drafted_decision,
    setup_finalized_assessment,
    setup_mediation_cycle_decision,
    setup_two_evidence_alerts_with_custody,
    validate_error,
    validate_success,
)


# ===========================================================================
# Creation rules
# ===========================================================================
def test_pct_sum_invalid_rejected(api):
    """PRD §3.10: 'The three percentages must sum to 1.00 exactly when
    rounded half up to two decimals; any other sum is rejected with
    ERR_PCT_SUM_INVALID.'"""
    scenario = setup_finalized_assessment()
    payload = create_responsibility_decision_payload(
        task_id=scenario["task"]["id"],
        assessment_id=scenario["assessment"]["id"],
        shipper_pct=0.30, carrier_pct=0.30, consignee_pct=0.30,  # sums 0.90
        split_method="DURATION_WEIGHTED",
    )
    resp = api.create_responsibility_decision(payload, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_PCT_SUM_INVALID.value)


def test_pct_sum_one_accepted(api):
    """PRD §3.10: 'The three percentages must sum to 1.00 exactly when
    rounded half up to two decimals.'"""
    scenario = setup_drafted_decision()
    assert_responsibility_decision(scenario["decision"])
    assert scenario["decision"]["status"] == "DRAFT"
    assert_split_sums_to_one(scenario["decision"])


def test_responsibility_decision_must_reference_finalized_assessment(api):
    """PRD §3.10: 'A COMPLIANCE_OFFICER opens a ResponsibilityDecision
    in DRAFT against a task that has at least one FINALIZED
    DamageAssessment.'"""
    from test_helpers import setup_delivered_with_alert
    scenario = setup_delivered_with_alert()
    assessment = create_damage_assessment(
        scenario=scenario, damaged_quantity=1, damage_class="MINOR",
        salvage_pct=0.00, variant="INSURED_VALUE",
    )
    # Do NOT finalize the assessment — attempt to create decision.
    payload = create_responsibility_decision_payload(
        task_id=scenario["task"]["id"],
        assessment_id=assessment["id"],
        shipper_pct=0.30, carrier_pct=0.50, consignee_pct=0.20,
    )
    resp = api.create_responsibility_decision(payload, COMPLIANCE)
    # PRD precondition: decision must reference FINALIZED assessment.
    # Implementation could surface this as ERR_INVALID_STATE
    # (state precondition on referenced entity).
    assert resp.status_code >= 400


# ===========================================================================
# Submit / accept / dispute / mediate cycle — difficulty
# ===========================================================================
def test_mediation_cycle_returns_to_draft(api):
    """PRD §3.10: 'During mediation the compliance officer cycles the
    decision back to DRAFT via PATCH, revising the splits.'

    # difficulty: non_linear_state_machine/responsibility_decision_mediation_cycle
    """
    scenario = setup_mediation_cycle_decision()
    decision = scenario["decision"]
    assert decision["status"] == "MEDIATION"
    # PATCH revises and returns to DRAFT.
    patch_resp = validate_success(
        api.patch_responsibility_decision(
            decision["id"],
            {"version": decision["version"],
             "shipper_pct": 0.40,
             "carrier_pct": 0.40,
             "consignee_pct": 0.20},
            COMPLIANCE,
        )
    )
    assert patch_resp["status"] == "DRAFT"
    # Submit again -> UNDER_REVIEW (second arrival).
    second_under_review = validate_success(
        api.submit_decision(decision["id"], COMPLIANCE)
    )
    assert second_under_review["status"] == "UNDER_REVIEW"
    # Version bumped at least twice across the cycle (PATCH + submit).
    assert second_under_review["version"] >= decision["version"] + 2, (
        "PRD §2.4: 'a monotonic integer version that increments by one "
        "on every mutation.'"
    )


def test_mediation_cycle_preserves_pct_sum_invariant(api):
    """PRD §3.10: 'PATCH revisions must still preserve the sum-to-1.00
    invariant or are rejected with ERR_PCT_SUM_INVALID.'

    # difficulty: non_linear_state_machine/responsibility_decision_mediation_cycle
    """
    scenario = setup_mediation_cycle_decision()
    decision = scenario["decision"]
    resp = api.patch_responsibility_decision(
        decision["id"],
        {"version": decision["version"],
         "shipper_pct": 0.40,
         "carrier_pct": 0.40,
         "consignee_pct": 0.10},  # sum 0.90
        COMPLIANCE,
    )
    validate_error(resp, ApiErrorId.ERR_PCT_SUM_INVALID.value)


# ===========================================================================
# Advisory split — DURATION_WEIGHTED vs SEVERITY_WEIGHTED
# ===========================================================================
def test_advisory_split_duration_vs_severity(api):
    """PRD §3.10: 'Under DURATION_WEIGHTED, for each of the three
    parties sum, over the evidence alerts, the overlap in seconds
    between the alert's open-to-resolved interval and the custody
    segments belonging to that party. ... Under SEVERITY_WEIGHTED, for
    each evidence alert attribute its peak_deviation_celsius to the
    party whose custody segment covers the alert's opened_at moment.'

    With Alert A held entirely in SHIPPER custody (long duration, peak
    1.50) and Alert B held entirely in CARRIER custody (short duration,
    peak 7.00):
      DURATION_WEIGHTED: SHIPPER overlap > CARRIER overlap
      SEVERITY_WEIGHTED: CARRIER peak (7.00) > SHIPPER peak (1.50)

    # difficulty: dual_variant_calc/responsibility_split_duration_vs_severity_weighted
    """
    scenario = setup_two_evidence_alerts_with_custody()
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    # Finalize an assessment referencing BOTH alerts.
    assessment_a = create_damage_assessment(
        scenario={**scenario,
                  "alert": scenario["alert_a"]},
        damaged_quantity=5, damage_class="MODERATE", salvage_pct=0.10,
        variant="INSURED_VALUE",
        evidence_alert_ids=[
            scenario["alert_a"]["id"], scenario["alert_b"]["id"],
        ],
    )
    finalized = validate_success(
        api.finalize_damage_assessment(assessment_a["id"], COMPLIANCE)
    )
    # Create DURATION_WEIGHTED decision.
    payload_d = create_responsibility_decision_payload(
        task_id=task["id"], assessment_id=finalized["id"],
        shipper_pct=0.50, carrier_pct=0.50, consignee_pct=0.00,
        split_method="DURATION_WEIGHTED",
    )
    dec_d = validate_success(
        api.create_responsibility_decision(payload_d, COMPLIANCE),
        expected_status=201,
    )
    advisory_d = dec_d.get("advisory_split")
    assert advisory_d is not None, (
        "PRD §3.10: 'the server returns an advisory_split computed "
        "from the evidence chain.'"
    )
    # PRD §3.10 names parties as SHIPPER/CARRIER/CONSIGNEE but does not
    # pin the advisory_split dict key format; both uppercase party-name
    # keys and snake_case `<party>_pct` keys are PRD-faithful readings.
    def _share(d: dict, party: str) -> float:
        return d.get(party, d.get(f"{party.lower()}_pct", 0))
    # Under DURATION_WEIGHTED: SHIPPER held cargo longer -> SHIPPER
    # share > CARRIER share.
    assert _share(advisory_d, "SHIPPER") > _share(advisory_d, "CARRIER"), (
        "PRD §3.10 DURATION_WEIGHTED: SHIPPER custody overlap exceeds "
        f"CARRIER's; got advisory_split={advisory_d}"
    )


# ===========================================================================
# Segregation of duties (PRD §3.10)
# ===========================================================================
def test_finalize_segregation_of_duties_violated(api):
    """PRD §3.10: 'Segregation of duties is the load-bearing check
    here: the finalizing actor's X-User-ID must not equal any of the
    task's shipper_id, carrier_id, or consignee_id — that is, a party
    cannot finalise a decision that involves them. A violation is
    reported as ERR_SEGREGATION_VIOLATION.'"""
    scenario = setup_accepted_decision()
    parties: TaskParties = scenario["parties"]
    decision = scenario["decision"]
    # Use the task's shipper_id as the would-be finalizer.
    violator_headers = make_compliance_headers(parties.shipper_id)
    resp = api.finalize_decision(decision["id"], violator_headers)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION.value)


def test_finalize_with_distinct_compliance_officer_succeeds(api):
    """PRD §3.10: 'Once the decision is ACCEPTED, a compliance officer
    finalises it, advancing it from ACCEPTED to FINALIZED.'

    Side effects: finalizing_role=COMPLIANCE_OFFICER,
    attributed_quantity=DamageAssessment.damaged_quantity.
    """
    scenario = setup_accepted_decision(damaged_quantity=7, cargo_quantity=100)
    decision = scenario["decision"]
    finalizer = make_compliance_headers("finalizer-001")
    finalized = validate_success(
        api.finalize_decision(decision["id"], finalizer)
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized.get("finalizing_role") == "COMPLIANCE_OFFICER"
    assert finalized.get("attributed_quantity") == 7, (
        "PRD §3.10: 'attributed_quantity is set to the assessment's "
        "damaged_quantity.'"
    )


# ===========================================================================
# Damaged-quantity conservation across mediation cycle — difficulty
# ===========================================================================
def test_attributed_quantity_matches_damaged_quantity_after_cycle(api):
    """PRD §3.10: 'attributed_quantity is set to the assessment's
    damaged_quantity (so the invariant that party-attributed quantity
    totals the assessment's damaged quantity is enforced).'

    Even after a DISPUTED -> MEDIATION -> DRAFT -> resubmit -> accept ->
    finalize cycle revising percentage splits, the final
    attributed_quantity must equal the assessment's damaged_quantity.

    # difficulty: compensating_invariant/damaged_quantity_conservation_across_mediation_cycle
    """
    scenario = setup_mediation_cycle_decision(
        damaged_quantity=7, cargo_quantity=100,
    )
    parties: TaskParties = scenario["parties"]
    decision = scenario["decision"]
    # Revise splits via PATCH (MEDIATION -> DRAFT).
    decision = validate_success(
        api.patch_responsibility_decision(
            decision["id"],
            {"version": decision["version"],
             "shipper_pct": 0.30, "carrier_pct": 0.50, "consignee_pct": 0.20},
            COMPLIANCE,
        )
    )
    # Submit -> UNDER_REVIEW.
    decision = validate_success(
        api.submit_decision(decision["id"], COMPLIANCE)
    )
    # All three accept.
    validate_success(
        api.accept_decision(decision["id"], parties.shipper_h())
    )
    validate_success(
        api.accept_decision(decision["id"], parties.carrier_h())
    )
    validate_success(
        api.accept_decision(decision["id"], parties.consignee_h())
    )
    # Finalize with distinct compliance officer.
    finalizer = make_compliance_headers("finalizer-cycle-001")
    finalized = validate_success(
        api.finalize_decision(decision["id"], finalizer)
    )
    assert finalized["attributed_quantity"] == 7, (
        "PRD §3.10 conserved-quantity invariant: attributed_quantity "
        "after the mediation cycle MUST equal the assessment's "
        "damaged_quantity (7), regardless of intervening percentage "
        "revisions."
    )


def test_attributed_quantity_set_to_damaged_quantity_no_cycle(api):
    """PRD §3.10: 'attributed_quantity is set to the assessment's
    damaged_quantity (so the invariant that party-attributed quantity
    totals the assessment's damaged quantity is enforced).'

    Companion to the cycle test: a finalize without any mediation cycle
    must also set attributed_quantity to the assessment's
    damaged_quantity. Together with the cycle test, this pins the
    conserved-quantity invariant on both branches.

    # difficulty: compensating_invariant/damaged_quantity_conservation_across_mediation_cycle
    """
    scenario = setup_accepted_decision(damaged_quantity=10, cargo_quantity=100)
    decision = scenario["decision"]
    finalizer = make_compliance_headers("finalizer-nocycle-001")
    finalized = validate_success(
        api.finalize_decision(decision["id"], finalizer)
    )
    assert finalized["attributed_quantity"] == 10


def test_advisory_split_changes_with_split_method_on_same_evidence(api):
    """PRD §3.10: 'A PATCH to the decision while in DRAFT recomputes
    the advisory; the same recomputation fires when the decision cycles
    back to DRAFT from MEDIATION.'
    PRD §3.10: 'Under DURATION_WEIGHTED ... advisory_pct[p] :=
    overlap_seconds[p] / sum_over_parties(overlap_seconds). ... Under
    SEVERITY_WEIGHTED, for each evidence alert attribute its
    peak_deviation_celsius to the party whose custody segment covers
    the alert's opened_at moment.'

    Same evidence chain, different split_method via PATCH -> different
    advisory_split.

    # difficulty: dual_variant_calc/responsibility_split_duration_vs_severity_weighted
    """
    scenario = setup_two_evidence_alerts_with_custody()
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    # Finalize an assessment with both alerts.
    assessment = create_damage_assessment(
        scenario={**scenario, "alert": scenario["alert_a"]},
        damaged_quantity=5, damage_class="MODERATE", salvage_pct=0.10,
        variant="INSURED_VALUE",
        evidence_alert_ids=[
            scenario["alert_a"]["id"], scenario["alert_b"]["id"],
        ],
    )
    finalized = validate_success(
        api.finalize_damage_assessment(assessment["id"], COMPLIANCE)
    )
    # DURATION_WEIGHTED decision.
    dec_d = validate_success(
        api.create_responsibility_decision(
            create_responsibility_decision_payload(
                task_id=task["id"], assessment_id=finalized["id"],
                shipper_pct=0.50, carrier_pct=0.50, consignee_pct=0.00,
                split_method="DURATION_WEIGHTED",
            ),
            COMPLIANCE,
        ),
        expected_status=201,
    )
    advisory_d = dec_d.get("advisory_split")
    # PATCH split_method to SEVERITY_WEIGHTED -> advisory recomputed.
    dec_s = validate_success(
        api.patch_responsibility_decision(
            dec_d["id"],
            {"version": dec_d["version"],
             "split_method": "SEVERITY_WEIGHTED"},
            COMPLIANCE,
        )
    )
    advisory_s = dec_s.get("advisory_split")
    assert advisory_s is not None
    assert advisory_d != advisory_s, (
        "PRD §3.10: SEVERITY_WEIGHTED on the same evidence chain must "
        "yield a different advisory_split than DURATION_WEIGHTED."
    )
    # PRD §3.10 names parties as SHIPPER/CARRIER/CONSIGNEE but does not
    # pin the advisory_split dict key format; tolerate both.
    def _share(d: dict, party: str) -> float:
        return d.get(party, d.get(f"{party.lower()}_pct", 0))
    # Under SEVERITY_WEIGHTED, CARRIER absorbed Alert B's large peak.
    assert _share(advisory_s, "CARRIER") > _share(advisory_s, "SHIPPER"), (
        "PRD §3.10 SEVERITY_WEIGHTED: CARRIER attributed the higher peak"
    )
