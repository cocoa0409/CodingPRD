"""Cross-entity state gates: FIRM issue gated by design release; spare
allocation gated by the tool's production state (PRD §3.3, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_quote,
    create_customer,
    create_design,
    create_quote,
    create_spare,
    drive_job_to_ready_to_ship,
    get_success_data,
    setup_booked_job,
    submit_design,
    deliver_tool,
    ship_tool,
    validate_error,
    validate_success,
)

ESTIMATOR = TEST_USERS["estimator_headers"]
PM = TEST_USERS["project_manager_headers"]


def _setup_submitted_design_with_two_quotes():
    """Design held in SUBMITTED (never reviewed) with one FIRM and one
    BUDGETARY quote against it."""
    customer = create_customer(company_name="Gate Co")
    design = create_design(customer["id"], part_number="PN-1002")
    design = submit_design(design["id"], customer["id"])
    assert design["status"] == "SUBMITTED"
    q_firm = create_quote(customer["id"], design["id"], quote_kind="FIRM",
                          requested_lead_weeks=12)
    q_budgetary = create_quote(customer["id"], design["id"], quote_kind="BUDGETARY",
                               requested_lead_weeks=12)
    return customer, design, q_firm, q_budgetary


def test_firm_issue_rejected_while_design_not_released(api):
    """PRD §3.3: "A `FIRM` quote may only be issued against a `RELEASED`
    design — otherwise `ERR_DESIGN_NOT_RELEASED`; a `BUDGETARY` quote may be
    issued while the design is `SUBMITTED` or `RELEASED`."

    Design: Difficulty/cross_entity_state_dependency/firm_quote_issue_gated_by_design_release
    """
    _, design, q_firm, _ = _setup_submitted_design_with_two_quotes()

    res = api_client.issue_quote(q_firm["id"], ESTIMATOR)
    error = validate_error(res, ApiErrorId.ERR_DESIGN_NOT_RELEASED)
    assert error["error_id"] == "ERR_DESIGN_NOT_RELEASED"
    assert res.status_code == 409

    quote = get_success_data(api_client.get_quote(q_firm["id"], ESTIMATOR))
    assert quote["status"] == "DRAFT", (
        f"a rejected issue must not move the quote, got {quote['status']}"
    )
    assert design["status"] == "SUBMITTED"


def test_budgetary_issue_succeeds_on_submitted_design_with_14_day_validity(api):
    """PRD §3.3: "A `FIRM` quote may only be issued against a `RELEASED`
    design — otherwise `ERR_DESIGN_NOT_RELEASED`; a `BUDGETARY` quote may be
    issued while the design is `SUBMITTED` or `RELEASED`."
    PRD §3.3: "Issuance stamps `issued_at` from the logical clock and computes
    `valid_until` as fourteen days after issuance for `BUDGETARY` quotes and
    thirty days for `FIRM` quotes (both remain null while the quote is in
    `DRAFT`)."
    PRD §2.4: "Before any operator sets it, the logical clock starts at
    exactly 2026-08-01T00:00:00Z."

    Design: Difficulty/cross_entity_state_dependency/firm_quote_issue_gated_by_design_release
    """
    _, _, _, q_budgetary = _setup_submitted_design_with_two_quotes()

    issued = validate_success(api_client.issue_quote(q_budgetary["id"], ESTIMATOR), 200)
    assert_quote(issued)
    assert issued["status"] == "ISSUED"
    # Datetime comparisons resolve to the second (PRD §2.4).
    assert issued["issued_at"].startswith("2026-08-01T00:00:00"), (
        f"issued_at must stamp the logical clock, got {issued['issued_at']}"
    )
    assert issued["valid_until"].startswith("2026-08-15T00:00:00"), (
        f"BUDGETARY validity is issued_at + 14 days, got {issued['valid_until']}"
    )


def test_spare_allocate_rejected_while_tool_in_build(api):
    """PRD §3.9: "Allocating inserts to the customer — a sale against stock —
    takes a `quantity` and is gated by production: the tool must be
    `IN_PRODUCTION` (`ERR_TOOL_NOT_IN_PRODUCTION`), and a `DISCONTINUED` SKU
    refuses with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/spare_allocate_gated_by_tool_production_state
    """
    ctx = setup_booked_job(company_name="Spare Co", part_number="PN-1003")
    spare = create_spare(ctx["tool"]["id"], initial_on_hand=5, reorder_point=2)
    assert ctx["tool"]["physical_status"] == "IN_BUILD"

    res = api_client.allocate_spare_insert(spare["id"], {"quantity": 1}, PM)
    error = validate_error(res, ApiErrorId.ERR_TOOL_NOT_IN_PRODUCTION)
    assert error["error_id"] == "ERR_TOOL_NOT_IN_PRODUCTION"
    assert res.status_code == 409

    unchanged = get_success_data(api_client.get_spare_insert(spare["id"], PM))
    assert unchanged["on_hand"] == 5, (
        f"a rejected allocation must not decrement stock, got {unchanged['on_hand']}"
    )


def test_spare_allocate_succeeds_once_tool_in_production(api):
    """PRD §3.9: "Allocating inserts to the customer — a sale against stock —
    takes a `quantity` and is gated by production: the tool must be
    `IN_PRODUCTION` (`ERR_TOOL_NOT_IN_PRODUCTION`), and a `DISCONTINUED` SKU
    refuses with `ERR_INVALID_STATE`."
    PRD §3.9: "The reorder flag is a derived boundary-inclusive test:
    `reorder_needed` is true whenever `on_hand` is less than or equal to
    `reorder_point`."

    Design: Difficulty/cross_entity_state_dependency/spare_allocate_gated_by_tool_production_state
    """
    ctx = setup_booked_job(company_name="Spare Co", part_number="PN-1003")
    spare = create_spare(ctx["tool"]["id"], initial_on_hand=5, reorder_point=2)
    # Drive the job all the way to delivery so the tool reaches IN_PRODUCTION.
    drive_job_to_ready_to_ship(ctx)
    ship_tool(ctx["tool"]["id"], tracking_number="TRK-S1")
    deliver_tool(ctx["tool"]["id"])

    tool = get_success_data(api_client.get_tool_asset(ctx["tool"]["id"], PM))
    assert tool["physical_status"] == "IN_PRODUCTION"

    updated = validate_success(
        api_client.allocate_spare_insert(spare["id"], {"quantity": 1}, PM), 200
    )
    assert updated["on_hand"] == 4, (
        f"allocation must decrement stock 5 -> 4, got {updated['on_hand']}"
    )
    assert updated["reorder_needed"] is False  # 4 > reorder_point 2
    assert updated["status"] == "ACTIVE"
