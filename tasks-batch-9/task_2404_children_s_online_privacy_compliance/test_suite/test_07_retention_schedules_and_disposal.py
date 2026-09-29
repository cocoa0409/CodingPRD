"""Retention schedules, the inclusive disposal boundary and two-run secure disposal."""

from test_helpers import (
    ENGINEER_HEADERS,
    OFFICER_HEADERS,
    api_client,
    assert_compliance_run_summary,
    assert_instant,
    collect_record,
    create_activity,
    create_age_screen,
    create_consent,
    create_retention_schedule,
    create_service,
    deliver_notice_to_consent,
    grant_consent,
    mixed_audience_service,
    open_verification,
    published_notice,
    read_consent,
    read_record,
    read_service,
    retention_schedule_payload,
    run_compliance,
    set_clock,
    set_screen_status,
    validate_error,
    validate_paginated,
)


class TestOverlapCheckPrecedesDisposalMethodCheck:
    """A range conflict is reported before the method admissibility is considered."""

    def test_01_an_adjacent_range_with_an_inadmissible_method_reports_the_overlap(self):
        """The range conflict wins over the inadmissible disposal method.

        The precedence list places "16. **Retention-schedule range rules**, else
        `ERR_RETENTION_SCHEDULE_OVERLAP` (409)" ahead of "21. **Notice completeness and
        disposal-method admissibility**, else ... `ERR_DISPOSAL_METHOD_NOT_PERMITTED`", and
        "A later check never masks an earlier one."

        Design: Difficulty/priority_pair_validation_conflict/retention_overlap_p102_beats_disposal_method_p112
        """
        service = create_service(name="Overlap Beats Method Service")
        create_retention_schedule(
            service["id"],
            data_element_code="GEOLOCATION_PRECISE",
            purpose_code="PARTICIPATION_CORE",
            disposal_method="CRYPTO_ERASE",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-06-30T00:00:00Z",
        )

        validate_error(
            api_client.create_retention_schedule(
                retention_schedule_payload(
                    service["id"],
                    data_element_code="GEOLOCATION_PRECISE",
                    purpose_code="PARTICIPATION_CORE",
                    disposal_method="ANONYMIZE",
                    effective_from="2026-06-30T00:00:00Z",
                    effective_to="2026-12-31T00:00:00Z",
                ),
                OFFICER_HEADERS,
            ),
            "ERR_RETENTION_SCHEDULE_OVERLAP",
        )

    def test_02_a_clear_range_exposes_the_inadmissible_disposal_method(self):
        """With a day of handover the method check is finally reached.

        "Precise geolocation permits only `CRYPTO_ERASE` or `OVERWRITE` ... A method outside
        its element's permitted list is refused with `ERR_DISPOSAL_METHOD_NOT_PERMITTED`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/retention_overlap_p102_beats_disposal_method_p112
        """
        service = create_service(name="Method Not Permitted Service")
        create_retention_schedule(
            service["id"],
            data_element_code="GEOLOCATION_PRECISE",
            purpose_code="PARTICIPATION_CORE",
            disposal_method="CRYPTO_ERASE",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-06-30T00:00:00Z",
        )

        validate_error(
            api_client.create_retention_schedule(
                retention_schedule_payload(
                    service["id"],
                    data_element_code="GEOLOCATION_PRECISE",
                    purpose_code="PARTICIPATION_CORE",
                    disposal_method="ANONYMIZE",
                    effective_from="2026-07-01T00:00:00Z",
                    effective_to="2026-12-31T00:00:00Z",
                ),
                OFFICER_HEADERS,
            ),
            "ERR_DISPOSAL_METHOD_NOT_PERMITTED",
        )

    def test_03_a_clear_range_with_an_admissible_method_is_accepted(self):
        """Both checks satisfied, the schedule is stored and the first one is untouched.

        "Precise geolocation permits only `CRYPTO_ERASE` or `OVERWRITE`, as do a full name, an
        email address and a phone number." A refused schedule changes nothing about the
        schedule it conflicted with.

        Design: Difficulty/priority_pair_validation_conflict/retention_overlap_p102_beats_disposal_method_p112
        """
        service = create_service(name="Accepted Successor Service")
        first = create_retention_schedule(
            service["id"],
            data_element_code="GEOLOCATION_PRECISE",
            purpose_code="PARTICIPATION_CORE",
            disposal_method="CRYPTO_ERASE",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-06-30T00:00:00Z",
        )
        validate_error(
            api_client.create_retention_schedule(
                retention_schedule_payload(
                    service["id"],
                    data_element_code="GEOLOCATION_PRECISE",
                    purpose_code="PARTICIPATION_CORE",
                    disposal_method="ANONYMIZE",
                    effective_from="2026-07-01T00:00:00Z",
                    effective_to="2026-12-31T00:00:00Z",
                ),
                OFFICER_HEADERS,
            ),
            "ERR_DISPOSAL_METHOD_NOT_PERMITTED",
        )

        second = create_retention_schedule(
            service["id"],
            data_element_code="GEOLOCATION_PRECISE",
            purpose_code="PARTICIPATION_CORE",
            disposal_method="OVERWRITE",
            effective_from="2026-07-01T00:00:00Z",
            effective_to="2026-12-31T00:00:00Z",
        )

        assert second["disposal_method"] == "OVERWRITE"
        rows, meta = validate_paginated(
            api_client.list_service_retention_schedules(
                service["id"],
                OFFICER_HEADERS,
                {"data_element_code": "GEOLOCATION_PRECISE", "purpose_code": "PARTICIPATION_CORE"},
            )
        )
        assert meta["total_count"] == 2, (
            f"only the two accepted schedules are stored, got {meta['total_count']}"
        )
        stored_first = [row for row in rows if row["id"] == first["id"]][0]
        assert_instant(
            stored_first["effective_to"], "2026-06-30T00:00:00Z", "effective_to"
        )


