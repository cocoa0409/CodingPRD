"""Two meat departments in the same chain: codes that repeat harmlessly across
them, and references that must never cross the boundary between them.

Every test starts against an empty database with the logical clock at its
initial instant, and builds the state it needs through the public endpoints.
"""

import pytest

from test_helpers import (
    CLERK,
    DEPARTMENT_DEFAULTS,
    FIXTURE_DATE,
    MANAGER,
    TEST_DEFAULTS,
    case_plan_line_payload,
    case_plan_payload,
    create_case_plan,
    create_department,
    create_primal_purchase,
    create_retail_item,
    expected_shelf_price_cents,
    get_success_data,
    pre_order_payload,
    propose_price,
    read_case_plan,
    read_retail_item,
    retail_item_payload,
    seeded_department,
    validate_error,
    validate_paginated,
)


def test_scoped_uniqueness_is_enforced_per_department(api):
    """An item code or a service date already taken in one department is still free in the other.

    "The scoped keys are `store_code` across all departments, `item_code` per
    department, `lot_code` per department, `service_date` per department, a
    cutting-test line's `line_seq` per test, a case-plan line's `line_seq` per
    plan, and a grind input's `input_seq` and `trim_lot_id` each per run."

    Design: Corner/validations/scoped_uniqueness_is_enforced_per_department
    """
    first = seeded_department(api)
    second = create_department(
        api,
        name=TEST_DEFAULTS["SECOND_DEPARTMENT_NAME"],
        store_code=TEST_DEFAULTS["SECOND_STORE_CODE"],
    )

    original_item = create_retail_item(api, first["id"])
    create_case_plan(api, first["id"], FIXTURE_DATE)

    # RIB01 is already taken inside the first department.
    duplicate_item = api.create_retail_item(
        retail_item_payload(first["id"], subprimal_code="RIBEYE_STEAK_THIN"), MANAGER
    )
    validate_error(duplicate_item, "ERR_DUPLICATE_RESOURCE", 409)

    # The same code in the second department is a different shelf tag entirely.
    twin_item = get_success_data(
        api.create_retail_item(retail_item_payload(second["id"]), MANAGER), 201
    )
    assert twin_item["item_code"] == original_item["item_code"]
    assert twin_item["department_id"] == second["id"]
    assert twin_item["id"] != original_item["id"]
    assert twin_item["price_status"] == "UNPRICED"

    # The refused create left the incumbent item exactly as it was.
    stored_item = read_retail_item(api, original_item["id"])
    assert stored_item["subprimal_code"] == original_item["subprimal_code"]
    assert stored_item["version"] == original_item["version"]

    # A second plan for the same service date in the same department collides.
    duplicate_plan = api.create_case_plan(
        case_plan_payload(first["id"], FIXTURE_DATE), MANAGER
    )
    validate_error(duplicate_plan, "ERR_DUPLICATE_RESOURCE", 409)

    plan_rows, plan_meta = validate_paginated(
        api.list_department_case_plans(first["id"], MANAGER)
    )
    assert plan_meta["total_count"] == 1
    assert plan_rows[0]["service_date"] == FIXTURE_DATE

    # And the same service date is still available to the second department.
    twin_plan = get_success_data(
        api.create_case_plan(case_plan_payload(second["id"], FIXTURE_DATE), MANAGER), 201
    )
    assert twin_plan["department_id"] == second["id"]
    assert twin_plan["service_date"] == FIXTURE_DATE


def test_references_across_departments_are_rejected(api):
    """A priced item from a neighbouring department may be neither planned nor pre-ordered here.

    "The item must belong to the plan's department, or the line is refused with
    `ERR_DEPARTMENT_MISMATCH`, and its `price_status` must be `PROPOSED` or
    `PRICED` — an `UNPRICED` or `SUSPENDED` item is refused with
    `ERR_ITEM_NOT_PRICED`."

    Design: Corner/validations/references_across_departments_are_rejected
    """
    first = seeded_department(api)
    second = create_department(
        api,
        name=TEST_DEFAULTS["SECOND_DEPARTMENT_NAME"],
        store_code=TEST_DEFAULTS["SECOND_STORE_CODE"],
    )

    foreign_item = create_retail_item(api, second["id"], item_code="RIB02")
    foreign_purchase = create_primal_purchase(api, second["id"])
    proposed = propose_price(api, foreign_item["id"], foreign_purchase["id"])

    # The item is priced, so only its department can be the reason for a refusal.
    # Basis 86000/98.5 over the 0.62 WHOLE_MUSCLE yield assumption is 1375.4708.
    assert proposed["price_status"] == "PROPOSED"
    assert proposed["provisional_price_per_lb_cents"] == expected_shelf_price_cents(
        1375.4708, DEPARTMENT_DEFAULTS["target_margin_pct"]
    )
    assert proposed["provisional_price_per_lb_cents"] == 2149

    local_plan = create_case_plan(api, first["id"], FIXTURE_DATE)

    crossed_line = api.create_case_plan_line(
        local_plan["id"], case_plan_line_payload(foreign_item["id"], 1, 4, 30.0), MANAGER
    )
    validate_error(crossed_line, "ERR_DEPARTMENT_MISMATCH", 422)

    stored_plan = read_case_plan(api, local_plan["id"])
    assert stored_plan["plan_status"] == "DRAFT"
    assert stored_plan["total_required_fill_lb"] == pytest.approx(0.00, abs=0.01)

    line_rows, line_meta = validate_paginated(
        api.list_case_plan_lines(MANAGER, {"case_plan_id": local_plan["id"]})
    )
    assert line_meta["total_count"] == 0
    assert line_rows == []

    crossed_order = api.create_pre_order(
        pre_order_payload(
            first["id"],
            foreign_item["id"],
            5.0,
            "2026-08-05T14:00:00Z",
            "2026-08-05T15:00:00Z",
        ),
        CLERK,
    )
    validate_error(crossed_order, "ERR_DEPARTMENT_MISMATCH", 422)

    order_rows, order_meta = validate_paginated(
        api.list_pre_orders(CLERK, {"department_id": first["id"]})
    )
    assert order_meta["total_count"] == 0
    assert order_rows == []
