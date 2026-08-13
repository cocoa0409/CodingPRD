"""Distribution records, the daily scan checkpoint, and subcontractor standing (PRD §3.3, §3.5, §3.8)."""
from test_helpers import (
    ApiErrorId,
    add_spec_section,
    activate_spec_section,
    answer_rfi,
    assert_distribution_record,
    assert_escalation_event,
    create_active_project,
    create_answered_rfi,
    create_rfi,
    distribute_rfi,
    escalation_events,
    get_record,
    get_subcontractor,
    make_subcontractor_rep_headers,
    route_rfi,
    set_clock,
    setup_distributed_rfi,
    setup_sent_distributions,
    submit_revision,
    submittals_of_section,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["project_manager_headers"]
PE = TEST_USERS["project_engineer_headers"]


class TestDistributionRecordLifecycle:
    def test_distribution_record_initial_state_queued(self, api):
        """PRD §3.3: "A fresh record is `QUEUED` with `sent_date`, `ack_due_date`, and
        `acknowledged_date` all null and `is_overdue` false."
        PRD §3.5: "The affected set is the responsible subcontractor of the linked spec
        section, when one is linked, unioned with the `subcontractor_id` of every
        non-`CANCELLED` InstallationActivity referencing the RFI's linked submittal."

        Design: Corner/state_machines/distribution_record_initial_state_queued
        """
        world = setup_distributed_rfi()
        records = world["records"]
        assert len(records) == 1, "one affected subcontractor -> one record"
        record = records[0]
        assert_distribution_record(record)
        assert record["status"] == "QUEUED"
        assert record["sent_date"] is None
        assert record["ack_due_date"] is None
        assert record["source_type"] == "RFI"
        assert record["subcontractor_id"] == world["subcontractor"]["id"]

    def test_acknowledge_before_send_rejected(self, api):
        """PRD §3.3: "Acknowledgement belongs to the addressed subcontractor: a
        `SubcontractorRep` whose `X-User-ID` equals the record's `subcontractor_id`
        (otherwise `ERR_WRONG_SUBCONTRACTOR`), against a record that is `SENT` (otherwise
        `ERR_DISTRIBUTION_NOT_SENT`)."
        The correct subcontractor acknowledges a QUEUED record: only the state rule
        fails.

        Design: Corner/state_machines/acknowledge_before_send_rejected
        """
        world = setup_distributed_rfi()
        record = world["records"][0]
        resp = api.acknowledge_distribution_record(
            record["id"],
            make_subcontractor_rep_headers(world["subcontractor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISTRIBUTION_NOT_SENT, 409)

    def test_distribute_without_targets_and_repeat_distribute(self, api):
        """PRD §3.5: "Distributing against an empty set fails with
        `ERR_NO_DISTRIBUTION_TARGETS`, and distributing an RFI that already has
        distribution records fails with `ERR_ALREADY_DISTRIBUTED`."
        An unlinked answered RFI has an empty affected set; a linked one distributes
        once and refuses a second pass.

        Design: Corner/errors/distribute_without_targets_and_repeat_distribute
        """
        world = setup_distributed_rfi(clock_to=None)
        # world["rfi"] is the linked, already-distributed RFI.
        rfi_unlinked = create_answered_rfi(world["project"]["id"], world["reviewer"]["id"])

        resp = api.distribute_rfi(rfi_unlinked["id"], PE)
        validate_error(resp, ApiErrorId.ERR_NO_DISTRIBUTION_TARGETS, 409)

        resp = api.distribute_rfi(world["rfi"]["id"], PE)
        validate_error(resp, ApiErrorId.ERR_ALREADY_DISTRIBUTED, 409)


class TestDistributionOverdueCascade:
    def test_scan_latches_overdue_records_and_counts_late_acks(self, api):
        """PRD §3.3: "Sending, by a `ProjectEngineer`, requires `QUEUED` (otherwise
        `ERR_DISTRIBUTION_NOT_QUEUED`) and stamps `sent_date` with the clock date while
        computing `ack_due_date` as the project's `ack_required_days` business days
        later."
        PRD §3.8: "every DistributionRecord still `SENT` whose `ack_due_date` has passed
        is latched `is_overdue` exactly once, a `DIST_ACK_OVERDUE` event is appended, and
        the addressed subcontractor's `late_ack_count` increments by one."
        Three records sent Monday 2026-08-03 fall due 2026-08-10; the 2026-08-11 scan
        latches all three.

        Design: Difficulty/transitive_cascade/distribution_overdue_standing_cascade
        """
        world = setup_sent_distributions(3, clock_to="2026-08-03T09:00:00Z")
        records = world["records"]
        for record in records:
            assert record["ack_due_date"] == "2026-08-10", (
                "sent 2026-08-03 + 5 business days"
            )
            assert record["is_overdue"] is False

        set_clock("2026-08-11T09:00:00Z")
        validate_success(api.run_daily_scan(world["project"]["id"], PM), 200)

        for record in records:
            assert get_record(record["id"])["is_overdue"] is True
        assert get_subcontractor(world["subcontractor"]["id"])["late_ack_count"] == 3, (
            "one increment per newly-overdue record"
        )

    def test_late_ack_threshold_crossing_flips_standing_with_events(self, api):
        """PRD §3.8: "At three or more late acknowledgements the standing moves from
        `GOOD` to `WATCH` and a `SUBCONTRACTOR_WATCH` event is appended; at six or more
        it falls to `SUSPENDED` with a `SUBCONTRACTOR_SUSPENDED` event."
        PRD §3.8: "every DistributionRecord still `SENT` whose `ack_due_date` has passed
        is latched `is_overdue` exactly once, a `DIST_ACK_OVERDUE` event is appended"
        The third latch crosses the WATCH threshold: three DIST_ACK_OVERDUE events plus
        one SUBCONTRACTOR_WATCH event land in the append-only log.

        Design: Difficulty/transitive_cascade/distribution_overdue_standing_cascade
        """
        world = setup_sent_distributions(3, clock_to="2026-08-03T09:00:00Z")
        set_clock("2026-08-11T09:00:00Z")
        validate_success(api.run_daily_scan(world["project"]["id"], PM), 200)

        subcontractor = get_subcontractor(world["subcontractor"]["id"])
        assert subcontractor["late_ack_count"] == 3
        assert subcontractor["standing"] == "WATCH"

        overdue_events = escalation_events(event_type="DIST_ACK_OVERDUE")
        assert len(overdue_events) == 3
        for event in overdue_events:
            assert_escalation_event(event)
        watch_events = escalation_events(
            event_type="SUBCONTRACTOR_WATCH", source_id=world["subcontractor"]["id"]
        )
        assert len(watch_events) == 1
        assert_escalation_event(watch_events[0])


class TestDailyScanCheckpoint:
    def test_daily_scan_is_idempotent_checkpoint(self, api):
        """PRD §3.8: "every DistributionRecord still `SENT` whose `ack_due_date` has
        passed is latched `is_overdue` exactly once, a `DIST_ACK_OVERDUE` event is
        appended, and the addressed subcontractor's `late_ack_count` increments by one."
        PRD §2.11: "Each successful scan increments the project's `ops_scan_index`, a
        monotonic counter starting at zero, by exactly one and bumps the Project's
        `version`."
        A second scan at the same clock appends no new events and does not re-increment
        the counter, while the scan epoch still advances.

        Design: Corner/cross_cutting_layers/daily_scan_is_idempotent_checkpoint
        """
        world = setup_sent_distributions(1, clock_to="2026-08-03T09:00:00Z")
        record = world["records"][0]
        set_clock("2026-08-11T09:00:00Z")

        first = validate_success(api.run_daily_scan(world["project"]["id"], PM), 200)
        assert get_subcontractor(world["subcontractor"]["id"])["late_ack_count"] == 1

        second = validate_success(api.run_daily_scan(world["project"]["id"], PM), 200)
        assert second["ops_scan_index"] == first["ops_scan_index"] + 1
        assert get_subcontractor(world["subcontractor"]["id"])["late_ack_count"] == 1, (
            "the overdue latch fires exactly once; re-scan does not double-count"
        )
        assert len(escalation_events(event_type="DIST_ACK_OVERDUE", source_id=record["id"])) == 1


class TestSuspendedSubcontractor:
    def test_suspended_subcontractor_blocked_from_revision_submit(self, api):
        """PRD §3.8: "At three or more late acknowledgements the standing moves from
        `GOOD` to `WATCH` and a `SUBCONTRACTOR_WATCH` event is appended; at six or more
        it falls to `SUSPENDED` with a `SUBCONTRACTOR_SUSPENDED` event."
        PRD §3.2: "a subcontractor whose `standing` has fallen to `SUSPENDED` is blocked
        from submitting new revisions at all with `ERR_SUBCONTRACTOR_SUSPENDED`"
        Six overdue acknowledgements drive the responsible sub to SUSPENDED; its next
        revision submit is refused.

        Design: Corner/errors/suspended_subcontractor_blocked_from_revision_submit
        """
        world = setup_sent_distributions(6, clock_to="2026-08-03T09:00:00Z")
        project = world["project"]
        subcontractor = world["subcontractor"]

        # A second, activated section gives a REGISTERED submittal owned by the sub.
        section2 = add_spec_section(
            project["id"],
            "230500",
            lead_time_days=5,
            default_need_date="2026-10-30",
            responsible_subcontractor_id=subcontractor["id"],
        )
        activate_spec_section(section2["id"])
        submittal = submittals_of_section(project["id"], "230500")[0]

        set_clock("2026-08-11T09:00:00Z")
        validate_success(api.run_daily_scan(project["id"], PM), 200)
        subcontractor = get_subcontractor(subcontractor["id"])
        assert subcontractor["late_ack_count"] == 6
        assert subcontractor["standing"] == "SUSPENDED", (
            "crossed WATCH at three and SUSPENDED at six"
        )

        resp = api.create_revision(
            submittal["id"],
            {
                "document_ref": "doc://blocked",
                "expected_submittal_version": submittal["version"],
            },
            make_subcontractor_rep_headers(subcontractor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SUBCONTRACTOR_SUSPENDED, 409)
