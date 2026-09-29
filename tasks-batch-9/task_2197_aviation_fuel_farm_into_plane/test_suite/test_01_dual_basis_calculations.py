"""Dual-basis arithmetic: governing vs advisory receipt volumes, accrual vs invoiced
airline exposure, and the two reconciliation variance denominators."""
import pytest

from test_helpers import (
    validate_success, fixtures as fx,
)


class TestReceiptGoverningBasis:
    def test_truck_meter_ticket_governs_while_pipeline_gauge_delta_governs(self, api):
        """PRD §3.2: "For a `TRUCK` parcel the `governing_gross_liters` is the supplier meter
        ticket and the `advisory_gross_liters` is the gauge delta; for a `PIPELINE` parcel it
        is the other way round — the gauge delta governs and the meter ticket becomes advisory."
        PRD §3.2: "**Second**, the volume correction factor is one minus the coefficient
        multiplied by the parcel temperature less the 15-degree reference temperature, and this
        factor is rounded half up to five decimal places *before* it multiplies anything."
        PRD §3.2: "**Fifth**, the water deduction cap is one half of one percent of the
        *governing gross* — not of the corrected volume — rounded half up to two decimals, and
        the deduction actually applied is the smaller of the measured water volume and that cap."

        Design: Difficulty/dual_variant_calc/receipt_governing_basis_truck_meter_vs_pipeline_gauge
        """
        env = fx.setup_fuel_farm(permit_overrides={"max_daily_throughput_liters": 400000.0})
        tank = fx.register_tank(env["farm"]["id"], capacity_liters=5_000_000.0,
                                safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                opening_volume_liters=0.0)

        measurements = dict(
            supplier_name="Refinery One", meter_ticket_gross_liters=30120.0,
            tank_opening_gauge_liters=100.0, tank_closing_gauge_liters=30100.0,
            temperature_c=25.0, certificate_density_kg_per_m3=795.0,
            measured_water_liters=200.0,
        )
        truck = fx.record_receipt(tank["id"], delivery_mode="TRUCK", **measurements)
        pipeline = fx.record_receipt(tank["id"], delivery_mode="PIPELINE", **measurements)

        assert truck["governing_gross_liters"] == pytest.approx(30120.00, abs=0.005)
        assert truck["net_volume_liters"] == pytest.approx(29698.32, abs=0.005)
        assert truck["advisory_net_volume_liters"] == pytest.approx(29580.00, abs=0.005)

        assert pipeline["governing_gross_liters"] == pytest.approx(30000.00, abs=0.005)
        assert pipeline["net_volume_liters"] == pytest.approx(29580.00, abs=0.005)
        assert pipeline["advisory_net_volume_liters"] == pytest.approx(29698.32, abs=0.005)

    def test_recorded_receipt_volumes_are_frozen_and_add_nothing_to_the_tank(self, api):
        """PRD §3.2: "A newly recorded receipt sits in `RECORDED` and has added nothing to any tank."
        PRD §3.2: "the volumes computed on creation are never recomputed, and they are exactly
        what a later release verdict adds to the tank ledger."
        PRD §3.2: "The `advisory_net_volume_liters` repeats the fourth, fifth and sixth steps on
        the advisory gross basis, using the same correction factor and the same measured water
        figure against a cap of one half of one percent of the advisory gross; it exists purely
        for the reconciliation audit trail and never enters the ledger."

        Design: Difficulty/dual_variant_calc/receipt_governing_basis_truck_meter_vs_pipeline_gauge
        """
        env = fx.setup_fuel_farm(permit_overrides={"max_daily_throughput_liters": 400000.0})
        tank = fx.register_tank(env["farm"]["id"], capacity_liters=5_000_000.0,
                                safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                opening_volume_liters=0.0)
        receipt = fx.record_receipt(
            tank["id"], delivery_mode="PIPELINE", meter_ticket_gross_liters=30120.0,
            tank_opening_gauge_liters=100.0, tank_closing_gauge_liters=30100.0,
            temperature_c=25.0, certificate_density_kg_per_m3=795.0,
            measured_water_liters=200.0)

        assert receipt["status"] == "RECORDED"
        assert receipt["advisory_gross_liters"] == pytest.approx(30120.00, abs=0.005)
        assert receipt["net_volume_liters"] == pytest.approx(29580.00, abs=0.005)

        after = validate_success(api.get_storage_tank(tank["id"], fx.ADMIN))
        assert after["book_volume_liters"] == pytest.approx(0.00, abs=0.005), \
            "a RECORDED receipt contributes nothing to the tank ledger"

        # the frozen volumes survive a re-read unchanged
        reread = validate_success(api.get_fuel_receipt(receipt["id"], fx.OPERATOR))
        assert reread["net_volume_liters"] == pytest.approx(29580.00, abs=0.005)
        assert reread["advisory_net_volume_liters"] == pytest.approx(29698.32, abs=0.005)


