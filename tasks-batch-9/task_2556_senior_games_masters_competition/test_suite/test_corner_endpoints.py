"""Endpoint breadth: the computed read, the action endpoints and their declared
side effects, conditional actions and cross-reference link creation."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    age_group_record_payload,
    allocate_commitment,
    api_client,
    create_athlete,
    create_entry,
    create_sponsorship_commitment,
    get_athlete,
    get_edition,
    get_entry,
    get_event,
    ops_run,
    pay_fees,
    set_clock,
    setup_open_edition,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["games_admin_headers"]
OFFICER = TEST_USERS["registration_officer_headers"]
SPONSOR = TEST_USERS["sponsor_liaison_headers"]
RATIFIER = TEST_USERS["records_ratifier_headers"]

GHOST_EVENT_ID = "44444444-4444-4444-8444-444444444444"
GHOST_RESULT_ID = "55555555-5555-4555-8555-555555555555"


def test_the_impact_reading_reports_every_figure_consistently_with_the_ledgers(clock_at_epoch):
    """PRD §3.9: "That reading reports the `provisional_impact_cents` and
    `final_impact_cents` figures, the `sponsorship_recognized_cents` and
    `municipal_support_cents` ledgers, and the three underlying counts —
    `registered_heads`, `checked_in_heads` and `actual_room_nights` — so that the
    projection can be audited without recomputing it."
    PRD §3.9: "It is a pure read: it never advances a status, never recomputes a stored
    ledger and never bumps a version."
    PRD §3.9: "Its head count, reported as `registered_heads`, is the number of athletes
    in the edition whose `registration_status` is `PENDING_PAYMENT`, `REGISTERED` or
    `CHECKED_IN` — everyone who has entered and not fallen away."
    PRD §3.9: "`provisional_impact_cents` is then that rounded direct spend multiplied
    by one point four five and rounded again to whole cents, half up."
    PRD §3.9: "Only after all four buckets have been rounded are they added together,
    and that sum — not a separately rounded product of pledge and multiplier — becomes
    the commitment's `recognized_cents`."

    The computed reading agrees with the stored projection, the recognition
    ledger and the municipal input, and reads the same for every role.

    Design: Corner/endpoints/corner_endpoint_computed_read_economic_impact_matches_projection
    """
    base = setup_open_edition(
        edition={"municipal_support_cents": 750000}, event={"min_entries_to_stage": 1}
    )
    ed, event = base["edition"], base["event"]
    create_athlete(ed["id"], full_name="Ada Fenn")
    create_athlete(ed["id"], full_name="Bo Marsh", date_of_birth="1961-04-10")
    create_athlete(ed["id"], full_name="Cy Dolan", date_of_birth="1971-11-20")

    checkpointed = ops_run(ed["id"])
    assert checkpointed["ops_epoch"] == 1
    # The clock is still before the deadline, so no status step was admissible.
    assert checkpointed["status"] == "REGISTRATION_OPEN"
    # 3 heads + 5.4 visitor heads = 8.4; 8.4 * 18500 * 4 = 621600; * 1.45 = 901320.
    assert checkpointed["provisional_impact_cents"] == 901320

    commitment = create_sponsorship_commitment(
        ed["id"], sponsor_name="Silverline Mutual", tier="SILVER", pledged_cents=250100
    )
    allocated = allocate_commitment(commitment["id"], ed["id"])
    assert allocated["recognized_cents"] == 262606
    version_after_allocation = get_edition(ed["id"])["version"]
    assert version_after_allocation == checkpointed["version"] + 1

    as_sponsor = validate_success(api_client.get_economic_impact(ed["id"], SPONSOR))
    as_admin = validate_success(api_client.get_economic_impact(ed["id"], ADMIN))
    assert as_sponsor == as_admin

    assert as_sponsor["provisional_impact_cents"] == 901320
    assert as_sponsor["final_impact_cents"] is None
    assert as_sponsor["checked_in_heads"] == 0
    assert as_sponsor["actual_room_nights"] == 0
    # PENDING_PAYMENT heads count toward the projection.
    assert as_sponsor["registered_heads"] == 3
    assert as_sponsor["sponsorship_recognized_cents"] == 262606
    assert as_sponsor["municipal_support_cents"] == 750000

    # The reading declares no side effects of its own.
    assert get_edition(ed["id"])["version"] == version_after_allocation
    assert get_event(event["id"])["status"] == "OPEN"


def test_each_checkpoint_run_advances_the_edition_by_exactly_one_step(clock_at_epoch):
    """PRD §3.9: "Each of those three steps needs its own checkpoint call: an operator who
    sets the clock far into the future and then runs a single checkpoint gets exactly
    one advance, not a cascade to `COMPLETED`."
    PRD §3.9: "First, the edition's `ops_epoch` is incremented by one, stamping the
    run."
    PRD §3.9: "From `REGISTRATION_OPEN` the run moves the edition to
    `REGISTRATION_CLOSED` when the logical clock has reached the
    `registration_deadline_utc`."
    PRD §3.9: "From `REGISTRATION_CLOSED` it moves the edition to `IN_PROGRESS` when the
    clock's date has reached the `competition_start_date`."
    PRD §3.9: "From `IN_PROGRESS` it moves the edition to `COMPLETED` when the clock's
    date is past the `competition_end_date`, and that closing step also finishes
    competition on the ground: every session slot still `IN_PROGRESS` anywhere in the
    edition moves to `COMPLETED`, with all the staffing consequences a block closure
    carries."
    PRD §3.9: "The run also increments the edition's `version` by one."

    With the clock parked past the final competition day, three runs walk the
    edition one step each and a fourth still stamps the epoch.

    Design: Corner/endpoints/corner_endpoint_action_ops_run_advances_at_most_one_status_step
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed, event = base["edition"], base["event"]
    # Opening registration is not a checkpoint and never touches the epoch.
    assert ed["ops_epoch"] == 0
    opened_version = ed["version"]

    installed = validate_success(api_client.set_clock("2026-09-25T00:00:00Z", ADMIN))
    assert installed["current_utc"].startswith("2026-09-25T00:00:00")

    first = ops_run(ed["id"])
    assert (first["status"], first["ops_epoch"]) == ("REGISTRATION_CLOSED", 1)
    second = ops_run(ed["id"])
    assert (second["status"], second["ops_epoch"]) == ("IN_PROGRESS", 2)
    third = ops_run(ed["id"])
    assert (third["status"], third["ops_epoch"]) == ("COMPLETED", 3)

    # The epoch is stamped first, whether or not a status step is admissible.
    fourth = ops_run(ed["id"])
    assert (fourth["status"], fourth["ops_epoch"]) == ("COMPLETED", 4)
    assert fourth["version"] == opened_version + 4

    # Walking the edition did not touch the event machine.
    assert get_event(event["id"])["status"] == "OPEN"


