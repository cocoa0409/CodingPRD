"""Split allocation, refund window boundary, priority conflicts."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_household, create_adult_member,
    create_and_activate_campaign, create_pledge, create_donation,
    cancel_pledge, create_pledge_payload,
)


class TestDonationSplitRounding:
    def test_last_pledge_absorbs_rounding_remainder(self, api):
        """PRD §3.3: "for every candidate pledge except the last in the
        sorted list, the share is the whole-cent floor of (donation
        amount_cents multiplied by that pledge's remaining_amount_cents,
        divided by the weight denominator); the last pledge in the sorted
        list absorbs the rounding remainder, receiving the donation
        amount_cents minus the sum of all the earlier shares."

        Design: Difficulty/combinatorial_formula/donation_split_last_pledge_absorbs_rounding_remainder
        """
        set_clock("2026-06-15T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        c = create_and_activate_campaign(name="Split", target_amount_cents=100_000)
        # P1 remaining=6000 (sorted first — larger), P2 remaining=3000 (last).
        p1 = create_pledge(c["id"], m["id"], pledged_amount_cents=6_000)
        p2 = create_pledge(c["id"], m["id"], pledged_amount_cents=3_000)

        # Donate 10000 with split_across=true.
        resp = api.create_donation(
            {"member_id": m["id"], "amount_cents": 10_000,
             "donation_date": "2026-06-15", "payment_method": "CHECK",
             "campaign_id": c["id"], "split_across": True},
            TEST_USERS["finance_admin_headers"],
        )
        # The parent donation is created HTTP 201 (auto-post for CHECK).
        assert resp.status_code in (200, 201), (
            f"expected 2xx for split donation, got {resp.status_code}: "
            f"{resp.text[:200]}"
        )
        # Per PRD: floor(10000*6000/9000) = 6666 for P1;
        # 10000 - 6666 = 3334 for P2.
        p1_after = validate_success(
            api.get_pledge(p1["id"], TEST_USERS["finance_admin_headers"])
        )
        p2_after = validate_success(
            api.get_pledge(p2["id"], TEST_USERS["finance_admin_headers"])
        )
        assert p1_after["received_amount_cents"] == 6_666
        assert p2_after["received_amount_cents"] == 3_334

    def test_split_shares_sum_to_parent_amount(self, api):
        """PRD §3.3: "receiving the donation amount_cents minus the sum of
        all the earlier shares."

        Design: Difficulty/combinatorial_formula/donation_split_last_pledge_absorbs_rounding_remainder
        """
        # Second test for this instance: campaign-level invariant.
        set_clock("2026-06-15T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        c = create_and_activate_campaign(name="Split2", target_amount_cents=100_000)
        create_pledge(c["id"], m["id"], pledged_amount_cents=6_000)
        create_pledge(c["id"], m["id"], pledged_amount_cents=3_000)

        api.create_donation(
            {"member_id": m["id"], "amount_cents": 10_000,
             "donation_date": "2026-06-15", "payment_method": "CHECK",
             "campaign_id": c["id"], "split_across": True},
            TEST_USERS["finance_admin_headers"],
        )
        campaign = validate_success(
            api.get_pledge_campaign(c["id"],
                                    TEST_USERS["finance_admin_headers"])
        )
        # Split shares sum to parent amount, so campaign received_total = 10000.
        assert campaign["received_total_cents"] == 10_000


class TestSplitAcrossEmptyPledgeSet:
    def test_split_across_with_zero_active_pledges_rejected(self, api):
        """PRD §3.3: "If the weight denominator is zero — either because
        the member has no ACTIVE pledges on the campaign or because every
        one of them has zero remaining — the split is rejected with
        ERR_NO_ACTIVE_PLEDGE."

        Design: Difficulty/boundary_precision_check/donation_split_across_empty_active_pledge_set
        """
        set_clock("2026-06-15T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        c = create_and_activate_campaign(name="C1", target_amount_cents=100_000)
        p = create_pledge(c["id"], m["id"], pledged_amount_cents=10_000)
        cancel_pledge(p["id"])  # No ACTIVE pledges on (M, C).

        resp = api.create_donation(
            {"member_id": m["id"], "amount_cents": 10_000,
             "donation_date": "2026-06-15", "payment_method": "CHECK",
             "campaign_id": c["id"], "split_across": True},
            TEST_USERS["finance_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PLEDGE)

    def test_split_across_with_no_pledges_rejected(self, api):
        """PRD §3.3: "If the weight denominator is zero — either because
        the member has no ACTIVE pledges on the campaign or because every
        one of them has zero remaining — the split is rejected with
        ERR_NO_ACTIVE_PLEDGE."

        Design: Difficulty/boundary_precision_check/donation_split_across_empty_active_pledge_set
        """
        # Second required test — same rule via the alternate empty-set path
        # (no pledges at all, versus all pledges cancelled).
        set_clock("2026-06-15T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        c = create_and_activate_campaign(name="C1b", target_amount_cents=100_000)
        # No pledges created at all.
        resp = api.create_donation(
            {"member_id": m["id"], "amount_cents": 5_000,
             "donation_date": "2026-06-15", "payment_method": "CHECK",
             "campaign_id": c["id"], "split_across": True},
            TEST_USERS["finance_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PLEDGE)


class TestRefundBoundary:
    def test_refund_at_exact_60_day_boundary_succeeds(self, api):
        """PRD §3.3: "A FinanceAdmin may refund a POSTED donation, and
        only within the refund window — the current logical date MUST be
        at most donation.donation_date plus 60 days, otherwise the refund
        is rejected with ERR_REFUND_WINDOW_EXPIRED."

        Design: Difficulty/boundary_precision_check/refund_at_exact_60_day_boundary
        """
        set_clock("2026-03-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        d = create_donation(m["id"], 5_000, "2026-03-01",
                            payment_method="CASH")
        assert d["status"] == "POSTED"
        # Advance clock to exactly donation_date + 60 days (2026-04-30).
        set_clock("2026-04-30T00:00:00Z")
        resp = api.refund_donation(d["id"],
                                   TEST_USERS["finance_admin_headers"])
        donation_after = validate_success(resp)
        assert donation_after["status"] == "REFUNDED"

    def test_refund_past_60_day_window_rejected(self, api):
        """PRD §3.3: "the current logical date MUST be at most
        donation.donation_date plus 60 days, otherwise the refund is
        rejected with ERR_REFUND_WINDOW_EXPIRED."

        Design: Difficulty/boundary_precision_check/refund_at_exact_60_day_boundary
        """
        # Second required test: the complementary rejection side of the
        # same 60-day boundary rule.
        set_clock("2026-03-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        d = create_donation(m["id"], 5_000, "2026-03-01",
                            payment_method="CASH")
        set_clock("2026-05-01T00:00:00Z")  # 61 days after donation_date.
        resp = api.refund_donation(d["id"],
                                   TEST_USERS["finance_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_REFUND_WINDOW_EXPIRED)


class TestPriorityPairStateBeatsTemporal:
    def test_state_check_precedes_refund_window(self, api):
        """PRD §2.8: "Every request runs through a priority-ordered
        validation ladder; the first rung whose predicate fails determines
        the returned error."
        PRD §2.8 rung 5: "The target resource must be in a state that
        admits the requested transition; otherwise ERR_INVALID_STATE (HTTP
        409)."

        Design: Difficulty/priority_pair_validation_conflict/refund_on_refunded_donation_past_window_state_beats_temporal
        """
        # Setup: donation refunded 2026-01-01 (within window). Advance to
        # 2026-06-01 where the 60-day window has expired. The state check
        # (already REFUNDED — priority 5) fires ahead of the window check
        # (priority 10).
        set_clock("2026-01-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        d = create_donation(m["id"], 10_000, "2026-01-01",
                            payment_method="CHECK")
        # First refund succeeds (within window at 2026-01-01).
        validate_success(
            api.refund_donation(d["id"], TEST_USERS["finance_admin_headers"])
        )
        # Advance so a fresh attempt would also fail the 60-day window.
        set_clock("2026-06-01T00:00:00Z")
        resp = api.refund_donation(d["id"],
                                   TEST_USERS["finance_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_state_precedence_returns_409(self, api):
        """PRD §2.8: "Because the ladder is strict, a request that fails
        several rungs is reported at the highest (lowest-numbered) failing
        rung."

        Design: Difficulty/priority_pair_validation_conflict/refund_on_refunded_donation_past_window_state_beats_temporal
        """
        # Second required test: same rule, distinct observable (HTTP status).
        set_clock("2026-01-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        d = create_donation(m["id"], 5_000, "2026-01-01",
                            payment_method="CHECK")
        api.refund_donation(d["id"], TEST_USERS["finance_admin_headers"])
        set_clock("2026-08-01T00:00:00Z")
        resp = api.refund_donation(d["id"],
                                   TEST_USERS["finance_admin_headers"])
        # ERR_INVALID_STATE HTTP status is 409 (both would-be errors are 409,
        # but the returned error_id is the state one).
        assert resp.status_code == 409
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_INVALID_STATE"


class TestPriorityPairReferentialBeatsFiscal:
    def test_reference_mismatch_wins_over_zero_amount(self, api):
        """PRD §2.8 rung 4: "Cross-body referential integrity — that a
        donation's pledge_id refers to a pledge whose campaign_id and
        member_id both match the donation's own campaign_id and
        member_id... must hold; otherwise ERR_REFERENCE_MISMATCH (HTTP
        422)."

        Design: Difficulty/priority_pair_validation_conflict/donation_pledge_campaign_mismatch_and_zero_amount_referential_beats_fiscal
        """
        set_clock("2026-06-15T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        c1 = create_and_activate_campaign(name="C1", target_amount_cents=50_000)
        c2 = create_and_activate_campaign(name="C2", target_amount_cents=50_000)
        p1 = create_pledge(c1["id"], m["id"], pledged_amount_cents=10_000)
        # amount_cents == 0 (would fire ERR_INVALID_AMOUNT at priority 11)
        # AND pledge.campaign != donation.campaign (fires
        # ERR_REFERENCE_MISMATCH at priority 4). Priority 4 wins.
        resp = api.create_donation(
            {"member_id": m["id"], "amount_cents": 0,
             "donation_date": "2026-06-15", "payment_method": "CHECK",
             "campaign_id": c2["id"], "pledge_id": p1["id"]},
            TEST_USERS["finance_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_MISMATCH)

    def test_reference_mismatch_returns_422(self, api):
        """PRD §5: "ERR_REFERENCE_MISMATCH | 422"

        Design: Difficulty/priority_pair_validation_conflict/donation_pledge_campaign_mismatch_and_zero_amount_referential_beats_fiscal
        """
        # Second required test for this instance: verify status code side.
        set_clock("2026-06-15T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        c1 = create_and_activate_campaign(name="C1b", target_amount_cents=50_000)
        c2 = create_and_activate_campaign(name="C2b", target_amount_cents=50_000)
        p1 = create_pledge(c1["id"], m["id"], pledged_amount_cents=10_000)
        resp = api.create_donation(
            {"member_id": m["id"], "amount_cents": 0,
             "donation_date": "2026-06-15", "payment_method": "CHECK",
             "campaign_id": c2["id"], "pledge_id": p1["id"]},
            TEST_USERS["finance_admin_headers"],
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_REFERENCE_MISMATCH"
