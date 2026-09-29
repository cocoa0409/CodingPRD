"""Calculations: duration terms, ledger populations, fee tiers, the purse ladder and the caps."""

from test_helpers import api_client, validate_paginated, validate_success
from test_helpers.fixtures import (
    accept_entry,
    acknowledge,
    approve_license,
    book_slot,
    build_approved_show,
    build_entry,
    build_multi_class_show,
    create_class,
    create_division,
    create_horse,
    create_rider,
    create_ring,
    create_show,
    get_class,
    get_class_entry,
    get_entry,
    get_ring,
    get_show,
    get_slot,
    invoice_entry,
    open_class,
    pay_entry,
    ring_version,
    run_class_to_posted,
    settle_entry,
    stage_class_slot,
    submit_points,
    verify_entry,
    withdraw_entry,
)
from test_helpers.test_users import TEST_USERS

SECRETARY = TEST_USERS["show_secretary_headers"]
RING_MASTER = TEST_USERS["ring_master_headers"]


def _horses_entered(show_id, rider_id, class_ids, count):
    """`count` horses of one rider, each entered in every class, all left at RECEIVED."""
    rows = []
    for _ in range(count):
        horse = create_horse()
        rows.append(build_entry(show_id, rider_id, horse["id"], class_ids))
    return rows


def _projection(show_id):
    return validate_success(api_client.get_schedule_projection(show_id, SECRETARY))


def test_the_jump_off_term_is_gated_on_the_divisions_flag_not_on_the_class():
    """Two classes are identical in fence height and in field size — four entered horses at 120 cm
    — and differ only in the division they hang beneath. The jumper division has jump-offs enabled,
    so its four rounds become six and the estimate is 29 minutes; the hunter division never
    declared the flag, so it defaults to false, no jump-off rounds are added, and the estimate is
    27. Both classes report the same populations, which is what makes the four-minute difference
    attributable to the jump-off term alone.

    PRD §3.2: "And it declares with `jumpoff_enabled` whether its classes run a jump-off; the flag defaults to false and only affects duration estimation for jumper classes."
    PRD §3.6: "Start from a base round time in seconds determined by the division's `discipline`: 90 seconds for `HUNTER`, 75 for `JUMPER`, 100 for `EQUITATION` and 300 for `DRESSAGE`."
    PRD §3.6: "A jump-off adds rounds only when the division's `jumpoff_enabled` is true *and* the division's `discipline` is `JUMPER`; in that case the jump-off rounds are the smaller of 8 and the entry count multiplied by 0.30 rounded up to a whole number."
    PRD §3.6: "In every other case there are zero jump-off rounds."
    PRD §3.6: "Finally, `estimated_minutes` is ride time plus course walk time plus the ring's `turnover_buffer_minutes`."
    PRD §3.6: "Its `duration_minutes` is copied from the class's freshly computed `estimated_minutes`; its `end_utc` is its `start_utc` advanced by `duration_minutes`, and that upper bound is half-open, so the ring is free again at `end_utc`; and its `warmup_start_utc` is its `start_utc` moved back by 30 minutes, marking the beginning of the supervised warm-up window."

    Design: Corner/calculations/duration_omits_jumpoff_for_non_jumper_division
    """
    show = create_show()
    ring = create_ring(show["id"])
    jumper_division = create_division(show["id"])
    hunter_division = validate_success(
        api_client.create_division(
            show["id"],
            {
                "name": "Open Hunter",
                "discipline": "HUNTER",
                "age_group": "OPEN",
                "min_jump_height_cm": 80,
                "max_jump_height_cm": 130,
                "division_share_bp": 3000,
            },
            SECRETARY,
        ),
        201,
    )
    assert hunter_division["jumpoff_enabled"] is False
    assert jumper_division["jumpoff_enabled"] is True

    jumper_class = create_class(jumper_division["id"])
    hunter_class = create_class(
        hunter_division["id"],
        class_number=201,
        name="Open Hunter 1.20m",
        jump_height_cm=120,
        class_share_bp=1000,
    )
    approve_license(show["id"])
    open_class(jumper_class["id"])
    open_class(hunter_class["id"])

    rider = create_rider()
    _horses_entered(show["id"], rider["id"], [jumper_class["id"], hunter_class["id"]], 4)

    jumper_slot = book_slot(ring["id"], jumper_class["id"], "2026-09-10T14:00:00Z")
    hunter_slot = book_slot(ring["id"], hunter_class["id"], "2026-09-10T15:00:00Z")

    assert jumper_slot["duration_minutes"] == 29
    assert jumper_slot["end_utc"] == "2026-09-10T14:29:00Z"
    assert hunter_slot["duration_minutes"] == 27
    assert hunter_slot["end_utc"] == "2026-09-10T15:27:00Z"

    jumper_read = get_class(jumper_class["id"])
    hunter_read = get_class(hunter_class["id"])
    assert jumper_read["estimated_minutes"] == 29
    assert hunter_read["estimated_minutes"] == 27
    assert jumper_read["entry_count"] == hunter_read["entry_count"] == 4
    assert jumper_read["confirmed_entry_count"] == hunter_read["confirmed_entry_count"] == 0

    ring_after = get_ring(ring["id"])
    assert ring_after["scheduled_minutes_total"] == 56
    assert ring_after["slot_count"] == 2


