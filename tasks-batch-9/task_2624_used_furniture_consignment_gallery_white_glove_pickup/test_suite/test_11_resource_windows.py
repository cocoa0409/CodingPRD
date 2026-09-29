"""Trucks keep a buffered closed window; crews keep two half-open ones."""

from test_helpers import (
    LOGISTICS_COORDINATOR,
    SCORES_GRADE_A,
    SCORES_GRADE_B,
    STD_SCHEDULE_STEPS,
    ApiErrorId,
    api_client,
    create_buyer,
    create_crew,
    create_item,
    create_truck,
    create_zone,
    delivery_order_payload,
    fetch_consignor,
    fetch_consignor_ledger,
    fetch_delivery_order,
    fetch_item,
    fetch_pickup_job,
    fetch_sale,
    fetch_zone,
    get_success_data,
    pickup_job_payload,
    place_item,
    receive_item,
    schedule_delivery,
    schedule_pickup,
    screen_item,
    sell_item,
    setup_consignor_with_active_agreement,
    take_custody,
    total_count,
    validate_error,
)

TWO_STEP_SCHEDULE = STD_SCHEDULE_STEPS[:2]

TUFTED_SOFA = {
    "title": "Tufted sofa",
    "category": "SOFA",
    "declared_value_cents": 189_950,
    "photo_count": 5,
    "volume_cuft": 55,
    "footprint_sqft": 24,
}
CREDENZA = {
    "title": "Ash credenza",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 20,
    "footprint_sqft": 18,
}
PINE_CHEST = {
    "title": "Pine chest",
    "category": "CASEGOOD",
    "declared_value_cents": 20_000,
    "photo_count": 3,
    "volume_cuft": 13,
    "footprint_sqft": 12,
}


def _one_truck_already_booked_from_nine_until_eleven():
    """Three screened pieces and a single truck holding one morning window."""
    world = setup_consignor_with_active_agreement(
        schedule_steps=TWO_STEP_SCHEDULE,
        consignor_overrides={"payout_method": "ACH"},
    )
    agreement_id = world["agreement"]["id"]

    world["sofa"] = create_item(agreement_id, **TUFTED_SOFA)
    world["credenza"] = create_item(agreement_id, **CREDENZA)
    world["chest"] = create_item(agreement_id, **PINE_CHEST)
    screen_item(world["sofa"]["id"], scores=SCORES_GRADE_B)
    screen_item(world["credenza"]["id"], scores=SCORES_GRADE_A)
    screen_item(world["chest"]["id"], scores=SCORES_GRADE_A)

    world["truck"] = create_truck(name="Truck 1")
    world["job_a"] = schedule_pickup(
        world["consignor"]["id"],
        world["truck"]["id"],
        [world["sofa"]["id"]],
        window_start="2026-08-05T09:00:00Z",
        window_end="2026-08-05T11:00:00Z",
    )
    return world


def _reserve(world, item_id, window_start, window_end):
    return api_client.create_pickup_job(
        pickup_job_payload(
            world["consignor"]["id"],
            world["truck"]["id"],
            window_start,
            window_end,
            item_ids=[item_id],
        ),
        LOGISTICS_COORDINATOR,
    )


def test_a_truck_window_reopens_forty_five_minutes_after_the_previous_one_closes():
    """Eleven forty-four is still inside the turnaround; eleven forty-five is not.

    PRD 3.4: "The request is refused with `ERR_TRUCK_WINDOW_CONFLICT` exactly when both
    of the following hold against some other job: the requested start is earlier than
    that job's end advanced by 45 minutes,"

    PRD 3.4: "A window that begins exactly 45 minutes after another job ends therefore
    clears, while one that begins 44 minutes after does not."

    Design: Difficulty/resource_temporal_overlap/truck_windows_are_closed_intervals_plus_a_forty_five_minute_turnaround
    """
    world = _one_truck_already_booked_from_nine_until_eleven()
    credenza_id = world["credenza"]["id"]

    refused = _reserve(
        world, credenza_id, "2026-08-05T11:44:00Z", "2026-08-05T12:44:00Z"
    )
    validate_error(refused, ApiErrorId.ERR_TRUCK_WINDOW_CONFLICT, 409)

    listed = api_client.list_pickup_jobs(
        LOGISTICS_COORDINATOR, params={"truck_id": world["truck"]["id"], "limit": 100}
    )
    assert total_count(listed) == 1, (
        f"Expected the refused reservation to create nothing, "
        f"got {total_count(listed)} jobs"
    )

    credenza = fetch_item(credenza_id)
    assert credenza["pickup_job_id"] is None, (
        f"Expected the piece unattached, got {credenza['pickup_job_id']}"
    )
    assert credenza["lifecycle_state"] == "SCREEN_ACCEPTED", (
        f"Expected SCREEN_ACCEPTED, got {credenza['lifecycle_state']}"
    )

    job_a = fetch_pickup_job(world["job_a"]["id"])
    assert job_a["status"] == "SCHEDULED", (
        f"Expected the standing job untouched, got {job_a['status']}"
    )
    assert job_a["quoted_surcharge_cents"] == 27_000, (
        f"Expected 12000 plus six volume blocks, "
        f"got {job_a['quoted_surcharge_cents']}"
    )

    accepted = get_success_data(
        _reserve(world, credenza_id, "2026-08-05T11:45:00Z", "2026-08-05T12:45:00Z")
    )
    assert accepted["quoted_surcharge_cents"] == 17_000, (
        f"Expected 12000 plus two volume blocks, "
        f"got {accepted['quoted_surcharge_cents']}"
    )
    credenza = fetch_item(credenza_id)
    assert credenza["lifecycle_state"] == "SCHEDULED_PICKUP", (
        f"Expected the piece booked onto the truck, "
        f"got {credenza['lifecycle_state']}"
    )


