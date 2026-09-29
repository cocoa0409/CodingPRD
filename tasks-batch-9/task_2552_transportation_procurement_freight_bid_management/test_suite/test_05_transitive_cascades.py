"""Multi-link cascades where each link exists only because the previous one fired.

Three separate chains are covered: the five-link award commit, the three-link
tender-rejection risk cascade, and the three-link watchlist cascade driven by
publishing a scorecard. In each case the middle links are the interesting part —
a run that lands the first and last state but skips a middle one is wrong.
"""

from test_helpers import (
    ANALYST,
    api_client,
    append_tender,
    assert_same_instant,
    assert_tender_event,
    CATEGORY_MANAGER,
    CLOCK_GO_LIVE,
    CONTRACT_EFFECTIVE_FROM,
    CONTRACT_EFFECTIVE_TO,
    create_qualified_carrier,
    DEFAULT_CLOCK,
    draft_scorecard,
    get_success_data,
    list_contracts,
    read_allocation,
    read_carrier,
    read_lane,
    read_lane_bid,
    read_rate_record,
    set_clock,
    setup_tendered_rate_record,
    two_lane_awarded_event,
)

# The incumbent baseline of lane A alone: 1147 x 2.4000 = 2752.80, plus 137.55,
# on 550 planned loads. Lane B has no incumbent and contributes nothing.
BASELINE_COST_USD = 1589692.50

# 550 loads on lane A plus 120 on lane B, from the executed allocations - not the
# 750 loads the carrier offered to commit across its two bids.
EXECUTED_COMMITTED_VOLUME_LOADS = 670

# A period with 40.00 on-time, no tenders and a claims ratio that floors the
# claims subscore: 40.00 x 0.45 + 100.00 x 0.35 + 0.00 x 0.20.
POOR_PERIOD = {
    "period_start": "2026-04-01T00:00:00Z",
    "period_end": "2026-07-01T00:00:00Z",
    "on_time_pct": 40.00,
    "claims_ratio": 0.1000,
}
POOR_PERIOD_SCORE = 53.00
COMPOSITE_AFTER_PUBLICATION = 64.70


def _list_mini_bids(**params):
    body = get_success_data(api_client.list_mini_bids(CATEGORY_MANAGER, params or None))
    return body["data"] if isinstance(body, dict) and "data" in body else body


def _list_tender_events(rate_record_id):
    body = get_success_data(api_client.list_tender_events(rate_record_id, ANALYST))
    return body["data"] if isinstance(body, dict) and "data" in body else body


