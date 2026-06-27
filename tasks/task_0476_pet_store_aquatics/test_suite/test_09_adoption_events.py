"""Adoption events and placements: close-cascade returns, place-then-return
compensating invariant, aggregate-capacity overlap, insufficient-head check,
and placement-not-returnable."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    create_adoption_placement_payload,
    make_store, make_healthy_on_floor_batch, make_open_event,
    setup_event_with_placement,
)

INVMGR = TEST_USERS["inventory_manager_headers"]
KEEPER = TEST_USERS["livestock_keeper_headers"]
CLERK = TEST_USERS["store_clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / close returns placement & frees batch
# ---------------------------------------------------------------------------
def test_adoption_close_returns_placement_and_frees_batch(api):
    """PRD §3.6: "Closing is a cascade: for every placement still in `PLACED`
    status under the event, the placement's `status` is set to `RETURNED`, the
    event's `placed_head` is reduced by that placement's `head`, and if the
    placement's batch had its sale in `RESERVED` the batch returns to `ON_FLOOR`
    with its `version` bumped. After the cascade resolves all outstanding
    placements, the event's `status` becomes `CLOSED`".

    Design: Difficulty/transitive_cascade/adoption_close_returns_placement_and_frees_batch
    """
    ctx = setup_event_with_placement(head_count=4, capacity=10, species="hamster")
    event = ctx["event"]
    batch = ctx["batch"]
    placement = ctx["placement"]
    validate_success(api.close_adoption_event(event["id"], CLERK), 200)
    pl_after = validate_success(api.get_adoption_placement(placement["id"], KEEPER), 200)
    event_after = validate_success(api.get_adoption_event(event["id"], CLERK), 200)
    batch_after = validate_success(api.get_livestock_batch(batch["id"], KEEPER), 200)
    assert pl_after["status"] == "RETURNED"
    assert event_after["placed_head"] == 0
    assert event_after["status"] == "CLOSED"
    assert batch_after["sale_state"] == "ON_FLOOR"


def test_adoption_close_event_becomes_closed(api):
    """PRD §3.6: "Closing an event advances it from `OPEN` to `CLOSED`, permitted
    only while it is `OPEN` (otherwise `ERR_EVENT_STATE_INVALID`)."
    PRD §3.6: "After the cascade resolves all outstanding placements, the event's
    `status` becomes `CLOSED` and its `version` is bumped."

    Design: Difficulty/transitive_cascade/adoption_close_returns_placement_and_frees_batch
    """
    ctx = setup_event_with_placement(head_count=4, capacity=10, species="hamster")
    closed = validate_success(api.close_adoption_event(ctx["event"]["id"], CLERK), 200)
    assert closed["status"] == "CLOSED"
    assert closed["placed_head"] == 0


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / place then return conserves placed_head
# ---------------------------------------------------------------------------
def test_adoption_place_then_return_conserves_event_placed_head(api):
    """PRD §3.4: "A successful placement is created in `PLACED` status; the
    event's `placed_head` is increased by the placed `head`".
    PRD §3.4: "On return, the placement's `status` becomes `RETURNED`, the
    event's `placed_head` is decreased by that placement's `head` ..., and if the
    batch's sale was `RESERVED` it returns to `ON_FLOOR`".

    Design: Difficulty/compensating_invariant/adoption_place_then_return_conserves_event_placed_head
    """
    ctx = setup_event_with_placement(head_count=4, capacity=10, species="ferret")
    event = ctx["event"]
    batch = ctx["batch"]
    placement = ctx["placement"]
    # placed_head was raised 0→4 by the placement.
    validate_success(api.return_adoption_placement(placement["id"], KEEPER), 200)
    event_after = validate_success(api.get_adoption_event(event["id"], CLERK), 200)
    pl_after = validate_success(api.get_adoption_placement(placement["id"], KEEPER), 200)
    batch_after = validate_success(api.get_livestock_batch(batch["id"], KEEPER), 200)
    assert event_after["placed_head"] == 0
    assert pl_after["status"] == "RETURNED"
    assert batch_after["sale_state"] == "ON_FLOOR"


def test_adoption_placement_reserves_full_head_batch(api):
    """PRD §3.4: "When — and only when — the placed `head` equals the batch's
    entire live head (its `head_count` minus its `mortality_count`), the batch's
    sale advances from `ON_FLOOR` to `RESERVED`, reflecting that the whole live
    batch is now committed to the event."

    Design: Difficulty/compensating_invariant/adoption_place_then_return_conserves_event_placed_head
    """
    ctx = setup_event_with_placement(head_count=4, capacity=10, species="ferret")
    batch = ctx["batch"]
    event = ctx["event"]
    # Full live head (4) placed → batch RESERVED, event placed_head == 4.
    batch_now = validate_success(api.get_livestock_batch(batch["id"], KEEPER), 200)
    event_now = validate_success(api.get_adoption_event(event["id"], CLERK), 200)
    assert batch_now["sale_state"] == "RESERVED"
    assert event_now["placed_head"] == 4


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / aggregate-capacity overlap
# ---------------------------------------------------------------------------
def test_adoption_event_capacity_aggregate_overlap_rejected(api):
    """PRD §3.4: "the event's `placed_head` plus the requested `head` to be no
    greater than the event's `capacity` (otherwise `ERR_EVENT_CAPACITY_EXCEEDED`)."

    Design: Difficulty/resource_temporal_overlap/adoption_event_capacity_aggregate_overlap_rejected
    """
    store = make_store()
    b1 = make_healthy_on_floor_batch(
        store["id"], head_count=4, unit_price_cents=3000,
        species="rabbit", animal_class="SMALL_ANIMAL",
    )
    b2 = make_healthy_on_floor_batch(
        store["id"], head_count=2, unit_price_cents=3000,
        species="rabbit", animal_class="SMALL_ANIMAL",
    )
    event = make_open_event(store["id"], capacity=5)
    # First placement uses 4 of 5 capacity.
    validate_success(
        api.create_adoption_placement(
            create_adoption_placement_payload(event["id"], b1["id"], 4), KEEPER
        ), 201,
    )
    # Second placement of 2 would push placed_head to 6 > capacity 5.
    res = api.create_adoption_placement(
        create_adoption_placement_payload(event["id"], b2["id"], 2), KEEPER
    )
    validate_error(res, ApiErrorId.ERR_EVENT_CAPACITY_EXCEEDED)


def test_adoption_event_capacity_exact_fit_allowed(api):
    """PRD §3.4: "the event's `placed_head` plus the requested `head` to be no
    greater than the event's `capacity` (otherwise `ERR_EVENT_CAPACITY_EXCEEDED`)."
    PRD §3.4: "A successful placement is created in `PLACED` status; the event's
    `placed_head` is increased by the placed `head`".

    Design: Difficulty/resource_temporal_overlap/adoption_event_capacity_aggregate_overlap_rejected
    """
    store = make_store()
    b1 = make_healthy_on_floor_batch(
        store["id"], head_count=4, unit_price_cents=3000,
        species="rabbit", animal_class="SMALL_ANIMAL",
    )
    b2 = make_healthy_on_floor_batch(
        store["id"], head_count=1, unit_price_cents=3000,
        species="rabbit", animal_class="SMALL_ANIMAL",
    )
    event = make_open_event(store["id"], capacity=5)
    validate_success(
        api.create_adoption_placement(
            create_adoption_placement_payload(event["id"], b1["id"], 4), KEEPER
        ), 201,
    )
    # placed_head 4 + head 1 == capacity 5: aggregate fit is allowed (<=).
    placement = validate_success(
        api.create_adoption_placement(
            create_adoption_placement_payload(event["id"], b2["id"], 1), KEEPER
        ), 201,
    )
    assert placement["status"] == "PLACED"
    event_after = validate_success(api.get_adoption_event(event["id"], CLERK), 200)
    assert event_after["placed_head"] == 5


# ---------------------------------------------------------------------------
# Corner: validations / insufficient head placement
# ---------------------------------------------------------------------------
def test_insufficient_head_placement_rejected(api):
    """PRD §3.4: "the requested `head` to be no greater than the batch's live
    head — its `head_count` minus its `mortality_count` (otherwise
    `ERR_INSUFFICIENT_HEAD`) ... When both quantity checks could fail, the
    live-head check is evaluated before the capacity check."

    Design: Corner/validations/insufficient_head_placement_rejected
    """
    store = make_store()
    batch = make_healthy_on_floor_batch(
        store["id"], head_count=4, unit_price_cents=3000,
        species="rabbit", animal_class="SMALL_ANIMAL",
    )
    event = make_open_event(store["id"], capacity=10)
    # head=5 exceeds the batch's live head of 4.
    res = api.create_adoption_placement(
        create_adoption_placement_payload(event["id"], batch["id"], 5), KEEPER
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_HEAD)


# ---------------------------------------------------------------------------
# Corner: errors / placement already returned
# ---------------------------------------------------------------------------
def test_placement_return_already_returned_rejected(api):
    """PRD §3.4: "Returning a placement requires that the placement is still in
    `PLACED` status (otherwise `ERR_PLACEMENT_NOT_RETURNABLE`)."

    Design: Corner/errors/placement_return_already_returned_rejected
    """
    ctx = setup_event_with_placement(head_count=4, capacity=10, species="rabbit")
    placement = ctx["placement"]
    validate_success(api.return_adoption_placement(placement["id"], KEEPER), 200)
    res = api.return_adoption_placement(placement["id"], KEEPER)
    validate_error(res, ApiErrorId.ERR_PLACEMENT_NOT_RETURNABLE)
