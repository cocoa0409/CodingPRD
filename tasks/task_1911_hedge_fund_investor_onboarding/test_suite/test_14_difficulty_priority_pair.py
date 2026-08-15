"""Queue A — priority_pair_validation_conflict.

Instances:
  - state_vs_business_safety_on_kyc_approve
  - temporal_vs_constraint_on_redemption_approve
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_fund_payload,
    create_share_class_payload,
    create_investor_payload,
    create_kyc_case_payload,
    create_subscription_payload,
    create_funding_payload,
    create_nav_period_payload,
    create_redemption_payload,
    get_fund,
    list_capital_accounts,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

FA = TEST_USERS["fund_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
TA = TEST_USERS["transfer_agent_headers"]


class TestStateVsBusinessSafety:
    """Two tests for Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_kyc_approve.

    PRD §2.9 pins the order: state validity (ERR_INVALID_STATE) is evaluated
    before the business rules attached to the specific endpoint (which
    includes the sanctions check producing ERR_SANCTIONS_HIT).
    """

    def test_approve_awaiting_documents_with_sanctions_yields_invalid_state(
        self, api, fund_admin_headers, compliance_officer_headers
    ):
        """PRD §2.9: "The order is: authentication ... then state validity
        (ERR_INVALID_STATE), then the business rules attached to the
        specific endpoint (sanctions, ...)." When a KycCase is in
        AWAITING_DOCUMENTS (not IN_REVIEW) and sanctions_hit is true,
        ERR_INVALID_STATE fires before ERR_SANCTIONS_HIT.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_kyc_approve
        """
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        kyc = validate_success(
            api.create_kyc_case(
                inv["id"],
                create_kyc_case_payload(risk_rating="HIGH", sanctions_hit=True),
                compliance_officer_headers,
            ),
            201,
        )
        # Case is OPEN/AWAITING_DOCUMENTS, NOT IN_REVIEW. sanctions_hit=true
        # would also trigger ERR_SANCTIONS_HIT if state were valid.
        resp = api.approve_kyc_case(inv["id"], kyc["id"], {}, compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_approve_in_review_with_sanctions_yields_sanctions_hit(
        self, api, fund_admin_headers, compliance_officer_headers, transfer_agent_headers
    ):
        """PRD §3.2: "Approving a case from IN_REVIEW requires that
        sanctions_hit be false — a sanctions hit blocks approval outright
        with ERR_SANCTIONS_HIT."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_kyc_approve
        """
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        kyc = validate_success(
            api.create_kyc_case(
                inv["id"],
                create_kyc_case_payload(risk_rating="HIGH", sanctions_hit=True),
                compliance_officer_headers,
            ),
            201,
        )
        # Move toward review by submitting all required docs. PRD §4
        # authorizes only Investor/TransferAgent on the documents endpoint,
        # so submissions must be made as the TransferAgent.
        for doc in kyc["required_documents"]:
            api.submit_kyc_document(
                inv["id"], kyc["id"],
                {"document_type": doc, "document_reference": f"ref-{doc}"},
                transfer_agent_headers,
            )
        # Per PRD §3.2 the case "auto-transitions from IN_REVIEW to
        # ESCALATED" once sanctions_hit is true, so by approve time the case
        # sits in ESCALATED. PRD names ERR_SANCTIONS_HIT for approve from
        # IN_REVIEW but does not name the error for a non-override approve on
        # ESCALATED (§2.9 would also permit ERR_INVALID_STATE) — accept both.
        resp = api.approve_kyc_case(inv["id"], kyc["id"], {}, compliance_officer_headers)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_SANCTIONS_HIT, ApiErrorId.ERR_INVALID_STATE]
        )


class TestTemporalVsConstraintOnRedemptionApprove:
    """Two tests for Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_on_redemption_approve.

    PRD §3.7 lists approval preconditions in order: lockup check before
    notice check.
    """

    def _build_locked_ctx_with_short_notice(self):
        """Capital account whose lockup has not expired; redemption request
        whose notice is also insufficient. Lockup check must fire first."""
        fund = validate_success(
            api_client.create_fund(
                create_fund_payload(lockup_months_default=12, notice_days_default=30),
                FA,
            ),
            201,
        )
        cls = validate_success(
            api_client.create_share_class(
                fund["id"],
                create_share_class_payload(lockup_months=12, notice_days=30,
                                           redemption_frequency="QUARTERLY"),
                FA,
            ),
            201,
        )
        period = validate_success(
            api_client.create_nav_period(
                fund["id"], create_nav_period_payload(period_end_utc="2026-08-31T23:59:59Z"), FA
            ),
            201,
        )
        inv = validate_success(api_client.create_investor(create_investor_payload(), FA), 201)
        sub = validate_success(
            api_client.create_subscription(
                fund["id"],
                create_subscription_payload(
                    investor_id=inv["id"], share_class_id=cls["id"],
                    commitment_amount_cents=500000,
                    funding_deadline_utc="2026-08-05T00:00:00Z",
                ),
                FA,
            ),
            201,
        )
        api_client.submit_subscription(fund["id"], sub["id"], TA)
        api_client.compliance_approve_subscription(fund["id"], sub["id"], CO)
        api_client.record_funding(
            fund["id"], sub["id"],
            create_funding_payload(amount_cents=500000, received_at_utc="2026-08-05T00:00:00Z"),
            TA,
        )
        fv = get_fund(fund["id"])["version"]
        api_client.accept_subscription(
            fund["id"], sub["id"], {"expected_fund_version": fv}, FA
        )
        ca = list_capital_accounts(inv["id"])[0]
        red = validate_success(
            api_client.create_redemption(
                fund["id"],
                create_redemption_payload(
                    capital_account_id=ca["id"],
                    requested_amount_cents=100000,
                    requested_effective_period_id=period["id"],
                ),
                TA,
            ),
            201,
        )
        # Advance clock so notice is also short (1 day before period end).
        api_client.set_current_utc({"to_iso8601": "2026-08-30T00:00:00Z"}, FA)
        return {"fund": fund, "redemption": red}

    def test_lockup_fires_before_insufficient_notice(self, api, fund_admin_headers):
        """PRD §3.7: "Approval enforces, in priority order after the global
        checks: the capital account's locked_until_utc must be at or before
        the current logical time (otherwise ERR_LOCKUP_NOT_EXPIRED); the
        notice given must satisfy the notice requirement (otherwise
        ERR_INSUFFICIENT_NOTICE)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_on_redemption_approve
        """
        ctx = self._build_locked_ctx_with_short_notice()
        resp = api.approve_redemption(
            ctx["fund"]["id"], ctx["redemption"]["id"], fund_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_LOCKUP_NOT_EXPIRED)

    def test_insufficient_notice_fires_when_lockup_satisfied(
        self, api, fund_admin_headers
    ):
        """PRD §3.7: "the notice given must satisfy the notice requirement
        (otherwise ERR_INSUFFICIENT_NOTICE)". When lockup has expired but
        notice is short, ERR_INSUFFICIENT_NOTICE fires.

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_on_redemption_approve
        """
        # Build ctx where lockup_months=0 so lockup already expired, but
        # notice_days=30 with only 1 day before period end.
        fund = validate_success(
            api_client.create_fund(
                create_fund_payload(lockup_months_default=0, notice_days_default=30),
                FA,
            ),
            201,
        )
        cls = validate_success(
            api_client.create_share_class(
                fund["id"],
                create_share_class_payload(lockup_months=0, notice_days=30,
                                           redemption_frequency="QUARTERLY"),
                FA,
            ),
            201,
        )
        period = validate_success(
            api_client.create_nav_period(
                fund["id"],
                create_nav_period_payload(period_end_utc="2026-08-31T23:59:59Z"),
                FA,
            ),
            201,
        )
        inv = validate_success(api_client.create_investor(create_investor_payload(), FA), 201)
        sub = validate_success(
            api_client.create_subscription(
                fund["id"],
                create_subscription_payload(
                    investor_id=inv["id"], share_class_id=cls["id"],
                    commitment_amount_cents=500000,
                    funding_deadline_utc="2026-08-05T00:00:00Z",
                ),
                FA,
            ),
            201,
        )
        api_client.submit_subscription(fund["id"], sub["id"], TA)
        api_client.compliance_approve_subscription(fund["id"], sub["id"], CO)
        api_client.record_funding(
            fund["id"], sub["id"],
            create_funding_payload(amount_cents=500000, received_at_utc="2026-08-04T00:00:00Z"),
            TA,
        )
        fv = get_fund(fund["id"])["version"]
        api_client.accept_subscription(
            fund["id"], sub["id"], {"expected_fund_version": fv}, FA
        )
        ca = list_capital_accounts(inv["id"])[0]
        # Move clock to 1 day before period end.
        api_client.set_current_utc({"to_iso8601": "2026-08-30T00:00:00Z"}, FA)
        red = validate_success(
            api_client.create_redemption(
                fund["id"],
                create_redemption_payload(
                    capital_account_id=ca["id"],
                    requested_amount_cents=100000,
                    requested_effective_period_id=period["id"],
                ),
                TA,
            ),
            201,
        )
        resp = api_client.approve_redemption(fund["id"], red["id"], fund_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_NOTICE)
