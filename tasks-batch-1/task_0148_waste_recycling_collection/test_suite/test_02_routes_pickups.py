"""Route manifests, pickup outcomes, weighing, and contamination.

Covers difficulty rules transitive_cascade (route cancel), cross_entity_state_dependency
(pickup needs route IN_PROGRESS), resource_temporal_overlap (pickup slot), and the
state_machines / validations / entities corner instances for routes, stops, pickups,
weight tickets, and contamination tags.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_route_payload,
    create_stop_payload,
    create_pickup_payload,
    complete_pickup_payload,
    miss_pickup_payload,
    create_weight_ticket_payload,
    create_contamination_tag_payload,
    assert_weight_ticket,
    create_account,
    create_active_cart,
    create_cart as fx_create_cart,
    setup_route_in_progress,
    schedule_pickup,
    complete_pickup_with_ticket,
    setup_completed_pickup,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]
BILLING = TEST_USERS["billing_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# Corner / state_machines — pickup completion bubbles stop, route terminal lock
# ═══════════════════════════════════════════════════════════════════════════

def test_pickup_complete_bubbles_stop_to_serviced(api):
    """PRD §3.2: "when a pickup at the stop completes, the stop bubbles up from
    `PENDING` to `SERVICED`".
    PRD §3.3: "The `Driver` **completes** a pickup, setting `outcome` to `COMPLETED`".

    Design: Corner/state_machines/pickup_complete_bubbles_stop_to_serviced
    """
    account = create_account(address="114 Main St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    route, stops = setup_route_in_progress(account["id"], stream="TRASH")
    stop = stops[0]
    pickup = schedule_pickup(stop["id"], cart["id"])
    completed = validate_success(
        api.complete_pickup(pickup["id"], complete_pickup_payload(cart["version"]), DRIVER), 200
    )
    assert completed["outcome"] == "COMPLETED", f"expected COMPLETED, got {completed['outcome']}"
    stop_after = validate_success(api.get_stop(stop["id"], DISPATCHER), 200)
    assert stop_after["status"] == "SERVICED", f"stop must be SERVICED, got {stop_after['status']}"


def test_pickup_miss_customer_fault_no_credit(api):
    """PRD §3.3: "Missing a pickup bubbles its stop up from `PENDING` to `SKIPPED` and
    increments the pickup's `version`."
    PRD §3.3: "When the `miss_reason` is `BLOCKED_ACCESS` or `NOT_OUT` — both
    customer-fault reasons — no credit is created."

    Design: Corner/state_machines/pickup_miss_customer_fault_no_credit
    """
    account = create_account(address="115 Main St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    route, stops = setup_route_in_progress(account["id"], stream="TRASH")
    stop = stops[0]
    pickup = schedule_pickup(stop["id"], cart["id"])
    missed = validate_success(
        api.miss_pickup(pickup["id"], miss_pickup_payload("NOT_OUT"), DRIVER), 200
    )
    assert missed["outcome"] == "MISSED", f"expected MISSED, got {missed['outcome']}"
    stop_after = validate_success(api.get_stop(stop["id"], DISPATCHER), 200)
    assert stop_after["status"] == "SKIPPED", f"stop must be SKIPPED, got {stop_after['status']}"
    credits, _ = validate_paginated(
        api.list_credits(BILLING, params={"source_pickup_id": pickup["id"]})
    )
    assert credits == [], f"customer-fault miss must create no credit, got {credits}"


def test_route_complete_from_completed_terminal_lockdown(api):
    """PRD §3.7: "Any invoice transition attempted from a status the transition is not
    defined for is rejected with `ERR_INVALID_STATE`." (general lockdown principle)
    PRD §3.2: "the driver completes the route, moving it from `IN_PROGRESS` to the
    terminal `COMPLETED` state" — COMPLETED is terminal, so a second completion has no
    defined transition.

    Design: Corner/state_machines/route_complete_from_completed_terminal_lockdown
    """
    account = create_account(address="113 Main St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    route, stops = setup_route_in_progress(account["id"], stream="TRASH")
    pickup = schedule_pickup(stops[0]["id"], cart["id"])
    validate_success(api.complete_pickup(pickup["id"], complete_pickup_payload(cart["version"]), DRIVER), 200)
    validate_success(api.complete_route(route["id"], DRIVER), 200)
    resp = api.complete_route(route["id"], DRIVER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


# ═══════════════════════════════════════════════════════════════════════════
# Corner / state_machines — route ledger sync (total net weight)
# ═══════════════════════════════════════════════════════════════════════════

def test_route_total_net_weight_recomputed_after_ticket(api):
    """PRD §3.4: "Recording a ticket also recomputes the route's `total_net_weight_lbs`,
    which is the sum of `net_weight_lbs` across all weight tickets on `COMPLETED`
    pickups whose stop belongs to that route."

    Design: Corner/state_machines/route_total_net_weight_recomputed_ledger_sync
    """
    account = create_account(address="118 Main St")
    cart, route, stop, pickup, ticket = setup_completed_pickup(
        account["id"], stream="TRASH", tare_weight_lbs=50, gross_weight_lbs=250, diverted=False
    )
    # net = 250 - 50 = 200
    route_after = validate_success(api.get_route(route["id"], DISPATCHER), 200)
    assert route_after["total_net_weight_lbs"] == 200, (
        f"expected total_net_weight_lbs 200, got {route_after['total_net_weight_lbs']}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Corner / entities — weight ticket computed net + immutability
# ═══════════════════════════════════════════════════════════════════════════

def test_weight_ticket_net_weight_computed(api):
    """PRD §3.4: "the system computes the ticket's `net_weight_lbs` as the gross reading
    minus the tare weight of the pickup's cart, floored at 0 so it never goes negative —
    that is, the larger of 0 and the difference between `gross_weight_lbs` and the cart's
    `tare_weight_lbs` — rounded to three decimal places, round-half-up."

    Design: Corner/entities/weight_ticket_net_weight_computed
    """
    account = create_account(address="105 Main St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=96, tare_weight_lbs=50)
    route, stops = setup_route_in_progress(account["id"], stream="TRASH")
    pickup = schedule_pickup(stops[0]["id"], cart["id"])
    validate_success(api.complete_pickup(pickup["id"], complete_pickup_payload(cart["version"]), DRIVER), 200)
    data = validate_success(
        api.create_weight_ticket(pickup["id"], create_weight_ticket_payload(250, False), DRIVER), 201
    )
    assert data["net_weight_lbs"] == 200, f"expected net 200, got {data['net_weight_lbs']}"


def test_weight_ticket_immutable_no_version_field(api):
    """PRD §2.4: "a `WeightTicket` is an immutable scale record and carries only `id`
    and `created_at`. It has no `updated_at` and no `version`, because once recorded it
    is never mutated."

    Design: Corner/entities/weight_ticket_immutable_no_version_field
    """
    account = create_account(address="109 Main St")
    cart, route, stop, pickup, ticket = setup_completed_pickup(
        account["id"], stream="TRASH", tare_weight_lbs=10, gross_weight_lbs=110, diverted=False
    )
    tickets, _ = validate_paginated(api.list_weight_tickets(pickup["id"], BILLING))
    assert len(tickets) == 1, f"expected one ticket, got {len(tickets)}"
    t = tickets[0]
    assert "version" not in t, "WeightTicket must not expose version"
    assert "updated_at" not in t, "WeightTicket must not expose updated_at"
    assert "id" in t and "created_at" in t
    assert_weight_ticket(t)


# ═══════════════════════════════════════════════════════════════════════════
# Corner / validations — weight ticket gating, duplicate sequence, dispatch driver
# ═══════════════════════════════════════════════════════════════════════════

def test_weight_ticket_on_scheduled_pickup_not_allowed(api):
    """PRD §3.4: "A weight ticket may only be recorded for a pickup whose `outcome` is
    `COMPLETED`, and at most one ticket may exist per pickup; recording a ticket for a
    non-completed pickup, or a second ticket for a pickup that already has one, is
    rejected with `ERR_WEIGHT_TICKET_NOT_ALLOWED`."

    Design: Corner/validations/weight_ticket_on_scheduled_pickup_not_allowed
    """
    account = create_account(address="122 Main St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    route, stops = setup_route_in_progress(account["id"], stream="TRASH")
    pickup = schedule_pickup(stops[0]["id"], cart["id"])  # still SCHEDULED
    resp = api.create_weight_ticket(pickup["id"], create_weight_ticket_payload(100, False), DRIVER)
    validate_error(resp, ApiErrorId.ERR_WEIGHT_TICKET_NOT_ALLOWED, 409)


def test_duplicate_stop_sequence_rejected(api):
    """PRD §3.2: "a `sequence`, a 1-based ordinal position that must be at least 1 and
    must be unique within the route; a second stop claiming a `sequence` already present
    on the route is rejected with `ERR_DUPLICATE_SEQUENCE`."

    Design: Corner/validations/duplicate_stop_sequence_rejected
    """
    account = create_account(address="124 Main St")
    route = validate_success(api.create_route(create_route_payload(
        service_date="2026-06-04T00:00:00Z", stream="TRASH", assigned_driver_id="drv-29"), DISPATCHER), 201)
    validate_success(api.create_stop(route["id"], create_stop_payload(account["id"], 1), DISPATCHER), 201)
    resp = api.create_stop(route["id"], create_stop_payload(account["id"], 1), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SEQUENCE, 409)


def test_route_complete_with_pending_stop_rejected(api):
    """PRD §3.2: "the driver completes the route, moving it from `IN_PROGRESS` to the
    terminal `COMPLETED` state — but only when every `Stop` on the route has reached a
    terminal stop state of `SERVICED` or `SKIPPED`; if any stop is still `PENDING` the
    completion is rejected with `ERR_STOPS_PENDING`."

    Design: Corner/validations/route_complete_with_pending_stop_rejected
    """
    account = create_account(address="126 Main St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    route, stops = setup_route_in_progress(account["id"], stream="TRASH", num_stops=2)
    pk1 = schedule_pickup(stops[0]["id"], cart["id"])
    validate_success(api.complete_pickup(pk1["id"], complete_pickup_payload(cart["version"]), DRIVER), 200)
    # stops[1] is still PENDING
    resp = api.complete_route(route["id"], DRIVER)
    validate_error(resp, ApiErrorId.ERR_STOPS_PENDING, 409)


def test_dispatch_route_without_driver_rejected(api):
    """PRD §3.2: "A `Dispatcher` dispatches a `PLANNED` route, moving it to `DISPATCHED`,
    but only when the route has a non-null `assigned_driver_id` and at least one `Stop`;
    a dispatch attempt on a route lacking an assigned driver or having zero stops is
    rejected with `ERR_DRIVER_NOT_ASSIGNED`."

    Design: Corner/validations/dispatch_route_without_driver_rejected
    """
    account = create_account(address="127 Main St")
    route = validate_success(
        api.create_route({"service_date": "2026-06-06T00:00:00Z", "stream": "TRASH"}, DISPATCHER),
        201,
    )
    validate_success(api.create_stop(route["id"], create_stop_payload(account["id"], 1), DISPATCHER), 201)
    resp = api.dispatch_route(route["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_ASSIGNED, 409)


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / transitive_cascade — route cancel skips PENDING stops
# ═══════════════════════════════════════════════════════════════════════════

def test_route_cancel_cascades_pending_stops_to_skipped(api):
    """PRD §3.2: "A dispatcher may instead cancel a route while it is `PLANNED` or
    `DISPATCHED`, transitioning it to the terminal `CANCELLED` state; cancellation
    cascades by driving every `Stop` on the route that is still `PENDING` to `SKIPPED`."

    Design: Difficulty/transitive_cascade/route_cancel_cascades_pending_stops_depth2
    """
    account = create_account(address="17 Fir St")
    route = validate_success(api.create_route(create_route_payload(
        service_date="2026-05-14T00:00:00Z", stream="TRASH", assigned_driver_id="drv-6"), DISPATCHER), 201)
    stop1 = validate_success(api.create_stop(route["id"], create_stop_payload(account["id"], 1), DISPATCHER), 201)
    stop2 = validate_success(api.create_stop(route["id"], create_stop_payload(account["id"], 2), DISPATCHER), 201)
    validate_success(api.dispatch_route(route["id"], DISPATCHER), 200)
    cancelled = validate_success(api.cancel_route(route["id"], DISPATCHER), 200)
    assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"
    s1 = validate_success(api.get_stop(stop1["id"], DISPATCHER), 200)
    s2 = validate_success(api.get_stop(stop2["id"], DISPATCHER), 200)
    assert s1["status"] == "SKIPPED", f"stop1 must be SKIPPED, got {s1['status']}"
    assert s2["status"] == "SKIPPED", f"stop2 must be SKIPPED, got {s2['status']}"


def test_route_cancel_from_planned_skips_stop(api):
    """PRD §3.2: "A dispatcher may instead cancel a route while it is `PLANNED` or
    `DISPATCHED`, transitioning it to the terminal `CANCELLED` state; cancellation
    cascades by driving every `Stop` on the route that is still `PENDING` to `SKIPPED`."

    Design: Difficulty/transitive_cascade/route_cancel_cascades_pending_stops_depth2
    """
    account = create_account(address="17b Fir St")
    route = validate_success(api.create_route(create_route_payload(
        service_date="2026-05-14T00:00:00Z", stream="TRASH", assigned_driver_id="drv-6b"), DISPATCHER), 201)
    stop = validate_success(api.create_stop(route["id"], create_stop_payload(account["id"], 1), DISPATCHER), 201)
    cancelled = validate_success(api.cancel_route(route["id"], DISPATCHER), 200)
    assert cancelled["status"] == "CANCELLED"
    s = validate_success(api.get_stop(stop["id"], DISPATCHER), 200)
    assert s["status"] == "SKIPPED", f"PLANNED-route stop must be SKIPPED, got {s['status']}"


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / cross_entity_state_dependency — pickup complete needs route IN_PROGRESS
# ═══════════════════════════════════════════════════════════════════════════

def test_pickup_complete_requires_route_in_progress(api):
    """PRD §3.3: "The `Driver` **completes** a pickup, setting `outcome` to `COMPLETED`,
    but only when the pickup is still `SCHEDULED`, the pickup's stop's route is
    `IN_PROGRESS`, and the pickup's cart is in `ASSIGNED` or `ACTIVE` status."
    PRD §3.3: "Any pickup-outcome transition attempted from a state other than
    `SCHEDULED`, or against a route or cart not in the required status, is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/pickup_complete_requires_route_in_progress_pickup_to_route
    """
    account = create_account(address="27 Larch St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    route = validate_success(api.create_route(create_route_payload(
        service_date="2026-05-18T00:00:00Z", stream="TRASH", assigned_driver_id="drv-9"), DISPATCHER), 201)
    stop = validate_success(api.create_stop(route["id"], create_stop_payload(account["id"], 1), DISPATCHER), 201)
    pickup = validate_success(api.create_pickup(stop["id"], create_pickup_payload(cart["id"]), DISPATCHER), 201)
    validate_success(api.dispatch_route(route["id"], DISPATCHER), 200)  # DISPATCHED, not started
    resp = api.complete_pickup(pickup["id"], complete_pickup_payload(cart["version"]), DRIVER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    after = validate_success(api.get_pickup(pickup["id"], DRIVER), 200)
    assert after["outcome"] == "SCHEDULED", f"pickup must stay SCHEDULED, got {after['outcome']}"


def test_pickup_complete_succeeds_when_route_in_progress(api):
    """PRD §3.3: "The `Driver` **completes** a pickup, setting `outcome` to `COMPLETED`,
    but only when the pickup is still `SCHEDULED`, the pickup's stop's route is
    `IN_PROGRESS`, and the pickup's cart is in `ASSIGNED` or `ACTIVE` status."

    Design: Difficulty/cross_entity_state_dependency/pickup_complete_requires_route_in_progress_pickup_to_route
    """
    account = create_account(address="27b Larch St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    route, stops = setup_route_in_progress(account["id"], stream="TRASH")
    pickup = schedule_pickup(stops[0]["id"], cart["id"])
    completed = validate_success(
        api.complete_pickup(pickup["id"], complete_pickup_payload(cart["version"]), DRIVER), 200
    )
    assert completed["outcome"] == "COMPLETED", f"expected COMPLETED, got {completed['outcome']}"


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / resource_temporal_overlap — pickup slot per cart per stop
# ═══════════════════════════════════════════════════════════════════════════

def test_pickup_slot_taken_per_cart_per_stop_rejected(api):
    """PRD §3.3: "The system enforces one active pickup per cart per stop: if the stop's
    route already has a non-`CANCELLED` pickup covering the same `cart_id` at that stop,
    the new pickup is rejected with `ERR_PICKUP_SLOT_TAKEN`."

    Design: Difficulty/resource_temporal_overlap/pickup_slot_taken_per_cart_per_stop_rejected
    """
    account = create_account(address="31 Walnut St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    route = validate_success(api.create_route(create_route_payload(
        service_date="2026-05-19T00:00:00Z", stream="TRASH", assigned_driver_id="drv-10"), DISPATCHER), 201)
    stop = validate_success(api.create_stop(route["id"], create_stop_payload(account["id"], 1), DISPATCHER), 201)
    validate_success(api.create_pickup(stop["id"], create_pickup_payload(cart["id"]), DISPATCHER), 201)
    resp = api.create_pickup(stop["id"], create_pickup_payload(cart["id"]), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_PICKUP_SLOT_TAKEN, 409)


def test_pickup_slot_freed_after_cancel(api):
    """PRD §3.3: "A `CANCELLED` pickup frees the slot, allowing a fresh pickup for the
    same cart at that stop."

    Design: Difficulty/resource_temporal_overlap/pickup_slot_taken_per_cart_per_stop_rejected
    """
    account = create_account(address="31b Walnut St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    route = validate_success(api.create_route(create_route_payload(
        service_date="2026-05-19T00:00:00Z", stream="TRASH", assigned_driver_id="drv-10b"), DISPATCHER), 201)
    stop = validate_success(api.create_stop(route["id"], create_stop_payload(account["id"], 1), DISPATCHER), 201)
    pk1 = validate_success(api.create_pickup(stop["id"], create_pickup_payload(cart["id"]), DISPATCHER), 201)
    validate_success(api.cancel_pickup(pk1["id"], DISPATCHER), 200)
    # Slot freed — a fresh pickup for the same cart at the same stop succeeds.
    pk2 = validate_success(api.create_pickup(stop["id"], create_pickup_payload(cart["id"]), DISPATCHER), 201)
    assert pk2["outcome"] == "SCHEDULED", f"expected SCHEDULED, got {pk2['outcome']}"


# ═══════════════════════════════════════════════════════════════════════════
# Corner / state_machines — contamination clear reconciles pickup flag
# ═══════════════════════════════════════════════════════════════════════════

def test_contamination_clear_reconciles_pickup_flag(api):
    """PRD §3.4: "A `Dispatcher` clears an `OPEN` tag, moving it to the terminal
    `CLEARED` state and incrementing the tag's `version`; clearing reconciles the
    pickup's `contaminated` flag back to false only if no other `OPEN` tag remains on
    that pickup."

    Design: Corner/state_machines/contamination_clear_reconciles_pickup_flag
    """
    account = create_account(address="116 Main St")
    cart, route, stop, pickup, ticket = setup_completed_pickup(
        account["id"], stream="TRASH", tare_weight_lbs=0, gross_weight_lbs=120, diverted=False
    )
    tag = validate_success(
        api.create_contamination_tag(pickup["id"], create_contamination_tag_payload("MINOR"), DRIVER), 201
    )
    cleared = validate_success(api.clear_contamination_tag(tag["id"], DISPATCHER), 200)
    assert cleared["status"] == "CLEARED", f"expected CLEARED, got {cleared['status']}"
    pk_after = validate_success(api.get_pickup(pickup["id"], DISPATCHER), 200)
    assert pk_after["contaminated"] is False, (
        f"contaminated must reconcile to false, got {pk_after['contaminated']}"
    )
