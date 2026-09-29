"""What each endpoint hands back, and what it deliberately leaves alone."""

from test_helpers import (
    FLOOR_OPERATOR,
    FLOOR_OPERATOR_ID,
    GALLERY_MANAGER,
    INTAKE_APPRAISER_ID,
    LOGISTICS_COORDINATOR,
    SCORES_GRADE_A,
    SCORES_GRADE_B,
    api_client,
    attach_item_payload,
    complete_delivery_payload,
    consignor_payload,
    create_buyer,
    create_crew,
    create_item,
    create_truck,
    create_zone,
    fetch_consignor,
    fetch_consignor_ledger,
    fetch_item,
    fetch_sale,
    fetch_zone,
    place_item,
    receive_item,
    schedule_delivery,
    schedule_pickup,
    screen_item,
    sell_item,
    setup_consignor_with_active_agreement,
    shrinkage_audit_payload,
    take_custody,
    total_count,
    validate_paginated,
    validate_success,
)

ONE_STEP = [(1, 0, 0.00, 0)]

WALNUT_CREDENZA = {
    "title": "Walnut credenza",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 20,
}


def test_a_consignor_is_created_read_listed_and_partially_corrected():
    """The account opens with its defaults, and the correction touches only what it names.

    PRD 3.1: "The submitted payload carries a `display_name`, an `email`, an
    `address_line`, the `floor_number` of the pickup residence where 1 means ground floor,
    and a `has_elevator` flag stating whether the building has a working elevator."

    PRD 3.1: "A `payout_method` may be supplied and must be one of `ACH`, `CHECK` or
    `STORE_CREDIT`; when it is omitted the account defaults to `ACH`."

    PRD 3.1: "A freshly registered consignor opens with `status` `ACTIVE`, `escheat_state`
    `NONE`, `unclaimed_balance_cents` of 0, `lifetime_credits_cents` of 0"

    PRD 3.1: "A correction may revise any of `address_line`, `floor_number`,
    `has_elevator` or `payout_method`, and it increments the consignor's `version` by 1."

    Design: Corner/endpoints/consignor_create_read_list_and_patch_all_work
    """
    created = validate_success(
        api_client.create_consignor(
            consignor_payload(
                display_name="Alpha",
                email="alpha@example.com",
                address_line="1 A St",
                floor_number=1,
                has_elevator=False,
            ),
            GALLERY_MANAGER,
        ),
        201,
    )
    assert created["version"] == 1, (
        f"Expected a fresh row at version 1, got {created['version']}"
    )
    consignor_id = created["id"]

    read = validate_success(api_client.get_consignor(consignor_id, GALLERY_MANAGER), 200)
    assert read["id"] == consignor_id, (
        f"Expected the row just created, got {read['id']}"
    )
    assert read["display_name"] == "Alpha", (
        f"Expected Alpha, got {read['display_name']}"
    )

    rows, meta = validate_paginated(api_client.list_consignors(GALLERY_MANAGER))
    assert meta["total_count"] == 1, (
        f"Expected the one account on the books, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"Expected no further page, got {meta['has_more']}"
    )
    assert [row["id"] for row in rows] == [consignor_id], (
        f"Expected the listing to carry the same row, got {[r['id'] for r in rows]}"
    )

    patched = validate_success(
        api_client.patch_consignor(
            consignor_id, {"floor_number": 5, "has_elevator": True}, GALLERY_MANAGER
        ),
        200,
    )
    assert patched["floor_number"] == 5, (
        f"Expected the fifth floor, got {patched['floor_number']}"
    )
    assert patched["has_elevator"] is True, (
        f"Expected the elevator recorded, got {patched['has_elevator']}"
    )
    assert patched["version"] == 2, (
        f"Expected version 1 incremented by 1, got {patched['version']}"
    )
    assert patched["display_name"] == "Alpha", (
        f"Expected the name untouched by a partial correction, "
        f"got {patched['display_name']}"
    )
    assert patched["email"] == "alpha@example.com", (
        f"Expected the email untouched, got {patched['email']}"
    )
    assert patched["address_line"] == "1 A St", (
        f"Expected the address untouched, got {patched['address_line']}"
    )
    assert patched["payout_method"] == "ACH", (
        f"Expected the defaulted payout method untouched, "
        f"got {patched['payout_method']}"
    )

    reread = fetch_consignor(consignor_id)
    assert reread["unclaimed_balance_cents"] == 0, (
        f"Expected an empty ledger, got {reread['unclaimed_balance_cents']}"
    )
    assert reread["status"] == "ACTIVE", (
        f"Expected ACTIVE, got {reread['status']}"
    )
    assert reread["escheat_state"] == "NONE", (
        f"Expected NONE, got {reread['escheat_state']}"
    )


