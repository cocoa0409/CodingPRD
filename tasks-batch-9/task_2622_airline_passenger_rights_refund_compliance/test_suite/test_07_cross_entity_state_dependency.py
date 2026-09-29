"""Gates that read a neighbouring row's state before letting an action through."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ERR_OPEN_COMPLAINT_IN_PERIOD,
    ERR_SEGMENT_STATE_INVALID,
    ERR_SOURCE_DISRUPTION_RESCINDED,
    OFFICER_2,
    OFFICER_2_HEADERS,
    OFFICER_HEADERS,
    OPS_HEADERS,
    acknowledge,
    answer,
    assert_booking_ledger,
    assert_instant,
    assert_null,
    assert_obligation_axes,
    assert_segment_state,
    build_world,
    create_booking,
    create_passenger,
    create_policy_profile,
    delay_segment,
    elect,
    factories as f,
    file_complaint,
    initiate,
    obligations_with_meta,
    open_report,
    read_booking,
    read_complaint,
    read_obligation,
    read_profile,
    read_segment,
    read_tarmac_event,
    record_operation,
    set_clock,
    sole_obligation,
)

# ─── Settlement blocked by a rescinded disruption ─────


def _restored_delay(api):
    """A significant delay that produced an obligation, then walked back to schedule."""
    set_clock(api, "2026-08-11T09:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "restored@example.com", "Rory Restored")
    booking = create_booking(
        api, passenger["id"], profile["id"], "RES001", 100000, "CREDIT_CARD"
    )
    segment = validate_success(
        api.create_flight_segment(
            booking["id"],
            f.flight_segment_payload(
                sequence_index=1,
                flight_number="ZQ101",
                origin_iata="LAX",
                destination_iata="DEN",
                scheduled_departure_utc="2026-08-12T14:00:00Z",
                scheduled_arrival_utc="2026-08-12T17:00:00Z",
                segment_fare_cents=100000,
            ),
            OPS_HEADERS,
        ),
        201,
    )
    delay_segment(api, segment["id"], "2026-08-12T20:00:00Z", "2026-08-11T09:00:00Z")
    obligation = sole_obligation(api, booking["id"])
    elect(api, obligation["id"], "CASH", OFFICER_HEADERS)
    record_operation(api, segment["id"], "RESTORED", "2026-08-11T10:00:00Z")
    return booking, segment, obligation


class TestSettlementBlockedAfterRestore:
    def test_restoring_the_leg_leaves_the_obligation_standing_but_unpayable(self, api):
        """The delay facts are wiped, the debt survives, and the money cannot move.

        PRD §3.2: "Restoration clears `disruption_type` back to `NONE`, sets
        `revised_arrival_utc` to null, resets `delay_minutes` to 0 and
        `is_significant_delay` to false, sets `disruption_declared_at_utc` to null, and
        advances the leg's `version` by 1; the booking's `disruption_posture` and
        `unused_segment_count` are recomputed and the booking's `version` advances by 1."

        PRD §3.7: "For an obligation on a `FARE` basis, the leg that caused it must
        still be disrupted: its `status` must be `CANCELLED` or `DISRUPTED_UNUSED`, or it
        must be `DELAYED` with `is_significant_delay` true; a leg whose disruption was
        rescinded by a restore blocks settlement of the obligation it produced, with
        `ERR_SOURCE_DISRUPTION_RESCINDED`."

        Design: Difficulty/cross_entity_state_dependency/settlement_blocked_after_source_delay_restored
        """
        booking, segment, obligation = _restored_delay(api)

        stored_segment = read_segment(api, segment["id"])
        assert_segment_state(
            stored_segment,
            status="SCHEDULED",
            disruption_type="NONE",
            revised_arrival_utc=None,
            delay_minutes=0,
            is_significant_delay=False,
            disruption_declared_at_utc=None,
        )

        refused = api.initiate_settlement(
            obligation["id"], f.initiate_payload("PROC-0001"), OFFICER_2_HEADERS
        )
        validate_error(refused, ERR_SOURCE_DISRUPTION_RESCINDED, 409)

        blocked = read_obligation(api, obligation["id"])
        assert_obligation_axes(
            blocked, settlement_status="UNSETTLED", settlement_attempt_count=0
        )
        assert blocked["amount_cents"] == 100000
        assert_booking_ledger(
            read_booking(api, booking["id"]), total_refund_obligated_cents=100000
        )

    def test_re_declaring_the_delay_unblocks_settlement_without_a_second_obligation(
        self, api
    ):
        """The first valuation stands and the gate reopens the moment the leg is delayed again.

        PRD §3.2: "If a fare obligation already exists for the leg, its `amount_cents`
        is **not** recomputed — the first valuation stands."

        PRD §3.7: "On success the settlement axis moves `UNSETTLED → INITIATED` (or
        `FAILED → INITIATED` on a retry), `settlement_attempt_count` increases by 1,
        `settlement_initiated_at_utc` is stamped from the logical clock's current instant,
        `settlement_initiated_by_user_id` is written from `X-User-ID`, and the
        obligation's `version` advances by 1."

        Design: Difficulty/cross_entity_state_dependency/settlement_blocked_after_source_delay_restored
        """
        booking, segment, obligation = _restored_delay(api)

        delay_segment(api, segment["id"], "2026-08-12T20:00:00Z", "2026-08-11T11:00:00Z")
        assert_segment_state(
            read_segment(api, segment["id"]),
            status="DELAYED",
            delay_minutes=180,
            is_significant_delay=True,
        )
        _, meta = obligations_with_meta(api, booking["id"], basis="FARE")
        assert meta["total_count"] == 1, "the re-declaration must not mint a second row"

        initiate(api, obligation["id"], OFFICER_2_HEADERS)

        settled_axis = read_obligation(api, obligation["id"])
        assert_obligation_axes(
            settled_axis, settlement_status="INITIATED", settlement_attempt_count=1
        )
        assert settled_axis["settlement_initiated_by_user_id"] == OFFICER_2
        assert_booking_ledger(
            read_booking(api, booking["id"]), total_refund_obligated_cents=100000
        )


# ─── Report submission blocked by an open complaint ────


def _report_with_an_open_complaint(api):
    """A June report whose only complaint is still sitting in ACKNOWLEDGED."""
    set_clock(api, "2026-06-10T10:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "june@example.com", "Jun Ledger")
    booking = create_booking(
        api, passenger["id"], profile["id"], "JUN001", 40000, "CREDIT_CARD"
    )
    validate_success(
        api.create_flight_segment(
            booking["id"],
            f.flight_segment_payload(
                sequence_index=1,
                flight_number="ZQ101",
                origin_iata="LAX",
                destination_iata="DEN",
                scheduled_departure_utc="2026-06-12T14:00:00Z",
                scheduled_arrival_utc="2026-06-12T17:00:00Z",
                segment_fare_cents=40000,
            ),
            OPS_HEADERS,
        ),
        201,
    )
    complaint = file_complaint(
        api,
        booking["id"],
        category="REFUND",
        channel="PHONE",
        received_at_utc="2026-06-10T10:00:00Z",
    )
    acknowledge(api, complaint["id"], "2026-06-11T09:00:00Z")
    report = open_report(
        api, profile["id"], "2026-06-01T00:00:00Z", "2026-06-30T23:59:59Z"
    )
    set_clock(api, "2026-07-05T12:00:00Z")
    return profile, complaint, report


class TestReportSubmitBlockedByOpenComplaint:
    def test_an_unanswered_complaint_in_the_window_blocks_the_filing(self, api):
        """The report stays in DRAFT with every metric still at zero.

        PRD §3.9: "Every consumer complaint inside the report's scope and period must
        have reached `ANSWERED` or `CLOSED`; an open complaint anywhere in the window
        blocks the filing with `ERR_OPEN_COMPLAINT_IN_PERIOD`."

        PRD §3.9: "A new report opens in `DRAFT` with all seven metrics at 0,
        `policy_version_pinned` at 0 and `amendment_count` at 0; opening it also increases
        the profile's `report_count` and advances the profile's `version` by 1, which is
        why two reports cannot be opened back to back against one stale profile version."

        Design: Difficulty/cross_entity_state_dependency/report_submit_blocked_by_open_complaint_in_period
        """
        profile, complaint, report = _report_with_an_open_complaint(api)

        refused = api.submit_regulator_report(
            report["id"], f.submit_report_payload("2026-07-05T12:00:00Z"), ADMIN_HEADERS
        )

        validate_error(refused, ERR_OPEN_COMPLAINT_IN_PERIOD, 409)
        assert read_complaint(api, complaint["id"])["status"] == "ACKNOWLEDGED"
        rows, _ = _reports_of(api, profile["id"])
        stored = _report_by_id(rows, report["id"])
        assert stored["status"] == "DRAFT"
        for metric in (
            "complaint_count",
            "disability_complaint_count",
            "late_answer_count",
            "tarmac_violation_count",
            "involuntary_denied_boarding_count",
            "refund_obligation_cents_total",
            "overdue_refund_count",
        ):
            assert stored[metric] == 0, f"{metric} must stay at 0 on a refused submit"

    def test_answering_the_complaint_lets_the_filing_freeze_its_metrics(self, api):
        """Once answered, the submit succeeds and counts the one complaint in scope.

        PRD §3.9: "On that basis the seven metrics are computed and frozen onto the row:
        `complaint_count`, the number of complaints in scope whose `received_at_utc` falls
        in the window; `disability_complaint_count`, how many of those same complaints
        have `category` `DISABILITY`; `late_answer_count`, how many of those same
        complaints carry `answer_breached` true; `tarmac_violation_count`, the number of
        tarmac delay events in scope, reached through their leg's booking, whose
        `tarmac_start_utc` falls in the window and whose `is_violation` is true;
        `involuntary_denied_boarding_count`, the number of denied-boarding records in
        scope whose `status` is `FINALIZED` or `RECATEGORIZED`, whose `finalized_at_utc`
        falls in the window, and whose `effective_category` is `INVOLUNTARY` — so a
        recategorized volunteer counts here, which is the whole point of recategorization;
        `refund_obligation_cents_total`, the sum of `amount_cents` over obligations in
        scope whose `obligation_start_utc` falls in the window and whose settlement axis is
        not voided, added in ascending `created_at` order; and `overdue_refund_count`, the
        number of obligations in scope whose `obligation_start_utc` falls in the window and
        whose `deadline_breached` is true."

        PRD §3.9: "Alongside them `policy_version_pinned` captures the profile's
        `version` as observed during this submit, and the report moves to `SUBMITTED` with
        `submitted_at_utc` stored and `submitted_by_user_id` taken from `X-User-ID`, its
        `version` advancing by 1."

        Design: Difficulty/cross_entity_state_dependency/report_submit_blocked_by_open_complaint_in_period
        """
        profile, complaint, report = _report_with_an_open_complaint(api)

        answer(api, complaint["id"], "2026-07-05T12:00:00Z", "POLICY_EXPLAINED")
        profile_version = read_profile(api, profile["id"])["version"]
        submitted = validate_success(
            api.submit_regulator_report(
                report["id"], f.submit_report_payload("2026-07-05T12:00:00Z"), ADMIN_HEADERS
            )
        )

        assert submitted["status"] == "SUBMITTED"
        assert_instant(submitted["submitted_at_utc"], "2026-07-05T12:00:00Z")
        assert submitted["complaint_count"] == 1
        assert submitted["disability_complaint_count"] == 0
        assert submitted["late_answer_count"] == 0
        assert submitted["tarmac_violation_count"] == 0
        assert submitted["involuntary_denied_boarding_count"] == 0
        assert submitted["refund_obligation_cents_total"] == 0
        assert submitted["overdue_refund_count"] == 0
        assert submitted["policy_version_pinned"] == profile_version


def _reports_of(api, profile_id):
    return validate_paginated(api.list_policy_profile_reports(profile_id, ADMIN_HEADERS))


def _report_by_id(rows, report_id):
    for row in rows:
        if row["id"] == report_id:
            return row
    raise AssertionError(f"report {report_id} not listed on its profile")


# ─── Tarmac filing blocked by an open leg ─────────────


def _deplaned_event_on_a_scheduled_leg(api):
    """A compliant occupation closed out on a leg that has not yet departed."""
    set_clock(api, "2026-08-10T22:00:00Z")
    world = build_world(
        api,
        total_fare_cents=30000,
        segment_fares=[30000],
        record_locator="GAT001",
        email="gate@example.com",
    )
    segment = world.segments[0]
    event = validate_success(
        api.create_tarmac_delay_event(
            f.tarmac_event_payload(segment["id"], "2026-08-10T14:10:00Z", "DEPARTURE"),
            OPS_HEADERS,
        ),
        201,
    )
    validate_success(
        api.deplane_tarmac_event(
            event["id"], f.deplane_payload("2026-08-10T17:10:00Z"), OPS_HEADERS
        )
    )
    return segment, event


class TestTarmacReportBlockedWhileLegIsScheduled:
    def test_filing_on_a_leg_that_never_departed_is_premature(self, api):
        """The contingency report waits for the leg to close out operationally.

        PRD §3.5: "The parent leg must additionally be operationally closed out — its
        `status` must be `DEPARTED`, `ARRIVED` or `CANCELLED` — since a contingency-plan
        report on a flight still shown as scheduled or merely delayed would be premature;
        filing while the leg is `SCHEDULED` or `DELAYED` is refused with
        `ERR_SEGMENT_STATE_INVALID`."

        Design: Difficulty/cross_entity_state_dependency/tarmac_report_blocked_while_segment_still_scheduled
        """
        segment, event = _deplaned_event_on_a_scheduled_leg(api)

        refused = api.file_tarmac_report(
            event["id"],
            f.file_report_payload("TDR-GATE-1", "2026-08-10T22:00:00Z"),
            ADMIN_HEADERS,
        )

        validate_error(refused, ERR_SEGMENT_STATE_INVALID, 409)
        stored = read_tarmac_event(api, event["id"], segment["id"])
        assert stored["status"] == "DEPLANED"
        assert_null(stored["report_reference"], "report_reference")
        assert_segment_state(
            read_segment(api, segment["id"]),
            status="SCHEDULED",
            cumulative_tarmac_minutes=180,
            exempted_tarmac_event_count=0,
        )

    def test_recording_the_departure_opens_the_gate_for_the_filing(self, api):
        """A compliant deplaning files with no narrative once the leg has departed.

        PRD §3.2: "Departure writes `actual_departure_utc` from `occurred_at_utc`,
        advances the leg's `version` by 1, sets the booking's `travel_commenced` to true,
        recomputes `unused_segment_count` and `disruption_posture`, and advances the
        booking's `version` by 1."

        PRD §3.5: "On the deplaning branch, an event whose `is_violation` is true
        requires a narrative `corrective_action_summary`, and omitting it is
        `ERR_CORRECTIVE_ACTION_REQUIRED`; a compliant deplaned event needs no narrative."

        Design: Difficulty/cross_entity_state_dependency/tarmac_report_blocked_while_segment_still_scheduled
        """
        segment, event = _deplaned_event_on_a_scheduled_leg(api)

        record_operation(api, segment["id"], "DEPARTED", "2026-08-10T17:30:00Z")
        validate_success(
            api.file_tarmac_report(
                event["id"],
                f.file_report_payload("TDR-GATE-1", "2026-08-10T22:00:00Z"),
                ADMIN_HEADERS,
            )
        )

        stored = read_tarmac_event(api, event["id"], segment["id"])
        assert stored["status"] == "REPORT_FILED"
        assert stored["report_reference"] == "TDR-GATE-1"
        assert_null(stored["corrective_action_summary"], "corrective_action_summary")
        stored_segment = read_segment(api, segment["id"])
        assert_instant(stored_segment["actual_departure_utc"], "2026-08-10T17:30:00Z")
        assert_segment_state(
            stored_segment, cumulative_tarmac_minutes=180, exempted_tarmac_event_count=0
        )