class TestAwardCommitCascade:
    """Committing the routing guide must land all five links."""

    def test_commit_awards_the_event_and_executes_every_allocation(self):
        """Links 1 and 2: the event closes out and its allocations execute.

        PRD §3.7: "The event moves from `AWARDING` to `AWARDED`, `awarded_at` is set
        to the logical clock, and its `award_cost_usd` and `savings_pct` are
        recomputed per §3.3."
        PRD §3.7: "Every allocation of the `PUBLISHED` run whose `status` is
        `APPROVED` moves to `EXECUTED`, and each one's referenced lane bid moves from
        `SHORTLISTED` to `AWARDED_PRIMARY` when the allocation's `routing_position` is
        `PRIMARY`"
        PRD §3.3: "`award_cost_usd` is `0.00` when the event has no contracts at all"
        PRD §3.3: "`savings_pct` is `0.00` whenever `baseline_cost_usd` is `0.00` or
        `award_cost_usd` is `0.00`"

        Design: Difficulty/transitive_cascade/award_commit_five_link_cascade
        """
        ctx = two_lane_awarded_event()
        event = ctx["event"]
        assert event["status"] == "AWARDED"
        assert_same_instant(event["awarded_at"], DEFAULT_CLOCK, "awarded_at")
        assert float(event["baseline_cost_usd"]) == BASELINE_COST_USD
        # No rate record has been staged, so the fresh contracts carry no value yet.
        assert float(event["award_cost_usd"]) == 0.00
        assert float(event["savings_pct"]) == 0.00

        assert len(ctx["allocations"]) == 2
        for allocation in ctx["allocations"]:
            assert allocation["status"] == "EXECUTED"
            assert allocation["routing_position"] == "PRIMARY"
        for bid in ctx["bids"]:
            assert read_lane_bid(bid["id"])["status"] == "AWARDED_PRIMARY"

    def test_lanes_award_and_exactly_one_contract_is_minted_per_carrier(self):
        """Links 3 and 4: awarded lanes are what the contract is minted from.

        PRD §3.7: "Every lane holding an executed allocation moves from `LOCKED` to
        `AWARDED`, and its `awarded_coverage_pct` is recomputed."
        PRD §3.7: "One contract is created for each distinct pairing of
        `bid_event_id` and `carrier_id` appearing among those executed allocations —
        one contract per carrier per event, however many lanes that carrier won."
        PRD §3.7: "Each contract is created with `status` `DRAFT`, `signature_status`
        `PENDING_BOTH`, `rate_load_status` `NOT_STAGED`, `amendment_count` `0`,
        `rate_record_count` `0`"

        Design: Difficulty/transitive_cascade/award_commit_five_link_cascade
        """
        ctx = two_lane_awarded_event()
        for lane in ctx["lanes"]:
            refreshed = read_lane(lane["id"])
            assert refreshed["status"] == "AWARDED"
            assert float(refreshed["awarded_coverage_pct"]) == 100.00
            assert refreshed["unallocated_volume_loads"] == 0

        contracts = list_contracts(bid_event_id=ctx["event"]["id"])
        assert len(contracts) == 1, (
            "one contract per carrier per event, whatever the lane count"
        )
        contract = contracts[0]
        assert contract["carrier_id"] == ctx["carrier"]["id"]
        assert contract["status"] == "DRAFT"
        assert contract["signature_status"] == "PENDING_BOTH"
        assert contract["rate_load_status"] == "NOT_STAGED"
        assert contract["amendment_count"] == 0
        assert contract["rate_record_count"] == 0
        assert float(contract["total_committed_value_usd"]) == 0.00
        assert_same_instant(contract["effective_from"], CONTRACT_EFFECTIVE_FROM)
        assert_same_instant(contract["effective_to"], CONTRACT_EFFECTIVE_TO)
        assert contract["carrier_signed_by_user_id"] is None
        assert contract["shipper_signed_at"] is None

    def test_carrier_capacity_is_re_derived_from_the_executed_allocations(self):
        """Link 5: the carrier's capacity follows the allocations, not the bids.

        PRD §3.7: "Each carrier that now holds a contract has its
        `committed_volume_loads` and `active_primary_lane_count` recomputed from its
        executed allocations, per the status sets in §2.12."
        PRD §2.12: "`Carrier.committed_volume_loads` sums `allocated_volume_loads`
        over that carrier's allocations whose status is `EXECUTED`, `ACTIVE` or
        `SUSPENDED_ROUTING`."
        PRD §2.12: "`Carrier.active_primary_lane_count` counts that carrier's award
        allocations whose `routing_position` is `PRIMARY` and whose status is
        `EXECUTED` or `ACTIVE`."

        Design: Difficulty/transitive_cascade/award_commit_five_link_cascade
        """
        ctx = two_lane_awarded_event()
        allocated = sum(
            allocation["allocated_volume_loads"] for allocation in ctx["allocations"]
        )
        assert allocated == EXECUTED_COMMITTED_VOLUME_LOADS

        carrier = read_carrier(ctx["carrier"]["id"])
        assert carrier["committed_volume_loads"] == EXECUTED_COMMITTED_VOLUME_LOADS, (
            "capacity is summed from executed allocations, not from bid commitments"
        )
        assert carrier["active_primary_lane_count"] == 2


