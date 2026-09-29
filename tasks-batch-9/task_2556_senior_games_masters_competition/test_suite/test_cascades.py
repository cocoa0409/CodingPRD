"""Multi-link cascades: closing a venue down the facility spine, and withdrawing
an athlete down the registration spine."""
from test_helpers import (
    api_client,
    TEST_USERS,
    close_venue,
    create_accommodation_block,
    create_athlete,
    create_entry,
    create_session_slot,
    create_venue,
    get_assignment,
    get_athlete,
    get_block,
    get_entry,
    get_event,
    get_person,
    get_slot,
    get_stay,
    get_venue,
    pay_fees,
    reserve_stay,
    review_entry,
    screen_athlete,
    setup_open_edition,
    setup_seeded_event_with_staffed_slot,
    validate_success,
)

ADMIN = TEST_USERS["games_admin_headers"]

CLOSE_REASON = "Storm damage to the grandstand roof; facility taken out of service."


def _staffed_slot_with_a_fallback_venue() -> dict:
    """The facility spine fully wired — a `SEEDED` event, a `SCHEDULED` slot and a
    `CONFIRMED` sixty-minute assignment — plus a second open venue to move to."""
    ctx = setup_seeded_event_with_staffed_slot()
    ctx["fallback_venue"] = create_venue(
        ctx["edition"]["id"], name="Rivergate Oval", competition_area_count=1,
        spectator_capacity=300,
    )
    assert ctx["slot"]["confirmed_official_count"] == 1
    assert ctx["assignment"]["status"] == "CONFIRMED"
    assert ctx["assignment"]["duration_minutes"] == 60
    assert get_person(ctx["official"]["id"])["assigned_minutes_total"] == 60
    assert ctx["event"]["status"] == "SEEDED"
    return ctx


def test_closing_a_venue_displaces_its_slot_and_releases_the_staffing_ledger():
    """PRD §2.9: "Closing a venue displaces its scheduled and running slots, which releases
    the personnel assignments on those slots, which debits each affected person's
    served-minutes ledger, which may in turn put the slots' sport events on schedule
    hold."
    PRD §3.5: "A `GamesAdmin` closing a venue supplies a `reason`, which is stored as
    the venue's `closed_reason` as the venue moves `OPEN` → `CLOSED`, and three links
    then fire."
    PRD §3.5: "First, every slot at that venue whose status is `SCHEDULED` or
    `IN_PROGRESS` moves to `DISPLACED`."
    PRD §3.5: "Second, each displaced slot releases every personnel assignment on it in
    `ASSIGNED` or `CONFIRMED`, and each of those releases debits that person's
    `assigned_minutes_total` by the assignment's `duration_minutes`; a slot displaced
    from `SCHEDULED` additionally resets its `confirmed_official_count` to 0, while a
    slot displaced out of `IN_PROGRESS` releases its assignments and debits the minutes
    but leaves `confirmed_official_count` as it stood."

    Closing the venue fires four links the request never named.  The venue
    stores its `closed_reason` and becomes `CLOSED`; that displaces the slot,
    resetting `confirmed_official_count` to 0; the displacement releases the
    confirmed assignment; and the release debits the official's
    `assigned_minutes_total` by the assignment's sixty minutes, back to 0, with
    no no-show recorded.

    Design: Difficulty/transitive_cascade/venue_close_cascades_slots_assignments_and_personnel_minutes_ledger
    """
    ctx = _staffed_slot_with_a_fallback_venue()

    closed = validate_success(
        api_client.close_venue(ctx["venue"]["id"], {"reason": CLOSE_REASON}, ADMIN)
    )

    assert closed["status"] == "CLOSED"
    assert closed["closed_reason"] == CLOSE_REASON
    slot = get_slot(ctx["slot"]["id"])
    assert slot["status"] == "DISPLACED"
    assert slot["confirmed_official_count"] == 0
    assert get_assignment(ctx["assignment"]["id"])["status"] == "RELEASED"
    official = get_person(ctx["official"]["id"])
    assert official["assigned_minutes_total"] == 0
    assert official["no_show_count"] == 0


