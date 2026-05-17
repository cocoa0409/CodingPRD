"""Episode opening, derived fields, closing, expire-sweep.

PRD §3.4 (Opening, Closing, and Expiring an Episode).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    EPISODE_END_OFFSET_DAYS,
    RECERT_DUE_DAYS_BEFORE_END,
    TEST_USERS,
    advance_clock_past_end_date,
    advance_clock_past_expire_grace,
    advance_clock_to,
    anchor_clock,
    assert_episode,
    assert_pdgm_claim,
    close_episode,
    close_episode_at_end_date,
    create_and_lock_oasis,
    create_clinician,
    create_oasis,
    create_patient,
    date_offset,
    lock_oasis,
    open_episode,
    parse_date,
    re_get_claim,
    re_get_episode,
    re_get_visit,
    run_expire_sweep,
    schedule_visit,
    setup_open_episode,
    setup_open_episode_for_expire_sweep,
    setup_open_episode_with_one_scheduled_visit_for_expire_sweep,
    validate_error,
    validate_success,
)


# ===========================================================================
# Episode open — preconditions
# ===========================================================================
class TestEpisodeOpenPreconditions:

    def test_open_episode_with_draft_oasis_rejected(self, api):
        """PRD §3.4: "Opening fails with ERR_OASIS_NOT_LOCKED if the
        referenced OASIS is not in LOCKED status."

        Claim: posting an Episode with a DRAFT (not LOCKED) OASIS
        returns ERR_OASIS_NOT_LOCKED.
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

    def test_cannot_open_two_episodes_with_same_locked_oasis(self, api):
        """PRD §3.4: "The OASIS must not already have been used to open
        a prior episode; a violation is rejected with
        ERR_OASIS_ALREADY_USED."

        Claim: opening a second Episode from the same LOCKED OASIS is
        rejected. (Closing the first episode satisfies the "no other
        OPEN episode" rule so the only remaining failure mode is the
        OASIS reuse rule.)
        """
        anchor_clock()
        patient = create_patient()
        oasis = create_and_lock_oasis(patient=patient)
        e1 = open_episode(patient=patient, oasis=oasis)
        # Close the first episode so it no longer counts against the
        # one-OPEN-episode-per-patient rule.
        close_episode_at_end_date(e1)
        # Try to reopen with the SAME OASIS.
        res = api.create_episode(
            patient["id"],
            {"source_oasis_id": oasis["id"]},
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_OASIS_ALREADY_USED")

    def test_cannot_open_two_concurrent_open_episodes_on_same_patient(
        self, api,
    ):
        """PRD §3.4: "The patient must have no other episode whose
        status is OPEN; a violation is rejected with
        ERR_PATIENT_HAS_OPEN_EPISODE."

        Claim: attempting to open a second Episode on a patient who
        already has an OPEN Episode is rejected.
        """
        anchor_clock()
        patient = create_patient()
        o1 = create_and_lock_oasis(patient=patient)
        open_episode(patient=patient, oasis=o1)  # E1: OPEN
        # Second OASIS: PRD §3.3 requires START_OF_CARE,
        # RECERTIFICATION, or RESUMPTION_OF_CARE. Use
        # RESUMPTION_OF_CARE which only requires an OPEN episode (now
        # satisfied) to lock.
        o2 = create_and_lock_oasis(
            patient=patient,
            assessment_reason="RESUMPTION_OF_CARE",
        )
        res = api.create_episode(
            patient["id"],
            {"source_oasis_id": o2["id"]},
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_PATIENT_HAS_OPEN_EPISODE")


# ===========================================================================
# Episode open — derived field rules
# ===========================================================================
class TestEpisodeDerivedFields:

    def test_initial_episode_type_and_start_date_match_oasis(self, api):
        """PRD §3.4: "episode_type is derived from assessment_reason: a
        START_OF_CARE OASIS produces INITIAL". PRD §3.4: "start_date
        equals the source OASIS's assessment_date when episode_type is
        INITIAL or ROC".

        Claim: opening from a START_OF_CARE OASIS produces episode_type
        INITIAL and start_date equal to the OASIS's assessment_date.
        """
        anchor_clock()
        patient = create_patient()
        oasis = create_and_lock_oasis(
            patient=patient,
            assessment_reason="START_OF_CARE",
            assessment_date="2026-01-10",
        )
        episode = open_episode(patient=patient, oasis=oasis)
        assert_episode(episode)
        assert episode["episode_type"] == "INITIAL"
        assert episode["start_date"] == "2026-01-10"

    def test_end_date_equals_start_date_plus_59_days(self, api):
        """PRD §3.4: "end_date equals start_date plus 59 days — i.e.,
        the inclusive 60-day window from start_date through start_date
        + 59 days."

        Claim: end_date is exactly 59 days after start_date.
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        s = parse_date(episode["start_date"])
        e = parse_date(episode["end_date"])
        assert (e - s).days == EPISODE_END_OFFSET_DAYS

    def test_recert_due_date_is_end_date_minus_four(self, api):
        """PRD §3.4: "recert_due_date is end_date minus four days".

        Claim: recert_due_date = end_date - 4 days exactly.
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        rdd = parse_date(episode["recert_due_date"])
        end = parse_date(episode["end_date"])
        assert (end - rdd).days == RECERT_DUE_DAYS_BEFORE_END

    def test_initial_episode_is_early_timing(self, api):
        """PRD §3.4: "timing_category is EARLY for an INITIAL episode."

        Claim: an INITIAL episode is EARLY.
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        assert episode["episode_type"] == "INITIAL"
        assert episode["timing_category"] == "EARLY"

    def test_episode_open_creates_paired_pending_claim(self, api):
        """PRD §3.4: "The system also creates a paired PDGMClaim in
        PENDING status as a side effect of episode opening, and
        computes the claim's hipps_code, case_mix_weight, and
        provisional_payment in the same transaction."

        Claim: immediately after Episode open, GET /episodes/{id}/claim
        returns a PENDING claim with hipps_code, case_mix_weight, and
        provisional_payment populated.
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        claim = re_get_claim(episode["id"])
        assert_pdgm_claim(claim)
        assert claim["status"] == "PENDING"
        assert claim["episode_id"] == episode["id"]
        assert claim["provisional_payment"] > 0
        assert claim["case_mix_weight"] > 0
        # PRD §3.7: hipps_code length 5; positional encoding is asserted
        # in assert_pdgm_claim.
        assert len(claim["hipps_code"]) == 5


# ===========================================================================
# Episode close — preconditions and effects
# ===========================================================================
class TestEpisodeClose:

    def test_close_before_end_date_rejected(self, api):
        """PRD §3.4: "Closing requires the logical clock to have reached
        or passed the episode's end_date (current_date >= end_date)".

        Claim: closing an Episode while clock < end_date is rejected
        with a 4xx response.
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        # Clock is still at anchor / start_date, far before end_date.
        res = api.close_episode(
            episode["id"],
            TEST_USERS["billing_specialist_headers"],
        )
        assert res.status_code >= 400, (
            "PRD §3.4: close before end_date must be rejected; "
            f"got status {res.status_code}"
        )

    def test_close_with_scheduled_visit_rejected(self, api):
        """PRD §3.4: "requires that the episode have zero visits still
        in SCHEDULED. If a SCHEDULED visit remains, the close is blocked
        — the billing team must wait for it to either be completed or
        cancelled."

        Claim: closing an Episode while a SCHEDULED visit exists is
        rejected.
        """
        anchor_clock()
        _, _, episode, _, _ = (
            setup_open_episode_with_one_scheduled_visit_for_expire_sweep()
        )
        advance_clock_past_end_date(episode, extra_days=1)
        res = api.close_episode(
            episode["id"],
            TEST_USERS["billing_specialist_headers"],
        )
        assert res.status_code >= 400, (
            "PRD §3.4: close with a SCHEDULED visit must be blocked; "
            f"got status {res.status_code}"
        )

    def test_close_finalizes_paired_claim(self, api):
        """PRD §3.4: "A successful close re-runs the final-payment
        formula, the LUPA check, and the mileage aggregation on the
        paired claim — writing final_payment, lupa_applied, and
        total_mileage_reimbursement — and the paired PDGMClaim
        transitions from PENDING to FINALIZED atomically with the
        episode's transition from OPEN to CLOSED."

        Claim: after close, Episode is CLOSED and PDGMClaim is
        FINALIZED with final_payment, lupa_applied, and
        total_mileage_reimbursement populated.
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        closed = close_episode_at_end_date(episode)
        assert closed["status"] == "CLOSED"
        claim = re_get_claim(episode["id"])
        assert claim["status"] == "FINALIZED"
        assert "final_payment" in claim
        assert "lupa_applied" in claim
        assert "total_mileage_reimbursement" in claim


# ===========================================================================
# Episode expire-sweep cascade
# ===========================================================================
class TestExpireSweep:

    def test_sweep_marks_open_episode_as_expired_past_grace(self, api):
        """PRD §3.4: "an admin-driven sweep that scans OPEN episodes and,
        for each one whose end_date is more than seven days behind
        current_date (i.e., current_date > end_date + 7), transitions
        the episode to EXPIRED."

        Claim: after advancing the clock past end_date + 7, the sweep
        transitions the Episode OPEN → EXPIRED.
        """
        anchor_clock()
        _, _, episode = setup_open_episode_for_expire_sweep()
        advance_clock_past_expire_grace(episode, extra_days=1)
        run_expire_sweep()
        e_after = re_get_episode(episode["id"])
        assert e_after["status"] == "EXPIRED"

    def test_sweep_cancels_scheduled_visits_on_expired_episode(self, api):
        """PRD §3.4: "Every Visit on that episode whose status is
        SCHEDULED is cancelled in the same step, moving to CANCELLED."

        Claim: a SCHEDULED visit on an Episode is transitioned to
        CANCELLED when its parent Episode expires via sweep.
        """
        anchor_clock()
        _, _, episode, _, visit = (
            setup_open_episode_with_one_scheduled_visit_for_expire_sweep()
        )
        advance_clock_past_expire_grace(episode, extra_days=1)
        run_expire_sweep()
        v_after = re_get_visit(visit["id"])
        assert v_after["status"] == "CANCELLED"
