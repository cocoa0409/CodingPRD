"""Values sitting exactly on a declared threshold, where >= and > diverge.

Two independent boundaries are walked here. The tender risk determination has two
gates that must both hold, so a rate can be over the percentage boundary and still
be safe for want of sample; and the single-carrier share cap lands on an exact half
load, where flooring and rounding give different answers.
"""

from test_helpers import (
    ANALYST,
    CATEGORY_MANAGER,
    api_client,
    append_tender,
    approve_allocation,
    get_success_data,
    list_allocations,
    read_allocation,
    read_lane,
    read_rate_record,
    setup_published_routing_guide,
    setup_tendered_rate_record,
)

# Three accepted loads and one refusal: 1/4 is 25.00 percent, over the 20.00
# threshold, but one tender short of the minimum sample of 5.
UNDER_SAMPLE_OUTCOMES = ["ACCEPTED", "ACCEPTED", "ACCEPTED", "REJECTED"]

# 550 planned loads at a 55.00 percent single-carrier cap: 302.50 exactly.
SHARE_CAP_EVENT = {"max_award_share_pct": 55.00, "max_carriers_per_lane": 1}
CAPPED_LOADS = 302
CAPPED_PCT = 54.91
CAPPED_COST_USD = 780461.62


def _list_mini_bids(**params):
    body = get_success_data(api_client.list_mini_bids(CATEGORY_MANAGER, params or None))
    return body["data"] if isinstance(body, dict) and "data" in body else body


def _read_run(run_id):
    return get_success_data(api_client.get_optimization_run(run_id, ANALYST))


class TestTenderRiskTwoGateBoundary:
    """Both the sample gate and the percentage gate must hold at once."""

    def test_a_quarter_rejection_rate_on_four_tenders_is_not_at_risk(self):
        """Over the percentage boundary, under the sample boundary: nothing fires.

        PRD §3.9: "The record is **at risk** when two conditions hold
        **independently and together**: `tender_count` is greater than or equal to the
        minimum sample of 5, and `rejection_pct` is greater than or equal to the
        at-risk threshold of `20.00`."
        PRD §3.9: "A record with 4 tenders of which all 4 were rejected has a
        `rejection_pct` of `100.00` but has not met the sample gate, so it is **not**
        at risk — a small sample is not evidence."

        Design: Difficulty/boundary_precision_check/tender_rejection_pct_exactly_at_threshold_with_minimum_sample
        """
        ctx = setup_tendered_rate_record(UNDER_SAMPLE_OUTCOMES)
        record = ctx["rate_record"]
        assert record["tender_count"] == 4
        assert record["rejection_count"] == 1
        assert float(record["rejection_pct"]) == 25.00
        assert float(record["acceptance_pct"]) == 75.00
        assert record["status"] == "LIVE", (
            "25.00 >= 20.00 holds, but a sample of 4 has not met the gate"
        )
        assert ctx["allocation"]["status"] == "ACTIVE"
        assert ctx["lane"]["status"] == "AWARDED"
        assert _list_mini_bids(lane_id=ctx["lane"]["id"]) == []

    def test_exactly_twenty_percent_on_the_fifth_tender_crosses_both_gates(self):
        """An accepted fifth load lowers the ratio to exactly the threshold and fires.

        PRD §3.9: "A record with 5 tenders of which exactly 1 was rejected has a
        `rejection_pct` of exactly `20.00`, meets both gates, and **is** at risk."
        PRD §3.9: "The rate record moves from `LIVE` to `AT_RISK`."
        PRD §3.9: "The award allocation the record implements, if it is `ACTIVE` and
        its `routing_position` is `PRIMARY`, moves to `SUSPENDED_ROUTING`; and the lane
        moves from `AWARDED` to `UNDER_REBID`."

        Design: Difficulty/boundary_precision_check/tender_rejection_pct_exactly_at_threshold_with_minimum_sample
        """
        ctx = setup_tendered_rate_record(UNDER_SAMPLE_OUTCOMES)
        append_tender(ctx["rate_record"]["id"], "LD-0005", outcome="ACCEPTED")

        record = read_rate_record(ctx["rate_record"]["id"])
        assert record["tender_count"] == 5
        assert record["rejection_count"] == 1
        assert float(record["rejection_pct"]) == 20.00
        assert float(record["acceptance_pct"]) == 80.00
        assert record["status"] == "AT_RISK", (
            "the comparison is at-or-above the threshold, not strictly above it"
        )
        assert read_allocation(ctx["allocation"]["id"])["status"] == "SUSPENDED_ROUTING"
        assert read_lane(ctx["lane"]["id"])["status"] == "UNDER_REBID"
        opened = _list_mini_bids(lane_id=ctx["lane"]["id"])
        assert len(opened) == 1
        assert opened[0]["origin"] == "SYSTEM"
        assert opened[0]["status"] == "REQUESTED"

    def test_the_sixth_tender_unwinds_the_risk_but_leaves_the_mini_bid_standing(self):
        """One more acceptance takes the ratio below the threshold and reverses links 1-2.

        PRD §3.9: "`rejection_pct` is `0.00` when `tender_count` is zero; otherwise
        multiply `rejection_count` by `100.00`, divide by `tender_count`, and round to
        2 decimal places."
        PRD §3.9: "the cascade unwinds symmetrically: the record moves from `AT_RISK`
        back to `LIVE`, the suspended allocation moves from `SUSPENDED_ROUTING` back to
        `ACTIVE`, and the lane moves from `UNDER_REBID` back to `AWARDED` provided no
        other at-risk record remains on that lane."
        PRD §2.7: "All monetary amounts are decimal values carried to exactly 2 decimal
        places, and all rounding is **round half up**."

        Design: Difficulty/boundary_precision_check/tender_rejection_pct_exactly_at_threshold_with_minimum_sample
        """
        ctx = setup_tendered_rate_record(UNDER_SAMPLE_OUTCOMES)
        append_tender(ctx["rate_record"]["id"], "LD-0005", outcome="ACCEPTED")
        append_tender(ctx["rate_record"]["id"], "LD-0006", outcome="ACCEPTED")

        record = read_rate_record(ctx["rate_record"]["id"])
        assert record["tender_count"] == 6
        # 1/6 is 16.6666..., which rounds half up at 2dp to 16.67.
        assert float(record["rejection_pct"]) == 16.67
        assert float(record["acceptance_pct"]) == 83.33
        assert record["status"] == "LIVE"
        assert read_allocation(ctx["allocation"]["id"])["status"] == "ACTIVE"
        assert read_lane(ctx["lane"]["id"])["status"] == "AWARDED"

        standing = _list_mini_bids(lane_id=ctx["lane"]["id"])
        assert len(standing) == 1, "the unwind restores routing, not the rebid request"
        assert standing[0]["status"] == "REQUESTED"


