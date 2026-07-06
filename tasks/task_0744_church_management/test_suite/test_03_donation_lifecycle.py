"""Donation state machine: post, refund, mark-failed, cyclic pledge revert."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_household, create_adult_member,
    create_and_activate_campaign, create_pledge, create_donation,
    setup_fulfilled_pledge,
)


class TestDonationInvalidStateRepost:
    def test_post_on_already_posted_donation_rejected(self, api):
        """PRD §2.8 rung 5: "The target resource must be in a state that
        admits the requested transition; otherwise ERR_INVALID_STATE (HTTP
        409)."
        PRD §3.3: "CASH and CHECK gifts auto-post at create: the create
        returns HTTP 201 with status POSTED..."

        Design: Corner/state_machines/donation_post_from_posted_returns_invalid_state
        """
        set_clock("2026-06-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        d = create_donation(m["id"], 5_000, "2026-06-01",
                            payment_method="CHECK")
        assert d["status"] == "POSTED", (
            f"CHECK donation should auto-post, got status={d['status']}"
        )
        resp = api.post_donation(d["id"], TEST_USERS["finance_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPledgeCancelTerminalState:
    def test_cancel_on_cancelled_pledge_rejected(self, api):
        """PRD §3.3: "the cancel is rejected with ERR_INVALID_STATE if the
        pledge is not ACTIVE..."

        Design: Corner/state_machines/pledge_cancel_on_cancelled_returns_invalid_state
        """
        set_clock("2026-06-15T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        c = create_and_activate_campaign()
        p = create_pledge(c["id"], m["id"], pledged_amount_cents=10_000)
        first = api.cancel_pledge(p["id"], TEST_USERS["finance_admin_headers"])
        validate_success(first)
        resp = api.cancel_pledge(p["id"], TEST_USERS["finance_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPledgeAutoFulfillBoundary:
    def test_posted_donation_equal_to_pledge_amount_fulfills(self, api):
        """PRD §3.3: "It reaches FULFILLED automatically when a donation
        posts pushes received_amount_cents up to or beyond
        pledged_amount_cents; this transition is a system-driven side
        effect of the donation posting, and it bumps the campaign's
        fulfilled_pledge_count by one."

        Design: Corner/state_machines/pledge_active_to_fulfilled_bubble_up_on_boundary
        """
        set_clock("2026-06-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        c = create_and_activate_campaign(target_amount_cents=100_000)
        p = create_pledge(c["id"], m["id"], pledged_amount_cents=5_000)
        create_donation(m["id"], 5_000, "2026-06-01",
                        payment_method="CHECK",
                        campaign_id=c["id"], pledge_id=p["id"])
        pledge = validate_success(
            api.get_pledge(p["id"], TEST_USERS["finance_admin_headers"])
        )
        campaign = validate_success(
            api.get_pledge_campaign(c["id"],
                                    TEST_USERS["finance_admin_headers"])
        )
        assert pledge["status"] == "FULFILLED"
        assert campaign["fulfilled_pledge_count"] == 1


class TestPledgeCyclicRevertOnRefund:
    def test_refund_reverts_fulfilled_pledge_to_active(self, api):
        """PRD §3.3: "the pledge returns from FULFILLED to ACTIVE
        automatically when a donation refund pulls received_amount_cents
        back below pledged_amount_cents, at which moment the campaign's
        fulfilled_pledge_count decrements by one."

        Design: Difficulty/non_linear_state_machine/pledge_cyclic_fulfilled_to_active_on_refund
        """
        h, m, c, p, d = setup_fulfilled_pledge(
            pledged_amount_cents=10_000,
            donation_date="2026-06-01",
            clock="2026-06-15T00:00:00Z",
        )
        assert d["status"] == "POSTED"
        pledge_before = validate_success(
            api.get_pledge(p["id"], TEST_USERS["finance_admin_headers"])
        )
        assert pledge_before["status"] == "FULFILLED"

        refund_resp = api.refund_donation(d["id"],
                                          TEST_USERS["finance_admin_headers"])
        donation_after = validate_success(refund_resp)
        assert donation_after["status"] == "REFUNDED"

        pledge_after = validate_success(
            api.get_pledge(p["id"], TEST_USERS["finance_admin_headers"])
        )
        campaign_after = validate_success(
            api.get_pledge_campaign(c["id"],
                                    TEST_USERS["finance_admin_headers"])
        )
        assert pledge_after["status"] == "ACTIVE"
        assert pledge_after["received_amount_cents"] == 0
        assert campaign_after["fulfilled_pledge_count"] == 0

    def test_refund_clears_pledge_received_amount(self, api):
        """PRD §3.3: "as Link 1 (caused directly by the donation state change), if `pledge_id` is non-null, the pledge's `received_amount_cents` decrements by `amount_cents`."

        Design: Difficulty/non_linear_state_machine/pledge_cyclic_fulfilled_to_active_on_refund
        """
        # Second required test for this instance (queue A ≥2-per-instance).
        # Same underlying rule (cyclic Pledge FULFILLED->ACTIVE), asserted
        # on a distinct observable (received_amount_cents crossing threshold).
        h, m, c, p, d = setup_fulfilled_pledge(
            pledged_amount_cents=8_000,
            donation_date="2026-06-01",
            clock="2026-06-10T00:00:00Z",
        )
        api.refund_donation(d["id"], TEST_USERS["finance_admin_headers"])
        pledge_after = validate_success(
            api.get_pledge(p["id"], TEST_USERS["finance_admin_headers"])
        )
        assert pledge_after["received_amount_cents"] == 0
        assert pledge_after["remaining_amount_cents"] == 8_000