def test_displacing_the_last_live_slot_puts_the_seeded_event_on_schedule_hold():
    """PRD §2.9: "Closing a venue displaces its scheduled and running slots, which releases
    the personnel assignments on those slots, which debits each affected person's
    served-minutes ledger, which may in turn put the slots' sport events on schedule
    hold."
    PRD §3.5: "Third, each displaced slot re-evaluates its sport event, and an event
    whose slot set no longer contains any `SCHEDULED` or `IN_PROGRESS` slot moves
    `SEEDED` → `SCHEDULE_HOLD`."
    PRD §3.1: "An event that has lost its whole schedule to a venue closure moves
    `SEEDED` → `SCHEDULE_HOLD`, which requires that the event has at least one session
    slot and that none of its slots is currently `SCHEDULED` or `IN_PROGRESS`;
    rescheduling any one of those displaced slots back into a scheduled state returns
    the event `SCHEDULE_HOLD` → `SEEDED`."

    The displacement also re-evaluates the event: with no slot of the event
    left `SCHEDULED` or `IN_PROGRESS`, the event moves `SEEDED` →
    `SCHEDULE_HOLD`.  The athlete side of the same event is untouched — the entry
    stays `ACCEPTED` and the capacity ledger does not move.

    Design: Difficulty/transitive_cascade/venue_close_cascades_slots_assignments_and_personnel_minutes_ledger
    """
    ctx = _staffed_slot_with_a_fallback_venue()

    close_venue(ctx["venue"]["id"], CLOSE_REASON)

    event = get_event(ctx["event"]["id"])
    assert event["status"] == "SCHEDULE_HOLD"
    assert event["accepted_entry_count"] == 1
    assert get_entry(ctx["entry"]["id"])["status"] == "ACCEPTED"
    assert get_athlete(ctx["athlete"]["id"])["registration_status"] == "REGISTERED"


def test_rescheduling_the_displaced_slot_is_not_a_reverse_cascade():
    """PRD §2.9: "Personnel assignments released by a venue closure are not restored when
    the slot is rescheduled."
    PRD §3.5: "On success the slot's `venue_id`, `start_utc` and `end_utc` are
    overwritten, the slot moves `DISPLACED` → `SCHEDULED`, and the slot's event returns
    `SCHEDULE_HOLD` → `SEEDED` if it was on hold."
    PRD §3.5: "That closes the `SCHEDULED` → `DISPLACED` → `SCHEDULED` cycle — but the
    personnel released when the slot was displaced are not restored, and the slot must
    be staffed again from scratch."
    PRD §3.5: "Venues start `OPEN` with `closed_reason` null; `CLOSED` is terminal."

    Recovery is deliberately partial.  Moving the displaced slot to the open
    fallback venue returns it to `SCHEDULED` and the event to `SEEDED`, but the
    released assignment stays `RELEASED`, the debited minutes stay at 0 and
    `confirmed_official_count` stays at 0.  The closed venue is not reopened by
    moving its slot away.

    Design: Difficulty/transitive_cascade/venue_close_cascades_slots_assignments_and_personnel_minutes_ledger
    """
    ctx = _staffed_slot_with_a_fallback_venue()
    close_venue(ctx["venue"]["id"], CLOSE_REASON)

    rescheduled = validate_success(
        api_client.reschedule_session_slot(
            ctx["slot"]["id"],
            {
                "venue_id": ctx["fallback_venue"]["id"],
                "start_utc": "2026-09-13T09:00:00Z",
                "end_utc": "2026-09-13T10:00:00Z",
                "teardown_buffer_minutes": 15,
            },
            ADMIN,
        )
    )

    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["venue_id"] == ctx["fallback_venue"]["id"]
    assert rescheduled["start_utc"].startswith("2026-09-13T09:00:00")
    assert rescheduled["confirmed_official_count"] == 0
    assert get_event(ctx["event"]["id"])["status"] == "SEEDED"
    assert get_assignment(ctx["assignment"]["id"])["status"] == "RELEASED"
    assert get_person(ctx["official"]["id"])["assigned_minutes_total"] == 0
    assert get_venue(ctx["venue"]["id"])["status"] == "CLOSED"


WITHDRAW_REASON = "Family emergency; athlete withdraws before the games open."


