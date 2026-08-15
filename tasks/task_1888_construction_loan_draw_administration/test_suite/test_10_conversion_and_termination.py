"""Conversion to permanent financing and early termination."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_approved_release,
    create_conversion_review,
    create_draw,
    get_budget_line,
    get_loan,
    review_decision_payload,
    setup_completion_inspection,
    setup_conversion_ready_scenario,
    setup_funded_scenario,
    setup_loan_with_lines,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["lender_admin_headers"]
OFFICER = TEST_USERS["credit_officer_headers"]
SERVICER = TEST_USERS["loan_servicer_headers"]


class TestConversionBranches:
    def test_conversion_decline_branch_has_no_side_effects(self, api):
        """PRD §3.9: "Adjudication belongs to the `CreditOfficer`, whose `decision`
        of `DECLINED` takes a `reason`, recorded as the review's `decline_reason`,
        and closes the review as `DECLINED`."
        PRD §3.9: "Only one conversion review may be open per loan: if a review in
        `REQUESTED` or `APPROVED` already exists, the new request is rejected with
        `ERR_CONVERSION_IN_PROGRESS` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/conversion_decline_branch_vs_convert_branch
        """
        sc = setup_conversion_ready_scenario(reserve_cents=95_000)
        cr1 = create_conversion_review(sc)
        declined = validate_success(api.review_conversion_review(
            cr1["id"],
            review_decision_payload("DECLINED", reason="Appraisal stale"),
            OFFICER,
        ), 200)
        assert declined["status"] == "DECLINED", "The decline branch closes the review"
        assert declined["decline_reason"] == "Appraisal stale"

        loan = get_loan(sc["loan"]["id"])
        assert loan["status"] == "OPEN", "Declining fires no loan cascade"
        assert loan["interest_reserve_balance_cents"] == 95_000
        assert get_budget_line(sc["lines"]["SITE"]["id"])["status"] == "ACTIVE"

        # A DECLINED review is closed: a fresh review may be opened.
        cr2 = create_conversion_review(sc)
        assert cr2["status"] == "REQUESTED"

    def test_conversion_convert_branch_fires_cascade(self, api):
        """PRD §3.9: "Execution belongs to the `LoanServicer`, who supplies the
        permanent terms — `permanent_interest_rate_annual_bps` and
        `permanent_term_months` — on an `APPROVED` review. The terms are recorded
        on the review, which settles `CONVERTED`, and copied onto the loan's own
        `permanent_interest_rate_annual_bps` and `permanent_term_months`. Executing
        conversion fires the loan's completion cascade: the loan moves from `OPEN`
        to `CONVERTED`; every `ACTIVE` budget line of the loan cascades to `CLOSED`
        with its `version` incrementing; any remaining interest reserve is swept
        back to the borrower by writing a `SWEEP` entry whose `amount_cents` is the
        negative of the remaining balance, growing the loan's
        `interest_reserve_swept_cents` by the swept amount and driving
        `interest_reserve_balance_cents` to zero; and the loan's `version`
        increments by one."

        Design: Difficulty/non_linear_state_machine/conversion_decline_branch_vs_convert_branch
        """
        sc = setup_conversion_ready_scenario(reserve_cents=95_000)
        cr1 = create_conversion_review(sc)
        validate_success(api.review_conversion_review(
            cr1["id"],
            review_decision_payload("DECLINED", reason="Appraisal stale"),
            OFFICER), 200)
        cr2 = create_conversion_review(sc)
        validate_success(api.review_conversion_review(
            cr2["id"], review_decision_payload("APPROVED"), OFFICER), 200)

        converted = validate_success(api.convert_conversion_review(
            cr2["id"],
            {"permanent_interest_rate_annual_bps": 650,
             "permanent_term_months": 360},
            SERVICER,
        ), 200)
        assert converted["status"] == "CONVERTED"
        assert converted["permanent_interest_rate_annual_bps"] == 650, (
            "Terms are recorded on the review"
        )

        loan = get_loan(sc["loan"]["id"])
        assert loan["status"] == "CONVERTED"
        assert loan["permanent_interest_rate_annual_bps"] == 650
        assert loan["permanent_term_months"] == 360, "Terms are copied to the loan"
        assert get_budget_line(sc["lines"]["SITE"]["id"])["status"] == "CLOSED", (
            "Every ACTIVE budget line cascades to CLOSED"
        )
        assert loan["interest_reserve_balance_cents"] == 0
        assert loan["interest_reserve_swept_cents"] == 95_000, (
            "The remaining reserve is swept back to the borrower"
        )


class TestConversionReadiness:
    def _funded_loan_with_conversion_review(self):
        """Funded draw (retained 500000) + ACCEPTED 100.00 completion inspection +
        REQUESTED conversion review."""
        sc = setup_funded_scenario()
        sc["completion_inspection"] = setup_completion_inspection(sc)
        review = create_conversion_review(sc)
        return sc, review

    def test_conversion_approve_blocked_by_retained_balance(self, api):
        """PRD §3.9: "Approval is readiness-gated: the loan must be `OPEN`, or the
        review is rejected with `ERR_LOAN_NOT_OPEN` (HTTP 409); and three
        conditions must all hold, or approval is rejected with
        `ERR_CONVERSION_PRECONDITIONS_UNMET` (HTTP 409) — the loan's
        `retained_cents` is zero, no draw of the loan sits in `DRAFT`, `SUBMITTED`,
        `UNDER_REVIEW`, `REVISION_REQUESTED`, or `APPROVED`, and at least one
        `ACCEPTED` inspection for the loan reports a `percent_complete_reported` of
        exactly 100.00."

        Design: Difficulty/cross_entity_state_dependency/conversion_approve_requires_clean_loan
        """
        sc, review = self._funded_loan_with_conversion_review()
        assert get_loan(sc["loan"]["id"])["retained_cents"] == 500_000

        resp = api.review_conversion_review(
            review["id"], review_decision_payload("APPROVED"), OFFICER)
        validate_error(resp, ApiErrorId.ERR_CONVERSION_PRECONDITIONS_UNMET)

    def test_conversion_approve_unblocked_after_release(self, api):
        """PRD §3.9: "three conditions must all hold, or approval is rejected with
        `ERR_CONVERSION_PRECONDITIONS_UNMET` (HTTP 409) — the loan's
        `retained_cents` is zero, no draw of the loan sits in `DRAFT`, `SUBMITTED`,
        `UNDER_REVIEW`, `REVISION_REQUESTED`, or `APPROVED`, and at least one
        `ACCEPTED` inspection for the loan reports a `percent_complete_reported` of
        exactly 100.00."
        PRD §3.6: "On the loan, `retained_cents` and `principal_disbursed_cents`
        are recomputed".

        Design: Difficulty/cross_entity_state_dependency/conversion_approve_requires_clean_loan
        """
        sc, review = self._funded_loan_with_conversion_review()
        validate_error(api.review_conversion_review(
            review["id"], review_decision_payload("APPROVED"), OFFICER),
            ApiErrorId.ERR_CONVERSION_PRECONDITIONS_UNMET)

        release = create_approved_release(sc, sc["lines"]["SITE"]["id"], 500_000,
                                          reason="Final release")
        validate_success(api.pay_retainage_release(release["id"], SERVICER), 200)
        assert get_loan(sc["loan"]["id"])["retained_cents"] == 0, (
            "The release cascade zeroes the withheld balance"
        )

        approved = validate_success(api.review_conversion_review(
            review["id"], review_decision_payload("APPROVED"), OFFICER), 200)
        assert approved["status"] == "APPROVED", (
            "The same review approves once the loan reads clean"
        )


class TestConversionGuards:
    def test_conversion_in_progress_rejected(self, api):
        """PRD §3.9: "Only one conversion review may be open per loan: if a review
        in `REQUESTED` or `APPROVED` already exists, the new request is rejected
        with `ERR_CONVERSION_IN_PROGRESS` (HTTP 409)."

        Design: Corner/validations/conversion_in_progress_rejected
        """
        sc = setup_loan_with_lines()
        create_conversion_review(sc)
        resp = api.create_conversion_review(
            {"loan_id": sc["loan"]["id"]}, sc["borrower_headers"])
        validate_error(resp, ApiErrorId.ERR_CONVERSION_IN_PROGRESS)

    def test_conversion_declined_terminal_lockdown(self, api):
        """PRD §3.9: "Adjudication belongs to the `CreditOfficer`, whose `decision`
        of `DECLINED` takes a `reason`, recorded as the review's `decline_reason`,
        and closes the review as `DECLINED`."
        PRD §2.6: "A transition attempted from any other state — including from an
        already-terminal state — is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/conversion_declined_terminal_lockdown
        """
        sc = setup_loan_with_lines()
        review = create_conversion_review(sc)
        validate_success(api.review_conversion_review(
            review["id"],
            review_decision_payload("DECLINED", reason="Not ready"),
            OFFICER), 200)

        resp = api.convert_conversion_review(
            review["id"],
            {"permanent_interest_rate_annual_bps": 650,
             "permanent_term_months": 360},
            SERVICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_loan(sc["loan"]["id"])["status"] == "OPEN", (
            "The loan stays OPEN when convert is attempted on a DECLINED review"
        )


class TestTermination:
    def test_terminate_with_activity_rejected(self, api):
        """PRD §3.9: "Termination requires zero activity: `principal_disbursed_cents`
        and `retained_cents` must both be zero; no draw may sit in `DRAFT`,
        `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, or `APPROVED`; no
        reallocation request may sit in `PENDING` or `APPROVED`; no retainage
        release may sit in `REQUESTED` or `APPROVED`; and no conversion review may
        sit in `REQUESTED` or `APPROVED`. Any violation is rejected with
        `ERR_LOAN_HAS_ACTIVITY` (HTTP 409)."

        Design: Corner/validations/terminate_with_activity_rejected
        """
        sc = setup_loan_with_lines()
        create_draw(sc["loan"]["id"], sc["borrower"]["id"])

        resp = api.terminate_loan(sc["loan"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_LOAN_HAS_ACTIVITY)
        assert get_loan(sc["loan"]["id"])["status"] == "OPEN", (
            "A lone DRAFT draw blocks termination"
        )
