"""Quote pricing: pinned per-leg rounding, pinned discount/surcharge
evaluation order, and the rate-card / fee constants."""
from test_helpers import (
    setup_quoted_trip,
)

# Canonical quote arithmetic (LIGHT_JET 250000/h, MIDSIZE_JET 400000/h):
#   37min REV -> round_half_up(37*250000/60) = 154167 (twice)
#   10min POS -> round_half_up(10*250000/60*0.6) = 25000
#   480min REV -> 2000000 (tier-1 discount boundary, 5% off)
#   120min REV MIDSIZE + fuel stop + international -> 800000 + fees


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / quote_per_leg_rounding_pinned
# ---------------------------------------------------------------------------

def test_quote_per_leg_rounding_then_sum_pinned(api):
    """PRD §2.6: "Where a calculation has multiple rounding steps, the
    rounding order is pinned: each per-leg charge is rounded half up to whole
    cents first, and only then are the leg charges summed. Summing raw
    unrounded amounts and rounding once at the end produces a different
    number and is not acceptable."

    Design: Difficulty/combinatorial_formula/quote_per_leg_rounding_pinned
    """
    # Round-per-leg: 154167 + 154167 + 25000 = 333334; surcharge 8% = 26667;
    # total 360001. Sum-then-round would give legs 333333 and total 360000.
    trip, _legs = setup_quoted_trip(
        legs=((37, "REVENUE", False), (37, "REVENUE", False), (10, "POSITIONING", False)),
        departure_at="2026-08-20T10:00:00Z", customer_name="Cust R")
    assert trip["quoted_total_cents"] == 360001, (
        f"per-leg rounding pinned; got {trip['quoted_total_cents']}")


def test_quote_deposit_round_half_up_on_quarter(api):
    """PRD §3.3: "The `deposit_required_cents` is one quarter of the quoted
    total, rounded half up."

    Design: Difficulty/combinatorial_formula/quote_per_leg_rounding_pinned
    """
    trip, _legs = setup_quoted_trip(
        legs=((37, "REVENUE", False), (37, "REVENUE", False), (10, "POSITIONING", False)),
        departure_at="2026-08-20T10:00:00Z", customer_name="Cust R")
    # round_half_up(360001 * 0.25) = round_half_up(90000.25) = 90000
    assert trip["deposit_required_cents"] == 90000, (
        f"quarter of 360001 rounds half up; got {trip['deposit_required_cents']}")


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / quote_discount_surcharge_order_pinned
# ---------------------------------------------------------------------------

def test_quote_discount_tier_applies_at_exactly_2000000(api):
    """PRD §3.3: "First the volume discount is taken from the legs total: a
    legs total of at least 5000000 cents earns a discount of ten percent of
    the legs total, rounded half up; a legs total below that but of at least
    2000000 cents earns five percent, rounded half up; below 2000000 cents
    there is no discount."

    Design: Difficulty/combinatorial_formula/quote_discount_surcharge_order_pinned
    """
    # Single 480min LIGHT_JET leg -> legs_total exactly 2000000 (>= tier 1).
    trip, _legs = setup_quoted_trip(legs=((480, "REVENUE", False),),
                                    departure_at="2026-08-15T10:00:00Z",
                                    customer_name="Cust D")
    # 2000000 - 100000 discount + surcharge; see companion test for the order.
    assert trip["quoted_total_cents"] == 2052000, (
        f"5% tier at exactly 2000000; got {trip['quoted_total_cents']}")
    assert trip["deposit_required_cents"] == 513000


def test_quote_surcharge_computed_on_discounted_amount(api):
    """PRD §3.3: "Next the fuel surcharge is computed as eight percent of the
    discounted amount — the legs total minus the volume discount — rounded
    half up; computing the surcharge on the pre-discount total is a
    different, wrong number."

    Design: Difficulty/combinatorial_formula/quote_discount_surcharge_order_pinned
    """
    # Surcharge on discounted 1900000 -> 152000; on pre-discount 2000000 it
    # would be 160000 (total 2060000, the pinned-wrong number).
    trip, _legs = setup_quoted_trip(legs=((480, "REVENUE", False),),
                                    departure_at="2026-08-15T10:00:00Z",
                                    customer_name="Cust D")
    assert trip["quoted_total_cents"] == 2000000 - 100000 + 152000
    assert trip["quoted_total_cents"] != 2060000, (
        "surcharge must be computed on the discounted amount")


# ---------------------------------------------------------------------------
# Queue B: calculations / quote_intl_and_fuel_stop_constants
# ---------------------------------------------------------------------------

def test_quote_applies_fuel_stop_and_international_fees(api):
    """PRD §3.3: "Quoting uses the published category rate card, not any
    aircraft's own hourly rate, because no tail has been assigned yet:
    `TURBOPROP` bills at 150000 cents per block hour, `LIGHT_JET` at 250000,
    `MIDSIZE_JET` at 400000, and `HEAVY_JET` at 650000."
    PRD §3.3: "A fuel-stop fee of 15000 cents is added for each leg whose
    `fuel_stop` is true, and a flat international fee of 250000 cents applies
    when the trip's `international` flag is true."

    Design: Corner/calculations/quote_intl_and_fuel_stop_constants
    """
    # MIDSIZE_JET 120min REV with fuel_stop, international:
    # legs 800000, surcharge 8% = 64000, stop fee 15000, intl fee 250000.
    trip, _legs = setup_quoted_trip(
        legs=((120, "REVENUE", True),), category="MIDSIZE_JET",
        destination_icao="MMCZ", departure_at="2026-08-12T10:00:00Z",
        passenger_count=2, international=True, customer_name="Cust MS")
    assert trip["quoted_total_cents"] == 1129000
    assert trip["deposit_required_cents"] == 282250
