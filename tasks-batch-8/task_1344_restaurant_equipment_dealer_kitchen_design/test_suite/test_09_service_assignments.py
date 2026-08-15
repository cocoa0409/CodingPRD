"""ServiceAgency capacity ceiling and transfer conservation invariant."""
from test_helpers import (
    TEST_USERS,
    create_service_agency,
    get_success_data,
    setup_commissioned_project,
    validate_error,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]
SM = TEST_USERS["service_manager_headers"]


def test_service_agency_capacity_inclusive_ceiling(api):
    """PRD §3.7: "the target agency, named by `target_agency_id`, to be
    `ACTIVE` with `open_assignment_count` below `capacity`
    (`ERR_AGENCY_AT_CAPACITY`, HTTP 402)." and "Eligibility requires ... the
    agency's `open_assignment_count` to be strictly below its `capacity`."

    Design: Difficulty/resource_temporal_overlap/service_agency_capacity_inclusive_ceiling
    """
    # A1 is created first and wins the auto-selection tie-break (oldest).
    customer, project, layout, items, quote = _setup_to_presented(api)
    a1 = create_service_agency(
        agency_name="A1 Full", covered_jurisdictions=["CITY_HEALTH"], capacity=1
    )
    a2 = create_service_agency(
        agency_name="A2 Free", covered_jurisdictions=["CITY_HEALTH"], capacity=5
    )
    _drive_to_commissioned(api, customer, project, items)

    assignments = get_success_data(api.list_service_assignments(project["id"], SM))
    asgn = assignments[0]
    assert asgn["agency_id"] == a1["id"]

    # A1 is now at capacity 1/1: transfer back to A1 must be rejected.
    res = api.transfer_service_assignment(project["id"], asgn["id"], a1["id"], SM)
    validate_error(res, "ERR_AGENCY_AT_CAPACITY", expected_status=402)


def test_service_agency_below_capacity_accepts_transfer(api):
    """PRD §3.7: "Transfer requires the assignment to be `OPEN`
    (`ERR_ASSIGNMENT_NOT_OPEN` applies to both close and transfer) and the
    target agency, named by `target_agency_id`, to be `ACTIVE` with
    `open_assignment_count` below `capacity` (`ERR_AGENCY_AT_CAPACITY`,
    HTTP 402)."

    Design: Difficulty/resource_temporal_overlap/service_agency_capacity_inclusive_ceiling
    """
    customer, project, layout, items, quote = _setup_to_presented(api)
    a1 = create_service_agency(
        agency_name="A1 Full", covered_jurisdictions=["CITY_HEALTH"], capacity=1
    )
    a2 = create_service_agency(
        agency_name="A2 Free", covered_jurisdictions=["CITY_HEALTH"], capacity=5
    )
    _drive_to_commissioned(api, customer, project, items)

    asgn = get_success_data(api.list_service_assignments(project["id"], SM))[0]
    # A2 has headroom (0 < 5): transfer succeeds.
    transferred = validate_success(
        api.transfer_service_assignment(project["id"], asgn["id"], a2["id"], SM), 200
    )
    assert transferred["status"] == "TRANSFERRED"


def test_agency_transfer_conserves_total_open_assignments(api):
    """PRD §3.7: "A transfer moves the original assignment to `TRANSFERRED`,
    decrements the original agency's count, creates a new assignment in `OPEN`
    referencing the target agency, and increments the target agency's count."

    Design: Difficulty/compensating_invariant/agency_transfer_conserves_total_open_assignments
    """
    customer, project, layout, items, quote = _setup_to_presented(api)
    ag_a = create_service_agency(
        agency_name="A-First", covered_jurisdictions=["CITY_HEALTH"], capacity=5
    )
    ag_b = create_service_agency(
        agency_name="B-Second", covered_jurisdictions=["CITY_HEALTH"], capacity=5
    )
    _drive_to_commissioned(api, customer, project, items)

    asgn = get_success_data(api.list_service_assignments(project["id"], SM))[0]
    assert asgn["agency_id"] == ag_a["id"]

    validate_success(
        api.transfer_service_assignment(project["id"], asgn["id"], ag_b["id"], SM),
        200,
    )

    a_after = get_success_data(api.get_service_agency(ag_a["id"], SM))
    b_after = get_success_data(api.get_service_agency(ag_b["id"], SM))
    assert a_after["open_assignment_count"] == 0
    assert b_after["open_assignment_count"] == 1
    assert (
        a_after["open_assignment_count"] + b_after["open_assignment_count"] == 1
    ), "total open assignments across agencies must be conserved by transfer"


def test_agency_transfer_creates_new_open_assignment(api):
    """PRD §3.7: "A transfer moves the original assignment to `TRANSFERRED`,
    decrements the original agency's count, creates a new assignment in `OPEN`
    referencing the target agency, and increments the target agency's count."

    Design: Difficulty/compensating_invariant/agency_transfer_conserves_total_open_assignments
    """
    customer, project, layout, items, quote = _setup_to_presented(api)
    ag_a = create_service_agency(
        agency_name="A-First", covered_jurisdictions=["CITY_HEALTH"], capacity=5
    )
    ag_b = create_service_agency(
        agency_name="B-Second", covered_jurisdictions=["CITY_HEALTH"], capacity=5
    )
    _drive_to_commissioned(api, customer, project, items)

    asgn = get_success_data(api.list_service_assignments(project["id"], SM))[0]
    validate_success(
        api.transfer_service_assignment(project["id"], asgn["id"], ag_b["id"], SM),
        200,
    )

    assignments = get_success_data(api.list_service_assignments(project["id"], SM))
    assert len(assignments) == 2
    by_status = {}
    for a in assignments:
        by_status.setdefault(a["status"], []).append(a)
    assert len(by_status["TRANSFERRED"]) == 1
    assert by_status["TRANSFERRED"][0]["agency_id"] == ag_a["id"]
    assert len(by_status["OPEN"]) == 1
    assert by_status["OPEN"][0]["agency_id"] == ag_b["id"]


# ---------------------------------------------------------------------------
# Local composite helpers (kept test-local; shared tiers live in fixtures.py)
# ---------------------------------------------------------------------------

def _setup_to_presented(api):
    """Customer + Project + APPROVED one-item layout + presented quote."""
    from test_helpers import setup_quote_presented

    return setup_quote_presented(
        item_overrides_list=[
            {"model_no": "OVEN", "quantity": 1, "unit_price_cents": 100_000,
             "lead_time_days": 5}
        ]
    )


def _drive_to_commissioned(api, customer, project, items):
    """Accept the presented quote, deliver, and complete startup so the
    project reaches COMMISSIONED and the auto-assignment opens."""
    from test_helpers import (
        accept_quote_flow,
        commission_project,
        deliver_project,
        setup_quote_accepted,
    )

    quote_list = get_success_data(api.list_quotes(project["id"], TEST_USERS["sales_rep_headers"]))
    quote = quote_list[0]
    accept_quote_flow(project, quote, customer)
    deliver_project(project)
    commission_project(project, items)
