"""Values that sit exactly on a declared edge: the 70.00 risk threshold, the
half-open buffered hoist interval, the two-kind evidence conjunction and the
two breakage ceilings that meet at 72 lites."""
import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_glass_lite_ledger
from test_helpers.constants import CLOCK_FIELD_TEST_DAY, USER_IDS
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["cw_project_manager_headers"]
PROCUREMENT = TEST_USERS["glazing_procurement_headers"]
SUPERINTENDENT = TEST_USERS["field_superintendent_headers"]


class TestGlassRiskThresholdBoundary:
    """One quoted lead day separates a blocked order from an admissible one."""

    @staticmethod
    def _two_orders_astride_the_threshold():
        """Two orders on one package whose expedited scores land on 70.00 and
        68.89 respectively."""
        ctx = fx.setup_qualified_package(weather_tightness_deadline_date="2026-12-16")
        fx.add_approved_submittal(ctx)
        fx.add_zone_a(ctx)

        at_threshold = get_success_data(
            api_client.create_glass_order(
                f.create_glass_order_payload(
                    ctx["package_id"], quoted_lead_time_days=136, ordered_lites=240
                ),
                PROCUREMENT,
            )
        )
        below_threshold = get_success_data(
            api_client.create_glass_order(
                f.create_glass_order_payload(
                    ctx["package_id"], quoted_lead_time_days=135, ordered_lites=240
                ),
                PROCUREMENT,
            )
        )
        return ctx, at_threshold, below_threshold

    def test_expedited_scores_of_exactly_seventy_and_of_sixty_eight_point_eight_nine(self):
        """Both orders score 80.00 while nominal; buying ten days drops one to
        exactly 70.00, which still sets the flag, and the other to 68.89, which
        clears it.

        PRD: "`risk_flag` is true when `risk_score` is at or above the release threshold of 70.00 — exactly 70.00 sets the flag, 69.99 does not."

        Design: Difficulty/boundary_precision_check/glass_risk_score_exactly_at_threshold_still_blocks_release
        """
        _, at_threshold, below_threshold = self._two_orders_astride_the_threshold()

        for nominal in (at_threshold, below_threshold):
            assert nominal["risk_variant"] == "NOMINAL"
            assert nominal["risk_score"] == pytest.approx(80.00, abs=0.01)
            assert nominal["risk_flag"] is True

        expedited_a = validate_success(
            api_client.request_expedite(
                at_threshold["id"], f.request_expedite_payload(1), PROCUREMENT
            ),
            expected_status=200,
        )
        assert expedited_a["risk_variant"] == "EXPEDITE_ADJUSTED"
        assert expedited_a["effective_lead_days"] == 126
        assert expedited_a["risk_score"] == pytest.approx(70.00, abs=0.01)
        assert expedited_a["risk_flag"] is True

        expedited_b = validate_success(
            api_client.request_expedite(
                below_threshold["id"], f.request_expedite_payload(1), PROCUREMENT
            ),
            expected_status=200,
        )
        assert expedited_b["effective_lead_days"] == 125
        assert expedited_b["risk_score"] == pytest.approx(68.89, abs=0.01)
        assert expedited_b["risk_flag"] is False
        assert expedited_a["risk_score"] - expedited_b["risk_score"] == pytest.approx(
            1.11, abs=0.01
        )

    def test_order_at_the_threshold_blocks_the_release_while_the_other_admits_it(self):
        """A release drawing on the 70.00 order is refused and allocates nothing,
        while the identical release against the 68.89 order is created and
        allocates its 72 lites.

        PRD: "And the referenced order's `risk_flag` must be false; an order at or above the 70.00 risk threshold refuses the release with `ERR_GLASS_RISK_THRESHOLD_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/glass_risk_score_exactly_at_threshold_still_blocks_release
        """
        ctx, at_threshold, below_threshold = self._two_orders_astride_the_threshold()
        api_client.request_expedite(
            at_threshold["id"], f.request_expedite_payload(1), PROCUREMENT
        )
        api_client.request_expedite(
            below_threshold["id"], f.request_expedite_payload(1), PROCUREMENT
        )
        zone_ids = list(ctx["zone_ids"])

        refused = api_client.create_fabrication_release(
            f.create_fabrication_release_payload(
                ctx["package_id"],
                ctx["submittal_id"],
                at_threshold["id"],
                zone_ids,
                fx.package_version(ctx),
            ),
            PM,
        )
        validate_error(
            refused,
            ApiErrorId.ERR_GLASS_RISK_THRESHOLD_EXCEEDED.value,
            expected_status=422,
        )

        accepted = api_client.create_fabrication_release(
            f.create_fabrication_release_payload(
                ctx["package_id"],
                ctx["submittal_id"],
                below_threshold["id"],
                zone_ids,
                fx.package_version(ctx),
            ),
            PM,
        )
        release = validate_success(accepted, expected_status=201)
        assert release["state"] == "RELEASED"
        assert release["lot_count"] == 1

        blocked = get_success_data(
            api_client.get_glass_order(at_threshold["id"], PROCUREMENT)
        )
        assert blocked["allocated_lites"] == 0
        used = get_success_data(
            api_client.get_glass_order(below_threshold["id"], PROCUREMENT)
        )
        assert used["allocated_lites"] == 72


