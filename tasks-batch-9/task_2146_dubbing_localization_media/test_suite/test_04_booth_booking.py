"""Booking the booth: the two interval geometries, the daily ceilings, the
waitlist and the conservation of booth minutes."""

from test_helpers import (
    CASTING,
    MIXER,
    PC,
    ApiErrorId,
    UNKNOWN_UUIDS,
    assert_recording_session,
    book_session,
    create_casting_assignment_payload,
    create_order,
    create_recording_session_payload,
    create_studio,
    create_voice_talent,
    make_voice_talent_headers,
    open_script_workstream,
    order_version,
    set_clock,
    setup_canon,
    validate_error,
    validate_paginated,
    validate_success,
    walk_script_to_in_review,
)


# --------------------------------------------------------------------------
# Studio geometry: half-open with a trailing buffer
# --------------------------------------------------------------------------
def test_booking_at_the_previous_sessions_end_collides_through_the_buffer(api):
    """PRD §3.6: "**The studio geometry is half-open with a trailing buffer.** The
    interval a booking occupies on a room runs from its `start_utc` up to but not
    including its `end_utc` plus that room's `turnaround_buffer_minutes`."
    PRD §3.6: "A new booking collides when its buffered interval intersects the
    identically-buffered interval of any session already on that room in `SCHEDULED`,
    `CONFIRMED`, `IN_PROGRESS` or `COMPLETED`."
    PRD §3.6: "Under the default `REJECT`, a buffered studio collision is refused with
    `ERR_STUDIO_SLOT_CONFLICT`, a room-capacity shortfall is refused with
    `ERR_STUDIO_DAILY_CAPACITY`, and no row is created in either case."

    Design: Difficulty/resource_temporal_overlap/studio_half_open_interval_plus_trailing_buffer
    """
    ctx = setup_canon(27)
    resp = api.create_recording_session(
        create_recording_session_payload(
            ctx["o_id"], ctx["st_id"], ctx["ca2_id"],
            "2026-09-10T11:00:00Z", "2026-09-10T12:00:00Z",
        ),
        PC,
    )
    validate_error(resp, ApiErrorId.ERR_STUDIO_SLOT_CONFLICT.value)
    assert resp.status_code == 409
    rows, _ = validate_paginated(api.list_recording_sessions(PC, {"studio_id": ctx["st_id"]}))
    assert len(rows) == 1, "the refused booking must create no row"
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 120


def test_booking_exactly_at_the_buffered_end_instant_is_accepted(api):
    """PRD §3.6: "Because the geometry is half-open, a booking whose `start_utc` falls
    exactly on the instant a previous booking's buffered interval ends does **not**
    collide."
    PRD §3.6: "A session landing in `SCHEDULED` adds its `duration_minutes` to the
    room's `booked_minutes` and to the performer's `held_minutes`, has its provisional
    `session_cost_cents` stamped, and — when the owning order is still in `CASTING` —
    cascades that order `CASTING → RECORDING` with the order's `version` incremented
    by 1."

    Design: Difficulty/resource_temporal_overlap/studio_half_open_interval_plus_trailing_buffer
    """
    ctx = setup_canon(27)
    data = validate_success(
        api.create_recording_session(
            create_recording_session_payload(
                ctx["o_id"], ctx["st_id"], ctx["ca2_id"],
                "2026-09-10T11:30:00Z", "2026-09-10T12:30:00Z",
            ),
            PC,
        ),
        201,
    )
    assert_recording_session(data)
    assert data["status"] == "SCHEDULED"
    assert data["duration_minutes"] == 60
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 180


