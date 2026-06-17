"""Validation-priority conflicts, fill preconditions, span-of-control,
incumbency overlap, the existence-before-state ordering, and RBAC.

Queue A (Difficulty): priority_pair_validation_conflict, boundary_precision_check
(span), resource_temporal_overlap (incumbency).
Queue B (Corner): validations, rbac.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, fixtures, factories,
)


# ===========================================================================
# Priority-pair conflicts — higher-priority gate wins
# ===========================================================================
def test_frozen_masks_budget_on_fund(api, finance_headers):
    """PRD §2.5: "Only after all of these structural gates pass are the
    domain-specific business rules — frozen posture, span limits, fill
    preconditions, freeze-window overlap, FTE cap, and budget — evaluated."
    PRD §2.9: "While a cost center is FROZEN, a set of growth-oriented operations
    is blocked and rejected with ERR_COST_CENTER_FROZEN (HTTP 409): requisitioning
    a position, funding a position, filling a position with an incumbent, approving
    a requisition, and approving a reclassification."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_frozen_state_vs_budget_fiscal
    """
    fixtures.set_clock("2026-02-01T00:00:00Z")
    grade = fixtures.create_grade_g07()
    # Budget 1 so any fund would also exceed budget; freeze covering now.
    cc = fixtures.create_cost_center(name="Tight", annual_budget_cents=1, fte_cap=5.0)
    p1 = fixtures.create_requisitioned_position(cc["id"], grade["id"], title="P1", fte=0.5)
    fixtures.open_freeze_order(cc["id"], "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z")

    v = fixtures.cost_center_version(cc["id"])
    resp = api.position_lifecycle(
        p1["id"], factories.lifecycle_payload("FUND", expected_cost_center_version=v), finance_headers
    )
    # Frozen posture is reported, NOT the budget error.
    validate_error(resp, ApiErrorId.ERR_COST_CENTER_FROZEN.value)

    position = fixtures.get_position(p1["id"])
    assert position["lifecycle_status"] == "REQUISITIONED", \
        f"Position must stay REQUISITIONED, got {position['lifecycle_status']}"


def test_frozen_fund_leaves_position_requisitioned(api, finance_headers):
    """PRD §2.9: "While a cost center is FROZEN, a set of growth-oriented
    operations is blocked and rejected with ERR_COST_CENTER_FROZEN (HTTP 409):
    requisitioning a position, funding a position".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_frozen_state_vs_budget_fiscal
    """
    fixtures.set_clock("2026-02-01T00:00:00Z")
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Tight", annual_budget_cents=1, fte_cap=5.0)
    p1 = fixtures.create_requisitioned_position(cc["id"], grade["id"], title="P1", fte=0.5)
    fixtures.open_freeze_order(cc["id"], "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z")

    # The frozen posture (not the budget overflow) governs the outcome. Read the
    # live cost-center version so the OCC token is fresh and the higher-priority
    # ERR_STALE_VERSION gate (PRD §2.5) does not mask the frozen-posture rule.
    v = fixtures.cost_center_version(cc["id"])
    resp = api.position_lifecycle(p1["id"], factories.lifecycle_payload("FUND", expected_cost_center_version=v),
                                  finance_headers)
    validate_error(resp, ApiErrorId.ERR_COST_CENTER_FROZEN.value)
    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["committed_cost_cents"] == 0, \
        f"No commitment must be made, got {cost_center['committed_cost_cents']}"


def test_abolish_draft_with_report_stays_draft(api, director_headers):
    """PRD §3.8: "A position may be abolished from either REQUISITIONED or
    FUNDED, moving its lifecycle_status to the terminal ABOLISHED."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_invalid_state_vs_has_reports_referential
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    mgr = fixtures.create_position(cc["id"], grade["id"], title="Mgr", fte=0.5)  # DRAFT
    child = fixtures.create_position(cc["id"], grade["id"], title="Child", fte=0.5, manager_position_id=mgr["id"])

    resp = api.position_lifecycle(mgr["id"], factories.lifecycle_payload("ABOLISH"), director_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    # Neither the manager nor its report changed state.
    child_pos = fixtures.get_position(child["id"])
    assert child_pos["lifecycle_status"] == "DRAFT", \
        f"Child must stay DRAFT, got {child_pos['lifecycle_status']}"


def test_invalid_state_masks_direct_reports_on_abolish(api, director_headers):
    """PRD §2.5: "The target resource's state is checked sixth against the
    requested transition, yielding ERR_INVALID_STATE (HTTP 409)." PRD §3.8: "A
    position may be abolished from either REQUISITIONED or FUNDED, moving its
    lifecycle_status to the terminal ABOLISHED. The one structural guard is the
    org chart: a position cannot be abolished while any position reporting to it
    ... is still in a state other than ABOLISHED; such an attempt is rejected with
    ERR_HAS_DIRECT_REPORTS (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_invalid_state_vs_has_reports_referential
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    # Manager DRAFT (no ABOLISH transition from DRAFT) with a non-abolished report.
    mgr = fixtures.create_position(cc["id"], grade["id"], title="Mgr", fte=0.5)
    fixtures.create_position(cc["id"], grade["id"], title="Child", fte=0.5, manager_position_id=mgr["id"])

    resp = api.position_lifecycle(mgr["id"], factories.lifecycle_payload("ABOLISH"), director_headers)
    # State check (DRAFT has no ABOLISH) precedes the direct-reports check.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    position = fixtures.get_position(mgr["id"])
    assert position["lifecycle_status"] == "DRAFT", \
        f"Manager must stay DRAFT, got {position['lifecycle_status']}"


# ===========================================================================
# Span-of-control boundary
# ===========================================================================
def test_ninth_direct_report_rejected_eight_allowed(api, hrbp_headers):
    """PRD §3.2: "a single manager may have no more than eight non-abolished
    direct reports. Consequently, when creating a position under a manager ... if
    that manager's direct-report count would rise to nine, the operation is
    rejected with ERR_SPAN_LIMIT_EXCEEDED (HTTP 409); a manager reaching exactly
    eight reports is permitted".

    Design: Difficulty/boundary_precision_check/bpc_span_of_control_eight_ok_nine_rejected
    """
    cc, grade, mgr, report_ids = fixtures.setup_manager_with_reports(8)
    # Manager already has 8 reports; a 9th is rejected.
    resp = api.create_position(
        factories.create_position_payload(cc["id"], grade["id"], title="r9", fte=0.5, manager_position_id=mgr["id"]),
        hrbp_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SPAN_LIMIT_EXCEEDED.value)

    manager = fixtures.get_position(mgr["id"])
    assert manager["span_of_control"] == 8, \
        f"Manager span_of_control must be 8, got {manager['span_of_control']}"


def test_eighth_direct_report_succeeds(api, hrbp_headers):
    """PRD §3.2: "a manager reaching exactly eight reports is permitted, since
    the cap is the eighth report, not the ninth."

    Design: Difficulty/boundary_precision_check/bpc_span_of_control_eight_ok_nine_rejected
    """
    cc, grade, mgr, report_ids = fixtures.setup_manager_with_reports(7)
    # The 8th report is permitted.
    resp = api.create_position(
        factories.create_position_payload(cc["id"], grade["id"], title="r8", fte=0.5, manager_position_id=mgr["id"]),
        hrbp_headers,
    )
    validate_success(resp, 201)
    manager = fixtures.get_position(mgr["id"])
    assert manager["span_of_control"] == 8, \
        f"Manager span_of_control must reach 8, got {manager['span_of_control']}"


# ===========================================================================
# Incumbency inclusive-boundary overlap
# ===========================================================================
def test_refill_on_inclusive_end_boundary_overlaps(api, hrbp_headers):
    """PRD §3.4: "the new occupancy interval, running from start_date forward
    with an open end, must not overlap any existing incumbency interval on that
    position, whether that prior incumbency is still ACTIVE or already VACATED; an
    overlap is rejected with ERR_INCUMBENCY_OVERLAP." PRD §3.4: "its end_date is
    set to the supplied vacate_date (inclusive)".

    Design: Difficulty/resource_temporal_overlap/rto_incumbency_inclusive_boundary_overlap
    """
    grade, cc, pos = fixtures.setup_funded_vacant_position(pos_overrides={"fte": 0.5})
    e1 = fixtures.create_employee(annual_salary_cents=13000000)
    e2 = fixtures.create_employee(annual_salary_cents=13000000)
    inc1 = fixtures.fill_position(pos["id"], e1["id"], start_date="2026-01-01")
    api.vacate_incumbent(inc1["id"], factories.vacate_payload("2026-06-30"), hrbp_headers)

    # Refill starting exactly on the inclusive end 2026-06-30 collides.
    resp = api.create_incumbent(
        pos["id"], factories.create_incumbent_payload(e2["id"], "2026-06-30"), hrbp_headers
    )
    validate_error(resp, ApiErrorId.ERR_INCUMBENCY_OVERLAP.value)

    position = fixtures.get_position(pos["id"])
    assert position["occupancy_status"] == "VACANT", \
        f"Position must stay VACANT, got {position['occupancy_status']}"


def test_refill_started_inside_vacated_interval_rejected(api, hrbp_headers):
    """PRD §3.4: "the new occupancy interval, running from start_date forward
    with an open end, must not overlap any existing incumbency interval on that
    position, whether that prior incumbency is still ACTIVE or already VACATED; an
    overlap is rejected with ERR_INCUMBENCY_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/rto_incumbency_inclusive_boundary_overlap
    """
    grade, cc, pos = fixtures.setup_funded_vacant_position(pos_overrides={"fte": 0.5})
    e1 = fixtures.create_employee(annual_salary_cents=13000000)
    e2 = fixtures.create_employee(annual_salary_cents=13000000)
    inc1 = fixtures.fill_position(pos["id"], e1["id"], start_date="2026-01-01")
    api.vacate_incumbent(inc1["id"], factories.vacate_payload("2026-06-30"), hrbp_headers)

    # Position is VACANT, but a refill whose start lands strictly inside the prior
    # [2026-01-01, 2026-06-30] interval overlaps it.
    resp = api.create_incumbent(
        pos["id"], factories.create_incumbent_payload(e2["id"], "2026-03-01"), hrbp_headers
    )
    validate_error(resp, ApiErrorId.ERR_INCUMBENCY_OVERLAP.value)

    position = fixtures.get_position(pos["id"])
    assert position["occupancy_status"] == "VACANT", \
        f"Position must stay VACANT, got {position['occupancy_status']}"


# ===========================================================================
# Fill precondition errors (Corner)
# ===========================================================================
def test_salary_above_band_max_rejects_fill(api, hrbp_headers):
    """PRD §3.4: "the employee's annual_salary_cents must lie within the grade
    band — at least band_min_cents and at most band_max_cents, inclusive at both
    ends — or the fill is rejected with ERR_SALARY_OUT_OF_BAND."

    Design: Corner/calculations/calc_salary_out_of_band_rejects_fill
    """
    # G07 band_max 15000000; employee salary 16000000 is above band.
    grade, cc, pos = fixtures.setup_funded_vacant_position(pos_overrides={"fte": 0.5})
    emp = fixtures.create_employee(annual_salary_cents=16000000)

    resp = api.create_incumbent(pos["id"], factories.create_incumbent_payload(emp["id"], "2026-01-01"), hrbp_headers)
    validate_error(resp, ApiErrorId.ERR_SALARY_OUT_OF_BAND.value)

    position = fixtures.get_position(pos["id"])
    assert position["occupancy_status"] == "VACANT", \
        f"Position must stay VACANT, got {position['occupancy_status']}"


def test_assigned_employee_cannot_fill_second_position(api, hrbp_headers):
    """PRD §3.4: "the chosen employee's status must be AVAILABLE (else
    ERR_EMPLOYEE_UNAVAILABLE)." PRD §3.1: "an employee becomes ASSIGNED only while
    actively occupying a position".

    Design: Corner/validations/val_employee_unavailable_rejects_second_fill
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    p1 = fixtures.create_funded_position(cc["id"], grade["id"], title="P1", fte=0.5)
    p2 = fixtures.create_funded_position(cc["id"], grade["id"], title="P2", fte=0.5)
    emp = fixtures.create_employee(annual_salary_cents=13000000)
    fixtures.fill_position(p1["id"], emp["id"])  # emp now ASSIGNED

    resp = api.create_incumbent(p2["id"], factories.create_incumbent_payload(emp["id"], "2026-01-01"), hrbp_headers)
    validate_error(resp, ApiErrorId.ERR_EMPLOYEE_UNAVAILABLE.value)

    position = fixtures.get_position(p2["id"])
    assert position["occupancy_status"] == "VACANT", \
        f"P2 must stay VACANT, got {position['occupancy_status']}"