def test_the_height_factor_is_clamped_below_a_metre_and_alive_one_centimetre_above_it():
    """Three hunter classes with the same four-horse field are booked at 60, 100 and 101
    centimetres. The 60 cm class does not get a discount — the factor's excess term is floored at
    zero — so it estimates the same 26 minutes as the 100 cm class that sits exactly on the
    threshold. One centimetre higher the factor is live at 1.005, and because the single rounding
    up happens after both multiplications, 6.03 ride minutes become 7 and the estimate steps to 27.

    PRD §3.6: "Next compute a height factor as 1 plus the greater of zero and the amount by which the class's `jump_height_cm` exceeds 100 centimetres, that excess divided by 200 — so a 100-centimetre class has a factor of exactly 1, a 140-centimetre class a factor of 1.2, and a class below 100 centimetres also exactly 1."
    PRD §3.6: "Course walk time is the greater of 10 minutes and the entry count divided by ten, rounded up to a whole number, then multiplied by 5 minutes."
    PRD §3.6: "Ride time in minutes is obtained by multiplying the total round count — scheduled rounds plus jump-off rounds — by the base round seconds, multiplying that product by the height factor, dividing by 60, and rounding the result up to a whole minute."
    PRD §3.6: "The single rounding-up happens exactly once, at the end, after both multiplications; rounding each round to whole minutes and then summing is not the specified order and produces a different answer."
    PRD §3.6: "The ring's `scheduled_minutes_total` becomes the sum, over those same occupancies, of the whole minutes from each one's `start_utc` to its `end_utc`, and `slot_count` becomes their count."

    Design: Corner/calculations/duration_height_factor_floors_below_base_height
    """
    ctx = build_approved_show(
        division_overrides={
            "name": "Cross Rail Hunter",
            "discipline": "HUNTER",
            "min_jump_height_cm": 60,
            "max_jump_height_cm": 130,
            "division_share_bp": 3000,
            "jumpoff_enabled": False,
        },
        class_specs=[
            {"class_number": 301, "name": "Cross Rails 0.60m", "jump_height_cm": 60,
             "class_share_bp": 1000},
            {"class_number": 302, "name": "Hunter 1.00m", "jump_height_cm": 100,
             "class_share_bp": 1000},
            {"class_number": 303, "name": "Hunter 1.01m", "jump_height_cm": 101,
             "class_share_bp": 1000},
        ],
        ring_specs=[{}],
    )
    low, base, above = ctx["class_ids"]
    rider = create_rider()
    _horses_entered(ctx["show_id"], rider["id"], [low, base, above], 4)

    slot_low = book_slot(ctx["ring_id"], low, "2026-09-10T14:00:00Z")
    slot_base = book_slot(ctx["ring_id"], base, "2026-09-10T15:00:00Z")
    slot_above = book_slot(ctx["ring_id"], above, "2026-09-10T16:00:00Z")

    assert slot_low["duration_minutes"] == 26
    assert slot_base["duration_minutes"] == 26
    assert slot_above["duration_minutes"] == 27

    assert slot_low["end_utc"] == "2026-09-10T14:26:00Z"
    assert slot_base["end_utc"] == "2026-09-10T15:26:00Z"
    assert slot_above["end_utc"] == "2026-09-10T16:27:00Z"

    ring = get_ring(ctx["ring_id"])
    assert ring["scheduled_minutes_total"] == 79
    assert ring["slot_count"] == 3