class TestTenderRejectionRiskCascade:
    """The fifth tender is what turns a rejection pattern into a formal risk."""

    def test_the_fifth_tender_at_the_threshold_flips_the_record_to_at_risk(self):
        """Link 1: four rejections-free tenders, then one refusal at exactly 20.00.

        PRD §3.9: "`rejection_pct` is `0.00` when `tender_count` is zero; otherwise
        multiply `rejection_count` by `100.00`, divide by `tender_count`, and round to
        2 decimal places."
        PRD §3.9: "A record with 5 tenders of which exactly 1 was rejected has a
        `rejection_pct` of exactly `20.00`, meets both gates, and **is** at risk."
        PRD §3.9: "The rate record moves from `LIVE` to `AT_RISK`."

        Design: Difficulty/transitive_cascade/tender_rejection_three_link_risk_cascade
        """
        ctx = setup_tendered_rate_record(["ACCEPTED"] * 4)
        before = ctx["rate_record"]
        assert before["status"] == "LIVE"
        assert before["tender_count"] == 4
        assert before["rejection_count"] == 0
        assert float(before["rejection_pct"]) == 0.00
        assert ctx["allocation"]["status"] == "ACTIVE"
        assert ctx["lane"]["status"] == "AWARDED"

        append_tender(
            ctx["rate_record"]["id"],
            "LD-0005",
            outcome="REJECTED",
            reject_reason="No capacity",
        )
        record = read_rate_record(ctx["rate_record"]["id"])
        assert record["tender_count"] == 5
        assert record["rejection_count"] == 1
        assert float(record["rejection_pct"]) == 20.00
        assert float(record["acceptance_pct"]) == 80.00
        assert record["status"] == "AT_RISK"

    def test_at_risk_suspends_the_routing_and_opens_a_system_mini_bid(self):
        """Links 2 and 3: the allocation and lane step aside and a window opens.

        PRD §3.9: "The award allocation the record implements, if it is `ACTIVE` and
        its `routing_position` is `PRIMARY`, moves to `SUSPENDED_ROUTING`; and the lane
        moves from `AWARDED` to `UNDER_REBID`."
        PRD §3.9: "A mini-bid is created automatically, with `origin` `SYSTEM`,
        `status` `REQUESTED`, `trigger_reason` `TENDER_REJECTION_RATE`, its
        `window_open_at` set to the current logical clock instant and its
        `window_close_at` set to that instant advanced by the system mini-bid window
        of 10 days."

        Design: Difficulty/transitive_cascade/tender_rejection_three_link_risk_cascade
        """
        ctx = setup_tendered_rate_record(["ACCEPTED"] * 4)
        assert _list_mini_bids(lane_id=ctx["lane"]["id"]) == [], (
            "no window may exist before the risk determination turns positive"
        )

        append_tender(
            ctx["rate_record"]["id"],
            "LD-0005",
            outcome="REJECTED",
            reject_reason="No capacity",
        )

        assert read_allocation(ctx["allocation"]["id"])["status"] == "SUSPENDED_ROUTING"
        assert read_lane(ctx["lane"]["id"])["status"] == "UNDER_REBID"

        mini_bids = _list_mini_bids(lane_id=ctx["lane"]["id"])
        assert len(mini_bids) == 1
        mini_bid = mini_bids[0]
        assert mini_bid["origin"] == "SYSTEM"
        assert mini_bid["status"] == "REQUESTED"
        assert mini_bid["trigger_reason"] == "TENDER_REJECTION_RATE"
        assert mini_bid["rate_record_id"] == ctx["rate_record"]["id"]
        assert_same_instant(mini_bid["window_open_at"], CLOCK_GO_LIVE, "window_open_at")
        assert_same_instant(
            mini_bid["window_close_at"], "2026-09-11T00:00:00Z", "window_close_at"
        )

    def test_the_tender_log_stays_an_immutable_append_only_record(self):
        """Every link above is driven by rows that are never rewritten.

        PRD §3.9: "As stated in §2.6, a tender event carries only `id` and
        `created_at` — no `updated_at` and no `version` — because it is an immutable
        log entry."
        PRD §3.9: "The tender event records `tendered_at` from the logical clock and
        freezes `position_used` from the rate record's `routing_position` as it stands
        at append time"

        Design: Difficulty/transitive_cascade/tender_rejection_three_link_risk_cascade
        """
        ctx = setup_tendered_rate_record(["ACCEPTED"] * 4)
        append_tender(
            ctx["rate_record"]["id"],
            "LD-0005",
            outcome="REJECTED",
            reject_reason="No capacity",
        )

        tenders = _list_tender_events(ctx["rate_record"]["id"])
        assert len(tenders) == 5
        for tender in tenders:
            assert_tender_event(tender)
            assert_same_instant(tender["tendered_at"], CLOCK_GO_LIVE, "tendered_at")
            assert tender["position_used"] == "PRIMARY"
        created = [tender["created_at"] for tender in tenders]
        assert created == sorted(created), "the log reads in created_at ascending order"
        assert [tender["outcome"] for tender in tenders] == [
            "ACCEPTED",
            "ACCEPTED",
            "ACCEPTED",
            "ACCEPTED",
            "REJECTED",
        ]


