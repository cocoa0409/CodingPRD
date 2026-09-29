"""Three machines that do not run in a straight line: submittal review that
escalates on its third return, a zone whose two axes advance independently and
can be re-certified, and a glass order that cycles back to ORDERED on a
coating re-fire."""
import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_RECERTIFY_DAY, USER_IDS
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["cw_project_manager_headers"]
DETAILER = TEST_USERS["cw_detailer_headers"]
PROCUREMENT = TEST_USERS["glazing_procurement_headers"]


class TestSubmittalEscalationBoundary:
    """Two returns revise; the third escalates instead."""

    def test_third_return_for_revision_escalates_and_freezes_the_package(self):
        """The first two REVISION_REQUIRED decisions land on REVISION_REQUIRED;
        the decision recorded while revision_cycle is 3 lands on ESCALATED and
        drives the package's posture to FROZEN.

        PRD: "`REVISION_REQUIRED` while the submittal's `revision_cycle` is 3 or more moves it `UNDER_REVIEW` → `ESCALATED` instead, sets `review_decision` to `REVISION_REQUIRED`, and records the payload's `escalation_ref` as the delegated-design dispute reference when one is supplied."

        Design: Difficulty/non_linear_state_machine/submittal_third_return_escalates_instead_of_revising
        """
        ctx = fx.new_project()
        fx.create_submittal(ctx)
        fx.seal_submittal(ctx)
        fx.start_review(ctx)
        first = fx.review_submittal(ctx, "REVISION_REQUIRED")
        assert first["state"] == "REVISION_REQUIRED"
        assert first["revision_cycle"] == 1

        fx.resubmit_submittal(ctx, "SD-002")
        fx.seal_submittal(ctx)
        fx.start_review(ctx)
        second = fx.review_submittal(ctx, "REVISION_REQUIRED")
        assert second["state"] == "REVISION_REQUIRED"
        assert second["revision_cycle"] == 2

        fx.resubmit_submittal(ctx, "SD-003")
        fx.seal_submittal(ctx)
        fx.start_review(ctx)
        third = fx.review_submittal(ctx, "REVISION_REQUIRED")

        assert third["state"] == "ESCALATED"
        assert third["review_decision"] == "REVISION_REQUIRED"
        assert third["revision_cycle"] == 3

        package = get_success_data(api_client.get_facade_package(ctx["package_id"], PM))
        assert package["engineering_posture"] == "FROZEN"
        assert package["blocking_submittal_count"] == 1

    def test_escalated_resubmittal_needs_a_dispute_reference_and_is_never_terminal(self):
        """An escalated submittal refuses a bare resubmittal with
        ERR_DISPUTE_REF_REQUIRED rather than a terminal-state error, and accepts
        the same call once the dispute reference is supplied.

        PRD: "An escalated submittal resubmitted without that reference is refused with `ERR_DISPUTE_REF_REQUIRED`."

        Design: Difficulty/non_linear_state_machine/submittal_third_return_escalates_instead_of_revising
        """
        ctx = fx.setup_escalated_submittal()
        submittal_id = ctx["submittal_id"]
        assert ctx["submittal"]["state"] == "ESCALATED"

        refused = api_client.resubmit_submittal(
            submittal_id, f.resubmit_payload("SD-004"), DETAILER
        )
        validate_error(
            refused, ApiErrorId.ERR_DISPUTE_REF_REQUIRED.value, expected_status=409
        )
        assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_TERMINAL_STATE.value

        accepted = api_client.resubmit_submittal(
            submittal_id,
            f.resubmit_payload("SD-004", dispute_resolution_ref="DRB-2026-11"),
            DETAILER,
        )
        submittal = validate_success(accepted, expected_status=200)
        assert submittal["state"] == "SUBMITTED"
        assert submittal["revision_cycle"] == 4
        assert submittal["sealed_by_user_id"] is None
        assert submittal["seal_license_no"] is None
        assert submittal["sealed_at"] is None


