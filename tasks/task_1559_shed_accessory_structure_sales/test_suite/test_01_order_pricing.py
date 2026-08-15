"""Order pricing: tiered structure pricing, fee lines, tax, and the CASH/RTO variants
(PRD §3.2)."""
import pytest
from test_helpers import (
    validate_success,
    setup_book, create_draft_order, submit_site_check, file_report,
    create_order_payload, api_client,
    QUOTED_10X12_WINDOW_CASH, QUOTED_10X12_WINDOW_RTO, QUOTED_8X8_CASH,
    QUOTED_8X8_WINDOW, QUOTED_10X12_REMOVAL_TRADEIN, QUOTED_10X12_WINDOW_PREP_30000,
    QUOTED_16X24_OSB_PIERS, STRUCTURE_PRICE_10X12, STRUCTURE_PRICE_16X24,
)
from test_helpers import TEST_USERS

SALES = TEST_USERS["sales_rep_headers"]


class TestCashVsRtoDivergence:
    def test_cash_variant_total(self, api):
        """PRD §3.2: "For a `CASH` purchase, the total is the subtotal plus the tax."
        PRD §3.2: "The estimate produced at creation and at each amendment is stored as
        `quoted_total_cents`; the identical formula is recomputed at completion and stored
        as `final_total_cents`."

        Design: Difficulty/dual_variant_calc/order_total_cash_vs_rto_divergence
        """
        jur, model, cust = setup_book()
        order = create_draft_order(cust["id"], model["id"], jur["id"], options=["WINDOW"])
        assert order["area_sqft"] == 120
        assert order["structure_price_cents"] == STRUCTURE_PRICE_10X12
        assert order["quoted_total_cents"] == QUOTED_10X12_WINDOW_CASH, (
            f"CASH total should be subtotal+tax 601490, got {order['quoted_total_cents']}"
        )

    def test_rto_variant_total_diverges(self, api):
        """PRD §3.2: "For an `RTO` purchase, the subtotal is first multiplied by 1.6 and
        rounded half-up to whole cents, and the tax is added afterward — identical
        configurations therefore quote higher under rent-to-own than under cash."

        Design: Difficulty/dual_variant_calc/order_total_cash_vs_rto_divergence
        """
        jur, model, cust = setup_book()
        cash = create_draft_order(cust["id"], model["id"], jur["id"], options=["WINDOW"])
        rto = create_draft_order(
            cust["id"], model["id"], jur["id"],
            options=["WINDOW"], purchase_type="RTO", rto_term_months=24,
        )
        assert rto["area_sqft"] == 120
        assert rto["structure_price_cents"] == STRUCTURE_PRICE_10X12
        assert rto["quoted_total_cents"] == QUOTED_10X12_WINDOW_RTO
        assert (
            rto["quoted_total_cents"] - cash["quoted_total_cents"]
        ) == QUOTED_10X12_WINDOW_RTO - QUOTED_10X12_WINDOW_CASH == 343800
        assert rto["quoted_total_cents"] > cash["quoted_total_cents"]


class TestTieredAndConditionalBranches:
    def test_tiered_overage_and_gravel_prebuilt(self, api):
        """PRD §3.2: "the overage is the amount by which the configured area exceeds the
        base area, never less than zero; the first forty square feet of overage price at
        the tier-one rate, and any remainder prices at the tier-two rate."
        PRD §3.2: "Delivery adds a flat $250.00 for `PRE_BUILT` or $450.00 for
        `ON_SITE_BUILD`."

        Design: Difficulty/combinatorial_formula/order_pricing_tiered_and_conditional_branches
        """
        jur, model, cust = setup_book()
        order = create_draft_order(cust["id"], model["id"], jur["id"], options=["WINDOW"])
        # 120 sqft: base 64, overage 56 -> 40*1500 + 16*2000 over base 300000
        assert order["structure_price_cents"] == 392000
        assert order["quoted_total_cents"] == 601490

    def test_piers_and_onsite_branches(self, api):
        """PRD §3.2: "`PIERS` are counted by dividing the width in feet by four and
        rounding up, dividing the depth in feet by four and rounding up, multiplying the
        two counts, and charging $120.00 per pier; `NONE` costs nothing."
        PRD §3.2: "Anchoring with `AUGER_STRAP` requires four anchors plus two additional
        anchors for every full hundred square feet of footprint, at $75.00 per anchor"

        Design: Difficulty/combinatorial_formula/order_pricing_tiered_and_conditional_branches
        """
        jur, model, cust = setup_book()
        order = create_draft_order(
            cust["id"], model["id"], jur["id"],
            width_ft=16, depth_ft=24, delivery_mode="ON_SITE_BUILD",
            foundation_type="PIERS",
        )
        assert order["area_sqft"] == 384
        # tier2 branch: 300000 + 40*1500 + 280*2000
        assert order["structure_price_cents"] == 920000
        # piers ceil(16/4)*ceil(24/4)=24 * 12000; delivery 45000; anchor (4+2*3)*7500
        assert order["quoted_total_cents"] == 1392400


