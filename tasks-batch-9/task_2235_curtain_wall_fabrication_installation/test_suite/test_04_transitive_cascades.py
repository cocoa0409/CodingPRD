"""Retraction chains that run several hops away from the row the caller
touched: a submittal returning for revision, and a failed deflection test."""
import pytest
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_client import api_client
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_FIELD_TEST_DAY, USER_IDS
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["cw_project_manager_headers"]


def _certified_zone_with_a_second_live_release():
    """Zone A certified under a closed release, then superseded by a live
    second release whose lot has reached GLAZED."""
    ctx = fx.setup_qualified_package()
    fx.add_approved_submittal(ctx, decision="APPROVED_AS_NOTED", notes_count=2)
    fx.add_received_glass_order(ctx, ordered_lites=240)
    fx.add_zone_a(ctx)
    zone_id = ctx["zone_ids"][0]

    fx.create_release(ctx)
    first_release_id = ctx["release_id"]
    first_lot_id = ctx["lots"][zone_id][0]["id"]

    fx.prepare_zone_for_hang(ctx, zone_id)
    fx.set_clock(fx.CLOCK_HANG_DAY)
    fx.hang_panels(ctx, zone_id)
    fx.post_crew_days(ctx, zone_id, fx.ZONE_A_CREW_DAYS)
    fx.set_clock(CLOCK_FIELD_TEST_DAY)
    fx.pass_field_tests(ctx, zone_id, user_id=USER_IDS["QC_2"])
    fx.certify_zone(ctx, zone_id)

    fx.create_release(ctx, panels_per_zone=18)
    second_release_id = ctx["release_id"]
    second_lot_id = ctx["lots"][zone_id][-1]["id"]
    fx.advance_lot(ctx, second_lot_id, "GLAZED")

    return ctx, first_release_id, first_lot_id, second_release_id, second_lot_id


class TestSubmittalRevisionCascade:
    """One review decision reaches release, lot, zone and package."""

    def test_revision_revokes_the_live_release_and_holds_only_its_unshipped_lot(self):
        """The revision decision revokes the release still in RELEASED and puts
        its GLAZED lot on hold with GLAZED recorded, while the closed release and
        its shipped lot are left exactly as they were.

        PRD: "Caused by hop 1: every panel lot belonging to each revoked release whose `fabrication_status` is `BATCHED` or `GLAZED` records that value into `status_before_hold` and transitions to `ON_HOLD` with `hold_reason` `SUBMITTAL_REVISION`."

        Design: Difficulty/transitive_cascade/submittal_revision_cascade_revokes_release_holds_lot_reverts_zone_and_package
        """
        (
            ctx,
            first_release_id,
            first_lot_id,
            second_release_id,
            second_lot_id,
        ) = _certified_zone_with_a_second_live_release()

        get_success_data(
            api_client.reopen_submittal_review(
                ctx["submittal_id"],
                f.reopen_review_payload("owner disputes the head detail"),
                TEST_USERS["architect_of_record_headers"],
            )
        )
        response = api_client.review_submittal(
            ctx["submittal_id"], f.review_payload("REVISION_REQUIRED"),
            TEST_USERS["architect_of_record_headers"],
        )
        submittal = validate_success(response, expected_status=200)
        assert submittal["state"] == "REVISION_REQUIRED"

        revoked = get_success_data(
            api_client.get_fabrication_release(second_release_id, PM)
        )
        assert revoked["state"] == "REVOKED"
        assert revoked["revoked_reason"] == "SUBMITTAL_REVISION"

        closed = get_success_data(api_client.get_fabrication_release(first_release_id, PM))
        assert closed["state"] == "CLOSED"
        assert closed["revoked_reason"] is None

        held = get_success_data(api_client.get_panel_lot(second_lot_id, PM))
        assert held["fabrication_status"] == "ON_HOLD"
        assert held["hold_reason"] == "SUBMITTAL_REVISION"
        assert held["status_before_hold"] == "GLAZED"

        untouched = get_success_data(api_client.get_panel_lot(first_lot_id, PM))
        assert untouched["fabrication_status"] == "SHIPPED"
        assert untouched["hold_reason"] is None
        assert untouched["status_before_hold"] is None

    def test_held_lot_reverts_the_zone_and_zeroes_the_package_earned_value(self):
        """The held lot drags its weather-tight zone to REMEDIATION, which
        removes the only certified line, drops the package back to
        IN_INSTALLATION and leaves the erection axis and forward estimate intact.

        PRD: "Caused by hop 3: the package's `weather_tight_zone_count` decrements, its `certified_area_sqm`, `earned_value_certified_cents` and `retention_held_cents` recompute over the surviving weather-tight zones, and a package sitting in `WEATHER_TIGHT_ACHIEVED` reverts to `IN_INSTALLATION`."

        Design: Difficulty/transitive_cascade/submittal_revision_cascade_revokes_release_holds_lot_reverts_zone_and_package
        """
        ctx, _, _, _, _ = _certified_zone_with_a_second_live_release()
        zone_id = ctx["zone_ids"][0]

        before = get_success_data(api_client.get_facade_package(ctx["package_id"], PM))
        assert before["state"] == "WEATHER_TIGHT_ACHIEVED"
        assert before["earned_value_certified_cents"] == 55353057

        architect = TEST_USERS["architect_of_record_headers"]
        get_success_data(
            api_client.reopen_submittal_review(
                ctx["submittal_id"],
                f.reopen_review_payload("owner disputes the head detail"),
                architect,
            )
        )
        get_success_data(
            api_client.review_submittal(
                ctx["submittal_id"], f.review_payload("REVISION_REQUIRED"), architect
            )
        )

        zone = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert zone["weather_status"] == "REMEDIATION"
        assert zone["weather_tight_at"] is None
        assert zone["certified_line_cents"] is None
        assert zone["install_status"] == "PANELS_HUNG"
        assert zone["provisional_labor_cost_cents"] == 940800

        package = get_success_data(api_client.get_facade_package(ctx["package_id"], PM))
        assert package["state"] == "IN_INSTALLATION"
        assert package["weather_tight_zone_count"] == 0
        assert package["certified_area_sqm"] == pytest.approx(0.00, abs=0.01)
        assert package["earned_value_certified_cents"] == 0
        assert package["retention_held_cents"] == 0
        assert package["blocking_submittal_count"] == 1
        assert package["engineering_posture"] == "RESTRICTED"

        read = get_success_data(api_client.get_earned_value(ctx["package_id"], PM))
        assert read["certified_subtotal_cents"] == 0
        assert read["earned_value_certified_cents"] == 0
        assert read["weather_tight_zone_count"] == 0