class TestZoneAxesAndRecertification:
    """The erection axis and the weather axis move independently, and the
    weather axis can be walked more than once."""

    def test_failed_water_retest_reverts_only_the_weather_axis(self):
        """A failed water test drops the zone to REMEDIATION and clears its
        certified line while install_status stays PANELS_HUNG with its original
        hang_completed_at.

        PRD: "Hanging panels never touches `weather_status`; certifying weather-tightness never touches `install_status`."

        Design: Difficulty/non_linear_state_machine/zone_install_and_weather_axes_advance_independently_with_recertification
        """
        ctx = fx.setup_certified_zone()
        zone_id = ctx["zone_ids"][0]
        hung = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert hung["hang_completed_at"] == "2026-08-10T09:00:00.000Z"

        fx.set_clock(CLOCK_RECERTIFY_DAY)
        retest = fx.schedule_field_test(
            ctx, zone_id, "WATER_AAMA_501_2", CLOCK_RECERTIFY_DAY, attempt_no=2
        )
        result = fx.record_field_test(
            ctx, retest["id"], f.water_result_payload(True), USER_IDS["QC_2"]
        )
        assert result["state"] == "FAILED"
        assert result["outcome_reason"] == "WATER_PENETRATION"

        zone = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert zone["weather_status"] == "REMEDIATION"
        assert zone["weather_tight_at"] is None
        assert zone["certified_line_cents"] is None
        assert zone["install_status"] == "PANELS_HUNG"
        assert zone["hang_completed_at"] == hung["hang_completed_at"]

        read = get_success_data(api_client.get_earned_value(ctx["package_id"], PM))
        assert read["earned_value_certified_cents"] == 0

    def test_recertification_after_remediation_advances_the_cycle_count_to_two(self):
        """Closing the field-test defect and passing a fresh water test lets the
        zone walk REMEDIATION back to WEATHER_TIGHT, taking
        weather_tight_cycle_count to 2 without ever decrementing it.

        PRD: "Note that `weather_tight_cycle_count` is a running total of certifications and is never decremented by a revert."

        Design: Difficulty/non_linear_state_machine/zone_install_and_weather_axes_advance_independently_with_recertification
        """
        ctx = fx.setup_certified_zone()
        zone_id = ctx["zone_ids"][0]

        fx.set_clock(CLOCK_RECERTIFY_DAY)
        retest = fx.schedule_field_test(
            ctx, zone_id, "WATER_AAMA_501_2", CLOCK_RECERTIFY_DAY, attempt_no=2
        )
        fx.record_field_test(ctx, retest["id"], f.water_result_payload(True), USER_IDS["QC_2"])

        defects = get_success_data(
            api_client.list_defect_items(PM, params={"zone_id": zone_id})
        )
        assert len(defects) == 1
        defect = defects[0]
        assert defect["raised_by_user_id"] == USER_IDS["QC_2"]
        fx.submit_remediation(ctx, defect["id"])
        closed = fx.reinspect_defect(ctx, defect["id"], "PASS", USER_IDS["QC_1"])
        assert closed["status"] == "CLOSED"

        third = fx.schedule_field_test(
            ctx, zone_id, "WATER_AAMA_501_2", CLOCK_RECERTIFY_DAY, attempt_no=3
        )
        passed = fx.record_field_test(
            ctx, third["id"], f.water_result_payload(False), USER_IDS["QC_2"]
        )
        assert passed["state"] == "PASSED"

        zone = get_success_data(
            api_client.certify_weather_tight(zone_id, f.certify_weather_tight_payload(), PM)
        )
        assert zone["weather_status"] == "WEATHER_TIGHT"
        assert zone["weather_tight_cycle_count"] == 2
        assert zone["weather_tight_at"] == "2026-08-14T09:00:00.000Z"
        assert zone["certified_line_cents"] == 58266376
        assert zone["final_labor_cost_cents"] == 1149540
        assert zone["install_status"] == "PANELS_HUNG"

        package = get_success_data(api_client.get_facade_package(ctx["package_id"], PM))
        assert package["earned_value_certified_cents"] == 55353057
        assert package["state"] == "WEATHER_TIGHT_ACHIEVED"