def test_computed_input_fields_ignored(api):
    """PRD §3.2: "The configured `area_sqft` is the width times the depth."
    PRD §3.2: "The estimate produced at creation and at each amendment is stored as
    `quoted_total_cents`; the identical formula is recomputed at completion and stored
    as `final_total_cents`."

    Design: Corner/entities/order_create_computed_input_ignored
    """
    jur, model, cust = setup_book()
    payload = create_order_payload(
        cust["id"], model["id"], jur["id"], options=["WINDOW"],
    )
    payload["area_sqft"] = 999
    payload["quoted_total_cents"] = 1
    order = validate_success(api.create_order(payload, SALES), 201)
    assert order["area_sqft"] == 120, "server computes area 10*12, not the smuggled 999"
    assert order["quoted_total_cents"] == QUOTED_10X12_WINDOW_CASH


def test_order_defaults_applied(api):
    """PRD §3.2: "The `options` list may carry any subset of `WINDOW`, `LOFT`, `RAMP`,
    and `ELECTRICAL` and defaults to empty. Removal is off by default"
    PRD §3.2: "A new order starts in `DRAFT` with `structure_state` set to
    `NOT_INSTALLED`."
    PRD §3.2: "Both start at zero, as does `retained_cents`, and `site_prep_required`
    starts false."

    Design: Corner/entities/order_defaults_applied
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"], width_ft=8, depth_ft=8)
    assert order["options"] == []
    assert order["removal_requested"] is False
    assert order["structure_state"] == "NOT_INSTALLED"
    assert order["site_prep_required"] is False
    assert order["collected_cents"] == 0
    assert order["refunded_cents"] == 0
    assert order["retained_cents"] == 0
    assert order["quoted_total_cents"] == QUOTED_8X8_CASH


def test_trade_in_cap_and_removal_fee(api):
    """PRD §3.2: "Removal, when requested, adds $300.00 plus $5.00 per square foot of the
    old structure. The trade-in credit is the lesser of the appraised value — treated as
    zero when absent — and fifteen percent of the structure price, rounded down to whole
    cents."

    Design: Corner/calculations/trade_in_cap_and_removal_fee
    """
    jur, model, cust = setup_book()
    order = create_draft_order(
        cust["id"], model["id"], jur["id"],
        removal_requested=True, old_structure_area_sqft=80,
        trade_in_appraised_cents=100000,
    )
    # removal 30000 + 80*500 = 70000 added; trade-in capped at floor(392000*0.15)=58800,
    # NOT the 100000 appraisal: total 558000 + 70000 - 58800 + tax 27440
    assert order["quoted_total_cents"] == QUOTED_10X12_REMOVAL_TRADEIN


def test_prep_verdict_reprices_order(api):
    """PRD §3.3: "a `SUITABLE_WITH_PREP` verdict additionally sets `site_prep_required`
    to true, copies the filed `prep_cost_cents` into `site_prep_fee_cents`, and
    recomputes `quoted_total_cents`."
    PRD §3.1: "delivery, foundation, anchoring, site prep, and removal charges are never
    taxed."

    Design: Corner/calculations/prep_required_repricing
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"], options=["WINDOW"])
    asm = submit_site_check(order["id"])
    filed = file_report(asm["id"], ground_prep_needed=True, prep_cost_cents=30000)
    assert filed["verdict"] == "SUITABLE_WITH_PREP"

    refreshed = validate_success(api.get_order(order["id"], SALES), 200)
    assert refreshed["site_prep_required"] is True
    assert refreshed["site_prep_fee_cents"] == 30000
    # prep fee folded in; tax base unchanged (601490 + 30000)
    assert refreshed["quoted_total_cents"] == QUOTED_10X12_WINDOW_PREP_30000
    assert refreshed["status"] == "PERMIT_REVIEW"
