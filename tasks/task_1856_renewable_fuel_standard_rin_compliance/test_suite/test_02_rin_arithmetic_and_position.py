"""RIN arithmetic, position aggregation, and mark-to-market exposure (PRD §2.5, §3.7)."""
from test_helpers import (
    CM,
    OPS,
    TRADER,
    create_approved_vendor,
    create_account,
    create_generated_lot,
    create_price_quote,
    create_separated_lot,
    create_trade,
    create_verified_trade,
    deliver_trade,
    get_success_data,
    make_compliance_manager_headers,
    make_trader_headers,
    pay_trade,
    separate_lot,
    validate_success,
    api_client,
)


class TestPerLotGenerationRounding:
    def test_each_lot_rounds_half_up_independently(self, api):
        """PRD §2.5: "When a lot is generated, its RIN quantity is the wet-gallon volume multiplied by its equivalence value, rounded half-up to zero decimal places — and that rounding is applied per lot at the moment of generation."

        Design: Difficulty/combinatorial_formula/per_lot_generation_rounding_mode_b
        """
        acct = create_account(epa_registration_id="EPA-ACME-4")
        lot1 = create_generated_lot(
            acct["id"], d_code="D6", vintage_year=2026,
            gallon_qty=1, equivalence_value=1.5,
        )
        lot2 = create_generated_lot(
            acct["id"], d_code="D6", vintage_year=2026,
            gallon_qty=1, equivalence_value=1.5,
        )
        assert lot1["rin_qty"] == 2
        assert lot2["rin_qty"] == 2

    def test_position_sums_rounded_per_lot_values_not_aggregate(self, api):
        """PRD §2.5: "Position and obligation totals then sum the already-rounded per-lot quantities; the aggregate is never rounded again. Two lots of one gallon each at an equivalence value of 1.5 therefore contribute 2 RINs apiece, 4 in total — not the 3 that rounding their combined product would yield."

        Design: Difficulty/combinatorial_formula/per_lot_generation_rounding_mode_b
        """
        acct = create_account(epa_registration_id="EPA-ACME-4B")
        create_generated_lot(
            acct["id"], d_code="D6", vintage_year=2026,
            gallon_qty=1, equivalence_value=1.5,
        )
        create_generated_lot(
            acct["id"], d_code="D6", vintage_year=2026,
            gallon_qty=1, equivalence_value=1.5,
        )
        resp = api.get_account_position(acct["id"], CM)
        data = validate_success(resp)
        bucket = next(
            b for b in data["buckets"]
            if b["d_code"] == "D6" and b["vintage_year"] == 2026
        )
        assert bucket["generated_rins"] == 4


class TestPositionInputSetFiltering:
    def _setup_position_scenario(self, api):
        acct = create_account(epa_registration_id="EPA-CALC-5")
        lot_g = create_separated_lot(
            acct["id"], d_code="D6", vintage_year=2026, gallon_qty=100,
        )
        ven = create_approved_vendor(acct["id"])
        trd, _lot_p = create_verified_trade(
            acct["id"], ven["id"], rin_qty=50, price_per_rin_cents=100,
        )
        get_success_data(api.invalidate_trade(trd["id"], CM))
        return acct, lot_g

    def test_bucket_includes_invalidated_lots_for_reconciliation(self, api):
        """PRD §3.7: "The position read groups all of the account's lots — regardless of status, so that expired and invalidated lots still reconcile — into buckets keyed by D-code and vintage year."

        Design: Corner/calculations/position_input_set_filtering_by_status
        """
        acct, _lot_g = self._setup_position_scenario(api)
        resp = api.get_account_position(acct["id"], CM)
        data = validate_success(resp)
        bucket = next(
            b for b in data["buckets"]
            if b["d_code"] == "D6" and b["vintage_year"] == 2026
        )
        assert bucket["generated_rins"] == 100
        assert bucket["purchased_rins"] == 50
        assert bucket["invalidated_rins"] == 50
        assert bucket["available_rins"] == 100

    def test_position_total_invalidated_rins(self, api):
        """PRD §3.7: "Bucket values sum into totals, and the read surfaces `total_available_rins`, `total_retired_rins`, and `total_invalidated_rins` alongside the `buckets`"

        Design: Corner/calculations/position_input_set_filtering_by_status
        """
        acct, _lot_g = self._setup_position_scenario(api)
        resp = api.get_account_position(acct["id"], CM)
        data = validate_success(resp)
        assert data["total_invalidated_rins"] == 50


