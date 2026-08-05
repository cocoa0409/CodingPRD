"""Expected-amount reconciliation: provisional vs final variants, the combinatorial
tier/proration/platform-fee formula, immediate line recomputation, and utilization."""
from test_helpers import (
    validate_success,
    setup_service, setup_invoice_with_line, new_invoice, new_line_item, review,
    TEST_USERS,
)

_ANALYST = TEST_USERS["analyst_headers"]
_SOURCING = TEST_USERS["sourcing_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / invoice_line_expected_provisional_vs_final
# ---------------------------------------------------------------------------

def test_provisional_expected_uses_contracted_quantity_full_cycle(api):
    """PRD §3.4: "At line creation the provisional variant is used: the quantity is the
    service's contracted_quantity, the billed-days count is taken as a full cycle of 30 days,
    and the proration factor is therefore 1.0."
    PRD §3.4: "a quantity of at least 100 units earns a 15 percent discount, at least 50 earns
    10 percent, at least 10 earns 5 percent, and anything below 10 earns no discount"
    PRD §3.4: "if the service's service_type is SAAS_SUBSCRIPTION, add a flat platform fee of
    5,000 cents (50 dollars); telecom lines add no platform fee."

    Provisional: base 2000*60=120000, tier 0.10 (qty 60>=50), proration 1.0 -> 108000,
    + 5000 SAAS fee = 113000.

    Design: Difficulty/dual_variant_calc/invoice_line_expected_provisional_vs_final
    """
    scen = setup_service(api, service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60,
                                                 "active_quantity": 42})
    invoice = new_invoice(api, scen["contract"]["id"])
    line = new_line_item(api, invoice["id"], scen["service"]["id"],
                         billing_period_start="2026-06-01T00:00:00Z",
                         billing_period_end="2026-07-01T00:00:00Z",
                         billed_quantity=45, billed_amount_cents=100000)
    assert line["expected_amount_cents"] == 113000, \
        f"provisional expected should be 113000, got {line['expected_amount_cents']}"


def test_final_expected_uses_billed_quantity_at_review(api):
    """PRD §3.4: "At invoice review (below) the final variant is used: the quantity is the
    line's own billed_quantity, the billed-days count is the actual number of days in the
    line's half-open period (the end date minus the start date), and the proration factor is
    that day count divided by 30."
    PRD §3.4: "Review recomputes the final expected_amount_cents and the variance_cents for
    every line item — a line's variance_cents being its billed_amount_cents minus its final
    expected_amount_cents"

    Final: base 2000*45=90000, tier 0.05 (qty 45>=10), 30-day period proration 1.0 -> 85500,
    + 5000 SAAS fee = 90500. variance = 100000 - 90500 = 9500.

    Design: Difficulty/dual_variant_calc/invoice_line_expected_provisional_vs_final
    """
    scen = setup_invoice_with_line(
        api,
        service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60, "active_quantity": 42},
        line_overrides={"billing_period_start": "2026-06-01T00:00:00Z",
                        "billing_period_end": "2026-07-01T00:00:00Z",
                        "billed_quantity": 45, "billed_amount_cents": 100000},
        do_review=True,
    )
    line = validate_success(api.get_line_item(scen["line"]["id"], _ANALYST))
    assert line["expected_amount_cents"] == 90500, \
        f"final expected should be 90500, got {line['expected_amount_cents']}"
    assert line["variance_cents"] == 9500, f"variance should be 9500, got {line['variance_cents']}"


# ---------------------------------------------------------------------------
# combinatorial_formula / invoice_expected_tier_proration_fee_mode_a
# ---------------------------------------------------------------------------

