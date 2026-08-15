"""Access control and cross-reference reachability: authentication,
endpoint authorization, and filtered child collections."""
from test_helpers import (
    DESIGN,
    LAB_SLOT_A,
    NO_AUTH_HEADERS,
    PLANT,
    QUALITY,
    ApiErrorId,
    activate_program,
    begin_validation,
    create_approved_spec,
    create_customer,
    create_inventory_program,
    create_locked_cnc_program,
    create_material,
    create_quoted_order,
    create_release,
    create_spec,
    get_drop_test,
    schedule_drop_test,
    submit_spec,
    validate_error,
    validate_paginated,
)


def test_request_missing_auth_headers_returns_401(api):
    """PRD §2.5: "The `X-User-ID` and `X-User-Role` headers must be present
    and the role recognized — otherwise `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/request_missing_auth_headers_returns_401
    """
    resp = api.list_package_specs(NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_design_engineer_cannot_record_drop_test(api):
    """PRD §2.1: "A request whose role is recognized but not permitted on the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." PRD §2.1:
    "A `QualityEngineer` owns validation: drop tests, specification
    validation transitions, and quality holds."

    Design: Corner/rbac/design_engineer_cannot_record_drop_test
    """
    customer = create_customer()
    material = create_material()
    spec = create_spec(customer["id"], material["id"])
    submit_spec(spec["id"])
    begin_validation(spec["id"])
    drop_test = schedule_drop_test(spec["id"], *LAB_SLOT_A)

    resp = api.record_drop_test(drop_test["id"], 55, DESIGN)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert get_drop_test(drop_test["id"])["status"] == "SCHEDULED"


def test_fk_reverse_reachability_lists(api):
    """PRD §2.3: "Cut programs filter by `package_spec_id`,
    `supersedes_cut_program_id`, `status`, or `method`. Toolings filter by
    `cut_program_id` or `status`. Drop tests filter by `package_spec_id` or
    `result`. Production orders filter by `package_spec_id`,
    `cut_program_id`, `inventory_program_id`, or `fab_status`. Inventory
    programs filter by `customer_id`, `package_spec_id`, or `status`. Release
    orders filter by `inventory_program_id` or `status`. Scrap batches filter
    by `production_order_id` or `status`."

    Design: Corner/endpoints/fk_reverse_reachability_lists
    """
    customer, _m, spec = create_approved_spec()
    program = create_locked_cnc_program(spec["id"])
    order = create_quoted_order(spec["id"], program["id"], 100)
    inv_program = create_inventory_program(customer["id"], spec["id"],
                                           max_stock_qty=500,
                                           reorder_point_qty=100,
                                           min_release_qty=50)
    activate_program(inv_program["id"])
    release = create_release(inv_program["id"], 50, customer["id"])

    programs, meta = validate_paginated(
        api.list_cut_programs(DESIGN, params={"package_spec_id": spec["id"]})
    )
    assert meta["total_count"] == 1
    assert programs[0]["id"] == program["id"]

    tests, meta = validate_paginated(
        api.list_drop_tests(QUALITY, params={"package_spec_id": spec["id"]})
    )
    assert meta["total_count"] == 1, "the validation drop test is reachable"
    dt_id = tests[0]["id"]
    fetched = get_drop_test(dt_id)
    assert fetched["package_spec_id"] == spec["id"]

    orders, meta = validate_paginated(
        api.list_production_orders(PLANT, params={"cut_program_id": program["id"]})
    )
    assert meta["total_count"] == 1
    assert orders[0]["id"] == order["id"]

    releases, meta = validate_paginated(
        api.list_release_orders(PLANT, params={"inventory_program_id": inv_program["id"]})
    )
    assert meta["total_count"] == 1
    assert releases[0]["id"] == release["id"]
