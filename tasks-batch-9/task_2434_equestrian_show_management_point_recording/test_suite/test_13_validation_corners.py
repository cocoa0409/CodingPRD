"""Validation gates: the clean pass, the eligibility trio, third-entity conflicts and the caps."""

from test_helpers import api_client, validate_error, validate_paginated, validate_success
from test_helpers.factories import (
    create_class_entry_payload,
    create_official_assignment_payload,
)
from test_helpers.fixtures import (
    accept_entry,
    book_slot,
    build_approved_show,
    build_confirmed_entry,
    build_entry,
    build_multi_class_show,
    build_steward,
    confirmed_rows_for_class,
    create_horse,
    create_official,
    create_rider,
    default_placings,
    get_class,
    get_class_entry,
    get_entry,
    get_official,
    get_show,
    invoice_entry,
    open_compliance_case,
    record_finding,
    record_results,
    run_class_to_posted,
    stage_class_slot,
    start_slot,
    verify_entry,
)
from test_helpers.test_users import TEST_USERS, make_exhibitor_headers

SECRETARY = TEST_USERS["show_secretary_headers"]
OFFICER = TEST_USERS["federation_officer_headers"]


def _card(official_id, slot_id, official_role):
    return api_client.create_official_assignment(
        create_official_assignment_payload(official_id, slot_id, official_role), SECRETARY
    )


def _enter_class(entry_id, class_id, rider_id):
    return api_client.create_class_entry(
        create_class_entry_payload(entry_id, class_id), make_exhibitor_headers(rider_id)
    )


def test_a_clean_entry_walks_the_whole_intake_ladder_without_tripping_a_single_gate():
    """This is the mirror of every intake refusal: a rider whose membership runs to next summer, a
    horse whose Coggins outlasts the show's first day, two stalls that fit inside a forty-stall
    grounds and a payment that matches the invoice to the cent. Every step returns success, the
    settlement lands on 40000 plus the full 5000 office fee, the confirmation join fires because
    both dimensions have completed, and the stall ledger moves by exactly the two stalls asked for.

    PRD §3.4: "Membership is not stored as a settled state: `membership_status` is re-derived on every read as `ACTIVE` when the logical clock is strictly before `membership_expires_on` and `LAPSED` otherwise."
    PRD §3.4: "The service derives `coggins_expires_on` as `coggins_drawn_on` plus 365 days, and sets `eligibility_status` to `ELIGIBLE`."
    PRD §3.5: "The horse's `coggins_expires_on` must be at or after the show's `start_utc` — equality is acceptable — failing which `ERR_COGGINS_EXPIRED`."
    PRD §3.5: "The entry's `requested_stall_count` must not exceed the show's current `available_stall_count`; only a strictly greater request is refused, and the refusal is `ERR_STALL_CAPACITY_EXCEEDED`."
    PRD §3.5: "An entry not in `INVOICED` is refused with `ERR_ENTRY_NOT_INVOICED`, and an `amount_cents` that is not exactly equal to `total_due_cents` — short or over — is refused with `ERR_PAYMENT_AMOUNT_MISMATCH`."
    PRD §3.5: "A class entry starts life `ENTERED` and only reaches `CONFIRMED` when *both* entry dimensions have landed: `verification_status` of `ACCEPTED` and `settlement_status` of `PAID`."
    PRD §2.10: "The invariant `stall_capacity` equals `reserved_stall_count` plus `available_stall_count` holds before and after every acceptance and every withdrawal."

    Design: Corner/validations/valid_entry_passes_every_verification_gate
    """
    ctx = build_approved_show()
    rider = create_rider()
    horse = create_horse()
    assert rider["membership_status"] == "ACTIVE"
    assert horse["eligibility_status"] == "ELIGIBLE"
    assert horse["coggins_expires_on"] == "2027-03-01T00:00:00Z"
    assert get_show(ctx["show_id"])["start_utc"] == "2026-09-10T13:00:00Z"

    row = build_entry(
        ctx["show_id"], rider["id"], horse["id"], [ctx["class_id"]], requested_stall_count=2
    )
    entry_id = row["entry_id"]

    assert verify_entry(entry_id)["verification_status"] == "VERIFIED"
    accepted = accept_entry(entry_id)
    assert accepted["verification_status"] == "ACCEPTED"
    assert accepted["assigned_stall_count"] == 2

    invoiced = invoice_entry(entry_id)
    assert invoiced["class_fee_cents_total"] == 25000
    assert invoiced["stall_fee_cents"] == 15000
    assert invoiced["preliminary_subtotal_cents"] == 40000
    assert invoiced["office_fee_cents"] == 5000
    assert invoiced["total_due_cents"] == 45000

    paid = validate_success(
        api_client.pay_entry(
            entry_id, {"amount_cents": 45000}, make_exhibitor_headers(rider["id"])
        )
    )
    assert paid["settlement_status"] == "PAID"
    assert paid["verification_status"] == "ACCEPTED"

    assert get_class_entry(row["class_entry_id"])["status"] == "CONFIRMED"

    show = get_show(ctx["show_id"])
    assert show["reserved_stall_count"] == 2
    assert show["available_stall_count"] == 38
    assert show["reserved_stall_count"] + show["available_stall_count"] == 40


