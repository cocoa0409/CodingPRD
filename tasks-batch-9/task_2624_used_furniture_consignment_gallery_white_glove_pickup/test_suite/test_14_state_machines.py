"""Transitions taken, transitions refused, and the side effects that ride along."""

from test_helpers import (
    FLOOR_OPERATOR,
    GALLERY_MANAGER,
    GALLERY_MANAGER_2,
    GALLERY_MANAGER_ID,
    INTAKE_APPRAISER,
    INTAKE_APPRAISER_ID,
    LOGISTICS_COORDINATOR,
    SCORES_GRADE_A,
    ApiErrorId,
    api_client,
    complete_pickup_payload,
    create_active_agreement,
    create_agreement,
    create_buyer,
    create_consignor,
    create_item,
    create_price_schedule,
    create_truck,
    create_zone,
    fetch_agreement,
    fetch_consignor,
    fetch_consignor_ledger,
    fetch_item,
    fetch_pickup_job,
    fetch_zone,
    flag_inventory,
    get_success_data,
    place_item,
    place_payload,
    receive_item,
    sale_payload,
    schedule_pickup,
    screen_item,
    total_count,
    validate_error,
)

TWO_STEP = [(1, 0, 0.00, 0), (2, 30, 0.15, 0)]
ONE_STEP = [(1, 0, 0.00, 0)]

CREDENZA = {
    "title": "Walnut credenza",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 20,
}


def _an_active_agreement(steps=TWO_STEP):
    """A schedule, a ground-floor consignor and an ACTIVE agreement over both."""
    schedule = create_price_schedule(steps=steps)
    consignor = create_consignor(display_name="Alpha", address_line="1 A St")
    agreement = create_active_agreement(consignor["id"], schedule["id"], term_days=365)
    return {"schedule": schedule, "consignor": consignor, "agreement": agreement}


