"""Which error wins when two rules break at once, and what happens at the edges.

The first half drives requests that violate two rules in the same call and pins
the one the precedence order names. The second half sits exactly on a threshold
and then one unit past it.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    CALL_SHEET_DRAFT,
    CALL_SHEET_PUBLISHED,
    CATEGORY_CREW,
    CATEGORY_LOCATION,
    CERT_EXPIRED,
    CERT_ISSUED,
    COORDINATOR,
    DELIVERABLE_PENDING,
    DEPT_GRIP_ELECTRIC,
    POSTURE_BLOCKED,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    QC_DURATION_OUT_OF_TOLERANCE,
    SHOOT_DAY_CANCELLED,
    SHOOT_DAY_CONFIRMED,
    TECHNICAL_QC_FAILED,
    TECHNICAL_QC_PASSED,
    ApiErrorId,
    add_budget_line,
    add_crew_member,
    add_deliverable,
    approve_budget,
    assert_at_default_clock,
    assert_cert_statuses,
    assert_deliverable_state,
    assert_ledgers,
    assert_shoot_day_state,
    assert_total_count,
    assert_version_axes,
    book_crew,
    cancel_shoot_day,
    confirm_booking,
    confirm_shoot_day,
    issued_coi,
    issued_permit,
    lock_scope,
    open_project,
    read_cert,
    read_cut,
    read_deliverable,
    read_project,
    read_shoot_day,
    record_qc,
    register_location,
    schedule_shoot_day,
    set_clock,
    upload_next_cut,
)


def _cancelled_day_and_an_unaffordable_grip(api):
    """A cancelled day plus a booking that would also break the strict ceiling."""
    project = open_project(
        api,
        client_name="Tallow Coffee",
        campaign_title="Slow Roast",
        creative_brief_summary="Single-day broadcast brand film on a very tight budget.",
        channel_scope=["BROADCAST"],
        usage_term_months=12,
        budget_ceiling_cents=300000,
    )
    add_deliverable(
        api,
        project["id"],
        title="Slow Roast 30",
        channel="BROADCAST",
        aspect_ratio="16:9",
        target_duration_seconds=30,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_CREW,
        description="Grip department pool",
        quantity=1,
        unit_rate_cents=100000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    location = register_location(
        api,
        name="Warehouse 12",
        address="12 Dock Street, Tacoma",
        stage_count=1,
        daily_fee_cents=90000,
        insurance_minimum_cents=50000000,
        permit_authority="Tacoma Film Office",
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    crew = add_crew_member(
        api,
        full_name="Sasha Bell",
        department=DEPT_GRIP_ELECTRIC,
        hourly_rate_cents=45000,
        min_turnaround_hours=10,
    )
    day = cancel_shoot_day(
        api, day["id"], cancellation_reason="Location double-booked by the venue."
    )
    assert_shoot_day_state(day, status=SHOOT_DAY_CANCELLED)
    return project, day, crew


def _book_the_grip(api, day, crew):
    """The one request that breaks the day-state rule and the fiscal rule at once."""
    return api.create_crew_booking(
        {
            "shoot_day_id": day["id"],
            "crew_member_id": crew["id"],
            "department_role": "Key Grip",
            "call_time": "2026-09-10T06:00:00Z",
            "wrap_time": "2026-09-10T16:00:00Z",
        },
        headers=COORDINATOR,
    )


def test_the_cancelled_day_is_reported_and_the_blown_ceiling_is_not(api):
    """Day state ranks at 22 and the fiscal allowance at 46, so state wins.

    PRD §2.12: "Priority 22: **Shoot-day status permits the operation**
    (`ERR_SHOOT_DAY_STATE_INVALID`): confirmation requires `PLANNED`; call-sheet
    publication requires `CONFIRMED`; wrap requires `CONFIRMED`; cancellation
    requires `PLANNED` or `CONFIRMED`; crew-booking and equipment-reservation
    creation require the day to be `PLANNED` or `CONFIRMED`."

    PRD §2.8: "This gate is evaluated **last** of all checks on those four
    endpoints, so a state or safety defect on the same request always reports its
    own error first."

    Design: Difficulty/priority_pair_validation_conflict/shoot_day_state_outranks_budget_ceiling_on_crew_booking
    """
    _project, day, crew = _cancelled_day_and_an_unaffordable_grip(api)

    response = _book_the_grip(api, day, crew)

    validate_error(response, ApiErrorId.ERR_SHOOT_DAY_STATE_INVALID)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_BUDGET_CEILING_EXCEEDED.value


def test_the_refused_booking_writes_no_row_and_moves_no_ledger(api):
    """Losing on the higher-priority rule leaves the projected 550,000 untested.

    PRD §2.8: "The projected figure is the project's current
    `provisional_cost_cents` plus the provisional contribution the new row would
    add — nothing else; no other pending write participates."

    PRD §3.6: "Booking a person onto a day is reserved to a
    `ProductionCoordinator` and requires the day to be `PLANNED` or `CONFIRMED`; a
    `WRAPPED` or `CANCELLED` day accepts no new bookings and reports
    `ERR_SHOOT_DAY_STATE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/shoot_day_state_outranks_budget_ceiling_on_crew_booking
    """
    project, day, crew = _cancelled_day_and_an_unaffordable_grip(api)

    _book_the_grip(api, day, crew)

    assert_total_count(
        api.list_crew_bookings(headers=COORDINATOR, shoot_day_id=day["id"]), 0
    )
    assert_ledgers(
        read_project(api, project["id"]),
        provisional_cents=100000,
        committed_cents=0,
    )


def _confirmed_day_whose_permit_has_since_expired(api):
    """A day confirmed under a good permit, then read an hour past its expiry."""
    project = open_project(
        api,
        client_name="Harbor Health",
        campaign_title="Night Shift",
        creative_brief_summary="Broadcast brand film shot overnight at a working clinic.",
        channel_scope=["BROADCAST"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
    )
    add_deliverable(
        api,
        project["id"],
        title="Night Shift 90",
        channel="BROADCAST",
        aspect_ratio="16:9",
        target_duration_seconds=90,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_LOCATION,
        description="Clinic location fee",
        quantity=1,
        unit_rate_cents=100000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 100000)
    location = register_location(
        api,
        name="Harbor Clinic Wing B",
        address="8 Marine Parade, Seattle",
        stage_count=1,
        daily_fee_cents=100000,
        insurance_minimum_cents=100000000,
        permit_authority="Seattle Film Office",
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    issued_coi(
        api,
        project["id"],
        carrier_or_authority="Bluewater Mutual",
        reference_code="COI-88213",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-12-31T23:59:59Z",
        coverage_amount_cents=100000000,
        fee_cents=180000,
    )
    permit = issued_permit(
        api,
        project["id"],
        day["id"],
        carrier_or_authority="Seattle Film Office",
        reference_code="PRM-40771",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-09-10T23:00:00Z",
        fee_cents=250000,
    )
    day = confirm_shoot_day(api, day["id"])
    assert_shoot_day_state(day, status=SHOOT_DAY_CONFIRMED)
    set_clock(api, "2026-09-11T00:00:00Z")
    return project, day, permit


def test_the_lapsed_permit_is_reported_and_the_shut_lead_window_is_not(api):
    """Safety ranks at 29 and the lead-time rule at 33, so the permit wins.

    PRD §2.12: "Priority 29: **Film permit window**
    (`ERR_PERMIT_WINDOW_MISMATCH`, HTTP 422), checked on both shoot-day
    confirmation and call-sheet publication."

    PRD §2.12: "Priority 33: **Call-sheet lead time**
    (`ERR_CALL_SHEET_WINDOW_CLOSED`, HTTP 422), checked on call-sheet publication."

    PRD §3.7: "The film-permit test and the insurance test are re-run exactly as
    they were at confirmation, reporting `ERR_PERMIT_WINDOW_MISMATCH` and
    `ERR_INSUFFICIENT_COI_COVERAGE` respectively."

    Design: Difficulty/priority_pair_validation_conflict/permit_safety_outranks_call_sheet_lead_window_on_publish
    """
    _project, day, _permit = _confirmed_day_whose_permit_has_since_expired(api)

    response = api.publish_call_sheet(day["id"], headers=COORDINATOR)

    validate_error(response, ApiErrorId.ERR_PERMIT_WINDOW_MISMATCH)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_CALL_SHEET_WINDOW_CLOSED.value


def test_the_permit_row_still_reads_issued_while_deriving_expired(api):
    """The clock disarmed the day without any stored transition on the permit.

    PRD §3.5: "`effective_status` reads `EXPIRED` when the stored `status` is
    `ISSUED` and the logical clock has passed `effective_to`; in every other case
    it simply equals the stored `status`, so `SUBMITTED`, `DENIED`, and an `ISSUED`
    certificate still inside its window all report themselves."

    PRD §3.5: "The posture is `BLOCKED` whenever either the permit test or the
    insurance test fails; it is `RESTRICTED` when both pass but fewer than three
    crew bookings are confirmed; and it is `OPEN` only when both pass and at least
    three are confirmed."

    Design: Difficulty/priority_pair_validation_conflict/permit_safety_outranks_call_sheet_lead_window_on_publish
    """
    _project, day, permit = _confirmed_day_whose_permit_has_since_expired(api)

    api.publish_call_sheet(day["id"], headers=COORDINATOR)

    assert_cert_statuses(
        read_cert(api, permit["id"]), status=CERT_ISSUED, effective_status=CERT_EXPIRED
    )
    assert_shoot_day_state(
        read_shoot_day(api, day["id"]),
        status=SHOOT_DAY_CONFIRMED,
        compliance_posture=POSTURE_BLOCKED,
        call_sheet_status=CALL_SHEET_DRAFT,
    )


def _thirty_second_deliverable_with_a_31_and_a_32_second_cut(api):
    """Two cuts of the same 30-second spec, one inside tolerance and one outside."""
    project = open_project(
        api,
        client_name="Peakline Insurance",
        campaign_title="Thirty Seconds Flat",
        creative_brief_summary="OLV brand film cut to a hard thirty-second slot.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
    )
    deliverable = add_deliverable(
        api,
        project["id"],
        title="Thirty Flat",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=30,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    cut_31 = upload_next_cut(
        api,
        deliverable["id"],
        cut_label="v1 at 31 seconds",
        aspect_ratio="16:9",
        duration_seconds=31,
        has_captions=False,
        caption_format="NONE",
        file_size_gb=7.1,
    )
    cut_32 = upload_next_cut(
        api,
        deliverable["id"],
        cut_label="v2 at 32 seconds",
        aspect_ratio="16:9",
        duration_seconds=32,
        has_captions=False,
        caption_format="NONE",
        file_size_gb=7.3,
    )
    return deliverable, cut_31, cut_32


def test_a_cut_exactly_one_second_off_the_target_passes_qc_clean(api):
    """A one-second difference is inside tolerance, so no finding is recorded.

    PRD §3.8: "`DURATION_OUT_OF_TOLERANCE` is recorded when the absolute
    difference between the cut's `duration_seconds` and the deliverable's
    `target_duration_seconds` is greater than one second — a difference of exactly
    one second passes, a difference of two seconds fails."

    Design: Difficulty/boundary_precision_check/qc_duration_tolerance_passes_at_exactly_one_second
    """
    _deliverable, cut_31, _cut_32 = _thirty_second_deliverable_with_a_31_and_a_32_second_cut(api)

    judged = record_qc(api, cut_31["id"])

    assert_version_axes(judged, technical_status=TECHNICAL_QC_PASSED, qc_failure_reasons=[])


def test_a_cut_two_seconds_off_the_target_fails_on_duration_alone(api):
    """One second further out flips the verdict, and nothing else is faulted.

    PRD §3.8: "If the findings list is empty the cut advances `PENDING_QC →
    QC_PASSED` and `qc_failure_reasons` is written as an empty array; otherwise the
    cut advances `PENDING_QC → QC_FAILED` and `qc_failure_reasons` holds the
    findings in the order above."

    PRD §3.8: "A failing QC is a recorded outcome and a successful call, not a
    request error — the response is a 200 carrying the failed cut."

    Design: Difficulty/boundary_precision_check/qc_duration_tolerance_passes_at_exactly_one_second
    """
    deliverable, cut_31, cut_32 = _thirty_second_deliverable_with_a_31_and_a_32_second_cut(api)
    record_qc(api, cut_31["id"])

    judged = record_qc(api, cut_32["id"])

    assert_version_axes(
        judged,
        technical_status=TECHNICAL_QC_FAILED,
        qc_failure_reasons=[QC_DURATION_OUT_OF_TOLERANCE],
    )
    assert_version_axes(read_cut(api, cut_31["id"]), technical_status=TECHNICAL_QC_PASSED)
    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]),
        status=DELIVERABLE_PENDING,
        version_count=2,
    )


def _compliant_day_with_two_of_three_crew_confirmed(api):
    """A day cleared on paperwork and one confirmation short of publishable."""
    project = open_project(
        api,
        client_name="Fable Toys",
        campaign_title="Playroom",
        creative_brief_summary="Broadcast brand film shot on a single stage day with a small unit.",
        channel_scope=["BROADCAST"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
    )
    add_deliverable(
        api,
        project["id"],
        title="Playroom 60",
        channel="BROADCAST",
        aspect_ratio="16:9",
        target_duration_seconds=60,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_LOCATION,
        description="Stage day fee",
        quantity=1,
        unit_rate_cents=100000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 100000)
    location = register_location(
        api,
        name="Stage 4 Northlight",
        address="400 Foundry Row, Portland",
        stage_count=1,
        daily_fee_cents=100000,
        insurance_minimum_cents=100000000,
        permit_authority="Portland Film Office",
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    issued_coi(
        api,
        project["id"],
        carrier_or_authority="Bluewater Mutual",
        reference_code="COI-90114",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-12-31T23:59:59Z",
        coverage_amount_cents=100000000,
        fee_cents=180000,
    )
    issued_permit(
        api,
        project["id"],
        day["id"],
        carrier_or_authority="Portland Film Office",
        reference_code="PRM-51002",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-09-30T23:59:59Z",
        fee_cents=250000,
    )
    day = confirm_shoot_day(api, day["id"])
    roster = [
        add_crew_member(
            api, full_name="Ivo Marek", department="CAMERA", hourly_rate_cents=5000,
            min_turnaround_hours=10,
        ),
        add_crew_member(
            api, full_name="Sasha Bell", department="GRIP_ELECTRIC", hourly_rate_cents=5000,
            min_turnaround_hours=10,
        ),
        add_crew_member(
            api, full_name="Noor Haddad", department="SOUND", hourly_rate_cents=5000,
            min_turnaround_hours=10,
        ),
    ]
    roles = ["1st AC", "Key Grip", "Sound Mixer"]
    bookings = []
    for member, role in zip(roster[:2], roles[:2]):
        booking = book_crew(
            api,
            day["id"],
            member["id"],
            department_role=role,
            call_time="2026-09-10T06:00:00Z",
            wrap_time="2026-09-10T16:00:00Z",
        )
        bookings.append(confirm_booking(api, booking["id"]))
    return {
        "project": project,
        "day": day,
        "roster": roster,
        "roles": roles,
        "bookings": bookings,
    }


def _confirm_the_third_crew_member(api, built):
    """The confirmation that takes the day from two crew to exactly three."""
    booking = book_crew(
        api,
        built["day"]["id"],
        built["roster"][2]["id"],
        department_role=built["roles"][2],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    return confirm_booking(api, booking["id"])


def test_two_confirmed_crew_are_one_short_and_the_publish_is_refused(api):
    """The threshold is three, so a two-crew day publishes nothing.

    PRD §3.7: "The day must carry at least three crew bookings in `CONFIRMED` or
    `COMPLETED`, counted as `confirmed_crew_count`; fewer, including the empty case
    counted as zero, is refused with `ERR_MIN_CREW_NOT_MET`."

    PRD §3.5: "A day with no bookings at all has a confirmed crew count of 0 and is
    therefore `RESTRICTED`, never `OPEN`."

    Design: Difficulty/boundary_precision_check/call_sheet_crew_threshold_rejects_two_and_clears_at_exactly_three
    """
    built = _compliant_day_with_two_of_three_crew_confirmed(api)

    response = api.publish_call_sheet(built["day"]["id"], headers=COORDINATOR)

    validate_error(response, ApiErrorId.ERR_MIN_CREW_NOT_MET)
    assert_shoot_day_state(
        read_shoot_day(api, built["day"]["id"]),
        confirmed_crew_count=2,
        compliance_posture=POSTURE_RESTRICTED,
        call_sheet_status=CALL_SHEET_DRAFT,
    )


def test_the_third_confirmation_opens_the_posture_and_the_call_sheet_goes_out(api):
    """Exactly three confirmed crew clears the count, the posture and the publish.

    PRD §3.7: "When all of it passes, `call_sheet_status` advances `DRAFT →
    PUBLISHED` and `call_sheet_published_at` is stamped with the logical clock."

    PRD §3.5: "The posture is `BLOCKED` whenever either the permit test or the
    insurance test fails; it is `RESTRICTED` when both pass but fewer than three
    crew bookings are confirmed; and it is `OPEN` only when both pass and at least
    three are confirmed."

    Design: Difficulty/boundary_precision_check/call_sheet_crew_threshold_rejects_two_and_clears_at_exactly_three
    """
    built = _compliant_day_with_two_of_three_crew_confirmed(api)
    api.publish_call_sheet(built["day"]["id"], headers=COORDINATOR)

    third = _confirm_the_third_crew_member(api, built)

    assert_shoot_day_state(
        read_shoot_day(api, built["day"]["id"]),
        confirmed_crew_count=3,
        compliance_posture=POSTURE_OPEN,
    )
    day = get_success_data(
        api.publish_call_sheet(built["day"]["id"], headers=COORDINATOR), expected_status=200
    )
    assert_shoot_day_state(day, call_sheet_status=CALL_SHEET_PUBLISHED)
    assert_at_default_clock(day["call_sheet_published_at"])
    for booking in built["bookings"] + [third]:
        assert booking["cost_cents"] == 50000, booking["cost_cents"]
    assert_ledgers(read_project(api, built["project"]["id"]), committed_cents=250000)