class TestHoistChangeoverBufferBoundary:
    """Only the stored interval is buffered, and its far edge is exclusive."""

    @staticmethod
    def _rig_holding_a_morning_window():
        ctx = fx.new_project()
        fx.add_zone_a(ctx)
        fx.add_zone_b(ctx)
        fx.create_rig(ctx, changeover_buffer_minutes=45)
        first = fx.create_reservation(
            ctx,
            ctx["zone_ids"][0],
            "2026-08-10T06:00:00Z",
            "2026-08-10T12:00:00Z",
            planned_panel_count=36,
        )
        return ctx, first

    @staticmethod
    def _request(ctx, window_start, window_end):
        return api_client.create_hoist_reservation(
            f.create_hoist_reservation_payload(
                ctx["rig_id"],
                ctx["zone_ids"][1],
                window_start,
                window_end,
                planned_panel_count=30,
            ),
            SUPERINTENDENT,
        )

    def test_thirty_minutes_after_conflicts_while_exactly_forty_five_minutes_after_books(self):
        """The stored window is expanded to run 05:15 through 12:45, so a 12:30
        start lands inside it and is refused while a 12:45 start sits on the
        exclusive edge and is accepted unbuffered.

        PRD: "With a 45-minute buffer, a request starting half an hour after an existing window ends conflicts and is refused with `ERR_HOIST_WINDOW_CONFLICT`, while a request starting exactly 45 minutes after that window ends is accepted."

        Design: Difficulty/boundary_precision_check/hoist_changeover_buffer_boundary_on_half_open_windows
        """
        ctx, first = self._rig_holding_a_morning_window()
        assert first["blocked_from"] == "2026-08-10T05:15:00.000Z"
        assert first["blocked_until"] == "2026-08-10T12:45:00.000Z"

        conflicting = self._request(ctx, "2026-08-10T12:30:00Z", "2026-08-10T16:00:00Z")
        validate_error(
            conflicting, ApiErrorId.ERR_HOIST_WINDOW_CONFLICT.value, expected_status=409
        )

        accepted = self._request(ctx, "2026-08-10T12:45:00Z", "2026-08-10T16:00:00Z")
        second = validate_success(accepted, expected_status=201)
        assert second["window_start"] == "2026-08-10T12:45:00.000Z"
        assert second["blocked_from"] == "2026-08-10T12:00:00.000Z"
        assert second["blocked_until"] == "2026-08-10T16:45:00.000Z"
        assert second["status"] == "RESERVED"

    def test_a_start_one_minute_inside_the_new_blocked_interval_is_refused(self):
        """The accepted reservation projects its own buffered interval, so a
        16:44 start collides with its 16:45 edge and neither existing
        reservation is disturbed.

        PRD: "Occupancy is exclusive: the **requested raw window**, from `window_start` up to but not including `window_end`, must not intersect the stored interval from `blocked_from` up to but not including `blocked_until` of any reservation on the same rig whose `status` is `RESERVED` or `CONSUMED`."

        Design: Difficulty/boundary_precision_check/hoist_changeover_buffer_boundary_on_half_open_windows
        """
        ctx, first = self._rig_holding_a_morning_window()
        second = validate_success(
            self._request(ctx, "2026-08-10T12:45:00Z", "2026-08-10T16:00:00Z"),
            expected_status=201,
        )

        refused = self._request(ctx, "2026-08-10T16:44:00Z", "2026-08-10T18:00:00Z")
        validate_error(
            refused, ApiErrorId.ERR_HOIST_WINDOW_CONFLICT.value, expected_status=409
        )

        assert (
            get_success_data(api_client.get_hoist_reservation(first["id"], PM))["status"]
            == "RESERVED"
        )
        assert (
            get_success_data(api_client.get_hoist_reservation(second["id"], PM))["status"]
            == "RESERVED"
        )
        held = get_success_data(api_client.list_rig_reservations(ctx["rig_id"], PM))
        assert len(held) == 2