class TestScorecardPublicationWatchlistCascade:
    """Publication, not drafting, is what re-scores a carrier and can flag it."""

    def test_publication_flips_the_variant_and_recomputes_the_composite(self):
        """Links 1 and 2: the first published period replaces the provisional score.

        PRD §3.2: "Drafting a scorecard does not touch the carrier in any way. A
        `DRAFT` scorecard is invisible to the carrier's own composite score."
        PRD §3.2: "The carrier's `published_scorecard_count` is recomputed as the
        number of that carrier's scorecards that participate in the composite
        lookback"
        PRD §3.2: "The first publication is what flips the variant: because the
        final-variant threshold is one scorecard, a carrier goes from
        `PROVISIONAL_SCREENING` to `FINAL_PERFORMANCE` as soon as its first scorecard
        is published."
        PRD §3.2: "Multiply `on_time_pct` by `0.45`, `tender_acceptance_pct` by `0.35`
        and the claims subscore by `0.20`, add the three products, and round to 2
        decimal places."

        Design: Difficulty/transitive_cascade/scorecard_publication_three_link_watchlist_cascade
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_qualified_carrier()
        assert carrier["published_scorecard_count"] == 0
        assert float(carrier["composite_score"]) == 90.60
        assert carrier["composite_score_variant"] == "PROVISIONAL_SCREENING"
        assert carrier["status"] == "QUALIFIED"

        scorecard = draft_scorecard(carrier["id"], **POOR_PERIOD)
        assert scorecard["status"] == "DRAFT"
        assert float(scorecard["composite_score"]) == POOR_PERIOD_SCORE
        assert scorecard["period_tender_count"] == 0
        assert float(scorecard["tender_acceptance_pct"]) == 100.00
        drafted_carrier = read_carrier(carrier["id"])
        assert float(drafted_carrier["composite_score"]) == 90.60, (
            "a draft scorecard must not move the carrier's composite"
        )
        assert drafted_carrier["composite_score_variant"] == "PROVISIONAL_SCREENING"

        published = get_success_data(
            api_client.publish_scorecard(scorecard["id"], CATEGORY_MANAGER)
        )
        assert published["status"] == "PUBLISHED"
        assert_same_instant(published["published_at"], DEFAULT_CLOCK, "published_at")
        assert float(published["composite_score"]) == POOR_PERIOD_SCORE

        rescored = read_carrier(carrier["id"])
        assert rescored["published_scorecard_count"] == 1
        assert rescored["composite_score_variant"] == "FINAL_PERFORMANCE"
        assert float(rescored["composite_score"]) == COMPOSITE_AFTER_PUBLICATION
        assert float(rescored["capability_score"]) == 88.00, (
            "only the performance component of the composite moved"
        )

    def test_a_composite_below_the_floor_moves_the_carrier_to_watchlist(self):
        """Link 3: the re-scored composite crosses the watchlist floor downward.

        PRD §3.2: "Because link 2 may have moved the composite across the watchlist
        floor of `75.00`, the carrier's standing is re-evaluated."
        PRD §3.2: "A carrier whose `status` is `QUALIFIED` and whose new
        `composite_score` is strictly below `75.00` moves to `WATCHLIST`, with
        `status_reason` set to `SCORECARD_BELOW_FLOOR`."

        Design: Difficulty/transitive_cascade/scorecard_publication_three_link_watchlist_cascade
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_qualified_carrier()
        scorecard = draft_scorecard(carrier["id"], **POOR_PERIOD)
        assert read_carrier(carrier["id"])["status"] == "QUALIFIED"

        get_success_data(api_client.publish_scorecard(scorecard["id"], CATEGORY_MANAGER))

        flagged = read_carrier(carrier["id"])
        assert float(flagged["composite_score"]) < 75.00
        assert flagged["status"] == "WATCHLIST"
        assert flagged["status_reason"] == "SCORECARD_BELOW_FLOOR"
