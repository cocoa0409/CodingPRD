"""Cascades and conservation: block-release multi-level cascade, case-cancel
compensation, and the block-minute / supply-reservation conservation invariants.

Difficulty queue: transitive_cascade (block release depth-3, case cancel depth-2);
                  compensating_invariant (book-then-cancel minutes, attach-then-release supply).
Corner queue: cross_cutting_complexity_layers / complete_recomputes_supply_on_hand_derived_field.
"""
from test_helpers import validate_success, get_success_data, fixtures
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

SCHED = TEST_USERS["scheduler_headers"]
ORMGR = TEST_USERS["or_manager_headers"]


# ===========================================================================
# Difficulty / transitive_cascade / block_release_cascades_to_case_implant_supply_depth3
# ===========================================================================
def test_block_release_cascade_force_cancels_case_and_frees_supply():
    """PRD §3.4: "At the first level, every non-cancelled case in the block whose
    `case_status` is `SCHEDULED` is force-cancelled to `CANCELLED`, processed in ascending
    order of `start_min` and then `created_at`."
    PRD §3.4: "At the second level, each such forced cancellation releases that case's
    `RESERVED` implants (each moving to `RELEASED` and decrementing its supply item's
    `reserved_qty` by the implant's `planned_qty`) and subtracts the cancelled case's
    `scheduled_minutes` from the block's `committed_minutes`, after which the owning day's
    `booked_minutes` and `utilization_pct` are recomputed."

    Confirmed block with one SCHEDULED case carrying a RESERVED implant (planned_qty 3,
    item reserved_qty 3). Releasing the block force-cancels the case, releases the implant,
    and returns reserved_qty and committed_minutes to 0.

    Design: Difficulty/transitive_cascade/block_release_cascades_to_case_implant_supply_depth3
    """
    world, block = fixtures.setup_world_with_block(start_min=480, end_min=600)
    fac = world["facility"]
    item = fixtures.create_supply_item(fac["id"], sku="DEV1", description="Implant",
                                       unit_cost_cents=5000, is_device=True, on_hand_qty=5)
    case = fixtures.book_case(block["id"], block["version"], world["patient"]["id"],
                              world["procedure"]["id"], 480)
    imp = fixtures.attach_implant(case["id"], item["id"], 3)
    get_success_data(api_client.confirm_block(block["id"], SCHED))
    get_success_data(api_client.release_block(block["id"], SCHED))

    case_after = get_success_data(api_client.get_surgical_case(case["id"], SCHED))
    imp_after = get_success_data(api_client.get_case_implant(imp["id"], ORMGR))
    item_after = get_success_data(api_client.get_supply_item(item["id"], ORMGR))
    block_after = get_success_data(api_client.get_surgeon_block(block["id"], SCHED))

    assert case_after["case_status"] == "CANCELLED", case_after["case_status"]
    assert imp_after["status"] == "RELEASED", imp_after["status"]
    assert item_after["reserved_qty"] == 0, item_after["reserved_qty"]
    assert block_after["committed_minutes"] == 0, block_after["committed_minutes"]


def test_block_release_cascade_restores_on_hand_qty():
    """PRD §3.2: "Reserving stock does not reduce `on_hand_qty` — only consuming it at case
    completion does."
    PRD §3.4: "At the second level, each such forced cancellation releases that case's
    `RESERVED` implants (each moving to `RELEASED` and decrementing its supply item's
    `reserved_qty` by the implant's `planned_qty`)..."

    Because the implant was only RESERVED (never consumed), the cascade release leaves
    on_hand_qty untouched at its opening value (5) while reserved_qty returns to 0.

    Design: Difficulty/transitive_cascade/block_release_cascades_to_case_implant_supply_depth3
    """
    world, block = fixtures.setup_world_with_block(start_min=480, end_min=600)
    fac = world["facility"]
    item = fixtures.create_supply_item(fac["id"], sku="DEV1", description="Implant",
                                       unit_cost_cents=5000, is_device=True, on_hand_qty=5)
    case = fixtures.book_case(block["id"], block["version"], world["patient"]["id"],
                              world["procedure"]["id"], 480)
    fixtures.attach_implant(case["id"], item["id"], 3)
    get_success_data(api_client.confirm_block(block["id"], SCHED))
    get_success_data(api_client.release_block(block["id"], SCHED))
    item_after = get_success_data(api_client.get_supply_item(item["id"], ORMGR))
    assert item_after["reserved_qty"] == 0, item_after["reserved_qty"]
    assert item_after["on_hand_qty"] == 5, item_after["on_hand_qty"]