def test_a_scratched_row_leaves_the_estimate_and_the_projection_counts_only_live_horses():
    """Five class-entry rows exist on the class but one has been scratched by its entry's
    withdrawal, so the projected population is four and the booking freezes 29 minutes rather than
    the 30 that counting every row would give. The projection read then puts the two variants side
    by side: 29 against 20, because with no confirmed rides at all the course walk and the ring's
    turnover buffer still stand, and the drift between the variants is 9 minutes.

    PRD §3.6: "The *projected* variant counts class entries whose `status` is `ENTERED` or `CONFIRMED`, so it includes horses whose parent entry has not yet been accepted or paid."
    PRD §3.6: "Rows whose `status` is `SCRATCHED` or `DISQUALIFIED` are excluded from both."
    PRD §3.6: "Booking a class into a ring writes the *projected* variant into `estimated_minutes`."
    PRD §3.6: "For every class of the show that currently holds an occupancy whose `status` is `SCHEDULED` or `RUNNING`, it recomputes both variants against that occupancy's ring and returns `show_id`, the aggregate `projected_total_minutes` from the projected variant, the aggregate `confirmed_only_total_minutes` from the confirmed-only variant, `projected_drift_minutes` as `projected_total_minutes` minus `confirmed_only_total_minutes`, and a `class_projections` array carrying the per-class figures."
    PRD §3.2: "`entry_count` is the number of class entries on the class whose `status` is `ENTERED`, `CONFIRMED`, `COMPLETED` or `DISQUALIFIED` — scratched rows drop out of it — and it is `entry_count` that `max_entries` caps."

    Design: Corner/calculations/duration_input_set_excludes_scratched_rows
    """
    ctx = build_approved_show(ring_specs=[{}])
    rider = create_rider()
    rows = _horses_entered(ctx["show_id"], rider["id"], [ctx["class_id"]], 5)

    withdrawn = withdraw_entry(rows[4]["entry_id"], rider["id"])
    assert withdrawn["verification_status"] == "WITHDRAWN"
    assert get_class_entry(rows[4]["class_entry_id"])["status"] == "SCRATCHED"
    assert [get_class_entry(row["class_entry_id"])["status"] for row in rows[:4]] == [
        "ENTERED"
    ] * 4

    live_class = get_class(ctx["class_id"])
    assert live_class["entry_count"] == 4
    assert live_class["confirmed_entry_count"] == 0

    slot = book_slot(ctx["ring_id"], ctx["class_id"], "2026-09-10T14:00:00Z")
    assert slot["duration_minutes"] == 29

    projection = _projection(ctx["show_id"])
    assert projection["projected_total_minutes"] == 29
    assert projection["confirmed_only_total_minutes"] == 20
    assert projection["projected_drift_minutes"] == 9
    assert len(projection["class_projections"]) == 1


