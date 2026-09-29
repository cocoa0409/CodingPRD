"""The validation ladder of PRD §2.8 exercised at its ordering boundaries.

Every test here puts two rules in violation at once — or drives the same request
through a sequence of clock and posture states — so that the position a check
occupies on the ladder is observable rather than incidental.

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
    TEST_DEFAULTS,
    ApiErrorId,
    api_client,
    append_log_entry,
    assert_filing_record,
    assert_monitoring_assignment,
    assert_score_and_posture,
    assert_summary_inputs,
    assert_test_event,
    assert_test_log_entry,
    create_active_plan,
    create_ready_device,
    evaluate_readiness,
    file_results,
    filing_record_payload,
    get_success_data,
    make_engineer_headers,
    monitoring_assignment_payload,
    register_station,
    schedule_test_event,
    set_clock,
    setup_ready_test_event,
    setup_station,
    station_summary,
    station_version,
    validate_error,
    validate_paginated,
    validate_success,
    UNRESOLVABLE_UUID,
)
from test_helpers import test_event_payload as make_test_event_payload
from test_helpers import test_event_version as current_test_event_version

# ---------------------------------------------------------------------------
# Shared instants
# ---------------------------------------------------------------------------
WINDOW_START = "2026-08-12T00:00:00Z"
WINDOW_END = "2026-08-12T01:00:00Z"
FILING_DEADLINE = "2026-08-17T01:00:00Z"
LOG_INSTANT = "2026-08-12T00:30:00Z"
AFTER_WINDOW = "2026-08-12T02:00:00Z"
PAST_WINDOW_START = "2026-07-01T00:00:00Z"
PAST_WINDOW_END = "2026-07-01T01:00:00Z"

# The first test event of the two-filing ceiling fixture.
TE1_WINDOW_START = "2026-08-05T00:00:00Z"
TE1_WINDOW_END = "2026-08-05T01:00:00Z"
TE1_LOG_INSTANT = "2026-08-05T00:30:00Z"
TE1_FILED_AT = "2026-08-13T01:00:00Z"
TE2_FILED_AT = "2026-08-20T01:00:00Z"

UNASSIGNED_ENGINEER = make_engineer_headers("eng-9")


def _instant(value):
    """Parse an ISO 8601 UTC instant so two spellings of one instant compare equal."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant(actual, expected_iso, label):
    assert actual is not None, f"{label} must be set"
    assert _instant(actual) == _instant(expected_iso), (
        f"expected {label} == {expected_iso}, got {actual}"
    )


def _station_with_stale_version(engineer_user_ids=None):
    """Active plan requiring PEP and SATELLITE, a station, a READY device and one
    ACTIVE PEP assignment created with the station version captured immediately
    beforehand — so that captured value is now stale by exactly one."""
    plan = create_active_plan(("PEP", "SATELLITE"))
    station = register_station(plan["id"], engineer_user_ids=engineer_user_ids)
    device = create_ready_device(station["id"])
    stale_version = station_version(station["id"])
    assignment = get_success_data(
        api_client.create_monitoring_assignment(
            monitoring_assignment_payload(
                station["id"], device["id"], stale_version, source_type="PEP"
            ),
            ENGINEER,
        ),
        201,
    )
    return station, device, stale_version, assignment


def _suspended_station():
    """A station covering both required source types, then stripped of both, so its
    score falls to 100.00 - 2 * 25.00 == 50.00 and its posture is SUSPENDED_FILINGS."""
    ctx = setup_station(required_source_types=("PEP", "SATELLITE"))
    for assignment in ctx["assignments"].values():
        get_success_data(
            api_client.decommission_assignment(assignment["id"], ENGINEER)
        )
    return ctx


def _station_with_foreign_ready_device():
    """Two stations on one plan, both rostering the same engineer, each with its own
    READY device, plus a READY test event on the first station."""
    ctx = setup_station()
    other_station = register_station(
        ctx["plan_id"],
        call_sign=TEST_DEFAULTS["SECOND_CALL_SIGN"],
        service_type="FM",
    )
    other_device = create_ready_device(other_station["id"])
    event = schedule_test_event(ctx["station_id"], WINDOW_START, WINDOW_END)
    set_clock(LOG_INSTANT)
    ctx["test_event"] = evaluate_readiness(event["id"])
    ctx["test_event_id"] = event["id"]
    ctx["other_station"] = other_station
    ctx["other_device"] = other_device
    return ctx


