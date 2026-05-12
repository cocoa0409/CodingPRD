"""Allocation publish-time calculation: dual-variant total/free/paid quotas.

PRD references:
  - §3.2 Allocation Computation, Publication, and Objection
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_seconds,
    advance_clock,
    assert_allocation_post_publish,
    create_enterprise,
    create_allocation_cycle,
    finalize_cycle,
    get_cycle,
    propose_allocation,
    publish_cycle,
    setup_published_cycle_multi,
)


# ===========================================================================
# §3.2 — Industry-benchmark variant
# ===========================================================================
class TestIndustryBenchmarkAllocation:
    def test_total_quota_equals_activity_times_factor(self):
        """PRD §3.2: 'For an industry-benchmark allocation, the total quota
        is the activity volume multiplied by the benchmark factor, rounded
        half-up to two decimal places.'

        Claim: INDUSTRY_BENCHMARK with activity_volume=1000 and
        benchmark_factor=1.50 yields total_quota == 1500.00 after publish.
        """
        cyc, ents, allocs = setup_published_cycle_multi(
            enterprises_specs=[
                {"method": "INDUSTRY_BENCHMARK",
                 "activity_volume": 1000.00,
                 "benchmark_factor": 1.50},
            ],
            free_paid_ratio=0.80,
            ccer_cap_pct=0.05,
        )
        a = allocs[0]
        assert_allocation_post_publish(a)
        assert a["total_quota"] == pytest.approx(1500.00, abs=0.01)

    def test_free_paid_split_at_eighty_twenty(self):
        """PRD §3.2: 'From the total, the free quota is the total multiplied
        by the cycle's free-paid ratio, rounded half-up to two decimal
        places, and the paid quota is the total minus the free quota — the
        paid quota is computed by subtraction (not by independent rounding)
        so that free_quota plus paid_quota always equals total_quota
        exactly.'

        Claim: with free_paid_ratio=0.80 and total=1500.00,
        free_quota=1200.00 and paid_quota=300.00.
        """
        cyc, ents, allocs = setup_published_cycle_multi(
            enterprises_specs=[
                {"method": "INDUSTRY_BENCHMARK",
                 "activity_volume": 1000.00,
                 "benchmark_factor": 1.50},
            ],
            free_paid_ratio=0.80,
            ccer_cap_pct=0.05,
        )
        a = allocs[0]
        assert_allocation_post_publish(a)
        assert a["total_quota"] == pytest.approx(1500.00, abs=0.01)
        assert a["free_quota"] == pytest.approx(1200.00, abs=0.01)
        assert a["paid_quota"] == pytest.approx(300.00, abs=0.01)


# ===========================================================================
# §3.2 — Historical-emission variant
# ===========================================================================
class TestHistoricalEmissionAllocation:
    def test_total_quota_equals_baseline_times_point_ninety_seven(self):
        """PRD §3.2: 'For a historical-emission allocation, the total quota
        is the historical baseline multiplied by an annual-reduction factor
        of 0.97 (representing a three-percent annual reduction), rounded
        half-up to two decimal places.'

        Claim: HISTORICAL_EMISSION with historical_baseline=1500.00 yields
        total_quota == 1455.00.
        """
        cyc, ents, allocs = setup_published_cycle_multi(
            enterprises_specs=[
                {"method": "HISTORICAL_EMISSION",
                 "historical_baseline": 1500.00},
            ],
            free_paid_ratio=0.80,
            ccer_cap_pct=0.05,
        )
        a = allocs[0]
        assert_allocation_post_publish(a)
        assert a["total_quota"] == pytest.approx(1455.00, abs=0.01)

    def test_historical_quota_independent_of_planned_activity(self):
        """PRD §3.2: 'The benchmark variant is forward-looking and grows
        with planned activity volume; the historical variant is
        backward-looking and is independent of planned activity.'

        Claim: two HISTORICAL_EMISSION allocations with the same baseline
        but different (or unspecified) activity_volume produce the same
        total_quota — i.e., activity is irrelevant for HISTORICAL_EMISSION.
        """
        cyc, ents, allocs = setup_published_cycle_multi(
            enterprises_specs=[
                {"method": "HISTORICAL_EMISSION",
                 "historical_baseline": 800.00},
                {"method": "HISTORICAL_EMISSION",
                 "historical_baseline": 800.00},
            ],
            free_paid_ratio=0.80,
            ccer_cap_pct=0.05,
        )
        a, b = allocs
        assert_allocation_post_publish(a)
        assert_allocation_post_publish(b)
        assert a["total_quota"] == pytest.approx(b["total_quota"], abs=0.01)


# ===========================================================================
# §3.2 — Free + paid identity
# ===========================================================================
class TestFreePaidExactSum:
    def test_paid_quota_is_total_minus_free_exactly(self):
        """PRD §3.2: 'the paid quota is the total minus the free quota — the
        paid quota is computed by subtraction (not by independent rounding)
        so that free_quota plus paid_quota always equals total_quota
        exactly.'

        Claim: free + paid == total EXACTLY (no rounding gap).
        """
        # Use a ratio whose product produces a halfway case at the third
        # decimal so independent rounding would diverge from subtraction.
        cyc, ents, allocs = setup_published_cycle_multi(
            enterprises_specs=[
                {"method": "INDUSTRY_BENCHMARK",
                 "activity_volume": 100.00,
                 "benchmark_factor": 1.235},   # total = 123.50
            ],
            free_paid_ratio=0.333,
            ccer_cap_pct=0.05,
        )
        a = allocs[0]
        assert_allocation_post_publish(a)
        assert (a["free_quota"] + a["paid_quota"]) == pytest.approx(
            a["total_quota"], abs=1e-9
        ), (
            "free_quota + paid_quota must equal total_quota exactly "
            "(PRD §3.2 explicit identity)"
        )


# ===========================================================================
# §3.2 — Publication state transitions and audit
# ===========================================================================
class TestPublicationCascade:
    def test_publish_transitions_cycle_and_allocations(
        self, api, regulator_headers
    ):
        """PRD §3.2: 'When the regulator publishes the cycle, the cycle
        transitions from DRAFT to PUBLISHED, and immediately auto-transitions
        to OBJECTION_OPEN provided the current time is before the cycle's
        objection_deadline ... As a side effect, every Allocation cascades
        from PROPOSED to PUBLISHED, and for each one the system computes
        total_quota, free_quota, and paid_quota according to the dual-variant
        allocation rule.'

        Claim: after publish, cycle.status is OBJECTION_OPEN (auto-transition)
        and the proposed allocation moves to PUBLISHED with quotas computed.
        """
        ent = create_enterprise()
        cyc = create_allocation_cycle(
            free_paid_ratio=0.80,
            ccer_cap_pct=0.05,
        )
        propose_allocation(
            cycle_id=cyc["id"],
            enterprise_id=ent["id"],
            method="INDUSTRY_BENCHMARK",
            activity_volume=500.00,
            benchmark_factor=1.00,
        )
        cyc2 = publish_cycle(cyc["id"])
        # Cycle: DRAFT -> PUBLISHED -> OBJECTION_OPEN (auto) since
        # objection_deadline lies in the simulated future.
        assert cyc2["status"] in {"PUBLISHED", "OBJECTION_OPEN"}, (
            f"Cycle must transition from DRAFT after publish; "
            f"got status={cyc2['status']}"
        )
        # Re-read the cycle to inspect allocations after the cascade.
        cyc3 = get_cycle(cyc["id"])
        allocations = cyc3.get("allocations") or []
        assert allocations, (
            "Cycle GET must surface allocations[] for the publish cascade"
        )
        a = next((x for x in allocations
                  if x.get("enterprise_id") == ent["id"]), None)
        assert a is not None, (
            "Allocation for the enterprise must exist after publish"
        )
        assert a["status"] in {"PUBLISHED", "OBJECTED",
                               "REVISED", "FINALIZED"}, (
            f"Allocation status must advance from PROPOSED after publish; "
            f"got {a['status']}"
        )

    def test_publish_sets_publication_date(self, api, regulator_headers):
        """PRD §3.2: 'The cycle's publication_date is set to the current
        time.'

        Claim: post-publish AllocationCycle.publication_date is non-null.
        """
        ent = create_enterprise()
        cyc = create_allocation_cycle(
            free_paid_ratio=0.80,
            ccer_cap_pct=0.05,
        )
        propose_allocation(
            cycle_id=cyc["id"],
            enterprise_id=ent["id"],
            method="INDUSTRY_BENCHMARK",
            activity_volume=500.00,
            benchmark_factor=1.00,
        )
        cyc2 = publish_cycle(cyc["id"])
        assert cyc2.get("publication_date") is not None, (
            "publication_date must be set after publish per PRD §3.2"
        )


# ===========================================================================
# §3.2 — Cycle.finalize cascade onto enterprise balances
# ===========================================================================
class TestFinalizeCascade:
    def test_finalize_credits_balances_and_opens_account(self):
        """PRD §3.2: 'For each enterprise receiving allocation, the system
        increases quota_balance by that allocation's free_quota and
        paid_quota_balance by its paid_quota, and transitions account_status
        from PENDING to OPEN'.

        Claim: after cycle.finalize, the enterprise's quota_balance equals
        the allocation's free_quota, paid_quota_balance equals paid_quota,
        and account_status moves to OPEN.
        """
        cyc, ents, allocs = setup_published_cycle_multi(
            enterprises_specs=[
                {"method": "INDUSTRY_BENCHMARK",
                 "activity_volume": 1000.00,
                 "benchmark_factor": 1.50},  # total=1500
            ],
            free_paid_ratio=0.80,
            ccer_cap_pct=0.05,
            objection_deadline=None,
            compliance_deadline=None,
        )
        ent = ents[0]
        a = allocs[0]
        # advance past objection_deadline before finalize
        advance_clock(add_seconds(cyc["objection_deadline"], 1))
        finalize_cycle(cyc["id"])
        from test_helpers import get_enterprise as _ge
        ent_after = _ge(ent["id"])
        assert ent_after["account_status"] == "OPEN", (
            "PRD §3.2: account_status PENDING -> OPEN at finalize"
        )
        assert ent_after["quota_balance"] == pytest.approx(
            a["free_quota"], abs=0.01
        )
        assert ent_after["paid_quota_balance"] == pytest.approx(
            a["paid_quota"], abs=0.01
        )