def test_only_accepted_entries_put_stalls_on_the_ledger():
    """Fifteen stalls are asked for across three entries and the ledger ignores every one of them
    until the entry that asked is accepted. Verifying the first entry moves nothing at all; the
    acceptance that follows commits its five; the second acceptance brings the total to eleven
    against twenty-nine available. The third entry, still only RECEIVED, keeps its request of four
    entirely outside the sum with nothing assigned to it, and the capacity invariant holds at every
    read.

    PRD §2.10: "The **stall ledger** on a show maintains `reserved_stall_count` as the sum of `assigned_stall_count` across all of that show's entries whose `verification_status` is `ACCEPTED`, and `available_stall_count` as `stall_capacity` minus `reserved_stall_count`."
    PRD §2.10: "Entries in `RECEIVED`, `VERIFIED` or `WITHDRAWN` contribute zero regardless of what they requested."
    PRD §2.10: "The invariant `stall_capacity` equals `reserved_stall_count` plus `available_stall_count` holds before and after every acceptance and every withdrawal."
    PRD §3.5: "On success the entry's `assigned_stall_count` is set to its `requested_stall_count`, the show's `reserved_stall_count` and `available_stall_count` are recomputed per the stall ledger of §2.10, and both the entry's and the show's `version` increment."

    Design: Corner/calculations/stall_ledger_counts_only_accepted_entries
    """
    ctx = build_multi_class_show(
        class_specs=[{}],
        entry_plan=[
            {"classes": [0], "confirm": False, "stalls": 5},
            {"classes": [0], "confirm": False, "stalls": 6},
            {"classes": [0], "confirm": False, "stalls": 4},
        ],
    )
    first, second, third = ctx["field"]

    verify_entry(first["entry_id"])
    mid_flight = get_show(ctx["show_id"])
    assert mid_flight["reserved_stall_count"] == 0
    assert mid_flight["available_stall_count"] == 40
    assert get_entry(first["entry_id"])["assigned_stall_count"] == 0

    accept_entry(first["entry_id"])
    after_first = get_show(ctx["show_id"])
    assert after_first["reserved_stall_count"] == 5
    assert after_first["available_stall_count"] == 35
    assert get_entry(first["entry_id"])["assigned_stall_count"] == 5

    verify_entry(second["entry_id"])
    accept_entry(second["entry_id"])
    after_second = get_show(ctx["show_id"])
    assert after_second["reserved_stall_count"] == 11
    assert after_second["available_stall_count"] == 29
    assert get_entry(second["entry_id"])["assigned_stall_count"] == 6

    left_out = get_entry(third["entry_id"])
    assert left_out["verification_status"] == "RECEIVED"
    assert left_out["requested_stall_count"] == 4
    assert left_out["assigned_stall_count"] == 0

    for show in (mid_flight, after_first, after_second):
        assert show["reserved_stall_count"] + show["available_stall_count"] == 40


def test_the_office_fee_steps_exactly_on_fifty_thousand_and_on_one_hundred_thousand():
    """Four invoices are frozen against the same show. One class of 25000 sits below the reduced
    tier and pays 5000; two classes land exactly on 50000 and pay the reduced 2500; four classes
    land exactly on 100000 and pay nothing. The fourth invoice is the one that proves the tier is
    keyed on the preliminary subtotal rather than on class fees: one class plus three requested
    stalls comes to 47500, a tier below the two-class entry, even though both entries end up owing
    the same 52500.

    PRD §3.5: "Second, `stall_fee_cents` is the entry's `requested_stall_count` multiplied by the show's `stall_fee_cents` — the *requested* count, never the assigned one, which is why the invoice is entirely independent of where the verification dimension has got to."
    PRD §3.5: "Third, `preliminary_subtotal_cents` is `class_fee_cents_total` plus `stall_fee_cents`."
    PRD §3.5: "The tier is keyed on `preliminary_subtotal_cents` — the pre-fee figure — and evaluated exactly once."
    PRD §3.5: "When `preliminary_subtotal_cents` is at least 100000 cents, `office_fee_cents` is 0."
    PRD §3.5: "When it is at least 50000 cents but below 100000, `office_fee_cents` is 2500."
    PRD §3.5: "Below 50000 cents, `office_fee_cents` is 5000."
    PRD §3.5: "Finally `total_due_cents` is `preliminary_subtotal_cents` plus `office_fee_cents`, and there is no re-evaluation: a subtotal of 97500 cents attracts a 2500-cent office fee and a total of 100000 cents, even though 100000 would itself have qualified for the waiver."

    Design: Corner/calculations/office_fee_tier_boundaries_at_exact_thresholds
    """
    ctx = build_multi_class_show(
        class_specs=[
            {"class_number": 101, "name": "Open Jumper A", "class_share_bp": 1000},
            {"class_number": 102, "name": "Open Jumper B", "class_share_bp": 1000},
            {"class_number": 103, "name": "Open Jumper C", "class_share_bp": 1000},
            {"class_number": 104, "name": "Open Jumper D", "class_share_bp": 1000},
        ],
        entry_plan=[
            {"classes": [0], "confirm": False},
            {"classes": [0, 1], "confirm": False},
            {"classes": [0, 1, 2, 3], "confirm": False},
            {"classes": [0], "confirm": False, "stalls": 3},
        ],
    )
    one_class, two_classes, four_classes, with_stalls = ctx["field"]

    below = invoice_entry(one_class["entry_id"])
    assert below["class_fee_cents_total"] == 25000
    assert below["stall_fee_cents"] == 0
    assert below["preliminary_subtotal_cents"] == 25000
    assert below["office_fee_cents"] == 5000
    assert below["total_due_cents"] == 30000

    reduced = invoice_entry(two_classes["entry_id"])
    assert reduced["class_fee_cents_total"] == 50000
    assert reduced["preliminary_subtotal_cents"] == 50000
    assert reduced["office_fee_cents"] == 2500
    assert reduced["total_due_cents"] == 52500

    waived = invoice_entry(four_classes["entry_id"])
    assert waived["class_fee_cents_total"] == 100000
    assert waived["preliminary_subtotal_cents"] == 100000
    assert waived["office_fee_cents"] == 0
    assert waived["total_due_cents"] == 100000

    stalls = invoice_entry(with_stalls["entry_id"])
    assert stalls["class_fee_cents_total"] == 25000
    assert stalls["stall_fee_cents"] == 22500
    assert stalls["preliminary_subtotal_cents"] == 47500
    assert stalls["office_fee_cents"] == 5000
    assert stalls["total_due_cents"] == 52500
    assert stalls["assigned_stall_count"] == 0
    assert stalls["verification_status"] == "RECEIVED"

    assert {get_entry(row["entry_id"])["settlement_status"] for row in ctx["field"]} == {
        "INVOICED"
    }