def _a_credenza_awaiting_placement():
    """One grade-A credenza collected, received and waiting beside an empty showroom."""
    world = _an_active_agreement()
    credenza = create_item(world["agreement"]["id"], **CREDENZA)
    screen_item(credenza["id"], scores=SCORES_GRADE_A)
    truck = create_truck(name="BOX-1", capacity_volume_cuft=100)
    job = schedule_pickup(
        world["consignor"]["id"],
        truck["id"],
        [credenza["id"]],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    get_success_data(
        api_client.complete_pickup_job(
            job["id"], complete_pickup_payload(), LOGISTICS_COORDINATOR
        )
    )
    receive_item(credenza["id"], scores=SCORES_GRADE_A)
    world["truck"] = truck
    world["job"] = fetch_pickup_job(job["id"])
    world["credenza"] = fetch_item(credenza["id"])
    world["zone"] = create_zone(
        name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200
    )
    return world


def test_screening_accepts_the_piece_without_touching_its_custody_dimension():
    """The merchandising dimension advances; the custody dimension has not been asked to.

    PRD 3.3: "When the `decision` is `ACCEPT` and the derived grade is anything other
    than `REJECTED`, the piece moves `INTAKE_SUBMITTED → SCREEN_ACCEPTED`."

    PRD 3.3: "Screening records `screened_by_user_id` from `X-User-ID` and increments the
    piece's `version` by 1."

    Design: Corner/state_machines/screening_moves_the_item_from_intake_submitted_to_screen_accepted
    """
    world = _an_active_agreement(steps=ONE_STEP)
    credenza = create_item(world["agreement"]["id"], **CREDENZA)

    screened = screen_item(credenza["id"], scores=SCORES_GRADE_A)

    assert screened["lifecycle_state"] == "SCREEN_ACCEPTED", (
        f"Expected SCREEN_ACCEPTED, got {screened['lifecycle_state']}"
    )
    assert screened["inventory_state"] == "PENDING_CUSTODY", (
        f"Expected the custody dimension untouched, got {screened['inventory_state']}"
    )
    assert screened["screened_by_user_id"] == INTAKE_APPRAISER_ID, (
        f"Expected the acting appraiser recorded, "
        f"got {screened['screened_by_user_id']}"
    )
    assert screened["received_by_user_id"] is None, (
        f"Expected no receiving operator yet, got {screened['received_by_user_id']}"
    )
    assert screened["version"] == 2, (
        f"Expected version 2 after the first mutation, got {screened['version']}"
    )


def test_activating_an_agreement_twice_does_not_restamp_the_term():
    """The second activation is refused, and the first approver keeps the row.

    PRD 3.2: "The agreement must be in `DRAFT`, or the request is refused with
    `ERR_AGREEMENT_STATE_INVALID`"

    PRD 3.2: "On success, `effective_at` is stamped with the current logical clock,
    `expires_at` is computed as `effective_at` advanced by `term_days` whole days — that
    is, by `term_days` multiplied by 86,400 seconds — `approved_by_user_id` records the
    acting `X-User-ID`, and the agreement's `version` increments by 1."

    Design: Corner/state_machines/activating_an_already_active_agreement_is_refused
    """
    schedule = create_price_schedule(steps=ONE_STEP)
    consignor = create_consignor(display_name="Alpha", address_line="1 A St")
    drafted = create_agreement(consignor["id"], schedule["id"], term_days=365)
    get_success_data(api_client.activate_agreement(drafted["id"], GALLERY_MANAGER))

    second = api_client.activate_agreement(drafted["id"], GALLERY_MANAGER_2)
    validate_error(second, ApiErrorId.ERR_AGREEMENT_STATE_INVALID, 409)

    stored = fetch_agreement(drafted["id"])
    assert stored["approved_by_user_id"] == GALLERY_MANAGER_ID, (
        f"Expected the first approver retained, got {stored['approved_by_user_id']}"
    )
    assert stored["version"] == 2, (
        f"Expected version 2 from the single successful activation, "
        f"got {stored['version']}"
    )
    assert stored["effective_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected the original effective_at, got {stored['effective_at']}"
    )
    assert stored["expires_at"].startswith("2027-08-01T00:00:00"), (
        f"Expected the original expires_at, got {stored['expires_at']}"
    )


def test_placement_writes_the_tag_the_listing_stamp_and_the_zone_occupancy():
    """One call moves the piece, prints the tag, starts the tenure and fills the zone.

    PRD 3.6: "On success the piece moves `AWAITING_PLACEMENT → ON_FLOOR`, its
    `placement_zone_id` and `tag_code` are written, and its `version` increments by 1."

    PRD 3.6: "on a first placement `days_on_floor` is 0, so the step in force is the
    sequence-1 step sitting at day offset 0, `markdown_sequence` becomes 1, and
    `current_price_cents` becomes `list_price_cents` reduced by that step's
    `markdown_pct` and then raised to that step's `min_price_cents` if the reduction
    landed below it."

    PRD 3.6: "If the resulting `current_price_cents` is below 50,000 cents and the chosen
    zone's `zone_type` is not `CLEARANCE`, the clearance relocation selector runs
    immediately"

    PRD 2.10: "`occupied_sqft` is the exact integer sum of `footprint_sqft` over every
    `ConsignmentItem` whose `placement_zone_id` names that zone"

    Design: Corner/state_machines/placement_stamps_the_tag_the_listing_clock_and_the_zone_occupancy
    """
    world = _a_credenza_awaiting_placement()
    zone_id = world["zone"]["id"]
    assert fetch_zone(zone_id)["occupied_sqft"] == 0, "Expected an empty showroom"

    response = api_client.place_item(
        world["credenza"]["id"], place_payload(zone_id, tag_code="TAG-001"), FLOOR_OPERATOR
    )
    assert response.status_code == 200, (
        f"Expected 200 on placement, got {response.status_code}"
    )
    placed = get_success_data(response)

    assert placed["lifecycle_state"] == "ON_FLOOR", (
        f"Expected ON_FLOOR, got {placed['lifecycle_state']}"
    )
    assert placed["tag_code"] == "TAG-001", (
        f"Expected the printed tag, got {placed['tag_code']}"
    )
    assert placed["placement_zone_id"] == zone_id, (
        f"Expected the chosen zone, got {placed['placement_zone_id']}"
    )
    assert placed["listed_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected the logical clock stamped, got {placed['listed_at']}"
    )
    assert placed["days_on_floor"] == 0, (
        f"Expected a fresh tenure, got {placed['days_on_floor']}"
    )
    assert placed["markdown_sequence"] == 1, (
        f"Expected the sequence-1 step in force, got {placed['markdown_sequence']}"
    )
    assert placed["current_price_cents"] == 51_000, (
        f"Expected 51000 at a 0.00 markdown, got {placed['current_price_cents']}"
    )
    assert placed["list_price_cents"] == 51_000, (
        f"Expected the ticket price 51000, got {placed['list_price_cents']}"
    )
    assert placed["clearance_relocation_pending"] is False, (
        f"Expected no clearance debt at 51000, "
        f"got {placed['clearance_relocation_pending']}"
    )

    zone = fetch_zone(zone_id)
    assert zone["occupied_sqft"] == 20, (
        f"Expected the piece's 20 square feet booked, got {zone['occupied_sqft']}"
    )
    assert zone["utilization_state"] == "NORMAL", (
        f"Expected NORMAL at 20 of 200, got {zone['utilization_state']}"
    )


def test_placing_a_piece_that_has_not_been_screened_is_refused():
    """Placement is declared only out of AWAITING_PLACEMENT, and nothing leaks on refusal.

    PRD 3.6: "The piece must be in `lifecycle_state` `AWAITING_PLACEMENT`, otherwise
    `ERR_ITEM_STATE_INVALID`"

    PRD 3.6: "On success the piece moves `AWAITING_PLACEMENT → ON_FLOOR`, its
    `placement_zone_id` and `tag_code` are written, and its `version` increments by 1."

    Design: Corner/state_machines/placing_a_piece_that_was_never_screened_is_refused
    """
    world = _an_active_agreement()
    credenza = create_item(world["agreement"]["id"], **CREDENZA)
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)

    response = api_client.place_item(
        credenza["id"], place_payload(zone["id"], tag_code="TAG-001"), FLOOR_OPERATOR
    )
    validate_error(response, ApiErrorId.ERR_ITEM_STATE_INVALID, 409)

    stored = fetch_item(credenza["id"])
    assert stored["lifecycle_state"] == "INTAKE_SUBMITTED", (
        f"Expected INTAKE_SUBMITTED, got {stored['lifecycle_state']}"
    )
    assert stored["tag_code"] is None, (
        f"Expected no tag printed, got {stored['tag_code']}"
    )
    assert stored["listed_at"] is None, (
        f"Expected no tenure started, got {stored['listed_at']}"
    )
    assert stored["placement_zone_id"] is None, (
        f"Expected no zone, got {stored['placement_zone_id']}"
    )
    assert stored["version"] == 1, (
        f"Expected version 1 untouched, got {stored['version']}"
    )
    assert fetch_zone(zone["id"])["occupied_sqft"] == 0, (
        "Expected the showroom to stay empty"
    )


