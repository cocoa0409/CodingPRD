"""Inclusive and strict thresholds exercised exactly on the line: 90 percent permit utilisation,
a reconciliation variance of exactly 0.5000 percent, and two aggregations at cardinality zero."""
import pytest

from test_helpers import (
    assert_same_instant,
    validate_success, validate_error, validate_paginated, ApiErrorId, fixtures as fx,
)


def _farm_with_tight_permit():
    env = fx.setup_fuel_farm(permit_overrides={"max_daily_throughput_liters": 33000.0,
                                               "max_reportable_spill_liters": 20.0})
    fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                      turnaround_buffer_minutes=15, differential_pressure_kpa=10.0)
    env["tank"] = fx.make_released_tank(
        env["farm"]["id"], capacity_liters=5_000_000.0, safe_fill_liters=4_000_000.0,
        density_kg_per_m3=795.0, opening_volume_liters=0.0)
    return env


class TestPermitUtilisationBoundary:
    def test_exactly_ninety_percent_of_the_permit_day_restricts_the_farm(self, api):
        """PRD §2.7: "Third, the farm is **restricted** if any of four conditions holds: at least one
        storage tank at the farm has `quality_status` `QUARANTINED`; at least one spill incident at
        the farm has `status` `REPORTED`; the farm's `active_permit_throughput_used_liters` has
        reached or exceeded 90 percent of the governing permit's `max_daily_throughput_liters`; or the
        farm's `in_service_asset_count` is zero."
        PRD §2.7: "Note the ordering consequence: a frozen farm stays `FROZEN` regardless of how many
        restricted conditions also hold, and the 90-percent utilisation comparison is inclusive — a
        farm sitting at exactly 90.00 percent of its permitted daily throughput is `RESTRICTED`, not
        `OPEN`."
        PRD §3.3: "On success the receipt's `released_at_utc` is stamped from the logical clock and
        its `released_by_user_id` from the acting identifier; the receipt's net volume enters the tank
        ledger, which recomputes the tank's `book_volume_liters`, `reserved_volume_liters` and
        `available_volume_liters`; the farm's permit-day throughput counter is recomputed; and the
        farm's posture is recomputed, which may land on `RESTRICTED` the moment permit utilisation
        reaches the 90 percent boundary."

        Design: Difficulty/boundary_precision_check/permit_utilisation_exactly_ninety_percent_restricts_the_farm
        """
        env = _farm_with_tight_permit()
        before = fx.read_farm(env["farm"]["id"])
        assert before["posture"] == "OPEN"
        assert before["active_permit_throughput_used_liters"] == pytest.approx(0.00, abs=0.005)

        receipt = fx.make_released_receipt(
            env["tank"]["id"], metrics={"particulate_mg_per_l": 0.4,
                                        "conductivity_ps_per_m": 150.0, "flash_point_c": 41.0},
            delivery_mode="PIPELINE", supplier_name="Refinery One",
            meter_ticket_gross_liters=29800.0, tank_opening_gauge_liters=0.0,
            tank_closing_gauge_liters=29700.0, temperature_c=15.0,
            certificate_density_kg_per_m3=795.0, measured_water_liters=0.0)
        assert receipt["net_volume_liters"] == pytest.approx(29700.00, abs=0.005)
        assert receipt["status"] == "RELEASED"
        assert_same_instant(receipt["released_at_utc"], "2026-08-10T06:00:00Z",
                            "released_at_utc")

        farm = fx.read_farm(env["farm"]["id"])
        assert farm["active_permit_throughput_used_liters"] == pytest.approx(29700.00, abs=0.005)
        assert farm["posture"] == "RESTRICTED", \
            "29700.00 liters is exactly 90 percent of the 33000.0-liter permit day"

        tank = fx.read_tank(env["tank"]["id"])
        assert tank["book_volume_liters"] == pytest.approx(29700.00, abs=0.005)
        assert tank["available_volume_liters"] == pytest.approx(29200.00, abs=0.005)

    def test_one_hundredth_of_a_liter_below_the_boundary_leaves_the_farm_open(self, api):
        """PRD §2.7: "Note the ordering consequence: a frozen farm stays `FROZEN` regardless of how
        many restricted conditions also hold, and the 90-percent utilisation comparison is inclusive —
        a farm sitting at exactly 90.00 percent of its permitted daily throughput is `RESTRICTED`, not
        `OPEN`."
        PRD §2.7: "The resulting posture is `FROZEN` when the frozen condition holds, otherwise
        `RESTRICTED` when any restricted condition holds, otherwise `OPEN`."

        Design: Difficulty/boundary_precision_check/permit_utilisation_exactly_ninety_percent_restricts_the_farm
        """
        env = _farm_with_tight_permit()
        receipt = fx.make_released_receipt(
            env["tank"]["id"], metrics={"particulate_mg_per_l": 0.4,
                                        "conductivity_ps_per_m": 150.0, "flash_point_c": 41.0},
            delivery_mode="PIPELINE", supplier_name="Refinery One",
            meter_ticket_gross_liters=29800.0, tank_opening_gauge_liters=0.0,
            tank_closing_gauge_liters=29699.99, temperature_c=15.0,
            certificate_density_kg_per_m3=795.0, measured_water_liters=0.0)
        assert receipt["net_volume_liters"] == pytest.approx(29699.99, abs=0.005)

        farm = fx.read_farm(env["farm"]["id"])
        assert farm["active_permit_throughput_used_liters"] == pytest.approx(29699.99, abs=0.005)
        assert farm["posture"] == "OPEN", \
            "one hundredth of a liter short of 90 percent is not yet a restriction"


