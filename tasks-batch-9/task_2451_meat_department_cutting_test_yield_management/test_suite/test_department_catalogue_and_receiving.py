"""Provisioning a department, seeding its case catalogue, receiving primals, and
the not-found behaviour of every identifier the meat department hands the API.

Every test starts against an empty database with the logical clock at its
initial instant, and builds the state it needs through the public endpoints.
"""

import pytest

from test_helpers import (
    ADMIN,
    ANALYST,
    CLERK,
    CUTTER,
    DEPARTMENT_DEFAULTS,
    FIXTURE_CLOCK,
    FIXTURE_DATE,
    MANAGER,
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    add_cutting_test_line,
    approve_cutting_test,
    assert_common_fields,
    assert_cost_ledger_conserves,
    assert_department,
    assert_four_decimal_places,
    assert_primal_purchase,
    assert_reading_only_fields,
    assert_retail_item,
    assert_temperature_log,
    assert_three_fractional_digits,
    assert_trim_lot,
    assert_two_decimal_places,
    case_plan_line_payload,
    create_cutting_test,
    create_department,
    create_grind_run,
    create_ground_item,
    create_primal_purchase,
    create_retail_item,
    create_trim_lot_from_line,
    department_payload,
    get_success_data,
    grind_input_payload,
    grind_run_payload,
    is_valid_uuid,
    post_reading,
    primal_purchase_payload,
    propose_price,
    read_cutting_test,
    read_grind_run,
    read_trim_lot,
    received_primal,
    retail_item_payload,
    seeded_department,
    submit_cutting_test,
    temperature_log_payload,
    trim_lot_payload,
    validate_error,
    validate_paginated,
)


def test_department_creation_applies_every_optional_config_default(api):
    """A department provisioned with only a name and a store code operates on every declared default.

    "Everything else is optional configuration, and each optional field has a
    default that the department behaves with until somebody overrides it."

    Design: Corner/entities/department_creation_applies_every_optional_config_default
    """
    department = get_success_data(
        api.create_department(department_payload(), ADMIN), 201
    )

    assert_department(department)
    assert_common_fields(department)
    assert department["name"] == TEST_DEFAULTS["DEPARTMENT_NAME"]
    assert department["store_code"] == TEST_DEFAULTS["STORE_CODE"]
    assert department["version"] == 1

    # The margin target and the three settlement fractions.
    assert department["target_margin_pct"] == pytest.approx(
        DEPARTMENT_DEFAULTS["target_margin_pct"], abs=0.0001
    )
    assert department["markdown_floor_pct"] == pytest.approx(
        DEPARTMENT_DEFAULTS["markdown_floor_pct"], abs=0.0001
    )
    assert department["shrink_tolerance_pct"] == pytest.approx(
        DEPARTMENT_DEFAULTS["shrink_tolerance_pct"], abs=0.0001
    )
    assert department["deposit_rate"] == pytest.approx(
        DEPARTMENT_DEFAULTS["deposit_rate"], abs=0.0001
    )

    # Shelf lives per merchandising class.
    assert department["shelf_life_days_ground"] == 2
    assert department["shelf_life_days_whole_muscle"] == 5
    assert department["shelf_life_days_vac_packed"] == 14

    # Cold-chain thresholds.
    assert department["max_safe_case_temp_c"] == pytest.approx(4.4, abs=0.01)
    assert department["critical_case_temp_c"] == pytest.approx(7.0, abs=0.01)

    # Service and grinder configuration.
    assert department["pickup_slot_capacity"] == 2
    assert department["grind_sanitation_buffer_min"] == 30

    # A department is born operating normally.
    assert department["case_posture"] == "SALES_OPEN"
    assert department["open_case_failure_count"] == 0
    assert department["contained_case_failure_count"] == 0
    assert department["consecutive_out_of_spec_readings"] == 0


