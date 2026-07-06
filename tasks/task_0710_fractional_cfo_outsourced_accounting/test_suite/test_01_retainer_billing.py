"""Retainer invoice tier pricing, metered overage, and the catch-up surcharge."""
from test_helpers import (
    validate_success, get_success_data,
    create_client, create_client_with_close, setup_scoped_catchup,
    current_client_version, issue_retainer_invoice,
    assert_retainer_invoice_total_consistent,
    api_client, TEST_USERS,
)

CFO = TEST_USERS["cfo_headers"]
BK = TEST_USERS["bookkeeper_headers"]


class TestRetainerSurchargeVariant:
    def test_growth_close_with_active_catchup_carries_surcharge(self, api):
        """PRD §3.8: "The **surcharge**, stored as `surcharge_cents`, applies only
        when the client's `catchup_active` flag is true at the instant of issuance:
        it is 20 percent of the tier base fee, rounded half up to whole cents."
        PRD §3.8: "`GROWTH` includes 500 transactions at 600 milli-dollars ($0.60,
        i.e. 60 cents) each"

        Design: Difficulty/dual_variant_calc/retainer_surcharge_variant_divergence
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        setup_scoped_catchup(cid)
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 1, "txn_count": 650}, BK))
        cver = current_client_version(cid)
        inv = get_success_data(api.issue_retainer_invoice(
            cid, {"monthly_close_id": close["id"], "expected_client_version": cver}, CFO))
        assert inv["base_fee_cents"] == 300000
        assert inv["overage_cents"] == 9000
        assert inv["surcharge_cents"] == 60000
        assert inv["total_cents"] == 369000
        assert_retainer_invoice_total_consistent(inv)

    def test_growth_close_without_catchup_omits_surcharge(self, api):
        """PRD §3.8: "When `catchup_active` is false at issuance the surcharge is
        zero, so two invoices issued off identical close data — one with an active
        catch-up project, one without — produce different totals."

        Design: Difficulty/dual_variant_calc/retainer_surcharge_variant_divergence
        """
        client, close = create_client_with_close(
            retainer_tier="GROWTH", txn_count=650, period_month=1)
        inv = issue_retainer_invoice(client["id"], close["id"])
        assert inv["surcharge_cents"] == 0
        assert inv["total_cents"] == 309000


class TestRetainerCombinatorialFormula:
    def test_cfo_tier_overage_and_surcharge_combined(self, api):
        """PRD §3.8: "$6,000.00 (600000 cents) for `CFO`."
        PRD §3.8: "`CFO` includes 1,200 transactions at 450 milli-dollars ($0.45,
        i.e. 45 cents) each"
        PRD §3.8: "it is 20 percent of the tier base fee, rounded half up to whole
        cents."

        Design: Difficulty/combinatorial_formula/retainer_tiered_rate_with_conditional_surcharge
        """
        client = create_client(retainer_tier="CFO")
        cid = client["id"]
        setup_scoped_catchup(cid, months_behind=6, quoted_fee_cents=900000)
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 2, "txn_count": 1500}, BK))
        inv = issue_retainer_invoice(cid, close["id"])
        assert inv["base_fee_cents"] == 600000
        assert inv["overage_cents"] == 13500
        assert inv["surcharge_cents"] == 120000
        assert inv["total_cents"] == 733500
        assert_retainer_invoice_total_consistent(inv)

    def test_cfo_tier_total_is_sum_of_three_parts(self, api):
        """PRD §3.8: "The `total_cents` is the straightforward sum of
        `base_fee_cents`, `overage_cents`, and `surcharge_cents`."

        Design: Difficulty/combinatorial_formula/retainer_tiered_rate_with_conditional_surcharge
        """
        client = create_client(retainer_tier="CFO")
        cid = client["id"]
        setup_scoped_catchup(cid, months_behind=6, quoted_fee_cents=900000)
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 2, "txn_count": 1500}, BK))
        inv = issue_retainer_invoice(cid, close["id"])
        assert inv["total_cents"] == 733500
        assert_retainer_invoice_total_consistent(inv)

    def test_growth_overage_above_included_no_catchup(self, api):
        """PRD §3.8: "the named close's `txn_count` minus the tier's included
        transactions, floored at zero so an under-volume month carries no overage,
        multiplied by the tier's per-transaction overage rate."

        Design: Corner/calculations/retainer_overage_only_growth_above_included
        """
        client, close = create_client_with_close(
            retainer_tier="GROWTH", txn_count=650, period_month=6)
        inv = issue_retainer_invoice(client["id"], close["id"])
        assert inv["base_fee_cents"] == 300000
        assert inv["overage_cents"] == 9000
        assert inv["surcharge_cents"] == 0
        assert inv["total_cents"] == 309000


class TestRetainerOverageBoundary:
    def test_overage_zero_at_exactly_included_volume(self, api):
        """PRD §3.8: "the named close's `txn_count` minus the tier's included
        transactions, floored at zero so an under-volume month carries no overage,
        multiplied by the tier's per-transaction overage rate."
        PRD §3.8: "$1,500.00 (150000 cents) for `ESSENTIALS`"

        Design: Difficulty/boundary_precision_check/retainer_overage_zero_at_included_boundary
        """
        client, close = create_client_with_close(
            retainer_tier="ESSENTIALS", txn_count=200, period_month=5)
        inv = issue_retainer_invoice(client["id"], close["id"])
        assert inv["overage_cents"] == 0
        assert inv["total_cents"] == 150000

    def test_overage_one_transaction_over_included(self, api):
        """PRD §3.8: "`ESSENTIALS` includes 200 transactions and charges 750
        milli-dollars ($0.75, i.e. 75 cents) per overage transaction"

        Design: Difficulty/boundary_precision_check/retainer_overage_zero_at_included_boundary
        """
        client, close = create_client_with_close(
            retainer_tier="ESSENTIALS", txn_count=201, period_month=5)
        inv = issue_retainer_invoice(client["id"], close["id"])
        assert inv["overage_cents"] == 75
        assert inv["total_cents"] == 150075