def test_the_rounding_residual_is_folded_into_first_place_in_both_directions():
    """Two classes of the same show pay full five-ribbon ladders whose rounding residuals have
    opposite signs. The 41721-cent purse rounds down to 41720 across its five places, so first
    place is lifted a cent above its own share to 16689; the 24998-cent purse rounds up to 24999,
    so first place is cut a cent below its share to 9998. In both classes the purse is exhausted to
    the cent, which is only true because the residual is reconciled — and the show's prize ledger
    reflects exactly the two purses.

    PRD §3.2: "A class's `class_purse_cents` is then its division's already-rounded `division_allotment_cents` multiplied by the class's `class_share_bp`, divided by 10000, rounded half up to whole cents."
    PRD §3.2: "Working upward from first place to that last paying place, each place's cents figure is computed independently as `class_purse_cents` multiplied by that place's basis-point share, divided by 10000, rounded half up to whole cents."
    PRD §3.2: "Residual reconciliation applies in exactly one situation: when all five ribbons were filled."
    PRD §3.2: "In that case the difference between `class_purse_cents` and the sum of the five rounded figures — which may be negative — is added to first place's figure, and the class's `awarded_prize_cents` becomes exactly `class_purse_cents`."
    PRD §2.10: "The **prize ledger** on a show maintains `allocated_prize_cents` as the sum of `awarded_prize_cents` across classes of the show whose `status` is `RESULTS_POSTED` or `POINTS_SUBMITTED`, and `unallocated_prize_cents` as `prize_money_pool_cents` minus `allocated_prize_cents`."

    Design: Corner/calculations/prize_residual_folded_into_first_place_at_five_ribbons
    """
    ctx = build_multi_class_show(
        class_specs=[
            {"class_number": 101, "name": "Open Jumper 1.20m", "jump_height_cm": 120,
             "class_share_bp": 1669},
            {"class_number": 102, "name": "Open Jumper 1.10m", "jump_height_cm": 110,
             "class_share_bp": 1000},
        ],
        entry_plan=[{"classes": [0, 1]} for _ in range(5)],
    )
    class_a, class_b = ctx["class_ids"]
    assert get_class(class_a)["class_purse_cents"] == 41721
    assert get_class(class_b)["class_purse_cents"] == 24998

    slot_a = stage_class_slot(ctx, class_a, "2026-09-10T14:00:00Z")
    slot_b = stage_class_slot(ctx, class_b, "2026-09-10T15:10:00Z")
    assert slot_a["duration_minutes"] == 30
    assert slot_b["duration_minutes"] == 30

    posted_a = run_class_to_posted(ctx, class_a, 30)
    posted_b = run_class_to_posted(ctx, class_b, 30)

    rows_a = [row["by_class"][class_a] for row in ctx["field"]]
    rows_b = [row["by_class"][class_b] for row in ctx["field"]]
    assert [get_class_entry(ce)["prize_cents"] for ce in rows_a] == [
        16689, 10430, 6675, 4589, 3338
    ]
    assert [get_class_entry(ce)["prize_cents"] for ce in rows_b] == [
        9998, 6250, 4000, 2750, 2000
    ]

    assert posted_a["awarded_prize_cents"] == 41721 == posted_a["class_purse_cents"]
    assert posted_b["awarded_prize_cents"] == 24998 == posted_b["class_purse_cents"]
    assert posted_a["status"] == posted_b["status"] == "RESULTS_POSTED"
    assert posted_a["placed_count"] == posted_b["placed_count"] == 5

    show = get_show(ctx["show_id"])
    assert show["allocated_prize_cents"] == 66719
    assert show["unallocated_prize_cents"] == 683281


