"""The cycle, the snapped-forward auto-schedule and the two reminders."""

from test_helpers import *  # noqa: F401,F403


def _complete_single_trim_visit(world, route_date, scheduled_date, completion_clock):
    """Work one TRIM limb through to completion on `completion_clock`."""
    setup_route_with_stop(world, route_date=route_date, planned_start_minute=480)
    appointment, lines = setup_scheduled_visit(
        world, limbs=("LF",), service_type="TRIM", scheduled_date=scheduled_date
    )
    plan_route(world["route"]["id"])
    dispatch_route(world["route"]["id"])
    arrive_stop(world["stop"]["id"], world["farrier"]["id"])
    start_visit(appointment["id"], world["farrier"]["id"])
    set_clock(completion_clock)
    complete_visit(
        appointment["id"], [line["id"] for line in lines], world["farrier"]["id"]
    )
    world["origin"] = read_appointment(appointment["id"])
    return world


def test_snap_forward_moves_one_day_to_the_next_served_weekday(api):
    """PRD §3.8: "The horse's `next_due_on` is then the base date plus the cycle
    multiplied by 7 (`DAYS_PER_WEEK`) calendar days."
    PRD §3.8: "Starting at an offset of 0 days and testing 1, 2 and then 3
    (`SNAP_FORWARD_LOOKAHEAD_DAYS`) in turn, the first candidate date whose weekday
    is a member of the barn's `served_weekdays` and which does not appear in the
    barn's `blackout_dates` is taken."
    PRD §3.8: "Two reminder rows are minted against it, both `PENDING`, one at an
    `offset_days` of 7 (`REMINDER_OFFSET_DAYS_PRIMARY`) and one at an `offset_days`
    of 2 (`REMINDER_OFFSET_DAYS_SECONDARY`), each with a `due_on` equal to the
    appointment's `scheduled_date` minus its own `offset_days` and a null `sent_on`."

    Design: Corner/calculations/corner_snap_forward_moves_one_day_to_the_next_served_weekday
    """
    world = setup_reference(
        with_sku=False, barn={"served_weekdays": ["MON", "WED", "FRI"]}
    )
    _complete_single_trim_visit(
        world, "2026-05-04", "2026-05-04", "2026-05-05T08:00:00Z"
    )

    assert_same_date(world["origin"]["completed_on"], "2026-05-05")
    horse = read_horse(world["horse"]["id"])
    # 2026-05-05 plus 6 x 7 elapsed days is 2026-06-16, a Tuesday.
    assert plus_weeks("2026-05-05", 6) == "2026-06-16"
    assert weekday_token("2026-06-16") == "TUE"
    assert_same_date(horse["next_due_on"], "2026-06-16")

    successors = successor_of(world["horse"]["id"], [world["origin"]["id"]])
    assert len(successors) == 1
    successor = successors[0]
    assert_same_date(successor["scheduled_date"], "2026-06-17")
    assert successor["cycle_source"] == "ROUTINE"
    assert successor["visit_kind"] == "ROUTINE"

    reminders = reminders_for(successor["id"])
    assert len(reminders) == 2
    primary = reminder_with_offset(successor["id"], REMINDER_OFFSET_DAYS_PRIMARY)
    secondary = reminder_with_offset(successor["id"], REMINDER_OFFSET_DAYS_SECONDARY)
    assert_same_date(primary["due_on"], "2026-06-10")
    assert_same_date(secondary["due_on"], "2026-06-15")
    for reminder in (primary, secondary):
        assert_reminder(reminder)
        assert reminder["status"] == "PENDING"
        assert reminder["sent_on"] is None


def test_snap_forward_beyond_the_lookahead_cap_keeps_the_raw_due_date(api):
    """PRD §3.8: "If all four candidates fail, the raw due date is used as it stands
    and the visit will need a human to place it."
    PRD §3.8: "Because offset 0 is tested **first**, a raw due date that already
    lands on a served, non-blacked-out day is used unchanged."

    Design: Corner/calculations/corner_snap_forward_beyond_the_lookahead_cap_keeps_the_raw_due_date
    """
    world = setup_reference(with_sku=False, barn={"served_weekdays": ["MON"]})
    _complete_single_trim_visit(
        world, "2026-05-04", "2026-05-04", "2026-05-05T08:00:00Z"
    )

    horse = read_horse(world["horse"]["id"])
    assert_same_date(horse["next_due_on"], "2026-06-16")
    # Offsets 0..3 land on TUE, WED, THU and FRI, none of which the barn serves.
    for offset in range(SNAP_FORWARD_LOOKAHEAD_DAYS + 1):
        assert weekday_token(plus_days("2026-06-16", offset)) != "MON"

    successors = successor_of(world["horse"]["id"], [world["origin"]["id"]])
    assert len(successors) == 1
    assert_same_date(successors[0]["scheduled_date"], "2026-06-16")