# ===========================================================================
# Difficulty / transitive_cascade / case_cancel_cascades_to_block_minutes_and_day_util_depth2
# ===========================================================================
def test_case_cancel_recomputes_block_minutes_and_day_utilization():
    """PRD §3.10: "A cancellation is a compensating operation that must restore the
    conservation invariants: it subtracts the cancelled case's `scheduled_minutes` from its
    block's `committed_minutes`, moves every `RESERVED` implant on the case to `RELEASED`
    and decrements each affected supply item's `reserved_qty` by that implant's `planned_qty`,
    and recomputes the owning day's `booked_minutes` and `utilization_pct`."

    One 60-min SCHEDULED case; cancelling it returns block committed_minutes to 0, day
    booked_minutes to 0, and day utilization_pct to 0.

    Design: Difficulty/transitive_cascade/case_cancel_cascades_to_block_minutes_and_day_util_depth2
    """
    world, block, case = fixtures.setup_booked_case(
        start_min=480, block_start=480, block_end=600,
        world_kwargs={"prime_time_start_min": 420, "prime_time_end_min": 960})
    get_success_data(api_client.cancel_case(case["id"], SCHED))
    block_after = get_success_data(api_client.get_surgeon_block(block["id"], SCHED))
    day_after = get_success_data(api_client.get_surgical_day(world["day"]["id"], SCHED))
    assert block_after["committed_minutes"] == 0, block_after["committed_minutes"]
    assert day_after["booked_minutes"] == 0, day_after["booked_minutes"]
    assert day_after["utilization_pct"] == 0, day_after["utilization_pct"]


def test_case_cancel_moves_case_to_cancelled():
    """PRD §3.10: "A `Scheduler` cancels a case, advancing `case_status`
    `SCHEDULED → CANCELLED`. Cancellation is permitted only for a `SCHEDULED` case
    (otherwise `ERR_CASE_NOT_CANCELLABLE`)."

    Cancelling a SCHEDULED case moves case_status to CANCELLED (the depth-2 cascade's trigger).

    Design: Difficulty/transitive_cascade/case_cancel_cascades_to_block_minutes_and_day_util_depth2
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    cancelled = validate_success(api_client.cancel_case(case["id"], SCHED), 200)
    assert cancelled["case_status"] == "CANCELLED", cancelled["case_status"]


# ===========================================================================
# Difficulty / compensating_invariant / block_minutes_conservation_book_then_cancel
# ===========================================================================
def test_committed_minutes_conserved_book_then_cancel():
    """PRD §2.9: "block-minute conservation: a block's `committed_minutes` always equals the
    sum of the `scheduled_minutes` of the non-cancelled cases booked into it, so every
    booking adds the booked case's minutes and every cancellation or cascade-cancel
    subtracts them."

    Book a 60-min case (committed_minutes 60), then cancel it: committed_minutes returns
    to its pre-book value 0.

    Design: Difficulty/compensating_invariant/block_minutes_conservation_book_then_cancel
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    after_book = get_success_data(api_client.get_surgeon_block(block["id"], SCHED))
    assert after_book["committed_minutes"] == 60, after_book["committed_minutes"]
    get_success_data(api_client.cancel_case(case["id"], SCHED))
    after_cancel = get_success_data(api_client.get_surgeon_block(block["id"], SCHED))
    assert after_cancel["committed_minutes"] == 0, after_cancel["committed_minutes"]


def test_committed_minutes_added_on_booking():
    """PRD §2.9: "block-minute conservation: a block's `committed_minutes` always equals the
    sum of the `scheduled_minutes` of the non-cancelled cases booked into it, so every
    booking adds the booked case's minutes and every cancellation or cascade-cancel
    subtracts them."

    Booking a single 60-min case leaves the block's committed_minutes at exactly 60 (the
    conserved sum before any cancellation).

    Design: Difficulty/compensating_invariant/block_minutes_conservation_book_then_cancel
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    after = get_success_data(api_client.get_surgeon_block(block["id"], SCHED))
    assert after["committed_minutes"] == 60, after["committed_minutes"]


# ===========================================================================
# Difficulty / compensating_invariant / supply_reservation_conservation_attach_then_release
# ===========================================================================
def test_reserved_qty_conserved_attach_then_release():
    """PRD §2.9: "supply-reservation conservation: a supply item's `reserved_qty` always
    equals the sum of `planned_qty` across the case implants that are currently in
    `RESERVED` status, so reserving adds and releasing or consuming subtracts."
    PRD §3.9: "An `ORManager` may also release a still-`RESERVED` implant, advancing it
    `RESERVED → RELEASED`; release requires the implant to be `RESERVED` (otherwise
    `ERR_IMPLANT_NOT_RESERVED`), decrements the supply item's `reserved_qty` by `planned_qty`,
    and recomputes the case's `estimated_cost_cents` if the case is still `SCHEDULED`."

    Attach planned_qty 4 (reserved_qty 4), then release the implant: reserved_qty returns
    to 0 and on_hand_qty stays at its opening 7.

    Design: Difficulty/compensating_invariant/supply_reservation_conservation_attach_then_release
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    fac = world["facility"]
    item = fixtures.create_supply_item(fac["id"], sku="DEV1", description="Implant",
                                       unit_cost_cents=5000, is_device=True, on_hand_qty=7)
    imp = fixtures.attach_implant(case["id"], item["id"], 4)
    after_attach = get_success_data(api_client.get_supply_item(item["id"], ORMGR))
    assert after_attach["reserved_qty"] == 4, after_attach["reserved_qty"]
    released = validate_success(api_client.release_implant(case["id"], imp["id"], ORMGR), 200)
    assert released["status"] == "RELEASED", released["status"]
    item_after = get_success_data(api_client.get_supply_item(item["id"], ORMGR))
    assert item_after["reserved_qty"] == 0, item_after["reserved_qty"]
    assert item_after["on_hand_qty"] == 7, item_after["on_hand_qty"]