class TestCertificationEvidenceConjunction:
    """The evidence gate is a conjunction over two kinds, not a count."""

    @staticmethod
    def _hung_zone_without_evidence():
        ctx = fx.setup_hung_zone_with_crew_days()
        fx.set_clock(CLOCK_FIELD_TEST_DAY)
        return ctx, ctx["zone_ids"][0]

    def test_empty_evidence_and_a_water_only_set_both_fail_the_same_way(self):
        """A zone with no field tests at all and the same zone with one PASSED
        water test are refused with the identical evidence error, and neither
        rejection stamps anything.

        PRD: "An empty passed set fails here, and so does a set holding only one of the two kinds; one of each kind satisfies it."

        Design: Difficulty/boundary_precision_check/certification_evidence_set_empty_then_single_kind_then_complete
        """
        ctx, zone_id = self._hung_zone_without_evidence()
        assert get_success_data(api_client.list_zone_field_tests(zone_id, PM)) == []

        empty_set = api_client.certify_weather_tight(
            zone_id, f.certify_weather_tight_payload(), PM
        )
        validate_error(
            empty_set, ApiErrorId.ERR_NO_FIELD_TEST_EVIDENCE.value, expected_status=422
        )

        water = fx.schedule_field_test(
            ctx, zone_id, "WATER_AAMA_501_2", CLOCK_FIELD_TEST_DAY
        )
        passed_water = fx.record_field_test(
            ctx, water["id"], f.water_result_payload(False), USER_IDS["QC_2"]
        )
        assert passed_water["state"] == "PASSED"

        water_only = api_client.certify_weather_tight(
            zone_id, f.certify_weather_tight_payload(), PM
        )
        validate_error(
            water_only, ApiErrorId.ERR_NO_FIELD_TEST_EVIDENCE.value, expected_status=422
        )

        zone = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert zone["weather_status"] == "NOT_TIGHT"
        assert zone["weather_tight_at"] is None
        assert fx.refresh_package(ctx)["weather_tight_zone_count"] == 0

    def test_the_second_kind_completes_the_set_and_the_certification_lands(self):
        """Adding one PASSED air test — 0.04 cfm against the 0.06 limit — flips
        the same call to success, and the zone's child view then holds exactly
        one row per kind.

        PRD: "On success the zone stamps `weather_tight_at` from the logical clock and increments `weather_tight_cycle_count` by 1, writes `final_labor_cost_cents` from the chronological walk of §3.7, writes its own `certified_line_cents`, and rolls the package's `certified_area_sqm`, `earned_value_certified_cents`, `retention_held_cents` and `weather_tight_zone_count` forward."

        Design: Difficulty/boundary_precision_check/certification_evidence_set_empty_then_single_kind_then_complete
        """
        ctx, zone_id = self._hung_zone_without_evidence()
        water = fx.schedule_field_test(
            ctx, zone_id, "WATER_AAMA_501_2", CLOCK_FIELD_TEST_DAY
        )
        fx.record_field_test(
            ctx, water["id"], f.water_result_payload(False), USER_IDS["QC_2"]
        )
        air = fx.schedule_field_test(ctx, zone_id, "AIR_INFILTRATION", CLOCK_FIELD_TEST_DAY)
        passed_air = fx.record_field_test(
            ctx, air["id"], f.air_result_payload(0.04), USER_IDS["QC_2"]
        )
        assert passed_air["state"] == "PASSED"
        assert passed_air["measured_air_leakage_cfm"] == pytest.approx(0.04, abs=0.001)

        zone = validate_success(
            api_client.certify_weather_tight(
                zone_id, f.certify_weather_tight_payload(), PM
            ),
            expected_status=200,
        )
        assert zone["weather_status"] == "WEATHER_TIGHT"
        assert zone["weather_tight_cycle_count"] == 1
        assert zone["certified_line_cents"] == 58266376
        assert zone["final_labor_cost_cents"] == 1149540

        tests = get_success_data(api_client.list_zone_field_tests(zone_id, PM))
        assert len(tests) == 2
        assert {row["test_kind"] for row in tests} == {
            "WATER_AAMA_501_2",
            "AIR_INFILTRATION",
        }
        assert all(row["state"] == "PASSED" for row in tests)


