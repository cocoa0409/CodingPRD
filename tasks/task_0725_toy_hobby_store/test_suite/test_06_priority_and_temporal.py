"""Validation-priority conflicts and temporal-overlap constraints."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_customer_headers,
    create_active_product, create_store, create_inventory, create_customer,
    create_allocation, create_open_order,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
ANY = TEST_USERS["any_headers"]


def test_age_grade_reported_before_recall_on_add_line(api):
    """PRD §2.10: "The order is: ... (5) the age-grade safety gate; (6) the recall safety
    gate; ..."

    Design: Difficulty/priority_pair_validation_conflict/recall_state_beats_age_grade_safety_on_add_line
    """
    product = create_active_product(msrp_cents=1000, category="ACTION_FIGURE",
                                    age_grade_min_months=72, safety_labels=["SMALL_PARTS"])
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=10)
    recall = get_success_data(api.create_recall(
        {"product_id": product["id"], "severity": "MANDATORY", "reason": "hazard"}, ADMIN))
    validate_success(api.issue_recall(recall["id"], ADMIN))
    customer = create_customer()
    cid = customer["id"]
    order = create_open_order(cid, store["id"])

    # recipient_age 24 < 72 (age-grade fails, prio 5) AND product recalled (prio 6).
    validate_error(
        api.add_order_line(order["id"], {"product_id": product["id"], "qty": 1, "recipient_age_months": 24},
                           make_customer_headers(cid)),
        ApiErrorId.ERR_AGE_GRADE_VIOLATION.value,
    )


def test_recall_gate_fires_on_add_line_when_age_ok(api):
    """PRD §3.5: "The recall gate requires the product's `recall_status` to be `CLEARED`;
    a recalled product is refused with `ERR_PRODUCT_RECALLED`."

    Design: Difficulty/priority_pair_validation_conflict/recall_state_beats_age_grade_safety_on_add_line
    """
    product = create_active_product(msrp_cents=1000, category="ACTION_FIGURE",
                                    age_grade_min_months=0, safety_labels=["SMALL_PARTS"])
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=10)
    recall = get_success_data(api.create_recall(
        {"product_id": product["id"], "severity": "MANDATORY", "reason": "hazard"}, ADMIN))
    validate_success(api.issue_recall(recall["id"], ADMIN))
    customer = create_customer()
    cid = customer["id"]
    order = create_open_order(cid, store["id"])

    # Age is fine (age_grade_min 0), so only the recall gate can fire.
    validate_error(
        api.add_order_line(order["id"], {"product_id": product["id"], "qty": 1, "recipient_age_months": 60},
                           make_customer_headers(cid)),
        ApiErrorId.ERR_PRODUCT_RECALLED.value,
    )


def test_existence_reported_before_state_on_convert(api):
    """PRD §2.8: "each identifier segment is checked for existence in order, and the first
    unresolved identifier produces the corresponding not-found error (for example
    `ERR_PRODUCT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_REGISTRY_NOT_FOUND`, and their
    siblings listed in §5)."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_convert
    """
    create_customer()  # populate DB with an unrelated entity
    validate_error(
        api.convert_special_order("00000000-0000-4000-8000-000000000000", ASSOCIATE),
        ApiErrorId.ERR_SPECIAL_ORDER_NOT_FOUND.value,
    )


def test_existence_not_found_before_state_on_missing_special_order(api):
    """PRD §2.8: "each identifier segment is checked for existence in order, and the first
    unresolved identifier produces the corresponding not-found error (for example
    `ERR_PRODUCT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_REGISTRY_NOT_FOUND`, and their
    siblings listed in §5)."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_convert
    """
    validate_error(
        api.convert_special_order("11111111-1111-4111-8111-111111111111", ASSOCIATE),
        ApiErrorId.ERR_SPECIAL_ORDER_NOT_FOUND.value,
    )


def test_demo_event_overlap_within_buffer_rejected(api):
    """PRD §3.12: "Scheduling must not collide with another `SCHEDULED` event at the same
    store: the new event's closed interval, expanded by the store's `event_buffer_minutes`
    cleanup gap (which defaults to 30 when the store is created without one), must not
    overlap an existing event; a collision is rejected with `ERR_EVENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/demo_event_overlap_with_buffer_closed_interval
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store(event_buffer_minutes=30)
    get_success_data(api.create_event(
        {"store_id": store["id"], "product_id": product["id"],
         "start_at": "2026-04-01T10:00:00Z", "end_at": "2026-04-01T11:00:00Z", "capacity": 5},
        ASSOCIATE))
    # New event at 11:15 is within the 30-min buffer after 11:00 end.
    validate_error(
        api.create_event(
            {"store_id": store["id"], "product_id": product["id"],
             "start_at": "2026-04-01T11:15:00Z", "end_at": "2026-04-01T12:00:00Z", "capacity": 5},
            ASSOCIATE),
        ApiErrorId.ERR_EVENT_OVERLAP.value,
    )


def test_second_event_at_same_store_within_buffer_collides(api):
    """PRD §3.12: "the new event's closed interval, expanded by the store's
    `event_buffer_minutes` cleanup gap (which defaults to 30 when the store is created
    without one), must not overlap an existing event; a collision is rejected with
    `ERR_EVENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/demo_event_overlap_with_buffer_closed_interval
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()  # default buffer 30
    get_success_data(api.create_event(
        {"store_id": store["id"], "product_id": product["id"],
         "start_at": "2026-05-01T10:00:00Z", "end_at": "2026-05-01T11:00:00Z", "capacity": 5},
        ASSOCIATE))
    # New event starts 11:20, within default 30-min buffer of prior 11:00 end.
    validate_error(
        api.create_event(
            {"store_id": store["id"], "product_id": product["id"],
             "start_at": "2026-05-01T11:20:00Z", "end_at": "2026-05-01T12:30:00Z", "capacity": 5},
            ASSOCIATE),
        ApiErrorId.ERR_EVENT_OVERLAP.value,
    )


