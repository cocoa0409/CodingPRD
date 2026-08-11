"""Difficulty queue: cross-entity state dependencies."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_account,
    begin_edd_review,
    complete_edd_review,
    create_account,
    create_customer,
    create_edd_review,
    create_rep,
    post_transaction_payload,
    recommend_sar,
    set_clock,
    setup_case_in_state,
    setup_pending_account,
    submit_and_verify_document,
    validate_error,
    validate_success,
)
from test_helpers.test_users import make_rep_headers, make_sar_officer_headers


class TestTransactionPostingRequiresAccountOpen:
    def test_posting_to_pending_account_rejected_not_open(self, api):
        """PRD §3.5: "Posting against an account in `RESTRICTED` is refused with
        `ERR_ACCOUNT_RESTRICTED`; against a `CLOSED` or `DECLINED` account with
        `ERR_ACCOUNT_CLOSED_TERMINAL`; and against an account in any other non-`OPEN`
        state with `ERR_ACCOUNT_NOT_OPEN`."
        A PENDING_APPROVAL account is non-OPEN: the wire is refused with 409.

        Design: Difficulty/cross_entity_state_dependency/transaction_posting_requires_account_open
        """
        ctx = setup_pending_account()
        resp = api_client.post_transaction(
            ctx["account"]["id"],
            post_transaction_payload(txn_type="WIRE_OUT", amount=100.00),
            make_rep_headers(ctx["rep"]["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_OPEN)
        assert error["error_id"] == "ERR_ACCOUNT_NOT_OPEN"
        assert resp.status_code == 409

    def test_identical_payload_succeeds_after_approval(self, api):
        """PRD §3.5: "With an account `OPEN`, a `RegisteredRep` or `OperationsAnalyst`
        posts transactions."
        PRD §3.5: "New transactions normally land in `POSTED`".
        The identical wire payload succeeds once the account is OPEN.

        Design: Difficulty/cross_entity_state_dependency/transaction_posting_requires_account_open
        """
        ctx = setup_pending_account()
        approve_account(ctx["account"]["id"])
        resp = api_client.post_transaction(
            ctx["account"]["id"],
            post_transaction_payload(txn_type="WIRE_OUT", amount=100.00),
            make_rep_headers(ctx["rep"]["id"]),
        )
        txn = validate_success(resp, expected_status=201)
        assert txn["status"] == "POSTED"


class TestHighTierApprovalRequiresApprovedEdd:
    def _setup_high_account_with_edd(self):
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep Q", crd_number="CRD-CE2")
        customer = create_customer(
            rep,
            customer_type="INDIVIDUAL",
            full_name="Q Pep",
            tax_id="TIN-CE2",
            country_risk_tier="HIGH",
            is_pep=True,
        )
        submit_and_verify_document(customer["id"], rep, document_number="P-CE2")
        account = create_account(
            customer["id"], rep,
            product_set=["LOW_PRICED_SECURITIES", "MARGIN", "OPTIONS"],
        )
        review = create_edd_review(
            account["id"],
            period_start="2026-04-01",
            period_end="2026-05-01",
            trigger_reason="HIGH tier onboarding",
        )
        return account, review

    def test_pending_or_in_review_edd_blocks_approval(self, api):
        """PRD §3.3: "Fourth, a `HIGH`-tier account requires an `APPROVED` EDD review
        for the account before approval, else `ERR_EDD_APPROVAL_REQUIRED`."
        PRD §3.3: "a score of at least 70 yields `HIGH`" — 25 country + 20 PEP +
        25 capped products = 70 lands HIGH at the inclusive boundary.
        Neither a PENDING nor an IN_REVIEW review satisfies the gate.

        Design: Difficulty/cross_entity_state_dependency/high_tier_approval_requires_approved_edd
        """
        account, review = self._setup_high_account_with_edd()
        assert account["risk_score"] == 70, (
            f"score must be 70 at the inclusive HIGH boundary, got {account['risk_score']}"
        )
        assert account["risk_tier"] == "HIGH"

        resp = api_client.approve_account(account["id"], TEST_USERS["officer_headers"])
        error = validate_error(resp, ApiErrorId.ERR_EDD_APPROVAL_REQUIRED)
        assert error["error_id"] == "ERR_EDD_APPROVAL_REQUIRED"

        begin_edd_review(review["id"])
        resp = api_client.approve_account(account["id"], TEST_USERS["officer_headers"])
        error = validate_error(resp, ApiErrorId.ERR_EDD_APPROVAL_REQUIRED)
        assert error["error_id"] == "ERR_EDD_APPROVAL_REQUIRED", (
            "an IN_REVIEW review still does not satisfy the approval gate"
        )

    def test_approved_edd_unblocks_approval_and_fixes_refresh_schedule(self, api):
        """PRD §3.4: "A completion with decision `APPROVED` captures
        `tier_at_completion` from the account's current `risk_tier` — immutable
        thereafter — and schedules `refresh_due_date` as the completion date plus an
        interval fixed by that captured tier: twelve calendar months for `HIGH`,
        twenty-four for `MEDIUM`, thirty-six for `LOW`, preserving the day of month."
        Completing 2026-05-01 at HIGH fixes refresh due 2027-05-01; the approval gate
        then passes and the account opens.

        Design: Difficulty/cross_entity_state_dependency/high_tier_approval_requires_approved_edd
        """
        account, review = self._setup_high_account_with_edd()
        begin_edd_review(review["id"])
        completed = complete_edd_review(
            review["id"], "APPROVED", notes="verified source of funds"
        )
        assert completed["status"] == "APPROVED"
        assert completed["tier_at_completion"] == "HIGH"
        assert completed["refresh_due_date"] == "2027-05-01", (
            f"HIGH interval is 12 months from 2026-05-01, got {completed['refresh_due_date']}"
        )

        approved = approve_account(account["id"])
        assert approved["lifecycle_status"] == "OPEN"


class TestSarDraftRequiresCaseSarRecommended:
    def test_initial_draft_on_investigating_case_rejected(self, api):
        """PRD §3.6: "An *initial* filing — one with no `prior_filing_id` — requires
        its case to be in `SAR_RECOMMENDED`, else `ERR_CASE_NOT_SAR_RECOMMENDED`".

        Design: Difficulty/cross_entity_state_dependency/sar_draft_requires_case_sar_recommended
        """
        ctx = setup_case_in_state("INVESTIGATING")
        resp = api_client.create_sar_filing(
            {
                "case_id": ctx["case"]["id"],
                "narrative": "early draft",
                "activity_start": "2026-05-01",
                "activity_end": "2026-05-01",
            },
            TEST_USERS["sar_officer_headers"],
        )
        error = validate_error(resp, ApiErrorId.ERR_CASE_NOT_SAR_RECOMMENDED)
        assert error["error_id"] == "ERR_CASE_NOT_SAR_RECOMMENDED"
        assert resp.status_code == 409

    def test_identical_draft_succeeds_after_recommendation(self, api):
        """PRD §3.6: "When the evidence supports reporting, the analyst recommends a
        SAR, moving `INVESTIGATING` → `SAR_RECOMMENDED` and supplying
        `recommendation_note` and `initial_detection_date`".
        PRD §3.6: "A draft is created with `case_id`, `narrative`, `activity_start`,
        and `activity_end` (which must not precede the start, else
        `ERR_INVALID_DATE_RANGE`), entering `DRAFT`."

        Design: Difficulty/cross_entity_state_dependency/sar_draft_requires_case_sar_recommended
        """
        ctx = setup_case_in_state("INVESTIGATING")
        recommend_sar(
            ctx["case"]["id"],
            analyst_id="analyst-ce3",
            initial_detection_date="2026-05-01",
            recommendation_note="file",
        )
        resp = api_client.create_sar_filing(
            {
                "case_id": ctx["case"]["id"],
                "narrative": "early draft",
                "activity_start": "2026-05-01",
                "activity_end": "2026-05-01",
            },
            make_sar_officer_headers("saroff-ce3"),
        )
        sar = validate_success(resp, expected_status=201)
        assert sar["status"] == "DRAFT"
