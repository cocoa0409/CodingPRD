"""Shift scheduling: initial state, structural bounds, overlap and rolling caps,
staffing-ratio adequacy, termination cascade, and the compliance read endpoint."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_shift_payload, create_home, add_caregiver, create_licensed_home,
    setup_admitted_resident, create_shift_for, set_clock, fresh_caregiver,
    fresh_shift, TEST_USERS,
)

PROVIDER = TEST_USERS["provider_headers"]
NURSE = TEST_USERS["nurse_headers"]


class TestShiftCreation:
    def test_shift_created_in_scheduled_initial_state(self, api):
        """PRD §3.5: "A shift begins `SCHEDULED`."

        Design: Corner/state_machines/shift_created_in_scheduled_initial_state
        """
        home = create_home(name="Shift Init", licensed_bed_capacity=4)
        caregiver = add_caregiver(home["id"], full_name="Cg SI")
        shift = validate_success(api.create_shift(
            create_shift_payload(home["id"], caregiver["id"],
                                 "2026-06-01T13:00:00Z", "2026-06-01T21:00:00Z",
                                 caregiver["version"]),
            PROVIDER), 201)
        assert shift["status"] == "SCHEDULED"
        assert shift["version"] == 1

    def test_shift_create_increments_caregiver_version(self, api):
        """PRD §3.5: "A `Provider` schedules a shift with `home_id`, `caregiver_id`,
        `start_at`, `end_at`, an optional `overnight_mode`, and the OCC field
        `expected_caregiver_version` described in §2.7; creating the shift increments
        the caregiver's `version`."

        Design: Corner/state_machines/shift_created_in_scheduled_initial_state
        """
        home = create_home(name="Shift Init", licensed_bed_capacity=4)
        caregiver = add_caregiver(home["id"], full_name="Cg SI")
        before = caregiver["version"]
        create_shift_for(home["id"], caregiver["id"],
                         "2026-06-01T13:00:00Z", "2026-06-01T21:00:00Z")
        after = fresh_caregiver(caregiver["id"])
        assert after["version"] == before + 1, \
            "the OCC-guarded shift create must bump the caregiver's version"

    def test_shift_end_not_after_start_rejected(self, api):
        """PRD §2.6: "A shift's `end_at` must be strictly after its `start_at`, and a
        single shift's duration may not exceed sixteen hours."
        PRD §2.9: "Structural payload validity — a missing required field, a wrong
        type, an enum outside its declared set, or an inverted range such as a
        `period_end` not after its `period_start` or an `end_at` not after its
        `start_at`; failure yields `ERR_INVALID_REQUEST`."

        Design: Corner/entities/shift_end_not_after_start_rejected
        """
        home = create_home(name="Corner Fir", licensed_bed_capacity=4)
        caregiver = add_caregiver(home["id"], full_name="Cg Fir")
        res = api.create_shift(
            create_shift_payload(home["id"], caregiver["id"],
                                 "2026-06-01T13:00:00Z", "2026-06-01T13:00:00Z",
                                 caregiver["version"]),
            PROVIDER)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_occ_stale_caregiver_version_rejected(self, api):
        """PRD §2.7: "A `POST /api/shifts` request must carry
        `expected_caregiver_version` equal to the caregiver's current `version`. A
        credential or status change (for example a suspension) may have landed since
        the client last observed the caregiver, so the stale write is refused with
        `ERR_STALE_VERSION` (HTTP 412) rather than silently re-validated against old
        data."

        Design: Corner/cross_cutting_layers/occ_shift_create_stale_caregiver_version
        """
        home = create_home(name="OCC Shift", licensed_bed_capacity=4)
        caregiver = add_caregiver(home["id"], full_name="Cg OCC",
                                  awake_overnight_qualified=True)
        stale_version = caregiver["version"]
        first = api.create_shift(
            create_shift_payload(home["id"], caregiver["id"],
                                 "2026-06-01T13:00:00Z", "2026-06-02T05:00:00Z",
                                 stale_version),
            PROVIDER)
        validate_success(first, 201)
        res = api.create_shift(
            create_shift_payload(home["id"], caregiver["id"],
                                 "2026-06-03T13:00:00Z", "2026-06-04T05:00:00Z",
                                 stale_version),
            PROVIDER)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestCaregiverTemporalOverlap:
    def test_back_to_back_shifts_accepted(self, api):
        """PRD §3.5: "First, strict half-open overlap: the new shift conflicts with
        an existing `SCHEDULED` shift of the same caregiver when the new shift starts
        before the existing one ends and the existing one starts before the new one
        ends. Back-to-back shifts, where one ends exactly when the other begins, do
        not conflict."

        Design: Difficulty/resource_temporal_overlap/caregiver_overlap_touch_allowed_rolling16_accumulates
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Larch AFH", bed_label="1A",
                                   caregiver_awake=True)
        home, caregiver = ctx["home"], ctx["caregiver"]
        # Both shifts cover overnight local hours, so overnight_mode is supplied.
        shift1 = create_shift_for(home["id"], caregiver["id"],
                                  "2026-06-01T00:00:00Z", "2026-06-01T08:00:00Z",
                                  overnight_mode="AWAKE")
        shift2 = create_shift_for(home["id"], caregiver["id"],
                                  "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                  overnight_mode="AWAKE")
        assert shift1["status"] == "SCHEDULED"
        assert shift2["status"] == "SCHEDULED", (
            "a shift starting exactly when the other ends touches but does not "
            "overlap; it must be accepted")

    def test_rolling_16h_cap_accumulates_touching_intervals(self, api):
        """PRD §3.5: "Second, aggregate capacity: the caregiver's total `SCHEDULED`
        hours within any rolling twenty-four-hour window must not exceed sixteen —
        the window slides in one-minute steps, so touching intervals still accumulate
        toward the cap. Either violation is rejected with `ERR_SHIFT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/caregiver_overlap_touch_allowed_rolling16_accumulates
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Larch AFH", bed_label="1A",
                                   caregiver_awake=True)
        home, caregiver = ctx["home"], ctx["caregiver"]
        create_shift_for(home["id"], caregiver["id"],
                         "2026-06-01T00:00:00Z", "2026-06-01T08:00:00Z",
                         overnight_mode="AWAKE")
        create_shift_for(home["id"], caregiver["id"],
                         "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                         overnight_mode="AWAKE")
        caregiver_now = fresh_caregiver(caregiver["id"])
        res = api.create_shift(
            create_shift_payload(home["id"], caregiver["id"],
                                 "2026-06-01T16:01:00Z", "2026-06-02T04:01:00Z",
                                 caregiver_now["version"],
                                 overnight_mode="AWAKE"),
            PROVIDER)
        validate_error(res, ApiErrorId.ERR_SHIFT_CONFLICT, expected_status=409)


class TestStaffingRatioEnforcement:
    def test_understaffed_on_shift_create_overnight(self, api):
        """PRD §3.5: "An overnight segment — any overlap with 22:00–06:00 — passes in
        either of two ways: the number of covering `AWAKE` shifts staffed by
        `awake_overnight_qualified` caregivers is at least the census divided by two,
        rounded up; or at least one awake-overnight-qualified caregiver covers the
        segment and the total on-duty count is at least the census divided by three,
        rounded up, which is the mixed `AWAKE`/`ASLEEP` staffing pattern."
        PRD §3.5: "Creating a shift is rejected with `ERR_UNDERSTAFFED` whenever its
        addition would leave any currently occupied hour — an hour during which the
        home's census is above zero — non-compliant, and cancelling a shift is
        rejected with `ERR_UNDERSTAFFED` whenever its removal would do the same."

        Design: Corner/errors/err_understaffed_on_shift_create
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = setup_admitted_resident(caregiver_awake=False)
        home, caregiver = ctx["home"], ctx["caregiver"]
        caregiver_now = fresh_caregiver(caregiver["id"])
        res = api.create_shift(
            create_shift_payload(home["id"], caregiver["id"],
                                 "2026-06-02T05:00:00Z", "2026-06-02T13:00:00Z",
                                 caregiver_now["version"], overnight_mode="AWAKE"),
            PROVIDER)
        validate_error(res, ApiErrorId.ERR_UNDERSTAFFED, expected_status=422)

    def test_understaffed_on_shift_cancel(self, api):
        """PRD §3.5: "Creating a shift is rejected with `ERR_UNDERSTAFFED` whenever
        its addition would leave any currently occupied hour — an hour during which
        the home's census is above zero — non-compliant, and cancelling a shift is
        rejected with `ERR_UNDERSTAFFED` whenever its removal would do the same."
        PRD §3.5: "A day segment — one touching the 06:00–22:00 local window and not
        touching the 22:00–06:00 overnight window — requires on-duty coverage of at
        least the census divided by four, rounded up to a whole caregiver."

        Design: Corner/errors/err_understaffed_on_shift_cancel
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = setup_admitted_resident()
        home, caregiver = ctx["home"], ctx["caregiver"]
        shift = create_shift_for(home["id"], caregiver["id"],
                                 "2026-06-02T13:00:00Z", "2026-06-03T05:00:00Z")
        res = api.cancel_shift(shift["id"], PROVIDER)
        validate_error(res, ApiErrorId.ERR_UNDERSTAFFED, expected_status=422)
        assert fresh_shift(shift["id"])["status"] == "SCHEDULED", \
            "a rejected cancellation must leave the shift SCHEDULED"

    def test_staffing_compliance_endpoint_reports_segments(self, api):
        """PRD §3.5: "For forward visibility, a `Provider` or `Nurse` can run the
        same ratio evaluation over a supplied window from `from_iso8601` to
        `to_iso8601` and receive the per-segment results as `segments` together with
        an overall `compliant` flag."

        Design: Corner/endpoints/staffing_compliance_endpoint_reports_segments
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = setup_admitted_resident()
        home, caregiver = ctx["home"], ctx["caregiver"]
        create_shift_for(home["id"], caregiver["id"],
                         "2026-06-02T13:00:00Z", "2026-06-03T05:00:00Z")
        day = validate_success(api.get_staffing_compliance(
            home["id"], PROVIDER,
            params={"from_iso8601": "2026-06-02T14:00:00Z",
                    "to_iso8601": "2026-06-02T20:00:00Z"}), 200)
        assert day["compliant"] is True, (
            "covered day window with on-duty 1 >= ceil(1/4) must report compliant")
        night = validate_success(api.get_staffing_compliance(
            home["id"], PROVIDER,
            params={"from_iso8601": "2026-06-03T06:00:00Z",
                    "to_iso8601": "2026-06-03T12:00:00Z"}), 200)
        assert night["compliant"] is False, (
            "uncovered overnight window with census 1 must report non-compliant")


class TestCaregiverTermination:
    def test_terminate_cancels_future_shifts(self, api):
        """PRD §3.1: "Termination — from `ACTIVE` or `SUSPENDED` to the terminal
        `TERMINATED` — immediately cancels all of the caregiver's future `SCHEDULED`
        shifts, meaning those whose `start_at` lies after the current logical time."

        Design: Corner/state_machines/caregiver_terminate_cancels_future_shifts
        """
        set_clock("2026-05-20T00:00:00Z")
        home = create_home(name="Term Casc", licensed_bed_capacity=4)
        caregiver = add_caregiver(home["id"], full_name="Cg TC")
        shift = create_shift_for(home["id"], caregiver["id"],
                                 "2026-06-01T13:00:00Z", "2026-06-02T05:00:00Z")
        terminated = validate_success(
            api.terminate_caregiver(caregiver["id"], PROVIDER), 200)
        assert terminated["status"] == "TERMINATED"
        shift_after = fresh_shift(shift["id"])
        assert shift_after["status"] == "CANCELLED", \
            "the future SCHEDULED shift must be cancelled by the termination cascade"