def test_primal_purchase_creation_returns_full_landed_cost_ledger(api):
    """Receiving a primal derives its usable weight and opens its cost ledger in the same response.

    "The ledger opens with `allocated_cost_cents` at 0 and
    `unallocated_cost_cents` equal to the full landed total, and the purchase's
    `status` begins at `RECEIVED`."

    Design: Corner/entities/primal_purchase_creation_returns_full_landed_cost_ledger
    """
    department = seeded_department(api)

    purchase = get_success_data(
        api.create_primal_purchase(primal_purchase_payload(department["id"]), CUTTER),
        201,
    )

    assert_primal_purchase(purchase)
    assert purchase["department_id"] == department["id"]
    assert purchase["version"] == 1
    assert purchase["status"] == "RECEIVED"

    # 100.0 lb gross less 1.5 lb of dock purge and packaging.
    assert purchase["net_weight_lb"] == pytest.approx(98.50, abs=0.01)
    assert_two_decimal_places(purchase["net_weight_lb"])

    # 84000 invoice plus 2500 freight less a 500 vendor allowance.
    assert purchase["landed_cost_total_cents"] == 86000

    # 86000 / 98.5 rounded half up to four decimal places.
    assert purchase["landed_cost_per_lb_cents"] == pytest.approx(873.0964, abs=0.0001)
    assert_four_decimal_places(purchase["landed_cost_per_lb_cents"])

    assert purchase["allocated_cost_cents"] == 0
    assert purchase["unallocated_cost_cents"] == 86000
    assert_cost_ledger_conserves(purchase)


def test_primal_purchase_retrieval_returns_stored_entity(api):
    """Reading a received primal back hands over the stored row without recomputing or bumping it.

    "A mutation is any change to a resource's stored data, and that explicitly
    includes changes the server makes to *derived* fields on the caller's
    behalf."

    Design: Corner/entities/primal_purchase_retrieval_returns_stored_entity
    """
    department = seeded_department(api)
    purchase = create_primal_purchase(api, department["id"])

    fetched = get_success_data(api.get_primal_purchase(purchase["id"], ANALYST), 200)

    assert fetched["id"] == purchase["id"]
    assert fetched["vendor_name"] == TEST_DEFAULTS["VENDOR_NAME"]
    assert fetched["country_of_origin"] == "USA"
    assert fetched["primal_code"] == TEST_DEFAULTS["P1_PRIMAL_CODE"]
    assert fetched["net_weight_lb"] == pytest.approx(98.50, abs=0.01)
    assert fetched["landed_cost_total_cents"] == 86000
    assert fetched["landed_cost_per_lb_cents"] == pytest.approx(873.0964, abs=0.0001)
    assert fetched["status"] == "RECEIVED"

    # A read is not a mutation, so neither the counter nor the stamps move.
    assert fetched["version"] == purchase["version"]
    assert fetched["created_at"] == purchase["created_at"]
    assert fetched["updated_at"] == purchase["updated_at"]


def test_temperature_log_listing_paginates_with_total_count_and_has_more(api):
    """A department's reading history pages through its rows while reporting the full run length.

    "List responses carry `limit`, `offset`, `total_count` and `has_more` inside
    the `meta` object of the envelope described in §2.2."

    Design: Corner/entities/temperature_log_listing_paginates_with_total_count_and_has_more
    """
    department = seeded_department(api)
    for _ in range(5):
        post_reading(api, department["id"], "CASE-A", 2.0)

    middle_rows, middle_meta = validate_paginated(
        api.list_department_temperature_logs(
            department["id"], MANAGER, {"limit": 2, "offset": 2}
        )
    )
    assert len(middle_rows) == 2
    assert middle_meta["limit"] == 2
    assert middle_meta["offset"] == 2
    assert middle_meta["total_count"] == 5
    assert middle_meta["has_more"] is True

    last_rows, last_meta = validate_paginated(
        api.list_department_temperature_logs(
            department["id"], MANAGER, {"limit": 2, "offset": 4}
        )
    )
    assert len(last_rows) == 1
    assert last_meta["total_count"] == 5
    assert last_meta["has_more"] is False

    # Every reading sat at 2.0 C, comfortably under the 4.4 C safe ceiling.
    for row in middle_rows + last_rows:
        assert_temperature_log(row)
        assert row["out_of_spec"] is False
        assert row["consecutive_index"] == 0