def test_a_new_piece_opens_on_both_dimensions_with_every_price_column_null():
    """Intake seats two state machines at once and prices nothing yet.

    PRD 3.2: "A new piece opens with `lifecycle_state` `INTAKE_SUBMITTED` and
    `inventory_state` `PENDING_CUSTODY`, and the owning agreement's `item_count` is
    recomputed."

    PRD 3.2: "`consignor_id` is copied from the named agreement at intake, so a piece can
    never be attributed to a consignor who did not sign for it."

    PRD 3.2: "`lot_ready` is true when the piece has no components at all — a
    `lot_component_count` of zero"

    Design: Corner/state_machines/a_new_item_starts_in_intake_submitted_and_pending_custody
    """
    world = _an_active_agreement(steps=ONE_STEP)
    agreement_id = world["agreement"]["id"]

    response = api_client.create_item(
        {"agreement_id": agreement_id, **CREDENZA}, INTAKE_APPRAISER
    )
    assert response.status_code == 201, (
        f"Expected 201 on intake, got {response.status_code}"
    )
    created = get_success_data(response)

    assert created["lifecycle_state"] == "INTAKE_SUBMITTED", (
        f"Expected INTAKE_SUBMITTED, got {created['lifecycle_state']}"
    )
    assert created["inventory_state"] == "PENDING_CUSTODY", (
        f"Expected PENDING_CUSTODY, got {created['inventory_state']}"
    )
    assert created["consignor_id"] == world["consignor"]["id"], (
        f"Expected the agreement's consignor copied, got {created['consignor_id']}"
    )
    for column in (
        "photo_score",
        "provisional_condition_grade",
        "provisional_list_price_cents",
        "condition_grade",
        "list_price_cents",
        "current_price_cents",
    ):
        assert created[column] is None, (
            f"Expected {column} null before screening, got {created[column]}"
        )
    assert created["markdown_sequence"] == 0, (
        f"Expected no markdown step yet, got {created['markdown_sequence']}"
    )
    assert created["election_round"] == 0, (
        f"Expected no election rounds spent, got {created['election_round']}"
    )
    assert created["disposition_election"] == "NONE", (
        f"Expected NONE, got {created['disposition_election']}"
    )
    assert created["clearance_relocation_pending"] is False, (
        f"Expected no clearance debt, got {created['clearance_relocation_pending']}"
    )
    assert created["lot_component_count"] == 0, (
        f"Expected no components, got {created['lot_component_count']}"
    )
    assert created["lot_ready"] is True, (
        f"Expected a componentless piece to read ready, got {created['lot_ready']}"
    )
    assert fetch_agreement(agreement_id)["item_count"] == 1, (
        "Expected the agreement's item_count recomputed to 1"
    )


