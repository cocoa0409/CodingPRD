"""Queue A — resource_temporal_overlap.

Instances:
  - nav_period_open_excludes_second_open_period
  - side_letter_supersession_requires_active_target
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_fund_payload,
    create_nav_period_payload,
    create_side_letter_payload,
    get_subscription,
    setup_accepted_subscription,
    validate_error,
    validate_success,
)

FA = TEST_USERS["fund_admin_headers"]


class TestNavPeriodOpenExclusion:
    """Two tests for Difficulty/resource_temporal_overlap/nav_period_open_excludes_second_open_period."""

    def test_second_open_period_rejected_with_invalid_state(self, api, fund_admin_headers):
        """PRD §3.6: "Only one period may be OPEN at a time per fund."
        Attempting to open a second while one is OPEN is rejected. PRD §2.9
        pins state-validity failures to ERR_INVALID_STATE.

        Design: Difficulty/resource_temporal_overlap/nav_period_open_excludes_second_open_period
        """
        fund = validate_success(api.create_fund(create_fund_payload(), fund_admin_headers), 201)
        api.create_nav_period(
            fund["id"],
            create_nav_period_payload(period_end_utc="2026-08-31T23:59:59Z"),
            fund_admin_headers,
        )
        resp = api.create_nav_period(
            fund["id"],
            create_nav_period_payload(period_end_utc="2026-09-30T23:59:59Z"),
            fund_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_open_period_after_close_is_allowed(self, api, fund_admin_headers):
        """PRD §3.6: "Only one period may be OPEN at a time per fund."
        Closure auto-opens the next period, so a new period may exist OPEN
        after the previous one CLOSED.

        Design: Difficulty/resource_temporal_overlap/nav_period_open_excludes_second_open_period
        """
        # Create an accepted subscription so close has a capital account.
        ctx = setup_accepted_subscription(commitment_amount_cents=100000)
        fund = ctx["fund"]
        nav_period = ctx["nav_period"]
        from test_helpers import get_fund
        fund_now = get_fund(fund["id"])
        api.finalize_nav_period(
            fund["id"], nav_period["id"],
            {"gross_return_bps": 0, "expected_fund_version": fund_now["version"]},
            fund_admin_headers,
        )
        resp = api.close_nav_period(fund["id"], nav_period["id"], fund_admin_headers)
        closed = validate_success(resp, 200)
        assert closed["status"] == "CLOSED"

        # Fund now has a new OPEN period (auto-opened by close). Verify by
        # checking that a fresh manual open is still rejected (one OPEN slot
        # is taken by the auto-opened period).
        resp2 = api.create_nav_period(
            fund["id"],
            create_nav_period_payload(period_end_utc="2026-10-31T23:59:59Z"),
            fund_admin_headers,
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)


class TestSideLetterSupersession:
    """Two tests for Difficulty/resource_temporal_overlap/side_letter_supersession_requires_active_target."""

    def _build_chain(self):
        """Subscription ACCEPTED + L1 EXECUTED + L2 EXECUTED superseding L1."""
        ctx = setup_accepted_subscription(commitment_amount_cents=500000)
        fund = ctx["fund"]
        sub = ctx["subscription"]

        l1 = validate_success(
            api_client.create_side_letter(
                fund["id"],
                create_side_letter_payload(subscription_id=sub["id"], terms_document_id="L1"),
                FA,
            ),
            201,
        )
        sv1 = get_subscription(fund["id"], sub["id"])["version"]
        api_client.execute_side_letter(
            fund["id"], l1["id"], {"expected_subscription_version": sv1}, FA
        )
        l2 = validate_success(
            api_client.create_side_letter(
                fund["id"],
                create_side_letter_payload(
                    subscription_id=sub["id"],
                    terms_document_id="L2",
                    supersedes_side_letter_id=l1["id"],
                ),
                FA,
            ),
            201,
        )
        sv2 = get_subscription(fund["id"], sub["id"])["version"]
        api_client.execute_side_letter(
            fund["id"], l2["id"], {"expected_subscription_version": sv2}, FA
        )
        ctx["l1"] = l1
        ctx["l2"] = l2
        return ctx

    def test_superseding_already_superseded_letter_rejected(self, api, fund_admin_headers):
        """PRD §3.5: "When supersedes_side_letter_id is provided, it must
        reference an EXECUTED side letter owned by the same investor as the
        new letter's subscription; otherwise creation is rejected with
        ERR_INVALID_SUPERSESSION."

        Design: Difficulty/resource_temporal_overlap/side_letter_supersession_requires_active_target
        """
        ctx = self._build_chain()
        # At this point L1 has been SUPERSEDED by L2. Try to supersede L1 again.
        resp = api.create_side_letter(
            ctx["fund"]["id"],
            create_side_letter_payload(
                subscription_id=ctx["subscription"]["id"],
                terms_document_id="L3",
                supersedes_side_letter_id=ctx["l1"]["id"],
            ),
            fund_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SUPERSESSION)

    def test_superseding_head_of_chain_succeeds(self, api, fund_admin_headers):
        """PRD §3.5: supersedes_side_letter_id must reference an EXECUTED
        side letter. L2 is the current EXECUTED head; superseding it is
        valid and transitions L2 to SUPERSEDED.

        Design: Difficulty/resource_temporal_overlap/side_letter_supersession_requires_active_target
        """
        ctx = self._build_chain()
        l3 = validate_success(
            api.create_side_letter(
                ctx["fund"]["id"],
                create_side_letter_payload(
                    subscription_id=ctx["subscription"]["id"],
                    terms_document_id="L3",
                    supersedes_side_letter_id=ctx["l2"]["id"],
                ),
                fund_admin_headers,
            ),
            201,
        )
        sv3 = get_subscription(ctx["fund"]["id"], ctx["subscription"]["id"])["version"]
        resp = api.execute_side_letter(
            ctx["fund"]["id"], l3["id"],
            {"expected_subscription_version": sv3},
            fund_admin_headers,
        )
        executed = validate_success(resp, 200)
        assert executed["status"] == "EXECUTED"
        # L2 must now be SUPERSEDED.
        l2_after = validate_success(
            api.get_side_letter(ctx["fund"]["id"], ctx["l2"]["id"], fund_admin_headers), 200
        )
        assert l2_after["status"] == "SUPERSEDED"
