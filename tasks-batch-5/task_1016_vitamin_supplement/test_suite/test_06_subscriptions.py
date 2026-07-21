"""Auto-ship subscriptions: the ACTIVE<->PAUSED cycle, the scheduling-window
buffer, terminal-state guards, cadence-derived discount, cadence validation,
version increment on mutation, and OCC on generate-order.
"""
from test_helpers import (
    validate_success, validate_error, TEST_USERS, make_customer_headers,
    new_customer, new_product, new_subscription, generate_autoship_order,
    create_subscription_payload,
)

OPERATOR = TEST_USERS["store_operator_headers"]


def test_subscription_pause_transition(api):
    """PRD §3.5: "An `ACTIVE` subscription may be paused, moving it to `PAUSED`;
    a `PAUSED` subscription may be resumed back to `ACTIVE`, forming a cyclic
    `ACTIVE` ↔ `PAUSED` loop."

    Design: Difficulty/non_linear_state_machine/subscription_active_paused_cycle
    """
    cust = new_customer(email="c4@x.com", full_name="Cust Four")
    prod = new_product(unit_price_cents=2000, form="LIQUID", regimen_goals=["SLEEP"])
    sub = new_subscription(cust["id"], prod["id"], quantity_per_cycle=1, cadence_days=60)
    res = api.set_subscription_state(sub["id"], {"to_status": "PAUSED"},
                                     make_customer_headers(cust["id"]))
    updated = validate_success(res, 200)
    assert updated["status"] == "PAUSED"


def test_subscription_active_paused_active_round_trip(api):
    """PRD §3.5: "a `PAUSED` subscription may be resumed back to `ACTIVE`, forming
    a cyclic `ACTIVE` ↔ `PAUSED` loop."

    Design: Difficulty/non_linear_state_machine/subscription_active_paused_cycle
    """
    cust = new_customer(email="c4@x.com", full_name="Cust Four")
    prod = new_product(unit_price_cents=2000, form="LIQUID", regimen_goals=["SLEEP"])
    sub = new_subscription(cust["id"], prod["id"], quantity_per_cycle=1, cadence_days=60)
    headers = make_customer_headers(cust["id"])
    validate_success(api.set_subscription_state(sub["id"], {"to_status": "PAUSED"}, headers), 200)
    resumed = validate_success(
        api.set_subscription_state(sub["id"], {"to_status": "ACTIVE"}, headers), 200)
    assert resumed["status"] == "ACTIVE"


