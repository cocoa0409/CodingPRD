"""Depth tests for non-linear state machines, transitive cascades, and cross-entity
state dependencies (PRD §3.3, §3.4, §3.5, §3.6, §3.7, §3.9)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_access_visit_payload,
    TEST_USERS, make_customer_headers,
)
from test_helpers import fixtures as F

DO = TEST_USERS["dispatch_operator_headers"]
BC = TEST_USERS["billing_clerk_headers"]


# ── Rule 3: non_linear_state_machine / agreement_hold_resume_cycle ──

def test_hold_then_resume_returns_to_active(api):
    """PRD §3.5: "Resuming reverses this, advancing `lifecycle_status` from `ON_HOLD` back
    to `ACTIVE` and allowing monthly billing to resume from the next anchor; it is permitted
    only when the agreement is `ON_HOLD`."

    Design: Difficulty/non_linear_state_machine/agreement_hold_resume_cycle
    """
    world, ag, unit = F.setup_active_agreement(tier_code="NONE")
    cust = make_customer_headers(world["customer"]["id"])
    validate_success(api.hold_agreement(ag["id"], cust), 200)
    resumed = validate_success(api.resume_agreement(ag["id"], cust), 200)
    assert resumed["lifecycle_status"] == "ACTIVE"


def test_second_hold_after_resume_succeeds(api):
    """PRD §3.5: "Placing an agreement on hold ... advances `lifecycle_status` from
    `ACTIVE` to `ON_HOLD` and is permitted only when the agreement is `ACTIVE`." PRD §3.5:
    "The hold/resume loop may repeat any number of times."

    Design: Difficulty/non_linear_state_machine/agreement_hold_resume_cycle
    """
    world, ag, unit = F.setup_active_agreement(tier_code="NONE")
    cust = make_customer_headers(world["customer"]["id"])
    validate_success(api.hold_agreement(ag["id"], cust), 200)
    validate_success(api.resume_agreement(ag["id"], cust), 200)
    second_hold = validate_success(api.hold_agreement(ag["id"], cust), 200)
    assert second_hold["lifecycle_status"] == "ON_HOLD"


# ── Rule 3: non_linear_state_machine / container_unit_branching_access_vs_move ──

def test_depot_pickup_fulfill_moves_unit_in_transit(api):
    """PRD §3.7: "When the `access_kind` is `DEPOT_PICKUP`, fulfillment also cascades the
    container `ON_SITE → IN_TRANSIT` and leaves `redelivery_required` true".

    Design: Difficulty/non_linear_state_machine/container_unit_branching_access_vs_move
    """
    world, ag, unit = F.setup_active_agreement(tier_code="NONE")
    cust = make_customer_headers(world["customer"]["id"])
    av = validate_success(api.create_access_visit(
        create_access_visit_payload(ag["id"], unit["id"], access_kind="DEPOT_PICKUP",
                                    requested_for="2026-07-18T09:00:00Z"), cust), 201)
    fulfilled = validate_success(api.fulfill_access_visit(av["id"], DO), 200)
    assert fulfilled["status"] == "FULFILLED"

    unit_after = validate_success(api.get_container_unit(unit["id"], DO), 200)
    assert unit_after["status"] == "IN_TRANSIT"


def test_depot_pickup_fulfill_posts_access_fee(api):
    """PRD §3.7: "Fulfilling an access visit is a `DispatchOperator` action and advances it
    `REQUESTED → FULFILLED` ... Fulfillment posts an `ACCESS_FEE` charge."

    Design: Difficulty/non_linear_state_machine/container_unit_branching_access_vs_move
    """
    world, ag, unit = F.setup_active_agreement(tier_code="NONE")
    cust = make_customer_headers(world["customer"]["id"])
    av = validate_success(api.create_access_visit(
        create_access_visit_payload(ag["id"], unit["id"], access_kind="DEPOT_PICKUP",
                                    requested_for="2026-07-18T09:00:00Z"), cust), 201)
    validate_success(api.fulfill_access_visit(av["id"], DO), 200)

    fees, _ = validate_paginated(
        api.list_charges(ag["id"], BC, params={"charge_type": "ACCESS_FEE"}))
    assert len(fees) == 1


# ── Rule 4: transitive_cascade / delivery_activation_chain_depth3 ──

def test_delivery_completion_activates_and_posts_balance(api):
    """PRD §3.3: "the agreement's `lifecycle_status` advances `RESERVED → ACTIVE`.
    Activation also posts the opening charges and locks pricing, described in §3.4." PRD
    §3.4: "After posting, the agreement's `balance_due_cents` is recomputed (§3.8)".

    Design: Difficulty/transitive_cascade/delivery_activation_chain_depth3
    """
    # PLUS C16 declared 500000: DELIVERY_FEE 8900 + RENTAL_PRORATION 10271 +
    # PROTECTION_PREMIUM 5500 = 24671.
    world, ag, unit = F.setup_active_agreement(
        tier_code="PLUS", declared_value_cents=500000,
        plan_overrides={"base_premium_cents": 1500, "rate_bps": 80,
                        "min_premium_cents": 2000, "coverage_cap_cents": 100000000})
    assert ag["lifecycle_status"] == "ACTIVE"
    assert ag["balance_due_cents"] == 24671


def test_delivery_completion_cascades_to_customer_open_balance(api):
    """PRD §3.9: "`open_balance_cents` is the sum of `balance_due_cents` across that
    customer's agreements whose `lifecycle_status` is `RESERVED`, `ACTIVE`, `ON_HOLD`, or
    `CLOSING` ... These mirrors are likewise refreshed on delivery activation and on close."

    Design: Difficulty/transitive_cascade/delivery_activation_chain_depth3
    """
    world, ag, unit = F.setup_active_agreement(
        tier_code="PLUS", declared_value_cents=500000,
        plan_overrides={"base_premium_cents": 1500, "rate_bps": 80,
                        "min_premium_cents": 2000, "coverage_cap_cents": 100000000})
    cust = validate_success(api.get_customer(world["customer"]["id"], BC), 200)
    assert cust["open_balance_cents"] == 24671


# ── Rule 4: transitive_cascade / longdistance_move_completion_chain_depth2 ──

def _setup_long_distance_dispatched(api):
    """Two depots; LA-drawn ACTIVE C16 agreement; a LONG_DISTANCE move dispatched
    (unit IN_TRANSIT). Returns (la_inv, dal_inv, dal_depot, ag, unit, move)."""
    F.set_clock()
    F.create_container_model(size_code="C16")
    F.create_protection_plan(tier_code="NONE")
    la = F.create_depot(name="LA Depot", state_code="CA", service_radius_miles=50)
    dal = F.create_depot(name="DAL Depot", state_code="TX", service_radius_miles=50)
    la_inv = F.create_depot_inventory(la["id"], size_code="C16", total_units=1)
    dal_inv = F.create_depot_inventory(dal["id"], size_code="C16", total_units=1)
    crew = F.create_crew(la["id"])
    truck = F.create_truck(la["id"], plate="TRK-LD2", max_concurrent_containers=1)
    cust = F.create_customer(email="mv@x.com")
    world = {"depot": la, "crew": crew, "truck": truck, "customer": cust,
             "inventory": la_inv, "plan": {"tier_code": "NONE"}}
    ag, unit = F.deliver_and_activate(world, agreement_overrides={"declared_value_cents": 0})
    move = F.schedule_move(
        world, ag, unit, destination_state_code="TX", distance_miles=1800,
        window_start="2026-07-20T09:00:00Z", window_end="2026-07-21T11:00:00Z")
    validate_success(api.dispatch_move_order(move["id"], DO), 200)
    return la_inv, dal_inv, dal, ag, unit, move


def test_long_distance_completion_moves_unit_to_destination_depot(api):
    """PRD §3.6: "Completing an in-transit move advances it `IN_TRANSIT → COMPLETED` and
    cascades the container `IN_TRANSIT → ON_SITE`; when the `move_class` is `LONG_DISTANCE`,
    completion also sets the container's `current_depot_id` to the move's destination depot".

    Design: Difficulty/transitive_cascade/longdistance_move_completion_chain_depth2
    """
    la_inv, dal_inv, dal, ag, unit, move = _setup_long_distance_dispatched(api)
    validate_success(api.complete_move_order(move["id"], DO), 200)
    unit_after = validate_success(api.get_container_unit(unit["id"], DO), 200)
    assert unit_after["status"] == "ON_SITE"
    assert unit_after["current_depot_id"] == dal["id"]


def test_long_distance_completion_rebalances_committed_units(api):
    """PRD §3.6: "and rebalances inventory — the origin `DepotInventory` row's
    `committed_units` is decremented by 1 and the destination row's `committed_units`
    incremented by 1, preserving the global pool."

    Design: Difficulty/transitive_cascade/longdistance_move_completion_chain_depth2
    """
    la_inv, dal_inv, dal, ag, unit, move = _setup_long_distance_dispatched(api)
    validate_success(api.complete_move_order(move["id"], DO), 200)
    la_after = validate_success(api.get_depot_inventory(la_inv["id"], DO), 200)
    dal_after = validate_success(api.get_depot_inventory(dal_inv["id"], DO), 200)
    assert la_after["committed_units"] == 0
    assert dal_after["committed_units"] == 1


# ── Rule 7: cross_entity_state_dependency / move_dispatch_requires_unit_on_site ──

def test_move_dispatch_blocked_when_unit_in_transit(api):
    """PRD §3.6: "Dispatching a scheduled move advances it `SCHEDULED → IN_TRANSIT`; it is
    permitted only when the move is `SCHEDULED`, the container is `ON_SITE`, and the parent
    agreement is `ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/move_dispatch_requires_unit_on_site
    """
    # Two moves with non-overlapping windows so both schedule on the one truck; the
    # first dispatch leaves the unit IN_TRANSIT, blocking the second dispatch.
    world, ag, unit = F.setup_active_agreement(tier_code="NONE", with_truck=True)
    move1 = F.schedule_move(world, ag, unit, destination_state_code="CA", distance_miles=30,
                            window_start="2026-07-20T09:00:00Z", window_end="2026-07-20T11:00:00Z")
    move2 = F.schedule_move(world, ag, unit, destination_state_code="CA", distance_miles=40,
                            window_start="2026-07-22T09:00:00Z", window_end="2026-07-22T11:00:00Z")
    validate_success(api.dispatch_move_order(move1["id"], DO), 200)  # unit now IN_TRANSIT

    res = api.dispatch_move_order(move2["id"], DO)
    validate_error(res, "ERR_INVALID_STATE")


def test_move_dispatch_succeeds_when_unit_on_site(api):
    """PRD §3.6: "Dispatching a scheduled move advances it `SCHEDULED → IN_TRANSIT`; it is
    permitted only when the move is `SCHEDULED`, the container is `ON_SITE`, and the parent
    agreement is `ACTIVE`, and it cascades the container `ON_SITE → IN_TRANSIT`."

    Design: Difficulty/cross_entity_state_dependency/move_dispatch_requires_unit_on_site
    """
    # The same scheduled move dispatches cleanly while its linked unit is ON_SITE.
    world, ag, unit = F.setup_active_agreement(tier_code="NONE", with_truck=True)
    move = F.schedule_move(world, ag, unit, destination_state_code="CA", distance_miles=30,
                           window_start="2026-07-20T09:00:00Z", window_end="2026-07-20T11:00:00Z")
    dispatched = validate_success(api.dispatch_move_order(move["id"], DO), 200)
    assert dispatched["status"] == "IN_TRANSIT"
    unit_after = validate_success(api.get_container_unit(unit["id"], DO), 200)
    assert unit_after["status"] == "IN_TRANSIT"


def test_close_blocked_when_unit_still_on_site(api):
    """PRD §3.5: "Closing advances `lifecycle_status` from `CLOSING` to `CLOSED`, but only
    when three conditions hold: the agreement is `CLOSING`, its container is `RETURNED`, and
    its final balance is fully settled ... if the container is not yet `RETURNED`, the close
    is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/close_requires_unit_returned
    """
    world, ag, unit = F.setup_active_agreement(tier_code="NONE")
    cust_id = world["customer"]["id"]
    F.pay_full_balance(ag, cust_id)        # balance 19171 -> 0
    F.request_closeout(ag, cust_id)        # CLOSING, unit still ON_SITE

    res = api.close_agreement(ag["id"], BC)
    validate_error(res, "ERR_INVALID_STATE")


def test_close_succeeds_once_unit_returned(api):
    """PRD §3.5: "Closing advances `lifecycle_status` from `CLOSING` to `CLOSED`, but only
    when three conditions hold: the agreement is `CLOSING`, its container is `RETURNED`, and
    its final balance is fully settled."

    Design: Difficulty/cross_entity_state_dependency/close_requires_unit_returned
    """
    # Same agreement, but the unit is RETURNED first — close then succeeds (CLOSING->CLOSED),
    # confirming RETURNED is the gating linked-unit state the prior test rejected ON_SITE for.
    world, ag, unit = F.setup_closing_unit_returned(tier_code="NONE")
    closed = validate_success(api.close_agreement(ag["id"], BC), 200)
    assert closed["lifecycle_status"] == "CLOSED"
