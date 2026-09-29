"""Rule breadth: each declared gate refused on violation, satisfied on the
boundary, skipped when its condition does not hold, and ordered against its
neighbours in the precedence ladder."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    athlete_payload,
    close_venue,
    create_accommodation_block,
    create_athlete,
    create_entry,
    create_personnel,
    create_session_slot,
    create_sport,
    create_sport_event,
    create_venue,
    get_athlete,
    get_block,
    get_edition,
    get_entry,
    get_event,
    get_person,
    get_slot,
    get_venue,
    pay_fees_for,
    personnel_assignment_payload,
    review_entry,
    screen_athlete,
    session_slot_payload,
    set_clock,
    setup_open_edition,
    setup_open_edition_high_contact,
    sport_entry_payload,
    validate_error,
    validate_paginated,
    validate_success,
    venue_payload,
    village_stay_payload,
)

ADMIN = TEST_USERS["games_admin_headers"]
OFFICER = TEST_USERS["registration_officer_headers"]


def test_the_deadline_bites_on_the_clock_alone_while_registration_is_still_open(clock_at_epoch):
    """PRD §2.10: "The logical clock is strictly before the edition's
    `registration_deadline_utc` — otherwise `ERR_REGISTRATION_DEADLINE_PASSED` (HTTP
    422)."
    PRD §3.2: "Registration is only accepted while the edition is `REGISTRATION_OPEN`
    and while the logical clock is strictly before `registration_deadline_utc`."
    PRD §3.3: "The edition must be `REGISTRATION_OPEN` and the logical clock strictly
    before `registration_deadline_utc`."
    PRD §3.9: "From `REGISTRATION_OPEN` the run moves the edition to
    `REGISTRATION_CLOSED` when the logical clock has reached the
    `registration_deadline_utc`."

    One second past registration_deadline_utc both athlete creation and entry
    creation are refused, though the edition is still REGISTRATION_OPEN.

    Design: Corner/validations/corner_validation_athlete_create_after_deadline_rejected
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed, event = base["edition"], base["event"]
    in_time = create_athlete(ed["id"], full_name="Ada Fenn")

    set_clock("2026-08-26T00:00:00Z")

    validate_error(
        api_client.create_athlete(
            athlete_payload(ed["id"], full_name="Late Lena"), OFFICER
        ),
        ApiErrorId.ERR_REGISTRATION_DEADLINE_PASSED.value,
        422,
    )
    validate_error(
        api_client.create_sport_entry(
            sport_entry_payload(in_time["id"], event["id"]), OFFICER
        ),
        ApiErrorId.ERR_REGISTRATION_DEADLINE_PASSED.value,
        422,
    )

    # No checkpoint run was needed to make the deadline bite.
    still_open = get_edition(ed["id"])
    assert still_open["status"] == "REGISTRATION_OPEN"
    assert still_open["ops_epoch"] == 0

    _, athlete_meta = validate_paginated(
        api_client.list_athletes(OFFICER, {"games_edition_id": ed["id"]})
    )
    assert athlete_meta["total_count"] == 1

    _, entry_meta = validate_paginated(
        api_client.list_sport_entries(OFFICER, {"athlete_id": in_time["id"]})
    )
    assert entry_meta["total_count"] == 0