def test_the_buffer_guards_the_leading_edge_too_and_a_cancellation_releases_it():
    """A window ending 44 minutes before the standing job is refused; 45 clears it.

    PRD 3.4: "so the requested window is compared against every other non-terminal job
    already reserved on the same truck"

    PRD 3.4: "that job's start is earlier than the requested end advanced by 45
    minutes"

    PRD 3.4: "the truck window stops blocking overlap checks for future reservations"

    Design: Difficulty/resource_temporal_overlap/truck_windows_are_closed_intervals_plus_a_forty_five_minute_turnaround
    """
    world = _one_truck_already_booked_from_nine_until_eleven()
    chest_id = world["chest"]["id"]

    refused = _reserve(world, chest_id, "2026-08-05T07:00:00Z", "2026-08-05T08:16:00Z")
    validate_error(refused, ApiErrorId.ERR_TRUCK_WINDOW_CONFLICT, 409)

    accepted = get_success_data(
        _reserve(world, chest_id, "2026-08-05T07:00:00Z", "2026-08-05T08:15:00Z")
    )
    assert accepted["status"] == "SCHEDULED", (
        f"Expected the earlier window to clear, got {accepted['status']}"
    )

    get_success_data(
        api_client.cancel_pickup_job(world["job_a"]["id"], LOGISTICS_COORDINATOR)
    )
    after_cancel = get_success_data(
        api_client.create_pickup_job(
            pickup_job_payload(
                world["consignor"]["id"],
                world["truck"]["id"],
                "2026-08-05T09:30:00Z",
                "2026-08-05T10:30:00Z",
            ),
            LOGISTICS_COORDINATOR,
        )
    )
    assert after_cancel["status"] == "SCHEDULED", (
        f"Expected the released window to be bookable, "
        f"got {after_cancel['status']}"
    )

    consignor = fetch_consignor(world["consignor"]["id"])
    assert consignor["unclaimed_balance_cents"] == 0, (
        f"Expected no money to move while nothing has been collected, "
        f"got {consignor['unclaimed_balance_cents']}"
    )
    entries = fetch_consignor_ledger(world["consignor"]["id"])
    assert entries == [], (
        f"Expected an empty ledger, got {[e['entry_type'] for e in entries]}"
    )


TRACK_ARM_SOFA = {
    "title": "Track-arm sofa",
    "category": "SOFA",
    "declared_value_cents": 189_950,
    "photo_count": 5,
    "volume_cuft": 65,
    "footprint_sqft": 24,
}
BUFFET = {
    "title": "Elm buffet",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 20,
    "footprint_sqft": 18,
}
BEDSIDE = {
    "title": "Birch bedside",
    "category": "CASEGOOD",
    "declared_value_cents": 20_000,
    "photo_count": 3,
    "volume_cuft": 13,
    "footprint_sqft": 12,
}


def _one_crew_holding_two_overlapping_afternoons():
    """Three sold pieces, one crew, two orders already overlapping at capacity."""
    world = setup_consignor_with_active_agreement(
        schedule_steps=TWO_STEP_SCHEDULE,
        consignor_overrides={"payout_method": "ACH"},
    )
    agreement_id = world["agreement"]["id"]

    sofa = create_item(agreement_id, **TRACK_ARM_SOFA)
    buffet = create_item(agreement_id, **BUFFET)
    bedside = create_item(agreement_id, **BEDSIDE)
    screen_item(sofa["id"], scores=SCORES_GRADE_B)
    screen_item(buffet["id"], scores=SCORES_GRADE_A)
    screen_item(bedside["id"], scores=SCORES_GRADE_A)

    take_custody(
        world["consignor"]["id"],
        [sofa["id"], buffet["id"], bedside["id"]],
        window_start="2026-08-01T07:00:00Z",
        window_end="2026-08-01T10:00:00Z",
    )
    receive_item(sofa["id"], scores=SCORES_GRADE_B)
    receive_item(buffet["id"], scores=SCORES_GRADE_A)
    receive_item(bedside["id"], scores=SCORES_GRADE_A)

    world["zone"] = create_zone(
        name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200
    )
    zone_id = world["zone"]["id"]
    place_item(sofa["id"], zone_id, tag_code="T-1301")
    place_item(buffet["id"], zone_id, tag_code="T-1302")
    place_item(bedside["id"], zone_id, tag_code="T-1303")

    world["buyer"] = create_buyer(floor_number=2, has_elevator=False)
    buyer_id = world["buyer"]["id"]
    world["sofa_sale"] = sell_item(sofa["id"], buyer_id, 126_317)
    world["buffet_sale"] = sell_item(buffet["id"], buyer_id, 51_000)
    world["bedside_sale"] = sell_item(bedside["id"], buyer_id, 17_000)

    world["crew"] = create_crew(name="Crew 1", max_concurrent_jobs=2)
    world["order_one"] = schedule_delivery(
        world["sofa_sale"]["id"],
        world["crew"]["id"],
        window_start="2026-08-03T13:00:00Z",
        window_end="2026-08-03T15:00:00Z",
    )
    world["order_two"] = schedule_delivery(
        world["buffet_sale"]["id"],
        world["crew"]["id"],
        window_start="2026-08-03T14:00:00Z",
        window_end="2026-08-03T16:00:00Z",
    )
    return world


