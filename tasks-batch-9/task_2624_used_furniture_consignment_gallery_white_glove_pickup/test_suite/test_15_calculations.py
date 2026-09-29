"""Figures the gallery must land on exactly: scores, quotes, credits and bands."""

from test_helpers import (
    FLOOR_OPERATOR_ID,
    GALLERY_MANAGER,
    GALLERY_MANAGER_ID,
    LOGISTICS_COORDINATOR,
    SCORES_GRADE_A,
    SCORES_GRADE_B,
    api_client,
    approve_audit_write_off,
    create_active_agreement,
    create_consignor,
    create_item,
    create_price_schedule,
    create_truck,
    create_zone,
    elect_disposition,
    fetch_consignor,
    fetch_item,
    fetch_pickup_job,
    fetch_zone,
    get_success_data,
    pickup_job_payload,
    place_item,
    receive_item,
    run_markdown_epoch,
    schedule_pickup,
    screen_item,
    set_clock,
    setup_consignor_with_active_agreement,
    submit_shrinkage_audit,
    take_custody,
    total_count,
)

ONE_STEP = [(1, 0, 0.00, 0)]
FOUR_STEP_NO_FLOOR = [
    (1, 0, 0.00, 0),
    (2, 30, 0.15, 0),
    (3, 60, 0.30, 0),
    (4, 90, 0.50, 0),
]

SCORES_ON_THE_C_BOUNDARY = {
    "photo_surface_score": 5.0,
    "photo_structure_score": 4.5,
    "photo_completeness_score": 3.58,
}

TRESTLE_TABLE = {
    "title": "Trestle dining table",
    "category": "DINING",
    "declared_value_cents": 40_000,
    "photo_count": 4,
    "volume_cuft": 22,
    "footprint_sqft": 16,
}
SCUFFED_DRESSER = {
    "title": "Scuffed dresser",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 3,
    "volume_cuft": 14,
    "footprint_sqft": 18,
}


