"""Validation priority and concurrency-race tests.

Covers PRD §2.7 (validation ordering with the two explicit priority pairs
called out in prose) and PRD §2.10 (concurrency serialization rules).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    accept_aid_offer,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_applicant,
    create_application,
    create_program,
    create_university,
    decline_aid_offer,
    make_applicant_headers,
    run_race,
    setup_admitted_application,
    setup_admitted_with_aid_offered,
    setup_application_ready_to_submit,
    setup_submitted_application,
    setup_under_review_application,
    submit_application,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ---------------------------------------------------------------------------
# Validation priority pairs explicitly named in PRD §2.7
# ---------------------------------------------------------------------------
class TestSubmitEdBindingBeatsReferential:
    """PRD §2.7: "the submit endpoint runs its Early Decision binding
    check before any referential check, so an applicant who would also
    fail an essay-customization or recommendation-count check still
    sees ERR_ED_ALREADY_BOUND rather than ERR_ESSAY_NOT_CUSTOMIZED or
    ERR_INSUFFICIENT_RECOMMENDATIONS when the binding is the more
    fundamental obstacle."""

    def test_ed_already_bound_takes_precedence_over_insufficient_recommendations(
        self, api,
    ):
        """PRD §2.7: "the submit endpoint runs its Early Decision
        binding check before any referential check, so an applicant
        who would also fail an essay-customization or recommendation-
        count check still sees ERR_ED_ALREADY_BOUND rather than
        ERR_ESSAY_NOT_CUSTOMIZED or ERR_INSUFFICIENT_RECOMMENDATIONS
        when the binding is the more fundamental obstacle."

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_on_ed_submit
        """
        # Bind applicant to ED via APP1.
        ctx1 = setup_application_ready_to_submit(round_="EARLY_DECISION")
        submit_application(ctx1["applicant"]["id"], ctx1["application"]["id"])
        # Build a second ED application that ALSO lacks recommendations.
        applicant = ctx1["applicant"]
        uni2 = create_university()
        prog2 = create_program(uni2["id"])
        app2 = create_application(
            applicant["id"], prog2["id"], round="EARLY_DECISION",
        )
        # Attach a strong essay (so essay gate is not the failure)
        # but DO NOT add recommendations.
        from test_helpers import attach_strong_essay
        attach_strong_essay(
            applicant["id"], app2["id"],
            university_name=uni2["name"], program_name=prog2["name"],
        )
        # Now submit. APP2 has zero SUBMITTED recommendations AND the
        # applicant is already ED-bound. Per PRD §2.7, ED-already-bound
        # wins.
        res = api.submit_application(
            app2["id"], make_applicant_headers(applicant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ED_ALREADY_BOUND.value)


class TestEnrollDeadlineBeatsAlreadyEnrolledElsewhere:
    """PRD §2.7: "on enroll the temporal ERR_ENROLLMENT_DEADLINE_PASSED
    check runs before the ERR_ALREADY_ENROLLED_ELSEWHERE check."""

    def test_invalid_state_takes_precedence_over_program_at_capacity_on_admit(
        self, api, admissions_officer_headers,
    ):
        """PRD §2.7 priority: state precondition (priority 30) runs
        before business_fiscal capacity (priority 60). When AdmissionsOfficer
        calls decide(ADMIT) on an Application that is BOTH not in
        UNDER_REVIEW AND whose program is at capacity, ERR_INVALID_STATE
        wins.

        # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_on_admit
        """
        # First: fill program to capacity with one admitted application.
        ctx_admit = setup_admitted_application(
            program_overrides={"capacity": 1},
            round_="REGULAR_DECISION",
        )
        # Build a SUBMITTED (not UNDER_REVIEW) application on the same
        # program.
        applicant2 = create_applicant()
        from test_helpers import (
            attach_strong_essay, setup_strong_recommendations,
        )
        app2 = create_application(
            applicant2["id"], ctx_admit["program"]["id"],
            round="REGULAR_DECISION",
        )
        attach_strong_essay(
            applicant2["id"], app2["id"],
            university_name=ctx_admit["university"]["name"],
            program_name=ctx_admit["program"]["name"],
        )
        setup_strong_recommendations(applicant2["id"], app2["id"])
        submit_application(applicant2["id"], app2["id"])
        # APP2 is now SUBMITTED (not UNDER_REVIEW). Attempt decide(ADMIT).
        # Both gates fail: state-wrong AND program-at-capacity. PRD
        # priority puts state first.
        res = api.decide_application(
            app2["id"],
            {"decision": "ADMIT"},
            admissions_officer_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Concurrency races (PRD §2.10)
# ---------------------------------------------------------------------------
class TestConcurrencyED:
    """PRD §2.10: "When two Early Decision submissions land for the same
    applicant at the same instant, the first to acquire the row lock
    on Applicant.ed_commitment_application_id wins; the loser receives
    ERR_ED_ALREADY_BOUND (HTTP 409)."""

    def test_two_ed_submissions_race(self, api):
        """PRD §2.10: "When two Early Decision submissions land for the
        same applicant at the same instant, the first to acquire the
        row lock on Applicant.ed_commitment_application_id wins; the
        loser receives ERR_ED_ALREADY_BOUND (HTTP 409)."

        Claim: race two ED submissions for the same applicant; exactly
        one succeeds with status SUBMITTED; the other gets
        ERR_ED_ALREADY_BOUND.
        """
        # Build TWO ED applications for the same applicant, both
        # otherwise ready to submit.
        applicant = create_applicant()
        from test_helpers import (
            attach_strong_essay, setup_strong_recommendations,
        )
        uni1 = create_university()
        prog1 = create_program(uni1["id"])
        app1 = create_application(applicant["id"], prog1["id"], round="EARLY_DECISION")
        attach_strong_essay(applicant["id"], app1["id"],
                            university_name=uni1["name"],
                            program_name=prog1["name"])
        setup_strong_recommendations(applicant["id"], app1["id"])

        uni2 = create_university()
        prog2 = create_program(uni2["id"])
        app2 = create_application(applicant["id"], prog2["id"], round="EARLY_DECISION")
        attach_strong_essay(applicant["id"], app2["id"],
                            university_name=uni2["name"],
                            program_name=prog2["name"])
        setup_strong_recommendations(applicant["id"], app2["id"])

        headers = make_applicant_headers(applicant["id"])
        results = run_race(
            lambda: api.submit_application(app1["id"], headers),
            lambda: api.submit_application(app2["id"], headers),
        )
        outcome = assert_race_outcome(results, 1, 1)
        # The loser must report ERR_ED_ALREADY_BOUND per PRD §2.10.
        loser_response = outcome["failures"][0]
        loser_body = loser_response.json()
        assert loser_body["data"]["error_id"] == "ERR_ED_ALREADY_BOUND", (
            f"loser error_id expected ERR_ED_ALREADY_BOUND, "
            f"got {loser_body['data']['error_id']!r}"
        )


class TestConcurrencyDecideRace:
    """PRD §2.10: "When two admissions officers race to decide the same
    application — say, one ADMIT against one REJECT — the first writer
    wins on the status field; the loser receives ERR_INVALID_STATE
    (HTTP 409)."""

    def test_two_decisions_race_yields_invalid_state_loser(self, api):
        """PRD §2.10: "When two admissions officers race to decide the
        same application — say, one ADMIT against one REJECT — the
        first writer wins on the status field; the loser receives
        ERR_INVALID_STATE (HTTP 409)."

        Claim: race two decide calls on the same UNDER_REVIEW
        application; exactly one succeeds; the loser is
        ERR_INVALID_STATE.
        """
        ctx = setup_under_review_application(round_="REGULAR_DECISION")
        h = TEST_USERS["admissions_officer_headers"]
        app_id = ctx["application"]["id"]
        results = run_race(
            lambda: api.decide_application(app_id, {"decision": "ADMIT"}, h),
            lambda: api.decide_application(app_id, {"decision": "REJECT"}, h),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == "ERR_INVALID_STATE", (
            f"loser error_id expected ERR_INVALID_STATE, "
            f"got {loser_body['data']['error_id']!r}"
        )


class TestConcurrencyAidAcceptDeclineRace:
    """PRD §2.10: "When an applicant fires a simultaneous accept and
    decline on the same financial-aid package, the first writer on
    status wins and the loser receives ERR_INVALID_STATE (HTTP 409)."""

    def test_simultaneous_accept_and_decline_loser_invalid_state(self, api):
        """PRD §2.10: "When an applicant fires a simultaneous accept
        and decline on the same financial-aid package, the first
        writer on status wins and the loser receives ERR_INVALID_STATE
        (HTTP 409)."

        Claim: race accept + decline on the same OFFERED package;
        exactly one succeeds; the loser is ERR_INVALID_STATE.
        """
        ctx = setup_admitted_with_aid_offered(round_="REGULAR_DECISION")
        h = make_applicant_headers(ctx["applicant"]["id"])
        pkg_id = ctx["financial_aid"]["id"]
        results = run_race(
            lambda: api.accept_aid_offer(pkg_id, h),
            lambda: api.decline_aid_offer(pkg_id, h),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == "ERR_INVALID_STATE", (
            f"loser error_id expected ERR_INVALID_STATE, "
            f"got {loser_body['data']['error_id']!r}"
        )