class TestExposureMarkToMarket:
    def _setup_exposure_scenario(self, api):
        acct = create_account(epa_registration_id="EPA-CALC-4")
        ven = create_approved_vendor(acct["id"])
        tr1 = make_trader_headers("tr-1")
        cm1 = make_compliance_manager_headers("cm-1")
        # (D6, 2026) bucket: 3 @100c + 4 @190c, both verified; available 7,
        # cost sum 3*100 + 4*190 = 1060 so wac = 1060/7 = 151.4286 (4dp rhu).
        t1 = create_trade(acct["id"], ven["id"], trader_headers=tr1,
                          rin_qty=3, price_per_rin_cents=100)
        pay_trade(t1["id"], trader_headers=tr1)
        deliver_trade(t1["id"], trader_headers=tr1)
        get_success_data(api.verify_trade(t1["id"], cm1))
        t2 = create_trade(acct["id"], ven["id"], trader_headers=tr1,
                          rin_qty=4, price_per_rin_cents=190)
        pay_trade(t2["id"], trader_headers=tr1)
        deliver_trade(t2["id"], trader_headers=tr1)
        get_success_data(api.verify_trade(t2["id"], cm1))
        # (D4, 2026) bucket: 10 generated, zero basis.
        create_separated_lot(acct["id"], d_code="D4", vintage_year=2026,
                             gallon_qty=10)
        # (D3, 2026) bucket: 5 generated, no covering quote.
        create_separated_lot(acct["id"], d_code="D3", vintage_year=2026,
                             gallon_qty=5)
        # Covering quotes for D6 and D4 only.
        create_price_quote(
            acct["id"], d_code="D6", vintage_year=2026, price_cents=170,
            effective_start="2026-07-01T00:00:00Z",
            effective_end="2026-08-31T23:59:59Z",
        )
        create_price_quote(
            acct["id"], d_code="D4", vintage_year=2026, price_cents=40,
            effective_start="2026-07-01T00:00:00Z",
            effective_end="2026-08-31T23:59:59Z",
        )
        return acct

    def test_exposure_bucket_counts(self, api):
        """PRD §3.7: "The bucket's market quote is the account's quote for the same D-code and vintage whose closed window covers the current logical clock; if no quote covers the bucket, the bucket is excluded from the exposure total and counted in `unpriced_bucket_count`."

        Design: Corner/calculations/exposure_mark_to_market_weighted_buckets
        """
        acct = self._setup_exposure_scenario(api)
        resp = api.get_account_exposure(acct["id"], CM)
        data = validate_success(resp)
        assert data["priced_bucket_count"] == 2
        assert data["unpriced_bucket_count"] == 1

    def test_exposure_total_is_sum_of_priced_bucket_gains(self, api):
        """PRD §3.7: "Each bucket's weighted-average cost is the sum over its lots of available quantity times `unit_cost_cents`, divided by the bucket's total available quantity, rounded half-up to four decimal places."
        PRD §3.7: "Each priced bucket contributes a gain of its total available quantity multiplied by the difference between the quoted price and the weighted-average cost, rounded half-up to a whole cent, and the gains sum into `total_exposure_cents`"

        Design: Corner/calculations/exposure_mark_to_market_weighted_buckets
        """
        acct = self._setup_exposure_scenario(api)
        resp = api.get_account_exposure(acct["id"], CM)
        data = validate_success(resp)
        # D6: wac = 1060/7 = 151.4286 (4dp rhu);
        # gain = round_half_up(7 * (170 - 151.4286)) = 130.
        # D4: gain = round_half_up(10 * (40 - 0)) = 400. Total = 530.
        assert data["total_exposure_cents"] == 530
