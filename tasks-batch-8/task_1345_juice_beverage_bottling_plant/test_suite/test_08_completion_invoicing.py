"""Run completion: yield accounting, giveaway, case-floor billing, invoicing."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, factories,
    create_customer, create_formula, create_tank, create_line,
    create_container_lot, create_zone, create_released_batch, quote_run,
    confirm_run, schedule_run, set_clock, setup_scheduled_run,
    setup_completed_run, get_finished_lot_for_run,
)

# Module-level alias of the session-scoped `api` fixture (conftest returns
# the same object) so module/class helpers can call the client without
# declaring the fixture parameter.
api = api_client


PM = TEST_USERS["plant_manager_headers"]
FIN = TEST_USERS["finance_clerk_headers"]
PLAN = TEST_USERS["production_planner_headers"]


class TestCaseFloorRoundingOrder:
    def test_billable_units_case_floored_before_pricing(self, api):
        """PRD §3.8: "Billing is case-floored: `billable_units` is
        `actual_units_filled` divided by twelve with the remainder discarded —
        whole cases of twelve — then multiplied back by twelve, and this
        floor-then-scale order is pinned; summing first and rounding later is not
        an equivalent computation." and "The provisional invoice is
        `billable_units` multiplied by `unit_price_cents`, posted into
        `provisional_invoice_cents` at completion."

        Design: Difficulty/combinatorial_formula/case_floor_before_invoice_rounding_order
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=473)
        run = ctx["run"]
        assert run["billable_units"] == 996  # (1000 // 12) * 12, not 1000
        assert run["provisional_invoice_cents"] == 149_400  # 996 * 150, not 150000

    def test_theoretical_units_and_zero_giveaway(self, api):
        """PRD §3.7: "computes `theoretical_units` as the whole containers
        obtainable from the batch — the batch's `processed_liters` converted to
        milliliters, divided by the formula's `container_fill_ml`, rounded down"
        and §3.8: "Giveaway — product given away by overfilling — is the excess of
        `avg_fill_ml` over the formula's `container_fill_ml`, floored at zero when
        the filler underfills"

        Design: Difficulty/combinatorial_formula/case_floor_before_invoice_rounding_order
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=473)
        run = ctx["run"]
        # processed 1960.0 L (2000 L - 2% loss); floor(1960.0 * 1000 / 473) == 4143
        assert run["theoretical_units"] == 4143
        assert run["giveaway_liters"] == pytest.approx(0.0, abs=0.01)


class TestProvisionalVsFinalInvoice:
    def test_provisional_invoice_at_completion(self, api):
        """PRD §3.8: "The provisional invoice is `billable_units` multiplied by
        `unit_price_cents`, posted into `provisional_invoice_cents` at completion."
        and "flips the invoice dimension from `NOT_INVOICED` to `PROVISIONAL`, and
        adds `provisional_invoice_cents` to the customer's
        `outstanding_balance_cents`."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_diverge
        """
        # avg_fill 476 vs nominal 473 -> giveaway (476-473)*1000/1000 == 3.0 L
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=476)
        run = ctx["run"]
        assert run["giveaway_liters"] == pytest.approx(3.0, abs=0.01)
        assert run["billable_units"] == 996
        assert run["provisional_invoice_cents"] == 149_400
        assert run["invoice_status"] == "PROVISIONAL"
        assert run["production_status"] == "COMPLETED"
        customer = get_success_data(api.get_customer(ctx["customer"]["id"], PM))
        assert customer["outstanding_balance_cents"] == 149_400

    def test_final_invoice_deducts_giveaway(self, api):
        """PRD §3.8: "The final invoice subtracts the giveaway deduction —
        `giveaway_liters` multiplied by 140 cents per liter, rounded half up to a
        whole cent — from `provisional_invoice_cents`, and the ledger receives
        only the delta: `outstanding_balance_cents` moves by the difference
        between `final_invoice_cents` and `provisional_invoice_cents`."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_diverge
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=476)
        finalized = get_success_data(api.finalize_invoice(ctx["run"]["id"], FIN))
        # 149400 - round_half_up(3.0 * 140) == 148980
        assert finalized["final_invoice_cents"] == 148_980
        assert finalized["invoice_status"] == "FINAL"
        assert finalized["production_status"] == "COMPLETED"
        customer = get_success_data(api.get_customer(ctx["customer"]["id"], PM))
        assert customer["outstanding_balance_cents"] == 148_980