def test_retail_item_defaults_leave_it_unpriced(api):
    """A freshly seeded case item carries no price, no yield snapshot and no printed origin yet.

    "A new item is `UNPRICED` with `country_of_origin_label` `PENDING`, and
    `pricing_yield_pct_snapshot`, `yield_adjusted_cost_per_lb_cents`,
    `provisional_price_per_lb_cents`, `final_price_per_lb_cents`,
    `active_price_per_lb_cents`, `price_variance_pct` and `shelf_life_days` all
    sit at 0."

    Design: Corner/entities/retail_item_defaults_leave_it_unpriced
    """
    department = seeded_department(api)

    item = get_success_data(
        api.create_retail_item(retail_item_payload(department["id"]), MANAGER), 201
    )

    assert_retail_item(item)
    assert item["price_status"] == "UNPRICED"
    assert item["country_of_origin_label"] == "PENDING"
    assert item["provisional_price_per_lb_cents"] == 0
    assert item["final_price_per_lb_cents"] == 0
    assert item["active_price_per_lb_cents"] == 0
    assert item["price_variance_pct"] == pytest.approx(0.0, abs=0.0001)
    assert item["pricing_yield_pct_snapshot"] == pytest.approx(0.0, abs=0.0001)
    assert item["yield_adjusted_cost_per_lb_cents"] == pytest.approx(0.0, abs=0.0001)

    # Shelf life is stamped by the price proposal, not by catalogue seeding.
    assert item["shelf_life_days"] == 0

    # A WHOLE_MUSCLE item will take its measured basis off a cutting-test line.
    assert item["cost_basis_source"] == "CUT_TEST_LINE"


def test_retail_item_system_fields_are_server_generated(api):
    """The identifier, both stamps and the counter on a new case item all come from the server.

    "Every resource in this system carries a server-minted `id`: a UUID string
    with no type prefix of any kind."

    Design: Corner/entities/retail_item_system_fields_are_server_generated
    """
    department = seeded_department(api)

    item = get_success_data(
        api.create_retail_item(
            retail_item_payload(
                department["id"],
                item_code=TEST_DEFAULTS["GRD80_ITEM_CODE"],
                subprimal_code=TEST_DEFAULTS["GRD80_SUBPRIMAL_CODE"],
                product_class="GROUND",
            ),
            ADMIN,
        ),
        201,
    )

    assert is_valid_uuid(item["id"])
    assert item["id"] != TEST_DEFAULTS["GRD80_ITEM_CODE"]
    assert item["item_code"] == TEST_DEFAULTS["GRD80_ITEM_CODE"]
    assert item["version"] == 1

    # Both stamps are read off the logical clock, pinned at the fixture instant.
    assert_three_fractional_digits(item["created_at"])
    assert_three_fractional_digits(item["updated_at"])
    assert item["created_at"].startswith(FIXTURE_CLOCK[:-1])
    assert item["updated_at"] == item["created_at"]

    fetched = get_success_data(api.get_retail_item(item["id"], MANAGER), 200)
    assert fetched["id"] == item["id"]
    assert fetched["created_at"] == item["created_at"]
    assert fetched["version"] == item["version"]