def test_filling_already_filled_position_rejected(api, hrbp_headers):
    """PRD §3.4: "it must currently be VACANT (else ERR_POSITION_ALREADY_FILLED)".

    Design: Corner/validations/val_already_filled_rejects_double_fill
    """
    grade, cc, pos, emp, inc = fixtures.setup_filled_position(employee_salary_cents=13000000)
    e2 = fixtures.create_employee(annual_salary_cents=13000000)

    resp = api.create_incumbent(pos["id"], factories.create_incumbent_payload(e2["id"], "2026-01-01"), hrbp_headers)
    validate_error(resp, ApiErrorId.ERR_POSITION_ALREADY_FILLED.value)


def test_existence_checked_before_state_on_lifecycle(api, hrbp_headers):
    """PRD §2.4: "If any path segment or referenced resource does not exist, the
    request fails with ERR_NOT_FOUND (HTTP 404) before any business rule is
    evaluated."

    Design: Corner/validations/val_priority_existence_before_state
    """
    resp = api.position_lifecycle(
        NON_EXISTENT_UUID, factories.lifecycle_payload("REQUISITION"), hrbp_headers
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# RBAC — approval-chain exclusivity
# ===========================================================================
def test_hrbp_cannot_fund_position(api, hrbp_headers):
    """PRD §2.1: "A Finance Controller (FinanceController) owns cost centers,
    funds positions". PRD §2.1: "If the role is recognized but is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN
    (HTTP 403)."

    Design: Corner/rbac/rbac_hrbp_cannot_fund_position
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    v0 = cc["version"]
    p1 = fixtures.create_requisitioned_position(cc["id"], grade["id"], title="P1", fte=0.5)

    resp = api.position_lifecycle(
        p1["id"], factories.lifecycle_payload("FUND", expected_cost_center_version=v0), hrbp_headers
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    position = fixtures.get_position(p1["id"])
    assert position["lifecycle_status"] == "REQUISITIONED", \
        f"Position must stay REQUISITIONED, got {position['lifecycle_status']}"


def test_hrbp_cannot_create_grade(api, hrbp_headers):
    """PRD §2.1: "A Compensation Analyst (CompensationAnalyst) owns grade bands".
    PRD §2.1: "If the role is recognized but is not permitted to perform the
    requested operation, the request is rejected with ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/rbac_hrbp_cannot_create_grade
    """
    resp = api.create_grade(factories.create_grade_payload(code="G07", rank=7), hrbp_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_finance_cannot_approve_reclass(api, finance_headers):
    """PRD §2.1: "An HR Director (HRDirector) is the final approver: only this
    role can approve or reject a reclassification".

    Design: Corner/rbac/rbac_finance_cannot_approve_reclass
    """
    cc, pos, g_from, g_to, rr = fixtures.setup_reclass_under_review()
    resp = api.approve_reclass_request(rr["id"], factories.approve_reclass_payload(), finance_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    reclass = get_success_data(api.get_reclass_request(rr["id"], finance_headers))
    assert reclass["status"] == "UNDER_REVIEW", \
        f"Reclass must stay UNDER_REVIEW, got {reclass['status']}"


def test_unrecognised_role_rejected_unauthenticated(api, intruder_headers):
    """PRD §2.1: "If X-User-Role is absent or names a value outside this set, the
    request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/rbac_unauthenticated_missing_role_header
    """
    resp = api.create_cost_center(factories.create_cost_center_payload(), intruder_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
