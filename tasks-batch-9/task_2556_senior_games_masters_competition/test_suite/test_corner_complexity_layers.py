"""Cross-cutting breadth: the three optimistic-concurrency guards, the version
discipline they rest on, and the checkpoint that owns waitlist promotion."""
from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH_UTC,
    TEST_USERS,
    advance_slot,
    age_group_record_payload,
    api_client,
    confirm_assignment,
    create_accommodation_block,
    create_assignment,
    create_athlete,
    create_certified_official,
    create_edition,
    create_entry,
    create_session_slot,
    create_sponsorship_commitment,
    create_sport,
    create_sport_event,
    create_venue,
    get_athlete,
    get_block,
    get_commitment,
    get_edition,
    get_entry,
    get_event,
    get_record,
    make_records_ratifier_headers,
    ops_run,
    pay_fees,
    review_entry,
    screen_athlete,
    seed_event,
    set_clock,
    setup_accepted_entry,
    setup_open_edition,
    submit_result,
    take_up_and_accept,
    validate_error,
    validate_paginated,
    validate_success,
    verify_result,
)

ADMIN = TEST_USERS["games_admin_headers"]
OFFICER = TEST_USERS["registration_officer_headers"]
SPONSOR = TEST_USERS["sponsor_liaison_headers"]
CLAIMER = "rr-nolan"


def test_a_sibling_record_claim_makes_the_second_claims_event_version_stale(clock_at_epoch):
    """PRD §2.7: "Filing an age-group record claim requires `expected_sport_event_version`
    carrying the client's last observed `version` of the parent `SportEvent`."
    PRD §2.7: "A mismatch against the event's current `version` is rejected with
    `ERR_STALE_SPORT_EVENT_VERSION` (HTTP 412)."
    PRD §2.7: "The guard exists because another writer may already have filed and
    ratified a claim in the same event scope, which legitimately supersedes the prior
    record and rewrites the event's `current_record_id`; a client working from an older
    view of the event would compute the wrong `superseded_record_id`."
    PRD §3.7: "The claim names its `sport_event_id`, the `competition_result_id` it
    cites, the `claimed_by_user_id` of the person filing it, and an
    `expected_sport_event_version` that must match the event's current `version` — a
    mismatch is `ERR_STALE_SPORT_EVENT_VERSION`, and a successful filing increments that
    event's `version`."
    PRD §3.7: "The service derives the rest of the row rather than trusting the client:
    `holder_athlete_id` from the athlete behind the cited mark's entry, `age_group_code`
    copied from the event, `mark_value` copied from the cited mark, and
    `superseded_record_id` set to whatever record the event's `current_record_id`
    currently names — the record this claim would displace — or null when no record yet
    stands."

    Two claims filed from one snapshot of the event: the first advances the parent
    version, the second is refused at 412, and the identical body succeeds once the
    version is re-read.

    Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_stale_sport_event_version_rejected
    """
    base = setup_open_edition(event={"capacity": 8, "min_entries_to_stage": 1})
    edition, sport, event = base["edition"], base["sport"], base["event"]
    first = setup_accepted_entry(edition["id"], event, full_name="Ada Fenn")
    second = setup_accepted_entry(edition["id"], event, full_name="Bo Marsh")
    seed_event(event["id"])

    venue = create_venue(edition["id"], name="North Oval", competition_area_count=4)
    official = create_certified_official(edition["id"], sport["sport_code"])
    slot = create_session_slot(
        venue["id"], event["id"], teardown_buffer_minutes=0, required_official_count=1
    )
    assignment = create_assignment(official["id"], slot["id"])
    confirm_assignment(assignment["id"], official["id"])
    set_clock("2026-09-12T09:00:00Z")
    advance_slot(slot["id"], "IN_PROGRESS")
    slower = submit_result(
        first["entry"]["id"], slot["id"], official["id"], mark_value=13.42, placement=2
    )
    faster = submit_result(
        second["entry"]["id"], slot["id"], official["id"], mark_value=13.1, placement=1
    )
    advance_slot(slot["id"], "COMPLETED")

    # No record stands yet, so both verifications take the record branch.
    assert verify_result(slower["id"])["status"] == "RECORD_PENDING"
    assert verify_result(faster["id"])["status"] == "RECORD_PENDING"

    snapshot_version = get_event(event["id"])["version"]
    ratifier = make_records_ratifier_headers(CLAIMER)

    accepted = validate_success(
        api_client.create_age_group_record(
            age_group_record_payload(
                event["id"], slower["id"], CLAIMER, snapshot_version
            ),
            ratifier,
        ),
        expected_status=201,
    )
    assert accepted["superseded_record_id"] is None

    # The parent moved because a sibling claim was filed, not because the event
    # itself was edited.
    stale = api_client.create_age_group_record(
        age_group_record_payload(event["id"], faster["id"], CLAIMER, snapshot_version),
        ratifier,
    )
    validate_error(
        stale, ApiErrorId.ERR_STALE_SPORT_EVENT_VERSION.value, expected_status=412
    )

    refreshed = get_event(event["id"])
    assert refreshed["version"] == snapshot_version + 1
    # Filing a claim never sets the record pointer, so the version advance the
    # guard detected came purely from the sibling write.
    assert refreshed["current_record_id"] is None
    _rows, meta = validate_paginated(
        api_client.list_age_group_records(ADMIN, {"sport_event_id": event["id"]})
    )
    assert meta["total_count"] == 1

    retried = validate_success(
        api_client.create_age_group_record(
            age_group_record_payload(
                event["id"], faster["id"], CLAIMER, refreshed["version"]
            ),
            ratifier,
        ),
        expected_status=201,
    )
    assert retried["status"] == "PENDING_RATIFICATION"
    assert float(retried["mark_value"]) == 13.1
    assert get_record(retried["id"])["competition_result_id"] == faster["id"]


