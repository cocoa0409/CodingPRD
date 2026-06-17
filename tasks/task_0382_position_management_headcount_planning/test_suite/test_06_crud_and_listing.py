"""Resource creation, request well-formedness, FK existence, immutability,
invalid/terminal state transitions, listing/pagination envelopes, and the
append-only budget-adjustment path.

Queue B (Corner): entities, state_machines, endpoints, cross_cutting (budget
adjustment).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, fixtures, factories,
)


# ===========================================================================
# CostCenter creation defaults
# ===========================================================================
def test_create_cost_center_returns_201_with_empty_pool_defaults(api, finance_headers):
    """PRD §3.1: "At creation the derived fields settle to their empty-pool
    values: committed_fte, committed_cost_cents, and filled_fte are all zero;
    adjusted_budget_cents equals the base annual_budget_cents; available_budget_cents
    equals that same figure; and posture is OPEN. The cost center's version begins
    at 1."

    Design: Corner/entities/entity_create_cost_center_returns_201_with_derived_defaults
    """
    resp = api.create_cost_center(
        factories.create_cost_center_payload(name="Eng", annual_budget_cents=100000000, fte_cap=5.0),
        finance_headers,
    )
    data = validate_success(resp, 201)
    assert data["committed_cost_cents"] == 0, f"Expected committed_cost 0, got {data['committed_cost_cents']}"
    assert data["committed_fte"] == 0, f"Expected committed_fte 0, got {data['committed_fte']}"
    assert data["filled_fte"] == 0, f"Expected filled_fte 0, got {data['filled_fte']}"
    assert data["available_budget_cents"] == 100000000, \
        f"Expected available 100000000, got {data['available_budget_cents']}"
    assert data["posture"] == "OPEN", f"Expected posture OPEN, got {data['posture']}"
    assert data["version"] == 1, f"Expected version 1, got {data['version']}"


# ===========================================================================
# Not found / required fields / type constraints / FK
# ===========================================================================
def test_get_missing_position_returns_404(api, hrbp_headers):
    """PRD §2.4: "If any path segment or referenced resource does not exist, the
    request fails with ERR_NOT_FOUND (HTTP 404) before any business rule is
    evaluated."

    Design: Corner/entities/entity_position_not_found_returns_404
    """
    resp = api.get_position(NON_EXISTENT_UUID, hrbp_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_position_missing_fte_returns_422(api, hrbp_headers):
    """PRD §2.5: "Request well-formedness is checked fourth — required fields must
    be present ... with any violation yielding ERR_INVALID_REQUEST (HTTP 422)."
    PRD §3.2: "supplying the owning cost_center_id, the classification grade_id, a
    title, and an fte allocation".

    Design: Corner/entities/entity_position_missing_required_fte_returns_422
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center()
    # Omit the required fte field.
    resp = api.create_position(
        {"cost_center_id": cc["id"], "grade_id": grade["id"], "title": "P1"}, hrbp_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_position_fte_above_one_returns_422(api, hrbp_headers):
    """PRD §2.5: "every fte value must be greater than 0 and at most 1.0 with at
    most two decimal places ... with any violation yielding ERR_INVALID_REQUEST
    (HTTP 422)."

    Design: Corner/entities/entity_position_fte_out_of_range_returns_422
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center()
    resp = api.create_position(
        factories.create_position_payload(cc["id"], grade["id"], title="P1", fte=1.5), hrbp_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_position_bad_cost_center_fk_returns_404(api, hrbp_headers):
    """PRD §2.4: "any foreign-key reference carried in the request body is
    resolved after the path. If any path segment or referenced resource does not
    exist, the request fails with ERR_NOT_FOUND (HTTP 404)".

    Design: Corner/entities/entity_position_bad_cost_center_fk_returns_404
    """
    grade = fixtures.create_grade_g07()
    resp = api.create_position(
        factories.create_position_payload(NON_EXISTENT_UUID, grade["id"], title="P1", fte=0.5), hrbp_headers
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_grade_created_immutable_without_version(api, comp_headers):
    """PRD §2.4: "a Grade and a BudgetAdjustment each carry only id and created_at
    — they have no updated_at and no version, because once written they are never
    mutated."

    Design: Corner/entities/entity_grade_immutable_no_version_field
    """
    resp = api.create_grade(
        factories.create_grade_payload(
            code="G07", band_min_cents=10000000, band_mid_cents=12000000, band_max_cents=15000000, rank=7
        ),
        comp_headers,
    )
    data = validate_success(resp, 201)
    assert data["code"] == "G07", f"Expected code G07, got {data['code']}"
    assert data["rank"] == 7, f"Expected rank 7, got {data['rank']}"
    assert "version" not in data, "Grade must not carry a version field"
    assert "updated_at" not in data, "Grade must not carry an updated_at field"


# ===========================================================================
# Initial state + invalid / terminal transitions
# ===========================================================================
def test_new_position_starts_draft_vacant(api, hrbp_headers):
    """PRD §3.2: "Every position is born in lifecycle_status DRAFT and
    occupancy_status VACANT, with version 1."

    Design: Corner/state_machines/sm_initial_state_position_draft_vacant
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center()
    resp = api.create_position(
        factories.create_position_payload(cc["id"], grade["id"], title="P1", fte=0.5), hrbp_headers
    )
    data = validate_success(resp, 201)
    assert data["lifecycle_status"] == "DRAFT", f"Expected DRAFT, got {data['lifecycle_status']}"
    assert data["occupancy_status"] == "VACANT", f"Expected VACANT, got {data['occupancy_status']}"


def test_fund_from_draft_rejected_invalid_state(api, finance_headers):
    """PRD §3.3: "Second, a FinanceController funds the requisitioned position,
    advancing lifecycle_status from REQUISITIONED to FUNDED ... The position must
    currently be REQUISITIONED". PRD §2.5 maps an invalid transition to
    ERR_INVALID_STATE.

    Design: Corner/state_machines/sm_fund_from_draft_skips_requisition_invalid_state
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    v0 = cc["version"]
    pos = fixtures.create_position(cc["id"], grade["id"], title="P1", fte=0.5)  # DRAFT, never requisitioned

    resp = api.position_lifecycle(
        pos["id"], factories.lifecycle_payload("FUND", expected_cost_center_version=v0), finance_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    position = fixtures.get_position(pos["id"])
    assert position["lifecycle_status"] == "DRAFT", \
        f"Position must stay DRAFT, got {position['lifecycle_status']}"


def test_requisition_on_abolished_position_rejected(api, hrbp_headers, director_headers):
    """PRD §3.8: "A position may be abolished from either REQUISITIONED or
    FUNDED, moving its lifecycle_status to the terminal ABOLISHED." PRD §3.3
    permits REQUISITION "only while the position is DRAFT".

    Design: Corner/state_machines/sm_abolished_terminal_lockdown_rejects_requisition
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center()
    pos = fixtures.create_requisitioned_position(cc["id"], grade["id"], title="P1", fte=0.5)
    # Abolish from REQUISITIONED -> terminal ABOLISHED.
    get_success_data(api.position_lifecycle(pos["id"], factories.lifecycle_payload("ABOLISH"), director_headers))

    resp = api.position_lifecycle(pos["id"], factories.lifecycle_payload("REQUISITION"), hrbp_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    position = fixtures.get_position(pos["id"])
    assert position["lifecycle_status"] == "ABOLISHED", \
        f"Position must stay ABOLISHED, got {position['lifecycle_status']}"


# ===========================================================================
# Budget / fund admission corners
# ===========================================================================
def test_fund_one_cent_over_budget_rejected(api, finance_headers):
    """PRD §3.3: "If the FTE fits but the cost exceeds the budget headroom,
    funding is rejected with ERR_BUDGET_EXCEEDED (HTTP 409)".

    Design: Corner/calculations/calc_budget_exceeded_one_cent_over
    """
    grade = fixtures.create_grade_g07()
    # Budget 5999999; planned cost 6000000 exceeds by 1 cent.
    cc = fixtures.create_cost_center(name="Tight", annual_budget_cents=5999999, fte_cap=5.0)
    v0 = cc["version"]
    p1 = fixtures.create_requisitioned_position(cc["id"], grade["id"], title="P1", fte=0.5)

    resp = api.position_lifecycle(
        p1["id"], factories.lifecycle_payload("FUND", expected_cost_center_version=v0), finance_headers
    )
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value)

    position = fixtures.get_position(p1["id"])
    assert position["lifecycle_status"] == "REQUISITIONED", \
        f"Position must stay REQUISITIONED, got {position['lifecycle_status']}"


def test_fund_override_admits_negative_available_budget(api, finance_headers):
    """PRD §3.3: "unless the caller passed override as true, in which case the
    budget check is waived and the cost center is permitted to go into negative
    available_budget_cents."

    Design: Corner/calculations/calc_budget_override_admits_overcommit
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Over", annual_budget_cents=5999999, fte_cap=5.0)
    v0 = cc["version"]
    p1 = fixtures.create_requisitioned_position(cc["id"], grade["id"], title="P1", fte=0.5)

    resp = api.position_lifecycle(
        p1["id"],
        factories.lifecycle_payload("FUND", override=True, expected_cost_center_version=v0),
        finance_headers,
    )
    data = validate_success(resp, 200)
    assert data["lifecycle_status"] == "FUNDED", f"Expected FUNDED with override, got {data['lifecycle_status']}"

    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["committed_cost_cents"] == 6000000, \
        f"Expected committed_cost 6000000, got {cost_center['committed_cost_cents']}"
    assert cost_center["available_budget_cents"] == -1, \
        f"Expected available -1, got {cost_center['available_budget_cents']}"


def test_budget_adjustment_raises_adjusted_budget_and_admits_fund(api, finance_headers):
    """PRD §3.1: "Its adjusted_budget_cents is then recomputed as the base
    annual_budget_cents plus the sum of amount_cents over every APPLIED adjustment
    on that cost center ... and available_budget_cents is refreshed accordingly."

    Design: Corner/entities/budget_adjustment_increases_available_and_admits_fund
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Adj", annual_budget_cents=5999999, fte_cap=5.0)
    p1 = fixtures.create_requisitioned_position(cc["id"], grade["id"], title="P1", fte=0.5)

    # +1 raises adjusted_budget_cents to 6000000, so funding planned 6000000 now fits.
    fixtures.apply_budget_adjustment(cc["id"], 1, memo="top-up")
    raised = fixtures.get_cost_center(cc["id"])
    assert raised["adjusted_budget_cents"] == 6000000, \
        f"Expected adjusted_budget 6000000, got {raised['adjusted_budget_cents']}"

    funded = fixtures.fund_position(p1["id"], cc["id"])
    assert funded["lifecycle_status"] == "FUNDED", \
        f"Expected FUNDED after top-up, got {funded['lifecycle_status']}"
    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["available_budget_cents"] == 0, \
        f"Expected available 0, got {cost_center['available_budget_cents']}"


# ===========================================================================
# Listing / pagination envelopes
# ===========================================================================
def test_list_positions_pagination_envelope(api, hrbp_headers):
    """PRD §2.3: "total_count reports the number of records matching the request
    before pagination is applied, and has_more is true exactly when records remain
    beyond the current page."

    Design: Corner/endpoints/ep_list_positions_pagination_envelope
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center()
    fixtures.create_position(cc["id"], grade["id"], title="P1", fte=0.5)
    fixtures.create_position(cc["id"], grade["id"], title="P2", fte=0.5)

    resp = api.list_positions(hrbp_headers, params={"cost_center_id": cc["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"Expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"Expected has_more true, got {meta['has_more']}"
    assert len(data) == 1, f"Expected 1 record on the page, got {len(data)}"


def test_reports_subresource_lists_direct_reports(api, hrbp_headers):
    """PRD §3.2: "A manager's span_of_control is the count of positions whose
    manager_position_id equals that manager's id". The /reports subresource lists
    exactly those positions reporting to the manager.

    Design: Corner/endpoints/ep_reports_subresource_lists_direct_reports
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center()
    mgr = fixtures.create_position(cc["id"], grade["id"], title="M", fte=0.5)
    fixtures.create_position(cc["id"], grade["id"], title="C1", fte=0.5, manager_position_id=mgr["id"])
    fixtures.create_position(cc["id"], grade["id"], title="C2", fte=0.5, manager_position_id=mgr["id"])

    resp = api.list_position_reports(mgr["id"], hrbp_headers)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"Expected 2 direct reports, got {meta['total_count']}"


def test_incumbents_history_includes_vacated(api, hrbp_headers):
    """PRD §3.4: "The incumbent's status becomes VACATED". PRD §4 lists GET
    /positions/{positionId}/incumbents as "List incumbency records for a Position",
    which includes vacated history per the §3.4 narrative that vacate preserves the
    record.

    Design: Corner/endpoints/ep_incumbents_history_includes_vacated
    """
    grade, cc, pos, emp, inc = fixtures.setup_filled_position(employee_salary_cents=13000000)
    api.vacate_incumbent(inc["id"], factories.vacate_payload("2026-06-30"), hrbp_headers)

    resp = api.list_position_incumbents(pos["id"], hrbp_headers)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"Expected 1 incumbency record, got {meta['total_count']}"
    incumbent = get_success_data(api.get_incumbent(inc["id"], hrbp_headers))
    assert incumbent["status"] == "VACATED", \
        f"Expected VACATED record preserved, got {incumbent['status']}"


def test_budget_adjustments_reverse_reachable_list(api, finance_headers):
    """PRD §3.1: "Its adjusted_budget_cents is then recomputed as the base
    annual_budget_cents plus the sum of amount_cents over every APPLIED adjustment
    on that cost center". The cost-center subresource lists its applied adjustments.

    Design: Corner/entities/budget_adjustment_reverse_reachable_list
    """
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    fixtures.apply_budget_adjustment(cc["id"], 5000, memo="a1")
    fixtures.apply_budget_adjustment(cc["id"], -2000, memo="a2")

    resp = api.list_cost_center_budget_adjustments(cc["id"], finance_headers)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"Expected 2 adjustments, got {meta['total_count']}"
    cost_center = fixtures.get_cost_center(cc["id"])
    # 100000000 + 5000 - 2000 = 100003000.
    assert cost_center["adjusted_budget_cents"] == 100003000, \
        f"Expected adjusted_budget 100003000, got {cost_center['adjusted_budget_cents']}"
