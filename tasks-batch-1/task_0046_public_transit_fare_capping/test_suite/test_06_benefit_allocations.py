"""Transit FSA benefit allocations: the settle/reverse cascades that consume and
restore an allocation, and the optimistic-concurrency supersession path.

Covers Difficulty queue (A) rule transitive_cascade and Corner queue (B)
cross_cutting_complexity_layers OCC instances.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_benefit_allocation_payload,
    TEST_USERS, make_rider_headers,
    set_clock, make_fare_product, register_rider, add_funding_source, load_balance,
    open_week, record_tap, settle, create_captured_tap, setup_funded_rider,
    fund_allocation, get_allocation, get_funding_source, get_fare_week,
    ApiErrorId,
)


# ─── Difficulty rule transitive_cascade ───────────────────────────────────
#   instance: settle_captures_then_consumes_benefit_then_exhausts_allocation_depth3

def test_settle_consumes_then_exhausts_allocation(api):
    """PRD §3.7: "if `benefit_applied_cents` is greater than 0 it increments the
    chosen allocation's `consumed_cents` by `benefit_applied_cents`, and if that
    brings `consumed_cents` up to `allocated_cents` it sets the allocation's
    `status` to `EXHAUSTED`".
    PRD §3.5: "When a capture applies benefit and the resulting `consumed_cents`
    reaches `allocated_cents`, the allocation transitions from `ACTIVE` to
    `EXHAUSTED` and stops being eligible to subsidize future taps."

    Design: Difficulty/transitive_cascade/settle_captures_then_consumes_benefit_then_exhausts_allocation_depth3
    """
    world = setup_funded_rider(product_overrides={
        "base_fare_cents": 300, "daily_cap_cents": 5000, "weekly_cap_cents": 5000,
        "transfer_discount_pct": 0})
    alloc = fund_allocation(world["rider"]["id"], world["rider"]["version"],
                            employer_ref="EMP1", period_month="2026-06",
                            allocated_cents=300)  # exactly one tap's worth
    tap = create_captured_tap(world, "2026-06-01T09:00:00Z")
    assert tap["status"] == "CAPTURED"
    assert tap["benefit_applied_cents"] == 300
    assert tap["charge_cents"] == 0
    refreshed = get_allocation(world["rider"]["id"], alloc["id"])
    assert refreshed["consumed_cents"] == 300
    assert refreshed["status"] == "EXHAUSTED"


def test_settle_full_benefit_leaves_funding_source_undebited(api):
    """PRD §3.7: "The final out-of-pocket `charge_cents` is the billable amount minus
    `benefit_applied_cents`, which is non-negative by construction." When benefit
    covers the whole billable amount the out-of-pocket charge is 0, so the funding
    source is not debited.

    Design: Difficulty/transitive_cascade/settle_captures_then_consumes_benefit_then_exhausts_allocation_depth3
    """
    world = setup_funded_rider(product_overrides={
        "base_fare_cents": 300, "daily_cap_cents": 5000, "weekly_cap_cents": 5000,
        "transfer_discount_pct": 0})
    fund_allocation(world["rider"]["id"], world["rider"]["version"],
                    employer_ref="EMP1", period_month="2026-06", allocated_cents=300)
    create_captured_tap(world, "2026-06-01T09:00:00Z")
    fs = get_funding_source(world["rider"]["id"], world["funding_source"]["id"])
    assert fs["prepaid_balance_cents"] == 100000, "whole fare paid from FSA; no debit"


# ─── Difficulty rule transitive_cascade ───────────────────────────────────
#   instance: reverse_credits_funds_then_decrements_week_depth2

def test_reverse_credits_funds_and_decrements_week(api):
    """PRD §3.10: "On reversal the system credits the funding source's
    `prepaid_balance_cents` by the tap's `charge_cents`, decrements the fare week's
    `charged_total_cents` by that same `charge_cents` so the weekly reconciliation
    invariant holds ... The tap moves to the terminal `REVERSED` status".

    Design: Difficulty/transitive_cascade/reverse_credits_funds_then_decrements_week_depth2
    """
    world = setup_funded_rider(balance=1000)
    t1 = create_captured_tap(world, "2026-06-01T09:00:00Z")
    assert t1["charge_cents"] == 300
    res = api.reverse_tap(t1["id"], TEST_USERS["fare_admin_headers"])
    reversed_tap = validate_success(res, 200)
    assert reversed_tap["status"] == "REVERSED"
    fs = get_funding_source(world["rider"]["id"], world["funding_source"]["id"])
    assert fs["prepaid_balance_cents"] == 1000, "300 credited back"
    week = get_fare_week(world["rider"]["id"], world["week"]["id"])
    assert week["charged_total_cents"] == 0, "300 decremented"


def test_capture_then_reverse_leaves_tap_terminal(api):
    """PRD §3.10: "The tap moves to the terminal `REVERSED` status, and `updated_at`
    and `version` are refreshed on the tap, the funding source, the fare week, and
    any touched allocation."

    Design: Difficulty/transitive_cascade/reverse_credits_funds_then_decrements_week_depth2
    """
    world = setup_funded_rider(balance=1000)
    t1 = create_captured_tap(world, "2026-06-01T09:00:00Z")
    validate_success(api.reverse_tap(t1["id"], TEST_USERS["fare_admin_headers"]), 200)
    # Reversal is terminal; a second reverse is no longer defined.
    res = api.reverse_tap(t1["id"], TEST_USERS["fare_admin_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ─── Corner: cross_cutting_complexity_layers (OCC) ────────────────────────

def test_supersede_with_stale_version_returns_412(api):
    """PRD §2.7: "the server compares `expected_rider_version` against the rider's
    current `version`; if they do not match ... the create is rejected with
    `ERR_STALE_RIDER_VERSION` (HTTP 412), and no allocation is created or
    superseded."
    PRD §2.7: "A successful supersede increments the rider's `version` by one, which
    is precisely why two strictly sequential creates that each present the rider's
    last-observed version cannot both succeed".

    Design: Corner/cross_cutting_complexity_layers/benefit_allocation_supersede_stale_version_returns_412
    """
    make_fare_product(zone_code="ZONEX")
    rider = register_rider(home_zone_code="ZONEX", email="rz@x.com")
    v1 = rider["version"]
    # The initial create for a (rider, month) with no prior active allocation is
    # NOT a supersede (§3.5: "When no active allocation yet exists ... the create
    # simply produces a new ACTIVE allocation"), so it does not advance the rider's
    # version — the OCC check and version bump fire only on a supersede (§2.7).
    fund_allocation(rider["id"], v1, employer_ref="EMPZ1", period_month="2026-06",
                    allocated_cents=500)
    # A first VALID supersede presenting v1 succeeds and advances Rider.version to v1+1
    # (§2.7: "A successful supersede increments the rider's `version` by one").
    fund_allocation(rider["id"], v1, employer_ref="EMPZ2", period_month="2026-06",
                    allocated_cents=600)
    # A second supersede still carrying the now-stale v1 must be rejected — this is
    # the "two strictly sequential [supersede] creates ... cannot both succeed" case.
    res = api.create_benefit_allocation(
        create_benefit_allocation_payload(rider["id"], v1, employer_ref="EMPZ3",
                                          period_month="2026-06", allocated_cents=800),
        TEST_USERS["employer_admin_headers"])
    validate_error(res, ApiErrorId.ERR_STALE_RIDER_VERSION.value, expected_status=412)


def test_supersede_with_current_version_succeeds(api):
    """PRD §3.5: "A valid supersede sets the prior allocation's `status` to
    `SUPERSEDED`, creates the replacement as `ACTIVE` with its `consumed_cents`
    reset to 0 (the consumed amount is **not** carried over from the superseded
    allocation), and increments the rider's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/benefit_allocation_supersede_with_current_version_succeeds
    """
    make_fare_product(zone_code="ZONEX")
    rider = register_rider(home_zone_code="ZONEX", email="ry@x.com")
    first = fund_allocation(rider["id"], rider["version"], employer_ref="EMPY1",
                            period_month="2026-06", allocated_cents=500)
    # Re-read the rider's current version after the first create advanced it.
    current = validate_success(api.get_rider(
        rider["id"], TEST_USERS["employer_admin_headers"]), 200)
    res = api.create_benefit_allocation(
        create_benefit_allocation_payload(rider["id"], current["version"],
                                          employer_ref="EMPY2", period_month="2026-06",
                                          allocated_cents=800),
        TEST_USERS["employer_admin_headers"])
    replacement = validate_success(res, 201)
    assert replacement["status"] == "ACTIVE"
    assert replacement["consumed_cents"] == 0
    prior = get_allocation(rider["id"], first["id"])
    assert prior["status"] == "SUPERSEDED"