def test_a_stay_that_runs_outside_the_village_window_is_refused(clock_at_epoch):
    """PRD §3.8: "The stay must sit inside the village window, which opens two days before
    the edition's `competition_start_date` and closes two days after its
    `competition_end_date`: both the `check_in_date` and the `check_out_date` must fall
    within that inclusive span, and a booking that runs outside it in either direction
    is refused with `ERR_STAY_OUTSIDE_VILLAGE_WINDOW`."
    PRD §2.10: "A village stay lies inside the village window and `check_out_date` is
    strictly after `check_in_date` — otherwise `ERR_STAY_OUTSIDE_VILLAGE_WINDOW` (HTTP
    422)."
    PRD §3.8: "It is reserved either by the athlete themselves or by a `GamesAdmin`,
    naming `athlete_id`, `accommodation_block_id`, a `check_in_date`, a `check_out_date`
    strictly later than the check-in date, and an `expected_block_version` that must
    equal the block's current `version`; a stale figure is refused with
    `ERR_STALE_BLOCK_VERSION`, and a successful reservation increments the block's
    `version`."
    PRD §3.8: "A block carries one ledger, `reserved_bed_nights`, which starts at zero
    and holds the sum of the `nights` of every stay in that block whose status is
    `RESERVED`, `CHECKED_IN` or `COMPLETED`."

    The window is the two days either side of the competition dates: an early
    arrival, a late departure and a zero-night booking are all refused.

    Design: Corner/validations/corner_validation_village_stay_outside_window_rejected
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed = base["edition"]
    athlete = create_athlete(ed["id"], full_name="Ada Fenn")
    block = create_accommodation_block(
        ed["id"], name="Birch Hall", bed_capacity=4, nightly_rate_cents=12000
    )

    def _attempt(check_in, check_out):
        return api_client.create_village_stay(
            village_stay_payload(
                athlete["id"], block["id"], block["version"],
                check_in_date=check_in, check_out_date=check_out,
            ),
            ADMIN,
        )

    # The window runs 2026-09-08 through 2026-09-22 inclusive.
    validate_error(
        _attempt("2026-09-07", "2026-09-12"),
        ApiErrorId.ERR_STAY_OUTSIDE_VILLAGE_WINDOW.value, 422,
    )
    validate_error(
        _attempt("2026-09-18", "2026-09-23"),
        ApiErrorId.ERR_STAY_OUTSIDE_VILLAGE_WINDOW.value, 422,
    )
    # check_out_date must be strictly later than check_in_date.
    validate_error(
        _attempt("2026-09-12", "2026-09-12"),
        ApiErrorId.ERR_STAY_OUTSIDE_VILLAGE_WINDOW.value, 422,
    )

    # A refused stay reserves no night and does not spend the block's OCC token.
    untouched = get_block(block["id"])
    assert untouched["reserved_bed_nights"] == 0
    assert untouched["version"] == block["version"]

    _, meta = validate_paginated(
        api_client.list_village_stays(ADMIN, {"accommodation_block_id": block["id"]})
    )
    assert meta["total_count"] == 0


def test_a_stay_sitting_exactly_on_both_window_edges_is_accepted(clock_at_epoch):
    """PRD §3.8: "The stay must sit inside the village window, which opens two days before
    the edition's `competition_start_date` and closes two days after its
    `competition_end_date`: both the `check_in_date` and the `check_out_date` must fall
    within that inclusive span, and a booking that runs outside it in either direction
    is refused with `ERR_STAY_OUTSIDE_VILLAGE_WINDOW`."
    PRD §3.8: "Enumerate the nights of the candidate stay: each calendar date from the
    `check_in_date`, included, up to but not including the `check_out_date` — so the
    night of departure is never occupied and a stay of one night touches exactly one
    date."
    PRD §3.8: "Where the booking is accepted, the service derives the rest: `nights` is
    the whole number of days from the `check_in_date` to the `check_out_date`,
    `total_charge_cents` is that night count multiplied by the block's
    `nightly_rate_cents` — snapshotted at reservation so a later change to the block's
    nightly rate never rewrites an existing stay's charge — and the block's
    `reserved_bed_nights` is increased by the same night count."
    PRD §3.8: "It is reserved either by the athlete themselves or by a `GamesAdmin`,
    naming `athlete_id`, `accommodation_block_id`, a `check_in_date`, a `check_out_date`
    strictly later than the check-in date, and an `expected_block_version` that must
    equal the block's current `version`; a stale figure is refused with
    `ERR_STALE_BLOCK_VERSION`, and a successful reservation increments the block's
    `version`."

    2026-09-08 to 2026-09-22 is inside the inclusive window: 14 nights, since
    the check-out night is never occupied, at 12000 cents each.

    Design: Corner/validations/corner_validation_village_stay_on_window_edges_passes
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed = base["edition"]
    athlete = create_athlete(ed["id"], full_name="Ada Fenn")
    block = create_accommodation_block(
        ed["id"], name="Birch Hall", bed_capacity=4, nightly_rate_cents=12000
    )

    stay = validate_success(
        api_client.create_village_stay(
            village_stay_payload(
                athlete["id"], block["id"], block["version"],
                check_in_date="2026-09-08", check_out_date="2026-09-22",
            ),
            ADMIN,
        ),
        201,
    )
    assert stay["status"] == "RESERVED"
    # 2026-09-08 through 2026-09-21 inclusive; the night of 2026-09-22 is not slept.
    assert stay["nights"] == 14
    assert stay["total_charge_cents"] == 168000

    settled = get_block(block["id"])
    assert settled["reserved_bed_nights"] == 14
    assert settled["version"] == block["version"] + 1