class TestRetentionRangeHandoverBuffer:
    """Closed ranges need a clear day between them, and only within the same triple."""

    def test_04_same_day_adjacency_is_a_conflict_but_one_clear_day_is_not(self):
        """A successor may not begin on the day its predecessor ends.

        "A new schedule is accepted only when, against every existing schedule for that
        same triple, either its `effective_from` is at least one day after that schedule's
        `effective_to`, or its `effective_to` plus one day is at or before that schedule's
        `effective_from`."

        Design: Difficulty/resource_temporal_overlap/retention_schedule_closed_range_one_day_handover_buffer
        """
        service = create_service(name="Handover Buffer Service")
        create_retention_schedule(
            service["id"],
            data_element_code="SCREEN_NAME",
            purpose_code="PARTICIPATION_CORE",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-06-30T00:00:00Z",
        )

        validate_error(
            api_client.create_retention_schedule(
                retention_schedule_payload(
                    service["id"],
                    data_element_code="SCREEN_NAME",
                    purpose_code="PARTICIPATION_CORE",
                    effective_from="2026-06-30T00:00:00Z",
                    effective_to="2026-12-31T00:00:00Z",
                ),
                OFFICER_HEADERS,
            ),
            "ERR_RETENTION_SCHEDULE_OVERLAP",
        )

        successor = create_retention_schedule(
            service["id"],
            data_element_code="SCREEN_NAME",
            purpose_code="PARTICIPATION_CORE",
            effective_from="2026-07-01T00:00:00Z",
            effective_to="2026-12-31T00:00:00Z",
        )
        assert_instant(successor["effective_from"], "2026-07-01T00:00:00Z", "effective_from")

    def test_05_a_different_purpose_may_reuse_the_very_same_range(self):
        """The conflict is scoped to one element-and-purpose pair.

        "Schedules for different elements, different purposes or different services never
        conflict."

        Design: Difficulty/resource_temporal_overlap/retention_schedule_closed_range_one_day_handover_buffer
        """
        service = create_service(name="Purpose Partition Service")
        create_retention_schedule(
            service["id"],
            data_element_code="SCREEN_NAME",
            purpose_code="PARTICIPATION_CORE",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-06-30T00:00:00Z",
        )

        twin = create_retention_schedule(
            service["id"],
            data_element_code="SCREEN_NAME",
            purpose_code="INTERNAL_OPERATIONS",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-06-30T00:00:00Z",
        )

        assert twin["purpose_code"] == "INTERNAL_OPERATIONS"
        _, meta = validate_paginated(
            api_client.list_service_retention_schedules(
                service["id"], OFFICER_HEADERS, {"data_element_code": "SCREEN_NAME"}
            )
        )
        assert meta["total_count"] == 2, (
            f"both schedules for the element are stored, got {meta['total_count']}"
        )

    def test_06_a_predecessor_ending_on_the_start_day_is_also_a_conflict(self):
        """The buffer rule is symmetric on the left as well as the right.

        "including the same-day adjacency case where one range ends on the very day the next
        begins", so a predecessor whose `effective_to` plus one day is not at or before the
        existing `effective_from` is refused, while one ending a day earlier is accepted.

        Design: Difficulty/resource_temporal_overlap/retention_schedule_closed_range_one_day_handover_buffer
        """
        service = create_service(name="Left Mirror Service")
        create_retention_schedule(
            service["id"],
            data_element_code="SCREEN_NAME",
            purpose_code="PARTICIPATION_CORE",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-06-30T00:00:00Z",
        )

        validate_error(
            api_client.create_retention_schedule(
                retention_schedule_payload(
                    service["id"],
                    data_element_code="SCREEN_NAME",
                    purpose_code="PARTICIPATION_CORE",
                    effective_from="2025-12-01T00:00:00Z",
                    effective_to="2026-01-01T00:00:00Z",
                ),
                OFFICER_HEADERS,
            ),
            "ERR_RETENTION_SCHEDULE_OVERLAP",
        )

        predecessor = create_retention_schedule(
            service["id"],
            data_element_code="SCREEN_NAME",
            purpose_code="PARTICIPATION_CORE",
            effective_from="2025-12-01T00:00:00Z",
            effective_to="2025-12-31T00:00:00Z",
        )
        assert_instant(predecessor["effective_to"], "2025-12-31T00:00:00Z", "effective_to")

    def test_07_a_retention_period_below_one_day_is_an_invalid_period(self):
        """Zero retention days is refused even in a range that conflicts with nothing.

        "It declares `retention_days`, the number of days from collection until disposal is
        due, which must be at least 1", and "A `retention_days` below 1 ... is refused with
        `ERR_INVALID_PERIOD` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/retention_schedule_closed_range_one_day_handover_buffer
        """
        service = create_service(name="Zero Retention Days Service")
        create_retention_schedule(
            service["id"],
            data_element_code="SCREEN_NAME",
            purpose_code="PARTICIPATION_CORE",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-06-30T00:00:00Z",
        )

        validate_error(
            api_client.create_retention_schedule(
                retention_schedule_payload(
                    service["id"],
                    data_element_code="SCREEN_NAME",
                    purpose_code="PARTICIPATION_CORE",
                    retention_days=0,
                    effective_from="2027-01-01T00:00:00Z",
                    effective_to="2027-06-30T00:00:00Z",
                ),
                OFFICER_HEADERS,
            ),
            "ERR_INVALID_PERIOD",
        )

        _, meta = validate_paginated(
            api_client.list_service_retention_schedules(
                service["id"], OFFICER_HEADERS, {"purpose_code": "PARTICIPATION_CORE"}
            )
        )
        assert meta["total_count"] == 1, (
            f"the refused schedule was not stored, got {meta['total_count']}"
        )


