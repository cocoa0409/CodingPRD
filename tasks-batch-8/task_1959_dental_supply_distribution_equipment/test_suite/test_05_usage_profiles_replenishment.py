"""Usage profiles: OCC upsert, average-usage windowing, auto-reorder thresholds, sweep."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_practice,
    create_product,
    create_order_payload,
    create_usage_profile_payload,
    upsert_profile,
    get_practice_version,
    create_and_submit_order,
    set_clock,
    make_practice_manager_headers,
    TEST_USERS,
    ApiErrorId,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]


def _auto_orders(api, practice_id):
    data, _ = validate_paginated(
        api.list_orders(ADMIN, params={"practice_id": practice_id, "kind": "AUTO"})
    )
    return data


def test_usage_profile_upsert_supersedes_on_same_pair(api):
    """PRD §3.2: "there is exactly one profile per pair, and the upsert legitimately
    replaces any prior profile for that pair." and "the profile listing may be filtered by
    `practice_id` and `product_id`."

    Design: Corner/entities/usage_profile_upsert_supersedes_on_same_pair
    """
    practice = create_practice(name="P Up", credit_limit_cents=1000000)
    product = create_product(sku="C-4", name="Gauze", unit_price_cents=1000)
    upsert_profile(practice["id"], product["id"], reorder_point=20, target_stock_level=100)
    upsert_profile(practice["id"], product["id"], reorder_point=30, target_stock_level=120)

    data, _ = validate_paginated(
        api.list_usage_profiles(
            ADMIN, params={"practice_id": practice["id"], "product_id": product["id"]}
        )
    )
    assert len(data) == 1, "Exactly one profile may exist per (practice, product) pair"
    assert data[0]["reorder_point"] == 30, "The second upsert supersedes the first"
    assert data[0]["target_stock_level"] == 120


def test_usage_profile_target_not_above_reorder_rejected(api):
    """PRD §3.2: "The profiled product must be `CONSUMABLE` or `REGULATED`, and
    `target_stock_level` must be strictly greater than `reorder_point`; either violation is
    rejected with `ERR_REORDER_TARGET_INVALID`."

    Design: Corner/validations/usage_profile_target_not_above_reorder_rejected
    """
    practice = create_practice(name="P Rt", credit_limit_cents=1000000)
    product = create_product(sku="C-17", name="Gauze", unit_price_cents=1000)
    res = api.upsert_usage_profile(
        create_usage_profile_payload(
            practice["id"],
            product["id"],
            expected_practice_version=practice["version"],
            reorder_point=20,
            target_stock_level=10,
        ),
        make_practice_manager_headers(practice["id"]),
    )
    validate_error(res, ApiErrorId.ERR_REORDER_TARGET_INVALID)


def test_usage_profile_upsert_stale_version_rejected(api):
    """PRD §2.7: "If `expected_practice_version` does not equal the Practice's current
    `version` — because another writer has advanced the practice since the client last read
    it — the upsert is rejected with `ERR_STALE_VERSION` (HTTP 412), and no profile is
    created or superseded."
    PRD §3.2: "Every successful upsert also increments the practice's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/usage_profile_upsert_stale_version_rejected
    """
    practice = create_practice(name="P Occ", credit_limit_cents=1000000)
    product = create_product(sku="C-24", name="Gauze", unit_price_cents=1000)
    stale_version = practice["version"]
    pm = make_practice_manager_headers(practice["id"])

    profile = validate_success(
        api.upsert_usage_profile(
            create_usage_profile_payload(
                practice["id"], product["id"], expected_practice_version=stale_version,
                reorder_point=20, target_stock_level=100,
            ),
            pm,
        ),
        200,
    )
    # First upsert advanced Practice.version, so replaying the same expected version is stale.
    res = api.upsert_usage_profile(
        create_usage_profile_payload(
            practice["id"], product["id"], expected_practice_version=stale_version,
            reorder_point=25, target_stock_level=110,
        ),
        pm,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    after = validate_success(api.get_usage_profile(profile["id"], ADMIN), 200)
    assert after["reorder_point"] == 20, "The losing write must not be applied"


def test_usage_average_excludes_out_of_window_deliveries(api):
    """PRD §3.2: "The `average_daily_usage` is measured over the trailing 28-day window
    ending at the logical now, both bounds inclusive: sum the line quantities of this
    product across this practice's orders whose `status` is `DELIVERED` and whose
    `delivered_at` falls inside the window — drafts, submitted-but-undelivered orders, and
    cancelled orders are all excluded — divide that total by 28, and round half up to four
    decimal places."

    Design: Corner/calculations/usage_average_excludes_out_of_window_deliveries
    """
    practice = create_practice(name="P Win", credit_limit_cents=10000000)
    product = create_product(sku="C-13", name="Gauze", unit_price_cents=1000)
    profile = upsert_profile(
        practice["id"], product["id"],
        reorder_point=5, target_stock_level=50, auto_replenish_enabled=False,
    )
    # First delivery at the default clock 2026-08-01.
    create_and_deliver_order_local(api, practice["id"], product["id"], 28)
    # Advance 29 days; the first delivery now sits outside [2026-08-02, 2026-08-30].
    set_clock("2026-08-30T00:00:00Z")
    create_and_deliver_order_local(api, practice["id"], product["id"], 28)

    after = validate_success(api.get_usage_profile(profile["id"], ADMIN), 200)
    assert after["average_daily_usage"] == pytest.approx(1.0, abs=1e-9), (
        "Only the in-window 28-unit delivery counts: 28/28 == 1.0, not 2.0"
    )


def create_and_deliver_order_local(api, practice_id, product_id, quantity):
    order = validate_success(
        api.create_order(
            create_order_payload(practice_id, [{"product_id": product_id, "quantity": quantity}]),
            SALES,
        ),
        201,
    )
    validate_success(api.submit_order(order["id"], SALES), 200)
    return validate_success(api.deliver_order(order["id"], ADMIN), 200)


def test_reorder_point_equality_triggers_auto_order(api):
    """PRD §3.2: "When `auto_replenish_enabled` is true and `on_hand_estimate` is less
    than or equal to `reorder_point` — an estimate exactly equal to the point does trigger"
    and "the replenishment run accrues consumption on every usage profile, then evaluates
    the reorder threshold profile by profile, and returns the `evaluated_profile_count`
    together with the `created_order_ids` of any auto-drafts it spawned."

    Design: Difficulty/boundary_precision_check/reorder_point_equality_triggers_auto_order
    """
    practice = create_practice(name="P Bound", credit_limit_cents=10000000)
    pa = create_product(sku="PA-1", name="PA", unit_price_cents=1000)
    pb = create_product(sku="PB-1", name="PB", unit_price_cents=1000)
    upsert_profile(practice["id"], pa["id"], reorder_point=20, target_stock_level=100)
    upsert_profile(practice["id"], pb["id"], reorder_point=20, target_stock_level=100)
    # PA: 28 delivered -> avg 1.0/day -> after 8 days on_hand == 20 exactly.
    create_and_deliver_order_local(api, practice["id"], pa["id"], 28)
    # PB: 29 delivered -> avg 1.0357/day -> after 8 days on_hand == 20.7144 > 20.
    create_and_deliver_order_local(api, practice["id"], pb["id"], 29)
    set_clock("2026-08-09T00:00:00Z")

    run = validate_success(api.run_replenishment(ADMIN), 200)
    assert run["evaluated_profile_count"] == 2
    assert len(run["created_order_ids"]) == 1, (
        "Only PA (on_hand exactly == reorder_point) triggers; PB at 20.7144 does not"
    )
    autos = _auto_orders(api, practice["id"])
    assert len(autos) == 1
    assert autos[0]["lines"][0]["product_id"] == pa["id"]
    assert autos[0]["lines"][0]["quantity"] == 80, "ceiling(100 - 20)"


def test_reorder_point_equality_second_scenario(api):
    """PRD §3.2: "When `auto_replenish_enabled` is true and `on_hand_estimate` is less
    than or equal to `reorder_point` — an estimate exactly equal to the point does trigger"
    and "the system computes a reorder quantity as the ceiling of `target_stock_level`
    minus `on_hand_estimate`."

    Design: Difficulty/boundary_precision_check/reorder_point_equality_triggers_auto_order
    """
    practice = create_practice(name="P B2", credit_limit_cents=10000000)
    product = create_product(sku="PE-1", name="PE", unit_price_cents=1000)
    upsert_profile(practice["id"], product["id"], reorder_point=8, target_stock_level=50)
    # Deliver 28 at 2026-08-01: avg 1.0/day, on_hand 28 (> 8, no trigger yet).
    create_and_deliver_order_local(api, practice["id"], product["id"], 28)
    # +20 days: accrual 20 x 1.0 leaves on_hand == 8 == reorder_point exactly.
    set_clock("2026-08-21T00:00:00Z")

    run = validate_success(api.run_replenishment(ADMIN), 200)
    assert run["evaluated_profile_count"] == 1
    assert len(run["created_order_ids"]) == 1
    autos = _auto_orders(api, practice["id"])
    assert len(autos) == 1
    assert autos[0]["lines"][0]["quantity"] == 42, "ceiling(50 - 8)"


def test_deliver_triggers_usage_update_triggers_auto_order(api):
    """PRD §3.3: "Second, for each delivered line whose product is `CONSUMABLE` or
    `REGULATED` and for which a usage profile exists for the practice–product pair, the
    line quantity is added to the profile's `on_hand_estimate` and the profile's
    `average_daily_usage` is recomputed over the trailing 28-day window. Third, each
    profile so updated is evaluated against the auto-reorder rule of §3.2, which may spawn
    a new `DRAFT` auto-order."

    Design: Difficulty/transitive_cascade/deliver_triggers_usage_update_triggers_auto_order
    """
    practice = create_practice(name="P Casc", credit_limit_cents=10000000)
    product = create_product(sku="C-9", name="Gauze", unit_price_cents=1000)
    profile = upsert_profile(
        practice["id"], product["id"], reorder_point=20, target_stock_level=100
    )
    order = create_and_submit_order(
        practice["id"], [{"product_id": product["id"], "quantity": 20}]
    )

    delivered = validate_success(api.deliver_order(order["id"], ADMIN), 200)
    assert delivered["status"] == "DELIVERED"

    after = validate_success(api.get_usage_profile(profile["id"], ADMIN), 200)
    assert after["on_hand_estimate"] == pytest.approx(20.0, abs=1e-9)
    assert after["average_daily_usage"] == pytest.approx(0.7143, abs=1e-9), (
        "20 / 28 rounded half up to four decimals"
    )

    autos = _auto_orders(api, practice["id"])
    assert len(autos) == 1, "Exactly one AUTO draft may be spawned"
    assert autos[0]["kind"] == "AUTO" and autos[0]["status"] == "DRAFT"
    assert autos[0]["lines"][0]["product_id"] == product["id"]
    assert autos[0]["lines"][0]["quantity"] == 80, "ceiling(100 - 20)"


def test_deliver_auto_order_duplicate_guard(api):
    """PRD §3.2: "When `auto_replenish_enabled` is true and `on_hand_estimate` is less
    than or equal to `reorder_point` — an estimate exactly equal to the point does trigger —
    and no existing `DRAFT` order of kind `AUTO` already covers this practice–product pair,
    the system computes a reorder quantity as the ceiling of `target_stock_level` minus
    `on_hand_estimate`."

    Design: Difficulty/transitive_cascade/deliver_triggers_usage_update_triggers_auto_order
    """
    practice = create_practice(name="P Dup", credit_limit_cents=10000000)
    product = create_product(sku="C-9D", name="Gauze", unit_price_cents=1000)
    upsert_profile(practice["id"], product["id"], reorder_point=50, target_stock_level=100)

    # First delivery: on_hand 20 <= 50 -> AUTO draft spawned.
    create_and_deliver_order_local(api, practice["id"], product["id"], 20)
    autos = _auto_orders(api, practice["id"])
    assert len(autos) == 1

    # Second delivery: on_hand 40 <= 50, still breached, but an AUTO DRAFT already exists.
    create_and_deliver_order_local(api, practice["id"], product["id"], 20)
    autos = _auto_orders(api, practice["id"])
    assert len(autos) == 1, "The duplicate guard allows one outstanding auto-draft per pair"
