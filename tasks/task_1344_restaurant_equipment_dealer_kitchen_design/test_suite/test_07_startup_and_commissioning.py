"""Startup sessions: demo-minutes boundary and the depth-3 commissioning
cascade into the service-agency handoff."""
from test_helpers import (
    TEST_USERS,
    create_service_agency,
    create_startup_session_payload,
    get_success_data,
    setup_delivered_project,
    setup_quote_accepted,
    deliver_project,
    validate_error,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]
SM = TEST_USERS["service_manager_headers"]
ST = TEST_USERS["startup_technician_headers"]


def test_startup_complete_cascade_depth3(api):
    """PRD §3.7: "Completion fires a three-level cascade. The session moves to
    `COMPLETE` and its `warranty_registered` flips true. The linked item moves
    from `INSTALLED` to `STARTED`, its `warranty_status` flips from
    `UNREGISTERED` to `REGISTERED`, and the project's
    `warranty_registered_count` increments by 1. And when every non-cancelled
    equipment item on the project has reached `STARTED` with a `REGISTERED`
    warranty, the project bubbles from `DELIVERED` to `COMMISSIONED` — which
    in turn triggers the service-agency handoff below."

    Design: Difficulty/transitive_cascade/startup_complete_cascade_depth3
    """
    customer, project, layout, items, quote, job = setup_delivered_project(
        item_overrides_list=[
            {"model_no": "RANGE", "quantity": 1, "unit_price_cents": 1_000_000,
             "lead_time_days": 7}
        ]
    )
    agency = create_service_agency(
        agency_name="A1 Service", covered_jurisdictions=["CITY_HEALTH"], capacity=5
    )

    session = get_success_data(
        api.create_startup_session(
            project["id"],
            create_startup_session_payload(items[0]["id"], demo_minutes=30),
            ST,
        )
    )
    completed = validate_success(
        api.complete_startup_session(project["id"], session["id"], ST), 200
    )
    assert completed["status"] == "COMPLETE"
    assert completed["warranty_registered"] is True

    item_after = get_success_data(
        api.get_equipment_item(project["id"], items[0]["id"], PM)
    )
    assert item_after["status"] == "STARTED"
    assert item_after["warranty_status"] == "REGISTERED"

    project_after = get_success_data(api.get_project(project["id"], PM))
    assert project_after["status"] == "COMMISSIONED"
    assert project_after["warranty_registered_count"] == 1

    agency_after = get_success_data(api.get_service_agency(agency["id"], SM))
    assert agency_after["open_assignment_count"] == 1


def test_startup_complete_auto_opens_assignment(api):
    """PRD §3.7: "The moment a project reaches `COMMISSIONED`, the system
    selects a warranty service agency automatically." and "The winner gains a
    new `ServiceAssignment` in `OPEN` stamped with `opened_at`, and its
    `open_assignment_count` increments by 1."

    Design: Difficulty/transitive_cascade/startup_complete_cascade_depth3
    """
    customer, project, layout, items, quote, job = setup_delivered_project()
    agency = create_service_agency(
        agency_name="Solo", covered_jurisdictions=["CITY_HEALTH"], capacity=5
    )
    session = get_success_data(
        api.create_startup_session(
            project["id"],
            create_startup_session_payload(items[0]["id"], demo_minutes=30),
            ST,
        )
    )
    get_success_data(api.complete_startup_session(project["id"], session["id"], ST))

    assignments = get_success_data(
        api.list_service_assignments(project["id"], SM)
    )
    assert len(assignments) == 1
    assert assignments[0]["status"] == "OPEN"
    assert assignments[0]["agency_id"] == agency["id"]


def test_startup_demo_minutes_minimum_inclusive(api):
    """PRD §3.7: "`demo_minutes` must be at least 15 — a shorter demo does not
    count and fails with `ERR_DEMO_TOO_SHORT`."

    Design: Difficulty/boundary_precision_check/startup_demo_minutes_minimum_inclusive
    """
    customer, project, layout, items, quote, job = setup_delivered_project(
        item_overrides_list=[
            {"model_no": "RANGE", "quantity": 1, "unit_price_cents": 100_000,
             "lead_time_days": 7}
        ]
    )
    # No agency: bubble-up defers with no error, session still completes.
    session = get_success_data(
        api.create_startup_session(
            project["id"],
            create_startup_session_payload(items[0]["id"], demo_minutes=15),
            ST,
        )
    )
    completed = validate_success(
        api.complete_startup_session(project["id"], session["id"], ST), 200
    )
    assert completed["status"] == "COMPLETE"


def test_startup_demo_minutes_14_rejected(api):
    """PRD §3.7: "the linked item must be `INSTALLED` (`ERR_ITEM_NOT_INSTALLED`),
    and `demo_minutes` must be at least 15 — a shorter demo does not count and
    fails with `ERR_DEMO_TOO_SHORT`."

    Design: Difficulty/boundary_precision_check/startup_demo_minutes_minimum_inclusive
    """
    customer, project, layout, items, quote, job = setup_delivered_project(
        item_overrides_list=[
            {"model_no": "RANGE", "quantity": 1, "unit_price_cents": 100_000,
             "lead_time_days": 7}
        ]
    )
    session = get_success_data(
        api.create_startup_session(
            project["id"],
            create_startup_session_payload(items[0]["id"], demo_minutes=14),
            ST,
        )
    )
    res = api.complete_startup_session(project["id"], session["id"], ST)
    validate_error(res, "ERR_DEMO_TOO_SHORT", expected_status=422)
