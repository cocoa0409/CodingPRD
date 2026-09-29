"""Refusals that guard the photographs, the grade, the lot and the tag."""

from test_helpers import (
    FLOOR_OPERATOR,
    INTAKE_APPRAISER,
    SCORES_GRADE_A,
    SCORES_GRADE_D,
    SCORES_GRADE_REJECTED,
    ApiErrorId,
    api_client,
    create_item,
    create_zone,
    fetch_consignor,
    fetch_item,
    fetch_zone,
    get_success_data,
    item_payload,
    place_payload,
    receive_item,
    screen_item,
    screen_payload,
    setup_consignor_with_active_agreement,
    take_custody,
    total_count,
    validate_error,
)

ONE_STEP = [(1, 0, 0.00, 0)]

DOSSIER_FIELDS = {
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "volume_cuft": 12,
    "footprint_sqft": 10,
}
MARRED_BUREAU = {
    "title": "Marred Bureau",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 5,
    "volume_cuft": 12,
    "footprint_sqft": 10,
}


def test_screening_a_piece_backed_by_only_two_photographs_is_refused():
    """The photograph floor is three, and the third one changes nothing but admissibility.

    PRD 3.3: "It must also carry at least 3 intake photographs and all three sub-scores
    must be present; fewer than three photographs, or a missing sub-score, is refused with
    `ERR_PHOTOS_INSUFFICIENT`."

    PRD 3.3: "The computed price is written to `provisional_list_price_cents` and **also**
    seeds `list_price_cents`, while the derived grade seeds `condition_grade` as well as
    `provisional_condition_grade`, so the piece can be quoted and scheduled onto a truck
    before anyone has physically touched it."

    Design: Corner/errors/screening_a_piece_backed_by_only_two_photographs_is_refused
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    agreement_id = world["agreement"]["id"]

    thin = create_item(agreement_id, title="Thin Dossier", photo_count=2, **DOSSIER_FIELDS)
    fat = create_item(agreement_id, title="Fat Dossier", photo_count=3, **DOSSIER_FIELDS)

    refused = api_client.screen_item(
        thin["id"], screen_payload(scores=SCORES_GRADE_A), INTAKE_APPRAISER
    )
    validate_error(refused, ApiErrorId.ERR_PHOTOS_INSUFFICIENT, 422)

    unscreened = fetch_item(thin["id"])
    assert unscreened["lifecycle_state"] == "INTAKE_SUBMITTED", (
        f"Expected the piece still awaiting screening, "
        f"got {unscreened['lifecycle_state']}"
    )
    assert unscreened["photo_score"] is None, (
        f"Expected no score written, got {unscreened['photo_score']}"
    )
    assert unscreened["condition_grade"] is None, (
        f"Expected no grade written, got {unscreened['condition_grade']}"
    )

    accepted = get_success_data(
        api_client.screen_item(
            fat["id"], screen_payload(scores=SCORES_GRADE_A), INTAKE_APPRAISER
        )
    )
    assert accepted["photo_score"] == 8.55, (
        f"Expected 3.60 + 2.70 + 2.25, got {accepted['photo_score']}"
    )
    assert accepted["condition_grade"] == "A", (
        f"Expected A, got {accepted['condition_grade']}"
    )
    assert accepted["list_price_cents"] == 51_000, (
        f"Expected 60000 at eighty-five hundredths, got {accepted['list_price_cents']}"
    )


def test_placing_a_piece_regraded_to_rejected_on_arrival_is_refused():
    """A one-grade fall to REJECTED is no dispute, so the refusal waits for the floor.

    PRD 3.5: "a `D` graded down to `REJECTED` is only a one-grade step and lands in
    `AWAITING_PLACEMENT` with `condition_grade` `REJECTED` and `list_price_cents` null."

    PRD 3.5: "Receiving does not refuse a rejected piece — it will be refused later, when
    someone tries to put it on a floor, with `ERR_GRADE_REJECTED`."

    PRD 3.6: "A piece whose `condition_grade` is `REJECTED` may never reach a floor and is
    refused with `ERR_GRADE_REJECTED`."

    Design: Corner/errors/placing_a_piece_regraded_to_rejected_on_arrival_is_refused
    """
    world = setup_consignor_with_active_agreement(
        schedule_steps=ONE_STEP,
        consignor_overrides={"floor_number": 1, "has_elevator": False},
    )
    bureau = create_item(world["agreement"]["id"], **MARRED_BUREAU)
    provisional = screen_item(bureau["id"], scores=SCORES_GRADE_D)
    assert provisional["provisional_condition_grade"] == "D", (
        f"Expected a provisional D, got {provisional['provisional_condition_grade']}"
    )
    assert provisional["provisional_list_price_cents"] == 24_000, (
        f"Expected 60000 at forty hundredths, "
        f"got {provisional['provisional_list_price_cents']}"
    )

    take_custody(world["consignor"]["id"], [bureau["id"]])
    assert fetch_consignor(world["consignor"]["id"])["status"] == "ACTIVE", (
        "Expected a 17000 surcharge to leave the account well above the suspension floor"
    )

    received = receive_item(bureau["id"], scores=SCORES_GRADE_REJECTED)
    assert received["condition_grade"] == "REJECTED", (
        f"Expected REJECTED on arrival, got {received['condition_grade']}"
    )
    assert received["lifecycle_state"] == "AWAITING_PLACEMENT", (
        f"Expected a one-grade fall to skip the dispute, "
        f"got {received['lifecycle_state']}"
    )

    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    refused = api_client.place_item(
        bureau["id"], place_payload(zone["id"], "FRONT-0001"), FLOOR_OPERATOR
    )
    validate_error(refused, ApiErrorId.ERR_GRADE_REJECTED, 422)

    after = fetch_item(bureau["id"])
    assert after["lifecycle_state"] == "AWAITING_PLACEMENT", (
        f"Expected the piece parked where it stood, got {after['lifecycle_state']}"
    )
    assert after["condition_grade"] == "REJECTED", (
        f"Expected REJECTED, got {after['condition_grade']}"
    )
    assert after["provisional_condition_grade"] == "D", (
        f"Expected the provisional D kept for the record, "
        f"got {after['provisional_condition_grade']}"
    )
    assert after["list_price_cents"] is None, (
        f"Expected no ticket price, got {after['list_price_cents']}"
    )
    assert after["provisional_list_price_cents"] == 24_000, (
        f"Expected the provisional 24000 kept, "
        f"got {after['provisional_list_price_cents']}"
    )
    assert after["placement_zone_id"] is None, (
        f"Expected no zone claimed, got {after['placement_zone_id']}"
    )
    assert after["tag_code"] is None, (
        f"Expected no tag printed, got {after['tag_code']}"
    )

    empty = fetch_zone(zone["id"])
    assert empty["occupied_sqft"] == 0, (
        f"Expected the zone untouched, got {empty['occupied_sqft']}"
    )
    assert empty["utilization_state"] == "NORMAL", (
        f"Expected NORMAL, got {empty['utilization_state']}"
    )


SUITE_PARENT = {
    "title": "Suite Lot",
    "category": "CASEGOOD",
    "declared_value_cents": 1_000,
    "photo_count": 5,
    "volume_cuft": 2,
    "footprint_sqft": 12,
}
CHAIR_ONE = {
    "title": "Chair One",
    "category": "DINING",
    "declared_value_cents": 40_000,
    "photo_count": 5,
    "volume_cuft": 20,
    "footprint_sqft": 8,
}
CHAIR_TWO = {
    "title": "Chair Two",
    "category": "DINING",
    "declared_value_cents": 30_000,
    "photo_count": 5,
    "volume_cuft": 18,
    "footprint_sqft": 8,
}


def test_nesting_a_lot_component_under_another_component_is_refused():
    """A set is one level deep, so a chair may not become the parent of a chair.

    PRD 3.2: "Lots are exactly one level deep and never cross agreements: the named parent
    must itself not be a component, meaning its own `parent_lot_item_id` must be null, and
    it must belong to the same agreement as the component being created. Either violation is
    refused with `ERR_LOT_NESTING_FORBIDDEN`."

    PRD 3.2: "Supplying `parent_lot_item_id` recomputes the parent's
    `lot_component_count`, which is simply the number of pieces pointing at it, and
    re-evaluates the parent's `lot_ready` flag."

    Design: Corner/errors/nesting_a_lot_component_under_another_component_is_refused
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    agreement_id = world["agreement"]["id"]

    parent = create_item(agreement_id, **SUITE_PARENT)
    chair_one = create_item(agreement_id, parent_lot_item_id=parent["id"], **CHAIR_ONE)
    assert chair_one["parent_lot_item_id"] == parent["id"], (
        f"Expected the first chair pointed at the set, "
        f"got {chair_one['parent_lot_item_id']}"
    )

    nested = api_client.create_item(
        item_payload(agreement_id, parent_lot_item_id=chair_one["id"], **CHAIR_TWO),
        INTAKE_APPRAISER,
    )
    validate_error(nested, ApiErrorId.ERR_LOT_NESTING_FORBIDDEN, 422)

    under_the_chair = api_client.list_items(
        INTAKE_APPRAISER,
        params={"parent_lot_item_id": chair_one["id"], "limit": 100},
    )
    assert total_count(under_the_chair) == 0, (
        f"Expected nothing hanging off a component, "
        f"got {total_count(under_the_chair)}"
    )

    beside_it = api_client.create_item(
        item_payload(agreement_id, parent_lot_item_id=parent["id"], **CHAIR_TWO),
        INTAKE_APPRAISER,
    )
    assert beside_it.status_code == 201, (
        f"Expected the same chair under the set to be accepted, "
        f"got {beside_it.status_code}: {beside_it.text}"
    )
    assert fetch_item(parent["id"])["lot_component_count"] == 2, (
        f"Expected two components counted on the set, "
        f"got {fetch_item(parent['id'])['lot_component_count']}"
    )


