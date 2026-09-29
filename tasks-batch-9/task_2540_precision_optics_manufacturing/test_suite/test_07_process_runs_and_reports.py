"""The measurement-driven loop: start, complete, sign and the signing gates."""

from test_helpers import (
    CLOCK_EPOCH_UTC,
    ERR_CLOCK_NOT_MONOTONIC,
    ERR_INSTRUMENT_CALIBRATION_OVERDUE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_REPORT_ALREADY_SIGNED,
    ERR_SEGREGATION_OF_DUTIES,
    MT_CALIBRATOR,
    MT_RECORDER,
    MT_SIGNER,
    QM_PRIMARY,
    assert_booked_minutes,
    assert_instrument_drift,
    assert_null_fields,
    assert_removal_ledger,
    assert_wavefront_value,
    build_calibration_payload,
    build_complete_run_payload,
    build_metrology_report_payload,
    build_process_run_payload,
    create_instrument,
    error_id_of,
    make_metrology_technician_headers,
    make_plant_admin_headers,
    make_process_technician_headers,
    make_quality_manager_headers,
    set_clock,
    setup_work_order,
    validate_error,
    validate_success,
)

OVERDUE_CLOCK_UTC = "2026-11-01T00:00:00Z"


def _read_instrument(api, instrument_id):
    """Read one metrology station as the plant administrator."""
    return validate_success(
        api.get_metrology_instrument(instrument_id, make_plant_admin_headers()),
        expected_status=200,
    )


def _read_order(api, work_order_id):
    """Read one work order as the process technician who owns it."""
    return validate_success(
        api.get_work_order(work_order_id, make_process_technician_headers()),
        expected_status=200,
    )


def _read_run(api, run_id):
    """Read one process run as the process technician who booked it."""
    return validate_success(
        api.get_process_run(run_id, make_process_technician_headers()),
        expected_status=200,
    )


def _read_report(api, report_id):
    """Read one metrology report as the technician who recorded it."""
    return validate_success(
        api.get_metrology_report(report_id, make_metrology_technician_headers(MT_RECORDER)),
        expected_status=200,
    )