def test_the_third_regional_win_is_truncated_to_the_headroom_that_is_left():
    """One rider wins all three classes of a show. The first two wins credit 8 apiece, and the
    third is truncated to 4 — the headroom that remains under the per-show ceiling of 20 — rather
    than dropped or left at its raw table value. The rider two places behind keeps 5 + 5 + 5
    untouched, because the ceiling is applied per rider, and the national ladder pays a full
    10 + 10 + 10 to the same winner, because the ceiling is regional only.

    PRD §3.8: "A per-show ceiling of 20 regional points then applies per rider: the class entries of the same show belonging to the same rider are processed in ascending order of the class's `class_number`, with the class entry's `created_at` ascending as the tie-break, and each row's `points_regional` is the smaller of its raw table value and whatever headroom remains — that is, the greater of zero and 20 minus the regional points already credited to that rider for that show."
    PRD §3.8: ""Already credited" sums `points_regional` over that rider's class entries at the same show whose submission has a `status` of `REGIONAL_ACCEPTED` or `RECORDED`."
    PRD §3.8: "It awards only through third place — 8 points for first, 5 for second, 3 for third — and any placing beyond third scores zero."
    PRD §3.8: "There is no per-show cap on national points."
    PRD §3.8: "A rider's standings read recomputes both totals from accepted submissions without storing anything, optionally scoped by `show_id`, and returns `rider_id`, `national_points_total`, `regional_points_total`, `national_class_count` — the number of classes contributing national points — and `regional_capped`, a boolean reporting whether the per-show regional ceiling bound."

    Design: Corner/calculations/regional_show_cap_truncates_the_third_win
    """
    ctx = build_multi_class_show(
        class_specs=[
            {"class_number": 101, "name": "Open Jumper 1.20m", "jump_height_cm": 120,
             "class_share_bp": 1669},
            {"class_number": 102, "name": "Open Jumper 1.10m", "jump_height_cm": 110,
             "class_share_bp": 1000},
            {"class_number": 103, "name": "Open Jumper 1.00m", "jump_height_cm": 100,
             "class_share_bp": 1000},
        ],
        entry_plan=[{"classes": [0, 1, 2]} for _ in range(3)],
    )
    class_a, class_b, class_c = ctx["class_ids"]
    winner, runner_up, third_rider = ctx["field"]

    for class_id, start in (
        (class_a, "2026-09-10T14:00:00Z"),
        (class_b, "2026-09-10T15:00:00Z"),
        (class_c, "2026-09-10T16:00:00Z"),
    ):
        stage_class_slot(ctx, class_id, start)

    run_class_to_posted(ctx, class_a, 26)
    run_class_to_posted(ctx, class_b, 26)
    run_class_to_posted(ctx, class_c, 25)

    for class_id, regional_ref, national_ref in (
        (class_a, "REG-SE-0101", "NAT-2026-00501"),
        (class_b, "REG-SE-0102", "NAT-2026-00502"),
    ):
        submission = submit_points(class_id)
        acknowledge(submission["id"], "REGIONAL", "ACCEPTED", regional_ref)
        recorded = acknowledge(submission["id"], "NATIONAL", "ACCEPTED", national_ref)
        assert recorded["status"] == "RECORDED"

    assert get_class_entry(winner["by_class"][class_a])["points_regional"] == 8
    assert get_class_entry(winner["by_class"][class_b])["points_regional"] == 8

    last = submit_points(class_c)
    acknowledge(last["id"], "REGIONAL", "ACCEPTED", "REG-SE-0103")
    final_submission = acknowledge(last["id"], "NATIONAL", "ACCEPTED", "NAT-2026-00503")

    assert get_class_entry(winner["by_class"][class_c])["points_regional"] == 4
    assert get_class_entry(runner_up["by_class"][class_c])["points_regional"] == 5
    assert get_class_entry(third_rider["by_class"][class_c])["points_regional"] == 3

    assert get_class_entry(winner["by_class"][class_c])["points_national"] == 10.0
    assert get_class_entry(runner_up["by_class"][class_c])["points_national"] == 6.0
    assert get_class_entry(third_rider["by_class"][class_c])["points_national"] == 4.0

    assert final_submission["status"] == "RECORDED"
    assert final_submission["regional_points_total"] == 12
    assert final_submission["national_points_total"] == 20.0

    capped = validate_success(
        api_client.get_rider_standings(
            winner["rider_id"], SECRETARY, params={"show_id": ctx["show_id"]}
        )
    )
    assert capped["regional_points_total"] == 20
    assert capped["regional_capped"] is True
    assert capped["national_points_total"] == 30.0
    assert capped["national_class_count"] == 3

    uncapped = validate_success(
        api_client.get_rider_standings(
            runner_up["rider_id"], SECRETARY, params={"show_id": ctx["show_id"]}
        )
    )
    assert uncapped["regional_points_total"] == 15
    assert uncapped["regional_capped"] is False

    assert get_show(ctx["show_id"])["allocated_prize_cents"] == 74291


