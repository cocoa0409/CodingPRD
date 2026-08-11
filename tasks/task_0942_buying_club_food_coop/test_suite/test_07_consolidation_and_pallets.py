"""The supplier invoice, freight and reefer allocation, the pallet plan and
consolidation."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_freight_fully_allocated,
    assert_freight_fully_allocated_within_drop,
    assert_pallet,
    assert_reefer_fully_allocated,
    canonical_world,
    rice_world,
    seal_all_pallets,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["club_admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


# ----------------------------------------------------- freight allocation ---
def test_freight_allocation_conserves_at_the_drop_and_order_levels(api):
    """PRD §3.7: "At **level one**, the route run's `freight_cents` is split
    across its drop runs whose status is `RECEIVED`, weighted by each drop run's
    `subtotal_cents`."
    PRD §3.7: "At **level two**, each drop run's `freight_alloc_cents` is split
    across its member orders whose status is `FILLED` or `SHORT_FILLED`, weighted
    by each order's `gross_cents`, using the identical floor-then-largest-remainder
    scheme with ascending member-order `created_at` as the tie-break."
    PRD §3.7: "Both levels conserve exactly: the drop runs' `freight_alloc_cents`
    sum to the run's `freight_cents`, and inside each drop run the orders'
    `freight_alloc_cents` sum to that drop run's `freight_alloc_cents`."

    Design: Corner/calculations/freight_allocation_conserves_at_the_drop_and_order_levels
    """
    w = canonical_world(api, "invoiced")

    route_run = validate_success(api.get_route_run(w.route_run_id, ADMIN))
    assert route_run["freight_cents"] == 5000
    assert route_run["supplier_invoice_cents"] == 64400

    drop_run = validate_success(api.get_drop_run(w.drop_run_id, ADMIN))
    assert drop_run["freight_alloc_cents"] == 5000
    assert_freight_fully_allocated(route_run, [drop_run])

    orders, _ = validate_paginated(
        api.list_member_orders(ADMIN, params={"drop_run_id": w.drop_run_id})
    )
    by_id = {order["id"]: order for order in orders}
    assert by_id[w.order_mara]["freight_alloc_cents"] == 3143
    assert by_id[w.order_ben]["freight_alloc_cents"] == 1857
    assert_freight_fully_allocated_within_drop(drop_run, orders)


# ------------------------------------------------------- the pallet plan ----
def test_build_pallets_partitions_allocated_units_by_temperature_class(api):
    """PRD §3.7: "The plan is built one temperature class at a time, in the fixed
    order `FROZEN`, then `CHILLED`, then `DRY`."
    PRD §3.7: "Each pallet records its `route_run_id`, its `temp_class`, its
    running `weight_grams` and `cube_cm3`, a `unit_count` of the units loaded onto
    it, a `requires_reefer` flag that is true exactly when its `temp_class` is
    `FROZEN` or `CHILLED`, and a `status` that starts at `BUILDING`."
    PRD §2.3: "Pallets are written class by class in the fixed order `FROZEN`,
    then `CHILLED`, then `DRY`, and within a class in ascending `sequence_index`,
    during the pallet build."

    Design: Corner/endpoints/build_pallets_partitions_allocated_units_by_temperature_class
    """
    w = canonical_world(api, "invoiced")
    validate_success(api.build_pallets(w.route_run_id, WAREHOUSE))

    rows, meta = validate_paginated(
        api.list_pallets(ADMIN, params={"route_run_id": w.route_run_id})
    )
    assert meta["total_count"] == 3
    frozen, chilled, dry = rows
    for pallet in rows:
        assert_pallet(pallet)
        assert pallet["status"] == "BUILDING"

    assert frozen["temp_class"] == "FROZEN"
    assert frozen["unit_count"] == 12
    assert frozen["weight_grams"] == 6000
    assert frozen["requires_reefer"] is True

    assert chilled["temp_class"] == "CHILLED"
    assert chilled["unit_count"] == 6
    assert chilled["weight_grams"] == 5400
    assert chilled["requires_reefer"] is True

    assert dry["temp_class"] == "DRY"
    assert dry["unit_count"] == 8
    assert dry["weight_grams"] == 8000
    assert dry["requires_reefer"] is False


def test_pallet_build_keeps_one_pallet_when_the_load_lands_under_the_cap(api):
    """PRD §3.7: "A unit joins the current pallet when adding it would leave
    `weight_grams` at most 900000 **and** `cube_cm3` at most 1600000; both caps are
    inclusive, so a unit landing exactly on a cap still fits."
    PRD §3.7: "It opens a pallet with `sequence_index` 1, `weight_grams` 0 and
    `cube_cm3` 0, and walks the units."

    Design: Corner/calculations/pallet_build_keeps_one_pallet_when_the_load_lands_under_the_cap
    """
    w = rice_world(api, qty_units=38, cases_received=19, supplier_invoice_cents=760000)

    rows, meta = validate_paginated(
        api.list_pallets(ADMIN, params={"route_run_id": w.route_run_id, "temp_class": "DRY"})
    )
    assert meta["total_count"] == 1
    pallet = rows[0]
    assert pallet["sequence_index"] == 1
    assert pallet["unit_count"] == 38
    assert pallet["weight_grams"] == 862600
    assert pallet["cube_cm3"] == 1140000
    assert pallet["status"] == "BUILDING"


def test_pallet_build_opens_a_second_pallet_when_the_weight_cap_would_be_exceeded(api):
    """PRD §3.7: "Otherwise nothing is sealed — the server simply opens the next
    pallet of that class with `sequence_index` incremented by one and puts the unit
    there."
    PRD §3.7: "On success the run's `cold_pallet_count` is written as the number of
    pallets requiring a reefer, `dry_pallet_count` as the number of ambient ones,
    `reefer_slots_used` as exactly the `cold_pallet_count` (each cold pallet occupies
    one slot on the truck), and `reefer_surcharge_cents` as `reefer_slots_used`
    multiplied by 4500 cents per slot."

    Design: Corner/calculations/pallet_build_opens_a_second_pallet_when_the_weight_cap_would_be_exceeded
    """
    w = rice_world(api, qty_units=40, cases_received=20, supplier_invoice_cents=800000)

    rows, meta = validate_paginated(
        api.list_pallets(ADMIN, params={"route_run_id": w.route_run_id, "temp_class": "DRY"})
    )
    assert meta["total_count"] == 2
    first, second = rows
    assert first["sequence_index"] == 1
    assert first["unit_count"] == 39
    assert first["weight_grams"] == 885300
    assert first["cube_cm3"] == 1170000
    assert first["requires_reefer"] is False
    assert second["sequence_index"] == 2
    assert second["unit_count"] == 1
    assert second["weight_grams"] == 22700

    route_run = validate_success(api.get_route_run(w.route_run_id, ADMIN))
    assert route_run["cold_pallet_count"] == 0
    assert route_run["reefer_surcharge_cents"] == 0


def test_reefer_surcharge_allocation_distributes_every_cent(api):
    """PRD §3.7: "For each member order on the run with status `FILLED` or
    `SHORT_FILLED`, the server computes that order's cold value as the sum, over its
    lines whose item is `FROZEN` or `CHILLED`, of `allocated_units` multiplied by
    `unit_price_cents`; cancelled orders are excluded."
    PRD §3.7: "The run's `reefer_surcharge_cents` is then split across those orders
    in proportion to their cold values, by the same floor-then-largest-remainder
    scheme, ranking on the discarded fraction descending with ascending member-order
    `created_at` as the tie-break, and each order's share is written as its
    `reefer_alloc_cents`."
    PRD §2.11: "**Reefer surcharge fully allocated.** Summing `reefer_alloc_cents`
    across every member order on a route run yields the run's
    `reefer_surcharge_cents` exactly — never one cent more and never one cent fewer
    than the pallet build computed."

    Design: Corner/calculations/reefer_surcharge_allocation_distributes_every_cent
    """
    w = canonical_world(api, "pallets_built")

    route_run = validate_success(api.get_route_run(w.route_run_id, ADMIN))
    assert route_run["cold_pallet_count"] == 2
    assert route_run["dry_pallet_count"] == 1
    assert route_run["reefer_slots_used"] == 2
    assert route_run["reefer_surcharge_cents"] == 9000

    mara = validate_success(api.get_member_order(w.order_mara, ADMIN))
    ben = validate_success(api.get_member_order(w.order_ben, ADMIN))
    assert mara["reefer_alloc_cents"] == 6477
    assert ben["reefer_alloc_cents"] == 2523
    assert_reefer_fully_allocated(route_run, [mara, ben])

    assert (
        validate_success(api.get_drop_run(w.drop_run_id, ADMIN))["reefer_alloc_cents"]
        == 9000
    )


# ------------------------------------------------------- capacity guards ----
def test_building_pallets_before_the_supplier_invoice_returns_supplier_invoice_missing(api):
    """PRD §3.7: "Pallet building comes next, and it is refused with
    `ERR_SUPPLIER_INVOICE_MISSING` unless the run's `supplier_invoice_cents` is
    already greater than 0."

    Design: Corner/validations/building_pallets_before_the_supplier_invoice_returns_supplier_invoice_missing
    """
    w = canonical_world(api, "receipts")

    validate_error(
        api.build_pallets(w.route_run_id, WAREHOUSE),
        ApiErrorId.ERR_SUPPLIER_INVOICE_MISSING.value,
    )

    assert validate_success(api.get_route_run(w.route_run_id, ADMIN))["supplier_invoice_cents"] == 0
    _, meta = validate_paginated(
        api.list_pallets(ADMIN, params={"route_run_id": w.route_run_id})
    )
    assert meta["total_count"] == 0


def test_a_pallet_plan_needing_two_reefer_slots_on_a_one_slot_route_is_refused(api):
    """PRD §3.7: "If the count of pallets requiring a reefer exceeds the route's
    `reefer_slots`, the build is refused with `ERR_REEFER_CAPACITY_EXCEEDED`; if the
    total pallet count across all classes exceeds the route's `max_pallets`, it is
    refused with `ERR_PALLET_CAPACITY_EXCEEDED`."

    Design: Corner/validations/a_pallet_plan_needing_two_reefer_slots_on_a_one_slot_route_is_refused
    """
    w = canonical_world(api, "invoiced", reefer_slots=1)

    validate_error(
        api.build_pallets(w.route_run_id, WAREHOUSE),
        ApiErrorId.ERR_REEFER_CAPACITY_EXCEEDED.value,
    )

    _, meta = validate_paginated(
        api.list_pallets(ADMIN, params={"route_run_id": w.route_run_id})
    )
    assert meta["total_count"] == 0
    assert validate_success(api.get_route_run(w.route_run_id, ADMIN))["reefer_surcharge_cents"] == 0
    assert validate_success(api.get_member_order(w.order_mara, ADMIN))["reefer_alloc_cents"] == 0


def test_a_pallet_plan_needing_more_positions_than_the_truck_has_is_refused(api):
    """PRD §2.9: "**Rung 30** — the total pallet count on the run does not exceed
    the route's `max_pallets`. Applies to building pallets. Failure:
    `ERR_PALLET_CAPACITY_EXCEEDED`, HTTP 409."
    PRD §2.9: "**Rung 29** — the number of pallets requiring a reefer does not
    exceed the route's `reefer_slots`. Applies to building pallets. Failure:
    `ERR_REEFER_CAPACITY_EXCEEDED`, HTTP 409."

    Design: Corner/errors/a_pallet_plan_needing_more_positions_than_the_truck_has_is_refused
    """
    w = rice_world(
        api,
        qty_units=40,
        cases_received=20,
        supplier_invoice_cents=800000,
        max_pallets=1,
        stage="invoiced",
    )

    body = validate_error(
        api.build_pallets(w.route_run_id, WAREHOUSE),
        ApiErrorId.ERR_PALLET_CAPACITY_EXCEEDED.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_REEFER_CAPACITY_EXCEEDED.value

    _, meta = validate_paginated(
        api.list_pallets(ADMIN, params={"route_run_id": w.route_run_id})
    )
    assert meta["total_count"] == 0
    assert validate_success(api.get_route_run(w.route_run_id, ADMIN))["dry_pallet_count"] == 0


# ---------------------------------------------- sealing and consolidation ---
def test_sealing_an_already_sealed_pallet_returns_invalid_pallet_state(api):
    """PRD §3.7: "Pallets are sealed individually by the warehouse while the
    parent cycle is `RECEIVED`, moving each `BUILDING → SEALED`; sealing anything
    not in `BUILDING` is refused with `ERR_INVALID_PALLET_STATE`."

    Design: Corner/state_machines/sealing_an_already_sealed_pallet_returns_invalid_pallet_state
    """
    w = canonical_world(api, "pallets_sealed")
    pallet_id = w.pallets[0]

    validate_error(
        api.seal_pallet(pallet_id, WAREHOUSE), ApiErrorId.ERR_INVALID_PALLET_STATE.value
    )
    assert validate_success(api.get_pallet(pallet_id, ADMIN))["status"] == "SEALED"


def test_consolidating_before_the_exception_deadline_returns_exception_window_open(api):
    """PRD §3.7: "It requires the cycle to be `RECEIVED`, requires the clock to be
    at or after `exception_deadline_at` — an attempt before then is refused with
    `ERR_EXCEPTION_WINDOW_OPEN` — and requires every pallet on every route run of the
    cycle to have status `SEALED`, failing with `ERR_PALLETS_NOT_SEALED` otherwise."

    Design: Corner/state_machines/consolidating_before_the_exception_deadline_returns_exception_window_open
    """
    w = canonical_world(api, "pallets_sealed")

    validate_error(
        api.consolidate_cycle(w.cycle_id, WAREHOUSE),
        ApiErrorId.ERR_EXCEPTION_WINDOW_OPEN.value,
    )

    cycle = validate_success(api.get_cycle(w.cycle_id, ADMIN))
    assert cycle["status"] == "RECEIVED"
    assert cycle["exception_state"] == "OPEN"


def test_consolidating_with_an_unsealed_pallet_returns_pallets_not_sealed(api):
    """PRD §2.9: "**Rung 44** — every pallet on every route run of the cycle has
    status `SEALED`. Applies to consolidating a cycle. Failure:
    `ERR_PALLETS_NOT_SEALED`, HTTP 409."
    PRD §2.9: "**Rung 39** — the clock is at or after the cycle's
    `exception_deadline_at`. Applies to consolidating a cycle. Failure:
    `ERR_EXCEPTION_WINDOW_OPEN`, HTTP 409."

    Design: Corner/state_machines/consolidating_with_an_unsealed_pallet_returns_pallets_not_sealed
    """
    w = canonical_world(api, "pallets_built")
    set_clock(api, "2026-05-27T00:00:00Z")

    body = validate_error(
        api.consolidate_cycle(w.cycle_id, WAREHOUSE),
        ApiErrorId.ERR_PALLETS_NOT_SEALED.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_EXCEPTION_WINDOW_OPEN.value

    assert validate_success(api.get_cycle(w.cycle_id, ADMIN))["status"] == "RECEIVED"
    _, meta = validate_paginated(
        api.list_pallets(
            ADMIN, params={"route_run_id": w.route_run_id, "status": "BUILDING"}
        )
    )
    assert meta["total_count"] == 3
