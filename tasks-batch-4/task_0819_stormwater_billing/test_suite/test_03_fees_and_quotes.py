"""Tiered fee computation (marginal & flat variants), the ERU=5.0 flat-tier
edge, and the fee-quote endpoint."""
from test_helpers import (
    validate_success, TEST_USERS,
    create_active_parcel, grant_exemption,
)

ASSESSOR = TEST_USERS["assessor_headers"]
BILLING_CLERK = TEST_USERS["billing_clerk_headers"]


def test_tiered_fee_three_band_marginal_eru6(api):
    """PRD §3.5: "The first band covers ERU above 0 up to and including 1.0 and
    is priced at 4,000 cents per ERU; the second band covers ERU above 1.0 up to
    and including 5.0 and is priced at 3,500 cents per ERU; the third band covers
    all ERU above 5.0 and is priced at 3,000 cents per ERU."
    PRD §3.5: "Under the `MARGINAL` variant — the default — each band is charged
    at its own rate."

    Design: Difficulty/combinatorial_formula/tiered_fee_three_band_marginal_mode_a
    """
    base = create_active_parcel(api, measured_sqft=18000, land_use="INDUSTRIAL")
    quote = validate_success(api.get_fee_quote(base["parcel"]["id"], BILLING_CLERK))
    assert quote["billable_eru"] == 6.0
    assert quote["base_fee_marginal_cents"] == 21000
    assert quote["marginal_assessed_cents"] == 21500


def test_tiered_fee_three_band_marginal_eru7(api):
    """PRD §3.5: "the portion of ERU falling in the first band (the ERU capped at
    1.0), plus the portion in the second band (the ERU capped at 5.0 less 1.0,
    but never below 0), plus the portion in the third band (the ERU less 5.0, but
    never below 0), each multiplied by that band's rate, and the three products
    summed and then rounded once to whole cents."
    PRD §3.5: "The `assessed_fee_cents` is then the fixed charge plus the base
    fee minus the credit amount."

    Design: Difficulty/combinatorial_formula/tiered_fee_three_band_marginal_mode_a
    """
    # ERU 7.0 = 1.0*4000 + 4.0*3500 + 2.0*3000 = 24000; assessed = 500 + 24000.
    base = create_active_parcel(api, measured_sqft=21000, land_use="INDUSTRIAL")
    quote = validate_success(api.get_fee_quote(base["parcel"]["id"], BILLING_CLERK))
    assert quote["billable_eru"] == 7.0
    assert quote["base_fee_marginal_cents"] == 24000
    assert quote["marginal_assessed_cents"] == 24500


def test_flat_tier_upper_edge_at_eru_5_inclusive(api):
    """PRD §3.5: "Note the tier edge is decided by "at most," so an ERU of exactly
    5.0 is priced in the second tier at 3,500 cents per ERU; the flat figure is
    the ERU multiplied by that single rate and then rounded to whole cents."

    Design: Difficulty/boundary_precision_check/flat_tier_upper_edge_at_eru_5_inclusive
    """
    base = create_active_parcel(api, measured_sqft=15000, land_use="COMMERCIAL")
    quote = validate_success(api.get_fee_quote(base["parcel"]["id"], BILLING_CLERK))
    assert quote["billable_eru"] == 5.0
    assert quote["base_fee_flat_cents"] == 17500
    assert quote["base_fee_marginal_cents"] == 18000


def test_flat_tier_just_above_edge_uses_third_rate(api):
    """PRD §3.5: "Under the `FLAT` variant, the entire ERU is charged at the
    single rate of the tier the total ERU falls into: 4,000 cents per ERU when
    the ERU is at most 1.0, 3,500 cents per ERU when the ERU is at most 5.0, and
    3,000 cents per ERU when the ERU exceeds 5.0."

    Design: Difficulty/boundary_precision_check/flat_tier_upper_edge_at_eru_5_inclusive
    """
    # ERU 5.1 > 5.0 -> flat rate 3,000 cents/ERU: base_fee_flat = round(5.1*3000)=15300.
    base = create_active_parcel(api, measured_sqft=15300, land_use="COMMERCIAL")
    quote = validate_success(api.get_fee_quote(base["parcel"]["id"], BILLING_CLERK))
    assert quote["billable_eru"] == 5.1
    assert quote["base_fee_flat_cents"] == 15300


def test_zero_impervious_yields_zero_eru_fixed_charge_only(api):
    """PRD §3.5: "a flat per-bill administrative charge of 500 cents is written to
    `fixed_charge_cents`."
    PRD §3.5: "The `assessed_fee_cents` is then the fixed charge plus the base
    fee minus the credit amount."

    Design: Corner/calculations/zero_impervious_yields_zero_eru_fixed_charge_only
    """
    base = create_active_parcel(api, measured_sqft=0, land_use="UNDEVELOPED")
    quote = validate_success(api.get_fee_quote(base["parcel"]["id"], BILLING_CLERK))
    assert quote["billable_eru"] == 0.0
    assert quote["base_fee_marginal_cents"] == 0
    assert quote["marginal_assessed_cents"] == 500


def test_exemption_partial_reduces_marginal_fee(api):
    """PRD §3.3: "Granting sets the parcel's `exempt_pct` to the granted fraction,
    re-derives the parcel's `billable_eru` and `current_fee_cents` from the new
    exemption, and increments the parcel's `version` by one."
    PRD §3.2: "First the exemption is applied to area: the impervious area is
    multiplied by one minus the parcel's exempt fraction."

    Design: Corner/calculations/exemption_partial_reduces_marginal_fee
    """
    base = create_active_parcel(api, measured_sqft=18000, land_use="COMMERCIAL")
    grant_exemption(api, base["parcel"]["id"], requested_pct=0.25, granted_pct=0.25,
                    category="AGRICULTURAL")
    parcel = validate_success(api.get_parcel(base["parcel"]["id"], ASSESSOR))
    assert parcel["billable_eru"] == 4.5
    assert parcel["current_fee_cents"] == 16250