def test_the_three_eligibility_gates_fire_on_their_own_defects_and_in_their_own_order():
    """Three different data defects each get their own refusal on the endpoint that owns them: a
    membership that expired last month, a Coggins that expired before the show opens, and a horse
    suspended by a substantiated positive drug finding. The entry that is defective on the first two
    counts at once reports the membership error, because membership is checked first. The suspended
    horse is refused on both intake paths — adding it to a class and verifying its entry — and every
    refused entry is left exactly where it was, with nothing on the class's books.

    PRD §3.5: "The rider's `membership_status` must be `ACTIVE` at the logical clock, failing which the answer is `ERR_RIDER_MEMBERSHIP_LAPSED`."
    PRD §3.5: "The horse's `coggins_expires_on` must be at or after the show's `start_utc` — equality is acceptable — failing which `ERR_COGGINS_EXPIRED`."
    PRD §3.5: "And the horse's `eligibility_status` must be `ELIGIBLE`, failing which `ERR_HORSE_SUSPENDED`."
    PRD §3.5: "The Coggins and eligibility checks are not unique to verification: both are re-run whenever the entry is added to a class, with the same two error codes."
    PRD §3.9: "In order: the entry's horse has its `eligibility_status` set to `SUSPENDED`; then every class entry anywhere in the system whose parent entry names that same horse, whose own `status` is `ENTERED`, `CONFIRMED` or `COMPLETED`, and whose class is not `VOIDED`, moves to `DISQUALIFIED` with its `prize_cents` reset to 0 and its `placing` set back to null; then every class touched by those disqualifications whose `status` was `RESULTS_POSTED` reverts `RESULTS_POSTED → JUDGED` with its `awarded_prize_cents` reset to 0 and its `placed_count`, `entry_count`, `confirmed_entry_count` and `point_eligible` recomputed; and then the show's `allocated_prize_cents` and `unallocated_prize_cents` are recomputed per the prize ledger, so the money released by the reverted classes returns to the unallocated side."

    Design: Corner/validations/lapsed_membership_expired_coggins_and_suspended_horse_blocked
    """
    ctx = build_approved_show()
    class_id = ctx["class_id"]

    rider_ok = create_rider()
    rider_lapsed = create_rider(membership_expires_on="2026-07-15T00:00:00Z")
    assert rider_ok["membership_status"] == "ACTIVE"
    assert rider_lapsed["membership_status"] == "LAPSED"

    horse_ok = create_horse()
    horse_stale = create_horse(coggins_drawn_on="2025-06-01T00:00:00Z")
    horse_susp = create_horse()
    assert horse_stale["coggins_expires_on"] == "2026-06-01T00:00:00Z"

    entry_lapsed = build_entry(ctx["show_id"], rider_lapsed["id"], horse_ok["id"])
    entry_both = build_entry(ctx["show_id"], rider_lapsed["id"], horse_stale["id"])
    entry_stale = build_entry(ctx["show_id"], rider_ok["id"], horse_stale["id"])
    entry_susp = build_entry(ctx["show_id"], rider_ok["id"], horse_susp["id"])

    steward = build_steward()
    case = open_compliance_case(
        entry_susp["entry_id"], steward["steward_id"], sample_code="S-9001"
    )
    substantiated = record_finding(case["id"], "POSITIVE")
    assert substantiated["status"] == "SUBSTANTIATED"
    assert validate_success(api_client.get_horse(horse_susp["id"], OFFICER))["eligibility_status"] == "SUSPENDED"

    validate_error(
        api_client.verify_entry(entry_lapsed["entry_id"], SECRETARY),
        "ERR_RIDER_MEMBERSHIP_LAPSED",
        422,
    )
    validate_error(
        _enter_class(entry_stale["entry_id"], class_id, rider_ok["id"]),
        "ERR_COGGINS_EXPIRED",
        422,
    )
    validate_error(
        api_client.verify_entry(entry_both["entry_id"], SECRETARY),
        "ERR_RIDER_MEMBERSHIP_LAPSED",
        422,
    )
    validate_error(
        _enter_class(entry_susp["entry_id"], class_id, rider_ok["id"]),
        "ERR_HORSE_SUSPENDED",
        422,
    )
    validate_error(
        api_client.verify_entry(entry_susp["entry_id"], SECRETARY),
        "ERR_HORSE_SUSPENDED",
        422,
    )

    for row in (entry_lapsed, entry_both, entry_stale, entry_susp):
        blocked = get_entry(row["entry_id"])
        assert blocked["verification_status"] == "RECEIVED"
        assert blocked["settlement_status"] == "UNBILLED"

    assert get_class(class_id)["entry_count"] == 0