def test_placing_a_lot_parent_while_one_component_is_still_uncollected_is_refused():
    """One chair left in the living room holds the whole set off the floor.

    PRD 3.2: "`lot_ready` is true when the piece has no components at all — a
    `lot_component_count` of zero — and otherwise true only when every one of its
    components has reached `inventory_state` `IN_CUSTODY`; a parent with even one component
    still in `PENDING_CUSTODY` is not ready."

    PRD 3.6: "A lot parent must have `lot_ready` true — every one of its components in
    `IN_CUSTODY` — otherwise `ERR_LOT_NOT_READY`, since selling three chairs of a
    four-chair set as a set is not a thing the gallery does."

    PRD 3.3: "A piece that has components is priced as a bundle instead: collect every
    component whose `lifecycle_state` is not `SCREEN_REJECTED`, sum their
    `list_price_cents` values — the components' prices are already rounded integers, and
    addition is order-independent, though components are walked in `created_at` ascending
    order for deterministic replay — multiply that sum by 90 hundredths, and round the
    single product half up to a whole number of cents."

    Design: Corner/errors/placing_a_lot_parent_while_one_component_is_still_uncollected_is_refused
    """
    world = setup_consignor_with_active_agreement(
        schedule_steps=ONE_STEP,
        consignor_overrides={"floor_number": 1, "has_elevator": False},
    )
    agreement_id = world["agreement"]["id"]

    parent = create_item(agreement_id, **SUITE_PARENT)
    chair_one = create_item(agreement_id, parent_lot_item_id=parent["id"], **CHAIR_ONE)
    chair_two = create_item(agreement_id, parent_lot_item_id=parent["id"], **CHAIR_TWO)
    assert screen_item(chair_one["id"], scores=SCORES_GRADE_A)["list_price_cents"] == 35_700, (
        "Expected 40000 at eighty-five hundredths and then the dining factor"
    )
    assert screen_item(chair_two["id"], scores=SCORES_GRADE_A)["list_price_cents"] == 26_775, (
        "Expected 30000 at eighty-five hundredths and then the dining factor"
    )
    priced = screen_item(parent["id"], scores=SCORES_GRADE_A)
    assert priced["list_price_cents"] == 56_228, (
        f"Expected 62475 at ninety hundredths, got {priced['list_price_cents']}"
    )

    take_custody(world["consignor"]["id"], [parent["id"], chair_one["id"]])
    receive_item(parent["id"], scores=SCORES_GRADE_A)
    receive_item(chair_one["id"], scores=SCORES_GRADE_A)

    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    refused = api_client.place_item(
        parent["id"], place_payload(zone["id"], "FRONT-0001"), FLOOR_OPERATOR
    )
    validate_error(refused, ApiErrorId.ERR_LOT_NOT_READY, 409)

    after = fetch_item(parent["id"])
    assert after["lot_ready"] is False, (
        f"Expected the conjunction false, got {after['lot_ready']}"
    )
    assert after["lot_component_count"] == 2, (
        f"Expected two components, got {after['lot_component_count']}"
    )
    assert after["lifecycle_state"] == "AWAITING_PLACEMENT", (
        f"Expected the set still awaiting placement, got {after['lifecycle_state']}"
    )
    assert after["inventory_state"] == "IN_CUSTODY", (
        f"Expected the set itself in the building, got {after['inventory_state']}"
    )
    assert after["list_price_cents"] == 56_228, (
        f"Expected the bundle price intact, got {after['list_price_cents']}"
    )
    assert after["placement_zone_id"] is None, (
        f"Expected no zone claimed, got {after['placement_zone_id']}"
    )
    assert after["tag_code"] is None, (
        f"Expected no tag printed, got {after['tag_code']}"
    )

    laggard = fetch_item(chair_two["id"])
    assert laggard["inventory_state"] == "PENDING_CUSTODY", (
        f"Expected the uncollected chair still outside, "
        f"got {laggard['inventory_state']}"
    )
    assert laggard["pickup_job_id"] is None, (
        f"Expected it on no truck, got {laggard['pickup_job_id']}"
    )

    assert fetch_zone(zone["id"])["occupied_sqft"] == 0, (
        f"Expected the zone untouched, got {fetch_zone(zone['id'])['occupied_sqft']}"
    )