def test_a_screen_rejected_piece_cannot_be_screened_a_second_time():
    """Rejection is terminal, so a better second set of photographs never lands.

    PRD 3.3: "When the derived grade is `REJECTED`, or when the appraiser's `decision` is
    `REJECT`, the piece moves `INTAKE_SUBMITTED → SCREEN_REJECTED`, which is terminal on
    the merchandising dimension."

    PRD 3.3: "The piece must be in `lifecycle_state` `INTAKE_SUBMITTED`, or the request is
    refused with `ERR_ITEM_STATE_INVALID`."

    PRD 3.3: "Multiply the surface sub-score by 45 hundredths, the structure sub-score by
    30 hundredths and the completeness sub-score by 25 hundredths, add the three products
    together, and round that sum half up to two decimal places"

    Design: Corner/state_machines/rescreening_a_screen_rejected_piece_is_refused
    """
    world = _an_active_agreement(steps=ONE_STEP)
    credenza = create_item(world["agreement"]["id"], **CREDENZA)

    rejected = screen_item(credenza["id"], scores=SCORES_GRADE_A, decision="REJECT")
    assert rejected["lifecycle_state"] == "SCREEN_REJECTED", (
        f"Expected SCREEN_REJECTED, got {rejected['lifecycle_state']}"
    )
    assert rejected["photo_score"] == 8.55, (
        f"Expected the weighted 8.55 recorded even on a rejection, "
        f"got {rejected['photo_score']}"
    )

    second = api_client.screen_item(
        credenza["id"],
        {"decision": "ACCEPT", **SCORES_GRADE_A},
        INTAKE_APPRAISER,
    )
    validate_error(second, ApiErrorId.ERR_ITEM_STATE_INVALID, 409)

    stored = fetch_item(credenza["id"])
    assert stored["lifecycle_state"] == "SCREEN_REJECTED", (
        f"Expected SCREEN_REJECTED to hold, got {stored['lifecycle_state']}"
    )
    assert stored["version"] == 2, (
        f"Expected version 2 from the single screening, got {stored['version']}"
    )
    assert stored["photo_score"] == 8.55, (
        f"Expected the rejection's score kept, got {stored['photo_score']}"
    )
    assert stored["list_price_cents"] is None, (
        f"Expected a rejected piece to carry no ticket price, "
        f"got {stored['list_price_cents']}"
    )


