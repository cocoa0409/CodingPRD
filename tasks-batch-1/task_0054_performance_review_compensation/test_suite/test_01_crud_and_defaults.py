"""CRUD round-trips, field defaults, FK integrity, listing, pagination, filtering.

Queue B (Corner) — entities, endpoints, errors, rbac sections.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    create_cycle_payload, create_employee_payload, create_review_payload,
    create_rating_band_payload, create_goal_payload, create_feedback_request_payload,
    create_calibration_session_payload,
    assert_review_cycle, assert_employee, assert_rating_band,
    TEST_USERS,
    create_employee, create_open_cycle_single_band, create_draft_cycle_single_band,
    create_review, drive_review_to_submitted,
    setup_comp_planning_with_n_calibrated_reviews, create_comp_plan_for,
    make_manager_headers, make_employee_headers, make_hrbp_headers,
)

HR = TEST_USERS["hr_admin_headers"]


# --------------------------------------------------------------------------
# Defaults on create
# --------------------------------------------------------------------------
def test_cycle_create_defaults_to_draft(api):
    """PRD §3.1: "A review cycle is created by an `HrAdmin` and begins life in
    `DRAFT`." PRD §2.4: "an integer `version` that starts at 1". PRD §3.1: "The
    two ledger fields, `merit_committed_total` and `equity_committed_total`, are
    computed and begin at zero."

    Design: Corner/entities/cycle_create_defaults_draft_status
    """
    res = api.create_cycle(create_cycle_payload(
        name="FY26", cadence="ANNUAL", merit_budget_pct=0.04,
        equity_refresh_pool=5000,
        bell_curve_target={"EXCEEDS": 0.2, "MEETS": 0.65, "BELOW": 0.15}), HR)
    cyc = validate_success(res, 201)
    assert_review_cycle(cyc)
    assert cyc["status"] == "DRAFT"
    assert cyc["version"] == 1
    assert cyc["merit_committed_total"] == 0


def test_cycle_distribution_tolerance_default(api):
    """PRD §3.1: "Finally the cycle carries a `distribution_tolerance` ... it
    defaults to five hundredths and must be between zero and one inclusive."

    Design: Corner/entities/cycle_distribution_tolerance_default
    """
    res = api.create_cycle(create_cycle_payload(
        name="FY26b", cadence="SEMI_ANNUAL", merit_budget_pct=0.05,
        equity_refresh_pool=0, bell_curve_target={"MEETS": 1.0}), HR)
    cyc = validate_success(res, 201)
    assert cyc["distribution_tolerance"] == 0.05


def test_employee_defaults_is_active_true(api):
    """PRD §3.1: "an `is_active` boolean defaulting to true that records whether
    the person is currently employed."

    Design: Corner/entities/employee_defaults_is_active_true
    """
    res = api.create_employee(create_employee_payload(
        full_name="Alice", department="ENG", hire_date="2019-01-01T00:00:00.000Z"), HR)
    emp = validate_success(res, 201)
    assert_employee(emp)
    assert emp["is_active"] is True


def test_goal_create_defaults_open(api):
    """PRD §3.3: "A goal is created in the `OPEN` state."

    Design: Corner/entities/goal_create_defaults_open
    """
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rev = get_success_data(api.create_review(
        create_review_payload(cyc["id"], emp["id"], mgr["id"]), HR))
    res = api.create_goal(rev["id"], create_goal_payload(title="Ship X", weight=0.5),
                          make_manager_headers(mgr["id"]))
    goal = validate_success(res, 201)
    assert goal["status"] == "OPEN"
    data, _ = validate_paginated(api.list_goals(rev["id"], make_manager_headers(mgr["id"])))
    assert any(g["id"] == goal["id"] for g in data)


def test_feedback_create_defaults_pending(api):
    """PRD §3.3: "A new request begins `PENDING` and carries no `score` yet."

    Design: Corner/entities/feedback_create_defaults_pending
    """
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rater = create_employee(full_name="Rater", department="ENG")
    rev = get_success_data(api.create_review(
        create_review_payload(cyc["id"], emp["id"], mgr["id"]), HR))
    res = api.create_feedback_request(
        rev["id"], create_feedback_request_payload(rater["id"], relationship="PEER"),
        make_manager_headers(mgr["id"]))
    fr = validate_success(res, 201)
    assert fr["status"] == "PENDING"


# --------------------------------------------------------------------------
# FK integrity
# --------------------------------------------------------------------------
def test_review_fk_employee_invalid(api):
    """PRD §2.5: "The same code applies when a foreign key supplied in a request
    body — a `cycle_id`, `employee_id`, `reviewer_id`, `review_id`, `rater_id`,
    `facilitator_id`, or `manager_id` — points at a resource that does not exist."

    Design: Corner/entities/review_fk_employee_invalid
    """
    cyc = create_draft_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    res = api.create_review(create_review_payload(
        cyc["id"], NON_EXISTENT_UUID, mgr["id"]), HR)
    validate_error(res, "ERR_NOT_FOUND")


def test_err_not_found_unknown_cycle(api):
    """PRD §2.5: "every referenced resource must exist; the first missing one
    causes the request to fail with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/err_not_found_unknown_cycle
    """
    res = api.get_cycle(NON_EXISTENT_UUID, HR)
    validate_error(res, "ERR_NOT_FOUND")


# --------------------------------------------------------------------------
# CRUD round-trips, self-referential FK
# --------------------------------------------------------------------------
def test_rating_band_create_and_list(api):
    """PRD §3.1: "While the cycle is still in `DRAFT`, the `HrAdmin` defines its
    rating bands." Section 4: "GET /cycles/{id}/rating-bands | List a cycle's
    rating bands".

    Design: Corner/endpoints/rating_band_create_and_list
    """
    cyc = get_success_data(api.create_cycle(create_cycle_payload(
        name="C", cadence="ANNUAL", merit_budget_pct=0.04, equity_refresh_pool=0,
        bell_curve_target={"MEETS": 1.0}), HR))
    api.create_rating_band(cyc["id"], create_rating_band_payload(
        label="MEETS", min_score=0, max_score=100, merit_pct=0.04), HR)
    data, _ = validate_paginated(api.list_rating_bands(cyc["id"], HR))
    assert len(data) == 1
    assert data[0]["label"] == "MEETS"
    assert_rating_band(data[0])


def test_employee_self_referential_manager_read(api):
    """PRD §3.1: "an optional `manager_id` referencing another employee as their
    manager (null for the top of the chain, and never equal to the employee's own
    id)".

    Design: Corner/endpoints/employee_self_referential_manager_read
    """
    mgr = create_employee(full_name="Mgr", department="ENG")
    rep = create_employee(full_name="Report", department="ENG", manager_id=mgr["id"])
    got = validate_success(api.get_employee(rep["id"], HR), 200)
    assert got["manager_id"] == mgr["id"]


def test_employees_filter_by_manager_id(api):
    """PRD Section 4: "GET /employees | List employees, filterable by manager or
    department".

    Design: Corner/endpoints/employees_filter_by_manager_id
    """
    mgr = create_employee(full_name="Mgr", department="ENG")
    create_employee(full_name="R1", department="ENG", manager_id=mgr["id"])
    create_employee(full_name="R2", department="ENG", manager_id=mgr["id"])
    data, _ = validate_paginated(api.list_employees(HR, params={"manager_id": mgr["id"]}))
    assert len(data) == 2
    assert all(e["manager_id"] == mgr["id"] for e in data)


def test_feedback_filter_by_rater_id(api):
    """PRD Section 4: "GET /feedback-requests | List feedback requests, filterable
    by rater, review, or status".

    Design: Corner/endpoints/feedback_filter_by_rater_id
    """
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rater = create_employee(full_name="Rater", department="ENG")
    rev = get_success_data(api.create_review(
        create_review_payload(cyc["id"], emp["id"], mgr["id"]), HR))
    api.create_feedback_request(
        rev["id"], create_feedback_request_payload(rater["id"], relationship="PEER"),
        make_manager_headers(mgr["id"]))
    data, _ = validate_paginated(api.list_feedback_requests(
        make_hrbp_headers(create_employee(full_name="Hrbp")["id"]),
        params={"rater_id": rater["id"]}))
    assert len(data) == 1
    assert data[0]["rater_id"] == rater["id"]


def test_calibration_filter_by_facilitator_id(api):
    """PRD Section 4: "GET /calibration-sessions | List calibration sessions,
    filterable by cycle or facilitator".

    Design: Corner/endpoints/calibration_filter_by_facilitator_id
    """
    # Build a CALIBRATION-phase cycle so a session can be created.
    cyc = create_open_cycle_single_band()
    hrbp = create_employee(full_name="Hrbp", department="ENG")
    api.start_calibration(cyc["id"], HR)  # OPEN -> CALIBRATION (no reviews -> allowed)
    sess = get_success_data(api.create_calibration_session(
        create_calibration_session_payload(cyc["id"], hrbp["id"], department="ENG"),
        make_hrbp_headers(hrbp["id"])))
    data, _ = validate_paginated(api.list_calibration_sessions(
        make_hrbp_headers(hrbp["id"]), params={"facilitator_id": hrbp["id"]}))
    assert len(data) == 1
    assert data[0]["facilitator_id"] == hrbp["id"]
    assert data[0]["id"] == sess["id"]


def test_cycles_filter_by_status(api):
    """PRD Section 4: "GET /cycles | List cycles, filterable by status".

    Design: Corner/endpoints/cycles_filter_by_status
    """
    create_draft_cycle_single_band()
    create_open_cycle_single_band()
    data, _ = validate_paginated(api.list_cycles(HR, params={"status": "OPEN"}))
    assert len(data) >= 1
    assert all(c["status"] == "OPEN" for c in data)


def test_comp_plans_filter_by_cycle_id(api):
    """PRD Section 4: "GET /comp-plans | List compensation plans, filterable by
    cycle, review, or status".

    Design: Corner/endpoints/comp_plans_filter_by_cycle_id
    """
    ctx = setup_comp_planning_with_n_calibrated_reviews(
        n=2, band_label="MEETS", band_merit_pct=0.04,
        merit_budget_pct=0.5, equity_refresh_pool=100000)
    cyc_id = ctx["cycle"]["id"]
    create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], ctx["reviewers"][0]["id"])
    create_comp_plan_for(cyc_id, ctx["reviews"][1]["id"], ctx["reviewers"][1]["id"])
    data, _ = validate_paginated(api.list_comp_plans(HR, params={"cycle_id": cyc_id}))
    assert len(data) == 2
    assert all(p["cycle_id"] == cyc_id for p in data)


def test_pip_cases_filter_by_employee_id(api):
    """PRD Section 4: "GET /pip-cases | List PIP cases, filterable by employee or
    status".

    Design: Corner/endpoints/pip_cases_filter_by_employee_id
    """
    # A review landing in a pip_eligible BELOW band cascade-creates a PipCase at
    # calibration finalize (PRD §3.4), giving the employee exactly one PIP case.
    cyc = get_success_data(api.create_cycle(create_cycle_payload(
        name="Pip", cadence="ANNUAL", merit_budget_pct=0.5, equity_refresh_pool=0,
        bell_curve_target={"BELOW": 1.0}), HR))
    api.create_rating_band(cyc["id"], create_rating_band_payload(
        label="BELOW", min_score=0, max_score=100, merit_pct=0.0, pip_eligible=True), HR)
    api.open_cycle(cyc["id"], HR)
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rev = create_review(cyc["id"], emp["id"], mgr["id"])
    drive_review_to_submitted(cyc["id"], rev["id"], emp["id"], mgr["id"],
                              self_rating="BELOW", manager_rating="BELOW", goal_attainment=0.0)
    api.start_calibration(cyc["id"], HR)
    hrbp = create_employee(full_name="Hrbp", department="ENG")
    sess = get_success_data(api.create_calibration_session(
        create_calibration_session_payload(cyc["id"], hrbp["id"], department="ENG"),
        make_hrbp_headers(hrbp["id"])))
    api.balance_session(sess["id"], make_hrbp_headers(hrbp["id"]))
    api.finalize_session(sess["id"], make_hrbp_headers(hrbp["id"]))
    data, _ = validate_paginated(api.list_pip_cases(
        make_hrbp_headers(hrbp["id"]), params={"employee_id": emp["id"]}))
    assert len(data) == 1
    assert data[0]["employee_id"] == emp["id"]


def test_reviews_pagination(api):
    """PRD §2.3: "The `limit` parameter defaults to 10 ... Each list response
    carries pagination metadata in `meta`: the effective `limit`, the effective
    `offset`, the `total_count` of records matching the query before pagination,
    and a boolean `has_more` indicating whether records remain beyond the
    returned page."

    Design: Corner/endpoints/reviews_pagination
    """
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    for i in range(15):
        emp = create_employee(full_name=f"E{i}", department="ENG", manager_id=mgr["id"])
        api.create_review(create_review_payload(cyc["id"], emp["id"], mgr["id"]), HR)
    data, meta = validate_paginated(api.list_reviews(
        HR, params={"cycle_id": cyc["id"], "limit": 10, "offset": 0}))
    assert len(data) == 10
    assert meta["total_count"] == 15
    assert meta["has_more"] is True
