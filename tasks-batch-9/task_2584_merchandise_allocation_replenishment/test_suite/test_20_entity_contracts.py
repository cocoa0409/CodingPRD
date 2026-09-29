"""Entity contracts: creation payload completeness, post-mutation reads, list
paging and filter composition, the thirteen path-id not-found families, required
and optional inputs, computed and server-minted fields, declared type
constraints, the two immutable entities, program cohesion and the junction and
supersede topology."""
import pytest

from test_helpers import (
    ADMIN,
    ALLOCATOR,
    ALLOCATOR_USER_ID,
    MANAGER,
    ApiErrorId,
    assert_mutable_common_fields,
    assert_no_mutable_common_fields,
    units_by_size,
    validate_error,
    validate_paginated,
    validate_success,
)

# A well-formed uuid that belongs to no row of any table.
UNKNOWN_ID = "11111111-1111-4111-8111-111111111111"

CURVE_4SZ = [
    {"size_code": "S", "share_bp": 2000},
    {"size_code": "M", "share_bp": 3500},
    {"size_code": "L", "share_bp": 3000},
    {"size_code": "XL", "share_bp": 1500},
]

STORE_0101 = {
    "store_code": "0101",
    "grade": "A",
    "grade_index_bp": 13000,
    "cluster_code": "URBAN",
    "freight_flat_usd": 41.00,
    "historical_sell_through_bp": 6500,
}
STORE_0102 = {
    "store_code": "0102",
    "grade": "B",
    "grade_index_bp": 10000,
    "cluster_code": "URBAN",
    "freight_flat_usd": 38.00,
    "historical_sell_through_bp": 5800,
}

PLAN_0101 = {
    "item_class": "APPAREL_TOP",
    "effective_from": "2026-07-01T00:00:00Z",
    "fixture_count": 4,
    "facings_per_fixture": 3,
    "units_per_facing": 4,
    "presentation_min_units": 12,
}
PLAN_0102 = {
    "item_class": "APPAREL_TOP",
    "effective_from": "2026-07-01T00:00:00Z",
    "fixture_count": 2,
    "facings_per_fixture": 3,
    "units_per_facing": 4,
    "presentation_min_units": 8,
}

POSITION_0101 = {
    "on_hand_units": 4,
    "size_on_hand": [
        {"size_code": "S", "units": 0},
        {"size_code": "M", "units": 3},
        {"size_code": "L", "units": 1},
        {"size_code": "XL", "units": 0},
    ],
    "min_units": 12,
    "max_units": 48,
    "weekly_forecast_units": 9,
    "trailing_4wk_sales_units": 30,
}
POSITION_0102 = {
    "on_hand_units": 30,
    "size_on_hand": [
        {"size_code": "S", "units": 8},
        {"size_code": "M", "units": 10},
        {"size_code": "L", "units": 8},
        {"size_code": "XL", "units": 4},
    ],
    "min_units": 8,
    "max_units": 24,
    "weekly_forecast_units": 5,
    "trailing_4wk_sales_units": 16,
}

RECEIPT_20 = {
    "units_received": 20,
    "size_received": [
        {"size_code": "S", "units": 4},
        {"size_code": "M", "units": 7},
        {"size_code": "L", "units": 6},
        {"size_code": "XL", "units": 3},
    ],
    "receipt_date": "2026-08-01T00:00:00Z",
}


def _program(api, **overrides):
    payload = {"name": "FA26 Core Tops", "season_code": "FA26", "banner_code": "NORTH"}
    payload.update(overrides)
    return validate_success(api.create_program(payload, ADMIN), 201)


def _store(api, program_id, spec):
    return validate_success(
        api.create_store(dict(spec, program_id=program_id), ADMIN), 201
    )


def _plan(api, store_id, spec):
    return validate_success(
        api.create_fixture_plan(dict(spec, store_id=store_id), ADMIN), 201
    )


def _profile(api, program_id, **overrides):
    payload = {
        "program_id": program_id,
        "profile_code": "TOP-4SZ",
        "item_class": "APPAREL_TOP",
        "size_curve": [dict(entry) for entry in CURVE_4SZ],
    }
    payload.update(overrides)
    return validate_success(api.create_size_profile(payload, ADMIN), 201)


def _item(api, program_id, size_profile_id, **overrides):
    payload = {
        "program_id": program_id,
        "sku_code": "SKU-1001",
        "style_code": "ST-100",
        "item_class": "APPAREL_TOP",
        "item_type": "SEASONAL",
        "size_profile_id": size_profile_id,
        "unit_cost_usd": 14.20,
        "retail_price_usd": 36.50,
    }
    payload.update(overrides)
    return validate_success(api.create_item(payload, ADMIN), 201)


def _position(api, store_id, item_id, spec, **overrides):
    payload = dict(spec, store_id=store_id, item_id=item_id)
    payload.update(overrides)
    return validate_success(api.create_store_position(payload, ALLOCATOR), 201)


def _receipt(api, program_id, item_id, **overrides):
    payload = dict(RECEIPT_20, program_id=program_id, item_id=item_id)
    payload.setdefault("reference", "ASN-7001")
    payload.update(overrides)
    return validate_success(api.create_receipt(payload, ALLOCATOR), 201)


def _two_store_network(api, profile_overrides=None, item_overrides=None):
    """Program FA26 ACTIVE with stores 0101 and 0102, their shelf plans, the
    TOP-4SZ curve, SKU-1001 and one position in each store."""
    program = _program(api)
    stores = {
        "0101": _store(api, program["id"], STORE_0101),
        "0102": _store(api, program["id"], STORE_0102),
    }
    plans = {
        "0101": _plan(api, stores["0101"]["id"], PLAN_0101),
        "0102": _plan(api, stores["0102"]["id"], PLAN_0102),
    }
    profile = _profile(api, program["id"], **(profile_overrides or {}))
    item = _item(api, program["id"], profile["id"], **(item_overrides or {}))
    program = validate_success(api.activate_program(program["id"], ADMIN))
    positions = {
        "0101": _position(api, stores["0101"]["id"], item["id"], POSITION_0101),
        "0102": _position(api, stores["0102"]["id"], item["id"], POSITION_0102),
    }
    return {
        "program": program,
        "stores": stores,
        "fixture_plans": plans,
        "size_profile": profile,
        "item": item,
        "positions": positions,
    }


def test_every_creation_answers_201_with_its_full_declared_representation(api):
    """PRD §4: "Creating a brand-new resource returns HTTP 201; every other
    successful call — reads, patches, state transitions and sweeps — returns HTTP
    200." PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." PRD §2.4: "`version` is an integer that begins at 1 when the resource
    is created and increases by exactly 1 on each mutation."

    Each creation body must already carry its echoed inputs, its system fields at
    their declared openings and its computed fields evaluated: PRD §3.1 "A new
    program opens in `PLANNING` with `total_units_received`,
    `total_units_committed` and `open_reserve_units` all at 0 and with `locked_at`
    and `lock_reason` both null", "A store is created with `status` of `ACTIVE`",
    "the service computes `capacity_units` as the fixture count multiplied by the
    facings per fixture multiplied by the units per facing"; PRD §3.2 "Two counts
    are computed and exposed: `size_count`, the number of entries in the curve,
    and `core_size_count`, the number of entries whose `share_bp` reaches the
    threshold", "A new SKU opens with `lifecycle_state` of `ACTIVE` and with
    `broken_store_count` and `size_out_store_count` both at 0"; PRD §3.3 "so a
    brand-new position is created with `broken_size_count`, `stock_status` and
    `assortment_status` already populated" and "A position is created with
    `consolidated_out` set to false"; PRD §3.4 "A newly booked receipt opens in
    `STAGED` with `units_committed` at 0 and `units_unallocated` equal to
    `units_received`"; PRD §3.5 "An event is created in `DRAFT`" and "A `scope` of
    `PROGRAM` covers every store in the program, and both `cluster_code` and
    `store_id` must be null".

    Design: Corner/entities/entity_creation_returns_every_declared_field_on_201
    """
    program = _program(
        api, transfer_min_ratio_bp=18000, scorecard_basis="SIMPLE_AVERAGE"
    )
    assert program["name"] == "FA26 Core Tops"
    assert program["season_code"] == "FA26"
    assert program["banner_code"] == "NORTH"
    assert program["status"] == "PLANNING"
    assert program["transfer_min_ratio_bp"] == 18000
    assert program["scorecard_basis"] == "SIMPLE_AVERAGE"
    assert program["total_units_received"] == 0
    assert program["total_units_committed"] == 0
    assert program["open_reserve_units"] == 0
    assert program["locked_at"] is None
    assert program["lock_reason"] is None
    assert program["version"] == 1
    assert program["created_at"] is not None

    store = _store(api, program["id"], STORE_0101)
    assert store["store_code"] == "0101"
    assert store["grade"] == "A"
    assert store["grade_index_bp"] == 13000
    assert store["cluster_code"] == "URBAN"
    assert store["freight_flat_usd"] == pytest.approx(41.00, abs=0.01)
    assert store["historical_sell_through_bp"] == 6500
    assert store["status"] == "ACTIVE"
    assert store["version"] == 1

    plan = _plan(
        api,
        store["id"],
        dict(
            PLAN_0101,
            fixture_count=3,
            facings_per_fixture=4,
            units_per_facing=5,
            presentation_min_units=12,
        ),
    )
    assert plan["capacity_units"] == 60
    assert plan["presentation_min_units"] == 12
    assert plan.get("effective_to") is None
    assert plan["version"] == 1

    profile = _profile(api, program["id"], core_size_min_share_bp=2000)
    assert profile["size_count"] == 4
    assert profile["core_size_count"] == 3
    assert "version" not in profile
    assert "updated_at" not in profile
    assert profile["created_at"] is not None

    item = _item(api, program["id"], profile["id"], item_type="SEASONAL")
    assert item["replenishment_model_override"] is None
    assert item["replenishment_model"] == "DEMAND_DRIVEN"
    assert item["lifecycle_state"] == "ACTIVE"
    assert item["broken_store_count"] == 0
    assert item["size_out_store_count"] == 0
    assert item["version"] == 1

    activated = validate_success(api.activate_program(program["id"], ADMIN))
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == 2

    position = _position(
        api,
        store["id"],
        item["id"],
        POSITION_0101,
        on_hand_units=10,
        size_on_hand=[
            {"size_code": "S", "units": 3},
            {"size_code": "M", "units": 4},
            {"size_code": "L", "units": 3},
        ],
        min_units=8,
        max_units=20,
        weekly_forecast_units=3,
        trailing_4wk_sales_units=12,
    )
    assert position["on_hand_units"] == 10
    assert units_by_size(position["size_on_hand"]) == {"S": 3, "M": 4, "L": 3}
    assert position["on_order_units"] == 0
    assert position["in_transit_units"] == 0
    assert position["reserved_out_units"] == 0
    assert position["available_units"] == 10
    assert position["broken_size_count"] == 0
    assert position["assortment_status"] == "COMPLETE"
    assert position["stock_status"] == "IN_STOCK"
    assert position["consolidated_out"] is False
    assert position["version"] == 1

    receipt = _receipt(api, program["id"], item["id"])
    assert receipt["units_received"] == 20
    assert receipt["status"] == "STAGED"
    assert receipt["units_committed"] == 0
    assert receipt["units_unallocated"] == 20
    assert receipt["version"] == 1

    event = validate_success(
        api.create_promo_event(
            {
                "program_id": program["id"],
                "event_code": "BTS-A",
                "scope": "PROGRAM",
                "item_class": "APPAREL_TOP",
                "start_date": "2026-08-05T00:00:00Z",
                "end_date": "2026-08-10T00:00:00Z",
                "lift_factor_bp": 11000,
            },
            ADMIN,
        ),
        201,
    )
    assert event["scope"] == "PROGRAM"
    assert event["cluster_code"] is None
    assert event["store_id"] is None
    assert event["item_class"] == "APPAREL_TOP"
    assert event["lift_factor_bp"] == 11000
    assert event["status"] == "DRAFT"
    assert event["version"] == 1