# --------------------------------------------------------------------------
# Talent geometry: closed and unbuffered
# --------------------------------------------------------------------------
def test_touching_performer_intervals_collide_even_on_another_room(api):
    """PRD §3.6: "**The talent geometry is closed and unbuffered.** A booking collides
    on the performer when the closed interval from its `start_utc` through its
    `end_utc` intersects the closed interval of any other session of the same
    performer in `SCHEDULED`, `CONFIRMED`, `IN_PROGRESS` or `COMPLETED` — and because
    both intervals are closed, two sessions that merely touch endpoints *do* collide."
    PRD §3.6: "A talent collision is always `ERR_TALENT_DOUBLE_BOOKED`, and it is
    raised whatever the value of `on_conflict`."

    Design: Difficulty/resource_temporal_overlap/talent_closed_interval_touching_endpoints_collide
    """
    ctx = setup_canon(21)
    create_studio(ctx, "st2_id", name="Booth 2", territory="DE", hourly_rate_cents=24000,
                  turnaround_buffer_minutes=0, daily_capacity_minutes=600)
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")

    resp = api.create_recording_session(
        create_recording_session_payload(
            ctx["o_id"], ctx["st2_id"], ctx["ca1_id"],
            "2026-09-10T11:00:00Z", "2026-09-10T11:30:00Z",
        ),
        PC,
    )
    validate_error(resp, ApiErrorId.ERR_TALENT_DOUBLE_BOOKED.value)
    assert resp.status_code == 409
    rows, _ = validate_paginated(api.list_recording_sessions(PC, {"studio_id": ctx["st2_id"]}))
    assert rows == [], "the refused booking must create no row"


def test_a_performer_slot_one_minute_clear_of_the_previous_end_is_accepted(api):
    """PRD §3.6: "**The talent geometry is closed and unbuffered.** A booking collides
    on the performer when the closed interval from its `start_utc` through its
    `end_utc` intersects the closed interval of any other session of the same
    performer in `SCHEDULED`, `CONFIRMED`, `IN_PROGRESS` or `COMPLETED` — and because
    both intervals are closed, two sessions that merely touch endpoints *do* collide."
    PRD §2.10: "Booking a slot that lands on the calendar adds its `duration_minutes`
    to the room's `booked_minutes` and to the performer's `held_minutes`."

    Design: Difficulty/resource_temporal_overlap/talent_closed_interval_touching_endpoints_collide
    """
    ctx = setup_canon(21)
    create_studio(ctx, "st2_id", name="Booth 2", territory="DE", hourly_rate_cents=24000,
                  turnaround_buffer_minutes=0, daily_capacity_minutes=600)
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")

    data = validate_success(
        api.create_recording_session(
            create_recording_session_payload(
                ctx["o_id"], ctx["st2_id"], ctx["ca1_id"],
                "2026-09-10T11:01:00Z", "2026-09-10T11:31:00Z",
            ),
            PC,
        ),
        201,
    )
    assert data["status"] == "SCHEDULED"
    assert data["duration_minutes"] == 30
    assert validate_success(api.get_voice_talent(ctx["tal1_id"], CASTING))["held_minutes"] == 150
    assert validate_success(api.get_studio(ctx["st2_id"], PC))["booked_minutes"] == 30
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 120


# --------------------------------------------------------------------------
# Booth minutes are a conserved quantity
# --------------------------------------------------------------------------
def test_booking_holds_exactly_its_duration_on_room_and_performer(api):
    """PRD §2.10: "A `Studio` carries `booked_minutes`, defined at all times as the
    sum of `duration_minutes` over that room's sessions in `SCHEDULED`, `CONFIRMED`,
    `IN_PROGRESS` or `COMPLETED`."
    PRD §2.10: "Booking a slot that lands on the calendar adds its `duration_minutes`
    to the room's `booked_minutes` and to the performer's `held_minutes`."

    Design: Difficulty/compensating_invariant/booth_minutes_conserved_across_session_cancel
    """
    ctx = setup_canon(21)
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 0
    assert validate_success(api.get_voice_talent(ctx["tal1_id"], CASTING))["held_minutes"] == 0

    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 120
    assert validate_success(api.get_voice_talent(ctx["tal1_id"], CASTING))["held_minutes"] == 120


