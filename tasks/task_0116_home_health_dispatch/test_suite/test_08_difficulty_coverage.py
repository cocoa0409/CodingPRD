"""Difficulty-design coverage — at least TWO dedicated tests per
SCAFFOLD_DIFFICULTY_DESIGN.yaml instance.

Each test is tagged with `# difficulty: <rule_id>/<instance.name>` so
the coverage audit can confirm every instance has at least TWO tests
(some tests are in this file; some are in the topic-organised files
test_01..test_07). The aim of this file is to top up coverage to
two-per-instance and add additional boundary tests for the more
load-bearing instances.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    BASE_30DAY_RATE,
    LUPA_PER_VISIT_RATE,
    LUPA_THRESHOLD,
    TEST_DEFAULTS,
    TEST_USERS,
    advance_clock_past_end_date,
    advance_clock_past_expire_grace,
    advance_clock_to,
    anchor_clock,
    assert_money_2dp,
    assert_pdgm_claim,
    cancel_visit,
    close_episode,
    close_episode_at_end_date,
    complete_visit,
    create_and_lock_oasis,
    create_clinician,
    create_oasis,
    create_patient,
    create_visit_payload,
    date_offset,
    lock_oasis,
    make_field_clinician_headers,
    open_episode,
    re_get_claim,
    re_get_episode,
    re_get_oasis,
    re_get_visit,
    record_mileage,
    run_expire_sweep,
    schedule_visit,
    setup_closed_episode,
    setup_episode_with_five_completed_visits,
    setup_episode_with_hha_cap,
    setup_episode_with_one_completed_visit,
    setup_episode_with_three_completed_visits,
    setup_episode_with_two_completed_sn_visits_for_mileage,
    setup_open_episode,
    setup_open_episode_for_expire_sweep,
    setup_open_episode_with_one_scheduled_visit_for_expire_sweep,
    suspend_clinician,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1: dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_pdgm_provisional_unchanged_after_close_in_lupa_path(
        self, api,
    ):
        """PRD §3.7: "The provisional payment is a forward-looking
        estimate computed at episode open."
        PRD §3.7: "No visit data is read in this computation — only the
        source OASIS fields, the episode's timing_category, and the
        patient's wage_index."
        PRD §3.7: "If the count is strictly less than the LUPA threshold
        of 5, the claim is paid per visit instead of by case mix."

        Claim: provisional_payment is written at OPEN, and on close the
        LUPA path writes a final_payment that differs from
        provisional_payment — but provisional_payment itself is NOT
        overwritten by the close. This is the dual-variant divergence:
        two values, two formulas.

        # difficulty: dual_variant_calc/pdgm_payment_provisional_vs_final_lupa_divergence
        """
        _, _, episode, _, _ = setup_episode_with_three_completed_visits()
        # Snapshot provisional before close.
        before = re_get_claim(episode["id"])
        prov_before = before["provisional_payment"]
        close_episode_at_end_date(episode)
        after = re_get_claim(episode["id"])
        # provisional_payment is preserved across the close.
        assert after["provisional_payment"] == pytest.approx(
            prov_before, abs=0.001,
        ), (
            "PRD §3.7: provisional_payment is computed at OPEN and is "
            "not recomputed at CLOSE; only final_payment is set on "
            "close."
        )
        assert after["lupa_applied"] is True
        # And — the load-bearing dual-variant claim — final_payment !=
        # provisional_payment under the LUPA path.
        assert after["final_payment"] != pytest.approx(
            prov_before, abs=0.001,
        )

    def test_mileage_per_row_amounts_are_rounded_at_insertion(self, api):
        """PRD §2.6: "Mileage uses a round-then-sum convention that is
        load-bearing: each MileageLog's reimbursement_amount is rounded
        to two decimals at insertion time, and the claim's
        total_mileage_reimbursement is the sum of those already-rounded
        values with no further rounding."

        Claim: a single insertion at miles=31.7 stores 21.94 (rounded
        half-up) on the MileageLog row, proving the round-at-insert
        side of the round-then-sum pairing.

        # difficulty: dual_variant_calc/mileage_round_then_sum_vs_sum_then_round_divergence
        """
        _, _, _, clinician, visit = setup_episode_with_one_completed_visit()
        ml = record_mileage(
            visit=visit, clinician=clinician, miles_driven=31.7,
        )
        # 30*0.70 + 1.7*0.55 = 21.00 + 0.935 = 21.935 → half-up at 2dp
        # = 21.94.
        assert ml["reimbursement_amount"] == pytest.approx(
            21.94, abs=0.001,
        )
        assert_money_2dp(ml["reimbursement_amount"])


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_pdgm_case_mix_four_axis_lookup_provisional(self, api):
        """PRD §3.7: "Take the base rate of 2,000.00 USD and multiply
        it by the patient's wage_index read off the patient row at the
        moment of episode open; round that wage-adjusted base half-up
        to four decimals."
        PRD §3.7: "Multiply the rounded wage-adjusted base by the
        looked-up case_mix_weight; round the product half-up to two
        decimals."

        PRD §3.7 case-mix table: EARLY + MMTA_OTHER + MEDIUM +
        COMMUNITY → case_mix_weight 1.0000.

        Claim: opening a fresh INITIAL Episode with OASIS (MMTA_OTHER /
        MEDIUM / COMMUNITY) produces case_mix_weight 1.0000 and a
        provisional_payment equal to round_half_up(BASE_30DAY_RATE *
        wage_index, 4) * 1.0000 rounded half-up to 2dp.

        # difficulty: combinatorial_formula/pdgm_case_mix_four_axis_lookup_with_evaluation_order
        """
        anchor_clock()
        patient, _, episode = setup_open_episode(
            clinical_grouping="MMTA_OTHER",
            functional_impairment_level="MEDIUM",
            admission_source="COMMUNITY",
        )
        claim = re_get_claim(episode["id"])
        assert claim["case_mix_weight"] == pytest.approx(
            1.0000, abs=0.0001,
        )
        # Recompute expected provisional from PRD formula.
        wage = patient["wage_index"]
        wage_adjusted = round(BASE_30DAY_RATE * wage + 1e-9, 4)
        expected = round(wage_adjusted * 1.0000 + 1e-9, 2)
        assert claim["provisional_payment"] == pytest.approx(
            expected, abs=0.01,
        )
        # HIPPS: timing(EARLY)='1' + clinical(MMTA_OTHER)='A' +
        # functional(MEDIUM)='G' + admission(COMMUNITY)='J' + '1'.
        assert claim["hipps_code"][0] == "1"  # EARLY
        assert claim["hipps_code"][1] == "A"  # MMTA_OTHER
        assert claim["hipps_code"][2] == "G"  # MEDIUM
        assert claim["hipps_code"][3] == "J"  # COMMUNITY
        assert claim["hipps_code"][4] == "1"  # PRD-pinned constant

    def test_pdgm_case_mix_weight_for_neuro_high_community(self, api):
        """PRD §3.7 case-mix table: EARLY + NEURO + HIGH + COMMUNITY →
        case_mix_weight 1.3500.

        Claim: opening with NEURO/HIGH/COMMUNITY produces
        case_mix_weight 1.3500 — a different (timing, grouping,
        functional, admission) axis combination from the MMTA_OTHER/
        MEDIUM/COMMUNITY test above.

        # difficulty: combinatorial_formula/pdgm_case_mix_four_axis_lookup_with_evaluation_order
        """
        anchor_clock()
        patient, _, episode = setup_open_episode(
            clinical_grouping="NEURO",
            functional_impairment_level="HIGH",
            admission_source="COMMUNITY",
        )
        claim = re_get_claim(episode["id"])
        assert claim["case_mix_weight"] == pytest.approx(
            1.3500, abs=0.0001,
        )
        # HIPPS letters for NEURO=B, HIGH=H.
        assert claim["hipps_code"][1] == "B"
        assert claim["hipps_code"][2] == "H"

    def test_mileage_tier_boundary_30_miles_exactly(self, api):
        """PRD §3.6: "Tier 1 is inclusive of mile 30; tier 2 covers the
        interval from mile 30 (exclusive) through mile 100 (inclusive)".

        Claim: exactly 30 miles falls entirely in tier 1 → 30 * 0.70 =
        21.00.

        # difficulty: combinatorial_formula/mileage_three_tier_breakpoint_formula
        """
        _, _, _, clinician, visit = setup_episode_with_one_completed_visit()
        ml = record_mileage(
            visit=visit, clinician=clinician, miles_driven=30,
        )
        assert ml["reimbursement_amount"] == pytest.approx(
            21.00, abs=0.001,
        )

    def test_lupa_final_payment_three_visit_sn_pt_ot_chronological(
        self, api,
    ):
        """PRD §3.7: "For each visit, take the per-visit LUPA rate for
        the visit's visit_type, multiply by the patient's wage_index
        read at the moment of close, and round half-up to two decimals
        — that is the visit's per-visit payment. Sum the already-rounded
        per-visit payments to produce final_payment (round-then-sum is
        required)".

        Claim: with one SN, one PT, one OT COMPLETED visit and the
        patient's wage_index = W, final_payment equals
            round_half_up(160*W, 2) + round_half_up(170*W, 2)
                + round_half_up(165*W, 2).

        # difficulty: combinatorial_formula/lupa_per_visit_round_then_sum
        """
        patient, _, episode, _, _ = (
            setup_episode_with_three_completed_visits()
        )
        wage = patient["wage_index"]
        # Re-fetch patient to ensure wage_index is the current value.
        from test_helpers import re_get_patient
        patient_at_close = re_get_patient(patient["id"])
        wage_at_close = patient_at_close["wage_index"]
        close_episode_at_end_date(episode)
        claim = re_get_claim(episode["id"])
        per_sn = round(LUPA_PER_VISIT_RATE["SN"] * wage_at_close + 1e-9, 2)
        per_pt = round(LUPA_PER_VISIT_RATE["PT"] * wage_at_close + 1e-9, 2)
        per_ot = round(LUPA_PER_VISIT_RATE["OT"] * wage_at_close + 1e-9, 2)
        expected = round(per_sn + per_pt + per_ot, 2)
        assert claim["final_payment"] == pytest.approx(
            expected, abs=0.01,
        )
        assert claim["lupa_applied"] is True


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_episode_branches_closed_vs_expired_distinct_outcomes(
        self, api,
    ):
        """PRD §3.4: "Closing requires the logical clock to have reached
        or passed the episode's end_date" → CLOSED; PRD §3.4: "for each
        one whose end_date is more than seven days behind current_date
        (i.e., current_date > end_date + 7), transitions the episode to
        EXPIRED."

        Claim: two Episodes opened identically branch into distinct
        terminal states — one CLOSED (via /close), one EXPIRED (via
        sweep). The EXPIRED branch additionally has final_payment ==
        provisional_payment and lupa_applied == false (PRD §3.7).

        # difficulty: non_linear_state_machine/episode_branching_close_vs_expire
        """
        # E1 — taken to CLOSED.
        _, _, e1 = setup_open_episode_for_expire_sweep()
        close_episode_at_end_date(e1)
        e1_after = re_get_episode(e1["id"])
        assert e1_after["status"] == "CLOSED"

        # E2 — separate patient, no visits, taken to EXPIRED via sweep.
        _, _, e2 = setup_open_episode_for_expire_sweep()
        advance_clock_past_expire_grace(e2, extra_days=1)
        run_expire_sweep()
        e2_after = re_get_episode(e2["id"])
        assert e2_after["status"] == "EXPIRED"
        claim2 = re_get_claim(e2["id"])
        assert claim2["status"] == "FINALIZED"
        # PRD §3.7 (expire branch): "final_payment is set equal to
        # provisional_payment, lupa_applied is set to false".
        assert claim2["final_payment"] == pytest.approx(
            claim2["provisional_payment"], abs=0.01,
        )
        assert claim2["lupa_applied"] is False

    def test_expired_branch_writes_provisional_into_final(self, api):
        """PRD §3.7: "When the close is instead triggered indirectly by
        the expire-sweep — i.e., the episode transitions from OPEN to
        EXPIRED rather than CLOSED — the final payment is not
        recomputed from visits. Instead, final_payment is set equal to
        provisional_payment, lupa_applied is set to false".

        Claim: the EXPIRED branch sets final_payment :=
        provisional_payment exactly (no recomputation).

        # difficulty: non_linear_state_machine/episode_branching_close_vs_expire
        """
        _, _, episode = setup_open_episode_for_expire_sweep()
        claim_open = re_get_claim(episode["id"])
        prov = claim_open["provisional_payment"]
        advance_clock_past_expire_grace(episode, extra_days=1)
        run_expire_sweep()
        claim_after = re_get_claim(episode["id"])
        assert claim_after["final_payment"] == pytest.approx(
            prov, abs=0.01,
        )

    def test_lock_one_oasis_supersedes_sibling_draft_branching(
        self, api,
    ):
        """PRD §3.3: "Locking carries a side effect: any other OASIS on
        the same patient still in DRAFT is moved to SUPERSEDED in the
        same atomic step, refreshing each superseded row's updated_at
        and incrementing its version."

        Claim: with one Patient and two DRAFT OASIS rows, locking one
        leaves it LOCKED while moving the sibling to SUPERSEDED — two
        non-linear successor states on different rows from a single
        request.

        # difficulty: non_linear_state_machine/oasis_branching_lock_supersede
        """
        anchor_clock()
        patient = create_patient()
        o1 = create_oasis(patient=patient)
        o2 = create_oasis(patient=patient)
        lock_oasis(patient=patient, oasis=o1)
        o1_after = re_get_oasis(patient["id"], o1["id"])
        o2_after = re_get_oasis(patient["id"], o2["id"])
        assert o1_after["status"] == "LOCKED"
        assert o2_after["status"] == "SUPERSEDED"

    def test_supersede_bumps_version_on_sibling(self, api):
        """PRD §3.3: "refreshing each superseded row's updated_at and
        incrementing its version."

        Claim: the SUPERSEDED sibling has version > 1 (it was version 1
        on creation, then incremented during the supersede side
        effect).

        # difficulty: non_linear_state_machine/oasis_branching_lock_supersede
        """
        anchor_clock()
        patient = create_patient()
        o1 = create_oasis(patient=patient)
        o2 = create_oasis(patient=patient)
        v_before = o2["version"]
        lock_oasis(patient=patient, oasis=o1)
        o2_after = re_get_oasis(patient["id"], o2["id"])
        assert o2_after["version"] > v_before, (
            f"expected version > {v_before}, got {o2_after['version']}"
        )


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_sweep_expire_to_visit_cancel_to_claim_finalize_chain(
        self, api,
    ):
        """PRD §3.4: "The expire-sweep cascade is three layers deep on a
        single episode: 1. The episode itself moves from OPEN to
        EXPIRED. 2. Every Visit on that episode whose status is
        SCHEDULED is cancelled in the same step, moving to CANCELLED.
        3. The paired PDGMClaim is finalized: final_payment is set
        equal to provisional_payment, lupa_applied is set to false,
        total_mileage_reimbursement is recomputed from whatever visits
        have already reached COMPLETED on this episode, and the claim
        transitions from PENDING to FINALIZED."

        Claim: a single POST /_sweep/expire-episodes call cascades all
        three hops: Episode OPEN→EXPIRED, sibling Visit
        SCHEDULED→CANCELLED, PDGMClaim PENDING→FINALIZED with
        final_payment==provisional_payment.

        # difficulty: transitive_cascade/sweep_expire_to_visit_cancel_to_claim_finalize_chain
        """
        _, _, episode, _, visit = (
            setup_open_episode_with_one_scheduled_visit_for_expire_sweep()
        )
        claim_before = re_get_claim(episode["id"])
        prov = claim_before["provisional_payment"]
        advance_clock_past_expire_grace(episode, extra_days=2)
        run_expire_sweep()
        # Hop 1.
        e_after = re_get_episode(episode["id"])
        assert e_after["status"] == "EXPIRED"
        # Hop 2.
        v_after = re_get_visit(visit["id"])
        assert v_after["status"] == "CANCELLED"
        # Hop 3.
        claim_after = re_get_claim(episode["id"])
        assert claim_after["status"] == "FINALIZED"
        assert claim_after["final_payment"] == pytest.approx(
            prov, abs=0.01,
        )
        assert claim_after["lupa_applied"] is False

    def test_oasis_lock_to_episode_open_to_claim_create_chain(self, api):
        """PRD §3.3: "Locking it — promoting it to LOCKED — is the
        prerequisite for opening an episode". PRD §3.4: "The system
        also creates a paired PDGMClaim in PENDING status as a side
        effect of episode opening, and computes the claim's hipps_code,
        case_mix_weight, and provisional_payment in the same
        transaction."

        Claim: locking the OASIS (hop 1) makes it eligible to open an
        Episode; opening the Episode (hop 2 — caused by hop 1) creates
        a paired PDGMClaim with hipps_code, case_mix_weight, and
        provisional_payment populated.

        Using WOUND/HIGH/COMMUNITY (case_mix_weight 1.4000 per PRD
        §3.7 case-mix table).

        # difficulty: transitive_cascade/oasis_lock_to_episode_open_to_claim_create_chain
        """
        anchor_clock()
        patient = create_patient()
        oasis = create_oasis(
            patient=patient,
            clinical_grouping="WOUND",
            functional_impairment_level="HIGH",
            admission_source="COMMUNITY",
        )
        # Hop 1.
        locked = lock_oasis(patient=patient, oasis=oasis)
        assert locked["status"] == "LOCKED"
        # Hop 2.
        episode = open_episode(patient=patient, oasis=locked)
        assert episode["status"] == "OPEN"
        assert episode["episode_type"] == "INITIAL"
        assert episode["timing_category"] == "EARLY"
        claim = re_get_claim(episode["id"])
        assert claim["status"] == "PENDING"
        assert claim["case_mix_weight"] == pytest.approx(
            1.4000, abs=0.0001,
        )
        wage_adjusted = round(
            BASE_30DAY_RATE * patient["wage_index"] + 1e-9, 4,
        )
        expected_prov = round(wage_adjusted * 1.4000 + 1e-9, 2)
        assert claim["provisional_payment"] == pytest.approx(
            expected_prov, abs=0.01,
        )


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_state_vs_safety_state_error_wins(self, api):
        """PRD §2.9: "Every endpoint runs a fixed validation pipeline in
        a strict priority order; the first failing check is the
        rejection reason, and no later check is evaluated. … 4. State
        preconditions on the target resource (e.g., ERR_OASIS_NOT_DRAFT,
        ERR_OASIS_NOT_LOCKED, ERR_EPISODE_NOT_OPEN,
        ERR_VISIT_NOT_SCHEDULED). 5. Business safety/compliance:
        license expiration (ERR_CLINICIAN_LICENSE_EXPIRED) …".

        Claim: when both ERR_EPISODE_NOT_OPEN and
        ERR_CLINICIAN_LICENSE_EXPIRED would fire on the same request,
        the state check at priority 4 wins (returns
        ERR_EPISODE_NOT_OPEN, NOT ERR_CLINICIAN_LICENSE_EXPIRED).

        # difficulty: priority_pair_validation_conflict/state_vs_safety_visit_schedule_on_closed_episode_with_expired_license
        """
        anchor_clock()
        _, _, closed = setup_closed_episode()
        # Build a clinician whose license expired before any plausible
        # visit_date — this guarantees BOTH preconditions fail.
        clinician = create_clinician(
            discipline="SN", license_expiration_date="2025-01-01",
        )
        res = api.create_visit(
            closed["id"],
            create_visit_payload(
                clinician_id=clinician["id"], visit_type="SN",
                visit_date=closed["start_date"],
                start_minute=480, end_minute=540,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_EPISODE_NOT_OPEN")

    def test_state_vs_safety_priority_pair_check_double(self, api):
        """PRD §2.9: state checks (priority class 4) precede business
        safety/compliance (priority class 5).

        Claim: a second realization of the state-vs-safety pair —
        closed Episode + SUSPENDED clinician + discipline mismatch —
        still surfaces ERR_EPISODE_NOT_OPEN over any business safety
        error.

        # difficulty: priority_pair_validation_conflict/state_vs_safety_visit_schedule_on_closed_episode_with_expired_license
        """
        anchor_clock()
        _, _, closed = setup_closed_episode()
        clinician = create_clinician(discipline="SN")
        suspend_clinician(clinician)  # also fails safety check
        res = api.create_visit(
            closed["id"],
            create_visit_payload(
                clinician_id=clinician["id"],
                visit_type="PT",  # ALSO discipline mismatch
                visit_date=closed["start_date"],
                start_minute=480, end_minute=540,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_EPISODE_NOT_OPEN")

    def test_temporal_vs_fiscal_temporal_error_wins(self, api):
        """PRD §2.9: "6. Business temporal/referential: visit date
        inside the episode window (ERR_VISIT_OUTSIDE_EPISODE), visit
        minute bounds (ERR_VISIT_TIME_INVALID), clinician double-booking
        (ERR_CLINICIAN_DOUBLE_BOOKED), OASIS-already-used /
        open-episode-exists (ERR_OASIS_ALREADY_USED)."
        PRD §2.9: "7. Business fiscal/quota: HHA hours cap
        (ERR_HHA_HOURS_EXCEEDED)."
        PRD §2.9: "Every endpoint runs a fixed validation pipeline in a
        strict priority order; the first failing check is the rejection
        reason, and no later check is evaluated."

        Claim: when both ERR_VISIT_OUTSIDE_EPISODE and
        ERR_HHA_HOURS_EXCEEDED would fire on the same request, the
        temporal check at priority 6 wins (returns
        ERR_VISIT_OUTSIDE_EPISODE, NOT ERR_HHA_HOURS_EXCEEDED).

        # difficulty: priority_pair_validation_conflict/temporal_vs_fiscal_hha_visit_outside_window_and_over_cap
        """
        # Episode with hha_companion_hours_ordered = 1.0 → small cap.
        _, _, episode, hha = setup_episode_with_hha_cap(
            hha_companion_hours_ordered=1.0,
        )
        # Schedule an HHA visit that consumes the entire 1.0-hour cap
        # already. visit_date inside episode window.
        v1 = schedule_visit(
            episode=episode, clinician=hha, visit_type="HHA",
            visit_date=date_offset(episode["start_date"], days=3),
            start_minute=540, end_minute=600,  # 60 min = 1.0 h
        )
        # New visit OUTSIDE window AND would push HHA hours over cap.
        outside_date = date_offset(episode["end_date"], days=30)
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=hha["id"], visit_type="HHA",
                visit_date=outside_date,
                start_minute=540, end_minute=660,  # 120 min = 2.0 h
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_VISIT_OUTSIDE_EPISODE")

    def test_temporal_vs_fiscal_temporal_wins_with_only_2_hour_visit(
        self, api,
    ):
        """PRD §2.9: temporal checks precede fiscal/quota checks.

        Claim: a different concrete instance of the temporal-vs-fiscal
        pair — fresh Episode with cap 1.0, one already-scheduled 1.0-
        hour HHA visit, and a new request that is both outside the
        window and would exceed the cap — still returns the temporal
        error.

        # difficulty: priority_pair_validation_conflict/temporal_vs_fiscal_hha_visit_outside_window_and_over_cap
        """
        _, _, episode, hha = setup_episode_with_hha_cap(
            hha_companion_hours_ordered=1.0,
        )
        # Consume the entire cap.
        schedule_visit(
            episode=episode, clinician=hha, visit_type="HHA",
            visit_date=date_offset(episode["start_date"], days=3),
            start_minute=540, end_minute=600,  # 1.0 hour
        )
        # Visit BEFORE start_date AND over cap.
        before = date_offset(episode["start_date"], days=-30)
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=hha["id"], visit_type="HHA",
                visit_date=before,
                start_minute=540, end_minute=600,  # 1.0 hour (cap would
                                                   # be 2.0 total)
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_VISIT_OUTSIDE_EPISODE")


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
class TestBoundaryPrecision:

    def test_lupa_threshold_at_exactly_5_does_not_apply(self, api):
        """PRD §3.7: "the LUPA visit-count threshold is 5 (strictly: a
        completed-visit count of fewer than 5 triggers LUPA)."

        Claim: exactly 5 COMPLETED visits → lupa_applied == false (5 is
        NOT strictly less than 5).

        # difficulty: boundary_precision_check/lupa_threshold_strict_less_than_boundary
        """
        _, _, episode, _, _ = setup_episode_with_five_completed_visits()
        close_episode_at_end_date(episode)
        claim = re_get_claim(episode["id"])
        assert claim["lupa_applied"] is False

    def test_lupa_threshold_at_4_does_apply(self, api):
        """PRD §3.7: "If the count is strictly less than the LUPA
        threshold of 5, the claim is paid per visit instead of by case
        mix. … set lupa_applied to true."

        Claim: 4 COMPLETED visits (4 < 5) → lupa_applied == true.

        # difficulty: boundary_precision_check/lupa_threshold_strict_less_than_boundary
        """
        # Schedule + complete exactly 4 visits.
        anchor_clock()
        clinicians = [create_clinician(discipline="SN") for _ in range(4)]
        _, _, episode = setup_open_episode(
            clinical_grouping="NEURO",
            functional_impairment_level="MEDIUM",
            admission_source="COMMUNITY",
        )
        visits = []
        for i, c in enumerate(clinicians):
            v = schedule_visit(
                episode=episode, clinician=c, visit_type="SN",
                visit_date=date_offset(episode["start_date"], days=4 + i),
                start_minute=480, end_minute=540,
            )
            visits.append(v)
        advance_clock_to(visits[-1]["visit_date"])
        for v, c in zip(visits, clinicians):
            complete_visit(visit=v, clinician=c)
        close_episode_at_end_date(episode)
        claim = re_get_claim(episode["id"])
        assert claim["lupa_applied"] is True

    def test_mileage_at_minimum_positive_value(self, api):
        """PRD §3.6: "it must be strictly greater than zero".

        Claim: miles_driven just above zero (0.5) is accepted; a single
        record at exactly that value clears the boundary and stores a
        positive reimbursement_amount.

        # difficulty: boundary_precision_check/mileage_zero_miles_rejection_boundary
        """
        _, _, _, clinician, visit = setup_episode_with_one_completed_visit()
        ml = record_mileage(
            visit=visit, clinician=clinician, miles_driven=0.5,
        )
        # 0.5 * 0.70 = 0.35 → already 2dp.
        assert ml["reimbursement_amount"] == pytest.approx(
            0.35, abs=0.001,
        )


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_episode_open_requires_oasis_locked_draft_rejected(self, api):
        """PRD §3.4: "Opening fails with ERR_OASIS_NOT_LOCKED if the
        referenced OASIS is not in LOCKED status."

        Claim: opening an Episode against a DRAFT (not LOCKED) OASIS is
        rejected with ERR_OASIS_NOT_LOCKED — Episode's null→OPEN
        precondition inspects a different entity's status (OASIS).

        # difficulty: cross_entity_state_dependency/episode_open_requires_oasis_locked
        """
        anchor_clock()
        patient = create_patient()
        oasis = create_oasis(patient=patient)  # DRAFT
        res = api.create_episode(
            patient["id"],
            {"source_oasis_id": oasis["id"]},
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_OASIS_NOT_LOCKED")

    def test_episode_open_requires_oasis_locked_superseded_rejected(
        self, api,
    ):
        """PRD §3.4: "Opening fails with ERR_OASIS_NOT_LOCKED if the
        referenced OASIS is not in LOCKED status."

        Claim: opening an Episode against a SUPERSEDED OASIS is also
        rejected (status != LOCKED).

        # difficulty: cross_entity_state_dependency/episode_open_requires_oasis_locked
        """
        anchor_clock()
        patient = create_patient()
        # Two DRAFT OASIS; lock the second so the first cascades to
        # SUPERSEDED.
        o1 = create_oasis(patient=patient)
        o2 = create_oasis(patient=patient)
        lock_oasis(patient=patient, oasis=o2)
        o1_after = re_get_oasis(patient["id"], o1["id"])
        assert o1_after["status"] == "SUPERSEDED"
        res = api.create_episode(
            patient["id"],
            {"source_oasis_id": o1["id"]},
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_OASIS_NOT_LOCKED")

    def test_visit_schedule_requires_clinician_available(self, api):
        """PRD §3.5: "The clinician must be AVAILABLE; a SUSPENDED
        clinician is rejected with ERR_CLINICIAN_NOT_AVAILABLE."

        Claim: scheduling a Visit against a SUSPENDED Clinician is
        rejected — Visit's null→SCHEDULED precondition inspects a
        different entity's status (Clinician.status).

        # difficulty: cross_entity_state_dependency/visit_complete_requires_clinician_available_at_schedule_time
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        clinician = create_clinician(discipline="SN")
        suspend_clinician(clinician)
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=clinician["id"], visit_type="SN",
                visit_date=episode["start_date"],
                start_minute=480, end_minute=540,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_CLINICIAN_NOT_AVAILABLE")

    def test_visit_schedule_succeeds_when_clinician_available(self, api):
        """PRD §3.5: "The clinician must be AVAILABLE".

        Claim: scheduling against an AVAILABLE (newly created)
        Clinician succeeds — the cross-entity precondition is
        satisfied. Complement to the SUSPENDED-rejected test above.

        # difficulty: cross_entity_state_dependency/visit_complete_requires_clinician_available_at_schedule_time
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        clinician = create_clinician(discipline="SN")
        assert clinician["status"] == "AVAILABLE"
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=clinician["id"], visit_type="SN",
                visit_date=episode["start_date"],
                start_minute=480, end_minute=540,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "SCHEDULED"


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_clinician_overlapping_visits_rejected(self, api):
        """PRD §3.5: "The clinician must not already be booked into an
        overlapping window. The system compares the requested
        [start_minute, end_minute) against every other non-CANCELLED
        visit on the same clinician on the same visit_date; if any
        other booking overlaps, the request is rejected with
        ERR_CLINICIAN_DOUBLE_BOOKED."

        Claim: scheduling two visits for the same clinician with
        overlapping minute windows on the same visit_date returns
        ERR_CLINICIAN_DOUBLE_BOOKED.

        # difficulty: resource_temporal_overlap/clinician_visit_half_open_minute_overlap
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        c = create_clinician(discipline="SN")
        # First booking 480..540.
        schedule_visit(
            episode=episode, clinician=c, visit_type="SN",
            visit_date=date_offset(episode["start_date"], days=4),
            start_minute=480, end_minute=540,
        )
        # Overlapping booking 530..590 on the same date.
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=c["id"], visit_type="SN",
                visit_date=date_offset(episode["start_date"], days=4),
                start_minute=530, end_minute=590,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_CLINICIAN_DOUBLE_BOOKED")

    def test_clinician_touching_visits_allowed(self, api):
        """PRD §3.5: "The intervals are half-open, so two visits that
        touch exactly at the same minute (e.g., one ending at minute
        600 and another starting at minute 600) are permitted."

        Claim: scheduling [480, 540) then [540, 600) on the same
        clinician on the same date is permitted.

        # difficulty: resource_temporal_overlap/clinician_visit_half_open_minute_overlap
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        c = create_clinician(discipline="SN")
        v_date = date_offset(episode["start_date"], days=4)
        schedule_visit(
            episode=episode, clinician=c, visit_type="SN",
            visit_date=v_date,
            start_minute=480, end_minute=540,
        )
        # Touching: starts at 540, ends at 600. Must succeed.
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=c["id"], visit_type="SN",
                visit_date=v_date,
                start_minute=540, end_minute=600,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "SCHEDULED"

    def test_hha_cumulative_hours_cap_rejects_second_visit_over_cap(
        self, api,
    ):
        """PRD §3.5: "For HHA visits a final fiscal check runs: the
        cumulative hha_companion_hours_consumed already on the episode,
        plus the proposed visit's hha_hours, must not exceed the
        episode's source OASIS hha_companion_hours_ordered. A breach is
        rejected with ERR_HHA_HOURS_EXCEEDED."

        Claim: with cap=3.0 ordered and a SCHEDULED HHA visit consuming
        2.0 hours already, a second HHA visit on a DIFFERENT date that
        would add another 2.0 hours (total 4.0) is rejected — even
        though the two visits do not collide on time.

        # difficulty: resource_temporal_overlap/hha_companion_hours_aggregate_cap_overlap
        """
        _, _, episode, hha = setup_episode_with_hha_cap(
            hha_companion_hours_ordered=3.0,
        )
        # First HHA visit: 2 hours on day 4.
        schedule_visit(
            episode=episode, clinician=hha, visit_type="HHA",
            visit_date=date_offset(episode["start_date"], days=4),
            start_minute=480, end_minute=600,  # 120 min = 2.0 h
        )
        # Second HHA visit on a different date: 2 more hours → cap.
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=hha["id"], visit_type="HHA",
                visit_date=date_offset(episode["start_date"], days=9),
                start_minute=540, end_minute=660,  # 120 min = 2.0 h
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_HHA_HOURS_EXCEEDED")

    def test_hha_cumulative_hours_cap_allows_visits_within_cap(self, api):
        """PRD §3.5: "the cumulative hha_companion_hours_consumed
        already on the episode, plus the proposed visit's hha_hours,
        must not exceed the episode's source OASIS
        hha_companion_hours_ordered."

        Claim: with cap=3.0, two HHA visits at 1.0 hour each (total
        2.0 ≤ 3.0) are both accepted.

        # difficulty: resource_temporal_overlap/hha_companion_hours_aggregate_cap_overlap
        """
        _, _, episode, hha = setup_episode_with_hha_cap(
            hha_companion_hours_ordered=3.0,
        )
        v1 = schedule_visit(
            episode=episode, clinician=hha, visit_type="HHA",
            visit_date=date_offset(episode["start_date"], days=4),
            start_minute=480, end_minute=540,  # 60 min = 1.0 h
        )
        v2 = schedule_visit(
            episode=episode, clinician=hha, visit_type="HHA",
            visit_date=date_offset(episode["start_date"], days=9),
            start_minute=480, end_minute=540,  # 60 min = 1.0 h
        )
        assert v1["status"] == "SCHEDULED"
        assert v2["status"] == "SCHEDULED"


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_hha_hours_consumed_zero_after_schedule_then_cancel(
        self, api,
    ):
        """PRD §3.5: "The cumulative figure is the sum of hha_hours
        across visits on the episode whose visit_type is HHA and whose
        status is either SCHEDULED or COMPLETED — SCHEDULED aide hours
        count against the cap even before the visit happens, and
        CANCELLED aide visits do not (cancelling an aide visit frees
        its hours back up)."

        Claim: scheduling an HHA visit that exactly consumes the cap,
        then cancelling it, leaves the cap free again — a subsequent
        HHA visit of the same size succeeds.

        # difficulty: compensating_invariant/hha_hours_consumed_invariant_under_schedule_then_cancel
        """
        _, _, episode, hha = setup_episode_with_hha_cap(
            hha_companion_hours_ordered=2.0,
        )
        # First HHA visit: 2 hours — exactly hits the cap.
        v1 = schedule_visit(
            episode=episode, clinician=hha, visit_type="HHA",
            visit_date=date_offset(episode["start_date"], days=4),
            start_minute=480, end_minute=600,  # 120 min = 2.0 h
        )
        # Cancel it.
        cancel_visit(visit=v1)
        # A subsequent identical HHA visit MUST succeed (cap was
        # freed).
        v2 = schedule_visit(
            episode=episode, clinician=hha, visit_type="HHA",
            visit_date=date_offset(episode["start_date"], days=9),
            start_minute=480, end_minute=600,  # 120 min = 2.0 h
        )
        assert v2["status"] == "SCHEDULED"

    def test_scheduled_hha_hours_block_new_schedule_until_cancelled(
        self, api,
    ):
        """PRD §3.5: "SCHEDULED aide hours count against the cap even
        before the visit happens".

        Claim: with cap=2.0 and one SCHEDULED 2.0-hour HHA visit, a new
        HHA visit is rejected with ERR_HHA_HOURS_EXCEEDED (proving the
        SCHEDULED hours are counted); but after cancellation, the
        retry succeeds.

        # difficulty: compensating_invariant/hha_hours_consumed_invariant_under_schedule_then_cancel
        """
        _, _, episode, hha = setup_episode_with_hha_cap(
            hha_companion_hours_ordered=2.0,
        )
        v1 = schedule_visit(
            episode=episode, clinician=hha, visit_type="HHA",
            visit_date=date_offset(episode["start_date"], days=4),
            start_minute=480, end_minute=600,  # 2.0 h
        )
        # Second HHA visit while v1 is SCHEDULED → blocked.
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=hha["id"], visit_type="HHA",
                visit_date=date_offset(episode["start_date"], days=9),
                start_minute=480, end_minute=540,  # 1.0 h
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_HHA_HOURS_EXCEEDED")
        # Cancel v1 → cap free.
        cancel_visit(visit=v1)
        retry = schedule_visit(
            episode=episode, clinician=hha, visit_type="HHA",
            visit_date=date_offset(episode["start_date"], days=9),
            start_minute=480, end_minute=540,  # 1.0 h
        )
        assert retry["status"] == "SCHEDULED"

    def test_expired_episode_preserves_provisional_payment_amount(
        self, api,
    ):
        """PRD §3.7: "When the close is instead triggered indirectly by
        the expire-sweep — i.e., the episode transitions from OPEN to
        EXPIRED rather than CLOSED — the final payment is not
        recomputed from visits. Instead, final_payment is set equal to
        provisional_payment, lupa_applied is set to false, and
        total_mileage_reimbursement is recomputed only from already-
        COMPLETED visits' mileage rows".

        Claim: provisional_payment at OPEN equals final_payment at
        EXPIRED (the dollar quantity is the conserved invariant under
        the expire-sweep "compensator" path).

        # difficulty: compensating_invariant/pdgm_payment_invariant_under_episode_expire_uses_provisional
        """
        _, _, episode = setup_open_episode_for_expire_sweep()
        before = re_get_claim(episode["id"])
        prov_before = before["provisional_payment"]
        advance_clock_past_expire_grace(episode, extra_days=1)
        run_expire_sweep()
        after = re_get_claim(episode["id"])
        assert after["final_payment"] == pytest.approx(
            prov_before, abs=0.01,
        )
        assert after["provisional_payment"] == pytest.approx(
            prov_before, abs=0.01,
        ), (
            "provisional_payment must not change after expire-sweep"
        )
        assert after["lupa_applied"] is False

    def test_expired_branch_finalizes_claim_to_finalized_state(
        self, api,
    ):
        """PRD §3.7: "The paired claim then transitions from PENDING to
        FINALIZED, mirroring the CLOSED path's terminal claim state."

        Claim: after expire-sweep, the claim's status moves PENDING →
        FINALIZED (terminal). Complement to the dollar-invariant test
        above.

        # difficulty: compensating_invariant/pdgm_payment_invariant_under_episode_expire_uses_provisional
        """
        _, _, episode = setup_open_episode_for_expire_sweep()
        advance_clock_past_expire_grace(episode, extra_days=1)
        run_expire_sweep()
        claim = re_get_claim(episode["id"])
        assert claim["status"] == "FINALIZED"


# ===========================================================================
# Top-up: extra tests for instances that need a second tagged test.
# ===========================================================================
class TestTopUpCoverage:

    def test_lupa_per_visit_round_then_sum_summation_invariant(self, api):
        """PRD §3.7 (LUPA path): "Sum the already-rounded per-visit
        payments to produce final_payment (round-then-sum is required)".

        Claim: with 3 COMPLETED visits whose per-visit LUPA rates are
        SN=160, PT=170, OT=165 multiplied by the patient's wage_index
        and rounded half-up at 2dp, final_payment equals the SUM of
        those three rounded values — proving the round-then-sum
        ordering at the summation step. (The single-visit round-at-
        insertion test is the existing #5 coverage; this test focuses
        on summation correctness.)

        # difficulty: combinatorial_formula/lupa_per_visit_round_then_sum
        """
        patient, _, episode, _, visits = (
            setup_episode_with_three_completed_visits()
        )
        # Re-fetch patient to capture wage_index at close-time as PRD
        # §3.7 specifies "multiply by the patient's wage_index read at
        # the moment of close".
        from test_helpers import re_get_patient
        patient_at_close = re_get_patient(patient["id"])
        wage = patient_at_close["wage_index"]
        close_episode_at_end_date(episode)
        claim = re_get_claim(episode["id"])
        # Visits ordered chronologically: SN (day 4), PT (day 5),
        # OT (day 6).
        per_sn = round(LUPA_PER_VISIT_RATE["SN"] * wage + 1e-9, 2)
        per_pt = round(LUPA_PER_VISIT_RATE["PT"] * wage + 1e-9, 2)
        per_ot = round(LUPA_PER_VISIT_RATE["OT"] * wage + 1e-9, 2)
        expected_sum = round(per_sn + per_pt + per_ot, 2)
        assert claim["final_payment"] == pytest.approx(
            expected_sum, abs=0.01,
        ), (
            "final_payment must equal round(sn) + round(pt) + round(ot) "
            f"= {per_sn} + {per_pt} + {per_ot} = {expected_sum}; "
            f"got {claim['final_payment']}"
        )

    def test_sweep_expire_cascade_finalizes_claim_with_provisional(
        self, api,
    ):
        """PRD §3.4: "The paired PDGMClaim is finalized: final_payment
        is set equal to provisional_payment, lupa_applied is set to
        false, total_mileage_reimbursement is recomputed from whatever
        visits have already reached COMPLETED on this episode, and the
        claim transitions from PENDING to FINALIZED."

        Claim: a sweep cascade (with no completed visits, so no
        mileage) yields a FINALIZED claim whose final_payment ==
        provisional_payment and lupa_applied is false — proving the
        third hop of the depth-3 cascade. Complements the existing
        end-to-end three-hop test by isolating the claim-side
        invariants under the cascade.

        # difficulty: transitive_cascade/sweep_expire_to_visit_cancel_to_claim_finalize_chain
        """
        _, _, episode, _, _ = (
            setup_open_episode_with_one_scheduled_visit_for_expire_sweep()
        )
        before = re_get_claim(episode["id"])
        prov = before["provisional_payment"]
        advance_clock_past_expire_grace(episode, extra_days=1)
        run_expire_sweep()
        after = re_get_claim(episode["id"])
        assert after["status"] == "FINALIZED"
        assert after["final_payment"] == pytest.approx(prov, abs=0.01)
        assert after["lupa_applied"] is False
        # No completed visits → no mileage to aggregate.
        assert after["total_mileage_reimbursement"] == pytest.approx(
            0.0, abs=0.001,
        )

    def test_oasis_lock_then_open_writes_hipps_code_neuro_high(self, api):
        """PRD §3.3: "Locking it — promoting it to LOCKED — is the
        prerequisite for opening an episode". PRD §3.7 (HIPPS): "Position
        2 encodes the OASIS clinical_grouping as a single letter: A for
        MMTA_OTHER, B for NEURO". PRD §3.7: "Position 3 encodes the
        OASIS functional_impairment_level: F for LOW, G for MEDIUM,
        and H for HIGH."

        Claim: the lock → open chain produces a paired PDGMClaim whose
        hipps_code reflects the source OASIS's clinical_grouping and
        functional level. Using NEURO/HIGH/COMMUNITY (case_mix_weight
        1.3500) — different inputs from the WOUND/HIGH test above —
        the second hop should land hipps_code at "1BHJ1" with
        case_mix_weight 1.3500.

        # difficulty: transitive_cascade/oasis_lock_to_episode_open_to_claim_create_chain
        """
        anchor_clock()
        patient = create_patient()
        oasis = create_oasis(
            patient=patient,
            clinical_grouping="NEURO",
            functional_impairment_level="HIGH",
            admission_source="COMMUNITY",
        )
        locked = lock_oasis(patient=patient, oasis=oasis)
        assert locked["status"] == "LOCKED"
        episode = open_episode(patient=patient, oasis=locked)
        claim = re_get_claim(episode["id"])
        assert claim["status"] == "PENDING"
        assert claim["hipps_code"] == "1BHJ1"
        assert claim["case_mix_weight"] == pytest.approx(
            1.3500, abs=0.0001,
        )