def _two_accepted_athletes_one_slot_one_stay() -> dict:
    """The registration spine wired for a five-link unwind: an event needing two
    entries to stage holds exactly two `ACCEPTED` entries, one `SCHEDULED` slot,
    and the first athlete has a five-night reservation in a four-bed block."""
    ctx = setup_open_edition(event={"min_entries_to_stage": 2})
    venue = create_venue(ctx["edition"]["id"])
    block = create_accommodation_block(ctx["edition"]["id"])

    athletes = []
    for name, dob in (("Ada Frost", "1966-03-02"), ("Bruno Vega", "1963-07-18")):
        athlete = create_athlete(ctx["edition"]["id"], full_name=name, date_of_birth=dob)
        entry = create_entry(athlete["id"], ctx["event"]["id"])
        pay_fees(athlete["id"], 15500)
        screen_athlete(athlete["id"])
        review_entry(entry["id"], "TAKE_UP")
        review_entry(entry["id"], "ACCEPT")
        athletes.append({"athlete": athlete, "entry": entry})

    slot = create_session_slot(venue["id"], ctx["event"]["id"])
    stay = reserve_stay(
        athletes[0]["athlete"]["id"], block["id"],
        check_in_date="2026-09-09", check_out_date="2026-09-14",
    )

    event = get_event(ctx["event"]["id"])
    assert event["status"] == "OPEN"
    assert event["accepted_entry_count"] == 2
    assert event["available_slots"] == 6
    assert get_slot(slot["id"])["status"] == "SCHEDULED"
    assert get_block(block["id"])["reserved_bed_nights"] == 5
    assert stay["nights"] == 5
    assert stay["total_charge_cents"] == 60000

    return {
        "event": ctx["event"],
        "block": block,
        "slot": slot,
        "stay": stay,
        "first": athletes[0],
        "second": athletes[1],
    }


def test_withdrawing_a_registered_athlete_unwinds_entry_event_and_slot():
    """PRD §2.9: "Withdrawing an athlete withdraws their entries, which restores capacity
    on the affected events, which may drive those events undersubscribed, which releases
    the slots of those events, which releases the personnel on those slots."
    PRD §3.2: "From `REGISTERED`, withdrawal fires the full five-link cascade: the
    athlete moves `REGISTERED` → `WITHDRAWN`; every entry of theirs in `SUBMITTED`,
    `UNDER_REVIEW`, `REVISION_REQUESTED`, `ACCEPTED`, `WAITLISTED` or `MEDICAL_HOLD`
    moves to `WITHDRAWN`, and each entry leaving `ACCEPTED` decrements its event's
    `accepted_entry_count` by one and increments that event's `available_slots` by one;
    each such event whose `accepted_entry_count` has fallen below its
    `min_entries_to_stage` moves to `UNDERSUBSCRIBED`; each event so moved releases
    every session slot of that event still `SCHEDULED`; and each released slot releases
    every personnel assignment on it in `ASSIGNED` or `CONFIRMED`, each release debiting
    that person's `assigned_minutes_total` by the assignment's `duration_minutes`."
    PRD §3.5: "When a slot's event falls `UNDERSUBSCRIBED` or is cancelled, each of that
    event's still-`SCHEDULED` slots moves `SCHEDULED` → `RELEASED`, freeing the
    venue-area interval it held; every personnel assignment on that slot in `ASSIGNED`
    or `CONFIRMED` moves to `RELEASED`, each release debiting that person's
    `assigned_minutes_total` by the assignment's `duration_minutes`; and the slot's
    `confirmed_official_count` is reset to 0."
    PRD §2.8: "`accepted_entry_count` and `available_slots` on a sport event always sum
    to `capacity`, and `available_slots` is never negative."

    Four links fall out of one withdrawal: the athlete becomes `WITHDRAWN`;
    their `ACCEPTED` entry becomes `WITHDRAWN`, returning one slot of capacity so
    `accepted_entry_count` falls to 1 and `available_slots` rises to 7; the event
    drops to `UNDERSUBSCRIBED` because 1 is below its staging floor of 2; and the
    event's still-`SCHEDULED` slot is `RELEASED` even though the request never
    named it.

    Design: Difficulty/transitive_cascade/athlete_withdraw_cascades_entry_event_slot_and_bed_night_ledger
    """
    ctx = _two_accepted_athletes_one_slot_one_stay()

    withdrawn = validate_success(
        api_client.withdraw_athlete(
            ctx["first"]["athlete"]["id"], ADMIN, {"reason": WITHDRAW_REASON}
        )
    )

    assert withdrawn["registration_status"] == "WITHDRAWN"
    assert get_entry(ctx["first"]["entry"]["id"])["status"] == "WITHDRAWN"
    event = get_event(ctx["event"]["id"])
    assert event["accepted_entry_count"] == 1
    assert event["available_slots"] == 7
    assert event["status"] == "UNDERSUBSCRIBED"
    slot = get_slot(ctx["slot"]["id"])
    assert slot["status"] == "RELEASED"
    assert slot["confirmed_official_count"] == 0


