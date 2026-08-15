"""Boundary precision: the exact rush-capacity count boundary and the
inclusive estoppel valid-through/closing-date boundary."""
from test_helpers import (
    ApiErrorId,
    FINDINGS_EMPTY,
    UTILITY_ONLY_DEPARTMENTS,
    complete_task,
    create_department,
    create_jurisdiction,
    create_search_order,
    create_search_order_payload,
    create_statute,
    identify_order,
    list_order_estoppels,
    list_order_tasks,
    make_research_analyst_headers,
    make_title_agent_headers,
    place_estoppel,
    receive_estoppel,
    record_findings,
    set_clock,
    setup_config_a,
    submit_order,
    validate_error,
    validate_success,
)

AGENT = make_title_agent_headers("agent_1")
AGENT2 = make_title_agent_headers("agent_2")
ANALYST = make_research_analyst_headers("analyst_1")


def _capacity_one_config():
    set_clock()
    jurisdiction = create_jurisdiction(rush_daily_capacity=1)
    create_statute(jurisdiction["id"])
    create_department(
        jurisdiction["id"], dept_type="UTILITY", name="Water & Sewer",
        research_fee_cents=5000, rush_surcharge_cents=2500, supports_rush=True,
    )
    return jurisdiction


def test_rush_order_one_below_capacity_accepted(api):
    """PRD 3.2: "if that occupant count already equals or exceeds the
    jurisdiction's `rush_daily_capacity`, creation is rejected with
    `ERR_RUSH_CAPACITY_FULL`, while a count exactly one below capacity is still
    accepted."

    Design: Difficulty/boundary_precision_check/rush_capacity_exactly_at_capacity_rejected
    """
    jurisdiction = _capacity_one_config()
    response = api.create_search_order(
        create_search_order_payload(
            "P-K1",
            property_address="1 K St",
            closing_date="2026-08-25",
            order_class="RUSH",
            service_date="2026-08-10",
            jurisdiction_id=jurisdiction["id"],
        ),
        AGENT,
    )
    order = validate_success(response, 201)
    # Occupant count 0 == capacity - 1: accepted.
    assert order["status"] == "INTAKE"


def test_rush_order_at_capacity_rejected(api):
    """PRD 3.2: "if that occupant count already equals or exceeds the
    jurisdiction's `rush_daily_capacity`, creation is rejected with
    `ERR_RUSH_CAPACITY_FULL`, while a count exactly one below capacity is still
    accepted."

    Design: Difficulty/boundary_precision_check/rush_capacity_exactly_at_capacity_rejected
    """
    jurisdiction = _capacity_one_config()
    first = create_search_order(
        "P-K1",
        property_address="1 K St",
        closing_date="2026-08-25",
        order_class="RUSH",
        service_date="2026-08-10",
        jurisdiction_id=jurisdiction["id"],
    )
    assert first["status"] == "INTAKE"

    # Occupant count 1 >= capacity 1: rejected at the exact boundary.
    response = api.create_search_order(
        create_search_order_payload(
            "P-K2",
            property_address="2 K St",
            closing_date="2026-08-25",
            order_class="RUSH",
            service_date="2026-08-10",
            jurisdiction_id=jurisdiction["id"],
        ),
        AGENT2,
    )
    validate_error(response, ApiErrorId.ERR_RUSH_CAPACITY_FULL.value)
    assert response.status_code == 409


def _order_with_received_estoppel(ctx, parcel, closing_date):
    """One order on the shared config: identified, its single task completed
    with empty findings, its estoppel placed and received on 2026-08-01
    (valid_through = 2026-08-31)."""
    order = create_search_order(
        parcel, closing_date=closing_date, association_id=ctx["association"]["id"]
    )
    identify_order(order["id"], ctx["jurisdiction"]["id"])
    task = list_order_tasks(order["id"])[0]
    record_findings(task, FINDINGS_EMPTY)
    complete_task(task["id"])
    estoppel = list_order_estoppels(order["id"])[0]
    place_estoppel(estoppel["id"], 10000)
    receive_estoppel(estoppel["id"], 45000)
    return order["id"]


def test_closing_on_valid_through_day_accepted(api):
    """PRD 3.5: "An estoppel is current for closing exactly when the order's
    `closing_date` is on or before `valid_through`; the boundary day itself
    counts as valid."

    Design: Difficulty/boundary_precision_check/estoppel_valid_through_equals_closing_date_accepted
    """
    ctx = setup_config_a(departments=UTILITY_ONLY_DEPARTMENTS, with_association=True)
    # closing 2026-08-31 == valid_through 2026-08-31: inclusive boundary.
    order_id = _order_with_received_estoppel(ctx, "P-D1", "2026-08-31")
    submitted = submit_order(order_id)
    assert submitted["status"] == "VERIFICATION"


def test_closing_one_day_past_valid_through_rejected(api):
    """PRD 3.6: "every estoppel order is `RECEIVED` (anything else blocks with
    `ERR_ESTOPPEL_NOT_CURRENT`) with a `valid_through` on or after the
    `closing_date` (a stale letter blocks with `ERR_ESTOPPEL_STALE_FOR_CLOSING`)"
    PRD 3.5: "An estoppel is current for closing exactly when the order's
    `closing_date` is on or before `valid_through`; the boundary day itself
    counts as valid."

    Design: Difficulty/boundary_precision_check/estoppel_valid_through_equals_closing_date_accepted
    """
    ctx = setup_config_a(departments=UTILITY_ONLY_DEPARTMENTS, with_association=True)
    # closing 2026-09-01 > valid_through 2026-08-31: one day past the boundary.
    order_id = _order_with_received_estoppel(ctx, "P-D2", "2026-09-01")
    response = api.submit_for_verification(order_id, ANALYST)
    validate_error(response, ApiErrorId.ERR_ESTOPPEL_STALE_FOR_CLOSING.value)
    assert response.status_code == 422
