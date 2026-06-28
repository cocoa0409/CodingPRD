"""Patronage distribution: per-member cash floor with waterfalled remainder, close
cascade crediting members, and the empty-pool zero-bushel boundary.

Queue A (Difficulty) — combinatorial_formula (floor-then-waterfall mode_b),
                       transitive_cascade (close -> allocation -> member credit depth2),
                       boundary_precision_check (empty patronage pool).
Queue B (Corner) — (immutability covered in test_01).
"""
import pytest

from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS
import test_helpers.fixtures as fx

MERCH = TEST_USERS["merchandiser_headers"]


def _three_equal_members_period():
    """One CORN commodity + current board; members A,B,C created in order, each settled to
    net_priced_bushels 1000; an OPEN period pool 100000 cash_pct 0.20.
    Returns (member_a, member_b, member_c, period)."""
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    fx.create_price_board(commodity["id"])
    member_a = fx.create_member(name="A Farm")
    fx.settle_member_bushels(commodity["id"], member_a["id"], priced_bushels=1000, member_name="A Farm")
    member_b = fx.create_member(name="B Farm")
    fx.settle_member_bushels(commodity["id"], member_b["id"], priced_bushels=1000, member_name="B Farm")
    member_c = fx.create_member(name="C Farm")
    fx.settle_member_bushels(commodity["id"], member_c["id"], priced_bushels=1000, member_name="C Farm")
    period = fx.open_patronage_period(label="FY2026", pool_dollars=100000, qualified_cash_pct=0.20)
    return member_a, member_b, member_c, period


def _allocation_for(api, member_id):
    data, _meta = validate_paginated(api.list_member_allocations(member_id, MERCH))
    assert len(data) == 1, f"expected one allocation for member {member_id}"
    return data[0]


def test_patronage_close_sets_total_and_lead_member_absorbs_remainder(api):
    """PRD §3.9: "The `cash_dollars` are that raw cash share **floored down to whole
    cents** (rounded down to 2 decimal places)". PRD §3.9: "The entire cash remainder is
    assigned to the first member in the eligible order (the member with the greatest net
    priced bushels, ties broken by earliest `created_at`): that lead member's
    `cash_dollars` is increased by the remainder and its `equity_dollars` is decreased by
    the remainder".

    Design: Difficulty/combinatorial_formula/patronage_floor_then_waterfall_remainder_mode_b
    """
    member_a, member_b, member_c, period = _three_equal_members_period()
    closed = validate_success(api.close_patronage_period(period["id"], MERCH))
    assert closed["total_bushels"] == 3000

    alloc_a = _allocation_for(api, member_a["id"])
    alloc_b = _allocation_for(api, member_b["id"])
    alloc_c = _allocation_for(api, member_c["id"])
    assert alloc_a["allocation_dollars"] == pytest.approx(33333.33, abs=0.01)
    # lead member absorbs the 0.02 remainder
    assert alloc_a["cash_dollars"] == pytest.approx(6666.68, abs=0.01)
    assert alloc_a["equity_dollars"] == pytest.approx(26666.65, abs=0.01)
    assert alloc_b["cash_dollars"] == pytest.approx(6666.66, abs=0.01)
    assert alloc_c["cash_dollars"] == pytest.approx(6666.66, abs=0.01)


def test_patronage_cash_remainder_conserved_across_members(api):
    """PRD §3.9: "the `cash_dollars` are that raw cash share **floored down to whole
    cents**". PRD §3.9: "so the allocation is conserved." PRD §3.9: "That residue — the
    **cash remainder** — is computed as the sum of all allocation dollars multiplied by
    the qualified cash percent and rounded to 2 decimal places, minus the sum of every
    member's floored cash dollars."

    Design: Difficulty/combinatorial_formula/patronage_floor_then_waterfall_remainder_mode_b
    """
    member_a, member_b, member_c, period = _three_equal_members_period()
    validate_success(api.close_patronage_period(period["id"], MERCH))
    cash_total = (
        _allocation_for(api, member_a["id"])["cash_dollars"]
        + _allocation_for(api, member_b["id"])["cash_dollars"]
        + _allocation_for(api, member_c["id"])["cash_dollars"]
    )
    # round(100000 * 0.20, 2) = 20000.00; remainder conserved, not dropped
    assert cash_total == pytest.approx(20000.00, abs=0.01)