class TestVarianceExactlyAtTolerance:
    @staticmethod
    def _run_measured_at_the_tolerance():
        env = fx.setup_completed_order(
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000})
        fx.make_released_receipt(
            env["tank"]["id"], delivery_mode="TRUCK", meter_ticket_gross_liters=30120.0,
            tank_opening_gauge_liters=100.0, tank_closing_gauge_liters=30100.0,
            temperature_c=25.0, certificate_density_kg_per_m3=795.0,
            measured_water_liters=200.0)
        run = fx.open_reconciliation_run(env["farm"]["id"], "2026-08-10T00:00:00Z",
                                         "2026-08-11T00:00:00Z")
        fx.set_clock("2026-08-11T01:00:00Z")
        env["run"] = fx.measure_reconciliation_run(
            run["id"], [{"storage_tank_id": env["tank"]["id"],
                         "measured_volume_liters": 1009449.83, "temperature_c": 15.0}])
        return env

    def test_a_variance_of_exactly_half_a_percent_does_not_hold_the_run(self, api):
        """PRD §3.9: "The run auto-transitions `MEASURED → VARIANCE_HOLD` on the same request that
        computed the variance when the governing percentage is **strictly greater than** 0.50
        percent; a run sitting at exactly 0.5000 percent does not hold and posts clean."
        PRD §3.9: "Two variance percentages are then reported side by side, each the absolute variance
        divided by its denominator and multiplied by one hundred, rounded half up to four decimals,
        and in each case the denominator is taken as the larger of the computed denominator and 1.0 so
        that a dead-quiet period cannot divide by zero."
        PRD §3.9: "Their sum, rounded half up to two decimals, is `throughput_liters`, the governing
        variance denominator."

        Design: Difficulty/boundary_precision_check/reconciliation_variance_exactly_at_tolerance_posts_without_override
        """
        env = self._run_measured_at_the_tolerance()
        run = env["run"]

        assert run["throughput_liters"] == pytest.approx(49698.32, abs=0.005)
        assert run["variance_liters"] == pytest.approx(-248.49, abs=0.005)
        assert run["variance_pct_throughput_basis"] == pytest.approx(0.5000, abs=0.00005)
        assert run["status"] == "MEASURED", \
            "the hold guard is strictly greater than 0.50 percent"

    def test_the_run_posts_without_a_variance_override_reason(self, api):
        """PRD §3.9: "From `MEASURED` it needs nothing further; from `VARIANCE_HOLD` it needs a
        non-empty `variance_override_reason` in the payload, and posting a held run without one is
        rejected with `ERR_VARIANCE_OVERRIDE_REQUIRED`."
        PRD §3.9: "Posting writes the signed per-tank variance into the ledger as that tank's
        `adjustment_liters`, with the effect that each measured tank's `book_volume_liters` afterwards
        equals its corrected measured volume exactly."
        PRD §3.9: "Measuring also writes `last_gauge_volume_liters` and `last_gauge_at_utc` onto each
        measured tank and raises the run's `version` and each measured tank's `version` by one; the
        hold transition raises the run's `version` again."

        Design: Difficulty/boundary_precision_check/reconciliation_variance_exactly_at_tolerance_posts_without_override
        """
        env = self._run_measured_at_the_tolerance()
        posted = validate_success(api.post_reconciliation_run(env["run"]["id"], fx.ADMIN))

        assert posted["status"] == "POSTED"
        assert posted["adjustment_liters"] == pytest.approx(-248.49, abs=0.005)

        tank = fx.read_tank(env["tank"]["id"])
        assert tank["book_volume_liters"] == pytest.approx(1009449.83, abs=0.005)
        assert tank["last_gauge_volume_liters"] == pytest.approx(1009449.83, abs=0.005)
        assert_same_instant(tank["last_gauge_at_utc"], "2026-08-11T01:00:00Z",
                            "last_gauge_at_utc")