class TestInvoiceEvaluationOrder:
    def test_ledger_posts_provisional_then_delta_only(self, api):
        """PRD §3.8: "The final invoice subtracts the giveaway deduction —
        `giveaway_liters` multiplied by 140 cents per liter, rounded half up to a
        whole cent — from `provisional_invoice_cents`, and the ledger receives
        only the delta: `outstanding_balance_cents` moves by the difference
        between `final_invoice_cents` and `provisional_invoice_cents`."

        Design: Difficulty/combinatorial_formula/invoice_evaluation_order_circular_pin
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=476)
        mid = get_success_data(api.get_customer(ctx["customer"]["id"], PM))
        assert mid["outstanding_balance_cents"] == 149_400  # provisional posted
        finalized = get_success_data(api.finalize_invoice(ctx["run"]["id"], FIN))
        assert finalized["final_invoice_cents"] == 148_980
        end = get_success_data(api.get_customer(ctx["customer"]["id"], PM))
        # only the -420 delta was posted: NOT 149400 + 148980
        assert end["outstanding_balance_cents"] == 148_980

    def test_run_pallet_count_single_ceiling(self, api):
        """PRD §3.8: "The run's `pallet_count` is `actual_units_filled` divided by
        the pallet density of its container type, rounded up: a pallet holds 2,016
        units of `GLASS_355`, 1,440 of `PET_473`, 960 of `PET_1000`, or 2,880 of
        `CAN_330`."

        Design: Difficulty/combinatorial_formula/invoice_evaluation_order_circular_pin
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=476)
        assert ctx["run"]["pallet_count"] == 1  # ceil(1000 / 1440)
        finalized = get_success_data(api.finalize_invoice(ctx["run"]["id"], FIN))
        assert finalized["invoice_status"] == "FINAL"


class TestParallelInvoiceDimension:
    def test_completion_engages_invoice_axis_only(self, api):
        """PRD §3.8: "The two dimensions of a run evolve independently after
        completion: a run is done producing long before its invoice is final."

        Design: Difficulty/non_linear_state_machine/production_run_parallel_invoice_dimension
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=473)
        run = ctx["run"]
        assert run["production_status"] == "COMPLETED"
        assert run["invoice_status"] == "PROVISIONAL"
        finalized = get_success_data(api.finalize_invoice(run["id"], FIN))
        assert finalized["invoice_status"] == "FINAL"
        assert finalized["production_status"] == "COMPLETED"

    def test_cancelled_run_stays_not_invoiced(self, api):
        """PRD §3.7: "Cancellation compensates in full: container reservations are
        released, the line window is freed, the batch link is cleared while the
        batch itself remains `RELEASED`, and nothing is ever invoiced — the
        invoice dimension stays `NOT_INVOICED`."

        Design: Difficulty/non_linear_state_machine/production_run_parallel_invoice_dimension
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=473)
        run2 = quote_run(ctx["customer"]["id"], ctx["formula"]["id"], planned_units=600)
        cancelled = get_success_data(api.cancel_run(run2["id"], PLAN))
        assert cancelled["production_status"] == "CANCELLED"
        assert cancelled["invoice_status"] == "NOT_INVOICED"


class TestCompleteGates:
    def _in_production_run_with_zones(self):
        ctx = setup_scheduled_run()
        zone_frozen = create_zone(temperature_class="FROZEN")
        set_clock("2026-08-11T09:00:00Z")
        ctx["run"] = get_success_data(api.start_run(ctx["run"]["id"], PLAN))
        ctx["zone_frozen"] = zone_frozen
        return ctx

    def test_fill_count_bounds(self, api):
        """PRD §3.8: "The fill count must be at least one and no more than the
        smaller of `theoretical_units` and the reserved ceiling — the planned
        count inflated by five percent and rounded up — else the report is refused
        with `ERR_FILL_COUNT_EXCEEDS_THEORETICAL`."

        Design: Corner/endpoints/complete_fill_count_and_zone_gates
        """
        ctx = self._in_production_run_with_zones()
        rid = ctx["run"]["id"]
        # below the lower bound
        resp = api.complete_run(
            rid, factories.complete_run_payload(
                ctx["zone"]["id"], actual_units_filled=0, avg_fill_ml=473), PLAN)
        validate_error(resp, ApiErrorId.ERR_FILL_COUNT_EXCEEDS_THEORETICAL)
        assert resp.status_code == 422
        # above the reserved ceiling: 1051 > min(4143, ceil(1000 * 1.05)) == 1050
        resp = api.complete_run(
            rid, factories.complete_run_payload(
                ctx["zone"]["id"], actual_units_filled=1051, avg_fill_ml=473), PLAN)
        validate_error(resp, ApiErrorId.ERR_FILL_COUNT_EXCEEDS_THEORETICAL)
        assert get_success_data(api.get_production_run(rid, PM))["production_status"] == "IN_PRODUCTION"

    def test_frozen_zone_rejected_then_retry_succeeds(self, api):
        """PRD §3.9: "high-pressure product requires a `CHILLED` zone, pasteurized
        product may land in `AMBIENT` or `CHILLED`, and `FROZEN` is never
        acceptable — a mismatch is refused with `ERR_ZONE_TEMPERATURE_MISMATCH`."

        Design: Corner/endpoints/complete_fill_count_and_zone_gates
        """
        ctx = self._in_production_run_with_zones()
        rid = ctx["run"]["id"]
        resp = api.complete_run(
            rid, factories.complete_run_payload(
                ctx["zone_frozen"]["id"], actual_units_filled=1000, avg_fill_ml=473), PLAN)
        validate_error(resp, ApiErrorId.ERR_ZONE_TEMPERATURE_MISMATCH)
        assert resp.status_code == 422
        completed = get_success_data(api.complete_run(
            rid, factories.complete_run_payload(
                ctx["zone"]["id"], actual_units_filled=1000, avg_fill_ml=473), PLAN))
        assert completed["production_status"] == "COMPLETED"
        # the failed completes created no finished lots
        lots = get_success_data(api.list_run_finished_lots(rid, PM))
        assert isinstance(lots, list) and len(lots) == 1