class TestDeflectionFailureCascade:
    """A failed deflection test removes exactly one zone's line from the
    package total."""

    @staticmethod
    def _fail_deflection_on_zone_a(ctx):
        zone_id = ctx["zone_ids"][0]
        test = fx.schedule_field_test(
            ctx, zone_id, "STRUCTURAL_DEFLECTION", CLOCK_FIELD_TEST_DAY
        )
        return fx.record_field_test(
            ctx, test["id"], f.deflection_result_payload(13.33), USER_IDS["QC_2"]
        )

    def test_deflection_exactly_at_the_limit_fails_and_raises_a_critical_defect(self):
        """A measurement equal to the 13.33 mm limit is not strictly less than it,
        so the test fails for DEFLECTION_EXCEEDED and mints a CRITICAL field-test
        defect that restricts the package.

        PRD: "Its `severity` is `CRITICAL` when the outcome was `WATER_PENETRATION` or `DEFLECTION_EXCEEDED`, and `MAJOR` when the outcome was `AIR_LEAKAGE_EXCEEDED` — leaking air is a defect, but water intrusion and structural overdeflection are safety matters."

        Design: Difficulty/transitive_cascade/deflection_failure_cascade_removes_one_zone_line_from_package_earned_value
        """
        ctx = fx.setup_two_certified_zones()
        zone_id = ctx["zone_ids"][0]
        zone_before = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert zone_before["deflection_limit_mm"] == pytest.approx(13.33, abs=0.01)

        result = self._fail_deflection_on_zone_a(ctx)
        assert result["state"] == "FAILED"
        assert result["outcome_reason"] == "DEFLECTION_EXCEEDED"

        defects = get_success_data(
            api_client.list_defect_items(PM, params={"field_test_id": result["id"]})
        )
        assert len(defects) == 1
        assert defects[0]["origin"] == "FIELD_TEST"
        assert defects[0]["severity"] == "CRITICAL"
        assert defects[0]["status"] == "OPEN"
        assert defects[0]["zone_id"] == zone_id
        assert defects[0]["raised_by_user_id"] == USER_IDS["QC_2"]

        package = get_success_data(api_client.get_facade_package(ctx["package_id"], PM))
        assert package["open_critical_defect_count"] == 1
        assert package["engineering_posture"] == "RESTRICTED"

    def test_surviving_zone_line_is_re_summed_without_the_reverted_one(self):
        """Removing zone A's line leaves zone B's 54912001 as the whole subtotal,
        so retention and earned value are re-derived from the survivors only
        while zone A keeps its chronological labor actual.

        PRD: "Zones in `NOT_TIGHT` or `REMEDIATION` contribute nothing, which is why a revert cascade simply removes the reverted zone's line from the sum and re-runs all three stages."

        Design: Difficulty/transitive_cascade/deflection_failure_cascade_removes_one_zone_line_from_package_earned_value
        """
        ctx = fx.setup_two_certified_zones()
        zone_a_id, zone_b_id = ctx["zone_ids"][0], ctx["zone_ids"][1]
        before = get_success_data(api_client.get_facade_package(ctx["package_id"], PM))
        assert before["earned_value_certified_cents"] == 107519458

        self._fail_deflection_on_zone_a(ctx)

        zone_a = get_success_data(api_client.get_installation_zone(zone_a_id, PM))
        assert zone_a["weather_status"] == "REMEDIATION"
        assert zone_a["certified_line_cents"] is None
        assert zone_a["final_labor_cost_cents"] == 1149540

        zone_b = get_success_data(api_client.get_installation_zone(zone_b_id, PM))
        assert zone_b["weather_status"] == "WEATHER_TIGHT"
        assert zone_b["certified_line_cents"] == 54912001

        package = get_success_data(api_client.get_facade_package(ctx["package_id"], PM))
        assert package["state"] == "IN_INSTALLATION"
        assert package["weather_tight_zone_count"] == 1
        assert package["certified_area_sqm"] == pytest.approx(388.63, abs=0.01)
        assert package["earned_value_certified_cents"] == 52166401
        assert package["retention_held_cents"] == 2745600
