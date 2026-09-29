"""Endpoint-shape corners: computed reads, action endpoints and the CRUD surface.

Each test pins one endpoint's declared contract — what it returns, what it writes
and what it deliberately leaves alone — rather than the arithmetic behind it.

The harness restarts the API server before every individual test, so each test
begins against an empty database with the logical clock at its startup default
2026-08-01T00:00:00Z and builds its own world from there.
"""

from datetime import datetime

from test_helpers import (
    ADMIN,
    ENGINEER,
    INSPECTOR,
    OFFICER,
    ApiErrorId,
    api_client,
    assert_alert_event,
    assert_equipment_outage,
    assert_monitoring_assignment,
    assert_score_and_posture,
    assert_station,
    assert_summary_inputs,
    assert_test_event,
    assert_unmatched,
    create_active_plan,
    create_ready_device,
    get_success_data,
    log_alert,
    monitoring_assignment_payload,
    public_file_document_payload,
    register_station,
    run_log_review,
    schedule_test_event,
    set_clock,
    setup_outage,
    setup_station,
    station_summary,
    station_version,
    validate_error,
    validate_paginated,
    validate_success,
    UNRESOLVABLE_UUID,
)

# ---------------------------------------------------------------------------
# Shared instants
# ---------------------------------------------------------------------------
REVIEW_INSTANT = "2026-08-10T00:00:00Z"
WINDOW_START = "2026-08-12T00:00:00Z"
WINDOW_END = "2026-08-12T01:00:00Z"
PREFLIGHT_OPENS = "2026-08-11T00:00:00Z"
ONE_HOUR_TOO_EARLY = "2026-08-10T23:00:00Z"
ONE_HOUR_TOO_LATE = "2026-08-12T02:00:00Z"
ALERT_INSTANT = "2026-08-01T00:00:00Z"
OUTAGE_DETECTED_AT = "2026-08-12T08:00:00Z"
REPAIR_STARTED_AT = "2026-08-12T09:00:00Z"
OUTAGE_RESTORED_AT = "2026-08-12T14:00:00Z"

SUMMARY_FIELDS = (
    "station_id",
    "compliance_posture",
    "compliance_score",
    "compliance_variant_applied",
    "required_source_count",
    "accessible_source_count",
    "missing_source_count",
    "silent_assignment_count",
    "outage_breach_count",
    "unfiled_test_count",
    "penalty_points_total",
    "plan_revalidation_required",
    "public_file_document_count",
    "last_log_review_at",
)


