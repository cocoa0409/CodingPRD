"""State read across entities, interval conventions, and compensating reversals.

The first pair proves a transition is gated on another row's *state*. The second
pair pins the two opposite overlap conventions and their exact boundaries. The
third pair undoes a commitment and checks that nothing is left behind.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    BOOKING_RELEASED,
    CATEGORY_CREW,
    CATEGORY_LOCATION,
    CATEGORY_POST,
    CERT_ISSUED,
    CERT_SUBMITTED,
    CHANGE_ORDER_APPROVED,
    CHANGE_ORDER_PENDING_APPROVAL,
    CHANGE_ORDER_VOIDED,
    CLIENT_APPROVER,
    CLIENT_APPROVER_2,
    COORDINATOR,
    DECISION_APPROVE,
    DECISION_ISSUE,
    DECISION_REQUEST_CHANGES,
    DECISION_VOID,
    DELIVERABLE_CHANGES_REQUESTED,
    DELIVERABLE_IN_REVIEW,
    DEPT_CAMERA,
    DEPT_GRIP_ELECTRIC,
    POSTURE_BLOCKED,
    POSTURE_RESTRICTED,
    POST_SUPERVISOR,
    REVIEW_DRAFT,
    REVIEW_GATE_CHANGE_ORDER_PENDING,
    REVIEW_GATE_OPEN,
    REVIEW_SUBMITTED,
    SHOOT_DAY_CONFIRMED,
    SHOOT_DAY_PLANNED,
    TRIGGER_DELIVERABLE_ADDED_AFTER_SCOPE_LOCK,
    TRIGGER_REVISION_ROUND_EXCEEDED,
    ApiErrorId,
    add_budget_line,
    add_crew_member,
    add_deliverable,
    approve_budget,
    assert_cert_statuses,
    assert_change_order,
    assert_deliverable_state,
    assert_ledgers,
    assert_project_state,
    assert_shoot_day_state,
    assert_total_count,
    assert_version_axes,
    book_crew,
    confirm_booking,
    decide_cert,
    decide_change_order,
    file_permit,
    issued_coi,
    latest_change_order,
    lock_scope,
    ok_row,
    open_project,
    passed_cut,
    read_booking,
    read_cert,
    read_cut,
    read_deliverable,
    read_project,
    read_shoot_day,
    register_location,
    release_booking,
    review_cut,
    schedule_shoot_day,
    submit_cut,
)


def _day_whose_permit_is_filed_but_not_yet_issued(api):
    """Every window covers the day; the only defect is the permit's own status."""
    project = open_project(
        api,
        client_name="Ridgeline Bank",
        campaign_title="Open Doors",
        creative_brief_summary="Broadcast brand film on a permitted street exterior.",
        channel_scope=["BROADCAST"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
    )
    add_deliverable(
        api,
        project["id"],
        title="Open Doors 60",
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
        description="Street exterior fee",
        quantity=1,
        unit_rate_cents=100000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 100000)
    location = register_location(
        api,
        name="Third and Marion",
        address="Third Avenue at Marion, Seattle",
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
        reference_code="COI-77341",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-12-31T23:59:59Z",
        coverage_amount_cents=100000000,
        fee_cents=180000,
    )
    permit = file_permit(
        api,
        project["id"],
        day["id"],
        carrier_or_authority="Seattle Film Office",
        reference_code="PRM-66120",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-09-30T23:59:59Z",
        fee_cents=250000,
    )
    return project, day, permit


def test_a_covering_but_merely_submitted_permit_refuses_the_confirmation(api):
    """Existence and dates are not enough; the permit's status is what is read.

    PRD §3.5: "A filing lands at `status` `SUBMITTED` with `decision_note` and
    `decided_at` null, and while it sits there it satisfies nothing: a submitted
    permit leaves its shoot day's `compliance_posture` `BLOCKED`."

    PRD §3.5: "The permit test passes when there exists a certificate whose
    `shoot_day_id` is this day, whose `cert_type` is `FILM_PERMIT`, whose `status`
    is `ISSUED`, whose `effective_from` is at or before the day's `call_time`,
    whose `effective_to` is at or after the day's `wrap_time`, and whose
    `effective_to` is at or after the logical clock — that last clause being
    exactly the condition that its `effective_status` has not become `EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/shoot_day_confirm_gated_on_issued_permit_state_not_mere_existence
    """
    _project, day, permit = _day_whose_permit_is_filed_but_not_yet_issued(api)

    response = api.confirm_shoot_day(day["id"], headers=COORDINATOR)

    validate_error(response, ApiErrorId.ERR_PERMIT_WINDOW_MISMATCH)
    assert_cert_statuses(
        read_cert(api, permit["id"]), status=CERT_SUBMITTED, effective_status=CERT_SUBMITTED
    )
    assert_shoot_day_state(
        read_shoot_day(api, day["id"]),
        status=SHOOT_DAY_PLANNED,
        compliance_posture=POSTURE_BLOCKED,
    )


def test_issuing_that_same_permit_lets_the_identical_confirmation_through(api):
    """Nothing changes but the other row's status, and the transition opens.

    PRD §3.5: "Locking the day is the `ProductionCoordinator`'s move and advances
    the shoot day `PLANNED → CONFIRMED`. It requires the day to be `PLANNED`, the
    project to be `IN_PRODUCTION`, and the posture evaluated on the pre-transition
    state to be either `OPEN` or `RESTRICTED` — in other words the permit and
    insurance tests must both already pass, though the crew need not yet be
    assembled."

    PRD §3.5: "A day with no bookings at all has a confirmed crew count of 0 and is
    therefore `RESTRICTED`, never `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/shoot_day_confirm_gated_on_issued_permit_state_not_mere_existence
    """
    _project, day, permit = _day_whose_permit_is_filed_but_not_yet_issued(api)
    api.confirm_shoot_day(day["id"], headers=COORDINATOR)

    decide_cert(api, permit["id"], DECISION_ISSUE, decision_note="Street permit granted.")
    confirmed = get_success_data(
        api.confirm_shoot_day(day["id"], headers=COORDINATOR), expected_status=200
    )

    assert_shoot_day_state(
        confirmed,
        status=SHOOT_DAY_CONFIRMED,
        compliance_posture=POSTURE_RESTRICTED,
        confirmed_crew_count=0,
    )
    assert_cert_statuses(
        read_cert(api, permit["id"]), status=CERT_ISSUED, effective_status=CERT_ISSUED
    )


def _sibling_deliverable_raised_a_pending_change_order(api):
    """Deliverable A is spotless; deliverable B arrived late and froze the gate."""
    project = open_project(
        api,
        client_name="Northwind Freight",
        campaign_title="Long Haul",
        creative_brief_summary="OLV brand film plus a late-added social cutdown.",
        channel_scope=["OLV", "SOCIAL"],
        usage_term_months=24,
        contracted_revision_rounds=2,
        budget_ceiling_cents=50000000,
    )
    deliverable_a = add_deliverable(
        api,
        project["id"],
        title="Long Haul 90",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=90,
        caption_requirement="NONE",
        usage_rights_months=24,
        air_date="2026-12-01T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_POST,
        description="Offline and online edit",
        quantity=1,
        unit_rate_cents=2000000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 2000000)
    cut_a1 = passed_cut(
        api,
        deliverable_a["id"],
        cut_label="Long Haul 90 v1",
        aspect_ratio="16:9",
        duration_seconds=90,
        has_captions=False,
        caption_format="NONE",
        file_size_gb=12.4,
    )
    deliverable_b = add_deliverable(
        api,
        project["id"],
        title="Long Haul 15 social",
        channel="SOCIAL",
        aspect_ratio="9:16",
        target_duration_seconds=15,
        caption_requirement="BURNED_IN_SUBTITLES",
        usage_rights_months=24,
        air_date="2026-12-01T00:00:00Z",
    )
    change_order = latest_change_order(api, deliverable_b["id"])
    return project, deliverable_a, cut_a1, change_order


def test_a_siblings_pending_order_freezes_a_submit_that_breaks_no_rule_of_its_own(api):
    """The freeze is project-wide, and it outranks nothing on the cut itself.

    PRD §3.8: "Hop three, caused by hop two: the new `PENDING_APPROVAL` change
    order enters the provisional inclusion set, so the project's
    `provisional_cost_cents` increases by that change order's `amount_cents`, and
    the project's `review_gate` flips `OPEN → CHANGE_ORDER_PENDING`, which blocks
    every further cut submission across the *whole* project, not merely on the
    deliverable that triggered it."

    PRD §3.9: "`DELIVERABLE_ADDED_AFTER_SCOPE_LOCK` is raised when a deliverable is
    registered while the project's `status` is anything other than `DRAFT`, and it
    grants `additional_rounds_granted` of 0 — the client is buying a new
    deliverable, not another lap of an existing review."

    Design: Difficulty/cross_entity_state_dependency/version_submit_gated_on_sibling_deliverables_pending_change_order
    """
    project, deliverable_a, cut_a1, change_order = _sibling_deliverable_raised_a_pending_change_order(api)

    response = api.submit_version(cut_a1["id"], headers=POST_SUPERVISOR)

    validate_error(response, ApiErrorId.ERR_CHANGE_ORDER_PENDING)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_REVISION_ROUNDS_EXHAUSTED.value
    assert_deliverable_state(
        read_deliverable(api, deliverable_a["id"]),
        consumed_review_rounds=0,
        round_entitlement=2,
    )
    assert_change_order(
        change_order,
        trigger_reason=TRIGGER_DELIVERABLE_ADDED_AFTER_SCOPE_LOCK,
        labor_cents=620000,
        rush_pct=0.00,
        rush_cents=0,
        subtotal_cents=620000,
        producer_fee_pct=0.15,
        producer_fee_cents=93000,
        amount_cents=713000,
        status=CHANGE_ORDER_PENDING_APPROVAL,
    )
    assert change_order["additional_rounds_granted"] == 0
    assert_project_state(
        read_project(api, project["id"]),
        review_gate=REVIEW_GATE_CHANGE_ORDER_PENDING,
    )


def test_approving_the_siblings_order_reopens_the_gate_for_the_other_deliverable(api):
    """Clearing the sibling's order is the only thing the blocked cut needed.

    PRD §3.9: "The project's `review_gate` returns to `OPEN` once no
    `PENDING_APPROVAL` change order remains anywhere on the project, which is what
    unblocks cut submission."

    PRD §3.9: "The project's `committed_cost_cents` increases by `amount_cents`,
    because `APPROVED` enters the committed inclusion set, while
    `provisional_cost_cents` is unchanged — the row was already inside the
    provisional set as `PENDING_APPROVAL`."

    Design: Difficulty/cross_entity_state_dependency/version_submit_gated_on_sibling_deliverables_pending_change_order
    """
    project, deliverable_a, cut_a1, change_order = _sibling_deliverable_raised_a_pending_change_order(api)
    api.submit_version(cut_a1["id"], headers=POST_SUPERVISOR)

    decided = ok_row(
        api.change_order_decision(
            change_order["id"],
            {
                "decision": DECISION_APPROVE,
                "decision_note": "Client accepts the social cutdown fee.",
            },
            headers=CLIENT_APPROVER,
        )
    )

    assert decided["status"] == CHANGE_ORDER_APPROVED, decided["status"]
    assert_project_state(read_project(api, project["id"]), review_gate=REVIEW_GATE_OPEN)
    submitted = get_success_data(
        api.submit_version(cut_a1["id"], headers=POST_SUPERVISOR), expected_status=200
    )
    assert_version_axes(submitted, review_status=REVIEW_SUBMITTED, round_index=1)
    assert_deliverable_state(
        read_deliverable(api, deliverable_a["id"]), status=DELIVERABLE_IN_REVIEW
    )
    assert_ledgers(
        read_project(api, project["id"]),
        provisional_cents=2713000,
        committed_cents=2713000,
    )


def _four_days_and_one_operator_held_on_the_first(api):
    """Three stages so capacity never interferes, and one HELD 06:00-16:00 booking."""
    project = open_project(
        api,
        client_name="Cedar Mills",
        campaign_title="Two Days",
        creative_brief_summary="Two-day OLV brand film on a three-stage lot.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
    )
    add_deliverable(
        api,
        project["id"],
        title="Two Days 60",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=60,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_CREW,
        description="Camera department",
        quantity=1,
        unit_rate_cents=100000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    location = register_location(
        api,
        name="Northlight Lot",
        address="400 Foundry Row, Portland",
        stage_count=3,
        daily_fee_cents=90000,
        insurance_minimum_cents=50000000,
        permit_authority="Portland Film Office",
    )
    windows = {
        "a": ("2026-09-10T06:00:00Z", "2026-09-10T16:00:00Z"),
        "b": ("2026-09-10T16:00:00Z", "2026-09-11T02:00:00Z"),
        "c": ("2026-09-11T00:30:00Z", "2026-09-11T10:30:00Z"),
        "d": ("2026-09-11T02:00:00Z", "2026-09-11T12:00:00Z"),
    }
    days = {
        key: schedule_shoot_day(
            api, project["id"], location["id"], call_time=call, wrap_time=wrap
        )
        for key, (call, wrap) in windows.items()
    }
    crew = add_crew_member(
        api,
        full_name="Ivo Marek",
        department=DEPT_CAMERA,
        hourly_rate_cents=5000,
        min_turnaround_hours=10,
    )
    first = book_crew(
        api,
        days["a"]["id"],
        crew["id"],
        department_role="Operator",
        call_time=windows["a"][0],
        wrap_time=windows["a"][1],
    )
    return {
        "project": project,
        "days": days,
        "windows": windows,
        "crew": crew,
        "first_booking": first,
    }


def _book_the_operator(api, built, key):
    """Try the operator on one of the four days over that day's whole window."""
    call, wrap = built["windows"][key]
    return api.create_crew_booking(
        {
            "shoot_day_id": built["days"][key]["id"],
            "crew_member_id": built["crew"]["id"],
            "department_role": "Operator",
            "call_time": call,
            "wrap_time": wrap,
        },
        headers=COORDINATOR,
    )


def test_a_booking_starting_at_the_exact_wrap_instant_of_another_collides(api):
    """The crew interval is closed, so touching at 16:00Z is an intersection.

    PRD §3.6: "First, the person may hold no other `HELD` or `CONFIRMED` booking
    whose interval intersects the requested one, and here the interval is treated
    as **closed** — both endpoints included — so a booking that starts at the exact
    instant another ends counts as an intersection and is refused with
    `ERR_CREW_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/crew_closed_interval_touch_and_ten_hour_turnaround_boundary
    """
    built = _four_days_and_one_operator_held_on_the_first(api)

    response = _book_the_operator(api, built, "b")

    validate_error(response, ApiErrorId.ERR_CREW_DOUBLE_BOOKED)
    assert_total_count(
        api.list_crew_bookings(headers=COORDINATOR, crew_member_id=built["crew"]["id"]), 1
    )


def test_a_rest_gap_of_eight_and_a_half_hours_fails_and_exactly_ten_passes(api):
    """The turnaround minimum is inclusive, so equality is accepted.

    PRD §3.6: "Second, for every other `HELD` or `CONFIRMED` booking of the same
    person that does not overlap, the rest gap between the two intervals — the
    requested call time minus the other booking's wrap time, or the other booking's
    call time minus the requested wrap time, whichever of the two is the positive
    quantity — must be at least that person's `min_turnaround_hours`."

    PRD §3.6: "A gap of exactly the minimum passes; a gap of 8.5 hours against a
    10-hour minimum is refused with `ERR_CREW_TURNAROUND_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/crew_closed_interval_touch_and_ten_hour_turnaround_boundary
    """
    built = _four_days_and_one_operator_held_on_the_first(api)

    validate_error(
        _book_the_operator(api, built, "c"), ApiErrorId.ERR_CREW_TURNAROUND_VIOLATION
    )
    accepted = get_success_data(_book_the_operator(api, built, "d"), expected_status=201)

    assert accepted["cost_cents"] == 50000, accepted["cost_cents"]
    rows = assert_total_count(
        api.list_crew_bookings(headers=COORDINATOR, crew_member_id=built["crew"]["id"]), 2
    )
    assert {row["id"] for row in rows} == {built["first_booking"]["id"], accepted["id"]}
    assert_ledgers(
        read_project(api, built["project"]["id"]),
        provisional_cents=200000,
        committed_cents=0,
    )


def _two_stage_venue_with_both_stages_occupied(api):
    """Two identical 06:00-16:00 days on a two-stage venue, so it is full."""
    project = open_project(
        api,
        client_name="Loomis Dairy",
        campaign_title="Morning Route",
        creative_brief_summary="Two-unit OLV brand film shot on a two-stage location.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
    )
    add_deliverable(
        api,
        project["id"],
        title="Morning Route 60",
        channel="OLV",
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
        description="Two-stage hold",
        quantity=1,
        unit_rate_cents=100000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    location = register_location(
        api,
        name="Dairy Barn Stages",
        address="9 Creamery Lane, Salem",
        stage_count=2,
        daily_fee_cents=90000,
        insurance_minimum_cents=50000000,
        permit_authority="Salem Film Office",
    )
    occupied = [
        schedule_shoot_day(
            api,
            project["id"],
            location["id"],
            call_time="2026-09-10T06:00:00Z",
            wrap_time="2026-09-10T16:00:00Z",
        )
        for _ in range(2)
    ]
    return project, location, occupied


def _schedule(api, project, location, call, wrap):
    """One raw shoot-day creation, so the capacity verdict can be read off it."""
    return api.create_shoot_day(
        {
            "project_id": project["id"],
            "location_id": location["id"],
            "shoot_date": call[:10],
            "call_time": call,
            "wrap_time": wrap,
        },
        headers=COORDINATOR,
    )


def test_a_third_day_overlapping_both_stages_exceeds_the_venue_capacity(api):
    """The count is of concurrently overlapping days, not of days per date.

    PRD §3.4: "Before the day is written, the server counts the existing `PLANNED`
    or `CONFIRMED` shoot days at the same location whose occupation interval
    overlaps the requested one, where the interval is treated as **half-open** — it
    includes its call time and excludes its wrap time."

    PRD §3.4: "That count must be strictly less than the location's `stage_count`;
    if it is not, the request is refused with `ERR_LOCATION_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/location_stage_capacity_aggregate_with_touching_days_permitted
    """
    project, location, _occupied = _two_stage_venue_with_both_stages_occupied(api)

    response = _schedule(
        api, project, location, "2026-09-10T12:00:00Z", "2026-09-10T20:00:00Z"
    )

    validate_error(response, ApiErrorId.ERR_LOCATION_CAPACITY_EXCEEDED)
    assert_total_count(api.list_shoot_days(headers=COORDINATOR, location_id=location["id"]), 2)


def test_a_day_called_at_the_wrap_instant_of_the_others_takes_no_second_stage(api):
    """Half-open intervals that merely touch do not overlap, so the day fits.

    PRD §3.4: "Because the interval is half-open, back-to-back days that merely
    touch at an endpoint — one wrapping exactly when the next is called — do not
    overlap and do not consume a second stage."

    PRD §3.4: "`scheduled_shoot_day_count` is the number of shoot days at the
    location whose `status` is `PLANNED` or `CONFIRMED`."

    Design: Difficulty/resource_temporal_overlap/location_stage_capacity_aggregate_with_touching_days_permitted
    """
    project, location, occupied = _two_stage_venue_with_both_stages_occupied(api)
    _schedule(api, project, location, "2026-09-10T12:00:00Z", "2026-09-10T20:00:00Z")

    accepted = get_success_data(
        _schedule(api, project, location, "2026-09-10T16:00:00Z", "2026-09-11T02:00:00Z"),
        expected_status=201,
    )

    assert accepted["status"] == SHOOT_DAY_PLANNED, accepted["status"]
    refreshed = ok_row(api.get_location(location["id"], headers=COORDINATOR))
    assert refreshed["scheduled_shoot_day_count"] == 3, refreshed["scheduled_shoot_day_count"]
    rows = assert_total_count(
        api.list_shoot_days(headers=COORDINATOR, location_id=location["id"]), 3
    )
    assert {row["id"] for row in rows} == {
        occupied[0]["id"], occupied[1]["id"], accepted["id"],
    }
    assert all(row["status"] == SHOOT_DAY_PLANNED for row in rows), rows


def _confirmed_booking_over_an_awkward_23887_cent_baseline(api):
    """A 50,000-cent booking committed on top of a marked-up 23,887-cent line."""
    project = open_project(
        api,
        client_name="Alder & Finch",
        campaign_title="Small Batch",
        creative_brief_summary="One-day OLV brand film with a tiny committed budget.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=100000,
    )
    add_deliverable(
        api,
        project["id"],
        title="Small Batch 45",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=45,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_CREW,
        description="Grip day rate, two units",
        quantity=2,
        unit_rate_cents=11110,
        markup_pct=0.075,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 23887)
    location = register_location(
        api,
        name="Alder Street Kitchen",
        address="22 Alder Street, Eugene",
        stage_count=1,
        daily_fee_cents=40000,
        insurance_minimum_cents=50000000,
        permit_authority="Eugene Film Office",
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
        hourly_rate_cents=5000,
        min_turnaround_hours=10,
    )
    booking = book_crew(
        api,
        day["id"],
        crew["id"],
        department_role="Key Grip",
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    booking = confirm_booking(api, booking["id"])
    return project, day, booking


def test_releasing_the_booking_credits_back_exactly_what_confirming_it_debited(api):
    """Both variants return to 23,887 with no drift off the 0.075 markup.

    PRD §3.6: "The booking's cost is frozen at creation and reused by every later
    ledger movement of that booking, so releasing it later credits back exactly what
    confirming it debited."

    PRD §3.6: "Because `RELEASED` sits outside both inclusion sets, the project's
    `provisional_cost_cents` drops by the booking's `cost_cents`; and when the
    booking was `CONFIRMED`, the project's `committed_cost_cents` drops by exactly
    the amount that confirmation credited, leaving no drift."

    Design: Difficulty/compensating_invariant/crew_booking_release_reverses_the_exact_committed_credit
    """
    project, _day, booking = _confirmed_booking_over_an_awkward_23887_cent_baseline(api)
    assert_ledgers(
        read_project(api, project["id"]),
        provisional_cents=73887,
        committed_cents=73887,
        approved_cents=23887,
        variance_cents=50000,
    )

    released = release_booking(
        api, booking["id"], release_reason="Client cut the grip package after the tech scout."
    )

    assert released["status"] == BOOKING_RELEASED, released["status"]
    assert released["cost_cents"] == 50000, released["cost_cents"]
    assert_ledgers(
        read_project(api, project["id"]),
        provisional_cents=23887,
        committed_cents=23887,
        approved_cents=23887,
        variance_cents=0,
    )


def test_the_released_booking_is_still_a_row_and_the_day_count_unwinds(api):
    """The compensation is a status change, not a deletion, and the day feels it.

    PRD §3.6: "Either way `budget_variance_cents`, the day's `confirmed_crew_count`,
    its `compliance_posture` and its `day_cost_cents` are recomputed, and the
    vacated interval stops occupying the person, so a later booking may reuse it."

    PRD §3.5: "The posture is `BLOCKED` whenever either the permit test or the
    insurance test fails; it is `RESTRICTED` when both pass but fewer than three
    crew bookings are confirmed; and it is `OPEN` only when both pass and at least
    three are confirmed."

    Design: Difficulty/compensating_invariant/crew_booking_release_reverses_the_exact_committed_credit
    """
    _project, day, booking = _confirmed_booking_over_an_awkward_23887_cent_baseline(api)

    release_booking(
        api, booking["id"], release_reason="Client cut the grip package after the tech scout."
    )

    assert_shoot_day_state(
        read_shoot_day(api, day["id"]),
        confirmed_crew_count=0,
        compliance_posture=POSTURE_BLOCKED,
    )
    rows = assert_total_count(
        api.list_crew_bookings(headers=COORDINATOR, shoot_day_id=day["id"]), 1
    )
    assert rows[0]["id"] == booking["id"], rows
    assert read_booking(api, booking["id"])["status"] == BOOKING_RELEASED


def _approved_extra_round_on_a_single_round_contract(api):
    """One contracted round spent, then bought back by an APPROVED change order."""
    project = open_project(
        api,
        client_name="Ferro Steel",
        campaign_title="One Pass",
        creative_brief_summary="OLV brand film contracted with a single client review round.",
        channel_scope=["OLV"],
        usage_term_months=12,
        contracted_revision_rounds=1,
        budget_ceiling_cents=50000000,
    )
    deliverable = add_deliverable(
        api,
        project["id"],
        title="One Pass 60",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=60,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_POST,
        description="Offline and online edit",
        quantity=1,
        unit_rate_cents=2000000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 2000000)
    cut = passed_cut(
        api,
        deliverable["id"],
        cut_label="One Pass v1",
        aspect_ratio="16:9",
        duration_seconds=60,
        has_captions=False,
        caption_format="NONE",
        file_size_gb=9.2,
    )
    cut = submit_cut(api, cut["id"])
    cut = review_cut(
        api,
        cut["id"],
        DECISION_REQUEST_CHANGES,
        review_note="Recut the opening and drop the voiceover.",
    )
    change_order = latest_change_order(api, deliverable["id"])
    change_order = ok_row(
        api.change_order_decision(
            change_order["id"],
            {"decision": DECISION_APPROVE, "decision_note": "Client buys the extra round."},
            headers=CLIENT_APPROVER_2,
        )
    )
    return project, deliverable, cut, change_order


def test_voiding_the_order_reverses_both_the_money_and_the_granted_round(api):
    """The void is the exact compensating pair of the approval, on both quantities.

    PRD §3.9: "Voiding advances `APPROVED → VOIDED` and is the exact compensating
    pair for approval, which is what keeps the round-entitlement invariant honest."

    PRD §3.9: "The deliverable's `granted_extra_rounds` decreases by
    `additional_rounds_granted` and its `round_entitlement` falls by the same
    amount; caused by that fall, the project's `round_entitlement_balance` decreases
    by the same amount, restoring the value it held before the approval. Both
    `committed_cost_cents` and `provisional_cost_cents` are debited by
    `amount_cents`, and `budget_variance_cents` is recomputed."

    Design: Difficulty/compensating_invariant/change_order_void_restores_entitlement_and_reblocks_submission
    """
    project, deliverable, _cut, change_order = _approved_extra_round_on_a_single_round_contract(api)
    assert_change_order(
        change_order, amount_cents=566400, status=CHANGE_ORDER_APPROVED,
        trigger_reason=TRIGGER_REVISION_ROUND_EXCEEDED,
    )
    assert change_order["additional_rounds_granted"] == 1
    assert_ledgers(
        read_project(api, project["id"]), provisional_cents=2566400, committed_cents=2566400
    )
    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]),
        granted_extra_rounds=1,
        round_entitlement=2,
        consumed_review_rounds=1,
    )
    assert_project_state(read_project(api, project["id"]), round_entitlement_balance=1)

    voided = decide_change_order(
        api,
        change_order["id"],
        DECISION_VOID,
        decision_note="Client withdrew the extra round before work started.",
    )

    assert voided["status"] == CHANGE_ORDER_VOIDED, voided["status"]
    refreshed = read_project(api, project["id"])
    assert_ledgers(
        refreshed,
        provisional_cents=2000000,
        committed_cents=2000000,
        approved_cents=2000000,
        variance_cents=0,
    )
    assert_project_state(refreshed, round_entitlement_balance=0)
    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]),
        granted_extra_rounds=0,
        round_entitlement=1,
    )