def test_the_age_band_is_matched_by_code_equality_not_by_containment(clock_at_epoch):
    """PRD §3.3: "The target event's `age_group_code` must equal the athlete's computed
    `age_group_code`, and the sport's `min_age` must be no greater than the athlete's
    basis age; an `AGE_EXEMPT` entry additionally demands a basis age of at least 75,
    the age-exemption floor."
    PRD §3.3: "Any of those three failures is refused with `ERR_AGE_GROUP_MISMATCH`."
    PRD §3.2: "Otherwise the band floor is 50 plus five years for each complete
    five-year step the basis age sits above 50, and the code is that floor joined by a
    hyphen to the floor plus four — so a basis age of 67 gives the floor 65 and the code
    `65-69`."
    PRD §3.2: "`age_at_reference` applies that count from `date_of_birth` to the
    edition's `age_reference_date`, and `age_at_first_day` applies it from
    `date_of_birth` to the edition's `competition_start_date`."

    A 65-year-old is refused on the 60-64 event and admitted on the 65-69 event.

    Design: Corner/validations/corner_validation_entry_age_group_mismatch_rejected
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed, sp, ev_60 = base["edition"], base["sport"], base["event"]
    ev_65 = create_sport_event(
        sp["id"], ed["id"], event_code="T200M", age_group_code="65-69",
        min_entries_to_stage=1,
    )

    athlete = create_athlete(
        ed["id"], full_name="Gus Errante", date_of_birth="1961-04-10"
    )
    assert athlete["age_at_reference"] == 65
    assert athlete["age_group_code"] == "65-69"

    validate_error(
        api_client.create_sport_entry(
            sport_entry_payload(athlete["id"], ev_60["id"]), OFFICER
        ),
        ApiErrorId.ERR_AGE_GROUP_MISMATCH.value,
        422,
    )

    admitted = validate_success(
        api_client.create_sport_entry(
            sport_entry_payload(athlete["id"], ev_65["id"]), OFFICER
        ),
        201,
    )
    assert admitted["status"] == "SUBMITTED"

    _, meta = validate_paginated(
        api_client.list_sport_entries(OFFICER, {"athlete_id": athlete["id"]})
    )
    assert meta["total_count"] == 1


def test_the_certification_gate_tests_level_and_badge_and_spares_volunteers(clock_at_epoch):
    """PRD §3.6: "When the person's `personnel_type` is `OFFICIAL`, their
    `certification_level` must be at least the `required_certification_level` of the
    sport that owns the slot's event, and that sport's `sport_code` must appear in their
    `certified_sport_codes`; failing either half is refused with
    `ERR_CERTIFICATION_INSUFFICIENT`."
    PRD §3.6: "Volunteers are exempt from both halves of that gate — a volunteer with
    level 0 and an empty badge list may be assigned to any block — but volunteers do not
    count toward a slot's confirmed official coverage."
    PRD §3.6: "The service derives `duration_minutes` from the slot's own interval — the
    whole minutes from the slot's `start_utc` to its `end_utc`, with the teardown buffer
    playing no part — and credits the person's `assigned_minutes_total` by that figure."

    An under-certified official and an official badged for another sport are
    both refused, while a volunteer with no badges at all is assigned.

    Design: Corner/validations/corner_validation_assignment_certification_insufficient_rejected
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed, sp, event = base["edition"], base["sport"], base["event"]
    venue = create_venue(ed["id"], name="North Oval", competition_area_count=4)
    slot = create_session_slot(venue["id"], event["id"], teardown_buffer_minutes=0)

    low = create_personnel(
        ed["id"], full_name="Low Cert Lou", personnel_type="OFFICIAL",
        certification_level=1, certified_sport_codes=[sp["sport_code"]],
    )
    wrong = create_personnel(
        ed["id"], full_name="Wrong Sport Wren", personnel_type="OFFICIAL",
        certification_level=3, certified_sport_codes=["SWIM"],
    )
    volunteer = create_personnel(
        ed["id"], full_name="Vera Volunteer", personnel_type="VOLUNTEER",
        certification_level=0, certified_sport_codes=[],
    )

    # Level 1 against the sport's required level of 2.
    validate_error(
        api_client.create_personnel_assignment(
            personnel_assignment_payload(low["id"], slot["id"]), ADMIN
        ),
        ApiErrorId.ERR_CERTIFICATION_INSUFFICIENT.value,
        422,
    )
    # Level 3, but the sport's own code is absent from the badge list.
    validate_error(
        api_client.create_personnel_assignment(
            personnel_assignment_payload(wrong["id"], slot["id"]), ADMIN
        ),
        ApiErrorId.ERR_CERTIFICATION_INSUFFICIENT.value,
        422,
    )
    # Volunteers are exempt from both halves of the gate.
    assigned = validate_success(
        api_client.create_personnel_assignment(
            personnel_assignment_payload(
                volunteer["id"], slot["id"], role_at_event="MARSHAL"
            ),
            ADMIN,
        ),
        201,
    )
    assert assigned["duration_minutes"] == 60

    assert get_person(low["id"])["assigned_minutes_total"] == 0
    assert get_person(wrong["id"])["assigned_minutes_total"] == 0
    assert get_person(volunteer["id"])["assigned_minutes_total"] == 60
    # The volunteer is unconfirmed, and would not count as an official anyway.
    assert get_slot(slot["id"])["confirmed_official_count"] == 0