def _drafted_report(
    api,
    run_stage="POLISHING",
    surface_rms_waves=0.0200,
    surface_roughness_nm_rms=0.8000,
    material_removed_nm=800.0,
    window=("2026-08-01T08:00:00Z", "2026-08-01T10:00:00Z"),
    **report_overrides,
):
    """A run in AWAITING_METROLOGY carrying one DRAFT report recorded by mt-001."""
    ctx = setup_work_order(api, design_code="OD-2540-MR", lot_code="GL-2540-MR")
    ctx["instrument"] = create_instrument(api, instrument_code="IF-2540-1")
    ctx["run"] = validate_success(
        api.create_process_run(
            build_process_run_payload(
                ctx["work_order"]["id"],
                ctx["instrument"]["id"],
                run_stage=run_stage,
                metrology_window_start_utc=window[0],
                metrology_window_end_utc=window[1],
            ),
            make_process_technician_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.start_process_run(ctx["run"]["id"], make_process_technician_headers()),
        expected_status=200,
    )
    validate_success(
        api.complete_process_run(
            ctx["run"]["id"],
            build_complete_run_payload(material_removed_nm),
            make_process_technician_headers(),
        ),
        expected_status=200,
    )
    ctx["report"] = validate_success(
        api.create_metrology_report(
            build_metrology_report_payload(
                ctx["run"]["id"],
                surface_rms_waves=surface_rms_waves,
                surface_roughness_nm_rms=surface_roughness_nm_rms,
                **report_overrides,
            ),
            make_metrology_technician_headers(MT_RECORDER),
        ),
        expected_status=201,
    )
    return ctx


class TestSegregationOutranksCalibrationOnSign:
    """One signature breaks the identity rule and the calibration rule together."""

    @staticmethod
    def _overdue_station_with_draft_report(api):
        """A DRAFT report whose station is 92 days past a 90-day interval."""
        ctx = _drafted_report(api)
        set_clock(api, OVERDUE_CLOCK_UTC)
        return ctx

    def test_the_recorder_signing_his_own_report_reports_segregation_of_duties(self, api):
        """Priority 12 is adjudicated before priority 16.

        The PRD states that signing "is guarded by four preconditions, evaluated in
        this order: the report must still be in `DRAFT`, otherwise
        `ERR_REPORT_ALREADY_SIGNED`; the run must be in `AWAITING_METROLOGY`,
        otherwise `ERR_INVALID_STATE_TRANSITION`; the acting `X-User-ID` must differ
        from `recorded_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`; and the
        run's station must be `CALIBRATED` at the clock's **current** instant,
        otherwise `ERR_INSTRUMENT_CALIBRATION_OVERDUE`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_calibration_overdue_on_report_sign
        """
        ctx = self._overdue_station_with_draft_report(api)

        refused = api.sign_metrology_report(
            ctx["report"]["id"], make_metrology_technician_headers(MT_RECORDER)
        )

        validate_error(refused, ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        assert error_id_of(refused) != ERR_INSTRUMENT_CALIBRATION_OVERDUE, (
            "the identity gate is adjudicated first, so the calibration code must "
            "not surface"
        )

    def test_a_second_technician_then_surfaces_the_overdue_station(self, api):
        """With the identity gate satisfied, the drift clock is the live defect.

        The PRD states that "`instrument_status` is `OVERDUE` when
        `days_since_calibration` is strictly greater than `calibration_interval_days`,
        and `CALIBRATED` otherwise — so a station exactly at its interval is still
        calibrated, and it becomes overdue on the day after."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_calibration_overdue_on_report_sign
        """
        ctx = self._overdue_station_with_draft_report(api)

        refused = api.sign_metrology_report(
            ctx["report"]["id"], make_metrology_technician_headers(MT_SIGNER)
        )

        validate_error(refused, ERR_INSTRUMENT_CALIBRATION_OVERDUE, expected_status=409)
        instrument = _read_instrument(api, ctx["instrument"]["id"])
        assert_instrument_drift(instrument, 92, 0.002000, "OVERDUE")

    def test_neither_refusal_signs_the_report_or_moves_the_shop_floor(self, api):
        """The report is still unsigned and the run is still awaiting metrology.

        The PRD states that the calibration check "is re-evaluated at signing rather
        than trusted from scheduling, so a station that fell out of calibration while
        the glass was on the machine cannot grade the result."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_calibration_overdue_on_report_sign
        """
        ctx = self._overdue_station_with_draft_report(api)
        api.sign_metrology_report(
            ctx["report"]["id"], make_metrology_technician_headers(MT_RECORDER)
        )
        api.sign_metrology_report(
            ctx["report"]["id"], make_metrology_technician_headers(MT_SIGNER)
        )

        report = _read_report(api, ctx["report"]["id"])
        assert report["report_status"] == "DRAFT", (
            f"report_status must stay DRAFT, got {report['report_status']}"
        )
        assert report["verdict"] == "PENDING", (
            f"verdict must stay PENDING, got {report['verdict']}"
        )
        assert_null_fields(report, "signed_by_user_id", "signed_at_utc", "signature_note")
        assert _read_run(api, ctx["run"]["id"])["run_status"] == "AWAITING_METROLOGY"
        assert _read_order(api, ctx["work_order"]["id"])["process_status"] == "POLISHING"


class TestSignRecoversAfterRecalibration:
    """The signature depends on an entity two hops away, re-read at signing time."""

    @staticmethod
    def _overdue_station_with_draft_report(api):
        """The same 92-day-overdue station holding one DRAFT report."""
        ctx = _drafted_report(api)
        set_clock(api, OVERDUE_CLOCK_UTC)
        return ctx

    def test_the_overdue_station_refuses_the_signature_and_keeps_the_report_draft(
        self, api
    ):
        """Ninety-two days against a ninety-day interval is out of calibration.

        The PRD states that a signature is refused unless "the run's station must be
        `CALIBRATED` at the clock's **current** instant, otherwise
        `ERR_INSTRUMENT_CALIBRATION_OVERDUE`."

        Design: Difficulty/cross_entity_state_dependency/report_sign_requires_instrument_calibrated_and_recovers_after_recalibration
        """
        ctx = self._overdue_station_with_draft_report(api)

        refused = api.sign_metrology_report(
            ctx["report"]["id"], make_metrology_technician_headers(MT_SIGNER)
        )

        validate_error(refused, ERR_INSTRUMENT_CALIBRATION_OVERDUE, expected_status=409)
        report = _read_report(api, ctx["report"]["id"])
        assert report["report_status"] == "DRAFT", (
            f"report_status must stay DRAFT, got {report['report_status']}"
        )
        assert report["verdict"] == "PENDING", (
            f"verdict must stay PENDING, got {report['verdict']}"
        )

    def test_recording_a_calibration_resets_the_drift_curve(self, api):
        """A calibration at the current clock returns the station to zero days.

        The PRD states that "`last_calibrated_utc` is set to that instant, and
        `days_since_calibration`, `effective_uncertainty_waves` and
        `instrument_status` are re-derived from it."

        Design: Difficulty/cross_entity_state_dependency/report_sign_requires_instrument_calibrated_and_recovers_after_recalibration
        """
        ctx = self._overdue_station_with_draft_report(api)
        api.sign_metrology_report(
            ctx["report"]["id"], make_metrology_technician_headers(MT_SIGNER)
        )

        recalibrated = validate_success(
            api.record_calibration(
                ctx["instrument"]["id"],
                make_metrology_technician_headers(MT_CALIBRATOR),
                build_calibration_payload(calibrated_at_utc=OVERDUE_CLOCK_UTC),
            ),
            expected_status=200,
        )

        assert recalibrated["last_calibrated_utc"].startswith("2026-11-01T00:00:00"), (
            "last_calibrated_utc must be the calibration instant, got "
            f"{recalibrated['last_calibrated_utc']}"
        )
        assert_instrument_drift(recalibrated, 0, 0.001000, "CALIBRATED")
        assert_instrument_drift(
            _read_instrument(api, ctx["instrument"]["id"]), 0, 0.001000, "CALIBRATED"
        )

    def test_the_same_signature_is_then_accepted_and_advances_the_order(self, api):
        """The replayed signature grades the surface and moves POLISHING to FIGURING.

        The PRD states that "An accepted run advances the work order one stage:
        `GRINDING → POLISHING`, `POLISHING → FIGURING`, `FIGURING →
        FIGURE_ACCEPTED`."

        Design: Difficulty/cross_entity_state_dependency/report_sign_requires_instrument_calibrated_and_recovers_after_recalibration
        """
        ctx = self._overdue_station_with_draft_report(api)
        api.sign_metrology_report(
            ctx["report"]["id"], make_metrology_technician_headers(MT_SIGNER)
        )
        api.record_calibration(
            ctx["instrument"]["id"],
            make_metrology_technician_headers(MT_CALIBRATOR),
            build_calibration_payload(calibrated_at_utc=OVERDUE_CLOCK_UTC),
        )

        signed = validate_success(
            api.sign_metrology_report(
                ctx["report"]["id"], make_metrology_technician_headers(MT_SIGNER)
            ),
            expected_status=200,
        )

        assert signed["report_status"] == "SIGNED", (
            f"report_status must be SIGNED, got {signed['report_status']}"
        )
        assert signed["verdict"] == "ACCEPTED", (
            f"verdict must be ACCEPTED, got {signed['verdict']}"
        )
        assert_wavefront_value(
            signed["stage_figure_budget_waves"], 0.0750, "stage_figure_budget_waves"
        )
        assert signed["signed_by_user_id"] == MT_SIGNER, (
            f"signed_by_user_id must be mt-002, got {signed['signed_by_user_id']}"
        )
        assert signed["signed_at_utc"].startswith("2026-11-01T00:00:00"), (
            "signed_at_utc must be read from the logical clock, got "
            f"{signed['signed_at_utc']}"
        )
        assert _read_run(api, ctx["run"]["id"])["run_status"] == "ACCEPTED"
        order = _read_order(api, ctx["work_order"]["id"])
        assert order["process_status"] == "FIGURING", (
            f"process_status must be FIGURING, got {order['process_status']}"
        )
        assert_removal_ledger(order, 800.0, 6199.2000, 0)


def test_metrology_report_system_fields_come_from_the_header_and_the_logical_clock(api):
    """Two identities and one clock reading are minted by the system, not the client.

    The PRD states that "The report is created in `report_status` `DRAFT` with
    `verdict` `PENDING`, with `recorded_by_user_id` set to the acting `X-User-ID`, and
    with `signed_by_user_id`, `signed_at_utc` and `signature_note` all null." and that
    "Signing then sets `report_status` to `SIGNED`, records `signed_by_user_id` from
    the acting `X-User-ID` and `signed_at_utc` from the logical clock, and moves the
    run `AWAITING_METROLOGY → ACCEPTED` or `AWAITING_METROLOGY → REWORK_REQUIRED`
    accordingly."

    Design: Corner/entities/metrology_report_system_fields_come_from_the_header_and_the_logical_clock
    """
    ctx = _drafted_report(api)

    drafted = _read_report(api, ctx["report"]["id"])
    assert drafted["report_status"] == "DRAFT", (
        f"report_status must be DRAFT, got {drafted['report_status']}"
    )
    assert drafted["verdict"] == "PENDING", (
        f"verdict must be PENDING, got {drafted['verdict']}"
    )
    assert drafted["recorded_by_user_id"] == MT_RECORDER, (
        f"recorded_by_user_id must be mt-001, got {drafted['recorded_by_user_id']}"
    )
    assert_null_fields(drafted, "signed_by_user_id", "signed_at_utc", "signature_note")
    assert drafted["version"] == 1, (
        f"a freshly recorded report is at version 1, got {drafted['version']}"
    )
    assert_wavefront_value(drafted["surface_pv_waves"], 0.0000, "surface_pv_waves")
    assert_wavefront_value(
        drafted["transmitted_wavefront_rms_waves"],
        0.0000,
        "transmitted_wavefront_rms_waves",
    )

    set_clock(api, "2026-08-01T09:30:00Z")
    signed = validate_success(
        api.sign_metrology_report(
            ctx["report"]["id"], make_metrology_technician_headers(MT_SIGNER)
        ),
        expected_status=200,
    )

    assert signed["report_status"] == "SIGNED", (
        f"report_status must be SIGNED, got {signed['report_status']}"
    )
    assert signed["verdict"] == "ACCEPTED", (
        f"verdict must be ACCEPTED, got {signed['verdict']}"
    )
    assert signed["recorded_by_user_id"] == MT_RECORDER, (
        "the signature does not overwrite the recorder, got "
        f"{signed['recorded_by_user_id']}"
    )
    assert signed["signed_by_user_id"] == MT_SIGNER, (
        f"signed_by_user_id must be mt-002, got {signed['signed_by_user_id']}"
    )
    assert signed["signed_at_utc"].startswith("2026-08-01T09:30:00"), (
        "signed_at_utc must be the clock reading at signature time, got "
        f"{signed['signed_at_utc']}"
    )
    assert_wavefront_value(
        signed["stage_figure_budget_waves"], 0.0750, "stage_figure_budget_waves"
    )
    assert signed["version"] == 2, (
        f"the signature is one mutation, so version must be 2, got {signed['version']}"
    )
    assert signed["created_at"] == drafted["created_at"], (
        "created_at is immutable, got "
        f"{signed['created_at']} against {drafted['created_at']}"
    )
    run = _read_run(api, ctx["run"]["id"])
    assert run["started_at_utc"].startswith("2026-08-01T00:00:00"), (
        "started_at_utc was stamped from the clock as it stood at start, got "
        f"{run['started_at_utc']}"
    )


def test_second_signature_second_start_and_second_complete_are_rejected(api):
    """Every replayed step reports its own code and double-counts nothing.

    The PRD states that "A `ProcessTechnician` starts a run that is in `SCHEDULED`;
    from any other run state the request is refused with
    `ERR_INVALID_STATE_TRANSITION`." and that "Completing a run in any other state is
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/second_signature_second_start_and_second_complete_are_rejected
    """
    ctx = _drafted_report(api)
    validate_success(
        api.sign_metrology_report(
            ctx["report"]["id"], make_metrology_technician_headers(MT_SIGNER)
        ),
        expected_status=200,
    )

    second_signature = api.sign_metrology_report(
        ctx["report"]["id"], make_metrology_technician_headers(MT_SIGNER)
    )
    second_start = api.start_process_run(
        ctx["run"]["id"], make_process_technician_headers()
    )
    second_complete = api.complete_process_run(
        ctx["run"]["id"],
        build_complete_run_payload(800.0),
        make_process_technician_headers(),
    )

    validate_error(second_signature, ERR_REPORT_ALREADY_SIGNED, expected_status=409)
    validate_error(second_start, ERR_INVALID_STATE_TRANSITION, expected_status=409)
    validate_error(second_complete, ERR_INVALID_STATE_TRANSITION, expected_status=409)

    order = _read_order(api, ctx["work_order"]["id"])
    assert order["process_status"] == "FIGURING", (
        f"process_status must be FIGURING, got {order['process_status']}"
    )
    assert_removal_ledger(order, 800.0, 6199.2000, 0)
    run = _read_run(api, ctx["run"]["id"])
    assert run["run_status"] == "ACCEPTED", (
        f"run_status must be ACCEPTED, got {run['run_status']}"
    )
    assert run["material_removed_nm"] == 800.0, (
        f"material_removed_nm must stay 800.0, got {run['material_removed_nm']}"
    )
    report = _read_report(api, ctx["report"]["id"])
    assert report["report_status"] == "SIGNED"
    assert report["signed_by_user_id"] == MT_SIGNER, (
        "the refused second signature must not overwrite the signer, got "
        f"{report['signed_by_user_id']}"
    )
    assert report["version"] == 2, (
        f"a refused replay may not bump the version, got {report['version']}"
    )


def test_grinding_stage_gates_are_lenient_where_the_polishing_gates_are_not(api):
    """One measurement passes at grinding and needs rework at polishing.

    The PRD states that "The roughness gate is **suppressed entirely at the grinding
    stage** — a rough-ground surface advances on figure alone — and at the polishing
    and figuring stages compares `surface_roughness_nm_rms` against the design's
    `surface_roughness_budget_nm`." and that "A rework verdict at the grinding or
    polishing stage leaves the order's `process_status` untouched, so a further run at
    the same stage can simply be scheduled once the current one has left the
    calendar."

    Design: Corner/state_machines/grinding_stage_gates_are_lenient_where_the_polishing_gates_are_not
    """
    ctx = _drafted_report(
        api,
        run_stage="GRINDING",
        surface_rms_waves=0.2500,
        surface_roughness_nm_rms=5.0000,
    )

    ground = validate_success(
        api.sign_metrology_report(
            ctx["report"]["id"], make_metrology_technician_headers(MT_SIGNER)
        ),
        expected_status=200,
    )

    assert_wavefront_value(
        ground["stage_figure_budget_waves"], 0.2500, "stage_figure_budget_waves"
    )
    assert ground["verdict"] == "ACCEPTED", (
        "0.2500 sits exactly on the ten-times grinding budget and roughness is not "
        f"gated, got {ground['verdict']}"
    )
    after_grinding = _read_order(api, ctx["work_order"]["id"])
    assert after_grinding["process_status"] == "POLISHING", (
        f"process_status must be POLISHING, got {after_grinding['process_status']}"
    )
    assert_removal_ledger(after_grinding, 800.0, 6199.2000, 0)

    second_run = validate_success(
        api.create_process_run(
            build_process_run_payload(
                ctx["work_order"]["id"],
                ctx["instrument"]["id"],
                run_stage="POLISHING",
                metrology_window_start_utc="2026-08-01T11:00:00Z",
                metrology_window_end_utc="2026-08-01T12:00:00Z",
            ),
            make_process_technician_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.start_process_run(second_run["id"], make_process_technician_headers()),
        expected_status=200,
    )
    validate_success(
        api.complete_process_run(
            second_run["id"],
            build_complete_run_payload(300.0),
            make_process_technician_headers(),
        ),
        expected_status=200,
    )
    second_report = validate_success(
        api.create_metrology_report(
            build_metrology_report_payload(
                second_run["id"],
                surface_rms_waves=0.2500,
                surface_roughness_nm_rms=5.0000,
            ),
            make_metrology_technician_headers(MT_RECORDER),
        ),
        expected_status=201,
    )

    polished = validate_success(
        api.sign_metrology_report(
            second_report["id"], make_metrology_technician_headers(MT_SIGNER)
        ),
        expected_status=200,
    )

    assert_wavefront_value(
        polished["stage_figure_budget_waves"], 0.0750, "stage_figure_budget_waves"
    )
    assert polished["verdict"] == "REWORK_REQUIRED", (
        f"verdict must be REWORK_REQUIRED, got {polished['verdict']}"
    )
    assert _read_run(api, second_run["id"])["run_status"] == "REWORK_REQUIRED"
    after_polishing = _read_order(api, ctx["work_order"]["id"])
    assert after_polishing["process_status"] == "POLISHING", (
        "a rework at the polishing stage leaves the order where it was, got "
        f"{after_polishing['process_status']}"
    )
    assert_removal_ledger(after_polishing, 1100.0, 6198.9000, 0)


def test_run_start_stamps_the_clock_and_drags_the_work_order_to_the_run_stage(api):
    """The bodiless start action writes the run, its stamp and the order at once.

    The PRD states that "On success the run moves `SCHEDULED → IN_PROCESS`, its
    `started_at_utc` is stamped from the logical clock, and — this is the coupling
    that makes the work order's fabrication state a function of shop-floor reality
    rather than of intent — the work order's `process_status` is set to the run's
    `run_stage`."

    Design: Corner/endpoints/run_start_stamps_the_clock_and_drags_the_work_order_to_the_run_stage
    """
    ctx = setup_work_order(api, design_code="OD-2540-ST", lot_code="GL-2540-ST")
    instrument = create_instrument(api, instrument_code="IF-2540-1")
    run = validate_success(
        api.create_process_run(
            build_process_run_payload(ctx["work_order"]["id"], instrument["id"]),
            make_process_technician_headers(),
        ),
        expected_status=201,
    )
    assert_booked_minutes(_read_instrument(api, instrument["id"]), 120)
    set_clock(api, "2026-08-01T09:15:00Z")

    started = validate_success(
        api.start_process_run(run["id"], make_process_technician_headers()),
        expected_status=200,
    )

    assert started["run_status"] == "IN_PROCESS", (
        f"run_status must be IN_PROCESS, got {started['run_status']}"
    )
    assert started["started_at_utc"].startswith("2026-08-01T09:15:00"), (
        "started_at_utc must be the logical clock reading, not the window start, got "
        f"{started['started_at_utc']}"
    )
    assert started["metrology_window_start_utc"] == run["metrology_window_start_utc"], (
        "the reserved window is untouched by the start, got "
        f"{started['metrology_window_start_utc']}"
    )
    assert started["metrology_window_end_utc"] == run["metrology_window_end_utc"]
    assert started["window_minutes"] == 120, (
        f"window_minutes must still be 120, got {started['window_minutes']}"
    )
    assert started["capability_ratio_at_scheduling"] == run[
        "capability_ratio_at_scheduling"
    ], "the frozen capability ratio is not recomputed by the start"
    assert_wavefront_value(
        started["capability_ratio_at_scheduling"],
        0.0500,
        "capability_ratio_at_scheduling",
    )
    order = _read_order(api, ctx["work_order"]["id"])
    assert order["process_status"] == "POLISHING", (
        f"process_status must be POLISHING, got {order['process_status']}"
    )
    assert order["compliance_status"] == "UNCLASSIFIED", (
        "the compliance dimension is untouched, got "
        f"{order['compliance_status']}"
    )
    assert_booked_minutes(_read_instrument(api, instrument["id"]), 120)


def test_the_logical_clock_admits_equality_and_refuses_a_backward_step(api):
    """Priority 27 compares with greater-or-equal, not strictly greater.

    The PRD states that "The clock may only move forward: a `current_utc` that
    precedes the clock's present value is rejected with `ERR_CLOCK_NOT_MONOTONIC`
    (HTTP 422), while a `current_utc` exactly equal to the present value is
    admissible."

    Design: Corner/validations/the_logical_clock_admits_equality_and_refuses_a_backward_step
    """
    instrument = create_instrument(
        api, instrument_code="IF-2540-1", last_calibrated_utc=CLOCK_EPOCH_UTC
    )

    forward = validate_success(
        api.set_clock("2026-08-11T09:00:00Z", make_plant_admin_headers()),
        expected_status=200,
    )
    assert forward["current_utc"].startswith("2026-08-11T09:00:00"), (
        f"current_utc must be the new instant, got {forward['current_utc']}"
    )
    assert forward["previous_utc"].startswith("2026-08-01T00:00:00"), (
        "previous_utc must report the instant replaced, got "
        f"{forward['previous_utc']}"
    )

    equal = validate_success(
        api.set_clock("2026-08-11T09:00:00Z", make_plant_admin_headers()),
        expected_status=200,
    )
    assert equal["current_utc"].startswith("2026-08-11T09:00:00"), (
        f"an equal move is admissible, got {equal['current_utc']}"
    )
    assert equal["previous_utc"].startswith("2026-08-11T09:00:00"), (
        "an equal move echoes the same instant as previous_utc, got "
        f"{equal['previous_utc']}"
    )

    backward = api.set_clock("2026-08-11T08:59:00Z", make_plant_admin_headers())

    validate_error(backward, ERR_CLOCK_NOT_MONOTONIC, expected_status=422)
    assert_instrument_drift(
        _read_instrument(api, instrument["id"]), 10, 0.001200, "CALIBRATED"
    )


def test_a_report_cannot_be_signed_by_its_own_recorder_but_may_be_signed_by_quality(api):
    """The role check passes for the recorder; the identity check still refuses him.

    The PRD states that "the acting `X-User-ID` must differ from
    `recorded_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`" and that "Signing is
    shared between `MetrologyTechnician` and `QualityManager` and may carry an optional
    `signature_note`."

    Design: Corner/rbac/a_report_cannot_be_signed_by_its_own_recorder_but_may_be_signed_by_quality
    """
    ctx = _drafted_report(api)

    refused = api.sign_metrology_report(
        ctx["report"]["id"], make_metrology_technician_headers(MT_RECORDER)
    )

    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    unsigned = _read_report(api, ctx["report"]["id"])
    assert unsigned["report_status"] == "DRAFT", (
        f"report_status must stay DRAFT, got {unsigned['report_status']}"
    )
    assert_null_fields(unsigned, "signed_by_user_id", "signed_at_utc")
    assert _read_order(api, ctx["work_order"]["id"])["process_status"] == "POLISHING"
    assert _read_run(api, ctx["run"]["id"])["run_status"] == "AWAITING_METROLOGY"

    signed = validate_success(
        api.sign_metrology_report(
            ctx["report"]["id"], make_quality_manager_headers(QM_PRIMARY)
        ),
        expected_status=200,
    )

    assert signed["report_status"] == "SIGNED", (
        f"report_status must be SIGNED, got {signed['report_status']}"
    )
    assert signed["signed_by_user_id"] == QM_PRIMARY, (
        f"signed_by_user_id must be qm-001, got {signed['signed_by_user_id']}"
    )
    assert signed["recorded_by_user_id"] == MT_RECORDER, (
        "both identities are retained, got "
        f"{signed['recorded_by_user_id']}"
    )
    assert signed["verdict"] == "ACCEPTED", (
        f"verdict must be ACCEPTED, got {signed['verdict']}"
    )
    assert _read_run(api, ctx["run"]["id"])["run_status"] == "ACCEPTED"
    assert _read_order(api, ctx["work_order"]["id"])["process_status"] == "FIGURING"