def test_a_grade_a_dining_table_tickets_at_thirty_five_thousand_seven_hundred():
    """Both rounding steps land, and the dining premium above one is actually applied.

    PRD 3.3: "Multiply the surface sub-score by 45 hundredths, the structure sub-score
    by 30 hundredths and the completeness sub-score by 25 hundredths, add the three
    products together, and round that sum half up to two decimal places"

    PRD 3.3: "otherwise a score of 8.50 or higher grades `A`; otherwise a score of 6.50
    or higher grades `B`"

    PRD 3.3: "First, multiply `declared_value_cents` by the grade factor and round the
    product half up to a whole number of cents: the grade factors are 85 hundredths for
    `A`, 70 hundredths for `B`, 55 hundredths for `C` and 40 hundredths for `D`."

    PRD 3.3: "Second, take that already-rounded integer number of cents, multiply it by
    the category factor, and round that product half up to a whole number of cents."

    PRD 3.3: "The category factors are 95 hundredths for `SOFA`, 105 hundredths for
    `DINING`, 100 hundredths for `CASEGOOD`"

    PRD 3.3: "while the derived grade seeds `condition_grade` as well as
    `provisional_condition_grade`, so the piece can be quoted and scheduled onto a truck
    before anyone has physically touched it"

    PRD 3.6: "on a first placement `days_on_floor` is 0, so the step in force is the
    sequence-1 step sitting at day offset 0, `markdown_sequence` becomes 1"

    Design: Corner/calculations/grade_a_dining_piece_prices_at_thirty_five_thousand_seven_hundred
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    table = create_item(world["agreement"]["id"], **TRESTLE_TABLE)

    screened = screen_item(table["id"], scores=SCORES_GRADE_A)

    assert screened["photo_score"] == 8.55, (
        f"Expected 0.45*8.0 + 0.30*9.0 + 0.25*9.0 = 8.55, "
        f"got {screened['photo_score']}"
    )
    assert screened["provisional_condition_grade"] == "A", (
        f"Expected grade A at 8.55, got {screened['provisional_condition_grade']}"
    )
    assert screened["condition_grade"] == "A", (
        f"Expected the effective grade seeded to A, got {screened['condition_grade']}"
    )
    assert screened["provisional_list_price_cents"] == 35_700, (
        f"Expected round_half_up(34000 * 1.05) = 35700, "
        f"got {screened['provisional_list_price_cents']}"
    )
    assert screened["list_price_cents"] == 35_700, (
        f"Expected the ticket price seeded to 35700, "
        f"got {screened['list_price_cents']}"
    )
    assert screened["current_price_cents"] == 35_700, (
        f"Expected the posted price seeded to 35700, "
        f"got {screened['current_price_cents']}"
    )
    assert screened["markdown_sequence"] == 0, (
        f"Expected no markdown step before placement, "
        f"got {screened['markdown_sequence']}"
    )


def test_the_weighted_photo_score_rounds_half_up_onto_the_c_boundary():
    """Four forty-nine and a half is a C, not a D, so the dresser tickets at 33,000.

    PRD 3.3: "Multiply the surface sub-score by 45 hundredths, the structure sub-score
    by 30 hundredths and the completeness sub-score by 25 hundredths, add the three
    products together, and round that sum half up to two decimal places"

    PRD 3.3: "a `photo_score` below 3.00 grades `REJECTED`; otherwise a score of 8.50 or
    higher grades `A`; otherwise a score of 6.50 or higher grades `B`; otherwise a score
    of 4.50 or higher grades `C`; otherwise the piece grades `D`"

    PRD 3.3: "never to the raw weighted sum, and the ladder is walked from the top"

    PRD 3.3: "First, multiply `declared_value_cents` by the grade factor and round the
    product half up to a whole number of cents: the grade factors are 85 hundredths for
    `A`, 70 hundredths for `B`, 55 hundredths for `C` and 40 hundredths for `D`."

    PRD 3.3: "When the `decision` is `ACCEPT` and the derived grade is anything other
    than `REJECTED`, the piece moves `INTAKE_SUBMITTED → SCREEN_ACCEPTED`."

    Design: Corner/calculations/the_photo_weights_round_half_up_across_the_c_grade_boundary
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    dresser = create_item(world["agreement"]["id"], **SCUFFED_DRESSER)

    screened = screen_item(dresser["id"], scores=SCORES_ON_THE_C_BOUNDARY)

    assert screened["photo_score"] == 4.50, (
        f"Expected the exact weighted sum of 4.495 rounded half up to 4.50, "
        f"got {screened['photo_score']}"
    )
    assert screened["provisional_condition_grade"] == "C", (
        f"Expected grade C at exactly 4.50, "
        f"got {screened['provisional_condition_grade']}"
    )
    assert screened["condition_grade"] == "C", (
        f"Expected the effective grade seeded to C, got {screened['condition_grade']}"
    )
    assert screened["list_price_cents"] == 33_000, (
        f"Expected round_half_up(60000 * 0.55) carried through a category factor of "
        f"1.00, got {screened['list_price_cents']}"
    )
    assert screened["provisional_list_price_cents"] == 33_000, (
        f"Expected the frozen screening price to be 33000, "
        f"got {screened['provisional_list_price_cents']}"
    )
    assert screened["lifecycle_state"] == "SCREEN_ACCEPTED", (
        f"Expected SCREEN_ACCEPTED, got {screened['lifecycle_state']}"
    )


PLACED_CHEST = {
    "title": "Placed chest",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 20,
}
SHELVED_CHEST = {
    "title": "Shelved chest",
    "category": "CASEGOOD",
    "declared_value_cents": 20_000,
    "photo_count": 4,
    "volume_cuft": 8,
    "footprint_sqft": 15,
}