def _a_credenza_placed_in_the_front_showroom():
    """One grade-A credenza holding 20 square feet of an open front zone."""
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    credenza = create_item(world["agreement"]["id"], **WALNUT_CREDENZA)
    screen_item(credenza["id"], scores=SCORES_GRADE_A)
    take_custody(
        world["consignor"]["id"],
        [credenza["id"]],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    receive_item(credenza["id"], scores=SCORES_GRADE_A)
    world["zone"] = create_zone(
        name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200
    )
    world["credenza"] = place_item(
        credenza["id"], world["zone"]["id"], tag_code="TAG-001"
    )
    return world


def test_closing_a_zone_flips_its_status_without_moving_the_pieces_in_it():
    """A closed zone still reports the square footage it is holding.

    PRD 3.1: "A manager may close a zone, which sets `status` to `CLOSED` and increments
    the zone's `version` by 1 while leaving `occupied_sqft` untouched and every piece
    already inside it exactly where it stands"

    PRD 3.1: "Zone listings accept optional `zone_type` and `status` filters; truck and
    crew listings accept an optional `status` filter."

    PRD 2.10: "Dividing `occupied_sqft` by `capacity_sqft` without rounding, the zone is
    `FULL` when the ratio is at least 1.00, `TIGHT` when the ratio is at least 0.75 but
    below 1.00, and `NORMAL` otherwise."

    Design: Corner/endpoints/closing_a_zone_flips_its_status_without_moving_the_pieces_in_it
    """
    world = _a_credenza_placed_in_the_front_showroom()
    zone_id = world["zone"]["id"]

    before = fetch_zone(zone_id)
    assert before["status"] == "OPEN", (
        f"Expected an open zone before the close, got {before['status']}"
    )

    closed = validate_success(api_client.close_zone(zone_id, GALLERY_MANAGER), 200)
    assert closed["status"] == "CLOSED", (
        f"Expected CLOSED, got {closed['status']}"
    )
    assert closed["version"] == before["version"] + 1, (
        f"Expected version {before['version']} incremented by 1, "
        f"got {closed['version']}"
    )
    assert closed["occupied_sqft"] == 20, (
        f"Expected the credenza's 20 square feet still held, "
        f"got {closed['occupied_sqft']}"
    )
    assert closed["utilization_state"] == "NORMAL", (
        f"Expected NORMAL at 20 of 200, got {closed['utilization_state']}"
    )

    credenza = fetch_item(world["credenza"]["id"])
    assert credenza["placement_zone_id"] == zone_id, (
        f"Expected the piece exactly where it stands, "
        f"got {credenza['placement_zone_id']}"
    )
    assert credenza["lifecycle_state"] == "ON_FLOOR", (
        f"Expected ON_FLOOR, got {credenza['lifecycle_state']}"
    )

    listed = api_client.list_zones(GALLERY_MANAGER, params={"status": "CLOSED"})
    assert total_count(listed) == 1, (
        f"Expected the one closed zone, got {total_count(listed)}"
    )


FIRST_CREDENZA = {
    "title": "First credenza",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 20,
}
SECOND_NIGHTSTAND = {
    "title": "Second nightstand",
    "category": "CASEGOOD",
    "declared_value_cents": 20_000,
    "photo_count": 4,
    "volume_cuft": 15,
    "footprint_sqft": 15,
}


def test_attaching_a_second_piece_relinks_it_and_requotes_the_whole_job():
    """Twenty-seven cubic feet is requoted from scratch, not billed as an increment.

    PRD 3.4: "On success the piece moves `SCREEN_ACCEPTED → SCHEDULED_PICKUP`, the job's
    `item_count` and `total_volume_cuft` are recomputed, the quoted variant rewrites
    `quoted_surcharge_cents` against the enlarged load, and the job's `version` increments
    by 1."

    PRD 3.4: "Start from a base of 12,000 cents for showing up at all."

    PRD 3.4: "then charge 2,500 cents per block, so a 41-cubic-foot load pays for five
    blocks"

    PRD 3.4: "it reads `declared_stair_flights`, `declared_elevator` and the quoted
    `crew_size`, writes the result to `quoted_surcharge_cents`, and mints no ledger entry
    whatsoever"

    PRD 3.4: "writes `final_surcharge_cents`, together with `surcharge_variance_cents`
    computed as `final_surcharge_cents` minus `quoted_surcharge_cents`.
    `surcharge_variance_cents` is null until completion."

    PRD 3.2: "Item listings accept a generous filter set for exactly this reason: optional
    `consignor_id`, `agreement_id`, `parent_lot_item_id`, `pickup_job_id`,
    `placement_zone_id`, `lifecycle_state` and `inventory_state`, alongside `limit` and
    `offset`."

    Design: Corner/endpoints/attaching_a_second_piece_relinks_it_and_requotes_the_job
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    agreement_id = world["agreement"]["id"]
    one = create_item(agreement_id, **FIRST_CREDENZA)
    two = create_item(agreement_id, **SECOND_NIGHTSTAND)
    screen_item(one["id"], scores=SCORES_GRADE_A)
    screen_item(two["id"], scores=SCORES_GRADE_A)
    truck = create_truck(name="BOX-1", capacity_volume_cuft=100)
    job = schedule_pickup(
        world["consignor"]["id"],
        truck["id"],
        [one["id"]],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    assert job["quoted_surcharge_cents"] == 17_000, (
        f"Expected 12000 plus two volume blocks for 12 cubic feet, "
        f"got {job['quoted_surcharge_cents']}"
    )

    attached = validate_success(
        api_client.attach_pickup_item(
            job["id"], attach_item_payload(two["id"]), LOGISTICS_COORDINATOR
        ),
        200,
    )

    assert attached["item_count"] == 2, (
        f"Expected two pieces on the load, got {attached['item_count']}"
    )
    assert attached["total_volume_cuft"] == 27, (
        f"Expected 12 + 15 cubic feet, got {attached['total_volume_cuft']}"
    )
    assert attached["quoted_surcharge_cents"] == 19_500, (
        f"Expected 12000 plus three blocks for 27 cubic feet rather than an additive "
        f"top-up, got {attached['quoted_surcharge_cents']}"
    )
    assert attached["final_surcharge_cents"] is None, (
        f"Expected nothing settled before completion, "
        f"got {attached['final_surcharge_cents']}"
    )
    assert attached["surcharge_variance_cents"] is None, (
        f"Expected no variance before completion, "
        f"got {attached['surcharge_variance_cents']}"
    )
    assert attached["version"] == job["version"] + 1, (
        f"Expected version {job['version']} incremented by 1, "
        f"got {attached['version']}"
    )
    assert attached["status"] == "SCHEDULED", (
        f"Expected the job still SCHEDULED, got {attached['status']}"
    )

    nightstand = fetch_item(two["id"])
    assert nightstand["pickup_job_id"] == job["id"], (
        f"Expected the piece linked to the job, got {nightstand['pickup_job_id']}"
    )
    assert nightstand["lifecycle_state"] == "SCHEDULED_PICKUP", (
        f"Expected SCHEDULED_PICKUP, got {nightstand['lifecycle_state']}"
    )

    listed = api_client.list_items(
        GALLERY_MANAGER, params={"pickup_job_id": job["id"], "limit": 100}
    )
    assert total_count(listed) == 2, (
        f"Expected both pieces on the job, got {total_count(listed)}"
    )


def test_the_item_read_exposes_both_grade_columns_and_both_price_columns():
    """One read shows what the photographs promised beside what actually arrived.

    PRD 3.3: "`provisional_condition_grade` and `provisional_list_price_cents` are frozen
    at their screening values forever, while `condition_grade` and `list_price_cents` are
    the effective figures that later steps overwrite"

    PRD 3.5: "`photo_score` is overwritten, `condition_grade` is overwritten with the
    newly derived grade, and `list_price_cents` is recomputed by the same two-step
    grade-and-category calculation using the new grade"

    PRD 3.5: "`current_price_cents` is refreshed from the recomputed ticket price,
    `received_by_user_id` records the acting `X-User-ID`, and the piece's `version`
    increments by 1."

    PRD 3.5: "A distance of at most one grade — including no downgrade at all, and
    including an upgrade — moves the piece `RECEIVED → AWAITING_PLACEMENT` and the gallery
    simply absorbs the difference."

    PRD 3.7: "divide the elapsed seconds by 86,400, and discard the remainder, so a
    piece placed nineteen hours ago has been on the floor for zero days. When `listed_at`
    is null, `days_on_floor` is 0."

    Design: Corner/endpoints/the_item_read_exposes_both_grade_columns_and_both_price_columns
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    credenza = create_item(world["agreement"]["id"], **WALNUT_CREDENZA)
    screen_item(credenza["id"], scores=SCORES_GRADE_A)
    take_custody(
        world["consignor"]["id"],
        [credenza["id"]],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    receive_item(credenza["id"], scores=SCORES_GRADE_B)

    read = validate_success(
        api_client.get_item(credenza["id"], GALLERY_MANAGER), 200
    )

    assert read["provisional_condition_grade"] == "A", (
        f"Expected the photographic grade frozen at A, "
        f"got {read['provisional_condition_grade']}"
    )
    assert read["provisional_list_price_cents"] == 51_000, (
        f"Expected the screening ticket frozen at 51000, "
        f"got {read['provisional_list_price_cents']}"
    )
    assert read["condition_grade"] == "B", (
        f"Expected the inspected grade B, got {read['condition_grade']}"
    )
    assert read["list_price_cents"] == 42_000, (
        f"Expected round_half_up(60000 * 0.70) = 42000, "
        f"got {read['list_price_cents']}"
    )
    assert read["current_price_cents"] == 42_000, (
        f"Expected the ticket refreshed to 42000, got {read['current_price_cents']}"
    )
    assert read["photo_score"] == 6.60, (
        f"Expected the final 6.60 to overwrite the 8.55 of the screen, "
        f"got {read['photo_score']}"
    )
    assert read["lifecycle_state"] == "AWAITING_PLACEMENT", (
        f"Expected a one-grade fall to be absorbed, got {read['lifecycle_state']}"
    )
    assert read["inventory_state"] == "IN_CUSTODY", (
        f"Expected IN_CUSTODY, got {read['inventory_state']}"
    )
    assert read["screened_by_user_id"] == INTAKE_APPRAISER_ID, (
        f"Expected the screening appraiser recorded, "
        f"got {read['screened_by_user_id']}"
    )
    assert read["received_by_user_id"] == FLOOR_OPERATOR_ID, (
        f"Expected the receiving operator recorded, "
        f"got {read['received_by_user_id']}"
    )
    assert read["markdown_sequence"] == 0, (
        f"Expected no markdown step before placement, "
        f"got {read['markdown_sequence']}"
    )
    assert read["listed_at"] is None, (
        f"Expected no listing stamp, got {read['listed_at']}"
    )
    assert read["days_on_floor"] == 0, (
        f"Expected no floor tenure, got {read['days_on_floor']}"
    )


COUNTED_CREDENZA = {
    "title": "Counted credenza",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 20,
}
UNCOUNTED_BUREAU = {
    "title": "Uncounted bureau",
    "category": "CASEGOOD",
    "declared_value_cents": 80_000,
    "photo_count": 4,
    "volume_cuft": 8,
    "footprint_sqft": 10,
}


def test_a_partial_count_marks_every_uncounted_piece_missing_in_one_call():
    """Naming one of two pieces does not half-apply: the unnamed one is simply missing.

    PRD 3.9: "`expected_item_count` is the number of pieces whose `placement_zone_id` names
    the counted zone and whose `inventory_state` is either `IN_CUSTODY` or
    `SHRINKAGE_MISSING`."

    PRD 3.9: "`counted_item_count` is the number of distinct entries in `counted_item_ids`
    that belong to that expected set."

    PRD 3.9: "`counted_by_user_id` records the acting `X-User-ID`. Every expected piece
    absent from the count is immediately moved to `inventory_state` `SHRINKAGE_MISSING`
    with its `lifecycle_state` untouched."

    PRD 3.9: "When `variance_count` is 0, the audit is `RECONCILED` at the moment of
    creation: `write_off_total_cents` is 0, `approved_by_user_id` stays null because nobody
    needed to approve anything, and no ledger entry is minted. When `variance_count` is
    greater than 0, the audit opens in `status` `COUNTED` and waits for a manager."

    PRD 3.9: "the piece keeps counting toward its zone's `occupied_sqft` until the loss is
    actually booked"

    PRD 3.4: "exactly one `PICKUP_SURCHARGE_DEBIT` ledger entry is minted for the job's
    consignor, carrying `amount_cents` equal to the negation of `final_surcharge_cents`"

    Design: Corner/endpoints/a_partial_count_marks_every_uncounted_piece_missing_in_one_call
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    agreement_id = world["agreement"]["id"]
    counted = create_item(agreement_id, **COUNTED_CREDENZA)
    uncounted = create_item(agreement_id, **UNCOUNTED_BUREAU)
    screen_item(counted["id"], scores=SCORES_GRADE_A)
    screen_item(uncounted["id"], scores=SCORES_GRADE_A)
    take_custody(
        world["consignor"]["id"],
        [counted["id"], uncounted["id"]],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    receive_item(counted["id"], scores=SCORES_GRADE_A)
    receive_item(uncounted["id"], scores=SCORES_GRADE_A)
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    place_item(counted["id"], zone["id"], tag_code="TAG-001")
    place_item(uncounted["id"], zone["id"], tag_code="TAG-002")

    audit = validate_success(
        api_client.create_shrinkage_audit(
            shrinkage_audit_payload(zone["id"], [counted["id"]]), FLOOR_OPERATOR
        ),
        201,
    )

    assert audit["expected_item_count"] == 2, (
        f"Expected two pieces on the books, got {audit['expected_item_count']}"
    )
    assert audit["counted_item_count"] == 1, (
        f"Expected one piece found, got {audit['counted_item_count']}"
    )
    assert audit["variance_count"] == 1, (
        f"Expected a variance of one, got {audit['variance_count']}"
    )
    assert audit["missing_item_ids"] == [uncounted["id"]], (
        f"Expected the uncounted bureau alone, got {audit['missing_item_ids']}"
    )
    assert audit["status"] == "COUNTED", (
        f"Expected COUNTED while a manager is awaited, got {audit['status']}"
    )
    assert audit["counted_by_user_id"] == FLOOR_OPERATOR_ID, (
        f"Expected the counting operator recorded, "
        f"got {audit['counted_by_user_id']}"
    )
    assert audit["approved_by_user_id"] is None, (
        f"Expected no approver yet, got {audit['approved_by_user_id']}"
    )
    assert audit["write_off_total_cents"] == 0, (
        f"Expected nothing written off before approval, "
        f"got {audit['write_off_total_cents']}"
    )

    missing = fetch_item(uncounted["id"])
    assert missing["inventory_state"] == "SHRINKAGE_MISSING", (
        f"Expected SHRINKAGE_MISSING, got {missing['inventory_state']}"
    )
    assert missing["lifecycle_state"] == "ON_FLOOR", (
        f"Expected the merchandising state untouched, "
        f"got {missing['lifecycle_state']}"
    )
    assert missing["placement_zone_id"] == zone["id"], (
        f"Expected the piece still charged to the zone, "
        f"got {missing['placement_zone_id']}"
    )

    found = fetch_item(counted["id"])
    assert found["inventory_state"] == "IN_CUSTODY", (
        f"Expected the counted piece untouched, got {found['inventory_state']}"
    )

    occupancy = fetch_zone(zone["id"])
    assert occupancy["occupied_sqft"] == 30, (
        f"Expected 20 + 10 square feet still held, got {occupancy['occupied_sqft']}"
    )

    entries = fetch_consignor_ledger(world["consignor"]["id"])
    assert [e["amount_cents"] for e in entries] == [-17_000], (
        f"Expected the count itself to mint nothing, "
        f"got {[e['amount_cents'] for e in entries]}"
    )


CHESTERFIELD_SOFA = {
    "title": "Chesterfield sofa",
    "category": "SOFA",
    "declared_value_cents": 189_950,
    "photo_count": 6,
    "volume_cuft": 65,
    "footprint_sqft": 30,
}


def test_a_refused_delivery_reverses_the_sale_instead_of_settling_it():
    """The piece comes back to its zone, the money unwinds, and no claim window opens.

    PRD 3.8: "Both require the order to be in `status` `SCHEDULED` and the sale to be in
    `status` `COMPLETED`, and both stamp `outcome_recorded_at` with the current clock and
    increment the order's `version` by 1."

    PRD 3.8: "On `REFUSED` the order moves `SCHEDULED → REFUSED` and nothing settles"

    PRD 3.8: "The sale moves `COMPLETED → REVERSED`, a `SALE_REVERSAL_DEBIT` of the
    negated `consignor_share_cents` is minted, the consignor's `unclaimed_balance_cents` is
    recomputed, and the piece goes back onto the floor in its former zone"

    PRD 3.8: "Begin with a base white-glove charge of 7,500 cents. Add an access charge: a
    flat 3,000 cents when `elevator_used` is true; otherwise 4,500 cents per flight for up
    to 6 flights, plus a further 8,000 cents when `stair_flights` is strictly greater than
    6."

    PRD 3.8: "Add an assembly charge of 4,000 cents when the sold piece's `category` is
    `DINING` or `CASEGOOD`, and nothing otherwise"

    PRD 3.8: "`stair_flights` is the buyer's `floor_number` reduced by 1 but never below
    zero"

    PRD 2.10: "`occupied_sqft` is the exact integer sum of `footprint_sqft` over every
    `ConsignmentItem` whose `placement_zone_id` names that zone"

    Design: Corner/endpoints/a_refused_delivery_reverses_the_sale_instead_of_settling_it
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    consignor_id = world["consignor"]["id"]
    sofa = create_item(world["agreement"]["id"], **CHESTERFIELD_SOFA)
    screen_item(sofa["id"], scores=SCORES_GRADE_B)
    take_custody(
        consignor_id,
        [sofa["id"]],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    receive_item(sofa["id"], scores=SCORES_GRADE_B)
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    place_item(sofa["id"], zone["id"], tag_code="TAG-001")
    buyer = create_buyer(floor_number=2, has_elevator=False)
    sale = sell_item(sofa["id"], buyer["id"], 126_317)
    crew = create_crew(name="GLOVE-1", max_concurrent_jobs=2)
    order = schedule_delivery(
        sale["id"],
        crew["id"],
        window_start="2026-08-01T14:00:00Z",
        window_end="2026-08-01T16:00:00Z",
    )

    refused = validate_success(
        api_client.complete_delivery_order(
            order["id"], complete_delivery_payload("REFUSED"), LOGISTICS_COORDINATOR
        ),
        200,
    )

    assert refused["status"] == "REFUSED", (
        f"Expected REFUSED, got {refused['status']}"
    )
    assert refused["outcome_recorded_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected the outcome stamped from the clock, "
        f"got {refused['outcome_recorded_at']}"
    )
    assert refused["claim_window_ends_at"] is None, (
        f"Expected no claim window on a refusal, "
        f"got {refused['claim_window_ends_at']}"
    )
    assert refused["delivery_fee_cents"] == 12_000, (
        f"Expected 7500 plus one charged flight, quoted at scheduling, "
        f"got {refused['delivery_fee_cents']}"
    )
    assert refused["stair_flights"] == 1, (
        f"Expected one flight for a second-floor buyer, "
        f"got {refused['stair_flights']}"
    )
    assert refused["elevator_used"] is False, (
        f"Expected no elevator, got {refused['elevator_used']}"
    )
    assert refused["version"] == order["version"] + 1, (
        f"Expected version {order['version']} incremented by 1, "
        f"got {refused['version']}"
    )

    reversed_sale = fetch_sale(sale["id"])
    assert reversed_sale["status"] == "REVERSED", (
        f"Expected REVERSED, got {reversed_sale['status']}"
    )
    assert reversed_sale["reversed_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected the reversal stamped from the clock, "
        f"got {reversed_sale['reversed_at']}"
    )

    entries = fetch_consignor_ledger(consignor_id)
    assert [e["amount_cents"] for e in entries] == [-35_000, 69_474, -69_474], (
        f"Expected the credit unwound by its own negation, "
        f"got {[e['amount_cents'] for e in entries]}"
    )
    assert entries[-1]["entry_type"] == "SALE_REVERSAL_DEBIT", (
        f"Expected a reversal debit last, got {entries[-1]['entry_type']}"
    )

    consignor = fetch_consignor(consignor_id)
    assert consignor["unclaimed_balance_cents"] == -35_000, (
        f"Expected exactly the pre-sale figure, "
        f"got {consignor['unclaimed_balance_cents']}"
    )

    back_on_floor = fetch_item(sofa["id"])
    assert back_on_floor["lifecycle_state"] == "ON_FLOOR", (
        f"Expected ON_FLOOR under the sequence-1 step, "
        f"got {back_on_floor['lifecycle_state']}"
    )
    assert back_on_floor["placement_zone_id"] == zone["id"], (
        f"Expected the former zone, got {back_on_floor['placement_zone_id']}"
    )
    assert back_on_floor["current_price_cents"] == 126_317, (
        f"Expected the ticket price kept, got {back_on_floor['current_price_cents']}"
    )

    occupancy = fetch_zone(zone["id"])
    assert occupancy["occupied_sqft"] == 30, (
        f"Expected the 30 square feet never released, "
        f"got {occupancy['occupied_sqft']}"
    )
