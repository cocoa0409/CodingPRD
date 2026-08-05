"""Inspection/meter-set scheduling, overlap rules, cascades, and cross-entity guards."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    approved_application, setup_meter_set_installed, ensure_meter_schedule,
    create_application, create_inspector, create_meter_crew,
    create_inspection, create_scheduled_inspection, create_scheduled_meter_set,
    create_meter_set_payload,
    make_field_inspector_headers, TEST_USERS, api_client,
)

FI = TEST_USERS["field_inspector_headers"]


def _fih(inspector_id):
    return make_field_inspector_headers(inspector_id)


class TestInspectionReinspectionCycle:
    """Inspection is cyclic: IN_PROGRESS -> FAILED -> SCHEDULED -> IN_PROGRESS."""

    def _failed_inspection(self):
        ensure_meter_schedule()
        app = create_application(parcel_id="APN-I")
        inspector = create_inspector(name="Insp Cyc")
        hdr = _fih(inspector["id"])
        insp = create_scheduled_inspection(app["id"], inspector["id"], "TAP",
                                           "2026-06-01T09:00:00Z", "2026-06-01T10:00:00Z")
        api_client.start_inspection(insp["id"], hdr)
        api_client.fail_inspection(insp["id"], hdr)
        return insp["id"], inspector["id"]

    def test_reschedule_from_failed(self, api):
        """PRD §3.5: "A `FieldInspector` schedules it, transitioning `REQUESTED → SCHEDULED`;
        the same schedule action also serves the reinspection loop, taking a `FAILED` inspection
        back to `SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/inspection_reinspection_cycle
        """
        insp_id, inspector_id = self._failed_inspection()
        rescheduled = validate_success(api.schedule_inspection(
            insp_id, _fih(inspector_id),
            {"scheduled_start": "2026-06-02T09:00:00Z", "scheduled_end": "2026-06-02T10:00:00Z"}), 200)
        assert rescheduled["status"] == "SCHEDULED"

    def test_restart_after_reschedule(self, api):
        """PRD §3.5: "Once scheduled, the assigned inspector starts the inspection,
        transitioning `SCHEDULED → IN_PROGRESS` (permitted only when the acting `FieldInspector`
        is the assigned `inspector_id`)".

        Design: Difficulty/non_linear_state_machine/inspection_reinspection_cycle
        """
        insp_id, inspector_id = self._failed_inspection()
        api.schedule_inspection(insp_id, _fih(inspector_id),
                                {"scheduled_start": "2026-06-02T09:00:00Z",
                                 "scheduled_end": "2026-06-02T10:00:00Z"})
        started = validate_success(api.start_inspection(insp_id, _fih(inspector_id)), 200)
        assert started["status"] == "IN_PROGRESS"


class TestMeterSetPassDepth2Cascade:
    """Passing a METER_SET inspection: meter set SET -> INSTALLED bubbles the application
    APPROVED -> READY_FOR_ACTIVATION."""

    def test_meter_set_reaches_installed(self, api):
        """PRD §3.5: "A `METER_SET` inspection passing advances the application's meter set from
        `SET` to `INSTALLED`, which in turn bubbles the application from `APPROVED` to
        `READY_FOR_ACTIVATION`."

        Design: Difficulty/transitive_cascade/meterset_pass_depth2_cascade
        """
        app = approved_application(service_type="WATER", use_type="RESIDENTIAL", parcel_id="APN-F")
        ctx = setup_meter_set_installed(app)
        api.pass_inspection(ctx["meter_set_inspection_id"], _fih(ctx["inspector_id"]))
        meter_set = validate_success(api.get_meter_set(ctx["meter_set_id"], FI), 200)
        assert meter_set["status"] == "INSTALLED"

    def test_application_bubbles_to_ready(self, api):
        """PRD §2.7: "when a meter-set inspection passes, the application's meter set is advanced
        from `SET` to `INSTALLED`, and that meter set reaching `INSTALLED` bubbles the
        application up from `APPROVED` to `READY_FOR_ACTIVATION`."

        Design: Difficulty/transitive_cascade/meterset_pass_depth2_cascade
        """
        app = approved_application(service_type="WATER", use_type="RESIDENTIAL", parcel_id="APN-F2")
        ctx = setup_meter_set_installed(app)
        api.pass_inspection(ctx["meter_set_inspection_id"], _fih(ctx["inspector_id"]))
        updated = validate_success(api.get_application(app["id"], TEST_USERS["reviewer_headers"]), 200)
        assert updated["status"] == "READY_FOR_ACTIVATION"


class TestMeterSetInstallRequiresTapPassed:
    """complete-install (SCHEDULED -> SET) requires the application's TAP inspection PASSED."""

    def _scheduled_meterset_with_started_tap(self, parcel):
        app = approved_application(service_type="WATER", use_type="RESIDENTIAL", parcel_id=parcel)
        inspector = create_inspector(name="Insp M")
        crew = create_meter_crew(name="Crew M")
        ms = create_scheduled_meter_set(app["id"], crew["id"], inspector["id"],
                                        "2026-06-03T09:00:00Z", "2026-06-03T10:00:00Z")
        tap = create_scheduled_inspection(app["id"], inspector["id"], "TAP",
                                          "2026-06-01T09:00:00Z", "2026-06-01T10:00:00Z")
        api_client.start_inspection(tap["id"], _fih(inspector["id"]))
        return app, ms, tap, inspector["id"]

    def test_complete_install_before_tap_passed_rejected(self, api):
        """PRD §3.5: "This action requires that the application's `TAP` inspection be `PASSED`,
        or it is rejected with `ERR_INSPECTION_NOT_PASSED` (HTTP 422)".

        Design: Difficulty/cross_entity_state_dependency/meterset_install_requires_tap_inspection_passed
        """
        app, ms, tap, inspector_id = self._scheduled_meterset_with_started_tap("APN-M")
        res = api.complete_install_meter_set(ms["id"], _fih(inspector_id))
        validate_error(res, ApiErrorId.ERR_INSPECTION_NOT_PASSED.value, expected_status=422)

    def test_complete_install_after_tap_passed_succeeds(self, api):
        """PRD §3.5: "A scheduled meter set is installed by a `FieldInspector` via the
        complete-install action, transitioning `SCHEDULED → SET`."

        Design: Difficulty/cross_entity_state_dependency/meterset_install_requires_tap_inspection_passed
        """
        app, ms, tap, inspector_id = self._scheduled_meterset_with_started_tap("APN-M2")
        api.pass_inspection(tap["id"], _fih(inspector_id))
        installed = validate_success(api.complete_install_meter_set(ms["id"], _fih(inspector_id)), 200)
        assert installed["status"] == "SET"


class TestInspectorHalfOpenOverlap:
    """Inspector scheduling uses half-open [start,end): overlap conflicts, adjacency does not."""

    def _inspector_with_scheduled_and_pending(self):
        ensure_meter_schedule()
        app = create_application(parcel_id="APN-N")
        inspector = create_inspector(name="Insp N")
        first = create_scheduled_inspection(app["id"], inspector["id"], "TAP",
                                            "2026-06-01T09:00:00Z", "2026-06-01T10:00:00Z")
        overlap = create_inspection(app["id"], inspector["id"], "TAP",
                                    "2026-06-01T09:30:00Z", "2026-06-01T10:30:00Z")
        adjacent = create_inspection(app["id"], inspector["id"], "TAP",
                                     "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")
        return inspector["id"], overlap["id"], adjacent["id"]

    def test_overlapping_window_rejected(self, api):
        """PRD §3.5: "It further requires that the window not overlap any other `SCHEDULED` or
        `IN_PROGRESS` inspection on the same `inspector_id`; overlap is evaluated on half-open
        intervals, meaning two windows conflict only when the new start is strictly before an
        existing end and the new end is strictly after an existing start ... A conflict is
        rejected with `ERR_INSPECTOR_UNAVAILABLE` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/inspector_half_open_overlap
        """
        inspector_id, overlap_id, _ = self._inspector_with_scheduled_and_pending()
        res = api.schedule_inspection(overlap_id, _fih(inspector_id))
        validate_error(res, ApiErrorId.ERR_INSPECTOR_UNAVAILABLE.value, expected_status=409)

    def test_adjacent_window_accepted(self, api):
        """PRD §3.5: "so windows that merely touch end-to-start do not conflict."

        Design: Difficulty/resource_temporal_overlap/inspector_half_open_overlap
        """
        inspector_id, _, adjacent_id = self._inspector_with_scheduled_and_pending()
        scheduled = validate_success(api.schedule_inspection(adjacent_id, _fih(inspector_id)), 200)
        assert scheduled["status"] == "SCHEDULED"


class TestCrewBufferOverlap:
    """Crew scheduling uses closed interval + 60-minute buffer."""

    def _crew_with_scheduled_and_pending(self):
        ensure_meter_schedule()
        app = create_application(parcel_id="APN-O")
        crew = create_meter_crew(name="Crew O")
        inspector = create_inspector(name="Insp O")
        first = create_scheduled_meter_set(app["id"], crew["id"], inspector["id"],
                                           "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
        too_close = validate_success(api_client.create_meter_set(
            create_meter_set_payload(app["id"], crew["id"],
                                     "2026-06-02T10:30:00Z", "2026-06-02T11:00:00Z"),
            _fih(inspector["id"])), 201)
        far_enough = validate_success(api_client.create_meter_set(
            create_meter_set_payload(app["id"], crew["id"],
                                     "2026-06-02T11:00:00Z", "2026-06-02T12:00:00Z"),
            _fih(inspector["id"])), 201)
        return inspector["id"], too_close["id"], far_enough["id"]

    def test_within_buffer_rejected(self, api):
        """PRD §3.5: "Crew conflicts use a closed interval plus a buffer of 60 minutes (one
        hour): the new appointment conflicts with any `SCHEDULED` or `SET` appointment on the
        same `crew_id` unless the two are separated by at least that buffer ... A conflict is
        rejected with `ERR_CREW_UNAVAILABLE` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/crew_closed_interval_buffer_overlap
        """
        inspector_id, too_close_id, _ = self._crew_with_scheduled_and_pending()
        res = api.schedule_meter_set(too_close_id, _fih(inspector_id))
        validate_error(res, ApiErrorId.ERR_CREW_UNAVAILABLE.value, expected_status=409)

    def test_exact_buffer_gap_accepted(self, api):
        """PRD §3.5: "the new appointment conflicts with any `SCHEDULED` or `SET` appointment on
        the same `crew_id` unless the two are separated by at least that buffer — concretely, a
        conflict exists when the new start is before the existing end extended by the buffer and
        the new end extended by the buffer is after the existing start."

        Design: Difficulty/resource_temporal_overlap/crew_closed_interval_buffer_overlap
        """
        inspector_id, _, far_enough_id = self._crew_with_scheduled_and_pending()
        scheduled = validate_success(api.schedule_meter_set(far_enough_id, _fih(inspector_id)), 200)
        assert scheduled["status"] == "SCHEDULED"


class TestScheduleInvalidWindowBeatsOverlap:
    """A schedule request with a bad window AND an inspector overlap returns ERR_INVALID_WINDOW."""

    def test_invalid_window_and_overlap_returns_window_error(self, api):
        """PRD §3.5: "Scheduling requires the window end to be strictly after the window start,
        or the request is rejected with `ERR_INVALID_WINDOW` (HTTP 422)." PRD §2.10:
        "Business-specific guards — separation of duties, referential prerequisites, safety
        prerequisites, temporal window checks, resource-availability overlap checks, and fiscal
        checks — follow, each described alongside the workflow it guards."

        Design: Difficulty/priority_pair_validation_conflict/schedule_invalid_window_beats_inspector_overlap
        """
        ensure_meter_schedule()
        app = create_application(parcel_id="APN-H")
        inspector = create_inspector(name="Insp H")
        create_scheduled_inspection(app["id"], inspector["id"], "TAP",
                                    "2026-06-01T09:00:00Z", "2026-06-01T10:00:00Z")
        overlap = create_inspection(app["id"], inspector["id"], "TAP",
                                    "2026-06-01T09:30:00Z", "2026-06-01T10:30:00Z")
        # Restated window has end == start (invalid) and also overlaps the SCHEDULED one.
        res = api.schedule_inspection(overlap["id"], _fih(inspector["id"]),
                                      {"scheduled_start": "2026-06-01T09:30:00Z",
                                       "scheduled_end": "2026-06-01T09:30:00Z"})
        validate_error(res, ApiErrorId.ERR_INVALID_WINDOW.value, expected_status=422)

    def test_invalid_window_alone_returns_window_error(self, api):
        """PRD §3.5: "Scheduling requires the window end to be strictly after the window start,
        or the request is rejected with `ERR_INVALID_WINDOW` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/schedule_invalid_window_beats_inspector_overlap
        """
        ensure_meter_schedule()
        app = create_application(parcel_id="APN-H2")
        inspector = create_inspector(name="Insp H2")
        insp = create_inspection(app["id"], inspector["id"], "TAP",
                                 "2026-06-01T09:00:00Z", "2026-06-01T10:00:00Z")
        res = api.schedule_inspection(insp["id"], _fih(inspector["id"]),
                                      {"scheduled_start": "2026-06-01T09:00:00Z",
                                       "scheduled_end": "2026-06-01T09:00:00Z"})
        validate_error(res, ApiErrorId.ERR_INVALID_WINDOW.value, expected_status=422)


def test_meterset_complete_install_from_pending_invalid(api):
    """PRD §3.5: "A scheduled meter set is installed by a `FieldInspector` via the
    complete-install action, transitioning `SCHEDULED → SET`." PRD §2.10: "Next comes the
    state-legality check (`ERR_INVALID_STATE`, HTTP 409), confirming the target resource is in a
    state from which the requested transition is allowed."

    Design: Corner/state_machines/meterset_complete_install_from_pending_invalid
    """
    app = create_application(parcel_id="APN-MS")
    crew = create_meter_crew(name="Crew MS")
    ms = validate_success(api.create_meter_set(
        create_meter_set_payload(app["id"], crew["id"],
                                 "2026-06-03T09:00:00Z", "2026-06-03T10:00:00Z"), FI), 201)
    res = api.complete_install_meter_set(ms["id"], FI)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_backflow_install_then_certify_flow(api):
    """PRD §3.6: "An `Applicant` records installation, transitioning `REQUIRED → INSTALLED` and
    setting the supplied `serial_number` (installation requires a `serial_number` to be
    provided)." PRD §3.6: "Certification is not a direct action: it arrives as the cascade from
    a passing `BACKFLOW` inspection, which advances the assembly from `INSTALLED` to the terminal
    `CERTIFIED` state".

    Design: Corner/state_machines/backflow_install_certify_flow
    """
    app = approved_application(service_type="WATER", use_type="COMMERCIAL", parcel_id="APN-BF")
    applicant = TEST_USERS["applicant_headers"]
    data, _meta = validate_paginated(
        api.list_backflow_assemblies(applicant, params={"application_id": app["id"]}))
    assembly = data[0]
    installed = validate_success(api.install_backflow_assembly(
        assembly["id"], {"serial_number": "BF-123"}, applicant), 200)
    assert installed["status"] == "INSTALLED"
    inspector = create_inspector(name="Insp BF")
    insp = create_scheduled_inspection(app["id"], inspector["id"], "BACKFLOW",
                                       "2026-06-05T09:00:00Z", "2026-06-05T10:00:00Z")
    api.start_inspection(insp["id"], _fih(inspector["id"]))
    api.pass_inspection(insp["id"], _fih(inspector["id"]))
    certified = validate_success(api.get_backflow_assembly(assembly["id"], applicant), 200)
    assert certified["status"] == "CERTIFIED"
