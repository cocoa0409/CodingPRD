"""Cross-cutting layers: the two optimistic-concurrency tokens, the derived
counters that are re-derived rather than incremented, and the immediacy of every
effect."""
import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_crew_hour_ledger, assert_glass_lite_ledger
from test_helpers.constants import CLOCK_HANG_DAY
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["cw_project_manager_headers"]
PROCUREMENT = TEST_USERS["glazing_procurement_headers"]
SUPERINTENDENT = TEST_USERS["field_superintendent_headers"]


class TestStalePackageVersionOnRelease:
    """The release's only guard against a client working from an old picture."""

    @staticmethod
    def _release(ctx, zone_ids, expected_version):
        return api_client.create_fabrication_release(
            f.create_fabrication_release_payload(
                ctx["package_id"],
                ctx["submittal_id"],
                ctx["glass_order_id"],
                zone_ids,
                expected_version,
            ),
            PM,
        )

    def test_one_version_behind_writes_nothing_and_the_token_dies_on_first_use(self):
        """A release quoting the version before the current one is refused and leaves
        no release, no lot and an untouched lite ledger; the current version is
        accepted and carries the package into fabrication; and replaying that same
        number afterwards is refused again, because the successful write consumed it.

        PRD: "If that value does not equal the package's current `version`, the create is rejected with `ERR_STALE_PACKAGE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_package_version_is_rejected
        """
        ctx = fx.setup_ready_for_release()
        zone_ids = [ctx["zone_ids"][0]]
        current = fx.package_version(ctx)
        order_version = fx.refresh_glass_order(ctx)["version"]

        validate_error(
            self._release(ctx, zone_ids, current - 1),
            ApiErrorId.ERR_STALE_PACKAGE_VERSION.value,
            expected_status=412,
        )
        assert get_success_data(api_client.list_fabrication_releases(PM)) == []
        assert get_success_data(api_client.list_panel_lots(PM)) == []
        untouched = fx.refresh_glass_order(ctx)
        assert untouched["allocated_lites"] == 0
        assert untouched["version"] == order_version
        assert fx.refresh_package(ctx)["state"] == "MOCKUP_QUALIFIED"
        assert fx.package_version(ctx) == current

        release = validate_success(
            self._release(ctx, zone_ids, current), expected_status=201
        )
        assert release["state"] == "RELEASED"
        advanced = fx.refresh_package(ctx)
        assert advanced["state"] == "IN_FABRICATION"
        assert advanced["version"] > current

        validate_error(
            self._release(ctx, zone_ids, current),
            ApiErrorId.ERR_STALE_PACKAGE_VERSION.value,
            expected_status=412,
        )
        assert len(get_success_data(api_client.list_fabrication_releases(PM))) == 1
        assert fx.refresh_glass_order(ctx)["allocated_lites"] == 72

    def test_the_stale_token_is_reported_before_the_business_gates_are_reached(self):
        """A release that is both stale and impossible to satisfy — it asks for far
        more glass than the order can cover — reports the stale version rather than
        the glass balance, and once the version is right the balance objection finally
        surfaces.

        PRD: "Stale parent version: `ERR_STALE_PACKAGE_VERSION` (412) on release creation, then `ERR_STALE_GLASS_ORDER_VERSION` (412) on breakage draws."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_package_version_is_rejected
        """
        ctx = fx.setup_ready_for_release()
        zone_ids = [ctx["zone_ids"][0]]
        current = fx.package_version(ctx)

        greedy = f.create_fabrication_release_payload(
            ctx["package_id"],
            ctx["submittal_id"],
            ctx["glass_order_id"],
            zone_ids,
            current - 1,
            panels_per_zone=400,
        )
        validate_error(
            api_client.create_fabrication_release(greedy, PM),
            ApiErrorId.ERR_STALE_PACKAGE_VERSION.value,
            expected_status=412,
        )

        greedy["expected_package_version"] = current
        validate_error(
            api_client.create_fabrication_release(greedy, PM),
            ApiErrorId.ERR_GLASS_BALANCE_INSUFFICIENT.value,
            expected_status=422,
        )
        assert get_success_data(api_client.list_fabrication_releases(PM)) == []