def test_the_restored_entitlement_blocks_the_next_submission_all_over_again(api):
    """The proof the count really came back is that the next submit is refused.

    PRD §2.12: "Priority 38: **Revision-round entitlement**
    (`ERR_REVISION_ROUNDS_EXHAUSTED`, HTTP 409), checked on cut submission."

    PRD §3.8: "That second edge is what closes the review cycle `PENDING →
    IN_REVIEW → CHANGES_REQUESTED → IN_REVIEW`, and it carries the same entitlement
    precondition — the deliverable's `consumed_review_rounds` must still be strictly
    below its `round_entitlement` — so the number of laps the loop can run is
    bounded by the entitlement, which only an approved change order can raise."

    Design: Difficulty/compensating_invariant/change_order_void_restores_entitlement_and_reblocks_submission
    """
    _project, deliverable, cut, change_order = _approved_extra_round_on_a_single_round_contract(api)
    decide_change_order(
        api,
        change_order["id"],
        DECISION_VOID,
        decision_note="Client withdrew the extra round before work started.",
    )

    second = passed_cut(
        api,
        deliverable["id"],
        cut_label="One Pass v2",
        aspect_ratio="16:9",
        duration_seconds=60,
        has_captions=False,
        caption_format="NONE",
        file_size_gb=9.4,
        supersedes_version_id=cut["id"],
    )
    response = api.submit_version(second["id"], headers=POST_SUPERVISOR)

    validate_error(response, ApiErrorId.ERR_REVISION_ROUNDS_EXHAUSTED)
    assert_version_axes(read_cut(api, second["id"]), review_status=REVIEW_DRAFT)
    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]), status=DELIVERABLE_CHANGES_REQUESTED
    )