ON_FLOOR_BUREAU = {
    "title": "Bureau",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 5,
    "volume_cuft": 12,
    "footprint_sqft": 10,
}
SECOND_CREDENZA = {
    "title": "Credenza",
    "category": "CASEGOOD",
    "declared_value_cents": 80_000,
    "photo_count": 5,
    "volume_cuft": 20,
    "footprint_sqft": 10,
}


def test_reusing_a_tag_code_held_by_a_piece_still_on_the_floor_is_refused():
    """The tag on a piece in the building is taken, and the refusal claims no floor space.

    PRD 3.6: "Finally the `tag_code` must be free — no other piece whose `inventory_state`
    is anything other than `WRITTEN_OFF_INV` may already hold it — otherwise
    `ERR_DUPLICATE_TAG_CODE`."

    PRD 2.10: "`occupied_sqft` is the exact integer sum of `footprint_sqft` over every
    `ConsignmentItem` whose `placement_zone_id` names that zone"

    Design: Corner/errors/reusing_a_tag_code_held_by_a_piece_still_on_the_floor_is_refused
    """
    world = setup_consignor_with_active_agreement(
        schedule_steps=ONE_STEP,
        consignor_overrides={"floor_number": 1, "has_elevator": False},
    )
    agreement_id = world["agreement"]["id"]

    bureau = create_item(agreement_id, **ON_FLOOR_BUREAU)
    credenza = create_item(agreement_id, **SECOND_CREDENZA)
    assert screen_item(bureau["id"], scores=SCORES_GRADE_A)["list_price_cents"] == 51_000, (
        "Expected 60000 at eighty-five hundredths for the bureau"
    )
    assert screen_item(credenza["id"], scores=SCORES_GRADE_A)["list_price_cents"] == 68_000, (
        "Expected 80000 at eighty-five hundredths for the credenza"
    )

    take_custody(world["consignor"]["id"], [bureau["id"], credenza["id"]])
    receive_item(bureau["id"], scores=SCORES_GRADE_A)
    receive_item(credenza["id"], scores=SCORES_GRADE_A)

    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    placed = get_success_data(
        api_client.place_item(
            bureau["id"], place_payload(zone["id"], "SHOWROOM-1"), FLOOR_OPERATOR
        )
    )
    assert placed["tag_code"] == "SHOWROOM-1", (
        f"Expected the first tag printed, got {placed['tag_code']}"
    )
    assert fetch_zone(zone["id"])["occupied_sqft"] == 10, (
        f"Expected ten square feet claimed, "
        f"got {fetch_zone(zone['id'])['occupied_sqft']}"
    )

    collision = api_client.place_item(
        credenza["id"], place_payload(zone["id"], "SHOWROOM-1"), FLOOR_OPERATOR
    )
    validate_error(collision, ApiErrorId.ERR_DUPLICATE_TAG_CODE, 409)

    unplaced = fetch_item(credenza["id"])
    assert unplaced["lifecycle_state"] == "AWAITING_PLACEMENT", (
        f"Expected the credenza still off the floor, "
        f"got {unplaced['lifecycle_state']}"
    )
    assert unplaced["tag_code"] is None, (
        f"Expected no tag printed, got {unplaced['tag_code']}"
    )
    assert unplaced["placement_zone_id"] is None, (
        f"Expected no zone claimed, got {unplaced['placement_zone_id']}"
    )
    assert unplaced["listed_at"] is None, (
        f"Expected no listing instant, got {unplaced['listed_at']}"
    )
    assert fetch_zone(zone["id"])["occupied_sqft"] == 10, (
        f"Expected the bureau's footprint alone, "
        f"got {fetch_zone(zone['id'])['occupied_sqft']}"
    )

    fresh = get_success_data(
        api_client.place_item(
            credenza["id"], place_payload(zone["id"], "SHOWROOM-2"), FLOOR_OPERATOR
        )
    )
    assert fresh["tag_code"] == "SHOWROOM-2", (
        f"Expected the fresh tag, got {fresh['tag_code']}"
    )
    assert fresh["current_price_cents"] == 68_000, (
        f"Expected the credenza ticketed at 68000, got {fresh['current_price_cents']}"
    )
    assert fetch_zone(zone["id"])["occupied_sqft"] == 20, (
        f"Expected twenty square feet, "
        f"got {fetch_zone(zone['id'])['occupied_sqft']}"
    )
