"""Fulfillment and payment guards: validation-priority precedence (state>safety, safety>
constraint), fusti-posture gating, expired-fusti and insufficient-volume errors."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_member, create_bulk_product, create_fusti, create_order, pay_order, fulfill_order,
    set_clock, refill_line, make_customer_headers, get_success_data, TEST_USERS,
)

STAFF = TEST_USERS["shop_staff_headers"]
INV = TEST_USERS["inventory_manager_headers"]


def _fulfilled_short_shelf_then_expired(api):
    """Fulfil a 30d-shelf order at 2026-06-20, then advance clock past best-by to 2026-07-15."""
    set_clock(api, "2026-06-15T00:00:00Z")
    member = create_member(api)
    product = create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=30)
    fusti = create_fusti(api, product["id"], capacity_ml=10000, initial_volume_ml=10000,
                         reorder_point_ml=1000, harvest_date="2026-06-01T00:00:00Z")
    order = create_order(api, member, [refill_line(product["id"], 100)])
    order = pay_order(api, member, order)
    set_clock(api, "2026-06-20T00:00:00Z")
    order = fulfill_order(api, order)  # first fulfill succeeds
    set_clock(api, "2026-07-15T00:00:00Z")
    return member, product, fusti, order


# ── Difficulty: priority_pair_validation_conflict / state_beats_safety_on_second_fulfill ──

def test_second_fulfill_returns_state_error_not_expired(api):
    """PRD §3.5: "Fulfillment is performed by `ShopStaff` on an order whose `fulfillment_status`
    is `RESERVED`, with a matching `expected_order_version`; a wrong state yields
    `ERR_INVALID_STATE` and a wrong version yields `ERR_STALE_VERSION`."
    PRD §2.10: "Only after those pass does the system evaluate state legality ... then the
    optimistic-concurrency version match, then structural body validation ... then — on
    fulfillment — the past-best-by guard ahead of the vessel-posture guard".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_second_fulfill
    """
    member, product, fusti, order = _fulfilled_short_shelf_then_expired(api)
    resp = api.fulfill_order(order["id"], {"expected_order_version": order["version"]}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_error_wins_even_though_fusti_is_past_best_by(api):
    """PRD §2.10: "Only after those pass does the system evaluate state legality (whether the
    requested transition is defined from the resource's current state), then the
    optimistic-concurrency version match, then structural body validation ... then — on
    fulfillment — the past-best-by guard ahead of the vessel-posture guard".
    PRD §3.2: "The vessel also reports `is_past_best_by`, which is true exactly when the logical
    now is at or after the best-by date."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_second_fulfill
    """
    member, product, fusti, order = _fulfilled_short_shelf_then_expired(api)
    fusti_now = validate_success(api.get_fusti(fusti["id"], INV))
    assert fusti_now["is_past_best_by"] is True, "safety condition must genuinely hold"
    resp = api.fulfill_order(order["id"], {"expected_order_version": order["version"]}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ── Difficulty: priority_pair_validation_conflict / safety_beats_constraint_on_pay ──

def _allergen_and_insufficient_volume_order(api, allergen):
    member = create_member(api, allergen_restrictions=[allergen])
    product = create_bulk_product(api, price_per_ml_cents=0.50, shelf_life_days=540,
                                  allergens=[allergen])
    create_fusti(api, product["id"], capacity_ml=200, initial_volume_ml=100,
                 reorder_point_ml=50, harvest_date="2026-06-01T00:00:00Z")
    order = create_order(api, member, [refill_line(product["id"], 5000)])
    return member, order


def test_allergen_conflict_wins_over_insufficient_volume_tree_nut(api):
    """PRD §3.4: "No line's product may declare an allergen that intersects the member's
    `allergen_restrictions`; a conflict is rejected with `ERR_ALLERGEN_CONFLICT`."
    PRD §2.10: "then allergen safety, then — on fulfillment — the past-best-by guard ahead of the
    vessel-posture guard, then — on booking — station buffer adjacency ahead of member
    double-booking ahead of the future-start guard, then wholesale-approval status, then
    bulk-volume availability".

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_pay
    """
    member, order = _allergen_and_insufficient_volume_order(api, "TREE_NUT")
    resp = api.pay_order(order["id"], {"expected_order_version": order["version"]},
                         make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_CONFLICT.value)


def test_allergen_conflict_wins_over_insufficient_volume_sulfites(api):
    """PRD §3.4: "No line's product may declare an allergen that intersects the member's
    `allergen_restrictions`; a conflict is rejected with `ERR_ALLERGEN_CONFLICT`."
    PRD §2.10: "then allergen safety, then — on fulfillment — the past-best-by guard ahead of the
    vessel-posture guard, then — on booking — station buffer adjacency ahead of member
    double-booking ahead of the future-start guard, then wholesale-approval status, then
    bulk-volume availability".

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_pay
    """
    member, order = _allergen_and_insufficient_volume_order(api, "SULFITES")
    resp = api.pay_order(order["id"], {"expected_order_version": order["version"]},
                         make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_CONFLICT.value)


# ── Difficulty: cross_entity_state_dependency / fulfill_requires_reserved_fusti_in_service ──

def _paid_refill_then_transition_fusti(api, actions):
    member = create_member(api)
    product = create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=540)
    fusti = create_fusti(api, product["id"], capacity_ml=10000, initial_volume_ml=10000,
                         reorder_point_ml=2000, harvest_date="2026-06-01T00:00:00Z")
    order = create_order(api, member, [refill_line(product["id"], 1000)])
    order = pay_order(api, member, order)
    for action in actions:
        get_success_data(api.transition_fusti(fusti["id"], {"action": action}, INV))
    return member, order


def test_fulfill_rejected_when_reserved_fusti_quarantined(api):
    """PRD §3.5: "if any such vessel is not in `IN_SERVICE` or `LOW` posture (that is, it has
    become `QUARANTINED`, `EMPTY`, or `RETIRED`), fulfillment is rejected with
    `ERR_FUSTI_QUARANTINED`."

    Design: Difficulty/cross_entity_state_dependency/fulfill_requires_reserved_fusti_in_service
    """
    member, order = _paid_refill_then_transition_fusti(api, ["QUARANTINE"])
    resp = api.fulfill_order(order["id"], {"expected_order_version": order["version"]}, STAFF)
    validate_error(resp, ApiErrorId.ERR_FUSTI_QUARANTINED.value)


def test_fulfill_rejected_when_reserved_fusti_retired(api):
    """PRD §3.5: "if any such vessel is not in `IN_SERVICE` or `LOW` posture (that is, it has
    become `QUARANTINED`, `EMPTY`, or `RETIRED`), fulfillment is rejected with
    `ERR_FUSTI_QUARANTINED`."

    Design: Difficulty/cross_entity_state_dependency/fulfill_requires_reserved_fusti_in_service
    """
    member, order = _paid_refill_then_transition_fusti(api, ["QUARANTINE", "RETIRE"])
    resp = api.fulfill_order(order["id"], {"expected_order_version": order["version"]}, STAFF)
    validate_error(resp, ApiErrorId.ERR_FUSTI_QUARANTINED.value)


# ── Corner: errors / fulfill_expired_fusti_returns_expired ──

def test_fulfill_past_best_by_fusti_returns_expired(api):
    """PRD §3.5: "Before anything is committed, every refill line's held vessel is re-checked:
    if any such vessel is past its best-by, fulfillment is rejected with `ERR_FUSTI_EXPIRED`".

    Design: Corner/errors/fulfill_expired_fusti_returns_expired
    """
    set_clock(api, "2026-06-20T00:00:00Z")
    member = create_member(api)
    product = create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=30)
    create_fusti(api, product["id"], capacity_ml=10000, initial_volume_ml=10000,
                 reorder_point_ml=1000, harvest_date="2026-06-01T00:00:00Z")
    order = create_order(api, member, [refill_line(product["id"], 100)])
    order = pay_order(api, member, order)
    set_clock(api, "2026-07-15T00:00:00Z")  # best_by 2026-07-01 now passed
    resp = api.fulfill_order(order["id"], {"expected_order_version": order["version"]}, STAFF)
    validate_error(resp, ApiErrorId.ERR_FUSTI_EXPIRED.value)


# ── Corner: errors / pay_insufficient_volume_returns_error ──

def test_pay_rejected_when_no_fusti_has_enough_volume(api):
    """PRD §3.4: "The candidates are the vessels for the line's product that are `IN_SERVICE` or
    `LOW`, are not past their best-by, and have an `available_volume_ml` of at least the line's
    `volume_ml`; ... If no candidate qualifies, the payment is rejected with
    `ERR_INSUFFICIENT_VOLUME`."

    Design: Corner/errors/pay_insufficient_volume_returns_error
    """
    member = create_member(api)
    product = create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=540)
    create_fusti(api, product["id"], capacity_ml=200, initial_volume_ml=100,
                 reorder_point_ml=50, harvest_date="2026-06-01T00:00:00Z")
    order = create_order(api, member, [refill_line(product["id"], 5000)])
    resp = api.pay_order(order["id"], {"expected_order_version": order["version"]},
                         make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_VOLUME.value)
