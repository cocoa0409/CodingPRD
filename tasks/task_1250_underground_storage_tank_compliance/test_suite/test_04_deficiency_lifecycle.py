"""Failure cascades and the deficiency correction / re-test loop (PRD §3.4, §3.5)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_owner_headers, make_technician_headers,
    make_reviewer_headers, assert_ts_equal,
    set_clock, create_order, schedule_order, start_order, record_results,
    certify_order, get_order, get_tank, get_component, get_deficiency,
    get_facility, deficiency_for_order, latest_result_record,
    setup_started_tightness_order, setup_failed_cp_order,
    setup_corrected_deficiency, setup_cp_site, create_started_order,
    tightness_readings, cp_readings, cp_divergence_readings,
    CRITICAL_WEIGHT, OPEN_RELEASE_WEIGHT,
)

OWNER = TEST_USERS["facility_owner_headers"]
ADMIN = TEST_USERS["contractor_admin_headers"]
READER = TEST_USERS["any_headers"]


class TestFailedComponentTestCascade:
    def test_fail_result_opens_major_deficiency(self, api):
        """PRD §3.4: "When a `CP_SURVEY`, `LLD_FUNCTION`, or
        `SPILL_OVERFILL_INSPECTION` order fails, the system instead opens a `MAJOR`
        deficiency of origin `TEST_FAILURE` referencing the tested component, and
        that component moves to `DEFICIENT`."
        PRD §3.4: "The order moves `IN_PROGRESS` → `UNDER_REVIEW`"

        Design: Difficulty/transitive_cascade/failed_component_test_cascades_deficiency_component_posture
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_failed_cp_order()
        order = ctx["order"]
        assert order["status"] == "UNDER_REVIEW"
        assert latest_result_record(order["id"])["outcome"] == "FAIL"
        deficiency = ctx["deficiency"]
        assert deficiency["severity"] == "MAJOR"
        assert deficiency["origin"] == "TEST_FAILURE"
        assert deficiency["component_id"] == ctx["component"]["id"]

    def test_fail_result_marks_component_and_drops_posture(self, api):
        """PRD §3.4: "Whenever any deficiency is created, the facility's
        `posture_score` and `compliance_posture` are recomputed."
        PRD §2.9: "Each deficiency of the facility in `OPEN`, `CORRECTION_ORDERED`,
        `CORRECTED`, `RE_TEST_SCHEDULED`, or `ESCALATED` status subtracts its
        severity weight — 25 points for `CRITICAL`, 15 for `MAJOR`, 5 for `MINOR`"

        Design: Difficulty/transitive_cascade/failed_component_test_cascades_deficiency_component_posture
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_failed_cp_order()
        assert get_component(ctx["component"]["id"])["status"] == "DEFICIENT"
        facility = get_facility(ctx["facility"]["id"])
        assert facility["posture_score"] == 100 - 15, (
            "one open MAJOR deficiency subtracts exactly 15")


class TestTightnessFailureCascade:
    def test_tightness_fail_creates_release_and_closes_tank(self, api):
        """PRD §3.4: "When a `TANK_TIGHTNESS` or `LINE_TIGHTNESS` order fails, the
        system opens a `CRITICAL` deficiency of origin `TEST_FAILURE` with
        `source_service_order_id` pointing at the failing order and no component,
        and simultaneously opens a `SUSPECTED` release event with `discovered_at`
        set to the current clock and `tank_system_id` set to the tested tank. The
        new `CRITICAL` deficiency then drives the tank into `TEMPORARILY_CLOSED`"
        PRD §3.5: "The deadline is the deficiency's `created_at` plus 7 days for
        `CRITICAL`, 30 days for `MAJOR`, or 90 days for `MINOR`, and it never moves
        afterwards."
        PRD §3.8: "The event enters in `SUSPECTED` status with a `report_deadline`
        of `discovered_at` plus 24 hours"
        PRD §2.9: "status subtracts its severity weight — 25 points for `CRITICAL`,
        15 for `MAJOR`, 5 for `MINOR`" and "Each release event of the facility in
        `SUSPECTED`, `CONFIRMED`, or `CLEANUP_IN_PROGRESS` status subtracts 10
        points."

        Design: Corner/state_machines/tightness_fail_creates_release_and_closes_tank
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_started_tightness_order()
        record_results(ctx["order"]["id"], ctx["tester"]["id"],
                       tightness_readings(0.5))  # 0.5 > 0.100 -> FAIL

        deficiency = deficiency_for_order(ctx["order"]["id"])
        assert deficiency["severity"] == "CRITICAL"
        assert deficiency["origin"] == "TEST_FAILURE"
        assert deficiency.get("component_id") is None
        assert_ts_equal(deficiency["correction_deadline"], "2026-05-09T10:30:00Z",
                        label="created_at 2026-05-02T10:30:00Z + 7 days")

        data, meta = validate_paginated(api.list_release_events(
            READER, params={"tank_system_id": ctx["tank"]["id"]}))
        assert meta["total_count"] == 1
        release = data[0]
        assert release["status"] == "SUSPECTED"
        assert_ts_equal(release["report_deadline"], "2026-05-03T10:30:00Z",
                        label="discovered_at + 24 hours")

        assert get_tank(ctx["tank"]["id"])["status"] == "TEMPORARILY_CLOSED"
        facility = get_facility(ctx["facility"]["id"])
        assert facility["posture_score"] == 100 - CRITICAL_WEIGHT - OPEN_RELEASE_WEIGHT == 65
        assert facility["compliance_posture"] == "DEFICIENT"


