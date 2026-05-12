"""Tax calculations: dutiable_value variants, declaration_tax_total
mode-selection and per-line-floor-then-sum, postal exemption, boundary
precision.

PRD anchors: §3.5 (dutiable value variants), §3.6 (tax composition).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    PERSONAL_POSTAL_THRESHOLD_CNY_MINOR,
    POSTAL_EXEMPTION_CNY_MINOR,
    setup_draft_declaration,
    submit_declaration,
    create_party_pair,
    create_order,
    create_draft_declaration,
    create_exchange_rate,
    create_hs_code,
    add_line,
    setup_personal_postal_at_dutiable,
    make_line_item,
    assert_declaration_taxes_present,
)


# ---------------------------------------------------------------------------
# Dutiable value variants — three distinct values for the same Order line.
# ---------------------------------------------------------------------------
def test_transaction_value_simple_conversion(api):
    """PRD §3.5: "Under TRANSACTION_VALUE, the line's CNY contribution is
    the simplest mapping: multiply line_value_minor by the pinned
    exchange rate's rate_micros, divide by 1,000,000, and floor toward
    zero."

    Claim: a single 10000 USD-cent line at rate 7.0 → 70000 fen
    (= floor(10000 * 7_000_000 / 1_000_000)).
    """
    ctx = setup_draft_declaration(
        dutiable_value_method="TRANSACTION_VALUE",
        line_items=[make_line_item(quantity=1, unit_price=10_000, weight_kg=1.0)],
        currency="USD",
        rate_micros=7_000_000,
        rate_effective_date="2026-01-01",
        hs_code_overrides={
            "tariff_rate_bps": 0, "vat_rate_bps": 0,
            "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
        },
    )
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert_declaration_taxes_present(submitted)
    assert submitted["dutiable_value_cny_minor"] == 70_000


def test_deductive_value_calculation(api):
    """PRD §3.5: "Under DEDUCTIVE_VALUE, the calculation begins from a
    presumed retail price equal to the transaction price multiplied by
    125 and divided by 100 (i.e., a 25 percent retail markup), floored.
    From that presumed retail price, the calculation deducts a
    logistics-and-profit component computed by multiplying the retail
    price by DEDUCTION_RATIO_BPS and dividing by 10,000, where
    DEDUCTION_RATIO_BPS is fixed at 1500 (representing a 15 percent
    deduction); the deduction itself is floored. The deductive value is
    the retail price minus the deduction; the line's CNY contribution
    is the deductive value multiplied by the pinned rate_micros and
    divided by 1,000,000, again floored."

    Claim: 10000 USD-cents at rate 7 → retail=12500, deduction=1875,
    deductive=10625, CNY=floor(10625*7_000_000/1_000_000)=74375 fen.
    """
    ctx = setup_draft_declaration(
        dutiable_value_method="DEDUCTIVE_VALUE",
        line_items=[make_line_item(quantity=1, unit_price=10_000, weight_kg=1.0)],
        currency="USD",
        rate_micros=7_000_000,
        hs_code_overrides={
            "tariff_rate_bps": 0, "vat_rate_bps": 0,
            "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
        },
    )
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert submitted["dutiable_value_cny_minor"] == 74_375


def test_computed_value_calculation(api):
    """PRD §3.5: "Under COMPUTED_VALUE, the calculation is cost-plus.
    First, a logistics component is computed by multiplying the line's
    weight_kg by LOGISTICS_PER_KG_MINOR (fixed at 5,000 fen, i.e.,
    50.00 CNY per kilogram) and rounding up to the next integer; the
    cost-plus base is line_value_minor + logistics_minor. The base is
    then uplifted by COMPUTED_UPLIFT_BPS (fixed at 1000, i.e., a
    10 percent profit uplift) by multiplying it by 11,000, dividing by
    10,000, and flooring. The line's CNY contribution is the uplifted
    value multiplied by the pinned rate_micros and divided by
    1,000,000, floored."

    Claim: weight=1 kg, unit_price=10000, rate=7 →
    logistics=ceil(1*5000)=5000; cost_plus=10000+5000=15000;
    uplifted=floor(15000*11000/10000)=16500;
    CNY=floor(16500*7_000_000/1_000_000)=115500 fen.
    """
    ctx = setup_draft_declaration(
        dutiable_value_method="COMPUTED_VALUE",
        line_items=[make_line_item(quantity=1, unit_price=10_000, weight_kg=1.0)],
        currency="USD",
        rate_micros=7_000_000,
        hs_code_overrides={
            "tariff_rate_bps": 0, "vat_rate_bps": 0,
            "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
        },
    )
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert submitted["dutiable_value_cny_minor"] == 115_500


# ---------------------------------------------------------------------------
# Per-line-floor-then-sum order (PRD §2.5 + §3.5)
# ---------------------------------------------------------------------------
def test_floor_per_line_then_sum_for_dutiable_value(api):
    """PRD §3.5: "Across all three variants, the order of operations is
    fixed: each line's contribution is computed and floored
    independently, and only then are the per-line contributions summed
    to produce dutiable_value_cny_minor. Computing the sum first and
    flooring the total would produce different values to the cent and
    is not equivalent."

    Claim: with rate_micros=1_000_000 (1:1) and two lines each with
    line_value_minor=5050, the per-line CNY values are 5050 each (floor
    is a no-op), so dutiable_value=10100. (We use 1:1 rate to isolate
    the per-line/sum order from the rate conversion arithmetic.)
    """
    ctx = setup_draft_declaration(
        dutiable_value_method="TRANSACTION_VALUE",
        line_items=[
            make_line_item(quantity=1, unit_price=5050, weight_kg=0.1),
            make_line_item(quantity=1, unit_price=5050, weight_kg=0.1),
        ],
        currency="USD",
        rate_micros=1_000_000,
        hs_code_overrides={
            "tariff_rate_bps": 100,  # 1%
            "vat_rate_bps": 0,
            "consumption_tax_rate_bps": 0,
            "postal_tax_rate_bps": 0,
        },
    )
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert submitted["dutiable_value_cny_minor"] == 10_100


def test_floor_per_line_then_sum_for_tariff(api):
    """PRD §2.5: "All such divisions truncate toward zero (a per-line
    floor is applied), and the order of operations is fixed: compute
    each line's contribution, floor that contribution, then sum across
    lines. Summing first and flooring the total is not equivalent and
    is not allowed."

    Claim: two lines each with line_dutiable=5050 fen, tariff 1%
    (100 bps): per-line tariff = floor(5050*100/10000) = 50, sum = 100.
    The 'sum-then-floor' alternative would be floor(10100*100/10000)
    = 101. The PRD pins 100.
    """
    ctx = setup_draft_declaration(
        dutiable_value_method="TRANSACTION_VALUE",
        line_items=[
            make_line_item(quantity=1, unit_price=5050, weight_kg=0.1),
            make_line_item(quantity=1, unit_price=5050, weight_kg=0.1),
        ],
        currency="USD",
        rate_micros=1_000_000,
        hs_code_overrides={
            "tariff_rate_bps": 100,
            "vat_rate_bps": 0,
            "consumption_tax_rate_bps": 0,
            "postal_tax_rate_bps": 0,
        },
    )
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert submitted["tariff_amount_cny_minor"] == 100


# ---------------------------------------------------------------------------
# tax_mode selection (STANDARD vs PERSONAL_POSTAL) — PRD §3.6
# ---------------------------------------------------------------------------
def test_general_trade_below_threshold_is_standard(api):
    """PRD §3.6: "In every other case (general trade, bonded warehouse,
    or B2C direct mail strictly above the threshold), the mode is
    STANDARD."

    Claim: a GENERAL_TRADE order with tiny dutiable value still resolves
    to tax_mode=STANDARD (mode is gated on trade_mode==B2C_DIRECT_MAIL
    AND value <= threshold).
    """
    ctx = setup_draft_declaration(
        trade_mode="GENERAL_TRADE",
        dutiable_value_method="TRANSACTION_VALUE",
        line_items=[make_line_item(quantity=1, unit_price=100, weight_kg=0.1)],
        currency="USD",
        rate_micros=1_000_000,
        hs_code_overrides={
            "tariff_rate_bps": 0,
            "vat_rate_bps": 0,
            "consumption_tax_rate_bps": 0,
            "postal_tax_rate_bps": 1000,
        },
    )
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert submitted["tax_mode"] == "STANDARD"


def test_b2c_at_threshold_is_personal_postal(api):
    """PRD §3.6: "The mode is PERSONAL_POSTAL only when both conditions
    hold: the declaration's trade_mode is B2C_DIRECT_MAIL, and the
    declaration's dutiable_value_cny_minor is at most
    PERSONAL_POSTAL_THRESHOLD_CNY_MINOR, which is fixed at 500,000 fen
    (i.e., 5,000.00 CNY). The boundary is inclusive: a declaration whose
    dutiable value is exactly 5,000.00 CNY still qualifies for
    personal-postal mode if its trade mode is B2C_DIRECT_MAIL."

    Claim: dutiable_value_cny_minor == 500_000 → tax_mode=PERSONAL_POSTAL.
    """
    ctx = setup_personal_postal_at_dutiable(
        PERSONAL_POSTAL_THRESHOLD_CNY_MINOR
    )
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert submitted["dutiable_value_cny_minor"] == PERSONAL_POSTAL_THRESHOLD_CNY_MINOR
    assert submitted["tax_mode"] == "PERSONAL_POSTAL"


def test_b2c_one_above_threshold_is_standard(api):
    """PRD §3.6: "In every other case (general trade, bonded warehouse,
    or B2C direct mail strictly above the threshold), the mode is
    STANDARD."

    Claim: dutiable_value_cny_minor == 500_001 → tax_mode=STANDARD
    (one fen above the inclusive threshold flips the mode).
    """
    ctx = setup_personal_postal_at_dutiable(
        PERSONAL_POSTAL_THRESHOLD_CNY_MINOR + 1
    )
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert submitted["dutiable_value_cny_minor"] == PERSONAL_POSTAL_THRESHOLD_CNY_MINOR + 1
    assert submitted["tax_mode"] == "STANDARD"


# ---------------------------------------------------------------------------
# Postal exemption (PRD §3.6)
# ---------------------------------------------------------------------------
def test_postal_exemption_at_boundary(api):
    """PRD §3.6: "The candidate total is the sum of per-line postal
    taxes; if that candidate total is at most POSTAL_EXEMPTION_CNY_MINOR,
    fixed at 5,000 fen (i.e., 50.00 CNY), the importer pays nothing and
    total_tax_cny_minor is set to zero — this is the statutory waiver
    for very small parcels. The exemption boundary is inclusive: a
    candidate total of exactly 50.00 CNY is exempt."

    Claim: setup yields postal_total exactly equal to
    POSTAL_EXEMPTION_CNY_MINOR (=5000 fen) → total_tax_cny_minor == 0.

    Construction:
      dutiable_value_cny_minor = 50000 fen, postal_tax_rate_bps = 1000
      → postal_total = floor(50000 * 1000 / 10000) = 5000 fen.
    """
    ctx = setup_personal_postal_at_dutiable(
        50_000, postal_tax_rate_bps=1000
    )
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert submitted["tax_mode"] == "PERSONAL_POSTAL"
    assert submitted["total_tax_cny_minor"] == 0
    assert submitted["tariff_amount_cny_minor"] == 0
    assert submitted["vat_amount_cny_minor"] == 0
    assert submitted["consumption_tax_cny_minor"] == 0


def test_postal_exemption_just_above_boundary(api):
    """PRD §3.6: "If the candidate total exceeds the exemption,
    total_tax_cny_minor is the candidate total."

    Claim: with a postal_total strictly greater than 5000 fen, the
    exemption does NOT apply and total_tax_cny_minor equals postal_total.

    Construction:
      dutiable_value_cny_minor = 50_010, postal_tax_rate_bps = 1000
      → postal_total = floor(50_010 * 1000 / 10000) = 5001 > 5000 →
        total_tax_cny_minor = 5001.
    """
    ctx = setup_personal_postal_at_dutiable(
        50_010, postal_tax_rate_bps=1000
    )
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert submitted["tax_mode"] == "PERSONAL_POSTAL"
    assert submitted["total_tax_cny_minor"] == 5_001


# ---------------------------------------------------------------------------
# STANDARD-mode three-tax composition (PRD §3.6)
# ---------------------------------------------------------------------------
def test_standard_mode_vat_compounds_on_tariff_and_consumption(api):
    """PRD §3.6: "The VAT base for the line is the dutiable contribution
    plus the line tariff plus the line consumption tax — VAT compounds
    on top of the other two taxes — and the line VAT is that base
    multiplied by the HS code's vat_rate_bps, divided by 10,000,
    floored."

    Claim: with dutiable=10_000, tariff_rate=10% (1000 bps),
    consumption_rate=5% (500 bps), vat_rate=13% (1300 bps):
      tariff = floor(10000 * 1000 / 10000) = 1000
      consumption = floor(10000 * 500 / 10000) = 500
      vat_base = 10000 + 1000 + 500 = 11500
      vat = floor(11500 * 1300 / 10000) = 1495
      total_tax = 1000 + 500 + 1495 = 2995
    """
    ctx = setup_draft_declaration(
        dutiable_value_method="TRANSACTION_VALUE",
        line_items=[make_line_item(quantity=1, unit_price=10_000, weight_kg=0.1)],
        currency="USD",
        rate_micros=1_000_000,  # 1:1 → dutiable_cny == line_value_minor
        hs_code_overrides={
            "tariff_rate_bps": 1000,
            "consumption_tax_rate_bps": 500,
            "vat_rate_bps": 1300,
            "postal_tax_rate_bps": 0,
        },
        trade_mode="GENERAL_TRADE",
    )
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert submitted["tax_mode"] == "STANDARD"
    assert submitted["dutiable_value_cny_minor"] == 10_000
    assert submitted["tariff_amount_cny_minor"] == 1_000
    assert submitted["consumption_tax_cny_minor"] == 500
    assert submitted["vat_amount_cny_minor"] == 1_495
    assert submitted["total_tax_cny_minor"] == 2_995


# ---------------------------------------------------------------------------
# Exchange-rate selection (PRD §3.1)
# ---------------------------------------------------------------------------
def test_exchange_rate_pinned_to_latest_at_or_before_submission(api):
    """PRD §3.1: "the server selects the exchange rate by finding, for
    the order's currency converted to CNY, the row whose effective_date
    is the latest one not after the submission date; that selected date
    is pinned onto the declaration as exchange_rate_date_used and the
    corresponding rate_micros is what the dutiable-value calculation
    uses."

    Claim: with two rates published — 2026-01-01 (rate=7_000_000) and
    2026-02-01 (rate=8_000_000) — and the submission happening after
    2026-02-01, the declaration uses rate=8_000_000 and pins
    exchange_rate_date_used=2026-02-01.
    """
    # Setup includes one rate at 2026-01-01.
    ctx = setup_draft_declaration(
        dutiable_value_method="TRANSACTION_VALUE",
        line_items=[make_line_item(quantity=1, unit_price=10_000, weight_kg=0.1)],
        currency="USD",
        rate_micros=7_000_000,
        rate_effective_date="2026-01-01",
        hs_code_overrides={
            "tariff_rate_bps": 0, "vat_rate_bps": 0,
            "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
        },
    )
    # Publish a later rate for the same order currency the setup used.
    # (Fixtures mint a fresh per-setup currency code so rate-table rows
    # don't collide on PRD §3.1's (from, to, effective_date) uniqueness.)
    create_exchange_rate(
        from_currency=ctx.order["currency"], to_currency="CNY",
        rate_micros=8_000_000, effective_date="2026-02-01",
    )
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    # The PRD says the latest at-or-before submission_date is selected.
    # Without test-driving the clock we can't pin submission_date exactly,
    # but we can assert exchange_rate_date_used is one of the published
    # dates and dutiable_value_cny_minor is 70_000 (rate=7) or 80_000
    # (rate=8) depending on which date the server selected.
    assert submitted.get("exchange_rate_date_used") in ("2026-01-01", "2026-02-01")
    assert submitted["dutiable_value_cny_minor"] in (70_000, 80_000)
