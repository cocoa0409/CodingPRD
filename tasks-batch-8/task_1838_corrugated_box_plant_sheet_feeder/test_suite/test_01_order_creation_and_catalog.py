"""Order creation, master data, listing, and creation-time validation rules."""
import pytest

from test_helpers import (
    UNKNOWN_UUID,
    ApiErrorId,
    assert_box_order,
    assert_customer_account,
    assert_money,
    create_board_grade_payload,
    create_box_order_payload,
    create_customer,
    create_draft_order,
    create_grade,
    create_inventory_program,
    create_release,
    create_stocked_program,
    make_customer_headers,
    post_receipt,
    quote_order,
    setup_customer_and_grade,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

SALES = TEST_USERS["sales_rep_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


def test_create_customer_account_returns_server_managed_defaults(api, sales_rep_headers):
    """PRD 2.4: "Every entity in the system carries four server-managed
    properties: `id` (a server-minted UUID with no type prefix), `created_at`
    (an ISO 8601 UTC timestamp with three fractional digits), `updated_at`
    (same format, refreshed on every mutation), and `version` (an integer that
    increments by 1 on every mutation of that entity)."
    PRD 3.1: "The account's `credit_exposure_dollars` initializes to 0 and is
    thereafter maintained entirely by the server".

    Design: Corner/entities/customer_account_creation_defaults_and_system_fields
    """
    res = api.create_customer_account(
        {
            "account_name": "Acme Foods",
            "ship_to_city": "Fresno",
            "distance_miles_from_plant": 120.0,
            "credit_limit_dollars": 50000.00,
        },
        sales_rep_headers,
    )
    customer = validate_success(res, 201)
    assert_customer_account(customer)
    assert customer["version"] == 1
    assert customer["credit_exposure_dollars"] == 0
    assert customer["created_at"] == customer["updated_at"]


def test_duplicate_grade_code_rejected(api, plant_admin_headers):
    """PRD 3.1: "A `PlantAdmin` registers each grade with `grade_code` (unique
    across all board grades — a duplicate submission is rejected with
    `ERR_DUPLICATE_CODE`)".

    Design: Corner/entities/board_grade_duplicate_code_rejected
    """
    first = api.create_board_grade(
        create_board_grade_payload(grade_code="32C"), plant_admin_headers
    )
    validate_success(first, 201)
    dup = api.create_board_grade(
        create_board_grade_payload(
            grade_code="32C",
            liner_combo="42/26/42",
            flute="B",
            ect_rating_lbs_per_in=40,
            burst_rating_psi=250,
            basis_weight_lbs_per_msf=110.0,
        ),
        plant_admin_headers,
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_CODE, expected_status=409)


def test_order_create_computes_area_and_ignores_client_computed_fields(
    api, sales_rep_headers
):
    """PRD 3.2: "At creation the server computes `area_sqft_per_box` — the
    product of `blank_width_in` and `blank_length_in` divided by 144, rounded
    half-up to 4 decimal places — and `color_count`, the number of entries in
    `ink_colors`. The order's `committed_value_dollars` starts at 0, and
    `corrugator_run_id`, `produced_qty`, and all five `invoice_*` fields start
    null."
    PRD 2.8: "None of these are writable by clients; each is recomputed by the
    server whenever an operation that feeds it commits."

    Design: Corner/entities/box_order_computed_fields_and_input_ignored
    """
    customer, grade = setup_customer_and_grade()
    payload = create_box_order_payload(customer["id"], grade["id"])
    payload["area_sqft_per_box"] = 999.0  # client-sent computed field: ignored
    res = api.create_box_order(payload, sales_rep_headers)
    order = validate_success(res, 201)
    assert_box_order(order)
    assert_money(order["area_sqft_per_box"], 7.25)
    assert order["color_count"] == 2
    assert order["ink_colors"] == ["BLACK", "RED"]
    assert order["corrugator_run_id"] is None
    assert order["committed_value_dollars"] == 0
    assert order["status"] == "DRAFT"


def test_order_create_missing_quantity_rejected(api, sales_rep_headers):
    """PRD 3.2: "A box order begins life in `DRAFT` when a `SalesRep` creates
    it with `customer_id`, `board_grade_id`, `routing_type` (`DIE_CUT` or
    `SLOTTED`, selecting the converting branch), `board_source` (`INTERNAL`
    when the plant corrugates its own board, `SHEET_FEEDER` when pre-combined
    sheets are purchased from an outside sheet feeder), `quantity` (strictly
    positive)".
    PRD 2.7: "General business constraints are sixth: well-formedness
    (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/box_order_missing_required_field_returns_invalid_request
    """
    customer, grade = setup_customer_and_grade()
    payload = create_box_order_payload(
        customer["id"],
        grade["id"],
        routing_type="SLOTTED",
        quantity=100,
        blank_width_in=24.0,
        blank_length_in=20.0,
        min_ect_required=30,
        ink_colors=[],
    )
    del payload["quantity"]
    res = api.create_box_order(payload, sales_rep_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_order_create_invalid_routing_type_rejected(api, sales_rep_headers):
    """PRD 3.2: "`routing_type` (`DIE_CUT` or `SLOTTED`, selecting the
    converting branch)".
    PRD 2.7: "General business constraints are sixth: well-formedness
    (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/box_order_invalid_enum_returns_invalid_request
    """
    customer, grade = setup_customer_and_grade()
    payload = create_box_order_payload(
        customer["id"],
        grade["id"],
        routing_type="SPIRAL",
        quantity=100,
        blank_width_in=24.0,
        blank_length_in=20.0,
        min_ect_required=30,
        ink_colors=[],
    )
    res = api.create_box_order(payload, sales_rep_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_get_box_order_not_found(api, sales_rep_headers):
    """PRD 2.7: "Existence of every path id and every body-supplied foreign key
    is checked next (priority 3), surfacing `ERR_NOT_FOUND`."

    Design: Corner/entities/box_order_get_not_found_returns_404
    """
    res = api.get_box_order(UNKNOWN_UUID, sales_rep_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_order_create_with_unknown_grade_reference_not_found(api, sales_rep_headers):
    """PRD 2.7: "Existence of every path id and every body-supplied foreign key
    is checked next (priority 3), surfacing `ERR_NOT_FOUND`."

    Design: Corner/entities/box_order_fk_reference_not_found
    """
    customer = create_customer()
    payload = create_box_order_payload(
        customer["id"],
        UNKNOWN_UUID,
        routing_type="SLOTTED",
        quantity=100,
        blank_width_in=24.0,
        blank_length_in=20.0,
        min_ect_required=99,
        ink_colors=[],
    )
    res = api.create_box_order(payload, sales_rep_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_box_order_list_pagination(api, sales_rep_headers):
    """PRD 2.3: "List endpoints accept `limit` and `offset` query parameters.
    `limit` defaults to 10, must be at least 1, and may not exceed 100.
    `offset` defaults to 0. The `meta` block of every list response carries
    `limit`, `offset`, `total_count`, and `has_more`. All list endpoints sort
    by `created_at` ascending."

    Design: Corner/entities/box_order_list_pagination
    """
    customer, grade = setup_customer_and_grade()
    for qty in (100, 200, 300):
        create_draft_order(
            customer["id"],
            grade["id"],
            routing_type="SLOTTED",
            quantity=qty,
            blank_width_in=24.0,
            blank_length_in=20.0,
            min_ect_required=30,
            ink_colors=[],
        )

    page1, meta1 = validate_paginated(
        api.list_box_orders(sales_rep_headers, params={"limit": 2})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_box_orders(sales_rep_headers, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert page1[0]["id"] != page2[0]["id"]


def test_order_without_ink_colors_defaults_empty_and_no_surcharge(
    api, sales_rep_headers
):
    """PRD 3.2: "optionally `ink_colors` (a set such as [BLACK, RED],
    defaulting to empty)".
    PRD 3.3: "Third, the merchandise rate per thousand square feet: the locked
    `unit_price_per_msf` plus a color surcharge of 1.50 per MSF for each entry
    in `color_count`."

    Design: Corner/entities/box_order_ink_colors_default_empty
    """
    customer, grade = setup_customer_and_grade()
    payload = create_box_order_payload(
        customer["id"],
        grade["id"],
        routing_type="SLOTTED",
        quantity=1000,
        blank_width_in=24.0,
        blank_length_in=20.0,
        min_ect_required=30,
    )
    # Omit ink_colors entirely so the server-side default (empty) is exercised;
    # the shared factory would otherwise inject its own default.
    del payload["ink_colors"]
    order = validate_success(api.create_box_order(payload, sales_rep_headers), 201)
    assert order["ink_colors"] == []
    assert order["color_count"] == 0

    quote = quote_order(order, unit_price=50.00)
    # billable 3.3333 MSF x 50.00 flat rate x 1.00 SLOTTED multiplier
    assert_money(quote["merchandise_total_dollars"], 166.67)


def test_new_entities_start_in_initial_states(api, sales_rep_headers):
    """PRD 3.2: "A box order begins life in `DRAFT` when a `SalesRep` creates
    it".
    PRD 3.2: "On success a `PriceQuote` is created in `OPEN` status with its
    full PROVISIONAL pricing computed (see §3.3)".
    PRD 3.7: "The program starts `ACTIVE` with `on_hand_qty` 0 and
    `committed_qty` 0."

    Design: Corner/state_machines/initial_states_on_creation
    """
    customer, grade = setup_customer_and_grade()
    order = create_draft_order(
        customer["id"],
        grade["id"],
        routing_type="SLOTTED",
        quantity=100,
        blank_width_in=24.0,
        blank_length_in=20.0,
        min_ect_required=30,
        ink_colors=[],
    )
    assert order["status"] == "DRAFT"

    quote = quote_order(order, unit_price=50.00)
    assert quote["status"] == "OPEN"
    order_after = validate_success(api.get_box_order(order["id"], sales_rep_headers))
    assert order_after["status"] == "QUOTED"

    program = create_inventory_program(
        customer["id"], grade["id"], reorder_point=10, replenishment_qty=500
    )
    assert program["status"] == "ACTIVE"
    assert program["on_hand_qty"] == 0
    assert program["committed_qty"] == 0
    assert program["available_qty"] == 0


def test_ect_equality_satisfies_spec(api, sales_rep_headers):
    """PRD 3.2: "Second, the strength floor: `min_ect_required` may not exceed
    the referenced grade's `ect_rating_lbs_per_in`, with equality allowed; an
    excess is rejected with `ERR_ECT_SPEC_NOT_MET`."

    Design: Corner/validations/ect_equality_satisfies_spec
    """
    customer, grade = setup_customer_and_grade()  # grade ect_rating 32
    ok = api.create_box_order(
        create_box_order_payload(
            customer["id"],
            grade["id"],
            routing_type="SLOTTED",
            quantity=100,
            blank_width_in=24.0,
            blank_length_in=20.0,
            min_ect_required=32,
            ink_colors=[],
        ),
        sales_rep_headers,
    )
    order = validate_success(ok, 201)
    assert_box_order(order)

    over = api.create_box_order(
        create_box_order_payload(
            customer["id"],
            grade["id"],
            routing_type="SLOTTED",
            quantity=100,
            blank_width_in=24.0,
            blank_length_in=20.0,
            min_ect_required=33,
            ink_colors=[],
        ),
        sales_rep_headers,
    )
    validate_error(over, ApiErrorId.ERR_ECT_SPEC_NOT_MET, expected_status=422)


def test_supplier_name_conditional_requirement(api, sales_rep_headers):
    """PRD 3.2: "First, the supplier rule: when `board_source` is
    `SHEET_FEEDER`, `sheet_supplier_name` is required; when `board_source` is
    `INTERNAL`, `sheet_supplier_name` is forbidden — a violation either way is
    rejected with `ERR_SUPPLIER_REQUIRED`."

    Design: Corner/validations/supplier_required_conditional_field
    """
    customer, grade = setup_customer_and_grade()
    missing = api.create_box_order(
        create_box_order_payload(
            customer["id"],
            grade["id"],
            routing_type="SLOTTED",
            board_source="SHEET_FEEDER",
            quantity=100,
            blank_width_in=24.0,
            blank_length_in=20.0,
            min_ect_required=30,
            ink_colors=[],
        ),
        sales_rep_headers,
    )
    validate_error(missing, ApiErrorId.ERR_SUPPLIER_REQUIRED, expected_status=422)

    forbidden = api.create_box_order(
        create_box_order_payload(
            customer["id"],
            grade["id"],
            routing_type="SLOTTED",
            board_source="INTERNAL",
            sheet_supplier_name="SheetCo",
            quantity=100,
            blank_width_in=24.0,
            blank_length_in=20.0,
            min_ect_required=30,
            ink_colors=[],
        ),
        sales_rep_headers,
    )
    validate_error(forbidden, ApiErrorId.ERR_SUPPLIER_REQUIRED, expected_status=422)


def test_children_reverse_reachable_via_subresource_lists(api, sales_rep_headers):
    """PRD 3.2: "On success a `PriceQuote` is created in `OPEN` status with its
    full PROVISIONAL pricing computed (see §3.3), its `order_id` pointing back
    at the parent box order".
    PRD 4 lists GET /api/box-orders/{id}/quotes ("List quotes of an order") and
    GET /api/inventory-programs/{id}/release-orders ("List release orders of a
    program").

    Design: Corner/endpoints/children_reverse_reachable_via_subresource_lists
    """
    customer, grade = setup_customer_and_grade()
    order = create_draft_order(
        customer["id"],
        grade["id"],
        routing_type="SLOTTED",
        quantity=100,
        blank_width_in=24.0,
        blank_length_in=20.0,
        min_ect_required=30,
        ink_colors=[],
    )
    quote = quote_order(order, unit_price=50.00)
    quotes, quotes_meta = validate_paginated(
        api.list_price_quotes(order["id"], sales_rep_headers)
    )
    assert quotes_meta["total_count"] == 1
    assert quotes[0]["id"] == quote["id"]

    program = create_stocked_program(
        customer["id"], grade["id"], 100, reorder_point=10, replenishment_qty=500
    )
    release = create_release(program["id"], 10, customer["id"])
    releases, releases_meta = validate_paginated(
        api.list_release_orders(program["id"], sales_rep_headers)
    )
    assert releases_meta["total_count"] == 1
    assert releases[0]["id"] == release["id"]


def test_ect_safety_error_returned_over_supplier_constraint_error(
    api, sales_rep_headers
):
    """PRD 2.7: "When a request trips multiple rules, the first applicable rule
    by the following priority order determines the error." ... "Business safety
    rules come fifth: the ECT floor on order creation
    (`ERR_ECT_SPEC_NOT_MET`) and the warp-measurement floor on claim filing
    (`ERR_WARP_BELOW_THRESHOLD`). General business constraints are sixth:
    well-formedness (`ERR_INVALID_REQUEST`), quantity ranges
    (`ERR_INVALID_QUANTITY`), supplier-name consistency
    (`ERR_SUPPLIER_REQUIRED`)".

    Design: Difficulty/priority_pair_validation_conflict/order_create_safety_ect_beats_constraint_supplier
    """
    customer, grade = setup_customer_and_grade()  # grade ect_rating 32
    res = api.create_box_order(
        create_box_order_payload(
            customer["id"],
            grade["id"],
            routing_type="SLOTTED",
            board_source="SHEET_FEEDER",  # missing sheet_supplier_name (P6)
            quantity=100,
            blank_width_in=10.0,
            blank_length_in=10.0,
            min_ect_required=99,  # exceeds grade ect 32 (P5)
            ink_colors=[],
        ),
        sales_rep_headers,
    )
    validate_error(res, ApiErrorId.ERR_ECT_SPEC_NOT_MET, expected_status=422)


def test_rejected_order_create_persists_nothing(api, sales_rep_headers):
    """PRD 3.2: "Second, the strength floor: `min_ect_required` may not exceed
    the referenced grade's `ect_rating_lbs_per_in`, with equality allowed; an
    excess is rejected with `ERR_ECT_SPEC_NOT_MET`." A rejected creation
    persists no order.
    PRD 2.3: "The `meta` block of every list response carries `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Difficulty/priority_pair_validation_conflict/order_create_safety_ect_beats_constraint_supplier
    """
    customer, grade = setup_customer_and_grade()
    res = api.create_box_order(
        create_box_order_payload(
            customer["id"],
            grade["id"],
            routing_type="SLOTTED",
            board_source="SHEET_FEEDER",
            quantity=100,
            blank_width_in=10.0,
            blank_length_in=10.0,
            min_ect_required=99,
            ink_colors=[],
        ),
        sales_rep_headers,
    )
    validate_error(res, ApiErrorId.ERR_ECT_SPEC_NOT_MET, expected_status=422)
    _, meta = validate_paginated(api.list_box_orders(sales_rep_headers))
    assert meta["total_count"] == 0, "rejected order creation must persist nothing"
