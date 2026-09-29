"""The cyclic review machine, the two-axis cut row, and the two long cascades.

Each test here drives a graph whose shape is not a straight line — a loop that
re-enters a state it has already visited, one row advancing on two independent
axes, or one request whose consequences arrive several hops away from it.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    BOOKING_CONFIRMED,
    BOOKING_RELEASED,
    CATEGORY_POST,
    CHANGE_ORDER_PENDING_APPROVAL,
    DECISION_REQUEST_CHANGES,
    DELIVERABLE_CHANGES_REQUESTED,
    DELIVERABLE_IN_REVIEW,
    DELIVERABLE_PENDING,
    PROJECT_IN_POST,
    QC_ASPECT_RATIO_MISMATCH,
    RESERVATION_RELEASED,
    RESERVATION_RESERVED,
    REVIEW_CHANGES_REQUESTED,
    REVIEW_GATE_CHANGE_ORDER_PENDING,
    REVIEW_GATE_OPEN,
    REVIEW_DRAFT,
    REVIEW_SUBMITTED,
    REVIEW_SUPERSEDED,
    SHOOT_DAY_CANCELLED,
    TECHNICAL_PENDING_QC,
    TECHNICAL_QC_FAILED,
    TRIGGER_REVISION_ROUND_EXCEEDED,
    USER_CLIENT_1,
    ApiErrorId,
    COORDINATOR,
    POST_SUPERVISOR,
    add_budget_line,
    add_crew_member,
    add_deliverable,
    approve_budget,
    assert_change_order,
    assert_deliverable_state,
    assert_ledgers,
    assert_project_state,
    assert_reservation,
    assert_shoot_day_state,
    assert_total_count,
    assert_version_axes,
    book_crew,
    cancel_shoot_day,
    confirm_booking,
    latest_change_order,
    list_change_orders,
    lock_scope,
    open_project,
    passed_cut,
    read_booking,
    read_cut,
    read_deliverable,
    read_project,
    read_shoot_day,
    record_qc,
    register_location,
    reserve_equipment,
    review_cut,
    schedule_shoot_day,
    submit_cut,
    submitted_cut,
    upload_next_cut,
)


def _two_round_project_after_the_first_lap(api):
    """A deliverable back at CHANGES_REQUESTED with one of two rounds spent."""
    project = open_project(
        api,
        client_name="Lumen Energy",
        campaign_title="Grid Stories",
        creative_brief_summary="OLV brand film with two contracted revision rounds.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
        contracted_revision_rounds=2,
    )
    deliverable = add_deliverable(
        api,
        project["id"],
        title="Grid Stories 60",
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
        description="Post production package",
        quantity=2,
        unit_rate_cents=1000000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 2000000)
    first_cut = submitted_cut(api, deliverable["id"], cut_label="v1 rough", file_size_gb=11.0)
    first_cut = review_cut(
        api, first_cut["id"], DECISION_REQUEST_CHANGES, review_note="Recut the middle act."
    )
    return project, deliverable, first_cut


def test_a_later_cut_takes_the_deliverable_back_into_in_review_as_round_two(api):
    """The loop re-enters IN_REVIEW, and the new cut is stamped as the second lap.

    PRD §3.8: "Submission stamps `submitted_by_user_id` with the acting
    `X-User-ID` and `submitted_at` with the logical clock, then bubbles up: the
    deliverable advances `PENDING → IN_REVIEW` on a first cut, or
    `CHANGES_REQUESTED → IN_REVIEW` on a later one, incrementing the deliverable's
    `version` and refreshing its `updated_at`."

    PRD §3.8: "Its `round_index` is set to one more than the parent deliverable's
    `consumed_review_rounds` at that moment, which is the round this cut is
    competing for."

    Design: Difficulty/non_linear_state_machine/deliverable_review_cycle_reenters_in_review_on_a_later_cut
    """
    _project, deliverable, first_cut = _two_round_project_after_the_first_lap(api)
    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]),
        status=DELIVERABLE_CHANGES_REQUESTED,
        consumed_review_rounds=1,
        round_entitlement=2,
    )

    second_cut = passed_cut(
        api,
        deliverable["id"],
        cut_label="v2 recut",
        file_size_gb=11.4,
        supersedes_version_id=first_cut["id"],
    )
    second_cut = submit_cut(api, second_cut["id"])

    assert_version_axes(second_cut, review_status=REVIEW_SUBMITTED, round_index=2)
    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]),
        status=DELIVERABLE_IN_REVIEW,
        version_count=2,
        consumed_review_rounds=1,
        round_entitlement=2,
    )
    assert_version_axes(read_cut(api, first_cut["id"]), review_status=REVIEW_SUPERSEDED)


def test_the_second_lap_spends_no_new_round_so_the_gate_stays_open(api):
    """One consumed round out of two leaves the entitlement unspent, and unpriced.

    PRD §3.8: "That second edge is what closes the review cycle `PENDING →
    IN_REVIEW → CHANGES_REQUESTED → IN_REVIEW`, and it carries the same
    entitlement precondition — the deliverable's `consumed_review_rounds` must
    still be strictly below its `round_entitlement` — so the number of laps the
    loop can run is bounded by the entitlement, which only an approved change
    order can raise."

    PRD §3.8: "Hop two, caused by hop one rather than directly by the request: if
    the incremented `consumed_review_rounds` has reached or passed the
    deliverable's `round_entitlement` — the entitlement is now spent — a change
    order row is created against that deliverable with `trigger_reason`
    `REVISION_ROUND_EXCEEDED`, `additional_rounds_granted` 1, `status`
    `PENDING_APPROVAL`, `requested_by_user_id` set to the reviewing `X-User-ID`,
    and every money column priced as described in §3.9."

    Design: Difficulty/non_linear_state_machine/deliverable_review_cycle_reenters_in_review_on_a_later_cut
    """
    project, deliverable, first_cut = _two_round_project_after_the_first_lap(api)

    second_cut = passed_cut(
        api,
        deliverable["id"],
        cut_label="v2 recut",
        file_size_gb=11.4,
        supersedes_version_id=first_cut["id"],
    )
    submit_cut(api, second_cut["id"])

    assert_project_state(
        read_project(api, project["id"]),
        review_gate=REVIEW_GATE_OPEN,
        round_entitlement_balance=1,
    )
    assert_total_count(list_change_orders(api, deliverable["id"]), 0)


def _vertical_cut_of_a_broadcast_deliverable(api):
    """A cut delivered 9:16 against a 16:9 spec, correct on every other axis."""
    project = open_project(
        api,
        client_name="Kestrel Bank",
        campaign_title="Open Doors",
        creative_brief_summary="Social-first brand film with a broadcast-ratio hero cut.",
        channel_scope=["SOCIAL"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
        contracted_revision_rounds=2,
    )
    deliverable = add_deliverable(
        api,
        project["id"],
        title="Open Doors Hero",
        channel="SOCIAL",
        aspect_ratio="16:9",
        target_duration_seconds=60,
        caption_requirement="CLOSED_SRT",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_POST,
        description="Post production package",
        quantity=2,
        unit_rate_cents=1000000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 2000000)
    cut = upload_next_cut(
        api,
        deliverable["id"],
        cut_label="v1 vertical by mistake",
        aspect_ratio="9:16",
        duration_seconds=60,
        has_captions=True,
        caption_format="CLOSED_SRT",
        file_size_gb=9.2,
    )
    return project, deliverable, cut


def test_a_failed_qc_moves_only_the_technical_axis_and_leaves_review_at_draft(api):
    """The QC verdict lands on one axis of the row and never touches the other.

    PRD §3.8: "Every cut carries two independent state axes on the same row, and
    this separation matters: `review_status` tracks the client conversation
    (`DRAFT`, `SUBMITTED`, `APPROVED`, `CHANGES_REQUESTED`, `SUPERSEDED`) while
    `technical_status` tracks the technical conversation (`PENDING_QC`,
    `QC_PASSED`, `QC_FAILED`). Neither axis's transitions touch the other's value."

    PRD §3.8: "`ASPECT_RATIO_MISMATCH` is recorded when the cut's `aspect_ratio`
    differs from the deliverable's `aspect_ratio`."

    Design: Difficulty/non_linear_state_machine/version_review_and_technical_axes_advance_independently
    """
    _project, _deliverable, cut = _vertical_cut_of_a_broadcast_deliverable(api)
    assert_version_axes(
        cut,
        review_status=REVIEW_DRAFT,
        technical_status=TECHNICAL_PENDING_QC,
        qc_failure_reasons=[],
    )

    judged = record_qc(api, cut["id"])

    assert_version_axes(
        judged,
        review_status=REVIEW_DRAFT,
        technical_status=TECHNICAL_QC_FAILED,
        qc_failure_reasons=[QC_ASPECT_RATIO_MISMATCH],
    )


def test_the_cross_axis_guard_refuses_the_submit_of_a_qc_failed_cut(api):
    """A cut whose review axis is ready is still blocked by its technical axis.

    PRD §3.8: "Six conditions must hold: the cut's `review_status` is `DRAFT`; its
    `technical_status` is `QC_PASSED` — the cross-axis guard, with both
    `PENDING_QC` and `QC_FAILED` refused as `ERR_VERSION_QC_NOT_PASSED`; the
    parent deliverable is `PENDING` or `CHANGES_REQUESTED`; the project is
    `IN_PRODUCTION` or `IN_POST`; the project's `review_gate` is `OPEN`, or the
    submission is frozen with `ERR_CHANGE_ORDER_PENDING`; and the deliverable's
    `consumed_review_rounds` is strictly less than its `round_entitlement`, or the
    submission is refused with `ERR_REVISION_ROUNDS_EXHAUSTED`."

    PRD §3.8: "Because the `review_status` axis is untouched, a `QC_FAILED` cut
    simply can never be submitted; the only way forward is a new cut."

    Design: Difficulty/non_linear_state_machine/version_review_and_technical_axes_advance_independently
    """
    _project, deliverable, cut = _vertical_cut_of_a_broadcast_deliverable(api)
    record_qc(api, cut["id"])

    response = api.submit_version(cut["id"], headers=POST_SUPERVISOR)

    validate_error(response, ApiErrorId.ERR_VERSION_QC_NOT_PASSED)
    assert_version_axes(
        read_cut(api, cut["id"]),
        review_status=REVIEW_DRAFT,
        technical_status=TECHNICAL_QC_FAILED,
    )
    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]),
        status=DELIVERABLE_PENDING,
        consumed_review_rounds=0,
    )


def _request_changes_on_a_rush_deliverable(api):
    """One REQUEST_CHANGES on a deliverable airing four days out, entitlement 1."""
    project = open_project(
        api,
        client_name="Vantage Retail",
        campaign_title="Back To School Sprint",
        creative_brief_summary="Rush OLV brand film with a single contracted revision round.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
        contracted_revision_rounds=1,
    )
    deliverable = add_deliverable(
        api,
        project["id"],
        title="Sprint 30",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=30,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-08-05T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_POST,
        description="Post production package",
        quantity=2,
        unit_rate_cents=1000000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 2000000)
    cut = submitted_cut(
        api,
        deliverable["id"],
        cut_label="v1 rough",
        duration_seconds=30,
        file_size_gb=6.4,
    )
    decided = review_cut(
        api,
        cut["id"],
        DECISION_REQUEST_CHANGES,
        review_note="Lose the voiceover in the last five seconds.",
    )
    return project, deliverable, decided


def test_one_request_for_changes_prices_a_690000_cent_change_order_nobody_asked_for(api):
    """Hops zero to two: the cut, the deliverable, and a rush-priced order.

    PRD §3.8: "A request for changes advances the cut `SUBMITTED →
    CHANGES_REQUESTED` and sets off a four-hop cascade that is the single most
    consequential chain in the system."

    PRD §3.8: "Hop one: the deliverable advances `IN_REVIEW → CHANGES_REQUESTED`
    and its `consumed_review_rounds` increases by one."

    PRD §3.9: "`rush_pct` is 0.25 when the day count is 7 or fewer, 0.15 when it
    is more than 7 and 14 or fewer, and 0.00 for anything further out."

    Design: Difficulty/transitive_cascade/request_changes_cascades_four_hops_to_budget_variance
    """
    _project, deliverable, decided = _request_changes_on_a_rush_deliverable(api)

    assert_version_axes(decided, review_status=REVIEW_CHANGES_REQUESTED)
    assert decided["reviewed_by_user_id"] == USER_CLIENT_1
    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]),
        status=DELIVERABLE_CHANGES_REQUESTED,
        consumed_review_rounds=1,
    )

    change_order = latest_change_order(api, deliverable["id"])
    assert_change_order(
        change_order,
        trigger_reason=TRIGGER_REVISION_ROUND_EXCEEDED,
        labor_cents=480000,
        rush_pct=0.25,
        rush_cents=120000,
        subtotal_cents=600000,
        producer_fee_pct=0.15,
        producer_fee_cents=90000,
        amount_cents=690000,
        status=CHANGE_ORDER_PENDING_APPROVAL,
    )
    assert change_order["additional_rounds_granted"] == 1
    assert change_order["requested_by_user_id"] == USER_CLIENT_1


def test_the_cascade_reaches_the_provisional_ledger_the_gate_and_the_variance(api):
    """Hops three and four, with the committed variant left exactly where it was.

    PRD §3.8: "Hop three, caused by hop two: the new `PENDING_APPROVAL` change
    order enters the provisional inclusion set, so the project's
    `provisional_cost_cents` increases by that change order's `amount_cents`, and
    the project's `review_gate` flips `OPEN → CHANGE_ORDER_PENDING`, which blocks
    every further cut submission across the *whole* project, not merely on the
    deliverable that triggered it."

    PRD §3.8: "Hop four, caused by hop three: `budget_variance_cents` is
    recomputed as `provisional_cost_cents` minus `approved_budget_cents`, and
    `round_entitlement_balance` is recomputed."

    Design: Difficulty/transitive_cascade/request_changes_cascades_four_hops_to_budget_variance
    """
    project, _deliverable, _decided = _request_changes_on_a_rush_deliverable(api)

    refreshed = read_project(api, project["id"])

    assert_ledgers(
        refreshed,
        provisional_cents=2690000,
        committed_cents=2000000,
        approved_cents=2000000,
        variance_cents=690000,
    )
    assert_project_state(
        refreshed,
        review_gate=REVIEW_GATE_CHANGE_ORDER_PENDING,
        round_entitlement_balance=0,
    )


def _only_reservation_of(api, shoot_day_id):
    """The day's single kit reservation, read back through the day's listing."""
    return assert_total_count(
        api.list_shoot_day_equipment_reservations(shoot_day_id, headers=COORDINATOR), 1
    )[0]


def _day_carrying_a_confirmed_booking_and_a_reservation(api):
    """One planned stage day with 170,000 cents of children on both ledgers."""
    project = open_project(
        api,
        client_name="Cascadia Outdoor",
        campaign_title="Trailhead",
        creative_brief_summary="Broadcast brand film captured on a single stage day.",
        channel_scope=["BROADCAST"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
    )
    add_deliverable(
        api,
        project["id"],
        title="Trailhead 60",
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
        category=CATEGORY_POST,
        description="Post production package",
        quantity=2,
        unit_rate_cents=1000000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 2000000)
    location = register_location(
        api,
        name="Cedar Barn",
        address="44 Ridge Road, Bend",
        stage_count=2,
        daily_fee_cents=400000,
        insurance_minimum_cents=100000000,
        permit_authority="Deschutes County Film",
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    crew = add_crew_member(
        api, full_name="Ivo Marek", department="CAMERA", hourly_rate_cents=5000,
        min_turnaround_hours=10,
    )
    booking = book_crew(
        api,
        day["id"],
        crew["id"],
        department_role="1st AC",
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    booking = confirm_booking(api, booking["id"])
    reservation = reserve_equipment(
        api,
        day["id"],
        vendor_name="Radiant Rentals",
        kit_label="Alexa 35 two-body package",
        unit_count=2,
        daily_rate_cents=30000,
        pickup_at="2026-09-09T12:00:00Z",
        return_at="2026-09-11T12:00:00Z",
    )
    return {
        "project": project,
        "day": day,
        "booking": booking,
        "reservation": reservation,
    }


def test_cancelling_the_day_releases_the_booking_and_the_kit_beneath_it(api):
    """Hops zero and one: the day terminates and both children follow it out.

    PRD §3.7: "The cascade runs in hops. Hop one: every crew booking of the day
    whose `status` is `HELD` or `CONFIRMED` moves to `RELEASED`."

    PRD §3.7: "In parallel, every equipment reservation of the day whose `status`
    is `RESERVED` moves `RESERVED → RELEASED`, each one debiting *both*
    `committed_cost_cents` and `provisional_cost_cents` by its `total_cost_cents`,
    because a reservation had been inside both sets."

    PRD §3.6: "`rental_days` is the span from pickup to return in hours divided by
    24 and rounded up to a whole day, with a floor of one day, so any partial day
    bills as a full day and a same-morning pickup and return still bills one."

    Design: Difficulty/transitive_cascade/shoot_day_cancel_cascades_releases_debits_and_bubbles_project
    """
    built = _day_carrying_a_confirmed_booking_and_a_reservation(api)
    assert_reservation(
        built["reservation"], rental_days=2, total_cost_cents=120000,
        status=RESERVATION_RESERVED,
    )
    assert built["booking"]["status"] == BOOKING_CONFIRMED
    assert_ledgers(
        read_project(api, built["project"]["id"]),
        provisional_cents=2170000,
        committed_cents=2170000,
        approved_cents=2000000,
        variance_cents=170000,
    )

    cancelled = cancel_shoot_day(
        api, built["day"]["id"],
        cancellation_reason="Client pushed the shoot window by three weeks.",
    )

    assert_shoot_day_state(cancelled, status=SHOOT_DAY_CANCELLED)
    assert read_booking(api, built["booking"]["id"])["status"] == BOOKING_RELEASED
    assert_reservation(_only_reservation_of(api, built["day"]["id"]), status=RESERVATION_RELEASED)


def test_the_cancellation_debits_both_ledgers_and_bubbles_the_project_into_post(api):
    """Hops two and three: 170,000 cents come back off and the project moves up.

    PRD §3.7: "Hop two, caused by hop one: each booking that left `CONFIRMED`
    debits the project's `committed_cost_cents` by its own `cost_cents`, while
    bookings released out of `HELD` debit the committed figure nothing; every
    released booking, from either state, leaves the provisional set, so
    `provisional_cost_cents` drops by its `cost_cents`."

    PRD §3.7: "And exactly as with wrap, when no shoot day of the project remains
    in `PLANNED` or `CONFIRMED` and at least one exists, the project bubbles
    `IN_PRODUCTION → IN_POST`."

    PRD §3.6: "A day's `day_cost_cents` is a display-only total, recomputed on
    every shoot-day read and after any booking or reservation status change on
    that day: it is the venue's `daily_fee_cents` plus the `cost_cents` of every
    crew booking on the day whose `status` is `CONFIRMED` or `COMPLETED` plus the
    `total_cost_cents` of every reservation on the day whose `status` is
    `RESERVED` or `RETURNED`."

    Design: Difficulty/transitive_cascade/shoot_day_cancel_cascades_releases_debits_and_bubbles_project
    """
    built = _day_carrying_a_confirmed_booking_and_a_reservation(api)

    cancel_shoot_day(
        api, built["day"]["id"],
        cancellation_reason="Client pushed the shoot window by three weeks.",
    )

    refreshed = read_project(api, built["project"]["id"])
    assert_ledgers(
        refreshed,
        provisional_cents=2000000,
        committed_cents=2000000,
        approved_cents=2000000,
        variance_cents=0,
    )
    assert_project_state(refreshed, status=PROJECT_IN_POST)
    assert_shoot_day_state(
        read_shoot_day(api, built["day"]["id"]),
        status=SHOOT_DAY_CANCELLED,
        confirmed_crew_count=0,
        day_cost_cents=400000,
    )
