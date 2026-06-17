"""Shop-day capacity, fulfillment legs, conflicts, cross-entity gating, settlement.

The aggregate-capacity pool and its FULL boundary, the half-open delivery-window
conflict, window/duplicate-day validations, the materials-outstanding and
production-not-complete cross-entity gates, validation-priority conflicts, and the
settlement-mismatch gate.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_line_item_payload,
    register_customer, register_fabric_sku, register_shop_day,
    open_intake_work_order, create_approved_order, create_awaiting_approval_order,
    create_in_production_order, create_ready_for_fulfillment_order,
    place_material_order, book_production_leg, complete_production_leg,
    complete_pickup_or_delivery,
    reupholstery_line_item, get_work_order, current_version, approve_order,
    make_customer_headers, factories,
    TEST_USERS,
)

CLERK = TEST_USERS["intake_clerk_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]


# ---------------------------------------------------------------------------
# Shop capacity boundary — booked == capacity flips to FULL (inclusive >=)
# ---------------------------------------------------------------------------
def test_shop_capacity_exact_equals_is_full_inclusive(api):
    """PRD §3.6: "On a successful booking, the day's `booked_hours` increases by the order's
    labor sum, and if `booked_hours` then reaches or exceeds `labor_capacity_hours` the day
    flips to `FULL` (the boundary where booked exactly equals capacity is `FULL`)."

    Design: Difficulty/boundary_precision_check/shop_capacity_exact_equals_is_full_inclusive
    """
    cust, wo, est, _ = create_awaiting_approval_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="Strip & sand", yardage_required=0, labor_hours=8)],
    )
    approve_order(cust, wo["id"], 20000)
    day = register_shop_day("2026-04-15", 8)
    book_production_leg(wo["id"], day["id"])
    day_after = validate_success(api.get_shop_day(day["id"], MANAGER), 200)
    assert day_after["booked_hours"] == 8
    assert day_after["status"] == "FULL"
    assert get_work_order(wo["id"])["status"] == "IN_PRODUCTION"


def test_shop_capacity_below_capacity_stays_open(api):
    """PRD §3.6: "if `booked_hours` then reaches or exceeds `labor_capacity_hours` the day
    flips to `FULL` (the boundary where booked exactly equals capacity is `FULL`)."

    Design: Difficulty/boundary_precision_check/shop_capacity_exact_equals_is_full_inclusive
    """
    cust, wo, est, _ = create_awaiting_approval_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="Strip 7h", yardage_required=0, labor_hours=7)],
    )
    approve_order(cust, wo["id"], 20000)
    day = register_shop_day("2026-04-16", 8)
    book_production_leg(wo["id"], day["id"])
    day_after = validate_success(api.get_shop_day(day["id"], MANAGER), 200)
    assert day_after["booked_hours"] == 7  # 7 < 8 capacity
    assert day_after["status"] == "OPEN"


def test_shopday_aggregate_capacity_overlap_rejected(api):
    """PRD §3.6: "the shop day is treated as an aggregate capacity pool: a `PRODUCTION` leg
    may not book if the cumulative booked labor hours across all of the day's non-cancelled
    production legs would exceed `labor_capacity_hours`, and it may not book onto a day that
    is `FULL` or `CLOSED`; any of these is rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/shopday_aggregate_capacity_overlap_rejected
    """
    day = register_shop_day("2026-05-10", 6)
    # first order books 4h
    cust1, wo1, _, _ = create_awaiting_approval_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="Job A", yardage_required=0, labor_hours=4)],
    )
    approve_order(cust1, wo1["id"], 8000)
    book_production_leg(wo1["id"], day["id"])
    # second order needs 5h -> 4+5=9 > 6
    cust2, wo2, _, _ = create_awaiting_approval_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="Job B", yardage_required=0, labor_hours=5)],
    )
    approve_order(cust2, wo2["id"], 10000)
    res = api.create_fulfillment_leg(
        factories.create_fulfillment_leg_payload(wo2["id"], "PRODUCTION", shop_day_id=day["id"]),
        MANAGER)
    validate_error(res, "ERR_CAPACITY_EXCEEDED", expected_status=409)
    day_after = validate_success(api.get_shop_day(day["id"], MANAGER), 200)
    assert day_after["booked_hours"] == 4


def test_shopday_capacity_pool_accumulates_within_capacity(api):
    """PRD §3.6: "A production booking consumes day capacity equal to the order's total
    labor — the sum of `labor_hours` across the order's line items."
    PRD §3.6: "On a successful booking, the day's `booked_hours` increases by the order's
    labor sum, and if `booked_hours` then reaches or exceeds `labor_capacity_hours` the day
    flips to `FULL` (the boundary where booked exactly equals capacity is `FULL`)."

    Design: Difficulty/resource_temporal_overlap/shopday_aggregate_capacity_overlap_rejected
    """
    day = register_shop_day("2026-05-11", 10)
    cust1, wo1, _, _ = create_awaiting_approval_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="Job A2", yardage_required=0, labor_hours=4)],
    )
    approve_order(cust1, wo1["id"], 8000)
    book_production_leg(wo1["id"], day["id"])
    cust2, wo2, _, _ = create_awaiting_approval_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="Job B2", yardage_required=0, labor_hours=5)],
    )
    approve_order(cust2, wo2["id"], 10000)
    # 4 + 5 = 9 <= 10, so the second booking succeeds and the pool accumulates.
    book_production_leg(wo2["id"], day["id"])
    day_after = validate_success(api.get_shop_day(day["id"], MANAGER), 200)
    assert day_after["booked_hours"] == 9
    assert day_after["status"] == "OPEN"


def test_production_leg_onto_closed_shop_day_returns_capacity_exceeded(api):
    """PRD §3.6: "Closing a shop day is permitted from `OPEN` or `FULL` and moves it to
    `CLOSED`, after which no further production may book onto it."
    PRD §3.6: "it may not book onto a day that is `FULL` or `CLOSED`; any of these is
    rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Corner/state_machines/production_leg_onto_closed_shop_day_returns_capacity_exceeded
    """
    day = register_shop_day("2026-07-04", 20)
    closed = validate_success(api.close_shop_day(day["id"], MANAGER), 200)
    assert closed["status"] == "CLOSED"
    cust, wo, _, _ = create_approved_order(
        service_type="REPAIR", deposit_amount_cents=5000,
        line_items=[create_line_item_payload(piece_label="P", yardage_required=0, labor_hours=2)],
    )
    res = api.create_fulfillment_leg(
        factories.create_fulfillment_leg_payload(wo["id"], "PRODUCTION", shop_day_id=day["id"]),
        MANAGER)
    validate_error(res, "ERR_CAPACITY_EXCEEDED", expected_status=409)


# ---------------------------------------------------------------------------
# Delivery window conflict — half-open geometric overlap
# ---------------------------------------------------------------------------
def test_delivery_window_halfopen_geometric_overlap_rejected(api):
    """PRD §3.6: "a new `DELIVERY` leg's window may not overlap the window of any existing
    non-cancelled `DELIVERY` leg. Overlap is judged on half-open intervals — two delivery
    windows conflict when the existing window's start is before the new window's end and the
    new window's start is before the existing window's end; windows that merely touch at an
    endpoint, where one window's start equals the other's end, do not conflict. A conflicting
    delivery window is rejected with `ERR_DELIVERY_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/delivery_window_halfopen_geometric_overlap_rejected
    """
    # Order X: ready, then a DELIVERY leg 11:00-13:00
    _, wox, _, _, _ = create_ready_for_fulfillment_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="X piece", yardage_required=0, labor_hours=3)],
        deposit_amount_cents=6000, shop_day_date="2026-05-12", shop_capacity=20,
    )
    validate_success(api.create_fulfillment_leg(
        factories.create_fulfillment_leg_payload(
            wox["id"], "DELIVERY",
            scheduled_window_start="2026-05-20T11:00:00Z",
            scheduled_window_end="2026-05-20T13:00:00Z"), MANAGER), 201)
    # Order Y: ready on a different day, then a DELIVERY leg 10:00-12:00 overlapping X
    _, woy, _, _, _ = create_ready_for_fulfillment_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="Y piece", yardage_required=0, labor_hours=3)],
        deposit_amount_cents=6000, shop_day_date="2026-05-13", shop_capacity=20,
    )
    res = api.create_fulfillment_leg(
        factories.create_fulfillment_leg_payload(
            woy["id"], "DELIVERY",
            scheduled_window_start="2026-05-20T10:00:00Z",
            scheduled_window_end="2026-05-20T12:00:00Z"), MANAGER)
    validate_error(res, "ERR_DELIVERY_WINDOW_CONFLICT", expected_status=409)


def test_delivery_window_touching_endpoint_does_not_conflict(api):
    """PRD §3.6: "windows that merely touch at an endpoint, where one window's start equals
    the other's end, do not conflict. A conflicting delivery window is rejected with
    `ERR_DELIVERY_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/delivery_window_halfopen_geometric_overlap_rejected
    """
    # Order X: ready, DELIVERY 11:00-13:00
    _, wox, _, _, _ = create_ready_for_fulfillment_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="X piece2", yardage_required=0, labor_hours=3)],
        deposit_amount_cents=6000, shop_day_date="2026-05-14", shop_capacity=20,
    )
    validate_success(api.create_fulfillment_leg(
        factories.create_fulfillment_leg_payload(
            wox["id"], "DELIVERY",
            scheduled_window_start="2026-05-21T11:00:00Z",
            scheduled_window_end="2026-05-21T13:00:00Z"), MANAGER), 201)
    # Order Y: DELIVERY 13:00-15:00 — touches X's end exactly, must NOT conflict
    _, woy, _, _, _ = create_ready_for_fulfillment_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="Y piece2", yardage_required=0, labor_hours=3)],
        deposit_amount_cents=6000, shop_day_date="2026-05-15", shop_capacity=20,
    )
    leg = validate_success(api.create_fulfillment_leg(
        factories.create_fulfillment_leg_payload(
            woy["id"], "DELIVERY",
            scheduled_window_start="2026-05-21T13:00:00Z",
            scheduled_window_end="2026-05-21T15:00:00Z"), MANAGER), 201)
    assert leg["kind"] == "DELIVERY"


def test_delivery_leg_inverted_window_returns_invalid_window(api):
    """PRD §3.6: "a `PICKUP` or `DELIVERY` leg leaves `shop_day_id` null and instead carries
    a `scheduled_window_start` and `scheduled_window_end`, where the end must be strictly
    after the start or the leg is rejected with `ERR_INVALID_WINDOW`."

    Design: Corner/validations/delivery_leg_inverted_window_returns_invalid_window
    """
    _, wo, _, _, _ = create_ready_for_fulfillment_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="Z", yardage_required=0, labor_hours=2)],
        deposit_amount_cents=5000, shop_day_date="2026-06-01", shop_capacity=20,
    )
    res = api.create_fulfillment_leg(
        factories.create_fulfillment_leg_payload(
            wo["id"], "DELIVERY",
            scheduled_window_start="2026-06-03T12:00:00Z",
            scheduled_window_end="2026-06-03T11:00:00Z"), MANAGER)
    validate_error(res, "ERR_INVALID_WINDOW", expected_status=422)


def test_duplicate_shop_day_same_date_returns_duplicate(api):
    """PRD §3.6: "at most one non-cancelled shop day may exist per `work_date`, and a
    duplicate is rejected with `ERR_DUPLICATE_SHOP_DAY`."

    Design: Corner/validations/duplicate_shop_day_same_date_returns_duplicate
    """
    register_shop_day("2026-06-10", 8)
    res = api.create_shop_day({"work_date": "2026-06-10", "labor_capacity_hours": 12}, MANAGER)
    validate_error(res, "ERR_DUPLICATE_SHOP_DAY", expected_status=409)


# ---------------------------------------------------------------------------
# Cross-entity gates
# ---------------------------------------------------------------------------
def test_production_blocked_by_ordered_material_order(api):
    """PRD §3.6: "Booking the first `PRODUCTION` leg onto a shop day is what advances the
    order from `APPROVED` to `IN_PRODUCTION`, and it has preconditions: the order must be
    `APPROVED`, every material order for the order must already be in `RECEIVED` or
    `CANCELLED` with none still `ORDERED`, and the target shop day must be `OPEN` with enough
    remaining capacity. An attempt to start production while a material order is still
    `ORDERED` is rejected with `ERR_MATERIALS_OUTSTANDING`."

    Design: Difficulty/cross_entity_state_dependency/production_blocked_by_ordered_materialorder
    """
    fab = register_fabric_sku(price_cents_per_yard=1700, in_stock_yards=80)
    day = register_shop_day("2026-05-01", 40)
    cust, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY", deposit_amount_cents=12000,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=5, labor_hours=4,
                                           piece_label="Wingback")],
    )
    place_material_order(wo["id"], fabric_sku_id=fab["id"], yards_ordered=5)  # stays ORDERED
    res = api.create_fulfillment_leg(
        factories.create_fulfillment_leg_payload(wo["id"], "PRODUCTION", shop_day_id=day["id"]),
        MANAGER)
    validate_error(res, "ERR_MATERIALS_OUTSTANDING", expected_status=409)
    assert get_work_order(wo["id"])["status"] == "APPROVED"


def test_finish_production_blocked_until_production_leg_complete(api):
    """PRD §3.7: "This is permitted only while the order is `IN_PRODUCTION`, and only once
    the order's `PRODUCTION` fulfillment leg is itself `COMPLETED`; finishing while the
    production leg is not complete is rejected with `ERR_PRODUCTION_NOT_COMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/finish_production_blocked_until_production_leg_complete
    """
    day = register_shop_day("2026-05-05", 20)
    cust, wo, _, _ = create_approved_order(
        service_type="REFINISH", deposit_amount_cents=12000,
        line_items=[create_line_item_payload(piece_label="Dresser refinish", yardage_required=0, labor_hours=6)],
    )
    leg = book_production_leg(wo["id"], day["id"])
    # dispatch but do NOT complete the production leg
    validate_success(api.dispatch_fulfillment_leg(leg["id"], MANAGER), 200)
    res = api.finish_production(wo["id"], MANAGER)
    validate_error(res, "ERR_PRODUCTION_NOT_COMPLETE", expected_status=409)
    assert get_work_order(wo["id"])["status"] == "IN_PRODUCTION"


def test_production_proceeds_once_material_received(api):
    """PRD §3.6: "the order must be `APPROVED`, every material order for the order must
    already be in `RECEIVED` or `CANCELLED` with none still `ORDERED`, and the target shop
    day must be `OPEN` with enough remaining capacity. An attempt to start production while a
    material order is still `ORDERED` is rejected with `ERR_MATERIALS_OUTSTANDING`."

    Design: Difficulty/cross_entity_state_dependency/production_blocked_by_ordered_materialorder
    """
    fab = register_fabric_sku(price_cents_per_yard=1700, in_stock_yards=80)
    day = register_shop_day("2026-05-02", 40)
    cust, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY", deposit_amount_cents=12000,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=5, labor_hours=4,
                                           piece_label="Wingback2")],
    )
    mo = place_material_order(wo["id"], fabric_sku_id=fab["id"], yards_ordered=5)
    validate_success(api.receive_material_order(
        mo["id"], {"received_fabric_price_cents_per_yard": 1700}, MANAGER), 200)
    # now no ORDERED material remains -> production books and order advances
    book_production_leg(wo["id"], day["id"])
    assert get_work_order(wo["id"])["status"] == "IN_PRODUCTION"


def test_finish_production_proceeds_once_leg_complete(api):
    """PRD §3.7: "When the piece is built and its production leg has reached `COMPLETED`, a
    `ShopManager` finishes production. This is permitted only while the order is
    `IN_PRODUCTION`, and only once the order's `PRODUCTION` fulfillment leg is itself
    `COMPLETED`; finishing while the production leg is not complete is rejected with
    `ERR_PRODUCTION_NOT_COMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/finish_production_blocked_until_production_leg_complete
    """
    day = register_shop_day("2026-05-06", 20)
    cust, wo, _, _ = create_approved_order(
        service_type="REFINISH", deposit_amount_cents=12000,
        line_items=[create_line_item_payload(piece_label="Dresser refinish2", yardage_required=0, labor_hours=6)],
    )
    leg = book_production_leg(wo["id"], day["id"])
    complete_production_leg(leg["id"])
    validate_success(api.finish_production(wo["id"], MANAGER), 200)
    assert get_work_order(wo["id"])["status"] == "READY_FOR_FULFILLMENT"


# ---------------------------------------------------------------------------
# Validation-priority conflicts
# ---------------------------------------------------------------------------
def test_approve_intake_state_beats_low_deposit_fiscal(api):
    """PRD §3.10: "Only after those pass does the system evaluate state validity
    (`ERR_INVALID_STATE`), then the optimistic-concurrency version check
    (`ERR_STALE_WORK_ORDER_VERSION`), then the cross-entity state guards
    (`ERR_MATERIALS_OUTSTANDING`, `ERR_PRODUCTION_NOT_COMPLETE`), then the domain business
    constraints (`ERR_LINE_ITEM_FIELDS_INVALID`, `ERR_CATALOG_ITEM_UNAVAILABLE`,
    `ERR_INVALID_WINDOW`, `ERR_DUPLICATE_SHOP_DAY`, `ERR_CAPACITY_EXCEEDED`,
    `ERR_DELIVERY_WINDOW_CONFLICT`, `ERR_DEPOSIT_TOO_LOW`, `ERR_SETTLEMENT_MISMATCH`,
    `ERR_ORDER_NOT_COMPLETED`), and finally pagination bounds (`ERR_INVALID_PAGINATION`) and
    request well-formedness (`ERR_INVALID_REQUEST`)."

    Design: Difficulty/priority_pair_validation_conflict/approve_state_vs_fiscal_state_wins
    """
    cust = register_customer()
    wo = validate_success(api.create_work_order(
        factories.create_work_order_payload(cust["id"], service_type="REPAIR"), CLERK), 201)
    # order is INTAKE: approve is state-invalid; deposit 1 is also below any threshold
    v = wo["version"]
    res = api.approve_work_order(
        wo["id"], factories.approve_payload(v, 1), make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_production_materials_state_beats_capacity_safety(api):
    """PRD §3.10: "Only after those pass does the system evaluate state validity
    (`ERR_INVALID_STATE`), then the optimistic-concurrency version check
    (`ERR_STALE_WORK_ORDER_VERSION`), then the cross-entity state guards
    (`ERR_MATERIALS_OUTSTANDING`, `ERR_PRODUCTION_NOT_COMPLETE`), then the domain business
    constraints (`ERR_LINE_ITEM_FIELDS_INVALID`, `ERR_CATALOG_ITEM_UNAVAILABLE`,
    `ERR_INVALID_WINDOW`, `ERR_DUPLICATE_SHOP_DAY`, `ERR_CAPACITY_EXCEEDED`,
    `ERR_DELIVERY_WINDOW_CONFLICT`, `ERR_DEPOSIT_TOO_LOW`, `ERR_SETTLEMENT_MISMATCH`,
    `ERR_ORDER_NOT_COMPLETED`), and finally pagination bounds (`ERR_INVALID_PAGINATION`) and
    request well-formedness (`ERR_INVALID_REQUEST`)."

    Design: Difficulty/priority_pair_validation_conflict/production_leg_materials_state_vs_capacity_safety_state_wins
    """
    fab = register_fabric_sku(price_cents_per_yard=3000, in_stock_yards=50)
    day = register_shop_day("2026-04-10", 4)
    # filler order books 4h -> day FULL
    cust_f, wo_f, _, _ = create_approved_order(
        service_type="REPAIR", deposit_amount_cents=8000,
        line_items=[create_line_item_payload(piece_label="Filler", yardage_required=0, labor_hours=4)],
    )
    book_production_leg(wo_f["id"], day["id"])
    day_full = validate_success(api.get_shop_day(day["id"], MANAGER), 200)
    assert day_full["status"] == "FULL"
    # target order: 6h, one ORDERED material; booking onto FULL day would also fail capacity
    cust, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY", deposit_amount_cents=30000,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=5, labor_hours=6,
                                           piece_label="Recliner")],
    )
    place_material_order(wo["id"], fabric_sku_id=fab["id"], yards_ordered=5)  # ORDERED
    res = api.create_fulfillment_leg(
        factories.create_fulfillment_leg_payload(wo["id"], "PRODUCTION", shop_day_id=day["id"]),
        MANAGER)
    validate_error(res, "ERR_MATERIALS_OUTSTANDING", expected_status=409)


def test_approve_state_failure_leaves_order_in_intake(api):
    """PRD §3.4: "Approval is a customer action available only while the order is
    `AWAITING_APPROVAL` and only to the owning customer; otherwise it is rejected with
    `ERR_INVALID_STATE` or, for a non-owner, `ERR_NOT_OWNER`."

    Design: Difficulty/priority_pair_validation_conflict/approve_state_vs_fiscal_state_wins
    """
    cust = register_customer()
    wo = validate_success(api.create_work_order(
        factories.create_work_order_payload(cust["id"], service_type="REPAIR"), CLERK), 201)
    res = api.approve_work_order(
        wo["id"], factories.approve_payload(wo["version"], 1), make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert get_work_order(wo["id"])["status"] == "INTAKE"


def test_production_materials_failure_leaves_order_approved(api):
    """PRD §3.6: "An attempt to start production while a material order is still `ORDERED` is
    rejected with `ERR_MATERIALS_OUTSTANDING`."
    PRD §3.6: "it may not book onto a day that is `FULL` or `CLOSED`; any of these is
    rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/production_leg_materials_state_vs_capacity_safety_state_wins
    """
    fab = register_fabric_sku(price_cents_per_yard=3000, in_stock_yards=50)
    day = register_shop_day("2026-04-11", 4)
    cust_f, wo_f, _, _ = create_approved_order(
        service_type="REPAIR", deposit_amount_cents=8000,
        line_items=[create_line_item_payload(piece_label="Filler2", yardage_required=0, labor_hours=4)],
    )
    book_production_leg(wo_f["id"], day["id"])
    cust, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY", deposit_amount_cents=30000,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=5, labor_hours=6,
                                           piece_label="Recliner2")],
    )
    place_material_order(wo["id"], fabric_sku_id=fab["id"], yards_ordered=5)
    res = api.create_fulfillment_leg(
        factories.create_fulfillment_leg_payload(wo["id"], "PRODUCTION", shop_day_id=day["id"]),
        MANAGER)
    validate_error(res, "ERR_MATERIALS_OUTSTANDING", expected_status=409)
    assert get_work_order(wo["id"])["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Settlement mismatch
# ---------------------------------------------------------------------------
def test_settlement_mismatch_returns_error(api):
    """PRD §3.7: "The call supplies `settlement_amount_cents`, which must exactly equal the
    order's `balance_due_cents` as it stands before this call — neither under- nor
    overpayment is allowed, and a mismatch is rejected with `ERR_SETTLEMENT_MISMATCH`."

    Design: Corner/validations/settlement_mismatch_returns_error
    """
    _, wo, _, _, _ = create_ready_for_fulfillment_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="Repair", yardage_required=0, labor_hours=2)],
        deposit_amount_cents=5000, shop_day_date="2026-06-15", shop_capacity=20,
    )
    complete_pickup_or_delivery(
        wo["id"], kind="PICKUP",
        window_start="2026-06-20T09:00:00Z", window_end="2026-06-20T10:00:00Z")
    res = api.complete_work_order(wo["id"], {"settlement_amount_cents": 1}, MANAGER)
    validate_error(res, "ERR_SETTLEMENT_MISMATCH", expected_status=422)
    assert get_work_order(wo["id"])["status"] == "READY_FOR_FULFILLMENT"