def test_single_reads_return_the_persisted_post_mutation_state(api):
    """PRD §3.3: "A `PlanningAdmin` or `Allocator` may later patch `min_units`,
    `max_units`, `weekly_forecast_units`, `trailing_4wk_sales_units` or
    `on_order_units`; such a patch re-derives the position's stock dimension,
    leaves its assortment dimension entirely alone because the two are
    independent, and advances `version` by one." "otherwise, when
    `available_units` is greater than 0 and strictly less than `min_units` it is
    `LOW`". PRD §3.5: "The event lifecycle is `PlanningAdmin`-driven throughout,
    and each transition advances the event's `version` by one." PRD §3.4: "the
    program's `total_units_received` and `open_reserve_units` are recomputed to
    take it in". PRD §2.9: "`open_reserve_units` is `total_units_received` minus
    `total_units_committed`". PRD §2.4: "For those two kinds, `id` and
    `created_at` are the only common properties present, and the absence of
    `updated_at` and `version` in their payloads is intended rather than an
    omission."

    Design: Corner/entities/single_read_returns_the_persisted_post_mutation_representation
    """
    program = _program(api)
    store = _store(api, program["id"], STORE_0101)
    plan = _plan(
        api,
        store["id"],
        dict(
            PLAN_0101,
            fixture_count=3,
            facings_per_fixture=4,
            units_per_facing=5,
        ),
    )
    profile = _profile(api, program["id"], core_size_min_share_bp=2000)
    item = _item(api, program["id"], profile["id"])
    validate_success(api.activate_program(program["id"], ADMIN))
    position = _position(
        api,
        store["id"],
        item["id"],
        POSITION_0101,
        on_hand_units=10,
        size_on_hand=[
            {"size_code": "S", "units": 3},
            {"size_code": "M", "units": 4},
            {"size_code": "L", "units": 3},
        ],
        min_units=8,
        max_units=20,
        weekly_forecast_units=3,
        trailing_4wk_sales_units=12,
    )
    receipt = _receipt(api, program["id"], item["id"], reference="ASN-7002")
    event = validate_success(
        api.create_promo_event(
            {
                "program_id": program["id"],
                "event_code": "BTS-A",
                "scope": "PROGRAM",
                "item_class": "APPAREL_TOP",
                "start_date": "2026-08-05T00:00:00Z",
                "end_date": "2026-08-10T00:00:00Z",
                "lift_factor_bp": 11000,
            },
            ADMIN,
        ),
        201,
    )

    validate_success(api.patch_store_position(position["id"], {"min_units": 12}, ADMIN))
    validate_success(api.schedule_promo_event(event["id"], ADMIN))

    read_position = validate_success(api.get_store_position(position["id"], ALLOCATOR))
    assert read_position["id"] == position["id"]
    assert read_position["min_units"] == 12
    assert read_position["available_units"] == 10
    assert read_position["stock_status"] == "LOW"
    assert read_position["assortment_status"] == "COMPLETE"
    assert read_position["version"] == 2

    read_event = validate_success(api.get_promo_event(event["id"], ADMIN))
    assert read_event["status"] == "SCHEDULED"
    assert read_event["version"] == 2

    read_program = validate_success(api.get_program(program["id"], ADMIN))
    assert read_program["status"] == "ACTIVE"
    assert read_program["version"] == 2
    assert read_program["total_units_received"] == 20
    assert read_program["total_units_committed"] == 0
    assert read_program["open_reserve_units"] == 20

    read_store = validate_success(api.get_store(store["id"], ADMIN))
    assert read_store["status"] == "ACTIVE"
    assert read_store["version"] == 1

    read_plan = validate_success(api.get_fixture_plan(plan["id"], ADMIN))
    assert read_plan["capacity_units"] == 60
    assert read_plan["version"] == 1

    read_profile = validate_success(api.get_size_profile(profile["id"], ADMIN))
    assert read_profile["size_count"] == 4
    assert read_profile["core_size_count"] == 3
    assert "version" not in read_profile
    assert "updated_at" not in read_profile

    read_item = validate_success(api.get_item(item["id"], ADMIN))
    assert read_item["version"] == 1
    assert read_item["replenishment_model"] == "DEMAND_DRIVEN"
    assert read_item["lifecycle_state"] == "ACTIVE"

    read_receipt = validate_success(api.get_receipt(receipt["id"], ALLOCATOR))
    assert read_receipt["status"] == "STAGED"
    assert read_receipt["units_committed"] == 0
    assert read_receipt["units_unallocated"] == 20
    assert read_receipt["version"] == 1


def _four_store_network(api):
    """Four stores, three of them URBAN with 0103 moved to REMODEL, shelf plans
    for 0101 and 0102 only, and positions at 0101 (empty) and 0102 (12 units)."""
    program = _program(api)
    stores = {
        "0101": _store(api, program["id"], STORE_0101),
        "0102": _store(api, program["id"], STORE_0102),
        "0103": _store(
            api,
            program["id"],
            {
                "store_code": "0103",
                "grade": "B",
                "grade_index_bp": 12500,
                "cluster_code": "URBAN",
                "freight_flat_usd": 42.00,
                "historical_sell_through_bp": 4200,
            },
        ),
        "0104": _store(
            api,
            program["id"],
            {
                "store_code": "0104",
                "grade": "A",
                "grade_index_bp": 11000,
                "cluster_code": "SUBURBAN",
                "freight_flat_usd": 55.00,
                "historical_sell_through_bp": 3100,
            },
        ),
    }
    plans = {
        "0101": _plan(api, stores["0101"]["id"], PLAN_0101),
        "0102": _plan(api, stores["0102"]["id"], PLAN_0102),
    }
    profile = _profile(api, program["id"])
    item = _item(api, program["id"], profile["id"])
    program = validate_success(api.activate_program(program["id"], ADMIN))
    positions = {
        "0101": _position(
            api,
            stores["0101"]["id"],
            item["id"],
            POSITION_0101,
            on_hand_units=0,
            size_on_hand=[],
            min_units=6,
            max_units=20,
            weekly_forecast_units=3,
            trailing_4wk_sales_units=10,
        ),
        "0102": _position(
            api,
            stores["0102"]["id"],
            item["id"],
            POSITION_0102,
            on_hand_units=12,
            size_on_hand=[
                {"size_code": "S", "units": 3},
                {"size_code": "M", "units": 4},
                {"size_code": "L", "units": 3},
                {"size_code": "XL", "units": 2},
            ],
        ),
    }
    validate_success(
        api.set_store_status(stores["0103"]["id"], {"target_status": "REMODEL"}, ADMIN)
    )
    return {
        "program": program,
        "stores": stores,
        "fixture_plans": plans,
        "size_profile": profile,
        "item": item,
        "positions": positions,
    }


