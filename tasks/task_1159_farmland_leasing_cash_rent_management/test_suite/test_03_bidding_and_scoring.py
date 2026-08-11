"""Bidding window guards, weighted evaluation scoring, bid revision, list
filtering, and the eligible-bid-count conservation invariant."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_version_incremented,
    create_bid_payload,
    get_bid,
    get_offering,
    list_offering_bids,
    make_tenant_headers,
    set_clock,
    setup_bid,
    setup_field,
    setup_landlord,
    setup_offering,
    setup_tenant,
    setup_two_tenant_bidding_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

MGR = TEST_USERS["farm_manager_headers"]


class TestBidEvaluationScore:
    def test_bid_evaluation_score_weighted_components(self, api):
        """PRD §3.3: "Every eligible bid — one in `SUBMITTED` or `SHORTLISTED` status on the offering — carries an `evaluation_score` rounded half up to four decimal places, computed from three weighted components. The rent component is the bid's `cash_equivalent_bid_cents_per_acre` divided by the highest such value among the offering's eligible bids; a bid that is alone in the pool scores a rent component of exactly 1.0. The compliance component is the bidding tenant's `compliance_score` divided by 100. The experience component is the tenant's `years_experience`, capped at twenty years, divided by 20 — so twenty or more years of experience saturates the component. The score itself is the sum of the rent component weighted at 0.6, the compliance component weighted at 0.25, and the experience component weighted at 0.15."

        Design: Corner/calculations/bid_evaluation_score_weighted_components
        """
        ctx = setup_two_tenant_bidding_scenario(experience_a=10, experience_b=20)
        off = ctx["offering"]
        bid_a = setup_bid(
            off["id"], ctx["tenant_a"]["id"], "CASH",
            cash_bid_per_acre_cents=25000, cash_equivalent_bid_cents_per_acre=25000,
        )
        bid_b = setup_bid(
            off["id"], ctx["tenant_b"]["id"], "CASH",
            cash_bid_per_acre_cents=30000, cash_equivalent_bid_cents_per_acre=30000,
        )

        bids = list_offering_bids(off["id"])
        assert [b["id"] for b in bids] == [bid_a["id"], bid_b["id"]], (
            "list is created_at ascending"
        )
        # A: 0.6*(25000/30000) + 0.25*1.0 + 0.15*(10/20) = 0.825
        assert bids[0]["evaluation_score"] == pytest.approx(0.825, abs=1e-6)
        # B: 0.6*1.0 + 0.25*1.0 + 0.15*(20/20) = 1.0
        assert bids[1]["evaluation_score"] == pytest.approx(1.0, abs=1e-9)
        offering = get_offering(off["id"])
        assert offering["eligible_bid_count"] == 2

    def test_bid_revision_recomputes_offering_scores(self, api):
        """PRD §3.2: "Each accepted revision increments the bid's `version` and recomputes the evaluation scores of all eligible bids on the offering."
        PRD §3.3: "The rent component is the bid's `cash_equivalent_bid_cents_per_acre` divided by the highest such value among the offering's eligible bids"

        Design: Corner/calculations/bid_revision_recomputes_offering_scores
        """
        ctx = setup_two_tenant_bidding_scenario(experience_a=20, experience_b=20)
        off = ctx["offering"]
        bid_a = setup_bid(
            off["id"], ctx["tenant_a"]["id"], "CASH",
            cash_bid_per_acre_cents=25000, cash_equivalent_bid_cents_per_acre=25000,
        )
        bid_b = setup_bid(
            off["id"], ctx["tenant_b"]["id"], "CASH",
            cash_bid_per_acre_cents=26000, cash_equivalent_bid_cents_per_acre=26000,
        )

        bids = list_offering_bids(off["id"])
        # Before revision: A = 0.6*(25000/26000)+0.25+0.15 = 0.9769 (4dp); B = 1.0.
        assert bids[0]["evaluation_score"] == pytest.approx(0.9769, abs=1e-6)
        assert bids[1]["evaluation_score"] == pytest.approx(1.0, abs=1e-9)

        revised = validate_success(
            api.revise_bid(
                bid_b["id"],
                {
                    "expected_bid_version": bid_b["version"],
                    "cash_bid_per_acre_cents": 24000,
                    "cash_equivalent_bid_cents_per_acre": 24000,
                },
                make_tenant_headers(ctx["tenant_b"]["id"]),
            )
        )
        assert_version_incremented(revised["version"], bid_b["version"])

        bids = list_offering_bids(off["id"])
        # After revision: A (now the max) = 1.0; B = 0.6*(24000/25000)+0.4 = 0.976.
        assert bids[0]["evaluation_score"] == pytest.approx(1.0, abs=1e-9)
        assert bids[1]["evaluation_score"] == pytest.approx(0.976, abs=1e-6)


class TestBiddingGuards:
    def test_bid_below_minimum_rejected(self, api):
        """PRD §3.2: "And the `cash_equivalent_bid_cents_per_acre` must be at least the offering's `min_bid_per_acre_cents`, else `ERR_BID_BELOW_MINIMUM`."

        Design: Corner/validations/bid_below_minimum_rejected
        """
        ctx = setup_two_tenant_bidding_scenario()
        payload = create_bid_payload(
            ctx["offering"]["id"], "CASH",
            cash_bid_per_acre_cents=19999, cash_equivalent_bid_cents_per_acre=19999,
        )
        resp = api.create_bid(payload, make_tenant_headers(ctx["tenant_a"]["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_BELOW_MINIMUM)

    def test_bid_after_deadline_rejected(self, api):
        """PRD §3.2: "The clock must be on or before the offering's `bid_deadline`; a bid arriving after the deadline is rejected with `ERR_BID_WINDOW_CLOSED`."
        PRD §3.3: "bids also stop being accepted once the clock passes the `bid_deadline` even without a manual close"

        Design: Corner/validations/bid_after_deadline_rejected
        """
        ctx = setup_two_tenant_bidding_scenario()
        set_clock("2026-06-16T00:00:00Z")  # past the 2026-06-15 bid_deadline
        assert get_offering(ctx["offering"]["id"])["status"] == "OPEN", (
            "offering is still OPEN; the deadline, not the status, rejects the bid"
        )
        resp = api.create_bid(
            create_bid_payload(ctx["offering"]["id"], "CASH"),
            make_tenant_headers(ctx["tenant_a"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BID_WINDOW_CLOSED)


class TestBidListing:
    def test_list_bids_filter_by_offering_and_status(self, api):
        """PRD §3.2: "The bid list accepts optional `offering_id`, `tenant_id`, and `status` filters."
        PRD §3.2: "Shortlisting moves a bid from `SUBMITTED` to `SHORTLISTED`"

        Design: Corner/endpoints/list_bids_filter_by_offering_and_status
        """
        ctx = setup_two_tenant_bidding_scenario(experience_a=5, experience_b=7)
        off = ctx["offering"]
        bid_a = setup_bid(off["id"], ctx["tenant_a"]["id"], "CASH")
        bid_b = setup_bid(
            off["id"], ctx["tenant_b"]["id"], "CASH",
            cash_bid_per_acre_cents=26000, cash_equivalent_bid_cents_per_acre=26000,
        )
        validate_success(api.shortlist_bid(bid_a["id"], MGR))

        data, meta = validate_paginated(
            api.list_bids(MGR, params={"offering_id": off["id"], "status": "SHORTLISTED"})
        )
        assert len(data) == 1, "exactly one SHORTLISTED bid on this offering"
        assert data[0]["id"] == bid_a["id"]
        assert data[0]["status"] == "SHORTLISTED"
        assert all(b["id"] != bid_b["id"] for b in data), "SUBMITTED bid is excluded"


class TestEligibleBidCountInvariant:
    def test_submit_raises_eligible_bid_count(self, api):
        """PRD §3.2: "An offering opens in `OPEN` status with an `eligible_bid_count` of zero; that count always reflects the number of the offering's bids currently in `SUBMITTED` or `SHORTLISTED` status and is recomputed on every bid creation, revision, withdrawal, award, cancellation, and tenant-suspension cascade."
        PRD §3.2: "A bid that passes starts in `SUBMITTED` status, its `evaluation_score` is computed, and the offering's `eligible_bid_count` is recomputed."

        Design: Difficulty/compensating_invariant/submit_then_withdraw_conserves_eligible_bid_count
        """
        ctx = setup_two_tenant_bidding_scenario(experience_a=5, experience_b=7)
        off = ctx["offering"]
        setup_bid(off["id"], ctx["tenant_a"]["id"], "CASH")
        baseline = get_offering(off["id"])["eligible_bid_count"]
        assert baseline == 1, "baseline: one eligible bid from tenant A"

        bid_b = setup_bid(
            off["id"], ctx["tenant_b"]["id"], "CASH",
            cash_bid_per_acre_cents=26000, cash_equivalent_bid_cents_per_acre=26000,
        )
        assert bid_b["status"] == "SUBMITTED"
        after_submit = get_offering(off["id"])["eligible_bid_count"]
        assert after_submit == baseline + 1, "submit increments the eligible count"

    def test_withdraw_returns_eligible_bid_count_to_baseline(self, api):
        """PRD §3.2: "that count always reflects the number of the offering's bids currently in `SUBMITTED` or `SHORTLISTED` status and is recomputed on every bid creation, revision, withdrawal, award, cancellation, and tenant-suspension cascade"
        PRD §3.2: "A tenant may also withdraw a bid they own — the bid's `tenant_id` must equal the caller's `X-User-ID`, else `ERR_NOT_RESOURCE_OWNER` — moving it from `SUBMITTED` or `SHORTLISTED` to `WITHDRAWN`"

        Design: Difficulty/compensating_invariant/submit_then_withdraw_conserves_eligible_bid_count
        """
        ctx = setup_two_tenant_bidding_scenario(experience_a=5, experience_b=7)
        off = ctx["offering"]
        setup_bid(off["id"], ctx["tenant_a"]["id"], "CASH")
        baseline = get_offering(off["id"])["eligible_bid_count"]

        bid_b = setup_bid(
            off["id"], ctx["tenant_b"]["id"], "CASH",
            cash_bid_per_acre_cents=26000, cash_equivalent_bid_cents_per_acre=26000,
        )
        assert get_offering(off["id"])["eligible_bid_count"] == baseline + 1

        withdrawn = validate_success(
            api.withdraw_bid(bid_b["id"], make_tenant_headers(ctx["tenant_b"]["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert get_bid(bid_b["id"])["status"] == "WITHDRAWN"
        after_withdraw = get_offering(off["id"])["eligible_bid_count"]
        assert after_withdraw == baseline, (
            "the compensating withdrawal returns the count to its exact baseline"
        )
