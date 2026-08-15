"""Emergency drills (quiet-gap scheduling, conduct guards) and training-record
currency boundaries."""
from test_helpers import (
    PSC,
    ApiErrorId,
    api_client,
    assert_timestamp_instant,
    create_drill_event_payload,
    create_employee,
    create_facility,
    create_trained_employee,
    record_training,
    schedule_drill,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDrillQuietGap:

    def test_drill_quiet_gap_exactly_24h_allowed(self):
        """PRD section 3.5: "Scheduling also enforces a quiet period against
        every other `PLANNED` or `CONDUCTED` drill of the same facility: a
        conflict exists unless the new drill begins no earlier than 24 hours
        after the existing drill's scheduled end, or ends no later than 24
        hours before the existing drill's scheduled start — exactly 24 hours
        of separation satisfies the rule in both directions — and a violating
        schedule is rejected with `ERR_DRILL_GAP_VIOLATION` (409)."

        Design: Difficulty/resource_temporal_overlap/drill_quiet_gap_buffer
        """
        facility = create_facility()
        drill1 = schedule_drill(facility["id"], drill_type="TABLETOP",
                                scheduled_start_at="2026-09-10T09:00:00Z",
                                scheduled_end_at="2026-09-10T11:00:00Z")
        assert drill1["status"] == "PLANNED"
        # begins exactly 24 hours after drill1's scheduled end: allowed (>=)
        drill2 = schedule_drill(facility["id"], drill_type="FIELD",
                                scheduled_start_at="2026-09-11T11:00:00Z",
                                scheduled_end_at="2026-09-11T12:00:00Z")
        assert drill2["status"] == "PLANNED"

    def test_drill_quiet_gap_one_hour_rejected(self):
        """PRD section 3.5: "Scheduling also enforces a quiet period against
        every other `PLANNED` or `CONDUCTED` drill of the same facility: a
        conflict exists unless the new drill begins no earlier than 24 hours
        after the existing drill's scheduled end, or ends no later than 24
        hours before the existing drill's scheduled start — exactly 24 hours
        of separation satisfies the rule in both directions — and a violating
        schedule is rejected with `ERR_DRILL_GAP_VIOLATION` (409)."

        Design: Difficulty/resource_temporal_overlap/drill_quiet_gap_buffer
        """
        facility = create_facility()
        schedule_drill(facility["id"], drill_type="TABLETOP",
                       scheduled_start_at="2026-09-10T09:00:00Z",
                       scheduled_end_at="2026-09-10T11:00:00Z")
        schedule_drill(facility["id"], drill_type="FIELD",
                       scheduled_start_at="2026-09-11T11:00:00Z",
                       scheduled_end_at="2026-09-11T12:00:00Z")
        # only 1h after the second drill ends: inside the 24h quiet buffer
        resp = api_client.create_drill_event(
            create_drill_event_payload(
                facility["id"], drill_type="EVACUATION",
                scheduled_start_at="2026-09-11T13:00:00Z",
                scheduled_end_at="2026-09-11T14:00:00Z"),
            PSC)
        validate_error(resp, ApiErrorId.ERR_DRILL_GAP_VIOLATION,
                       expected_status=409)

    def test_drill_inverted_window_rejected(self):
        """PRD section 3.5: "A `PsCoordinator` schedules one with `facility_id`,
        a `drill_type` of `TABLETOP`, `FIELD`, or `EVACUATION`, and an
        inclusive window from `scheduled_start_at` to `scheduled_end_at`; the
        end must come strictly after the start, else `ERR_INVALID_WINDOW`."

        Design: Corner/validations/drill_inverted_window_rejected
        """
        facility = create_facility()
        resp = api_client.create_drill_event(
            create_drill_event_payload(
                facility["id"], drill_type="TABLETOP",
                scheduled_start_at="2026-09-10T11:00:00Z",
                scheduled_end_at="2026-09-10T09:00:00Z"),
            PSC)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW, expected_status=422)


class TestDrillConduct:

    def test_drill_conduct_cross_facility_attendee_rejected(self):
        """PRD section 3.5: "The `PsCoordinator` supplies the
        `attendee_employee_ids` roster, and two guards apply: every roster
        entry must reference an `ACTIVE` employee of the drill's own facility
        (`ERR_CROSS_FACILITY_REFERENCE`), and at least two attendees must each
        hold an `AMMONIA_OPERATOR` training record whose currency is not
        `EXPIRED` at conduct time — fewer than two such attendees means
        rejection with `ERR_DRILL_TRAINING_SHORTFALL` (422)."

        Design: Corner/validations/drill_conduct_cross_facility_attendee_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        plant_a = create_facility(name="Plant A")
        plant_b = create_facility(name="Plant B")
        a1, _ = create_trained_employee(plant_a["id"], "A One")
        a2, _ = create_trained_employee(plant_a["id"], "A Two")
        b1, _ = create_trained_employee(plant_b["id"], "B One")
        drill = schedule_drill(plant_a["id"], drill_type="FIELD",
                               scheduled_start_at="2026-09-10T09:00:00Z",
                               scheduled_end_at="2026-09-10T11:00:00Z")
        # the training quorum is satisfied (all three hold current
        # AMMONIA_OPERATOR records), so only the referential guard can fail
        resp = api_client.conduct_drill(
            drill["id"],
            {"attendee_employee_ids": [a1["id"], a2["id"], b1["id"]]},
            PSC)
        validate_error(resp, ApiErrorId.ERR_CROSS_FACILITY_REFERENCE,
                       expected_status=422)
        after = validate_success(api_client.get_drill_event(drill["id"], PSC),
                                 expected_status=200)
        assert after["status"] == "PLANNED"


class TestTrainingCurrency:

    def test_training_currency_boundaries(self):
        """PRD section 3.5: "Training currency follows a three-year refresher
        cycle."
        PRD section 3.5: "the platform computes `expires_at` as exactly 1095
        days after completion and derives the record's `currency` — `EXPIRED`
        once the clock reaches or passes `expires_at`, `EXPIRING_SOON` while
        expiry lies no more than 90 days ahead, and `CURRENT` otherwise."

        Design: Corner/calculations/training_currency_boundaries
        """
        set_clock("2026-08-01T00:00:00Z")
        facility = create_facility()
        emp_a = create_employee(facility["id"], "Amy A")
        emp_b = create_employee(facility["id"], "Bob B")
        record_training(emp_a["id"], topic="AMMONIA_OPERATOR",
                        completed_at="2023-10-31T00:00:00Z")
        record_training(emp_b["id"], topic="AMMONIA_OPERATOR",
                        completed_at="2023-08-02T00:00:00Z")

        records, meta = validate_paginated(api_client.list_training_records(PSC))
        by_employee = {r["employee_id"]: r for r in records}

        record_a = by_employee[emp_a["id"]]
        # 2023-10-31 + 1095 days = 2026-10-30: exactly 90 days out (<=)
        assert_timestamp_instant(record_a["expires_at"], "2026-10-30T00:00:00Z")
        assert record_a["currency"] == "EXPIRING_SOON"

        record_b = by_employee[emp_b["id"]]
        # 2023-08-02 + 1095 days = 2026-08-01: the clock has reached it (>=)
        assert_timestamp_instant(record_b["expires_at"], "2026-08-01T00:00:00Z")
        assert record_b["currency"] == "EXPIRED"
