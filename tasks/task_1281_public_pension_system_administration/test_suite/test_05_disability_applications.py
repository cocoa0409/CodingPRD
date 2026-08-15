"""Disability retirement: medical review cycle, appeals, fresh-eyes rule."""
import pytest

from test_helpers import (
    ApiErrorId,
    appeal_disability_app,
    assert_benefit,
    assert_disability_application,
    create_disability_app,
    create_member,
    decide_disability_app,
    make_medical_reviewer_headers,
    make_member_headers,
    set_clock,
    setup_fund_and_employer,
    setup_vested_member,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST, APPROVER


class TestDenyAppealReopenCycle:
    def test_deny_then_appeal_reopens_review(self, api):
        """PRD §3.6: "A successful appeal moves the application `DENIED →
        UNDER_MEDICAL_REVIEW` and increments `appeal_count` by 1, reopening
        the cycle — with the guarantee, via the fresh-eyes rule, that whoever
        decides next is not the reviewer who decided last."
        PRD §3.6: "The application enters `UNDER_MEDICAL_REVIEW` immediately
        upon creation; the filing captures `submitted_by_user_id` from the
        request's `X-User-ID`, initializes `appeal_count` to 0, and leaves
        `decided_at` and `last_reviewer_user_id` unset until the first
        decision."

        Design: Difficulty/non_linear_state_machine/disability_deny_appeal_reopen_cycle
        """
        ctx = setup_vested_member(full_name="Appeal Annie")
        member = ctx["member"]
        app = create_disability_app(member["id"], "NON_DUTY",
                                    description="chronic back injury")
        assert app["status"] == "UNDER_MEDICAL_REVIEW"
        denied = decide_disability_app(app["id"], "DENY", "reviewer-1",
                                       "insufficient evidence")
        assert denied["status"] == "DENIED"
        assert denied["appeal_count"] == 0
        assert denied["last_reviewer_user_id"] == "reviewer-1"

        appealed = appeal_disability_app(app["id"], member["id"])
        assert appealed["status"] == "UNDER_MEDICAL_REVIEW"
        assert appealed["appeal_count"] == 1

    def test_fresh_eyes_approve_creates_disability_benefit(self, api):
        """PRD §3.6: "Approving a disability application runs the disability
        benefit calculation over the FINAL input set — accepted contribution
        lines only: the monthly amount is 0.60 times the final average salary
        (computed exactly as in §3.5) divided by twelve, rounded half-up to
        whole cents."
        PRD §3.6: "A Benefit is created with `benefit_kind` `DISABILITY`, that
        monthly amount, `status` `ACTIVE`, and `effective_date` on the first
        day of the decision month. The member moves to `RETIRED`"

        Design: Difficulty/non_linear_state_machine/disability_deny_appeal_reopen_cycle
        """
        ctx = setup_vested_member(full_name="Appeal Annie")
        member = ctx["member"]
        app = create_disability_app(member["id"], "NON_DUTY")
        decide_disability_app(app["id"], "DENY", "reviewer-1")
        appeal_disability_app(app["id"], member["id"])
        approved = decide_disability_app(app["id"], "APPROVE", "reviewer-2")
        assert_disability_application(approved)
        assert approved["status"] == "APPROVED"
        assert approved["last_reviewer_user_id"] == "reviewer-2"

        benefits, meta = validate_paginated(
            api.list_member_benefits(member["id"], ANALYST))
        assert meta["total_count"] == 1
        assert_benefit(benefits[0])
        assert benefits[0]["benefit_kind"] == "DISABILITY"
        assert benefits[0]["monthly_amount_cents"] == 275_000, (
            f"round_half_up(5,500,000 * 0.60 / 12) = 275,000, "
            f"got {benefits[0]['monthly_amount_cents']}")
        assert benefits[0]["status"] == "ACTIVE"
        assert benefits[0]["effective_date"] == "2026-08-01"
        member_after = validate_success(api.get_member(member["id"], ANALYST),
                                        200)
        assert member_after["status"] == "RETIRED"


class TestDisabilityAuthorization:
    def test_benefit_approver_cannot_decide_disability(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list, or that fails an entity-backed ownership check, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.6: "Decisions belong to the MedicalReviewer."

        Design: Corner/validations/approver_cannot_decide_disability_returns_forbidden
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Duty Doug",
                               date_of_birth="1970-01-01",
                               hire_date="2018-01-01")
        app = create_disability_app(member["id"], "DUTY")
        res = api.decide_disability_application(
            app["id"], {"outcome": "APPROVE"}, APPROVER)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_disability_application(app["id"],
                                                                ANALYST), 200)
        assert after["status"] == "UNDER_MEDICAL_REVIEW"


class TestAppealWindow:
    def test_appeal_window_inclusive_at_sixty_days_closed_after(self, api):
        """PRD §3.6: "The member or an analyst may appeal within 60 days of
        `decided_at`, measured against the logical clock; an appeal filed
        after that window is `ERR_APPEAL_WINDOW_CLOSED` (HTTP 422)."

        Design: Corner/validations/appeal_after_sixty_days_returns_error
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Window Will",
                               date_of_birth="1970-01-01",
                               hire_date="2018-01-01")
        app = create_disability_app(member["id"], "DUTY")
        decide_disability_app(app["id"], "DENY", "reviewer-1")

        # decided_at 2026-08-01 + 60 days = 2026-09-30: still within window
        set_clock("2026-09-30T00:00:00Z")
        appealed = appeal_disability_app(app["id"], member["id"])
        assert appealed["status"] == "UNDER_MEDICAL_REVIEW"
        assert appealed["appeal_count"] == 1

        # second denial re-stamps decided_at at 2026-09-30; +62 days is closed
        decide_disability_app(app["id"], "DENY", "reviewer-2")
        set_clock("2026-12-01T00:00:00Z")
        res = api.appeal_disability_application(
            app["id"], make_member_headers(member["id"]))
        validate_error(res, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)


class TestFreshEyesRule:
    def test_appeal_decision_by_same_reviewer_returns_segregation(self, api):
        """PRD §3.6: "when the application has been appealed — `appeal_count`
        greater than 0 — the deciding reviewer's `X-User-ID` must differ from
        `last_reviewer_user_id`, the fresh-eyes rule, enforced as
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/disability_appeal_same_reviewer_returns_segregation
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Fresh Eyes Fay",
                               date_of_birth="1970-01-01",
                               hire_date="2018-01-01")
        app = create_disability_app(member["id"], "DUTY")
        decide_disability_app(app["id"], "DENY", "reviewer-1")
        appeal_disability_app(app["id"], member["id"])
        res = api.decide_disability_application(
            app["id"], {"outcome": "APPROVE"},
            make_medical_reviewer_headers("reviewer-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = validate_success(api.get_disability_application(app["id"],
                                                                ANALYST), 200)
        assert after["status"] == "UNDER_MEDICAL_REVIEW"
        assert after["appeal_count"] == 1