class TestShareCapExactHalfLoadBoundary:
    """A cap of 302.50 loads may only ever grant 302."""

    def test_the_share_cap_floors_an_exact_half_load_downward(self):
        """The cap is floored, so the grant is 302 and never 303.

        PRD §3.6: "The lane then has a remaining volume, initialised to its
        `annual_volume_loads`, and a single-carrier share cap computed by multiplying
        `annual_volume_loads` by the event's `max_award_share_pct`, dividing by
        `100.00`, and taking the **floor** — the largest whole number of loads not
        exceeding that product, never a rounded-up figure."
        PRD §3.6: "For each candidate it computes a grant as the smallest of three
        quantities: the lane's remaining volume, the bid's `committed_volume_loads`,
        and the share cap."
        PRD §3.6: "A positive grant produces a pick carrying the next
        `routing_position` in sequence, `allocated_volume_loads` equal to the grant,
        `allocated_pct` equal to the grant multiplied by `100.00`, divided by
        `annual_volume_loads` and rounded to 2 decimal places, and `allocated_cost_usd`
        equal to the bid's `cost_per_load_usd` multiplied by the grant and rounded to 2
        decimal places."

        Design: Difficulty/boundary_precision_check/award_share_cap_floor_at_exact_half_load_boundary
        """
        ctx = setup_published_routing_guide(**SHARE_CAP_EVENT)
        allocations = list_allocations(lane_id=ctx["lane"]["id"])
        assert len(allocations) == 1
        allocation = allocations[0]
        assert allocation["routing_position"] == "PRIMARY"
        assert allocation["allocated_volume_loads"] == CAPPED_LOADS, (
            "550 x 55.00 / 100 is 302.50 exactly, and the floor of that is 302"
        )
        assert float(allocation["allocated_pct"]) == CAPPED_PCT
        assert float(allocation["allocated_cost_usd"]) == CAPPED_COST_USD

        run = _read_run(ctx["run"]["id"])
        # "The run moves from `COMPLETED` to `PUBLISHED`" once its guide is published.
        assert run["status"] == "PUBLISHED"
        assert run["proposed_primary_count"] == 1
        assert run["proposed_backup_count"] == 0
        assert float(run["total_cost_usd"]) == CAPPED_COST_USD
        assert float(run["coverage_pct"]) == CAPPED_PCT
        assert float(run["diversity_pct"]) == 0.00

    def test_a_proposed_allocation_reserves_nothing_until_it_is_approved(self):
        """The capped volume only leaves the lane's unallocated pool on approval.

        PRD §3.6: "The waterfall itself writes nothing to the lane: it never sets
        `unallocated_volume_loads` and never sets `awarded_coverage_pct`."
        PRD §3.7: "The lane's `unallocated_volume_loads` is reduced by the allocation's
        `allocated_volume_loads`, and the lane's `awarded_coverage_pct` is recomputed as
        `annual_volume_loads` minus `unallocated_volume_loads`, multiplied by `100.00`,
        divided by `annual_volume_loads`, and rounded to 2 decimal places."

        Design: Difficulty/boundary_precision_check/award_share_cap_floor_at_exact_half_load_boundary
        """
        ctx = setup_published_routing_guide(**SHARE_CAP_EVENT)
        allocation = list_allocations(lane_id=ctx["lane"]["id"])[0]
        assert allocation["status"] == "PROPOSED"

        before = read_lane(ctx["lane"]["id"])
        assert before["unallocated_volume_loads"] == 550
        assert float(before["awarded_coverage_pct"]) == 0.00

        approve_allocation(allocation["id"])

        after = read_lane(ctx["lane"]["id"])
        assert after["unallocated_volume_loads"] == 248
        assert float(after["awarded_coverage_pct"]) == CAPPED_PCT
        assert after["unallocated_volume_loads"] + CAPPED_LOADS == 550
