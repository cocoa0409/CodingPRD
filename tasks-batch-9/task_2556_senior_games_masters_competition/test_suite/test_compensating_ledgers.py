"""Undo paths measured against the ledgers they must restore: served minutes,
bed nights and recognised cents."""
from test_helpers import (
    ApiErrorId,
    api_client,
    TEST_USERS,
    allocate_commitment,
    cancel_stay,
    confirm_assignment,
    create_accommodation_block,
    create_athlete,
    create_personnel,
    create_session_slot,
    create_sponsorship_commitment,
    create_venue,
    get_assignment,
    get_block,
    get_commitment,
    get_edition,
    get_person,
    get_slot,
    get_stay,
    reserve_stay,
    setup_open_edition,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    village_stay_payload,
)

ADMIN = TEST_USERS["games_admin_headers"]
SPONSOR = TEST_USERS["sponsor_liaison_headers"]


def _official_with_three_blocks() -> dict:
    """One badged official holding three non-conflicting blocks of 60, 90 and 90
    minutes at a single four-area venue — a served-minutes ledger of 240.
    """
    ctx = setup_open_edition()
    venue = create_venue(
        ctx["edition"]["id"], name="North Oval", competition_area_count=4
    )
    official = create_personnel(
        ctx["edition"]["id"], full_name="Dana Reyes", certification_level=3,
        certified_sport_codes=[ctx["sport"]["sport_code"]],
    )
    windows = [
        ("2026-09-12T09:00:00Z", "2026-09-12T10:00:00Z", "CHIEF_JUDGE"),
        ("2026-09-12T11:00:00Z", "2026-09-12T12:30:00Z", "JUDGE"),
        ("2026-09-12T13:30:00Z", "2026-09-12T15:00:00Z", "TIMER"),
    ]
    slots, assignments = [], []
    for start, end, role in windows:
        slot = create_session_slot(
            venue["id"], ctx["event"]["id"],
            start_utc=start, end_utc=end, teardown_buffer_minutes=0,
            required_official_count=1,
        )
        slots.append(slot)
        assignments.append(
            validate_success(
                api_client.create_personnel_assignment(
                    {
                        "personnel_id": official["id"],
                        "session_slot_id": slot["id"],
                        "role_at_event": role,
                    },
                    ADMIN,
                ),
                expected_status=201,
            )
        )
    assert get_person(official["id"])["assigned_minutes_total"] == 240
    return {
        "event": ctx["event"], "venue": venue, "official": official,
        "slots": slots, "assignments": assignments,
    }


def test_release_from_assigned_subtracts_exactly_the_snapshotted_duration():
    """PRD §2.8: "`assigned_minutes_total` on a person rises by an assignment's
    `duration_minutes` when the assignment is created and falls by exactly that same
    figure when the assignment is released or marked a no-show."
    PRD §3.6: "Releasing an `ASSIGNED` assignment moves it to `RELEASED` and debits the
    person's `assigned_minutes_total` by that assignment's `duration_minutes`."
    PRD §3.6: "Releasing a `CONFIRMED` assignment does the same and additionally
    decrements the slot's `confirmed_official_count` by one when the person is an
    `OFFICIAL`; it further requires that the slot not be `IN_PROGRESS`, so a confirmed
    official cannot be pulled out of a block that is already under way — unless the
    release arrives as part of the venue-close cascade, which overrides that protection
    because the block is being abandoned anyway."

    The undo debits the ninety minutes the assignment itself recorded, leaving
    the ledger at 240 - 90.  The snapshot survives on the released row rather than
    being zeroed, and the block's confirmed-official counter — the second ledger —
    is untouched, because nobody had confirmed.

    Design: Difficulty/compensating_invariant/assignment_release_restores_personnel_minutes_ledger_without_drift
    """
    ctx = _official_with_three_blocks()
    second = ctx["assignments"][1]

    validate_success(
        api_client.release_personnel_assignment(
            second["id"], ADMIN, {"reason": "Judge reassigned to a concurrent discipline"}
        )
    )

    released = get_assignment(second["id"])
    assert released["status"] == "RELEASED"
    assert released["duration_minutes"] == 90
    assert get_person(ctx["official"]["id"])["assigned_minutes_total"] == 150
    assert get_slot(ctx["slots"][1]["id"])["confirmed_official_count"] == 0