class TestEmptyAggregateSets:
    @staticmethod
    def _fuelling_order_without_tickets():
        return fx.setup_truck_order(
            target_state="FUELING", requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000, "tax_exempt": False},
            permit_overrides={"max_daily_throughput_liters": 400000.0})

    def test_completion_refuses_an_order_with_no_posted_ticket(self, api):
        """PRD §3.6: "**Completion**, `FUELING → COMPLETED`, requires at least one `POSTED` ticket on
        the order (otherwise `ERR_NO_UPLIFT_RECORDED`) and requires the order's `posted_net_liters` to
        be at most the authorization's `max_authorized_liters` — with **no tolerance at all** at this
        gate, in contrast to the five percent allowed when posting."
        PRD §3.5: "It is `REDEEMED` by the system when an order completes against it, subject to that
        order's `posted_net_liters` not exceeding the authorization's `max_authorized_liters`."

        Design: Difficulty/boundary_precision_check/empty_aggregate_sets_block_completion_and_invoice_sweep
        """
        env = self._fuelling_order_without_tickets()

        validate_error(api.complete_order(env["order"]["id"], fx.AGENT),
                       ApiErrorId.ERR_NO_UPLIFT_RECORDED, 409)

        order = fx.read_order(env["order"]["id"])
        assert order["status"] == "FUELING"
        assert order["posted_net_liters"] == pytest.approx(0.00, abs=0.005)
        assert fx.read_authorization(env["auth"]["id"])["status"] == "ISSUED", \
            "a refused completion does not redeem the authorization"

    def test_an_empty_sweep_refuses_to_create_a_zero_total_draft(self, api):
        """PRD §3.9: "If the sweep finds nothing, the create is rejected with
        `ERR_NOTHING_TO_SWEEP`."
        PRD §3.9: "The sweep collects the uplift tickets belonging to that airline account — reached
        from each ticket's `fueling_order_id` through the order's flight to the account — whose
        `status` is `POSTED`, whose `invoice_id` is still null, and whose `created_at` falls at or
        after the period start and strictly before the period end, taken in `created_at` ascending
        order."
        PRD §3.5: "The **accrual basis** adds two further terms to that figure: the sum of
        `billed_line_cents` over the account's uplift tickets whose `status` is `POSTED` (tickets
        already `BILLED` sit inside an issued invoice and would double-count; `VOIDED` tickets are
        excluded), plus the sum of `reserved_amount_cents` over the account's orders whose `status` is
        `AUTHORIZED`, `ASSIGNED` or `FUELING`."

        Design: Difficulty/boundary_precision_check/empty_aggregate_sets_block_completion_and_invoice_sweep
        """
        env = self._fuelling_order_without_tickets()
        fx.set_clock("2026-08-11T01:00:00Z")
        account = fx.read_account(env["account"]["id"])

        payload = {"airline_account_id": account["id"],
                   "period_start_utc": "2026-08-10T00:00:00Z",
                   "period_end_utc": "2026-08-11T00:00:00Z",
                   "expected_airline_account_version": account["version"]}
        validate_error(api.create_invoice(payload, fx.BILLING),
                       ApiErrorId.ERR_NOTHING_TO_SWEEP, 422)

        data, _meta = validate_paginated(api.list_invoices(
            fx.BILLING, {"airline_account_id": account["id"]}))
        assert data == [], "the refused sweep left no invoice row behind"

        after = fx.read_account(account["id"])
        assert after["invoiced_exposure_cents"] == 0
        assert after["accrual_exposure_cents"] == 1313000, \
            "only the open reservation stands on the accrual basis"

        tank = fx.read_tank(env["tank"]["id"])
        assert tank["book_volume_liters"] == pytest.approx(1000000.00, abs=0.005)
        assert tank["reserved_volume_liters"] == pytest.approx(20000.00, abs=0.005)