def _station_with_two_logged_test_events():
    """One station with two disjoint weekly test windows, both taken to LOGGED — the
    first with three log lines, the second with two."""
    ctx = setup_station()
    te1 = schedule_test_event(ctx["station_id"], TE1_WINDOW_START, TE1_WINDOW_END)
    te2 = schedule_test_event(ctx["station_id"], WINDOW_START, WINDOW_END)

    set_clock(TE1_LOG_INSTANT)
    evaluate_readiness(te1["id"])
    append_log_entry(te1["id"], ctx["device_id"], "TRANSMISSION")
    append_log_entry(te1["id"], ctx["device_id"], "RECEIPT")
    append_log_entry(te1["id"], ctx["device_id"], "RECEIPT")
    get_success_data(api_client.close_logging(te1["id"], ENGINEER))

    set_clock(LOG_INSTANT)
    evaluate_readiness(te2["id"])
    append_log_entry(te2["id"], ctx["device_id"], "TRANSMISSION")
    append_log_entry(te2["id"], ctx["device_id"], "RECEIPT")
    get_success_data(api_client.close_logging(te2["id"], ENGINEER))

    ctx["te1"] = te1
    ctx["te2"] = te2
    return ctx


class TestRoleDenialBeforeExistence:
    """Ladder position 2 runs to completion before position 4 resolves any id."""

    def test_wrong_role_is_refused_before_the_unresolvable_id_is_resolved(self):
        """PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.8: "The ladder is evaluated strictly in this order, and a check never runs before every lower-numbered check has passed."
        PRD §2.8: "2. **Role authorisation for the endpoint** — `ERR_UNAUTHORIZED`, 403. Applies to every endpoint."
        PRD §2.8: "4. **Existence** — the 404 family. Applies to every endpoint that carries an id in its path or a foreign-key id in its body."

        Design: Corner/validations/role_denial_precedes_the_missing_row_lookup
        """
        plan = create_active_plan()
        register_station(plan["id"])

        validate_error(
            api_client.evaluate_readiness(UNRESOLVABLE_UUID, INSPECTOR),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        validate_error(
            api_client.create_test_event(
                make_test_event_payload(UNRESOLVABLE_UUID, WINDOW_START, WINDOW_END),
                INSPECTOR,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

    def test_authorised_role_reaches_the_existence_check_on_path_and_body_ids(self):
        """PRD §2.9: "Identifier resolution is strictly left to right, and the first identifier that fails to resolve determines the error reported."
        PRD §2.9: "Path identifiers resolve before body identifiers; among body identifiers, resolution follows the order in which they are listed for that endpoint in §3."
        PRD §2.9: "Each entity type has its own not-found code so that a caller can tell which reference broke: `ERR_STATE_PLAN_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_RELAY_RULE_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_OUTAGE_NOT_FOUND`, `ERR_ALERT_EVENT_NOT_FOUND`, `ERR_WEA_NOTICE_NOT_FOUND`, `ERR_TEST_EVENT_NOT_FOUND`, `ERR_LOG_ENTRY_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and `ERR_INSPECTION_NOT_FOUND`."

        Design: Corner/validations/role_denial_precedes_the_missing_row_lookup
        """
        plan = create_active_plan()
        register_station(plan["id"])

        validate_error(
            api_client.create_test_event(
                make_test_event_payload(UNRESOLVABLE_UUID, WINDOW_START, WINDOW_END),
                ADMIN,
            ),
            ApiErrorId.ERR_STATION_NOT_FOUND,
        )
        validate_error(
            api_client.evaluate_readiness(UNRESOLVABLE_UUID, ENGINEER),
            ApiErrorId.ERR_TEST_EVENT_NOT_FOUND,
        )

        _, meta = validate_paginated(api_client.list_test_events(ADMIN))
        assert meta["total_count"] == 0, (
            f"no test event may exist after four refused calls, got {meta['total_count']}"
        )


class TestSchemaBeforeExistence:
    """Ladder position 3 completes — enum membership and window ordering alike —
    before any foreign key is looked up."""

    def test_schema_failure_is_reported_before_the_unresolvable_station_reference(self):
        """PRD §2.8: "This check covers presence of every required body field, membership of every enum value in its declared set, numeric ranges, array shapes, the requirement that `window_start_at` be strictly earlier than `window_end_at`, and the rule that `source_call_sign` is present on a `RECEIPT` log line and absent on a `TRANSMISSION` log line."
        PRD §3.6: "The two bounds must satisfy `window_start_at` strictly earlier than `window_end_at`, and a payload that does not is a schema failure."
        PRD §2.8: "The ladder is evaluated strictly in this order, and a check never runs before every lower-numbered check has passed."

        Design: Corner/validations/schema_rejection_precedes_the_fk_lookup
        """
        plan = create_active_plan()
        station = register_station(plan["id"])

        validate_error(
            api_client.create_test_event(
                make_test_event_payload(
                    UNRESOLVABLE_UUID, WINDOW_START, WINDOW_END, test_type="DAILY"
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )
        validate_error(
            api_client.create_test_event(
                make_test_event_payload(UNRESOLVABLE_UUID, WINDOW_END, WINDOW_END),
                ADMIN,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )
        validate_error(
            api_client.create_test_event(
                make_test_event_payload(
                    station["id"], WINDOW_START, WINDOW_END, test_type="DAILY"
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

    def test_well_formed_schedule_lands_in_scheduled_with_the_derived_deadline(self):
        """PRD §3.6: "A newly scheduled event sits in `SCHEDULED` with `readiness_score` and `readiness_evaluated_at` null, `logged_entry_count` 0 and `retention_until_max` null, and the server derives `filing_deadline_at` at create time as `window_end_at` plus five days."

        Design: Corner/validations/schema_rejection_precedes_the_fk_lookup
        """
        plan = create_active_plan()
        station = register_station(plan["id"])

        event = validate_success(
            api_client.create_test_event(
                make_test_event_payload(station["id"], WINDOW_START, WINDOW_END), ADMIN
            ),
            201,
        )
        assert_test_event(event)
        assert event["status"] == "SCHEDULED", (
            f"a new test event opens in SCHEDULED, got {event['status']}"
        )
        assert event["readiness_score"] is None
        assert event["readiness_evaluated_at"] is None
        assert event["logged_entry_count"] == 0
        _assert_instant(event["filing_deadline_at"], FILING_DEADLINE, "filing_deadline_at")

        _, meta = validate_paginated(
            api_client.list_test_events(ADMIN, params={"station_id": station["id"]})
        )
        assert meta["total_count"] == 1, (
            f"exactly one test event may exist for the station, got {meta['total_count']}"
        )


class TestExistenceBeforeConcurrency:
    """Ladder position 4 wins over position 6: one captured version drives a 404, a
    412 and a success."""

    def test_unresolvable_station_beats_the_stale_station_version(self):
        """PRD §2.7: "If that value does not equal the station's current `version`, the create is rejected with `ERR_STALE_STATION_VERSION` and HTTP 412."
        PRD §2.8: "4. **Existence** — the 404 family. Applies to every endpoint that carries an id in its path or a foreign-key id in its body."
        PRD §2.8: "6. **Concurrency** — `ERR_STALE_STATION_VERSION` or `ERR_STALE_TEST_EVENT_VERSION`, both 412. Applies to `POST /monitoring-assignments` and `POST /filing-records` respectively, per §2.7."

        Design: Corner/validations/existence_precedes_occ_then_stale_version_then_success
        """
        station, device, stale_version, _ = _station_with_stale_version()

        validate_error(
            api_client.create_monitoring_assignment(
                monitoring_assignment_payload(
                    UNRESOLVABLE_UUID, device["id"], stale_version,
                    source_type="SATELLITE",
                ),
                ENGINEER,
            ),
            ApiErrorId.ERR_STATION_NOT_FOUND,
        )
        assert station_version(station["id"]) == stale_version + 1, (
            "only the accepted PEP create may have incremented the station version"
        )

    def test_stale_then_freshly_read_station_version_on_the_same_create(self):
        """PRD §2.7: "If that value does not equal the station's current `version`, the create is rejected with `ERR_STALE_STATION_VERSION` and HTTP 412."
        PRD §2.7: "A successful create increments the station's `version` by one, so a client that reads the station once and then creates two assignments must re-read between them."

        Design: Corner/validations/existence_precedes_occ_then_stale_version_then_success
        """
        station, device, stale_version, _ = _station_with_stale_version()

        validate_error(
            api_client.create_monitoring_assignment(
                monitoring_assignment_payload(
                    station["id"], device["id"], stale_version, source_type="SATELLITE"
                ),
                ENGINEER,
            ),
            ApiErrorId.ERR_STALE_STATION_VERSION,
        )

        fresh_version = station_version(station["id"])
        assert fresh_version == stale_version + 1, (
            f"the rejected create must not bump the version: expected "
            f"{stale_version + 1}, got {fresh_version}"
        )

        assignment = validate_success(
            api_client.create_monitoring_assignment(
                monitoring_assignment_payload(
                    station["id"], device["id"], fresh_version, source_type="SATELLITE"
                ),
                ENGINEER,
            ),
            201,
        )
        assert_monitoring_assignment(assignment)
        assert assignment["status"] == "ACTIVE"

        summary = station_summary(station["id"])
        assert_summary_inputs(
            summary,
            required_source_count=2,
            accessible_source_count=2,
            missing_source_count=0,
        )
        assert_score_and_posture(summary, 100.00, "COMPLIANT")


class TestOwnershipBeforeConcurrency:
    """Ladder position 5 is evaluated against the target station before position 6
    compares versions."""

    def test_unassigned_engineer_is_refused_with_a_stale_and_with_a_fresh_version(self):
        """PRD §2.1: "For every write endpoint reached by a `StationEngineer`, the acting `X-User-ID` must appear in the `engineer_user_ids` array of the station the write ultimately targets; if it does not, the request is rejected with `ERR_ENGINEER_NOT_ASSIGNED` (HTTP 403)."
        PRD §2.8: "5. **Ownership** — `ERR_ENGINEER_NOT_ASSIGNED` or `ERR_NOT_CERTIFYING_OFFICER`, both 403. Applies to every `StationEngineer` and `CertifyingOfficer` write endpoint, using the rules of §2.1."
        PRD §2.8: "6. **Concurrency** — `ERR_STALE_STATION_VERSION` or `ERR_STALE_TEST_EVENT_VERSION`, both 412. Applies to `POST /monitoring-assignments` and `POST /filing-records` respectively, per §2.7."

        Design: Corner/validations/ownership_check_precedes_the_occ_version_check
        """
        station, device, stale_version, _ = _station_with_stale_version()

        validate_error(
            api_client.create_monitoring_assignment(
                monitoring_assignment_payload(
                    station["id"], device["id"], stale_version, source_type="SATELLITE"
                ),
                UNASSIGNED_ENGINEER,
            ),
            ApiErrorId.ERR_ENGINEER_NOT_ASSIGNED,
        )

        fresh_version = station_version(station["id"])
        validate_error(
            api_client.create_monitoring_assignment(
                monitoring_assignment_payload(
                    station["id"], device["id"], fresh_version, source_type="SATELLITE"
                ),
                UNASSIGNED_ENGINEER,
            ),
            ApiErrorId.ERR_ENGINEER_NOT_ASSIGNED,
        )

    def test_assigned_engineer_with_the_same_stale_version_reaches_concurrency(self):
        """PRD §2.7: "If that value does not equal the station's current `version`, the create is rejected with `ERR_STALE_STATION_VERSION` and HTTP 412."
        PRD §3.8: "25.00 points for every required source type the station is missing, where the missing count is the plan's `required_source_count` less the station's `accessible_source_count`, floored at zero so that over-coverage never earns a credit"

        Design: Corner/validations/ownership_check_precedes_the_occ_version_check
        """
        station, device, stale_version, _ = _station_with_stale_version()
        fresh_version = station_version(station["id"])

        validate_error(
            api_client.create_monitoring_assignment(
                monitoring_assignment_payload(
                    station["id"], device["id"], stale_version, source_type="SATELLITE"
                ),
                ENGINEER,
            ),
            ApiErrorId.ERR_STALE_STATION_VERSION,
        )

        assert station_version(station["id"]) == fresh_version, (
            "a refused create leaves the station version where it was"
        )
        rows, meta = validate_paginated(
            api_client.list_monitoring_assignments(
                ADMIN, params={"station_id": station["id"], "source_type": "SATELLITE"}
            )
        )
        assert meta["total_count"] == 0, (
            f"no SATELLITE assignment may exist, got {meta['total_count']}: {rows}"
        )

        summary = station_summary(station["id"])
        assert_summary_inputs(
            summary,
            required_source_count=2,
            accessible_source_count=1,
            missing_source_count=1,
        )
        assert_score_and_posture(summary, 75.00, "WATCH")


class TestStateBeforePostureSafety:
    """Ladder position 7 wins over position 8 on one and the same filing."""

    def test_scheduled_event_at_a_suspended_station_reports_test_not_logged(self):
        """PRD §3.7: "The event's `status` must be `LOGGED` or `FILED`; anything else is rejected with `ERR_TEST_NOT_LOGGED`, except that an event already in `FAILED_UNFILED` is rejected with the more specific `ERR_TEST_ALREADY_FAILED_UNFILED`."
        PRD §3.7: "The owning station's `compliance_posture` must not be `SUSPENDED_FILINGS`, otherwise `ERR_FILINGS_SUSPENDED`."
        PRD §2.8: "7. **State** — the 409 state family. Applies to every state-transition endpoint: the target row must currently be in one of the states the requested transition declares as a legal starting state."
        PRD §2.8: "8. **Posture safety** — 422. Applies to two endpoints: `POST /filing-records` is rejected with `ERR_FILINGS_SUSPENDED` and `POST /test-events` is rejected with `ERR_POSTURE_NOT_TEST_ELIGIBLE`, in both cases when the owning station's `compliance_posture` is `SUSPENDED_FILINGS`."

        Design: Corner/validations/state_error_precedes_the_posture_suspension_check
        """
        ctx = setup_station(required_source_types=("PEP", "SATELLITE"))
        event = schedule_test_event(ctx["station_id"], WINDOW_START, WINDOW_END)
        for assignment in ctx["assignments"].values():
            get_success_data(
                api_client.decommission_assignment(assignment["id"], ENGINEER)
            )

        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(
            summary, accessible_source_count=0, missing_source_count=2
        )
        assert_score_and_posture(summary, 50.00, "SUSPENDED_FILINGS")

        event_version = current_test_event_version(event["id"])
        assert get_success_data(
            api_client.get_test_event(event["id"], ADMIN)
        )["status"] == "SCHEDULED"

        validate_error(
            api_client.create_filing_record(
                filing_record_payload(event["id"], event_version), OFFICER
            ),
            ApiErrorId.ERR_TEST_NOT_LOGGED,
        )

        _, meta = validate_paginated(
            api_client.list_filing_records(
                ADMIN, params={"test_event_id": event["id"]}
            )
        )
        assert meta["total_count"] == 0, "the refused filing stored no row"
        assert current_test_event_version(event["id"]) == event_version, (
            "a refused filing does not consume the test event's version"
        )
        assert station_summary(ctx["station_id"])["penalty_points_total"] == 0.00


class TestPostureSafetyBeforeClockWindows:
    """Ladder position 8 wins over position 10, and position 10 becomes reachable
    once the posture recovers."""

    def test_suspended_posture_beats_the_past_test_window(self):
        """PRD §3.6: "A station whose `compliance_posture` is `SUSPENDED_FILINGS` may not have new tests scheduled at all, and the attempt is rejected with `ERR_POSTURE_NOT_TEST_ELIGIBLE`."
        PRD §3.6: "A `window_start_at` earlier than the logical clock's current value is rejected with `ERR_TEST_WINDOW_IN_PAST`."
        PRD §2.8: "8. **Posture safety** — 422. Applies to two endpoints: `POST /filing-records` is rejected with `ERR_FILINGS_SUSPENDED` and `POST /test-events` is rejected with `ERR_POSTURE_NOT_TEST_ELIGIBLE`, in both cases when the owning station's `compliance_posture` is `SUSPENDED_FILINGS`."
        PRD §2.8: "10. **Clock-relative windows** — `ERR_TEST_WINDOW_OVERLAP` carries 409; every other member of this group carries 422."

        Design: Corner/validations/posture_suspension_precedes_the_past_window_check
        """
        ctx = _suspended_station()
        assert_score_and_posture(
            station_summary(ctx["station_id"]), 50.00, "SUSPENDED_FILINGS"
        )

        validate_error(
            api_client.create_test_event(
                make_test_event_payload(
                    ctx["station_id"], PAST_WINDOW_START, PAST_WINDOW_END
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_POSTURE_NOT_TEST_ELIGIBLE,
        )

    def test_past_window_is_reported_once_the_posture_recovers(self):
        """PRD §3.3: "Reinstatement runs the other way, `DECOMMISSIONED` → `ACTIVE`, and carries three preconditions: the row must currently be `DECOMMISSIONED`, otherwise `ERR_ASSIGNMENT_NOT_DECOMMISSIONED`; no other assignment of the same station may be in `ACTIVE` with the same `source_type`, otherwise `ERR_SOURCE_TYPE_ALREADY_COVERED`; and the referenced unit must currently be in `READY`, otherwise `ERR_DEVICE_NOT_READY`."
        PRD §3.6: "A `window_start_at` earlier than the logical clock's current value is rejected with `ERR_TEST_WINDOW_IN_PAST`."

        Design: Corner/validations/posture_suspension_precedes_the_past_window_check
        """
        ctx = _suspended_station()
        for assignment in ctx["assignments"].values():
            reinstated = get_success_data(
                api_client.reinstate_assignment(assignment["id"], ENGINEER)
            )
            assert reinstated["status"] == "ACTIVE", (
                f"reinstatement lands in ACTIVE, got {reinstated['status']}"
            )

        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(summary, accessible_source_count=2)
        assert_score_and_posture(summary, 100.00, "COMPLIANT")

        validate_error(
            api_client.create_test_event(
                make_test_event_payload(
                    ctx["station_id"], PAST_WINDOW_START, PAST_WINDOW_END
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_TEST_WINDOW_IN_PAST,
        )

        event = validate_success(
            api_client.create_test_event(
                make_test_event_payload(ctx["station_id"], WINDOW_START, WINDOW_END), ADMIN
            ),
            201,
        )
        assert event["status"] == "SCHEDULED"
        _assert_instant(event["filing_deadline_at"], FILING_DEADLINE, "filing_deadline_at")


class TestReferentialCoherenceBeforeClockWindows:
    """Ladder position 9 is neither skipped nor shadowed by position 10."""

    def test_foreign_device_on_a_log_line_is_refused_inside_and_outside_the_window(self):
        """PRD §3.6: "The named unit must belong to the event's station, otherwise `ERR_DEVICE_STATION_MISMATCH`."
        PRD §2.8: "9. **Cross-row referential coherence** — 422. Applies to three endpoints: `POST /filing-records` (every source type the plan requires must have at least one receipt log line for the test event, else `ERR_RECEIPT_COVERAGE_INCOMPLETE`), `POST /test-log-entries` (a receipt line's `source_call_sign` must match a monitoring assignment of the station, else `ERR_LOG_ENTRY_SOURCE_UNKNOWN`; and the referenced device must belong to the test event's station, else `ERR_DEVICE_STATION_MISMATCH`), and `POST /monitoring-assignments` (the referenced device must belong to the referenced station, else `ERR_DEVICE_STATION_MISMATCH`)."
        PRD §2.8: "10. **Clock-relative windows** — `ERR_TEST_WINDOW_OVERLAP` carries 409; every other member of this group carries 422."

        Design: Corner/validations/device_station_mismatch_precedes_the_closed_logging_window
        """
        ctx = _station_with_foreign_ready_device()
        foreign_line = {
            "test_event_id": ctx["test_event_id"],
            "device_id": ctx["other_device"]["id"],
            "entry_kind": "TRANSMISSION",
        }

        validate_error(
            api_client.create_test_log_entry(foreign_line, ENGINEER),
            ApiErrorId.ERR_DEVICE_STATION_MISMATCH,
        )

        set_clock(AFTER_WINDOW)
        validate_error(
            api_client.create_test_log_entry(foreign_line, ENGINEER),
            ApiErrorId.ERR_DEVICE_STATION_MISMATCH,
        )

    def test_owned_device_outside_the_closed_logging_window_reports_the_window(self):
        """PRD §3.6: "The logical clock must lie inside the **closed** interval from `window_start_at` through `window_end_at` inclusive — this is where the end bound is inclusive — and a line offered outside it is rejected with `ERR_LOGGING_WINDOW_CLOSED`."
        PRD §3.6: "It is permitted only from `READY`, otherwise `ERR_TEST_NOT_READY`, and only when the event has at least one log line — an event whose `logged_entry_count` is 0 is rejected with `ERR_TEST_NO_ENTRIES`."

        Design: Corner/validations/device_station_mismatch_precedes_the_closed_logging_window
        """
        ctx = _station_with_foreign_ready_device()
        set_clock(AFTER_WINDOW)

        validate_error(
            api_client.create_test_log_entry(
                {
                    "test_event_id": ctx["test_event_id"],
                    "device_id": ctx["device_id"],
                    "entry_kind": "TRANSMISSION",
                },
                ENGINEER,
            ),
            ApiErrorId.ERR_LOGGING_WINDOW_CLOSED,
        )

        event = get_success_data(api_client.get_test_event(ctx["test_event_id"], ADMIN))
        assert event["logged_entry_count"] == 0, (
            f"no line was appended, got logged_entry_count {event['logged_entry_count']}"
        )
        assert event["status"] == "READY", (
            f"a refused line leaves the event in READY, got {event['status']}"
        )

        validate_error(
            api_client.close_logging(ctx["test_event_id"], ENGINEER),
            ApiErrorId.ERR_TEST_NO_ENTRIES,
        )


class TestStationPointCeiling:
    """Ladder position 12 is charged against the running station ledger, not against
    the single filing."""

    def test_first_late_filing_rounds_every_log_line_before_summing(self):
        """PRD §3.7: "Lateness comes first: `late_days` is 0 when `filed_at` is at or before the event's `filing_deadline_at`, and otherwise the number of whole days obtained by dividing the elapsed time between `filing_deadline_at` and `filed_at` by 86400 seconds and rounding that quotient **up** to the next whole number — so any part of a day late counts as a full day late."
        PRD §3.7: "For each log line — taking every line whose `test_event_id` matches, in `created_at` ascending order, with no status filter whatsoever since log lines have no status — multiply `late_days` by a per-entry late rate of 0.065 points and by that line's kind weight, and **round that per-line product half-up to two decimal places immediately**."
        PRD §3.7: "`lateness_points` is `late_days` multiplied by 0.75 points per late day, rounded half-up to two decimals."
        PRD §3.7: "`penalty_points` is then the smaller of a per-filing cap of 25.00 points and the sum of `entry_subtotal_points`, `lateness_points` and `unconfirmed_relay_points`, rounded half-up to two decimal places."

        Design: Corner/validations/two_individually_legal_filings_breach_the_station_point_ceiling
        """
        ctx = _station_with_two_logged_test_events()
        set_clock(TE1_FILED_AT)
        filing = file_results(ctx["te1"]["id"])

        assert_filing_record(filing)
        assert filing["late_days"] == 3, (
            f"expected late_days 3, got {filing['late_days']}"
        )
        assert filing["entry_subtotal_points"] == 0.75, (
            "three lines rounded individually give 0.35 + 0.20 + 0.20 == 0.75, got "
            f"{filing['entry_subtotal_points']}"
        )
        assert filing["lateness_points"] == 2.25
        assert filing["unconfirmed_relay_points"] == 0.00
        assert filing["penalty_points"] == 3.00
        assert filing["status"] == "SUBMITTED"

        assert station_summary(ctx["station_id"])["penalty_points_total"] == 3.00

    def test_second_filing_that_would_cross_five_points_is_refused(self):
        """PRD §3.7: "And last of all, the fiscal ceiling of §2.6 and §2.8 applies: the station's existing `penalty_points_total` plus the `penalty_points` this filing would compute must not exceed 5.00 points, otherwise `ERR_PENALTY_CEILING_EXCEEDED`."
        PRD §3.7: "Finally the station's ledger is resynchronised: `penalty_points_total` becomes the sum of `penalty_points` across all of that station's filing records whose `status` is `SUBMITTED` or `ACCEPTED`, rounded half-up to two decimal places."
        PRD §3.8: "When the station is not certified-eligible, `compliance_variant_applied` is `PROVISIONAL` and only the first four deductions are applied."

        Design: Corner/validations/two_individually_legal_filings_breach_the_station_point_ceiling
        """
        ctx = _station_with_two_logged_test_events()
        set_clock(TE1_FILED_AT)
        file_results(ctx["te1"]["id"])

        set_clock(TE2_FILED_AT)
        te2_version = current_test_event_version(ctx["te2"]["id"])
        validate_error(
            api_client.create_filing_record(
                filing_record_payload(ctx["te2"]["id"], te2_version), OFFICER
            ),
            ApiErrorId.ERR_PENALTY_CEILING_EXCEEDED,
        )

        _, meta = validate_paginated(
            api_client.list_filing_records(
                ADMIN, params={"test_event_id": ctx["te2"]["id"]}
            )
        )
        assert meta["total_count"] == 0, "the refused filing stored no row"

        te2 = get_success_data(api_client.get_test_event(ctx["te2"]["id"], ADMIN))
        assert te2["status"] == "LOGGED", (
            f"the refused filing left te2 in LOGGED, got {te2['status']}"
        )
        assert te2["version"] == te2_version, (
            "the refused filing did not consume the concurrency increment"
        )

        summary = station_summary(ctx["station_id"])
        assert summary["penalty_points_total"] == 3.00
        assert summary["compliance_variant_applied"] == "PROVISIONAL"
        assert_score_and_posture(summary, 100.00, "COMPLIANT")


class TestConditionalLogLineSchema:
    """`source_call_sign` is conditionally required in one direction and conditionally
    forbidden in the other."""

    def test_receipt_without_and_transmission_with_a_source_call_sign_are_refused(self):
        """PRD §3.6: "`source_call_sign` is required on a `RECEIPT` line, naming the monitored source's call sign, and is forbidden on a `TRANSMISSION` line; violating either half of that rule is a schema failure."
        PRD §2.8: "This check covers presence of every required body field, membership of every enum value in its declared set, numeric ranges, array shapes, the requirement that `window_start_at` be strictly earlier than `window_end_at`, and the rule that `source_call_sign` is present on a `RECEIPT` log line and absent on a `TRANSMISSION` log line."

        Design: Corner/validations/conditional_schema_rules_on_receipt_and_transmission_lines
        """
        ctx = setup_ready_test_event()

        validate_error(
            api_client.create_test_log_entry(
                {
                    "test_event_id": ctx["test_event_id"],
                    "device_id": ctx["device_id"],
                    "entry_kind": "RECEIPT",
                },
                ENGINEER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )
        validate_error(
            api_client.create_test_log_entry(
                {
                    "test_event_id": ctx["test_event_id"],
                    "device_id": ctx["device_id"],
                    "entry_kind": "TRANSMISSION",
                    "source_call_sign": "WXPEP",
                },
                ENGINEER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )
        validate_error(
            api_client.create_test_log_entry(
                {
                    "test_event_id": ctx["test_event_id"],
                    "device_id": ctx["device_id"],
                    "entry_kind": "BEACON",
                },
                ENGINEER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

        event = get_success_data(api_client.get_test_event(ctx["test_event_id"], ADMIN))
        assert event["logged_entry_count"] == 0, (
            "the three refused calls did not increment logged_entry_count"
        )

    def test_well_formed_receipt_line_is_stored_with_the_two_year_retention_term(self):
        """PRD §3.6: "An accepted line stamps `logged_at` from the logical clock and records the acting `X-User-ID` as `logged_by_user_id` — the value the segregation-of-duties check of §2.12 later compares against."
        PRD §3.6: "The base term is 1095 days — three years — when the owning event's `test_type` is `NATIONAL`, and 730 days — two years — for `WEEKLY` and `MONTHLY` alike."
        PRD §3.6: "The resulting figure is stored as `retention_days_applied`, and `retention_until` is `logged_at` advanced by that many whole calendar days in UTC."
        PRD §3.6: "It raises the event's `logged_entry_count` by one."

        Design: Corner/validations/conditional_schema_rules_on_receipt_and_transmission_lines
        """
        ctx = setup_ready_test_event()

        entry = validate_success(
            api_client.create_test_log_entry(
                {
                    "test_event_id": ctx["test_event_id"],
                    "device_id": ctx["device_id"],
                    "entry_kind": "RECEIPT",
                    "source_call_sign": "WXPEP",
                },
                ENGINEER,
            ),
            201,
        )
        assert_test_log_entry(entry)
        _assert_instant(entry["logged_at"], LOG_INSTANT, "logged_at")
        assert entry["retention_days_applied"] == 730, (
            f"a WEEKLY event retains for 730 days, got {entry['retention_days_applied']}"
        )
        _assert_instant(entry["retention_until"], "2028-08-11T00:30:00Z", "retention_until")

        event = get_success_data(api_client.get_test_event(ctx["test_event_id"], ADMIN))
        assert event["logged_entry_count"] == 1, (
            f"expected logged_entry_count 1, got {event['logged_entry_count']}"
        )