def test_re_assigning_the_same_block_returns_the_ledger_to_the_exact_baseline():
    """PRD §2.8: "Derived counters are conserved quantities, maintained incrementally
    rather than recomputed by scan, and every debit has an exactly compensating credit."
    PRD §2.8: "`assigned_minutes_total` on a person rises by an assignment's
    `duration_minutes` when the assignment is created and falls by exactly that same
    figure when the assignment is released or marked a no-show."
    PRD §3.6: "The service derives `duration_minutes` from the slot's own interval — the
    whole minutes from the slot's `start_utc` to its `end_utc`, with the teardown buffer
    playing no part — and credits the person's `assigned_minutes_total` by that figure."

    Compensation must not drift: releasing and then re-creating the identical
    assignment restores 240 precisely, not 239 or 241, and the fresh row derives
    the same ninety minutes from the unchanged block.

    Design: Difficulty/compensating_invariant/assignment_release_restores_personnel_minutes_ledger_without_drift
    """
    ctx = _official_with_three_blocks()
    validate_success(
        api_client.release_personnel_assignment(
            ctx["assignments"][1]["id"], ADMIN, {"reason": "Judge reassigned"}
        )
    )

    redo = validate_success(
        api_client.create_personnel_assignment(
            {
                "personnel_id": ctx["official"]["id"],
                "session_slot_id": ctx["slots"][1]["id"],
                "role_at_event": "JUDGE",
            },
            ADMIN,
        ),
        expected_status=201,
    )

    assert redo["duration_minutes"] == 90
    assert get_person(ctx["official"]["id"])["assigned_minutes_total"] == 240


