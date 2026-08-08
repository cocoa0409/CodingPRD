"""Rent, platform-fee, and payout-net calculations, including the dual-variant
provisional/final divergence and the pinned round-per-month-then-sum rule.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula.
Queue B (Corner): calculations.
"""
from test_helpers import (
    get_success_data, PayoutBasis,
    register_host, register_tenant, create_unit, request_booking, confirm_booking,
    activate_booking, complete_booking, set_clock,
    get_payout_for_booking,
    make_tenant_headers,
    create_booking_payload,
)


# --------------------------------------------------------------------------
# dual_variant_calc / booking_rent_provisional_vs_final
# --------------------------------------------------------------------------

def _completed_rent_scenario(api, *, rate, start, end, activate_clock=None, complete_clock=None):
    """Full lifecycle; returns (rent_provisional_at_creation, completed_booking)."""
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True,
                       deposit_cents=0, monthly_rate_cents=rate)
    booking = request_booking(api, unit["id"], tenant["id"], start, end)
    rent_prov = booking["rent_cents"]
    confirm_booking(api, booking["id"], host["id"])
    if activate_clock:
        set_clock(api, activate_clock)
    activate_booking(api, booking["id"])
    if complete_clock:
        set_clock(api, complete_clock)
    completed = complete_booking(api, booking["id"])
    return rent_prov, completed


def test_booking_rent_provisional_at_creation(api):
    """PRD §3.3: "The provisional `rent_cents` is computed on a thirty-day-month
    convention: the monthly rate multiplied by the term in days and divided by a
    thirty-day month, rounded half up to whole cents — that is,
    `monthly_rate_cents` times `term_days` divided by thirty."

    Design: Difficulty/dual_variant_calc/booking_rent_provisional_vs_final
    """
    rent_prov, _ = _completed_rent_scenario(
        api, rate=300000, start="2026-06-15", end="2026-07-15",
        activate_clock="2026-07-15T00:00:00Z", complete_clock="2026-07-15T00:00:00Z")
    assert rent_prov == 300000, f"provisional rent must be 300000 (300000*30/30), got {rent_prov}"


def test_booking_rent_final_diverges_after_completion(api):
    """PRD §3.6: "for each calendar month that the occupancy window touches, the
    platform takes the number of days of that month that fall inside the half-open
    window, divides by the actual number of days in that month (28, 29, 30, or 31),
    multiplies by `monthly_rate_cents`, and rounds that month's contribution half
    up to whole cents; the finalized rent is the sum of those per-month rounded
    contributions."

    Design: Difficulty/dual_variant_calc/booking_rent_provisional_vs_final
    """
    rent_prov, completed = _completed_rent_scenario(
        api, rate=300000, start="2026-06-15", end="2026-07-15",
        activate_clock="2026-07-15T00:00:00Z", complete_clock="2026-07-15T00:00:00Z")
    assert completed["rent_cents"] == 295484, \
        f"final rent must be 295484 (160000 Jun + 135484 Jul), got {completed['rent_cents']}"
    assert completed["rent_basis"] == PayoutBasis.FINAL.value
    assert rent_prov != completed["rent_cents"], "provisional and final rent must diverge"


# --------------------------------------------------------------------------
# dual_variant_calc / payout_net_provisional_vs_final
# --------------------------------------------------------------------------

def test_payout_net_provisional_while_pending(api):
    """PRD §3.4: "A `Payout` is created on the `PROVISIONAL` basis in state
    `PENDING`, its `gross_rent_cents` snapshotted from the booking's gross rent,
    its `platform_fee_cents` computed by the fee rule below, its
    `deposit_adjustment_cents` at zero, and its `net_cents` equal to gross rent
    minus platform fee."

    Design: Difficulty/dual_variant_calc/payout_net_provisional_vs_final
    """
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True, tenant_type="RELOCATION")
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True,
                       deposit_cents=0, monthly_rate_cents=300000)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-08-10", "2026-09-10")
    confirm_booking(api, booking["id"], host["id"])
    payout = get_payout_for_booking(api, booking["id"])
    assert payout["net_cents"] == 272800, f"provisional net must be 272800 (310000-37200), got {payout['net_cents']}"
    assert payout["payout_basis"] == PayoutBasis.PROVISIONAL.value


def test_payout_net_final_after_completion_diverges(api):
    """PRD §3.6: "the payout's `gross_rent_cents` is reset to the booking's final
    gross, its `platform_fee_cents` is recomputed against the final gross, its
    `net_cents` is recomputed, its `payout_basis` becomes `FINAL`, and the host's
    `projected_payout_cents` is recomputed."

    Design: Difficulty/dual_variant_calc/payout_net_provisional_vs_final
    """
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True, tenant_type="RELOCATION")
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True,
                       deposit_cents=0, monthly_rate_cents=300000)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-08-10", "2026-09-10")
    confirm_booking(api, booking["id"], host["id"])
    prov = get_payout_for_booking(api, booking["id"])
    set_clock(api, "2026-09-10T00:00:00Z")
    activate_booking(api, booking["id"])
    complete_booking(api, booking["id"])
    final = get_payout_for_booking(api, booking["id"])
    assert final["net_cents"] == 266555, f"final net must be 266555 (302903-36348), got {final['net_cents']}"
    assert final["payout_basis"] == PayoutBasis.FINAL.value
    assert final["net_cents"] != prov["net_cents"], "payout net must diverge between provisional and final"