class TestAirlineExposureTwoBases:
    def test_posted_ticket_raises_accrual_exposure_while_invoiced_stays_zero(self, api):
        """PRD §3.5: "`invoiced_exposure_cents` is the sum, over the account's invoices whose
        `status` is `ISSUED` or `DISPUTED`, of that invoice's `total_cents` less its
        `amount_paid_cents`."
        PRD §3.5: "The **accrual basis** adds two further terms to that figure: the sum of
        `billed_line_cents` over the account's uplift tickets whose `status` is `POSTED`
        (tickets already `BILLED` sit inside an issued invoice and would double-count; `VOIDED`
        tickets are excluded), plus the sum of `reserved_amount_cents` over the account's orders
        whose `status` is `AUTHORIZED`, `ASSIGNED` or `FUELING`."

        Design: Difficulty/dual_variant_calc/airline_exposure_accrual_basis_vs_invoiced_basis
        """
        env = fx.setup_completed_order(
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000,
                               "tax_exempt": False})

        uplift = validate_success(api.get_uplift_record(env["uplift"]["id"], fx.AGENT))
        assert uplift["net_liters"] == pytest.approx(20000.00, abs=0.005)
        assert uplift["billed_line_cents"] == 1433393
        assert uplift["status"] == "POSTED"

        account = validate_success(api.get_airline_account(env["account"]["id"], fx.BILLING))
        assert account["accrual_exposure_cents"] == 1433393
        assert account["invoiced_exposure_cents"] == 0, \
            "no invoice exists, so the invoiced basis counts nothing"
        assert validate_success(
            api.get_fueling_order(env["order"]["id"], fx.AGENT))["status"] == "COMPLETED"

    def test_accrual_basis_carries_reservation_and_posted_ticket_together(self, api):
        """PRD §3.5: "The **accrual basis** adds two further terms to that figure: the sum of
        `billed_line_cents` over the account's uplift tickets whose `status` is `POSTED`
        (tickets already `BILLED` sit inside an issued invoice and would double-count; `VOIDED`
        tickets are excluded), plus the sum of `reserved_amount_cents` over the account's orders
        whose `status` is `AUTHORIZED`, `ASSIGNED` or `FUELING`."
        PRD §3.5: "The reservation term for a single order is computed once, at authorization
        time, and is the sum of two components: the requested volume multiplied by the account's
        `base_price_cents_per_liter` plus the applicable tier differential, rounded half up to
        whole cents; plus an into-plane handling component that is the larger of 2,500 cents and
        the requested volume multiplied by 0.45 cents per liter rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/airline_exposure_accrual_basis_vs_invoiced_basis
        """
        env = fx.setup_fueling_order_with_uplift(
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000,
                               "tax_exempt": False})

        order = validate_success(api.get_fueling_order(env["order"]["id"], fx.AGENT))
        assert order["status"] == "FUELING"
        assert order["reserved_amount_cents"] == 1313000

        account = validate_success(api.get_airline_account(env["account"]["id"], fx.BILLING))
        assert account["accrual_exposure_cents"] == 1433393 + 1313000, \
            "the accrual basis carries both the POSTED ticket and the open reservation"
        assert account["invoiced_exposure_cents"] == 0