class TestDeficiencyCorrectionLoop:
    def test_mark_corrected_from_open_rejected(self, api):
        """PRD §3.5: "Once the physical fix is applied, marking corrected moves
        `CORRECTION_ORDERED` → `CORRECTED` (`ERR_DEFICIENCY_NOT_ORDERED`
        otherwise)."

        Design: Corner/state_machines/mark_corrected_from_open_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_failed_cp_order()  # deficiency is OPEN
        res = api.mark_corrected(ctx["deficiency"]["id"], OWNER)
        validate_error(res, ApiErrorId.ERR_DEFICIENCY_NOT_ORDERED, expected_status=409)

    def test_order_correction_from_corrected_rejected(self, api):
        """PRD §3.5: "Ordering correction moves a deficiency from `OPEN` — or from
        `ESCALATED` — to `CORRECTION_ORDERED` (`ERR_DEFICIENCY_NOT_OPEN` from any
        other status)."

        Design: Corner/errors/deficiency_order_correction_from_corrected_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_corrected_deficiency()  # deficiency is CORRECTED
        res = api.order_correction(ctx["deficiency"]["id"], OWNER)
        validate_error(res, ApiErrorId.ERR_DEFICIENCY_NOT_OPEN, expected_status=409)


class TestDeficiencyRetestLoop:
    def _run_first_retest_fail(self):
        """Corrected deficiency -> linked re-test scheduled -> certified FAIL.
        Returns (ctx, retest_order)."""
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_corrected_deficiency()
        retest = create_order(ctx["facility"]["id"], ctx["tank"]["id"], "CP_SURVEY",
                              component_id=ctx["component"]["id"],
                              linked_deficiency_id=ctx["deficiency"]["id"],
                              line_items=[{"description": "cp retest", "qty": 1,
                                           "unit_price_cents": 40000}])
        schedule_order(retest["id"], ctx["tester"]["id"],
                       "2026-05-04T10:00:00Z", "2026-05-04T11:00:00Z")
        ctx["retest"] = retest
        return ctx

    def test_schedule_linked_retest_advances_and_certified_fail_loops_back(self, api):
        """PRD §3.3: "when the order carries a `linked_deficiency_id` whose
        deficiency is `CORRECTED`, that deficiency advances to `RE_TEST_SCHEDULED`
        — the re-test is on the calendar."
        PRD §3.5: "a `FAIL` loops the deficiency back to `CORRECTION_ORDERED` with
        a posture recompute"

        Design: Difficulty/non_linear_state_machine/deficiency_retest_loop_after_failed_verify
        """
        ctx = self._run_first_retest_fail()
        d_id = ctx["deficiency"]["id"]
        assert get_deficiency(d_id)["status"] == "RE_TEST_SCHEDULED", (
            "scheduling the linked re-test advanced CORRECTED")

        start_order(ctx["retest"]["id"], ctx["tester"]["id"], "2026-05-04T10:30:00Z")
        record_results(ctx["retest"]["id"], ctx["tester"]["id"],
                       cp_divergence_readings("INSTANT_OFF"))  # FAIL again
        certify_order(ctx["retest"]["id"], ctx["reviewer"]["id"])
        assert get_deficiency(d_id)["status"] == "CORRECTION_ORDERED", (
            "certified re-test FAIL loops RE_TEST_SCHEDULED back")

    def test_certified_pass_verifies_and_restores_component(self, api):
        """PRD §3.5: "a `PASS` moves the deficiency to `VERIFIED_CLOSED`, records
        the certifying order as `verified_by_service_order_id`, restores any
        referenced component to `IN_SERVICE`, and recomputes the facility posture
        now that the deficiency has left the open set"

        Design: Difficulty/non_linear_state_machine/deficiency_retest_loop_after_failed_verify
        """
        ctx = self._run_first_retest_fail()
        d_id = ctx["deficiency"]["id"]
        start_order(ctx["retest"]["id"], ctx["tester"]["id"], "2026-05-04T10:30:00Z")
        record_results(ctx["retest"]["id"], ctx["tester"]["id"],
                       cp_divergence_readings("INSTANT_OFF"))  # FAIL
        certify_order(ctx["retest"]["id"], ctx["reviewer"]["id"])
        assert get_deficiency(d_id)["status"] == "CORRECTION_ORDERED"

        # Correct again, then a second linked re-test that passes.
        owner = make_owner_headers(ctx["owner_id"])
        validate_success(api.mark_corrected(d_id, owner), 200)
        retest2 = create_order(ctx["facility"]["id"], ctx["tank"]["id"], "CP_SURVEY",
                               component_id=ctx["component"]["id"],
                               linked_deficiency_id=d_id,
                               line_items=[{"description": "cp retest 2", "qty": 1,
                                            "unit_price_cents": 40000}])
        schedule_order(retest2["id"], ctx["tester"]["id"],
                       "2026-05-06T10:00:00Z", "2026-05-06T11:00:00Z")
        start_order(retest2["id"], ctx["tester"]["id"], "2026-05-06T10:30:00Z")
        record_results(retest2["id"], ctx["tester"]["id"], cp_readings())  # PASS
        certify_order(retest2["id"], ctx["reviewer"]["id"])

        deficiency = get_deficiency(d_id)
        assert deficiency["status"] == "VERIFIED_CLOSED"
        assert deficiency["verified_by_service_order_id"] == retest2["id"]
        assert get_component(ctx["component"]["id"])["status"] == "IN_SERVICE", (
            "component restored on verification")
