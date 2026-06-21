"""Compensating-action invariants: rider out-of-pocket reconciliation and FSA
benefit-consumed conservation across settle/reverse, plus immediate consistency.

Covers Difficulty queue (A) rule compensating_invariant and Corner queue (B)
consistency_model instance.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    TEST_USERS, make_rider_headers,
    setup_funded_rider, create_captured_tap, fund_allocation,
    get_funding_source, get_fare_week, get_allocation,
    assert_out_of_pocket_conserved,
)


# ─── Difficulty rule compensating_invariant ───────────────────────────────
#   instance: reverse_conserves_rider_out_of_pocket_equals_week_charged_total

def test_settle_then_reverse_conserves_out_of_pocket(api):
    """PRD §2.6: "at every moment `charged_total_cents` must equal the sum of
    `charge_cents` over the week's currently-`CAPTURED` taps, and it is bounded
    below by 0 and above by the effective weekly cap. Reversal is therefore a true
    compensating action — it conserves the rider's total out-of-pocket quantity
    across the week".

    Design: Difficulty/compensating_invariant/reverse_conserves_rider_out_of_pocket_equals_week_charged_total
    """
    initial_balance = 100000
    world = setup_funded_rider(balance=initial_balance)
    t1 = create_captured_tap(world, "2026-06-01T09:00:00Z")
    assert t1["charge_cents"] == 300
    validate_success(api.reverse_tap(t1["id"], TEST_USERS["fare_admin_headers"]), 200)
    fs = get_funding_source(world["rider"]["id"], world["funding_source"]["id"])
    week = get_fare_week(world["rider"]["id"], world["week"]["id"])
    assert fs["prepaid_balance_cents"] == initial_balance
    assert week["charged_total_cents"] == 0
    assert_out_of_pocket_conserved(initial_balance, fs["prepaid_balance_cents"],
                                   week["charged_total_cents"])


def test_invariant_holds_after_capture_before_reverse(api):
    """PRD §2.6: "Its `charged_total_cents` is a computed running sum of the
    out-of-pocket `charge_cents` over the `CAPTURED` taps belonging to that week; it
    starts at 0, increases by a tap's `charge_cents` when that tap is captured".
    After a single capture the (initial - current) balance must equal the week's
    charged_total_cents.

    Design: Difficulty/compensating_invariant/reverse_conserves_rider_out_of_pocket_equals_week_charged_total
    """
    initial_balance = 100000
    world = setup_funded_rider(balance=initial_balance)
    create_captured_tap(world, "2026-06-01T09:00:00Z")
    fs = get_funding_source(world["rider"]["id"], world["funding_source"]["id"])
    week = get_fare_week(world["rider"]["id"], world["week"]["id"])
    assert week["charged_total_cents"] == 300
    assert_out_of_pocket_conserved(initial_balance, fs["prepaid_balance_cents"],
                                   week["charged_total_cents"])


# ─── Difficulty rule compensating_invariant ───────────────────────────────
#   instance: reverse_conserves_benefit_consumed_quantity

def test_reverse_restores_benefit_consumed_and_status(api):
    """PRD §3.10: "if the tap had applied benefit — decrements the relevant
    allocation's `consumed_cents` by `benefit_applied_cents`, restoring that
    allocation's `status` to `ACTIVE` if it had been `EXHAUSTED`."
    PRD §3.5: "When a later reversal decrements `consumed_cents` back below
    `allocated_cents`, an `EXHAUSTED` allocation returns to `ACTIVE`."

    Design: Difficulty/compensating_invariant/reverse_conserves_benefit_consumed_quantity
    """
    world = setup_funded_rider(product_overrides={
        "base_fare_cents": 300, "daily_cap_cents": 5000, "weekly_cap_cents": 5000,
        "transfer_discount_pct": 0})
    alloc = fund_allocation(world["rider"]["id"], world["rider"]["version"],
                            employer_ref="EMP17", period_month="2026-06",
                            allocated_cents=300)
    t1 = create_captured_tap(world, "2026-06-01T09:00:00Z")
    assert t1["benefit_applied_cents"] == 300
    exhausted = get_allocation(world["rider"]["id"], alloc["id"])
    assert exhausted["status"] == "EXHAUSTED"
    validate_success(api.reverse_tap(t1["id"], TEST_USERS["fare_admin_headers"]), 200)
    restored = get_allocation(world["rider"]["id"], alloc["id"])
    assert restored["consumed_cents"] == 0
    assert restored["status"] == "ACTIVE"


def test_capture_consumes_benefit_quantity_matches_applied(api):
    """PRD §3.5: "it is the sum of `benefit_applied_cents` over the `CAPTURED` taps
    that cite this allocation, and it is credited back on reversal."
    After the single capture that consumes the allocation, consumed_cents equals the
    tap's benefit_applied_cents.

    Design: Difficulty/compensating_invariant/reverse_conserves_benefit_consumed_quantity
    """
    world = setup_funded_rider(product_overrides={
        "base_fare_cents": 300, "daily_cap_cents": 5000, "weekly_cap_cents": 5000,
        "transfer_discount_pct": 0})
    alloc = fund_allocation(world["rider"]["id"], world["rider"]["version"],
                            employer_ref="EMP17", period_month="2026-06",
                            allocated_cents=300)
    t1 = create_captured_tap(world, "2026-06-01T09:00:00Z")
    consumed = get_allocation(world["rider"]["id"], alloc["id"])
    assert consumed["consumed_cents"] == t1["benefit_applied_cents"] == 300


# ─── Corner: consistency_model ────────────────────────────────────────────

def test_settle_response_and_balance_immediately_consistent(api):
    """PRD §3.7: "If the funding source's `prepaid_balance_cents` is greater than or
    equal to `charge_cents` ... the tap is `CAPTURED`: the system debits
    `prepaid_balance_cents` by `charge_cents`".
    PRD §3.3: "The balance is the pool from which captured taps are debited and to
    which reversed taps are credited; it must never go below 0." The settle response
    carries the computed charge, and a subsequent read of the funding source shows
    the debit immediately.

    Design: Corner/consistency_model/settle_response_reflects_all_charge_fields_immediately
    """
    world = setup_funded_rider(balance=1000)
    captured = create_captured_tap(world, "2026-06-01T09:00:00Z")
    assert captured["charge_cents"] == 300
    assert captured["status"] == "CAPTURED"
    res = api.list_funding_sources(make_rider_headers(world["rider"]["id"]),
                                   params={"rider_id": world["rider"]["id"]})
    data = validate_success(res, 200)
    assert data[0]["prepaid_balance_cents"] == 700, "debit immediately visible"
