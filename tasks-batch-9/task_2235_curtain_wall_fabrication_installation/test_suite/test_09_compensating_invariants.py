"""Two compensating actions that must recompute derived state rather than
decrement it: cancelling a breakage draw and voiding a crew day."""
import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_crew_hour_ledger,
    assert_day_cost_sum_equals_final,
    assert_day_indices_packed,
    assert_glass_lite_ledger,
)
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["cw_project_manager_headers"]
PROCUREMENT = TEST_USERS["glazing_procurement_headers"]
SUPERINTENDENT = TEST_USERS["field_superintendent_headers"]


class TestBreakageDrawCancellationRestoresConservation:
    """The reserve is recomputed from the surviving DRAWN rows."""

    @staticmethod
    def _order_with_its_reserve_fully_drawn():
        ctx = fx.setup_released_zone(ordered_lites=240)
        lot = ctx["lots"][ctx["zone_ids"][0]][0]
        first = fx.create_breakage_draw(ctx, lot["id"], 3)
        second = fx.create_breakage_draw(ctx, lot["id"], 4)
        return ctx, lot, first, second

    @staticmethod
    def _draw(ctx, lot_id, quantity_lites):
        version = fx.refresh_glass_order(ctx)["version"]
        return api_client.create_breakage_draw(
            f.create_breakage_draw_payload(
                ctx["glass_order_id"], lot_id, quantity_lites, version
            ),
            PROCUREMENT,
        )

    def test_two_draws_summing_to_the_reserve_leave_nothing_drawable(self):
        """Three lites plus four lites exactly consume the seven-lite reserve, so
        one further lite is refused while the allocation side of the ledger never
        moves.

        PRD: "`drawn_lites` is the sum of `quantity_lites` over the order's breakage draws whose `status` is `DRAWN`; `available_stock_lites` is `breakage_stock_lites` less `drawn_lites`."

        Design: Difficulty/compensating_invariant/breakage_draw_cancellation_restores_lite_conservation
        """
        ctx, lot, first, second = self._order_with_its_reserve_fully_drawn()
        assert first["status"] == "DRAWN"
        assert second["status"] == "DRAWN"

        order = fx.refresh_glass_order(ctx)
        assert order["breakage_stock_lites"] == 7
        assert order["drawn_lites"] == 7
        assert order["available_stock_lites"] == 0
        assert order["allocated_lites"] == 72
        assert order["unallocated_lites"] == 161
        assert_glass_lite_ledger(order)

        refused = self._draw(ctx, lot["id"], 1)
        validate_error(
            refused, ApiErrorId.ERR_BREAKAGE_STOCK_EXHAUSTED.value, expected_status=422
        )
        assert_glass_lite_ledger(fx.refresh_glass_order(ctx))

    def test_cancelling_one_draw_frees_exactly_its_quantity_for_a_fresh_draw(self):
        """Cancelling the three-lite draw recomputes the balances rather than
        deleting the row, so exactly three lites become drawable again and the
        conservation identity survives all five writes with no drift.

        PRD: "It moves the draw `DRAWN` → `CANCELLED`, stores the free-text `cancelled_reason` from the payload, and recomputes the order's `drawn_lites` and `available_stock_lites` so that `breakage_stock_lites` equals `available_stock_lites` plus `drawn_lites` again with no drift whatsoever."

        Design: Difficulty/compensating_invariant/breakage_draw_cancellation_restores_lite_conservation
        """
        ctx, lot, first, second = self._order_with_its_reserve_fully_drawn()
        self._draw(ctx, lot["id"], 1)
        before_cancel_version = fx.refresh_glass_order(ctx)["version"]

        cancelled = validate_success(
            api_client.cancel_breakage_draw(
                first["id"],
                f.cancel_breakage_draw_payload("lite recovered undamaged"),
                PROCUREMENT,
            ),
            expected_status=200,
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancelled_reason"] == "lite recovered undamaged"

        freed = fx.refresh_glass_order(ctx)
        assert freed["breakage_stock_lites"] == 7
        assert freed["drawn_lites"] == 4
        assert freed["available_stock_lites"] == 3
        assert freed["version"] == before_cancel_version + 1
        assert_glass_lite_ledger(freed)

        third = validate_success(self._draw(ctx, lot["id"], 3), expected_status=201)
        assert third["status"] == "DRAWN"

        restored = fx.refresh_glass_order(ctx)
        assert restored["drawn_lites"] == 7
        assert restored["available_stock_lites"] == 0
        assert restored["breakage_stock_lites"] == 7
        assert restored["allocated_lites"] == 72
        assert restored["unallocated_lites"] == 161
        assert_glass_lite_ledger(restored)

        rows = get_success_data(
            api_client.list_breakage_draws(
                PROCUREMENT, params={"glass_order_id": ctx["glass_order_id"]}
            )
        )
        assert len(rows) == 3
        assert sorted(row["status"] for row in rows) == ["CANCELLED", "DRAWN", "DRAWN"]


class TestCrewDayVoidRestoresThreeDerivedStructures:
    """One void must undo the hour ledger, the index packing and the actual
    cost together."""

    @staticmethod
    def _certified_zone_with_three_days():
        ctx = fx.setup_certified_zone()
        zone_id = ctx["zone_ids"][0]
        logs = ctx["crew_days"][zone_id]
        return ctx, zone_id, logs

    @staticmethod
    def _void(ctx, zone_id, crew_day_id, reason="posted against the wrong zone"):
        return api_client.void_crew_day(
            zone_id, crew_day_id, f.void_crew_day_payload(reason), SUPERINTENDENT
        )

    def test_void_clears_its_own_index_repacks_the_survivors_and_re_sums_the_hours(self):
        """Voiding the first of three days nulls its index, re-packs the two
        survivors to 1 and 2 rather than leaving them at 2 and 3, and drops
        consumed hours from 100.0 to 64.0 while the budget identity still holds.

        PRD: "The voided log's `day_index` is cleared to null, and the surviving `POSTED` logs of the zone are re-indexed from 1 in the same `work_date`-then-`created_at` order, so the index sequence never leaves a gap."

        Design: Difficulty/compensating_invariant/crew_day_void_restores_hour_ledger_reindexes_and_recomputes_final_cost
        """
        ctx, zone_id, logs = self._certified_zone_with_three_days()
        before = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert before["consumed_crew_hours"] == pytest.approx(100.0, abs=0.01)
        assert before["remaining_crew_hours"] == pytest.approx(220.0, abs=0.01)

        voided = validate_success(
            self._void(ctx, zone_id, logs[0]["id"]), expected_status=200
        )
        assert voided["status"] == "VOIDED"
        assert voided["day_index"] is None
        assert voided["void_reason"] == "posted against the wrong zone"

        rows = get_success_data(api_client.list_zone_crew_day_logs(zone_id, PM))
        survivors = [row for row in rows if row["status"] == "POSTED"]
        assert len(survivors) == 2
        assert_day_indices_packed(survivors)
        by_date = {row["work_date"]: row for row in survivors}
        assert by_date["2026-08-11"]["day_index"] == 1
        assert by_date["2026-08-12"]["day_index"] == 2
        assert by_date["2026-08-11"]["day_cost_cents"] == 360640
        assert by_date["2026-08-11"]["straight_person_hours"] == pytest.approx(32.0, abs=0.01)
        assert by_date["2026-08-11"]["overtime_person_hours"] == pytest.approx(0.0, abs=0.01)

        zone = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert zone["consumed_crew_hours"] == pytest.approx(64.0, abs=0.01)
        assert zone["remaining_crew_hours"] == pytest.approx(256.0, abs=0.01)
        assert_crew_hour_ledger(zone)

    def test_void_re_stamps_the_actual_cost_but_never_the_estimate_or_the_billing(self):
        """The weather-tight zone's actual cost falls to the sum of the two
        surviving days, while the forward estimate, the certified line and the
        package's earned value are all left exactly as they were, and a second
        void of the same log is terminal.

        PRD: "`final_labor_cost_cents` is stamped when a zone is certified weather-tight, and re-stamped whenever a crew day of an already-weather-tight zone is voided."

        Design: Difficulty/compensating_invariant/crew_day_void_restores_hour_ledger_reindexes_and_recomputes_final_cost
        """
        ctx, zone_id, logs = self._certified_zone_with_three_days()
        before = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert before["final_labor_cost_cents"] == 1149540

        self._void(ctx, zone_id, logs[0]["id"])

        zone = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert zone["final_labor_cost_cents"] == 721280
        assert zone["provisional_labor_cost_cents"] == 940800
        assert zone["certified_line_cents"] == 58266376
        assert zone["weather_status"] == "WEATHER_TIGHT"
        assert zone["weather_tight_cycle_count"] == 1

        rows = get_success_data(api_client.list_zone_crew_day_logs(zone_id, PM))
        assert_day_cost_sum_equals_final(
            zone, [row for row in rows if row["status"] == "POSTED"]
        )

        package = fx.refresh_package(ctx)
        assert package["earned_value_certified_cents"] == 55353057
        assert package["weather_tight_zone_count"] == 1

        again = self._void(ctx, zone_id, logs[0]["id"])
        validate_error(again, ApiErrorId.ERR_TERMINAL_STATE.value, expected_status=409)
        unchanged = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert unchanged["final_labor_cost_cents"] == 721280
        assert unchanged["consumed_crew_hours"] == pytest.approx(64.0, abs=0.01)
