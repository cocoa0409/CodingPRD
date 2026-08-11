"""Record designation, transcript orders, completeness computation."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_record, assert_transcript_order,
    assert_instant_equal, add_calendar_days, iso_utc, parse_ts,
    create_transcript_order_payload, deliver_transcript_payload,
    attorney_headers,
    setup_record_pending_case,
    order_transcript,
    set_clock,
    CLERK,
)


class TestRevokeDesignation:
    def test_revoke_designation_cancels_open_transcripts(self, api):
        """PRD §3.3: "Designation can also be walked back: revoking a designation
        moves the record from `DESIGNATED` back to `PENDING_DESIGNATION`, but only
        while no transcript order under the record has reached `DELIVERED` or
        `FILED`. Revocation clears `designated_at` to null and cancels every
        transcript order still sitting in `ORDERED` or `IN_PREPARATION`."

        Design: Corner/state_machines/record_revoke_designation_cancels_open_transcripts
        """
        ctx = setup_record_pending_case(court_overrides={"code": "SM5"})
        attorney = ctx["attorney"]
        headers = attorney_headers(attorney)
        rec_id = ctx["record"]["id"]

        validate_success(api.designate_record(rec_id, headers), 200)
        t_ordered = order_transcript(rec_id, attorney, court_reporter="R1")
        t_ordered_2 = order_transcript(rec_id, attorney, court_reporter="R2",
                                       hearing_date="2026-04-02T10:00:00Z")

        res = api.revoke_designation(rec_id, headers)
        record = validate_success(res, 200)
        assert_record(record)
        assert record["status"] == "PENDING_DESIGNATION"
        assert record["designated_at"] is None, "revocation must clear designated_at to null"

        for tid, label in ((t_ordered["id"], "ORDERED"), (t_ordered_2["id"], "ORDERED")):
            after = validate_success(api.get_transcript_order(tid, headers), 200)
            assert after["status"] == "CANCELLED", (
                f"transcript that was {label} must be CANCELLED after revocation, got {after['status']}"
            )


class TestTranscriptTerminalLockdown:
    def test_cancel_filed_transcript_returns_already_terminal(self, api):
        """PRD §2.9: "And a transition attempted against a resource already
        resting in a terminal state — `FILED` or `CANCELLED` for a transcript
        order, `ACCEPTED` or `STRICKEN` for a brief, `GRANTED`, `DENIED`, or
        `WITHDRAWN` for a motion or petition, `ACCEPTED` or `REJECTED` for a
        filing, `HELD` or `WAIVED` for an argument, `COMPLETE` or `VACATED` for a
        schedule, `FILED` for a record, `CLOSED` for a case — is rejected with
        `ERR_ALREADY_TERMINAL` (HTTP 409) rather than `ERR_INVALID_STATE`."

        Design: Corner/state_machines/transcript_cancel_from_terminal_returns_already_terminal
        """
        ctx = setup_record_pending_case(court_overrides={"code": "SM2"})
        attorney = ctx["attorney"]
        headers = attorney_headers(attorney)
        rec_id = ctx["record"]["id"]

        validate_success(api.designate_record(rec_id, headers), 200)
        transcript = order_transcript(rec_id, attorney)
        validate_success(api.begin_preparation(transcript["id"], CLERK), 200)
        validate_success(
            api.deliver_transcript(transcript["id"], deliver_transcript_payload(), CLERK), 200
        )
        filed = validate_success(api.file_transcript(transcript["id"], headers), 200)
        assert filed["status"] == "FILED"

        res = api.cancel_transcript(transcript["id"], headers)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL.value, expected_status=409)


class TestRecordCompleteness:
    def test_completeness_pct_floor_math_with_partial_delivery(self, api):
        """PRD §3.3: "Every change to any transcript order under a record
        recomputes the record's `completeness_pct`: counting only orders that are
        not `CANCELLED` as the designated set, and counting orders that are
        `DELIVERED` or `FILED` as delivered, the percentage is one hundred times
        the delivered count divided by the designated count, truncated down to a
        whole percent; when no non-cancelled orders exist at all, completeness
        is 0."

        Design: Corner/calculations/record_completeness_pct_correct_math
        """
        ctx = setup_record_pending_case(court_overrides={"code": "CAL1"})
        attorney = ctx["attorney"]
        headers = attorney_headers(attorney)
        rec_id = ctx["record"]["id"]

        validate_success(api.designate_record(rec_id, headers), 200)
        transcripts = [
            order_transcript(rec_id, attorney, hearing_date=f"2026-04-0{i}T10:00:00Z",
                             court_reporter=f"R{i}")
            for i in range(1, 5)
        ]
        for t in transcripts[:3]:
            validate_success(api.begin_preparation(t["id"], CLERK), 200)
            validate_success(
                api.deliver_transcript(t["id"], deliver_transcript_payload(), CLERK), 200
            )
        validate_success(api.begin_preparation(transcripts[3]["id"], CLERK), 200)

        record = validate_success(api.get_record(rec_id, headers), 200)
        assert_record(record)
        assert record["completeness_pct"] == 75, (
            f"3 of 4 delivered must floor to 75, got {record['completeness_pct']}"
        )
        assert record["status"] == "ASSEMBLING", (
            f"record must stay ASSEMBLING while one order is IN_PREPARATION, got {record['status']}"
        )

    def test_completeness_pct_zero_when_no_transcripts(self, api):
        """PRD §3.3: "Every change to any transcript order under a record
        recomputes the record's `completeness_pct`: counting only orders that are
        not `CANCELLED` as the designated set, and counting orders that are
        `DELIVERED` or `FILED` as delivered, the percentage is one hundred times
        the delivered count divided by the designated count, truncated down to a
        whole percent; when no non-cancelled orders exist at all, completeness
        is 0."

        Design: Corner/calculations/record_completeness_pct_zero_when_no_transcripts
        """
        ctx = setup_record_pending_case(court_overrides={"code": "CAL2"})
        headers = attorney_headers(ctx["attorney"])
        rec_id = ctx["record"]["id"]
        validate_success(api.designate_record(rec_id, headers), 200)

        record = validate_success(api.get_record(rec_id, headers), 200)
        assert record["completeness_pct"] == 0, (
            f"zero transcript orders must yield completeness 0, got {record['completeness_pct']}"
        )


class TestTranscriptDeliveryDeadline:
    def test_transcript_due_at_is_ordered_at_plus_thirty_days(self, api):
        """PRD §3.3: "A new order starts in `ORDERED` with `ordered_at` stamped
        at creation, `actual_pages` at 0, `delivered_at` null, and a `due_at`
        computed as `ordered_at` plus the court's transcript delivery window —
        thirty days unless the court configures otherwise."

        Design: Difficulty/resource_temporal_overlap/transcript_delivery_deadline_vs_record_designation_window
        """
        ctx = setup_record_pending_case(court_overrides={"code": "OV2"})
        attorney = ctx["attorney"]
        headers = attorney_headers(attorney)
        rec_id = ctx["record"]["id"]
        validate_success(api.designate_record(rec_id, headers), 200)

        set_clock("2026-06-11T00:00:00Z")
        res = api.create_transcript_order(
            rec_id, create_transcript_order_payload(), headers
        )
        transcript = validate_success(res, 201)
        assert_transcript_order(transcript)
        assert transcript["status"] == "ORDERED"
        assert transcript["actual_pages"] == 0
        assert transcript["delivered_at"] is None
        assert_instant_equal(transcript["ordered_at"], "2026-06-11T00:00:00Z")
        expected_due = iso_utc(add_calendar_days("2026-06-11T00:00:00Z", 30))
        assert_instant_equal(
            transcript["due_at"], expected_due,
            "transcript due_at must be ordered_at plus the thirty-day delivery window",
        )
        assert parse_ts(transcript["due_at"]) > parse_ts(transcript["ordered_at"])

    def test_transcript_due_at_preserves_time_of_day_of_ordering(self, api):
        """PRD §3.3: "A new order starts in `ORDERED` with `ordered_at` stamped
        at creation, `actual_pages` at 0, `delivered_at` null, and a `due_at`
        computed as `ordered_at` plus the court's transcript delivery window —
        thirty days unless the court configures otherwise."
        PRD §2.7: "Deadline arithmetic throughout the system adds whole calendar
        days to timestamps and preserves the time-of-day of the anchor instant;
        all timestamps are compared and stored at one-second precision with no
        rounding."

        Design: Difficulty/resource_temporal_overlap/transcript_delivery_deadline_vs_record_designation_window
        """
        ctx = setup_record_pending_case(court_overrides={"code": "OV2T"})
        attorney = ctx["attorney"]
        headers = attorney_headers(attorney)
        rec_id = ctx["record"]["id"]
        validate_success(api.designate_record(rec_id, headers), 200)

        set_clock("2026-06-11T15:45:30Z")
        transcript = validate_success(
            api.create_transcript_order(rec_id, create_transcript_order_payload(), headers),
            201,
        )
        expected_due = iso_utc(add_calendar_days("2026-06-11T15:45:30Z", 30))
        assert_instant_equal(
            transcript["due_at"], expected_due,
            "the thirty-day addition must preserve the anchor's time-of-day",
        )