class TestGlassOrderCoatingRefireCycle:
    """A coating revision is a backward edge that can revoke live work."""

    @staticmethod
    def _order_in_production_with_release(quoted_lead_time_days=96):
        ctx = fx.setup_qualified_package()
        fx.add_approved_submittal(ctx)
        fx.create_glass_order(
            ctx, quoted_lead_time_days=quoted_lead_time_days, ordered_lites=240
        )
        fx.start_glass_production(ctx)
        fx.add_zone_a(ctx)
        fx.create_release(ctx)
        return ctx

    def test_coating_revision_cycles_the_order_back_to_ordered_and_rescores_it(self):
        """The re-fire edge returns an IN_PRODUCTION order to ORDERED, counts the
        revision, adds the 21-day penalty and pushes the risk flag true.

        PRD: "A **coating revision** is more disruptive: it is the cycle edge that sends the order back `IN_PRODUCTION` → `ORDERED` for a re-fire."

        Design: Difficulty/non_linear_state_machine/glass_order_returns_to_ordered_on_coating_re_fire
        """
        ctx = self._order_in_production_with_release()
        before = fx.refresh_glass_order(ctx)
        assert before["state"] == "IN_PRODUCTION"
        assert before["risk_score"] == pytest.approx(52.46, abs=0.01)
        assert before["risk_flag"] is False

        response = api_client.revise_coating(
            ctx["glass_order_id"],
            f.coating_revision_payload("LOWE-452", re_fire_required=True),
            PROCUREMENT,
        )
        order = validate_success(response, expected_status=200)

        assert order["state"] == "ORDERED"
        assert order["coating_code"] == "LOWE-452"
        assert order["coating_revision_count"] == 1
        assert order["re_fire_required"] is True
        assert order["risk_variant"] == "EXPEDITE_ADJUSTED"
        assert order["effective_lead_days"] == 117
        assert order["risk_score"] == pytest.approx(71.07, abs=0.01)
        assert order["risk_flag"] is True

    def test_flipping_the_risk_flag_revokes_the_release_and_holds_its_lot(self):
        """Because the rescoring flips risk_flag to true, the live release is
        revoked for GLASS_RE_FIRE and its batched lot is put on hold with its
        prior status recorded; a fresh release is then refused outright.

        PRD: "When and only when that recomputation **flips `risk_flag` to true**, the coating revision runs a two-hop cascade: first, every fabrication release drawing on this order whose state is `RELEASED` transitions to `REVOKED` with `revoked_reason` `GLASS_RE_FIRE`; second, caused by that, every panel lot of each revoked release whose `fabrication_status` is `BATCHED` or `GLAZED` records that value into `status_before_hold` and transitions to `ON_HOLD` with `hold_reason` `GLASS_RE_FIRE`."

        Design: Difficulty/non_linear_state_machine/glass_order_returns_to_ordered_on_coating_re_fire
        """
        ctx = self._order_in_production_with_release()
        zone_id = ctx["zone_ids"][0]
        lot_id = ctx["lots"][zone_id][0]["id"]

        api_client.revise_coating(
            ctx["glass_order_id"],
            f.coating_revision_payload("LOWE-452", re_fire_required=True),
            PROCUREMENT,
        )

        release = get_success_data(
            api_client.get_fabrication_release(ctx["release_id"], PM)
        )
        assert release["state"] == "REVOKED"
        assert release["revoked_reason"] == "GLASS_RE_FIRE"

        lot = get_success_data(api_client.get_panel_lot(lot_id, PM))
        assert lot["fabrication_status"] == "ON_HOLD"
        assert lot["hold_reason"] == "GLASS_RE_FIRE"
        assert lot["status_before_hold"] == "BATCHED"

        order = fx.refresh_glass_order(ctx)
        assert order["committable_lites"] == 240
        assert order["allocated_lites"] == 72
        assert order["breakage_stock_lites"] == 0
        assert order["unallocated_lites"] == 168

        refused = api_client.create_fabrication_release(
            f.create_fabrication_release_payload(
                ctx["package_id"],
                ctx["submittal_id"],
                ctx["glass_order_id"],
                [zone_id],
                fx.package_version(ctx),
            ),
            PM,
        )
        validate_error(
            refused,
            ApiErrorId.ERR_GLASS_RISK_THRESHOLD_EXCEEDED.value,
            expected_status=422,
        )