def test_the_withdrawal_cancels_the_stay_and_rebates_the_bed_night_ledger():
    """PRD §3.2: "Alongside the five links, every village stay of the athlete in `RESERVED`
    or `CHECKED_IN` is cancelled, each cancellation debiting that stay's `nights` from
    the block's `reserved_bed_nights`."
    PRD §3.8: "A cancellation debits the block's `reserved_bed_nights` by exactly the
    stay's own `nights` — the precise compensating action of the reservation — and
    zeroes the stay's `total_charge_cents`, so a cancelled booking bills nothing."
    PRD §2.8: "`reserved_bed_nights` on an accommodation block rises by a stay's
    `nights` on reservation and falls by exactly that figure on cancellation."

    A parallel branch of the same cascade cancels the athlete's `RESERVED`
    stay, zeroes its `total_charge_cents` so a cancelled booking bills nothing,
    and debits the block's `reserved_bed_nights` by exactly the stay's own five
    nights, back to 0.

    Design: Difficulty/transitive_cascade/athlete_withdraw_cascades_entry_event_slot_and_bed_night_ledger
    """
    ctx = _two_accepted_athletes_one_slot_one_stay()

    api_client.withdraw_athlete(
        ctx["first"]["athlete"]["id"], ADMIN, {"reason": WITHDRAW_REASON}
    )

    stay = get_stay(ctx["stay"]["id"])
    assert stay["status"] == "CANCELLED"
    assert stay["total_charge_cents"] == 0
    assert get_block(ctx["block"]["id"])["reserved_bed_nights"] == 0


def test_the_withdrawal_cascade_is_scoped_to_the_withdrawing_athlete():
    """PRD §3.2: "From `REGISTERED`, withdrawal fires the full five-link cascade: the
    athlete moves `REGISTERED` → `WITHDRAWN`; every entry of theirs in `SUBMITTED`,
    `UNDER_REVIEW`, `REVISION_REQUESTED`, `ACCEPTED`, `WAITLISTED` or `MEDICAL_HOLD`
    moves to `WITHDRAWN`, and each entry leaving `ACCEPTED` decrements its event's
    `accepted_entry_count` by one and increments that event's `available_slots` by one;
    each such event whose `accepted_entry_count` has fallen below its
    `min_entries_to_stage` moves to `UNDERSUBSCRIBED`; each event so moved releases
    every session slot of that event still `SCHEDULED`; and each released slot releases
    every personnel assignment on it in `ASSIGNED` or `CONFIRMED`, each release debiting
    that person's `assigned_minutes_total` by the assignment's `duration_minutes`."
    PRD §2.9: "Each of these steps is a real transition on a real row: it sets that
    row's status, refreshes that row's `updated_at`, and increments that row's `version`
    independently of every other row touched in the same request."
    PRD §3.2: "On success the recomputed `fee_total_cents` and `fee_breakdown` are
    stored, `fee_paid_cents` is set equal to `fee_total_cents`, and the registration
    dimension advances `PENDING_PAYMENT` → `REGISTERED`."

    The unwind reaches only rows belonging to the named athlete: the second
    athlete's entry is still `ACCEPTED` and their registration and payment stand.
    Nor is any fee reversed for the withdrawing athlete — the settlement figures
    are left exactly as they were.

    Design: Difficulty/transitive_cascade/athlete_withdraw_cascades_entry_event_slot_and_bed_night_ledger
    """
    ctx = _two_accepted_athletes_one_slot_one_stay()

    api_client.withdraw_athlete(
        ctx["first"]["athlete"]["id"], ADMIN, {"reason": WITHDRAW_REASON}
    )

    assert get_entry(ctx["second"]["entry"]["id"])["status"] == "ACCEPTED"
    second = get_athlete(ctx["second"]["athlete"]["id"])
    assert second["registration_status"] == "REGISTERED"
    assert second["fee_paid_cents"] == 15500
    first = get_athlete(ctx["first"]["athlete"]["id"])
    assert first["fee_paid_cents"] == 15500
    assert first["fee_total_cents"] == 15500
