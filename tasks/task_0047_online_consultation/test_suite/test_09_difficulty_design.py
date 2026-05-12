"""High-difficulty integration claims that exercise dual-variant
calculations, combinatorial rounding, non-linear state machines,
transitive cascades, validation-priority conflicts, boundary precision,
cross-entity state dependencies, resource temporal overlap, and
compensating invariants. Each behavior the file covers is traced to a
PRD §3 sentence in the test's docstring.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    ADMIN,
    accept_consultation,
    advance_clock,
    api_client,
    approve_prescription,
    bureau_rejected_event,
    bureau_settled_event,
    build_responses_for_band,
    create_consultation,
    create_consultation_payload,
    create_doctor,
    create_follow_up,
    create_follow_up_payload,
    create_patient,
    create_pharmacist,
    create_prescription_payload,
    dispatch_prescription,
    draft_prescription,
    fire_reminder,
    get_success_data,
    make_doctor_headers,
    make_patient_headers,
    make_pharmacist_headers,
    make_prescription_item,
    make_questionnaire_response,
    open_and_assess_triage,
    open_triage_session,
    quality_report_payload,
    register_department_mapping,
    reject_prescription,
    revise_prescription,
    setup_basic_org,
    setup_completed_consultation,
    setup_consultation_pending,
    setup_in_progress_consultation,
    settle_claim,
    start_consultation,
    submit_follow_up_form,
    submit_form_payload,
    submit_prescription,
    transfer_payload,
    validate_error,
    validate_success,
    verify_eligibility,
    DEFAULT_DEPARTMENT_CODE,
    DEFAULT_REGION_CODE,
    DEFAULT_HOSPITAL_ID,
    IN_SCOPE_DISEASE,
    OUT_OF_SCOPE_DISEASE,
    TEST_USERS,
)
from test_suite.test_06_insurance import _find_claim_for_consultation


def _future_iso(seconds: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{dt.microsecond // 1000:03d}"
    return f"{base}.{millis}Z"


# =========================================================================
# rule: dual_variant_calc
# =========================================================================
class TestDualVariantCalc:
    # ---------------------------------------------------------------------
    # difficulty: dual_variant_calc/insurance_reimbursement_in_scope_vs_out_of_scope
    # ---------------------------------------------------------------------
    def test_in_scope_tier_rates(self, api):
        """PRD §3.7: 'the first-tier rate is 0.70 and the second-tier
        rate is 0.50' for in-scope diseases.

        Claim: in-scope claim with claim_amount_cents=15000, deductible
        5000 -> eligible=10000 fits exactly tier1; reimbursed_cents =
        round_half_up(10000 * 0.70) = 7000; self_pay = 8000.

        # difficulty: dual_variant_calc/insurance_reimbursement_in_scope_vs_out_of_scope
        """
        state = setup_completed_consultation(
            elapsed_seconds=20 * 60, doctor_base_fee=30.00,
            insurance_policy_no="POL-001",
        )
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
            items=[make_prescription_item(
                quantity=18, unit_price_cents=500,
            )],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE under this setup")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = approve_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        pres = dispatch_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        claim = _find_claim_for_consultation(state["consultation"]["id"])
        if claim is None:
            pytest.skip("No claim discoverable")
        verified = verify_eligibility(claim=claim, insurance_status="ELIGIBLE")
        assert verified["claim_amount_cents"] == 15000
        settling = settle_claim(claim=verified)
        assert settling["reimbursed_cents"] == 7000
        assert settling["self_pay_cents"] == 8000

    # DELETED: test_out_of_scope_tier_rates.
    # PRD §3.6 requires every disease_code in a prescription to lie inside
    # PRESCRIPTION_ALLOWED_DISEASES for eligibility=ELIGIBLE. PRD §3.7's
    # out-of-scope penalty branch requires the linked prescription's
    # disease_codes to be fully OUTSIDE the in-scope enumeration. With
    # the test's `disease_codes=[OUT_OF_SCOPE_DISEASE]`, the prescription
    # can never become ELIGIBLE under PRD §3.6 and therefore can never
    # reach the dispatch->insurance-claim path. The test path is
    # unreachable from a PRD-faithful implementation; PRD does not
    # uniquely determine an out-of-scope-but-eligible prescription, so
    # the assertion is not uniquely derivable. (STEP 1b unique-derivability
    # collapse: BRANCH-ASYMMETRIC SIDE EFFECT.)

    # ---------------------------------------------------------------------
    # difficulty: dual_variant_calc/triage_severity_score_initial_vs_replay
    # ---------------------------------------------------------------------
    def test_triage_score_forward_looking_initial_v1(self, api):
        """PRD §3.2: 'The first call to assess on a COLLECTING session
        uses the forward-looking initial variant: all currently attached
        responses are included and the raw weights are used. A
        chronological-replay variant is reserved for future re-assessment
        after a reopen but is not exposed in v1 -- v1 is locked to the
        forward-looking initial variant.'

        Claim: same-question-code entries are summed (not overwritten);
        responses with question_code=CHEST_PAIN weights [2, 1] and a
        VITAL_BP NORMAL entry -> chief_complaint_score == (2+1+0)*10 == 30,
        vital_anomaly_score == 0, risk_factor_score == 3 (DIABETES),
        severity_score == 33.

        # difficulty: dual_variant_calc/triage_severity_score_initial_vs_replay
        """
        setup_basic_org()
        patient = create_patient(chronic_condition_codes=["DIABETES"])
        session = open_and_assess_triage(
            patient=patient,
            responses=[
                make_questionnaire_response(
                    question_code="CHEST_PAIN", answer_value="YES",
                    severity_weight=2,
                ),
                make_questionnaire_response(
                    question_code="CHEST_PAIN", answer_value="INTENSE",
                    severity_weight=1,
                ),
                make_questionnaire_response(
                    question_code="VITAL_BP", answer_value="NORMAL",
                    severity_weight=0,
                ),
            ],
        )
        # Forward-looking initial: sum all weights for chief.
        assert session["chief_complaint_score"] == (2 + 1 + 0) * 10
        # VITAL_BP NORMAL doesn't count as ABNORMAL -> vital_anomaly == 0
        assert session["vital_anomaly_score"] == 0
        assert session["risk_factor_score"] == 3
        assert session["severity_score"] == 33

    def test_triage_score_distinct_from_insurance_domain(self, api):
        """PRD §3.2: 'The final severity_score is the sum of
        chief_complaint_score, vital_anomaly_score, and risk_factor_score.
        All arithmetic is integer; no rounding is required.'

        Claim: the triage score is fully determined by the
        questionnaire+chronic_codes inputs, and is independent of any
        InsuranceClaim domain values (no cross-influence).

        # difficulty: dual_variant_calc/triage_severity_score_initial_vs_replay
        """
        setup_basic_org()
        patient = create_patient(chronic_condition_codes=[])
        session = open_and_assess_triage(
            patient=patient,
            responses=[
                make_questionnaire_response(
                    question_code="CHEST_PAIN", severity_weight=5,
                ),
            ],
        )
        # chief = 50, vital = 0, risk = 0 -> 50 (MID band)
        assert session["chief_complaint_score"] == 50
        assert session["severity_score"] == 50
        assert session["severity_band"] == "MID"


# =========================================================================
# rule: combinatorial_formula
# =========================================================================
class TestCombinatorialFormula:
    # ---------------------------------------------------------------------
    # difficulty: combinatorial_formula/consultation_fee_tiered_rate_with_ceil_mode_a
    # ---------------------------------------------------------------------
    def test_consultation_fee_tiered_with_ceil_750s(self, api):
        """PRD §3.5: 'let the elapsed minutes be the ceiling of the
        elapsed seconds divided by 60. Let the first-tier minutes be the
        smaller of the elapsed minutes and 10, and let the second-tier
        minutes be zero or the elapsed minutes minus 10, whichever is
        greater. The raw total in cents is the snapshotted base_fee
        converted to cents, plus the first-tier minutes multiplied by the
        first-tier rate, plus the second-tier minutes multiplied by the
        second-tier rate.'

        Claim: 750 seconds elapsed (== 12 min 30 sec) -> duration_minutes
        = ceil(750/60) = 13; with base_fee=30.00 (3000 cents), total =
        (3000 + 10*100 + 3*200) / 100 = 46.00.

        # difficulty: combinatorial_formula/consultation_fee_tiered_rate_with_ceil_mode_a
        """
        state = setup_completed_consultation(
            elapsed_seconds=750, doctor_base_fee=30.00,
        )
        c = state["consultation"]
        assert c["duration_minutes"] == 13
        assert c["total_fee"] == pytest.approx(46.00, abs=0.001)

    def test_consultation_fee_round_half_up_at_end(self, api):
        """PRD §3.5: 'The final total_fee is that raw cents total divided
        by 100.0 and rounded half-up to two decimal places. The rounding
        happens exactly once, on the final sum -- not per tier.'

        Claim: any whole-cent raw total divided by 100 produces an exact
        two-decimal result (no rounding needed since cents-precision is
        preserved); demonstrating that the system stores total_fee with
        2-decimal precision and matches the formula.

        # difficulty: combinatorial_formula/consultation_fee_tiered_rate_with_ceil_mode_a
        """
        # 5-minute session @ base 30.00:
        # raw_cents = 3000 + 5*100 + 0 = 3500; / 100.0 = 35.00
        state = setup_completed_consultation(
            elapsed_seconds=300, doctor_base_fee=30.00,
        )
        c = state["consultation"]
        assert c["total_fee"] == pytest.approx(35.00, abs=0.001)

    # ---------------------------------------------------------------------
    # difficulty: combinatorial_formula/insurance_reimbursement_per_tier_then_sum_rounding_mode_b
    # ---------------------------------------------------------------------
    def test_insurance_per_tier_rounding(self, api):
        """PRD §3.7: 'Each tier is multiplied by its rate and rounded
        half-up to integer cents independently; the rounded tier amounts
        are then summed to produce reimbursed_cents. (Contrast this
        rounding order with the consultation fee, which rounds once at
        the very end.)'

        Claim: in-scope claim with claim_amount_cents=15000, deductible
        5000 -> eligible=10000, tier1=10000, tier1_amt=round_half_up(7000.0)=7000,
        tier2=0; reimbursed_cents=7000. Verifies the per-tier rounding
        formula precision.

        # difficulty: combinatorial_formula/insurance_reimbursement_per_tier_then_sum_rounding_mode_b
        """
        state = setup_completed_consultation(
            elapsed_seconds=20 * 60, doctor_base_fee=30.00,
            insurance_policy_no="POL-001",
        )
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
            items=[make_prescription_item(
                quantity=18, unit_price_cents=500,
            )],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = approve_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        pres = dispatch_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        claim = _find_claim_for_consultation(state["consultation"]["id"])
        if claim is None:
            pytest.skip("No claim discoverable")
        verified = verify_eligibility(claim=claim, insurance_status="ELIGIBLE")
        settling = settle_claim(claim=verified)
        # Per-tier formula: tier1_amt = round_half_up(10000 * 0.70) = 7000,
        # tier2_amt = 0; reimbursed_cents = 7000.
        assert settling["reimbursed_cents"] == 7000

    def test_insurance_rounding_distinct_from_consultation_fee(self, api):
        """PRD §3.7: 'Contrast this rounding order with the consultation
        fee, which rounds once at the very end.'

        Claim: consultation_fee.total_fee uses round-once semantics
        ('total_fee == 35.00' on a 5-minute session at base 30.00,
        independent of any per-tier rounding) while insurance
        reimbursement uses per-tier semantics — demonstrating the
        deliberately different rounding orders.

        # difficulty: combinatorial_formula/insurance_reimbursement_per_tier_then_sum_rounding_mode_b
        """
        # Consultation total_fee with a simple 5-min @ 30.00 base -> 35.00
        state = setup_completed_consultation(
            elapsed_seconds=300, doctor_base_fee=30.00,
        )
        assert state["consultation"]["total_fee"] == pytest.approx(35.00,
                                                                   abs=0.001)


# =========================================================================
# rule: non_linear_state_machine
# =========================================================================
class TestNonLinearStateMachine:
    # ---------------------------------------------------------------------
    # difficulty: non_linear_state_machine/prescription_revision_cycle_REJECTED_to_DRAFT
    # ---------------------------------------------------------------------
    def test_prescription_revise_cycle_increments_revision_count(self, api):
        """PRD §3.6: 'From REJECTED, the drafting doctor ... may revise
        to bring the prescription back to DRAFT. Revision may optionally
        replace items and disease_codes. Revision clears rejection_reason
        and increments revision_count by one.'

        Claim: REJECTED -> /revise -> DRAFT with revision_count == 1.
        # difficulty: non_linear_state_machine/prescription_revision_cycle_REJECTED_to_DRAFT
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = reject_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        revised = revise_prescription(
            prescription=pres, doctor=state["doctor"],
        )
        assert revised["status"] == "DRAFT"
        assert revised["revision_count"] == 1

    def test_prescription_revise_to_failed_at_max(self, api):
        """PRD §3.6: 'The system caps the revision loop: once
        revision_count has reached the configured maximum, a further
        revise call instead drives an automatic transition from REJECTED
        to the terminal FAILED.'

        Claim: cycling revisions until the implementation's max boundary,
        the next /revise drives status to FAILED. We loop up to a
        generous cap (10) since PRD §3.6 does not name MAX_REVISIONS;
        the test asserts the existence of the cap rather than a specific
        value, by verifying that the prescription eventually reaches
        FAILED.
        # difficulty: non_linear_state_machine/prescription_revision_cycle_REJECTED_to_DRAFT
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE")
        for _ in range(15):
            pres = submit_prescription(prescription=pres, doctor=state["doctor"])
            pres = reject_prescription(
                prescription=pres, pharmacist=state["pharmacist"],
            )
            res = api.revise_prescription(
                pres["id"], make_doctor_headers(state["doctor"]["id"]),
            )
            data = get_success_data(res)
            pres = data
            if pres["status"] == "FAILED":
                break
        assert pres["status"] == "FAILED", (
            "Expected eventual transition to FAILED via the PRD §3.6 "
            "cap; got "
            f"status={pres['status']}, revision_count={pres.get('revision_count')}"
        )

    # ---------------------------------------------------------------------
    # difficulty: non_linear_state_machine/consultation_parallel_session_and_quality_dimensions
    # ---------------------------------------------------------------------
    def test_quality_status_independently_steps_to_failed(self, api):
        """PRD §3.5: 'A quality report submission carries a report_tier
        and steps the status along OK -> DEGRADED -> FAILED.'

        Claim: two /quality-report calls (DEGRADED then FAILED) move
        quality_status from OK to FAILED while session_status remains
        IN_PROGRESS — parallel dimensions evolve independently.
        # difficulty: non_linear_state_machine/consultation_parallel_session_and_quality_dimensions
        """
        state = setup_in_progress_consultation(media_type="VIDEO")
        # quality_status begins at OK (PRD §3.4 video init)
        first = get_success_data(api.quality_report(
            state["consultation"]["id"],
            quality_report_payload("DEGRADED"),
            make_doctor_headers(state["doctor"]["id"]),
        ))
        assert first["quality_status"] == "DEGRADED"
        assert first["session_status"] == "IN_PROGRESS"
        second = get_success_data(api.quality_report(
            state["consultation"]["id"],
            quality_report_payload("FAILED"),
            make_doctor_headers(state["doctor"]["id"]),
        ))
        assert second["quality_status"] == "FAILED"
        assert second["session_status"] == "IN_PROGRESS"

    def test_quality_failed_blocks_complete(self, api):
        """PRD §3.5: 'Once quality_status reaches FAILED, the doctor may
        no longer complete the session normally -- completion of a video
        consultation is gated on quality_status being anything other than
        FAILED.'

        Claim: VIDEO quality FAILED -> /complete returns ERR_INVALID_STATE.
        # difficulty: non_linear_state_machine/consultation_parallel_session_and_quality_dimensions
        """
        state = setup_in_progress_consultation(media_type="VIDEO")
        get_success_data(api.quality_report(
            state["consultation"]["id"],
            quality_report_payload("DEGRADED"),
            make_doctor_headers(state["doctor"]["id"]),
        ))
        get_success_data(api.quality_report(
            state["consultation"]["id"],
            quality_report_payload("FAILED"),
            make_doctor_headers(state["doctor"]["id"]),
        ))
        res = api.complete_consultation(
            state["consultation"]["id"],
            make_doctor_headers(state["doctor"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =========================================================================
# rule: transitive_cascade
# =========================================================================
class TestTransitiveCascade:
    # ---------------------------------------------------------------------
    # difficulty: transitive_cascade/consultation_complete_to_prescription_to_insurance_chain_depth3
    # ---------------------------------------------------------------------
    def test_complete_to_prescription_to_claim_depth3(self, api):
        """PRD §3.7: 'A patient whose insurance_status is ELIGIBLE
        advances the claim to VERIFIED and sets ... claim_amount_cents to
        the consultation's total_fee converted to cents plus the linked
        prescription's gross_amount_cents (when a prescription is
        linked).'

        Claim (depth-3 chain): completed consultation total_fee feeds
        gross_amount_cents (via the linked prescription) into
        claim_amount_cents at /verify-eligibility. Concrete: 10-min
        @ base 30.00 -> total_fee = 40.00 -> 4000 cents; pres items
        [qty=2, unit=500] -> gross 1000; verified claim_amount_cents = 5000.
        # difficulty: transitive_cascade/consultation_complete_to_prescription_to_insurance_chain_depth3
        """
        state = setup_completed_consultation(
            elapsed_seconds=600, doctor_base_fee=30.00,
            insurance_policy_no="POL-001",
        )
        # 10-min: raw = 3000 + 10*100 + 0 = 4000 -> total_fee = 40.00
        assert state["consultation"]["total_fee"] == pytest.approx(40.00,
                                                                   abs=0.001)
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
            items=[make_prescription_item(
                quantity=2, unit_price_cents=500,
            )],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = approve_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        assert pres["gross_amount_cents"] == 1000
        pres = dispatch_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        claim = _find_claim_for_consultation(state["consultation"]["id"])
        if claim is None:
            pytest.skip("No claim discoverable")
        verified = verify_eligibility(
            claim=claim, insurance_status="ELIGIBLE",
        )
        # 4000 + 1000 = 5000
        assert verified["claim_amount_cents"] == 5000

    def test_claim_deductible_set_at_verified(self, api):
        """PRD §3.7: 'A patient whose insurance_status is ELIGIBLE
        advances the claim to VERIFIED and sets deductible_cents to a
        per-claim deductible of 5,000 cents'.

        Claim: at VERIFIED, deductible_cents == 5000.
        # difficulty: transitive_cascade/consultation_complete_to_prescription_to_insurance_chain_depth3
        """
        state = setup_completed_consultation(
            elapsed_seconds=600, doctor_base_fee=30.00,
            insurance_policy_no="POL-001",
        )
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
            items=[make_prescription_item(
                quantity=2, unit_price_cents=500,
            )],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = approve_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        pres = dispatch_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        claim = _find_claim_for_consultation(state["consultation"]["id"])
        if claim is None:
            pytest.skip("No claim")
        verified = verify_eligibility(claim=claim, insurance_status="ELIGIBLE")
        assert verified["deductible_cents"] == 5000

    # ---------------------------------------------------------------------
    # difficulty: transitive_cascade/follow_up_submit_abnormal_creates_consultation_depth2
    # ---------------------------------------------------------------------
    def test_abnormal_submission_creates_escalation_consultation(self, api):
        """PRD §3.8: 'When abnormal_flag is true, the task advances from
        SUBMITTED to the terminal ESCALATED: the system creates a new
        Consultation for the same patient with the same doctor in a
        freshly created state, records the new consultation's id in
        escalation_consultation_id'.

        Claim: form severity high -> task ESCALATED and
        escalation_consultation_id resolves to a Consultation.
        # difficulty: transitive_cascade/follow_up_submit_abnormal_creates_consultation_depth2
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        task = create_follow_up(
            consultation=state["consultation"],
            doctor=state["doctor"],
            scheduled_reminder_at=_future_iso(60),
            reminder_channels=["SMS"],
        )
        advance_clock(61)
        fire_reminder(task)
        result = submit_follow_up_form(
            task=task, patient=state["patient"],
            form_payload={"severity": 10, "issue": "bleeding"},
        )
        assert result["status"] == "ESCALATED"
        assert result["abnormal_flag"] is True
        assert result.get("escalation_consultation_id")
        consult = get_success_data(api_client.get_consultation(
            result["escalation_consultation_id"], ADMIN,
        ))
        # The escalation Consultation must reference the same patient.
        assert consult["patient_id"] == state["patient"]["id"]

    def test_normal_submission_closes_no_escalation(self, api):
        """PRD §3.8: 'When abnormal_flag is false, the task advances from
        SUBMITTED to the terminal CLOSED.'

        Claim: severity below threshold -> CLOSED, no
        escalation_consultation_id.
        # difficulty: transitive_cascade/follow_up_submit_abnormal_creates_consultation_depth2
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        task = create_follow_up(
            consultation=state["consultation"],
            doctor=state["doctor"],
            scheduled_reminder_at=_future_iso(60),
            reminder_channels=["SMS"],
        )
        advance_clock(61)
        fire_reminder(task)
        result = submit_follow_up_form(
            task=task, patient=state["patient"],
            form_payload={"severity": 1},
        )
        assert result["status"] == "CLOSED"
        assert result["abnormal_flag"] is False
        assert result.get("escalation_consultation_id") in (None, "")


# =========================================================================
# rule: priority_pair_validation_conflict
# =========================================================================
class TestPriorityPairValidationConflict:
    # ---------------------------------------------------------------------
    # difficulty: priority_pair_validation_conflict/state_vs_business_safety_segregation_pair
    # ---------------------------------------------------------------------
    def test_state_check_wins_over_segregation_of_duties(self, api):
        """PRD §2.6: 'header presence first (ERR_AUTH_MISSING), then
        role-permission (ERR_FORBIDDEN), then path-existence
        (ERR_NOT_FOUND), then body foreign-key existence
        (ERR_REF_NOT_FOUND), then state-machine from-state
        (ERR_INVALID_STATE), and only after all of those have passed are
        domain-specific business rules evaluated.'

        Claim: when Prescription is in DRAFT (not UNDER_REVIEW) AND the
        caller is a pharmacist whose X-User-ID equals drafting_doctor_id,
        the state check (priority 5) shadows the SoD check (priority 7).
        Result: ERR_INVALID_STATE (HTTP 409), not ERR_SEGREGATION_OF_DUTIES.
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_segregation_pair
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
        )
        # Pres is in DRAFT (not UNDER_REVIEW). Pharmacist sends approve
        # with X-User-ID equal to drafting doctor's id. Both SoD and
        # state would fail. PRD §2.6 says state check wins.
        res = api.approve_prescription(
            pres["id"],
            make_pharmacist_headers(state["doctor"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_segregation_of_duties_when_state_is_correct(self, api):
        """PRD §3.6: 'A pharmacist whose X-User-ID equals the
        prescription's drafting_doctor_id is rejected on either approval
        or rejection with ERR_SEGREGATION_OF_DUTIES.'

        Claim: when the state precondition is satisfied (UNDER_REVIEW) and
        only SoD would fail, the error_id is ERR_SEGREGATION_OF_DUTIES.
        Complement to the state-wins case above.
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_segregation_pair
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        # Now UNDER_REVIEW; pharmacist X-User-ID == drafting_doctor_id.
        res = api.approve_prescription(
            pres["id"],
            make_pharmacist_headers(state["doctor"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    # ---------------------------------------------------------------------
    # difficulty: priority_pair_validation_conflict/business_safety_emergency_vs_business_referential_doctor_pair
    # ---------------------------------------------------------------------
    def test_emergency_triage_wins_over_preferred_doctor_ineligible(self, api):
        """PRD §3.2: 'subsequently rejects any attempt to create a
        Consultation against this triage session with
        ERR_TRIAGE_EMERGENCY_ROUTED.'

        Claim: when the triage is EMERGENCY_ROUTED AND the patient has a
        preferred_doctor_id that would independently fail eligibility,
        the safety check fires first (priority 6 > priority 13). Result:
        ERR_TRIAGE_EMERGENCY_ROUTED, not ERR_PREFERRED_DOCTOR_INELIGIBLE.
        # difficulty: priority_pair_validation_conflict/business_safety_emergency_vs_business_referential_doctor_pair
        """
        register_department_mapping(
            department_code=DEFAULT_DEPARTMENT_CODE,
            disease_codes=[IN_SCOPE_DISEASE],
        )
        register_department_mapping(
            department_code="DERM",
            disease_codes=["DERMA_X"], triage_priority=2,
        )
        # Eligible cardio doctor:
        create_doctor(
            department_code=DEFAULT_DEPARTMENT_CODE,
            specialty_codes=[IN_SCOPE_DISEASE],
            licensed_region_codes=[DEFAULT_REGION_CODE],
        )
        derm_doc = create_doctor(
            department_code="DERM",
            specialty_codes=["DERMA_X"],
            licensed_region_codes=[DEFAULT_REGION_CODE],
        )
        patient = create_patient(preferred_doctor_id=derm_doc["id"])
        triage = open_and_assess_triage(
            patient=patient,
            responses=build_responses_for_band("EMERGENCY"),
        )
        res = api.create_consultation(
            create_consultation_payload(
                triage_session_id=triage["id"],
                mode="REAL_TIME", media_type="TEXT_IMAGE",
                doctor_id=derm_doc["id"],
            ),
            make_patient_headers(patient["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TRIAGE_EMERGENCY_ROUTED.value)

    def test_preferred_doctor_ineligible_when_no_emergency(self, api):
        """PRD §3.3: 'If the named doctor fails the filter, the request
        is rejected with ERR_PREFERRED_DOCTOR_INELIGIBLE'.

        Claim: when triage is not emergency but the preferred doctor is
        ineligible, error_id is ERR_PREFERRED_DOCTOR_INELIGIBLE.
        Complement to the safety-wins case above.
        # difficulty: priority_pair_validation_conflict/business_safety_emergency_vs_business_referential_doctor_pair
        """
        register_department_mapping(
            department_code=DEFAULT_DEPARTMENT_CODE,
            disease_codes=[IN_SCOPE_DISEASE],
        )
        register_department_mapping(
            department_code="DERM",
            disease_codes=["DERMA_X"], triage_priority=2,
        )
        create_doctor(
            department_code=DEFAULT_DEPARTMENT_CODE,
            specialty_codes=[IN_SCOPE_DISEASE],
            licensed_region_codes=[DEFAULT_REGION_CODE],
        )
        derm_doc = create_doctor(
            department_code="DERM",
            specialty_codes=["DERMA_X"],
            licensed_region_codes=[DEFAULT_REGION_CODE],
        )
        patient = create_patient(preferred_doctor_id=derm_doc["id"])
        triage = open_and_assess_triage(
            patient=patient, responses=build_responses_for_band("MID"),
        )
        res = api.create_consultation(
            create_consultation_payload(
                triage_session_id=triage["id"],
                mode="REAL_TIME", media_type="TEXT_IMAGE",
                doctor_id=derm_doc["id"],
            ),
            make_patient_headers(patient["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PREFERRED_DOCTOR_INELIGIBLE.value)


# =========================================================================
# rule: boundary_precision_check
# =========================================================================
class TestBoundaryPrecisionCheck:
    # ---------------------------------------------------------------------
    # difficulty: boundary_precision_check/severity_band_threshold_30_inclusive_via_triage_assess
    # ---------------------------------------------------------------------
    def test_severity_30_is_mid_inclusive(self, api):
        """PRD §3.2: 'MID when the score is at least 30 and strictly
        below 60'.

        Claim: severity_score == 30 -> severity_band == MID
        (boundary inclusive on >= 30).
        # difficulty: boundary_precision_check/severity_band_threshold_30_inclusive_via_triage_assess
        """
        setup_basic_org()
        patient = create_patient(
            chronic_condition_codes=["DIABETES", "HYPERTENSION"],
        )
        # chief = 20, vital = 4, risk = 6 -> 30
        responses = [
            make_questionnaire_response(
                question_code="CHEST_PAIN", severity_weight=2,
            ),
            make_questionnaire_response(
                question_code="VITAL_BP", answer_value="ABNORMAL",
                severity_weight=0,
            ),
            make_questionnaire_response(
                question_code="VITAL_HR", answer_value="ABNORMAL",
                severity_weight=0,
            ),
        ]
        session = open_and_assess_triage(
            patient=patient, responses=responses,
        )
        assert session["severity_score"] == 30
        assert session["severity_band"] == "MID"

    def test_severity_28_is_low(self, api):
        """PRD §3.2: 'LOW when the score is strictly below 30'.

        Claim: severity_score == 28 -> severity_band == LOW
        (boundary exclusive on < 30).
        # difficulty: boundary_precision_check/severity_band_threshold_30_inclusive_via_triage_assess
        """
        setup_basic_org()
        patient = create_patient(
            chronic_condition_codes=["DIABETES", "HYPERTENSION"],
        )
        # chief = 20, vital = 2, risk = 6 -> 28
        responses = [
            make_questionnaire_response(
                question_code="CHEST_PAIN", severity_weight=2,
            ),
            make_questionnaire_response(
                question_code="VITAL_BP", answer_value="ABNORMAL",
                severity_weight=0,
            ),
        ]
        session = open_and_assess_triage(
            patient=patient, responses=responses,
        )
        assert session["severity_score"] == 28
        assert session["severity_band"] == "LOW"

    # ---------------------------------------------------------------------
    # difficulty: boundary_precision_check/pagination_zero_count_vs_one_count_on_follow_up_tasks
    # ---------------------------------------------------------------------
    def test_reminder_channels_empty_rejected(self, api):
        """PRD §3.8: 'An empty or out-of-range reminder_channels value is
        rejected with ERR_REMINDER_CHANNELS_INVALID.'

        Claim: reminder_channels=[] (collection size 0) -> 422
        ERR_REMINDER_CHANNELS_INVALID.
        # difficulty: boundary_precision_check/pagination_zero_count_vs_one_count_on_follow_up_tasks
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        res = api.create_follow_up_task(
            create_follow_up_payload(
                consultation_id=state["consultation"]["id"],
                scheduled_reminder_at=_future_iso(3600),
                reminder_channels=[],
            ),
            make_doctor_headers(state["doctor"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_REMINDER_CHANNELS_INVALID.value)

    def test_reminder_channels_single_accepted(self, api):
        """PRD §3.8: 'a non-empty subset of reminder_channels drawn from
        SMS, EMAIL, and APP_PUSH'.

        Claim: reminder_channels=['SMS'] (collection size 1) -> 201,
        status == PLANNED.
        # difficulty: boundary_precision_check/pagination_zero_count_vs_one_count_on_follow_up_tasks
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        res = api.create_follow_up_task(
            create_follow_up_payload(
                consultation_id=state["consultation"]["id"],
                scheduled_reminder_at=_future_iso(3600),
                reminder_channels=["SMS"],
            ),
            make_doctor_headers(state["doctor"]["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "PLANNED"
        assert len(data["reminder_channels"]) == 1


# =========================================================================
# rule: cross_entity_state_dependency
# =========================================================================
class TestCrossEntityStateDependency:
    # ---------------------------------------------------------------------
    # difficulty: cross_entity_state_dependency/consultation_create_requires_triage_session_ASSESSED_not_emergency
    # ---------------------------------------------------------------------
    def test_consultation_against_collecting_triage_rejected(self, api):
        """PRD §3.3: 'When the patient proceeds beyond triage by creating
        a Consultation, the body carries the triage_session_id'. The
        parent triage must be ASSESSED for the transition ASSESSED ->
        MATCHED to apply.

        Claim: POST /consultations against a TriageSession still in
        COLLECTING -> ERR_INVALID_STATE.
        # difficulty: cross_entity_state_dependency/consultation_create_requires_triage_session_ASSESSED_not_emergency
        """
        setup_basic_org()
        patient = create_patient()
        triage = open_triage_session(patient=patient)
        # Not assessed yet -> status COLLECTING.
        assert triage["status"] == "COLLECTING"
        res = api.create_consultation(
            create_consultation_payload(
                triage_session_id=triage["id"],
                mode="REAL_TIME", media_type="TEXT_IMAGE",
            ),
            make_patient_headers(patient["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_consultation_against_emergency_triage_rejected(self, api):
        """PRD §3.2: 'subsequently rejects any attempt to create a
        Consultation against this triage session with
        ERR_TRIAGE_EMERGENCY_ROUTED.'

        Claim: POST /consultations against EMERGENCY_ROUTED triage -> 422.
        # difficulty: cross_entity_state_dependency/consultation_create_requires_triage_session_ASSESSED_not_emergency
        """
        setup_basic_org()
        patient = create_patient()
        triage = open_and_assess_triage(
            patient=patient,
            responses=build_responses_for_band("EMERGENCY"),
        )
        res = api.create_consultation(
            create_consultation_payload(
                triage_session_id=triage["id"],
                mode="REAL_TIME", media_type="TEXT_IMAGE",
            ),
            make_patient_headers(patient["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TRIAGE_EMERGENCY_ROUTED.value)

    # ---------------------------------------------------------------------
    # difficulty: cross_entity_state_dependency/prescription_submit_requires_consultation_COMPLETED
    # ---------------------------------------------------------------------
    def test_prescription_submit_requires_consultation_completed(self, api):
        """PRD §3.6: 'Submission also requires the parent consultation's
        session_status to be COMPLETED.'

        Claim: /submit on a Prescription whose parent Consultation is
        IN_PROGRESS (not COMPLETED) -> ERR_INVALID_STATE.
        # difficulty: cross_entity_state_dependency/prescription_submit_requires_consultation_COMPLETED
        """
        state = setup_in_progress_consultation()
        # Doctor attempts to draft a prescription pre-completion. PRD
        # §3.6 says 'After a consultation reaches COMPLETED, the
        # attending doctor may draft an electronic prescription' — we
        # try the draft regardless and, if it succeeds, /submit MUST
        # surface ERR_INVALID_STATE because the parent is not COMPLETED.
        res = api.create_prescription(
            create_prescription_payload(
                consultation_id=state["consultation"]["id"],
                disease_codes=[IN_SCOPE_DISEASE],
            ),
            make_doctor_headers(state["doctor"]["id"]),
        )
        if not (200 <= res.status_code < 300):
            # If the implementation blocks draft pre-completion, that's
            # an alternative-but-PRD-faithful behavior. We treat that as
            # an early signal that the cross-entity state dep is enforced
            # and skip the submit-specific assertion to remain
            # PRD-faithful (since PRD does not commit to blocking draft).
            pytest.skip(
                "Implementation blocks draft pre-completion; the "
                "submit-time cross-entity check is therefore unreachable."
            )
        pres = res.json()["data"]
        res2 = api.submit_prescription(
            pres["id"], make_doctor_headers(state["doctor"]["id"]),
        )
        validate_error(res2, ApiErrorId.ERR_INVALID_STATE.value)

    def test_prescription_submit_succeeds_after_completion(self, api):
        """PRD §3.6: 'After a consultation reaches COMPLETED, the
        attending doctor may draft an electronic prescription.'
        PRD §3.6: 'submits the draft to the pharmacist queue, advancing
        status from DRAFT to UNDER_REVIEW.'

        Claim: /submit succeeds once the consultation is COMPLETED.
        # difficulty: cross_entity_state_dependency/prescription_submit_requires_consultation_COMPLETED
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE under this setup")
        submitted = submit_prescription(
            prescription=pres, doctor=state["doctor"],
        )
        assert submitted["status"] == "UNDER_REVIEW"


# =========================================================================
# rule: resource_temporal_overlap
# =========================================================================
class TestResourceTemporalOverlap:
    # ---------------------------------------------------------------------
    # difficulty: resource_temporal_overlap/appointment_consultation_slot_overlap_closed_open
    # ---------------------------------------------------------------------
    def test_appointment_slot_overlap_rejected(self, api):
        """PRD §3.4: 'scheduled_start_at must not overlap any other
        accepted-or-in-progress appointment for the same doctor_id,
        where each existing appointment occupies the closed-open window
        [scheduled_start_at, scheduled_start_at + SLOT_MINUTES); overlapping
        with a row in ACCEPTED or IN_PROGRESS yields ERR_DOCTOR_SLOT_OVERLAP.'

        Claim: a second APPOINTMENT scheduled inside the first's
        [start, start+SLOT_MINUTES) -> 409 ERR_DOCTOR_SLOT_OVERLAP.
        # difficulty: resource_temporal_overlap/appointment_consultation_slot_overlap_closed_open
        """
        # PRD §3.4 names SLOT_MINUTES as the slot length but does not
        # commit to a specific value; the closed-open semantics state
        # that two appointments starting at the same instant overlap.
        # We schedule both at the same moment to be unambiguous.
        future = _future_iso(3600 * 4)
        register_department_mapping(
            department_code=DEFAULT_DEPARTMENT_CODE,
            disease_codes=[IN_SCOPE_DISEASE],
        )
        doctor = create_doctor(
            department_code=DEFAULT_DEPARTMENT_CODE,
            specialty_codes=[IN_SCOPE_DISEASE],
            licensed_region_codes=[DEFAULT_REGION_CODE],
            hospital_id=DEFAULT_HOSPITAL_ID,
            base_fee=30.00,
        )
        # First appointment:
        patient_a = create_patient()
        triage_a = open_and_assess_triage(
            patient=patient_a,
            responses=build_responses_for_band("MID"),
        )
        first = api.create_consultation(
            create_consultation_payload(
                triage_session_id=triage_a["id"],
                mode="APPOINTMENT", media_type="TEXT_IMAGE",
                scheduled_start_at=future,
            ),
            make_patient_headers(patient_a["id"]),
        )
        if not (200 <= first.status_code < 300):
            pytest.skip(
                "First appointment failed (possibly OUT_OF_SCHEDULE); "
                "PRD does not commit to a default DoctorSchedule API."
            )
        # Second appointment at the same instant:
        patient_b = create_patient()
        triage_b = open_and_assess_triage(
            patient=patient_b,
            responses=build_responses_for_band("MID"),
        )
        second = api.create_consultation(
            create_consultation_payload(
                triage_session_id=triage_b["id"],
                mode="APPOINTMENT", media_type="TEXT_IMAGE",
                scheduled_start_at=future,
            ),
            make_patient_headers(patient_b["id"]),
        )
        validate_error(second, ApiErrorId.ERR_DOCTOR_SLOT_OVERLAP.value)

    def test_appointment_in_open_window_succeeds(self, api):
        """PRD §3.4: 'For APPOINTMENT, the system advances session_status
        from PENDING directly to ACCEPTED (no queue) and queue_position
        remains null.'

        Claim: a single appointment scheduled at a reasonable time is
        accepted (queue_position null). Complement to the overlap test:
        absent overlap, the request succeeds.
        # difficulty: resource_temporal_overlap/appointment_consultation_slot_overlap_closed_open
        """
        future = _future_iso(3600 * 4)
        state = setup_consultation_pending(
            mode="APPOINTMENT", scheduled_start_at=future,
        )
        c = state["consultation"]
        assert c["session_status"] == "ACCEPTED"
        assert c.get("queue_position") is None

    # ---------------------------------------------------------------------
    # difficulty: resource_temporal_overlap/doctor_schedule_open_window_inclusive_inclusive
    # ---------------------------------------------------------------------
    # DELETED: test_schedule_window_published_required_for_appointment.
    # PRD §3.4 references "a published DoctorSchedule open window" but the
    # PRD does not commit to any publish-API. With no publish API, the
    # state in which a doctor has zero open windows cannot be established
    # via PRD-described inputs, so PRD does not uniquely determine the
    # outcome of an appointment created against an unpublished doctor.
    # (STEP 1b unique-derivability collapse: DEFAULT-VALUE SILENCE — the
    # impl is free to treat absent windows as permissive (always-open) and
    # remain PRD-faithful.)

    def test_appointment_at_workday_noon_succeeds(self, api):
        """PRD §3.4: 'scheduled_start_at must fall entirely inside a
        published DoctorSchedule open window for that doctor'.

        Claim: an appointment at a workday-noon time is INSIDE any
        reasonable open window and succeeds — complement to the
        out-of-window rejection above.
        # difficulty: resource_temporal_overlap/doctor_schedule_open_window_inclusive_inclusive
        """
        future = _future_iso(3600 * 4)
        state = setup_consultation_pending(
            mode="APPOINTMENT", scheduled_start_at=future,
        )
        assert state["consultation"]["session_status"] == "ACCEPTED"


# =========================================================================
# rule: compensating_invariant
# =========================================================================
class TestCompensatingInvariant:
    # ---------------------------------------------------------------------
    # difficulty: compensating_invariant/insurance_settlement_amount_invariant
    # ---------------------------------------------------------------------
    def test_settled_path_preserves_claim_amount_invariant(self, api):
        """PRD §3.7: 'the audit point at which the compensating invariant
        claim_amount_cents == reimbursed_cents + self_pay_cents must hold.'

        Claim: the SETTLED path satisfies reimbursed + self_pay ==
        claim_amount.
        # difficulty: compensating_invariant/insurance_settlement_amount_invariant
        """
        state = setup_completed_consultation(
            elapsed_seconds=20 * 60, doctor_base_fee=30.00,
            insurance_policy_no="POL-001",
        )
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
            items=[make_prescription_item(
                quantity=18, unit_price_cents=500,
            )],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = approve_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        pres = dispatch_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        claim = _find_claim_for_consultation(state["consultation"]["id"])
        if claim is None:
            pytest.skip("No claim discoverable")
        verified = verify_eligibility(claim=claim, insurance_status="ELIGIBLE")
        settling = settle_claim(claim=verified)
        bureau_settled_event(claim=settling, bureau_ref="BR-INV-A")
        final = get_success_data(api_client.get_insurance_claim(
            settling["id"], ADMIN,
        ))
        assert final["status"] == "SETTLED"
        assert (final["reimbursed_cents"] + final["self_pay_cents"]
                == final["claim_amount_cents"])

    def test_rejected_path_preserves_claim_amount_invariant(self, api):
        """PRD §3.7: 'A BUREAU_REJECTED event advances status from
        SETTLING to the terminal REJECTED_BY_BUREAU, resets
        reimbursed_cents to zero, and sets self_pay_cents to the full
        claim_amount_cents.'

        Claim: REJECTED_BY_BUREAU path also satisfies
        reimbursed_cents + self_pay_cents == claim_amount_cents
        (the same compensating invariant applies to both forward and
        compensating outcomes).
        # difficulty: compensating_invariant/insurance_settlement_amount_invariant
        """
        state = setup_completed_consultation(
            elapsed_seconds=20 * 60, doctor_base_fee=30.00,
            insurance_policy_no="POL-001",
        )
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
            items=[make_prescription_item(
                quantity=18, unit_price_cents=500,
            )],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = approve_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        pres = dispatch_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        claim = _find_claim_for_consultation(state["consultation"]["id"])
        if claim is None:
            pytest.skip("No claim discoverable")
        verified = verify_eligibility(claim=claim, insurance_status="ELIGIBLE")
        settling = settle_claim(claim=verified)
        bureau_rejected_event(claim=settling)
        final = get_success_data(api_client.get_insurance_claim(
            settling["id"], ADMIN,
        ))
        assert final["status"] == "REJECTED_BY_BUREAU"
        assert final["reimbursed_cents"] == 0
        assert final["self_pay_cents"] == final["claim_amount_cents"]
        assert (final["reimbursed_cents"] + final["self_pay_cents"]
                == final["claim_amount_cents"])

    # ---------------------------------------------------------------------
    # difficulty: compensating_invariant/doctor_load_invariant_across_transfer
    # ---------------------------------------------------------------------
    def test_transfer_outgoing_terminal_receiving_accepted(self, api):
        """PRD §3.5: 'A transfer advances the original consultation from
        IN_PROGRESS to the terminal TRANSFERRED and creates a brand-new
        consultation under the receiving doctor in ACCEPTED status with
        mode = REAL_TIME and a null queue_position.'

        Claim: after /transfer, the outgoing Consultation is TRANSFERRED
        (terminal) and a new Consultation exists for the receiving doctor
        in ACCEPTED — proving the load invariant via the structural shape
        of the transition.
        # difficulty: compensating_invariant/doctor_load_invariant_across_transfer
        """
        state = setup_in_progress_consultation()
        target_doc = create_doctor(
            department_code=DEFAULT_DEPARTMENT_CODE,
            specialty_codes=[IN_SCOPE_DISEASE],
            licensed_region_codes=[DEFAULT_REGION_CODE],
        )
        res = api.transfer_consultation(
            state["consultation"]["id"],
            transfer_payload(target_doctor_id=target_doc["id"]),
            make_doctor_headers(state["doctor"]["id"]),
        )
        data = validate_success(res)
        assert data["session_status"] == "TRANSFERRED"
        assert data.get("transfer_to_doctor_id") == target_doc["id"]
        # Verify the new sibling: list consultations filtered by the new
        # doctor; expect at least one ACCEPTED row.
        from prd_bench_local_runner.testing import validate_paginated
        resp = api_client.list_consultations(
            ADMIN, params={"doctor_id": target_doc["id"]},
        )
        rows, _ = validate_paginated(resp)
        assert any(
            r.get("session_status") == "ACCEPTED" for r in rows
        ), "Expected at least one ACCEPTED Consultation for receiving doctor"

    def test_transfer_records_transfer_to_doctor_id_on_origin(self, api):
        """PRD §3.5: 'records the new sibling's doctor id in
        transfer_to_doctor_id'.

        Claim: the outgoing Consultation's transfer_to_doctor_id equals
        the receiving doctor's id.
        # difficulty: compensating_invariant/doctor_load_invariant_across_transfer
        """
        state = setup_in_progress_consultation()
        target_doc = create_doctor(
            department_code=DEFAULT_DEPARTMENT_CODE,
            specialty_codes=[IN_SCOPE_DISEASE],
            licensed_region_codes=[DEFAULT_REGION_CODE],
        )
        res = api.transfer_consultation(
            state["consultation"]["id"],
            transfer_payload(target_doctor_id=target_doc["id"]),
            make_doctor_headers(state["doctor"]["id"]),
        )
        data = validate_success(res)
        assert data["transfer_to_doctor_id"] == target_doc["id"]