def test_second_reminder_inside_the_suppression_window_is_refused(api, dispatcher):
    """PRD §3.8: "A send is refused with `ERR_REMINDER_SUPPRESSED` when some
    **other** reminder of the same appointment has a `status` of `SENT` or
    `ACKNOWLEDGED`, a non-null `sent_on`, and a `sent_on` within 3 days
    (`REMINDER_SUPPRESSION_WINDOW_DAYS`) of the logical clock date in either
    direction. The window is a closed interval on both sides: exactly three days
    apart is still suppressed, and four days apart is not."
    PRD §3.8: "A `DELIVERED` outcome moves the reminder from `PENDING` — or from
    `FAILED`, since a failure may be retried — to `SENT` and sets its `sent_on` to
    the logical clock date."

    Design: Corner/calculations/corner_second_reminder_inside_the_suppression_window_is_refused
    """
    world = setup_reference(with_sku=False)
    setup_route_with_stop(world, route_date="2026-05-13", planned_start_minute=480)
    appointment, _lines = setup_scheduled_visit(
        world, limbs=("LF",), service_type="TRIM", scheduled_date="2026-05-13"
    )
    primary = reminder_with_offset(appointment["id"], REMINDER_OFFSET_DAYS_PRIMARY)
    secondary = reminder_with_offset(appointment["id"], REMINDER_OFFSET_DAYS_SECONDARY)
    get_success_data(
        api.send_reminder(primary["id"], {"delivery_outcome": "DELIVERED"}, dispatcher)
    )
    sent = read_reminder(primary["id"])
    assert sent["status"] == "SENT"
    assert_same_date(sent["sent_on"], "2026-05-04")
    set_clock("2026-05-07T08:00:00Z")
    assert lead_days("2026-05-07", "2026-05-04") == REMINDER_SUPPRESSION_WINDOW_DAYS

    response = api.send_reminder(
        secondary["id"], {"delivery_outcome": "DELIVERED"}, dispatcher
    )

    validate_error(response, ApiErrorId.ERR_REMINDER_SUPPRESSED.value)
    assert response.status_code == 409
    after = read_reminder(secondary["id"])
    assert after["status"] == "PENDING"
    assert after["sent_on"] is None


# ---------------------------------------------------------------------------
# A live prescription overrides the routine cycle unconditionally
# ---------------------------------------------------------------------------


def _setup_therapeutic_cycle_world():
    """A severity-2 case (no hold) carrying an ACTIVE two-week prescription, and a
    four-limb TRIM visit completed on 2026-05-06."""
    world = setup_reference(with_sku=False)
    world["case"] = report_lameness(world["horse"]["id"], "2026-05-04", 2)
    world["prescription"] = draft_prescription(
        world["case"]["id"], "2026-05-04", "2026-06-30", ["LF", "RF", "LH", "RH"], 2
    )
    activate_prescription(world["prescription"]["id"], world["case"]["id"])

    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    appointment, lines = setup_scheduled_visit(
        world, service_type="TRIM", scheduled_date="2026-05-06"
    )
    plan_route(world["route"]["id"])
    dispatch_route(world["route"]["id"])
    set_clock("2026-05-06T08:00:00Z")
    arrive_stop(world["stop"]["id"], world["farrier"]["id"])
    start_visit(appointment["id"], world["farrier"]["id"])
    complete_visit(
        appointment["id"], [line["id"] for line in lines], world["farrier"]["id"]
    )
    world["origin"] = read_appointment(appointment["id"])
    return world


def test_next_due_on_follows_the_prescribed_cycle_not_the_routine_one(api):
    """PRD §3.8: "A live therapeutic prescription is the other, and while one lives
    it **overrides the routine cycle unconditionally** — even when its
    `prescribed_cycle_weeks` is not shorter than the routine figure."
    PRD §3.8: "If the horse's `active_prescription_id` is not null, and that
    prescription's `status` is `ACTIVE`, and its `expires_on` is on or after the
    base date, then the cycle is that prescription's `prescribed_cycle_weeks` and
    the derivation is the therapeutic one; otherwise the cycle is the horse's
    `routine_cycle_weeks` and the derivation is the routine one."
    PRD §3.7: "the horse's `last_completed_on` is set to the completion date and its
    `next_due_on` recomputed; a successor appointment is minted with two reminder
    rows of its own"

    Design: Difficulty/dual_variant_calc/next_due_on_therapeutic_cycle_overrides_routine_cycle
    """
    world = _setup_therapeutic_cycle_world()

    horse = read_horse(world["horse"]["id"])
    assert_same_date(horse["last_completed_on"], "2026-05-06")
    # Therapeutic: 2026-05-06 plus 2 x 7 days. Routine would give 2026-06-17.
    assert plus_weeks("2026-05-06", 2) == "2026-05-20"
    assert plus_weeks("2026-05-06", 6) == "2026-06-17"
    assert_same_date(horse["next_due_on"], "2026-05-20")
    assert parse_iso_date(horse["next_due_on"]) != parse_iso_date("2026-06-17")


