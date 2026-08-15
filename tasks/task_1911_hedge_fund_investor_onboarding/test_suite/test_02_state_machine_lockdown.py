"""State machine integrity: invalid transitions, terminal-state lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_fund_payload,
    create_share_class_payload,
    create_investor_payload,
    create_kyc_case_payload,
    create_subscription_payload,
    create_funding_payload,
    create_nav_period_payload,
    create_redemption_payload,
    setup_accepted_subscription,
    setup_fund_with_class_and_period,
    get_fund,
    get_success_data,
    validate_error,
    validate_success,
)


class TestSubscriptionInvalidTransition:
    def test_subscription_submit_from_accepted_returns_invalid_state(
        self, api, fund_admin_headers, transfer_agent_headers
    ):
        """PRD §2.9: "state validity (ERR_INVALID_STATE)". Once a subscription
        has been ACCEPTED, submit is not a valid outgoing transition.

        Design: Corner/state_machines/subscription_submit_from_accepted_returns_invalid_state
        """
        ctx = setup_accepted_subscription()
        fund = ctx["fund"]
        sub = ctx["subscription"]
        # sub is ACCEPTED here. Submitting again must fail.
        resp = api.submit_subscription(fund["id"], sub["id"], transfer_agent_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSubscriptionTerminalLockdown:
    def test_cancelled_subscription_terminal_no_further_transitions(
        self,
        api,
        fund_admin_headers,
        transfer_agent_headers,
        compliance_officer_headers,
    ):
        """PRD §2.9: "state validity (ERR_INVALID_STATE)". A CANCELLED
        subscription is terminal; any further transition is rejected.

        Design: Corner/state_machines/cancelled_subscription_terminal_no_further_transitions
        """
        fund = validate_success(api.create_fund(create_fund_payload(), fund_admin_headers), 201)
        cls = validate_success(
            api.create_share_class(
                fund["id"],
                create_share_class_payload(
                    min_initial_investment_cents=100,
                    min_additional_investment_cents=50,
                ),
                fund_admin_headers,
            ),
            201,
        )
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        sub = validate_success(
            api.create_subscription(
                fund["id"],
                create_subscription_payload(
                    investor_id=inv["id"],
                    share_class_id=cls["id"],
                    commitment_amount_cents=500,
                    funding_deadline_utc="2026-08-05T00:00:00Z",
                ),
                fund_admin_headers,
            ),
            201,
        )
        api.submit_subscription(fund["id"], sub["id"], transfer_agent_headers)
        api.compliance_approve_subscription(fund["id"], sub["id"], compliance_officer_headers)
        api.record_funding(
            fund["id"], sub["id"],
            create_funding_payload(amount_cents=100, received_at_utc="2026-08-04T00:00:00Z"),
            transfer_agent_headers,
        )
        # Advance clock past the deadline, then cancel.
        api.set_current_utc({"to_iso8601": "2026-08-10T00:00:00Z"}, fund_admin_headers)
        cancel_resp = api.cancel_subscription(fund["id"], sub["id"], fund_admin_headers)
        cancelled = validate_success(cancel_resp, 200)
        assert cancelled["status"] == "CANCELLED"

        # Any further transition attempt must fail.
        resp = api.submit_subscription(fund["id"], sub["id"], transfer_agent_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestKycCaseInitialState:
    def test_new_kyc_case_initial_state_open(
        self, api, fund_admin_headers, compliance_officer_headers
    ):
        """PRD §3.2: "Each case receives a case_sequence (1-based within the
        investor) and starts in OPEN, then immediately auto-transitions to
        AWAITING_DOCUMENTS."

        Design: Corner/state_machines/new_kyc_case_initial_state_open
        """
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        resp = api.create_kyc_case(
            inv["id"], create_kyc_case_payload(), compliance_officer_headers
        )
        case = validate_success(resp, 201)
        # The auto-transition is permitted to run synchronously; either initial
        # OPEN or post-auto-transition AWAITING_DOCUMENTS is faithful to PRD.
        assert case["status"] in ("OPEN", "AWAITING_DOCUMENTS")


class TestRedemptionCancelAfterSettle:
    def test_redemption_cancel_after_settle_returns_invalid_state(
        self,
        api,
        fund_admin_headers,
        transfer_agent_headers,
    ):
        """PRD §3.7: "Cancellation transitions the request from PENDING to
        CANCELLED." Once SETTLED, the request cannot be cancelled — the state
        machine permits cancel only from PENDING, so this fails with
        ERR_INVALID_STATE.

        Design: Corner/state_machines/redemption_cancel_after_settle_returns_invalid_state
        """
        ctx = setup_accepted_subscription(
            fund_overrides={"gate_threshold_pct": 0.50},
            commitment_amount_cents=500000,
        )
        fund = ctx["fund"]
        nav_period = ctx["nav_period"]
        investor = ctx["investor"]
        capital_account = ctx["capital_account"]

        red = validate_success(
            api.create_redemption(
                fund["id"],
                create_redemption_payload(
                    capital_account_id=capital_account["id"],
                    requested_amount_cents=100000,
                    requested_effective_period_id=nav_period["id"],
                ),
                transfer_agent_headers,
            ),
            201,
        )
        api.approve_redemption(fund["id"], red["id"], fund_admin_headers)
        fund_now = get_fund(fund["id"])
        api.finalize_nav_period(
            fund["id"], nav_period["id"],
            {"gross_return_bps": 0, "expected_fund_version": fund_now["version"]},
            fund_admin_headers,
        )
        api.close_nav_period(fund["id"], nav_period["id"], fund_admin_headers)

        # Now red is SETTLED. Investor cancel must fail.
        from test_helpers import make_investor_headers
        resp = api.cancel_redemption(
            fund["id"], red["id"], make_investor_headers(investor["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestKycApproveIdempotency:
    def test_idempotent_double_kyc_approve_returns_invalid_state(
        self, api, fund_admin_headers, compliance_officer_headers
    ):
        """PRD §3.2: KycCase transitions from IN_REVIEW to APPROVED via the
        approve endpoint. A second approve on an already-APPROVED case is not
        a permitted transition and fails with ERR_INVALID_STATE.

        Design: Corner/state_machines/idempotent_double_kyc_approve_returns_invalid_state
        """
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        kyc = validate_success(
            api.create_kyc_case(inv["id"], create_kyc_case_payload(), compliance_officer_headers),
            201,
        )
        # Submit all required documents to reach IN_REVIEW.
        for doc in kyc["required_documents"]:
            api.submit_kyc_document(
                inv["id"], kyc["id"],
                {"document_type": doc, "document_reference": f"ref-{doc}"},
                compliance_officer_headers,
            )
        first = api.approve_kyc_case(inv["id"], kyc["id"], {}, compliance_officer_headers)
        approved = validate_success(first, 200)
        assert approved["status"] == "APPROVED"

        # Second approve is not a valid outgoing transition from APPROVED.
        resp = api.approve_kyc_case(inv["id"], kyc["id"], {}, compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
