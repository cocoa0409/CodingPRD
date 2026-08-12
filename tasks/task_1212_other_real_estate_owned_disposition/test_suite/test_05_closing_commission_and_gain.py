"""Closing statements: tiered commission, split rounding order, dual-variant
gain recognition, settlement, and the settle-then-void compensating invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    create_property,
    create_marketed_property,
    create_offer_under_review,
    setup_approval_tiers,
    setup_property_with_accepted_offer,
    setup_settled_sale,
    get_offer,
    get_property,
    get_property_summary,
    get_listing,
    list_ledger_entries,
    assert_closing_statement,
    assert_closing_split_consistency,
    assert_property_summary_invariants,
    set_clock,
    create_closing_statement_payload,
)

ADMIN = TEST_USERS["oreo_admin_headers"]
SPEC = TEST_USERS["oreo_specialist_headers"]
CO = TEST_USERS["credit_officer_headers"]
COMMITTEE = TEST_USERS["oreo_committee_headers"]


class TestCommissionCalculation:
    def test_tiered_commission_property_type_and_financing_overrides_land_sf(self, api):
        """PRD §3.7: "the first 500,000.00 of price at 6 percent, the portion
        strictly above 500,000.00 up to and including 1,000,000.00 at 5 percent,
        and the portion strictly above 1,000,000.00 at 3 percent — and for a
        LAND property each tier's rate carries an additional 1 percent
        surcharge. The tiered total is rounded half-up to two decimals exactly
        once. For a SELLER_FINANCED deal the rounded tiered total is capped at 6
        percent of the price — the cap figure itself is 0.06 times the price,
        rounded half-up to two decimals, and the commission is the smaller of
        the two; for a CASH deal no cap applies."

        Design: Difficulty/combinatorial_formula/tiered_commission_property_type_and_financing_overrides
        """
        # LAND property, SELLER_FINANCED offer at 400000.00
        # tiered LAND: 400000 * 0.07 = 28000.00
        # SF cap:      400000 * 0.06 = 24000.00
        # commission_total = min(28000, 24000) = 24000.00
        ctx = setup_property_with_accepted_offer(
            offer_price=400000.00,
            financing_type="SELLER_FINANCED",
            down_payment=100000.00,
            accept_as="credit_officer",
            property_overrides={
                "address": "Lot 7 Desert View",
                "county": "Kern",
                "property_type": "LAND",
                "bpo_value": 300000.00,
                "foreclosure_debt": 295000.00,
            },
            appraised_value=300000.00,
            listing_price=400000.00,
        )
        closing_resp = api.create_closing_statement(
            create_closing_statement_payload(
                offer_id=ctx["offer"]["id"], closing_date="2026-08-01"
            ),
            SPEC,
        )
        closing = validate_success(closing_resp, expected_status=201)
        assert_closing_statement(closing)
        assert closing["commission_total"] == 24000.00
        assert closing["net_proceeds"] == 373500.00
        # carrying = 300000 - 8% = 276000
        assert closing["gain_loss"] == 97500.00
        # SF variant: recognized = round(100000 * 97500/400000, 2) = 24375.00
        assert closing["recognized_gain_at_settlement"] == 24375.00

    def test_tiered_commission_land_surcharge_per_tier_without_cap(self, api):
        """PRD §3.7: "for a LAND property each tier's rate carries an
        additional 1 percent surcharge... for a CASH deal no cap applies."
        A LAND CASH 400000.00 contract must price at 400000 * 0.07 = 28000.00
        (the LAND surcharge applies, and no SELLER_FINANCED cap is consulted).

        Design: Difficulty/combinatorial_formula/tiered_commission_property_type_and_financing_overrides
        """
        ctx = setup_property_with_accepted_offer(
            offer_price=400000.00,
            financing_type="CASH",
            accept_as="credit_officer",
            property_overrides={
                "address": "Lot 7 Desert View",
                "county": "Kern",
                "property_type": "LAND",
                "bpo_value": 300000.00,
                "foreclosure_debt": 295000.00,
            },
            appraised_value=300000.00,
            listing_price=400000.00,
        )
        closing = validate_success(
            api.create_closing_statement(
                create_closing_statement_payload(
                    offer_id=ctx["offer"]["id"], closing_date="2026-08-01"
                ),
                SPEC,
            ),
            expected_status=201,
        )
        # LAND CASH: 400000 * 0.07 = 28000 (no cap)
        assert closing["commission_total"] == 28000.00

    def test_commission_tier_boundary_at_500000(self, api):
        """PRD §3.7: "the first 500,000.00 of price at 6 percent, the portion
        strictly above 500,000.00 up to and including 1,000,000.00 at 5
        percent".

        Design: Corner/calculations/commission_tier_boundary_at_500000
        """
        # Price exactly 500000 -> tier 1 only: 500000 * 0.06 = 30000.00
        ctx_a = setup_property_with_accepted_offer(
            offer_price=500000.00,
            financing_type="CASH",
            accept_as="committee",
            property_overrides={
                "address": "1 Boundary Rd",
                "county": "Marin",
                "bpo_value": 600000.00,
                "foreclosure_debt": 590000.00,
            },
            appraised_value=600000.00,
            listing_price=520000.00,
        )
        ca = validate_success(
            api.create_closing_statement(
                create_closing_statement_payload(
                    offer_id=ctx_a["offer"]["id"], closing_date="2026-08-01"
                ),
                SPEC,
            ),
            expected_status=201,
        )
        assert ca["commission_total"] == 30000.00

        # Price 500001 -> 30000 + 0.05 = 30000.05
        ctx_b = setup_property_with_accepted_offer(
            offer_price=500001.00,
            financing_type="CASH",
            accept_as="committee",
            property_overrides={
                "address": "2 Boundary Rd",
                "county": "Marin",
                "bpo_value": 600000.00,
                "foreclosure_debt": 590000.00,
            },
            appraised_value=600000.00,
            listing_price=520000.00,
        )
        cb = validate_success(
            api.create_closing_statement(
                create_closing_statement_payload(
                    offer_id=ctx_b["offer"]["id"], closing_date="2026-08-01"
                ),
                SPEC,
            ),
            expected_status=201,
        )
        assert cb["commission_total"] == 30000.05


class TestCommissionSplit:
    def test_commission_split_rounding_order_pinned_total_first(self, api):
        """PRD §2.6: "Broker commission rounds the tiered total once, then
        computes the listing-broker share from that rounded total, then assigns
        the selling-broker share as the remainder so the odd cent always lands
        on the selling side. Computing each share and rounding the shares
        separately is explicitly not the specification — it produces a one-cent
        drift that the settlement ledger does not tolerate."
        PRD §3.7: "listing_broker_share is one-half of commission_total rounded
        half-up to two decimals, and selling_broker_share is commission_total
        minus listing_broker_share, so the selling side absorbs any odd cent."

        Design: Difficulty/combinatorial_formula/commission_split_rounding_order_pinned
        """
        # price 1200001.00 -> tiered = 500000*0.06 + 500000*0.05 + 200001*0.03
        #                       = 30000 + 25000 + 6000.03 = 61000.03
        # listing = round(61000.03 * 0.5, 2) = 30500.02 (half-up)
        # selling = 61000.03 - 30500.02 = 30500.01
        ctx = setup_property_with_accepted_offer(
            offer_price=1200001.00,
            financing_type="CASH",
            accept_as="committee",
            property_overrides={
                "address": "900 Hillcrest Dr",
                "county": "Marin",
                "bpo_value": 1300000.00,
                "foreclosure_debt": 1250000.00,
            },
            appraised_value=1300000.00,
            listing_price=1300000.00,
            earnest_money=25000.00,
        )
        closing = validate_success(
            api.create_closing_statement(
                create_closing_statement_payload(
                    offer_id=ctx["offer"]["id"], closing_date="2026-08-01"
                ),
                SPEC,
            ),
            expected_status=201,
        )
        assert closing["commission_total"] == 61000.03
        assert closing["listing_broker_share"] == 30500.02
        assert closing["selling_broker_share"] == 30500.01
        # selling side absorbs the odd cent
        assert_closing_split_consistency(closing)

    def test_commission_split_sums_to_total(self, api):
        """PRD §3.7: "listing_broker_share is one-half of commission_total
        rounded half-up to two decimals, and selling_broker_share is
        commission_total minus listing_broker_share".

        Design: Difficulty/combinatorial_formula/commission_split_rounding_order_pinned
        """
        ctx = setup_property_with_accepted_offer(
            offer_price=450000.00, financing_type="CASH", accept_as="credit_officer"
        )
        closing = validate_success(
            api.create_closing_statement(
                create_closing_statement_payload(
                    offer_id=ctx["offer"]["id"], closing_date="2026-08-01"
                ),
                SPEC,
            ),
            expected_status=201,
        )
        # 450000 * 0.06 = 27000 -> 13500 each
        assert closing["commission_total"] == 27000.00
        assert closing["listing_broker_share"] == 13500.00
        assert closing["selling_broker_share"] == 13500.00


class TestGainRecognitionVariants:
    def test_gain_recognition_cash_variant_recognizes_full(self, api):
        """PRD §3.7: "For a CASH deal, recognized_gain_at_settlement is the
        full gain_loss and deferred_gain is 0.00."

        Design: Difficulty/dual_variant_calc/gain_recognition_cash_vs_installment
        """
        # 450000 CASH on carrying 368000
        # commission 27000 -> net = 450000 - 27000 - 2500 = 420500
        # gain_loss = 420500 - 368000 = 52500
        ctx = setup_settled_sale(
            offer_price=450000.00, financing_type="CASH", accept_as="credit_officer"
        )
        closing = ctx["closing"]
        assert closing["gain_loss"] == 52500.00
        assert closing["recognized_gain_at_settlement"] == 52500.00
        assert closing["deferred_gain"] == 0.00

    def test_gain_recognition_seller_financed_installment_variant(self, api):
        """PRD §3.7: "For a SELLER_FINANCED deal with a positive gain_loss,
        recognized_gain_at_settlement is the down payment multiplied by the
        ratio of gain_loss to contract_price, rounded half-up to two decimals —
        the ratio itself is not pre-rounded — and deferred_gain is gain_loss
        minus the recognized amount; identical economics therefore recognize
        less at settlement than the CASH variant, deferring the remainder."

        Design: Difficulty/dual_variant_calc/gain_recognition_cash_vs_installment
        """
        # same economics as CASH: price 450000, down 90000
        # recognized = round(90000 * 52500/450000, 2) = 10500.00
        # deferred   = 52500 - 10500 = 42000.00
        ctx = setup_settled_sale(
            offer_price=450000.00,
            financing_type="SELLER_FINANCED",
            down_payment=90000.00,
            accept_as="credit_officer",
        )
        closing = ctx["closing"]
        assert closing["gain_loss"] == 52500.00
        assert closing["recognized_gain_at_settlement"] == 10500.00
        assert closing["deferred_gain"] == 42000.00

        # summary recognized_gain_loss_total matches the SF recognized amount
        summary = get_property_summary(ctx["property"]["id"])
        assert summary["recognized_gain_loss_total"] == 10500.00


class TestLossRecognition:
    def test_cash_sale_below_carrying_recognizes_loss(self, api):
        """PRD §3.7: "it appends either a GAIN_RECOGNIZED entry carrying the
        positive recognized_gain_at_settlement when gain_loss is positive, or a
        LOSS_RECOGNIZED entry carrying the negative of the loss magnitude
        otherwise."
        PRD §2.7: "LOSS_RECOGNIZED carries the negative of the loss magnitude".

        Design: Corner/calculations/cash_sale_below_carrying_recognizes_loss
        """
        # 350000 CASH on carrying 368000
        # commission 21000 -> net = 350000 - 21000 - 2500 = 326500
        # gain_loss = 326500 - 368000 = -41500 (LOSS)
        # 326500 < 0.9 * 368000 = 331200 -> deep-discount -> committee
        ctx = setup_settled_sale(
            offer_price=350000.00,
            financing_type="CASH",
            accept_as="committee",
            listing_price=380000.00,
        )
        closing = ctx["closing"]
        assert closing["gain_loss"] == -41500.00

        # ledger carries LOSS_RECOGNIZED -41500
        entries = list_ledger_entries(ctx["property"]["id"])
        losses = [e for e in entries if e["entry_type"] == "LOSS_RECOGNIZED"]
        assert len(losses) == 1
        assert losses[0]["amount"] == -41500.00

        # summary recognized total matches; property DISPOSED
        summary = get_property_summary(ctx["property"]["id"])
        assert summary["recognized_gain_loss_total"] == -41500.00
        assert summary["lifecycle_status"] == "DISPOSED"


class TestSettleVoidInvariant:
    def test_settle_then_void_preserves_recognized_gain_total(self, api):
        """PRD §3.7: "Voiding appends compensating ledger rows with negated
        amounts — PROCEEDS at negative net_proceeds and the negated
        gain-or-loss counterpart — moves the closing to VOID, returns the offer
        to ACCEPTED, returns the property from DISPOSED to UNDER_CONTRACT,
        recomputes recognized_gain_loss_total back to its pre-settle value, and
        increments property.version. The ledger never edits the original rows;
        the reversal is itself history."

        Design: Difficulty/compensating_invariant/settle_then_void_preserves_recognized_gain_total
        """
        ctx = setup_settled_sale(
            offer_price=450000.00, financing_type="CASH", accept_as="credit_officer"
        )
        closing = ctx["closing"]
        prop = ctx["property"]
        # after settle: recognized == 52500
        s1 = get_property_summary(prop["id"])
        assert s1["recognized_gain_loss_total"] == 52500.00

        # void
        void_resp = api.void_closing(closing["id"], COMMITTEE)
        validate_success(void_resp, expected_status=200)
        s2 = get_property_summary(prop["id"])
        assert s2["recognized_gain_loss_total"] == 0.00

    def test_void_appends_negated_counterparts_and_restores_states(self, api):
        """PRD §3.7: "Voiding appends compensating ledger rows with negated
        amounts — PROCEEDS at negative net_proceeds and the negated
        gain-or-loss counterpart — moves the closing to VOID, returns the offer
        to ACCEPTED, returns the property from DISPOSED to UNDER_CONTRACT".

        Design: Difficulty/compensating_invariant/settle_then_void_preserves_recognized_gain_total
        """
        ctx = setup_settled_sale(
            offer_price=450000.00, financing_type="CASH", accept_as="credit_officer"
        )
        closing = ctx["closing"]
        prop = ctx["property"]
        api.void_closing(closing["id"], COMMITTEE)

        # closing voided
        c_after = validate_success(api.get_closing_statement(closing["id"], ADMIN))
        assert c_after["status"] == "VOID"

        # offer back to ACCEPTED, property back to UNDER_CONTRACT
        assert get_offer(ctx["offer"]["id"])["status"] == "ACCEPTED"
        assert get_property(prop["id"])["lifecycle_status"] == "UNDER_CONTRACT"

        # ledger for this closing contains negated counterparts
        entries = list_ledger_entries(prop["id"], closing_statement_id=closing["id"])
        by_type = {}
        for e in entries:
            by_type.setdefault(e["entry_type"], []).append(e["amount"])
        proceeds = sorted(by_type.get("PROCEEDS", []))
        gains = sorted(by_type.get("GAIN_RECOGNIZED", []))
        # both +420500 and -420500 exist
        assert 420500.00 in proceeds and -420500.00 in proceeds
        assert 52500.00 in gains and -52500.00 in gains


class TestClosingInvalidStates:
    def test_settle_voided_closing_returns_invalid_state(self, api):
        """PRD §3.7: "Settlement is a CreditOfficer action on a DRAFT closing
        (any other from-state raises ERR_CLOSING_INVALID_STATE)."

        Design: Corner/state_machines/settle_voided_closing_returns_invalid_state
        """
        ctx = setup_settled_sale()
        closing = ctx["closing"]
        # void it first
        api.void_closing(closing["id"], COMMITTEE)
        # now settle must fail (VOID is terminal)
        resp = api.settle_closing(closing["id"], CO)
        validate_error(resp, ApiErrorId.ERR_CLOSING_INVALID_STATE)
        c_after = validate_success(api.get_closing_statement(closing["id"], ADMIN))
        assert c_after["status"] == "VOID"


class TestBrokerScoreFromSale:
    def test_broker_score_computed_from_closed_sale(self, api):
        """PRD §3.11: "The score is one-half of the close rate plus
        three-tenths of the market-time ratio plus one-fifth of the price
        ratio, rounded half-up to four decimal places."
        Components: close_rate = count(CLOSED) / count(terminal), market-time
        caps avg days at 180 and yields 1 - capped_avg/180, price_ratio =
        contract_price / listing_price.

        Design: Corner/calculations/broker_score_computed_from_closed_sale
        """
        ctx = setup_settled_sale(
            offer_price=450000.00,
            financing_type="CASH",
            accept_as="credit_officer",
            listing_price=450000.00,
            closing_date="2026-08-01",
        )
        broker = ctx["broker"]
        # listing start 2026-06-05 -> close 2026-08-01 = 57 days
        # close_rate = 1.0; market_ratio = 1 - 57/180; price_ratio = 450000/450000 = 1.0
        # score = round(0.5*1.0 + 0.3*(1 - 57/180) + 0.2*1.0, 4)
        #       = 0.5 + 0.3*0.683333... + 0.2 = 0.5 + 0.205 + 0.2 = 0.905
        b = validate_success(api.get_broker(broker["id"], ADMIN))
        assert b["performance_score"] == pytest.approx(0.905, abs=1e-4)
