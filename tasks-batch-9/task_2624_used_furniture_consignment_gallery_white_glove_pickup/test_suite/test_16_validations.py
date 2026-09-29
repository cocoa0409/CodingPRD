"""Guards at their exact edges: the register floor, the clock, the zone and the tag."""

from test_helpers import (
    FLOOR_OPERATOR,
    FLOOR_OPERATOR_ID,
    GALLERY_MANAGER,
    SCORES_GRADE_A,
    SCORES_GRADE_B,
    SYSTEM_OPERATOR,
    ApiErrorId,
    api_client,
    clock_payload,
    create_buyer,
    create_item,
    create_zone,
    elect_disposition,
    elect_disposition_payload,
    fetch_consignor,
    fetch_consignor_ledger,
    fetch_item,
    fetch_zone,
    flag_inventory,
    get_success_data,
    make_consignor_headers,
    place_item,
    place_payload,
    receive_item,
    run_markdown_epoch,
    sale_payload,
    screen_item,
    set_clock,
    setup_consignor_with_active_agreement,
    take_custody,
    total_count,
    validate_error,
    write_off_item,
)

ONE_STEP = [(1, 0, 0.00, 0)]
FOUR_STEP_NO_FLOOR = [
    (1, 0, 0.00, 0),
    (2, 30, 0.15, 0),
    (3, 60, 0.30, 0),
    (4, 90, 0.50, 0),
]

CHESTERFIELD = {
    "title": "Chesterfield sofa",
    "category": "SOFA",
    "declared_value_cents": 189_950,
    "photo_count": 6,
    "volume_cuft": 65,
    "footprint_sqft": 30,
}


