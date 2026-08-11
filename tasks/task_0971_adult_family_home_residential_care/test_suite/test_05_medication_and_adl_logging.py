"""Medication administration windows, duplicate-dose detection, on-shift rules,
and ADL logging."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_medication_log, assert_same_instant, create_medication_log_payload,
    create_adl_log_payload,
    setup_med_logging_scenario, setup_admitted_resident, set_clock,
    make_caregiver_headers, TEST_USERS,
)

PROVIDER = TEST_USERS["provider_headers"]
NURSE = TEST_USERS["nurse_headers"]

# The home timezone defaults to America/Los_Angeles; in June (PDT, UTC-7) the
# 08:00-local schedule opens the window [14:00Z, 16:00Z).
WINDOW_OPEN_UTC = "2026-06-02T14:00:00Z"     # lower edge (inclusive)
WINDOW_MID_UTC = "2026-06-02T14:30:00Z"
WINDOW_LATE_UTC = "2026-06-02T14:45:00Z"
NEXT_DAY_WINDOW_CLOSE_UTC = "2026-06-03T16:00:00Z"  # upper edge (exclusive)


class TestMedicationWindowBoundaries:
    def test_window_lower_edge_inclusive_accepted(self, api):
        """PRD §3.4: "Each scheduled time T on a local date opens a half-open window
        running from sixty minutes before T — inclusive — to sixty minutes after T —
        exclusive: an administration exactly at the window's lower edge is inside,
        while one exactly at the upper edge is outside."

        Design: Difficulty/boundary_precision_check/med_window_inclusive_lower_exclusive_upper
        """
        ctx = setup_med_logging_scenario(
            shift_windows=(("2026-06-02T13:00:00Z", "2026-06-03T05:00:00Z"),
                           ("2026-06-03T13:00:00Z", "2026-06-04T05:00:00Z")))
        set_clock(WINDOW_OPEN_UTC)
        res = api.create_medication_log(
            create_medication_log_payload(
                ctx["resident"]["id"], ctx["order"]["id"], ctx["caregiver"]["id"],
                WINDOW_OPEN_UTC, outcome="GIVEN"),
            NURSE)
        log = validate_success(res, 201)
        assert_medication_log(log)
        assert_same_instant(log["administered_at"], WINDOW_OPEN_UTC)

    def test_window_upper_edge_exclusive_rejected(self, api):
        """PRD §3.4: "Each scheduled time T on a local date opens a half-open window
        running from sixty minutes before T — inclusive — to sixty minutes after T —
        exclusive: an administration exactly at the window's lower edge is inside,
        while one exactly at the upper edge is outside."
        PRD §3.4: "A window miss or a duplicate dose is rejected with
        `ERR_OUTSIDE_MED_WINDOW`."

        Design: Difficulty/boundary_precision_check/med_window_inclusive_lower_exclusive_upper
        """
        ctx = setup_med_logging_scenario(
            shift_windows=(("2026-06-02T13:00:00Z", "2026-06-03T05:00:00Z"),
                           ("2026-06-03T13:00:00Z", "2026-06-04T05:00:00Z")))
        set_clock(WINDOW_OPEN_UTC)
        validate_success(api.create_medication_log(
            create_medication_log_payload(
                ctx["resident"]["id"], ctx["order"]["id"], ctx["caregiver"]["id"],
                WINDOW_OPEN_UTC, outcome="GIVEN"),
            NURSE), 201)
        set_clock(NEXT_DAY_WINDOW_CLOSE_UTC)
        res = api.create_medication_log(
            create_medication_log_payload(
                ctx["resident"]["id"], ctx["order"]["id"], ctx["caregiver"]["id"],
                NEXT_DAY_WINDOW_CLOSE_UTC, outcome="GIVEN"),
            NURSE)
        validate_error(res, ApiErrorId.ERR_OUTSIDE_MED_WINDOW, expected_status=422)


class TestDuplicateDoseDetection:
    def test_duplicate_given_in_same_window_rejected(self, api):
        """PRD §3.4: "The `administered_at` instant must fall inside at least one
        open window of the order, and no earlier log with outcome `GIVEN` or
        `SELF_ADMINISTERED` may already exist in the same window for the same order —
        that is duplicate-dose detection."
        PRD §3.4: "A window miss or a duplicate dose is rejected with
        `ERR_OUTSIDE_MED_WINDOW`."

        Design: Corner/calculations/duplicate_given_in_same_window_rejected
        """
        ctx = setup_med_logging_scenario()
        set_clock(WINDOW_OPEN_UTC)
        validate_success(api.create_medication_log(
            create_medication_log_payload(
                ctx["resident"]["id"], ctx["order"]["id"], ctx["caregiver"]["id"],
                WINDOW_OPEN_UTC, outcome="GIVEN"),
            NURSE), 201)
        res = api.create_medication_log(
            create_medication_log_payload(
                ctx["resident"]["id"], ctx["order"]["id"], ctx["caregiver"]["id"],
                WINDOW_MID_UTC, outcome="GIVEN"),
            NURSE)
        validate_error(res, ApiErrorId.ERR_OUTSIDE_MED_WINDOW, expected_status=422)

    def test_refused_does_not_consume_window_then_given_accepted(self, api):
        """PRD §3.4: "Outcomes `REFUSED` and `HELD` do not consume a window, so a
        later `GIVEN` inside the same window remains permitted."
        PRD §3.4: "Logging an administration — a `Nurse` or `CaregiverRole` action —
        records `resident_id`, `order_id`, `administered_at`, an `outcome` of
        `GIVEN`, `REFUSED`, `HELD`, or `SELF_ADMINISTERED`, the acting
        `caregiver_id`, and an optional free-text `note` that becomes required
        whenever the outcome is `REFUSED` or `HELD`."

        Design: Corner/calculations/med_window_refused_does_not_consume_window
        """
        ctx = setup_med_logging_scenario()
        set_clock(WINDOW_OPEN_UTC)
        refused = validate_success(api.create_medication_log(
            create_medication_log_payload(
                ctx["resident"]["id"], ctx["order"]["id"], ctx["caregiver"]["id"],
                WINDOW_MID_UTC, outcome="REFUSED", note="Resident refused dose"),
            NURSE), 201)
        assert refused["outcome"] == "REFUSED"
        given = validate_success(api.create_medication_log(
            create_medication_log_payload(
                ctx["resident"]["id"], ctx["order"]["id"], ctx["caregiver"]["id"],
                WINDOW_LATE_UTC, outcome="GIVEN"),
            NURSE), 201)
        assert given["outcome"] == "GIVEN", \
            "REFUSED must not consume the window for a later GIVEN"

    def test_refused_then_given_both_listed_for_order(self, api):
        """PRD §3.4: "Outcomes `REFUSED` and `HELD` do not consume a window, so a
        later `GIVEN` inside the same window remains permitted."
        PRD §4: "Collection endpoints accept `limit` and `offset` for pagination
        plus resource-appropriate filters: `status` on most collections, `payer_type`
        on resident and rate-schedule listings, `severity` on incident listings, and
        the foreign-key filters `resident_id`, `bed_id`, `assessment_id`, `order_id`,
        `caregiver_id`, `home_id`, `incident_id`, and `invoice_id` where a collection
        is reachable through multiple parents."

        Design: Corner/calculations/med_window_refused_does_not_consume_window
        """
        ctx = setup_med_logging_scenario()
        set_clock(WINDOW_OPEN_UTC)
        validate_success(api.create_medication_log(
            create_medication_log_payload(
                ctx["resident"]["id"], ctx["order"]["id"], ctx["caregiver"]["id"],
                WINDOW_MID_UTC, outcome="REFUSED", note="Resident refused dose"),
            NURSE), 201)
        validate_success(api.create_medication_log(
            create_medication_log_payload(
                ctx["resident"]["id"], ctx["order"]["id"], ctx["caregiver"]["id"],
                WINDOW_LATE_UTC, outcome="GIVEN"),
            NURSE), 201)
        data, meta = validate_paginated(
            api.list_medication_logs(PROVIDER,
                                     params={"order_id": ctx["order"]["id"]}))
        assert meta["total_count"] == 2
        assert len(data) == 2


class TestCaregiverOnShiftRule:
    def test_log_rejected_when_caregiver_not_on_shift(self, api):
        """PRD §3.4: "Separately, the caregiver named on the log must hold a
        `SCHEDULED` shift covering `administered_at`, else the log is rejected with
        `ERR_CAREGIVER_NOT_ON_SHIFT`."

        Design: Corner/errors/err_caregiver_not_on_shift_triggered
        """
        ctx = setup_admitted_resident()  # no shifts are ever scheduled
        order_res = api.create_medication_order(
            ctx["resident"]["id"],
            {"drug_name": "Lisinopril", "dose": "5mg oral",
             "schedule_times": ["08:00"]},
            NURSE)
        order = validate_success(order_res, 201)
        set_clock(WINDOW_OPEN_UTC)
        res = api.create_medication_log(
            create_medication_log_payload(
                ctx["resident"]["id"], order["id"], ctx["caregiver"]["id"],
                WINDOW_MID_UTC, outcome="GIVEN"),
            NURSE)
        validate_error(res, ApiErrorId.ERR_CAREGIVER_NOT_ON_SHIFT,
                       expected_status=422)

    def test_caregiver_can_log_adl_when_on_shift(self, api):
        """PRD §3.4: "ADL assistance is logged by a `Nurse` or `CaregiverRole` with
        `resident_id`, an `adl_type` of `BATHING`, `DRESSING`, `GROOMING`,
        `TOILETING`, `TRANSFERRING`, or `EATING`, an `assistance_level` of
        `INDEPENDENT`, `SUPERVISION`, `PARTIAL`, or `FULL`, a `performed_at`
        timestamp, and a `caregiver_id`."
        PRD §2.1: "When `X-User-Role` is `CaregiverRole`, `X-User-ID` is the `id` of
        the acting `Caregiver`; ownership checks on any resource that references a
        caregiver compare the resource's foreign-key field to `X-User-ID`, and a
        missing or unknown caregiver identifier fails authentication."

        Design: Corner/rbac/caregiver_can_log_adl_when_on_shift
        """
        ctx = setup_med_logging_scenario()
        caregiver_headers = make_caregiver_headers(ctx["caregiver"]["id"])
        res = api.create_adl_log(
            create_adl_log_payload(
                ctx["resident"]["id"], ctx["caregiver"]["id"],
                "2026-06-02T15:00:00Z", adl_type="BATHING",
                assistance_level="PARTIAL"),
            caregiver_headers)
        log = validate_success(res, 201)
        assert log["adl_type"] == "BATHING"
        assert log["assistance_level"] == "PARTIAL"


class TestMedicationOrderLifecycle:
    def test_double_discontinue_rejected(self, api):
        """PRD §3.4: "`DISCONTINUED` is terminal, and any attempt to log an
        administration against a discontinued order is rejected with
        `ERR_ORDER_DISCONTINUED`."
        PRD §2.9: "State-machine legality — the target resource is in a from-state
        that permits the transition and is not terminally locked; failure yields
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/medication_order_double_discontinue_rejected
        """
        ctx = setup_admitted_resident()
        order = validate_success(api.create_medication_order(
            ctx["resident"]["id"],
            {"drug_name": "Metformin", "dose": "500mg oral",
             "schedule_times": ["08:00"]},
            NURSE), 201)
        discontinued = validate_success(
            api.discontinue_medication_order(order["id"], NURSE), 200)
        assert discontinued["status"] == "DISCONTINUED"
        res = api.discontinue_medication_order(order["id"], NURSE)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_log_against_discontinued_order_rejected(self, api):
        """PRD §3.4: "`DISCONTINUED` is terminal, and any attempt to log an
        administration against a discontinued order is rejected with
        `ERR_ORDER_DISCONTINUED`."

        Design: Corner/errors/err_order_discontinued_triggered
        """
        ctx = setup_med_logging_scenario()
        validate_success(
            api.discontinue_medication_order(ctx["order"]["id"], NURSE), 200)
        set_clock(WINDOW_OPEN_UTC)
        res = api.create_medication_log(
            create_medication_log_payload(
                ctx["resident"]["id"], ctx["order"]["id"], ctx["caregiver"]["id"],
                WINDOW_MID_UTC, outcome="GIVEN"),
            NURSE)
        validate_error(res, ApiErrorId.ERR_ORDER_DISCONTINUED, expected_status=409)


class TestMedicationLogRecordShape:
    def test_medication_log_is_append_only_without_version(self, api):
        """PRD §2.5: "Four record types are append-only exceptions to this
        convention: a `MedicationLog`, an `ADLLog`, a `Payment`, and a
        `DischargeRecord` each carry only `id` and `created_at`."
        PRD §2.5: "Both `updated_at` and `version` are absent from these four
        resources."

        Design: Corner/entities/medication_log_immutable_no_version_field
        """
        ctx = setup_med_logging_scenario()
        set_clock(WINDOW_OPEN_UTC)
        log = validate_success(api.create_medication_log(
            create_medication_log_payload(
                ctx["resident"]["id"], ctx["order"]["id"], ctx["caregiver"]["id"],
                WINDOW_MID_UTC, outcome="GIVEN"),
            NURSE), 201)
        assert_medication_log(log)  # enforces id + created_at present
        assert "version" not in log, "append-only log must not carry version"
        assert "updated_at" not in log, "append-only log must not carry updated_at"
