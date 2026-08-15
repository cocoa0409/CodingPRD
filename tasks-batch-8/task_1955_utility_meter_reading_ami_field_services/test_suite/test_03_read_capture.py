"""Field read capture: window boundaries, hazard gates, OCC, supersede.

Covers the capture contract of PRD sections 2.6, 2.7, 2.8, 2.10, 3.3 and the
read adjudication rules of section 3.4.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_route_payload,
    capture_read_payload,
    create_billing_period_payload,
    create_field_technician_payload,
    create_hazard_flag_payload,
    create_meter,
    create_route_payload,
    get_read,
    get_route,
    get_route_stops,
    get_stop,
    ingest_ami_read,
    make_field_technician_headers,
    open_period_window,
    report_hazard,
    run_ops_snapshot,
    set_logical_clock,
    setup_account_with_installed_meter,
    setup_in_progress_route,
    skip_stop_for_hazard_as,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["meter_ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_liaison_headers"]


def _three_stop_route(api, cycle_code="C15", window_open="2026-08-06", window_close="2026-08-10"):
    """Three handheld accounts with meters; period window open; route FULL on
    the open date, assigned and started. Returns (accounts, meters, route, stops, tech)."""
    set_logical_clock("2026-08-01T00:00:00Z")
    accounts, meters = [], []
    for i in range(1, 4):
        account, meter = setup_account_with_installed_meter(
            f"A-80{i:02d}", cycle_code, service_address=f"4{i} Ash Ct"
        )
        accounts.append(account)
        meters.append(meter)
    period, route, stops, tech = setup_in_progress_route(
        cycle_code,
        "2026-08-01",
        "2026-08-31",
        window_open,
        window_close,
        "2026-08-31",
        window_open,
        route_shift="FULL",
        open_clock=f"{window_open}T08:00:00Z",
        tech_name="Tech Eight",
    )
    assert len(stops) == 3
    return accounts, meters, route, stops, tech


class TestReadWindowBoundaries:
    def test_capture_on_open_and_close_dates_accepted(self, api):
        """PRD section 2.8: "The read window is the interval from
        `read_window_open_date` through `read_window_close_date` with both
        endpoints inclusive. A read whose `read_at` date falls inside its
        period's window is on-cycle and is credited to the period whose window
        contains it; a `read_at` even one day outside in either direction is
        rejected at capture with `ERR_READ_OUTSIDE_WINDOW` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/read_capture_window_date_inclusive_boundaries
        """
        _accounts, meters, _route, stops, tech = _three_stop_route(api)

        read_open = validate_success(
            api.capture_read(
                stops[0]["id"],
                capture_read_payload(
                    meters[0]["id"], 100, "2026-08-06T00:00:00Z", stops[0]["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        assert read_open["read_status"] == "PROVISIONAL"

        read_close = validate_success(
            api.capture_read(
                stops[1]["id"],
                capture_read_payload(
                    meters[1]["id"], 200, "2026-08-10T23:59:59Z", stops[1]["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        assert read_close["read_status"] == "PROVISIONAL"

    def test_capture_one_second_after_close_rejected(self, api):
        """PRD section 2.8: "The read window is the interval from
        `read_window_open_date` through `read_window_close_date` with both
        endpoints inclusive. A read whose `read_at` date falls inside its
        period's window is on-cycle and is credited to the period whose window
        contains it; a `read_at` even one day outside in either direction is
        rejected at capture with `ERR_READ_OUTSIDE_WINDOW` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/read_capture_window_date_inclusive_boundaries
        """
        _accounts, meters, _route, stops, tech = _three_stop_route(api)

        res = api.capture_read(
            stops[2]["id"],
            capture_read_payload(
                meters[2]["id"], 300, "2026-08-11T00:00:00Z", stops[2]["version"]
            ),
            make_field_technician_headers(tech["id"]),
        )
        validate_error(res, ApiErrorId.ERR_READ_OUTSIDE_WINDOW.value, 422)
        assert get_stop(stops[2]["id"])["stop_status"] == "PENDING"


class TestValidationPriorityPairs:
    def _skipped_hazard_stop_with_history(self, api):
        """AMI account with last validated 10000; meter degraded; route
        IN_PROGRESS; ACTIVE DOG hazard; stop SKIPPED_HAZARD."""
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter(
            "A-7001", "C14", meter_type="AMI", service_address="31 Walnut Ln"
        )
        ingest_ami_read(meter["id"], 9700, "2026-08-02T10:00:00Z")
        ingest_ami_read(meter["id"], 10000, "2026-08-03T10:00:00Z")
        # Snapshot 08-04 sees the 08-03 read (no miss); 08-05 misses once -> DEGRADED.
        run_ops_snapshot("2026-08-04T00:00:00Z")
        run_ops_snapshot("2026-08-05T00:00:00Z")
        period, route, stops, tech = setup_in_progress_route(
            "C14",
            "2026-08-01",
            "2026-08-31",
            "2026-08-06",
            "2026-08-10",
            "2026-08-31",
            "2026-08-06",
            route_shift="FULL",
            open_clock="2026-08-06T08:00:00Z",
            tech_name="Tech Six",
        )
        assert len(stops) == 1
        stop = stops[0]
        flag = report_hazard(account["id"], tech["id"], hazard_type="DOG", severity="HIGH")
        skip_stop_for_hazard_as(stop["id"], flag["id"], tech["id"])
        return account, meter, route, get_stop(stop["id"]), tech

    def test_skipped_stop_capture_reports_stop_not_actionable(self, api):
        """PRD section 3.3: "A stop may receive a capture from `PENDING`,
        `NO_READ_PENDING`, `READ_CAPTURED`, or `ESTIMATED`; capture from any
        other stop state fails with `ERR_STOP_NOT_ACTIONABLE` (HTTP 409)."
        PRD section 2.6: "Only then do domain state gates engage, in this
        relative order: stop actionability (`ERR_STOP_NOT_ACTIONABLE`, HTTP
        409) is evaluated before the generic state-machine gate so that
        stop-state failures surface as domain-specific errors; the generic
        gate follows (`ERR_INVALID_STATE_TRANSITION`, HTTP 409 — including
        `ERR_ROUTE_NOT_REASSIGNABLE` when reassignment is attempted from a
        route that is not `ASSIGNED`); then the route-in-progress requirement
        for stop field operations (`ERR_ROUTE_NOT_IN_PROGRESS`, HTTP 409); then
        the period window gates (`ERR_READ_WINDOW_NOT_OPEN` and
        `ERR_READ_WINDOW_STILL_OPEN`, HTTP 409)."
        PRD section 2.6: "Business constraints close the middle of the ladder:
        register rollback (`ERR_READ_ROLLBACK`, HTTP 422); meter installation
        and swap rules (`ERR_ACCOUNT_HAS_INSTALLED_METER` and
        `ERR_METER_NOT_AVAILABLE_FOR_INSTALL` at HTTP 409,
        `ERR_METER_NOT_INSTALLED_AT_ACCOUNT` at HTTP 409, `ERR_METER_NOT_AMI`
        at HTTP 422); uniqueness (`ERR_DUPLICATE_ACCOUNT_NUMBER` and
        `ERR_DUPLICATE_SERIAL_NUMBER`, HTTP 409); estimate eligibility
        (`ERR_ESTIMATE_CAP_REACHED` and `ERR_INSUFFICIENT_READ_HISTORY`, HTTP
        409); account lifecycle gates (`ERR_ACCOUNT_NOT_ACTIVE`,
        `ERR_ACCOUNT_HAS_OPEN_INVESTIGATION`, and `ERR_ACCOUNT_HAS_OPEN_WORK`,
        HTTP 409); technician lifecycle gates (`ERR_TECHNICIAN_NOT_ACTIVE` and
        `ERR_TECHNICIAN_HAS_OPEN_WORK`, HTTP 409); and the
        one-open-investigation-per-meter rule (`ERR_INVESTIGATION_ALREADY_OPEN`,
        HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_stop_not_actionable_beats_business_constraint_rollback
        """
        account, meter, _route, stop, tech = self._skipped_hazard_stop_with_history(api)
        assert stop["stop_status"] == "SKIPPED_HAZARD"

        res = api.capture_read(
            stop["id"],
            capture_read_payload(
                meter["id"], 9000, "2026-08-06T12:00:00Z", stop["version"]
            ),
            make_field_technician_headers(tech["id"]),
        )
        # 9000 rolls back the account's last validated 10000, yet the state
        # gate (stop actionability) must surface first.
        error = validate_error(res, ApiErrorId.ERR_STOP_NOT_ACTIONABLE.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_READ_ROLLBACK.value

    def test_skipped_stop_unchanged_after_priority_rejection(self, api):
        """PRD section 3.3: "A stop may receive a capture from `PENDING`,
        `NO_READ_PENDING`, `READ_CAPTURED`, or `ESTIMATED`; capture from any
        other stop state fails with `ERR_STOP_NOT_ACTIONABLE` (HTTP 409)."
        PRD section 2.9: "Meter registers move in one direction. Every
        `read_value`, `old_final_read_value`, and `reread_value` is a
        non-negative integer number of kWh, and any value presented below the
        account's `last_validated_read_value` (when that field is set) is
        rejected with `ERR_READ_ROLLBACK` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_stop_not_actionable_beats_business_constraint_rollback
        """
        account, meter, _route, stop, tech = self._skipped_hazard_stop_with_history(api)

        res = api.capture_read(
            stop["id"],
            capture_read_payload(
                meter["id"], 9000, "2026-08-06T12:00:00Z", stop["version"]
            ),
            make_field_technician_headers(tech["id"]),
        )
        validate_error(res, ApiErrorId.ERR_STOP_NOT_ACTIONABLE.value, 409)

        after = get_stop(stop["id"])
        assert after["stop_status"] == "SKIPPED_HAZARD"
        reads, meta = validate_paginated(
            api.list_reads(BILLING, params={"route_stop_id": stop["id"]})
        )
        assert meta["total_count"] == 0

    def _pending_stop_with_active_hazard(self, api):
        """Handheld account; ACTIVE ACCESS hazard; route AM (single-person
        crew) IN_PROGRESS; stop PENDING. Period window [08-06..08-10]."""
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter(
            "A-7002", "C14B", service_address="33 Walnut Ln"
        )
        period, route, stops, tech = setup_in_progress_route(
            "C14B",
            "2026-08-01",
            "2026-08-31",
            "2026-08-06",
            "2026-08-10",
            "2026-08-31",
            "2026-08-06",
            route_shift="AM",
            two_person_crew=False,
            open_clock="2026-08-06T08:00:00Z",
            tech_name="Tech Seven",
        )
        assert len(stops) == 1
        report_hazard(account["id"], tech["id"], hazard_type="ACCESS", severity="HIGH")
        return account, meter, route, stops[0], tech

    def test_active_hazard_block_beats_outside_window(self, api):
        """PRD section 2.6: "Safety screens come next: the active-hazard block
        on read capture (`ERR_ACTIVE_HAZARD_BLOCKS_READ`, HTTP 422), the
        active-flag requirement for hazard skips (`ERR_SKIP_REQUIRES_ACTIVE_HAZARD`,
        HTTP 409), and the evidence-preservation hold on meters under
        investigation (`ERR_EVIDENCE_PRESERVATION_HOLD`, HTTP 409). Temporal
        business rules follow: the `read_at` window check
        (`ERR_READ_OUTSIDE_WINDOW`, HTTP 422), the route-schedule window check
        (`ERR_ROUTE_OUTSIDE_READ_WINDOW`, HTTP 422), and technician
        shift-window conflicts (`ERR_TECHNICIAN_WINDOW_CONFLICT`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_hazard_beats_business_temporal_window
        """
        _account, meter, _route, stop, tech = self._pending_stop_with_active_hazard(api)

        res = api.capture_read(
            stop["id"],
            # read_at one day after window close violates the temporal rule too
            capture_read_payload(
                meter["id"], 100, "2026-08-11T09:00:00Z", stop["version"]
            ),
            make_field_technician_headers(tech["id"]),
        )
        error = validate_error(res, ApiErrorId.ERR_ACTIVE_HAZARD_BLOCKS_READ.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_READ_OUTSIDE_WINDOW.value

    def test_stop_unchanged_after_hazard_priority_rejection(self, api):
        """PRD section 2.10: "A service account carrying an `ACTIVE` hazard
        flag blocks field read capture on its stops unless the route was
        explicitly planned as a two-person crew (`two_person_crew`), in which
        case capture proceeds."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_hazard_beats_business_temporal_window
        """
        _account, meter, _route, stop, tech = self._pending_stop_with_active_hazard(api)

        res = api.capture_read(
            stop["id"],
            capture_read_payload(
                meter["id"], 100, "2026-08-11T09:00:00Z", stop["version"]
            ),
            make_field_technician_headers(tech["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ACTIVE_HAZARD_BLOCKS_READ.value, 422)
        assert get_stop(stop["id"])["stop_status"] == "PENDING"


class TestCaptureRejectRecapture:
    def _captured_then_rejected(self, api):
        """Three handheld accounts; route IN_PROGRESS; stop_1 captured then
        its read rejected. Returns (meters, route, stops, tech, read_1)."""
        set_logical_clock("2026-08-01T00:00:00Z")
        accounts, meters = [], []
        for i in range(1, 4):
            account, meter = setup_account_with_installed_meter(
                f"A-93{i:02d}", "C22", service_address=f"8{i} Poplar St"
            )
            accounts.append(account)
            meters.append(meter)
        period, route, stops, tech = setup_in_progress_route(
            "C22",
            "2026-08-01",
            "2026-08-31",
            "2026-08-03",
            "2026-08-07",
            "2026-08-31",
            "2026-08-03",
            route_shift="FULL",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="Tech Thirteen",
        )
        assert len(stops) == 3
        stop_1 = stops[0]
        read_1 = validate_success(
            api.capture_read(
                stop_1["id"],
                capture_read_payload(
                    meters[0]["id"], 100, "2026-08-03T09:00:00Z", stop_1["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        validate_success(
            api.reject_read(read_1["id"], {"rejection_reason": "IMPLAUSIBLE_SPIKE"}, BILLING),
            200,
        )
        return meters, route, stops, tech, read_1

    def test_reject_returns_stop_to_no_read_pending(self, api):
        """PRD section 3.4: "Rejection moves a `PROVISIONAL` read to
        `REJECTED` with a mandatory `rejection_reason`; the owning stop, when
        its `current_read_id` is this read, falls back from `READ_CAPTURED` to
        `NO_READ_PENDING` with `no_read_reason` `READ_REJECTED`, and the
        stop's `current_read_id` is cleared to null — a rejected read is never
        superseded by a later capture."
        PRD section 3.4: "`SUPERSEDED` and `REJECTED` reads are never
        billable"

        Design: Difficulty/compensating_invariant/capture_reject_recapture_conserves_stop_partition
        """
        _meters, _route, stops, _tech, read_1 = self._captured_then_rejected(api)

        stop_after = get_stop(stops[0]["id"])
        assert stop_after["stop_status"] == "NO_READ_PENDING"
        assert stop_after["no_read_reason"] == "READ_REJECTED"
        assert stop_after["current_read_id"] is None
        # create v1 -> capture v2 -> reject cascade v3 (cascade mutations bump
        # version per PRD 2.5: "any mutation — client-driven or cascaded —
        # refreshes `updated_at` and increments `version`")
        assert stop_after["version"] == 3

        rejected = get_read(read_1["id"])
        assert rejected["read_status"] == "REJECTED"
        assert rejected["is_billable"] is False

    def test_recapture_after_reject_conserves_stop_partition(self, api):
        """PRD section 3.2: "`stops_total` counts the route's stops excluding
        any in `CANCELLED`, and `captured_stop_count` counts stops in
        `READ_CAPTURED`, `VALIDATED`, `ESTIMATED`, or `SUPERSEDED`."
        PRD section 3.4: "Rejection moves a `PROVISIONAL` read to `REJECTED`
        with a mandatory `rejection_reason`; the owning stop, when its
        `current_read_id` is this read, falls back from `READ_CAPTURED` to
        `NO_READ_PENDING` with `no_read_reason` `READ_REJECTED`, and the
        stop's `current_read_id` is cleared to null — a rejected read is never
        superseded by a later capture."

        Design: Difficulty/compensating_invariant/capture_reject_recapture_conserves_stop_partition
        """
        meters, route, stops, tech, read_1 = self._captured_then_rejected(api)

        stop_after = get_stop(stops[0]["id"])
        read_2 = validate_success(
            api.capture_read(
                stops[0]["id"],
                capture_read_payload(
                    meters[0]["id"], 150, "2026-08-03T10:00:00Z", stop_after["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        assert read_2["read_status"] == "PROVISIONAL"
        # the rejected read is never superseded, so nothing was superseded here
        assert read_2["supersedes_read_id"] is None
        assert get_read(read_1["id"])["read_status"] == "REJECTED"

        route_after = get_route(route["id"])
        assert route_after["stops_total"] == 3
        assert route_after["captured_stop_count"] == 1

        histogram = {}
        for stop in get_route_stops(route["id"]):
            histogram[stop["stop_status"]] = histogram.get(stop["stop_status"], 0) + 1
        assert histogram == {"READ_CAPTURED": 1, "PENDING": 2}
        assert sum(histogram.values()) == route_after["stops_total"]


class TestCaptureGuards:
    def test_capture_with_meter_not_installed_at_account_rejected(self, api):
        """PRD section 3.3: "The request is then checked, in the §2.6 order,
        against the route being `IN_PROGRESS` (`ERR_ROUTE_NOT_IN_PROGRESS`),
        the period being `WINDOW_OPEN` (`ERR_READ_WINDOW_NOT_OPEN`), the hazard
        screen — an `ACTIVE` hazard flag on the account blocks capture unless
        the route's `two_person_crew` is true (`ERR_ACTIVE_HAZARD_BLOCKS_READ`,
        HTTP 422) — the `read_at` date falling inside the read window on both
        ends (`ERR_READ_OUTSIDE_WINDOW`), the presented `meter_id` being the
        account's currently installed meter (`ERR_METER_NOT_INSTALLED_AT_ACCOUNT`,
        HTTP 409), and the rollback rule against `last_validated_read_value`
        (`ERR_READ_ROLLBACK`)."

        Design: Corner/validations/capture_with_meter_not_installed_at_account_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, m1 = setup_account_with_installed_meter(
            "C-0075", "C75", service_address="75 Wrong Rd"
        )
        m2 = create_meter("SN-WM-2", "HANDHELD")  # stays IN_STOCK, never installed
        period, route, stops, tech = setup_in_progress_route(
            "C75",
            "2026-08-01",
            "2026-08-31",
            "2026-08-03",
            "2026-08-07",
            "2026-08-31",
            "2026-08-03",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="WrongMeter Tech",
        )
        assert len(stops) == 1
        stop = stops[0]

        res = api.capture_read(
            stop["id"],
            capture_read_payload(m2["id"], 100, "2026-08-03T09:00:00Z", stop["version"]),
            make_field_technician_headers(tech["id"]),
        )
        validate_error(res, ApiErrorId.ERR_METER_NOT_INSTALLED_AT_ACCOUNT.value, 409)
        assert get_stop(stop["id"])["stop_status"] == "PENDING"

    def test_capture_allowed_with_two_person_crew_despite_active_hazard(self, api):
        """PRD section 2.10: "A service account carrying an `ACTIVE` hazard
        flag blocks field read capture on its stops unless the route was
        explicitly planned as a two-person crew (`two_person_crew`), in which
        case capture proceeds."

        Design: Corner/validations/capture_allowed_with_two_person_crew_despite_active_hazard
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter(
            "C-0084", "C84", service_address="84 Crew Rd"
        )
        period, route, stops, tech = setup_in_progress_route(
            "C84",
            "2026-08-01",
            "2026-08-31",
            "2026-08-03",
            "2026-08-07",
            "2026-08-31",
            "2026-08-03",
            two_person_crew=True,
            open_clock="2026-08-03T08:00:00Z",
            tech_name="Crew Tech",
        )
        assert len(stops) == 1
        stop = stops[0]
        report_hazard(account["id"], tech["id"], hazard_type="DOG", severity="HIGH")

        read = validate_success(
            api.capture_read(
                stop["id"],
                capture_read_payload(
                    meter["id"], 640, "2026-08-03T09:00:00Z", stop["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        assert read["read_status"] == "PROVISIONAL"
        assert get_stop(stop["id"])["stop_status"] == "READ_CAPTURED"

    def test_correction_capture_requires_admin_and_supersedes_provisional(self, api):
        """PRD section 3.3: "Ordinarily the caller is the route's assigned
        `FieldTechnician`; the alternative path is an administrative correction
        — a payload with `correction` set true — which only a `MeterOpsAdmin`
        may send, and a `FieldTechnician` presenting `correction` as true is
        rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD section 3.3: "Re-capturing a stop already in `READ_CAPTURED`
        transitions the prior provisional current read to `SUPERSEDED` with its
        `supersedes_read_id` pointing at the new read."

        Design: Corner/validations/correction_capture_requires_admin_and_supersedes_provisional
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter(
            "C-0085", "C85", service_address="85 Corr Rd"
        )
        period, route, stops, tech = setup_in_progress_route(
            "C85",
            "2026-08-01",
            "2026-08-31",
            "2026-08-03",
            "2026-08-07",
            "2026-08-31",
            "2026-08-03",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="Corr Tech",
        )
        stop = stops[0]
        read_1 = validate_success(
            api.capture_read(
                stop["id"],
                capture_read_payload(
                    meter["id"], 800, "2026-08-03T09:00:00Z", stop["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        stop_v2 = get_stop(stop["id"])
        assert stop_v2["stop_status"] == "READ_CAPTURED"

        # A FieldTechnician presenting correction=true is role-rejected.
        res = api.capture_read(
            stop["id"],
            capture_read_payload(
                meter["id"],
                850,
                "2026-08-03T10:00:00Z",
                stop_v2["version"],
                correction=True,
            ),
            make_field_technician_headers(tech["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)

        # The MeterOpsAdmin correction path succeeds and supersedes the prior
        # provisional read.
        read_2 = validate_success(
            api.capture_read(
                stop["id"],
                capture_read_payload(
                    meter["id"],
                    850,
                    "2026-08-03T10:00:00Z",
                    stop_v2["version"],
                    correction=True,
                ),
                ADMIN,
            ),
            201,
        )
        assert read_2["read_status"] == "PROVISIONAL"
        prior = get_read(read_1["id"])
        assert prior["read_status"] == "SUPERSEDED"
        stop_after = get_stop(stop["id"])
        assert stop_after["current_read_id"] == read_2["id"]


class TestCaptureOcc:
    def test_occ_stop_read_capture_stale_version(self, api):
        """PRD section 2.7: "Capturing a read on a route stop
        (`POST /route-stops/{id}/reads`) requires
        `expected_route_stop_version` matching the stop's current `version`.
        Re-capture from `READ_CAPTURED` and actual-supersedes-estimate from
        `ESTIMATED` are both legitimate supersede operations, so a
        stale-version capture would otherwise overwrite a newer read the
        client never saw."
        PRD section 2.7: "if another writer has advanced the resource's
        `version` since the client last read it, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting
        a state it has not observed."

        Design: Corner/complexity_layers/occ_stop_read_capture_stale_version
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter(
            "C-0130", "CE2", service_address="130 Occ Rd"
        )
        period, route, stops, tech = setup_in_progress_route(
            "CE2",
            "2026-08-01",
            "2026-08-31",
            "2026-08-03",
            "2026-08-07",
            "2026-08-31",
            "2026-08-03",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="OCC Stop Tech",
        )
        stop = stops[0]

        read_1 = validate_success(
            api.capture_read(
                stop["id"],
                capture_read_payload(
                    meter["id"], 100, "2026-08-03T09:00:00Z", stop["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        assert read_1["read_status"] == "PROVISIONAL"

        # Replaying the pre-capture version is rejected even though re-capture
        # from READ_CAPTURED is itself a legitimate operation.
        stale = api.capture_read(
            stop["id"],
            capture_read_payload(
                meter["id"], 150, "2026-08-03T09:05:00Z", stop["version"]
            ),
            make_field_technician_headers(tech["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

        stop_v2 = get_stop(stop["id"])
        read_2 = validate_success(
            api.capture_read(
                stop["id"],
                capture_read_payload(
                    meter["id"], 150, "2026-08-03T09:05:00Z", stop_v2["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        assert read_2["read_status"] == "PROVISIONAL"
        assert get_read(read_1["id"])["read_status"] == "SUPERSEDED"
        assert get_stop(stop["id"])["current_read_id"] == read_2["id"]

    def test_occ_version_checked_before_business_rules(self, api):
        """PRD section 2.6: "Seventh, the optimistic-concurrency check on the
        three version-guarded writes (`ERR_STALE_VERSION`, HTTP 412; see
        §2.7)."
        PRD section 2.6: "Business constraints close the middle of the ladder:
        register rollback (`ERR_READ_ROLLBACK`, HTTP 422); meter installation
        and swap rules (`ERR_ACCOUNT_HAS_INSTALLED_METER` and
        `ERR_METER_NOT_AVAILABLE_FOR_INSTALL` at HTTP 409,
        `ERR_METER_NOT_INSTALLED_AT_ACCOUNT` at HTTP 409, `ERR_METER_NOT_AMI`
        at HTTP 422); uniqueness (`ERR_DUPLICATE_ACCOUNT_NUMBER` and
        `ERR_DUPLICATE_SERIAL_NUMBER`, HTTP 409); estimate eligibility
        (`ERR_ESTIMATE_CAP_REACHED` and `ERR_INSUFFICIENT_READ_HISTORY`, HTTP
        409); account lifecycle gates (`ERR_ACCOUNT_NOT_ACTIVE`,
        `ERR_ACCOUNT_HAS_OPEN_INVESTIGATION`, and `ERR_ACCOUNT_HAS_OPEN_WORK`,
        HTTP 409); technician lifecycle gates (`ERR_TECHNICIAN_NOT_ACTIVE` and
        `ERR_TECHNICIAN_HAS_OPEN_WORK`, HTTP 409); and the
        one-open-investigation-per-meter rule (`ERR_INVESTIGATION_ALREADY_OPEN`,
        HTTP 409)."

        Design: Corner/validations/occ_version_checked_before_business_rules
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter(
            "C-0071", "C71", meter_type="AMI", service_address="71 Occ Rd"
        )
        ingest_ami_read(meter["id"], 10000, "2026-08-02T10:00:00Z")
        run_ops_snapshot("2026-08-03T00:00:00Z")  # sees the 08-02 read; no miss
        run_ops_snapshot("2026-08-04T00:00:00Z")  # first miss -> DEGRADED
        period, route, stops, tech = setup_in_progress_route(
            "C71",
            "2026-08-01",
            "2026-08-31",
            "2026-08-04",
            "2026-08-07",
            "2026-08-31",
            "2026-08-04",
            open_clock="2026-08-04T08:00:00Z",
            tech_name="OCC Prio Tech",
        )
        stop = stops[0]
        validate_success(
            api.capture_read(
                stop["id"],
                capture_read_payload(
                    meter["id"], 10100, "2026-08-04T09:00:00Z", stop["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )

        # Stale version AND a rollback value (9000 < 10000): the OCC gate runs
        # before business rules, so ERR_STALE_VERSION must surface.
        res = api.capture_read(
            stop["id"],
            capture_read_payload(
                meter["id"], 9000, "2026-08-04T10:00:00Z", stop["version"]
            ),
            make_field_technician_headers(tech["id"]),
        )
        error = validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, 412)
        assert error["error_id"] != ApiErrorId.ERR_READ_ROLLBACK.value
        assert get_stop(stop["id"])["stop_status"] == "READ_CAPTURED"

    def test_immediate_consistency_read_after_write(self, api):
        """PRD section 2.12: "Consistency is immediate, never deferred."
        PRD section 3.3: "A successful capture creates a MeterRead with
        `read_source` `HANDHELD` and `read_status` `PROVISIONAL`, moves the
        stop to `READ_CAPTURED`, points the stop's `current_read_id` at the new
        read, and increments the stop's `version` by one."

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter(
            "C-0140", "CF1", service_address="140 Imm Rd"
        )
        period, route, stops, tech = setup_in_progress_route(
            "CF1",
            "2026-08-01",
            "2026-08-31",
            "2026-08-03",
            "2026-08-07",
            "2026-08-31",
            "2026-08-03",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="Imm Tech",
        )
        stop = stops[0]
        read = validate_success(
            api.capture_read(
                stop["id"],
                capture_read_payload(meter["id"], 77, "2026-08-03T09:00:00Z", stop["version"]),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        stop_after = get_stop(stop["id"])
        assert stop_after["current_read_id"] == read["id"]
        assert stop_after["stop_status"] == "READ_CAPTURED"