def test_finalization_is_admissible_only_from_completed_and_only_once(clock_at_epoch):
    """PRD §3.9: "The edition must be `COMPLETED` and its `final_impact_cents` must still
    be null; a second attempt is refused with `ERR_EDITION_STATE_INVALID`, because the
    edition is by then `IMPACT_FINALIZED`."
    PRD §2.10: "Registration writes — athlete creation, fee payment and sport-entry
    creation — require `REGISTRATION_OPEN`; athlete check-in requires
    `REGISTRATION_CLOSED` or `IN_PROGRESS`; impact finalization requires `COMPLETED`;
    sponsorship allocation requires any status other than `IMPACT_FINALIZED`."
    PRD §3.9: "The finalising call moves the edition `COMPLETED` → `IMPACT_FINALIZED`,
    writes `final_impact_cents`, and deliberately leaves `provisional_impact_cents`
    exactly as the last checkpoint run left it, so the projection and the settled figure
    remain side by side for comparison."
    PRD §3.9: "Once an edition's `final_impact_cents` has been set, the books are closed
    and any further checkpoint run is refused with `ERR_IMPACT_ALREADY_FINALIZED`."
    PRD §3.9: "Its head count, reported as `checked_in_heads`, counts only athletes
    whose `registration_status` is `CHECKED_IN` — nobody who merely registered."

    Finalizing too early is refused, finalizing from COMPLETED settles the
    final figure without disturbing the projection, and afterwards the books
    are shut against both a checkpoint and a second finalization.

    Design: Corner/endpoints/corner_endpoint_conditional_action_finalize_impact_before_completed_rejected
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed = base["edition"]
    athlete = create_athlete(ed["id"], full_name="Ada Fenn")
    # The base registration fee alone completes registration for an entry-less athlete.
    assert pay_fees(athlete["id"], 9500)["registration_status"] == "REGISTERED"

    validate_error(
        api_client.finalize_impact(ed["id"], SPONSOR),
        ApiErrorId.ERR_EDITION_STATE_INVALID.value,
        409,
    )
    assert get_edition(ed["id"])["final_impact_cents"] is None

    set_clock("2026-09-25T00:00:00Z")
    ops_run(ed["id"])
    ops_run(ed["id"])
    completed = ops_run(ed["id"])
    assert completed["status"] == "COMPLETED"
    # One surviving head: 1 + 1.8 = 2.8; 2.8 * 18500 * 4 = 207200; * 1.45 = 300440.
    assert completed["provisional_impact_cents"] == 300440

    finalized = validate_success(api_client.finalize_impact(ed["id"], SPONSOR))
    assert finalized["status"] == "IMPACT_FINALIZED"
    # Nobody checked in and no stay was slept, so the observed figure is zero.
    assert finalized["final_impact_cents"] == 0
    assert finalized["provisional_impact_cents"] == 300440

    validate_error(
        api_client.ops_run(ed["id"], ADMIN),
        ApiErrorId.ERR_IMPACT_ALREADY_FINALIZED.value,
        409,
    )
    assert get_edition(ed["id"])["ops_epoch"] == 3

    # The status is no longer COMPLETED, so the edition-state gate answers first.
    validate_error(
        api_client.finalize_impact(ed["id"], SPONSOR),
        ApiErrorId.ERR_EDITION_STATE_INVALID.value,
        409,
    )


def test_a_record_claim_demands_that_both_cited_rows_exist(clock_at_epoch):
    """PRD §2.6: "Foreign-key identifiers supplied in a request body are resolved after all
    path identifiers, and among themselves they are resolved in the order the endpoint
    declares its input fields — not in alphabetical order and not in whatever order a
    map happens to iterate."
    PRD §2.6: "Each has a dedicated HTTP 404 error: `ERR_GAMES_EDITION_NOT_FOUND`,
    `ERR_SPORT_NOT_FOUND`, `ERR_SPORT_EVENT_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`,
    `ERR_SESSION_SLOT_NOT_FOUND`, `ERR_ATHLETE_NOT_FOUND`,
    `ERR_QUALIFYING_RESULT_NOT_FOUND`, `ERR_SPORT_ENTRY_NOT_FOUND`,
    `ERR_MEDICAL_SCREENING_NOT_FOUND`, `ERR_PERSONNEL_NOT_FOUND`,
    `ERR_PERSONNEL_ASSIGNMENT_NOT_FOUND`, `ERR_COMPETITION_RESULT_NOT_FOUND`,
    `ERR_AGE_GROUP_RECORD_NOT_FOUND`, `ERR_ACCOMMODATION_BLOCK_NOT_FOUND`,
    `ERR_VILLAGE_STAY_NOT_FOUND` and `ERR_SPONSORSHIP_COMMITMENT_NOT_FOUND`."
    PRD §2.10: "Every identifier in the request path resolves, left to right — otherwise
    the matching not-found error."
    PRD §2.10: "Every foreign-key identifier in the request body resolves, in the order
    the endpoint declares its inputs — otherwise the matching not-found error."

    An unknown event, an unknown mark and an unknown claim each answer their
    own not-found error, and no claim row survives.

    Design: Corner/endpoints/corner_endpoint_cross_reference_record_claim_unknown_parent_returns_not_found
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    event = base["event"]

    # Body identifiers are resolved in the order the endpoint declares them.
    validate_error(
        api_client.create_age_group_record(
            age_group_record_payload(
                GHOST_EVENT_ID, GHOST_RESULT_ID, "ratifier-alpha", event["version"]
            ),
            RATIFIER,
        ),
        ApiErrorId.ERR_SPORT_EVENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.create_age_group_record(
            age_group_record_payload(
                event["id"], GHOST_RESULT_ID, "ratifier-alpha", event["version"]
            ),
            RATIFIER,
        ),
        ApiErrorId.ERR_COMPETITION_RESULT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.ratify_age_group_record(
            NON_EXISTENT_UUID, {"decision": "RATIFY"}, RATIFIER
        ),
        ApiErrorId.ERR_AGE_GROUP_RECORD_NOT_FOUND.value,
        404,
    )

    _, meta = validate_paginated(api_client.list_age_group_records(RATIFIER))
    assert meta["total_count"] == 0

    untouched = get_event(event["id"])
    assert untouched["version"] == event["version"]
    assert untouched["current_record_id"] is None