def test_final_expected_combines_tier_proration_and_platform_fee(api):
    """PRD §3.4: "Multiply the base by one minus the discount fraction, then by the proration
    factor, and round that result half up to whole cents. Finally, if the service's
    service_type is SAAS_SUBSCRIPTION, add a flat platform fee of 5,000 cents (50 dollars)"
    PRD §3.4: "The rounding is applied once, to the discounted and prorated base, before the
    integer platform fee is added."

    billed_quantity 45 over a 15-day half-open period: base 90000, tier 0.05, proration 0.5
    -> round_half_up(90000*0.95*0.5)=42750, + 5000 fee = 47750.

    Design: Difficulty/combinatorial_formula/invoice_expected_tier_proration_fee_mode_a
    """
    scen = setup_invoice_with_line(
        api,
        service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60, "active_quantity": 42},
        line_overrides={"billing_period_start": "2026-06-01T00:00:00Z",
                        "billing_period_end": "2026-06-16T00:00:00Z",
                        "billed_quantity": 45, "billed_amount_cents": 50000},
        do_review=True,
    )
    line = validate_success(api.get_line_item(scen["line"]["id"], _ANALYST))
    assert line["expected_amount_cents"] == 47750, \
        f"expected 47750 (tier 0.05 * proration 0.5 + fee 5000), got {line['expected_amount_cents']}"


def test_final_variance_reflects_prorated_expected(api):
    """PRD §3.4: "Review recomputes the final expected_amount_cents and the variance_cents for
    every line item — a line's variance_cents being its billed_amount_cents minus its final
    expected_amount_cents"

    billed 50000 - final expected 47750 = variance 2250.

    Design: Difficulty/combinatorial_formula/invoice_expected_tier_proration_fee_mode_a
    """
    scen = setup_invoice_with_line(
        api,
        service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60, "active_quantity": 42},
        line_overrides={"billing_period_start": "2026-06-01T00:00:00Z",
                        "billing_period_end": "2026-06-16T00:00:00Z",
                        "billed_quantity": 45, "billed_amount_cents": 50000},
        do_review=True,
    )
    line = validate_success(api.get_line_item(scen["line"]["id"], _ANALYST))
    assert line["variance_cents"] == 2250, f"variance should be 2250, got {line['variance_cents']}"


# ---------------------------------------------------------------------------
# Corner: consistency_model / line_item_creation_recomputes_invoice_billed_immediately
# ---------------------------------------------------------------------------

def test_line_item_creation_recomputes_invoice_billed_immediately(api):
    """PRD §3.4: "the invoice's billed_amount_cents and net_amount_cents are then refreshed to
    reflect the new line."

    Design: Corner/consistency_model/line_item_creation_recomputes_invoice_billed_immediately
    """
    scen = setup_service(api)
    invoice = new_invoice(api, scen["contract"]["id"])
    new_line_item(api, invoice["id"], scen["service"]["id"],
                  billing_period_start="2026-06-01T00:00:00Z",
                  billing_period_end="2026-07-01T00:00:00Z",
                  billed_quantity=20, billed_amount_cents=40000)
    fetched = validate_success(api.get_invoice(invoice["id"], _ANALYST))
    assert fetched["billed_amount_cents"] == 40000, \
        f"invoice billed_amount_cents should be 40000, got {fetched['billed_amount_cents']}"


# ---------------------------------------------------------------------------
# Corner: entities / service_utilization_computed_on_create
# ---------------------------------------------------------------------------

def test_service_utilization_computed_on_create(api):
    """PRD §3.2: "Every service tracks a utilization figure, utilization_pct, computed as the
    active quantity divided by the contracted quantity, expressed as a percentage and rounded
    half up to two decimal places"
    PRD §3.2: "Utilization is computed when the service is created and is re-evaluated whenever
    the service is considered for a rightsizing recommendation."

    active 30 / contracted 60 -> 50.00.

    Design: Corner/entities/service_utilization_computed_on_create
    """
    scen = setup_service(api, service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60,
                                                 "active_quantity": 30})
    assert scen["service"]["utilization_pct"] == 50.00, \
        f"utilization_pct should be 50.00, got {scen['service']['utilization_pct']}"