def test_the_running_order_is_a_clock_rank_so_the_first_booking_ends_up_last():
    """The 16:00 class is booked first and is momentarily rank 1 because nothing else is on the
    ring. Inserting 14:00 renumbers the whole ring rather than appending, so the new booking takes
    rank 1 and the 16:00 occupancy is pushed down; inserting 15:00 lands between them. The ring
    ends up numbered in clock order, which puts the first booking taken last, and the ring's
    version has moved exactly once per accepted booking.

    PRD §3.6: "After every insertion — a class booking or a maintenance hold — the ring's running order is recomputed across the whole ring."
    PRD §3.6: "The occupancies that count are those whose `status` is `SCHEDULED`, `RUNNING` or `COMPLETED`; they are sorted by `start_utc` ascending, with `created_at` ascending as the sole tie-break (`id` is never consulted), and each is assigned a 1-based `order_index` equal to its position in that sorted list."
    PRD §3.6: "The ring's `scheduled_minutes_total` becomes the sum, over those same occupancies, of the whole minutes from each one's `start_utc` to its `end_utc`, and `slot_count` becomes their count."
    PRD §2.7: "The reason is that a ring's running order is one ordered artifact: any earlier accepted booking, or a footing-maintenance hold, renumbers `order_index` across the whole ring and legitimately supersedes the layout the current writer was reading."

    Design: Corner/calculations/order_index_recomputed_for_out_of_order_booking
    """
    ctx = build_approved_show(
        class_specs=[
            {"class_number": 101, "name": "Open Jumper A", "class_share_bp": 1000},
            {"class_number": 102, "name": "Open Jumper B", "class_share_bp": 1000},
            {"class_number": 103, "name": "Open Jumper C", "class_share_bp": 1000},
        ],
        ring_specs=[{}],
    )
    late_class, early_class, mid_class = ctx["class_ids"]
    assert ring_version(ctx["ring_id"]) == 1

    late = book_slot(ctx["ring_id"], late_class, "2026-09-10T16:00:00Z")
    assert late["order_index"] == 1

    early = book_slot(ctx["ring_id"], early_class, "2026-09-10T14:00:00Z")
    assert early["order_index"] == 1

    mid = book_slot(ctx["ring_id"], mid_class, "2026-09-10T15:00:00Z")
    assert mid["order_index"] == 2

    assert get_slot(early["id"])["order_index"] == 1
    assert get_slot(mid["id"])["order_index"] == 2
    assert get_slot(late["id"])["order_index"] == 3

    rows, meta = validate_paginated(
        api_client.list_ring_slots(
            RING_MASTER, params={"ring_id": ctx["ring_id"], "status": "SCHEDULED"}
        )
    )
    assert meta["total_count"] == 3
    assert {row["duration_minutes"] for row in rows} == {20}

    ring = get_ring(ctx["ring_id"])
    assert ring["scheduled_minutes_total"] == 60
    assert ring["slot_count"] == 3
    assert ring["version"] == 4


