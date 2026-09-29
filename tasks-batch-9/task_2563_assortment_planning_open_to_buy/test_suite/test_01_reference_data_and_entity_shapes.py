"""Reference-data entity shapes: creation echoes, retrieval, listing, defaults,
system-generated fields, type constraints, immutable append-only rows, body
foreign-key resolution order and the vendor-authorization junction.

Every test builds its own reference spine from scratch, because the database is
empty when each test starts.
"""
from test_helpers import (
    ApiErrorId,
    CANONICAL_M1_OTB_PLANNED_CENTS,
    CLOCK_STARTUP_UTC,
    assert_actuals_post,
    assert_department,
    assert_plan_month,
    assert_size_curve_cell,
    create_category,
    create_category_plan,
    create_department,
    create_option_plan,
    create_plan_month,
    create_store_cluster,
    create_vendor,
    get_month,
    get_option_plan,
    get_plan,
    is_iso8601_timestamp,
    is_valid_uuid,
    month_version,
    post_actuals,
    propose_item,
    receipt_commitment_payload,
    replace_size_curve,
    set_clock,
    setup_in_season_plan,
    setup_reference_spine,
    setup_single_month_approved_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

# Syntactically valid UUIDs that match no row in an empty database.
UNKNOWN_ID_1 = "11111111-1111-4111-8111-111111111111"
UNKNOWN_ID_2 = "22222222-2222-4222-8222-222222222222"
UNKNOWN_ID_3 = "33333333-3333-4333-8333-333333333333"

DEPARTMENT_INPUT = {
    "name": "Womens Apparel",
    "code": "WAPP",
    "fiscal_year": 2027,
    "sales_target_cents": 500_000_000,
    "margin_target_bps": 5600,
    "turn_target_x100": 320,
}


def test_department_create_echoes_every_declared_field(api, admin_headers, planner_headers):
    """PRD §3.1: "A **Department** is created with a `name` of 1 to 120 characters, a `code` of 2 to 8 uppercase characters that must be unique across all departments, and the `fiscal_year` between 2000 and 2100 that its financial targets belong to."

    PRD §3.1: "Its three targets are the annual net sales target at retail in cents, `sales_target_cents`, which must be at least 1; the gross margin target in basis points of retail sales, `margin_target_bps`, between 0 and 9999; and the inventory turn target scaled by one hundred, `turn_target_x100`, which must be at least 1, so a 3.50-turn goal is submitted as 350."

    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    PRD §2.4: "Every resource the API mints carries an `id` that is a server-generated UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits (for example `2027-02-14T09:00:00.000Z`)."

    Design: Corner/entities/department_create_echoes_every_declared_field
    """
    set_clock(CLOCK_STARTUP_UTC)

    response = api.create_department(dict(DEPARTMENT_INPUT), admin_headers)
    data = validate_success(response, 201)
    assert response.json()["response_type"] == "object", (
        "a single created department must come back as response_type 'object'"
    )

    for field, expected in DEPARTMENT_INPUT.items():
        assert data[field] == expected, (
            f"Department.{field} must be echoed as {expected!r}, got {data.get(field)!r}"
        )

    assert_department(data)
    assert is_valid_uuid(data["id"]), "Department.id must be a server-generated UUID"
    assert is_iso8601_timestamp(data["created_at"]), (
        "Department.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data["updated_at"]), (
        "Department.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert data["version"] == 1, "a freshly created department must carry version 1"

    read_back = validate_success(api.get_department(data["id"], planner_headers))
    assert read_back["id"] == data["id"], "the read must address the created department"
    for field, expected in DEPARTMENT_INPUT.items():
        assert read_back[field] == expected, (
            f"Department.{field} must survive the round trip as {expected!r}, "
            f"got {read_back.get(field)!r}"
        )


def test_plan_month_get_by_id_returns_stored_row(api, planner_headers):
    """PRD §3.3: "A **PlanMonth** is added with `category_plan_id`, a `month_index` between 1 and 12 that must be unique within the plan and is the sole ordering key for every waterfall in the system, and a `fiscal_month_label` of exactly seven characters in `YYYY-MM` form."

    PRD §3.3: "Four monetary inputs, each an integer count of cents of at least 0, describe the month: `bom_inventory_cents`, the beginning-of-month inventory at cost; `planned_sales_cents`, the planned net sales at retail; `planned_markdown_cents`, the planned markdown dollars at cost; and `planned_eom_cents`, the planned end-of-month inventory at cost."

    PRD §3.3: "A new month is created in `DRAFT` with `active_basis` set to `PLANNED_BASIS` and with every computed open-to-buy figure — `provisional_sell_through_bps`, `reserve_rate_bps`, `markdown_reserve_cents`, `otb_planned_cents`, `otb_committed_cents`, `otb_received_cents` and `otb_open_cents` — at 0."

    Design: Corner/entities/plan_month_get_by_id_returns_stored_row
    """
    set_clock(CLOCK_STARTUP_UTC)
    department = create_department()
    category = create_category(department["id"])
    plan = create_category_plan(category["id"])
    month = create_plan_month(
        plan["id"],
        month_index=1,
        fiscal_month_label="2027-03",
        first_receipt_date="2027-03-05T00:00:00Z",
        bom_inventory_cents=20_000_000,
        planned_sales_cents=30_000_000,
        planned_markdown_cents=2_000_000,
        planned_eom_cents=22_000_000,
    )

    data = validate_success(api.get_plan_month(month["id"], planner_headers))

    assert data["id"] == month["id"], "the read must return the addressed plan month"
    assert data["category_plan_id"] == plan["id"], (
        "PlanMonth.category_plan_id must point at the plan it was authored under"
    )
    assert data["month_index"] == 1, "PlanMonth.month_index must be stored as authored"
    assert data["fiscal_month_label"] == "2027-03", (
        "PlanMonth.fiscal_month_label must be the authored YYYY-MM string"
    )
    assert data["bom_inventory_cents"] == 20_000_000, "authored bom_inventory_cents must persist"
    assert data["planned_sales_cents"] == 30_000_000, "authored planned_sales_cents must persist"
    assert data["planned_markdown_cents"] == 2_000_000, (
        "authored planned_markdown_cents must persist"
    )
    assert data["planned_eom_cents"] == 22_000_000, "authored planned_eom_cents must persist"

    assert data["status"] == "DRAFT", "a new plan month is created in DRAFT"
    assert data["active_basis"] == "PLANNED_BASIS", (
        "a new plan month is created on PLANNED_BASIS"
    )

    for field in (
        "provisional_sell_through_bps",
        "reserve_rate_bps",
        "markdown_reserve_cents",
        "otb_planned_cents",
        "otb_committed_cents",
        "otb_received_cents",
        "otb_open_cents",
    ):
        assert data[field] == 0, (
            f"PlanMonth.{field} must be 0 on a month that no approval has locked yet, "
            f"got {data.get(field)!r}"
        )

    assert_plan_month(data)


def test_assortment_item_list_filters_paginate_and_reject_bad_pagination(
    api, planner_headers, buyer_headers
):
    """PRD §3.5: "Item listings can be narrowed by `option_plan_id`, `vendor_id`, `lifecycle_stage` or `status`."

    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filter before pagination is applied."

    PRD §2.3: "Unless a specific list endpoint states otherwise, rows are returned sorted by `created_at` ascending."

    PRD §2.3: "A `limit` outside 1 through 100, or a negative or non-integer `offset`, is rejected with `ERR_INVALID_PAGINATION` (400)."

    Design: Corner/entities/assortment_item_list_filters_paginate_and_reject_bad_pagination
    """
    spine = setup_reference_spine(vendor_authorized=False, authorize_category=False)
    plan = create_category_plan(spine["category"]["id"])
    option_plan = create_option_plan(plan["id"], spine["store_cluster"]["id"])
    vendor_id = spine["vendor"]["id"]

    item_a1 = validate_success(
        api.create_assortment_item(
            {
                "option_plan_id": option_plan["id"],
                "vendor_id": vendor_id,
                "sku_code": "DRSS-A1",
                "color_code": "NAVY",
                "lifecycle_stage": "CARRYOVER",
                "unit_cost_cents": 2500,
                "retail_price_cents": 6900,
                "prior_season_sell_through_bps": 7100,
            },
            buyer_headers,
        ),
        201,
    )
    item_a2 = validate_success(
        api.create_assortment_item(
            {
                "option_plan_id": option_plan["id"],
                "vendor_id": vendor_id,
                "sku_code": "DRSS-A2",
                "color_code": "BLACK",
                "lifecycle_stage": "CARRYOVER",
                "unit_cost_cents": 2500,
                "retail_price_cents": 6900,
                "prior_season_sell_through_bps": 6800,
            },
            buyer_headers,
        ),
        201,
    )
    item_a3 = validate_success(
        api.create_assortment_item(
            {
                "option_plan_id": option_plan["id"],
                "vendor_id": vendor_id,
                "sku_code": "DRSS-A3",
                "color_code": "CORAL",
                "lifecycle_stage": "NEW",
                "unit_cost_cents": 2500,
                "retail_price_cents": 7500,
            },
            buyer_headers,
        ),
        201,
    )

    filtered_response = api.list_assortment_items(
        planner_headers,
        params={"option_plan_id": option_plan["id"], "lifecycle_stage": "CARRYOVER"},
    )
    rows, meta = validate_paginated(filtered_response)
    assert filtered_response.json()["response_type"] == "array", (
        "a list read must come back as response_type 'array'"
    )
    assert meta["total_count"] == 2, (
        "total_count must count the CARRYOVER rows only, not every item on the cell"
    )
    assert meta["has_more"] is False, "two of two filtered rows leaves nothing more to page"
    assert len(rows) == 2, f"the filtered page must hold both CARRYOVER items, got {len(rows)}"
    assert {row["id"] for row in rows} == {item_a1["id"], item_a2["id"]}, (
        "the lifecycle_stage filter must return exactly the two CARRYOVER items"
    )
    assert item_a3["id"] not in {row["id"] for row in rows}, (
        "the NEW item must be excluded by the lifecycle_stage CARRYOVER filter"
    )
    first_listed = rows[0]["id"]

    paged_response = api.list_assortment_items(
        planner_headers,
        params={
            "option_plan_id": option_plan["id"],
            "lifecycle_stage": "CARRYOVER",
            "limit": 1,
            "offset": 1,
        },
    )
    paged_rows, paged_meta = validate_paginated(paged_response)
    assert len(paged_rows) == 1, "limit 1 must return exactly one row"
    assert paged_meta["limit"] == 1, "meta.limit must echo the requested limit"
    assert paged_meta["offset"] == 1, "meta.offset must echo the requested offset"
    assert paged_meta["total_count"] == 2, (
        "total_count must still count the filtered set of 2, not all three items"
    )
    assert paged_meta["has_more"] is False, (
        "offset 1 with limit 1 over 2 filtered rows leaves nothing more to page"
    )
    assert paged_rows[0]["id"] == rows[1]["id"], (
        "the offset-1 page must be the second row of the unpaged filtered list"
    )
    assert paged_rows[0]["id"] != first_listed, (
        "the offset-1 page must skip the first filtered row"
    )

    validate_error(
        api.list_assortment_items(
            planner_headers, params={"option_plan_id": option_plan["id"], "limit": 0}
        ),
        ApiErrorId.ERR_INVALID_PAGINATION,
    )


def test_category_plan_get_unknown_id_returns_not_found(api, planner_headers):
    """PRD §2.7: "Path identifiers are resolved first, left to right, and the first one that matches no row decides the response with that entity's own not-found code: `ERR_DEPARTMENT_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`, `ERR_STORE_CLUSTER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`, `ERR_CATEGORY_PLAN_NOT_FOUND`, `ERR_PLAN_MONTH_NOT_FOUND`, `ERR_OPTION_PLAN_NOT_FOUND`, `ERR_ASSORTMENT_ITEM_NOT_FOUND`, `ERR_RECEIPT_COMMITMENT_NOT_FOUND`, `ERR_REFORECAST_CYCLE_NOT_FOUND`, `ERR_CHASE_CANCEL_DECISION_NOT_FOUND` or `ERR_LOCALIZATION_OVERLAY_NOT_FOUND`, each returned with 404."

    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/category_plan_get_unknown_id_returns_not_found
    """
    set_clock(CLOCK_STARTUP_UTC)

    response = api.get_category_plan(UNKNOWN_ID_1, planner_headers)
    error_data = validate_error(response, ApiErrorId.ERR_CATEGORY_PLAN_NOT_FOUND)

    body = response.json()
    assert body["response_type"] == "error", (
        "an unresolvable path identifier must produce the error envelope, not an empty 200"
    )
    assert isinstance(error_data["message"], str) and error_data["message"].strip(), (
        "the error payload must carry a non-empty human-readable message"
    )
    assert "id" not in error_data, (
        "the error payload must not carry a resource id for a row that does not exist"
    )


def test_store_cluster_create_missing_required_field_rejected(api, admin_headers):
    """PRD §3.1: "It is created with a `name` of 1 to 120 characters, a `climate_zone` of `COLD`, `TEMPERATE` or `HOT`, a `volume_tier` of `A`, `B` or `C`, a `store_count` of at least 1, and two productivity indices expressed in basis points against a chain average of 10000."

    PRD §2.8: "Request-body shape: every required field present, every value of its declared JSON type, every enum value a declared member, every integer within its declared range, every string within its declared length bounds, every ISO-8601 field parseable, and no unknown body field — `ERR_INVALID_REQUEST` (400), on every POST and PUT endpoint."

    Design: Corner/entities/store_cluster_create_missing_required_field_rejected
    """
    set_clock(CLOCK_STARTUP_UTC)

    validate_error(
        api.create_store_cluster(
            {
                "name": "Cold-A",
                "climate_zone": "COLD",
                "demographic_index_bps": 10500,
                "store_count": 40,
                "sales_index_bps": 11500,
            },
            admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    _, empty_meta = validate_paginated(api.list_store_clusters(admin_headers))
    assert empty_meta["total_count"] == 0, (
        "a body missing volume_tier must persist no store cluster at all"
    )

    created = validate_success(
        api.create_store_cluster(
            {
                "name": "Cold-A",
                "climate_zone": "COLD",
                "demographic_index_bps": 10500,
                "volume_tier": "A",
                "store_count": 40,
                "sales_index_bps": 11500,
            },
            admin_headers,
        ),
        201,
    )
    assert created["volume_tier"] == "A", (
        "the accepted body must store the declared volume_tier"
    )

    _, meta = validate_paginated(api.list_store_clusters(admin_headers))
    assert meta["total_count"] == 1, (
        "exactly one store cluster must exist: the rejected call created nothing"
    )


def test_vendor_and_authorization_and_item_defaults_applied(api, admin_headers, buyer_headers):
    """PRD §3.2: "The vendor's `status` is server-owned and is initialised to `PENDING`."

    PRD §3.2: "It is created with `vendor_id`, `category_id` and `max_open_units` of at least 1, which is the ceiling on the units this vendor may hold open — neither received nor cancelled — for that category."

    PRD §3.2: "Its `status` is server-owned, initialised to `ACTIVE`, and only ever `ACTIVE` or `REVOKED` thereafter, moving between the two only through the vendor's suspension and reinstatement described above."

    PRD §3.5: "The optional `prior_season_sell_through_bps`, between 0 and 10000 and defaulting to 0 when omitted, is the option's own history; it is mandatory in substance for a carryover-style forecast and is ignored outright by the new-item forecast."

    PRD §3.5: "A newly proposed item has `status` `PROPOSED`, `sell_through_basis` and `sell_through_bps` and `planned_units` all null, and `effective_overlay_multiplier_bps` at 10000."

    Design: Corner/entities/vendor_and_authorization_and_item_defaults_applied
    """
    set_clock(CLOCK_STARTUP_UTC)
    department = create_department()
    category = create_category(department["id"])
    store_cluster = create_store_cluster()
    plan = create_category_plan(category["id"])
    option_plan = create_option_plan(plan["id"], store_cluster["id"])

    vendor = validate_success(
        api.create_vendor(
            {
                "name": "Aurora Mills",
                "code": "AURM",
                "lead_time_days": 45,
                "weekly_unit_capacity": 12000,
                "min_order_units": 200,
                "cancel_cutoff_days": 21,
            },
            admin_headers,
        ),
        201,
    )
    assert vendor["status"] == "PENDING", (
        "a vendor is created in PENDING even though status was never supplied, so it "
        f"cannot be committed against yet; got {vendor['status']!r}"
    )

    authorization = validate_success(
        api.create_vendor_authorization(
            {
                "vendor_id": vendor["id"],
                "category_id": category["id"],
                "max_open_units": 40000,
            },
            admin_headers,
        ),
        201,
    )
    assert authorization["status"] == "ACTIVE", (
        "a new vendor authorization defaults to ACTIVE, got "
        f"{authorization['status']!r}"
    )
    assert authorization["vendor_id"] == vendor["id"], (
        "the authorization must join the vendor it names"
    )
    assert authorization["category_id"] == category["id"], (
        "the authorization must join the category it names"
    )
    assert authorization["max_open_units"] == 40000, (
        "the authorization must store its declared open-unit ceiling"
    )

    item = validate_success(
        api.create_assortment_item(
            {
                "option_plan_id": option_plan["id"],
                "vendor_id": vendor["id"],
                "sku_code": "DRSS-D1",
                "color_code": "CORAL",
                "lifecycle_stage": "NEW",
                "unit_cost_cents": 2500,
                "retail_price_cents": 7500,
            },
            buyer_headers,
        ),
        201,
    )
    assert item["prior_season_sell_through_bps"] == 0, (
        "an omitted prior_season_sell_through_bps defaults to 0, not null; got "
        f"{item['prior_season_sell_through_bps']!r}"
    )
    assert item["status"] == "PROPOSED", "a newly proposed item starts at PROPOSED"
    assert item["effective_overlay_multiplier_bps"] == 10000, (
        "a newly proposed item starts with effective_overlay_multiplier_bps 10000"
    )
    assert item["sell_through_basis"] is None, (
        "sell_through_basis stays null until the item is adopted"
    )
    assert item["sell_through_bps"] is None, (
        "sell_through_bps stays null until the item is adopted"
    )
    assert item["planned_units"] is None, (
        "planned_units stays null until the item is adopted"
    )


def test_commitment_computed_money_fields_are_not_inputs(api, buyer_headers):
    """PRD §2.8: "Request-body shape: every required field present, every value of its declared JSON type, every enum value a declared member, every integer within its declared range, every string within its declared length bounds, every ISO-8601 field parseable, and no unknown body field — `ERR_INVALID_REQUEST` (400), on every POST and PUT endpoint."

    PRD §3.6: "The commitment's `cost_cents` — its `units` multiplied by its `unit_cost_cents` — is compared against the month's `otb_open_cents`: a cost exactly equal to the open balance is accepted, and one cent more is refused with `ERR_OTB_EXCEEDED`."

    PRD §3.6: "On success the commitment is stored with `commit_status` `PROPOSED`, `fulfillment_status` `AWAITING_SHIP`, `origin` `BUYER`, `received_units` and `cancelled_units` at 0, `cost_cents` computed as above, `open_cost_cents` computed as `units` less `received_units` less `cancelled_units`, multiplied by `unit_cost_cents`, and `received_cost_cents` computed as `received_units` multiplied by `unit_cost_cents`."

    Design: Corner/entities/commitment_computed_money_fields_are_not_inputs
    """
    scenario = setup_single_month_approved_plan(
        size_curve=[{"size_label": "OS", "size_sort_order": 1, "pct_bps": 10000}],
    )
    month_id = scenario["m1"]["id"]
    vendor_id = scenario["vendor"]["id"]
    assert scenario["m1"]["otb_open_cents"] == CANONICAL_M1_OTB_PLANNED_CENTS, (
        "the locked month must carry its full planned open-to-buy before any buying"
    )

    item = propose_item(
        scenario["option_plan"]["id"],
        vendor_id,
        headers=buyer_headers,
        sku_code="DRSS-C1",
        color_code="NAVY",
        lifecycle_stage="CARRYOVER",
        unit_cost_cents=2500,
        retail_price_cents=6900,
        prior_season_sell_through_bps=7100,
    )
    month_version_before = month_version(month_id)

    accepted_body = receipt_commitment_payload(
        month_id, item["id"], vendor_id, month_version_before,
        units=400, unit_cost_cents=2500,
        ship_window_start="2027-03-05T00:00:00Z",
        ship_window_end="2027-03-19T00:00:00Z",
    )
    smuggled_body = dict(accepted_body, cost_cents=1)

    validate_error(
        api.create_receipt_commitment(smuggled_body, buyer_headers),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    _, meta = validate_paginated(
        api.list_receipt_commitments(buyer_headers, params={"plan_month_id": month_id})
    )
    assert meta["total_count"] == 0, (
        "a body smuggling the computed cost_cents must create no commitment at all"
    )
    assert month_version(month_id) == month_version_before, (
        "a rejected create must not advance the plan month's version"
    )

    created = validate_success(
        api.create_receipt_commitment(accepted_body, buyer_headers), 201
    )
    assert created["cost_cents"] == 1_000_000, (
        "cost_cents must be derived server-side as 400 units * 2500 cents, got "
        f"{created['cost_cents']!r}"
    )
    assert created["open_cost_cents"] == 1_000_000, (
        "open_cost_cents must be (units - received_units - cancelled_units) * unit_cost_cents"
    )
    assert created["received_cost_cents"] == 0, (
        "received_cost_cents must be received_units * unit_cost_cents, which is 0 here"
    )

    read_back = validate_success(api.get_receipt_commitment(created["id"], buyer_headers))
    assert read_back["cost_cents"] == 1_000_000, "cost_cents must be stable on re-read"
    assert read_back["open_cost_cents"] == 1_000_000, (
        "open_cost_cents must be stable on re-read"
    )
    assert read_back["received_cost_cents"] == 0, (
        "received_cost_cents must be stable on re-read"
    )


def test_system_fields_are_server_generated_and_rejected_as_input(api, admin_headers):
    """PRD §2.4: "Clients never supply `id`, `created_at`, `updated_at` or `version`; any attempt to send one is an unknown body field and is rejected as an invalid request."

    PRD §2.4: "Every resource the API mints carries an `id` that is a server-generated UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits (for example `2027-02-14T09:00:00.000Z`)."

    PRD §2.7: "Path identifiers are resolved first, left to right, and the first one that matches no row decides the response with that entity's own not-found code: `ERR_DEPARTMENT_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`, `ERR_STORE_CLUSTER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`, `ERR_CATEGORY_PLAN_NOT_FOUND`, `ERR_PLAN_MONTH_NOT_FOUND`, `ERR_OPTION_PLAN_NOT_FOUND`, `ERR_ASSORTMENT_ITEM_NOT_FOUND`, `ERR_RECEIPT_COMMITMENT_NOT_FOUND`, `ERR_REFORECAST_CYCLE_NOT_FOUND`, `ERR_CHASE_CANCEL_DECISION_NOT_FOUND` or `ERR_LOCALIZATION_OVERLAY_NOT_FOUND`, each returned with 404."

    Design: Corner/entities/system_fields_are_server_generated_and_rejected_as_input
    """
    set_clock(CLOCK_STARTUP_UTC)
    department = create_department()
    clean_body = {
        "department_id": department["id"],
        "name": "Dresses",
        "code": "DRSS",
        "role": "DESTINATION",
        "sales_share_bps": 3000,
    }

    validate_error(
        api.create_category(dict(clean_body, id=UNKNOWN_ID_2), admin_headers),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_category(dict(clean_body, version=7), admin_headers),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    created = validate_success(api.create_category(dict(clean_body), admin_headers), 201)
    assert created["version"] == 1, (
        "version is server-owned and starts at 1 whatever the client tried to send"
    )
    assert created["id"] != UNKNOWN_ID_2, (
        "the server must mint its own id rather than honour a client-chosen one"
    )
    assert is_valid_uuid(created["id"]), "the minted id must be a UUID"

    validate_error(
        api.get_category(UNKNOWN_ID_2, admin_headers),
        ApiErrorId.ERR_CATEGORY_NOT_FOUND,
    )

    _, meta = validate_paginated(api.list_categories(admin_headers))
    assert meta["total_count"] == 1, (
        "only the clean create may have persisted a category, got "
        f"total_count {meta['total_count']}"
    )


def test_category_enum_and_integer_range_constraints_enforced(api, admin_headers):
    """PRD §3.1: "It carries a `name` of 1 to 120 characters, a `code` of 2 to 8 uppercase characters that must be unique within its department rather than globally, and `sales_share_bps` between 1 and 10000, expressing the share of the department's sales target this category is expected to carry."

    PRD §3.1: "The category's `role` is the merchandising posture that will later drive its receipt appetite, and it is one of `TRAFFIC_DRIVER`, `DESTINATION`, `CONVENIENCE`, `SEASONAL` or `OCCASIONAL`."

    PRD §3.1: "`demographic_index_bps`, between 5000 and 20000, is the cluster's demographic productivity and is the sole scaling factor applied to a carryover option's own sell-through history."

    PRD §2.8: "Request-body shape: every required field present, every value of its declared JSON type, every enum value a declared member, every integer within its declared range, every string within its declared length bounds, every ISO-8601 field parseable, and no unknown body field — `ERR_INVALID_REQUEST` (400), on every POST and PUT endpoint."

    Design: Corner/entities/category_enum_and_integer_range_constraints_enforced
    """
    set_clock(CLOCK_STARTUP_UTC)
    department = create_department()

    def category_body(**overrides):
        body = {
            "department_id": department["id"],
            "name": "Dresses",
            "code": "DRSS",
            "role": "DESTINATION",
            "sales_share_bps": 3000,
        }
        body.update(overrides)
        return body

    validate_error(
        api.create_category(category_body(role="FLAGSHIP"), admin_headers),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_category(category_body(sales_share_bps=0), admin_headers),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_category(category_body(sales_share_bps=10001), admin_headers),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    accepted = validate_success(
        api.create_category(category_body(sales_share_bps=10000), admin_headers), 201
    )
    assert accepted["sales_share_bps"] == 10000, (
        "sales_share_bps 10000 is the inclusive upper bound and must be accepted as authored"
    )

    validate_error(
        api.create_store_cluster(
            {
                "name": "Edge",
                "climate_zone": "TEMPERATE",
                "demographic_index_bps": 4999,
                "volume_tier": "C",
                "store_count": 1,
                "sales_index_bps": 3000,
            },
            admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    _, category_meta = validate_paginated(api.list_categories(admin_headers))
    assert category_meta["total_count"] == 1, (
        "only the in-range category may exist, got "
        f"total_count {category_meta['total_count']}"
    )
    _, cluster_meta = validate_paginated(api.list_store_clusters(admin_headers))
    assert cluster_meta["total_count"] == 0, (
        "the cluster whose demographic_index_bps sits one below the floor must not persist"
    )


def test_size_curve_cell_immutable_and_versionless(api, planner_headers):
    """PRD §3.3: "A cell's **size curve** is submitted as a whole set, not edited cell by cell: the size-curve replacement operation takes a `cells` array, deletes every existing size-curve row of that option plan, and persists the submitted set in its place, advancing the option plan's own version by 1."

    PRD §2.4: "Two resources are append-only records rather than governed rows, and they carry **only** `id` and `created_at` — neither `updated_at` nor `version` exists on them at all."

    PRD §2.3: "Three lists override that default because their domain ordering is the one planners read them in: the plan-month list is ordered by `month_index` ascending, the size-curve-cell list of an option plan is ordered by `size_sort_order` ascending, and the weekly actuals list of a plan month is ordered by `week_index` ascending."

    PRD §3.3: "Then, for each size row, it computes an unrounded demand in ten-thousandths of a unit: the exact demand for that size is `depth_units_per_option` times `store_count` times the cluster's `sales_index_bps` divided by ten thousand times the row's `pct_bps` divided by ten thousand; multiplying that exact demand by ten thousand and rounding half up to an integer gives the row's `raw_units_x10000`, which is retained on the row precisely so the remainder tie-break is auditable."

    PRD §3.3: "The row's `allocated_units` is then `raw_units_x10000` divided by ten thousand and rounded half up to a whole unit."

    PRD §3.3: "it does **not** write the option plan's `target_units_per_option`, which stays null for as long as the cell's `status` is `OPEN`."

    Design: Corner/entities/size_curve_cell_immutable_and_versionless
    """
    set_clock(CLOCK_STARTUP_UTC)
    department = create_department()
    category = create_category(department["id"])
    store_cluster = create_store_cluster(
        name="Metro A", climate_zone="TEMPERATE", store_count=40, sales_index_bps=11500
    )
    plan = create_category_plan(category["id"])
    option_plan = create_option_plan(
        plan["id"], store_cluster["id"],
        tier="BETTER", breadth_target=14, depth_units_per_option=6,
        assumed_unit_cost_cents=2400,
    )
    version_at_creation = option_plan["version"]

    replace_size_curve(
        option_plan["id"],
        [
            {"size_label": "XS", "size_sort_order": 1, "pct_bps": 800},
            {"size_label": "S", "size_sort_order": 2, "pct_bps": 2200},
            {"size_label": "M", "size_sort_order": 3, "pct_bps": 3400},
            {"size_label": "L", "size_sort_order": 4, "pct_bps": 2600},
            {"size_label": "XL", "size_sort_order": 5, "pct_bps": 1000},
        ],
    )

    validate_success(
        api.replace_size_curve(
            option_plan["id"],
            {
                "cells": [
                    {"size_label": "S", "size_sort_order": 1, "pct_bps": 4000},
                    {"size_label": "L", "size_sort_order": 2, "pct_bps": 6000},
                ]
            },
            planner_headers,
        )
    )

    rows, meta = validate_paginated(
        api.list_size_curve_cells(option_plan["id"], planner_headers)
    )
    assert meta["total_count"] == 2, (
        "the replacement deletes every existing row, so only the two submitted cells "
        f"may remain; got total_count {meta['total_count']}"
    )
    assert len(rows) == 2, f"exactly two size-curve rows must be listed, got {len(rows)}"
    assert [row["size_label"] for row in rows] == ["S", "L"], (
        "the five XS/S/M/L/XL rows must be gone rather than merged, and the list is "
        "ordered by size_sort_order ascending"
    )
    assert rows[0]["size_label"] == "S", (
        "the first listed row must be size_sort_order 1, which is the S cell"
    )

    assert rows[0]["size_sort_order"] == 1, "the S row keeps its submitted sort order"
    assert rows[0]["pct_bps"] == 4000, "the S row keeps its submitted share"
    assert rows[0]["raw_units_x10000"] == 1_104_000, (
        "the S row's raw_units_x10000 must be 1104000, got "
        f"{rows[0]['raw_units_x10000']!r}"
    )
    assert rows[0]["allocated_units"] == 110, (
        f"the S row's allocated_units must be 110, got {rows[0]['allocated_units']!r}"
    )
    assert rows[1]["size_sort_order"] == 2, "the L row keeps its submitted sort order"
    assert rows[1]["pct_bps"] == 6000, "the L row keeps its submitted share"
    assert rows[1]["raw_units_x10000"] == 1_656_000, (
        "the L row's raw_units_x10000 must be 1656000, got "
        f"{rows[1]['raw_units_x10000']!r}"
    )
    assert rows[1]["allocated_units"] == 166, (
        f"the L row's allocated_units must be 166, got {rows[1]['allocated_units']!r}"
    )

    for row in rows:
        assert_size_curve_cell(row)
        assert "updated_at" not in row, (
            "a size-curve cell is an append-only record and carries no updated_at"
        )
        assert "version" not in row, (
            "a size-curve cell is an append-only record and carries no version"
        )

    refreshed = get_option_plan(option_plan["id"])
    assert refreshed["version"] == version_at_creation + 2, (
        "each wholesale replacement advances the option plan's version by exactly 1, so "
        f"two PUTs leave version {version_at_creation + 2}, got {refreshed['version']}"
    )
    assert refreshed["status"] == "OPEN", (
        "the cell is still OPEN because the plan was never approved"
    )
    assert refreshed["option_slots_total"] is None, (
        "option_slots_total stays null until the approval cascade slots the cell"
    )
    assert refreshed["option_slots_open"] is None, (
        "option_slots_open stays null until the approval cascade slots the cell"
    )
    assert refreshed["target_units_per_option"] is None, (
        "the size-curve replacement never writes target_units_per_option"
    )


def test_actuals_post_immutable_and_week_unique(api, admin_headers):
    """PRD §3.7: "The `week_index`, between 1 and 4, is unique within the month and is the sole chronological replay key; a repeat is refused with `ERR_DUPLICATE_ACTUALS_WEEK`."

    PRD §3.7: "An actuals post is an immutable record and, per §2.4, carries only `id` and `created_at`."

    PRD §2.4: "Two resources are append-only records rather than governed rows, and they carry **only** `id` and `created_at` — neither `updated_at` nor `version` exists on them at all."

    PRD §3.7: "The month's `active_basis` flips to `PROJECTED_BASIS`, and the markdown reserve is recomputed — this is the second and only other event that recomputes it — followed by a full recomputation of the month's open-to-buy on the projected basis."

    PRD §3.7: "The month set is every plan month of the plan whose `status` is `IN_SEASON` or `CLOSED`; months still `DRAFT` or `LOCKED_PLAN` contribute neither actuals nor plan, and an `IN_SEASON` month with no posts contributes zero to both sides."

    PRD §3.7: "For each month in the set, the weeks credited are the count of its actuals rows, capped at the four weeks a fiscal month holds, and that month's contribution to the plan side is its `planned_sales_cents` multiplied by the weeks credited and divided by four, **rounded half up per month before the months are summed**."

    Design: Corner/entities/actuals_post_immutable_and_week_unique
    """
    scenario = setup_in_season_plan(
        cluster_overrides={"name": "Metro A", "climate_zone": "TEMPERATE"}
    )
    month_id = scenario["m1"]["id"]
    post_actuals(
        month_id,
        week_index=1,
        actual_sales_cents=7_500_000,
        actual_receipts_cents=6_000_000,
        actual_units_received=2500,
    )

    validate_error(
        api.create_actuals_post(
            {
                "plan_month_id": month_id,
                "week_index": 1,
                "actual_sales_cents": 9_999_999,
                "actual_receipts_cents": 0,
                "actual_units_received": 0,
            },
            admin_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_ACTUALS_WEEK,
    )

    rows, meta = validate_paginated(api.list_month_actuals_posts(month_id, admin_headers))
    assert meta["total_count"] == 1, (
        "the rejected duplicate must not append a second row for week 1, got "
        f"total_count {meta['total_count']}"
    )
    assert len(rows) == 1, f"exactly one weekly actuals row must be listed, got {len(rows)}"
    stored = rows[0]
    assert stored["plan_month_id"] == month_id, "the stored week belongs to the posted month"
    assert stored["week_index"] == 1, "the stored week keeps its week_index"
    assert stored["actual_sales_cents"] == 7_500_000, (
        "the accepted week's actual_sales_cents must survive the duplicate attempt, got "
        f"{stored['actual_sales_cents']!r}"
    )
    assert stored["actual_receipts_cents"] == 6_000_000, (
        "the accepted week's actual_receipts_cents must be unchanged"
    )
    assert stored["actual_units_received"] == 2500, (
        "the accepted week's actual_units_received must be unchanged"
    )
    assert_actuals_post(stored)
    assert "updated_at" not in stored, (
        "an actuals post is an immutable record and carries no updated_at"
    )
    assert "version" not in stored, (
        "an actuals post is an immutable record and carries no version"
    )

    month = get_month(month_id)
    assert month["active_basis"] == "PROJECTED_BASIS", (
        "the single accepted post flips the month onto the projected basis"
    )
    assert month["provisional_sell_through_bps"] == 5967, (
        "the projected-basis reserve pass must write provisional_sell_through_bps 5967, "
        f"got {month['provisional_sell_through_bps']!r}"
    )
    assert month["reserve_rate_bps"] == 600, (
        f"a 5967 bps sell-through selects a 600 bps reserve rate, got {month['reserve_rate_bps']!r}"
    )
    assert month["markdown_reserve_cents"] == 1_357_500, (
        "markdown_reserve_cents must be 1357500, got "
        f"{month['markdown_reserve_cents']!r}"
    )
    assert month["otb_planned_cents"] == 16_232_500, (
        "the projected-basis otb_planned_cents must be 16232500, got "
        f"{month['otb_planned_cents']!r}"
    )
    assert_plan_month(month)

    plan = get_plan(scenario["plan_id"])
    assert plan["sales_variance_bps"] == 0, (
        "one week of 7500000 against a prorated plan of 7500000 is a zero variance, got "
        f"{plan['sales_variance_bps']!r}"
    )
    assert plan["variance_status"] == "ON_PLAN", (
        "a zero variance verdict is ON_PLAN, so the rejected duplicate produced no "
        f"governance side effect; got {plan['variance_status']!r}"
    )


def test_fk_body_resolution_left_to_right(api, buyer_headers):
    """PRD §2.7: "Body foreign keys are resolved next, in the order the endpoint declares its input fields, and again the first unresolvable one decides the response with the corresponding not-found code."

    PRD §2.8: "Body foreign keys resolve, in declared field order — the matching 404 not-found code, on every POST and PUT endpoint that carries foreign-key fields."

    PRD §3.6: "Proposing one names the `plan_month_id` of the month whose budget is being drawn down, the `assortment_item_id` of the option being bought, and the `vendor_id` of the supplier — denormalized onto the row deliberately, so that a supplier-side ownership check is a single-field comparison."

    PRD §3.6: "Creating the commitment advances the target plan month's version by 1 even though a `PROPOSED` commitment has not yet entered the month's committed figure — which is exactly why the next buyer to size a buy from that month needs a fresh `expected_plan_month_version`."

    Design: Corner/entities/fk_body_resolution_left_to_right
    """
    scenario = setup_single_month_approved_plan(
        cluster_overrides={"name": "Metro A", "climate_zone": "TEMPERATE"},
        vendor_overrides={
            "name": "Atlas Apparel",
            "code": "ATLS",
            "lead_time_days": 45,
            "weekly_unit_capacity": 12000,
            "min_order_units": 100,
            "cancel_cutoff_days": 14,
        },
    )
    month_id = scenario["m1"]["id"]
    vendor_id = scenario["vendor"]["id"]

    item = propose_item(
        scenario["option_plan"]["id"],
        vendor_id,
        headers=buyer_headers,
        sku_code="DR-1001",
        color_code="BLK",
        lifecycle_stage="CARRYOVER",
        unit_cost_cents=2600,
        retail_price_cents=7900,
        prior_season_sell_through_bps=7100,
    )
    month_version_before = month_version(month_id)

    def commitment_body(plan_month_id, assortment_item_id, body_vendor_id):
        return receipt_commitment_payload(
            plan_month_id, assortment_item_id, body_vendor_id, month_version_before,
            units=400, unit_cost_cents=2600,
            ship_window_start="2027-02-01T00:00:00Z",
            ship_window_end="2027-02-15T00:00:00Z",
        )

    validate_error(
        api.create_receipt_commitment(
            commitment_body(UNKNOWN_ID_1, UNKNOWN_ID_2, UNKNOWN_ID_3), buyer_headers
        ),
        ApiErrorId.ERR_PLAN_MONTH_NOT_FOUND,
    )
    validate_error(
        api.create_receipt_commitment(
            commitment_body(month_id, UNKNOWN_ID_2, UNKNOWN_ID_3), buyer_headers
        ),
        ApiErrorId.ERR_ASSORTMENT_ITEM_NOT_FOUND,
    )
    validate_error(
        api.create_receipt_commitment(
            commitment_body(month_id, item["id"], UNKNOWN_ID_3), buyer_headers
        ),
        ApiErrorId.ERR_VENDOR_NOT_FOUND,
    )

    created = validate_success(
        api.create_receipt_commitment(
            commitment_body(month_id, item["id"], vendor_id), buyer_headers
        ),
        201,
    )
    assert is_valid_uuid(created["id"]), "the accepted proposal must mint a commitment id"
    assert created["commit_status"] == "PROPOSED", (
        "a newly proposed commitment starts at PROPOSED"
    )
    assert created["fulfillment_status"] == "AWAITING_SHIP", (
        "a newly proposed commitment starts at AWAITING_SHIP"
    )
    assert created["origin"] == "BUYER", "a buyer-originated commitment carries origin BUYER"
    assert created["cost_cents"] == 1_040_000, (
        f"cost_cents must be 400 units * 2600 cents, got {created['cost_cents']!r}"
    )
    assert created["open_cost_cents"] == 1_040_000, (
        "open_cost_cents must be the full cost while nothing is received or cancelled"
    )

    _, meta = validate_paginated(
        api.list_receipt_commitments(buyer_headers, params={"plan_month_id": month_id})
    )
    assert meta["total_count"] == 1, (
        "none of the three unresolvable bodies may have created a row, got "
        f"total_count {meta['total_count']}"
    )

    month = get_month(month_id)
    assert month["otb_open_cents"] == CANONICAL_M1_OTB_PLANNED_CENTS, (
        "a PROPOSED commitment has not entered the month's committed figure, so the "
        f"open balance is untouched; got {month['otb_open_cents']!r}"
    )
    assert month["version"] == month_version_before + 1, (
        "only the accepted create advances the plan month's version, and by exactly 1; "
        f"got {month['version']} against {month_version_before} before the probes"
    )


def test_vendor_authorization_many_to_many_junction(api, admin_headers):
    """PRD §3.2: "A **VendorAuthorization** is the many-to-many join that licenses one vendor to supply one category."

    PRD §3.2: "It is created with `vendor_id`, `category_id` and `max_open_units` of at least 1, which is the ceiling on the units this vendor may hold open — neither received nor cancelled — for that category."

    PRD §3.2: "Authorizations can be listed and narrowed by `vendor_id`, by `category_id` or by `status`."

    PRD §2.7: "Every collection in this API is mounted directly beneath `/otb`; no resource is addressed through a nested path, and every link between rows is an explicit foreign-key field carried in the request body."

    Design: Corner/entities/vendor_authorization_many_to_many_junction
    """
    set_clock(CLOCK_STARTUP_UTC)
    department = create_department()
    category_a = create_category(
        department["id"], name="Dresses", code="DRSS", role="DESTINATION",
        sales_share_bps=3000,
    )
    category_b = create_category(
        department["id"], name="Knits", code="KNIT", role="CONVENIENCE",
        sales_share_bps=2000,
    )
    vendor_a = create_vendor(
        name="Atlas Apparel", code="ATLS", lead_time_days=45,
        weekly_unit_capacity=12000, min_order_units=100, cancel_cutoff_days=14,
    )
    vendor_b = create_vendor(
        name="Borealis Knitwear", code="BORE", lead_time_days=30,
        weekly_unit_capacity=9000, min_order_units=50, cancel_cutoff_days=7,
    )

    pairs = [
        (vendor_a["id"], category_a["id"], 40000),
        (vendor_a["id"], category_b["id"], 15000),
        (vendor_b["id"], category_a["id"], 8000),
        (vendor_b["id"], category_b["id"], 6000),
    ]
    authorizations = []
    for vendor_id, category_id, max_open_units in pairs:
        row = validate_success(
            api.create_vendor_authorization(
                {
                    "vendor_id": vendor_id,
                    "category_id": category_id,
                    "max_open_units": max_open_units,
                },
                admin_headers,
            ),
            201,
        )
        assert row["status"] == "ACTIVE", "every junction row is created ACTIVE"
        assert row["version"] == 1, "every junction row is created at version 1"
        assert row["vendor_id"] == vendor_id, "the row must hold the vendor it joins"
        assert row["category_id"] == category_id, "the row must hold the category it joins"
        assert row["max_open_units"] == max_open_units, (
            "each junction row carries its own open-unit ceiling, got "
            f"{row['max_open_units']!r} instead of {max_open_units}"
        )
        authorizations.append(row)

    assert len({row["id"] for row in authorizations}) == 4, (
        "two vendors each authorized for two categories yield four independent rows"
    )

    vendor_rows, vendor_meta = validate_paginated(
        api.list_vendor_authorizations(admin_headers, params={"vendor_id": vendor_a["id"]})
    )
    assert vendor_meta["total_count"] == 2, (
        "the junction must be traversable from the vendor side, got "
        f"total_count {vendor_meta['total_count']}"
    )
    assert {row["category_id"] for row in vendor_rows} == {
        category_a["id"], category_b["id"]
    }, "the vendor_id filter must return that vendor's two categories"
    assert vendor_rows[0]["category_id"] in (category_a["id"], category_b["id"]), (
        "every row of the vendor-side traversal names one of the two categories"
    )

    category_rows, category_meta = validate_paginated(
        api.list_vendor_authorizations(
            admin_headers, params={"category_id": category_b["id"], "status": "ACTIVE"}
        )
    )
    assert category_meta["total_count"] == 2, (
        "the same junction must be traversable from the category side, got "
        f"total_count {category_meta['total_count']}"
    )
    assert {row["vendor_id"] for row in category_rows} == {vendor_a["id"], vendor_b["id"]}, (
        "the category_id filter must return both vendors authorized for that category"
    )
    assert category_rows[0]["vendor_id"] in (vendor_a["id"], vendor_b["id"]), (
        "every row of the category-side traversal names one of the two vendors"
    )

    _, all_meta = validate_paginated(api.list_vendor_authorizations(admin_headers))
    assert all_meta["total_count"] == 4, (
        "the unfiltered junction list must hold all four rows, got "
        f"total_count {all_meta['total_count']}"
    )

    independent = validate_success(
        api.get_vendor_authorization(authorizations[2]["id"], admin_headers)
    )
    assert independent["max_open_units"] == 8000, (
        "the (vendor_b, category_a) row keeps its own 8000 ceiling, independent of the "
        f"(vendor_a, category_a) row's 40000; got {independent['max_open_units']!r}"
    )