class TestBreakageDrawBoundaries:
    """Available stock and lot content are two ceilings that meet at 72."""

    @staticmethod
    def _order_with_two_lots():
        """A 2400-lite order reserving 72 for breakage, with a 72-lite lot and a
        20-lite lot drawing on it."""
        ctx = fx.setup_qualified_package()
        fx.add_approved_submittal(ctx)
        fx.add_received_glass_order(ctx, ordered_lites=2400)
        zone_a = fx.add_zone_a(ctx)
        zone_b = fx.add_zone_b(ctx, planned_panel_count=10)
        fx.create_release(ctx, zone_ids=[zone_a["id"]], panels_per_zone=36)
        fx.create_release(ctx, zone_ids=[zone_b["id"]], panels_per_zone=10)
        big_lot = ctx["lots"][zone_a["id"]][0]
        small_lot = ctx["lots"][zone_b["id"]][0]
        return ctx, big_lot, small_lot

    @staticmethod
    def _draw(ctx, lot_id, quantity_lites):
        version = fx.refresh_glass_order(ctx)["version"]
        return api_client.create_breakage_draw(
            f.create_breakage_draw_payload(
                ctx["glass_order_id"], lot_id, quantity_lites, version
            ),
            PROCUREMENT,
        )

    def test_oversized_draw_reports_lot_content_and_over_available_reports_exhaustion(self):
        """A 30-lite draw fits inside the 72 available but overruns its 20-lite
        lot, so it reports the quantity error; a 73-lite draw overruns the
        reserve itself and reports exhaustion.

        PRD: "Two capacity limits apply in order: a draw for more lites than the order's `available_stock_lites` is refused with `ERR_BREAKAGE_STOCK_EXHAUSTED`, and a draw whose `quantity_lites` exceeds the `lite_count` of the referenced panel lot is refused with `ERR_DRAW_QUANTITY_INVALID`, because a replacement draw cannot exceed the glass content of the lot it repairs."

        Design: Difficulty/boundary_precision_check/breakage_stock_draw_boundaries_at_exact_availability_and_lot_content
        """
        ctx, big_lot, small_lot = self._order_with_two_lots()
        order = fx.refresh_glass_order(ctx)
        assert order["committable_lites"] == 2400
        assert order["breakage_stock_lites"] == 72
        assert order["available_stock_lites"] == 72
        assert order["allocated_lites"] == 92
        assert order["unallocated_lites"] == 2236
        assert big_lot["lite_count"] == 72
        assert small_lot["lite_count"] == 20

        oversized = self._draw(ctx, small_lot["id"], 30)
        validate_error(
            oversized, ApiErrorId.ERR_DRAW_QUANTITY_INVALID.value, expected_status=422
        )

        exhausting = self._draw(ctx, big_lot["id"], 73)
        validate_error(
            exhausting,
            ApiErrorId.ERR_BREAKAGE_STOCK_EXHAUSTED.value,
            expected_status=422,
        )
        assert_glass_lite_ledger(fx.refresh_glass_order(ctx))

    def test_a_draw_for_exactly_the_available_reserve_is_accepted_and_then_nothing_is(self):
        """A 72-lite draw sits on both ceilings at once and is taken, which
        empties the reserve so that a single further lite is refused; only the
        accepted draw bumped the order's version.

        PRD: "Second, `breakage_stock_lites` must equal `available_stock_lites` plus `drawn_lites`."

        Design: Difficulty/boundary_precision_check/breakage_stock_draw_boundaries_at_exact_availability_and_lot_content
        """
        ctx, big_lot, small_lot = self._order_with_two_lots()
        opening_version = fx.refresh_glass_order(ctx)["version"]

        self._draw(ctx, small_lot["id"], 30)
        self._draw(ctx, big_lot["id"], 73)

        accepted = self._draw(ctx, big_lot["id"], 72)
        draw = validate_success(accepted, expected_status=201)
        assert draw["status"] == "DRAWN"
        assert draw["quantity_lites"] == 72
        assert draw["cancelled_reason"] is None

        drained = fx.refresh_glass_order(ctx)
        assert drained["drawn_lites"] == 72
        assert drained["available_stock_lites"] == 0
        assert drained["unallocated_lites"] == 2236
        assert_glass_lite_ledger(drained)

        refused = self._draw(ctx, big_lot["id"], 1)
        validate_error(
            refused, ApiErrorId.ERR_BREAKAGE_STOCK_EXHAUSTED.value, expected_status=422
        )

        final = fx.refresh_glass_order(ctx)
        assert final["version"] == opening_version + 1
        assert_glass_lite_ledger(final)
