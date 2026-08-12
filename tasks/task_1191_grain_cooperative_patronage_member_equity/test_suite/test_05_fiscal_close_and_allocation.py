"""Provisional close preconditions and the tiered allocation waterfall
(PRD §2.10, §3.3)."""
from test_helpers import (
    validate_error,
    assert_allocation_slice_identity,
    create_district, create_member, create_fiscal_year, set_clock,
    book_delivery, close_year_provisional, get_fiscal_year,
    setup_year_with_deliveries, list_year_allocations,
    get_allocation_for_member,
    TEST_USERS,
)

ACCOUNTANT = TEST_USERS["accountant_headers"]


def test_close_provisional_with_booked_delivery_fails(api):
    """PRD §3.3: "When the year has run its course — the logical clock has
    reached the year's `end_date` and no delivery in the year remains
    `BOOKED` (every delivery is `SETTLED` or `CANCELLED`) — the accountant
    performs the provisional close, moving the year from `OPEN` to
    `CLOSED_PROVISIONAL`."
    PRD §2.10: "The resource is in a valid source state for the requested
    transition — otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/fiscal_year_close_provisional_from_open_with_booked_delivery_fails
    """
    set_clock("2025-09-01T00:00:00Z")
    district = create_district()
    member = create_member(district["id"])
    fy = create_fiscal_year()
    book_delivery(member["id"], fy["id"], commodity="CORN", gross_bushels=50)
    set_clock("2026-09-01T00:00:00Z")
    res = api.close_provisional(fy["id"], ACCOUNTANT)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = get_fiscal_year(fy["id"])
    assert after["status"] == "OPEN"


def test_tier_boundary_999_bushels_is_t1(api):
    """PRD §3.3: "a member whose `allocated_volume_bu` is at least 10000
    bushels is tier `T3` and uses a rate modifier of 1.10; at least 1000
    bushels (but below 10000) is tier `T2` with a modifier of 1.05; below
    1000 is tier `T1` with a modifier of 1.00. The boundary is inclusive on
    the lower bound — a volume of exactly 1000 bushels classifies as `T2`,
    and exactly 10000 as `T3` — and the resulting tier is recorded on the
    allocation as `tier_code`."

    Design: Difficulty/boundary_precision_check/tier_volume_boundary_at_1000_bushels
    """
    ctx = setup_year_with_deliveries(
        [{"member_key": "low", "commodity": "CORN", "gross_bushels": 999}],
    )
    fy = close_year_provisional(ctx["fiscal_year"]["id"])
    alloc = get_allocation_for_member(fy["id"], ctx["members"]["low"]["id"])
    assert alloc["allocated_volume_bu"] == 999
    assert alloc["tier_code"] == "T1", (
        f"999 bushels is below the T2 bound; got {alloc['tier_code']}"
    )


def test_tier_boundary_1000_bushels_is_t2(api):
    """PRD §3.3: "The boundary is inclusive on the lower bound — a volume of
    exactly 1000 bushels classifies as `T2`, and exactly 10000 as `T3` — and
    the resulting tier is recorded on the allocation as `tier_code`."

    Design: Difficulty/boundary_precision_check/tier_volume_boundary_at_1000_bushels
    """
    ctx = setup_year_with_deliveries(
        [{"member_key": "edge", "commodity": "CORN", "gross_bushels": 1000}],
    )
    fy = close_year_provisional(ctx["fiscal_year"]["id"])
    alloc = get_allocation_for_member(fy["id"], ctx["members"]["edge"]["id"])
    assert alloc["allocated_volume_bu"] == 1000
    assert alloc["tier_code"] == "T2", (
        f"1000 bushels meets the inclusive T2 bound; got {alloc['tier_code']}"
    )


def test_tiered_allocation_tiers_and_pool(api):
    """PRD §3.3: "The provisional close first computes `patronage_pool_cents`:
    the year's `net_margin_cents` multiplied by one minus the
    `retained_reserve_pct`, rounded half-up to whole cents."
    PRD §3.3: "The boundary is inclusive on the lower bound — a volume of
    exactly 1000 bushels classifies as `T2`, and exactly 10000 as `T3` — and
    the resulting tier is recorded on the allocation as `tier_code`."

    Design: Difficulty/combinatorial_formula/patronage_allocation_tiered_formula_with_conditional_branches
    """
    ctx = setup_year_with_deliveries(
        [
            {"member_key": "m_t2", "commodity": "WHEAT", "gross_bushels": 1000},
            {"member_key": "m_t3", "commodity": "WHEAT",
             "gross_bushels": 10000},
        ],
        net_margin_cents=2000000, retained_reserve_pct=0.25,
        qualified_payout_pct=0.50,
    )
    fy = close_year_provisional(ctx["fiscal_year"]["id"])
    # round_half_up(2_000_000 * (1 - 0.25)) = 1_500_000
    assert fy["patronage_pool_cents"] == 1500000, (
        f"Pool must be 1500000, got {fy['patronage_pool_cents']}"
    )
    alloc_t2 = get_allocation_for_member(
        fy["id"], ctx["members"]["m_t2"]["id"],
    )
    alloc_t3 = get_allocation_for_member(
        fy["id"], ctx["members"]["m_t3"]["id"],
    )
    assert alloc_t2["tier_code"] == "T2"
    assert alloc_t3["tier_code"] == "T3"
    assert alloc_t2["allocated_volume_bu"] == 1000
    assert alloc_t3["allocated_volume_bu"] == 10000


def test_tiered_allocation_slice_identities_and_pool_sum(api):
    """PRD §3.3: "The cash the member actually receives, `cash_paid_cents`,
    is the qualified slice multiplied by the year's `qualified_payout_pct`,
    rounded half-up; the rest of the qualified slice,
    `qualified_equity_issued_cents`, is issued as qualified equity, so any
    rounding residual inside the qualified slice lands in equity rather than
    cash."
    PRD §3.3: "Finally, because per-member rounding can drift the sum of
    slices away from the pool, the reconciliation posts any cents lost or
    gained across all members to the member with the largest allocated
    volume, breaking ties by the earliest `joined_at`. The pool conservation
    invariant of §2.9 must hold exactly once this reconciliation is posted."

    Design: Difficulty/combinatorial_formula/patronage_allocation_tiered_formula_with_conditional_branches
    """
    ctx = setup_year_with_deliveries(
        [
            {"member_key": "m_t2", "commodity": "WHEAT", "gross_bushels": 1000},
            {"member_key": "m_t3", "commodity": "WHEAT",
             "gross_bushels": 10000},
        ],
        net_margin_cents=2000000, retained_reserve_pct=0.25,
        qualified_payout_pct=0.50,
    )
    fy = close_year_provisional(ctx["fiscal_year"]["id"])
    allocations = list_year_allocations(fy["id"])
    assert len(allocations) == 2
    total = 0
    for alloc in allocations:
        assert_allocation_slice_identity(alloc)
        total += (
            alloc["cash_paid_cents"]
            + alloc["qualified_equity_issued_cents"]
            + alloc["nonqualified_allocation_cents"]
        )
    assert total == fy["patronage_pool_cents"] == 1500000, (
        f"Allocated slices must re-sum to the pool; got total {total}"
    )