def test_adjacent_allocation_window_allowed(api):
    """PRD §3.3: "The season window is half-open on `[season_start, season_end)`; if it
    overlaps the window of another allocation for the same product and store, creation is
    rejected with `ERR_ALLOCATION_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/allocation_window_overlap_half_open_interval
    """
    product = create_active_product(msrp_cents=1000, category="BOARD_GAME")
    store = create_store()
    create_allocation(product["id"], store["id"], allocated_qty=10,
                      season_start="2026-03-01T00:00:00Z", season_end="2026-06-01T00:00:00Z")
    # New window starts exactly at prior season_end -> half-open, adjacency allowed.
    data = validate_success(
        api.create_allocation(
            {"product_id": product["id"], "store_id": store["id"], "allocated_qty": 10,
             "season_start": "2026-06-01T00:00:00Z", "season_end": "2026-08-01T00:00:00Z"},
            MANAGER),
        expected_status=201,
    )
    assert data["status"] == "ACTIVE"


def test_allocation_window_overlap_rejected(api):
    """PRD §3.3: "The season window is half-open on `[season_start, season_end)`; if it
    overlaps the window of another allocation for the same product and store, creation is
    rejected with `ERR_ALLOCATION_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/allocation_window_overlap_half_open_interval
    """
    product = create_active_product(msrp_cents=1000, category="BOARD_GAME")
    store = create_store()
    create_allocation(product["id"], store["id"], allocated_qty=10,
                      season_start="2026-03-01T00:00:00Z", season_end="2026-06-01T00:00:00Z")
    # New window starts 2026-05-15 (before prior end 2026-06-01) -> overlap.
    validate_error(
        api.create_allocation(
            {"product_id": product["id"], "store_id": store["id"], "allocated_qty": 10,
             "season_start": "2026-05-15T00:00:00Z", "season_end": "2026-08-01T00:00:00Z"},
            MANAGER),
        ApiErrorId.ERR_ALLOCATION_WINDOW_OVERLAP.value,
    )