def test_cancelling_a_booking_returns_every_minute_it_held(api):
    """PRD §2.10: "Cancelling that slot from either `SCHEDULED` or `CONFIRMED`
    subtracts the same `duration_minutes` from both counters."
    PRD §2.10: "A create followed by its cancel therefore restores both counters to
    their exact pre-create values — and it does so even when the cancel additionally
    promotes a waitlisted row, because the promotion adds the *promoted* row's own
    `duration_minutes` and never the cancelled row's."

    Design: Difficulty/compensating_invariant/booth_minutes_conserved_across_session_cancel
    """
    ctx = setup_canon(21)
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")

    cancelled = validate_success(
        api.cancel_recording_session(ctx["s1_id"], {"reason": "Schedule change"}, PC)
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["duration_minutes"] == 120
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 0
    talent = validate_success(api.get_voice_talent(ctx["tal1_id"], CASTING))
    assert talent["held_minutes"] == 0
    assert talent["recorded_minutes"] == 0


# --------------------------------------------------------------------------
# Cancel -> free minutes -> promote -> order cascade
# --------------------------------------------------------------------------
def _setup_waitlisted_second_order(ctx, api):
    """Second order (STANDARD, fr-FR) whose 10:00-11:00 booking is waitlisted."""
    create_voice_talent(ctx, "tal3_id", full_name="Chloe Marin", language_code="fr-FR",
                        base_rate_cents_per_hour=30000, licensed_territories=["FR"],
                        union_status="NON_UNION", max_daily_recorded_minutes=300)
    create_order(ctx, key="o2_id", target_language="fr-FR", territory="FR",
                 budget_cap_cents=500000, priority_tier="STANDARD")
    open_script_workstream(ctx, order_key="o2_id", key="sa2_id", adaptor_user="adaptor-2")
    walk_script_to_in_review(ctx, key="sa2_id", adaptor_user="adaptor-2")
    version = validate_success(api.get_localization_order(ctx["o2_id"], PC))["version"]
    ca3 = validate_success(
        api.create_casting_assignment(
            create_casting_assignment_payload(
                ctx["o2_id"], ctx["ch1_id"], ctx["tal3_id"], version,
                usage_variant="BUYOUT", agreed_rate_cents_per_hour=36000,
            ),
            CASTING,
        ),
        201,
    )
    ctx["ca3_id"] = ca3["id"]
    validate_success(api.request_hold(ctx["ca3_id"], CASTING))
    validate_success(
        api.respond_hold(ctx["ca3_id"], {"response": "ACCEPT"},
                         make_voice_talent_headers(ctx["tal3_id"]))
    )
    validate_success(api.confirm_casting_assignment(ctx["ca3_id"], CASTING))
    waitlisted = validate_success(
        api.create_recording_session(
            create_recording_session_payload(
                ctx["o2_id"], ctx["st_id"], ctx["ca3_id"],
                "2026-09-10T10:00:00Z", "2026-09-10T11:00:00Z", on_conflict="WAITLIST",
            ),
            PC,
        ),
        201,
    )
    ctx["s2_id"] = waitlisted["id"]
    return waitlisted


def test_cancelling_a_booking_promotes_the_waitlisted_row_on_that_room(api):
    """PRD §3.6: "**Waitlist promotion** runs whenever booth time is returned to a
    room — that is, on a session cancellation from `SCHEDULED` or `CONFIRMED`, and on
    a no-show."
    PRD §3.6: "Promotion itself is a `WAITLISTED → SCHEDULED` transition with four
    consequences: `waitlisted_reason` is cleared to null, the promoted row's
    `duration_minutes` is added to the room's `booked_minutes`, the same
    `duration_minutes` is added to the performer's `held_minutes`, and — when the
    promoted session's order is still in `CASTING` — that order cascades
    `CASTING → RECORDING`."

    Design: Difficulty/transitive_cascade/session_cancel_waitlist_promotion_chain
    """
    ctx = setup_canon(21)
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")
    waitlisted = _setup_waitlisted_second_order(ctx, api)
    assert waitlisted["status"] == "WAITLISTED"
    assert waitlisted["waitlisted_reason"] == "STUDIO_SLOT_CONFLICT"

    validate_success(
        api.cancel_recording_session(ctx["s1_id"], {"reason": "Talent illness"}, PC)
    )
    assert validate_success(api.get_recording_session(ctx["s1_id"], PC))["status"] == "CANCELLED"
    promoted = validate_success(api.get_recording_session(ctx["s2_id"], PC))
    assert promoted["status"] == "SCHEDULED"
    assert promoted["waitlisted_reason"] is None
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 60
    assert validate_success(api.get_voice_talent(ctx["tal1_id"], CASTING))["held_minutes"] == 0
    assert validate_success(api.get_voice_talent(ctx["tal3_id"], CASTING))["held_minutes"] == 60


def test_waitlist_promotion_advances_the_promoted_rows_own_order(api):
    """PRD §3.6: "Promotion itself is a `WAITLISTED → SCHEDULED` transition with four
    consequences: `waitlisted_reason` is cleared to null, the promoted row's
    `duration_minutes` is added to the room's `booked_minutes`, the same
    `duration_minutes` is added to the performer's `held_minutes`, and — when the
    promoted session's order is still in `CASTING` — that order cascades
    `CASTING → RECORDING`."
    PRD §3.6: "An order therefore stays in `CASTING` until one of its sessions
    actually reaches the calendar, whether by direct booking or by later promotion off
    the waitlist."

    Design: Difficulty/transitive_cascade/session_cancel_waitlist_promotion_chain
    """
    ctx = setup_canon(21)
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")
    _setup_waitlisted_second_order(ctx, api)
    assert validate_success(api.get_localization_order(ctx["o2_id"], PC))["status"] == "CASTING", (
        "a waitlisted booking holds no booth time and fires no order cascade"
    )

    validate_success(
        api.cancel_recording_session(ctx["s1_id"], {"reason": "Talent illness"}, PC)
    )
    assert validate_success(api.get_localization_order(ctx["o2_id"], PC))["status"] == "RECORDING"
    assert validate_success(api.get_localization_order(ctx["o_id"], PC))["status"] == "RECORDING"


def test_waitlist_ranking_puts_a_rush_order_ahead_of_an_earlier_standard_slot(api):
    """PRD §3.6: "Surviving candidates are ranked on two keys in order. The first key
    is the priority rank of the candidate's own order — a `RUSH` order ranks ahead of
    an `EXPEDITED` order, which ranks ahead of a `STANDARD` order. The second key is
    `start_utc` ascending, so the earlier slot wins among equals."
    PRD §3.6: "Exactly one row, the first after ranking, is promoted."
    PRD §3.6: "Under `WAITLIST`, no error is raised for either condition: the session
    is created in `WAITLISTED` with `waitlisted_reason` set to `STUDIO_SLOT_CONFLICT`
    when the buffered interval collided and to `STUDIO_DAILY_CAPACITY` when the day's
    capacity was short."

    Design: Corner/calculations/waitlist_selector_ranks_rush_tier_ahead_of_earlier_start
    """
    ctx = setup_canon(21, studio={"daily_capacity_minutes": 150})
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")

    # A STANDARD order wanting the earlier 12:00 slot.
    create_voice_talent(ctx, "tal3_id", full_name="Chloe Marin", language_code="fr-FR",
                        base_rate_cents_per_hour=30000, licensed_territories=["FR"],
                        union_status="NON_UNION", max_daily_recorded_minutes=300)
    create_order(ctx, key="o2_id", target_language="fr-FR", territory="FR",
                 budget_cap_cents=500000, priority_tier="STANDARD")
    open_script_workstream(ctx, order_key="o2_id", key="sa2_id", adaptor_user="adaptor-2")
    walk_script_to_in_review(ctx, key="sa2_id", adaptor_user="adaptor-2")
    v2 = validate_success(api.get_localization_order(ctx["o2_id"], PC))["version"]
    ca3 = validate_success(
        api.create_casting_assignment(
            create_casting_assignment_payload(
                ctx["o2_id"], ctx["ch1_id"], ctx["tal3_id"], v2,
                usage_variant="BUYOUT", agreed_rate_cents_per_hour=36000,
            ),
            CASTING,
        ),
        201,
    )

    # A RUSH order wanting the later 13:30 slot.
    create_voice_talent(ctx, "tal5_id", full_name="Diego Salas", language_code="es-ES",
                        base_rate_cents_per_hour=30000, licensed_territories=["BR"],
                        union_status="NON_UNION", max_daily_recorded_minutes=300)
    create_order(ctx, key="o3_id", target_language="es-ES", territory="BR",
                 budget_cap_cents=500000, priority_tier="RUSH")
    open_script_workstream(ctx, order_key="o3_id", key="sa3_id", adaptor_user="adaptor-3")
    walk_script_to_in_review(ctx, key="sa3_id", adaptor_user="adaptor-3")
    v3 = validate_success(api.get_localization_order(ctx["o3_id"], PC))["version"]
    ca4 = validate_success(
        api.create_casting_assignment(
            create_casting_assignment_payload(
                ctx["o3_id"], ctx["ch1_id"], ctx["tal5_id"], v3,
                usage_variant="BUYOUT", agreed_rate_cents_per_hour=36000,
            ),
            CASTING,
        ),
        201,
    )

    standard_row = validate_success(
        api.create_recording_session(
            create_recording_session_payload(
                ctx["o2_id"], ctx["st_id"], ca3["id"],
                "2026-09-10T12:00:00Z", "2026-09-10T13:00:00Z", on_conflict="WAITLIST",
            ),
            PC,
        ),
        201,
    )
    rush_row = validate_success(
        api.create_recording_session(
            create_recording_session_payload(
                ctx["o3_id"], ctx["st_id"], ca4["id"],
                "2026-09-10T13:30:00Z", "2026-09-10T14:30:00Z", on_conflict="WAITLIST",
            ),
            PC,
        ),
        201,
    )
    assert standard_row["status"] == "WAITLISTED"
    assert rush_row["status"] == "WAITLISTED"

    validate_success(api.cancel_recording_session(ctx["s1_id"], {"reason": "Room flood"}, PC))
    assert validate_success(api.get_recording_session(ctx["s1_id"], PC))["status"] == "CANCELLED"
    assert validate_success(api.get_recording_session(rush_row["id"], PC))["status"] == "SCHEDULED"
    still_waiting = validate_success(api.get_recording_session(standard_row["id"], PC))
    assert still_waiting["status"] == "WAITLISTED"
    assert still_waiting["waitlisted_reason"] == "STUDIO_DAILY_CAPACITY"
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 60
    assert validate_success(api.get_localization_order(ctx["o3_id"], PC))["status"] == "RECORDING"
    assert validate_success(api.get_localization_order(ctx["o2_id"], PC))["status"] == "CASTING"


# --------------------------------------------------------------------------
# Booking guards
# --------------------------------------------------------------------------
def test_a_new_booking_carries_its_provisional_cost_immediately(api):
    """PRD §3.7: "**The cost of a session** is stamped provisionally when the row is
    created and restamped from live data at completion; the restamped figure is the
    one the budget check and the invoice use."
    PRD §3.6: "A session landing in `SCHEDULED` adds its `duration_minutes` to the
    room's `booked_minutes` and to the performer's `held_minutes`, has its provisional
    `session_cost_cents` stamped, and — when the owning order is still in `CASTING` —
    cascades that order `CASTING → RECORDING` with the order's `version` incremented
    by 1."

    Design: Corner/calculations/provisional_session_cost_is_stamped_at_creation
    """
    ctx = setup_canon(21)
    data = validate_success(
        api.create_recording_session(
            create_recording_session_payload(
                ctx["o_id"], ctx["st_id"], ctx["ca1_id"],
                "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z",
            ),
            PC,
        ),
        201,
    )
    assert data["status"] == "SCHEDULED"
    assert data["duration_minutes"] == 120
    assert data["session_cost_cents"] == 120000
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 120
    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["committed_cents"] == 0, "the provisional stamp accrues no money"
    assert order["status"] == "RECORDING"


def test_a_session_naming_another_orders_assignment_is_refused(api):
    """PRD §3.6: "Referential integrity comes first among the domain checks: the
    assignment named by `casting_assignment_id` must belong to the very order named by
    `order_id`, and a mismatch is `ERR_CROSS_ORDER_REFERENCE`."

    Design: Corner/validations/session_referencing_another_orders_assignment_is_rejected
    """
    ctx = setup_canon(21)
    create_voice_talent(ctx, "tal3_id", full_name="Chloe Marin", language_code="fr-FR",
                        base_rate_cents_per_hour=30000, licensed_territories=["FR"],
                        union_status="NON_UNION", max_daily_recorded_minutes=300)
    create_order(ctx, key="o2_id", target_language="fr-FR", territory="FR",
                 budget_cap_cents=500000, priority_tier="STANDARD")
    resp = api.create_recording_session(
        create_recording_session_payload(
            ctx["o2_id"], ctx["st_id"], ctx["ca1_id"],
            "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z",
        ),
        PC,
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_ORDER_REFERENCE.value)
    assert resp.status_code == 422
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 0


def test_a_booking_that_starts_before_the_logical_clock_is_refused(api):
    """PRD §3.6: "The interval itself must be well-formed: `start_utc` strictly earlier
    than `end_utc`, both endpoints falling exactly on a whole minute, and `start_utc`
    at or after the current logical clock — any of those three failing gives
    `ERR_SESSION_WINDOW_INVALID`."

    Design: Corner/validations/booking_a_session_in_the_past_is_rejected
    """
    ctx = setup_canon(21)
    set_clock("2026-09-12T00:00:00Z")
    resp = api.create_recording_session(
        create_recording_session_payload(
            ctx["o_id"], ctx["st_id"], ctx["ca1_id"],
            "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z",
        ),
        PC,
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_WINDOW_INVALID.value)
    assert resp.status_code == 422
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 0
    assert validate_success(api.get_voice_talent(ctx["tal1_id"], CASTING))["held_minutes"] == 0


def test_a_room_in_maintenance_refuses_bookings_until_it_is_active_again(api):
    """PRD §3.6: "The room must then be `ACTIVE`; booking onto a room in `MAINTENANCE`
    earns `ERR_STUDIO_UNAVAILABLE`."
    PRD §3.2: "Both directions increment the room's `version` by 1, and a room in
    `MAINTENANCE` accepts no bookings."

    Design: Corner/validations/booking_a_room_in_maintenance_is_rejected
    """
    ctx = setup_canon(21)
    validate_success(api.set_studio_status(ctx["st_id"], {"to_status": "MAINTENANCE"}, PC))
    body = create_recording_session_payload(
        ctx["o_id"], ctx["st_id"], ctx["ca1_id"],
        "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z",
    )
    resp = api.create_recording_session(body, PC)
    validate_error(resp, ApiErrorId.ERR_STUDIO_UNAVAILABLE.value)
    assert resp.status_code == 409

    validate_success(api.set_studio_status(ctx["st_id"], {"to_status": "ACTIVE"}, PC))
    studio = validate_success(api.get_studio(ctx["st_id"], PC))
    assert studio["status"] == "ACTIVE"
    created = validate_success(api.create_recording_session(body, PC), 201)
    assert created["status"] == "SCHEDULED"
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 120


def test_the_performer_daily_cap_is_an_aggregate_over_one_utc_day(api):
    """PRD §3.6: "Two daily ceilings apply on top of the geometries, each counted over
    the requested booking's own UTC calendar day only."
    PRD §3.6: "The performer's recorded plus held minutes for that day plus the new
    `duration_minutes` must be at most that performer's `max_daily_recorded_minutes`;
    exceeding the performer's cap is `ERR_TALENT_DAILY_CAP_EXCEEDED` and is likewise
    raised whatever the value of `on_conflict`."

    Design: Corner/validations/talent_daily_minute_cap_is_an_aggregate_check
    """
    ctx = setup_canon(21)
    create_voice_talent(ctx, "tal6_id", full_name="Anna Vogel Cap", language_code="de-DE",
                        base_rate_cents_per_hour=30000, licensed_territories=["DE"],
                        union_status="NON_UNION", max_daily_recorded_minutes=240)
    create_studio(ctx, "st2_id", name="Booth 2", territory="DE", hourly_rate_cents=24000,
                  turnaround_buffer_minutes=0, daily_capacity_minutes=600)
    version = order_version(ctx["o_id"])
    ca6 = validate_success(
        api.create_casting_assignment(
            create_casting_assignment_payload(
                ctx["o_id"], ctx["ch2_id"], ctx["tal6_id"], version,
                usage_variant="BUYOUT", agreed_rate_cents_per_hour=30000,
            ),
            CASTING,
        ),
        201,
    )
    validate_success(
        api.create_recording_session(
            create_recording_session_payload(
                ctx["o_id"], ctx["st_id"], ca6["id"],
                "2026-09-10T14:00:00Z", "2026-09-10T16:00:00Z",
            ),
            PC,
        ),
        201,
    )

    over_cap = api.create_recording_session(
        create_recording_session_payload(
            ctx["o_id"], ctx["st2_id"], ca6["id"],
            "2026-09-10T17:00:00Z", "2026-09-10T19:01:00Z",
        ),
        PC,
    )
    validate_error(over_cap, ApiErrorId.ERR_TALENT_DAILY_CAP_EXCEEDED.value)
    assert over_cap.status_code == 422

    next_day = validate_success(
        api.create_recording_session(
            create_recording_session_payload(
                ctx["o_id"], ctx["st2_id"], ca6["id"],
                "2026-09-11T17:00:00Z", "2026-09-11T19:01:00Z",
            ),
            PC,
        ),
        201,
    )
    assert next_day["status"] == "SCHEDULED"
    assert next_day["duration_minutes"] == 121
    assert validate_success(api.get_voice_talent(ctx["tal6_id"], CASTING))["held_minutes"] == 241


def test_the_room_daily_ceiling_refuses_a_clash_free_slot_on_the_same_day(api):
    """PRD §3.6: "The room's already-booked minutes for that day plus the new
    `duration_minutes` must be at most that room's `daily_capacity_minutes`, or the
    booking is short of room capacity."
    PRD §3.6: "Under the default `REJECT`, a buffered studio collision is refused with
    `ERR_STUDIO_SLOT_CONFLICT`, a room-capacity shortfall is refused with
    `ERR_STUDIO_DAILY_CAPACITY`, and no row is created in either case."

    Design: Corner/errors/studio_daily_capacity_rejects_when_on_conflict_is_reject
    """
    ctx = setup_canon(27, studio={"daily_capacity_minutes": 150})
    same_day = api.create_recording_session(
        create_recording_session_payload(
            ctx["o_id"], ctx["st_id"], ctx["ca2_id"],
            "2026-09-10T12:00:00Z", "2026-09-10T13:00:00Z",
        ),
        PC,
    )
    validate_error(same_day, ApiErrorId.ERR_STUDIO_DAILY_CAPACITY.value)
    assert same_day.status_code == 409

    next_day = validate_success(
        api.create_recording_session(
            create_recording_session_payload(
                ctx["o_id"], ctx["st_id"], ctx["ca2_id"],
                "2026-09-11T12:00:00Z", "2026-09-11T13:00:00Z",
            ),
            PC,
        ),
        201,
    )
    assert next_day["status"] == "SCHEDULED"
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 180


def test_an_unknown_studio_id_in_the_body_is_a_studio_not_found(api):
    """PRD §2.5: "The same not-found codes apply: a body naming an unknown `title_id`,
    `cut_id`, `character_id`, `platform_spec_id`, `talent_id`, `studio_id`,
    `order_id`, `casting_assignment_id`, `quality_review_id` or `mix_job_id` is
    refused at HTTP 404 with the code belonging to the entity that identifier points
    at."

    Design: Corner/errors/unknown_studio_id_in_body_returns_studio_not_found
    """
    ctx = setup_canon(21)
    resp = api.create_recording_session(
        create_recording_session_payload(
            ctx["o_id"], UNKNOWN_UUIDS["studio"], ctx["ca1_id"],
            "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z",
        ),
        PC,
    )
    validate_error(resp, ApiErrorId.ERR_STUDIO_NOT_FOUND.value)
    assert resp.status_code == 404
    assert validate_success(api.get_voice_talent(ctx["tal1_id"], CASTING))["held_minutes"] == 0


def test_a_mix_engineer_may_read_a_room_but_never_book_it(api):
    """PRD §2.1: "Every role may perform every read operation in the system."
    PRD §2.6 ladder step 3: "The acting role appears in the set of roles authorised
    for the requested endpoint, on every endpoint; otherwise `ERR_ROLE_FORBIDDEN`
    (403)."
    PRD §2.1: "A `MixEngineer` owns mixing and music-and-effects stem handling."

    Design: Corner/rbac/mix_engineer_may_read_but_not_book_studio_time
    """
    ctx = setup_canon(21)
    studio = validate_success(api.get_studio(ctx["st_id"], MIXER))
    assert studio["booked_minutes"] == 0

    resp = api.create_recording_session(
        create_recording_session_payload(
            ctx["o_id"], ctx["st_id"], ctx["ca1_id"],
            "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z",
        ),
        MIXER,
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value)
    assert resp.status_code == 403
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 0