def test_a_stale_block_version_is_answered_before_the_window_violation_it_hides(clock_at_epoch):
    """PRD §2.7: "Reserving a village stay requires `expected_block_version` carrying the
    client's last observed `version` of the parent `AccommodationBlock`."
    PRD §2.7: "A mismatch against the block's current `version` is rejected with
    `ERR_STALE_BLOCK_VERSION` (HTTP 412)."
    PRD §2.10: "The version guard field equals the parent's current `version` on the
    three guarded writes — otherwise `ERR_STALE_SPORT_EVENT_VERSION`,
    `ERR_STALE_BLOCK_VERSION` or `ERR_STALE_GAMES_EDITION_VERSION` as described in
    §2.7."
    PRD §2.10: "A village stay lies inside the village window and `check_out_date` is
    strictly after `check_in_date` — otherwise `ERR_STAY_OUTSIDE_VILLAGE_WINDOW` (HTTP
    422)."
    PRD §3.8: "The stay must sit inside the village window, which opens two days before
    the edition's `competition_start_date` and closes two days after its
    `competition_end_date`: both the `check_in_date` and the `check_out_date` must fall
    within that inclusive span, and a booking that runs outside it in either direction
    is refused with `ERR_STAY_OUTSIDE_VILLAGE_WINDOW`."
    PRD §3.8: "Where the booking is accepted, the service derives the rest: `nights` is
    the whole number of days from the `check_in_date` to the `check_out_date`,
    `total_charge_cents` is that night count multiplied by the block's
    `nightly_rate_cents` — snapshotted at reservation so a later change to the block's
    nightly rate never rewrites an existing stay's charge — and the block's
    `reserved_bed_nights` is increased by the same night count."

    The same body carries two defects: the 412 comes first, and only once the version
    is refreshed does the window violation surface as its own 422.

    Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_stale_block_version_rejected
    """
    base = setup_open_edition(event={"capacity": 8, "min_entries_to_stage": 1})
    edition = base["edition"]
    first_guest = create_athlete(edition["id"], full_name="Ada Fenn")
    second_guest = create_athlete(edition["id"], full_name="Bo Marsh")
    block = create_accommodation_block(
        edition["id"], name="Maple Hall", bed_capacity=2, nightly_rate_cents=12000,
        accessible_units=1,
    )
    # The bed-night ledger is a computed counter and starts empty.
    assert block["reserved_bed_nights"] == 0
    snapshot_version = block["version"]

    booked = validate_success(
        api_client.create_village_stay(
            {
                "athlete_id": first_guest["id"],
                "accommodation_block_id": block["id"],
                "check_in_date": "2026-09-09",
                "check_out_date": "2026-09-14",
                "expected_block_version": snapshot_version,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    # Five nights: the departure night is never occupied.
    assert booked["nights"] == 5
    assert booked["total_charge_cents"] == 60000

    out_of_window = {
        "athlete_id": second_guest["id"],
        "accommodation_block_id": block["id"],
        "check_in_date": "2026-09-05",
        "check_out_date": "2026-09-07",
    }
    stale = api_client.create_village_stay(
        dict(out_of_window, expected_block_version=snapshot_version), ADMIN
    )
    # The dates are outside the village window as well, but the version guard is
    # decided first.
    validate_error(stale, ApiErrorId.ERR_STALE_BLOCK_VERSION.value, expected_status=412)

    after_one = get_block(block["id"])
    assert after_one["version"] == snapshot_version + 1
    assert after_one["reserved_bed_nights"] == 5

    windowed = api_client.create_village_stay(
        dict(out_of_window, expected_block_version=after_one["version"]), ADMIN
    )
    # With a fresh version the hidden defect finally answers.
    validate_error(
        windowed, ApiErrorId.ERR_STAY_OUTSIDE_VILLAGE_WINDOW.value, expected_status=422
    )

    # The 422 incremented nothing, so the same version is still current.
    second_booking = validate_success(
        api_client.create_village_stay(
            {
                "athlete_id": second_guest["id"],
                "accommodation_block_id": block["id"],
                "check_in_date": "2026-09-09",
                "check_out_date": "2026-09-14",
                "expected_block_version": after_one["version"],
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert second_booking["nights"] == 5
    assert second_booking["total_charge_cents"] == 60000

    # Two reservations, two increments, ten bed-nights — and with two beds every
    # night of the overlapping pair stayed inside capacity.
    final = get_block(block["id"])
    assert final["version"] == snapshot_version + 2
    assert final["reserved_bed_nights"] == 10
    assert final["bed_capacity"] == 2


def test_a_stale_edition_version_stops_the_second_allocation_before_it_posts(clock_at_epoch):
    """PRD §2.7: "Allocating recognition for a sponsorship commitment requires
    `expected_games_edition_version` carrying the client's last observed `version` of
    the parent `GamesEdition`."
    PRD §2.7: "A mismatch against the edition's current `version` is rejected with
    `ERR_STALE_GAMES_EDITION_VERSION` (HTTP 412)."
    PRD §3.9: "The tier sets a recognition multiplier: `BRONZE` recognises the pledge at
    par, one times the pledged amount; `SILVER` at one and five hundredths; `GOLD` at
    one and twelve hundredths; and `PLATINUM` at one and a quarter."
    PRD §3.9: "The four buckets take fixed shares of the pledge and are filled in this
    declared order: `VENUE_SIGNAGE` takes forty percent, `ATHLETE_SERVICES` thirty
    percent, `MEDICAL_COVERAGE` twenty percent and `SOCIAL_PROGRAM` the remaining ten
    percent."
    PRD §3.9: "Each bucket's figure is computed independently as the `pledged_cents`
    multiplied by that bucket's share and by the tier multiplier, and each is then
    rounded to a whole number of cents on its own, with a half cent rounding upward."
    PRD §3.9: "The four rounded figures are stored as the `allocation_map`, keyed by
    bucket name, and `recognized_cents` is added to the edition's
    `sponsorship_recognized_cents` ledger."

    Two pledges read one edition version; the first allocation posts 120000 and the
    second is refused before its buckets are even computed.

    Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_stale_games_edition_version_rejected
    """
    edition = create_edition()
    assert edition["sponsorship_recognized_cents"] == 0
    bronze = create_sponsorship_commitment(
        edition["id"], sponsor_name="Prairie Mutual", sponsor_kind="CORPORATE",
        tier="BRONZE", pledged_cents=120000,
    )
    gold = create_sponsorship_commitment(
        edition["id"], sponsor_name="Springfield Utilities", sponsor_kind="MUNICIPAL",
        tier="GOLD", pledged_cents=400000,
    )
    assert bronze["status"] == gold["status"] == "PLEDGED"
    snapshot_version = get_edition(edition["id"])["version"]

    allocated = validate_success(
        api_client.allocate_sponsorship_commitment(
            bronze["id"], {"expected_games_edition_version": snapshot_version}, SPONSOR
        )
    )
    assert allocated["status"] == "ALLOCATED"
    # BRONZE multiplies by 1.00, so each bucket is just its own share.
    assert allocated["recognized_cents"] == 120000
    assert allocated["allocation_map"] == {
        "VENUE_SIGNAGE": 48000,
        "ATHLETE_SERVICES": 36000,
        "MEDICAL_COVERAGE": 24000,
        "SOCIAL_PROGRAM": 12000,
    }

    stale = api_client.allocate_sponsorship_commitment(
        gold["id"], {"expected_games_edition_version": snapshot_version}, SPONSOR
    )
    validate_error(
        stale, ApiErrorId.ERR_STALE_GAMES_EDITION_VERSION.value, expected_status=412
    )
    untouched = get_commitment(gold["id"])
    assert untouched["status"] == "PLEDGED"
    assert untouched["recognized_cents"] == 0
    assert untouched["allocation_map"] == {}

    refreshed = get_edition(edition["id"])
    assert refreshed["version"] == snapshot_version + 1
    assert refreshed["sponsorship_recognized_cents"] == 120000

    retried = validate_success(
        api_client.allocate_sponsorship_commitment(
            gold["id"], {"expected_games_edition_version": refreshed["version"]}, SPONSOR
        )
    )
    assert retried["status"] == "ALLOCATED"
    # GOLD multiplies each bucket by 1.12, rounded per bucket before the sum.
    assert retried["recognized_cents"] == 448000
    assert retried["allocation_map"] == {
        "VENUE_SIGNAGE": 179200,
        "ATHLETE_SERVICES": 134400,
        "MEDICAL_COVERAGE": 89600,
        "SOCIAL_PROGRAM": 44800,
    }

    reading = validate_success(api_client.get_economic_impact(edition["id"], SPONSOR))
    # Each allocation posted exactly once; the refused attempt posted nothing.
    assert reading["sponsorship_recognized_cents"] == 568000
    # Municipal support is a separate input ledger the allocation never touches.
    assert reading["municipal_support_cents"] == 0


def test_version_moves_once_per_write_to_that_row_and_never_on_a_read(clock_at_epoch):
    """PRD §2.5: "`version` is an integer that starts at 1 on creation and increments by
    one on every mutation of that row, including mutations the server performs on its
    own initiative as part of a cascade, and including mutations that only touch a
    derived counter such as `accepted_entry_count`, `confirmed_official_count`,
    `assigned_minutes_total`, `reserved_bed_nights` or `sponsorship_recognized_cents`."
    PRD §2.9: "Each of these steps is a real transition on a real row: it sets that
    row's status, refreshes that row's `updated_at`, and increments that row's `version`
    independently of every other row touched in the same request."
    PRD §3.9: "The run also increments the edition's `version` by one."
    PRD §3.9: "First, the edition's `ops_epoch` is incremented by one, stamping the
    run."
    PRD §3.1: "A newly created edition is `DRAFT`, its `ops_epoch` counter reads 0, both
    `sponsorship_recognized_cents` and `provisional_impact_cents` read 0, and
    `final_impact_cents` is null."
    PRD §2.4: "On process startup that clock reads exactly `2026-08-01T00:00:00Z`, and
    until a harness moves it, that is the instant every rule sees; falling back to real
    time is a defect."

    The premise every version guard rests on: reads are inert, child inserts naming
    the edition leave its version alone, and each accepted write moves it by one.

    Design: Corner/cross_cutting_complexity_layers/corner_layer_version_increments_on_every_write_and_reads_are_inert
    """
    assert clock_at_epoch["current_utc"].startswith(CLOCK_EPOCH_UTC[:19])
    edition = create_edition()
    opening_version = edition["version"]
    assert edition["ops_epoch"] == 0

    # A read is inert, so the version a client would put in a guard field survives.
    assert get_edition(edition["id"])["version"] == opening_version

    sport = create_sport()
    event = create_sport_event(sport["id"], edition["id"], min_entries_to_stage=1)
    # Children name the edition as their foreign key without writing to it.
    assert get_edition(edition["id"])["version"] == opening_version

    opened = validate_success(api_client.open_registration(edition["id"], ADMIN))
    assert opened["status"] == "REGISTRATION_OPEN"
    assert opened["version"] == opening_version + 1
    assert opened["ops_epoch"] == 0
    after_open = validate_success(api_client.get_games_edition(edition["id"], OFFICER))
    assert after_open["version"] == opened["version"]

    checkpointed = ops_run(edition["id"])
    # One checkpoint is one increment, not one per phase it executes.
    assert checkpointed["version"] == opening_version + 2
    # The two counters diverge on purpose: epochs count checkpoints, versions
    # count writes.
    assert checkpointed["ops_epoch"] == 1
    # The clock never left its starting instant, which is before the registration
    # deadline, so the checkpoint admitted no status step.
    assert checkpointed["status"] == "REGISTRATION_OPEN"
    after_run = validate_success(api_client.get_games_edition(edition["id"], SPONSOR))
    assert after_run["version"] == checkpointed["version"]

    # Version is per row, not a global sequence: the untouched event never moved.
    assert get_event(event["id"])["version"] == event["version"]


def test_a_freed_slot_waits_for_the_checkpoint_before_the_waitlist_moves(clock_at_epoch):
    """PRD §3.3: "From `ACCEPTED` it is not: the withdrawal decrements the event's
    `accepted_entry_count` by one, increments the event's `available_slots` by one, and
    drives the event to `UNDERSUBSCRIBED` when `accepted_entry_count` has fallen below
    `min_entries_to_stage`; it also carries the precondition that no competition result
    in `VERIFIED`, `RECORD_PENDING` or `PUBLISHED` cites the entry."
    PRD §3.9: "Third, waitlisted entries are promoted into whatever capacity now exists,
    event by event and candidate by candidate in the promotion ranking."
    PRD §3.3: "Within each event, the candidate set is that event's entries currently
    `WAITLISTED` whose athlete is `REGISTERED` and whose athlete's `medical_status` is
    one of `SCREENED_CLEARED`, `SCREENED_RESTRICTED` or `CLEARED_BY_APPEAL`."
    PRD §3.3: "Candidates are promoted in that rank order while the event still has
    `available_slots` greater than zero; each promotion moves the entry `WAITLISTED` →
    `ACCEPTED`, increments `accepted_entry_count` by one, decrements `available_slots`
    by one, and lifts the event `UNDERSUBSCRIBED` → `OPEN` when the floor is reached."
    PRD §3.3: "An event with no eligible candidate is simply skipped: that is not an
    error, and the checkpoint carries on."
    PRD §3.9: "Its head count, reported as `registered_heads`, is the number of athletes
    in the edition whose `registration_status` is `PENDING_PAYMENT`, `REGISTERED` or
    `CHECKED_IN` — everyone who has entered and not fallen away."

    The withdrawal frees the only seat and the candidate is fully eligible, yet the
    promotion happens only inside the ops-run — together with the event's recovery
    and the projection recompute.

    Design: Corner/cross_cutting_complexity_layers/corner_layer_ops_run_checkpoint_defers_waitlist_promotion_to_the_epoch
    """
    base = setup_open_edition(event={"capacity": 1, "min_entries_to_stage": 1})
    edition, event = base["edition"], base["event"]
    holder = create_athlete(edition["id"], full_name="Ada Fenn")
    candidate = create_athlete(edition["id"], full_name="Bo Marsh")
    held_entry = create_entry(holder["id"], event["id"])
    waiting_entry = create_entry(candidate["id"], event["id"])
    pay_fees(holder["id"], 15500)
    pay_fees(candidate["id"], 15500)
    screen_athlete(holder["id"])
    screen_athlete(candidate["id"])
    take_up_and_accept(held_entry["id"])
    review_entry(waiting_entry["id"], "TAKE_UP")
    assert review_entry(waiting_entry["id"], "WAITLIST")["status"] == "WAITLISTED"

    surrendered = validate_success(
        api_client.withdraw_sport_entry(
            held_entry["id"], OFFICER, {"reason": "travel cancelled"}
        )
    )
    assert surrendered["status"] == "WITHDRAWN"

    # The withdrawal freed the seat and dropped the event below its staging floor
    # in the same write.
    stranded = get_event(event["id"])
    assert stranded["status"] == "UNDERSUBSCRIBED"
    assert stranded["accepted_entry_count"] == 0
    assert stranded["available_slots"] == 1
    # A free seat and an eligible candidate are still not enough on their own.
    assert get_entry(waiting_entry["id"])["status"] == "WAITLISTED"

    first_run = ops_run(edition["id"])
    assert first_run["ops_epoch"] == 1
    assert get_entry(waiting_entry["id"])["status"] == "ACCEPTED"

    recovered = get_event(event["id"])
    assert recovered["status"] == "OPEN"
    assert recovered["accepted_entry_count"] == 1
    assert recovered["available_slots"] == 0

    # 2 heads + 3.6 accompanying = 5.6; 5.6 * 18500 * 4 = 414400; * 1.45 = 600880.
    # Withdrawing an entry left both registrations intact.
    assert first_run["provisional_impact_cents"] == 600880
    assert first_run["status"] == "REGISTRATION_OPEN"
    assert get_athlete(holder["id"])["registration_status"] == "REGISTERED"
    assert get_athlete(candidate["id"])["registration_status"] == "REGISTERED"

    # The waitlist is empty now, so the promotion phase is a declared no-op.
    second_run = ops_run(edition["id"])
    assert second_run["ops_epoch"] == 2
    assert second_run["provisional_impact_cents"] == 600880
    assert get_entry(waiting_entry["id"])["status"] == "ACCEPTED"
