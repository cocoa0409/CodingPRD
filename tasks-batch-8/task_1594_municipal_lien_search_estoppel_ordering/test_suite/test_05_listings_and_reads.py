"""Listing, computed-read, and retrieval claims: the pagination envelope, the
order summary projection, field round-tripping, and conditional fan-out."""
from test_helpers import (
    ApiErrorId,
    CONFIG_A_DEPARTMENTS,
    FINDINGS_EMPTY,
    UTILITY_ONLY_DEPARTMENTS,
    create_department,
    create_jurisdiction,
    create_search_order,
    create_statute,
    identify_order,
    list_order_tasks,
    make_provider_admin_headers,
    make_qa_reviewer_headers,
    make_research_analyst_headers,
    set_clock,
    setup_config_a,
    setup_identified_order,
    setup_in_verification,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_provider_admin_headers()
ANALYST = make_research_analyst_headers("analyst_1")
QA = make_qa_reviewer_headers("qa_1")


def test_departments_list_paginates(api):
    """PRD 2.3: "List endpoints accept two optional query parameters, `limit`
    and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0. Every list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`. Items
    are always returned in `created_at` ascending order; because the logical
    clock can assign identical timestamps to several resources, ties are broken
    by insertion order — the order in which the server accepted the creates."

    Design: Corner/endpoints/departments_list_paginates
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    for dept in CONFIG_A_DEPARTMENTS:
        create_department(jurisdiction["id"], **dept)

    page_one, meta_one = validate_paginated(
        api.list_jurisdiction_departments(
            jurisdiction["id"], ADMIN, params={"limit": 2, "offset": 0}
        )
    )
    assert [d["dept_type"] for d in page_one] == ["UTILITY", "CODE_ENFORCEMENT"]
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0

    page_two, meta_two = validate_paginated(
        api.list_jurisdiction_departments(
            jurisdiction["id"], ADMIN, params={"limit": 2, "offset": 2}
        )
    )
    assert [d["dept_type"] for d in page_two] == ["PERMIT"]
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert meta_two["offset"] == 2


def test_order_summary_reflects_current_totals(api):
    """PRD 3.6: "The order-summary read, by contrast, always re-runs the same
    five steps over current totals — never reusing a frozen snapshot — so fees
    accruing after delivery can raise the projection, which it reports as
    `projected_coverage_fee_cents` and `projected_liability_cap_cents` alongside
    `total_payoff_cents`, `total_fees_cents`, `pending_claims_cents`,
    `total_liability_cents`, a `task_counts` breakdown, the `estoppel_count`,
    the `open_discrepancy_count`, and the `latest_delivery_status`."

    Design: Corner/endpoints/summary_computed_read_reflects_totals
    """
    # Task fee 5000 + estoppel fee 10000 = 15000 fees; payoff 300000 + 45000.
    ctx = setup_in_verification(
        "P-X2",
        departments=UTILITY_ONLY_DEPARTMENTS,
        findings_per_task=[[{"finding_kind": "UNPAID_UTILITY", "amount_cents": 300000}]],
    )
    summary = validate_success(
        api.get_search_order_summary(ctx["order"]["id"], QA), 200
    )
    assert summary["total_payoff_cents"] == 345000
    assert summary["total_fees_cents"] == 15000
    # Standard coverage -> fee 0; clamp(10 x 15000) = clamp(150000) -> 100000.
    assert summary["projected_coverage_fee_cents"] == 0
    assert summary["projected_liability_cap_cents"] == 100000
    assert summary["estoppel_count"] == 1
    assert summary["open_discrepancy_count"] == 0
    assert summary["task_counts"]["COMPLETED"] == 1
    assert summary.get("latest_delivery_status") is None


def test_get_search_order_returns_persisted_fields(api):
    """PRD 3.2: "The order is born in `INTAKE`, and its `title_agent_id` is
    copied from the caller's `X-User-ID`; the `jurisdiction_id` and `statute_id`
    remain null until jurisdiction identification."
    PRD 2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/endpoints/get_search_order_returns_persisted_fields
    """
    set_clock()
    created = create_search_order(
        "P-Y3", property_address="3 Y St", closing_date="2026-08-20"
    )
    fetched = validate_success(api.get_search_order(created["id"], QA), 200)
    assert fetched["parcel_number"] == "P-Y3"
    assert fetched["closing_date"] == "2026-08-20"
    assert fetched["order_class"] == "STANDARD"
    assert fetched["title_agent_id"] == "agent_1"


def test_inactive_department_skipped_at_identify(api):
    """PRD 3.1: "Departments are born `ACTIVE`; deactivating one flips its
    `status` to `INACTIVE`, and future jurisdiction identifications simply skip
    it when spawning research tasks."

    Design: Corner/endpoints/inactive_department_not_spawned
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    create_statute(jurisdiction["id"])
    create_department(
        jurisdiction["id"], dept_type="UTILITY", name="Water & Sewer",
        research_fee_cents=5000, rush_surcharge_cents=2500, supports_rush=True,
    )
    code_dept = create_department(
        jurisdiction["id"], dept_type="CODE_ENFORCEMENT", name="Code Compliance",
        research_fee_cents=7000, rush_surcharge_cents=3000, supports_rush=True,
    )
    validate_success(api.deactivate_department(code_dept["id"], ADMIN))
    order = create_search_order("P-AJ5")

    identify_order(order["id"], jurisdiction["id"])
    tasks = list_order_tasks(order["id"])
    assert len(tasks) == 1, (
        f"Only the ACTIVE department may spawn a task, got {len(tasks)} tasks"
    )
    assert tasks[0]["dept_type"] == "UTILITY"


def test_identify_into_inactive_jurisdiction_rejected(api):
    """PRD 3.1: "A jurisdiction is born `ACTIVE`, and only an `ACTIVE`
    jurisdiction accepts jurisdiction identification; deactivation flips its
    `status` to `INACTIVE` and blocks new identifications without disturbing
    orders already in flight."
    PRD 3.3: "A `ResearchAnalyst` identifies the governing jurisdiction for an
    order in `INTAKE`, which must reference an existing, `ACTIVE` jurisdiction —
    a missing one surfaces as `ERR_NOT_FOUND`, an inactive one as
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/endpoints/identify_into_inactive_jurisdiction_rejected
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    create_statute(jurisdiction["id"])
    validate_success(api.deactivate_jurisdiction(jurisdiction["id"], ADMIN))
    order = create_search_order("P-AK6")

    response = api.identify_jurisdiction(
        order["id"], {"jurisdiction_id": jurisdiction["id"]}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    from test_helpers import get_order

    assert get_order(order["id"])["status"] == "INTAKE"
