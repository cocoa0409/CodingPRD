"""Entity-level behaviour of the RV assembly plant API.

Creation defaults, derived fields, single-resource reads, listing filters,
404 sweeps and schema rejection across the fifteen resources of PRD §2.4.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_cents,
    assert_common_fields,
    assert_component_installation,
    assert_component_lot,
    assert_hours,
    assert_lot_counter_invariant,
    assert_supplier,
    assert_two_decimals,
    assert_unit_order,
    assert_vin_format,
    advance_build,
    create_chassis_receipt,
    create_component_lot,
    create_dealer,
    create_floor_plan,
    create_option_item,
    create_order,
    create_production_line,
    create_supplier,
    inject_delivered_unit,
    install_pieces,
    make_dealer_principal_headers,
    match_chassis,
    read_build,
    read_lot,
    read_order,
    release_to_line,
    reserve_slot,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Local payload material (PRD §3.1 master data) ─────────────────────────

TOW_FLOOR_PLAN = {
    "model_code": "FP-TOW",
    "chassis_class": "TOWABLE",
    "length_ft": 28,
    "base_msrp_cents": 8000000,
    "base_station_hours": 40.00,
    "base_dry_weight_lbs": 6000,
    "gvwr_lbs": 9000,
    "required_wheelbase_in": 180,
    "electrical_service_amps": 50,
    "fresh_water_capacity_gal": 60,
}

CANON_FLOOR_PLAN = {
    "model_code": "FP-3410",
    "chassis_class": "CLASS_A",
    "length_ft": 34,
    "base_msrp_cents": 18500000,
    "base_station_hours": 46.00,
    "base_dry_weight_lbs": 22400,
    "gvwr_lbs": 26000,
    "required_wheelbase_in": 242,
    "electrical_service_amps": 50,
    "fresh_water_capacity_gal": 90,
}

OPT_E1 = {
    "option_code": "OPT-E1",
    "category": "ELECTRICAL",
    "install_station": "ROUGH_IN",
    "price_cents": 100000,
    "weight_lbs": 0,
    "added_station_hours": 1.00,
    "amp_draw": 20,
    "water_demand_gal": 0,
}

OPT_AC2 = {
    "option_code": "OPT-AC2",
    "category": "ELECTRICAL",
    "install_station": "ROOF_SET",
    "price_cents": 385000,
    "weight_lbs": 95,
    "added_station_hours": 2.50,
    "amp_draw": 16,
    "water_demand_gal": 0,
}

OPT_WASH = {
    "option_code": "OPT-WASH",
    "category": "APPLIANCE",
    "install_station": "APPLIANCE_INSTALL",
    "price_cents": 245500,
    "weight_lbs": 180,
    "added_station_hours": 3.00,
    "amp_draw": 12,
    "water_demand_gal": 0,
}

UNKNOWN_IDS = {
    "supplier": "00000000-0000-4000-8000-000000000001",
    "floor_plan": "00000000-0000-4000-8000-000000000002",
    "option_item": "00000000-0000-4000-8000-000000000003",
    "dealer": "00000000-0000-4000-8000-000000000004",
    "production_line": "00000000-0000-4000-8000-000000000005",
    "test_booth": "00000000-0000-4000-8000-000000000006",
    "body_supplier": "00000000-0000-4000-8000-000000000007",
    "unit_order": "00000000-0000-4000-8000-000000000011",
    "production_slot": "00000000-0000-4000-8000-000000000012",
    "chassis_receipt": "00000000-0000-4000-8000-000000000013",
    "component_lot": "00000000-0000-4000-8000-000000000014",
    "unit_build": "00000000-0000-4000-8000-000000000015",
    "body_build": "00000000-0000-4000-8000-000000000016",
    "body_lot": "00000000-0000-4000-8000-000000000017",
    "installation": "00000000-0000-4000-8000-000000000021",
    "inspection": "00000000-0000-4000-8000-000000000022",
    "claim": "00000000-0000-4000-8000-000000000023",
    "claim_pay": "00000000-0000-4000-8000-000000000024",
    "campaign": "00000000-0000-4000-8000-000000000025",
    "orphan_order": "00000000-0000-4000-8000-0000000000ff",
}


def _parse_instant(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def assert_same_instant(actual, expected):
    """PRD §2.4 stamps timestamps with three fractional digits; compare instants."""
    assert actual is not None, f"expected the instant {expected}, got null"
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"expected the instant {expected}, got {actual}"
    )


def test_floor_plan_creation_derives_max_payload_and_defaults_status_to_active(
    api, plant_admin_headers
):
    """PRD §3.1: "The plant derives `max_payload_lbs` as the gross vehicle weight rating minus the base dry weight, and re-derives it whenever the plan is edited."

    PRD §3.1: "It is published with a `model_code` unique across floor plans, a `chassis_class`, an overall coach `length_ft` between 18 and 45 inclusive, a `base_msrp_cents` greater than zero, a `base_station_hours` figure greater than zero carrying at most two decimals, a `base_dry_weight_lbs` greater than zero, a `gvwr_lbs` strictly greater than `base_dry_weight_lbs`, an exact `required_wheelbase_in` greater than zero, an `electrical_service_amps` rating of either 30 or 50, a `fresh_water_capacity_gal` greater than zero, and optionally a `status` that defaults to `ACTIVE`."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the row."
    PRD §2.4: "`created_at` is an ISO 8601 UTC timestamp with three fractional digits, stamped when the row is first written."
    PRD §2.5: "The plant does not read the wall clock."
    PRD §2.5: "A `PlantAdmin` moves it by supplying a `current_utc` instant; the response reports both the new `current_utc` and the `previous_utc` it replaced."

    Design: Corner/entities/floor_plan_creation_returns_computed_payload_and_default_status
    """
    clock = validate_success(
        api.set_clock({"current_utc": "2026-08-02T00:00:00Z"}, plant_admin_headers)
    )

    response = api.create_floor_plan(dict(CANON_FLOOR_PLAN), plant_admin_headers)
    floor_plan = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"].get("api_request_id"), str) and body["meta"]["api_request_id"]
    assert (
        isinstance(body["meta"].get("api_request_timestamp"), str)
        and body["meta"]["api_request_timestamp"]
    )

    assert_common_fields(floor_plan)
    assert floor_plan["max_payload_lbs"] == 3600
    assert floor_plan["status"] == "ACTIVE"
    assert floor_plan["version"] == 1
    assert_same_instant(floor_plan["created_at"], "2026-08-02T00:00:00Z")
    assert_same_instant(floor_plan["updated_at"], "2026-08-02T00:00:00Z")

    assert_same_instant(clock["previous_utc"], "2026-08-01T00:00:00Z")
    assert_same_instant(clock["current_utc"], "2026-08-02T00:00:00Z")


def test_option_item_optional_inputs_default_and_supplied_values_are_kept(
    api, plant_admin_headers
):
    """PRD §3.1: "It is published with an `option_code` unique across options, a commercial `category` that selects its dealer discount rate, an `install_station` naming where on the line it goes, a `price_cents` of zero or more, an installed `weight_lbs` of zero or more, an `added_station_hours` figure of zero or more with at most two decimals, an `amp_draw` defaulting to 0, a `water_demand_gal` defaulting to 0, a `requires_option_codes` array defaulting to empty, an `excludes_option_codes` array defaulting to empty, and a `status` defaulting to `ACTIVE`."

    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the row."

    Design: Corner/entities/option_item_defaults_applied_when_optional_fields_are_omitted
    """
    advance_clock("2026-08-02T00:00:00Z")

    bare = validate_success(
        api.create_option_item(
            {
                "option_code": "OPT-BARE",
                "category": "INTERIOR",
                "install_station": "FINISH",
                "price_cents": 50000,
                "weight_lbs": 10,
                "added_station_hours": 1.00,
            },
            plant_admin_headers,
        ),
        201,
    )
    full = validate_success(
        api.create_option_item(
            {
                "option_code": "OPT-FULL",
                "category": "ELECTRICAL",
                "install_station": "ROUGH_IN",
                "price_cents": 100000,
                "weight_lbs": 0,
                "added_station_hours": 1.00,
                "amp_draw": 20,
                "water_demand_gal": 3,
                "requires_option_codes": ["OPT-BARE"],
                "excludes_option_codes": [],
                "status": "DISCONTINUED",
            },
            plant_admin_headers,
        ),
        201,
    )

    assert bare["amp_draw"] == 0
    assert bare["water_demand_gal"] == 0
    assert bare["requires_option_codes"] == []
    assert bare["excludes_option_codes"] == []
    assert bare["status"] == "ACTIVE"
    assert bare["version"] == 1

    assert full["amp_draw"] == 20
    assert full["water_demand_gal"] == 3
    assert full["requires_option_codes"] == ["OPT-BARE"]
    assert full["status"] == "DISCONTINUED"


def test_unit_order_configuration_roll_up_runs_at_create_without_pricing(api):
    """PRD §3.2: "The new order begins with `status` `DRAFT` and `financing_status` `NOT_FINANCED`, and the configuration roll-up runs immediately."

    PRD §3.2: "`option_price_total_cents` is the sum of `price_cents` across the selected options at list price. `config_weight_lbs` is the floor plan's `base_dry_weight_lbs` plus the sum of `weight_lbs` across the selected options. `payload_remaining_lbs` is the floor plan's `gvwr_lbs` minus `config_weight_lbs`. `total_amp_draw` is the sum of `amp_draw` across the selected options, and `total_water_demand_gal` is the sum of `water_demand_gal` across them."
    PRD §3.2: "Begin with raw hours: the floor plan's `base_station_hours` plus the sum of `added_station_hours` across the selected options. Next choose a complexity factor from the *count* of selected options: four or fewer options (including none at all) gives 1.00; five through nine gives 1.05; ten through fourteen gives 1.12; fifteen or more gives 1.20. Then choose a class factor from the floor plan's `chassis_class`: a towable is 1.00, a Class C is 1.10, and a Class A is 1.15. Then determine the electrical surcharge: a configuration whose `total_amp_draw` is more than 40 amps adds a flat four hours of extra rough-in labour, and one at 40 amps or below adds nothing. Multiply raw hours by the complexity factor and by the class factor, add the surcharge, and round that single final result half up to two decimal places."
    PRD §3.2: "at submit the order's `provisional_invoice_cents` is written from the provisional variant of the invoice calculation, and `final_invoice_cents` stays null until the coach ships."
    PRD §3.2: "An order that clears all of it is stamped: the roll-up is recomputed, `provisional_invoice_cents` is written, `locked_floor_plan_version` is pinned to the floor plan's current `version`, and `locked_option_versions` is pinned as one entry per selected option carrying that option's identifier, its `version`, and its `price_cents` at the moment of submit."
    PRD §2.10: "Shipment holds are `NONE`, `RECALL_HOLD`, and `QUALITY_HOLD`."

    Design: Corner/entities/unit_order_computed_totals_are_derived_at_create
    """
    floor_plan = create_floor_plan(**CANON_FLOOR_PLAN)
    option_ac2 = create_option_item(**OPT_AC2)
    option_wash = create_option_item(**OPT_WASH)
    dealer = create_dealer(
        dealer_code="D-CANON",
        region="WEST",
        allocation_share_bp=1500,
        floor_plan_credit_limit_cents=100000000,
        goodwill_budget_cents=500000,
    )

    response = api.create_unit_order(
        {
            "dealer_id": dealer["id"],
            "floor_plan_id": floor_plan["id"],
            "order_type": "STOCK",
            "selected_option_ids": [option_ac2["id"], option_wash["id"]],
            "requested_delivery_date": "2026-10-01T00:00:00Z",
            "customer_reference": "WALK-IN",
        },
        make_dealer_principal_headers(dealer["id"]),
    )
    order = validate_success(response, 201)
    assert_unit_order(order)

    assert_cents(order["option_price_total_cents"], 630500)
    assert order["config_weight_lbs"] == 22675
    assert order["payload_remaining_lbs"] == 3325
    assert order["total_amp_draw"] == 28
    assert order["total_water_demand_gal"] == 0
    assert_hours(order["required_station_hours"], "59.23")
    assert order["status"] == "DRAFT"
    assert order["financing_status"] == "NOT_FINANCED"
    assert_cents(order["provisional_invoice_cents"], 0)
    assert order["final_invoice_cents"] is None
    assert order["locked_floor_plan_version"] is None
    assert order["locked_option_versions"] == []
    assert order["ship_hold_reason"] == "NONE"
    assert order["version"] == 1


def test_warranty_claim_dealer_is_taken_from_the_acting_principal(api, warranty_admin_headers):
    """PRD §3.8: "The claim's `dealer_id` is taken from the submitting principal's `X-User-ID` and never from the body; filing against a build belonging to another dealer is `ERR_DEALER_SCOPE_VIOLATION`."

    PRD §3.8: "At filing, `in_warranty` is set true when the logical clock is within that period of `shipped_at` and false otherwise, and that single boolean selects which of the two reimbursement variants governs the payout."
    PRD §3.8: "Multiply the billable hours by the flat rate for the claim's `claim_type` — 7800 cents per hour for `APPLIANCE`, 8600 for `PLUMBING`, 9200 for `ELECTRICAL`, 10400 for `STRUCTURAL`, and 11000 for `WATER_INTRUSION` — and round half up to whole cents. That is `labor_reimbursement_cents`."
    PRD §3.8: "Parts carry a handling uplift of 1500 basis points. Multiply `parts_cost_cents` by 11500, divide by 10000, and round half up to whole cents. That is `parts_reimbursement_cents`."
    PRD §3.8: "a subtotal at or below 150000 cents is `TIER_A`, a subtotal above that but at or below 750000 cents is `TIER_B`, and anything above 750000 cents is `TIER_C`."
    PRD §3.8: "Filing a claim previews steps 1 through 4 and step 7's structure, writing `labor_reimbursement_cents` and `parts_reimbursement_cents`; `goodwill_authorized_cents`, `total_reimbursement_cents`, and `supplier_chargeback_cents` all stay at zero until a decision is made."
    PRD §3.8: "The claim starts at `status` `SUBMITTED` with `denial_reason` null, `info_request_count` 0, `resubmission_count` 0, and both `approved_by_user_id` and `paid_by_user_id` null."
    PRD §3.8: "Claims are listable with filters on `dealer_id`, `unit_build_id`, `component_lot_id`, `status`, and `claim_type`."

    Design: Corner/entities/warranty_claim_dealer_id_is_header_derived_and_body_input_ignored
    """
    floor_plan = create_floor_plan(**TOW_FLOOR_PLAN)
    dealer_a = create_dealer(
        dealer_code="D-A",
        region="CENTRAL",
        allocation_share_bp=1500,
        floor_plan_credit_limit_cents=100000000,
        goodwill_budget_cents=500000,
    )
    dealer_b = create_dealer(
        dealer_code="D-B",
        region="EAST",
        allocation_share_bp=1500,
        floor_plan_credit_limit_cents=100000000,
        goodwill_budget_cents=500000,
    )
    build = inject_delivered_unit(dealer_a["id"], floor_plan["id"])

    response = api.create_warranty_claim(
        {
            "unit_build_id": build["id"],
            "claim_type": "APPLIANCE",
            "labor_hours": 3.50,
            "parts_cost_cents": 68000,
            "narrative": "Refrigerator will not hold temperature",
            "dealer_id": dealer_b["id"],
        },
        make_dealer_principal_headers(dealer_a["id"]),
    )
    claim = validate_success(response, 201)

    assert claim["dealer_id"] == dealer_a["id"]
    assert claim["dealer_id"] != dealer_b["id"]
    assert claim["in_warranty"] is True
    assert_cents(claim["labor_reimbursement_cents"], 27300)
    assert_cents(claim["parts_reimbursement_cents"], 78200)
    assert claim["authority_tier"] == "TIER_A"
    assert_cents(claim["goodwill_authorized_cents"], 0)
    assert_cents(claim["supplier_chargeback_cents"], 0)
    assert_cents(claim["total_reimbursement_cents"], 0)
    assert claim["status"] == "SUBMITTED"
    assert claim["info_request_count"] == 0
    assert claim["resubmission_count"] == 0

    _rows, meta = validate_paginated(
        api.list_warranty_claims(warranty_admin_headers, params={"dealer_id": dealer_b["id"]})
    )
    assert meta["total_count"] == 0


def test_unit_order_listing_filters_by_dealer_and_paginates(api, plant_admin_headers):
    """PRD §3.2: "Orders are listable with filters on `dealer_id`, `floor_plan_id`, `status`, `financing_status`, and `order_type`, and a `DealerPrincipal` sees only its own rows."

    PRD §2.3: "Every list endpoint accepts two optional query parameters. `limit` controls page size: it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100."
    PRD §2.3: "`offset` is the zero-based index of the first row returned and defaults to 0."
    PRD §2.3: "List results are ordered by `created_at` ascending unless a subsection below says otherwise, and that default applies to every collection in the API. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of rows matching the supplied filters before pagination is applied, and `has_more` is true exactly when rows matching the filters remain beyond the returned page."

    Design: Corner/entities/unit_order_listing_filters_by_dealer_and_paginates
    """
    floor_plan = create_floor_plan(**TOW_FLOOR_PLAN)
    option = create_option_item(**OPT_E1)
    dealer_a = create_dealer(
        dealer_code="D-A",
        region="CENTRAL",
        allocation_share_bp=1500,
        floor_plan_credit_limit_cents=100000000,
        goodwill_budget_cents=500000,
    )
    dealer_b = create_dealer(
        dealer_code="D-B",
        region="EAST",
        allocation_share_bp=1500,
        floor_plan_credit_limit_cents=100000000,
        goodwill_budget_cents=500000,
    )
    order_a1 = create_order(
        dealer_a["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    order_a2 = create_order(
        dealer_a["id"],
        floor_plan["id"],
        order_type="SOLD",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-02T00:00:00Z",
    )
    order_b1 = create_order(
        dealer_b["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-03T00:00:00Z",
    )

    page1, meta1 = validate_paginated(
        api.list_unit_orders(
            plant_admin_headers, params={"dealer_id": dealer_a["id"], "limit": 1, "offset": 0}
        )
    )
    page2, meta2 = validate_paginated(
        api.list_unit_orders(
            plant_admin_headers, params={"dealer_id": dealer_a["id"], "limit": 1, "offset": 1}
        )
    )
    sold_rows, sold_meta = validate_paginated(
        api.list_unit_orders(plant_admin_headers, params={"order_type": "SOLD"})
    )

    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert meta1["limit"] == 1
    assert meta1["offset"] == 0
    assert len(page1) == 1
    assert page1[0]["id"] == order_a1["id"]

    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert page2[0]["id"] == order_a2["id"]

    assert sold_meta["total_count"] == 1
    assert [row["id"] for row in sold_rows] == [order_a2["id"]]

    _all_rows, all_meta = validate_paginated(api.list_unit_orders(plant_admin_headers))
    assert all_meta["total_count"] == 3
    assert all_meta["limit"] == 10
    assert all_meta["offset"] == 0

    assert order_b1["dealer_id"] == dealer_b["id"]
    for row in page1 + page2:
        assert row["dealer_id"] != dealer_b["id"]


def test_reference_data_reads_and_body_foreign_keys_report_their_own_not_found_code(
    api, plant_admin_headers
):
    """PRD §2.8: "Every `{id}` segment resolves to an existing row of the addressed entity, else the entity-specific 404 code: `ERR_UNIT_ORDER_NOT_FOUND`, `ERR_PRODUCTION_SLOT_NOT_FOUND`, `ERR_CHASSIS_RECEIPT_NOT_FOUND`, `ERR_COMPONENT_LOT_NOT_FOUND`, `ERR_UNIT_BUILD_NOT_FOUND`, `ERR_COMPONENT_INSTALLATION_NOT_FOUND`, `ERR_QUALITY_INSPECTION_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`, `ERR_RECALL_CAMPAIGN_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_FLOOR_PLAN_NOT_FOUND`, `ERR_OPTION_ITEM_NOT_FOUND`, `ERR_PRODUCTION_LINE_NOT_FOUND`, or `ERR_TEST_BOOTH_NOT_FOUND`."

    PRD §2.8: "Every foreign key supplied in the request **body** resolves to an existing row, using the same per-entity 404 codes, and checked in the field order the endpoint declares its inputs."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/reference_data_path_and_body_ids_not_found
    """
    advance_clock("2026-08-02T00:00:00Z")

    validate_error(
        api.get_supplier(UNKNOWN_IDS["supplier"], plant_admin_headers),
        ApiErrorId.ERR_SUPPLIER_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_floor_plan(UNKNOWN_IDS["floor_plan"], plant_admin_headers),
        ApiErrorId.ERR_FLOOR_PLAN_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_option_item(UNKNOWN_IDS["option_item"], plant_admin_headers),
        ApiErrorId.ERR_OPTION_ITEM_NOT_FOUND,
        404,
    )
    validate_error(
        api.set_dealer_status(
            UNKNOWN_IDS["dealer"], {"status": "SUSPENDED"}, plant_admin_headers
        ),
        ApiErrorId.ERR_DEALER_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_production_line(UNKNOWN_IDS["production_line"], plant_admin_headers),
        ApiErrorId.ERR_PRODUCTION_LINE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_test_booth(UNKNOWN_IDS["test_booth"], plant_admin_headers),
        ApiErrorId.ERR_TEST_BOOTH_NOT_FOUND,
        404,
    )
    body_error = validate_error(
        api.create_chassis_receipt(
            {
                "supplier_id": UNKNOWN_IDS["body_supplier"],
                "chassis_serial": "CH-ORPHAN",
                "chassis_class": "TOWABLE",
                "gvwr_lbs": 9000,
                "wheelbase_in": 180,
            },
            plant_admin_headers,
        ),
        ApiErrorId.ERR_SUPPLIER_NOT_FOUND,
        404,
    )
    assert body_error["message"].strip()

    _rows, meta = validate_paginated(api.list_chassis_receipts(plant_admin_headers))
    assert meta["total_count"] == 0


def test_order_and_supply_reads_report_their_own_not_found_code(
    api, plant_admin_headers, scheduler_headers, supervisor_headers
):
    """PRD §2.8: "Every `{id}` segment resolves to an existing row of the addressed entity, else the entity-specific 404 code: `ERR_UNIT_ORDER_NOT_FOUND`, `ERR_PRODUCTION_SLOT_NOT_FOUND`, `ERR_CHASSIS_RECEIPT_NOT_FOUND`, `ERR_COMPONENT_LOT_NOT_FOUND`, `ERR_UNIT_BUILD_NOT_FOUND`, `ERR_COMPONENT_INSTALLATION_NOT_FOUND`, `ERR_QUALITY_INSPECTION_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`, `ERR_RECALL_CAMPAIGN_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_FLOOR_PLAN_NOT_FOUND`, `ERR_OPTION_ITEM_NOT_FOUND`, `ERR_PRODUCTION_LINE_NOT_FOUND`, or `ERR_TEST_BOOTH_NOT_FOUND`."

    PRD §2.8: "Every foreign key supplied in the request **body** resolves to an existing row, using the same per-entity 404 codes, and checked in the field order the endpoint declares its inputs."
    PRD §3.5: "A `LineSupervisor` records an installation by naming the `unit_build_id` receiving the pieces, the `component_lot_id` they came from, the `station` at which they went in, and a `quantity` of at least one."

    Design: Corner/entities/order_and_supply_path_ids_not_found
    """
    advance_clock("2026-08-02T00:00:00Z")

    validate_error(
        api.get_unit_order(UNKNOWN_IDS["unit_order"], scheduler_headers),
        ApiErrorId.ERR_UNIT_ORDER_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_production_slot(UNKNOWN_IDS["production_slot"], scheduler_headers),
        ApiErrorId.ERR_PRODUCTION_SLOT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_chassis_receipt(UNKNOWN_IDS["chassis_receipt"], scheduler_headers),
        ApiErrorId.ERR_CHASSIS_RECEIPT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_component_lot(UNKNOWN_IDS["component_lot"], plant_admin_headers),
        ApiErrorId.ERR_COMPONENT_LOT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_unit_build(UNKNOWN_IDS["unit_build"], supervisor_headers),
        ApiErrorId.ERR_UNIT_BUILD_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_component_installation(
            {
                "unit_build_id": UNKNOWN_IDS["body_build"],
                "component_lot_id": UNKNOWN_IDS["body_lot"],
                "station": "APPLIANCE_INSTALL",
                "quantity": 1,
            },
            supervisor_headers,
        ),
        ApiErrorId.ERR_UNIT_BUILD_NOT_FOUND,
        404,
    )

    _rows, meta = validate_paginated(api.list_component_installations(plant_admin_headers))
    assert meta["total_count"] == 0


def test_quality_warranty_and_recall_transitions_report_not_found_before_state(
    api, plant_admin_headers, inspector_headers, warranty_admin_headers, recall_coordinator_headers
):
    """PRD §2.8: "Every `{id}` segment resolves to an existing row of the addressed entity, else the entity-specific 404 code: `ERR_UNIT_ORDER_NOT_FOUND`, `ERR_PRODUCTION_SLOT_NOT_FOUND`, `ERR_CHASSIS_RECEIPT_NOT_FOUND`, `ERR_COMPONENT_LOT_NOT_FOUND`, `ERR_UNIT_BUILD_NOT_FOUND`, `ERR_COMPONENT_INSTALLATION_NOT_FOUND`, `ERR_QUALITY_INSPECTION_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`, `ERR_RECALL_CAMPAIGN_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_FLOOR_PLAN_NOT_FOUND`, `ERR_OPTION_ITEM_NOT_FOUND`, `ERR_PRODUCTION_LINE_NOT_FOUND`, or `ERR_TEST_BOOTH_NOT_FOUND`."

    PRD §2.8: "Validation is a strictly ordered ladder, not a set of independent checks. The **first** violated rule determines the response; later rules are never reported even when they are also violated."
    PRD §3.8: "A `WarrantyAdministrator` pays a claim whose `status` is `APPROVED`, driving it `APPROVED → PAID` and stamping `paid_by_user_id` from the acting `X-User-ID`, which must differ from `approved_by_user_id`."

    Design: Corner/entities/quality_warranty_and_recall_path_ids_not_found
    """
    advance_clock("2026-08-02T00:00:00Z")

    validate_error(
        api.get_component_installation(UNKNOWN_IDS["installation"], plant_admin_headers),
        ApiErrorId.ERR_COMPONENT_INSTALLATION_NOT_FOUND,
        404,
    )
    validate_error(
        api.complete_inspection(
            UNKNOWN_IDS["inspection"],
            {"defect_points": 0, "leak_detected": False},
            inspector_headers,
        ),
        ApiErrorId.ERR_QUALITY_INSPECTION_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_warranty_claim(UNKNOWN_IDS["claim"], warranty_admin_headers),
        ApiErrorId.ERR_WARRANTY_CLAIM_NOT_FOUND,
        404,
    )
    validate_error(
        api.pay_claim(UNKNOWN_IDS["claim_pay"], warranty_admin_headers),
        ApiErrorId.ERR_WARRANTY_CLAIM_NOT_FOUND,
        404,
    )
    validate_error(
        api.open_recall_campaign(UNKNOWN_IDS["campaign"], recall_coordinator_headers),
        ApiErrorId.ERR_RECALL_CAMPAIGN_NOT_FOUND,
        404,
    )


def test_dealer_and_supplier_registration_require_every_non_defaulted_field(
    api, plant_admin_headers
):
    """PRD §2.8: "The body parses; every required field is present; every field matches its declared type; every enum value is a declared member; every money field is a non-negative integer; every station-hour field carries at most two decimals; no array field contains duplicates. Violations are `ERR_INVALID_REQUEST` (400)."

    PRD §3.1: "A **dealer** is registered with a `dealer_code` unique across dealers, a freight `region`, an `allocation_share_bp` between 1 and 10000 expressing its share of plant monthly capacity in basis points, a `floor_plan_credit_limit_cents` greater than zero, a `goodwill_budget_cents` of zero or more representing its annual goodwill authority pool, and a `status` defaulting to `ACTIVE`."
    PRD §3.1: "A **supplier** is registered with a `supplier_code` (unique across suppliers and between 3 and 16 characters), a legal `name`, and a non-empty `component_categories` array whose members are drawn from `CHASSIS`, `APPLIANCE`, `PLUMBING`, and `ELECTRICAL`."

    Design: Corner/entities/create_dealer_missing_required_fields_returns_invalid_request
    """
    advance_clock("2026-08-02T00:00:00Z")

    validate_error(
        api.create_dealer(
            {
                "dealer_code": "D-NOREGION",
                "allocation_share_bp": 1500,
                "floor_plan_credit_limit_cents": 100000000,
                "goodwill_budget_cents": 500000,
            },
            plant_admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_dealer(
            {
                "dealer_code": "D-NOLIMIT",
                "region": "WEST",
                "allocation_share_bp": 1500,
                "goodwill_budget_cents": 500000,
            },
            plant_admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_supplier(
            {"supplier_code": "SUP-NOCAT", "name": "Categoryless Supply"}, plant_admin_headers
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_supplier(
            {
                "supplier_code": "SUP-EMPTY",
                "name": "Empty Category Supply",
                "component_categories": [],
            },
            plant_admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    # The unique codes are still free, so none of the four calls wrote a row.
    dealer = validate_success(
        api.create_dealer(
            {
                "dealer_code": "D-NOREGION",
                "region": "WEST",
                "allocation_share_bp": 1500,
                "floor_plan_credit_limit_cents": 100000000,
                "goodwill_budget_cents": 500000,
            },
            plant_admin_headers,
        ),
        201,
    )
    assert dealer["dealer_code"] == "D-NOREGION"
    supplier = validate_success(
        api.create_supplier(
            {
                "supplier_code": "SUP-NOCAT",
                "name": "Categoryless Supply",
                "component_categories": ["CHASSIS"],
            },
            plant_admin_headers,
        ),
        201,
    )
    assert supplier["supplier_code"] == "SUP-NOCAT"


def test_invalid_enum_and_out_of_range_physical_values_are_rejected_at_create(
    api, plant_admin_headers
):
    """PRD §2.10: "Chassis families are `CLASS_A`, `CLASS_C`, and `TOWABLE`."

    PRD §2.10: "The system's enumerations are closed sets and the exact strings below are the contract. A value outside its set is a schema violation under band 3."
    PRD §3.1: "It is published with a `model_code` unique across floor plans, a `chassis_class`, an overall coach `length_ft` between 18 and 45 inclusive, a `base_msrp_cents` greater than zero, a `base_station_hours` figure greater than zero carrying at most two decimals, a `base_dry_weight_lbs` greater than zero, a `gvwr_lbs` strictly greater than `base_dry_weight_lbs`, an exact `required_wheelbase_in` greater than zero, an `electrical_service_amps` rating of either 30 or 50, a `fresh_water_capacity_gal` greater than zero, and optionally a `status` that defaults to `ACTIVE`."
    PRD §3.1: "A **component lot** records pieces with a `supplier_id`, a `part_number`, a `lot_code` unique within that supplier-and-part-number pair, a `category` that must be among its supplier's `component_categories`, and a `quantity_received` greater than zero."
    PRD §2.8: "The body parses; every required field is present; every field matches its declared type; every enum value is a declared member; every money field is a non-negative integer; every station-hour field carries at most two decimals; no array field contains duplicates. Violations are `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_rows_with_invalid_enum_and_out_of_range_values_are_rejected
    """
    supplier = create_supplier(
        supplier_code="SUP-CH",
        name="Cascade Chassis Works",
        component_categories=["CHASSIS", "APPLIANCE"],
    )

    validate_error(
        api.create_floor_plan(
            {**CANON_FLOOR_PLAN, "model_code": "FP-BADCLASS", "chassis_class": "CLASS_B"},
            plant_admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_floor_plan(
            {**CANON_FLOOR_PLAN, "model_code": "FP-TOOLONG", "length_ft": 50},
            plant_admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_floor_plan(
            {**CANON_FLOOR_PLAN, "model_code": "FP-BADAMPS", "electrical_service_amps": 40},
            plant_admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_floor_plan(
            {**CANON_FLOOR_PLAN, "model_code": "FP-BADGVWR", "gvwr_lbs": 22400},
            plant_admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_component_lot(
            {
                "supplier_id": supplier["id"],
                "part_number": "WH-6G-2026",
                "lot_code": "L-ZERO",
                "category": "APPLIANCE",
                "quantity_received": 0,
            },
            plant_admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    _rows, meta = validate_paginated(
        api.list_component_lots(plant_admin_headers, params={"supplier_id": supplier["id"]})
    )
    assert meta["total_count"] == 0


def test_installation_is_reachable_from_its_build_and_its_lot(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §3.5: "A `LineSupervisor` records an installation by naming the `unit_build_id` receiving the pieces, the `component_lot_id` they came from, the `station` at which they went in, and a `quantity` of at least one."

    PRD §3.5: "On success the lot's `quantity_available` decreases by the installed quantity and its `quantity_installed` increases by the same amount, conserving the piece total, and a lot whose `quantity_available` reaches exactly zero moves `AVAILABLE → DEPLETED`. The new installation starts at `status` `INSTALLED` with `recall_campaign_id` null."
    PRD §3.5: "Installations are listable with filters on `unit_build_id`, `component_lot_id`, `recall_campaign_id`, and `status`."
    PRD §3.4: "It records the order it serves as `unit_order_id` and the chassis it consumed as `chassis_receipt_id` — both taken from the operation's context, never from a body."
    PRD §3.4: "It receives a `build_sequence` equal to the plant-wide build counter plus one, a one-based monotonic figure in build-creation order, and a `vin` formed from the floor plan's `model_code`, then a hyphen, then that `build_sequence` zero-padded to six digits."
    PRD §3.4: "Builds are listable with filters on `unit_order_id`, `chassis_receipt_id`, `current_station`, and `recall_hold`."
    PRD §3.1: "Chassis receipts and component lots are both listable with filters. Chassis receipts may be narrowed by `supplier_id`, `matched_unit_order_id`, `status`, and `chassis_class`; component lots by `supplier_id`, `part_number`, `lot_code`, and `status`."
    PRD §3.3: "The created slot is stamped `RESERVED` with `station_hours_committed` copied from the order's `required_station_hours` at the moment of reservation, a one-based `sequence_position` equal to the day bucket's occupied-unit count plus one (which is the coach's build order on that line that day), and an `expires_at` exactly 72 hours after the slot's `created_at`."

    Design: Corner/entities/component_installation_links_build_and_lot_and_is_findable_from_both_sides
    """
    chassis_supplier = create_supplier(
        supplier_code="SUP-CH", name="Cascade Chassis Works", component_categories=["CHASSIS"]
    )
    appliance_supplier = create_supplier(
        supplier_code="SUP-APP", name="Northline Appliance", component_categories=["APPLIANCE"]
    )
    floor_plan = create_floor_plan(**CANON_FLOOR_PLAN)
    option_wash = create_option_item(**OPT_WASH)
    dealer = create_dealer(
        dealer_code="D-CANON",
        region="WEST",
        allocation_share_bp=1500,
        floor_plan_credit_limit_cents=100000000,
        goodwill_budget_cents=500000,
    )
    line = create_production_line(
        line_code="LINE-A",
        chassis_class_supported="CLASS_A",
        daily_station_hour_capacity=240.00,
        max_units_per_day=4,
    )
    chassis = create_chassis_receipt(
        chassis_supplier["id"],
        chassis_serial="CH-0001",
        chassis_class="CLASS_A",
        gvwr_lbs=26000,
        wheelbase_in=242,
    )
    lot = create_component_lot(
        appliance_supplier["id"],
        part_number="WH-6G-2026",
        lot_code="L-2211",
        category="APPLIANCE",
        quantity_received=20,
    )
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="SOLD",
        selected_option_ids=[option_wash["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    order = submit_order(order["id"], dealer["id"])
    slot = reserve_slot(order["id"], line["id"], "2026-08-05T00:00:00Z", order["version"])
    match_chassis(order["id"])
    build = release_to_line(order["id"])
    for station in ("SIDEWALL_LAM", "ROOF_SET", "ROUGH_IN", "APPLIANCE_INSTALL"):
        advance_build(build["id"], station, 5.00)
    installation = install_pieces(build["id"], lot["id"], "APPLIANCE_INSTALL", 2)

    by_build, by_build_meta = validate_paginated(
        api.list_component_installations(
            plant_admin_headers, params={"unit_build_id": build["id"]}
        )
    )
    by_lot, by_lot_meta = validate_paginated(
        api.list_component_installations(
            plant_admin_headers, params={"component_lot_id": lot["id"]}
        )
    )
    builds_by_order, _ = validate_paginated(
        api.list_unit_builds(scheduler_headers, params={"unit_order_id": order["id"]})
    )
    chassis_by_order, _ = validate_paginated(
        api.list_chassis_receipts(scheduler_headers, params={"matched_unit_order_id": order["id"]})
    )

    assert by_build[0]["id"] == installation["id"]
    assert by_build_meta["total_count"] == 1
    assert by_lot[0]["id"] == installation["id"]
    assert by_lot_meta["total_count"] == 1

    assert builds_by_order[0]["id"] == build["id"]
    assert chassis_by_order[0]["id"] == chassis["id"]

    stored_installation = validate_success(
        api.get_component_installation(installation["id"], plant_admin_headers)
    )
    assert_component_installation(stored_installation)
    assert stored_installation["station"] == "APPLIANCE_INSTALL"
    assert stored_installation["quantity"] == 2
    assert stored_installation["status"] == "INSTALLED"
    assert stored_installation["recall_campaign_id"] is None

    stored_lot = read_lot(lot["id"])
    assert stored_lot["quantity_available"] == 18
    assert stored_lot["quantity_installed"] == 2
    assert stored_lot["status"] == "AVAILABLE"
    assert_lot_counter_invariant(stored_lot)

    stored_build = read_build(build["id"])
    assert_vin_format(stored_build["vin"], "FP-3410", 1)
    assert stored_build["vin"] == "FP-3410-000001"
    assert stored_build["build_sequence"] == 1

    assert_hours(read_order(order["id"])["required_station_hours"], "56.35")
    stored_slot = validate_success(api.get_production_slot(slot["id"], plant_admin_headers))
    assert_hours(stored_slot["station_hours_committed"], "56.35")


def test_supplier_and_lot_single_reads_return_stored_and_derived_fields(
    api, scheduler_headers, supervisor_headers
):
    """PRD §3.1: "On registration a supplier's derived trust fields start clean: `quality_score` is `100.00`, `supplier_status` is `ACTIVE`, `open_recall_count` is 0, and `penalty_event_count` is 0."

    PRD §3.1: "On receipt `quantity_available` equals `quantity_received`, `quantity_installed` is 0, `quantity_quarantined` is 0, and `status` is `AVAILABLE`."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the row."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/supplier_and_lot_retrieval_return_stored_and_derived_fields
    """
    supplier = create_supplier(
        supplier_code="SUP-APP",
        name="Northline Appliance",
        component_categories=["APPLIANCE", "PLUMBING"],
    )
    lot = create_component_lot(
        supplier["id"],
        part_number="WH-6G-2026",
        lot_code="L-2211",
        category="APPLIANCE",
        quantity_received=20,
    )

    supplier_response = api.get_supplier(supplier["id"], scheduler_headers)
    stored_supplier = validate_success(supplier_response, 200)
    assert supplier_response.json()["response_type"] == "object"

    stored_lot = validate_success(api.get_component_lot(lot["id"], supervisor_headers))

    assert_supplier(stored_supplier)
    assert stored_supplier["supplier_code"] == "SUP-APP"
    assert stored_supplier["name"] == "Northline Appliance"
    assert stored_supplier["component_categories"] == ["APPLIANCE", "PLUMBING"]
    assert_two_decimals(stored_supplier["quality_score"], "100.00")
    assert stored_supplier["supplier_status"] == "ACTIVE"
    assert stored_supplier["open_recall_count"] == 0
    assert stored_supplier["penalty_event_count"] == 0
    assert stored_supplier["version"] == 1

    assert_component_lot(stored_lot)
    assert stored_lot["quantity_received"] == 20
    assert stored_lot["quantity_available"] == 20
    assert stored_lot["quantity_installed"] == 0
    assert stored_lot["quantity_quarantined"] == 0
    assert stored_lot["status"] == "AVAILABLE"
    assert stored_lot["version"] == 1


def test_pinned_floor_plan_version_and_provisional_invoice_survive_a_reprice(
    api, plant_admin_headers
):
    """PRD §3.2: "An order that clears all of it is stamped: the roll-up is recomputed, `provisional_invoice_cents` is written, `locked_floor_plan_version` is pinned to the floor plan's current `version`, and `locked_option_versions` is pinned as one entry per selected option carrying that option's identifier, its `version`, and its `price_cents` at the moment of submit."

    PRD §3.1: "A floor plan may later be repriced through `base_msrp_cents` or retired by setting `status` to `RETIRED`; either edit increments the plan's `version`, which invalidates the pinned reference on every already-submitted order that names it."
    PRD §3.1: "The plant derives `max_payload_lbs` as the gross vehicle weight rating minus the base dry weight, and re-derives it whenever the plan is edited."
    PRD §3.2: "That pinned price is what the *final* invoice reprices from months later, so a mid-flight catalogue reprice never silently moves an already-committed invoice — it instead trips the drift detector of §3.4."
    PRD §3.2: "**Submitting** the order is the moment the configuration becomes a commitment, moving `status` from `DRAFT` to `CONFIG_VALIDATED`."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the row."

    Design: Corner/entities/pinned_configuration_snapshot_survives_a_floor_plan_reprice
    """
    floor_plan = create_floor_plan(**TOW_FLOOR_PLAN)
    option = create_option_item(**OPT_E1)
    dealer = create_dealer(
        dealer_code="D-TOW",
        region="CENTRAL",
        allocation_share_bp=1500,
        floor_plan_credit_limit_cents=100000000,
        goodwill_budget_cents=500000,
    )
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    submitted = submit_order(order["id"], dealer["id"])

    repriced = validate_success(
        api.patch_floor_plan(floor_plan["id"], {"base_msrp_cents": 9000000}, plant_admin_headers)
    )
    stored_order = validate_success(api.get_unit_order(order["id"], plant_admin_headers))

    assert submitted["locked_floor_plan_version"] == 1
    assert submitted["version"] == 2

    assert repriced["version"] == 2
    assert_cents(repriced["base_msrp_cents"], 9000000)
    assert repriced["max_payload_lbs"] == 3000

    assert stored_order["locked_floor_plan_version"] == 1
    assert_cents(stored_order["provisional_invoice_cents"], 6620350)
    assert stored_order["version"] == 2
    assert stored_order["status"] == "CONFIG_VALIDATED"


def test_slot_reservation_takes_its_order_from_the_path(api, scheduler_headers):
    """PRD §3.3: "The order's identifier comes from the path and is never taken from the body; the created slot records it as `unit_order_id`. A successful reservation drives the order's `status` from `CONFIG_VALIDATED` to `SLOTTED`."

    PRD §2.8: "Every `{id}` segment resolves to an existing row of the addressed entity, else the entity-specific 404 code: `ERR_UNIT_ORDER_NOT_FOUND`, `ERR_PRODUCTION_SLOT_NOT_FOUND`, `ERR_CHASSIS_RECEIPT_NOT_FOUND`, `ERR_COMPONENT_LOT_NOT_FOUND`, `ERR_UNIT_BUILD_NOT_FOUND`, `ERR_COMPONENT_INSTALLATION_NOT_FOUND`, `ERR_QUALITY_INSPECTION_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`, `ERR_RECALL_CAMPAIGN_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_FLOOR_PLAN_NOT_FOUND`, `ERR_OPTION_ITEM_NOT_FOUND`, `ERR_PRODUCTION_LINE_NOT_FOUND`, or `ERR_TEST_BOOTH_NOT_FOUND`."
    PRD §3.3: "The created slot is stamped `RESERVED` with `station_hours_committed` copied from the order's `required_station_hours` at the moment of reservation, a one-based `sequence_position` equal to the day bucket's occupied-unit count plus one (which is the coach's build order on that line that day), and an `expires_at` exactly 72 hours after the slot's `created_at`."
    PRD §3.3: "Slots are listable with filters on `line_id`, `unit_order_id`, `slot_date`, and `status`."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the row."

    Design: Corner/entities/nested_slot_route_binds_the_slot_to_the_path_order
    """
    floor_plan = create_floor_plan(**TOW_FLOOR_PLAN)
    option = create_option_item(**OPT_E1)
    dealer = create_dealer(
        dealer_code="D-TOW",
        region="CENTRAL",
        allocation_share_bp=1500,
        floor_plan_credit_limit_cents=100000000,
        goodwill_budget_cents=500000,
    )
    line = create_production_line(
        line_code="LINE-T",
        chassis_class_supported="TOWABLE",
        daily_station_hour_capacity=240.00,
        max_units_per_day=4,
    )
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    submitted = submit_order(order["id"], dealer["id"])

    slot_payload = {
        "line_id": line["id"],
        "slot_date": "2026-08-05T00:00:00Z",
        "expected_unit_order_version": submitted["version"],
    }
    validate_error(
        api.reserve_production_slot(UNKNOWN_IDS["orphan_order"], slot_payload, scheduler_headers),
        ApiErrorId.ERR_UNIT_ORDER_NOT_FOUND,
        404,
    )

    slot = validate_success(
        api.reserve_production_slot(order["id"], slot_payload, scheduler_headers), 201
    )
    assert slot["unit_order_id"] == order["id"]
    assert slot["line_id"] == line["id"]
    assert_same_instant(slot["slot_date"], "2026-08-05T00:00:00Z")
    assert slot["status"] == "RESERVED"
    assert_hours(slot["station_hours_committed"], "41.00")
    assert slot["sequence_position"] == 1
    assert_same_instant(slot["expires_at"], "2026-08-04T00:00:00Z")

    listed, listed_meta = validate_paginated(
        api.list_production_slots(scheduler_headers, params={"unit_order_id": order["id"]})
    )
    assert listed[0]["id"] == slot["id"]
    assert listed_meta["total_count"] == 1

    stored_order = read_order(order["id"])
    assert stored_order["status"] == "SLOTTED"
    assert stored_order["version"] == 3
