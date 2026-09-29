"""Alarm ingestion, correlation and the structural cascade it drives.

An alarm is the only client-supplied fault signal, so a single POST has to be
worth several derivations: the source's health, every path that rides it, the
single-point-of-failure flag on the surviving siblings, and finally the incident
classification that reads those post-cascade values.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CLOCK_EPOCH,
    ApiErrorId,
    advance_clock,
    alarm_payload,
    assert_append_only_record,
    assert_circuit_posture,
    assert_incident_classification,
    assert_instant,
    assert_page,
    assert_path_posture,
    build_ewt_two_leg,
    build_pft_single_leg,
    clear_alarm,
    create_carrier,
    create_circuit,
    create_device,
    get_success_data,
    raise_alarm,
    read_circuit,
    read_incident,
    read_path,
    stamped,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAlarmCascade:
    """One critical alarm must walk circuit, path, sibling and incident in order."""

    def test_critical_alarm_walks_circuit_path_and_sibling_leg(self, api):
        """The failed leg goes down, the path loses redundancy, the survivor becomes the risk.

        PRD 3.3: "A circuit's `operational_state` is derived from the set of uncleared root alarms on it: the circuit is `DOWN` while any of them has `raw_severity` `CRITICAL`, `DEGRADED` while any of them has `raw_severity` `MAJOR` or `MINOR` and none is `CRITICAL`, and `UP` when none remains."
        PRD 3.2: "Otherwise the posture is `DEGRADED_NO_REDUNDANCY`, the dangerous case where the path is still carrying traffic on exactly the minimum it needs."
        PRD 3.2: "A circuit's `spof_flag` is true when, and only when, there exists at least one path whose `posture` is `DEGRADED_NO_REDUNDANCY` that has an `ACTIVE` hop pointing at that circuit inside a leg all of whose `ACTIVE` hop targets currently count as up."

        Design: Difficulty/transitive_cascade/alarm_to_circuit_to_path_posture_to_sibling_spof_to_severity
        """
        state = build_ewt_two_leg(api, "2026-08-11T04:00:00Z")

        before = read_path(api, state["path_id"])
        assert_path_posture(
            before, posture="PROTECTED", active_leg_count=2, healthy_leg_count=2
        )
        for label in ("circuit_a_id", "circuit_b_id"):
            assert read_circuit(api, state[label])["spof_flag"] is False, (
                f"{label} must not be a single point of failure while both legs are up"
            )

        alarm = raise_alarm(
            api, "2026-08-11T04:00:00Z", source_circuit_id=state["circuit_a_id"]
        )
        assert alarm["correlation_state"] == "ROOT", (
            f"the first alarm on the circuit is a root condition, got {alarm['correlation_state']}"
        )
        assert alarm["correlation_parent_alarm_id"] is None, (
            "a root condition has no correlation parent"
        )

        assert_circuit_posture(
            read_circuit(api, state["circuit_a_id"]),
            operational_state="DOWN",
            spof_flag=False,
        )
        assert_circuit_posture(
            read_circuit(api, state["circuit_b_id"]),
            operational_state="UP",
            spof_flag=True,
        )
        assert_path_posture(
            read_path(api, state["path_id"]),
            posture="DEGRADED_NO_REDUNDANCY",
            active_leg_count=2,
            healthy_leg_count=1,
        )

    def test_incident_score_reads_the_post_cascade_network(self, api):
        """Impact is scored after the posture hops, so the redundancy term is 4 and not 8.

        PRD 3.4: "The redundancy term looks at the smallest `healthy_leg_count` among the affected paths — treated as 99 when there are no affected paths at all — and contributes 8 when that smallest value is zero, 4 when it is exactly 1, and nothing otherwise."
        PRD 3.4: "`impact_score` is the tier term multiplied by ten, plus the breadth term, plus the redundancy term, plus the single-point-of-failure term, and it is an integer."
        PRD 3.4: "Classification also sets two deadlines from `detected_at`: `response_due_at` is `detected_at` plus 15 minutes for `SEV1`, 30 minutes for `SEV2`, 120 minutes for `SEV3` and 480 minutes for `SEV4`, while `escalation_due_at` is `detected_at` plus 30 minutes for `SEV1`, 60 minutes for `SEV2`, 240 minutes for `SEV3` and 960 minutes for `SEV4`."

        Design: Difficulty/transitive_cascade/alarm_to_circuit_to_path_posture_to_sibling_spof_to_severity
        """
        state = build_ewt_two_leg(api, "2026-08-11T04:00:00Z")

        alarm = raise_alarm(
            api, "2026-08-11T04:00:00Z", source_circuit_id=state["circuit_a_id"]
        )
        incident = read_incident(api, alarm["incident_id"])

        assert_incident_classification(
            incident,
            severity="SEV2",
            impact_score=46,
            response_state="DETECTED",
            escalation_state="NONE",
            alarm_count=1,
        )
        assert incident["affected_path_count"] == 1, (
            "exactly one path has an active hop on the failed circuit"
        )
        assert incident["primary_circuit_id"] == state["circuit_a_id"], (
            "the incident is anchored to the alarming circuit"
        )
        assert_instant(
            incident["detected_at"], stamped("2026-08-11", "04:00"), "detected_at"
        )
        assert_instant(
            incident["response_due_at"],
            stamped("2026-08-11", "04:30"),
            "response_due_at",
        )
        assert_instant(
            incident["escalation_due_at"],
            stamped("2026-08-11", "05:00"),
            "escalation_due_at",
        )

    def test_the_whole_cascade_is_readable_immediately(self, api):
        """The create response already carries its own incident and the reads are final.

        PRD 2.10: "When an operation changes a source's health, the affected application paths recompute their leg counts and `posture` first, then single-point-of-failure flags are re-derived from the resulting postures, and only then is incident classification evaluated — so the impact score reads post-cascade redundancy values, not the values that held before the alarm arrived."
        PRD 3.3: "Opening a new incident stamps the circuit's `last_incident_at`, and each circuit, path and incident touched by the cascade has its `version` advanced by 1."

        Design: Corner/consistency_model/corner_cascade_is_visible_in_the_same_response
        """
        state = build_pft_single_leg(api, "2026-09-02T00:00:00Z")

        created = validate_success(
            api.create_alarm(
                alarm_payload(
                    "2026-09-02T00:00:00Z", source_circuit_id=state["circuit_id"]
                ),
                ANALYST_HEADERS,
            ),
            201,
        )["data"]
        assert created["incident_id"] is not None, (
            "the alarm creation response already names the incident its cascade opened"
        )
        assert created["correlation_state"] == "ROOT", (
            f"the first alarm is a root condition, got {created['correlation_state']}"
        )

        circuit = read_circuit(api, state["circuit_id"])
        assert_circuit_posture(circuit, operational_state="DOWN")
        assert circuit["version"] == 2, (
            f"the cascade advanced the circuit version once, got {circuit['version']}"
        )
        assert_path_posture(
            read_path(api, state["path_id"]),
            posture="DOWN",
            active_leg_count=1,
            healthy_leg_count=0,
        )
        assert_incident_classification(
            read_incident(api, created["incident_id"]),
            severity="SEV3",
            impact_score=20,
            response_state="DETECTED",
            alarm_count=1,
        )


class TestAlarmCorrelation:
    """Repeat noise on one circuit collapses under the root that explains it."""

    def test_second_alarm_exactly_at_the_window_edge_is_suppressed(self, api):
        """A gap of exactly 900 seconds still files the noise under the open root.

        PRD 3.3: "In both cases a candidate qualifies only if its `correlation_state` is `ROOT`, its `cleared_at` is still null, its `raised_at` is at or before the new alarm's `raised_at`, and the gap between the two `raised_at` instants is no more than 900 seconds — fifteen minutes — with the boundary inclusive, so a gap of exactly fifteen minutes still suppresses."
        PRD 3.3: "Suppressed noise never opens an incident of its own; it increments the incident's `alarm_count` by 1 and can only ratchet severity upward, never re-classify it downward."

        Design: Corner/calculations/corner_duplicate_alarm_inside_window_is_suppressed_under_root
        """
        state = build_pft_single_leg(
            api, "2026-08-21T00:00:00Z", alarm_raised_at="2026-08-21T00:00:00Z"
        )
        root_id = state["alarm_id"]
        incident_id = state["incident_id"]

        advance_clock(api, "2026-08-21T00:15:00Z")
        noise = raise_alarm(
            api,
            "2026-08-21T00:15:00Z",
            alarm_type="ERRORED_SECONDS",
            raw_severity="MINOR",
            source_circuit_id=state["circuit_id"],
        )

        assert noise["correlation_state"] == "SUPPRESSED", (
            f"an alarm 900 seconds after the root is suppressed, got {noise['correlation_state']}"
        )
        assert noise["correlation_parent_alarm_id"] == root_id, (
            "the suppressed alarm records the root that explains it"
        )
        assert noise["incident_id"] == incident_id, (
            "suppressed noise inherits the parent's incident rather than opening its own"
        )

        _, meta = validate_paginated(
            api.list_incidents(
                ANALYST_HEADERS, params={"primary_circuit_id": state["circuit_id"]}
            )
        )
        assert_page(meta, total_count=1)

        assert_incident_classification(
            read_incident(api, incident_id),
            severity="SEV3",
            impact_score=20,
            alarm_count=2,
        )
        assert_circuit_posture(
            read_circuit(api, state["circuit_id"]), operational_state="DOWN"
        )


class TestAlarmIngestionRefusals:
    """Malformed and impossible alarms must be turned away before any cascade."""

    def test_unknown_raw_severity_is_refused_before_any_cascade(self, api):
        """`raw_severity` is a closed enum, so an invented member never lands.

        PRD 3.3: "Ingesting one supplies the `alarm_type` that fired — `LOSS_OF_SIGNAL`, `ERRORED_SECONDS`, `PATH_LATENCY` or `DEVICE_UNREACHABLE` — the `raw_severity` the monitoring platform assigned before any correlation (`CRITICAL`, `MAJOR`, `MINOR` or `WARNING`), the `raised_at` instant at which the condition was observed, and exactly one source: either `source_circuit_id` or `source_device_id`."
        PRD 2.7: "Violations are `ERR_INVALID_REQUEST` (400), and this check applies to every operation."

        Design: Corner/entities/corner_alarm_create_unknown_severity_enum_rejected
        """
        advance_clock(api, CLOCK_EPOCH)
        carrier = create_carrier(api)
        circuit = create_circuit(api, carrier["id"], monitoring_state="MONITORED")

        validate_error(
            api.create_alarm(
                alarm_payload(
                    CLOCK_EPOCH,
                    raw_severity="CATASTROPHIC",
                    source_circuit_id=circuit["id"],
                ),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

        assert_circuit_posture(
            read_circuit(api, circuit["id"]), operational_state="UP"
        )
        _, alarm_meta = validate_paginated(
            api.list_alarms(ANALYST_HEADERS, params={"source_circuit_id": circuit["id"]})
        )
        assert_page(alarm_meta, total_count=0)
        _, incident_meta = validate_paginated(api.list_incidents(ANALYST_HEADERS))
        assert_page(incident_meta, total_count=0)

    def test_alarm_raised_ahead_of_the_clock_is_refused(self, api):
        """A poller running fast cannot seed a future-dated fault history.

        PRD 2.4: "Instant and interval inputs must be internally coherent, and incoherence is reported as `ERR_TIMESTAMP_RANGE_INVALID` (HTTP 422)."
        PRD 2.4: "Concretely: a maintenance window's `window_end` must be strictly after its `window_start`; a failover test's `scheduled_end` must be strictly after its `scheduled_start`; a vendor review's `period_end` must be strictly after its `period_start`; an availability query's `to_iso8601` must be strictly after its `from_iso8601`; an alarm's `raised_at` must be at or before the current logical clock instant; a clearing `cleared_at` must fall at or after the alarm's `raised_at` and at or before the current clock instant; and a carrier-asserted `restored_at` must fall strictly after the ticket's `opened_at` and at or before the current clock instant."

        Design: Corner/validations/corner_alarm_raised_in_the_future_rejected
        """
        advance_clock(api, "2026-08-23T00:00:00Z")
        carrier = create_carrier(api)
        circuit = create_circuit(api, carrier["id"], monitoring_state="MONITORED")

        validate_error(
            api.create_alarm(
                alarm_payload(
                    "2026-08-23T00:05:00Z",
                    alarm_type="PATH_LATENCY",
                    raw_severity="MAJOR",
                    source_circuit_id=circuit["id"],
                ),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ERR_TIMESTAMP_RANGE_INVALID,
        )

        _, meta = validate_paginated(
            api.list_alarms(ANALYST_HEADERS, params={"source_circuit_id": circuit["id"]})
        )
        assert_page(meta, total_count=0)
        unchanged = read_circuit(api, circuit["id"])
        assert_circuit_posture(unchanged, operational_state="UP")
        assert unchanged["version"] == 1, (
            f"a refused alarm leaves the circuit at version 1, got {unchanged['version']}"
        )

    def test_alarm_must_name_exactly_one_source(self, api):
        """Both sources and neither source are equally invalid.

        PRD 3.3: "Supplying both or neither is `ERR_ALARM_SOURCE_INVALID`."

        Design: Corner/validations/corner_alarm_source_requires_exactly_one_target
        """
        advance_clock(api, "2026-08-24T00:00:00Z")
        carrier = create_carrier(api)
        circuit = create_circuit(api, carrier["id"], monitoring_state="MONITORED")
        device = create_device(
            api,
            device_role="EDGE",
            primary_uplink_circuit_id=circuit["id"],
            monitoring_state="MONITORED",
        )

        both = alarm_payload(
            "2026-08-24T00:00:00Z",
            alarm_type="DEVICE_UNREACHABLE",
            source_circuit_id=circuit["id"],
            source_device_id=device["id"],
        )
        neither = alarm_payload(
            "2026-08-24T00:00:00Z", alarm_type="DEVICE_UNREACHABLE"
        )
        assert "source_circuit_id" not in neither and "source_device_id" not in neither, (
            "the second attempt must genuinely omit both sources"
        )

        for payload in (both, neither):
            validate_error(
                api.create_alarm(payload, ANALYST_HEADERS),
                ApiErrorId.ERR_ALARM_SOURCE_INVALID,
            )

        _, meta = validate_paginated(api.list_alarms(ANALYST_HEADERS))
        assert_page(meta, total_count=0)
        assert_circuit_posture(read_circuit(api, circuit["id"]), operational_state="UP")
        stored_device = get_success_data(api.get_device(device["id"], ADMIN_HEADERS))
        assert stored_device["monitoring_state"] == "MONITORED", (
            "the refused alarms leave the device monitoring state alone"
        )

    def test_clearing_an_already_cleared_alarm_is_refused(self, api):
        """Clearing is deliberately not idempotent, so a replay cannot move `cleared_at`.

        PRD 3.3: "Clearing supplies `cleared_at`, which must fall at or after the alarm's `raised_at` and at or before the current clock instant; an alarm that already carries a `cleared_at` cannot be cleared again and yields `ERR_ALARM_ALREADY_CLEARED`."

        Design: Corner/state_machines/corner_alarm_clear_twice_rejected
        """
        state = build_pft_single_leg(
            api, "2026-08-17T00:00:00Z", alarm_raised_at="2026-08-17T00:00:00Z"
        )

        advance_clock(api, "2026-08-17T00:20:00Z")
        clear_alarm(api, state["alarm_id"], "2026-08-17T00:20:00Z")

        advance_clock(api, "2026-08-17T00:40:00Z")
        validate_error(
            api.clear_alarm(
                state["alarm_id"],
                {"cleared_at": "2026-08-17T00:40:00Z"},
                ANALYST_HEADERS,
            ),
            ApiErrorId.ERR_ALARM_ALREADY_CLEARED,
        )

        stored = get_success_data(api.get_alarm(state["alarm_id"], ANALYST_HEADERS))
        assert_instant(
            stored["cleared_at"], stamped("2026-08-17", "00:20"), "alarm.cleared_at"
        )
        assert stored["correlation_state"] == "CLEARED", (
            f"the alarm stays cleared, got {stored['correlation_state']}"
        )
        assert_circuit_posture(
            read_circuit(api, state["circuit_id"]), operational_state="UP"
        )
        assert_path_posture(read_path(api, state["path_id"]), posture="PROTECTED")


class TestAlarmRecordShape:
    """Alarms are append-only evidence, not editable rows."""

    def test_alarm_carries_no_version_and_only_the_clear_mutates_it(self, api):
        """Clearing stamps `cleared_at` and the state; nothing else about the row moves.

        PRD 2.5: "Three record types are deliberately append-only and therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent from them entirely."
        PRD 2.5: "An alarm's `correlation_state` and `cleared_at` are still updated by correlation and clearing, but the alarm record exposes no `version` and no `updated_at`; test results and capacity readings are never modified after insertion at all."

        Design: Corner/entities/corner_alarm_row_is_immutable_and_versionless
        """
        advance_clock(api, CLOCK_EPOCH)
        carrier = create_carrier(api)
        circuit = create_circuit(api, carrier["id"], monitoring_state="MONITORED")
        alarm = raise_alarm(api, CLOCK_EPOCH, source_circuit_id=circuit["id"])

        advance_clock(api, "2026-08-01T00:20:00Z")
        clear_alarm(api, alarm["id"], "2026-08-01T00:20:00Z")

        stored = get_success_data(api.get_alarm(alarm["id"], ANALYST_HEADERS))
        assert_append_only_record(stored, label="alarm")
        assert_instant(
            stored["cleared_at"], stamped("2026-08-01", "00:20"), "alarm.cleared_at"
        )
        assert stored["correlation_state"] == "CLEARED", (
            f"the cleared alarm reports CLEARED, got {stored['correlation_state']}"
        )
        assert_instant(
            stored["raised_at"], stamped("2026-08-01", "00:00"), "alarm.raised_at"
        )
        assert stored["alarm_type"] == "LOSS_OF_SIGNAL", (
            "clearing never rewrites the alarm type"
        )
        assert_circuit_posture(read_circuit(api, circuit["id"]), operational_state="UP")