def test_reserved_qty_added_on_attach():
    """PRD §2.9: "supply-reservation conservation: a supply item's `reserved_qty` always
    equals the sum of `planned_qty` across the case implants that are currently in
    `RESERVED` status, so reserving adds and releasing or consuming subtracts."
    PRD §3.2: "Reserving stock does not reduce `on_hand_qty` — only consuming it at case
    completion does."

    Attaching planned_qty 4 raises reserved_qty to 4 while on_hand_qty stays at 7.

    Design: Difficulty/compensating_invariant/supply_reservation_conservation_attach_then_release
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    fac = world["facility"]
    item = fixtures.create_supply_item(fac["id"], sku="DEV1", description="Implant",
                                       unit_cost_cents=5000, is_device=True, on_hand_qty=7)
    fixtures.attach_implant(case["id"], item["id"], 4)
    after = get_success_data(api_client.get_supply_item(item["id"], ORMGR))
    assert after["reserved_qty"] == 4, after["reserved_qty"]
    assert after["on_hand_qty"] == 7, after["on_hand_qty"]


# ===========================================================================
# Corner / cross_cutting_complexity_layers / complete_recomputes_supply_on_hand_derived_field
# ===========================================================================
def test_complete_consumes_implant_and_recomputes_supply():
    """PRD §3.11: "each `RESERVED` implant on the case advances `RESERVED → CONSUMED`,
    decrementing its supply item's `reserved_qty` by the implant's `planned_qty` and its
    `on_hand_qty` by the implant's `consumed_qty`..."

    Implant planned 4 / consumed 3, item on_hand 10: on completion reserved_qty 4->0 and
    on_hand_qty 10->7.

    Design: Corner/cross_cutting_complexity_layers/complete_recomputes_supply_on_hand_derived_field
    """
    # Build the world first, then create the supply item in that same facility and pass it
    # into the in-recovery helper so the implant is attached + consumed_qty recorded before
    # the case is started and completed.
    world = fixtures.setup_facility_world(
        with_clock="2026-07-01T00:00:00.000Z", with_bay=True, with_anesthesia=True)
    item = fixtures.create_supply_item(world["facility"]["id"], sku="DEV1",
                                       description="Implant", unit_cost_cents=5000,
                                       is_device=True, on_hand_qty=10)
    block = fixtures.setup_block(world, 480, 600)
    case = fixtures.book_case(block["id"], block["version"], world["patient"]["id"],
                              world["procedure"]["id"], 480,
                              anesthesiologist_id=world["anesthesiologist"]["id"],
                              recovery_bay_id=world["bay"]["id"])
    imp = fixtures.attach_implant(case["id"], item["id"], 4)
    get_success_data(api_client.patch_implant(imp["id"], {"consumed_qty": 3}, ORMGR))
    fixtures.clear_case_full(case["id"])
    get_success_data(api_client.lock_day(world["day"]["id"], SCHED))
    get_success_data(api_client.start_case(case["id"], ORMGR))
    get_success_data(api_client.case_to_recovery(case["id"], ORMGR))
    fixtures.complete_case(case["id"], 60)

    imp_after = get_success_data(api_client.get_case_implant(imp["id"], ORMGR))
    item_after = get_success_data(api_client.get_supply_item(item["id"], ORMGR))
    assert imp_after["status"] == "CONSUMED", imp_after["status"]
    assert item_after["reserved_qty"] == 0, item_after["reserved_qty"]
    assert item_after["on_hand_qty"] == 7, item_after["on_hand_qty"]