def test_store_pages_are_counted_over_the_filtered_set(api):
    """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, its
    minimum accepted value is 1 and its maximum accepted value is 100." "The
    `meta` block of a list response carries `limit` and `offset` echoing the
    values in effect, `total_count` giving the number of records matching the
    filters before pagination is applied, and `has_more`, which is true exactly
    when `offset` plus the number of records in `data` is less than
    `total_count`." PRD §4: "List stores, filterable by program, cluster, status
    and grade".

    Design: Corner/entities/store_listing_pagination_and_filter_composition
    """
    scenario = _four_store_network(api)
    program_id = scenario["program"]["id"]

    page_one, meta_one = validate_paginated(
        api.list_stores(
            ADMIN,
            {
                "program_id": program_id,
                "cluster_code": "URBAN",
                "limit": 2,
                "offset": 0,
            },
        )
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        api.list_stores(
            ADMIN,
            {
                "program_id": program_id,
                "cluster_code": "URBAN",
                "limit": 2,
                "offset": 2,
            },
        )
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    seen = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(set(seen)) == 3
    assert set(row["store_code"] for row in page_one + page_two) == {
        "0101",
        "0102",
        "0103",
    }

    everything, meta_all = validate_paginated(
        api.list_stores(ADMIN, {"program_id": program_id})
    )
    assert len(everything) == 4
    assert meta_all["total_count"] == 4
    assert meta_all["limit"] == 10
    assert meta_all["offset"] == 0
    assert meta_all["has_more"] is False


def test_list_filters_compose_conjunctively_across_three_collections(api):
    """PRD §2.3: "Every filter query parameter documented for a list endpoint is
    optional and combines with the others conjunctively: supplying `program_id`
    and `status` together returns only records matching both." PRD §4: "List
    stores, filterable by program, cluster, status and grade"; "List shelf plans,
    filterable by store and class". PRD §3.3: "The list view filters on
    `store_id`, `item_id`, `stock_status` and `assortment_status` — either
    dimension independently — and is closed to `StoreOperator`."

    Design: Corner/entities/store_listing_pagination_and_filter_composition
    """
    scenario = _four_store_network(api)
    program_id = scenario["program"]["id"]

    urban_active, urban_meta = validate_paginated(
        api.list_stores(
            ADMIN,
            {"program_id": program_id, "cluster_code": "URBAN", "status": "ACTIVE"},
        )
    )
    assert urban_meta["total_count"] == 2
    assert set(row["store_code"] for row in urban_active) == {"0101", "0102"}

    grade_b, grade_meta = validate_paginated(
        api.list_stores(ADMIN, {"program_id": program_id, "grade": "B"})
    )
    assert grade_meta["total_count"] == 2
    assert set(row["store_code"] for row in grade_b) == {"0102", "0103"}

    empty, empty_meta = validate_paginated(
        api.list_stores(ADMIN, {"program_id": program_id, "cluster_code": "MOUNTAIN"})
    )
    assert empty == []
    assert empty_meta["total_count"] == 0

    broken, broken_meta = validate_paginated(
        api.list_store_positions(
            ALLOCATOR,
            {"item_id": scenario["item"]["id"], "assortment_status": "BROKEN"},
        )
    )
    assert broken_meta["total_count"] == 1
    assert broken[0]["id"] == scenario["positions"]["0101"]["id"]

    plans, plans_meta = validate_paginated(
        api.list_fixture_plans(
            ADMIN,
            {
                "store_id": scenario["stores"]["0101"]["id"],
                "item_class": "APPAREL_TOP",
            },
        )
    )
    assert plans_meta["total_count"] == 1
    assert plans[0]["id"] == scenario["fixture_plans"]["0101"]["id"]


@pytest.mark.parametrize(
    "reader,expected_error",
    [
        ("get_program", ApiErrorId.ERR_PROGRAM_NOT_FOUND),
        ("get_store", ApiErrorId.ERR_STORE_NOT_FOUND),
        ("get_fixture_plan", ApiErrorId.ERR_FIXTURE_PLAN_NOT_FOUND),
        ("get_size_profile", ApiErrorId.ERR_SIZE_PROFILE_NOT_FOUND),
        ("get_item", ApiErrorId.ERR_ITEM_NOT_FOUND),
        ("get_store_position", ApiErrorId.ERR_POSITION_NOT_FOUND),
        ("get_receipt", ApiErrorId.ERR_RECEIPT_NOT_FOUND),
        ("get_allocation_run", ApiErrorId.ERR_RUN_NOT_FOUND),
        ("get_allocation_line", ApiErrorId.ERR_LINE_NOT_FOUND),
        ("get_promo_event", ApiErrorId.ERR_PROMO_EVENT_NOT_FOUND),
        ("get_transfer_recommendation", ApiErrorId.ERR_RECOMMENDATION_NOT_FOUND),
        ("get_assortment_action", ApiErrorId.ERR_ASSORTMENT_ACTION_NOT_FOUND),
        ("get_performance_snapshot", ApiErrorId.ERR_SNAPSHOT_NOT_FOUND),
    ],
)
def test_each_path_id_family_answers_with_its_own_not_found(api, reader, expected_error):
    """PRD §2.10: "Path identifiers are resolved strictly left to right, and the
    first one that fails to resolve determines the response." "The identifiers
    used in URLs are `programId`, `storeId`, `fixturePlanId`, `sizeProfileId`,
    `itemId`, `positionId`, `receiptId`, `runId`, `lineId`, `eventId`,
    `recommendationId`, `actionId` and `snapshotId`, and each has its own 404
    error". PRD §2.10 rung 5: "Every path identifier resolves, left to right —
    the matching not-found error, 404."

    Design: Corner/entities/not_found_probes_for_all_thirteen_path_id_families
    """
    response = getattr(api, reader)(UNKNOWN_ID, ADMIN)
    body = validate_error(response, expected_error)
    assert body["error_id"] == expected_error.value


def test_body_foreign_keys_report_the_entity_that_is_actually_missing(api):
    """PRD §2.10: "Foreign keys supplied in a request body resolve against the
    same catalogue and raise the same error for the referenced entity kind".
    PRD §2.10 rung 6: "Every foreign key in the request body resolves — the
    matching not-found error for the referenced entity, 404."

    Design: Corner/entities/not_found_probes_for_all_thirteen_path_id_families
    """
    program = _program(api)
    store = _store(api, program["id"], STORE_0101)
    profile = _profile(api, program["id"])
    item = _item(api, program["id"], profile["id"])

    unknown_item = api.create_store_position(
        {
            "store_id": store["id"],
            "item_id": UNKNOWN_ID,
            "on_hand_units": 0,
            "size_on_hand": [],
            "min_units": 4,
            "max_units": 10,
            "weekly_forecast_units": 2,
            "trailing_4wk_sales_units": 4,
        },
        ALLOCATOR,
    )
    validate_error(unknown_item, ApiErrorId.ERR_ITEM_NOT_FOUND)

    unknown_store = api.create_store_position(
        {
            "store_id": UNKNOWN_ID,
            "item_id": item["id"],
            "on_hand_units": 0,
            "size_on_hand": [],
            "min_units": 4,
            "max_units": 10,
            "weekly_forecast_units": 2,
            "trailing_4wk_sales_units": 4,
        },
        ALLOCATOR,
    )
    validate_error(unknown_store, ApiErrorId.ERR_STORE_NOT_FOUND)

    _, meta = validate_paginated(
        api.list_store_positions(ALLOCATOR, {"item_id": item["id"]})
    )
    assert meta["total_count"] == 0


def test_every_write_shape_rejects_a_single_missing_required_field(api):
    """PRD §2.10 rung 4: "Request body and query shape: every required field
    present, every enum value inside its declared set, every integer inside its
    declared range, monetary values at 2 decimals, datetimes ISO 8601 UTC,
    `limit` between 1 and 100 inclusive and `offset` at least 0 —
    `ERR_INVALID_REQUEST`, 400." "Checks are evaluated in ascending priority and
    the **first** violated check determines the response; later checks are never
    reached", so the shape rule at rung 4 answers before the path-id rule at rung
    5, the body foreign-key rule at rung 6 and every state rule.

    The single-input action shapes are required inputs too: PRD §2.7 "requires
    `expected_receipt_version` in the request body, carrying the client's last
    observed `version` of that receipt. This field is not optional."; PRD §3.1 "An
    `AllocationManager` may take the program `ACTIVE → LOCKED`, supplying a
    `reason` that is stored as `lock_reason`"; PRD §3.8 "It may be **rejected** by
    an `AllocationManager`, which takes it `PROPOSED → REJECTED`, stores the
    supplied `reason` as `reject_reason`"; PRD §3.1 "The store lifecycle is driven
    by a `PlanningAdmin` supplying a `target_status`"; PRD §3.4 "supplying a
    corrected `units_received`, a corrected `size_received` array, and an
    `adjustment_reason` explaining the change"; PRD §2.5 "An admin-only
    test-driving capability sets that clock to a supplied `current_utc` instant."

    Design: Corner/entities/required_field_omission_rejected_on_every_write_shape
    """
    scenario = _two_store_network(api)
    program_id = scenario["program"]["id"]
    item_id = scenario["item"]["id"]
    store_0101 = scenario["stores"]["0101"]["id"]
    store_0102 = scenario["stores"]["0102"]["id"]
    receipt = _receipt(api, program_id, item_id, reference="ASN-7005")
    transfer = validate_success(
        api.create_transfer_recommendation(
            {
                "program_id": program_id,
                "from_store_id": store_0102,
                "to_store_id": store_0101,
                "item_id": item_id,
                "units": 6,
                "expected_from_position_version": scenario["positions"]["0102"][
                    "version"
                ],
            },
            ALLOCATOR,
        ),
        201,
    )

    probes = [
        api.create_program({"name": "No Season", "banner_code": "NORTH"}, ADMIN),
        api.create_store(
            {
                "program_id": program_id,
                "store_code": "0199",
                "grade": "C",
                "cluster_code": "URBAN",
                "freight_flat_usd": 40.00,
                "historical_sell_through_bp": 5000,
            },
            ADMIN,
        ),
        api.create_fixture_plan(
            {
                "store_id": store_0101,
                "item_class": "APPAREL_TOP",
                "effective_from": "2026-10-01T00:00:00Z",
                "fixture_count": 2,
                "facings_per_fixture": 2,
                "units_per_facing": 3,
            },
            ADMIN,
        ),
        api.create_size_profile(
            {
                "program_id": program_id,
                "profile_code": "TOP-NOCURVE",
                "item_class": "APPAREL_TOP",
            },
            ADMIN,
        ),
        api.create_item(
            {
                "program_id": program_id,
                "sku_code": "SKU-1099",
                "style_code": "ST-100",
                "item_class": "APPAREL_TOP",
                "item_type": "BASIC",
                "unit_cost_usd": 10.00,
                "retail_price_usd": 25.00,
            },
            ADMIN,
        ),
        api.create_store_position(
            {
                "store_id": store_0101,
                "item_id": item_id,
                "on_hand_units": 4,
                "min_units": 2,
                "max_units": 8,
                "weekly_forecast_units": 2,
                "trailing_4wk_sales_units": 4,
            },
            ALLOCATOR,
        ),
        api.create_receipt(
            {
                "program_id": program_id,
                "item_id": item_id,
                "reference": "ASN-NODATE",
                "units_received": 4,
                "size_received": [{"size_code": "M", "units": 4}],
            },
            ALLOCATOR,
        ),
        api.create_allocation_run(
            receipt["id"],
            {"method": "DEMAND_DRIVEN", "need_basis": "FORWARD_LOOKING"},
            ALLOCATOR,
        ),
        api.create_promo_event(
            {
                "program_id": program_id,
                "event_code": "NOLIFT",
                "scope": "PROGRAM",
                "start_date": "2026-09-01T00:00:00Z",
                "end_date": "2026-09-05T00:00:00Z",
            },
            ADMIN,
        ),
        api.create_transfer_recommendation(
            {
                "program_id": program_id,
                "from_store_id": store_0102,
                "to_store_id": store_0101,
                "item_id": item_id,
                "expected_from_position_version": scenario["positions"]["0102"][
                    "version"
                ],
            },
            ALLOCATOR,
        ),
        api.create_performance_snapshot({"program_id": program_id}, ALLOCATOR),
        api.lock_program(program_id, MANAGER, {}),
        api.reject_transfer(transfer["id"], {}, MANAGER),
        api.set_store_status(store_0101, {}, ADMIN),
        api.adjust_receipt(
            receipt["id"],
            {"units_received": 24, "size_received": [{"size_code": "M", "units": 24}]},
            ALLOCATOR,
        ),
        api.set_current_utc({}, ADMIN),
    ]
    assert len(probes) == 16
    for index, response in enumerate(probes):
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
        assert response.status_code == 400, f"probe {index} answered with the wrong status"

    for lister, params, expected_total in [
        (api.list_stores, {"program_id": program_id}, 2),
        (api.list_fixture_plans, {"store_id": store_0101}, 1),
        (api.list_size_profiles, {"program_id": program_id}, 1),
        (api.list_items, {"program_id": program_id}, 1),
        (api.list_store_positions, {"item_id": item_id}, 2),
        (api.list_receipts, {"program_id": program_id}, 1),
        (api.list_allocation_runs, {"receipt_id": receipt["id"]}, 0),
        (api.list_promo_events, {"program_id": program_id}, 0),
        (api.list_performance_snapshots, {"program_id": program_id}, 0),
    ]:
        _, meta = validate_paginated(lister(ADMIN, params))
        assert meta["total_count"] == expected_total

    unchanged_transfer = validate_success(
        api.get_transfer_recommendation(transfer["id"], MANAGER)
    )
    assert unchanged_transfer["status"] == "PROPOSED"
    assert unchanged_transfer["reject_reason"] is None
    assert unchanged_transfer["version"] == 1

    unchanged_program = validate_success(api.get_program(program_id, ADMIN))
    assert unchanged_program["status"] == "ACTIVE"
    assert unchanged_program["locked_at"] is None
    assert unchanged_program["lock_reason"] is None

    unchanged_receipt = validate_success(api.get_receipt(receipt["id"], ALLOCATOR))
    assert unchanged_receipt["units_received"] == 20
    assert unchanged_receipt["status"] == "STAGED"
    assert unchanged_receipt["version"] == 1

    # PRD §2.5: the logical clock "before any client sets it, reads exactly
    # `2026-08-01T00:00:00Z`", and the malformed clock probe must not have moved
    # it, so a fresh scorecard still stamps that instant.
    snapshot = validate_success(
        api.create_performance_snapshot(
            {"program_id": program_id, "cluster_code": "URBAN"}, ALLOCATOR
        ),
        201,
    )
    assert snapshot["as_of_date"].startswith("2026-08-01T00:00:00")


def test_omitted_optional_inputs_land_on_their_declared_defaults(api):
    """PRD §3.1: "`transfer_min_ratio_bp` is the minimum benefit-to-landed-cost
    ratio, in basis points, that a rebalancing transfer must clear before it may
    be approved; it must be at least 0, and when omitted it defaults to 15000";
    "`scorecard_basis` is the default variant used for cluster scorecards when a
    snapshot request does not name one, and when omitted it defaults to
    `UNIT_WEIGHTED`". PRD §3.1: "The plan's effective interval runs from
    `effective_from` inclusive to `effective_to` exclusive, and an omitted or null
    `effective_to` means the plan runs forever." PRD §3.2: "The profile also fixes
    what counts as a **CORE size**, through `core_size_min_share_bp`, which
    defaults to 1500 when omitted. A size is CORE when its `share_bp` is greater
    than or equal to that threshold — the comparison is inclusive, so a size
    sitting exactly on the threshold is CORE." PRD §3.2: "When
    `replenishment_model_override` is null — its default — the resolved
    `replenishment_model` follows the type: a `BASIC` SKU resolves to `MIN_MAX`".
    PRD §3.3: "`on_order_units` records units sitting on an open purchase order
    that have not yet reached the DC; it defaults to 0 when omitted"; "A position
    is created with `consolidated_out` set to false"; "the number of the SKU's
    **CORE** sizes for which the position's `size_on_hand` shows zero units, where
    a size code entirely absent from `size_on_hand` counts as zero"; "if
    `broken_size_count` is exactly 1 the position is `SIZE_OUT_RISK`". PRD §3.5: "A
    `scope` of `PROGRAM` covers every store in the program, and both `cluster_code`
    and `store_id` must be null"; "Independently of scope, an optional `item_class`
    restricts the event to a single merchandise class; leaving it null applies the
    event to every class"; "An event is created in `DRAFT`." PRD §2.3: "`limit`
    controls page size: it defaults to 10 when omitted"; "`offset` controls the
    starting position within the result set: it defaults to 0".

    Design: Corner/entities/optional_field_omission_lands_on_declared_defaults
    """
    program = validate_success(
        api.create_program(
            {
                "name": "FA26 Defaults",
                "season_code": "FA26",
                "banner_code": "NORTH",
            },
            ADMIN,
        ),
        201,
    )
    assert program["transfer_min_ratio_bp"] == 15000
    assert program["scorecard_basis"] == "UNIT_WEIGHTED"
    assert program["status"] == "PLANNING"
    assert program["locked_at"] is None
    assert program["lock_reason"] is None

    store = _store(api, program["id"], STORE_0101)

    plan = validate_success(
        api.create_fixture_plan(
            {
                "store_id": store["id"],
                "item_class": "APPAREL_TOP",
                "effective_from": "2026-07-01T00:00:00Z",
                "fixture_count": 3,
                "facings_per_fixture": 4,
                "units_per_facing": 5,
                "presentation_min_units": 12,
            },
            ADMIN,
        ),
        201,
    )
    assert plan["effective_to"] is None
    assert plan["capacity_units"] == 60

    profile = _profile(api, program["id"])
    assert profile["core_size_min_share_bp"] == 1500
    assert profile["size_count"] == 4
    assert profile["core_size_count"] == 4

    item = validate_success(
        api.create_item(
            {
                "program_id": program["id"],
                "sku_code": "SKU-1001",
                "style_code": "ST-100",
                "item_class": "APPAREL_TOP",
                "item_type": "BASIC",
                "size_profile_id": profile["id"],
                "unit_cost_usd": 14.20,
                "retail_price_usd": 36.50,
            },
            ADMIN,
        ),
        201,
    )
    assert item["replenishment_model_override"] is None
    assert item["replenishment_model"] == "MIN_MAX"
    assert item["lifecycle_state"] == "ACTIVE"

    position = validate_success(
        api.create_store_position(
            {
                "store_id": store["id"],
                "item_id": item["id"],
                "on_hand_units": 10,
                "size_on_hand": [
                    {"size_code": "S", "units": 3},
                    {"size_code": "M", "units": 4},
                    {"size_code": "L", "units": 3},
                ],
                "min_units": 8,
                "max_units": 20,
                "weekly_forecast_units": 3,
                "trailing_4wk_sales_units": 12,
            },
            ALLOCATOR,
        ),
        201,
    )
    assert position["on_order_units"] == 0
    assert position["consolidated_out"] is False
    assert position["available_units"] == 10
    assert position["stock_status"] == "IN_STOCK"
    # XL sits exactly on the default 1500 threshold, so it is CORE and its
    # absence from size_on_hand counts as one broken CORE size.
    assert position["broken_size_count"] == 1
    assert position["assortment_status"] == "SIZE_OUT_RISK"

    event = validate_success(
        api.create_promo_event(
            {
                "program_id": program["id"],
                "event_code": "BTS-A",
                "scope": "PROGRAM",
                "start_date": "2026-08-05T00:00:00Z",
                "end_date": "2026-08-10T00:00:00Z",
                "lift_factor_bp": 11000,
            },
            ADMIN,
        ),
        201,
    )
    assert event["cluster_code"] is None
    assert event["store_id"] is None
    assert event["item_class"] is None
    assert event["status"] == "DRAFT"

    rows, meta = validate_paginated(api.list_stores(ADMIN, {"program_id": program["id"]}))
    assert len(rows) == 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False


def test_computed_fields_are_evaluated_by_the_write_that_creates_them(api):
    """PRD §3.1: "the service computes `capacity_units` as the fixture count
    multiplied by the facings per fixture multiplied by the units per facing".
    PRD §3.2: "Two counts are computed and exposed: `size_count`, the number of
    entries in the curve, and `core_size_count`, the number of entries whose
    `share_bp` reaches the threshold"; "a `SEASONAL` SKU to `DEMAND_DRIVEN`".
    PRD §3.3: "`available_units` is `on_hand_units` minus `reserved_out_units`";
    "so a brand-new position is created with `broken_size_count`, `stock_status`
    and `assortment_status` already populated"; "if `broken_size_count` is 0 the
    position is `COMPLETE`"; "when `available_units` is greater than or equal to
    `min_units` and less than or equal to `max_units` it is `IN_STOCK`". PRD §3.4:
    "A newly booked receipt opens in `STAGED` with `units_committed` at 0 and
    `units_unallocated` equal to `units_received`" and "the program's
    `total_units_received` and `open_reserve_units` are recomputed to take it in".
    PRD §2.9: "`open_reserve_units` is `total_units_received` minus
    `total_units_committed`". PRD §3.6: "`units_proposed` is the sum of the lines'
    proposed units and is 0 while the run is `DRAFT`"; "`units_committed` is the
    sum of the lines' allocated units, which stays 0 unless the run has reached
    `COMMITTED`"; "resets `units_proposed`, `unallocated_remainder_units` and
    `eligible_store_count` to 0"; "The run opens in `DRAFT`, records the acting
    `X-User-ID` as `proposed_by_user_id`, and advances the receipt's `version` by
    one."; "Opening the first run against a `STAGED` receipt also drives the
    receipt into `ALLOCATING`."

    Design: Corner/entities/computed_fields_are_derived_at_write_time_from_their_declared_inputs
    """
    program = _program(api)
    store = _store(api, program["id"], STORE_0101)

    plan = validate_success(
        api.create_fixture_plan(
            {
                "store_id": store["id"],
                "item_class": "APPAREL_TOP",
                "effective_from": "2026-07-01T00:00:00Z",
                "fixture_count": 3,
                "facings_per_fixture": 4,
                "units_per_facing": 5,
                "presentation_min_units": 12,
            },
            ADMIN,
        ),
        201,
    )
    assert plan["capacity_units"] == 60

    profile = _profile(api, program["id"], core_size_min_share_bp=2000)
    assert profile["size_count"] == 4
    # S 2000, M 3500 and L 3000 reach the threshold; XL 1500 does not.
    assert profile["core_size_count"] == 3

    item = _item(api, program["id"], profile["id"])
    assert item["replenishment_model"] == "DEMAND_DRIVEN"
    assert item["replenishment_model_override"] is None

    validate_success(api.activate_program(program["id"], ADMIN))

    position = validate_success(
        api.create_store_position(
            {
                "store_id": store["id"],
                "item_id": item["id"],
                "on_hand_units": 10,
                "size_on_hand": [
                    {"size_code": "S", "units": 3},
                    {"size_code": "M", "units": 4},
                    {"size_code": "L", "units": 3},
                ],
                "min_units": 8,
                "max_units": 20,
                "weekly_forecast_units": 3,
                "trailing_4wk_sales_units": 12,
            },
            ALLOCATOR,
        ),
        201,
    )
    assert position["reserved_out_units"] == 0
    assert position["in_transit_units"] == 0
    assert position["available_units"] == 10
    assert position["broken_size_count"] == 0
    assert position["assortment_status"] == "COMPLETE"
    assert position["stock_status"] == "IN_STOCK"

    receipt = _receipt(api, program["id"], item["id"], reference="ASN-7007")
    assert receipt["units_committed"] == 0
    assert receipt["units_unallocated"] == 20
    assert receipt["status"] == "STAGED"

    rolled_up = validate_success(api.get_program(program["id"], ADMIN))
    assert rolled_up["total_units_received"] == 20
    assert rolled_up["total_units_committed"] == 0
    assert rolled_up["open_reserve_units"] == 20

    run = validate_success(
        api.create_allocation_run(
            receipt["id"],
            {
                "method": "DEMAND_DRIVEN",
                "need_basis": "FORWARD_LOOKING",
                "expected_receipt_version": receipt["version"],
            },
            ALLOCATOR,
        ),
        201,
    )
    assert run["status"] == "DRAFT"
    assert run["units_proposed"] == 0
    assert run["units_committed"] == 0
    assert run["unallocated_remainder_units"] == 0
    assert run["eligible_store_count"] == 0
    assert run["proposed_by_user_id"] == ALLOCATOR_USER_ID
    assert run["committed_by_user_id"] is None
    assert run["supersedes_run_id"] is None

    after_run = validate_success(api.get_receipt(receipt["id"], ALLOCATOR))
    assert after_run["status"] == "ALLOCATING"
    assert after_run["units_received"] == 20
    assert after_run["version"] == receipt["version"] + 1


def test_smuggled_system_and_computed_values_are_ignored_not_honoured(api):
    """PRD §2.4: "Each stored resource is addressed by an `id`, which is a
    server-minted UUID carrying no type prefix of any kind — clients never supply
    it"; "`version` is an integer that begins at 1 when the resource is created".
    PRD §2.10 rung 4 admits only these defects: "every required field present,
    every enum value inside its declared set, every integer inside its declared
    range, monetary values at 2 decimals, datetimes ISO 8601 UTC, `limit` between
    1 and 100 inclusive and `offset` at least 0", so a body that is otherwise
    valid is accepted and the server mints the fields it owns. PRD §3.1: "A store
    is created with `status` of `ACTIVE`"; "the service computes `capacity_units`
    as the fixture count multiplied by the facings per fixture multiplied by the
    units per facing". PRD §3.2: "A new SKU opens with `lifecycle_state` of
    `ACTIVE` and with `broken_store_count` and `size_out_store_count` both at 0";
    "The **replenishment model** is what makes a SKU behave one way rather than
    another, and it is resolved rather than stored directly."; "When
    `replenishment_model_override` is null — its default — the resolved
    `replenishment_model` follows the type: a `BASIC` SKU resolves to `MIN_MAX`".
    PRD §3.3: "Three quantities on a position are never supplied by a client and
    are always derived."; "A position is created with `consolidated_out` set to
    false"; "otherwise, when `available_units` is greater than 0 and strictly less
    than `min_units` it is `LOW`". PRD §3.4: "A newly booked receipt opens in
    `STAGED` with `units_committed` at 0 and `units_unallocated` equal to
    `units_received`". PRD §2.7: "supplying one has no effect."

    Design: Corner/entities/system_and_computed_field_input_ignored_never_honoured
    """
    scenario = _two_store_network(api)
    program_id = scenario["program"]["id"]
    profile_id = scenario["size_profile"]["id"]

    store_0103 = validate_success(
        api.create_store(
            {
                "program_id": program_id,
                "store_code": "0103",
                "grade": "C",
                "grade_index_bp": 12500,
                "cluster_code": "SUBURBAN",
                "freight_flat_usd": 42.00,
                "historical_sell_through_bp": 4200,
                "status": "CLOSED",
            },
            ADMIN,
        ),
        201,
    )
    assert store_0103["status"] == "ACTIVE"

    plan_0103 = validate_success(
        api.create_fixture_plan(
            {
                "store_id": store_0103["id"],
                "item_class": "APPAREL_TOP",
                "effective_from": "2026-07-01T00:00:00Z",
                "fixture_count": 3,
                "facings_per_fixture": 4,
                "units_per_facing": 5,
                "presentation_min_units": 12,
                "capacity_units": 9999,
            },
            ADMIN,
        ),
        201,
    )
    assert plan_0103["capacity_units"] == 60

    second_item = validate_success(
        api.create_item(
            {
                "program_id": program_id,
                "sku_code": "SKU-2002",
                "style_code": "ST-200",
                "item_class": "APPAREL_TOP",
                "item_type": "BASIC",
                "size_profile_id": profile_id,
                "unit_cost_usd": 9.00,
                "retail_price_usd": 22.00,
                "replenishment_model": "PUSH",
                "lifecycle_state": "MARKDOWN",
                "broken_store_count": 5,
            },
            ADMIN,
        ),
        201,
    )
    assert second_item["lifecycle_state"] == "ACTIVE"
    assert second_item["replenishment_model"] == "MIN_MAX"
    assert second_item["broken_store_count"] == 0

    smuggling_position = validate_success(
        api.create_store_position(
            {
                "store_id": scenario["stores"]["0102"]["id"],
                "item_id": second_item["id"],
                "on_hand_units": 10,
                "size_on_hand": [
                    {"size_code": "S", "units": 3},
                    {"size_code": "M", "units": 4},
                    {"size_code": "L", "units": 3},
                ],
                "min_units": 12,
                "max_units": 24,
                "weekly_forecast_units": 4,
                "trailing_4wk_sales_units": 10,
                "available_units": 999,
                "stock_status": "OVERSTOCK",
                "in_transit_units": 5,
                "consolidated_out": True,
            },
            ALLOCATOR,
        ),
        201,
    )
    assert smuggling_position["available_units"] == 10
    assert smuggling_position["in_transit_units"] == 0
    assert smuggling_position["consolidated_out"] is False
    assert smuggling_position["stock_status"] == "LOW"

    smuggling_receipt = validate_success(
        api.create_receipt(
            dict(
                RECEIPT_20,
                program_id=program_id,
                item_id=scenario["item"]["id"],
                reference="ASN-7008",
                status="ALLOCATED",
                units_committed=99,
                version=9,
            ),
            ALLOCATOR,
        ),
        201,
    )
    assert smuggling_receipt["status"] == "STAGED"
    assert smuggling_receipt["units_committed"] == 0
    assert smuggling_receipt["units_unallocated"] == 20
    assert smuggling_receipt["version"] == 1

    for minted in (
        store_0103,
        plan_0103,
        second_item,
        smuggling_position,
        smuggling_receipt,
    ):
        assert_mutable_common_fields(minted)
        assert minted["version"] == 1

    # The server-side version, not the smuggled 9, is the token a run must carry.
    run = validate_success(
        api.create_allocation_run(
            smuggling_receipt["id"],
            {
                "method": "DEMAND_DRIVEN",
                "need_basis": "FORWARD_LOOKING",
                "expected_receipt_version": smuggling_receipt["version"],
            },
            ALLOCATOR,
        ),
        201,
    )
    assert run["status"] == "DRAFT"


def test_declared_type_and_range_constraints_are_rejected_as_shape_defects(api):
    """PRD §2.10 rung 4: "Request body and query shape: every required field
    present, every enum value inside its declared set, every integer inside its
    declared range, monetary values at 2 decimals, datetimes ISO 8601 UTC, `limit`
    between 1 and 100 inclusive and `offset` at least 0 — `ERR_INVALID_REQUEST`,
    400." The declared constraints exercised here are PRD §3.1 "a `grade` of `A`,
    `B`, `C` or `D`" and "a `historical_sell_through_bp` trailing-season
    sell-through between 0 and 10000 inclusive"; PRD §3.1 "`fixture_count`
    fixtures of at least one" and "it must be at least 0 and may not exceed the
    computed `capacity_units`"; PRD §3.3 "`max_units` is the ceiling and must be
    greater than or equal to `min_units`"; PRD §3.4 "a `units_received` count of
    at least 1"; PRD §3.6 "declaring the `method` to be used — `MIN_MAX_TOPUP`,
    `DEMAND_DRIVEN` or `PUSH_SIZE_PROFILE`"; PRD §3.5 "a window running from
    `start_date` to `end_date` where the end must not precede the start, and a
    `lift_factor_bp` multiplier in basis points that must be at least 10000"; PRD
    §2.3 "A `limit` below 1 or above 100, or a negative `offset`, is a malformed
    request and is rejected with `ERR_INVALID_REQUEST` and HTTP 400."

    The two interleaved contrasts are semantic, not shape: PRD §3.2 "the `share_bp`
    values must sum to **exactly** 10000; a repeated size code or any other sum is
    refused with `ERR_SIZE_CURVE_INVALID`", and PRD §3.4 "the sum of the `units`
    entries in `size_received` must equal `units_received` exactly or the booking
    is refused with `ERR_SIZE_UNITS_MISMATCH`".

    Design: Corner/entities/type_constraint_violations_rejected_across_enums_ranges_money_and_paging
    """
    program = _program(api)
    store = _store(api, program["id"], STORE_0101)
    _plan(
        api,
        store["id"],
        dict(PLAN_0101, fixture_count=3, facings_per_fixture=4, units_per_facing=5),
    )
    profile = _profile(api, program["id"])
    item = _item(api, program["id"], profile["id"])
    validate_success(api.activate_program(program["id"], ADMIN))
    _position(
        api,
        store["id"],
        item["id"],
        POSITION_0101,
        on_hand_units=12,
        size_on_hand=[
            {"size_code": "S", "units": 3},
            {"size_code": "M", "units": 4},
            {"size_code": "L", "units": 3},
            {"size_code": "XL", "units": 2},
        ],
        min_units=8,
        max_units=20,
        weekly_forecast_units=3,
        trailing_4wk_sales_units=12,
    )
    receipt = _receipt(api, program["id"], item["id"], reference="ASN-7009")

    def store_probe(**overrides):
        payload = dict(
            STORE_0101,
            program_id=program["id"],
            store_code="0191",
            grade="B",
            grade_index_bp=12000,
            freight_flat_usd=40.00,
            historical_sell_through_bp=5000,
        )
        payload.update(overrides)
        return api.create_store(payload, ADMIN)

    def plan_probe(**overrides):
        payload = {
            "store_id": store["id"],
            "item_class": "APPAREL_TOP",
            "effective_from": "2026-10-01T00:00:00Z",
            "fixture_count": 3,
            "facings_per_fixture": 4,
            "units_per_facing": 5,
            "presentation_min_units": 12,
        }
        payload.update(overrides)
        return api.create_fixture_plan(payload, ADMIN)

    def event_probe(**overrides):
        payload = {
            "program_id": program["id"],
            "event_code": "LOWLIFT",
            "scope": "PROGRAM",
            "start_date": "2026-09-01T00:00:00Z",
            "end_date": "2026-09-05T00:00:00Z",
            "lift_factor_bp": 11000,
        }
        payload.update(overrides)
        return api.create_promo_event(payload, ADMIN)

    shape_probes = [
        store_probe(grade="E"),
        store_probe(store_code="0192", historical_sell_through_bp=12000),
        store_probe(store_code="0193", freight_flat_usd=12.345),
        plan_probe(fixture_count=0),
        plan_probe(presentation_min_units=100),
        plan_probe(effective_from="2026-13-45"),
        api.create_store_position(
            {
                "store_id": store["id"],
                "item_id": item["id"],
                "on_hand_units": 4,
                "size_on_hand": [{"size_code": "M", "units": 4}],
                "min_units": 8,
                "max_units": 5,
                "weekly_forecast_units": 2,
                "trailing_4wk_sales_units": 4,
            },
            ALLOCATOR,
        ),
        api.create_receipt(
            {
                "program_id": program["id"],
                "item_id": item["id"],
                "reference": "ASN-ZERO",
                "units_received": 0,
                "size_received": [],
                "receipt_date": "2026-08-01T00:00:00Z",
            },
            ALLOCATOR,
        ),
        api.create_allocation_run(
            receipt["id"],
            {
                "method": "PUSH",
                "need_basis": "FORWARD_LOOKING",
                "expected_receipt_version": receipt["version"],
            },
            ALLOCATOR,
        ),
        event_probe(lift_factor_bp=9000),
        event_probe(
            event_code="BACKWARD",
            start_date="2026-09-10T00:00:00Z",
            end_date="2026-09-05T00:00:00Z",
        ),
        api.list_stores(ADMIN, {"program_id": program["id"], "limit": 0}),
        api.list_stores(ADMIN, {"program_id": program["id"], "limit": 101}),
        api.list_stores(ADMIN, {"program_id": program["id"], "offset": -1}),
    ]
    assert len(shape_probes) == 14
    for index, response in enumerate(shape_probes):
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
        assert response.status_code == 400, f"shape probe {index} used the wrong status"

    validate_error(
        api.create_size_profile(
            {
                "program_id": program["id"],
                "profile_code": "TOP-BAD",
                "item_class": "APPAREL_TOP",
                "size_curve": [
                    {"size_code": "S", "share_bp": 4000},
                    {"size_code": "M", "share_bp": 5000},
                ],
            },
            ADMIN,
        ),
        ApiErrorId.ERR_SIZE_CURVE_INVALID,
    )
    validate_error(
        api.create_receipt(
            {
                "program_id": program["id"],
                "item_id": item["id"],
                "reference": "ASN-MISMATCH",
                "units_received": 10,
                "size_received": [{"size_code": "M", "units": 8}],
                "receipt_date": "2026-08-01T00:00:00Z",
            },
            ALLOCATOR,
        ),
        ApiErrorId.ERR_SIZE_UNITS_MISMATCH,
    )

    for lister, params, expected_total in [
        (api.list_stores, {"program_id": program["id"]}, 1),
        (api.list_size_profiles, {"program_id": program["id"]}, 1),
        (api.list_fixture_plans, {"store_id": store["id"]}, 1),
        (api.list_receipts, {"program_id": program["id"]}, 1),
        (api.list_promo_events, {"program_id": program["id"]}, 0),
        (api.list_allocation_runs, {"receipt_id": receipt["id"]}, 0),
    ]:
        _, meta = validate_paginated(lister(ADMIN, params))
        assert meta["total_count"] == expected_total

    assert validate_success(api.get_store(store["id"], ADMIN))["status"] == "ACTIVE"


def test_the_two_immutable_entities_carry_no_version_and_are_never_recomputed(api):
    """PRD §2.4: "For those two kinds, `id` and `created_at` are the only common
    properties present, and the absence of `updated_at` and `version` in their
    payloads is intended rather than an omission". PRD §3.2: "Because a size
    profile is immutable, it carries only `id` and `created_at` and has neither
    `updated_at` nor `version`." PRD §3.9: "The snapshot records `as_of_date` from
    the logical clock and is immutable thereafter, which is why it carries neither
    `updated_at` nor `version`."; "optionally naming a `basis` of `SIMPLE_AVERAGE`
    or `UNIT_WEIGHTED`; when `basis` is omitted it falls back to the program's
    `scorecard_basis`"; "`store_count` is the number of distinct stores
    contributing at least one included position and `included_position_count` is
    the number of included positions"; "A position's **covered** units are the
    lesser of its `available_units` and its `min_units`."; "Its **base** is its
    sold units plus its `available_units`."; "`in_stock_pct_bp` is 10000 basis
    points when the sum of `min_units` across included positions is 0, and
    otherwise the sum of covered units multiplied by 10000, divided by the sum of
    `min_units`, truncated down to a whole number of basis points."; "the sum of
    sold units multiplied by 10000, divided by the sum of the bases, truncated
    down"; "Otherwise it is 10000 less the deviation multiplied by 10000 and
    divided by total sold with the quotient truncated down, and that result floored
    at 0 so the figure never goes negative." PRD §3.3: "such a patch re-derives the
    position's stock dimension, leaves its assortment dimension entirely alone
    because the two are independent, and advances `version` by one".

    Design: Corner/entities/immutable_entities_expose_no_version_and_no_update_surface
    """
    program = _program(api)
    store = _store(api, program["id"], STORE_0101)
    _plan(
        api,
        store["id"],
        dict(PLAN_0101, fixture_count=3, facings_per_fixture=4, units_per_facing=5),
    )
    profile = _profile(api, program["id"], core_size_min_share_bp=2000)
    item = _item(api, program["id"], profile["id"])
    validate_success(api.activate_program(program["id"], ADMIN))
    position = _position(
        api,
        store["id"],
        item["id"],
        POSITION_0101,
        on_hand_units=10,
        size_on_hand=[
            {"size_code": "S", "units": 3},
            {"size_code": "M", "units": 4},
            {"size_code": "L", "units": 3},
        ],
        min_units=8,
        max_units=20,
        weekly_forecast_units=3,
        trailing_4wk_sales_units=12,
    )

    first = validate_success(
        api.create_performance_snapshot(
            {"program_id": program["id"], "cluster_code": "URBAN"}, ALLOCATOR
        ),
        201,
    )
    assert first["basis"] == "UNIT_WEIGHTED"
    assert first["as_of_date"].startswith("2026-08-01T00:00:00")
    assert first["store_count"] == 1
    assert first["included_position_count"] == 1
    # covered = min(10, 8) = 8 against a min_units sum of 8.
    assert first["in_stock_pct_bp"] == 10000
    # sold 12 over a base of 12 + 10 = 22, truncated down.
    assert first["sell_through_pct_bp"] == 5454
    assert first["allocation_accuracy_bp"] == 0
    assert_no_mutable_common_fields(first)

    read_profile = validate_success(api.get_size_profile(profile["id"], ADMIN))
    assert_no_mutable_common_fields(read_profile)
    assert_no_mutable_common_fields(profile)

    patched = validate_success(
        api.patch_store_position(position["id"], {"trailing_4wk_sales_units": 30}, ALLOCATOR)
    )
    assert patched["version"] == 2
    assert patched["trailing_4wk_sales_units"] == 30

    validate_success(api.set_current_utc({"current_utc": "2026-08-05T00:00:00Z"}, ADMIN))

    second = validate_success(
        api.create_performance_snapshot(
            {"program_id": program["id"], "cluster_code": "URBAN"}, ALLOCATOR
        ),
        201,
    )
    assert second["as_of_date"].startswith("2026-08-05T00:00:00")
    assert second["in_stock_pct_bp"] == 10000
    # sold 30 over a base of 30 + 10 = 40.
    assert second["sell_through_pct_bp"] == 7500
    assert second["allocation_accuracy_bp"] == 0
    assert_no_mutable_common_fields(second)

    reread_first = validate_success(api.get_performance_snapshot(first["id"], ALLOCATOR))
    assert reread_first["sell_through_pct_bp"] == 5454
    assert reread_first["as_of_date"].startswith("2026-08-01T00:00:00")
    assert_no_mutable_common_fields(reread_first)

    assert first["id"] != second["id"]
    rows, meta = validate_paginated(
        api.list_performance_snapshots(
            ALLOCATOR, {"program_id": program["id"], "cluster_code": "URBAN"}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


def test_no_write_may_stitch_two_programs_together(api):
    """PRD §2.10: "Resources may not be joined across programs. Every write that
    references more than one entity must find them all inside the same allocation
    program: a SKU's `size_profile_id` must name a size profile of the SKU's own
    program; a position's store and SKU must share a program; a receipt's SKU must
    belong to the receipt's `program_id`; a transfer's donor store, receiving store
    and SKU must all belong to its `program_id`; and a promotional event's
    `store_id` must belong to its `program_id`. A violation is rejected with
    `ERR_CROSS_PROGRAM_REFERENCE` and HTTP 422. The five writes that carry this
    check are SKU creation, position creation, receipt creation, transfer creation
    and promotional-event creation." The rungs are ordered "6. Every foreign key in
    the request body resolves — the matching not-found error for the referenced
    entity, 404." then "7. Program cohesion across referenced entities —
    `ERR_CROSS_PROGRAM_REFERENCE`, 422.", so an id that resolves nowhere answers
    404 while an id that resolves into the other program answers 422. The natural
    keys are program-scoped: PRD §3.1 "a `store_code` that must be unique within
    that program", PRD §3.2 "A `profile_code` already used within the same program
    is refused with `ERR_DUPLICATE_PROFILE_CODE`" and "a `sku_code` unique within
    that program".

    Design: Corner/entities/every_child_write_must_resolve_a_same_program_parent
    """
    program_a = _program(api)
    store_a1 = _store(api, program_a["id"], STORE_0101)
    store_a2 = _store(api, program_a["id"], STORE_0102)
    profile_a = _profile(api, program_a["id"])
    item_a = _item(api, program_a["id"], profile_a["id"])
    validate_success(api.activate_program(program_a["id"], ADMIN))
    _position(api, store_a1["id"], item_a["id"], POSITION_0101)
    position_a2 = _position(api, store_a2["id"], item_a["id"], POSITION_0102)

    # Program B reuses store_code 0101, profile_code TOP-4SZ and sku_code SKU-1001.
    program_b = _program(api, name="SP27 Other", season_code="SP27", banner_code="SOUTH")
    store_b1 = _store(api, program_b["id"], STORE_0101)
    profile_b = _profile(api, program_b["id"])
    item_b = _item(api, program_b["id"], profile_b["id"])

    cross_program_probes = [
        api.create_item(
            {
                "program_id": program_a["id"],
                "sku_code": "SKU-3003",
                "style_code": "ST-300",
                "item_class": "APPAREL_TOP",
                "item_type": "BASIC",
                "size_profile_id": profile_b["id"],
                "unit_cost_usd": 9.00,
                "retail_price_usd": 22.00,
            },
            ADMIN,
        ),
        api.create_store_position(
            {
                "store_id": store_a1["id"],
                "item_id": item_b["id"],
                "on_hand_units": 0,
                "size_on_hand": [],
                "min_units": 4,
                "max_units": 10,
                "weekly_forecast_units": 2,
                "trailing_4wk_sales_units": 4,
            },
            ALLOCATOR,
        ),
        api.create_receipt(
            {
                "program_id": program_a["id"],
                "item_id": item_b["id"],
                "reference": "ASN-XPROG",
                "units_received": 4,
                "size_received": [{"size_code": "M", "units": 4}],
                "receipt_date": "2026-08-01T00:00:00Z",
            },
            ALLOCATOR,
        ),
        api.create_promo_event(
            {
                "program_id": program_a["id"],
                "event_code": "XPROG",
                "scope": "STORE",
                "store_id": store_b1["id"],
                "item_class": "APPAREL_TOP",
                "start_date": "2026-09-01T00:00:00Z",
                "end_date": "2026-09-05T00:00:00Z",
                "lift_factor_bp": 11000,
            },
            ADMIN,
        ),
        api.create_transfer_recommendation(
            {
                "program_id": program_a["id"],
                "from_store_id": store_a2["id"],
                "to_store_id": store_b1["id"],
                "item_id": item_a["id"],
                "units": 6,
                "expected_from_position_version": position_a2["version"],
            },
            ALLOCATOR,
        ),
    ]
    assert len(cross_program_probes) == 5
    for index, response in enumerate(cross_program_probes):
        validate_error(response, ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE)
        assert response.status_code == 422, f"cohesion probe {index} used the wrong status"

    validate_error(
        api.create_promo_event(
            {
                "program_id": program_a["id"],
                "event_code": "GHOST",
                "scope": "STORE",
                "store_id": UNKNOWN_ID,
                "item_class": "APPAREL_TOP",
                "start_date": "2026-09-01T00:00:00Z",
                "end_date": "2026-09-05T00:00:00Z",
                "lift_factor_bp": 11000,
            },
            ADMIN,
        ),
        ApiErrorId.ERR_STORE_NOT_FOUND,
    )

    for lister, params, expected_total in [
        (api.list_items, {"program_id": program_a["id"]}, 1),
        (api.list_store_positions, {"item_id": item_a["id"]}, 2),
        (api.list_receipts, {"program_id": program_a["id"]}, 0),
        (api.list_promo_events, {"program_id": program_a["id"]}, 0),
        (api.list_transfer_recommendations, {"program_id": program_a["id"]}, 0),
    ]:
        _, meta = validate_paginated(lister(ADMIN, params))
        assert meta["total_count"] == expected_total


POSITION_0101_SKU2002 = {
    "on_hand_units": 2,
    "size_on_hand": [{"size_code": "M", "units": 2}],
    "min_units": 4,
    "max_units": 12,
    "weekly_forecast_units": 2,
    "trailing_4wk_sales_units": 6,
}


def _junction_network(api):
    """The two-store network plus a second SKU positioned in store 0101 and a
    20-unit STAGED receipt, so the store leg of the junction already carries two
    rows before anything is probed."""
    network = _two_store_network(api)
    network["item2"] = _item(
        api,
        network["program"]["id"],
        network["size_profile"]["id"],
        sku_code="SKU-2002",
        style_code="ST-200",
        item_type="BASIC",
    )
    network["positions"]["0101-SKU-2002"] = _position(
        api,
        network["stores"]["0101"]["id"],
        network["item2"]["id"],
        POSITION_0101_SKU2002,
    )
    network["receipt"] = _receipt(
        api,
        network["program"]["id"],
        network["item"]["id"],
        reference="ASN-7012",
    )
    return network


def test_the_store_sku_pair_is_unique_and_navigable_from_either_leg(api):
    """PRD §3.3: "The pairing of one store with one SKU is materialised as a
    **store position**" and "Only one position may exist for a given store-and-SKU
    pair; a second attempt is refused with `ERR_DUPLICATE_POSITION`." The
    constraint is on the pair, not on either column alone, and PRD §3.3 makes both
    legs queryable: "The list view filters on `store_id`, `item_id`,
    `stock_status` and `assortment_status` — either dimension independently".

    Design: Corner/entities/junction_uniqueness_and_self_referential_supersede_edges
    """
    network = _junction_network(api)
    store_0101 = network["stores"]["0101"]["id"]
    item_1001 = network["item"]["id"]

    duplicate = api.create_store_position(
        {
            "store_id": store_0101,
            "item_id": item_1001,
            "on_hand_units": 2,
            "size_on_hand": [{"size_code": "M", "units": 2}],
            "min_units": 4,
            "max_units": 10,
            "weekly_forecast_units": 2,
            "trailing_4wk_sales_units": 4,
        },
        ALLOCATOR,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_POSITION)
    assert duplicate.status_code == 409

    by_store, store_meta = validate_paginated(
        api.list_store_positions(ADMIN, {"store_id": store_0101})
    )
    assert store_meta["total_count"] == 2
    assert {row["item_id"] for row in by_store} == {item_1001, network["item2"]["id"]}

    by_item, item_meta = validate_paginated(
        api.list_store_positions(ADMIN, {"item_id": item_1001})
    )
    assert item_meta["total_count"] == 2
    assert {row["store_id"] for row in by_item} == {
        store_0101,
        network["stores"]["0102"]["id"],
    }

    _, all_meta = validate_paginated(api.list_store_positions(ADMIN, {}))
    assert all_meta["total_count"] == 3


def test_self_referential_supersede_edges_retire_their_peer_and_read_back(api):
    """PRD §3.6: "If any sibling run on the same receipt is sitting in `DRAFT` or
    `PROPOSED`, that sibling is driven to `CANCELLED`, the new run's
    `supersedes_run_id` is set to the superseded sibling's identifier", the run
    "advances the receipt's `version` by one" and "Opening the first run against a
    `STAGED` receipt also drives the receipt into `ALLOCATING`.", so the second
    creation can only be made with the refreshed token. PRD §3.6 also makes the
    edge queryable backwards: "the filtered list view over runs accepts
    `receipt_id`, `supersedes_run_id` and `status` as filters". PRD §3.8 repeats the
    shape for transfers: "Donor and receiver must differ, or the request is refused
    with `ERR_SAME_STORE_TRANSFER`.", creation "advances the donor position's
    `version` by one to record the new claim staked against it", and "If any
    recommendation on the identical donor-store, receiving-store and SKU triple is
    already sitting in `PROPOSED`, that peer is driven to `CANCELLED` with its
    `reject_reason` set to the string `superseded`, its `version` advances by one,
    and the new recommendation's `supersedes_recommendation_id` points at it." That
    list "filters on `program_id`, `from_store_id`, `to_store_id`, `item_id`,
    `supersedes_recommendation_id`, `assortment_action_id` and `status`".

    Design: Corner/entities/junction_uniqueness_and_self_referential_supersede_edges
    """
    network = _junction_network(api)
    program_id = network["program"]["id"]
    store_0101 = network["stores"]["0101"]["id"]
    store_0102 = network["stores"]["0102"]["id"]
    item_1001 = network["item"]["id"]
    donor = network["positions"]["0102"]
    receipt = network["receipt"]

    self_loop = api.create_transfer_recommendation(
        {
            "program_id": program_id,
            "from_store_id": store_0102,
            "to_store_id": store_0102,
            "item_id": item_1001,
            "units": 6,
            "expected_from_position_version": donor["version"],
        },
        ALLOCATOR,
    )
    validate_error(self_loop, ApiErrorId.ERR_SAME_STORE_TRANSFER)
    assert self_loop.status_code == 422

    run_payload = {
        "method": "DEMAND_DRIVEN",
        "need_basis": "FORWARD_LOOKING",
        "expected_receipt_version": receipt["version"],
    }
    run_one = validate_success(
        api.create_allocation_run(receipt["id"], run_payload, ALLOCATOR), 201
    )
    assert run_one["status"] == "DRAFT"
    assert run_one["supersedes_run_id"] is None

    refreshed_receipt = validate_success(api.get_receipt(receipt["id"], ALLOCATOR))
    assert refreshed_receipt["version"] == receipt["version"] + 1
    assert refreshed_receipt["status"] == "ALLOCATING"

    run_two = validate_success(
        api.create_allocation_run(
            receipt["id"],
            dict(run_payload, expected_receipt_version=refreshed_receipt["version"]),
            ALLOCATOR,
        ),
        201,
    )
    assert run_two["supersedes_run_id"] == run_one["id"]
    assert validate_success(api.get_allocation_run(run_one["id"], ALLOCATOR))[
        "status"
    ] == "CANCELLED"

    successors, run_meta = validate_paginated(
        api.list_allocation_runs(ALLOCATOR, {"supersedes_run_id": run_one["id"]})
    )
    assert run_meta["total_count"] == 1
    assert [row["id"] for row in successors] == [run_two["id"]]

    transfer_payload = {
        "program_id": program_id,
        "from_store_id": store_0102,
        "to_store_id": store_0101,
        "item_id": item_1001,
        "units": 6,
        "expected_from_position_version": donor["version"],
    }
    transfer_one = validate_success(
        api.create_transfer_recommendation(transfer_payload, ALLOCATOR), 201
    )
    assert transfer_one["status"] == "PROPOSED"
    assert transfer_one["supersedes_recommendation_id"] is None

    refreshed_donor = validate_success(api.get_store_position(donor["id"], ALLOCATOR))
    assert refreshed_donor["version"] == donor["version"] + 1

    transfer_two = validate_success(
        api.create_transfer_recommendation(
            dict(
                transfer_payload,
                units=4,
                expected_from_position_version=refreshed_donor["version"],
            ),
            ALLOCATOR,
        ),
        201,
    )
    assert transfer_two["supersedes_recommendation_id"] == transfer_one["id"]

    retired = validate_success(
        api.get_transfer_recommendation(transfer_one["id"], ALLOCATOR)
    )
    assert retired["status"] == "CANCELLED"
    assert retired["reject_reason"] == "superseded"
    assert retired["version"] == transfer_one["version"] + 1

    heirs, transfer_meta = validate_paginated(
        api.list_transfer_recommendations(
            ALLOCATOR, {"supersedes_recommendation_id": transfer_one["id"]}
        )
    )
    assert transfer_meta["total_count"] == 1
    assert [row["id"] for row in heirs] == [transfer_two["id"]]
