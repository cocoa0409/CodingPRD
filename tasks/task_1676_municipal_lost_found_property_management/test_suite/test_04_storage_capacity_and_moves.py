"""Storage occupancy accounting, capacity, moves, and location state (PRD §2.9, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    confirm_pickup,
    create_item,
    create_item_payload,
    create_location,
    get_item,
    get_location,
    make_intake_officer_headers,
    make_property_custodian_headers,
    refer_item,
    setup_program_policy_location,
    setup_stored_item,
    validate_error,
    validate_success,
)

CUSTODIAN = make_property_custodian_headers("custodian-1")


def test_move_to_inactive_location_rejected(api, program_admin_headers):
    """PRD §3.1: "an inactive location cannot receive items, so intake or moves
    targeting one are rejected with `ERR_LOCATION_INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/item_move_blocked_by_inactive_location
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    cage_b = create_location(ctx.program["id"], name="Cage B", capacity_slots=5)
    validate_success(
        api.deactivate_storage_location(cage_b["id"], program_admin_headers), 200)

    res = api.move_item(ctx.item["id"], cage_b["id"], CUSTODIAN)
    validate_error(res, ApiErrorId.ERR_LOCATION_INACTIVE, expected_status=409)
    assert get_item(ctx.item["id"])["storage_location_id"] == ctx.location["id"], (
        "a rejected move leaves the item at its source location")


def test_intake_into_inactive_location_rejected(api, program_admin_headers):
    """PRD §3.1: "an inactive location cannot receive items, so intake or moves
    targeting one are rejected with `ERR_LOCATION_INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/item_move_blocked_by_inactive_location
    """
    ctx = setup_program_policy_location()
    cage_b = create_location(ctx.program["id"], name="Cage B", capacity_slots=5)
    validate_success(
        api.deactivate_storage_location(cage_b["id"], program_admin_headers), 200)

    res = api.create_item(
        create_item_payload(ctx.program["id"], cage_b["id"]),
        make_intake_officer_headers("officer-intake-1"))
    validate_error(res, ApiErrorId.ERR_LOCATION_INACTIVE, expected_status=409)


def test_intake_at_full_capacity_rejected(api, intake_officer_headers):
    """PRD §2.9: "a location whose occupied count already equals its capacity
    rejects further intake or moves with `ERR_STORAGE_CAPACITY_EXCEEDED`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/storage_aggregate_capacity_semantics
    """
    ctx = setup_program_policy_location(capacity_slots=2)
    create_item(ctx.program["id"], ctx.location["id"], description="item A")
    create_item(ctx.program["id"], ctx.location["id"], description="item B")
    assert get_location(ctx.location["id"])["occupied_slots"] == 2

    res = api.create_item(
        create_item_payload(ctx.program["id"], ctx.location["id"],
                            description="item C"),
        intake_officer_headers)
    validate_error(res, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED, expected_status=409)
    assert get_location(ctx.location["id"])["occupied_slots"] == 2


def test_capacity_frees_on_le_pickup_then_reintake_succeeds(api, intake_officer_headers):
    """PRD §2.9: "An item in `IN_LE_CUSTODY` does not occupy a slot" and "the
    count ... is recomputed whenever an item's status transition enters or
    leaves the occupying set — so a pickup confirmation for law enforcement
    frees a slot".

    Design: Difficulty/resource_temporal_overlap/storage_aggregate_capacity_semantics
    """
    ctx = setup_program_policy_location(capacity_slots=2)
    item_a = create_item(ctx.program["id"], ctx.location["id"], description="item A")
    create_item(ctx.program["id"], ctx.location["id"], description="item B")

    full_res = api.create_item(
        create_item_payload(ctx.program["id"], ctx.location["id"],
                            description="item C"),
        intake_officer_headers)
    validate_error(full_res, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED, expected_status=409)

    # Item A leaves the occupying set: REFERRED_TO_LE still occupies, but
    # IN_LE_CUSTODY frees the slot (PRD §2.9).
    referral = refer_item(item_a["id"])
    confirm_pickup(referral["id"])
    assert get_location(ctx.location["id"])["occupied_slots"] == 1, (
        "confirm-pickup moves the item to IN_LE_CUSTODY, freeing its slot")

    item_c = validate_success(api.create_item(
        create_item_payload(ctx.program["id"], ctx.location["id"],
                            description="item C"),
        intake_officer_headers), 201)
    assert item_c["status"] == "STORED"
    assert get_location(ctx.location["id"])["occupied_slots"] == 2


def test_move_conserves_total_occupancy(api):
    """PRD §2.9: "The count starts at zero and is recomputed whenever an item is
    created at the location, whenever an item is moved, and whenever an item's
    status transition enters or leaves the occupying set".

    Design: Difficulty/compensating_invariant/move_round_trip_conserves_total_occupancy
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    cage_b = create_location(ctx.program["id"], name="Cage B")
    assert get_location(ctx.location["id"])["occupied_slots"] == 1
    assert get_location(cage_b["id"])["occupied_slots"] == 0

    moved = validate_success(api.move_item(ctx.item["id"], cage_b["id"], CUSTODIAN), 200)
    assert moved["storage_location_id"] == cage_b["id"]
    occ_a = get_location(ctx.location["id"])["occupied_slots"]
    occ_b = get_location(cage_b["id"])["occupied_slots"]
    assert (occ_a, occ_b) == (0, 1), (
        f"after the forward move the slot moves with the item, got A={occ_a} B={occ_b}")
    assert occ_a + occ_b == 1, "total occupied slot count is conserved"


def test_move_round_trip_restores_original_counts(api):
    """PRD §2.9: "The count starts at zero and is recomputed whenever an item is
    created at the location, whenever an item is moved, and whenever an item's
    status transition enters or leaves the occupying set".

    Design: Difficulty/compensating_invariant/move_round_trip_conserves_total_occupancy
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    cage_b = create_location(ctx.program["id"], name="Cage B")

    validate_success(api.move_item(ctx.item["id"], cage_b["id"], CUSTODIAN), 200)
    validate_success(api.move_item(ctx.item["id"], ctx.location["id"], CUSTODIAN), 200)

    occ_a = get_location(ctx.location["id"])["occupied_slots"]
    occ_b = get_location(cage_b["id"])["occupied_slots"]
    assert (occ_a, occ_b) == (1, 0), (
        f"the compensating move restores the exact original counts, got A={occ_a} B={occ_b}")
    assert occ_a + occ_b == 1, "total occupied slot count is conserved at every step"
    assert get_item(ctx.item["id"])["storage_location_id"] == ctx.location["id"]