def test_the_markdown_run_walks_past_a_piece_that_was_never_placed():
    """Same owner, same age, one on the floor: only the listed piece steps down.

    PRD 3.7: "It visits every piece whose `listed_at` is not null and whose owning
    agreement is in `status` `ACTIVE` or `EXPIRED`, in `created_at` ascending order, and
    it increments a piece's `version` only when one of that piece's fields actually
    changed."

    PRD 3.7: "so a piece placed nineteen hours ago has been on the floor for zero days.
    When `listed_at` is null, `days_on_floor` is 0."

    PRD 3.7: "The stepped price is `list_price_cents` multiplied by one minus the step's
    `markdown_pct`, rounded half up to a whole number of cents."

    PRD 3.7: "A piece in `ON_FLOOR` whose governing step has a `sequence` of 2 or higher"

    Design: Corner/calculations/the_markdown_run_skips_pieces_that_were_never_placed
    """
    world = setup_consignor_with_active_agreement(schedule_steps=FOUR_STEP_NO_FLOOR)
    agreement_id = world["agreement"]["id"]
    placed = create_item(agreement_id, **PLACED_CHEST)
    shelved = create_item(agreement_id, **SHELVED_CHEST)
    screen_item(placed["id"], scores=SCORES_GRADE_A)
    screen_item(shelved["id"], scores=SCORES_GRADE_A)
    take_custody(world["consignor"]["id"], [placed["id"], shelved["id"]])
    receive_item(placed["id"], scores=SCORES_GRADE_A)
    receive_item(shelved["id"], scores=SCORES_GRADE_A)
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    place_item(placed["id"], zone["id"], tag_code="T-1601")

    set_clock("2026-09-10T00:00:00Z")
    run_markdown_epoch()

    stepped = fetch_item(placed["id"])
    assert stepped["days_on_floor"] == 40, (
        f"Expected 40 whole days since listing, got {stepped['days_on_floor']}"
    )
    assert stepped["markdown_sequence"] == 2, (
        f"Expected the day-30 step in force, got {stepped['markdown_sequence']}"
    )
    assert stepped["current_price_cents"] == 43_350, (
        f"Expected round_half_up(51000 * 0.85) = 43350, "
        f"got {stepped['current_price_cents']}"
    )
    assert stepped["lifecycle_state"] == "MARKED_DOWN", (
        f"Expected MARKED_DOWN, got {stepped['lifecycle_state']}"
    )
    assert stepped["list_price_cents"] == 51_000, (
        f"Expected the ticket price untouched by the run, "
        f"got {stepped['list_price_cents']}"
    )

    skipped = fetch_item(shelved["id"])
    assert skipped["listed_at"] is None, (
        f"Expected a piece that never reached a floor to carry no listing stamp, "
        f"got {skipped['listed_at']}"
    )
    assert skipped["days_on_floor"] == 0, (
        f"Expected 0 days on the floor, got {skipped['days_on_floor']}"
    )
    assert skipped["markdown_sequence"] == 0, (
        f"Expected no step in force, got {skipped['markdown_sequence']}"
    )
    assert skipped["current_price_cents"] == 17_000, (
        f"Expected the screening price of 17000 held, "
        f"got {skipped['current_price_cents']}"
    )
    assert skipped["lifecycle_state"] == "AWAITING_PLACEMENT", (
        f"Expected AWAITING_PLACEMENT, got {skipped['lifecycle_state']}"
    )


HALL_CHEST = {
    "title": "Hall chest",
    "category": "CASEGOOD",
    "declared_value_cents": 200_000,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 18,
}


