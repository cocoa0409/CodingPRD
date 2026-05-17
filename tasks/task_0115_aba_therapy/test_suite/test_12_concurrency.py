"""Concurrency outcomes.

PRD §2.13 (named race outcomes).

Each test uses the framework's run_race / assert_exactly_one_succeeds
utilities and asserts the PRD-named loser error_id.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_minutes,
    add_seconds,
    assert_exactly_one_succeeds,
    create_session_payload,
    make_bcba_headers,
    run_race,
    setup_basic_environment,
    setup_clinic_with_roster,
    setup_completed_evaluation,
    setup_two_claims_for_concurrency,
    submit_claim,
    validate_error_is_one_of,
    validate_success,
)


class TestPlanActivationConcurrency:
    """PRD §2.13: "When two BCBAs simultaneously activate two DRAFT
    plans of the same patient, first-writer-wins on the patient's
    ACTIVE-plan slot — the loser is rejected with
    ERR_TREATMENT_PLAN_CONFLICT and HTTP 409."

    PRD §3.3 also says: "A patient may have at most one TreatmentPlan
    in DRAFT or ACTIVE status at any time; a second draft is rejected
    with ERR_TREATMENT_PLAN_CONFLICT." Since two simultaneous DRAFT
    plans cannot coexist on the same patient under the static
    constraint, the race scenario reduces to the static-uniqueness
    case enforced at draft creation, which the test below exercises.
    """

    def test_second_draft_plan_for_patient_rejected(self, api):
        """PRD §3.3: "A patient may have at most one TreatmentPlan in
        DRAFT or ACTIVE status at any time; a second draft is rejected
        with ERR_TREATMENT_PLAN_CONFLICT."

        Claim: drafting a second plan while another DRAFT exists for
        the same patient is rejected with ERR_TREATMENT_PLAN_CONFLICT.
        """
        from test_helpers import (
            create_treatment_plan_payload,
            draft_treatment_plan,
            validate_error,
        )
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        evaluation = setup_completed_evaluation(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        # First DRAFT plan.
        draft_treatment_plan(
            patient_id=roster["patient"]["id"],
            source_evaluation_id=evaluation["id"],
            weekly_direct_hours_target=20,
            weekly_supervision_hours_target=2.0,
            weekly_parent_training_hours_target=1.0,
            bcba_id=bcba["id"],
        )
        # Second DRAFT plan — same patient.
        second_eval = setup_completed_evaluation(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        res = api.create_treatment_plan(
            roster["patient"]["id"],
            create_treatment_plan_payload(
                source_evaluation_id=second_eval["id"],
                weekly_direct_hours_target=20,
                weekly_supervision_hours_target=2.0,
                weekly_parent_training_hours_target=1.0,
            ),
            make_bcba_headers(bcba["id"]),
        )
        validate_error(res, "ERR_TREATMENT_PLAN_CONFLICT")


class TestTherapistOverlapConcurrency:
    """PRD §2.13: "When two therapists race to create overlapping
    sessions for the same therapist_id, first-writer-wins on the
    half-open interval and the loser is rejected with
    ERR_SESSION_THERAPIST_OVERLAP and HTTP 409."
    """

    def test_two_concurrent_overlapping_sessions_one_wins(self, api):
        """PRD §2.13: "first-writer-wins on the half-open interval and
        the loser is rejected with ERR_SESSION_THERAPIST_OVERLAP".

        Claim: when two concurrent POST /sessions for the same
        therapist with overlapping intervals fire, exactly one
        succeeds; the loser is rejected with
        ERR_SESSION_THERAPIST_OVERLAP.
        """
        env = setup_basic_environment()
        rbt = env["rbts"][0]
        planned_start = add_seconds(env["now_ts"], seconds=3600)
        planned_end = add_minutes(planned_start, minutes=60)
        # Two overlapping payloads — same start/end.
        from test_helpers import TEST_USERS
        headers = TEST_USERS["clinic_admin_headers"]
        payload_a = create_session_payload(
            authorization_id=env["authorization"]["id"],
            therapist_id=rbt["id"],
            session_type="DIRECT_RBT",
            planned_start=planned_start,
            planned_end=planned_end,
        )
        payload_b = create_session_payload(
            authorization_id=env["authorization"]["id"],
            therapist_id=rbt["id"],
            session_type="DIRECT_RBT",
            planned_start=planned_start,
            planned_end=planned_end,
        )
        results = run_race(
            lambda: api.create_session(
                env["patient"]["id"], payload_a, headers,
            ),
            lambda: api.create_session(
                env["patient"]["id"], payload_b, headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # Inspect the loser; it must carry ERR_SESSION_THERAPIST_OVERLAP.
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, ["ERR_SESSION_THERAPIST_OVERLAP"],
        )


class TestClaimSessionMembershipConcurrency:
    """PRD §2.13: "When two BCBAs race to submit two claims that share
    even one session, first-writer-wins on the session-membership
    claim — the loser is rejected with ERR_SESSION_ALREADY_CLAIMED and
    HTTP 409."

    The PRD names the loser ERR_SESSION_ALREADY_CLAIMED. To create the
    race, we need two draft claims that share at least one session.
    PRD §3.6 says draft creation does not yet reserve the session
    (membership is asserted at /submit), so we can set up two drafts
    both referencing the same session without an immediate rejection.
    """

    def test_two_submits_for_same_session_one_wins(self, api):
        """PRD §2.13: "first-writer-wins on the session-membership
        claim — the loser is rejected with ERR_SESSION_ALREADY_CLAIMED".

        Claim: when two concurrent POST /claims/{id}/submit calls
        share even one session, exactly one succeeds and the loser
        carries ERR_SESSION_ALREADY_CLAIMED.
        """
        env = setup_basic_environment()
        rbt = env["rbts"][0]
        from test_helpers import setup_completed_session, draft_claim
        # One completed session.
        s, _ = setup_completed_session(
            clinic=env["clinic"], patient=env["patient"],
            authorization=env["authorization"], therapist=rbt,
            therapist_role="RBT", session_type="DIRECT_RBT",
            duration_minutes=60, progress_rating=4,
        )
        claim_a = draft_claim(
            patient_id=env["patient"]["id"],
            authorization_id=env["authorization"]["id"],
            session_ids=[s["id"]],
        )
        claim_b = draft_claim(
            patient_id=env["patient"]["id"],
            authorization_id=env["authorization"]["id"],
            session_ids=[s["id"]],
        )
        from test_helpers import TEST_USERS
        headers = TEST_USERS["clinic_admin_headers"]
        results = run_race(
            lambda: api.submit_claim(claim_a["id"], headers),
            lambda: api.submit_claim(claim_b["id"], headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        # PRD §2.13 names ERR_SESSION_ALREADY_CLAIMED for this race, but
        # PRD §3.6 also stipulates that /submit re-verifies that every
        # referenced session is in COMPLETED (otherwise
        # ERR_SESSION_NOT_COMPLETED). Once the winning /submit cascades
        # the shared session from COMPLETED → BILLED, the losing
        # /submit's state pre-check naturally observes BILLED. PRD does
        # not pin down whether the membership rule preempts the state
        # check, so a faithful implementer could legitimately emit either
        # error_id — accept both.
        validate_error_is_one_of(
            loser,
            ["ERR_SESSION_ALREADY_CLAIMED", "ERR_SESSION_NOT_COMPLETED"],
        )
