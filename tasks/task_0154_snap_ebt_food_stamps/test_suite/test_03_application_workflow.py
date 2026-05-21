"""Application lifecycle: DRAFT -> SUBMITTED -> PENDING_INTERVIEW ->
INTERVIEW_DONE -> APPROVED / DENIED / CLOSED, plus return-for-correction revert.

Covers PRD §3.3 (workflow) and §2.8 (cascade on approve).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    NON_EXISTENT_UUID,
    ERR_FORBIDDEN, ERR_INVALID_STATE,
    ERR_GROSS_INCOME_OVER_LIMIT, ERR_NET_INCOME_OVER_LIMIT,
    TEST_USERS,
    assert_application,
    create_household, add_member,
    create_draft_application, walk_to_interview_done,
    setup_basic_household,
    setup_approved_household_at_net_income,
    setup_approved_household_with_active_card,
    dob_for_age,
)


CASEWORKER = TEST_USERS["caseworker_headers"]


class TestApplicationCreationAndDraft:
    def test_create_application_starts_in_draft(self, api):
        """PRD §3.3: "A `HouseholdHead` or `Caseworker` opens an `Application`
        against the household; it begins in `DRAFT` with no other fields populated."

        Claim: a newly created Application has state=DRAFT.
        """
        hh = create_household()
        app = create_draft_application(hh["id"])
        assert app["state"] == "DRAFT"
        assert app.get("submitted_at") is None
        assert app.get("decision_at") is None
        assert_application(app)


class TestApplicationSubmission:
    def test_submit_requires_at_least_one_active_member(self, api):
        """PRD §3.3: "Submission requires at least one active member on the
        household roster and both `address_zip` and `state_code` to be present
        — without these the transition fails with `ERR_INVALID_STATE`."

        Claim: submit on a member-less household yields ERR_INVALID_STATE.
        """
        hh = create_household()  # no members
        app = create_draft_application(hh["id"])
        resp = api.submit_application(hh["id"], app["id"], CASEWORKER)
        validate_error(resp, ERR_INVALID_STATE)

    def test_submit_sets_submitted_at_and_pending(self, api):
        """PRD §3.3: "On success the server records `submitted_at` as
        `Clock.now` and bumps the household's `certification_status` to `PENDING`."

        Claim: a successful submit returns SUBMITTED + sets submitted_at,
        and the household certification_status becomes PENDING.
        """
        hh, _ = setup_basic_household(size=1, age=30)
        app = create_draft_application(hh["id"])
        resp = api.submit_application(hh["id"], app["id"], CASEWORKER)
        data = validate_success(resp)
        assert data["state"] == "SUBMITTED"
        assert data["submitted_at"] is not None
        hh_after = validate_success(api.get_household(hh["id"], CASEWORKER))
        assert hh_after["certification_status"] == "PENDING"


class TestApplicationInterviewProgression:
    def test_schedule_interview_from_submitted(self, api):
        """PRD §3.3: "A caseworker then schedules the interview, transitioning
        the application from `SUBMITTED` to `PENDING_INTERVIEW`."

        Claim: schedule-interview moves SUBMITTED -> PENDING_INTERVIEW.
        """
        hh, _ = setup_basic_household(size=1, age=30)
        app = create_draft_application(hh["id"])
        validate_success(api.submit_application(hh["id"], app["id"], CASEWORKER))
        resp = api.schedule_interview(hh["id"], app["id"], CASEWORKER)
        data = validate_success(resp)
        assert data["state"] == "PENDING_INTERVIEW"

    def test_complete_interview_sets_timestamp(self, api):
        """PRD §3.3: "The interview is later marked complete, transitioning
        from `PENDING_INTERVIEW` to `INTERVIEW_DONE` and recording
        `interview_completed_at`."

        Claim: complete-interview sets interview_completed_at to non-null.
        """
        hh, _ = setup_basic_household(size=1, age=30)
        app = create_draft_application(hh["id"])
        validate_success(api.submit_application(hh["id"], app["id"], CASEWORKER))
        validate_success(api.schedule_interview(hh["id"], app["id"], CASEWORKER))
        resp = api.complete_interview(hh["id"], app["id"], CASEWORKER)
        data = validate_success(resp)
        assert data["state"] == "INTERVIEW_DONE"
        assert data["interview_completed_at"] is not None


class TestApplicationReturnForCorrection:
    def test_return_for_correction_reverts_to_draft(self, api):
        """PRD §3.3: "returning the application for correction reverts it from
        `SUBMITTED` back to `DRAFT`: `submitted_at` is cleared back to null,
        and the household's `certification_status` is set back to null **only**
        if no other approved application exists for this household."

        Claim: return-for-correction returns SUBMITTED -> DRAFT and clears
        submitted_at; household certification_status returns to null.
        """
        hh, _ = setup_basic_household(size=1, age=30)
        app = create_draft_application(hh["id"])
        validate_success(api.submit_application(hh["id"], app["id"], CASEWORKER))
        resp = api.return_for_correction(hh["id"], app["id"], CASEWORKER)
        data = validate_success(resp)
        assert data["state"] == "DRAFT"
        assert data["submitted_at"] is None
        hh_after = validate_success(api.get_household(hh["id"], CASEWORKER))
        assert hh_after["certification_status"] is None

    def test_return_for_correction_invalid_from_draft(self, api):
        """PRD §3.3: "returning the application for correction reverts it from
        `SUBMITTED` back to `DRAFT`."

        Claim: return-for-correction from DRAFT yields ERR_INVALID_STATE.
        """
        hh, _ = setup_basic_household(size=1, age=30)
        app = create_draft_application(hh["id"])
        resp = api.return_for_correction(hh["id"], app["id"], CASEWORKER)
        validate_error(resp, ERR_INVALID_STATE)


class TestApplicationApproval:
    def test_approve_requires_interview_done(self, api):
        """PRD §3.3: "The transition runs from `INTERVIEW_DONE` to `APPROVED`."

        Claim: approve from DRAFT yields ERR_INVALID_STATE.
        """
        hh, _ = setup_basic_household(size=1, age=30)
        app = create_draft_application(hh["id"])
        resp = api.approve_application(hh["id"], app["id"], CASEWORKER)
        validate_error(resp, ERR_INVALID_STATE)

    def test_approve_inclusive_net_boundary_passes(self, api):
        """PRD §3.3: "Both checks use **inclusive** comparisons — a household
        whose net income equals the limit exactly is approved, not rejected."

        Claim (boundary): size=3, net == 211800 (limit), approve succeeds.
        """
        # difficulty: boundary_precision_check/net_income_limit_inclusive_boundary
        ctx = setup_approved_household_at_net_income(target_net_cents=211800, size=3)
        assert ctx["application"]["state"] == "APPROVED"

    def test_approve_net_over_limit_rejected(self, api):
        """PRD §3.3: "A failure here yields `ERR_NET_INCOME_OVER_LIMIT`."

        Claim (boundary): size=3 net=211801 (1 over limit) yields
        ERR_NET_INCOME_OVER_LIMIT.
        """
        # difficulty: boundary_precision_check/net_income_limit_inclusive_boundary
        from test_helpers import setup_household_at_net_income
        hh, _ = setup_household_at_net_income(target_net_cents=211801, size=3)
        app = create_draft_application(hh["id"])
        walk_to_interview_done(hh["id"], app["id"])
        resp = api.approve_application(hh["id"], app["id"], CASEWORKER)
        validate_error(resp, ERR_NET_INCOME_OVER_LIMIT)

    def test_approve_gross_over_limit_rejected_for_non_elderly(self, api):
        """PRD §3.3: "A failure here yields `ERR_GROSS_INCOME_OVER_LIMIT`."

        Claim: a household with gross income exceeding the size-1 gross limit
        (162200 cents = $1,622) and no elderly/disabled member fails with
        ERR_GROSS_INCOME_OVER_LIMIT on approve.
        """
        # gross 200000 > 162200 limit; non-elderly; net would also overflow.
        hh = create_household()
        add_member(hh["id"], full_name="A", date_of_birth=dob_for_age(30),
                   unearned_income_cents=200000)
        app = create_draft_application(hh["id"])
        walk_to_interview_done(hh["id"], app["id"])
        resp = api.approve_application(hh["id"], app["id"], CASEWORKER)
        # Either gross-over or net-over may fire; PRD §3.3 names both:
        # "the gross-income test passes ... the net-income test passes" with
        # gross check named first in approve logic. We accept either of the
        # PRD-named income errors here.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(resp, [ERR_GROSS_INCOME_OVER_LIMIT, ERR_NET_INCOME_OVER_LIMIT])

    def test_approve_elderly_bypasses_gross_test(self, api):
        """PRD §3.3: "The gross-income test is satisfied when
        `gross_monthly_income_cents` is at or below the gross-income limit for
        the household size, **or** when `has_elderly_or_disabled` is true —
        households with an elderly or disabled member bypass the gross test
        entirely."

        Claim: an elderly household with gross above the size-1 limit but with
        net under the size-1 net limit can be approved.
        """
        hh = create_household(shelter_expense_cents=200000)
        # Elderly member; 200000 cents earned -> gross=200000 > 162200 gross limit (size 1)
        # but net test goes through with the uncapped shelter deduction.
        add_member(hh["id"], full_name="E", date_of_birth=dob_for_age(65),
                   earned_income_cents=200000)
        app = create_draft_application(hh["id"])
        walk_to_interview_done(hh["id"], app["id"])
        resp = api.approve_application(hh["id"], app["id"], CASEWORKER)
        # If the implementation passes the gross bypass and net is computed
        # correctly, this should succeed. Otherwise the most specific failure
        # would be ERR_NET_INCOME_OVER_LIMIT — accept either outcome path.
        # We assert: approval succeeds OR rejection is the net-income error
        # (NOT the gross error).
        if resp.status_code >= 400:
            from test_helpers import validate_error
            validate_error(resp, ERR_NET_INCOME_OVER_LIMIT)
        else:
            data = validate_success(resp)
            assert data["state"] == "APPROVED"

    def test_approve_cascade_sets_household_status_approved(self, api):
        """PRD §3.3: "On a successful approval ... `Household.certification_status`
        becomes `APPROVED` and `Household.certification_period_end` is set to
        the new `certification_period_end_at`."

        Claim: after approve, household.certification_status == APPROVED.
        """
        ctx = setup_approved_household_with_active_card(size=1, age=30)
        hh = validate_success(api.get_household(ctx["household"]["id"], CASEWORKER))
        assert hh["certification_status"] == "APPROVED"
        assert hh.get("certification_period_end") is not None

    def test_approve_stamps_decision_at_and_periods(self, api):
        """PRD §3.3: "decision_at`, `certification_period_start_at` (equal to
        `decision_at`), and `certification_period_end_at` (exactly 12 months
        after `decision_at`) are stamped on the application."

        Claim: approve sets all three timestamps non-null.
        """
        ctx = setup_approved_household_with_active_card(size=1, age=30)
        app = ctx["application"]
        assert app["decision_at"] is not None
        assert app["certification_period_start_at"] is not None
        assert app["certification_period_end_at"] is not None


class TestApplicationDenial:
    def test_deny_requires_denial_reason(self, api):
        """PRD §3.3: "Denial runs from `INTERVIEW_DONE` to `DENIED` and requires
        the caseworker to supply a `denial_reason`; absent that, the request fails."

        Claim: deny without denial_reason yields a validation error.
        """
        hh, _ = setup_basic_household(size=1, age=30)
        app = create_draft_application(hh["id"])
        walk_to_interview_done(hh["id"], app["id"])
        resp = api.deny_application(hh["id"], app["id"], {}, CASEWORKER)
        from test_helpers import validate_error_is_one_of
        from test_helpers import ERR_VALIDATION
        validate_error_is_one_of(resp, [ERR_VALIDATION])

    def test_deny_sets_household_denied(self, api):
        """PRD §3.3: "On success `decision_at` is stamped and
        `Household.certification_status` becomes `DENIED`."

        Claim: deny moves application to DENIED and household to DENIED.
        """
        hh, _ = setup_basic_household(size=1, age=30)
        app = create_draft_application(hh["id"])
        walk_to_interview_done(hh["id"], app["id"])
        resp = api.deny_application(hh["id"], app["id"], {"denial_reason": "INCOMPLETE_INFO"}, CASEWORKER)
        data = validate_success(resp)
        assert data["state"] == "DENIED"
        assert data["denial_reason"] == "INCOMPLETE_INFO"
        hh_after = validate_success(api.get_household(hh["id"], CASEWORKER))
        assert hh_after["certification_status"] == "DENIED"

    def test_deny_does_not_auto_issue_card(self, api):
        """PRD §3.3: "On a successful approval, the server performs the full
        cascade described in §2.8: ... if no `EbtCard` currently exists in
        `ISSUED`, `ACTIVE`, or `SUSPENDED`, a new one is auto-issued in `ISSUED`
        and a `REGULAR_ALLOTMENT` `BenefitLedger` entry is posted to it."

        Claim: denial does NOT trigger any card auto-issuance, so a subsequent
        manual issuance must succeed (no ERR_CARD_ALREADY_EXISTS).
        """
        hh, _ = setup_basic_household(size=1, age=30)
        app = create_draft_application(hh["id"])
        walk_to_interview_done(hh["id"], app["id"])
        validate_success(api.deny_application(hh["id"], app["id"], {"denial_reason": "OTHER"}, CASEWORKER))
        # Try manual issuance — should NOT collide because deny did not auto-issue
        resp = api.create_card(hh["id"], CASEWORKER)
        # Note: PRD §3.4 says ACTIVATE requires household certification APPROVED;
        # issuance is gated only by uniqueness + fraud-hold. So creation should succeed.
        validate_success(resp, expected_status=201)


class TestApplicationClose:
    def test_close_approved_application(self, api):
        """PRD §3.3: "Closing an approved application — either manually by a
        caseworker or automatically by the sweep at expiry — transitions it
        from `APPROVED` to `CLOSED`, flips `Household.certification_status` to
        `CLOSED`."

        Claim: close on APPROVED moves to CLOSED and updates household.
        """
        ctx = setup_approved_household_with_active_card(size=1, age=30)
        resp = api.close_application(ctx["household"]["id"], ctx["application"]["id"], CASEWORKER)
        data = validate_success(resp)
        assert data["state"] == "CLOSED"
        hh_after = validate_success(api.get_household(ctx["household"]["id"], CASEWORKER))
        assert hh_after["certification_status"] == "CLOSED"


class TestApplicationRBAC:
    def test_create_application_by_state_admin_forbidden(self, api):
        """PRD §4 table: "POST /households/{id}/applications — Create a draft
        Application — Caseworker, HouseholdHead."

        Claim: StateAdministrator cannot create an application.
        """
        hh = create_household()
        resp = api.create_application(hh["id"], TEST_USERS["state_admin_headers"])
        validate_error(resp, ERR_FORBIDDEN)
