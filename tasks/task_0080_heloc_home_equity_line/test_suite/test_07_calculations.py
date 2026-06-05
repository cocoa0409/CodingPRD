"""Corner coverage: early-closure tier pricing, annual-fee anniversary aggregation,
APR ceiling cap, and index-supersede APR recompute cascade (Queue B: calculations)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_active_line,
    advance_clock,
    ApiErrorId,
    TEST_USERS,
)

OFFICER = TEST_USERS["loan_officer_headers"]
SERVICER = TEST_USERS["loan_servicer_headers"]


def test_early_closure_fee_tier2_mid_draw_period(api):
    """PRD §3.11: "the years remaining is the number of days between the clock and the
    origination_date plus draw_period_years, divided by 365 and rounded up to a whole
    number. The tier rate, expressed in basis points of the credit_limit_cents, is ...
    100 bps when between 4 and 7 years inclusive remain ..."
    PRD §3.11: "The fee is the credit_limit_cents multiplied by the tier rate in basis
    points, divided by 10000, rounded half up."

    Close at 2032-06-01 (years_remaining 4, tier2 100bps) on credit_limit 50000000 ->
    EARLY_CLOSURE fee 500000.

    Design: Corner/calculations/early_closure_fee_tier2_mid_draw_period
    """
    ctx = setup_active_line(
        clock="2032-06-01T00:00:00Z",
        index_effective="2026-01-01T00:00:00Z",
        heloc_overrides={"credit_limit_cents": 50000000, "draw_period_years": 10},
    )
    hl_id = ctx["heloc"]["id"]
    # Close is blocked by the just-assessed OUTSTANDING fee; the fee record is what we assert.
    validate_error(api.close_heloc(hl_id, SERVICER), ApiErrorId.ERR_FEES_OUTSTANDING)
    fees, _ = validate_paginated(
        api.list_fee_assessments(hl_id, SERVICER, params={"fee_type": "EARLY_CLOSURE"})
    )
    assert fees[0]["amount_cents"] == 500000, (
        f"years_remaining 4 -> 100bps of 50000000 = 500000, got {fees[0]['amount_cents']}"
    )


def test_annual_fee_assessed_once_per_anniversary(api):
    """PRD §3.7: "For each anniversary index after the line's current anniversary_count
    up to and including the newly elapsed count, and only while that index does not
    exceed the draw_period_years, a fee assessment of type ANNUAL is created in
    OUTSTANDING status with amount_cents equal to the line's annual_fee_cents. The line's
    anniversary_count is then set to the lesser of the elapsed-anniversary count and the
    draw_period_years."

    Advancing from origination to 2028-01-01 (2 anniversaries) creates 2 ANNUAL fees and
    sets anniversary_count 2.

    Design: Corner/calculations/annual_fee_assessed_once_per_anniversary
    """
    ctx = setup_active_line(heloc_overrides={"annual_fee_cents": 5000})
    hl_id = ctx["heloc"]["id"]
    updated = advance_clock(hl_id, "2028-01-01T00:00:00Z")
    assert updated["anniversary_count"] == 2
    fees, meta = validate_paginated(
        api.list_fee_assessments(hl_id, SERVICER, params={"fee_type": "ANNUAL"})
    )
    assert meta["total_count"] == 2, f"expected 2 ANNUAL fees, got {meta['total_count']}"
    for f in fees:
        assert f["amount_cents"] == 5000


def test_apr_capped_at_rate_ceiling_on_activation(api):
    """PRD §3.3: "When activation succeeds, the line's current_apr_bps is set to the
    lesser of the active PRIME rate_bps plus the line's margin_bps, and the line's
    rate_ceiling_bps ..."

    PRIME 850 + margin 1500 = 2350 but rate_ceiling 1800 -> current_apr_bps min(2350,1800)
    = 1800.

    Design: Corner/calculations/apr_capped_at_rate_ceiling
    """
    ctx = setup_active_line(
        heloc_overrides={"margin_bps": 1500, "rate_ceiling_bps": 1800},
    )
    assert ctx["heloc"]["current_apr_bps"] == 1800, (
        f"expected min(850+1500, 1800) = 1800, got {ctx['heloc']['current_apr_bps']}"
    )


def test_index_supersede_recomputes_apr_on_active_line(api):
    """PRD §3.2: "the servicer publishes a fresh rate_bps and effective_date against the
    prior row, which creates a new PRIME IndexRate, sets the prior row's superseded to
    true, and recomputes the effective rate on every line currently in DRAW, FROZEN, or
    REPAYMENT — an index-reset cascade across all active lines."
    PRD §3.5: "the effective annual rate, current_apr_bps, is the lesser of the active
    PRIME rate_bps plus the line's margin_bps, and the line's rate_ceiling_bps."

    Superseding PRIME 850->900 (OCC version match) recomputes a DRAW line's APR from
    1000 (850+150) to 1050 (900+150).

    Design: Corner/calculations/index_supersede_cascades_apr_recompute
    """
    ctx = setup_active_line(heloc_overrides={"margin_bps": 150, "rate_ceiling_bps": 1800})
    hl_id = ctx["heloc"]["id"]
    idx = ctx["index"]
    assert ctx["heloc"]["current_apr_bps"] == 1000
    validate_success(
        api.supersede_index_rate(
            idx["id"],
            {
                "rate_bps": 900,
                "effective_date": "2026-02-01T00:00:00Z",
                "expected_indexrate_version": idx["version"],
            },
            SERVICER,
        ),
        201,
    )
    heloc = validate_success(api.get_heloc(hl_id, SERVICER))
    assert heloc["current_apr_bps"] == 1050, (
        f"expected 900+150 = 1050 after index reset, got {heloc['current_apr_bps']}"
    )