def test_the_duplicate_entry_guard_watches_live_entries_and_not_history(clock_at_epoch):
    """PRD §3.3: "The athlete must not already hold another entry on the same
    `sport_event_id` in any of `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`,
    `ACCEPTED`, `WAITLISTED` or `MEDICAL_HOLD`, a second live entry being refused with
    `ERR_DUPLICATE_ENTRY`."
    PRD §3.3: "Withdrawal of a single entry is available to the `Athlete` or to a
    `RegistrationOfficer`, takes an optional `reason`, and is admissible from
    `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, `WAITLISTED`, `ACCEPTED` and
    `MEDICAL_HOLD`."
    PRD §3.3: "From the four states that hold no capacity the move to `WITHDRAWN` is
    bookkeeping only."
    PRD §3.2: "Fee settlement is recomputed from scratch at payment time — never at
    entry time — and its six steps are evaluated in a pinned order, because the discount
    tier keys on the number of entries while the surcharge tier keys on the amount the
    discount itself produces."

    A second live entry on the same event is refused, but once the first entry
    is withdrawn the same athlete may enter that event again.

    Design: Corner/validations/corner_validation_duplicate_entry_on_same_event_rejected
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed, event = base["edition"], base["event"]
    athlete = create_athlete(ed["id"], full_name="Ada Fenn")
    first = create_entry(athlete["id"], event["id"])

    validate_error(
        api_client.create_sport_entry(
            sport_entry_payload(athlete["id"], event["id"]), OFFICER
        ),
        ApiErrorId.ERR_DUPLICATE_ENTRY.value,
        409,
    )

    validate_success(
        api_client.withdraw_sport_entry(
            first["id"], OFFICER, {"reason": "re-entering with a different declaration"}
        )
    )

    second = validate_success(
        api_client.create_sport_entry(
            sport_entry_payload(athlete["id"], event["id"]), OFFICER
        ),
        201,
    )
    assert second["id"] != first["id"]
    assert second["status"] == "SUBMITTED"

    rows, meta = validate_paginated(
        api_client.list_sport_entries(OFFICER, {"athlete_id": athlete["id"]})
    )
    assert meta["total_count"] == 2
    assert sorted(row["status"] for row in rows) == ["SUBMITTED", "WITHDRAWN"]

    # The fee is only ever computed by the payment call, which never ran.
    assert get_athlete(athlete["id"])["fee_total_cents"] == 0


def test_two_individually_valid_entries_collide_on_a_capacity_of_one(clock_at_epoch):
    """PRD §3.3: "`ACCEPT` moves it `UNDER_REVIEW` → `ACCEPTED`, and is the transition that
    consumes capacity: it requires the athlete's `registration_status` to be
    `REGISTERED` — otherwise `ERR_ATHLETE_NOT_REGISTERED` — the athlete's
    `medical_status` to be one of `SCREENED_CLEARED`, `SCREENED_RESTRICTED` or
    `CLEARED_BY_APPEAL`, the event's `available_slots` to be greater than zero —
    otherwise `ERR_EVENT_CAPACITY_FULL` — and the athlete's already-scheduled
    competition blocks to still satisfy the recovery-gap rule described in §3.5."
    PRD §3.3: "On success it stores the `review_note`, increments the event's
    `accepted_entry_count` by one, decrements the event's `available_slots` by one, and
    lifts the event `UNDERSUBSCRIBED` → `OPEN` when the acceptance brings
    `accepted_entry_count` up to `min_entries_to_stage`."
    PRD §3.3: "`WAITLIST` moves it `UNDER_REVIEW` → `WAITLISTED` and stores the
    `review_note`, consuming no capacity."
    PRD §2.8: "`accepted_entry_count` and `available_slots` on a sport event always sum
    to `capacity`, and `available_slots` is never negative."

    The second ACCEPT is refused because the last free slot has gone, and the
    refusal leaves the entry where it was, still open to a WAITLIST decision.

    Design: Corner/validations/corner_validation_event_capacity_full_on_accept_rejected
    """
    base = setup_open_edition(event={"capacity": 1, "min_entries_to_stage": 1})
    ed, event = base["edition"], base["event"]

    lucky = create_athlete(ed["id"], full_name="Ada Fenn")
    unlucky = create_athlete(ed["id"], full_name="Bo Marsh")
    lucky_entry = create_entry(lucky["id"], event["id"])
    unlucky_entry = create_entry(unlucky["id"], event["id"])
    for athlete in (lucky, unlucky):
        pay_fees_for(athlete["id"], [event["entry_fee_cents"]])
        screen_athlete(athlete["id"])

    review_entry(lucky_entry["id"], "TAKE_UP")
    review_entry(lucky_entry["id"], "ACCEPT")
    review_entry(unlucky_entry["id"], "TAKE_UP")

    validate_error(
        api_client.review_sport_entry(unlucky_entry["id"], {"decision": "ACCEPT"}, OFFICER),
        ApiErrorId.ERR_EVENT_CAPACITY_FULL.value,
        409,
    )

    # The refused ACCEPT wrote nothing, so UNDER_REVIEW is still the origin state
    # a WAITLIST decision needs.
    waitlisted = review_entry(unlucky_entry["id"], "WAITLIST")
    assert waitlisted["status"] == "WAITLISTED"

    full = get_event(event["id"])
    assert full["accepted_entry_count"] == 1
    assert full["available_slots"] == 0
    assert get_entry(lucky_entry["id"])["status"] == "ACCEPTED"


def test_the_medical_bay_requirement_follows_the_sport_and_not_the_venue(clock_at_epoch):
    """PRD §3.5: "The **medical-coverage gate** refuses a slot whose event belongs to a
    sport whose `contact_class` is `HIGH` unless the venue's `has_onsite_medical_bay` is
    true, answering `ERR_MEDICAL_COVERAGE_REQUIRED`."
    PRD §3.5: "Each venue declares the emergency tier in force on site as
    `emergency_protocol_code`, one of `EP_BASIC`, `EP_ADVANCED` or `EP_CARDIAC`, and may
    optionally declare `has_onsite_medical_bay`, which defaults to false."
    PRD §3.5: "A new slot is `SCHEDULED` with `confirmed_official_count` at 0."

    The same window is refused for a high-contact event at a bay-less venue,
    accepted for that event at a venue with a bay, and accepted at the bay-less
    venue for a low-contact event.

    Design: Corner/validations/corner_validation_high_contact_slot_without_medical_bay_rejected
    """
    base = setup_open_edition_high_contact(event={"min_entries_to_stage": 1})
    ed, high_event = base["edition"], base["event"]
    low_sport = create_sport(name="Track and Field", contact_class="LOW")
    low_event = create_sport_event(
        low_sport["id"], ed["id"], event_code="T100M", min_entries_to_stage=1
    )

    bay_less_payload = venue_payload(
        ed["id"], name="Field House", competition_area_count=4, spectator_capacity=300
    )
    bay_less_payload.pop("has_onsite_medical_bay")
    bay_less = validate_success(api_client.create_venue(bay_less_payload, ADMIN), 201)
    with_bay = create_venue(
        ed["id"], name="North Oval", competition_area_count=4,
        has_onsite_medical_bay=True,
    )

    validate_error(
        api_client.create_session_slot(
            session_slot_payload(bay_less["id"], high_event["id"], teardown_buffer_minutes=0),
            ADMIN,
        ),
        ApiErrorId.ERR_MEDICAL_COVERAGE_REQUIRED.value,
        422,
    )

    housed = validate_success(
        api_client.create_session_slot(
            session_slot_payload(with_bay["id"], high_event["id"], teardown_buffer_minutes=0),
            ADMIN,
        ),
        201,
    )
    assert housed["status"] == "SCHEDULED"

    # The bay requirement is not a blanket rule about the venue.
    low_slot = validate_success(
        api_client.create_session_slot(
            session_slot_payload(bay_less["id"], low_event["id"], teardown_buffer_minutes=0),
            ADMIN,
        ),
        201,
    )

    assert get_venue(bay_less["id"])["has_onsite_medical_bay"] is False
    assert get_venue(with_bay["id"])["has_onsite_medical_bay"] is True

    rows, meta = validate_paginated(
        api_client.list_session_slots(ADMIN, {"venue_id": bay_less["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [low_slot["id"]]


def test_the_cardiac_protocol_is_demanded_by_the_band_floor_of_seventy_five(clock_at_epoch):
    """PRD §3.5: "The **emergency-protocol gate** looks at the lower bound of the event's
    `age_group_code` — 75 for `75-79`, and 100 for the open band `100+` — and refuses
    any slot whose event's band floor is 75 or above unless the venue's
    `emergency_protocol_code` is exactly `EP_CARDIAC`, answering
    `ERR_EMERGENCY_PROTOCOL_INSUFFICIENT`."
    PRD §3.5: "Each venue declares the emergency tier in force on site as
    `emergency_protocol_code`, one of `EP_BASIC`, `EP_ADVANCED` or `EP_CARDIAC`, and may
    optionally declare `has_onsite_medical_bay`, which defaults to false."
    PRD §3.5: "A new slot is `SCHEDULED` with `confirmed_official_count` at 0."

    A 75-79 event may only be placed at an EP_CARDIAC venue, while a 70-74 event
    is content with EP_ADVANCED.

    Design: Corner/validations/corner_validation_oldest_age_group_without_cardiac_protocol_rejected
    """
    base = setup_open_edition(
        event={"age_group_code": "75-79", "min_entries_to_stage": 1}
    )
    ed, sp, ev_75 = base["edition"], base["sport"], base["event"]
    ev_70 = create_sport_event(
        sp["id"], ed["id"], event_code="T200M", age_group_code="70-74",
        min_entries_to_stage=1,
    )

    basic = create_venue(
        ed["id"], name="Community Track", competition_area_count=4,
        spectator_capacity=200, emergency_protocol_code="EP_BASIC",
    )
    advanced = create_venue(
        ed["id"], name="North Oval", competition_area_count=4,
        emergency_protocol_code="EP_ADVANCED",
    )
    cardiac = create_venue(
        ed["id"], name="Memorial Stadium", competition_area_count=4,
        spectator_capacity=900, emergency_protocol_code="EP_CARDIAC",
    )

    for venue in (basic, advanced):
        validate_error(
            api_client.create_session_slot(
                session_slot_payload(venue["id"], ev_75["id"], teardown_buffer_minutes=0),
                ADMIN,
            ),
            ApiErrorId.ERR_EMERGENCY_PROTOCOL_INSUFFICIENT.value,
            422,
        )

    placed = validate_success(
        api_client.create_session_slot(
            session_slot_payload(cardiac["id"], ev_75["id"], teardown_buffer_minutes=0),
            ADMIN,
        ),
        201,
    )
    assert placed["status"] == "SCHEDULED"

    # The comparison is against a floor of 75, so 70-74 clears at EP_ADVANCED.
    validate_success(
        api_client.create_session_slot(
            session_slot_payload(
                advanced["id"], ev_70["id"],
                start_utc="2026-09-12T11:00:00Z", end_utc="2026-09-12T12:00:00Z",
                teardown_buffer_minutes=0,
            ),
            ADMIN,
        ),
        201,
    )

    _, meta = validate_paginated(
        api_client.list_session_slots(ADMIN, {"venue_id": basic["id"]})
    )
    assert meta["total_count"] == 0


def test_neither_a_new_slot_nor_a_moved_slot_may_land_at_a_closed_venue(clock_at_epoch):
    """PRD §2.10: "The venue named for a session slot is `OPEN` — otherwise
    `ERR_VENUE_CLOSED` (HTTP 409)."
    PRD §2.10: "This guards slot creation, slot rescheduling and slot advancement."
    PRD §3.5: "A `GamesAdmin` closing a venue supplies a `reason`, which is stored as
    the venue's `closed_reason` as the venue moves `OPEN` → `CLOSED`, and three links
    then fire."
    PRD §3.5: "First, every slot at that venue whose status is `SCHEDULED` or
    `IN_PROGRESS` moves to `DISPLACED`."
    PRD §3.5: "The target venue must be `OPEN`, `end_utc` must be strictly later than
    `start_utc`, and the new interval must clear the venue-area gate at the target venue
    — with the slot being moved excluded from its own comparison set — the
    medical-coverage gate, the emergency-protocol gate and the athlete recovery gate for
    every `ACCEPTED` entry of the slot's event."

    Validity here depends on another row's state: the same window that was
    accepted while a venue was open is refused once any venue is closed, both for
    a fresh slot and for a slot being moved.

    Design: Corner/validations/corner_validation_slot_write_at_closed_venue_rejected
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed, event = base["edition"], base["event"]
    host = create_venue(ed["id"], name="North Oval", competition_area_count=4)
    doomed = create_venue(ed["id"], name="Field House", competition_area_count=4)

    # The identical payload is accepted while the venue is open.
    slot = create_session_slot(host["id"], event["id"], teardown_buffer_minutes=0)
    assert slot["status"] == "SCHEDULED"

    shut = close_venue(doomed["id"], reason="roof inspection")
    assert shut["status"] == "CLOSED"
    assert shut["closed_reason"] == "roof inspection"

    # Closing the slot's own venue displaces it, which is the only state a
    # reschedule may start from.
    close_venue(host["id"], reason="storm damage")
    assert get_slot(slot["id"])["status"] == "DISPLACED"

    validate_error(
        api_client.create_session_slot(
            session_slot_payload(
                doomed["id"], event["id"],
                start_utc="2026-09-13T09:00:00Z", end_utc="2026-09-13T10:00:00Z",
                teardown_buffer_minutes=0,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_VENUE_CLOSED.value,
        409,
    )

    validate_error(
        api_client.reschedule_session_slot(
            slot["id"],
            {
                "venue_id": doomed["id"],
                "start_utc": "2026-09-13T09:00:00Z",
                "end_utc": "2026-09-13T10:00:00Z",
                "teardown_buffer_minutes": 0,
            },
            ADMIN,
        ),
        ApiErrorId.ERR_VENUE_CLOSED.value,
        409,
    )

    # The refused reschedule wrote nothing at all.
    untouched = get_slot(slot["id"])
    assert untouched["venue_id"] == host["id"]
    assert untouched["status"] == "DISPLACED"
    assert untouched["start_utc"].startswith("2026-09-12T09:00:00")

    _, meta = validate_paginated(
        api_client.list_session_slots(ADMIN, {"venue_id": doomed["id"]})
    )
    assert meta["total_count"] == 0


def test_pagination_bounds_are_refused_outside_one_through_one_hundred(clock_at_epoch):
    """PRD §2.3: "`limit` sets the maximum number of rows returned; when omitted it
    defaults to 10, its minimum accepted value is 1 and its maximum accepted value is
    100."
    PRD §2.3: "`offset` sets how many rows to skip; when omitted it defaults to 0, and
    its minimum accepted value is 0."
    PRD §2.3: "A `limit` that is not an integer or falls outside 1 through 100, or an
    `offset` that is not an integer or is negative, is refused with
    `ERR_INVALID_PAGINATION` (HTTP 400)."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope."

    limit 101, limit 0 and offset -1 are each refused, while limit 100 with
    offset 0 is accepted and omitting both falls back to the default limit of 10.

    Design: Corner/validations/corner_validation_invalid_pagination_rejected
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed = base["edition"]
    create_athlete(ed["id"], full_name="Ada Fenn")

    for params in (
        {"games_edition_id": ed["id"], "limit": 101},
        {"games_edition_id": ed["id"], "limit": 0},
        {"games_edition_id": ed["id"], "offset": -1},
    ):
        validate_error(
            api_client.list_athletes(OFFICER, params),
            ApiErrorId.ERR_INVALID_PAGINATION.value,
            400,
        )

    # 100 is inside the accepted range, and 0 is an acceptable offset.
    _, wide = validate_paginated(
        api_client.list_athletes(
            OFFICER, {"games_edition_id": ed["id"], "limit": 100, "offset": 0}
        )
    )
    assert wide["total_count"] == 1
    assert wide["has_more"] is False
    assert wide["limit"] == 100
    assert wide["offset"] == 0

    _, defaulted = validate_paginated(
        api_client.list_athletes(OFFICER, {"games_edition_id": ed["id"]})
    )
    assert defaulted["total_count"] == 1
    assert defaulted["has_more"] is False
    assert defaulted["limit"] == 10
    assert defaulted["offset"] == 0


def test_the_role_gate_answers_before_the_path_is_ever_resolved(clock_at_epoch):
    """PRD §2.10: "The acting role is authorised for the endpoint called — otherwise
    `ERR_ROLE_NOT_PERMITTED`."
    PRD §2.10: "Every identifier in the request path resolves, left to right — otherwise
    the matching not-found error."
    PRD §2.1: "Every single-resource read and every list read is available to all seven
    roles; write access is per-endpoint, and a role that is not listed for the endpoint
    it calls is refused with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §3.5: "A `GamesAdmin` closing a venue supplies a `reason`, which is stored as
    the venue's `closed_reason` as the venue moves `OPEN` → `CLOSED`, and three links
    then fire."

    An unauthorised caller gets the same refusal for a real venue id and for one
    that does not exist, so nothing about existence leaks; the authorised caller
    reaches the not-found answer.

    Design: Corner/validations/corner_validation_priority_role_check_precedes_path_not_found
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed = base["edition"]
    venue = create_venue(ed["id"], name="North Oval", competition_area_count=4)

    validate_error(
        api_client.close_venue(
            NON_EXISTENT_UUID, {"reason": "probing an unknown id"}, OFFICER
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api_client.close_venue(venue["id"], {"reason": "probing a real id"}, OFFICER),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )

    # Once the role gate passes, the path is resolved and answers honestly.
    validate_error(
        api_client.close_venue(
            NON_EXISTENT_UUID, {"reason": "same unknown id with the right role"}, ADMIN
        ),
        ApiErrorId.ERR_VENUE_NOT_FOUND.value,
        404,
    )

    intact = get_venue(venue["id"])
    assert intact["status"] == "OPEN"
    assert intact["closed_reason"] is None
