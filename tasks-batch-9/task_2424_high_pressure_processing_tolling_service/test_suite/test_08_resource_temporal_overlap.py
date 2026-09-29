"""Two scarce resources are booked over time, with different interval semantics.

A vessel's occupancy is a half-open window compared pairwise with strict
inequalities, so windows that merely touch never collide, and a cross-group
neighbour additionally demands a sanitation gap that passes on equality.  A cold
room's occupancy is a closed interval counted N-way against capacity, and the
reservations expire on their own once the clock passes their `ship_by`.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    commission_vessel,
    create_lot_payload,
    create_vessel_cycle_payload,
    define_cold_room,
    define_family,
    list_cycles,
    read_cold_room,
    read_lot,
    receive_pallet,
    register_customer,
    qualify_recipe,
    schedule_cycle,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CLOCK_AUG03, OPERATOR, SCHEDULER


# --------------------------------------------------------------------------- #
# the vessel's half-open window and its cleanout buffer
# --------------------------------------------------------------------------- #
def _one_machine_two_families() -> dict:
    """HPP-1 with an RTE_PRODUCE family and a RAW_PROTEIN family, and one
    incumbent 472-second cycle occupying 09:00:00Z through 09:07:52Z."""
    set_clock(CLOCK_AUG03)
    family = define_family()
    raw_family = define_family(
        family_code="RAW_MEAT",
        cross_contamination_group="RAW_PROTEIN",
        cleanout_minutes=60,
        max_receipt_temp_c=2.0,
        max_outbound_temp_c=2.0,
        requires_dedicated_cycle=True,
    )
    vessel = commission_vessel()
    incumbent = schedule_cycle(vessel["id"], family["id"])
    return {
        "family": family,
        "raw_family": raw_family,
        "vessel": vessel,
        "incumbent": incumbent,
    }


def test_a_same_family_cycle_starting_exactly_at_the_incumbents_end_is_accepted():
    """The incumbent occupies up to but not including 09:07:52Z, so a candidate
    starting on that instant merely touches it.

    PRD 3.5: "The candidate's window is **half-open** — it runs from `scheduled_start`
    up to but not including `scheduled_end` — and the occupants it is compared against
    are the cycles on the same vessel whose `state` is `SCHEDULED`, `LOADED`,
    `RUNNING`, `COMPLETED_CLEAN`, `COMPLETED_DEVIATED` or `DISPOSITIONED`."
    PRD 3.5: "Because both comparisons are strict, windows that merely touch at an
    endpoint do not collide."

    Design: Difficulty/resource_temporal_overlap/vessel_half_open_windows_and_cleanout_buffer
    """
    world = _one_machine_two_families()
    assert world["incumbent"]["estimated_cycle_seconds"] == 472
    assert_instant_equals(world["incumbent"]["scheduled_end"], "2026-08-05T09:07:52Z")

    neighbour = schedule_cycle(
        world["vessel"]["id"],
        world["family"]["id"],
        scheduled_start="2026-08-05T09:07:52Z",
    )

    assert_instant_equals(neighbour["scheduled_end"], "2026-08-05T09:15:44Z")


def test_one_second_earlier_than_that_endpoint_is_a_window_conflict():
    """Starting at 09:07:51Z puts the candidate strictly inside the incumbent's
    window, which is the collision the strict comparisons are there to catch.

    PRD 3.5: "Two windows collide when the candidate's start is strictly earlier than
    the occupant's `scheduled_end` and the occupant's `scheduled_start` is strictly
    earlier than the candidate's end; a collision is refused with
    `ERR_VESSEL_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/vessel_half_open_windows_and_cleanout_buffer
    """
    world = _one_machine_two_families()

    response = api_client.create_vessel_cycle(
        create_vessel_cycle_payload(
            world["vessel"]["id"],
            world["family"]["id"],
            scheduled_start="2026-08-05T09:07:51Z",
        ),
        SCHEDULER,
    )

    validate_error(response, ApiErrorId.ERR_VESSEL_WINDOW_CONFLICT.value, 409)


def test_a_cross_group_neighbour_one_second_short_of_the_gap_is_refused():
    """After a second RTE_PRODUCE cycle ends at 09:15:44Z, a RAW_PROTEIN run needs
    the greater of the two cleanout figures — 3600 seconds — and 3599 will not do.

    PRD 3.5: "For each side that exists, if that neighbour's family belongs to a
    different `cross_contamination_group` than the candidate's family, a cleanout gap
    is required, equal to the greater of the two families' `cleanout_minutes` values
    converted to seconds by multiplying by 60."
    PRD 3.5: "A gap shorter than the requirement is refused with
    `ERR_CLEANOUT_GAP_REQUIRED` (HTTP 409); a gap exactly equal to the requirement
    passes."

    Design: Difficulty/resource_temporal_overlap/vessel_half_open_windows_and_cleanout_buffer
    """
    world = _one_machine_two_families()
    schedule_cycle(
        world["vessel"]["id"],
        world["family"]["id"],
        scheduled_start="2026-08-05T09:07:52Z",
    )

    response = api_client.create_vessel_cycle(
        create_vessel_cycle_payload(
            world["vessel"]["id"],
            world["raw_family"]["id"],
            scheduled_start="2026-08-05T10:15:43Z",
        ),
        SCHEDULER,
    )

    validate_error(response, ApiErrorId.ERR_CLEANOUT_GAP_REQUIRED.value, 409)


def test_the_cross_group_neighbour_is_accepted_at_exactly_the_required_gap():
    """One second later the gap is exactly 3600 seconds, which passes, and the
    machine ends up carrying exactly three cycles.

    PRD 3.5: "The actual gap is the whole number of seconds between the earlier
    window's end and the later window's start."
    PRD 3.5: "Cycles are read back with both fee variants and their utilisation
    visible, and can be listed and filtered by `vessel_id`, by `product_family_id`,
    by `state`, and by scheduling window through `scheduled_from` and `scheduled_to`."

    Design: Difficulty/resource_temporal_overlap/vessel_half_open_windows_and_cleanout_buffer
    """
    world = _one_machine_two_families()
    schedule_cycle(
        world["vessel"]["id"],
        world["family"]["id"],
        scheduled_start="2026-08-05T09:07:52Z",
    )

    accepted = schedule_cycle(
        world["vessel"]["id"],
        world["raw_family"]["id"],
        scheduled_start="2026-08-05T10:15:44Z",
    )

    assert_instant_equals(accepted["scheduled_end"], "2026-08-05T10:23:36Z")
    assert len(list_cycles(vessel_id=world["vessel"]["id"])) == 3


# --------------------------------------------------------------------------- #
# the cold room's closed interval and declared occupancy
# --------------------------------------------------------------------------- #
def _room_with_two_uninspected_reservations() -> dict:
    """Two pallets standing at the dock, both declared through 2026-08-10."""
    set_clock(CLOCK_AUG03)
    customer = register_customer()
    family = define_family()
    room = define_cold_room(capacity_pallets=2)
    qualification = qualify_recipe(customer["id"], family["id"])
    set_clock("2026-08-05T08:00:00Z")
    first = receive_pallet(
        customer["id"],
        qualification["id"],
        room["id"],
        pallet_ref="PAL-201",
        unit_count=500,
        gross_weight_kg=330.0,
        ship_by="2026-08-10T00:00:00Z",
    )
    second = receive_pallet(
        customer["id"],
        qualification["id"],
        room["id"],
        pallet_ref="PAL-202",
        unit_count=500,
        gross_weight_kg=330.0,
        ship_by="2026-08-10T00:00:00Z",
    )
    return {
        "customer": customer,
        "qualification": qualification,
        "room": room,
        "first": first,
        "second": second,
    }


def _third_pallet_payload(world: dict) -> dict:
    return create_lot_payload(
        world["customer"]["id"],
        world["qualification"]["id"],
        world["room"]["id"],
        pallet_ref="PAL-203",
        unit_count=500,
        gross_weight_kg=330.0,
        ship_by="2026-08-20T00:00:00Z",
    )


def test_a_third_reservation_over_the_same_days_exceeds_the_rooms_capacity():
    """Both incumbents are still only AT_DOCK, yet they count: sampled at the
    candidate's own start instant, occupancy would reach three in a two-position room.

    PRD 3.4: "The population it is measured against is every pallet already assigned
    to that room whose `custody_state` is `AT_DOCK`, `IN_COLD_STORAGE`, `IN_VESSEL` or
    `TREATED` — declared occupancy, so a pallet still standing at the dock counts,
    while pallets that are `SHIPPED`, `REJECTED_AT_DOCK` or `DISPOSED` never count."
    PRD 3.4: "If occupancy at any of those instants exceeds the room's
    `capacity_pallets`, the receipt is refused with `ERR_COLD_ROOM_CAPACITY_EXCEEDED`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/cold_room_closed_interval_declared_occupancy
    """
    world = _room_with_two_uninspected_reservations()

    response = api_client.create_lot(_third_pallet_payload(world), OPERATOR)

    validate_error(response, ApiErrorId.ERR_COLD_ROOM_CAPACITY_EXCEEDED.value, 409)


def test_the_interval_refusal_is_not_the_point_in_time_posture_refusal():
    """The room's own derived posture is still NORMAL with zero occupants, so the
    409 the client sees can only have come from the interval calculation.

    PRD 3.4: "The room's derived posture must be `NORMAL` at this instant; a room
    already at `AT_CAPACITY` refuses further receipts with `ERR_COLD_ROOM_AT_CAPACITY`
    (HTTP 409)."
    PRD 3.1: "The room's `capacity_state` is a derived posture with exactly two values
    — it is `AT_CAPACITY` whenever `occupied_pallets` is greater than or equal to
    `capacity_pallets`, and `NORMAL` otherwise — and it is recomputed after every
    request that changes the room's occupancy."

    Design: Difficulty/resource_temporal_overlap/cold_room_closed_interval_declared_occupancy
    """
    world = _room_with_two_uninspected_reservations()

    response = api_client.create_lot(_third_pallet_payload(world), OPERATOR)
    room = read_cold_room(world["room"]["id"])

    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_COLD_ROOM_AT_CAPACITY.value
    )
    assert room["occupied_pallets"] == 0
    assert room["capacity_state"] == "NORMAL"


def test_once_the_clock_passes_their_ship_by_the_identical_payload_is_accepted():
    """The incumbents' intervals close on 2026-08-10, so a candidate starting on
    2026-08-12 no longer overlaps them and the byte-identical request succeeds.

    PRD 3.4: "The candidate interval runs from the logical clock's current instant
    through the pallet's `ship_by`, inclusive at both ends."
    PRD 3.4: "At each of those instants, taken in ascending order, occupancy is the
    number of population pallets whose `created_at` is at or before that instant and
    whose `ship_by` is at or after it, plus one for the candidate itself."

    Design: Difficulty/resource_temporal_overlap/cold_room_closed_interval_declared_occupancy
    """
    world = _room_with_two_uninspected_reservations()
    payload = _third_pallet_payload(world)
    validate_error(
        api_client.create_lot(payload, OPERATOR),
        ApiErrorId.ERR_COLD_ROOM_CAPACITY_EXCEEDED.value,
        409,
    )

    set_clock("2026-08-12T08:00:00Z")
    accepted = validate_success(api_client.create_lot(payload, OPERATOR), 201)

    assert accepted["pallet_ref"] == "PAL-203"
    assert read_lot(accepted["id"])["custody_state"] == "AT_DOCK"
    assert read_lot(world["first"]["id"])["custody_state"] == "AT_DOCK"
    assert read_lot(world["second"]["id"])["custody_state"] == "AT_DOCK"
    assert read_cold_room(world["room"]["id"])["occupied_pallets"] == 0