def _instant(value):
    """Parse an ISO 8601 UTC instant so two spellings of one instant compare equal."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant(actual, expected_iso, label):
    assert actual is not None, f"{label} must be set"
    assert _instant(actual) == _instant(expected_iso), (
        f"expected {label} == {expected_iso}, got {actual}"
    )


def _reviewed_station_with_two_silent_assignments():
    """A station requiring two source types, covering one required and one unrequired
    source, both assignments left without a receipt until a log review eight days
    later sweeps them into SILENT."""
    ctx = setup_station(
        required_source_types=("PEP", "SATELLITE"), covered_source_types=("PEP", "LP1")
    )
    for kind, label in (
        ("STATION_LOG", "2026-Q3 station log"),
        ("TEST_LOGS", "weekly test logs 2026-08"),
    ):
        validate_success(
            api_client.create_public_file_document(
                ctx["station_id"],
                public_file_document_payload(document_kind=kind, reference_label=label),
                ENGINEER,
            ),
            201,
        )
    set_clock(REVIEW_INSTANT)
    run_log_review(ctx["station_id"])
    return ctx


def _station_with_ready_device():
    """Active plan requiring PEP, a station and a READY device — no assignment yet."""
    plan = create_active_plan(("PEP",))
    station = register_station(plan["id"])
    device = create_ready_device(station["id"])
    return station, device, station_version(station["id"])


def _station_with_scheduled_test_event():
    ctx = setup_station()
    ctx["test_event"] = schedule_test_event(ctx["station_id"], WINDOW_START, WINDOW_END)
    ctx["test_event_id"] = ctx["test_event"]["id"]
    return ctx


def _station_with_three_alerts():
    plan = create_active_plan(("PEP",))
    station = register_station(plan["id"])
    alerts = [
        log_alert(
            station["id"],
            ALERT_INSTANT,
            event_code="TOR",
            originator_sequence="KSAXS-7001",
            fips_codes=["20173", "20177"],
        ),
        log_alert(
            station["id"],
            ALERT_INSTANT,
            event_code="TOR",
            originator_sequence="KSAXS-7002",
            fips_codes=["20173"],
        ),
        log_alert(
            station["id"],
            ALERT_INSTANT,
            event_code="SVR",
            originator_sequence="KSAXS-7003",
            fips_codes=["20177"],
        ),
    ]
    return station, alerts


def _station_with_restored_outage():
    set_clock(OUTAGE_DETECTED_AT)
    ctx = setup_station()
    outage = setup_outage(ctx["device_id"], OUTAGE_DETECTED_AT)
    set_clock(REPAIR_STARTED_AT)
    get_success_data(api_client.start_repair(outage["id"], ENGINEER))
    set_clock(OUTAGE_RESTORED_AT)
    ctx["outage"] = get_success_data(api_client.restore_outage(outage["id"], ENGINEER))
    ctx["outage_id"] = outage["id"]
    ctx["assignment_id"] = ctx["assignments"]["PEP"]["id"]
    return ctx


class TestComplianceSummaryComputedRead:
    """The summary read exposes every input the current score consumed, and consumes
    nothing itself."""

    def test_compliance_summary_reports_every_declared_score_input(self):
        """PRD §3.8: "That summary reports `station_id`, `compliance_posture`, `compliance_score`, `compliance_variant_applied`, `required_source_count`, `accessible_source_count`, `missing_source_count`, `silent_assignment_count`, `outage_breach_count`, `unfiled_test_count`, `penalty_points_total`, `plan_revalidation_required`, `public_file_document_count` and `last_log_review_at`."
        PRD §3.8: "The three names that exist only here — `missing_source_count`, `outage_breach_count` and `unfiled_test_count` — are the intermediate figures described above: `missing_source_count` is the floored difference between `required_source_count` and `accessible_source_count`, `outage_breach_count` is the obligation-breached outage count over non-closed outages, and `unfiled_test_count` is the count of `FAILED_UNFILED` test events."
        PRD §3.8: "25.00 points for every required source type the station is missing, where the missing count is the plan's `required_source_count` less the station's `accessible_source_count`, floored at zero so that over-coverage never earns a credit"
        PRD §3.8: "10.00 points for each assignment counted in `silent_assignment_count`"

        Design: Corner/endpoints/compliance_summary_computed_read_exposes_every_score_input
        """
        ctx = _reviewed_station_with_two_silent_assignments()

        summary = get_success_data(
            api_client.get_compliance_summary(ctx["station_id"], INSPECTOR)
        )
        for field in SUMMARY_FIELDS:
            assert field in summary, f"the summary must report {field}"

        assert summary["station_id"] == ctx["station_id"]
        assert_score_and_posture(summary, 30.00, "SUSPENDED_FILINGS")
        assert summary["compliance_variant_applied"] == "PROVISIONAL"
        assert_summary_inputs(
            summary,
            required_source_count=2,
            accessible_source_count=0,
            missing_source_count=2,
            silent_assignment_count=2,
            outage_breach_count=0,
            unfiled_test_count=0,
            penalty_points_total=0.00,
            plan_revalidation_required=False,
            public_file_document_count=2,
        )
        _assert_instant(summary["last_log_review_at"], REVIEW_INSTANT, "last_log_review_at")

        reconciled = (
            100.00
            - 25.00 * summary["missing_source_count"]
            - 10.00 * summary["silent_assignment_count"]
        )
        assert summary["compliance_score"] == reconciled, (
            f"the exposed inputs must reconcile with the stored score: expected "
            f"{reconciled}, got {summary['compliance_score']}"
        )

    def test_compliance_summary_read_has_no_side_effects(self):
        """PRD §3.8: "A dedicated read exposes every input the current score consumed, so that a station can see *why* it scored what it scored rather than only the result."
        PRD §3.8: "The scoring variant is chosen, `compliance_score` and `compliance_variant_applied` are written, `compliance_posture` is set from the score bands, and `last_log_review_at` is stamped from the logical clock."
        PRD §3.8: "The ten other recompute events listed in §2.10 execute **phases 3 and 4 only** — they never sweep for silence and never mark events unfiled — and they never write `last_log_review_at`."

        Design: Corner/endpoints/compliance_summary_computed_read_exposes_every_score_input
        """
        ctx = _reviewed_station_with_two_silent_assignments()

        first = get_success_data(
            api_client.get_compliance_summary(ctx["station_id"], INSPECTOR)
        )
        second = get_success_data(
            api_client.get_compliance_summary(ctx["station_id"], OFFICER)
        )
        assert second == first, (
            "two reads of a computed endpoint must be identical: "
            f"{first} then {second}"
        )

        station = get_success_data(api_client.get_station(ctx["station_id"], ADMIN))
        assert_station(station)
        assert station["compliance_score"] == first["compliance_score"]
        assert station["compliance_posture"] == first["compliance_posture"]
        _assert_instant(
            get_success_data(
                api_client.get_compliance_summary(ctx["station_id"], ADMIN)
            )["last_log_review_at"],
            REVIEW_INSTANT,
            "last_log_review_at",
        )


class TestPublicFileDocumentAction:
    """The upload endpoint answers with the station, raises one counter and fires no
    recompute."""

    def test_each_upload_returns_the_station_with_the_counter_raised_by_one(self):
        """PRD §3.2: "Each recorded upload names a `document_kind` and a `reference_label`, advances the station's `public_file_document_count` by one, and returns the updated station row rather than a document row."
        PRD §3.2: "Because the upload registers a new public-file item, this operation answers with `201 Created` even though its response body is the station."

        Design: Corner/endpoints/public_file_document_action_increments_the_counter_without_recomputing
        """
        plan = create_active_plan(("PEP",))
        station = register_station(plan["id"])

        observed = []
        for kind, label in (
            ("STATION_LOG", "log-1"),
            ("STATION_LOG", "log-2"),
            ("TEST_LOGS", "weekly-tests"),
        ):
            body = validate_success(
                api_client.create_public_file_document(
                    station["id"],
                    public_file_document_payload(
                        document_kind=kind, reference_label=label
                    ),
                    ENGINEER,
                ),
                201,
            )
            assert_station(body)
            assert body["id"] == station["id"], (
                "the response body is the station itself, not a document row"
            )
            observed.append(body["public_file_document_count"])

        assert observed == [1, 2, 3], (
            f"the counter rises by exactly one per call, got {observed}"
        )

    def test_uploads_fire_no_recompute_event_and_score_no_points(self):
        """PRD §3.2: "The counter is informational: it appears in the station's compliance summary and is never an input to any score."
        PRD §2.10: "A station is created in `PROVISIONING` with `compliance_score` null, `compliance_variant_applied` null and `version` 1, and it stays in `PROVISIONING` until the first recompute event fires against it; from that moment on it is always in exactly one of `COMPLIANT`, `WATCH` or `SUSPENDED_FILINGS`."

        Design: Corner/endpoints/public_file_document_action_increments_the_counter_without_recomputing
        """
        plan = create_active_plan(("PEP",))
        station = register_station(plan["id"])

        for label in ("log-1", "log-2", "weekly-tests"):
            body = validate_success(
                api_client.create_public_file_document(
                    station["id"],
                    public_file_document_payload(reference_label=label),
                    ENGINEER,
                ),
                201,
            )
            assert body["compliance_score"] is None, (
                f"no recompute may fire: got compliance_score {body['compliance_score']}"
            )
            assert body["compliance_posture"] == "PROVISIONING", (
                f"the station stays in PROVISIONING, got {body['compliance_posture']}"
            )

        summary = station_summary(station["id"])
        assert_summary_inputs(summary, public_file_document_count=3)
        assert summary["compliance_score"] is None
        assert summary["last_log_review_at"] is None, (
            "an upload is not a station log review"
        )


class TestMonitoringAssignmentCrossReference:
    """The assignment row is the link between a station and a device, and both ends
    must resolve before it is created."""

    def test_good_station_with_an_unresolvable_device_creates_nothing(self):
        """PRD §2.9: "Each entity type has its own not-found code so that a caller can tell which reference broke: `ERR_STATE_PLAN_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_RELAY_RULE_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_OUTAGE_NOT_FOUND`, `ERR_ALERT_EVENT_NOT_FOUND`, `ERR_WEA_NOTICE_NOT_FOUND`, `ERR_TEST_EVENT_NOT_FOUND`, `ERR_LOG_ENTRY_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and `ERR_INSPECTION_NOT_FOUND`."
        PRD §3.3: "The create then increments the station's `version` by one."

        Design: Corner/endpoints/monitoring_assignment_is_the_cross_reference_link_between_station_and_device
        """
        station, _device, expected_version = _station_with_ready_device()

        validate_error(
            api_client.create_monitoring_assignment(
                monitoring_assignment_payload(
                    station["id"], UNRESOLVABLE_UUID, expected_version,
                    source_type="PEP",
                ),
                ENGINEER,
            ),
            ApiErrorId.ERR_DEVICE_NOT_FOUND,
        )

        assert station_version(station["id"]) == expected_version, (
            "a half-resolvable link neither stores a row nor consumes a version"
        )
        _, meta = validate_paginated(
            api_client.list_monitoring_assignments(
                ADMIN, params={"station_id": station["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_created_assignment_is_reachable_from_both_foreign_key_filters(self):
        """PRD §3.3: "A successful create lands in `ACTIVE` with `last_receipt_at` and `silence_flagged_at` null, and sets `counts_toward_required_sources` to true exactly when the row's `status` is `ACTIVE` and its `source_type` appears in the governing plan's `required_source_types` — a row covering a source the plan does not require is stored and reported but never contributes coverage."
        PRD §3.3: "If the station already had an `ACTIVE` assignment for the same `source_type`, that older row is pushed `ACTIVE` → `DECOMMISSIONED` and the new row's `superseded_assignment_id` is set to the older row's `id`; when no such row existed, `superseded_assignment_id` stays null."
        PRD §3.3: "Assignments can be listed filtered by `station_id`, `device_id`, `source_type`, `status` and `superseded_assignment_id`."
        PRD §3.3: "The station's `accessible_source_count` is recomputed exactly once, *after* the supersede has landed, and then the create fires a station recompute event."

        Design: Corner/endpoints/monitoring_assignment_is_the_cross_reference_link_between_station_and_device
        """
        station, device, expected_version = _station_with_ready_device()

        assignment = validate_success(
            api_client.create_monitoring_assignment(
                monitoring_assignment_payload(
                    station["id"], device["id"], expected_version, source_type="PEP"
                ),
                ENGINEER,
            ),
            201,
        )
        assert_monitoring_assignment(assignment)
        assert assignment["station_id"] == station["id"]
        assert assignment["device_id"] == device["id"]
        assert assignment["source_type"] == "PEP"
        assert assignment["source_call_sign"] == "WXPEP"
        assert assignment["status"] == "ACTIVE"
        assert assignment["superseded_assignment_id"] is None
        assert assignment["counts_toward_required_sources"] is True

        for filters in (
            {"station_id": station["id"]},
            {"device_id": device["id"]},
        ):
            rows, meta = validate_paginated(
                api_client.list_monitoring_assignments(ADMIN, params=filters)
            )
            assert meta["total_count"] == 1, (
                f"filter {filters} must reach the row, got {meta['total_count']}"
            )
            assert [row["id"] for row in rows] == [assignment["id"]]

        echoed = get_success_data(
            api_client.get_monitoring_assignment(assignment["id"], INSPECTOR)
        )
        assert echoed["id"] == assignment["id"]
        assert echoed["station_id"] == station["id"]
        assert echoed["device_id"] == device["id"]

        summary = station_summary(station["id"])
        assert_summary_inputs(summary, accessible_source_count=1)
        assert_score_and_posture(summary, 100.00, "COMPLIANT")


class TestEvaluateReadinessPreflightWindow:
    """The readiness action is admitted on a 25-hour window and nowhere else."""

    def test_one_hour_before_the_preflight_window_opens_the_action_is_refused(self):
        """PRD §3.6: "The readiness window opens 24 hours before `window_start_at` and closes at `window_end_at`: an evaluation is admitted when the logical clock is at or after `window_start_at` less 24 hours and at or before `window_end_at`, and is otherwise rejected with `ERR_READINESS_WINDOW_NOT_OPEN`."

        Design: Corner/endpoints/evaluate_readiness_is_a_conditional_action_bounded_by_the_preflight_window
        """
        ctx = _station_with_scheduled_test_event()
        set_clock(ONE_HOUR_TOO_EARLY)

        validate_error(
            api_client.evaluate_readiness(ctx["test_event_id"], ENGINEER),
            ApiErrorId.ERR_READINESS_WINDOW_NOT_OPEN,
        )

        event = get_success_data(api_client.get_test_event(ctx["test_event_id"], ADMIN))
        assert event["status"] == "SCHEDULED", (
            f"a refused evaluation leaves the event in SCHEDULED, got {event['status']}"
        )
        assert event["readiness_score"] is None
        assert event["readiness_evaluated_at"] is None

    def test_one_hour_after_the_window_closes_the_action_is_refused(self):
        """PRD §3.6: "The readiness window opens 24 hours before `window_start_at` and closes at `window_end_at`: an evaluation is admitted when the logical clock is at or after `window_start_at` less 24 hours and at or before `window_end_at`, and is otherwise rejected with `ERR_READINESS_WINDOW_NOT_OPEN`."

        Design: Corner/endpoints/evaluate_readiness_is_a_conditional_action_bounded_by_the_preflight_window
        """
        ctx = _station_with_scheduled_test_event()
        set_clock(ONE_HOUR_TOO_LATE)

        validate_error(
            api_client.evaluate_readiness(ctx["test_event_id"], ENGINEER),
            ApiErrorId.ERR_READINESS_WINDOW_NOT_OPEN,
        )

        event = get_success_data(api_client.get_test_event(ctx["test_event_id"], ADMIN))
        assert event["status"] == "SCHEDULED"
        assert event["readiness_score"] is None

    def test_the_minus_twenty_four_hour_boundary_is_inclusive_and_writes_the_score(self):
        """PRD §3.6: "The score is 40 times the device ratio plus 40 times the coverage ratio plus 20 times the recent-activity ratio, rounded half-up to two decimal places once, after the weighted sum has been formed."
        PRD §3.6: "That value is written to `readiness_score` and the evaluation instant is written to `readiness_evaluated_at`."
        PRD §3.6: "A score of 80.00 or greater advances the event to `READY`, whether it came from `SCHEDULED` → `READY` or from `READINESS_PENDING` → `READY` on a re-run; a score below 80.00 leaves the event in `READINESS_PENDING`, reached as `SCHEDULED` → `READINESS_PENDING` on a first evaluation or as `READINESS_PENDING` → `READINESS_PENDING` on a re-run that still falls short."

        Design: Corner/endpoints/evaluate_readiness_is_a_conditional_action_bounded_by_the_preflight_window
        """
        ctx = _station_with_scheduled_test_event()
        set_clock(PREFLIGHT_OPENS)

        event = validate_success(
            api_client.evaluate_readiness(ctx["test_event_id"], ENGINEER)
        )
        assert_test_event(event)
        assert event["readiness_score"] == 80.00, (
            "40 * 1/1 + 40 * 1/1 + 20 * 0 == 80.00 at the inclusive boundary, got "
            f"{event['readiness_score']}"
        )
        _assert_instant(
            event["readiness_evaluated_at"], PREFLIGHT_OPENS, "readiness_evaluated_at"
        )
        assert event["status"] == "READY"

        set_clock(ONE_HOUR_TOO_LATE)
        reread = get_success_data(api_client.get_test_event(ctx["test_event_id"], ADMIN))
        assert reread["readiness_score"] == 80.00
        _assert_instant(
            reread["readiness_evaluated_at"], PREFLIGHT_OPENS, "readiness_evaluated_at"
        )
        assert reread["status"] == "READY", (
            "passing window_end_at does not by itself move the event"
        )


class TestAlertEventCrudSurface:
    """Create, read and a filtered list are the whole read/write surface for alerts."""

    def test_alert_create_then_read_round_trips_every_supplied_field(self):
        """PRD §3.5: "The payload names the receiving station through `station_id`, the received `event_code` (one to six uppercase alphanumeric characters), the `originator_sequence` that identifies the originating transmission and serves as the duplicate-detection key, a non-empty `fips_codes` array of five-digit FIPS strings taken from the alert's location field, and the operator-reported `received_at` instant."
        PRD §3.5: "When the candidate pool is empty the alert moves `RECEIVED` → `UNMATCHED_OPTIONAL`, `matched_relay_rule_id` stays null, `relay_class_applied` stays `NONE` and `forward_delay_seconds_applied` stays 0."
        PRD §3.5: "The accessibility dimension is `accessibility_state`, which begins at `ACCESSIBILITY_UNVERIFIED` and ends at either `ACCESSIBILITY_PASSED` or `ACCESSIBILITY_FAILED`."

        Design: Corner/endpoints/alert_event_create_read_and_filtered_list_are_the_whole_crud_surface
        """
        station, alerts = _station_with_three_alerts()

        alert = get_success_data(api_client.get_alert_event(alerts[0]["id"], INSPECTOR))
        assert_alert_event(alert)
        assert alert["station_id"] == station["id"]
        assert alert["event_code"] == "TOR"
        assert alert["originator_sequence"] == "KSAXS-7001"
        assert sorted(alert["fips_codes"]) == ["20173", "20177"], (
            f"the supplied FIPS list must round-trip, got {alert['fips_codes']}"
        )
        _assert_instant(alert["received_at"], ALERT_INSTANT, "received_at")
        assert_unmatched(alert)
        assert alert["accessibility_state"] == "ACCESSIBILITY_UNVERIFIED"

    def test_alert_list_filters_on_supplied_and_computed_fields_with_paging_meta(self):
        """PRD §3.5: "Alerts can be listed filtered by `station_id`, `matched_relay_rule_id`, `suppression_reference_alert_id`, `relay_state`, `accessibility_state`, `event_code` and `originator_sequence`."
        PRD §2.4: "Every list response repeats `limit` and `offset` in the `meta` object alongside `total_count` (the number of rows matching the filters before the page window is applied) and `has_more` (true when rows remain beyond the current page)."

        Design: Corner/endpoints/alert_event_create_read_and_filtered_list_are_the_whole_crud_surface
        """
        station, alerts = _station_with_three_alerts()

        rows, meta = validate_paginated(
            api_client.list_alert_events(
                ADMIN, params={"station_id": station["id"], "event_code": "TOR"}
            )
        )
        assert meta["total_count"] == 2, (
            f"two TOR alerts match, got {meta['total_count']}"
        )
        assert meta["has_more"] is False
        assert {row["id"] for row in rows} == {alerts[0]["id"], alerts[1]["id"]}

        rows, meta = validate_paginated(
            api_client.list_alert_events(
                ADMIN,
                params={
                    "station_id": station["id"],
                    "relay_state": "UNMATCHED_OPTIONAL",
                    "limit": 2,
                    "offset": 0,
                },
            )
        )
        assert len(rows) == 2, f"the page window holds two rows, got {len(rows)}"
        assert meta["total_count"] == 3, (
            f"total_count counts matches before paging, got {meta['total_count']}"
        )
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

        rows, meta = validate_paginated(
            api_client.list_alert_events(
                ADMIN, params={"originator_sequence": "KSAXS-7003"}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [alerts[2]["id"]]


class TestFailVerificationClearsMeasuredDowntime:
    """Failing verification destroys exactly the figures restoration wrote."""

    def test_restoration_writes_both_downtime_figures_below_their_breach_limits(self):
        """PRD §3.4: "Subtract `detected_at` from `restored_at`, divide the resulting number of seconds by 3600, and round half-up to two decimal places; the result is `continuous_downtime_hours`."
        PRD §3.4: "Then `continuous_clock_breached` is true when `continuous_downtime_hours` is strictly greater than 60 hours — two and a half days of unbroken outage — and false when it equals 60 hours or is less."
        PRD §3.4: "Accumulate the day contributions in seconds, divide the accumulated total by 3600, and round half-up to two decimal places to obtain `obligation_downtime_hours`."
        PRD §3.4: "Then `obligation_breached` is true when `obligation_downtime_hours` is strictly greater than 48 hours — the statutory repair deadline — and false at exactly 48 hours or below."

        Design: Corner/endpoints/fail_verification_action_clears_the_measured_downtime_it_rejects
        """
        ctx = _station_with_restored_outage()
        outage = ctx["outage"]

        assert_equipment_outage(outage)
        assert outage["status"] == "RESTORED"
        assert outage["continuous_downtime_hours"] == 6.00, (
            f"08:00Z to 14:00Z is 6.00 hours, got {outage['continuous_downtime_hours']}"
        )
        assert outage["obligation_downtime_hours"] == 6.00, (
            "the whole outage lies inside one obligation day, got "
            f"{outage['obligation_downtime_hours']}"
        )
        assert outage["continuous_clock_breached"] is False
        assert outage["obligation_breached"] is False

    def test_fail_verification_nulls_the_downtime_and_leaves_the_device_failed(self):
        """PRD §3.4: "Rejection moves the row `RESTORED` → `VERIFICATION_FAILED`, may carry an optional `verification_note`, clears `restored_at` back to null, clears both `continuous_downtime_hours` and `obligation_downtime_hours` back to null, and leaves the unit `FAILED`; the outage is then eligible to re-enter `REPAIR_IN_PROGRESS`, closing the cycle `RESTORED` → `VERIFICATION_FAILED` → `REPAIR_IN_PROGRESS` → `RESTORED`."
        PRD §3.4: "Crucially, `detected_at` is never reset by any of this, so both downtime clocks keep accruing across every repair cycle from the original detection instant."
        PRD §3.4: "Both entries stamp `repair_started_at` from the logical clock, but only the entry from `VERIFICATION_FAILED` increases `repair_cycle_count` by one — the counter measures re-work, so the first repair attempt leaves it at 0."
        PRD §3.8: "The outage breach count is the number of equipment outages whose `device_id` belongs to this station, whose `obligation_breached` is true, and whose `status` is `OPEN`, `REPAIR_IN_PROGRESS`, `RESTORED` or `VERIFICATION_FAILED` — a `CLOSED` outage stops counting even if it breached."

        Design: Corner/endpoints/fail_verification_action_clears_the_measured_downtime_it_rejects
        """
        ctx = _station_with_restored_outage()

        failed = validate_success(
            api_client.fail_verification(
                ctx["outage_id"],
                ADMIN,
                {"verification_note": "audio still absent on the monitored air check"},
            )
        )
        assert_equipment_outage(failed)
        assert failed["status"] == "VERIFICATION_FAILED"
        assert failed["restored_at"] is None, (
            f"restored_at is cleared, got {failed['restored_at']}"
        )
        assert failed["continuous_downtime_hours"] is None
        assert failed["obligation_downtime_hours"] is None
        _assert_instant(failed["detected_at"], OUTAGE_DETECTED_AT, "detected_at")
        assert failed["repair_cycle_count"] == 0, (
            "the counter measures re-work, so the first attempt leaves it at 0, got "
            f"{failed['repair_cycle_count']}"
        )

        device = get_success_data(api_client.get_device(ctx["device_id"], ENGINEER))
        assert device["status"] == "FAILED", (
            f"the unit never returned to READY, got {device['status']}"
        )
        assignment = get_success_data(
            api_client.get_monitoring_assignment(ctx["assignment_id"], ENGINEER)
        )
        assert assignment["status"] == "SUSPENDED"

        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(summary, outage_breach_count=0, accessible_source_count=0)
        assert_score_and_posture(summary, 75.00, "WATCH")