class TestReconciliationVarianceDenominators:
    @staticmethod
    def _measured_run(api):
        env = fx.setup_completed_order(
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000})
        fx.make_released_receipt(
            env["tank"]["id"], delivery_mode="TRUCK", meter_ticket_gross_liters=30120.0,
            tank_opening_gauge_liters=100.0, tank_closing_gauge_liters=30100.0,
            temperature_c=25.0, certificate_density_kg_per_m3=795.0,
            measured_water_liters=200.0)
        tank_before = validate_success(api.get_storage_tank(env["tank"]["id"], fx.ADMIN))
        assert tank_before["book_volume_liters"] == pytest.approx(1009698.32, abs=0.005)

        run = fx.open_reconciliation_run(env["farm"]["id"], "2026-08-10T00:00:00Z",
                                        "2026-08-11T00:00:00Z")
        fx.set_clock("2026-08-11T01:00:00Z")
        measured = fx.measure_reconciliation_run(
            run["id"], [{"storage_tank_id": env["tank"]["id"],
                         "measured_volume_liters": 1009400.0, "temperature_c": 15.0}])
        return env, measured

    def test_governing_throughput_basis_holds_run_while_advisory_basis_looks_clean(self, api):
        """PRD §3.9: "Two variance percentages are then reported side by side, each the absolute
        variance divided by its denominator and multiplied by one hundred, rounded half up to
        four decimals, and in each case the denominator is taken as the larger of the computed
        denominator and 1.0 so that a dead-quiet period cannot divide by zero."
        PRD §3.9: "`variance_pct_throughput_basis` uses the throughput denominator and is the
        **governing** figure; `variance_pct_opening_stock_basis` uses the derived opening stock
        and is advisory, reported for the auditor."
        PRD §3.9: "The run auto-transitions `MEASURED → VARIANCE_HOLD` on the same request that
        computed the variance when the governing percentage is **strictly greater than** 0.50
        percent; a run sitting at exactly 0.5000 percent does not hold and posts clean."

        Design: Difficulty/dual_variant_calc/reconciliation_variance_throughput_basis_vs_opening_stock_basis
        """
        env, measured = self._measured_run(api)

        assert measured["variance_liters"] == pytest.approx(-298.32, abs=0.005)
        assert measured["variance_pct_throughput_basis"] == pytest.approx(0.6003, abs=0.00005)
        assert measured["variance_pct_opening_stock_basis"] == pytest.approx(0.0298, abs=0.00005)
        assert measured["status"] == "VARIANCE_HOLD", \
            "0.6003 percent on the governing basis is strictly greater than 0.50 percent"

    def test_period_movement_totals_feed_the_throughput_denominator(self, api):
        """PRD §3.9: "`receipts_net_liters` is the sum of `net_volume_liters` over receipts at
        the farm whose `status` is `RELEASED` and whose `released_at_utc` falls at or after the
        period start and strictly before the period end, and `uplifts_net_liters` is the sum of
        `net_liters` over tickets drawn from the farm's tanks whose `status` is `POSTED` or
        `BILLED` and whose `created_at` falls in the same half-open window."
        PRD §3.9: "Their sum, rounded half up to two decimals, is `throughput_liters`, the
        governing variance denominator."
        PRD §3.9: "Measuring also writes `last_gauge_volume_liters` and `last_gauge_at_utc` onto
        each measured tank and raises the run's `version` and each measured tank's `version` by
        one; the hold transition raises the run's `version` again."

        Design: Difficulty/dual_variant_calc/reconciliation_variance_throughput_basis_vs_opening_stock_basis
        """
        env, measured = self._measured_run(api)

        assert measured["receipts_net_liters"] == pytest.approx(29698.32, abs=0.005)
        assert measured["uplifts_net_liters"] == pytest.approx(20000.00, abs=0.005)
        assert measured["throughput_liters"] == pytest.approx(49698.32, abs=0.005)

        tank = validate_success(api.get_storage_tank(env["tank"]["id"], fx.ADMIN))
        assert tank["last_gauge_volume_liters"] == pytest.approx(1009400.0, abs=0.005)
        assert tank["last_gauge_at_utc"] is not None, \
            "measuring stamps last_gauge_at_utc from the logical clock"