def test_the_third_overlapping_delivery_exceeds_a_ceiling_of_two_not_one():
    """Two overlapping afternoons are legal; the third one is refused.

    PRD 3.8: "count the crew's non-terminal orders whose half-open windows contain any
    instant of the requested window, and if adding this order would push that count
    above the crew's `max_concurrent_jobs`, the request is refused with
    `ERR_CREW_CAPACITY_EXCEEDED`"

    PRD 3.8: "Add an assembly charge of 4,000 cents when the sold piece's `category` is
    `DINING` or `CASEGOOD`, and nothing otherwise"

    Design: Difficulty/resource_temporal_overlap/crew_windows_are_half_open_and_capacity_two_rather_than_one
    """
    world = _one_crew_holding_two_overlapping_afternoons()

    refused = api_client.create_delivery_order(
        delivery_order_payload(
            world["bedside_sale"]["id"],
            world["crew"]["id"],
            "2026-08-03T14:30:00Z",
            "2026-08-03T15:30:00Z",
        ),
        LOGISTICS_COORDINATOR,
    )
    validate_error(refused, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED, 409)

    order_two = fetch_delivery_order(world["order_two"]["id"])
    assert order_two["status"] == "SCHEDULED", (
        f"Expected the second overlapping order to stand, got {order_two['status']}"
    )

    order_one = fetch_delivery_order(world["order_one"]["id"])
    assert order_one["delivery_fee_cents"] == 12_000, (
        f"Expected 7500 plus one flight for the sofa, "
        f"got {order_one['delivery_fee_cents']}"
    )
    assert order_two["delivery_fee_cents"] == 16_000, (
        f"Expected a further 4000 of assembly for the buffet, "
        f"got {order_two['delivery_fee_cents']}"
    )

    listed = api_client.list_delivery_orders(
        LOGISTICS_COORDINATOR, params={"crew_id": world["crew"]["id"], "limit": 100}
    )
    assert total_count(listed) == 2, (
        f"Expected the refused order to create nothing, got {total_count(listed)}"
    )
    sale = fetch_sale(world["bedside_sale"]["id"])
    assert sale["status"] == "COMPLETED", (
        f"Expected the undelivered sale still COMPLETED, got {sale['status']}"
    )


def test_a_window_beginning_when_another_ends_does_not_overlap_it():
    """Half-open windows touch without conflicting, so the retry at three o'clock lands.

    PRD 3.8: "`window_start` is inclusive and `window_end` is exclusive, which is why
    two orders that merely touch at an instant do not conflict"

    PRD 3.8: "`stair_flights` is the buyer's `floor_number` reduced by 1 but never
    below zero"

    Design: Difficulty/resource_temporal_overlap/crew_windows_are_half_open_and_capacity_two_rather_than_one
    """
    world = _one_crew_holding_two_overlapping_afternoons()

    accepted = schedule_delivery(
        world["bedside_sale"]["id"],
        world["crew"]["id"],
        window_start="2026-08-03T15:00:00Z",
        window_end="2026-08-03T17:00:00Z",
    )
    assert accepted["status"] == "SCHEDULED", (
        f"Expected the touching window to clear, got {accepted['status']}"
    )
    assert accepted["delivery_fee_cents"] == 16_000, (
        f"Expected 7500 plus 4500 of stairs plus 4000 of assembly, "
        f"got {accepted['delivery_fee_cents']}"
    )
    assert accepted["stair_flights"] == 1, (
        f"Expected one flight snapshotted from the buyer, "
        f"got {accepted['stair_flights']}"
    )

    entries = fetch_consignor_ledger(world["consignor"]["id"])
    assert [e["amount_cents"] for e in entries] == [
        -42_500,
        69_474,
        30_600,
        9_350,
    ], f"Expected scheduling to book nothing, got {[e['amount_cents'] for e in entries]}"
    consignor = fetch_consignor(world["consignor"]["id"])
    assert consignor["unclaimed_balance_cents"] == 66_924, (
        f"Expected 66924, got {consignor['unclaimed_balance_cents']}"
    )

    zone = fetch_zone(world["zone"]["id"])
    assert zone["occupied_sqft"] == 54, (
        f"Expected all three sold pieces still holding their footage, "
        f"got {zone['occupied_sqft']}"
    )
