"""Fundraising campaigns: gross/raised/net divergence, attribution state+window
gating, sale-void compensation, disbursement cooling-off vs balance precedence."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    set_clock, create_gift_shop_cashier, create_item, create_campaign, ring_sale,
    make_treasurer_headers,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
TREASURER = TEST_USERS["treasurer_headers"]
TREASURER2 = TEST_USERS["treasurer2_headers"]


class TestGrossRaisedNetDiverge:
    def _setup(self):
        set_clock("2026-08-01T00:00:00Z")
        cashier = create_gift_shop_cashier()
        campaign = create_campaign(name="Lobby Renovation", goal_cents=100000,
                                   activate=True)
        it1 = create_item(sku="PLUSH-BEAR", name="Plush Bear", unit_price_cents=1000,
                          unit_cost_cents=300, stock_on_hand=10)
        it2 = create_item(sku="GETWELL-CARD", name="Get Well Card",
                          unit_price_cents=500, unit_cost_cents=100, stock_on_hand=5)
        set_clock("2026-08-02T12:00:00Z")
        s1 = ring_sale(cashier["volunteer_id"], [{"item_id": it1["id"], "qty": 2}],
                       2000, campaign_id=campaign["id"])
        s2 = ring_sale(cashier["volunteer_id"], [{"item_id": it2["id"], "qty": 1}],
                       500, campaign_id=campaign["id"])
        return campaign, it1, s1, s2

    def test_gross_raised_net_after_void(self, api):
        """PRD §3.8: "`gross_receipts_cents` sums `total_cents` over every attributed
        sale, voided ones included — the audit view of everything ever rung for the
        campaign. `raised_cents` sums `total_cents` over attributed sales in
        `COMPLETED` only — voids excluded. `net_proceeds_cents` is `raised_cents`
        minus the cost of goods of the non-voided attributed lines, where each line
        contributes its quantity times its item's `unit_cost_cents`."

        Design: Difficulty/dual_variant_calc/campaign_gross_raised_net_diverge
        """
        campaign, _, _, s2 = self._setup()
        validate_success(api.void_sale(s2["id"], {"void_reason": "customer changed mind"},
                                       TREASURER))
        camp = get_success_data(api.get_campaign(campaign["id"], TREASURER))
        assert camp["gross_receipts_cents"] == 2500, "2000 + 500, void included"
        assert camp["raised_cents"] == 2000, "the voided 500 is excluded"
        assert camp["net_proceeds_cents"] == 1400, "2000 - 2*300 COGS"
        assert camp["gross_receipts_cents"] > camp["raised_cents"] > camp["net_proceeds_cents"]

    def test_gross_is_immutable_across_void(self, api):
        """PRD §3.7: "The campaign's `gross_receipts_cents` — the everything-ever-rung
        figure — is deliberately left unchanged by a void."
        PRD §3.7: "for an attributed sale, subtracts the sale's `total_cents` from
        the campaign's `raised_cents` and the sale's margin (total minus the lines'
        cost of goods) from `net_proceeds_cents`."

        Design: Difficulty/dual_variant_calc/campaign_gross_raised_net_diverge
        """
        campaign, _, _, s2 = self._setup()
        before = get_success_data(api.get_campaign(campaign["id"], TREASURER))
        assert before["gross_receipts_cents"] == 2500
        assert before["raised_cents"] == 2500
        assert before["net_proceeds_cents"] == 1800, "2500 - (600 + 100) COGS"

        validate_success(api.void_sale(s2["id"], {"void_reason": "register error"}, TREASURER))
        after = get_success_data(api.get_campaign(campaign["id"], TREASURER))
        assert after["gross_receipts_cents"] == 2500, "gross keeps the audit trail"
        assert after["raised_cents"] == 2000
        assert after["net_proceeds_cents"] == 1400


class TestSaleAttributionGates:
    def _setup(self):
        set_clock("2026-08-01T00:00:00Z")
        cashier = create_gift_shop_cashier()
        item = create_item(sku="PLUSH-BEAR", name="Plush Bear", unit_price_cents=1000,
                           unit_cost_cents=300, stock_on_hand=10)
        campaign = create_campaign(name="Scanner Fund", activate=False)
        set_clock("2026-08-02T12:00:00Z")  # inside the window, campaign still DRAFT
        return cashier, item, campaign

    def test_attribution_blocked_by_state_then_window(self, api):
        """PRD §3.7: "Attribution itself is only valid into an `ACTIVE` campaign
        (`ERR_CAMPAIGN_INVALID_STATE`) whose window currently contains now —
        `start_at` at or before now and now strictly before `end_at`
        (`ERR_CAMPAIGN_WINDOW_MISMATCH`)."

        Design: Difficulty/cross_entity_state_dependency/sale_attribution_gated_by_campaign_state_and_window
        """
        cashier, item, campaign = self._setup()

        resp = api.create_sale(
            {"cashier_volunteer_id": cashier["volunteer_id"],
             "campaign_id": campaign["id"],
             "lines": [{"item_id": item["id"], "qty": 1}],
             "tendered_cents": 1000}, TREASURER)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_INVALID_STATE)

        validate_success(api.activate_campaign(campaign["id"], TREASURER))
        set_clock("2026-08-06T09:00:00Z")  # past end_at (exclusive)
        resp = api.create_sale(
            {"cashier_volunteer_id": cashier["volunteer_id"],
             "campaign_id": campaign["id"],
             "lines": [{"item_id": item["id"], "qty": 1}],
             "tendered_cents": 1000}, TREASURER)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_MISMATCH)

        item_now = get_success_data(api.get_item(item["id"], TREASURER))
        assert item_now["stock_on_hand"] == 10, "rejected attributions touch nothing"

    def test_attribution_happy_path_feeds_campaign(self, api):
        """PRD §3.8: "`gross_receipts_cents` sums `total_cents` over every attributed
        sale"; "`net_proceeds_cents` is `raised_cents` minus the cost of goods of the
        non-voided attributed lines".

        Design: Difficulty/cross_entity_state_dependency/sale_attribution_gated_by_campaign_state_and_window
        """
        cashier, item, campaign = self._setup()
        validate_success(api.activate_campaign(campaign["id"], TREASURER))
        sale = validate_success(api.create_sale(
            {"cashier_volunteer_id": cashier["volunteer_id"],
             "campaign_id": campaign["id"],
             "lines": [{"item_id": item["id"], "qty": 1}],
             "tendered_cents": 1000}, TREASURER), expected_status=201)
        assert sale["status"] == "COMPLETED"
        camp = get_success_data(api.get_campaign(campaign["id"], TREASURER))
        assert camp["gross_receipts_cents"] == 1000
        assert camp["raised_cents"] == 1000
        assert camp["net_proceeds_cents"] == 700, "1000 - 1*300 COGS"


class TestDisbursementPrecedence:
    def _setup_reconciled_campaign(self):
        set_clock("2026-08-01T00:00:00Z")
        cashier = create_gift_shop_cashier()
        campaign = create_campaign(name="Scanner Fund")  # creator: treasurer-1
        validate_success(api_client.activate_campaign(campaign["id"], TREASURER))
        item = create_item(sku="PLUSH-BEAR", name="Plush Bear", unit_price_cents=1000,
                           unit_cost_cents=300, stock_on_hand=10)
        set_clock("2026-08-02T12:00:00Z")
        ring_sale(cashier["volunteer_id"], [{"item_id": item["id"], "qty": 1}],
                  1000, campaign_id=campaign["id"])  # net = 1000 - 300 = 700
        set_clock("2026-08-05T00:00:00Z")  # now >= end_at
        validate_success(api_client.close_campaign(campaign["id"], TREASURER))
        validate_success(api_client.reconcile_campaign(campaign["id"], TREASURER))
        return campaign

    def test_cooling_off_beats_balance_overflow(self, api):
        """PRD §2.8: "Checks are evaluated in a fixed thirteen-tier order, and the
        earliest failing tier wins". (Tier 11, Temporal windows and deadlines —
        which lists ERR_DISBURSEMENT_COOLING_OFF — precedes tier 13, Money and
        stock, last of all — which lists ERR_DISBURSEMENT_EXCEEDS_BALANCE.)
        PRD §3.8: "The cooling-off period: now must be at least seven days after
        `closed_at`, or the request is `ERR_DISBURSEMENT_COOLING_OFF`."
        (The SoD gate is neutralized: the disburser is not the campaign creator.)

        Design: Difficulty/priority_pair_validation_conflict/disburse_temporal_beats_fiscal
        """
        campaign = self._setup_reconciled_campaign()
        set_clock("2026-08-08T00:00:00Z")  # closed_at + 3 days, inside cooling-off
        resp = api.disburse_campaign(
            campaign["id"], {"amount_cents": 9000, "recipient": "Hospital Foundation"},
            TREASURER2)
        validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_COOLING_OFF)
        camp = get_success_data(api.get_campaign(campaign["id"], TREASURER))
        assert camp["disbursed_cents"] == 0

    def test_balance_overflow_in_isolation(self, api):
        """PRD §3.8: "`amount_cents` may not exceed `net_proceeds_cents` minus
        `disbursed_cents`, or the request is `ERR_DISBURSEMENT_EXCEEDS_BALANCE`."
        (Isolation control: after the cooling-off lapses, the over-balance amount is
        the only failing check.)

        Design: Difficulty/priority_pair_validation_conflict/disburse_temporal_beats_fiscal
        """
        campaign = self._setup_reconciled_campaign()
        set_clock("2026-08-12T00:00:00Z")  # closed_at + 7 days: cooling-off satisfied
        resp = api.disburse_campaign(
            campaign["id"], {"amount_cents": 9000, "recipient": "Hospital Foundation"},
            TREASURER2)
        validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_EXCEEDS_BALANCE)
        camp = get_success_data(api.get_campaign(campaign["id"], TREASURER))
        assert camp["disbursed_cents"] == 0


class TestSaleVoidCompensation:
    def _setup(self):
        set_clock("2026-08-01T00:00:00Z")
        cashier = create_gift_shop_cashier()
        campaign = create_campaign(name="Scanner Fund", activate=True)
        item = create_item(sku="PLUSH-BEAR", name="Plush Bear", unit_price_cents=1000,
                           unit_cost_cents=300, stock_on_hand=10)
        set_clock("2026-08-02T12:00:00Z")
        return cashier, campaign, item

    def test_void_restores_stock_and_unwinds_campaign(self, api):
        """PRD §3.7: "Voiding restores each line's quantity to its item's
        `stock_on_hand` — the exact compensation of the sale — and, for an attributed
        sale, subtracts the sale's `total_cents` from the campaign's `raised_cents`
        and the sale's margin (total minus the lines' cost of goods) from
        `net_proceeds_cents`."

        Design: Difficulty/compensating_invariant/sale_void_restores_stock_exactly
        """
        cashier, campaign, item = self._setup()
        sale = ring_sale(cashier["volunteer_id"], [{"item_id": item["id"], "qty": 3}],
                         3000, campaign_id=campaign["id"])

        mid_item = get_success_data(api.get_item(item["id"], TREASURER))
        assert mid_item["stock_on_hand"] == 7
        mid_camp = get_success_data(api.get_campaign(campaign["id"], TREASURER))
        assert mid_camp["raised_cents"] == 3000
        assert mid_camp["net_proceeds_cents"] == 2100, "3000 - 3*300"

        validate_success(api.void_sale(sale["id"], {"void_reason": "register error"},
                                       TREASURER))
        fin_item = get_success_data(api.get_item(item["id"], TREASURER))
        assert fin_item["stock_on_hand"] == 10, "units conserved exactly (10 -> 7 -> 10)"
        fin_camp = get_success_data(api.get_campaign(campaign["id"], TREASURER))
        assert fin_camp["raised_cents"] == 0
        assert fin_camp["net_proceeds_cents"] == 0
        assert fin_camp["gross_receipts_cents"] == 3000, "the audit trail is preserved"

    def test_repeat_void_and_elapsed_window_rejected(self, api):
        """PRD §3.7: "A completed sale can be voided by the treasurer or a
        coordinator, but only within 24 hours of its creation — after that,
        `ERR_VOID_WINDOW_ELAPSED` — and only while it stands `COMPLETED` (a repeat
        void is `ERR_SALE_ALREADY_VOIDED`)."

        Design: Difficulty/compensating_invariant/sale_void_restores_stock_exactly
        """
        cashier, campaign, item = self._setup()
        sale = ring_sale(cashier["volunteer_id"], [{"item_id": item["id"], "qty": 1}],
                         1000, campaign_id=campaign["id"])
        validate_success(api.void_sale(sale["id"], {"void_reason": "register error"},
                                       TREASURER))
        resp = api.void_sale(sale["id"], {"void_reason": "second try"}, TREASURER)
        validate_error(resp, ApiErrorId.ERR_SALE_ALREADY_VOIDED)

        # A separate sale pushed past the 24h void window.
        sale2 = ring_sale(cashier["volunteer_id"], [{"item_id": item["id"], "qty": 1}],
                          1000, campaign_id=campaign["id"])
        set_clock("2026-08-04T00:00:00Z")  # 36h after sale2's creation
        resp = api.void_sale(sale2["id"], {"void_reason": "too late"}, TREASURER)
        validate_error(resp, ApiErrorId.ERR_VOID_WINDOW_ELAPSED)
        row = get_success_data(api.get_sale(sale2["id"], TREASURER))
        assert row["status"] == "COMPLETED", "the late void leaves the sale COMPLETED"