def _a_sofa_on_the_floor_at_one_hundred_twenty_six_thousand():
    """One grade-B sofa on the front showroom at 126,317, with a buyer waiting."""
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    sofa = create_item(world["agreement"]["id"], **CHESTERFIELD)
    screen_item(sofa["id"], scores=SCORES_GRADE_B)
    take_custody(
        world["consignor"]["id"],
        [sofa["id"]],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    receive_item(sofa["id"], scores=SCORES_GRADE_B)
    world["zone"] = create_zone(
        name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200
    )
    world["sofa"] = place_item(sofa["id"], world["zone"]["id"], tag_code="TAG-001")
    world["buyer"] = create_buyer(floor_number=2, has_elevator=False)
    return world


def test_a_sale_one_cent_under_the_register_floor_is_refused():
    """The floor rounds up to 101,054, so 101,053 rings nothing at all.

    PRD 3.8: "And the register has a floor: `sale_price_cents` must be at least the
    piece's `current_price_cents` multiplied by 80 hundredths and rounded half up to a
    whole number of cents."

    PRD 3.8: "The gallery may haggle a little at the counter but not below the
    consignor's negotiated floor, and a price below it is refused with
    `ERR_SALE_BELOW_FLOOR`."

    PRD 3.8: "Second, because the sale exists, one `SALE_CREDIT` ledger entry of positive
    `consignor_share_cents` is minted against the consignor."

    Design: Corner/validations/a_sale_one_cent_under_the_register_floor_is_refused
    """
    world = _a_sofa_on_the_floor_at_one_hundred_twenty_six_thousand()
    sofa_id = world["sofa"]["id"]
    consignor_id = world["consignor"]["id"]

    refused = api_client.create_sale(
        sale_payload(sofa_id, world["buyer"]["id"], 101_053), FLOOR_OPERATOR
    )
    validate_error(refused, ApiErrorId.ERR_SALE_BELOW_FLOOR, 422)

    listed = api_client.list_sales(
        GALLERY_MANAGER, params={"item_id": sofa_id, "limit": 100}
    )
    assert total_count(listed) == 0, (
        f"Expected the refusal to ring no sale, got {total_count(listed)}"
    )

    sofa = fetch_item(sofa_id)
    assert sofa["lifecycle_state"] == "ON_FLOOR", (
        f"Expected the sofa still on the floor, got {sofa['lifecycle_state']}"
    )
    assert sofa["current_price_cents"] == 126_317, (
        f"Expected the posted price untouched, got {sofa['current_price_cents']}"
    )

    entries = fetch_consignor_ledger(consignor_id)
    assert [entry["amount_cents"] for entry in entries] == [-35_000], (
        f"Expected only the collection surcharge and no credit, "
        f"got {[entry['amount_cents'] for entry in entries]}"
    )
    consignor = fetch_consignor(consignor_id)
    assert consignor["unclaimed_balance_cents"] == -35_000, (
        f"Expected -35000, got {consignor['unclaimed_balance_cents']}"
    )


def test_a_sale_at_exactly_the_register_floor_succeeds_and_splits():
    """The guard is strictly below, so 101,054 rings and the two shares re-add.

    PRD 3.8: "And the register has a floor: `sale_price_cents` must be at least the
    piece's `current_price_cents` multiplied by 80 hundredths and rounded half up to a
    whole number of cents."

    PRD 3.8: "Start from the category base share: 50 hundredths for `SOFA`, 55 hundredths
    for `DINING`, 55 hundredths for `CASEGOOD`"

    PRD 3.8: "Add a price-band bonus read off `sale_price_cents`: nothing at all below
    50,000 cents, 5 hundredths for a price of at least 50,000 cents but below 150,000
    cents"

    PRD 3.8: "Then subtract a tenure penalty of 5 hundredths when the piece's
    `markdown_sequence` at the moment of sale is 3 or higher"

    PRD 3.8: "`consignor_share_cents` is then `sale_price_cents` multiplied by
    `split_pct_applied`, rounded half up to a whole number of cents, and
    `gallery_share_cents` is the exact remainder of `sale_price_cents` after the
    consignor's share is taken out."

    PRD 3.8: "The `Sale` row is created with `status` `COMPLETED`, `sold_at` stamped from
    the clock and `sold_by_user_id` recording the acting `X-User-ID`, and the piece moves
    to `SOLD` on the merchandising dimension."

    PRD 3.8: "`markdown_sequence_at_sale` records a copy of the piece's
    `markdown_sequence` at the instant of sale"

    PRD 3.8: "so a sold-but-undelivered piece keeps counting toward its zone's
    `occupied_sqft`"

    PRD 2.11: "`lifetime_credits_cents` is the sum of `amount_cents` restricted to entries
    whose amount is positive, so it never decreases."

    Design: Corner/validations/a_sale_at_exactly_the_register_floor_succeeds_and_splits
    """
    world = _a_sofa_on_the_floor_at_one_hundred_twenty_six_thousand()
    sofa_id = world["sofa"]["id"]
    consignor_id = world["consignor"]["id"]

    response = api_client.create_sale(
        sale_payload(sofa_id, world["buyer"]["id"], 101_054), FLOOR_OPERATOR
    )
    assert response.status_code == 201, (
        f"Expected a sale at exactly the floor to be rung, got {response.status_code}"
    )
    sale = get_success_data(response)

    assert sale["split_pct_applied"] == 0.55, (
        f"Expected a SOFA base of 0.50 plus the 0.05 mid-band bonus, "
        f"got {sale['split_pct_applied']}"
    )
    assert sale["consignor_share_cents"] == 55_580, (
        f"Expected round_half_up(101054 * 0.55) = 55580, "
        f"got {sale['consignor_share_cents']}"
    )
    assert sale["gallery_share_cents"] == 45_474, (
        f"Expected the exact remainder of 101054, got {sale['gallery_share_cents']}"
    )
    assert (
        sale["consignor_share_cents"] + sale["gallery_share_cents"] == 101_054
    ), "The two shares must re-add to the sale price to the cent"
    assert sale["status"] == "COMPLETED", (
        f"Expected COMPLETED, got {sale['status']}"
    )
    assert sale["markdown_sequence_at_sale"] == 1, (
        f"Expected the first step copied onto the sale, "
        f"got {sale['markdown_sequence_at_sale']}"
    )
    assert sale["sold_by_user_id"] == FLOOR_OPERATOR_ID, (
        f"Expected the operator at the register recorded, "
        f"got {sale['sold_by_user_id']}"
    )
    assert sale["sold_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected the sale stamped from the clock, got {sale['sold_at']}"
    )

    sofa = fetch_item(sofa_id)
    assert sofa["lifecycle_state"] == "SOLD", (
        f"Expected SOLD, got {sofa['lifecycle_state']}"
    )
    assert sofa["placement_zone_id"] == world["zone"]["id"], (
        f"Expected the zone retained until delivery, "
        f"got {sofa['placement_zone_id']}"
    )

    consignor = fetch_consignor(consignor_id)
    assert consignor["unclaimed_balance_cents"] == 20_580, (
        f"Expected 55580 of credit against 35000 of surcharge, "
        f"got {consignor['unclaimed_balance_cents']}"
    )
    assert consignor["lifetime_credits_cents"] == 55_580, (
        f"Expected 55580 of lifetime credit, "
        f"got {consignor['lifetime_credits_cents']}"
    )

    zone = fetch_zone(world["zone"]["id"])
    assert zone["occupied_sqft"] == 30, (
        f"Expected the sold sofa to keep consuming its 30 square feet, "
        f"got {zone['occupied_sqft']}"
    )


WALNUT_CREDENZA = {
    "title": "Walnut credenza",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 20,
}


def test_setting_the_clock_backwards_is_refused_and_leaves_tenure_alone():
    """Time only moves forward, and the refused rewind does not shorten the tenure.

    PRD 2.5: "A `SystemOperator` moves it by supplying a `current_utc` instant; time may
    only move forward, so a request whose `current_utc` is earlier than the current clock
    reading is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422)."

    PRD 2.5: "Setting the clock mutates no entity and implies no epoch run."

    PRD 3.7: "`days_on_floor` is the number of whole days between `listed_at` and the
    current logical clock: subtract `listed_at` from the clock, divide the elapsed seconds
    by 86,400, and discard the remainder"

    PRD 3.6: "because `listed_at` is the origin of the piece's floor tenure and re-placing
    a recovered piece must not reset the clock it has already burned"

    Design: Corner/validations/moving_the_logical_clock_backwards_is_refused
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
    receive_item(credenza["id"], scores=SCORES_GRADE_A)
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    place_item(credenza["id"], zone["id"], tag_code="TAG-001")

    set_clock("2026-09-10T00:00:00Z")

    rewound = api_client.set_clock(
        clock_payload("2026-08-15T00:00:00Z"), SYSTEM_OPERATOR
    )
    validate_error(rewound, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC, 422)

    piece = fetch_item(credenza["id"])
    assert piece["days_on_floor"] == 40, (
        f"Expected the clock still reading the tenth of September, "
        f"got a tenure of {piece['days_on_floor']} days"
    )
    assert piece["listed_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected the listing stamp untouched, got {piece['listed_at']}"
    )
    assert piece["current_price_cents"] == 51_000, (
        f"Expected the price untouched by a refused clock move, "
        f"got {piece['current_price_cents']}"
    )


WIDE_SIDEBOARD = {
    "title": "Wide sideboard",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 24,
}
NARROW_BUREAU = {
    "title": "Narrow bureau",
    "category": "CASEGOOD",
    "declared_value_cents": 80_000,
    "photo_count": 4,
    "volume_cuft": 8,
    "footprint_sqft": 18,
}


def test_two_footprints_that_each_fit_are_refused_as_a_pair():
    """Twenty-four fits and eighteen fits, but forty-two does not fit forty.

    PRD 3.6: "it must have room: the zone's `occupied_sqft` plus the piece's
    `footprint_sqft` must not exceed the zone's `capacity_sqft`, otherwise
    `ERR_ZONE_CAPACITY_EXCEEDED`"

    PRD 2.10: "`occupied_sqft` is the exact integer sum of `footprint_sqft` over every
    `ConsignmentItem` whose `placement_zone_id` names that zone"

    PRD 2.10: "Dividing `occupied_sqft` by `capacity_sqft` without rounding, the zone is
    `FULL` when the ratio is at least 1.00, `TIGHT` when the ratio is at least 0.75 but
    below 1.00, and `NORMAL` otherwise."

    PRD 3.6: "On success the piece moves `AWAITING_PLACEMENT → ON_FLOOR`, its
    `placement_zone_id` and `tag_code` are written, and its `version` increments by 1."

    Design: Corner/validations/two_individually_legal_footprints_are_refused_as_a_collective_overflow
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    agreement_id = world["agreement"]["id"]
    sideboard = create_item(agreement_id, **WIDE_SIDEBOARD)
    bureau = create_item(agreement_id, **NARROW_BUREAU)
    screen_item(sideboard["id"], scores=SCORES_GRADE_A)
    screen_item(bureau["id"], scores=SCORES_GRADE_A)
    take_custody(
        world["consignor"]["id"],
        [sideboard["id"], bureau["id"]],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    receive_item(sideboard["id"], scores=SCORES_GRADE_A)
    receive_item(bureau["id"], scores=SCORES_GRADE_A)
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=40)
    place_item(sideboard["id"], zone["id"], tag_code="TAG-001")

    refused = api_client.place_item(
        bureau["id"], place_payload(zone["id"], "TAG-002"), FLOOR_OPERATOR
    )
    validate_error(refused, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED, 409)

    unchanged = fetch_zone(zone["id"])
    assert unchanged["occupied_sqft"] == 24, (
        f"Expected the sideboard's 24 square feet alone, "
        f"got {unchanged['occupied_sqft']}"
    )
    assert unchanged["utilization_state"] == "NORMAL", (
        f"Expected NORMAL at 24 of 40, got {unchanged['utilization_state']}"
    )

    rejected = fetch_item(bureau["id"])
    assert rejected["lifecycle_state"] == "AWAITING_PLACEMENT", (
        f"Expected the bureau still awaiting placement, "
        f"got {rejected['lifecycle_state']}"
    )
    assert rejected["placement_zone_id"] is None, (
        f"Expected no zone written, got {rejected['placement_zone_id']}"
    )
    assert rejected["tag_code"] is None, (
        f"Expected no tag written, got {rejected['tag_code']}"
    )
    assert rejected["listed_at"] is None, (
        f"Expected no listing stamp written, got {rejected['listed_at']}"
    )


OIL_STUDY = {
    "title": "Framed oil study",
    "category": "ART",
    "declared_value_cents": 129_950,
    "photo_count": 5,
    "volume_cuft": 10,
    "footprint_sqft": 12,
}


def test_donating_an_art_piece_is_refused_while_returning_it_is_allowed():
    """Art is never charity, but the very same piece may go home again.

    PRD 3.7: "`DONATE` is refused for a piece whose `category` is `ART`, and refused for
    any piece whose `current_price_cents` still exceeds 200,000 cents, because a valuable
    piece is not charity"

    PRD 3.7: "`RETURN` is refused for a piece whose `inventory_state` is
    `WRITTEN_OFF_INV`, since the gallery cannot hand back something it has already conceded
    is lost. Either refusal answers `ERR_DISPOSITION_NOT_ELIGIBLE`."

    PRD 3.7: "Electing `DONATE` moves the piece `UNSOLD_PENDING_ELECTION →
    DONATION_SCHEDULED`, and electing `RETURN` moves it `UNSOLD_PENDING_ELECTION →
    RETURN_SCHEDULED`; both set `disposition_election` to the elected value and clear
    `election_deadline_at` to null"

    PRD 3.7: "Electing `DISCOUNT` puts the piece back to work and is the one election that
    loops."

    PRD 3.3: "Second, take that already-rounded integer number of cents, multiply it by
    the category factor, and round that product half up to a whole number of cents."

    PRD 3.3: "The category factors are 95 hundredths for `SOFA`, 105 hundredths for
    `DINING`, 100 hundredths for `CASEGOOD`, 110 hundredths for `RUG`, 120 hundredths for
    `ART` and 85 hundredths for `OUTDOOR`"

    PRD 3.7: "The stepped price is `list_price_cents` multiplied by one minus the step's
    `markdown_pct`, rounded half up to a whole number of cents."

    Design: Corner/validations/donating_an_art_piece_is_refused_while_returning_it_is_allowed
    """
    world = setup_consignor_with_active_agreement(schedule_steps=FOUR_STEP_NO_FLOOR)
    consignor_id = world["consignor"]["id"]
    study = create_item(world["agreement"]["id"], **OIL_STUDY)
    screen_item(study["id"], scores=SCORES_GRADE_A)
    take_custody(
        consignor_id,
        [study["id"]],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    receive_item(study["id"], scores=SCORES_GRADE_A)
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    placed = place_item(study["id"], zone["id"], tag_code="TAG-001")
    assert placed["list_price_cents"] == 132_550, (
        f"Expected round_half_up(110458 * 1.20) = 132550 rather than a single combined "
        f"rounding, got {placed['list_price_cents']}"
    )

    set_clock("2026-11-29T00:00:00Z")
    run_markdown_epoch()

    refused = api_client.elect_disposition(
        study["id"],
        elect_disposition_payload("DONATE"),
        make_consignor_headers(consignor_id),
    )
    validate_error(refused, ApiErrorId.ERR_DISPOSITION_NOT_ELIGIBLE, 422)

    waiting = fetch_item(study["id"])
    assert waiting["lifecycle_state"] == "UNSOLD_PENDING_ELECTION", (
        f"Expected the piece still awaiting an election, "
        f"got {waiting['lifecycle_state']}"
    )
    assert waiting["disposition_election"] == "NONE", (
        f"Expected no election recorded, got {waiting['disposition_election']}"
    )
    assert waiting["election_deadline_at"].startswith("2026-12-13T00:00:00"), (
        f"Expected the election window still open, "
        f"got {waiting['election_deadline_at']}"
    )

    returned = elect_disposition(study["id"], "RETURN", consignor_id=consignor_id)
    assert returned["disposition_election"] == "RETURN", (
        f"Expected RETURN recorded, got {returned['disposition_election']}"
    )
    assert returned["lifecycle_state"] == "RETURN_SCHEDULED", (
        f"Expected RETURN_SCHEDULED, got {returned['lifecycle_state']}"
    )
    assert returned["election_deadline_at"] is None, (
        f"Expected the deadline cleared, got {returned['election_deadline_at']}"
    )
    assert returned["current_price_cents"] == 66_275, (
        f"Expected round_half_up(132550 * 0.50) = 66275 left alone by a return, "
        f"got {returned['current_price_cents']}"
    )
    assert returned["election_round"] == 0, (
        f"Expected only a discount election to consume a round, "
        f"got {returned['election_round']}"
    )


FIRST_CREDENZA = {
    "title": "First credenza",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 20,
}
SECOND_BUREAU = {
    "title": "Second bureau",
    "category": "CASEGOOD",
    "declared_value_cents": 80_000,
    "photo_count": 4,
    "volume_cuft": 8,
    "footprint_sqft": 15,
}


def test_a_tag_code_is_reusable_once_its_holder_has_been_written_off():
    """The tag has left the building with the piece, so the string is free again.

    PRD 3.6: "Finally the `tag_code` must be free — no other piece whose `inventory_state`
    is anything other than `WRITTEN_OFF_INV` may already hold it — otherwise
    `ERR_DUPLICATE_TAG_CODE`. Tag codes of written-off pieces are deliberately recyclable,
    because those tags have physically left the building."

    PRD 3.9: "On success the custody dimension moves `SHRINKAGE_MISSING → WRITTEN_OFF_INV`
    and the merchandising dimension moves to `WRITTEN_OFF`, `placement_zone_id` is cleared
    to null and the released zone's occupancy figures are recomputed, one `SHRINKAGE_CREDIT`
    entry of the same sixty-percent-of-current-price amount is minted"

    PRD 3.9: "The credit for one piece is that piece's `current_price_cents` multiplied by
    60 hundredths and rounded half up to a whole number of cents"

    PRD 2.10: "`occupied_sqft` is the exact integer sum of `footprint_sqft` over every
    `ConsignmentItem` whose `placement_zone_id` names that zone"

    PRD 3.6: "On success the piece moves `AWAITING_PLACEMENT → ON_FLOOR`, its
    `placement_zone_id` and `tag_code` are written, and its `version` increments by 1."

    Design: Corner/validations/a_tag_code_is_reusable_once_its_holder_has_been_written_off
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    consignor_id = world["consignor"]["id"]
    agreement_id = world["agreement"]["id"]
    one = create_item(agreement_id, **FIRST_CREDENZA)
    two = create_item(agreement_id, **SECOND_BUREAU)
    screen_item(one["id"], scores=SCORES_GRADE_A)
    screen_item(two["id"], scores=SCORES_GRADE_A)
    take_custody(
        consignor_id,
        [one["id"], two["id"]],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    receive_item(one["id"], scores=SCORES_GRADE_A)
    receive_item(two["id"], scores=SCORES_GRADE_A)
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    place_item(one["id"], zone["id"], tag_code="TAG-001")
    flag_inventory(one["id"], "MISSING")
    write_off_item(one["id"])

    reused = place_item(two["id"], zone["id"], tag_code="TAG-001")

    assert reused["tag_code"] == "TAG-001", (
        f"Expected the recycled tag accepted, got {reused['tag_code']}"
    )
    assert reused["lifecycle_state"] == "ON_FLOOR", (
        f"Expected ON_FLOOR, got {reused['lifecycle_state']}"
    )
    assert reused["current_price_cents"] == 68_000, (
        f"Expected the bureau's own price of 68000, "
        f"got {reused['current_price_cents']}"
    )
    assert reused["listed_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected the listing stamped from the clock, got {reused['listed_at']}"
    )

    written_off = fetch_item(one["id"])
    assert written_off["tag_code"] == "TAG-001", (
        f"Expected the written-off piece to keep the string on its row, "
        f"got {written_off['tag_code']}"
    )
    assert written_off["inventory_state"] == "WRITTEN_OFF_INV", (
        f"Expected WRITTEN_OFF_INV, got {written_off['inventory_state']}"
    )
    assert written_off["placement_zone_id"] is None, (
        f"Expected the zone cleared, got {written_off['placement_zone_id']}"
    )

    occupancy = fetch_zone(zone["id"])
    assert occupancy["occupied_sqft"] == 15, (
        f"Expected the released 20 square feet replaced by 15, "
        f"got {occupancy['occupied_sqft']}"
    )

    consignor = fetch_consignor(consignor_id)
    assert consignor["unclaimed_balance_cents"] == 13_600, (
        f"Expected round_half_up(51000 * 0.60) against 17000 of surcharge, "
        f"got {consignor['unclaimed_balance_cents']}"
    )