def test_an_elevator_replaces_the_whole_stair_ladder_with_a_flat_three_thousand():
    """Two fifth-floor residences, and the only difference in the quote is the lift.

    PRD 3.4: "`declared_elevator` is a copy of the consignor's `has_elevator`, and
    `declared_stair_flights` is the consignor's `floor_number` reduced by 1 but never
    below zero"

    PRD 3.4: "except that a consignor who declared an elevator declares zero flights
    regardless of `floor_number`"

    PRD 3.4: "Start from a base of 12,000 cents for showing up at all."

    PRD 3.4: "then charge 2,500 cents per block, so a 41-cubic-foot load pays for five
    blocks"

    PRD 3.4: "Add an access fee: when an elevator is in play the access fee is a flat
    3,000 cents and no stair charge applies at all; otherwise charge 4,500 cents per
    flight for up to 6 flights"

    PRD 3.4: "it reads `declared_stair_flights`, `declared_elevator` and the quoted
    `crew_size`, writes the result to `quoted_surcharge_cents`, and mints no ledger entry
    whatsoever"

    PRD 3.4: "writes `final_surcharge_cents`, together with `surcharge_variance_cents`
    computed as `final_surcharge_cents` minus `quoted_surcharge_cents`.
    `surcharge_variance_cents` is null until completion."

    Design: Corner/calculations/the_elevator_flat_fee_replaces_the_whole_stair_ladder
    """
    schedule = create_price_schedule(steps=ONE_STEP)
    alpha = create_consignor(floor_number=5, has_elevator=False)
    bravo = create_consignor(floor_number=5, has_elevator=True)
    alpha_agreement = create_active_agreement(alpha["id"], schedule["id"])
    bravo_agreement = create_active_agreement(bravo["id"], schedule["id"])
    alpha_chest = create_item(alpha_agreement["id"], **HALL_CHEST)
    bravo_chest = create_item(bravo_agreement["id"], **HALL_CHEST)
    screen_item(alpha_chest["id"], scores=SCORES_GRADE_A)
    screen_item(bravo_chest["id"], scores=SCORES_GRADE_A)

    truck = create_truck(name="BOX-1", capacity_volume_cuft=100)
    stairs_job = schedule_pickup(
        alpha["id"],
        truck["id"],
        [alpha_chest["id"]],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )

    response = api_client.create_pickup_job(
        pickup_job_payload(
            bravo["id"],
            truck["id"],
            "2026-08-01T13:00:00Z",
            "2026-08-01T15:00:00Z",
            item_ids=[bravo_chest["id"]],
        ),
        LOGISTICS_COORDINATOR,
    )
    assert response.status_code == 201, (
        f"Expected the second reservation to be created, got {response.status_code}"
    )
    elevator_job = get_success_data(response)

    assert elevator_job["quoted_surcharge_cents"] == 20_000, (
        f"Expected 12000 + 5000 of volume + a flat 3000 of lift access, "
        f"got {elevator_job['quoted_surcharge_cents']}"
    )
    assert elevator_job["declared_stair_flights"] == 0, (
        f"Expected zero flights declared behind a lift, "
        f"got {elevator_job['declared_stair_flights']}"
    )
    assert elevator_job["declared_elevator"] is True, (
        f"Expected the lift snapshotted from the consignor, "
        f"got {elevator_job['declared_elevator']}"
    )

    walked_up = fetch_pickup_job(stairs_job["id"])
    assert walked_up["quoted_surcharge_cents"] == 35_000, (
        f"Expected 12000 + 5000 of volume + four flights at 4500, "
        f"got {walked_up['quoted_surcharge_cents']}"
    )
    assert walked_up["declared_stair_flights"] == 4, (
        f"Expected four flights up to the fifth floor, "
        f"got {walked_up['declared_stair_flights']}"
    )
    assert walked_up["declared_elevator"] is False, (
        f"Expected no lift declared, got {walked_up['declared_elevator']}"
    )

    for label, job in (("walk-up", walked_up), ("lift", elevator_job)):
        assert job["final_surcharge_cents"] is None, (
            f"Expected the {label} job to carry no final figure before completion, "
            f"got {job['final_surcharge_cents']}"
        )
        assert job["surcharge_variance_cents"] is None, (
            f"Expected the {label} job to carry no variance before completion, "
            f"got {job['surcharge_variance_cents']}"
        )


ODD_DRESSER = {
    "title": "Odd-priced dresser",
    "category": "CASEGOOD",
    "declared_value_cents": 55_001,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 18,
}
ODD_NIGHTSTAND = {
    "title": "Odd-priced nightstand",
    "category": "CASEGOOD",
    "declared_value_cents": 20_004,
    "photo_count": 4,
    "volume_cuft": 21,
    "footprint_sqft": 12,
}


