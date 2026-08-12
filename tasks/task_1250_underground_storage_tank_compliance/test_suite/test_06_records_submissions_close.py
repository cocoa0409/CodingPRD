"""Monthly release-detection records, regulatory submissions, and the monthly
close sweep (PRD §3.6, §3.9)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_owner_headers, make_reviewer_headers,
    assert_ts_equal,
    set_clock, create_facility, create_tank, setup_active_facility_with_tank,
    setup_tightness_site, create_technician, create_order, schedule_order,
    start_order, record_results, create_record, create_monthly_submission,
    create_record_payload, create_submission_payload, tightness_readings,
    MINOR_WEIGHT, ESCALATED_EXTRA,
    get_order,
)

OWNER = TEST_USERS["facility_owner_headers"]
ADMIN = TEST_USERS["contractor_admin_headers"]
REGULATOR = TEST_USERS["state_regulator_headers"]
READER = TEST_USERS["any_headers"]


class TestReleaseDetectionRecords:
    def test_duplicate_release_detection_record_rejected(self, api):
        """PRD §3.6: "The period must not be after the logical clock's current
        month (`ERR_FUTURE_PERIOD`), and only one record may exist per tank and
        period (`ERR_DUPLICATE_RECORD`)."

        Design: Corner/validations/duplicate_release_detection_record_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        facility, tank = setup_active_facility_with_tank()
        create_record(tank["id"], "2026-04", readings_summary={"log": "april"})

        res = api.create_release_detection_record(
            create_record_payload(tank["id"], "2026-04",
                                  readings_summary={"log": "april again"}), OWNER)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_RECORD, expected_status=409)

        other = validate_success(api.create_release_detection_record(
            create_record_payload(tank["id"], "2026-05",
                                  readings_summary={"log": "may"}), OWNER), 201)
        assert other["period_month"] == "2026-05"

        data, meta = validate_paginated(api.list_release_detection_records(
            READER, params={"tank_system_id": tank["id"]}))
        assert meta["total_count"] == 2

    def test_future_period_record_rejected(self, api):
        """PRD §3.6: "The period must not be after the logical clock's current
        month (`ERR_FUTURE_PERIOD`)"

        Design: Corner/validations/future_period_record_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        facility, tank = setup_active_facility_with_tank()

        res = api.create_release_detection_record(
            create_record_payload(tank["id"], "2026-06",
                                  readings_summary={"log": "future"}), OWNER)
        validate_error(res, ApiErrorId.ERR_FUTURE_PERIOD)

        # The clock's own month is not after itself: allowed.
        current = validate_success(api.create_release_detection_record(
            create_record_payload(tank["id"], "2026-05",
                                  readings_summary={"log": "current"}), OWNER), 201)
        assert current["period_month"] == "2026-05"


class TestSubmissionBundles:
    def _setup_under_review_order(self):
        """TANK_TIGHTNESS order driven to UNDER_REVIEW with a PASS result; returns
        (facility, tank, order, reviewer technician)."""
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_tightness_site()
        reviewer = create_technician([], full_name="Rev")
        order = create_order(ctx["facility"]["id"], ctx["tank"]["id"],
                             "TANK_TIGHTNESS")
        schedule_order(order["id"], ctx["tester"]["id"],
                       "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")
        start_order(order["id"], ctx["tester"]["id"], "2026-05-02T10:30:00Z")
        record_results(order["id"], ctx["tester"]["id"], tightness_readings(0.05))
        return ctx["facility"], ctx["tank"], get_order(order["id"]), reviewer

    def test_submission_bundle_requires_certified_orders(self, api):
        """PRD §3.6: "A test report requires `service_order_ids`, every one of
        which must be `CERTIFIED` and belong to the facility." and "A bundle that
        is missing for its type, contains items of another facility, or contains
        items in the wrong state is rejected with `ERR_BUNDLE_ITEM_MISMATCH`."

        Design: Corner/endpoints/submission_bundle_requires_certified_orders
        """
        facility, tank, order, reviewer = self._setup_under_review_order()
        assert order["status"] == "UNDER_REVIEW"
        res = api.create_submission(
            create_submission_payload(facility["id"], "TEST_REPORT",
                                      service_order_ids=[order["id"]]),
            make_reviewer_headers(reviewer["id"]))
        validate_error(res, ApiErrorId.ERR_BUNDLE_ITEM_MISMATCH)

    def test_submission_state_transitions_rejected(self, api):
        """PRD §3.6: "Submitting a draft (`ERR_SUBMISSION_NOT_DRAFT` from any other
        status)" and "The `StateRegulator` then disposes of the filing from
        `SUBMITTED` (`ERR_SUBMISSION_NOT_SUBMITTED` otherwise)."

        Design: Corner/errors/submission_state_transitions_rejected
        """
        set_clock("2026-05-05T00:00:00Z")
        facility, tank = setup_active_facility_with_tank()
        rec = create_record(tank["id"], "2026-04")
        reviewer = create_technician([], full_name="Rev")
        sub = create_monthly_submission(facility["id"], "2026-04", [rec["id"]],
                                        reviewer["id"])

        res = api.accept_submission(sub["id"], REGULATOR)
        validate_error(res, ApiErrorId.ERR_SUBMISSION_NOT_SUBMITTED, expected_status=409)

        validate_success(
            api.submit_submission(sub["id"], make_reviewer_headers(reviewer["id"])), 200)
        res = api.submit_submission(sub["id"], make_reviewer_headers(reviewer["id"]))
        validate_error(res, ApiErrorId.ERR_SUBMISSION_NOT_DRAFT, expected_status=409)


class TestMonthlySubmissionLateFlag:
    def test_monthly_submission_late_flag(self, api):
        """PRD §3.6: "Submitting a draft (`ERR_SUBMISSION_NOT_DRAFT` from any other
        status) stamps `submitted_at` with the logical clock and computes lateness:
        for a monthly filing, `is_late` is true when `submitted_at` falls after the
        period's due timestamp — 23:59:59.999 on the 10th day of the month
        following the `period_month` — and for the other filing types `is_late` is
        false. Submission also moves every bundled release-detection record from
        `RECORDED` to `SUBMITTED`."

        Design: Corner/endpoints/monthly_submission_late_flag
        """
        set_clock("2026-05-05T00:00:00Z")
        facility, tank = setup_active_facility_with_tank()
        rec1 = create_record(tank["id"], "2026-04", readings_summary={"log": "april"})
        reviewer = create_technician([], full_name="Rev")
        rec2 = create_record(tank["id"], "2026-05", readings_summary={"log": "may"})
        rh = make_reviewer_headers(reviewer["id"])

        # Due for 2026-04 is 2026-05-10T23:59:59.999Z; submitting at 23:59:59Z is on time.
        set_clock("2026-05-10T23:59:59Z")
        sub1 = create_monthly_submission(facility["id"], "2026-04", [rec1["id"]],
                                         reviewer["id"])
        submitted1 = validate_success(api.submit_submission(sub1["id"], rh), 200)
        assert_ts_equal(submitted1["submitted_at"], "2026-05-10T23:59:59Z")
        assert submitted1["is_late"] is False

        # Due for 2026-05 is 2026-06-10T23:59:59.999Z; 2026-06-11T00:00:00Z is late.
        sub2 = create_monthly_submission(facility["id"], "2026-05", [rec2["id"]],
                                         reviewer["id"])
        set_clock("2026-06-11T00:00:00Z")
        submitted2 = validate_success(api.submit_submission(sub2["id"], rh), 200)
        assert_ts_equal(submitted2["submitted_at"], "2026-06-11T00:00:00Z")
        assert submitted2["is_late"] is True

        record_after = validate_success(
            api.get_release_detection_record(rec1["id"], READER), 200)
        assert record_after["status"] == "SUBMITTED"


class TestSubmissionLifecycle:
    def test_record_submission_lifecycle_compensation(self, api):
        """PRD §3.6: "Acceptance moves the submission to its terminal `ACCEPTED`
        state and every bundled record to `ACCEPTED`. Rejection takes a `note`,
        stores it as `state_reviewer_note`, moves the submission to `REJECTED`,
        and compensates by returning every bundled record to `RECORDED`. A rejected
        filing is not dead: the reviewer may amend it back to `DRAFT`
        (`ERR_SUBMISSION_NOT_REJECTED` otherwise)"

        Design: Corner/endpoints/record_submission_lifecycle_compensation
        """
        set_clock("2026-05-05T00:00:00Z")
        facility, tank = setup_active_facility_with_tank()
        rec = create_record(tank["id"], "2026-04", readings_summary={"log": "april"})
        reviewer = create_technician([], full_name="Rev")
        rh = make_reviewer_headers(reviewer["id"])
        sub = create_monthly_submission(facility["id"], "2026-04", [rec["id"]],
                                        reviewer["id"])

        validate_success(api.submit_submission(sub["id"], rh), 200)
        rec_state = validate_success(
            api.get_release_detection_record(rec["id"], READER), 200)
        assert rec_state["status"] == "SUBMITTED", "bundle submit propagates"

        rejected = validate_success(api.reject_submission(
            sub["id"], {"note": "missing signature page"}, REGULATOR), 200)
        assert rejected["status"] == "REJECTED"
        assert rejected["state_reviewer_note"] == "missing signature page"
        rec_state = validate_success(
            api.get_release_detection_record(rec["id"], READER), 200)
        assert rec_state["status"] == "RECORDED", "reject compensates the record"

        fresh = validate_success(api.get_submission(sub["id"], READER), 200)
        amended = validate_success(api.amend_submission(
            sub["id"], {"expected_submission_version": fresh["version"]}, rh), 200)
        assert amended["status"] == "DRAFT", "amend re-opens the filing"

        validate_success(api.submit_submission(sub["id"], rh), 200)
        accepted = validate_success(api.accept_submission(sub["id"], REGULATOR), 200)
        assert accepted["status"] == "ACCEPTED"
        rec_state = validate_success(
            api.get_release_detection_record(rec["id"], READER), 200)
        assert rec_state["status"] == "ACCEPTED"

        data, meta = validate_paginated(
            api.list_submissions(READER, params={"facility_id": facility["id"]}))
        assert meta["total_count"] == 1


class TestSubmissionAmendOcc:
    def _setup_rejected_submission(self):
        set_clock("2026-05-05T00:00:00Z")
        facility, tank = setup_active_facility_with_tank()
        rec = create_record(tank["id"], "2026-04", readings_summary={"log": "april"})
        reviewer = create_technician([], full_name="Rev")
        rh = make_reviewer_headers(reviewer["id"])
        sub = create_monthly_submission(facility["id"], "2026-04", [rec["id"]],
                                        reviewer["id"])
        return facility, sub, reviewer, rh

    def test_amend_from_draft_rejected(self, api):
        """PRD §3.6: "A rejected filing is not dead: the reviewer may amend it back
        to `DRAFT` (`ERR_SUBMISSION_NOT_REJECTED` otherwise)"

        Design: Corner/state_machines/amend_from_draft_rejected
        """
        facility, sub, reviewer, rh = self._setup_rejected_submission()
        res = api.amend_submission(
            sub["id"], {"expected_submission_version": sub["version"]}, rh)
        validate_error(res, ApiErrorId.ERR_SUBMISSION_NOT_REJECTED, expected_status=409)

    def test_occ_stale_version_rejected_on_submission_amend(self, api):
        """PRD §2.8: "Amending a rejected regulatory submission requires
        `expected_submission_version` carrying the client's last observed `version`
        of the submission. If the submission's version has advanced since — for
        instance because a `state_reviewer_note` was written after the client last
        read it — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.6: "carrying `expected_submission_version` per §2.8 with stale
        amendments rejected as `ERR_STALE_VERSION`" and "resets `submitted_at` to
        null and `is_late` to false so the filing can be submitted afresh."

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected_on_submission_amend
        """
        facility, sub, reviewer, rh = self._setup_rejected_submission()
        creation_version = sub["version"]
        validate_success(api.submit_submission(sub["id"], rh), 200)
        validate_success(api.reject_submission(
            sub["id"], {"note": "incomplete"}, REGULATOR), 200)

        res = api.amend_submission(
            sub["id"], {"expected_submission_version": creation_version}, rh)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        fresh = validate_success(api.get_submission(sub["id"], READER), 200)
        amended = validate_success(api.amend_submission(
            sub["id"], {"expected_submission_version": fresh["version"]}, rh), 200)
        assert amended["status"] == "DRAFT"
        assert amended["submitted_at"] is None
        assert amended["is_late"] is False


class TestMonthlyClose:
    def test_run_monthly_close_creates_gap_deficiency(self, api):
        """PRD §3.9: "First, the missing-record sweep: for each tank of the
        facility in `IN_SERVICE` or `TEMPORARILY_CLOSED`, taken in `created_at`
        ascending order, if no release-detection record exists for that tank and
        `period_month`, the system opens a `MINOR` deficiency of origin
        `CLOSE_SWEEP` carrying that `period_month`" and "The checkpoint returns the
        counts it produced: `deficiencies_created`, `operators_lapsed`,
        `deficiencies_escalated`, plus the refreshed `posture_score` and
        `compliance_posture`."
        PRD §3.5: "The deadline is the deficiency's `created_at` plus 7 days for
        `CRITICAL`, 30 days for `MAJOR`, or 90 days for `MINOR`"

        Design: Corner/endpoints/run_monthly_close_creates_gap_deficiency
        """
        set_clock("2026-05-01T00:00:00Z")
        facility, tank = setup_active_facility_with_tank()
        set_clock("2026-06-11T00:00:00Z")
        result = validate_success(api.run_monthly_close(
            facility["id"], {"period_month": "2026-05"}, ADMIN), 200)
        assert result["deficiencies_created"] == 1
        assert result["operators_lapsed"] == 0
        assert result["deficiencies_escalated"] == 0
        assert result["posture_score"] == 100 - MINOR_WEIGHT == 95
        assert result["compliance_posture"] == "COMPLIANT"

        data, meta = validate_paginated(api.list_deficiencies(
            READER, params={"facility_id": facility["id"], "status": "OPEN"}))
        assert meta["total_count"] == 1
        deficiency = data[0]
        assert deficiency["severity"] == "MINOR"
        assert deficiency["origin"] == "CLOSE_SWEEP"
        assert deficiency["period_month"] == "2026-05"
        assert deficiency["tank_system_id"] == tank["id"]
        assert_ts_equal(deficiency["correction_deadline"], "2026-09-09T00:00:00Z",
                        label="created 2026-06-11 + MINOR 90 days")

    def test_run_monthly_close_idempotent_rerun(self, api):
        """PRD §3.9: "unless a deficiency with the same tank, origin, and period
        already exists, which makes re-running a close idempotent"

        Design: Corner/endpoints/run_monthly_close_idempotent_rerun
        """
        set_clock("2026-06-11T00:00:00Z")
        facility, tank = setup_active_facility_with_tank()
        validate_success(api.run_monthly_close(
            facility["id"], {"period_month": "2026-05"}, ADMIN), 200)

        second = validate_success(api.run_monthly_close(
            facility["id"], {"period_month": "2026-05"}, ADMIN), 200)
        assert second["deficiencies_created"] == 0, "second sweep is a no-op"
        assert second["posture_score"] == 95, "posture unchanged on idempotent re-run"
        data, meta = validate_paginated(
            api.list_deficiencies(READER, params={"facility_id": facility["id"]}))
        assert meta["total_count"] == 1

    def test_run_monthly_close_too_early_rejected(self, api):
        """PRD §3.9: "the logical clock must be at or after 00:00:00 on the 11th
        day of the month following the `period_month` — earlier runs are rejected
        with `ERR_CLOSE_TOO_EARLY`"

        Design: Corner/endpoints/run_monthly_close_too_early_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        facility, tank = setup_active_facility_with_tank()
        set_clock("2026-06-10T00:00:00Z")  # day 10: one day too early
        res = api.run_monthly_close(facility["id"], {"period_month": "2026-05"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_CLOSE_TOO_EARLY)

    def test_run_monthly_close_escalates_overdue(self, api):
        """PRD §3.9: "Third, the escalation sweep of §3.5 escalates every
        non-terminal deficiency whose `correction_deadline` has passed."
        PRD §3.5: "any deficiency whose correction deadline has passed — the
        logical clock strictly later than `correction_deadline` — and whose status
        is `OPEN`, `CORRECTION_ORDERED`, `CORRECTED`, or `RE_TEST_SCHEDULED`
        escalates to `ESCALATED`, stamping `escalated_at` with the clock and
        recomputing the facility posture with the escalation surcharge."
        PRD §2.9: "an `ESCALATED` deficiency subtracts a further 5 points on top of
        its severity weight"

        Design: Corner/endpoints/run_monthly_close_escalates_overdue
        """
        set_clock("2026-05-01T00:00:00Z")
        facility, tank = setup_active_facility_with_tank()
        set_clock("2026-06-11T00:00:00Z")
        validate_success(api.run_monthly_close(
            facility["id"], {"period_month": "2026-05"}, ADMIN), 200)
        data, _ = validate_paginated(api.list_deficiencies(
            READER, params={"facility_id": facility["id"], "status": "OPEN"}))
        d1 = data[0]
        # D1 deadline: created 2026-06-11 + 90 days = 2026-09-09.

        set_clock("2026-09-20T00:00:00Z")  # past D1's deadline
        result = validate_success(api.run_monthly_close(
            facility["id"], {"period_month": "2026-08"}, ADMIN), 200)
        assert result["deficiencies_created"] == 1, "new MINOR gap for 2026-08"
        assert result["deficiencies_escalated"] == 1, "D1 overdue since 2026-09-09"
        # 100 - 5 (new MINOR) - 5 (D1 MINOR) - 5 (D1 escalation surcharge) = 85.
        assert result["posture_score"] == 100 - 2 * MINOR_WEIGHT - ESCALATED_EXTRA == 85
        assert result["compliance_posture"] == "COMPLIANT"

        escalated = validate_success(api.get_deficiency(d1["id"], READER), 200)
        assert escalated["status"] == "ESCALATED"
        assert_ts_equal(escalated["escalated_at"], "2026-09-20T00:00:00Z",
                        label="escalated_at stamped with the clock")

    def test_empty_facility_close_zero_deficiencies(self, api):
        """PRD §3.9: "First, the missing-record sweep: for each tank of the
        facility in `IN_SERVICE` or `TEMPORARILY_CLOSED`, taken in `created_at`
        ascending order, if no release-detection record exists for that tank and
        `period_month`, the system opens a `MINOR` deficiency" — a tank still
        `REGISTERED` is outside the sweep set.

        Design: Corner/endpoints/empty_facility_close_zero_deficiencies
        """
        set_clock("2026-06-11T00:00:00Z")
        facility = create_facility(facility_name="Empty Sweep")
        create_tank(facility["id"])  # stays REGISTERED, never placed in service
        validate_success(api.activate_facility(facility["id"], OWNER), 200)

        result = validate_success(api.run_monthly_close(
            facility["id"], {"period_month": "2026-05"}, ADMIN), 200)
        assert result["deficiencies_created"] == 0
        assert result["posture_score"] == 100


def get_order_ref(api, order_id):
    return validate_success(api.get_service_order(order_id, READER), 200)