def test_confirming_moves_no_minutes_but_release_from_confirmed_unwinds_two_ledgers():
    """PRD §3.6: "Confirming moves the assignment `ASSIGNED` → `CONFIRMED` and, when the
    person's `personnel_type` is `OFFICIAL`, increments the slot's
    `confirmed_official_count` by one, which is the counter the slot's own start gate
    reads."
    PRD §3.6: "Releasing a `CONFIRMED` assignment does the same and additionally
    decrements the slot's `confirmed_official_count` by one when the person is an
    `OFFICIAL`; it further requires that the slot not be `IN_PROGRESS`, so a confirmed
    official cannot be pulled out of a block that is already under way — unless the
    release arrives as part of the venue-close cascade, which overrides that protection
    because the block is being abandoned anyway."
    PRD §2.8: "`assigned_minutes_total` on a person rises by an assignment's
    `duration_minutes` when the assignment is created and falls by exactly that same
    figure when the assignment is released or marked a no-show."
    PRD §2.8: "`confirmed_official_count` on a session slot rises and falls with
    confirmed official assignments and is reset to zero when the slot's staffing is torn
    down."

    Confirmation moves the coverage counter and nothing else.  Releasing a
    confirmed assignment then has two ledgers to compensate at once: the minutes
    total falls to 150 and the block's confirmed-official count returns to zero.

    Design: Difficulty/compensating_invariant/assignment_release_restores_personnel_minutes_ledger_without_drift
    """
    ctx = _official_with_three_blocks()
    third = ctx["assignments"][2]

    confirmed = confirm_assignment(third["id"], ctx["official"]["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert get_person(ctx["official"]["id"])["assigned_minutes_total"] == 240
    assert get_slot(ctx["slots"][2]["id"])["confirmed_official_count"] == 1

    validate_success(
        api_client.release_personnel_assignment(
            third["id"], ADMIN, {"reason": "Timer withdrew after confirming"}
        )
    )

    assert get_assignment(third["id"])["status"] == "RELEASED"
    assert get_person(ctx["official"]["id"])["assigned_minutes_total"] == 150
    assert get_slot(ctx["slots"][2]["id"])["confirmed_official_count"] == 0


def test_a_second_release_compensates_nothing_at_all():
    """PRD §3.6: "`COMPLETED`, `RELEASED` and `NO_SHOW` are all final; an assignment in any
    of them admits no further action."
    PRD §2.10: "The target row's own current status is a declared origin state of the
    requested transition — otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
    PRD §2.10: "The terminal states for this purpose are `REJECTED` and `WITHDRAWN` on a
    sport entry, `VOIDED` on a competition result, `REJECTED` and `SUPERSEDED` on an
    age-group record, `COMPLETED` and `CANCELLED` on a village stay, `WITHDRAWN` and
    `EXPIRED` on an athlete's registration dimension, and `WITHDRAWN` on a sponsorship
    commitment."
    PRD §2.8: "`assigned_minutes_total` on a person rises by an assignment's
    `duration_minutes` when the assignment is created and falls by exactly that same
    figure when the assignment is released or marked a no-show."
    PRD §3.6: "Two ledgers accompany every person and both start at zero:
    `assigned_minutes_total`, the sum of the `duration_minutes` of that person's
    assignments whose status is `ASSIGNED`, `CONFIRMED` or `COMPLETED`; and
    `no_show_count`, the number of that person's assignments that ended in `NO_SHOW`."

    `RELEASED` is final, so the repeat call is refused rather than debiting a
    second time: the ledger stays at 150 instead of falling to 60, the refused
    call advances no version, and the no-show ledger was never involved.  The
    refusal is the wrong-origin conflict, because a personnel assignment is not
    among the rows the terminal-state check enumerates.

    Design: Difficulty/compensating_invariant/assignment_release_restores_personnel_minutes_ledger_without_drift
    """
    ctx = _official_with_three_blocks()
    second = ctx["assignments"][1]
    validate_success(
        api_client.release_personnel_assignment(
            second["id"], ADMIN, {"reason": "Judge reassigned"}
        )
    )
    after_first = get_assignment(second["id"])

    repeat = api_client.release_personnel_assignment(
        second["id"], ADMIN, {"reason": "Duplicate release attempt"}
    )

    validate_error(
        repeat, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409
    )
    person = get_person(ctx["official"]["id"])
    assert person["assigned_minutes_total"] == 150
    assert person["no_show_count"] == 0
    assert get_assignment(second["id"])["version"] == after_first["version"]


def _one_bed_block_with_a_five_night_stay() -> dict:
    """A single-bed block at 12000 cents a night, wholly occupied from 9 to 14
    September by one athlete, with a second athlete waiting for a night of it.
    """
    ctx = setup_open_edition()
    block = create_accommodation_block(
        ctx["edition"]["id"], name="Cedar Lodge", bed_capacity=1, nightly_rate_cents=12000
    )
    ada = create_athlete(ctx["edition"]["id"], full_name="Ada Fenn")
    ben = create_athlete(ctx["edition"]["id"], full_name="Ben Orsi")
    stay = reserve_stay(
        ada["id"], block["id"], check_in_date="2026-09-09", check_out_date="2026-09-14"
    )
    assert stay["nights"] == 5
    assert stay["total_charge_cents"] == 60000
    assert get_block(block["id"])["reserved_bed_nights"] == 5
    return {"block": block, "ada_stay": stay, "ben": ben}


def _ben_asks_for_the_eleventh(block_id, ben_id):
    block = get_block(block_id)
    return api_client.create_village_stay(
        village_stay_payload(
            ben_id, block_id, block["version"],
            check_in_date="2026-09-11", check_out_date="2026-09-12",
        ),
        ADMIN,
    )


def test_cancelling_a_stay_debits_exactly_its_own_nights_and_erases_its_charge():
    """PRD §2.8: "`reserved_bed_nights` on an accommodation block rises by a stay's
    `nights` on reservation and falls by exactly that figure on cancellation."
    PRD §3.8: "A cancellation debits the block's `reserved_bed_nights` by exactly the
    stay's own `nights` — the precise compensating action of the reservation — and
    zeroes the stay's `total_charge_cents`, so a cancelled booking bills nothing."

    The bed-night ledger unwinds by the stay's own five nights, back to zero.
    The night count survives on the cancelled row — it is the quantity the debit
    used — but the money does not: the charge is erased rather than conserved, so
    the two quantities unwind by different rules on one transition.

    Design: Difficulty/compensating_invariant/village_stay_cancel_restores_block_bed_nights_and_frees_the_night
    """
    ctx = _one_bed_block_with_a_five_night_stay()

    cancel_stay(ctx["ada_stay"]["id"], reason="Athlete arranged private lodging")

    cancelled = get_stay(ctx["ada_stay"]["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["nights"] == 5
    assert cancelled["total_charge_cents"] == 0
    assert get_block(ctx["block"]["id"])["reserved_bed_nights"] == 0


def test_the_cancelled_night_is_genuinely_released_and_not_merely_uncounted():
    """PRD §3.8: "If on any single one of the candidate's nights that count has already
    reached the block's `bed_capacity`, the reservation is refused with
    `ERR_BLOCK_NIGHT_FULL`."
    PRD §3.8: "Cancelled stays occupy nothing and are invisible to this count."
    PRD §3.8: "Where the booking is accepted, the service derives the rest: `nights` is
    the whole number of days from the `check_in_date` to the `check_out_date`,
    `total_charge_cents` is that night count multiplied by the block's
    `nightly_rate_cents` — snapshotted at reservation so a later change to the block's
    nightly rate never rewrites an existing stay's charge — and the block's
    `reserved_bed_nights` is increased by the same night count."

    The proof that the resource itself came back is a byte-identical request that
    is refused before the cancellation and accepted after it, rebuilding the
    ledger from zero to the one night the new stay occupies.

    Design: Difficulty/compensating_invariant/village_stay_cancel_restores_block_bed_nights_and_frees_the_night
    """
    ctx = _one_bed_block_with_a_five_night_stay()

    before = _ben_asks_for_the_eleventh(ctx["block"]["id"], ctx["ben"]["id"])
    validate_error(before, ApiErrorId.ERR_BLOCK_NIGHT_FULL.value, expected_status=409)

    cancel_stay(ctx["ada_stay"]["id"], reason="Athlete arranged private lodging")
    after = validate_success(
        _ben_asks_for_the_eleventh(ctx["block"]["id"], ctx["ben"]["id"]),
        expected_status=201,
    )

    assert after["status"] == "RESERVED"
    assert after["nights"] == 1
    assert after["total_charge_cents"] == 12000
    assert get_block(ctx["block"]["id"])["reserved_bed_nights"] == 1


def test_a_second_cancellation_never_drives_the_bed_night_ledger_negative():
    """PRD §3.8: "`COMPLETED` and `CANCELLED` are both final and admit no further action."
    PRD §2.10: "The target row is not already sitting in a terminal state of its own
    machine — otherwise `ERR_ALREADY_TERMINAL` (HTTP 409)."
    PRD §2.10: "The terminal states for this purpose are `REJECTED` and `WITHDRAWN` on a
    sport entry, `VOIDED` on a competition result, `REJECTED` and `SUPERSEDED` on an
    age-group record, `COMPLETED` and `CANCELLED` on a village stay, `WITHDRAWN` and
    `EXPIRED` on an athlete's registration dimension, and `WITHDRAWN` on a sponsorship
    commitment."
    PRD §2.8: "`reserved_bed_nights` on an accommodation block rises by a stay's
    `nights` on reservation and falls by exactly that figure on cancellation."

    `CANCELLED` is final.  The repeat call is refused, so the ledger holding the
    replacement stay's single night is not debited a second time down to minus
    four, and the block's own configured capacity and rate were never touched by
    any of it.  The PRD names the terminal-state check one rung below the
    origin-state check, so either conflict is an admissible reading of the
    refusal; what is pinned is that the call is refused and the ledger holds.

    Design: Difficulty/compensating_invariant/village_stay_cancel_restores_block_bed_nights_and_frees_the_night
    """
    ctx = _one_bed_block_with_a_five_night_stay()
    cancel_stay(ctx["ada_stay"]["id"], reason="Athlete arranged private lodging")
    validate_success(
        _ben_asks_for_the_eleventh(ctx["block"]["id"], ctx["ben"]["id"]),
        expected_status=201,
    )

    repeat = api_client.cancel_village_stay(
        ctx["ada_stay"]["id"], ADMIN, {"reason": "Duplicate cancellation attempt"}
    )

    assert repeat.status_code == 409
    validate_error_is_one_of(
        repeat,
        [
            ApiErrorId.ERR_ALREADY_TERMINAL.value,
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ],
    )
    block = get_block(ctx["block"]["id"])
    assert block["reserved_bed_nights"] == 1
    assert block["bed_capacity"] == 1
    assert block["nightly_rate_cents"] == 12000


def test_the_cancellation_advances_the_block_version_while_the_refusal_advances_nothing():
    """PRD §2.5: "`version` is an integer that starts at 1 on creation and increments by
    one on every mutation of that row, including mutations the server performs on its
    own initiative as part of a cascade, and including mutations that only touch a
    derived counter such as `accepted_entry_count`, `confirmed_official_count`,
    `assigned_minutes_total`, `reserved_bed_nights` or `sponsorship_recognized_cents`."
    PRD §3.8: "It is reserved either by the athlete themselves or by a `GamesAdmin`,
    naming `athlete_id`, `accommodation_block_id`, a `check_in_date`, a `check_out_date`
    strictly later than the check-in date, and an `expected_block_version` that must
    equal the block's current `version`; a stale figure is refused with
    `ERR_STALE_BLOCK_VERSION`, and a successful reservation increments the block's
    `version`."
    PRD §3.8: "If on any single one of the candidate's nights that count has already
    reached the block's `bed_capacity`, the reservation is refused with
    `ERR_BLOCK_NIGHT_FULL`."

    Only the accepted writes move the block's optimistic-concurrency counter: the
    refused reservation leaves it exactly where it stood, and the cancellation
    then advances it.

    Design: Difficulty/compensating_invariant/village_stay_cancel_restores_block_bed_nights_and_frees_the_night
    """
    ctx = _one_bed_block_with_a_five_night_stay()
    before_refusal = get_block(ctx["block"]["id"])["version"]

    validate_error(
        _ben_asks_for_the_eleventh(ctx["block"]["id"], ctx["ben"]["id"]),
        ApiErrorId.ERR_BLOCK_NIGHT_FULL.value,
    )
    after_refusal = get_block(ctx["block"]["id"])["version"]
    cancel_stay(ctx["ada_stay"]["id"], reason="Athlete arranged private lodging")
    after_cancel = get_block(ctx["block"]["id"])["version"]

    assert after_refusal == before_refusal
    assert after_cancel > after_refusal


def _edition_with_two_allocated_sponsors() -> dict:
    """Three pledges — a SILVER 250100, a BRONZE 120000 and a GOLD 400000 — with the
    first two allocated and the third still merely pledged.
    """
    ctx = setup_open_edition(edition={"municipal_support_cents": 0})
    edition_id = ctx["edition"]["id"]
    silver = create_sponsorship_commitment(
        edition_id, sponsor_name="Northline Bank", sponsor_kind="CORPORATE",
        tier="SILVER", pledged_cents=250100,
    )
    bronze = create_sponsorship_commitment(
        edition_id, sponsor_name="City of Springfield", sponsor_kind="MUNICIPAL",
        tier="BRONZE", pledged_cents=120000,
    )
    gold = create_sponsorship_commitment(
        edition_id, sponsor_name="Halberd Foundation", sponsor_kind="FOUNDATION",
        tier="GOLD", pledged_cents=400000,
    )
    allocate_commitment(silver["id"], edition_id)
    allocate_commitment(bronze["id"], edition_id)
    return {
        "edition_id": edition_id, "silver": silver, "bronze": bronze, "gold": gold
    }


def _withdraw(commitment_id, reason):
    return api_client.withdraw_sponsorship_commitment(
        commitment_id, SPONSOR, {"reason": reason}
    )


def test_the_recognised_baseline_exceeds_the_pledge_because_of_per_bucket_rounding():
    """PRD §3.9: "The tier sets a recognition multiplier: `BRONZE` recognises the pledge at
    par, one times the pledged amount; `SILVER` at one and five hundredths; `GOLD` at
    one and twelve hundredths; and `PLATINUM` at one and a quarter."
    PRD §3.9: "The four buckets take fixed shares of the pledge and are filled in this
    declared order: `VENUE_SIGNAGE` takes forty percent, `ATHLETE_SERVICES` thirty
    percent, `MEDICAL_COVERAGE` twenty percent and `SOCIAL_PROGRAM` the remaining ten
    percent."
    PRD §3.9: "Each bucket's figure is computed independently as the `pledged_cents`
    multiplied by that bucket's share and by the tier multiplier, and each is then
    rounded to a whole number of cents on its own, with a half cent rounding upward."
    PRD §3.9: "Only after all four buckets have been rounded are they added together,
    and that sum — not a separately rounded product of pledge and multiplier — becomes
    the commitment's `recognized_cents`."
    PRD §3.9: "The four rounded figures are stored as the `allocation_map`, keyed by
    bucket name, and `recognized_cents` is added to the edition's
    `sponsorship_recognized_cents` ledger."

    The quantity that will later have to be unwound is the recognised figure, and
    it is not the pledge: the SILVER 250100 recognises 105042 + 78782 + 52521 +
    26261 = 262606 across the four programme buckets, and the edition's ledger
    carries that alongside the BRONZE pledge recognised at par.

    Design: Difficulty/compensating_invariant/sponsorship_withdraw_restores_edition_recognition_ledger_in_cents
    """
    ctx = _edition_with_two_allocated_sponsors()

    silver = get_commitment(ctx["silver"]["id"])
    assert silver["recognized_cents"] == 262606
    assert silver["allocation_map"] == {
        "VENUE_SIGNAGE": 105042,
        "ATHLETE_SERVICES": 78782,
        "MEDICAL_COVERAGE": 52521,
        "SOCIAL_PROGRAM": 26261,
    }
    assert get_commitment(ctx["bronze"]["id"])["recognized_cents"] == 120000
    assert get_edition(ctx["edition_id"])["sponsorship_recognized_cents"] == 382606


def test_withdrawing_a_merely_pledged_commitment_moves_no_ledger_and_no_version():
    """PRD §3.9: "Withdrawing a commitment that is still `PLEDGED` moves it `PLEDGED` →
    `WITHDRAWN` and touches no ledger, because nothing had been recognised."
    PRD §2.8: "`sponsorship_recognized_cents` on an edition rises by a commitment's
    `recognized_cents` on allocation and falls by exactly that figure when an allocated
    commitment is withdrawn."
    PRD §3.9: "It opens `PLEDGED` with `recognized_cents` at zero and an empty
    `allocation_map`."

    The same endpoint compensates a different amount depending on the state it
    finds.  Nothing had been recognised for the GOLD pledge, so its withdrawal
    leaves both the commitment's own figure and the edition's ledger — and the
    edition's version — exactly as they stood.

    Design: Difficulty/compensating_invariant/sponsorship_withdraw_restores_edition_recognition_ledger_in_cents
    """
    ctx = _edition_with_two_allocated_sponsors()
    before = get_edition(ctx["edition_id"])

    validate_success(_withdraw(ctx["gold"]["id"], "Foundation deferred to the next biennium"))

    withdrawn = get_commitment(ctx["gold"]["id"])
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["recognized_cents"] == 0
    after = get_edition(ctx["edition_id"])
    assert after["sponsorship_recognized_cents"] == 382606
    assert after["version"] == before["version"]


def test_withdrawal_unwinds_the_recognised_amount_rather_than_the_pledged_amount():
    """PRD §2.8: "Derived counters are conserved quantities, maintained incrementally
    rather than recomputed by scan, and every debit has an exactly compensating credit."
    PRD §2.8: "`sponsorship_recognized_cents` on an edition rises by a commitment's
    `recognized_cents` on allocation and falls by exactly that figure when an allocated
    commitment is withdrawn."
    PRD §3.9: "Withdrawing one that is `ALLOCATED` moves it `ALLOCATED` → `WITHDRAWN`,
    requires the edition not to be `IMPACT_FINALIZED`, debits the edition's
    `sponsorship_recognized_cents` by exactly the commitment's `recognized_cents`,
    resets that `recognized_cents` to zero and empties the `allocation_map` back to
    nothing, and increments both versions."
    PRD §2.8: "Sponsorship recognition rounds four times, once per recognition bucket,
    before the buckets are summed; rounding the multiplied total once instead is a
    different and incorrect answer."

    382606 - 262606 leaves 120000.  Debiting the pledged 250100 would have left
    132506 and debiting a once-rounded 262605 would have left 120001, so the ledger
    proves the withdrawal used the stored per-bucket total.  The breakdown is
    cleared alongside it.

    Design: Difficulty/compensating_invariant/sponsorship_withdraw_restores_edition_recognition_ledger_in_cents
    """
    ctx = _edition_with_two_allocated_sponsors()

    validate_success(_withdraw(ctx["silver"]["id"], "Bank merger cancelled the sponsorship"))

    assert get_edition(ctx["edition_id"])["sponsorship_recognized_cents"] == 120000
    silver = get_commitment(ctx["silver"]["id"])
    assert silver["status"] == "WITHDRAWN"
    assert silver["recognized_cents"] == 0
    assert silver["allocation_map"] == {}


def test_the_recognition_ledger_returns_to_zero_and_a_repeat_withdrawal_moves_nothing():
    """PRD §3.9: "Withdrawing one that is `ALLOCATED` moves it `ALLOCATED` → `WITHDRAWN`,
    requires the edition not to be `IMPACT_FINALIZED`, debits the edition's
    `sponsorship_recognized_cents` by exactly the commitment's `recognized_cents`,
    resets that `recognized_cents` to zero and empties the `allocation_map` back to
    nothing, and increments both versions."
    PRD §2.8: "`sponsorship_recognized_cents` on an edition rises by a commitment's
    `recognized_cents` on allocation and falls by exactly that figure when an allocated
    commitment is withdrawn."
    PRD §2.10: "The target row is not already sitting in a terminal state of its own
    machine — otherwise `ERR_ALREADY_TERMINAL` (HTTP 409)."
    PRD §2.10: "The terminal states for this purpose are `REJECTED` and `WITHDRAWN` on a
    sport entry, `VOIDED` on a competition result, `REJECTED` and `SUPERSEDED` on an
    age-group record, `COMPLETED` and `CANCELLED` on a village stay, `WITHDRAWN` and
    `EXPIRED` on an athlete's registration dimension, and `WITHDRAWN` on a sponsorship
    commitment."

    Unwinding both allocations empties the ledger exactly.  `WITHDRAWN` is final,
    so the repeat call is refused and the ledger does not run to minus 262606, and
    every pledged figure is left as recorded — compensation touched only the
    recognised amounts, the breakdowns and the edition ledger.  The PRD names the
    terminal-state check one rung below the origin-state check, so either conflict
    is an admissible reading of the refusal; what is pinned is that the call is
    refused and the ledger holds at zero.

    Design: Difficulty/compensating_invariant/sponsorship_withdraw_restores_edition_recognition_ledger_in_cents
    """
    ctx = _edition_with_two_allocated_sponsors()
    validate_success(_withdraw(ctx["silver"]["id"], "Bank merger cancelled the sponsorship"))
    validate_success(_withdraw(ctx["bronze"]["id"], "Municipal budget amendment"))

    assert get_edition(ctx["edition_id"])["sponsorship_recognized_cents"] == 0
    assert get_commitment(ctx["bronze"]["id"])["allocation_map"] == {}

    repeat = _withdraw(ctx["silver"]["id"], "Duplicate withdrawal attempt")

    assert repeat.status_code == 409
    validate_error_is_one_of(
        repeat,
        [
            ApiErrorId.ERR_ALREADY_TERMINAL.value,
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ],
    )
    assert get_edition(ctx["edition_id"])["sponsorship_recognized_cents"] == 0
    assert get_commitment(ctx["silver"]["id"])["pledged_cents"] == 250100
    assert get_commitment(ctx["bronze"]["id"])["pledged_cents"] == 120000
    assert get_commitment(ctx["gold"]["id"])["pledged_cents"] == 400000
