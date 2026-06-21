"""Validation precedence, boundary precision, temporal-overlap semantics, the
stand cross-entity gates, and stand-version optimistic concurrency.

Queue A (Difficulty): priority_pair_validation_conflict, boundary_precision_check,
                      cross_entity_state_dependency, resource_temporal_overlap.
Queue B (Corner): validations/*, calculations (staffing/replenishment boundaries),
                  cross_cutting (OCC on ready).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_patron_headers,
    create_venue, create_product, create_event_payload, create_staff_shift_payload,
    create_inventory_lot_payload, create_transfer_payload, create_order_payload,
    create_order_line_payload, create_menu_item_payload, create_patron_payload,
)
from test_helpers.fixtures import (
    create_event, create_stand, create_event_doors_open, create_stand_opened_with_staff,
    create_checked_in_shift, create_lot, create_patron,
    setup_cart_order, setup_placed_order, setup_paid_order, setup_two_stands_one_event,
    current_stand_version,
)

MANAGER = TEST_USERS["manager_headers"]
RUNNER = TEST_USERS["runner_headers"]
OPERATOR = TEST_USERS["operator_headers"]
NON_EXISTENT_EVENT_ID = "00000000-0000-4000-8000-000000000000"


# ===========================================================================
# Queue A — invalid_state_beats_order_unpaid_on_ready
# A CART + UNPAID order readied fails state (not PLACED) AND unpaid; state wins.
# ===========================================================================
def test_ready_cart_unpaid_order_reports_invalid_state(api):
    """PRD §2.8: "Then the state check: the target must be in a state from which
    the requested transition is defined, else ERR_INVALID_STATE. Then the stand
    optimistic-concurrency check (ERR_STALE_STAND_VERSION) on the two endpoints that
    carry a version field. After these come the endpoint-specific business rules
    described throughout Section 3".

    Ready is defined only from PLACED; a CART order fails the state check, which is
    evaluated before the unpaid business rule.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_order_unpaid_on_ready
    """
    state = setup_cart_order(
        line_qtys=(1,),
        product_overrides={"sku": "WATER", "name": "Water", "base_price_cents": 100, "unit_cost_cents": 10},
    )
    sv = current_stand_version(state["stand"]["id"])
    resp = api.ready_order(state["order"]["id"], {"expected_stand_version": sv}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_ready_cart_unpaid_order_returns_409_status(api):
    """PRD §2.8: "the practical consequence of this ordering is that earlier checks
    mask later ones ... and a state-machine violation surfaces before any quantity
    or business check that would also have failed."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_order_unpaid_on_ready
    """
    state = setup_cart_order(
        line_qtys=(1,),
        product_overrides={"sku": "WATER", "name": "Water", "base_price_cents": 100, "unit_cost_cents": 10},
    )
    sv = current_stand_version(state["stand"]["id"])
    resp = api.ready_order(state["order"]["id"], {"expected_stand_version": sv}, OPERATOR)
    assert resp.status_code == 409


# ===========================================================================
# Queue A — forbidden_role_beats_not_found_on_settle
# A StockRunner settling a non-existent event fails auth AND existence; auth wins.
# ===========================================================================
def test_unauthorized_role_on_missing_event_reports_forbidden(api):
    """PRD §2.8: "Role authorization is next, yielding ERR_FORBIDDEN_ROLE. Then
    existence: every resource named in the path or body must exist, validated
    left-to-right in the path, with ERR_NOT_FOUND otherwise."

    A StockRunner is not authorized to settle; authorization precedes existence.

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_not_found_on_settle
    """
    resp = api.settle_event(NON_EXISTENT_EVENT_ID, RUNNER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_unauthorized_role_on_missing_event_returns_403_status(api):
    """PRD §2.8: "an unauthenticated request to a nonexistent resource reports the
    authentication failure, not the missing resource".

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_not_found_on_settle
    """
    resp = api.settle_event(NON_EXISTENT_EVENT_ID, RUNNER)
    assert resp.status_code == 403


# ===========================================================================
# Queue A — staffing_ceiling_boundary_160_vs_161 (exact-multiple case)
# expected_orders_per_hour=160, off-peak -> ceil(160/40)=4.
# ===========================================================================
def test_staffing_exact_multiple_of_throughput_needs_no_extra(api):
    """PRD §3.7: "The base requirement is the stand's expected_orders_per_hour
    divided by a throughput of 40 orders per worker per hour, rounded up to the next
    whole worker (ceiling division)."
    PRD §3.7: "an expected_orders_per_hour that is an exact multiple of 40 needs
    exactly that many base workers and no more".

    160/40 = 4 exactly, off-peak -> required_staff 4.

    Design: Difficulty/boundary_precision_check/staffing_ceiling_boundary_160_vs_161
    """
    base = create_stand_opened_with_staff(stand_overrides={"expected_orders_per_hour": 160})
    stand = validate_success(api.get_stand(base["stand"]["id"], OPERATOR), 200)
    assert stand["required_staff"] == 4, f"expected 4, got {stand['required_staff']}"


def test_staffing_required_staff_recomputed_on_open(api):
    """PRD §3.7: "The stand's required_staff is recomputed whenever the stand opens
    or reopens and whenever the event's peak window toggles."

    A stand opened off-peak with expected_orders_per_hour 160 reports required_staff 4.

    Design: Difficulty/boundary_precision_check/staffing_ceiling_boundary_160_vs_161
    """
    base = create_stand_opened_with_staff(stand_overrides={"expected_orders_per_hour": 160})
    assert base["stand"]["required_staff"] == 4


def test_staffing_above_boundary_161_rounds_up(api):
    """PRD §3.7: "whereas one unit above a multiple of 40 needs one more. A
    throughput of 40 means 80 expected orders per hour calls for a base of two
    workers, and 81 expected orders per hour calls for three."

    161/40 = 4.025, ceil = 5 off-peak.

    Design: Corner/calculations/staffing_above_boundary_161_rounds_up
    """
    base = create_stand_opened_with_staff(stand_overrides={"expected_orders_per_hour": 161})
    stand = validate_success(api.get_stand(base["stand"]["id"], OPERATOR), 200)
    assert stand["required_staff"] == 5, f"expected 5, got {stand['required_staff']}"


# ===========================================================================
# Queue A — replenishment_suggestion_at_reorder_point_inclusive
# on_hand == reorder_point (60==60) triggers a suggestion of par-on_hand=140.
# ===========================================================================
def _stand_with_lot(received_qty, reorder_point, par_level=200):
    venue = create_venue()
    product = create_product(venue["id"], sku="BUN", name="Bun", base_price_cents=0, unit_cost_cents=30, perishable=True)
    event = create_event(venue["id"])
    stand = create_stand(event["id"])
    create_lot(stand["id"], product["id"], received_qty=received_qty, unit_cost_cents=30,
               par_level=par_level, reorder_point=reorder_point)
    return stand, product


def test_replenishment_suggested_at_reorder_point_inclusive(api):
    """PRD §3.7: "when on_hand is at or below that reorder point — emits an entry
    naming the product_id, the on_hand, and a suggested_qty equal to the par level
    minus the on-hand."
    PRD §3.7: "The trigger is inclusive: a product whose on-hand exactly equals its
    reorder point is suggested".

    on_hand 60 == reorder_point 60 -> suggested_qty = 200-60 = 140.

    Design: Difficulty/boundary_precision_check/replenishment_suggestion_at_reorder_point_inclusive
    """
    stand, product = _stand_with_lot(received_qty=60, reorder_point=60, par_level=200)
    resp = api.get_replenishment_suggestions(stand["id"], RUNNER)
    data = validate_success(resp, 200)
    entries = [e for e in data if e["product_id"] == product["id"]]
    assert len(entries) == 1, f"expected one suggestion, got {data}"
    assert entries[0]["on_hand"] == 60
    assert entries[0]["suggested_qty"] == 140


def test_replenishment_suggestion_reports_on_hand_value(api):
    """PRD §3.7: "For each product stocked at the stand, the advisory sums
    remaining_qty across the stand's ACTIVE lots of that product to get the
    product's on_hand".

    Design: Difficulty/boundary_precision_check/replenishment_suggestion_at_reorder_point_inclusive
    """
    stand, product = _stand_with_lot(received_qty=60, reorder_point=60, par_level=200)
    data = validate_success(api.get_replenishment_suggestions(stand["id"], RUNNER), 200)
    entries = [e for e in data if e["product_id"] == product["id"]]
    assert entries and entries[0]["on_hand"] == 60


def test_replenishment_not_suggested_above_reorder_point(api):
    """PRD §3.7: "while one unit above the reorder point is not."

    on_hand 61 > reorder_point 60 -> no suggestion entry for the product.

    Design: Corner/calculations/replenishment_not_suggested_above_reorder_point
    """
    stand, product = _stand_with_lot(received_qty=61, reorder_point=60, par_level=200)
    data = validate_success(api.get_replenishment_suggestions(stand["id"], RUNNER), 200)
    entries = [e for e in data if e["product_id"] == product["id"]]
    assert entries == [], f"expected no suggestion, got {entries}"


# ===========================================================================
# Queue A — stand_open_requires_event_doors_open_pair_stand_event
# Event still SCHEDULED -> opening a (staffed) stand is rejected ERR_EVENT_NOT_OPENABLE.
# ===========================================================================
def test_open_stand_under_scheduled_event_rejected(api):
    """PRD §3.3: "the parent event must be in DOORS_OPEN or IN_PROGRESS — opening a
    stand whose event has not yet opened its doors (or has already settled) is
    rejected with ERR_EVENT_NOT_OPENABLE."

    Design: Difficulty/cross_entity_state_dependency/stand_open_requires_event_doors_open_pair_stand_event
    """
    venue = create_venue()
    event = create_event(venue["id"])  # left SCHEDULED
    stand = create_stand(event["id"])
    create_checked_in_shift(stand["id"])
    resp = api.open_stand(stand["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_OPENABLE.value, 409)


def test_open_stand_under_scheduled_event_returns_409(api):
    """PRD §3.3: "Opening a stand moves it from CLOSED to OPEN ... Opening carries
    two business preconditions beyond the state check. First, the parent event must
    be in DOORS_OPEN or IN_PROGRESS".

    Design: Difficulty/cross_entity_state_dependency/stand_open_requires_event_doors_open_pair_stand_event
    """
    venue = create_venue()
    event = create_event(venue["id"])
    stand = create_stand(event["id"])
    create_checked_in_shift(stand["id"])
    resp = api.open_stand(stand["id"], OPERATOR)
    assert resp.status_code == 409


# ===========================================================================
# Queue A — order_place_requires_stand_open_pair_order_stand
# Stand SUSPENDED -> placing a line-complete CART order rejected ERR_STAND_NOT_OPEN.
# ===========================================================================
def test_place_order_at_suspended_stand_rejected(api):
    """PRD §3.8: "Placement requires that the order have at least one line, that the
    order's stand be OPEN (a SUSPENDED or CLOSED stand is rejected with
    ERR_STAND_NOT_OPEN)".

    Design: Difficulty/cross_entity_state_dependency/order_place_requires_stand_open_pair_order_stand
    """
    state = setup_cart_order(
        line_qtys=(1,),
        product_overrides={"sku": "WATER", "name": "Water", "base_price_cents": 100, "unit_cost_cents": 10},
    )
    validate_success(api.suspend_stand(state["stand"]["id"], OPERATOR), 200)
    resp = api.place_order(state["order"]["id"], state["patron_headers"])
    validate_error(resp, ApiErrorId.ERR_STAND_NOT_OPEN.value, 409)


def test_place_order_at_suspended_stand_returns_409(api):
    """PRD §3.8: "Placing the order moves its fulfillment_status from CART to PLACED
    and recomputes the order totals from its current lines. Placement requires ...
    that the order's stand be OPEN (a SUSPENDED or CLOSED stand is rejected with
    ERR_STAND_NOT_OPEN)".

    Design: Difficulty/cross_entity_state_dependency/order_place_requires_stand_open_pair_order_stand
    """
    state = setup_cart_order(
        line_qtys=(1,),
        product_overrides={"sku": "WATER", "name": "Water", "base_price_cents": 100, "unit_cost_cents": 10},
    )
    validate_success(api.suspend_stand(state["stand"]["id"], OPERATOR), 200)
    resp = api.place_order(state["order"]["id"], state["patron_headers"])
    assert resp.status_code == 409


# ===========================================================================
# Queue A — event_window_closed_interval_boundary_touch_rejected
# Second event whose doors_time == first event's end_time is rejected (closed interval).
# ===========================================================================
def test_event_window_boundary_touch_is_overlap(api):
    """PRD §3.2: "Because the interval is treated as closed on both ends, a shared
    boundary instant counts as an overlap — if one event's end_time equals another's
    doors_time, that is a collision and the creation is rejected with
    ERR_EVENT_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/event_window_closed_interval_boundary_touch_rejected
    """
    venue = create_venue()
    validate_success(api.create_event(create_event_payload(
        venue["id"], name="EvtA", doors_time="2026-06-14T18:00:00.000Z", end_time="2026-06-14T22:00:00.000Z"), MANAGER), 201)
    resp = api.create_event(create_event_payload(
        venue["id"], name="EvtB", doors_time="2026-06-14T22:00:00.000Z", end_time="2026-06-15T02:00:00.000Z"), MANAGER)
    validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP.value, 409)


def test_event_window_overlap_returns_409(api):
    """PRD §3.2: "When a new event is created, its closed operating interval from
    doors_time through end_time must not overlap that of any other non-SETTLED event
    at the same venue."

    Design: Difficulty/resource_temporal_overlap/event_window_closed_interval_boundary_touch_rejected
    """
    venue = create_venue()
    validate_success(api.create_event(create_event_payload(
        venue["id"], name="EvtA2", doors_time="2026-06-18T18:00:00.000Z", end_time="2026-06-18T22:00:00.000Z"), MANAGER), 201)
    resp = api.create_event(create_event_payload(
        venue["id"], name="EvtB2", doors_time="2026-06-18T22:00:00.000Z", end_time="2026-06-19T02:00:00.000Z"), MANAGER)
    assert resp.status_code == 409


# ===========================================================================
# Queue A — staff_shift_half_open_interval_boundary_touch_allowed
# Back-to-back shift whose shift_start == prior shift_end is allowed (half-open).
# ===========================================================================
def test_staff_shift_back_to_back_boundary_allowed(api):
    """PRD §3.7: "Because the interval is half-open, a back-to-back pair where a
    prior shift's shift_end equals the new shift's shift_start does not overlap and
    is allowed."

    Design: Difficulty/resource_temporal_overlap/staff_shift_half_open_interval_boundary_touch_allowed
    """
    venue = create_venue()
    event = create_event(venue["id"], doors_time="2026-06-14T17:00:00.000Z", end_time="2026-06-15T03:00:00.000Z")
    stand = create_stand(event["id"])
    validate_success(api.create_staff_shift(create_staff_shift_payload(
        stand["id"], worker_name="Mia", shift_start="2026-06-14T18:00:00.000Z", shift_end="2026-06-14T22:00:00.000Z"), MANAGER), 201)
    resp = api.create_staff_shift(create_staff_shift_payload(
        stand["id"], worker_name="Mia", shift_start="2026-06-14T22:00:00.000Z", shift_end="2026-06-15T02:00:00.000Z"), MANAGER)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_staff_shift_back_to_back_returns_201(api):
    """PRD §3.7: "Shifts for the same worker_name may not overlap: a new shift's
    half-open interval from shift_start up to (but not including) shift_end must not
    overlap any non-CANCELLED shift for the same worker, and an overlap is rejected
    with ERR_SHIFT_OVERLAP."

    The boundary-touch pair does not overlap -> 201 (no ERR_SHIFT_OVERLAP).

    Design: Difficulty/resource_temporal_overlap/staff_shift_half_open_interval_boundary_touch_allowed
    """
    venue = create_venue()
    event = create_event(venue["id"], doors_time="2026-06-20T17:00:00.000Z", end_time="2026-06-21T03:00:00.000Z")
    stand = create_stand(event["id"])
    validate_success(api.create_staff_shift(create_staff_shift_payload(
        stand["id"], worker_name="Nia", shift_start="2026-06-20T18:00:00.000Z", shift_end="2026-06-20T22:00:00.000Z"), MANAGER), 201)
    resp = api.create_staff_shift(create_staff_shift_payload(
        stand["id"], worker_name="Nia", shift_start="2026-06-20T22:00:00.000Z", shift_end="2026-06-21T02:00:00.000Z"), MANAGER)
    assert resp.status_code == 201


# ===========================================================================
# Queue B — validations
# ===========================================================================
def test_open_stand_with_no_staff_returns_understaffed(api):
    """PRD §3.3: "the stand must already have at least one checked-in worker,
    meaning its assigned_staff_count is at least 1; attempting to open an unstaffed
    stand is rejected with ERR_UNDERSTAFFED_OPEN."

    Design: Corner/validations/open_stand_with_no_staff_returns_understaffed
    """
    base = create_event_doors_open(create_venue()["id"])
    resp = api.open_stand(base["stand"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_UNDERSTAFFED_OPEN.value, 409)


def test_place_order_insufficient_stock_returns_error(api):
    """PRD §3.8: "for each line the stand have enough on-hand — the summed
    remaining_qty across the stand's ACTIVE lots of the line's product must be at
    least the line's quantity, or the placement is rejected with
    ERR_INSUFFICIENT_STOCK."

    Line qty 5 vs a 2-unit lot -> ERR_INSUFFICIENT_STOCK.

    Design: Corner/validations/place_order_insufficient_stock_returns_error
    """
    state = setup_cart_order(
        line_qtys=(5,),
        product_overrides={"sku": "WATER", "name": "Water", "base_price_cents": 100, "unit_cost_cents": 10},
        lot_overrides={"received_qty": 2, "unit_cost_cents": 10, "par_level": 10, "reorder_point": 2},
    )
    resp = api.place_order(state["order"]["id"], state["patron_headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value, 409)


def test_transfer_dispatch_qty_exceeds_on_hand_returns_error(api):
    """PRD §3.5: "only when the source stand's on-hand for the product — the summed
    remaining_qty across its ACTIVE lots of that product — is at least qty; a
    dispatch whose qty exceeds that source on-hand is rejected with
    ERR_TRANSFER_QTY_EXCEEDS_ONHAND."

    Dispatch 200 with source on-hand 100 -> ERR_TRANSFER_QTY_EXCEEDS_ONHAND.

    Design: Corner/validations/transfer_dispatch_qty_exceeds_onhand_returns_error
    """
    base = setup_two_stands_one_event(source_lot_qty=100, lot_unit_cost=30)
    transfer = validate_success(api.create_transfer(create_transfer_payload(
        base["stand_a"]["id"], base["stand_b"]["id"], base["product"]["id"], qty=200), RUNNER), 201)
    sa_v = validate_success(api.get_stand(base["stand_a"]["id"], RUNNER), 200)["version"]
    resp = api.dispatch_transfer(transfer["id"], {"expected_from_stand_version": sa_v}, RUNNER)
    validate_error(resp, ApiErrorId.ERR_TRANSFER_QTY_EXCEEDS_ONHAND.value, 409)


def test_cross_event_transfer_rejected(api):
    """PRD §3.5: "The two stands must belong to the same event and must be distinct;
    a transfer whose stands are in different events or are the same stand is rejected
    with ERR_CROSS_EVENT_TRANSFER".

    Design: Corner/validations/cross_event_transfer_rejected
    """
    venue = create_venue()
    product = create_product(venue["id"], sku="BUN", name="Bun", base_price_cents=0, unit_cost_cents=30)
    event1 = create_event(venue["id"], name="E1", doors_time="2026-07-21T18:00:00.000Z", end_time="2026-07-21T23:00:00.000Z")
    event2 = create_event(venue["id"], name="E2", doors_time="2026-07-22T18:00:00.000Z", end_time="2026-07-22T23:00:00.000Z")
    stand_a = create_stand(event1["id"], name="SA1")
    stand_b = create_stand(event2["id"], name="SB2")
    resp = api.create_transfer(create_transfer_payload(stand_a["id"], stand_b["id"], product["id"], qty=10), RUNNER)
    validate_error(resp, ApiErrorId.ERR_CROSS_EVENT_TRANSFER.value, 422)


def test_patron_cannot_cancel_another_patrons_order(api):
    """PRD §2.1: "A Patron attempting to act on an order whose patron_id is not
    their own is rejected with ERR_NOT_ORDER_OWNER."

    Design: Corner/validations/patron_cannot_cancel_another_patrons_order
    """
    # P1 owns a PLACED order; ownership (priority 4) is checked before state (priority 5).
    state = setup_placed_order(line_qtys=(1,))
    other = create_patron(display_name="P2")
    resp = api.cancel_order(state["order"]["id"], make_patron_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_ORDER_OWNER.value, 403)


def test_settle_with_open_stand_returns_not_settleable(api):
    """PRD §3.3: "Settlement is permitted only while the event is IN_PROGRESS, only
    when every stand of the event is in status CLOSED, and only when no order of the
    event sits in fulfillment status PLACED or READY — an unsettleable event, with
    any non-CLOSED stand or any unfulfilled order, is rejected with
    ERR_EVENT_NOT_SETTLEABLE."

    Design: Corner/validations/settle_with_open_stand_returns_not_settleable
    """
    base = create_stand_opened_with_staff()
    validate_success(api.open_peak_window(base["event"]["id"], MANAGER), 200)  # -> IN_PROGRESS, stand still OPEN
    resp = api.settle_event(base["event"]["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_SETTLEABLE.value, 409)


# ===========================================================================
# Queue B — cross_cutting / OCC on ready
# ===========================================================================
def test_ready_with_stale_stand_version_rejected(api):
    """PRD §2.7: "A ready request must carry expected_stand_version ... If that
    value does not match the stand's current version ... the ready request is
    rejected with ERR_STALE_STAND_VERSION (HTTP 412), preventing two fulfilments
    from drawing the same units."

    expected_stand_version one behind live -> ERR_STALE_STAND_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_stand_version_on_ready
    """
    state = setup_paid_order(
        line_qtys=(1,),
        product_overrides={"sku": "WATER", "name": "Water", "base_price_cents": 100, "unit_cost_cents": 10},
    )
    live = current_stand_version(state["stand"]["id"])
    resp = api.ready_order(state["order"]["id"], {"expected_stand_version": live - 1}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_STALE_STAND_VERSION.value, 412)


def test_successful_ready_increments_stand_version(api):
    """PRD §2.7: "A successful ready increments Stand.version by one."
    PRD §3.8: "Readying an order is performed by a StandOperator and moves the
    fulfillment_status from PLACED to READY".

    Design: Corner/cross_cutting_complexity_layers/occ_stand_version_increments_on_ready
    """
    state = setup_paid_order(
        line_qtys=(1,),
        product_overrides={"sku": "WATER", "name": "Water", "base_price_cents": 100, "unit_cost_cents": 10},
    )
    live = current_stand_version(state["stand"]["id"])
    order = validate_success(api.ready_order(state["order"]["id"], {"expected_stand_version": live}, OPERATOR), 200)
    assert order["fulfillment_status"] == "READY"
    after = validate_success(api.get_stand(state["stand"]["id"], OPERATOR), 200)
    assert after["version"] == live + 1, f"expected {live + 1}, got {after['version']}"