def _service_with_one_due_record() -> dict:
    """A service holding one `SCREEN_NAME` record due for disposal on 2026-08-31."""
    service = mixed_audience_service(name="Disposal Boundary Service")
    service_id = service["id"]
    screen = create_age_screen(service_id)
    set_screen_status(screen["id"], "IN_REVIEW", ENGINEER_HEADERS)
    set_screen_status(screen["id"], "ACTIVE", OFFICER_HEADERS)
    activity = create_activity(service_id, participation_required_elements=["SCREEN_NAME"])
    create_retention_schedule(
        service_id,
        data_element_code="SCREEN_NAME",
        purpose_code="PARTICIPATION_CORE",
        retention_days=30,
        disposal_method="ANONYMIZE",
    )
    notice = published_notice(service_id)
    consent = create_consent(
        service_id, notice["id"], parent_email="parent@example.com", child_pseudonym="child-1"
    )
    deliver_notice_to_consent(consent["id"])
    open_verification(consent["id"])
    grant_consent(consent["id"])
    record = collect_record(service_id, consent["id"], activity["id"])
    return {"service_id": service_id, "consent_id": consent["id"], "record_id": record["id"]}


class TestInclusiveDisposalBoundaryAndTwoRunDisposal:
    """A record becomes due to the millisecond, and destruction always takes two runs."""

    def test_08_a_run_one_millisecond_early_schedules_nothing(self):
        """Just before the due instant, nothing is due.

        "A record is due for disposal when the current logical-clock instant has reached or
        passed `disposal_due_at`", and phase two acts only on records whose
        "`disposal_due_at` has been reached or passed".

        Design: Difficulty/boundary_precision_check/disposal_due_inclusive_boundary_and_two_run_secure_disposal
        """
        fixture = _service_with_one_due_record()
        set_clock("2026-08-30T23:59:59.999Z")

        summary = run_compliance(fixture["service_id"])

        assert_compliance_run_summary(summary)
        assert summary["run_sequence"] == 1
        assert summary["expired_consent_count"] == 0
        assert summary["scheduled_count"] == 0, (
            f"the record is not yet due, got scheduled_count {summary['scheduled_count']}"
        )
        assert summary["disposed_count"] == 0
        assert summary["live_child_data_element_count_after"] == 1
        record = read_record(fixture["record_id"])
        assert record["status"] == "COLLECTED"
        assert record["scheduled_run_sequence"] is None

    def test_09_a_run_at_the_due_instant_schedules_but_does_not_destroy(self):
        """At exactly the due instant the record is scheduled and survives the run.

        "the boundary is inclusive, so a record whose `disposal_due_at` equals the current
        instant to the millisecond is due", yet "A record that phase two scheduled moments
        ago in this very run therefore survives it". "Scheduling does not change
        `live_child_data_element_count`, because a record awaiting disposal is still held."

        Design: Difficulty/boundary_precision_check/disposal_due_inclusive_boundary_and_two_run_secure_disposal
        """
        fixture = _service_with_one_due_record()
        set_clock("2026-08-30T23:59:59.999Z")
        run_compliance(fixture["service_id"])
        set_clock("2026-08-31T00:00:00Z")

        summary = run_compliance(fixture["service_id"])

        assert summary["run_sequence"] == 2
        assert summary["scheduled_count"] == 1, (
            f"the due record is scheduled, got {summary['scheduled_count']}"
        )
        assert summary["disposed_count"] == 0, (
            "a record scheduled by this very run is not destroyed by it, got "
            f"{summary['disposed_count']}"
        )
        assert summary["live_child_data_element_count_after"] == 1
        record = read_record(fixture["record_id"])
        assert record["status"] == "SCHEDULED_FOR_DISPOSAL"
        assert record["scheduled_run_sequence"] == 2, (
            "the record carries this run's sequence number, got "
            f"{record['scheduled_run_sequence']}"
        )
        assert record["disposed_at"] is None

    def test_10_the_following_run_destroys_the_record_with_its_pinned_method(self):
        """The next run destroys what an earlier run scheduled.

        "a record whose `status` is `SCHEDULED_FOR_DISPOSAL` is moved to `DISPOSED` only
        when its `scheduled_run_sequence` is strictly less than this run's sequence number
        ... Destruction stamps `disposed_at` with the current logical-clock instant and is
        carried out by the record's pinned `disposal_method_applied`". Either a
        `ComplianceOfficer` or a `PrivacyEngineer` may trigger a run.

        Design: Difficulty/boundary_precision_check/disposal_due_inclusive_boundary_and_two_run_secure_disposal
        """
        fixture = _service_with_one_due_record()
        set_clock("2026-08-30T23:59:59.999Z")
        run_compliance(fixture["service_id"])
        set_clock("2026-08-31T00:00:00Z")
        run_compliance(fixture["service_id"])

        summary = run_compliance(fixture["service_id"], ENGINEER_HEADERS)

        assert summary["run_sequence"] == 3
        assert summary["scheduled_count"] == 0
        assert summary["disposed_count"] == 1, (
            f"the previously scheduled record is destroyed, got {summary['disposed_count']}"
        )
        assert summary["live_child_data_element_count_after"] == 0
        assert summary["compliance_posture_after"] == "OPEN"

        record = read_record(fixture["record_id"])
        assert record["status"] == "DISPOSED"
        assert_instant(record["disposed_at"], "2026-08-31T00:00:00Z", "disposed_at")
        assert record["disposal_method_applied"] == "ANONYMIZE"

        service = read_service(fixture["service_id"])
        assert service["compliance_run_sequence"] == 3, (
            f"three runs have executed, got {service['compliance_run_sequence']}"
        )
        assert service["live_child_data_element_count"] == 0
        assert service["lifetime_collected_element_count"] == 1
        assert read_consent(fixture["consent_id"])["status"] == "GRANTED", (
            "a granted consent is not touched by consent expiry"
        )