def test_the_projection_drift_closes_when_the_outstanding_entries_pay_up():
    """At booking time two of four entered horses are confirmed, so the projection reports 29
    against 25 with four minutes of drift. Taking the other two entries through acceptance and
    payment moves the confirmed-only variant up to the projected figure and the drift closes to
    zero. The stored estimate does not move with it: it was frozen when the slot was booked, and
    the reconciliation read stores nothing.

    PRD §3.6: "The *confirmed-only* variant counts class entries whose `status` is exactly `CONFIRMED`."
    PRD §3.6: "Because confirmation requires both entry dimensions, the confirmed-only population is always a subset of the projected one, and the two variants therefore report different minute counts over identical stored data."
    PRD §3.6: "The read computes and stores nothing."
    PRD §3.5: "Whichever of acceptance or payment completes the pair sweeps this entry's class entries whose `status` is `ENTERED`, moves each `ENTERED → CONFIRMED`, and recomputes the affected classes' `confirmed_entry_count` and `point_eligible`."
    PRD §3.8: "A class not in `RESULTS_POSTED` is refused with `ERR_CLASS_RESULTS_NOT_POSTED`, and a class whose `point_eligible` is false — that is, whose `confirmed_entry_count` is below 3 — is refused with `ERR_CLASS_NOT_POINT_ELIGIBLE`."

    Design: Corner/calculations/projection_drift_closes_after_late_confirmation
    """
    ctx = build_approved_show(ring_specs=[{}])
    rider = create_rider()
    rows = _horses_entered(ctx["show_id"], rider["id"], [ctx["class_id"]], 4)
    for row in rows[:2]:
        settle_entry(row["entry_id"], rider["id"])
        verify_entry(row["entry_id"])
        accept_entry(row["entry_id"])

    slot = book_slot(ctx["ring_id"], ctx["class_id"], "2026-09-10T14:00:00Z")
    assert slot["duration_minutes"] == 29

    before = _projection(ctx["show_id"])
    assert before["projected_total_minutes"] == 29
    assert before["confirmed_only_total_minutes"] == 25
    assert before["projected_drift_minutes"] == 4

    for row in rows[2:]:
        verify_entry(row["entry_id"])
        accept_entry(row["entry_id"])
        invoice_entry(row["entry_id"])
        pay_entry(row["entry_id"], rider["id"], 30000)

    after = _projection(ctx["show_id"])
    assert after["projected_total_minutes"] == 29
    assert after["confirmed_only_total_minutes"] == 29
    assert after["projected_drift_minutes"] == 0

    final_class = get_class(ctx["class_id"])
    assert final_class["estimated_minutes"] == 29
    assert final_class["entry_count"] == 4
    assert final_class["confirmed_entry_count"] == 4
    assert final_class["point_eligible"] is True

    assert [get_class_entry(row["class_entry_id"])["status"] for row in rows] == [
        "CONFIRMED"
    ] * 4
    assert get_slot(slot["id"])["duration_minutes"] == 29
