"""Concurrency rules for which PRD §2.10 explicitly names the outcome
or the loser's error_id.

For races where PRD declares the exact error_id of the loser, we
assert it directly; for races where PRD only says "exactly one wins,"
we use assert_exactly_one_succeeds.
"""
from __future__ import annotations

from test_helpers import (
    TEST_USERS,
    advance_clock_days,
    anchor_clock,
    assert_exactly_one_succeeds,
    create_dpt_therapist,
    create_episode,
    create_evaluation,
    create_patient,
    create_visit,
    iso_anchor_offset,
    iso_date_anchor_offset,
    make_therapist_headers,
    re_get_episode,
    run_race,
    setup_active_episode,
    setup_scheduled_visit,
    setup_va_referral_partial_consumed,
    validate_error,
    validate_success,
)
from test_helpers import (
    create_authorization_payload,
    sign_visit_payload,
)


# ===========================================================================
# Race: two starts on the same SCHEDULED visit — PRD §2.10.
# ===========================================================================
class TestConcurrentVisitStart:

    def test_two_starts_on_same_visit_exactly_one_wins(self, api):
        """PRD §2.10: "Two clinicians who attempt to start the same
        SCHEDULED visit at the same instant will produce exactly one
        IN_SESSION row; the loser is rejected with ERR_INVALID_STATE."

        Claim: two concurrent /start calls — exactly one 2xx, the
        other rejected with ERR_INVALID_STATE.
        """
        setup = setup_scheduled_visit()
        therapist = setup["therapist"]
        visit_id = setup["visit"]["id"]
        results = run_race(
            lambda: api.start_visit(
                visit_id, make_therapist_headers(therapist["id"]),
            ),
            lambda: api.start_visit(
                visit_id, make_therapist_headers(therapist["id"]),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD explicitly names ERR_INVALID_STATE as the loser.
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_INVALID_STATE")


# ===========================================================================
# Race: two finalizes on the same DRAFT evaluation — PRD §2.10.
# ===========================================================================
class TestConcurrentEvaluationFinalize:

    def test_two_finalizes_on_same_evaluation_exactly_one_wins(self, api):
        """PRD §2.10: "Two clinicians who attempt to finalize the same
        DRAFT evaluation concurrently produce exactly one FINALIZED
        row; the loser is rejected with ERR_INVALID_STATE."

        Claim: two concurrent /finalize calls — exactly one 2xx, the
        other rejected with ERR_INVALID_STATE.
        """
        anchor_clock()
        therapist = create_dpt_therapist()
        patient = create_patient(insurance_type="COMMERCIAL")
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=therapist["id"],
        )
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=therapist["id"], complexity="MODERATE",
            functional_baseline_score=50,
            acting_therapist_id=therapist["id"],
        )
        results = run_race(
            lambda: api.finalize_evaluation(
                evaluation["id"], make_therapist_headers(therapist["id"]),
            ),
            lambda: api.finalize_evaluation(
                evaluation["id"], make_therapist_headers(therapist["id"]),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_INVALID_STATE")


# ===========================================================================
# Race: two HEP issue calls — PRD §2.10.
# ===========================================================================
class TestConcurrentHepIssue:

    def test_two_issues_on_same_hep_exactly_one_wins(self, api):
        """PRD §2.10: "Two requests that attempt to issue the same
        DRAFT HEP concurrently produce exactly one ISSUED row; the
        loser is rejected with ERR_INVALID_STATE."

        Claim: two concurrent /issue calls — exactly one 2xx, the
        other rejected with ERR_INVALID_STATE.
        """
        from test_helpers import create_home_exercise_program
        setup = setup_active_episode()
        therapist = setup["therapist"]
        hep = create_home_exercise_program(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            prescribing_clinician_id=therapist["id"],
            acting_therapist_id=therapist["id"],
        )
        results = run_race(
            lambda: api.issue_home_exercise_program(
                hep["id"], make_therapist_headers(therapist["id"]),
            ),
            lambda: api.issue_home_exercise_program(
                hep["id"], make_therapist_headers(therapist["id"]),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_INVALID_STATE")


# ===========================================================================
# Race: two VA authorization creates against the same referral —
# PRD §2.10 / §3.4.
# ===========================================================================
class TestConcurrentVaAuthorizationCreate:

    def test_va_referral_exhaustion_concurrent_outcome(self, api):
        """PRD §2.10: "When two authorization creates race against
        the same VeteranReferral, the system serializes consumption
        on VeteranReferral.authorized_units; if their combined
        unit_quota would exceed the referral's authorized total, the
        loser is rejected with ERR_VA_REFERRAL_EXHAUSTED."

        Claim: two concurrent VA_REFERRAL authorization creates whose
        combined quota exceeds VeteranReferral.authorized_units —
        exactly one succeeds, the loser is rejected with
        ERR_VA_REFERRAL_EXHAUSTED.
        """
        # Start with a fresh VA referral & ACTIVE episode that has NO
        # consumed authorizations yet. Use setup_va_active_episode
        # with a large unit_quota (consuming most of the referral)
        # would over-commit; instead build the base setup with a
        # smaller first authorization and then race two further
        # creates that would push past authorized_units.
        # PRD §3.4 says the FIRST visit on a VA episode requires a
        # VA_REFERRAL authorization to already exist, but
        # authorization creation itself does not require an existing
        # one. To race two creates against an empty referral, build
        # the episode WITHOUT the initial VA_REFERRAL authorization
        # by skipping the va_active fixture.
        anchor_clock()
        therapist = create_dpt_therapist()
        patient = create_patient(insurance_type="VA")
        from test_helpers import create_veteran_referral
        ref = create_veteran_referral(
            patient_id=patient["id"], authorized_units=50,
        )
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=therapist["id"],
        )
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=therapist["id"], complexity="MODERATE",
            functional_baseline_score=50,
            acting_therapist_id=therapist["id"],
        )
        from test_helpers import finalize_evaluation, create_plan_of_care
        finalize_evaluation(
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
        )
        plan = create_plan_of_care(
            episode_id=episode["id"], evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
            planned_visit_count=10, planned_units_per_visit=3,
            cert_period_start=iso_date_anchor_offset(days=0),
            cert_period_end=iso_date_anchor_offset(days=60),
        )

        # Two concurrent VA_REFERRAL authorization creates, each for
        # 30 units (combined 60 > 50 authorized).
        def make_auth():
            return api.create_authorization(
                episode["id"],
                create_authorization_payload(
                    plan_of_care_id=plan["id"],
                    source="VA_REFERRAL",
                    external_reference=ref["id"],
                    unit_quota=30,
                    valid_from=iso_date_anchor_offset(days=-1),
                    valid_through=iso_date_anchor_offset(days=61),
                ),
                TEST_USERS["clinic_admin_headers"],
            )

        results = run_race(make_auth, make_auth)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_VA_REFERRAL_EXHAUSTED")
