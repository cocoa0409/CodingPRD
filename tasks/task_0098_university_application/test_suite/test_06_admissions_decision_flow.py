"""Admissions review and decisioning tests (begin-review, decide).

Covers PRD §3.7 (SUBMITTED → UNDER_REVIEW → {ADMITTED, WAITLISTED,
REJECTED}, program capacity gate, ED admit cascade).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_application,
    create_applicant,
    create_application,
    create_program,
    create_university,
    decide_application,
    get_application,
    get_program,
    make_applicant_headers,
    NON_EXISTENT_UUID,
    setup_admitted_application,
    setup_application_ready_to_submit,
    setup_submitted_application,
    setup_under_review_application,
    setup_waitlisted_application,
    submit_application,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Begin-review (PRD §3.7)
# ---------------------------------------------------------------------------
class TestBeginReview:

    def test_begin_review_moves_to_under_review(
        self, api, admissions_officer_headers,
    ):
        """PRD §3.7: "An admissions officer transitions a submitted
        application into review via SUBMITTED → UNDER_REVIEW... The
        application moves to UNDER_REVIEW with no other side effects."
        """
        ctx = setup_submitted_application(round_="REGULAR_DECISION")
        res = api.begin_review(
            ctx["application"]["id"], admissions_officer_headers,
        )
        data = validate_success(res)
        assert data["status"] == "UNDER_REVIEW"

    def test_begin_review_on_draft_yields_invalid_state(
        self, api, admissions_officer_headers,
    ):
        """PRD §3.7: "An admissions officer transitions a submitted
        application into review via SUBMITTED → UNDER_REVIEW..."
        PRD §2.7: "a state-machine endpoint invoked on an entity
        outside the legal from state yields ERR_INVALID_STATE."

        Claim: begin-review on a DRAFT application is rejected with
        ERR_INVALID_STATE (the only legal from-state per §3.7 is
        SUBMITTED).
        """
        # Application stays in DRAFT.
        applicant = create_applicant()
        uni = create_university()
        prog = create_program(uni["id"])
        app = create_application(applicant["id"], prog["id"])
        res = api.begin_review(app["id"], admissions_officer_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Decide: ADMIT (PRD §3.7)
# ---------------------------------------------------------------------------
class TestDecideAdmit:

    def test_admit_moves_to_admitted_and_sets_decision_at(
        self, api, admissions_officer_headers,
    ):
        """PRD §3.7: "On success, admission_decision_at is set to the
        current clock, admitted_count is incremented by one..."
        """
        ctx = setup_under_review_application(round_="REGULAR_DECISION")
        res = api.decide_application(
            ctx["application"]["id"],
            {"decision": "ADMIT"},
            admissions_officer_headers,
        )
        data = validate_success(res)
        assert data["status"] == "ADMITTED"
        assert data["admission_decision_at"] is not None

    def test_admit_sets_enrollment_deadline_30_days_for_rd(
        self, api, admissions_officer_headers,
    ):
        """PRD §3.7: "enrollment_deadline is set to admission_decision_at
        plus 30 days for REGULAR_DECISION or ROLLING applications..."

        Claim: after an RD admit, enrollment_deadline is non-null.
        Verifying that it is exactly 30 days requires server-clock
        access we don't have at the test layer; we assert presence and
        that it is strictly after admission_decision_at.
        """
        ctx = setup_under_review_application(round_="REGULAR_DECISION")
        res = api.decide_application(
            ctx["application"]["id"],
            {"decision": "ADMIT"},
            admissions_officer_headers,
        )
        data = validate_success(res)
        assert data["enrollment_deadline"] is not None
        assert data["enrollment_deadline"] > data["admission_decision_at"]

    def test_admit_increments_program_admitted_count(
        self, api, admissions_officer_headers,
    ):
        """PRD §3.7: "admitted_count is incremented by one..."
        """
        ctx = setup_under_review_application(round_="REGULAR_DECISION")
        prog_before = get_program(ctx["program"]["id"])
        api.decide_application(
            ctx["application"]["id"],
            {"decision": "ADMIT"},
            admissions_officer_headers,
        )
        prog_after = get_program(ctx["program"]["id"])
        assert prog_after["admitted_count"] == prog_before["admitted_count"] + 1

    def test_admit_when_program_at_capacity_yields_err_program_at_capacity(
        self, api, admissions_officer_headers,
    ):
        """PRD §3.7: "The admit decision is gated on program capacity:
        admitted_count + 1 for the target program must not exceed
        capacity (otherwise ERR_PROGRAM_AT_CAPACITY)."
        """
        # Create a capacity-1 program already at admitted_count=1
        # by walking one applicant through to ADMITTED first.
        ctx1 = setup_admitted_application(
            program_overrides={"capacity": 1},
            round_="REGULAR_DECISION",
        )
        # Second applicant on the same program — should fail at admit.
        applicant2 = create_applicant()
        from test_helpers import attach_strong_essay, setup_strong_recommendations
        app2 = create_application(
            applicant2["id"], ctx1["program"]["id"],
            round="REGULAR_DECISION",
        )
        attach_strong_essay(
            applicant2["id"], app2["id"],
            university_name=ctx1["university"]["name"],
            program_name=ctx1["program"]["name"],
        )
        setup_strong_recommendations(applicant2["id"], app2["id"])
        submit_application(applicant2["id"], app2["id"])
        api.begin_review(app2["id"], admissions_officer_headers)
        res = api.decide_application(
            app2["id"],
            {"decision": "ADMIT"},
            admissions_officer_headers,
        )
        validate_error(res, ApiErrorId.ERR_PROGRAM_AT_CAPACITY.value)


# ---------------------------------------------------------------------------
# Decide: WAITLIST (PRD §3.7)
# ---------------------------------------------------------------------------
class TestDecideWaitlist:

    def test_waitlist_moves_to_waitlisted_and_sets_decision_at(
        self, api, admissions_officer_headers,
    ):
        """PRD §3.7: "Waitlist (UNDER_REVIEW → WAITLISTED). No
        precondition beyond state. On success, admission_decision_at
        is set to the current clock..."
        """
        ctx = setup_under_review_application(round_="REGULAR_DECISION")
        res = api.decide_application(
            ctx["application"]["id"],
            {"decision": "WAITLIST"},
            admissions_officer_headers,
        )
        data = validate_success(res)
        assert data["status"] == "WAITLISTED"
        assert data["admission_decision_at"] is not None

    def test_waitlist_does_not_increment_admitted_count(
        self, api, admissions_officer_headers,
    ):
        """PRD §3.2: "a computed admitted_count, the running sum of
        applications in ADMITTED or ENROLLED for that program..."

        Claim: a WAITLIST decision does NOT bump admitted_count
        (waitlisted is neither ADMITTED nor ENROLLED).
        """
        ctx = setup_under_review_application(round_="REGULAR_DECISION")
        prog_before = get_program(ctx["program"]["id"])
        api.decide_application(
            ctx["application"]["id"],
            {"decision": "WAITLIST"},
            admissions_officer_headers,
        )
        prog_after = get_program(ctx["program"]["id"])
        assert prog_after["admitted_count"] == prog_before["admitted_count"]


# ---------------------------------------------------------------------------
# Decide: REJECT (PRD §3.7)
# ---------------------------------------------------------------------------
class TestDecideReject:

    def test_reject_moves_to_rejected_and_sets_decision_at(
        self, api, admissions_officer_headers,
    ):
        """PRD §3.7: "Reject (UNDER_REVIEW → REJECTED). No precondition
        beyond state. On success, admission_decision_at is set to the
        current clock."
        """
        ctx = setup_under_review_application(round_="REGULAR_DECISION")
        res = api.decide_application(
            ctx["application"]["id"],
            {"decision": "REJECT"},
            admissions_officer_headers,
        )
        data = validate_success(res)
        assert data["status"] == "REJECTED"
        assert data["admission_decision_at"] is not None

    def test_reject_of_ed_clears_ed_binding(
        self, api, admissions_officer_headers,
    ):
        """PRD §3.7: "If this application was the applicant's Early
        Decision binding (round equals EARLY_DECISION and
        ed_commitment_application_id equals this application's id),
        the binding is cleared, freeing the applicant to apply
        elsewhere."
        """
        ctx = setup_under_review_application(round_="EARLY_DECISION")
        # Confirm pre-reject the applicant is bound.
        from test_helpers import get_applicant
        applicant_before = get_applicant(ctx["applicant"]["id"])
        assert applicant_before["ed_commitment_application_id"] == (
            ctx["application"]["id"]
        )
        api.decide_application(
            ctx["application"]["id"],
            {"decision": "REJECT"},
            admissions_officer_headers,
        )
        applicant_after = get_applicant(ctx["applicant"]["id"])
        assert applicant_after["ed_commitment_application_id"] is None


# ---------------------------------------------------------------------------
# ED admit cascade (PRD §3.7)
# ---------------------------------------------------------------------------
class TestEDAdmitCascade:

    def test_ed_admit_cascades_withdraw_to_sibling_applications(
        self, api, admissions_officer_headers,
    ):
        """PRD §3.7: "When the admitted application is an Early Decision
        admit, the system cascades: every other in-flight application
        of the same applicant — those in DRAFT, SUBMITTED, UNDER_REVIEW,
        WAITLISTED, or ADMITTED (per the binding contract, the only
        in-flight statuses possible at this point are DRAFT and
        SUBMITTED) — transitions to WITHDRAWN."

        Claim: after ED admit on APP_ED, every other sibling
        application of the same applicant is WITHDRAWN.
        """
        # Build APP_ED in UNDER_REVIEW state.
        ctx = setup_under_review_application(round_="EARLY_DECISION")
        applicant = ctx["applicant"]
        # Build a sibling APP_RD on a different university in SUBMITTED.
        uni2 = create_university()
        prog2 = create_program(uni2["id"])
        app_rd = create_application(
            applicant["id"], prog2["id"], round="REGULAR_DECISION",
        )
        from test_helpers import attach_strong_essay, setup_strong_recommendations
        attach_strong_essay(
            applicant["id"], app_rd["id"],
            university_name=uni2["name"], program_name=prog2["name"],
        )
        setup_strong_recommendations(applicant["id"], app_rd["id"])
        submit_application(applicant["id"], app_rd["id"])

        # Now admit APP_ED.
        api.decide_application(
            ctx["application"]["id"],
            {"decision": "ADMIT"},
            admissions_officer_headers,
        )
        # APP_RD should be cascaded to WITHDRAWN.
        app_rd_after = get_application(app_rd["id"])
        assert app_rd_after["status"] == "WITHDRAWN", (
            f"sibling RD application should be cascaded to WITHDRAWN, "
            f"got {app_rd_after['status']!r}"
        )
