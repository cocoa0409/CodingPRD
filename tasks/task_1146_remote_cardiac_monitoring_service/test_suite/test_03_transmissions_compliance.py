"""Transmission ingest, connectivity gap detection, and the compliance
strike/suspension machinery (PRD §3.4, §3.6, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_transmission_payload,
    make_technician_headers,
    read_episode,
    read_patient,
    record_gap_strikes,
    register_technician,
    run_sweep,
    set_clock,
    setup_monitoring_episode,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["enrollment_coordinator_headers"]
GATEWAY = TEST_USERS["device_gateway_headers"]


class TestTransmissionIngest:
    def test_failed_transmission_reprocess_cycle(self, api):
        """PRD §3.4: "The server stamps `received_at` from the logical clock
        and assigns the transmission's `status` by quality: a reading of at
        least 30 yields `PROCESSED` and increments the episode's
        `transmission_count`; a reading below 30 yields `FAILED` and leaves the
        count untouched."
        PRD §3.4: "When the updated reading is at least 30, the transmission
        moves from `FAILED` to `PROCESSED` and the episode's
        `transmission_count` increments; a reading that remains below 30 leaves
        the transmission in `FAILED`."

        Design: Corner/state_machines/transmission_failed_reprocess_cycle
        """
        ctx = setup_monitoring_episode(prescribed_days=7)
        tech = register_technician()
        episode_id = ctx["episode_id"]

        failed = validate_success(
            api.ingest_transmission(
                episode_id,
                create_transmission_payload(seq_no=1, bytes_received=2048, signal_quality=20),
                GATEWAY,
            ),
            201,
        )
        assert failed["status"] == "FAILED"
        assert read_episode(episode_id)["transmission_count"] == 0

        reprocessed = validate_success(
            api.reprocess_transmission(
                failed["id"], {"signal_quality": 50}, make_technician_headers(tech["id"])
            )
        )
        assert reprocessed["status"] == "PROCESSED"
        assert read_episode(episode_id)["transmission_count"] == 1

    def test_duplicate_transmission_seq_conflict(self, api):
        """PRD §3.4: "Each ingest names the target episode and carries `seq_no`
        (the device's sequence number, unique within the episode — a reuse is
        rejected with `ERR_DUPLICATE_TRANSMISSION_SEQ`, HTTP 409),
        `bytes_received` (the payload size, a positive integer), and
        `signal_quality` on a 0-to-100 scale."

        Design: Corner/validations/duplicate_transmission_seq_conflict
        """
        ctx = setup_monitoring_episode(prescribed_days=7)
        episode_id = ctx["episode_id"]
        validate_success(
            api.ingest_transmission(
                episode_id, create_transmission_payload(seq_no=7), GATEWAY
            ),
            201,
        )
        resp = api.ingest_transmission(
            episode_id, create_transmission_payload(seq_no=7), GATEWAY
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TRANSMISSION_SEQ)
        assert read_episode(episode_id)["transmission_count"] == 1


class TestGapDetectionBoundary:
    def test_gap_threshold_boundary_48h(self, api):
        """PRD §3.4: "The boundary is inclusive: exactly 48 hours of silence
        triggers the event; 47 hours and 59 minutes does not."
        PRD §3.4: "When the elapsed time from that base to the current clock
        reaches 48 hours, and no `TRANSMISSION_GAP` event is currently `OPEN`
        for the episode, the sweep creates a new `TRANSMISSION_GAP` compliance
        event, which enters the strike cascade of §3.6."

        Design: Corner/calculations/gap_threshold_boundary_48h
        """
        ctx = setup_monitoring_episode(prescribed_days=10)
        episode_id = ctx["episode_id"]

        set_clock("2026-05-02T23:00:00Z")
        run_sweep()
        events, meta = validate_paginated(
            api.list_compliance_events(COORD, params={"episode_id": episode_id})
        )
        assert meta["total_count"] == 0, f"47h silence must not fire, got {meta['total_count']}"
        assert read_episode(episode_id)["strike_count"] == 0

        set_clock("2026-05-03T00:00:00Z")
        run_sweep()
        events, meta = validate_paginated(
            api.list_compliance_events(COORD, params={"episode_id": episode_id})
        )
        assert meta["total_count"] == 1
        assert events[0]["event_type"] == "TRANSMISSION_GAP"
        assert events[0]["status"] == "OPEN"
        episode = read_episode(episode_id)
        assert episode["strike_count"] == 1
        assert episode["compliance_status"] == "WATCH"

    def test_strike_watch_band_boundary(self, api):
        """PRD §3.6: "While the episode's `clinical_status` is `MONITORING`,
        the new strike count is immediately mapped onto the compliance
        dimension: zero strikes is `COMPLIANT`, one or two strikes is `WATCH`,
        and three or more is `SUSPENDED` — exactly three already suspends, from
        `WATCH` or directly from `COMPLIANT` when the count jumps."

        Design: Corner/calculations/strike_watch_band_boundary
        """
        ctx = setup_monitoring_episode(prescribed_days=10)
        record_gap_strikes(ctx["episode_id"], 1, resolve_last=False)
        episode = read_episode(ctx["episode_id"])
        assert episode["strike_count"] == 1
        assert episode["compliance_status"] == "WATCH", (
            "a single strike lands in the 1..2 WATCH band, not SUSPENDED"
        )


class TestDerivedComplianceCounters:
    def test_patient_open_compliance_events_counter(self, api):
        """PRD §3.1: "A new patient's `open_compliance_events` starts at 0 and
        thereafter tracks the count of that patient's unresolved compliance
        events across all episodes, so a patient read always reflects the
        current follow-up burden."
        PRD §3.6: "A coordinator resolves an `OPEN` event by recording a
        `resolution_action` of `CONTACTED_PATIENT`, `DEVICE_REPLACED`, or
        `PHYSICIAN_NOTIFIED`, which moves the event to its terminal `RESOLVED`
        status and decrements the patient's `open_compliance_events`."

        Design: Corner/entities/derived_open_compliance_events_counter
        """
        ctx = setup_monitoring_episode(prescribed_days=10)
        event_ids = record_gap_strikes(ctx["episode_id"], 1, resolve_last=False)
        patient = read_patient(ctx["patient"]["id"])
        assert patient["open_compliance_events"] == 1

        validate_success(
            api.resolve_compliance_event(
                event_ids[0], {"resolution_action": "CONTACTED_PATIENT"}, COORD
            )
        )
        patient = read_patient(ctx["patient"]["id"])
        assert patient["open_compliance_events"] == 0

    def test_episode_read_derived_counters(self, api):
        """PRD §3.7: "Episode reads expose the full picture: `enrollment_id`,
        `patient_id`, `monitor_type`, `started_at`, `scheduled_end_at`,
        `completed_at`, both status dimensions, `strike_count`, and the derived
        counters; the episode list can be filtered by `enrollment_id`,
        `patient_id`, `clinical_status`, and `compliance_status`."
        PRD §3.5: "Raising a `CRITICAL` alert also increments the episode's
        `unacknowledged_critical_count` — the figure that later gates report
        finalization."

        Design: Corner/endpoints/computed_read_episode_counters
        """
        from test_helpers import raise_alert

        ctx = setup_monitoring_episode(prescribed_days=7)
        episode_id = ctx["episode_id"]
        validate_success(
            api.ingest_transmission(
                episode_id, create_transmission_payload(seq_no=1, signal_quality=80), GATEWAY
            ),
            201,
        )
        validate_success(
            api.ingest_transmission(
                episode_id, create_transmission_payload(seq_no=2, signal_quality=75), GATEWAY
            ),
            201,
        )
        raise_alert(episode_id, severity="CRITICAL", arrhythmia_type="VTACH")
        episode = read_episode(episode_id)
        assert episode["transmission_count"] == 2
        assert episode["unacknowledged_critical_count"] == 1


class TestResumePreconditions:
    def test_resume_requires_suspended_rejected(self, api):
        """PRD §3.6: "A successful resume moves the compliance dimension from
        `SUSPENDED` to `COMPLIANT`, closes the open suspension interval by
        stamping its `ended_at`, and resets `strike_count` to 0."
        PRD §3.6: "`WATCH` never auto-decays: it persists until the episode
        either suspends or reaches a clinical terminal state, and the only way
        back to `COMPLIANT` is the resume below."
        PRD §2.8: "5. **State-machine preconditions** — from-state and guard
        checks: generic failures yield `ERR_INVALID_STATE` (409); a device
        already committed elsewhere yields `ERR_DEVICE_NOT_IN_STOCK` (409);
        activation before education yields `ERR_EDUCATION_INCOMPLETE` (422); a
        stale order version yields `ERR_STALE_VERSION` (412)."

        Design: Corner/state_machines/resume_requires_suspended_rejected
        """
        ctx = setup_monitoring_episode(prescribed_days=10)
        record_gap_strikes(ctx["episode_id"], 1, resolve_last=True)
        episode = read_episode(ctx["episode_id"])
        assert episode["compliance_status"] == "WATCH"
        resp = api.resume_episode(ctx["episode_id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestParallelStateDimensions:
    def test_suspension_while_clinical_monitoring(self, api):
        """PRD §3.6: "While the episode's `clinical_status` is `MONITORING`,
        the new strike count is immediately mapped onto the compliance
        dimension: zero strikes is `COMPLIANT`, one or two strikes is `WATCH`,
        and three or more is `SUSPENDED` — exactly three already suspends, from
        `WATCH` or directly from `COMPLIANT` when the count jumps."
        PRD §3.6: "Entering `SUSPENDED` opens a `SuspensionInterval` on the
        episode with `started_at` stamped from the clock and `ended_at` null."

        Design: Difficulty/non_linear_state_machine/episode_parallel_dimensions_independent
        """
        ctx = setup_monitoring_episode(prescribed_days=30)
        record_gap_strikes(ctx["episode_id"], 3, resolve_last=True)
        episode = read_episode(ctx["episode_id"])
        assert episode["compliance_status"] == "SUSPENDED"
        assert episode["clinical_status"] == "MONITORING", (
            "compliance suspension must not disturb the clinical dimension"
        )

    def test_clinical_completion_leaves_compliance_untouched(self, api):
        """PRD §3.6: "Once the episode's clinical status has gone terminal,
        further strikes may still be recorded, but the mapping no longer
        applies."
        PRD §3.7: "Completion shares the resume precondition — zero `OPEN`
        compliance events, else `ERR_OPEN_COMPLIANCE_EVENTS` (HTTP 422) — and
        on success stamps `completed_at` from the clock, moves
        `clinical_status` to the named terminal state, and bubbles the parent
        order from `IN_SERVICE` to `FULFILLED`."

        Design: Difficulty/non_linear_state_machine/episode_parallel_dimensions_independent
        """
        ctx = setup_monitoring_episode(prescribed_days=30)
        record_gap_strikes(ctx["episode_id"], 3, resolve_last=True)
        completed = validate_success(
            api.complete_episode(ctx["episode_id"], {"reason": "COMPLETED"}, COORD)
        )
        assert completed["clinical_status"] == "COMPLETED"
        episode = read_episode(ctx["episode_id"])
        assert episode["compliance_status"] == "SUSPENDED", (
            "clinical completion must not reset the compliance dimension"
        )


class TestGapStrikeSuspensionCascade:
    def _setup_two_strikes(self):
        ctx = setup_monitoring_episode(prescribed_days=30)
        record_gap_strikes(ctx["episode_id"], 2, resolve_last=True)
        return ctx

    def test_third_strike_suspends_and_opens_interval(self, api):
        """PRD §3.6: "While the episode's `clinical_status` is `MONITORING`,
        the new strike count is immediately mapped onto the compliance
        dimension: zero strikes is `COMPLIANT`, one or two strikes is `WATCH`,
        and three or more is `SUSPENDED` — exactly three already suspends, from
        `WATCH` or directly from `COMPLIANT` when the count jumps."
        PRD §3.6: "Entering `SUSPENDED` opens a `SuspensionInterval` on the
        episode with `started_at` stamped from the clock and `ended_at` null."

        Design: Difficulty/transitive_cascade/gap_strike_suspension_cascade
        """
        ctx = self._setup_two_strikes()
        episode_id = ctx["episode_id"]
        assert read_episode(episode_id)["strike_count"] == 2

        set_clock("2026-05-07T00:00:00Z")
        run_sweep()

        gap_events, _ = validate_paginated(
            api.list_compliance_events(
                COORD, params={"episode_id": episode_id, "event_type": "TRANSMISSION_GAP"}
            )
        )
        new_open = [e for e in gap_events if e["status"] == "OPEN"]
        assert len(new_open) == 1, "sweep must create exactly one new OPEN gap event"
        assert new_open[0]["created_at"].startswith("2026-05-07T00:00:00")

        episode = read_episode(episode_id)
        assert episode["strike_count"] == 3
        assert episode["compliance_status"] == "SUSPENDED"

        intervals, meta = validate_paginated(api.list_suspension_intervals(episode_id, COORD))
        assert meta["total_count"] == 1
        assert intervals[0]["started_at"].startswith("2026-05-07T00:00:00")
        assert intervals[0]["ended_at"] is None

    def test_third_strike_reconciles_patient_counter(self, api):
        """PRD §3.6: "Creating an event increments the episode's `strike_count`
        and the patient's `open_compliance_events`."
        PRD §3.1: "A new patient's `open_compliance_events` starts at 0 and
        thereafter tracks the count of that patient's unresolved compliance
        events across all episodes, so a patient read always reflects the
        current follow-up burden."

        Design: Difficulty/transitive_cascade/gap_strike_suspension_cascade
        """
        ctx = self._setup_two_strikes()
        episode_id = ctx["episode_id"]

        set_clock("2026-05-07T00:00:00Z")
        run_sweep()

        episode = read_episode(episode_id)
        assert episode["strike_count"] == 3
        assert episode["compliance_status"] == "SUSPENDED"
        patient = read_patient(ctx["patient"]["id"])
        assert patient["open_compliance_events"] == 1, (
            "the two earlier events were resolved; only the third remains OPEN"
        )


class TestEpisodeCompletionGate:
    def test_complete_blocked_by_open_compliance_event(self, api):
        """PRD §3.7: "Completion shares the resume precondition — zero `OPEN`
        compliance events, else `ERR_OPEN_COMPLIANCE_EVENTS` (HTTP 422) — and
        on success stamps `completed_at` from the clock, moves
        `clinical_status` to the named terminal state, and bubbles the parent
        order from `IN_SERVICE` to `FULFILLED`."

        Design: Difficulty/cross_entity_state_dependency/episode_complete_requires_no_open_compliance_events
        """
        ctx = setup_monitoring_episode(prescribed_days=10)
        record_gap_strikes(ctx["episode_id"], 1, resolve_last=False)
        resp = api.complete_episode(ctx["episode_id"], {"reason": "COMPLETED"}, COORD)
        validate_error(resp, ApiErrorId.ERR_OPEN_COMPLIANCE_EVENTS)

    def test_complete_succeeds_after_resolving_open_event(self, api):
        """PRD §3.7: "Completion shares the resume precondition — zero `OPEN`
        compliance events, else `ERR_OPEN_COMPLIANCE_EVENTS` (HTTP 422) — and
        on success stamps `completed_at` from the clock, moves
        `clinical_status` to the named terminal state, and bubbles the parent
        order from `IN_SERVICE` to `FULFILLED`."
        PRD §3.6: "A coordinator resolves an `OPEN` event by recording a
        `resolution_action` of `CONTACTED_PATIENT`, `DEVICE_REPLACED`, or
        `PHYSICIAN_NOTIFIED`, which moves the event to its terminal `RESOLVED`
        status and decrements the patient's `open_compliance_events`."

        Design: Difficulty/cross_entity_state_dependency/episode_complete_requires_no_open_compliance_events
        """
        ctx = setup_monitoring_episode(prescribed_days=10)
        event_ids = record_gap_strikes(ctx["episode_id"], 1, resolve_last=False)
        resp = api.complete_episode(ctx["episode_id"], {"reason": "COMPLETED"}, COORD)
        validate_error(resp, ApiErrorId.ERR_OPEN_COMPLIANCE_EVENTS)

        validate_success(
            api.resolve_compliance_event(
                event_ids[0], {"resolution_action": "CONTACTED_PATIENT"}, COORD
            )
        )
        completed = validate_success(
            api.complete_episode(ctx["episode_id"], {"reason": "COMPLETED"}, COORD)
        )
        assert completed["clinical_status"] == "COMPLETED"