def test_second_subscription_within_buffer_rejected(api):
    """PRD §3.5: "a new subscription's `first_ship_date` must be at least a fixed
    buffer of `SUBSCRIPTION_BUFFER_DAYS` (which is 7) days away from the
    `next_ship_date` of any existing `ACTIVE` or `PAUSED` subscription for the
    same customer and product: a first-ship date strictly closer than 7 days is
    rejected with `ERR_SUBSCRIPTION_WINDOW_CONFLICT`, while one exactly 7 days
    apart is accepted."

    Design: Difficulty/resource_temporal_overlap/subscription_window_buffer_conflict
    """
    cust = new_customer(email="c14@x.com", full_name="Cust Fourteen")
    prod = new_product(unit_price_cents=2000, form="TABLET", regimen_goals=["SLEEP"])
    new_subscription(cust["id"], prod["id"], quantity_per_cycle=1, cadence_days=30,
                     first_ship_date="2026-08-01T00:00:00Z")
    res = api.create_subscription(
        create_subscription_payload(prod["id"], quantity_per_cycle=1, cadence_days=30,
                                    first_ship_date="2026-08-03T00:00:00Z"),
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_SUBSCRIPTION_WINDOW_CONFLICT", expected_status=409)


def test_second_subscription_exactly_buffer_apart_accepted(api):
    """PRD §3.5: "a first-ship date strictly closer than 7 days is rejected with
    `ERR_SUBSCRIPTION_WINDOW_CONFLICT`, while one exactly 7 days apart is
    accepted."

    Design: Difficulty/resource_temporal_overlap/subscription_window_buffer_conflict
    """
    cust = new_customer(email="c14b@x.com", full_name="Cust Fourteen B")
    prod = new_product(unit_price_cents=2000, form="TABLET", regimen_goals=["SLEEP"])
    new_subscription(cust["id"], prod["id"], quantity_per_cycle=1, cadence_days=30,
                     first_ship_date="2026-08-01T00:00:00Z")
    res = api.create_subscription(
        create_subscription_payload(prod["id"], quantity_per_cycle=1, cadence_days=30,
                                    first_ship_date="2026-08-08T00:00:00Z"),
        make_customer_headers(cust["id"]))
    sub2 = validate_success(res, 201)
    assert sub2["status"] == "ACTIVE"


def test_resume_cancelled_subscription_rejected(api):
    """PRD §3.5: "A subscription may be cancelled to `CANCELLED` from either
    `ACTIVE` or `PAUSED`, which is terminal. A transition requested from a status
    that does not admit it is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_resume_cancelled_subscription_invalid_state
    """
    cust = new_customer(email="sm1@x.com", full_name="SM One")
    prod = new_product(unit_price_cents=1000, regimen_goals=["ENERGY"])
    sub = new_subscription(cust["id"], prod["id"], quantity_per_cycle=1, cadence_days=30)
    headers = make_customer_headers(cust["id"])
    validate_success(api.set_subscription_state(sub["id"], {"to_status": "CANCELLED"}, headers), 200)
    res = api.set_subscription_state(sub["id"], {"to_status": "ACTIVE"}, headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_ninety_day_cadence_discount_mapping(api):
    """PRD §3.5: "its `autoship_discount_pct` is derived from the cadence — 0.05
    for a 30-day cadence, 0.08 for a 60-day cadence, and 0.10 for a 90-day
    cadence."

    Design: Corner/calculations/corner_autoship_discount_cadence_mapping
    """
    cust = new_customer(email="ca3@x.com", full_name="CA Three")
    prod = new_product(unit_price_cents=2000, regimen_goals=["ENERGY"])
    sub = new_subscription(cust["id"], prod["id"], quantity_per_cycle=1, cadence_days=90)
    assert sub["autoship_discount_pct"] == 0.10


def test_invalid_cadence_rejected(api):
    """PRD §3.5: "The `cadence_days` must be one of 30, 60, or 90; any other value
    is rejected with `ERR_INVALID_CADENCE`."

    Design: Corner/validations/corner_invalid_cadence_rejected
    """
    cust = new_customer(email="v1@x.com", full_name="V One")
    prod = new_product(unit_price_cents=2000, regimen_goals=["SLEEP"])
    res = api.create_subscription(
        create_subscription_payload(prod["id"], quantity_per_cycle=1, cadence_days=45,
                                    first_ship_date="2026-08-01T00:00:00Z"),
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_CADENCE", expected_status=422)


def test_subscription_version_increments_on_pause(api):
    """PRD §2.4: "`version` is an integer that starts at its initial value and
    increments by one on every mutation of the resource, and it is the value used
    for optimistic concurrency control (Section 2.9)."

    Design: Corner/cross_cutting/corner_subscription_version_increments_on_mutation
    """
    cust = new_customer(email="cc2@x.com", full_name="CC Two")
    prod = new_product(unit_price_cents=2000, regimen_goals=["SLEEP"])
    sub = new_subscription(cust["id"], prod["id"], quantity_per_cycle=1, cadence_days=60)
    before = sub["version"]
    paused = validate_success(
        api.set_subscription_state(sub["id"], {"to_status": "PAUSED"},
                                   make_customer_headers(cust["id"])), 200)
    assert paused["version"] == before + 1, "one mutation advances version by exactly one"


def test_stale_generate_order_version_rejected(api):
    """PRD §2.9: "If `expected_subscription_version` does not equal the
    subscription's current `version` — because another writer has already
    generated a cycle and advanced the version since the client last read it —
    the request is rejected with `ERR_STALE_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting/corner_occ_stale_subscription_version_conflict
    """
    cust = new_customer(email="cc1@x.com", full_name="CC One")
    prod = new_product(unit_price_cents=2000, regimen_goals=["ENERGY"])
    sub = new_subscription(cust["id"], prod["id"], quantity_per_cycle=1, cadence_days=30)
    stale_version = sub["version"]
    # First generation succeeds and advances the version.
    generate_autoship_order(sub["id"], cust["id"], stale_version)
    # Second generation reuses the now-stale version.
    res = api.generate_order(sub["id"], {"expected_subscription_version": stale_version},
                             make_customer_headers(cust["id"]))
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
