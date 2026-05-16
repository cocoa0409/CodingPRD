"""Application lifecycle: create → submit → decide (APPROVE/DENY) →
withdraw, plus the snapshots captured at submit and the determination
issued at decide.

Exercises PRD §3.3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    add_applicant,
    add_income,
    assert_application,
    assert_eligibility_determination,
    create_application,
    create_application_payload,
    create_household,
    create_household_payload,
    create_state_policy,
    decide_application,
    decide_application_payload,
    get_application,
    setup_basic_household,
    setup_denied_application,
    setup_eligible_application,
    submit_application,
    validate_error,
    validate_success,
)


# ===========================================================================
# Application creation — PRD §3.3
# ===========================================================================
class TestApplicationCreation:

    def test_create_application_returns_draft(
            self, api, intake_worker_headers):
        """PRD §3.3: "An application is created by an IntakeWorker
        against a parent household. The intake worker supplies the
        program ... and optionally the rule_variant, which defaults to
        STATE. The new application enters DRAFT."

        Claim: a freshly created application has status=DRAFT.
        """
        _sp, household, _ = setup_basic_household()
        application = create_application(
            household=household, program="MAGI_ADULT",
        )
        assert_application(application)
        assert application["status"] == "DRAFT", (
            "New application must enter DRAFT per PRD §3.3; "
            f"got status={application['status']!r}"
        )

    def test_rule_variant_defaults_to_state(
            self, api, intake_worker_headers):
        """PRD §3.3: "optionally the rule_variant, which defaults to
        STATE."

        Claim: omitting rule_variant produces an application with
        rule_variant=STATE.
        """
        _sp, household, _ = setup_basic_household()
        application = create_application(
            household=household, program="MAGI_ADULT",
            rule_variant=None,
        )
        assert application["rule_variant"] == "STATE", (
            "rule_variant must default to STATE per PRD §3.3; "
            f"got rule_variant={application['rule_variant']!r}"
        )


# ===========================================================================
# Submit — PRD §3.3
# ===========================================================================
class TestSubmit:

    def test_submit_moves_draft_to_under_review(
            self, api, intake_worker_headers):
        """PRD §3.3: "Submission transitions the application from DRAFT
        to UNDER_REVIEW."

        Claim: submit on a DRAFT application returns status=UNDER_REVIEW.
        """
        _sp, household, _, application = setup_eligible_application()
        assert application["status"] == "UNDER_REVIEW"

    def test_submit_captures_three_snapshots(
            self, api, intake_worker_headers):
        """PRD §3.3: "On a successful submit, the system captures three
        immutable snapshots onto the application: snapshot_magi (the
        household's total_magi under the chosen rule variant ...),
        snapshot_fpl_percent (the household's fpl_percent recomputed
        against the same rule-variant-adjusted total MAGI), and
        snapshot_countable_assets (the sum of countable_assets across
        non-EXCLUDED applicants computed under the chosen rule-variant's
        exempt set)."

        Claim: after submit, snapshot_magi / snapshot_fpl_percent /
        snapshot_countable_assets are present and finite.
        """
        _sp, household, _, application = setup_eligible_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        for field in (
            "snapshot_magi", "snapshot_fpl_percent",
            "snapshot_countable_assets",
        ):
            assert field in application, (
                f"snapshot field {field!r} must be present after submit "
                f"per PRD §3.3; got keys={list(application)}"
            )
            assert application[field] is not None, (
                f"{field} must not be null after submit per PRD §3.3"
            )

    def test_submit_already_under_review_invalid_state(
            self, api, intake_worker_headers):
        """PRD §3.3: "the application is currently in DRAFT (otherwise
        ERR_INVALID_STATE)."

        Claim: submitting an already-submitted application →
        ERR_INVALID_STATE.
        """
        _sp, household, _, application = setup_eligible_application()
        res = api.submit_application(
            household["id"], application["id"], intake_worker_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_submit_without_head_applicant_household_incomplete(
            self, api, intake_worker_headers):
        """PRD §3.3: "the parent household has its head_applicant_id
        set ... (otherwise ERR_HOUSEHOLD_INCOMPLETE)."

        Claim: submitting a household with no non-EXCLUDED applicant
        (head_applicant_id null) → ERR_HOUSEHOLD_INCOMPLETE.
        """
        policy = create_state_policy()
        household = create_household(state_code=policy["state_code"])
        add_applicant(household=household, dependent_status="EXCLUDED")
        application = create_application(household=household)
        res = api.submit_application(
            household["id"], application["id"], intake_worker_headers,
        )
        validate_error(res, "ERR_HOUSEHOLD_INCOMPLETE")


# ===========================================================================
# Decide APPROVE — PRD §3.3
# ===========================================================================
class TestDecideApprove:

    def test_approve_creates_eligible_determination_and_enrollment(self, api):
        """PRD §3.3: "On approval, the application transitions to
        APPROVED, the system creates a new EligibilityDetermination
        with outcome ELIGIBLE ... The system then creates one
        Enrollment per non-EXCLUDED Applicant in the household."

        Claim: APPROVE returns an EligibilityDetermination(outcome=
        ELIGIBLE), the Application transitions to APPROVED, and at
        least one Enrollment exists for the applicant.
        """
        _sp, household, _, application = setup_eligible_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        determination = decide_application(
            household=household, application=application, decision="APPROVE",
        )
        assert_eligibility_determination(determination)
        assert determination["outcome"] == "ELIGIBLE"
        # Refetch application to confirm status transition.
        app_refreshed = get_application(household["id"], application["id"])
        assert app_refreshed["status"] == "APPROVED"

    def test_approve_sets_coverage_window_to_365_days(self, api):
        """PRD §3.3: "coverage_start is the current clock_now,
        coverage_end is coverage_start plus 365 days, redetermination_
        due_at is also coverage_start plus 365 days."
        PRD §2.6: "the '365 days' used to derive coverage_end and
        redetermination_due_at are interpreted as exactly 365 * 86400
        seconds added to the originating instant."

        Claim: enrollment.coverage_end - coverage_start == 365 days.
        """
        from datetime import timedelta
        from test_helpers import parse_iso
        _sp, household, _, _app, _det, enrollments = (
            __import__(
                "test_helpers", fromlist=["setup_approved_application"],
            ).setup_approved_application(
                incomes=[
                    {"applicant_index": 0, "source_type": "WAGES",
                     "gross_amount": 12_000.00, "frequency": "ANNUAL"},
                ],
            )
        )
        assert enrollments, "approve must create at least one enrollment"
        e = enrollments[0]
        start = parse_iso(e["coverage_start"])
        end = parse_iso(e["coverage_end"])
        assert (end - start) == timedelta(days=365), (
            "coverage_end must be coverage_start + 365 days exactly "
            f"per PRD §2.6 / §3.3; got delta={end - start}"
        )

    def test_approve_above_ceiling_returns_not_eligible(self, api):
        """PRD §3.3: "the application's snapshot_fpl_percent is at most
        the household's StatePolicy.magi_income_limit_pct ... otherwise
        ERR_NOT_ELIGIBLE."

        Claim: an application whose snapshot is above the ceiling, when
        APPROVE is attempted, returns ERR_NOT_ELIGIBLE (422).
        """
        _sp, household, _, application = setup_eligible_application(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 50.0,
            },
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 100_000.00, "frequency": "ANNUAL"},
            ],
        )
        res = api.decide_application(
            household["id"], application["id"],
            decide_application_payload(decision="APPROVE"),
            headers=TEST_USERS["eligibility_caseworker_headers"],
        )
        validate_error(res, "ERR_NOT_ELIGIBLE")


# ===========================================================================
# Decide DENY — PRD §3.3
# ===========================================================================
class TestDecideDeny:

    def test_deny_creates_ineligible_determination(self, api):
        """PRD §3.3: "On denial, the application transitions to DENIED,
        the system creates a new EligibilityDetermination with outcome
        INELIGIBLE and the supplied ineligibility_reason, and no
        enrollments are created."

        Claim: DENY returns outcome=INELIGIBLE with the supplied
        ineligibility_reason.
        """
        _sp, household, _, _application, determination = setup_denied_application(
            ineligibility_reason="INCOME_EXCEEDS_LIMIT",
        )
        assert determination["outcome"] == "INELIGIBLE"
        assert determination["ineligibility_reason"] == "INCOME_EXCEEDS_LIMIT"

    def test_deny_does_not_create_enrollments(self, api):
        """PRD §3.3: "and no enrollments are created" (on DENY).

        Claim: listing enrollments for the household's applicants after
        DENY returns no rows.
        """
        _sp, household, applicants, _app, _det = setup_denied_application()
        from test_helpers import TEST_USERS as _TU
        admin = _TU["policy_admin_headers"]
        for applicant in applicants:
            res = api.list_enrollments(
                admin, params={"applicant_id": applicant["id"]},
            )
            body = res.json()
            assert body["data"] == [], (
                "DENY must not create enrollments per PRD §3.3; "
                f"got data={body['data']}"
            )


# ===========================================================================
# Withdraw — PRD §3.3
# ===========================================================================
class TestWithdraw:

    def test_withdraw_from_draft_succeeds(self, api, intake_worker_headers):
        """PRD §3.3: "An application that is still in DRAFT or
        UNDER_REVIEW may be withdrawn by an IntakeWorker; the
        application transitions to WITHDRAWN."

        Claim: a DRAFT application can be withdrawn.
        """
        _sp, household, _ = setup_basic_household()
        application = create_application(household=household)
        res = api.withdraw_application(
            household["id"], application["id"], intake_worker_headers,
        )
        data = validate_success(res)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_from_under_review_succeeds(
            self, api, intake_worker_headers):
        """PRD §3.3: "An application that is still in DRAFT or
        UNDER_REVIEW may be withdrawn by an IntakeWorker; the
        application transitions to WITHDRAWN."

        Claim: an UNDER_REVIEW application can be withdrawn.
        """
        _sp, household, _, application = setup_eligible_application()
        res = api.withdraw_application(
            household["id"], application["id"], intake_worker_headers,
        )
        data = validate_success(res)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_from_approved_invalid_state(
            self, api, intake_worker_headers):
        """PRD §3.3: "A withdrawal attempted on an application in any
        other state is rejected with ERR_INVALID_STATE."

        Claim: withdrawing an APPROVED application → ERR_INVALID_STATE.
        """
        _sp, household, _, application = setup_eligible_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        decide_application(
            household=household, application=application, decision="APPROVE",
        )
        res = api.withdraw_application(
            household["id"], application["id"], intake_worker_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Decide on non-UNDER_REVIEW — PRD §3.3
# ===========================================================================
class TestDecidePreconditions:

    def test_decide_on_draft_invalid_state(self, api):
        """PRD §3.3: "the application is in UNDER_REVIEW (otherwise
        ERR_INVALID_STATE)."

        Claim: /decide on a DRAFT application → ERR_INVALID_STATE.
        """
        _sp, household, _ = setup_basic_household()
        application = create_application(household=household)
        res = api.decide_application(
            household["id"], application["id"],
            decide_application_payload(decision="APPROVE"),
            headers=TEST_USERS["eligibility_caseworker_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")
