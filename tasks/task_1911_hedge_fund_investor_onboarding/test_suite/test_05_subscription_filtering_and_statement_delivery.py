"""Endpoint behaviors: list filtering, statement delivery."""
from test_helpers import (
    api_client,
    create_fund_payload,
    create_share_class_payload,
    create_investor_payload,
    create_subscription_payload,
    setup_accepted_subscription,
    get_fund,
    list_capital_accounts,
    list_statements,
    validate_paginated,
    validate_success,
)


class TestSubscriptionListFiltering:
    def test_subscription_list_filter_by_status(self, api, fund_admin_headers):
        """PRD §4 (subscriptions list endpoint): "GET
        /funds/{id}/subscriptions" accepts a status filter. PRD §3.4: a
        newly-created subscription "starts in DRAFT."

        Design: Corner/endpoints/subscription_list_filter_by_status
        """
        fund = validate_success(api.create_fund(create_fund_payload(), fund_admin_headers), 201)
        cls = validate_success(
            api.create_share_class(
                fund["id"],
                create_share_class_payload(
                    min_initial_investment_cents=100, min_additional_investment_cents=50
                ),
                fund_admin_headers,
            ),
            201,
        )
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        validate_success(
            api.create_subscription(
                fund["id"],
                create_subscription_payload(
                    investor_id=inv["id"], share_class_id=cls["id"],
                    commitment_amount_cents=500, funding_deadline_utc="2026-08-10T00:00:00Z",
                ),
                fund_admin_headers,
            ),
            201,
        )
        resp = api.list_subscriptions(fund["id"], fund_admin_headers, params={"status": "DRAFT"})
        data, _meta = validate_paginated(resp)
        assert len(data) >= 1
        for sub in data:
            assert sub["status"] == "DRAFT", (
                f"Expected only DRAFT subscriptions, got status={sub['status']}"
            )


class TestStatementDelivery:
    def test_statement_deliver_marks_delivered_at(
        self, api, fund_admin_headers, transfer_agent_headers
    ):
        """PRD §3.8: "A TransferAgent or FundAdmin marks a statement
        delivered, which stamps delivered_at_utc from the logical clock and
        transitions the statement to DELIVERED."

        Design: Corner/endpoints/statement_deliver_marks_delivered_at
        """
        ctx = setup_accepted_subscription(
            fund_overrides={"gate_threshold_pct": 0.50},
            commitment_amount_cents=100000,
        )
        fund = ctx["fund"]
        nav_period = ctx["nav_period"]
        investor = ctx["investor"]
        capital_account = ctx["capital_account"]

        # Finalize and close to trigger statement generation.
        fund_now = get_fund(fund["id"])
        api.finalize_nav_period(
            fund["id"], nav_period["id"],
            {"gross_return_bps": 0, "expected_fund_version": fund_now["version"]},
            fund_admin_headers,
        )
        api.close_nav_period(fund["id"], nav_period["id"], fund_admin_headers)

        # Pull the statement created at close.
        stmts = list_statements(investor["id"], capital_account["id"])
        assert len(stmts) >= 1, "Expected at least one statement after period close"
        stmt = stmts[0]

        resp = api.deliver_statement(
            investor["id"], capital_account["id"], stmt["id"], transfer_agent_headers
        )
        delivered = validate_success(resp, 200)
        assert delivered["status"] == "DELIVERED"
        assert delivered.get("delivered_at_utc"), "delivered_at_utc must be stamped"
