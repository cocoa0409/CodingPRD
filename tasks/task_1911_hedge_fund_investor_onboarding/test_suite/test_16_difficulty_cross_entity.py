"""Queue A — cross_entity_state_dependency.

Instances:
  - subscription_accept_requires_open_nav_period
  - side_letter_execute_requires_subscription_accepted
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_fund_payload,
    create_share_class_payload,
    create_investor_payload,
    create_subscription_payload,
    create_funding_payload,
    create_side_letter_payload,
    get_fund,
    get_subscription,
    setup_accepted_subscription,
    validate_error,
    validate_success,
)

FA = TEST_USERS["fund_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
TA = TEST_USERS["transfer_agent_headers"]


def _build_funded_sub_no_period():
    """Subscription driven to FUNDED under a fund with NO open NavPeriod."""
    fund = validate_success(api_client.create_fund(create_fund_payload(), FA), 201)
    cls = validate_success(
        api_client.create_share_class(fund["id"], create_share_class_payload(), FA), 201
    )
    inv = validate_success(api_client.create_investor(create_investor_payload(), FA), 201)
    sub = validate_success(
        api_client.create_subscription(
            fund["id"],
            create_subscription_payload(
                investor_id=inv["id"], share_class_id=cls["id"],
                commitment_amount_cents=200000,
                funding_deadline_utc="2026-08-10T00:00:00Z",
            ),
            FA,
        ),
        201,
    )
    api_client.submit_subscription(fund["id"], sub["id"], TA)
    api_client.compliance_approve_subscription(fund["id"], sub["id"], CO)
    api_client.record_funding(
        fund["id"], sub["id"],
        create_funding_payload(amount_cents=200000, received_at_utc="2026-08-05T00:00:00Z"),
        TA,
    )
    return {"fund": fund, "sub": sub}


class TestAcceptRequiresOpenNavPeriod:
    """Two tests for Difficulty/cross_entity_state_dependency/subscription_accept_requires_open_nav_period."""

    def test_accept_without_open_nav_period_rejected(self, api, fund_admin_headers):
        """PRD §3.4: "the fund must have an open NAV period —
        Fund.current_nav_period_id must not be null — else the acceptance
        is rejected with ERR_NO_OPEN_NAV_PERIOD."

        Design: Difficulty/cross_entity_state_dependency/subscription_accept_requires_open_nav_period
        """
        ctx = _build_funded_sub_no_period()
        fv = get_fund(ctx["fund"]["id"])["version"]
        resp = api.accept_subscription(
            ctx["fund"]["id"], ctx["sub"]["id"],
            {"expected_fund_version": fv},
            fund_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_NAV_PERIOD)

    def test_accept_with_open_nav_period_succeeds(self, api, fund_admin_headers):
        """PRD §3.4: "the fund must have an open NAV period". When the fund
        does have one open, accept succeeds and transitions the subscription
        to ACCEPTED.

        Design: Difficulty/cross_entity_state_dependency/subscription_accept_requires_open_nav_period
        """
        ctx = setup_accepted_subscription(commitment_amount_cents=200000)
        assert ctx["subscription"]["status"] == "ACCEPTED"


class TestSideLetterExecuteRequiresAcceptedSubscription:
    """Two tests for Difficulty/cross_entity_state_dependency/side_letter_execute_requires_subscription_accepted."""

    def _build_partial_funding_sub_with_letter(self):
        """Subscription in FUNDING_PARTIAL (not ACCEPTED) + a DRAFT letter."""
        fund = validate_success(api_client.create_fund(create_fund_payload(), FA), 201)
        cls = validate_success(
            api_client.create_share_class(fund["id"], create_share_class_payload(), FA), 201
        )
        inv = validate_success(api_client.create_investor(create_investor_payload(), FA), 201)
        sub = validate_success(
            api_client.create_subscription(
                fund["id"],
                create_subscription_payload(
                    investor_id=inv["id"], share_class_id=cls["id"],
                    commitment_amount_cents=200000,
                    funding_deadline_utc="2026-08-10T00:00:00Z",
                ),
                FA,
            ),
            201,
        )
        api_client.submit_subscription(fund["id"], sub["id"], TA)
        api_client.compliance_approve_subscription(fund["id"], sub["id"], CO)
        api_client.record_funding(
            fund["id"], sub["id"],
            create_funding_payload(amount_cents=100000, received_at_utc="2026-08-05T00:00:00Z"),
            TA,
        )
        # Subscription is now FUNDING_PARTIAL. Create a DRAFT side letter.
        sl = validate_success(
            api_client.create_side_letter(
                fund["id"],
                create_side_letter_payload(subscription_id=sub["id"], terms_document_id="d1"),
                FA,
            ),
            201,
        )
        return {"fund": fund, "sub": sub, "sl": sl}

    def test_execute_on_partial_funding_subscription_rejected(self, api, fund_admin_headers):
        """PRD §3.5: "The parent subscription must be in ACCEPTED status."
        A DRAFT letter on a FUNDING_PARTIAL subscription cannot be executed;
        PRD §2.9 pins state-validity failures to ERR_INVALID_STATE.

        Design: Difficulty/cross_entity_state_dependency/side_letter_execute_requires_subscription_accepted
        """
        ctx = self._build_partial_funding_sub_with_letter()
        sub_v = get_subscription(ctx["fund"]["id"], ctx["sub"]["id"])["version"]
        resp = api.execute_side_letter(
            ctx["fund"]["id"], ctx["sl"]["id"],
            {"expected_subscription_version": sub_v},
            fund_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_execute_on_accepted_subscription_succeeds(self, api, fund_admin_headers):
        """PRD §3.5: "Execution transitions the letter from DRAFT to
        EXECUTED and is performed by a FundAdmin. The parent subscription
        must be in ACCEPTED status."

        Design: Difficulty/cross_entity_state_dependency/side_letter_execute_requires_subscription_accepted
        """
        ctx = setup_accepted_subscription(commitment_amount_cents=200000)
        fund = ctx["fund"]
        sub = ctx["subscription"]

        sl = validate_success(
            api.create_side_letter(
                fund["id"],
                create_side_letter_payload(subscription_id=sub["id"], terms_document_id="d1"),
                fund_admin_headers,
            ),
            201,
        )
        sub_now = get_subscription(fund["id"], sub["id"])
        resp = api.execute_side_letter(
            fund["id"], sl["id"],
            {"expected_subscription_version": sub_now["version"]},
            fund_admin_headers,
        )
        executed = validate_success(resp, 200)
        assert executed["status"] == "EXECUTED"