class TestHppZoneTemperature:
    def test_hpp_requires_chilled_zone(self, api):
        """PRD §3.9: "high-pressure product requires a `CHILLED` zone, pasteurized
        product may land in `AMBIENT` or `CHILLED`, and `FROZEN` is never
        acceptable — a mismatch is refused with `ERR_ZONE_TEMPERATURE_MISMATCH`."

        Design: Corner/endpoints/hpp_zone_temperature_rule
        """
        ctx = setup_scheduled_run(
            formula_overrides={"process_type": "HPP", "target_brix": 8.0,
                               "concentrate_brix": 60.0, "claims": ["COLD_PRESSED"]},
            zone_temperature="CHILLED")
        zone_ambient = create_zone(temperature_class="AMBIENT")
        set_clock("2026-08-11T09:00:00Z")
        get_success_data(api.start_run(ctx["run"]["id"], PLAN))
        resp = api.complete_run(
            ctx["run"]["id"],
            factories.complete_run_payload(zone_ambient["id"]), PLAN)
        validate_error(resp, ApiErrorId.ERR_ZONE_TEMPERATURE_MISMATCH)
        assert resp.status_code == 422
        completed = get_success_data(api.complete_run(
            ctx["run"]["id"],
            factories.complete_run_payload(ctx["zone"]["id"]), PLAN))
        assert completed["production_status"] == "COMPLETED"


class TestZoneCapacityBoundary:
    def _two_runs_one_tiny_zone(self):
        """Two scheduled runs (windows 08:00-12:00 and 13:00-17:00) and a zone
        with pallet_capacity 1."""
        customer = create_customer()
        formula = create_formula(customer["id"])
        tank1 = create_tank()
        batch1 = create_released_batch(formula, tank1)
        tank2 = create_tank()
        batch2 = create_released_batch(formula, tank2)
        line = create_line()
        create_container_lot()
        zone = create_zone(pallet_capacity=1)
        run1 = confirm_run(quote_run(customer["id"], formula["id"])["id"])
        run1 = schedule_run(run1["id"], batch1["id"], line["id"],
                            "2026-08-11T08:00:00Z", "2026-08-11T12:00:00Z")
        run2 = confirm_run(quote_run(customer["id"], formula["id"])["id"])
        run2 = schedule_run(run2["id"], batch2["id"], line["id"],
                            "2026-08-11T13:00:00Z", "2026-08-11T17:00:00Z")
        return {"zone": zone, "run1": run1, "run2": run2}

    def test_zone_filled_exactly_to_capacity_accepted(self, api):
        """PRD §3.9: "the zone's current `pallets_stored` plus the incoming run's
        `pallet_count` must not exceed `pallet_capacity`, with a zone filled
        exactly to capacity still acceptable"

        Design: Difficulty/boundary_precision_check/zone_capacity_equality_boundary
        """
        ctx = self._two_runs_one_tiny_zone()
        set_clock("2026-08-11T09:00:00Z")
        get_success_data(api.start_run(ctx["run1"]["id"], PLAN))
        completed = get_success_data(api.complete_run(
            ctx["run1"]["id"],
            factories.complete_run_payload(ctx["zone"]["id"]), PLAN))
        assert completed["production_status"] == "COMPLETED"
        assert completed["pallet_count"] == 1  # ceil(1000 / 1440)
        zone = get_success_data(api.get_zone(ctx["zone"]["id"], PM))
        assert zone["pallets_stored"] == 1  # == pallet_capacity, inclusive OK

    def test_one_pallet_over_capacity_rejected(self, api):
        """PRD §3.9: "with a zone filled exactly to capacity still acceptable, and
        an overflow refused with `ERR_ZONE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/zone_capacity_equality_boundary
        """
        ctx = self._two_runs_one_tiny_zone()
        set_clock("2026-08-11T09:00:00Z")
        get_success_data(api.start_run(ctx["run1"]["id"], PLAN))
        get_success_data(api.complete_run(
            ctx["run1"]["id"],
            factories.complete_run_payload(ctx["zone"]["id"]), PLAN))
        set_clock("2026-08-11T14:00:00Z")
        get_success_data(api.start_run(ctx["run2"]["id"], PLAN))
        # 1 stored + 1 new > capacity 1
        resp = api.complete_run(
            ctx["run2"]["id"],
            factories.complete_run_payload(ctx["zone"]["id"]), PLAN)
        validate_error(resp, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED)
        assert resp.status_code == 409
        run2 = get_success_data(api.get_production_run(ctx["run2"]["id"], PM))
        assert run2["production_status"] == "IN_PRODUCTION"
        lots = get_success_data(api.list_run_finished_lots(ctx["run2"]["id"], PM))
        assert lots == []