def test_completing_a_pickup_job_twice_mints_only_one_surcharge_debit():
    """The second completion is refused before the ledger can be charged again.

    PRD 3.4: "The job must be in `status` `SCHEDULED`, otherwise
    `ERR_PICKUP_JOB_STATE_INVALID`, and must have at least one piece attached."

    PRD 3.4: "exactly one `PICKUP_SURCHARGE_DEBIT` ledger entry is minted for the job's
    consignor, carrying `amount_cents` equal to the negation of `final_surcharge_cents`
    and an `item_id` of null"

    Design: Corner/state_machines/completing_an_already_completed_pickup_job_is_refused
    """
    world = _an_active_agreement(steps=ONE_STEP)
    consignor_id = world["consignor"]["id"]
    credenza = create_item(world["agreement"]["id"], **CREDENZA)
    screen_item(credenza["id"], scores=SCORES_GRADE_A)
    truck = create_truck(name="BOX-1", capacity_volume_cuft=100)
    job = schedule_pickup(
        consignor_id,
        truck["id"],
        [credenza["id"]],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    get_success_data(
        api_client.complete_pickup_job(
            job["id"], complete_pickup_payload(), LOGISTICS_COORDINATOR
        )
    )

    second = api_client.complete_pickup_job(
        job["id"], complete_pickup_payload(), LOGISTICS_COORDINATOR
    )
    validate_error(second, ApiErrorId.ERR_PICKUP_JOB_STATE_INVALID, 409)

    stored = fetch_pickup_job(job["id"])
    assert stored["status"] == "COMPLETED", (
        f"Expected COMPLETED to hold, got {stored['status']}"
    )
    assert stored["final_surcharge_cents"] == 17_000, (
        f"Expected 12000 plus two volume blocks, "
        f"got {stored['final_surcharge_cents']}"
    )
    assert stored["surcharge_variance_cents"] == 0, (
        f"Expected the quote to have been met exactly, "
        f"got {stored['surcharge_variance_cents']}"
    )

    entries = fetch_consignor_ledger(consignor_id)
    assert [e["amount_cents"] for e in entries] == [-17_000], (
        f"Expected a single debit, got {[e['amount_cents'] for e in entries]}"
    )
    assert fetch_consignor(consignor_id)["unclaimed_balance_cents"] == -17_000, (
        "Expected the balance charged once rather than twice"
    )


def test_selling_a_mislaid_piece_is_refused_on_the_custody_dimension():
    """The lifecycle guard passes and the custody guard answers, so the code is the custody one.

    PRD 2.9: "The item's `lifecycle_state` is a legal from-state for the requested
    transition, on every item action endpoint — screening, receiving, placement,
    disposition election, inventory flagging, write-off and release — plus pickup-job item
    attachment and sale creation."

    PRD 2.9: "The item's `inventory_state` is a legal from-state for the requested
    transition, on item placement, item write-off, item inventory flagging, sale creation
    and delivery-order creation. In particular a piece in `SHRINKAGE_MISSING` or
    `WRITTEN_OFF_INV` cannot be sold, placed or delivered."

    PRD 2.10: "Pieces in `WRITTEN_OFF_INV` and pieces in `RELEASED` are excluded"

    Design: Corner/state_machines/selling_a_piece_flagged_missing_is_refused_on_the_custody_dimension
    """
    world = _a_credenza_awaiting_placement()
    item_id = world["credenza"]["id"]
    zone_id = world["zone"]["id"]
    place_item(item_id, zone_id, tag_code="TAG-001")
    flag_inventory(item_id, "MISSING")
    buyer = create_buyer(display_name="Walk-in", floor_number=1)

    response = api_client.create_sale(
        sale_payload(item_id, buyer["id"], 51_000), FLOOR_OPERATOR
    )
    validate_error(response, ApiErrorId.ERR_ITEM_CUSTODY_INVALID, 409)

    stored = fetch_item(item_id)
    assert stored["lifecycle_state"] == "ON_FLOOR", (
        f"Expected the merchandising dimension still ON_FLOOR, "
        f"got {stored['lifecycle_state']}"
    )
    assert stored["inventory_state"] == "SHRINKAGE_MISSING", (
        f"Expected SHRINKAGE_MISSING, got {stored['inventory_state']}"
    )

    sales = api_client.list_sales(GALLERY_MANAGER, params={"item_id": item_id, "limit": 100})
    assert total_count(sales) == 0, (
        f"Expected no sale rung, got {total_count(sales)}"
    )

    consignor = fetch_consignor(world["consignor"]["id"])
    assert consignor["unclaimed_balance_cents"] == -17_000, (
        f"Expected only the collection debit, "
        f"got {consignor['unclaimed_balance_cents']}"
    )
    assert consignor["lifetime_credits_cents"] == 0, (
        f"Expected no credits, got {consignor['lifetime_credits_cents']}"
    )
    assert fetch_zone(zone_id)["occupied_sqft"] == 20, (
        "Expected a mislaid piece to keep occupying its footage"
    )


def test_recovering_a_merely_mislaid_piece_mints_no_ledger_entry():
    """The RECOVERED branch keyed on SHRINKAGE_MISSING touches custody and nothing else.

    PRD 3.9: "A `RECOVERED` flag on a piece in `SHRINKAGE_MISSING` simply moves it
    `SHRINKAGE_MISSING → IN_CUSTODY`"

    PRD 3.9: "no shrinkage credit was ever booked for a piece that was merely mislaid —
    and leaves `placement_zone_id` unchanged, so the zone's `occupied_sqft` does not move
    either."

    PRD 3.9: "Either flag increments the piece's `version` by 1, and a flag whose custody
    from-state does not match is refused with `ERR_ITEM_CUSTODY_INVALID`."

    Design: Corner/state_machines/recovery_from_missing_mints_no_ledger_entry_at_all
    """
    world = _a_credenza_awaiting_placement()
    item_id = world["credenza"]["id"]
    zone_id = world["zone"]["id"]
    place_item(item_id, zone_id, tag_code="TAG-001")
    missing = flag_inventory(item_id, "MISSING")

    recovered = flag_inventory(item_id, "RECOVERED")

    assert recovered["inventory_state"] == "IN_CUSTODY", (
        f"Expected IN_CUSTODY, got {recovered['inventory_state']}"
    )
    assert recovered["lifecycle_state"] == "ON_FLOOR", (
        f"Expected the merchandising dimension untouched, "
        f"got {recovered['lifecycle_state']}"
    )
    assert recovered["placement_zone_id"] == zone_id, (
        f"Expected the zone kept, got {recovered['placement_zone_id']}"
    )
    assert recovered["current_price_cents"] == 51_000, (
        f"Expected the price untouched, got {recovered['current_price_cents']}"
    )
    assert recovered["version"] == missing["version"] + 1, (
        f"Expected version {missing['version'] + 1} after the second flag, "
        f"got {recovered['version']}"
    )

    entries = fetch_consignor_ledger(world["consignor"]["id"])
    assert [e["entry_type"] for e in entries] == ["PICKUP_SURCHARGE_DEBIT"], (
        f"Expected only the collection debit, "
        f"got {[e['entry_type'] for e in entries]}"
    )
    consignor = fetch_consignor(world["consignor"]["id"])
    assert consignor["unclaimed_balance_cents"] == -17_000, (
        f"Expected -17000, got {consignor['unclaimed_balance_cents']}"
    )
    assert consignor["lifetime_credits_cents"] == 0, (
        f"Expected no credits, got {consignor['lifetime_credits_cents']}"
    )
    assert fetch_zone(zone_id)["occupied_sqft"] == 20, (
        "Expected the zone occupancy unchanged across both flags"
    )


SUITE_PARENT = {
    "title": "Dining suite",
    "category": "CASEGOOD",
    "declared_value_cents": 70_000,
    "photo_count": 6,
    "volume_cuft": 10,
    "footprint_sqft": 12,
}
SUITE_TABLE = {
    "title": "Suite table",
    "category": "DINING",
    "declared_value_cents": 40_000,
    "photo_count": 4,
    "volume_cuft": 20,
    "footprint_sqft": 15,
}
SUITE_CHAIRS = {
    "title": "Suite chairs",
    "category": "DINING",
    "declared_value_cents": 30_000,
    "photo_count": 4,
    "volume_cuft": 18,
    "footprint_sqft": 12,
}


def test_the_lot_parent_turns_ready_only_when_its_last_component_lands_in_custody():
    """One component in custody is not enough; the flag waits for the other.

    PRD 3.2: "`lot_ready` is true when the piece has no components at all — a
    `lot_component_count` of zero — and otherwise true only when every one of its
    components has reached `inventory_state` `IN_CUSTODY`; a parent with even one
    component still in `PENDING_CUSTODY` is not ready."

    PRD 3.4: "any lot parent above those pieces has its `lot_ready` recomputed, since
    custody of a component is exactly what that flag tracks"

    PRD 3.3: "collect every component whose `lifecycle_state` is not `SCREEN_REJECTED`,
    sum their `list_price_cents` values"

    PRD 3.4: "Finally the surcharge is capped at 35 hundredths of the summed
    `declared_value_cents` of every piece attached to the job, that cap being itself
    rounded half up to a whole number of cents, and the surcharge charged is the smaller
    of the two rounded integers"

    Design: Corner/state_machines/the_lot_parent_becomes_ready_only_when_its_last_component_enters_custody
    """
    world = _an_active_agreement(steps=ONE_STEP)
    consignor_id = world["consignor"]["id"]
    agreement_id = world["agreement"]["id"]

    parent = create_item(agreement_id, **SUITE_PARENT)
    table = create_item(agreement_id, parent_lot_item_id=parent["id"], **SUITE_TABLE)
    chairs = create_item(agreement_id, parent_lot_item_id=parent["id"], **SUITE_CHAIRS)
    screen_item(table["id"], scores=SCORES_GRADE_A)
    screen_item(chairs["id"], scores=SCORES_GRADE_A)
    screen_item(parent["id"], scores=SCORES_GRADE_A)

    truck = create_truck(name="BOX-1", capacity_volume_cuft=100)
    first_job = schedule_pickup(
        consignor_id,
        truck["id"],
        [parent["id"], table["id"]],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    get_success_data(
        api_client.complete_pickup_job(
            first_job["id"], complete_pickup_payload(), LOGISTICS_COORDINATOR
        )
    )
    second_job = schedule_pickup(
        consignor_id,
        truck["id"],
        [chairs["id"]],
        window_start="2026-08-01T13:00:00Z",
        window_end="2026-08-01T15:00:00Z",
    )

    waiting = fetch_item(parent["id"])
    assert waiting["lot_component_count"] == 2, (
        f"Expected two components, got {waiting['lot_component_count']}"
    )
    assert waiting["lot_ready"] is False, (
        f"Expected the parent not ready while the chairs are outstanding, "
        f"got {waiting['lot_ready']}"
    )
    assert waiting["inventory_state"] == "IN_CUSTODY", (
        f"Expected the parent itself already collected, "
        f"got {waiting['inventory_state']}"
    )
    assert fetch_item(chairs["id"])["inventory_state"] == "PENDING_CUSTODY", (
        "Expected the chairs still outside the building"
    )

    response = api_client.complete_pickup_job(
        second_job["id"], complete_pickup_payload(), LOGISTICS_COORDINATOR
    )
    assert response.status_code == 200, (
        f"Expected 200 on the second completion, got {response.status_code}"
    )
    completed = get_success_data(response)
    assert completed["final_surcharge_cents"] == 10_500, (
        f"Expected 17000 clamped to the 10500 cap on 30000 of declared value, "
        f"got {completed['final_surcharge_cents']}"
    )

    ready = fetch_item(parent["id"])
    assert ready["lot_ready"] is True, (
        f"Expected the parent ready once both components are in, "
        f"got {ready['lot_ready']}"
    )
    assert ready["list_price_cents"] == 56_228, (
        f"Expected round_half_up((35700 + 26775) * 0.90) = 56228, "
        f"got {ready['list_price_cents']}"
    )

    landed = fetch_item(chairs["id"])
    assert landed["inventory_state"] == "IN_CUSTODY", (
        f"Expected IN_CUSTODY, got {landed['inventory_state']}"
    )
    assert landed["lifecycle_state"] == "RECEIVED", (
        f"Expected RECEIVED, got {landed['lifecycle_state']}"
    )

    entries = fetch_consignor_ledger(consignor_id)
    assert [e["amount_cents"] for e in entries] == [-19_500, -10_500], (
        f"Expected the two collection debits, "
        f"got {[e['amount_cents'] for e in entries]}"
    )
    consignor = fetch_consignor(consignor_id)
    assert consignor["unclaimed_balance_cents"] == -30_000, (
        f"Expected -30000, got {consignor['unclaimed_balance_cents']}"
    )
    assert consignor["status"] == "ACTIVE", (
        f"Expected ACTIVE because the suspension floor is -50000, "
        f"got {consignor['status']}"
    )