class TestStaleGlassOrderVersionOnDraws:
    """Repeated draws are each legal, so only the token forces a re-read."""

    def test_the_drawer_must_re_read_the_order_between_two_legitimate_draws(self):
        """One version behind is refused with the stock untouched, the current version
        draws three lites, replaying that same version is refused even though four
        lites remain, and a re-read lets the two-lite draw through — with the reserve
        identity holding after every accepted and rejected call.

        PRD: "A mismatch with the order's current `version` is rejected with `ERR_STALE_GLASS_ORDER_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_glass_order_version_is_rejected
        """
        ctx = fx.setup_glass_order_with_breakage_stock(ordered_lites=240)
        lot = ctx["lots"][ctx["zone_ids"][0]][0]
        order = fx.refresh_glass_order(ctx)
        assert order["breakage_stock_lites"] == 7
        assert order["available_stock_lites"] == 7

        def draw(quantity, version):
            return api_client.create_breakage_draw(
                f.create_breakage_draw_payload(
                    ctx["glass_order_id"], lot["id"], quantity, version
                ),
                PROCUREMENT,
            )

        validate_error(
            draw(3, order["version"] - 1),
            ApiErrorId.ERR_STALE_GLASS_ORDER_VERSION.value,
            expected_status=412,
        )
        still = fx.refresh_glass_order(ctx)
        assert still["available_stock_lites"] == 7
        assert still["drawn_lites"] == 0
        assert still["version"] == order["version"]
        assert_glass_lite_ledger(still)

        first = validate_success(draw(3, order["version"]), expected_status=201)
        assert first["status"] == "DRAWN"
        drawn = fx.refresh_glass_order(ctx)
        assert drawn["drawn_lites"] == 3
        assert drawn["available_stock_lites"] == 4
        assert_glass_lite_ledger(drawn)

        validate_error(
            draw(2, order["version"]),
            ApiErrorId.ERR_STALE_GLASS_ORDER_VERSION.value,
            expected_status=412,
        )
        assert fx.refresh_glass_order(ctx)["drawn_lites"] == 3

        validate_success(draw(2, drawn["version"]), expected_status=201)
        final = fx.refresh_glass_order(ctx)
        assert final["drawn_lites"] == 5
        assert final["available_stock_lites"] == 2
        assert final["breakage_stock_lites"] == 7
        assert_glass_lite_ledger(final)


class TestDerivedCountersReconcile:
    """Counters are re-derived from their contributing rows, never bumped in
    place."""

    def test_one_release_sets_the_lot_count_and_the_whole_lite_ledger(self):
        """Two covered zones give a lot count of 2 and two lots of 72 lites each, and
        the order reports 144 allocated behind its seven-lite reserve with 89
        unallocated against a 240-lite commitment base that still balances.

        PRD: "First, `committable_lites` must equal `allocated_lites` plus `breakage_stock_lites` plus `unallocated_lites`."

        Design: Corner/cross_cutting_complexity_layers/derived_counters_reconcile_after_each_contributing_write
        """
        ctx = fx.setup_ready_for_release(zone_count=2)
        zone_a, zone_b = ctx["zone_ids"][0], ctx["zone_ids"][1]

        release = validate_success(
            api_client.create_fabrication_release(
                f.create_fabrication_release_payload(
                    ctx["package_id"],
                    ctx["submittal_id"],
                    ctx["glass_order_id"],
                    [zone_a, zone_b],
                    fx.package_version(ctx),
                ),
                PM,
            ),
            expected_status=201,
        )
        assert release["lot_count"] == 2

        lots = get_success_data(
            api_client.list_panel_lots(SUPERINTENDENT, params={"release_id": release["id"]})
        )
        assert len(lots) == 2
        assert [lot["lite_count"] for lot in lots] == [72, 72]

        order = fx.refresh_glass_order(ctx)
        assert order["committable_lites"] == 240
        assert order["allocated_lites"] == 144
        assert order["breakage_stock_lites"] == 7
        assert order["unallocated_lites"] == 89
        assert_glass_lite_ledger(order)

    def test_three_crew_days_roll_one_zones_ledger_and_leave_the_other_at_zero(self):
        """Nine hours then two eights on the first zone consume 100.0 of its 320.0
        budgeted person-hours, the budget identity holds after each of the three
        postings, and the second zone's ledger has not moved at all — the ledger is
        per zone.

        PRD: "The **zone crew-hour ledger** must satisfy `budget_crew_hours` equals `consumed_crew_hours` plus `remaining_crew_hours` after every crew-day posting and every void."

        Design: Corner/cross_cutting_complexity_layers/derived_counters_reconcile_after_each_contributing_write
        """
        ctx = fx.setup_ready_for_release(zone_count=2)
        zone_a, zone_b = ctx["zone_ids"][0], ctx["zone_ids"][1]
        fx.set_clock(CLOCK_HANG_DAY)

        expected = [(36.0, 284.0), (68.0, 252.0), (100.0, 220.0)]
        days = [
            {"work_date": "2026-08-10", "crew_size": 4, "shift_hours": 9.0, "panels_installed": 10},
            {"work_date": "2026-08-11", "crew_size": 4, "shift_hours": 8.0, "panels_installed": 13},
            {"work_date": "2026-08-12", "crew_size": 4, "shift_hours": 8.0, "panels_installed": 13},
        ]
        for day, (consumed, remaining) in zip(days, expected):
            validate_success(
                api_client.post_crew_day(zone_a, f.create_crew_day_payload(**day), SUPERINTENDENT),
                expected_status=201,
            )
            zone = get_success_data(api_client.get_installation_zone(zone_a, PM))
            assert zone["budget_crew_hours"] == pytest.approx(320.0, abs=0.01)
            assert zone["consumed_crew_hours"] == pytest.approx(consumed, abs=0.01)
            assert zone["remaining_crew_hours"] == pytest.approx(remaining, abs=0.01)
            assert_crew_hour_ledger(zone)

        idle = get_success_data(api_client.get_installation_zone(zone_b, PM))
        assert idle["consumed_crew_hours"] == pytest.approx(0.0, abs=0.01)
        assert idle["remaining_crew_hours"] == pytest.approx(320.0, abs=0.01)
        assert_crew_hour_ledger(idle)