def test_the_write_off_batch_rounds_each_credit_before_it_sums_them():
    """Two odd prices, two separate credits, and a total one cent above the lazy answer.

    PRD 3.9: "The credit for one piece is that piece's `current_price_cents` multiplied by
    60 hundredths and rounded half up to a whole number of cents"

    PRD 3.9: "The batch is walked in `missing_item_ids` order — the pieces' `created_at`
    ascending"

    PRD 3.9: "`write_off_total_cents` is the sum of those already-rounded per-piece
    credits, never a rounding of the summed prices."

    PRD 3.9: "a single merged entry for the batch is never minted"

    PRD 3.9: "Each piece in the batch moves to `inventory_state` `WRITTEN_OFF_INV` and
    `lifecycle_state` `WRITTEN_OFF` with its `placement_zone_id` cleared to null, and each
    owning consignor has `unclaimed_balance_cents` and `lifetime_credits_cents` recomputed
    and `last_activity_at` stamped with the clock."

    PRD 3.9: "The audit's `status` becomes `RECONCILED`, `approved_by_user_id` records the
    acting `X-User-ID`, its `version` increments by 1"

    PRD 3.9: "a consignor's own entries are readable in `effective_at` ascending order
    with an optional `entry_type` filter"

    PRD 2.11: "`lifetime_credits_cents` is the sum of `amount_cents` restricted to entries
    whose amount is positive, so it never decreases."

    PRD 2.10: "Dividing `occupied_sqft` by `capacity_sqft` without rounding, the zone is
    `FULL` when the ratio is at least 1.00, `TIGHT` when the ratio is at least 0.75 but
    below 1.00, and `NORMAL` otherwise."

    Design: Corner/calculations/the_write_off_batch_rounds_each_item_before_summing
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    consignor_id = world["consignor"]["id"]
    agreement_id = world["agreement"]["id"]
    dresser = create_item(agreement_id, **ODD_DRESSER)
    nightstand = create_item(agreement_id, **ODD_NIGHTSTAND)
    screen_item(dresser["id"], scores=SCORES_GRADE_A)
    screen_item(nightstand["id"], scores=SCORES_GRADE_A)
    take_custody(consignor_id, [dresser["id"], nightstand["id"]])
    receive_item(dresser["id"], scores=SCORES_GRADE_A)
    receive_item(nightstand["id"], scores=SCORES_GRADE_A)
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    place_item(dresser["id"], zone["id"], tag_code="TAG-001")
    place_item(nightstand["id"], zone["id"], tag_code="TAG-002")

    counted = submit_shrinkage_audit(zone["id"], [])
    assert counted["variance_count"] == 2, (
        f"Expected a count that found nothing at all, got {counted['variance_count']}"
    )

    reconciled = approve_audit_write_off(counted["id"])

    assert reconciled["write_off_total_cents"] == 38_253, (
        f"Expected 28051 + 10202 = 38253 rather than a rounding of the summed prices, "
        f"got {reconciled['write_off_total_cents']}"
    )
    assert reconciled["status"] == "RECONCILED", (
        f"Expected RECONCILED, got {reconciled['status']}"
    )
    assert reconciled["approved_by_user_id"] == GALLERY_MANAGER_ID, (
        f"Expected the approving manager recorded, "
        f"got {reconciled['approved_by_user_id']}"
    )
    assert reconciled["counted_by_user_id"] == FLOOR_OPERATOR_ID, (
        f"Expected the counting operator retained, "
        f"got {reconciled['counted_by_user_id']}"
    )

    listed = api_client.list_consignor_ledger_entries(
        consignor_id,
        GALLERY_MANAGER,
        params={"entry_type": "SHRINKAGE_CREDIT", "limit": 100},
    )
    assert total_count(listed) == 2, (
        f"Expected one credit per lost piece, got {total_count(listed)}"
    )
    credits = get_success_data(listed)
    assert [entry["amount_cents"] for entry in credits] == [28_051, 10_202], (
        f"Expected round_half_up(46751 * 0.60) then round_half_up(17003 * 0.60), "
        f"got {[entry['amount_cents'] for entry in credits]}"
    )

    consignor = fetch_consignor(consignor_id)
    assert consignor["unclaimed_balance_cents"] == 16_253, (
        f"Expected 28051 + 10202 against 22000 of surcharge, "
        f"got {consignor['unclaimed_balance_cents']}"
    )
    assert consignor["lifetime_credits_cents"] == 38_253, (
        f"Expected 38253 of lifetime credit, "
        f"got {consignor['lifetime_credits_cents']}"
    )

    written_off = fetch_item(dresser["id"])
    assert written_off["inventory_state"] == "WRITTEN_OFF_INV", (
        f"Expected WRITTEN_OFF_INV, got {written_off['inventory_state']}"
    )
    assert written_off["lifecycle_state"] == "WRITTEN_OFF", (
        f"Expected WRITTEN_OFF, got {written_off['lifecycle_state']}"
    )
    assert written_off["placement_zone_id"] is None, (
        f"Expected the zone cleared, got {written_off['placement_zone_id']}"
    )

    emptied = fetch_zone(zone["id"])
    assert emptied["occupied_sqft"] == 0, (
        f"Expected both footprints released, got {emptied['occupied_sqft']}"
    )
    assert emptied["utilization_state"] == "NORMAL", (
        f"Expected NORMAL at 0 of 200, got {emptied['utilization_state']}"
    )


LOUNGE_SOFA = {
    "title": "Lounge sofa",
    "category": "SOFA",
    "declared_value_cents": 189_950,
    "photo_count": 5,
    "volume_cuft": 65,
    "footprint_sqft": 30,
}


def test_a_discount_election_layers_ten_percent_onto_the_step_already_in_force():
    """The same fourth step prices two ways, and the sequence does not advance.

    PRD 3.7: "multiply `list_price_cents` by one minus the step's `markdown_pct`, then
    multiply that by one minus ten hundredths, round the result half up to a whole number
    of cents"

    PRD 3.7: "Identical stored data therefore yields a strictly different
    `current_price_cents` under the two variants, and which variant applies is read from
    `disposition_election` alone."

    PRD 3.7: "Electing `DISCOUNT` puts the piece back to work and is the one election
    that loops. The piece moves `UNSOLD_PENDING_ELECTION → MARKED_DOWN`, `election_round`
    is incremented by 1"

    PRD 3.7: "which immediately pushes `unsold_trigger_day_effective` out by another 30
    days and buys the piece a further stretch of floor time"

    PRD 3.7: "`disposition_election` is set to `DISCOUNT`, `election_deadline_at` is
    cleared to null, and the pricing calculation is re-run in the discount-elected variant
    so the extra ten-percent cut takes effect against the step in force."

    PRD 3.7: "The stepped price is `list_price_cents` multiplied by one minus the step's
    `markdown_pct`, rounded half up to a whole number of cents."

    Design: Corner/calculations/the_discount_election_switches_the_markdown_to_the_discount_elected_variant
    """
    world = setup_consignor_with_active_agreement(schedule_steps=FOUR_STEP_NO_FLOOR)
    consignor_id = world["consignor"]["id"]
    sofa = create_item(world["agreement"]["id"], **LOUNGE_SOFA)
    screen_item(sofa["id"], scores=SCORES_GRADE_B)
    take_custody(consignor_id, [sofa["id"]])
    receive_item(sofa["id"], scores=SCORES_GRADE_B)
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    place_item(sofa["id"], zone["id"], tag_code="T-1701")

    set_clock("2026-11-29T00:00:00Z")
    run_markdown_epoch()

    posted = fetch_item(sofa["id"])
    assert posted["current_price_cents"] == 63_159, (
        f"Expected the posted variant at round_half_up(126317 * 0.50) = 63159, "
        f"got {posted['current_price_cents']}"
    )
    assert posted["lifecycle_state"] == "UNSOLD_PENDING_ELECTION", (
        f"Expected the piece flagged unsold on day 120, "
        f"got {posted['lifecycle_state']}"
    )

    elected = elect_disposition(sofa["id"], "DISCOUNT", consignor_id=consignor_id)

    assert elected["current_price_cents"] == 56_843, (
        f"Expected the discount-elected variant at "
        f"round_half_up(126317 * 0.50 * 0.90) = 56843, "
        f"got {elected['current_price_cents']}"
    )
    assert elected["markdown_sequence"] == 4, (
        f"Expected the extra cut to ride on the same fourth step, "
        f"got {elected['markdown_sequence']}"
    )
    assert elected["list_price_cents"] == 126_317, (
        f"Expected the ticket price never rewritten by a markdown, "
        f"got {elected['list_price_cents']}"
    )
    assert elected["disposition_election"] == "DISCOUNT", (
        f"Expected DISCOUNT recorded, got {elected['disposition_election']}"
    )
    assert elected["election_round"] == 1, (
        f"Expected the first discount round taken, got {elected['election_round']}"
    )
    assert elected["unsold_trigger_day_effective"] == 150, (
        f"Expected 120 pushed out by another 30 days, "
        f"got {elected['unsold_trigger_day_effective']}"
    )
    assert elected["lifecycle_state"] == "MARKED_DOWN", (
        f"Expected the piece back at work in MARKED_DOWN, "
        f"got {elected['lifecycle_state']}"
    )
    assert elected["election_deadline_at"] is None, (
        f"Expected the deadline cleared, got {elected['election_deadline_at']}"
    )


EARLY_CHEST = {
    "title": "Early-registered chest",
    "category": "CASEGOOD",
    "declared_value_cents": 80_000,
    "photo_count": 4,
    "volume_cuft": 8,
    "footprint_sqft": 15,
}
LATE_CHEST = {
    "title": "Late-registered chest",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 20,
}


def test_the_unsold_flag_keys_on_each_pieces_own_listing_day():
    """The older row is the younger listing, and only the day-120 piece is flagged.

    PRD 3.7: "`days_on_floor` is the number of whole days between `listed_at` and the
    current logical clock: subtract `listed_at` from the clock, divide the elapsed seconds
    by 86,400, and discard the remainder"

    PRD 3.6: "because `listed_at` is the origin of the piece's floor tenure and re-placing
    a recovered piece must not reset the clock it has already burned"

    PRD 3.7: "computed as the schedule's `unsold_trigger_day` plus 30 days for each
    discount round the consignor has already taken"

    PRD 3.7: "When a piece in `ON_FLOOR` or `MARKED_DOWN` has a `days_on_floor` greater
    than or equal to its `unsold_trigger_day_effective`, it moves to
    `UNSOLD_PENDING_ELECTION` and `election_deadline_at` is stamped with the current clock
    advanced by the schedule's `election_window_days` whole days"

    PRD 3.7: "The stepped price is `list_price_cents` multiplied by one minus the step's
    `markdown_pct`, rounded half up to a whole number of cents."

    Design: Corner/calculations/the_unsold_window_keys_on_each_pieces_own_listing_day_not_on_creation_order
    """
    world = setup_consignor_with_active_agreement(schedule_steps=FOUR_STEP_NO_FLOOR)
    agreement_id = world["agreement"]["id"]
    early = create_item(agreement_id, **EARLY_CHEST)
    late = create_item(agreement_id, **LATE_CHEST)
    screen_item(early["id"], scores=SCORES_GRADE_A)
    screen_item(late["id"], scores=SCORES_GRADE_A)
    take_custody(world["consignor"]["id"], [early["id"], late["id"]])
    receive_item(early["id"], scores=SCORES_GRADE_A)
    receive_item(late["id"], scores=SCORES_GRADE_A)
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)

    place_item(late["id"], zone["id"], tag_code="T-1801")
    set_clock("2026-09-10T00:00:00Z")
    place_item(early["id"], zone["id"], tag_code="T-1802")

    set_clock("2026-11-29T00:00:00Z")
    run_markdown_epoch()

    flagged = fetch_item(late["id"])
    assert flagged["days_on_floor"] == 120, (
        f"Expected 120 whole days since the first of August, "
        f"got {flagged['days_on_floor']}"
    )
    assert flagged["markdown_sequence"] == 4, (
        f"Expected the day-90 step in force, got {flagged['markdown_sequence']}"
    )
    assert flagged["current_price_cents"] == 25_500, (
        f"Expected round_half_up(51000 * 0.50) = 25500, "
        f"got {flagged['current_price_cents']}"
    )
    assert flagged["lifecycle_state"] == "UNSOLD_PENDING_ELECTION", (
        f"Expected UNSOLD_PENDING_ELECTION, got {flagged['lifecycle_state']}"
    )
    assert flagged["election_deadline_at"].startswith("2026-12-13T00:00:00"), (
        f"Expected the clock advanced by the fourteen-day window, "
        f"got {flagged['election_deadline_at']}"
    )
    assert flagged["unsold_trigger_day_effective"] == 120, (
        f"Expected the window not yet extended, "
        f"got {flagged['unsold_trigger_day_effective']}"
    )
    assert flagged["election_round"] == 0, (
        f"Expected no discount round taken, got {flagged['election_round']}"
    )

    younger = fetch_item(early["id"])
    assert younger["days_on_floor"] == 80, (
        f"Expected 80 whole days since the tenth of September, "
        f"got {younger['days_on_floor']}"
    )
    assert younger["markdown_sequence"] == 3, (
        f"Expected the day-60 step in force, got {younger['markdown_sequence']}"
    )
    assert younger["current_price_cents"] == 47_600, (
        f"Expected round_half_up(68000 * 0.70) = 47600, "
        f"got {younger['current_price_cents']}"
    )
    assert younger["lifecycle_state"] == "MARKED_DOWN", (
        f"Expected MARKED_DOWN rather than a flag, got {younger['lifecycle_state']}"
    )
    assert younger["election_deadline_at"] is None, (
        f"Expected no election deadline, got {younger['election_deadline_at']}"
    )


WIDE_CHEST = {
    "title": "Wide chest",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 30,
}
NARROW_CHEST = {
    "title": "Narrow chest",
    "category": "CASEGOOD",
    "declared_value_cents": 80_000,
    "photo_count": 4,
    "volume_cuft": 8,
    "footprint_sqft": 29,
}


def test_a_zone_reads_tight_at_exactly_three_quarters_of_its_capacity():
    """Thirty of forty is TIGHT; twenty-nine of forty is not.

    PRD 2.10: "`occupied_sqft` is the exact integer sum of `footprint_sqft` over every
    `ConsignmentItem` whose `placement_zone_id` names that zone"

    PRD 2.10: "Dividing `occupied_sqft` by `capacity_sqft` without rounding, the zone is
    `FULL` when the ratio is at least 1.00, `TIGHT` when the ratio is at least 0.75 but
    below 1.00, and `NORMAL` otherwise."

    PRD 2.6: "Square footage is an exact integer sum and is never rounded; the utilization
    ratio derived from it is compared without rounding."

    PRD 2.10: "Both figures are recomputed on every event that changes a zone's
    membership: a placement, a release, a write-off, a recovery and a clearance
    relocation."

    PRD 3.6: "it must have room: the zone's `occupied_sqft` plus the piece's
    `footprint_sqft` must not exceed the zone's `capacity_sqft`, otherwise
    `ERR_ZONE_CAPACITY_EXCEEDED`"

    PRD 3.1: "a new zone opens with `occupied_sqft` of 0, `utilization_state` `NORMAL` and
    `status` `OPEN`"

    Design: Corner/calculations/zone_utilization_turns_tight_at_exactly_three_quarters
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    agreement_id = world["agreement"]["id"]
    wide = create_item(agreement_id, **WIDE_CHEST)
    narrow = create_item(agreement_id, **NARROW_CHEST)
    screen_item(wide["id"], scores=SCORES_GRADE_A)
    screen_item(narrow["id"], scores=SCORES_GRADE_A)
    take_custody(world["consignor"]["id"], [wide["id"], narrow["id"]])
    receive_item(wide["id"], scores=SCORES_GRADE_A)
    receive_item(narrow["id"], scores=SCORES_GRADE_A)

    front = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=40)
    rear = create_zone(name="Rear B", zone_type="SHOWROOM_REAR", capacity_sqft=40)
    place_item(narrow["id"], rear["id"], tag_code="TAG-002")

    placed = place_item(wide["id"], front["id"], tag_code="TAG-001")
    assert placed["placement_zone_id"] == front["id"], (
        f"Expected the wide chest in the front showroom, "
        f"got {placed['placement_zone_id']}"
    )

    tight = fetch_zone(front["id"])
    assert tight["occupied_sqft"] == 30, (
        f"Expected the wide chest's 30 square feet, got {tight['occupied_sqft']}"
    )
    assert tight["utilization_state"] == "TIGHT", (
        f"Expected TIGHT at exactly 30 of 40, got {tight['utilization_state']}"
    )

    normal = fetch_zone(rear["id"])
    assert normal["occupied_sqft"] == 29, (
        f"Expected the narrow chest's 29 square feet, got {normal['occupied_sqft']}"
    )
    assert normal["utilization_state"] == "NORMAL", (
        f"Expected NORMAL at 29 of 40, got {normal['utilization_state']}"
    )

    for label, zone in (("front", tight), ("rear", normal)):
        assert zone["status"] == "OPEN", (
            f"Expected the {label} zone still open, got {zone['status']}"
        )
        assert zone["capacity_sqft"] == 40, (
            f"Expected a capacity of 40 square feet in the {label} zone, "
            f"got {zone['capacity_sqft']}"
        )
