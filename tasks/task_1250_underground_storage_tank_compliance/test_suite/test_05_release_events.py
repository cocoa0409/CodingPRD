"""Suspected releases: reporting deadline, confirm/dismiss gates, cleanup
lifecycle, and the confirm cascade (PRD §3.8)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_owner_headers, assert_ts_equal,
    set_clock, create_facility, create_tank, create_order, schedule_order,
    create_technician, get_order, get_tank, get_deficiency, get_release,
    get_facility, setup_active_facility_with_tank, setup_corrected_deficiency,
    create_release_event_payload,
    api_client,
)

OWNER = TEST_USERS["facility_owner_headers"]
ADMIN = TEST_USERS["contractor_admin_headers"]
REGULATOR = TEST_USERS["state_regulator_headers"]
READER = TEST_USERS["any_headers"]


class TestReportDeadline:
    def test_release_report_deadline_late_and_on_time(self, api):
        """PRD §3.8: "The event enters in `SUSPECTED` status with a
        `report_deadline` of `discovered_at` plus 24 hours" and "either way stamps
        `reported_to_state_at` with the logical clock and computes
        `late_notification` — true only when the report reached the state strictly
        after the 24-hour `report_deadline`."

        Design: Corner/calculations/release_report_deadline_late_and_on_time
        """
        set_clock("2026-05-01T00:00:00Z")
        facility = create_facility(facility_name="Deadline Site")
        rel1 = validate_success(api.create_release_event(
            create_release_event_payload(facility["id"],
                                         discovered_at="2026-05-02T08:00:00Z",
                                         source_description="r1"), OWNER), 201)

        set_clock("2026-05-04T09:00:00Z")  # 49h after discovery
        confirmed = validate_success(api.confirm_release(rel1["id"], REGULATOR), 200)
        assert_ts_equal(confirmed["report_deadline"], "2026-05-03T08:00:00Z",
                        label="report_deadline = discovered_at + 24h")
        assert_ts_equal(confirmed["reported_to_state_at"], "2026-05-04T09:00:00Z",
                        label="reported_to_state_at = logical clock")
        assert confirmed["late_notification"] is True, "49h > 24h -> late"

        rel2 = validate_success(api.create_release_event(
            create_release_event_payload(facility["id"],
                                         discovered_at="2026-05-05T08:00:00Z",
                                         source_description="r2"), OWNER), 201)
        set_clock("2026-05-05T20:00:00Z")  # 12h after discovery
        dismissed = validate_success(api.dismiss_release(rel2["id"], REGULATOR), 200)
        assert_ts_equal(dismissed["report_deadline"], "2026-05-06T08:00:00Z")
        assert dismissed["late_notification"] is False, "12h < 24h -> on time"


class TestConfirmCascade:
    def _setup_cascade(self):
        """Corrected MAJOR deficiency with a SCHEDULED linked re-test (so2), a
        plain SCHEDULED TANK_TIGHTNESS order (so3) on the same tank, and a
        SUSPECTED release linked to the tank."""
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_corrected_deficiency()
        facility, tank = ctx["facility"], ctx["tank"]
        so2 = create_order(facility["id"], tank["id"], "CP_SURVEY",
                           component_id=ctx["component"]["id"],
                           linked_deficiency_id=ctx["deficiency"]["id"],
                           line_items=[{"description": "cp retest", "qty": 1,
                                        "unit_price_cents": 40000}])
        schedule_order(so2["id"], ctx["tester"]["id"],
                       "2026-05-04T10:00:00Z", "2026-05-04T11:00:00Z")
        assert get_deficiency(ctx["deficiency"]["id"])["status"] == "RE_TEST_SCHEDULED"

        t_tt = create_technician(["TIGHTNESS_TESTER"], full_name="Tightness Tester")
        so3 = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS",
                           line_items=[{"description": "tightness", "qty": 1,
                                        "unit_price_cents": 60000}])
        schedule_order(so3["id"], t_tt["id"],
                       "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z")

        release = validate_success(api_client.create_release_event(
            create_release_event_payload(
                facility["id"], tank_system_id=tank["id"],
                discovered_at="2026-05-02T08:00:00Z",
                source_description="fuel odor at dispenser"), OWNER), 201)
        ctx.update({"retest": so2, "tightness": so3, "release": release})
        return ctx

    def test_confirm_closes_tank_and_cancels_orders(self, api):
        """PRD §3.8: "Confirming the release moves it to `CONFIRMED` and triggers
        the tank cascade: when `tank_system_id` is set and that tank is not already
        `PERMANENTLY_CLOSED`, the tank moves to `TEMPORARILY_CLOSED`, its
        `REQUESTED` and `SCHEDULED` orders are cancelled, and their linked re-test
        deficiencies fall back to `CORRECTED`"

        Design: Difficulty/transitive_cascade/release_confirm_cascades_tank_orders_deficiency
        """
        ctx = self._setup_cascade()
        confirmed = validate_success(
            api.confirm_release(ctx["release"]["id"], REGULATOR), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert get_tank(ctx["tank"]["id"])["status"] == "TEMPORARILY_CLOSED", (
            "link 1: confirm closes the source tank")
        assert get_order(ctx["retest"]["id"])["status"] == "CANCELLED"
        assert get_order(ctx["tightness"]["id"])["status"] == "CANCELLED", (
            "link 2: tank closure cancels its SCHEDULED orders")

    def test_confirm_drops_linked_deficiency_back_to_corrected(self, api):
        """PRD §3.8: "their linked re-test deficiencies fall back to `CORRECTED`"
        PRD §3.3: "Cancellation also arrives uninvited through the closure and
        release cascades of §3.2 and §3.8."

        Design: Difficulty/transitive_cascade/release_confirm_cascades_tank_orders_deficiency
        """
        ctx = self._setup_cascade()
        validate_success(api.confirm_release(ctx["release"]["id"], REGULATOR), 200)
        deficiency = get_deficiency(ctx["deficiency"]["id"])
        assert deficiency["status"] == "CORRECTED", (
            "link 3: the cancelled re-test order drops the deficiency out of "
            "RE_TEST_SCHEDULED")


class TestReleaseStateGates:
    def test_confirm_dismissed_release_rejected(self, api):
        """PRD §3.8: "The `StateRegulator` disposes of a suspicion from `SUSPECTED`
        (`ERR_RELEASE_NOT_SUSPECTED` otherwise)" and "Dismissing the release moves
        it to `DISMISSED`, terminal"

        Design: Corner/state_machines/confirm_dismissed_release_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        facility = create_facility(facility_name="Release Gate")
        release = validate_success(api.create_release_event(
            create_release_event_payload(facility["id"], source_description="odor"),
            OWNER), 201)
        validate_success(api.dismiss_release(release["id"], REGULATOR), 200)
        res = api.confirm_release(release["id"], REGULATOR)
        validate_error(res, ApiErrorId.ERR_RELEASE_NOT_SUSPECTED, expected_status=409)

    def test_release_state_transitions_rejected(self, api):
        """PRD §3.8: "the owner moves a `CONFIRMED` release to
        `CLEANUP_IN_PROGRESS` (`ERR_RELEASE_NOT_CONFIRMED` otherwise), and the
        regulator closes it from `CLEANUP_IN_PROGRESS` to `CLOSED`
        (`ERR_RELEASE_NOT_CLEANUP` otherwise)"

        Design: Corner/errors/release_state_transitions_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        facility = create_facility(facility_name="Release States")
        release = validate_success(api.create_release_event(
            create_release_event_payload(facility["id"], source_description="odor"),
            OWNER), 201)

        res = api.begin_cleanup(release["id"], OWNER)
        validate_error(res, ApiErrorId.ERR_RELEASE_NOT_CONFIRMED, expected_status=409)

        validate_success(api.confirm_release(release["id"], REGULATOR), 200)
        res = api.close_release(release["id"], REGULATOR)
        validate_error(res, ApiErrorId.ERR_RELEASE_NOT_CLEANUP, expected_status=409)

    def test_begin_cleanup_then_close_release(self, api):
        """PRD §3.8: "Cleanup proceeds under shared custody: the owner moves a
        `CONFIRMED` release to `CLEANUP_IN_PROGRESS` (`ERR_RELEASE_NOT_CONFIRMED`
        otherwise), and the regulator closes it from `CLEANUP_IN_PROGRESS` to
        `CLOSED` (`ERR_RELEASE_NOT_CLEANUP` otherwise), again lifting the posture
        penalty."

        Design: Corner/endpoints/begin_cleanup_then_close_release
        """
        set_clock("2026-05-01T00:00:00Z")
        facility = create_facility(facility_name="Cleanup Site")
        release = validate_success(api.create_release_event(
            create_release_event_payload(facility["id"], source_description="sheen"),
            OWNER), 201)
        validate_success(api.confirm_release(release["id"], REGULATOR), 200)

        cleaning = validate_success(api.begin_cleanup(release["id"], OWNER), 200)
        assert cleaning["status"] == "CLEANUP_IN_PROGRESS"
        closed = validate_success(api.close_release(release["id"], REGULATOR), 200)
        assert closed["status"] == "CLOSED"
        facility = get_facility(facility["id"])
        assert facility["posture_score"] == 100, (
            "open-release weight 10 restored once the release is CLOSED")