def test_the_successor_records_the_therapeutic_branch_it_took(api):
    """PRD §3.8: "Completing a visit therefore mints a successor: a new appointment
    for the same horse, `UNROUTED`, with `scheduled_date` set to the snapped-forward
    date and `cycle_source` set to the branch the derivation took."
    PRD §3.8: "Where the derivation produces an appointment, that appointment's
    `cycle_source` records which branch was taken — `THERAPEUTIC` or `ROUTINE` — and
    an appointment a human created by hand carries a null `cycle_source`."

    Design: Difficulty/dual_variant_calc/next_due_on_therapeutic_cycle_overrides_routine_cycle
    """
    world = _setup_therapeutic_cycle_world()

    successors = successor_of(world["horse"]["id"], [world["origin"]["id"]])
    assert len(successors) == 1, "exactly one UNROUTED successor"
    successor = successors[0]
    assert_appointment(successor)
    # 2026-05-20 is a Wednesday, which the barn serves, so offset 0 is used.
    assert weekday_token("2026-05-20") == "WED"
    assert_same_date(successor["scheduled_date"], "2026-05-20")
    assert successor["cycle_source"] == "THERAPEUTIC"
    assert successor["status"] == "UNROUTED"


# ---------------------------------------------------------------------------
# PENDING -> FAILED -> SENT -> ACKNOWLEDGED on one reminder row
# ---------------------------------------------------------------------------


def _setup_attached_visit_with_reminders():
    world = setup_reference(with_sku=False)
    setup_route_with_stop(world, route_date="2026-05-13", planned_start_minute=480)
    appointment, _lines = setup_scheduled_visit(
        world, service_type="TRIM", scheduled_date="2026-05-13"
    )
    world["primary"] = reminder_with_offset(
        appointment["id"], REMINDER_OFFSET_DAYS_PRIMARY
    )
    world["secondary"] = reminder_with_offset(
        appointment["id"], REMINDER_OFFSET_DAYS_SECONDARY
    )
    return world


def test_a_failed_reminder_can_be_retried_back_into_sent(api, dispatcher):
    """PRD §3.8: "A `DELIVERED` outcome moves the reminder from `PENDING` — or from
    `FAILED`, since a failure may be retried — to `SENT` and sets its `sent_on` to
    the logical clock date. A `FAILED` outcome moves it from `PENDING` to `FAILED`
    and leaves `sent_on` null."
    PRD §3.8: "Two reminder rows are minted against it, both `PENDING`, one at an
    `offset_days` of 7 (`REMINDER_OFFSET_DAYS_PRIMARY`) and one at an `offset_days`
    of 2 (`REMINDER_OFFSET_DAYS_SECONDARY`), each with a `due_on` equal to the
    appointment's `scheduled_date` minus its own `offset_days` and a null `sent_on`."

    Design: Difficulty/non_linear_state_machine/reminder_pending_failed_sent_acknowledged_cycle_on_reminder
    """
    world = _setup_attached_visit_with_reminders()
    assert_same_date(world["primary"]["due_on"], "2026-05-06")
    assert_same_date(world["secondary"]["due_on"], "2026-05-11")

    failed = validate_success(
        api.send_reminder(
            world["primary"]["id"], {"delivery_outcome": "FAILED"}, dispatcher
        )
    )
    assert_reminder(failed)
    assert failed["status"] == "FAILED"
    assert failed["sent_on"] is None

    retried = validate_success(
        api.send_reminder(
            world["primary"]["id"], {"delivery_outcome": "DELIVERED"}, dispatcher
        )
    )
    assert retried["status"] == "SENT"
    assert_same_date(retried["sent_on"], "2026-05-04")


def test_acknowledging_a_sent_reminder_confirms_the_appointment(api, dispatcher):
    """PRD §3.8: "Acknowledgement is the owner's confirmation. It moves a `SENT`
    reminder to `ACKNOWLEDGED` and increments its `version` by 1; acknowledging a
    reminder that is `PENDING`, `FAILED` or already `ACKNOWLEDGED` is refused with
    `ERR_INVALID_STATE`."
    PRD §3.8: "Its cross-entity effect is the point of the whole mechanism: when the
    reminder's appointment is `SCHEDULED` it moves to `CONFIRMED`, and that
    appointment's `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/reminder_pending_failed_sent_acknowledged_cycle_on_reminder
    """
    world = _setup_attached_visit_with_reminders()
    get_success_data(
        api.send_reminder(
            world["primary"]["id"], {"delivery_outcome": "FAILED"}, dispatcher
        )
    )
    get_success_data(
        api.send_reminder(
            world["primary"]["id"], {"delivery_outcome": "DELIVERED"}, dispatcher
        )
    )
    assert read_appointment(world["appointment"]["id"])["status"] == "SCHEDULED"

    data = validate_success(
        api.acknowledge_reminder(
            world["primary"]["id"], make_client_headers(world["client"]["id"])
        )
    )

    assert_reminder(data)
    assert data["status"] == "ACKNOWLEDGED"
    assert read_appointment(world["appointment"]["id"])["status"] == "CONFIRMED"
    assert read_reminder(world["secondary"]["id"])["status"] == "PENDING"