def _single_member_period(pool=50000):
    """One member settled to 1000 net_priced_bushels; an OPEN period pool/cash_pct 0.20.
    Returns (member, period)."""
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    fx.create_price_board(commodity["id"])
    member = fx.create_member(name="Gus Farm")
    fx.settle_member_bushels(commodity["id"], member["id"], priced_bushels=1000, member_name="Gus Farm")
    period = fx.open_patronage_period(label="FY2026", pool_dollars=pool, qualified_cash_pct=0.20)
    return member, period


def test_patronage_close_creates_allocation_with_pool_value(api):
    """PRD §3.9: "the system creates a `PatronageAllocation` ... The `allocation_dollars`
    are the pool dollars multiplied by the member's bushels divided by the total bushels,
    rounded to 2 decimal places."

    Design: Difficulty/transitive_cascade/patronage_close_creates_allocation_credits_member_depth2
    """
    member, period = _single_member_period(pool=50000)
    validate_success(api.close_patronage_period(period["id"], MERCH))
    alloc = _allocation_for(api, member["id"])
    # sole eligible member gets the whole pool
    assert alloc["allocation_dollars"] == pytest.approx(50000.00, abs=0.01)


def test_patronage_close_credits_member_equity_and_cash(api):
    """PRD §3.9: "As each allocation is posted, the owning member is credited — the
    member's `equity_credit_dollars` is increased by the allocation's equity dollars and
    the member's `cash_paid_dollars` is increased by the allocation's cash dollars."

    Design: Difficulty/transitive_cascade/patronage_close_creates_allocation_credits_member_depth2
    """
    member, period = _single_member_period(pool=50000)
    before = validate_success(api.get_member(member["id"], MERCH))
    cash_before = before["cash_paid_dollars"]
    validate_success(api.close_patronage_period(period["id"], MERCH))
    after = validate_success(api.get_member(member["id"], MERCH))
    # 50000 alloc: cash floored = 10000.00, equity = 40000.00
    assert after["equity_credit_dollars"] == pytest.approx(40000.00, abs=0.01)
    assert after["cash_paid_dollars"] - cash_before == pytest.approx(10000.00, abs=0.01)


def test_patronage_close_empty_pool_zero_bushels_rejected(api):
    """PRD §3.9: "The period's `total_bushels` is set to the sum of `net_priced_bushels`
    across all members, and this total must be strictly greater than 0 or the close is
    refused with `ERR_EMPTY_PATRONAGE_POOL`."

    Design: Difficulty/boundary_precision_check/empty_patronage_pool_zero_bushels_boundary
    """
    fx.create_member(name="Jo Farm")  # no settlements -> net_priced_bushels 0
    period = fx.open_patronage_period(label="FY2026", pool_dollars=10000, qualified_cash_pct=0.20)
    resp = api.close_patronage_period(period["id"], MERCH)
    validate_error(resp, ApiErrorId.ERR_EMPTY_PATRONAGE_POOL.value)


def test_patronage_close_empty_pool_leaves_period_open(api):
    """PRD §3.9: "this total must be strictly greater than 0 or the close is refused with
    `ERR_EMPTY_PATRONAGE_POOL`." PRD §3.9: "**Closing** the period moves it from `OPEN` to
    `CLOSED`".

    Design: Difficulty/boundary_precision_check/empty_patronage_pool_zero_bushels_boundary
    """
    fx.create_member(name="Jo2 Farm")
    period = fx.open_patronage_period(label="FY2026", pool_dollars=10000, qualified_cash_pct=0.20)
    api.close_patronage_period(period["id"], MERCH)
    after = validate_success(api.get_patronage_period(period["id"], MERCH))
    assert after["status"] == "OPEN", "rejected close must leave the period OPEN"
