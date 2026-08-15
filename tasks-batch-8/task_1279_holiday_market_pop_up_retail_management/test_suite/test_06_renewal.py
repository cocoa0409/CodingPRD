"""Vendor renewal score composition and renewal-offer discount bands."""
import pytest

from test_helpers import (
    TEST_USERS, validate_success,
    setup_open_market, setup_reconciled_settlement,
    create_booth_entity, create_load_slot_for, create_renewal_offer_for,
    create_settlement, submit_settlement, reconcile_settlement,
    set_clock, get_vendor, get_load_slot, run_ops,
)

OPERATOR = TEST_USERS["market_operator_headers"]


def test_renewal_offer_discount_at_score_80_band(api):
    """PRD §3.10: "At creation, the system computes `discount_pct` from the
    vendor's `renewal_score` band: a score of 80 or above yields 20 percent; 60
    to 79 yields 15 percent; 40 to 59 yields 10 percent; 20 to 39 yields 5
    percent; below 20 yields 0 percent."
    PRD §3.10: "The sales component is the lesser of 50 and the vendor's
    `lifetime_gross_sales_cents` divided by 200000 (so $100,000 in lifetime gross
    sales yields the full 50 points)."

    Design: Corner/calculations/renewal_discount_threshold_bands
    """
    # Jury 100/100/100 -> jury component 20; no strikes -> reliability 30;
    # gross card 6,000,000 -> sales min(50, 30) = 30. Score = 80.00 exactly.
    ctx = setup_reconciled_settlement(
        market_overrides={"name": "CM5", "season_code": "CM5-1",
                          "closes_at": "2026-12-20T23:59:59Z"},
        scores=(100, 100, 100),
        business_date="2026-12-05", gross_card_cents=6_000_000, gross_cash_cents=0)
    vendor = get_vendor(ctx["vendor"]["id"])
    assert vendor["renewal_score"] == pytest.approx(80.00, abs=0.01)

    # Close the season, then extend the offer against a still-available booth.
    set_clock("2026-12-21T00:00:00Z")
    run_ops(ctx["market"]["id"])
    spare_booth = create_booth_entity(ctx["market"]["id"], booth_code="CH-5B",
                                      booth_type="CHALET", zone="SOUTH",
                                      square_feet=100)
    offer = create_renewal_offer_for(ctx["market"]["id"], ctx["vendor"]["id"],
                                     ctx["assignment"]["id"], spare_booth["id"])
    assert offer["status"] == "EXTENDED"
    assert offer["discount_pct"] == 20, "renewal_score >= 80 must yield 20 percent"


def test_renewal_score_composition_sales_reliability_jury(api):
    """PRD §3.10: "The sales component is the lesser of 50 and the vendor's
    `lifetime_gross_sales_cents` divided by 200000 (so $100,000 in lifetime gross
    sales yields the full 50 points). The reliability component is the greater of
    0 and 30 minus 10 times the vendor's `no_show_strikes`. The jury component is
    the vendor's most recent `jury_average` divided by 100 and multiplied by 20,
    or 0 if no jury average exists."
    PRD §3.6: "On submission, the vendor's `lifetime_gross_sales_cents`
    increases by `gross_card_cents` plus `gross_cash_cents` minus
    `refund_cents`."

    Design: Difficulty/combinatorial_formula/renewal_score_circular_dependency
    """
    ctx = setup_open_market(scores=(70, 70, 70))
    market_id, vendor_id, asg_id = (ctx["market"]["id"], ctx["vendor"]["id"],
                                    ctx["assignment"]["id"])

    # Sales: submit one settlement of 300000 card + 200000 cash.
    st = create_settlement(market_id, vendor_id, asg_id, "2026-12-05",
                           gross_card_cents=300000, gross_cash_cents=200000)
    submit_settlement(market_id, st["id"], vendor_id)

    # Reliability: one RESERVED load slot left to lapse into NO_SHOW via run_ops.
    slot = create_load_slot_for(market_id, asg_id, direction="LOAD_IN",
                                starts_at="2026-11-30T08:00:00Z",
                                ends_at="2026-11-30T10:00:00Z")
    run_ops(market_id)
    assert get_load_slot(market_id, slot["id"])["status"] == "NO_SHOW"

    vendor = get_vendor(vendor_id)
    assert vendor["lifetime_gross_sales_cents"] == 500000
    assert vendor["no_show_strikes"] == 1
    # sales = min(50, 500000/200000) = 2.50; reliability = max(0, 30-10) = 20;
    # jury = 70/100*20 = 14.00. Total = 36.50.
    assert vendor["renewal_score"] == pytest.approx(36.50, abs=0.01)


def test_renewal_score_recomputed_on_reconcile_with_sales_and_jury(api):
    """PRD §3.10: "The vendor's `renewal_score` is a composite value between 0
    and 100, recomputed whenever a settlement is reconciled, a load slot goes
    `NO_SHOW`, or an assignment is forfeited with reason `NO_SHOW`."
    PRD §3.10: "The final `renewal_score` is rounded half-up to two decimal
    places."

    Design: Difficulty/combinatorial_formula/renewal_score_circular_dependency
    """
    ctx = setup_open_market(scores=(70, 70, 70))
    market_id, vendor_id, asg_id = (ctx["market"]["id"], ctx["vendor"]["id"],
                                    ctx["assignment"]["id"])

    st = create_settlement(market_id, vendor_id, asg_id, "2026-12-05",
                           gross_card_cents=300000, gross_cash_cents=200000)
    st = submit_settlement(market_id, st["id"], vendor_id)
    mid = get_vendor(vendor_id)
    assert mid["lifetime_gross_sales_cents"] == 500000

    reconcile_settlement(market_id, st["id"])
    after = get_vendor(vendor_id)
    # sales = 2.50; reliability = 30 (no strikes); jury = 14.00 -> 46.50.
    assert after["renewal_score"] == pytest.approx(46.50, abs=0.01)