class TestEveryEffectIsImmediate:
    """No lag, no background job, no re-read required."""

    def test_the_certification_response_already_carries_the_whole_cascade(self):
        """The certifying call itself returns the weather-tight stamp, the
        chronological actual and the certified line; the very next package read
        already shows the achieved state, the one certified zone, the area and the
        earned value; the computed read agrees in the same instant; the zone keeps
        both labour figures; and repeating every read changes nothing.

        PRD: "Endpoints that modify an existing resource — every state transition, every compensating action, every recomputation — return HTTP 200 with the updated resource."

        Design: Corner/consistency_model/every_effect_is_visible_in_the_same_response_and_to_the_next_read
        """
        ctx = fx.setup_zone_ready_to_certify()
        zone_id = ctx["zone_ids"][0]

        certified = validate_success(
            api_client.certify_weather_tight(
                zone_id, f.certify_weather_tight_payload(), PM
            ),
            expected_status=200,
        )
        assert certified["weather_status"] == "WEATHER_TIGHT"
        assert certified["weather_tight_at"] == "2026-08-13T09:00:00.000Z"
        assert certified["final_labor_cost_cents"] == 1149540
        assert certified["certified_line_cents"] == 58266376

        package = get_success_data(api_client.get_facade_package(ctx["package_id"], PM))
        assert package["state"] == "WEATHER_TIGHT_ACHIEVED"
        assert package["weather_tight_zone_count"] == 1
        assert package["certified_area_sqm"] == pytest.approx(412.37, abs=0.01)
        assert package["earned_value_certified_cents"] == 55353057

        computed = get_success_data(api_client.get_earned_value(ctx["package_id"], PM))
        assert computed["weather_tight_zone_count"] == 1
        assert computed["certified_area_sqm"] == pytest.approx(412.37, abs=0.01)
        assert computed["earned_value_certified_cents"] == 55353057
        assert computed["retention_held_cents"] == 2913319

        zone = get_success_data(api_client.get_installation_zone(zone_id, SUPERINTENDENT))
        assert zone["provisional_labor_cost_cents"] == 940800
        assert zone["final_labor_cost_cents"] == 1149540
        assert zone["certified_line_cents"] == 58266376

        assert get_success_data(api_client.get_facade_package(ctx["package_id"], PM)) == package
        assert (
            get_success_data(api_client.get_earned_value(ctx["package_id"], PM)) == computed
        )
        assert (
            get_success_data(api_client.get_installation_zone(zone_id, SUPERINTENDENT)) == zone
        )