def test_setting_the_clock_moves_the_deadline_window_and_writes_no_row(clock_at_epoch):
    """PRD §2.4: "A `GamesAdmin` may reposition the clock to any instant by supplying a
    `to_iso8601` value; the response reports the resulting instant as `current_utc`."
    PRD §2.4: "Repositioning the clock mutates no entity row — it changes only what
    subsequent rule evaluations observe."
    PRD §2.10: "The logical clock is strictly before the edition's
    `registration_deadline_utc` — otherwise `ERR_REGISTRATION_DEADLINE_PASSED` (HTTP
    422)."
    PRD §3.2: "Registration is only accepted while the edition is `REGISTRATION_OPEN`
    and while the logical clock is strictly before `registration_deadline_utc`."

    The clock endpoint echoes the instant it installed and mutates nothing, yet
    the same athlete payload is refused past the deadline and accepted a second
    before it.

    Design: Corner/endpoints/corner_endpoint_action_clock_set_moves_deadline_window_and_mutates_no_row
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed = base["edition"]
    version_before, epoch_before = ed["version"], ed["ops_epoch"]
    first = create_athlete(ed["id"], full_name="Ada Fenn")

    late = validate_success(api_client.set_clock("2026-08-26T00:00:00Z", ADMIN))
    assert late["current_utc"].startswith("2026-08-26T00:00:00")

    payload = {
        "games_edition_id": ed["id"],
        "full_name": "Bo Marsh",
        "email": "bo.marsh@example.org",
        "date_of_birth": "1961-04-10",
        "residency_state_code": "IL",
    }
    validate_error(
        api_client.create_athlete(payload, OFFICER),
        ApiErrorId.ERR_REGISTRATION_DEADLINE_PASSED.value,
        422,
    )

    early = validate_success(api_client.set_clock("2026-08-25T23:59:58Z", ADMIN))
    assert early["current_utc"].startswith("2026-08-25T23:59:58")

    second = validate_success(api_client.create_athlete(payload, OFFICER), 201)
    assert second["registration_status"] == "PENDING_PAYMENT"

    # Repositioning the clock mutates no entity row.
    unchanged = get_edition(ed["id"])
    assert unchanged["version"] == version_before
    assert unchanged["ops_epoch"] == epoch_before

    rows, meta = validate_paginated(
        api_client.list_athletes(OFFICER, {"games_edition_id": ed["id"]})
    )
    assert meta["total_count"] == 2
    assert sorted(row["id"] for row in rows) == sorted([first["id"], second["id"]])


def test_one_checkpoint_expires_the_unpaid_head_before_it_reprojects(clock_at_epoch):
    """PRD §3.9: "Second, unpaid registrations are expired: every athlete still in
    `PENDING_PAYMENT` past the edition's `registration_deadline_utc` moves to `EXPIRED`,
    releasing that athlete's live entries and their held capacity."
    PRD §3.2: "An athlete still `PENDING_PAYMENT` when the operations checkpoint
    observes a logical clock at or past `registration_deadline_utc`, with
    `fee_paid_cents` short of `fee_total_cents`, moves `PENDING_PAYMENT` → `EXPIRED`;
    that expiry withdraws every entry of theirs in `SUBMITTED`, `UNDER_REVIEW`,
    `REVISION_REQUESTED`, `ACCEPTED`, `WAITLISTED` or `MEDICAL_HOLD`, and each entry
    leaving `ACCEPTED` decrements its event's `accepted_entry_count`."
    PRD §3.9: "Sixth, and only now that heads and stays have settled,
    `provisional_impact_cents` is recomputed."
    PRD §3.9: "Its head count, reported as `registered_heads`, is the number of athletes
    in the edition whose `registration_status` is `PENDING_PAYMENT`, `REGISTERED` or
    `CHECKED_IN` — everyone who has entered and not fallen away."
    PRD §3.2: "**Step three** adds the base registration fee — ninety-five dollars, that
    is 9500 cents — to `event_fees_cents` to give `subtotal_cents`."

    A single run stamps the epoch, expires the unpaid registration with its
    entry, and only then recomputes the projection on the surviving head.

    Design: Corner/endpoints/corner_endpoint_side_effect_ops_run_expires_unpaid_registration
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed, event = base["edition"], base["event"]
    paid = create_athlete(ed["id"], full_name="Ada Fenn")
    unpaid = create_athlete(ed["id"], full_name="Bo Marsh")
    paid_entry = create_entry(paid["id"], event["id"])
    unpaid_entry = create_entry(unpaid["id"], event["id"])

    # 9500 base + one 6000 entry fee, a single entry taking no discount.
    settled = pay_fees(paid["id"], 15500)
    assert settled["registration_status"] == "REGISTERED"
    assert settled["fee_total_cents"] == 15500

    set_clock("2026-08-26T00:00:00Z")
    swept = ops_run(ed["id"])
    assert swept["status"] == "REGISTRATION_CLOSED"
    assert swept["ops_epoch"] == 1

    assert get_athlete(unpaid["id"])["registration_status"] == "EXPIRED"
    assert get_athlete(paid["id"])["registration_status"] == "REGISTERED"
    assert get_entry(unpaid_entry["id"])["status"] == "WITHDRAWN"
    assert get_entry(paid_entry["id"])["status"] == "SUBMITTED"

    # The expiry ran before the reprojection: one head, not two.
    assert swept["provisional_impact_cents"] == 300440
    assert get_event(event["id"])["accepted_entry_count"] == 0