def test_the_officials_barn_is_compared_against_the_riders_in_the_class_being_booked():
    """Whether an official may take a chair depends on a third entity's data: the barn recorded
    against the official is compared with the trainer of every rider holding a live row in the
    booked class. The official tied to the barn that has a horse in this class is refused in the
    judge's chair and refused again in the steward's, because the rule does not care which chair is
    being filled; the official from another barn is carded without argument. Neither refusal touched
    the load ledger, so the conflicted official still reads zero minutes while the clean one carries
    the whole fifty-three-minute occupancy.

    PRD §3.4: "An optional `affiliated_trainer_name` records the barn the official is commercially tied to and defaults to null; it exists solely to drive the conflict-of-interest rule of §3.6."
    PRD §3.6: "The official's `affiliated_trainer_name` must not equal the `trainer_name` of any rider holding a class entry with `status` of `ENTERED` or `CONFIRMED` in the occupancy's class."
    PRD §3.6: "A match is `ERR_OFFICIAL_CONFLICT_OF_INTEREST`."
    PRD §3.6: "A new assignment has `status` of `ACTIVE`, and the official's `assigned_minutes` is increased by the whole minutes from the occupancy's `warmup_start_utc` to its `end_utc`; the official's `version` increments."
    PRD §2.10: "A fourth aggregate lives on the official: `assigned_minutes` sums, over that official's assignments whose `status` is `ACTIVE`, the whole minutes from the assigned slot's `warmup_start_utc` to its `end_utc`."

    Design: Corner/validations/conflict_of_interest_blocks_official_assignment
    """
    ctx = build_approved_show(ring_specs=[{}])
    rider = create_rider(full_name="Ada Rider", trainer_name="Bluegrass Barn")
    horse = create_horse()
    row = build_confirmed_entry(ctx["show_id"], rider["id"], horse["id"], [ctx["class_id"]])
    assert get_class_entry(row["class_entry_id"])["status"] == "CONFIRMED"

    slot = book_slot(ctx["ring_id"], ctx["class_id"], "2026-09-10T14:00:00Z")
    assert slot["duration_minutes"] == 23
    assert slot["warmup_start_utc"] == "2026-09-10T13:30:00Z"
    assert slot["end_utc"] == "2026-09-10T14:23:00Z"

    conflicted = create_official(
        license_roles=["JUDGE", "STEWARD"], affiliated_trainer_name="Bluegrass Barn"
    )
    clean = create_official(
        license_roles=["JUDGE", "STEWARD"], affiliated_trainer_name="Stonegate Barn"
    )

    validate_error(
        _card(conflicted["id"], slot["id"], "JUDGE"),
        "ERR_OFFICIAL_CONFLICT_OF_INTEREST",
        409,
    )
    validate_error(
        _card(conflicted["id"], slot["id"], "STEWARD"),
        "ERR_OFFICIAL_CONFLICT_OF_INTEREST",
        409,
    )

    carded = validate_success(_card(clean["id"], slot["id"], "JUDGE"), 201)
    assert carded["status"] == "ACTIVE"

    assert get_official(conflicted["id"])["assigned_minutes"] == 0
    assert get_official(clean["id"])["assigned_minutes"] == 53

    rows, meta = validate_paginated(
        api_client.list_official_assignments(SECRETARY, params={"slot_id": slot["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == carded["id"]


def test_the_daily_load_ceiling_admits_the_chair_that_lands_exactly_on_four_hundred_and_eighty():
    """Three chairs on three different days can never collide in time, so the only rule left to
    fire is the aggregate one. The first two occupancies are 250 and 230 minutes, which lands the
    official exactly on the 480-minute ceiling — accepted, because the ceiling is a must-not-exceed
    rather than a must-stay-below. The third chair would take the day to 520 and is refused, leaving
    the load at 480 and only the two accepted assignments on the books.

    PRD §3.6: "The official's current `assigned_minutes` plus the whole minutes from the candidate occupancy's `warmup_start_utc` to its `end_utc` must not exceed 480 minutes — eight hours of carded duty per official."
    PRD §3.6: "Exceeding it is `ERR_OFFICIAL_LOAD_EXCEEDED`."
    PRD §3.6: "Finally, `estimated_minutes` is ride time plus course walk time plus the ring's `turnover_buffer_minutes`."
    PRD §3.6: "The candidate collides with an existing assignment when the candidate's `warmup_start_utc` is at or before the existing occupancy's `end_utc` advanced by the required gap, *and* the existing occupancy's `warmup_start_utc` is at or before the candidate's `end_utc` advanced by the required gap."

    Design: Corner/validations/official_daily_load_cap_at_exact_boundary
    """
    ctx = build_approved_show(
        class_specs=[
            {"class_number": 101, "name": "Open Jumper A", "class_share_bp": 1000},
            {"class_number": 102, "name": "Open Jumper B", "class_share_bp": 1000},
            {"class_number": 103, "name": "Open Jumper C", "class_share_bp": 1000},
        ],
        ring_specs=[
            {"name": "Ring A", "turnover_buffer_minutes": 210},
            {"name": "Ring B", "turnover_buffer_minutes": 190},
            {"name": "Ring C", "turnover_buffer_minutes": 0},
        ],
    )
    ring_a, ring_b, ring_c = ctx["rings"]
    class_a, class_b, class_c = ctx["class_ids"]

    slot_a = book_slot(ring_a["id"], class_a, "2026-09-10T14:00:00Z")
    slot_b = book_slot(ring_b["id"], class_b, "2026-09-11T14:00:00Z")
    slot_c = book_slot(ring_c["id"], class_c, "2026-09-12T14:00:00Z")

    assert slot_a["duration_minutes"] == 220
    assert slot_b["duration_minutes"] == 200
    assert slot_c["duration_minutes"] == 10
    assert slot_a["end_utc"] == "2026-09-10T17:40:00Z"
    assert slot_b["end_utc"] == "2026-09-11T17:20:00Z"
    assert slot_c["end_utc"] == "2026-09-12T14:10:00Z"

    judge = create_official()
    first = validate_success(_card(judge["id"], slot_a["id"], "JUDGE"), 201)
    assert get_official(judge["id"])["assigned_minutes"] == 250

    second = validate_success(_card(judge["id"], slot_b["id"], "JUDGE"), 201)
    assert get_official(judge["id"])["assigned_minutes"] == 480

    validate_error(
        _card(judge["id"], slot_c["id"], "JUDGE"), "ERR_OFFICIAL_LOAD_EXCEEDED", 409
    )
    assert get_official(judge["id"])["assigned_minutes"] == 480

    rows, meta = validate_paginated(
        api_client.list_official_assignments(
            SECRETARY, params={"official_id": judge["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    assert slot_c["id"] not in {row["slot_id"] for row in rows}


def test_the_pool_headroom_is_recomputed_from_live_ledger_state_on_every_posting():
    """Two classes of one show each carry a purse equal to the whole pool, so either can be posted
    alone but not both. The first posting takes 81000 of the 100000 available; the second is refused
    on the aggregate headroom and leaves nothing behind — the class is still JUDGED, its rows still
    carry no prize money, and the show's allocated figure has not moved. Voiding the first class
    returns the purse to the unallocated side, and the very same posting that was refused now
    succeeds, which is only possible if the check reads the ledger rather than a latched flag.

    PRD §3.8: "And the show's current `allocated_prize_cents` plus the purse about to be awarded must not exceed `prize_money_pool_cents`; otherwise `ERR_PRIZE_POOL_EXCEEDED`."
    PRD §2.10: "The **prize ledger** on a show maintains `allocated_prize_cents` as the sum of `awarded_prize_cents` across classes of the show whose `status` is `RESULTS_POSTED` or `POINTS_SUBMITTED`, and `unallocated_prize_cents` as `prize_money_pool_cents` minus `allocated_prize_cents`."
    PRD §2.10: "Classes that are merely `JUDGED`, classes that are `VOIDED`, and classes that have not yet been judged all contribute zero."
    PRD §3.2: "When fewer than five places were filled, the unfilled places' shares are not redistributed to anyone: `awarded_prize_cents` is simply the sum of the filled places' figures and is strictly less than `class_purse_cents`."
    PRD §3.8: "When it succeeds, every class entry on the class has `prize_cents` reset to 0, the class's `awarded_prize_cents` becomes 0, and the show's `allocated_prize_cents` and `unallocated_prize_cents` are recomputed, returning the released purse to the unallocated side with zero drift."

    Design: Corner/validations/prize_pool_exhaustion_blocks_second_posting
    """
    ctx = build_multi_class_show(
        show_overrides={"prize_money_pool_cents": 100000},
        division_overrides={"division_share_bp": 10000},
        class_specs=[
            {"class_number": 101, "name": "Open Jumper 1.20m", "jump_height_cm": 120,
             "class_share_bp": 10000},
            {"class_number": 102, "name": "Open Jumper 1.10m", "jump_height_cm": 110,
             "class_share_bp": 10000},
        ],
        entry_plan=[{"classes": [0, 1]} for _ in range(3)],
    )
    class_a, class_b = ctx["class_ids"]
    assert get_class(class_a)["class_purse_cents"] == 100000
    assert get_class(class_b)["class_purse_cents"] == 100000
    assert get_entry(ctx["field"][0]["entry_id"])["total_due_cents"] == 52500

    slot_a = stage_class_slot(ctx, class_a, "2026-09-10T14:00:00Z")
    slot_b = stage_class_slot(ctx, class_b, "2026-09-10T15:00:00Z")
    assert slot_a["duration_minutes"] == 26
    assert slot_b["duration_minutes"] == 26

    posted_a = run_class_to_posted(ctx, class_a, 26)
    assert posted_a["awarded_prize_cents"] == 81000
    after_first = get_show(ctx["show_id"])
    assert after_first["allocated_prize_cents"] == 81000
    assert after_first["unallocated_prize_cents"] == 19000

    rows_b = confirmed_rows_for_class(ctx, class_b)
    start_slot(slot_b["id"])
    judged_b = record_results(class_b, ctx["judge_id"], default_placings(rows_b), 26)
    assert judged_b["status"] == "JUDGED"

    validate_error(
        api_client.post_class_results(class_b, SECRETARY), "ERR_PRIZE_POOL_EXCEEDED", 409
    )
    blocked = get_class(class_b)
    assert blocked["status"] == "JUDGED"
    assert blocked["awarded_prize_cents"] == 0
    assert [get_class_entry(ce)["prize_cents"] for ce in rows_b] == [0, 0, 0]
    assert get_show(ctx["show_id"])["allocated_prize_cents"] == 81000

    voided = validate_success(api_client.void_class_results(class_a, SECRETARY))
    assert voided["status"] == "VOIDED"
    released = get_show(ctx["show_id"])
    assert released["allocated_prize_cents"] == 0
    assert released["unallocated_prize_cents"] == 100000
    rows_a = [row["by_class"][class_a] for row in ctx["field"]]
    assert [get_class_entry(ce)["prize_cents"] for ce in rows_a] == [0, 0, 0]

    retried = validate_success(api_client.post_class_results(class_b, SECRETARY))
    assert retried["awarded_prize_cents"] == 81000
    assert get_show(ctx["show_id"])["allocated_prize_cents"] == 81000