def test_temperature_log_is_immutable_and_carries_no_version(api):
    """A case reading is a fact: a second reading appends a row rather than revising the first.

    "It has no `updated_at` and no `version`, because a reading is a fact that
    is never revised."

    Design: Corner/entities/temperature_log_is_immutable_and_carries_no_version
    """
    department = seeded_department(api)

    first = get_success_data(
        api.create_temperature_log(
            temperature_log_payload(department["id"], "CASE-A", 2.0), CLERK
        ),
        201,
    )
    second = get_success_data(
        api.create_temperature_log(
            temperature_log_payload(department["id"], "CASE-A", 3.0), CLERK
        ),
        201,
    )

    assert first["id"] != second["id"]
    for reading in (first, second):
        assert_reading_only_fields(reading)
        assert "updated_at" not in reading
        assert "version" not in reading

    # The earlier reading still reports the temperature it was taken at.
    unchanged = get_success_data(api.get_temperature_log(first["id"], CLERK), 200)
    assert unchanged["reading_c"] == pytest.approx(2.0, abs=0.01)
    assert_reading_only_fields(unchanged)

    rows, meta = validate_paginated(
        api.list_department_temperature_logs(
            department["id"], CLERK, {"case_code": "CASE-A"}
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2
    for row in rows:
        assert row["recorded_by_user_id"] == "clerk-01"
        assert row["taken_at"].startswith(FIXTURE_CLOCK[:-1])


def test_retail_item_read_with_unknown_id_returns_not_found(api):
    """Reading a case item that was never seeded is answered by the item's own not-found error.

    "Every identifier in the request path resolves, left to right — otherwise
    the matching not-found error (404)."

    Design: Corner/entities/retail_item_read_with_unknown_id_returns_not_found
    """
    seeded_department(api)

    response = api.get_retail_item(NON_EXISTENT_UUID, MANAGER)

    error = validate_error(response, "ERR_RETAIL_ITEM_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"
    assert error["message"].strip() != ""


def test_case_plan_line_creation_under_unknown_plan_returns_not_found(api):
    """A case line offered to a plan that does not exist fails on the path before its body is read.

    "When a request path carries an identifier, the server resolves it before
    doing anything else, and where a path carries several identifiers it
    resolves them strictly left to right, failing on the first one that does not
    exist."

    Design: Corner/entities/case_plan_line_creation_under_unknown_plan_returns_not_found
    """
    department = seeded_department(api)
    item = create_retail_item(api, department["id"])
    purchase = create_primal_purchase(api, department["id"])

    # The item is PROPOSED, so the body itself would have passed muster.
    proposed = propose_price(api, item["id"], purchase["id"])
    assert proposed["price_status"] == "PROPOSED"

    response = api.create_case_plan_line(
        NON_EXISTENT_UUID,
        case_plan_line_payload(item["id"], 1, 4, 30.0),
        MANAGER,
    )

    validate_error(response, "ERR_CASE_PLAN_NOT_FOUND", 404)

    rows, meta = validate_paginated(
        api.list_case_plan_lines(MANAGER, {"retail_item_id": item["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_grind_input_with_unknown_trim_lot_fk_returns_not_found(api):
    """Committing trim from a lot that does not exist is refused by the lot's own not-found error.

    "Every foreign-key identifier in the request body resolves — otherwise the
    matching not-found error (404)."

    Design: Corner/entities/grind_input_with_unknown_trim_lot_fk_returns_not_found
    """
    department = seeded_department(api)
    ground = create_ground_item(api, department["id"])
    run = create_grind_run(
        api,
        department["id"],
        ground["id"],
        "2026-08-06T06:00:00Z",
        "2026-08-06T07:00:00Z",
        declared_coo="USA",
        target_lean_pct=80.0,
    )

    response = api.create_grind_input(
        run["id"], grind_input_payload(NON_EXISTENT_UUID, 1, 5.0), CUTTER
    )

    validate_error(response, "ERR_TRIM_LOT_NOT_FOUND", 404)

    # Nothing was committed, so the blend is still empty and unlabelled.
    stored = read_grind_run(api, run["id"])
    assert stored["batch_weight_lb"] == pytest.approx(0.00, abs=0.01)
    assert stored["coo_label"] == "PENDING"
    assert stored["status"] == "SCHEDULED"

    rows, meta = validate_paginated(
        api.list_grind_inputs(CUTTER, {"grind_run_id": run["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_cutting_test_line_missing_market_value_is_invalid_request(api):
    """A yield line offered without its cost-allocation weight never reaches the bench.

    "Each line carries a `line_seq` between 1 and 40 that must be unique within
    the test and that pins the deterministic order in which cost is later
    allocated, a `subprimal_code` of 1 to 60 characters naming the cut or
    by-product, a `disposition` of `SALABLE_CUT`, `GRIND_TRIM` or
    `FAT_BONE_LOSS`, the `yield_weight_lb` read off the bench scale (at least
    0), and a `market_value_per_lb_cents` that serves as the cost-allocation
    weight."

    Design: Corner/entities/cutting_test_line_missing_market_value_is_invalid_request
    """
    department = seeded_department(api)
    purchase = create_primal_purchase(api, department["id"])
    test = create_cutting_test(
        api, purchase["id"], purchase["net_weight_lb"], purchase["version"]
    )

    response = api.create_cutting_test_line(
        test["id"],
        {
            "line_seq": 1,
            "subprimal_code": "RIBEYE_TRIM_LEAN",
            "disposition": "GRIND_TRIM",
            "yield_weight_lb": 12.0,
            "lean_pct": 78.0,
        },
        CUTTER,
    )

    validate_error(response, "ERR_INVALID_REQUEST", 400)

    # No line landed, so the bench still measures nothing.
    stored = read_cutting_test(api, test["id"])
    assert stored["status"] == "DRAFT"
    assert stored["total_yield_weight_lb"] == pytest.approx(0.00, abs=0.01)

    rows, meta = validate_paginated(
        api.list_cutting_test_lines(CUTTER, {"cutting_test_id": test["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_primal_purchase_rejects_unknown_country_of_origin_enum(api):
    """A primal declaring an origin outside the four permitted countries is never received.

    "Every primal purchase declares a `country_of_origin` drawn from `USA`,
    `CAN`, `MEX` or `AUS`, and that declaration flows to every cut and every
    trim lot derived from the primal."

    Design: Corner/entities/primal_purchase_rejects_unknown_country_of_origin_enum
    """
    department = seeded_department(api)

    response = api.create_primal_purchase(
        primal_purchase_payload(department["id"], country_of_origin="BRA"), CUTTER
    )

    validate_error(response, "ERR_INVALID_REQUEST", 400)

    rows, meta = validate_paginated(
        api.list_department_primal_purchases(department["id"], CUTTER)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_grind_run_window_end_not_after_start_is_invalid_request(api):
    """A zero-length grinder window fails the schema range check before any overlap is considered.

    "A run names its `department_id`, the `target_retail_item_id` it produces —
    which must be a `GROUND` item of the same department — the segregation block
    `declared_coo`, the occupation window `scheduled_start_at` and
    `scheduled_end_at` where the end must fall strictly after the start, and the
    `target_lean_pct` the finished blend must hit, between 60.0 and 95.0 with
    one decimal place."

    Design: Corner/entities/grind_run_window_end_not_after_start_is_invalid_request
    """
    department = seeded_department(api)
    ground = create_ground_item(api, department["id"])

    response = api.create_grind_run(
        grind_run_payload(
            department["id"],
            ground["id"],
            "2026-08-06T07:00:00Z",
            "2026-08-06T07:00:00Z",
            declared_coo="USA",
            target_lean_pct=80.0,
        ),
        CUTTER,
    )

    validate_error(response, "ERR_INVALID_REQUEST", 400)

    rows, meta = validate_paginated(
        api.list_grind_runs(CUTTER, {"department_id": department["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_trim_lot_requires_exactly_one_source_reference(api):
    """Grind trim must name either the bench line it came off or the parent lot being re-worked.

    "Exactly one of two sources must be named: `cutting_test_line_id`, pointing
    at the `GRIND_TRIM` line the trim came off, or `source_trim_lot_id`,
    pointing at the parent lot being re-worked."

    Design: Corner/entities/trim_lot_requires_exactly_one_source_reference
    """
    ctx = received_primal(api)
    department_id = ctx["department"]["id"]
    purchase = ctx["purchase"]

    test = create_cutting_test(
        api, purchase["id"], purchase["net_weight_lb"], purchase["version"]
    )
    add_cutting_test_line(
        api,
        test["id"],
        1,
        "RIBEYE_STEAK",
        "SALABLE_CUT",
        62.0,
        1450,
        retail_item_id=ctx["whole_muscle_item"]["id"],
    )
    lean_trim = add_cutting_test_line(
        api, test["id"], 2, "RIBEYE_TRIM_LEAN", "GRIND_TRIM", 12.0, 420, lean_pct=78.0
    )
    add_cutting_test_line(
        api,
        test["id"],
        3,
        "RIBEYE_TRIM_EXTRA_LEAN",
        "GRIND_TRIM",
        6.5,
        520,
        lean_pct=92.0,
    )
    add_cutting_test_line(
        api, test["id"], 4, "RIBEYE_FAT_BONE", "FAT_BONE_LOSS", 18.0, 0
    )
    submit_cutting_test(api, test["id"])
    approve_cutting_test(api, test["id"])

    harvested = create_trim_lot_from_line(
        api, department_id, "TL-A78", 12.0, lean_trim["id"], pack_date=FIXTURE_DATE
    )

    neither = api.create_trim_lot(
        trim_lot_payload(department_id, "TL-NONE", 4.0, FIXTURE_DATE), CUTTER
    )
    validate_error(neither, "ERR_INVALID_REQUEST", 400)

    both = api.create_trim_lot(
        trim_lot_payload(
            department_id,
            "TL-BOTH",
            4.0,
            FIXTURE_DATE,
            cutting_test_line_id=lean_trim["id"],
            source_trim_lot_id=harvested["id"],
        ),
        CUTTER,
    )
    validate_error(both, "ERR_INVALID_REQUEST", 400)

    rows, meta = validate_paginated(
        api.list_trim_lots(CUTTER, {"department_id": department_id})
    )
    assert meta["total_count"] == 1
    assert [row["lot_code"] for row in rows] == ["TL-A78"]

    # The one legitimate lot is untouched and carries what it inherited.
    stored = read_trim_lot(api, harvested["id"])
    assert_trim_lot(stored)
    assert stored["status"] == "AVAILABLE"
    assert stored["remaining_lb"] == pytest.approx(12.00, abs=0.01)
    assert stored["rework_generation"] == 0
    assert stored["country_of_origin"] == "USA"
    assert stored["lean_pct"] == pytest.approx(78.0, abs=0.01)


def test_unknown_path_ids_return_the_entity_specific_not_found_error(api):
    """Each well-formed but unminted identifier is answered by the error its own entity owns.

    "The 404 error names the entity that failed to resolve:
    `ERR_DEPARTMENT_NOT_FOUND`, `ERR_PRIMAL_PURCHASE_NOT_FOUND`,
    `ERR_CUTTING_TEST_NOT_FOUND`, `ERR_CUTTING_TEST_LINE_NOT_FOUND`,
    `ERR_RETAIL_ITEM_NOT_FOUND`, `ERR_CASE_PLAN_NOT_FOUND`,
    `ERR_CASE_PLAN_LINE_NOT_FOUND`, `ERR_TRIM_LOT_NOT_FOUND`,
    `ERR_GRIND_RUN_NOT_FOUND`, `ERR_GRIND_INPUT_NOT_FOUND`,
    `ERR_TEMPERATURE_LOG_NOT_FOUND`, `ERR_CASE_FAILURE_NOT_FOUND`,
    `ERR_PRE_ORDER_NOT_FOUND` and `ERR_SHRINK_RECONCILIATION_NOT_FOUND`."

    Design: Corner/entities/unknown_path_ids_return_the_entity_specific_not_found_error
    """
    department = create_department(api)

    probes = [
        (
            api.get_department("00000000-0000-4000-8000-000000000001", ADMIN),
            "ERR_DEPARTMENT_NOT_FOUND",
        ),
        (
            api.get_primal_purchase("00000000-0000-4000-8000-000000000002", CUTTER),
            "ERR_PRIMAL_PURCHASE_NOT_FOUND",
        ),
        (
            api.get_cutting_test("00000000-0000-4000-8000-000000000003", CUTTER),
            "ERR_CUTTING_TEST_NOT_FOUND",
        ),
        (
            api.get_cutting_test_line("00000000-0000-4000-8000-000000000004", ANALYST),
            "ERR_CUTTING_TEST_LINE_NOT_FOUND",
        ),
        (
            api.get_case_plan_line("00000000-0000-4000-8000-000000000005", MANAGER),
            "ERR_CASE_PLAN_LINE_NOT_FOUND",
        ),
        (
            api.get_grind_run("00000000-0000-4000-8000-000000000006", CUTTER),
            "ERR_GRIND_RUN_NOT_FOUND",
        ),
        (
            api.get_grind_input("00000000-0000-4000-8000-000000000007", CUTTER),
            "ERR_GRIND_INPUT_NOT_FOUND",
        ),
        (
            api.get_temperature_log("00000000-0000-4000-8000-000000000008", CLERK),
            "ERR_TEMPERATURE_LOG_NOT_FOUND",
        ),
        (
            api.get_case_failure("00000000-0000-4000-8000-000000000009", MANAGER),
            "ERR_CASE_FAILURE_NOT_FOUND",
        ),
        (
            api.get_pre_order("00000000-0000-4000-8000-00000000000a", CLERK),
            "ERR_PRE_ORDER_NOT_FOUND",
        ),
        (
            api.get_shrink_reconciliation(
                "00000000-0000-4000-8000-00000000000b", ANALYST
            ),
            "ERR_SHRINK_RECONCILIATION_NOT_FOUND",
        ),
    ]

    for response, error_id in probes:
        error = validate_error(response, error_id, 404)
        assert response.json()["response_type"] == "error"
        assert error["message"].strip() != ""

    # The department that does exist is untouched by any of those probes.
    stored = get_success_data(api.get_department(department["id"], ADMIN), 200)
    assert stored["id"] == department["id"]
    assert stored["version"] == department["version"]


def test_unknown_parent_id_on_a_sub_resource_listing_is_not_found(api):
    """A listing under a parent that does not exist is a 404, while a childless parent is an empty page.

    "When a request path carries an identifier, the server resolves it before
    doing anything else, and where a path carries several identifiers it
    resolves them strictly left to right, failing on the first one that does not
    exist."

    Design: Corner/entities/unknown_parent_id_on_a_sub_resource_listing_is_not_found
    """
    department = seeded_department(api)
    purchase = create_primal_purchase(api, department["id"])

    validate_error(
        api.list_department_case_plans(
            "00000000-0000-4000-8000-0000000000c1", MANAGER, {"limit": 10, "offset": 0}
        ),
        "ERR_DEPARTMENT_NOT_FOUND",
        404,
    )
    validate_error(
        api.list_purchase_cutting_tests(
            "00000000-0000-4000-8000-0000000000c2", CUTTER, {"limit": 10, "offset": 0}
        ),
        "ERR_PRIMAL_PURCHASE_NOT_FOUND",
        404,
    )

    # The real department plans nothing yet, which is an empty page and not a 404.
    plan_rows, plan_meta = validate_paginated(
        api.list_department_case_plans(
            department["id"], MANAGER, {"limit": 10, "offset": 0}
        )
    )
    assert plan_rows == []
    assert plan_meta["total_count"] == 0
    assert plan_meta["has_more"] is False

    # The real purchase has had no bench work opened against it yet.
    test_rows, test_meta = validate_paginated(
        api.list_purchase_cutting_tests(
            purchase["id"], CUTTER, {"limit": 10, "offset": 0}
        )
    )
    assert test_rows == []
    assert test_meta["total_count"] == 0