# --------------------------------------------------------------------------
# combinatorial_formula / platform_fee_tiered_with_nested_cap
# --------------------------------------------------------------------------

def _fee_cap_scenario(api):
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True,
                       utilities_included=False, deposit_cents=0, monthly_rate_cents=1000000)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-08-30")
    confirm_booking(api, booking["id"], host["id"])
    return get_payout_for_booking(api, booking["id"])


def test_platform_fee_gross_snapshot(api):
    """PRD §3.4: "A `Payout` is created on the `PROVISIONAL` basis in state
    `PENDING`, its `gross_rent_cents` snapshotted from the booking's gross rent".

    Design: Difficulty/combinatorial_formula/platform_fee_tiered_with_nested_cap
    """
    payout = _fee_cap_scenario(api)
    assert payout["gross_rent_cents"] == 3000000, \
        f"gross must be 3000000 (rent 3000000 + 0 cleaning), got {payout['gross_rent_cents']}"


def test_platform_fee_clamped_to_ceiling(api):
    """PRD §3.4: "The stored `platform_fee_cents` is then clamped to lie between a
    floor of 5,000 cents ($50.00) and a ceiling of 200,000 cents ($2,000.00): a
    raw fee below the floor is raised to the floor, and one above the ceiling is
    lowered to the ceiling."

    Design: Difficulty/combinatorial_formula/platform_fee_tiered_with_nested_cap
    """
    payout = _fee_cap_scenario(api)
    # term 90 -> tier 0.08; raw = round(3000000 * 0.08) = 240000 -> clamped to 200000.
    assert payout["platform_fee_cents"] == 200000, \
        f"fee must be clamped to the 200000 ceiling, got {payout['platform_fee_cents']}"


# --------------------------------------------------------------------------
# combinatorial_formula / booking_rent_rounding_order_pinned
# --------------------------------------------------------------------------

def test_provisional_rent_uses_thirty_day_convention(api):
    """PRD §3.3: "the monthly rate multiplied by the term in days and divided by a
    thirty-day month, rounded half up to whole cents — that is,
    `monthly_rate_cents` times `term_days` divided by thirty."

    Design: Difficulty/combinatorial_formula/booking_rent_rounding_order_pinned
    """
    # Default clock 2026-05-01 is already past a Feb-Mar window, so no clock moves.
    rent_prov, _ = _completed_rent_scenario(
        api, rate=200000, start="2026-02-05", end="2026-03-20")
    assert rent_prov == 286667, f"provisional rent must be 286667 (round(200000*43/30)), got {rent_prov}"


def test_final_rent_round_per_month_then_sum_pinned(api):
    """PRD §3.6: "The rounding is pinned to round-each-month-then-sum — the
    platform never sums the raw monthly amounts and rounds once at the end,
    because the two approaches can differ by a cent."

    Design: Difficulty/combinatorial_formula/booking_rent_rounding_order_pinned
    """
    _, completed = _completed_rent_scenario(
        api, rate=200000, start="2026-02-05", end="2026-03-20")
    # Feb round(200000*23/28)=171429 + Mar round(200000*19/31)=122581 = 294010
    # (sum-then-round would give 294009).
    assert completed["rent_cents"] == 294010, \
        f"final rent must be 294010 (round-per-month-then-sum), got {completed['rent_cents']}"


# --------------------------------------------------------------------------
# calculations / cleaning_charge_added_when_not_included  (Corner)
# --------------------------------------------------------------------------

def test_cleaning_charge_added_when_not_included(api):
    """PRD §3.3: "The `cleaning_charge_cents` is zero when the unit's
    `cleaning_included` is true and otherwise equals the unit's
    `cleaning_fee_cents`. The `gross_rent_cents` is the sum of `rent_cents` and
    `cleaning_charge_cents`."

    Design: Corner/calculations/cleaning_charge_added_when_not_included
    """
    host = register_host(api, verify_payout=False)
    tenant = register_tenant(api, verified=False)
    unit = create_unit(api, host["id"], listed=False, cleaning_included=False,
                       cleaning_fee_cents=15000, monthly_rate_cents=300000)
    booking = get_success_data(api.create_booking(
        create_booking_payload(unit["id"], tenant["id"], "2026-06-01", "2026-07-01"),
        make_tenant_headers(tenant["id"]),
    ))
    assert booking["rent_cents"] == 300000, f"rent must be 300000, got {booking['rent_cents']}"
    assert booking["cleaning_charge_cents"] == 15000, \
        f"cleaning_charge must be 15000, got {booking['cleaning_charge_cents']}"
    assert booking["gross_rent_cents"] == 315000, \
        f"gross must be 300000 + 15000 = 315000, got {booking['gross_rent_cents']}"
