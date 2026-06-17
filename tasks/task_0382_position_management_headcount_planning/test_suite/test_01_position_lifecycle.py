"""Position funding lifecycle, the parallel occupancy axis, fund-admission
boundaries, and cost-center optimistic concurrency.

Queue A (Difficulty): non_linear_state_machine, combinatorial_formula,
boundary_precision_check, cross_entity_state_dependency.
Queue B (Corner): cross_cutting_complexity_layers (OCC).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, fixtures, factories,
)


# ===========================================================================
# Parallel lifecycle x occupancy state machine
# ===========================================================================
def test_fill_then_vacate_keeps_funded_while_occupancy_cycles(api, hrbp_headers):
    """PRD §3.4: "the position returns to occupancy_status VACANT, and the
    employee's status returns to AVAILABLE." PRD §2.4 and §3.3 establish
    lifecycle_status (funding) and occupancy_status (vacancy) as independent
    axes; vacating touches only occupancy, leaving the position FUNDED.

    Design: Difficulty/non_linear_state_machine/nlsm_position_parallel_lifecycle_x_occupancy
    """
    grade, cc, pos, emp, inc = fixtures.setup_filled_position(employee_salary_cents=13000000)
    resp = api.vacate_incumbent(inc["id"], factories.vacate_payload("2026-06-30"), hrbp_headers)
    validate_success(resp, 200)

    position = fixtures.get_position(pos["id"])
    assert position["occupancy_status"] == "VACANT", \
        f"Expected VACANT after vacate, got {position['occupancy_status']}"
    assert position["lifecycle_status"] == "FUNDED", \
        f"Expected lifecycle to stay FUNDED, got {position['lifecycle_status']}"

    incumbent = get_success_data(api.get_incumbent(inc["id"], hrbp_headers))
    assert incumbent["status"] == "VACATED", \
        f"Expected incumbent VACATED, got {incumbent['status']}"


def test_vacate_returns_employee_to_available(api, hrbp_headers):
    """PRD §3.4: "the position returns to occupancy_status VACANT, and the
    employee's status returns to AVAILABLE."

    Design: Difficulty/non_linear_state_machine/nlsm_position_parallel_lifecycle_x_occupancy
    """
    grade, cc, pos, emp, inc = fixtures.setup_filled_position(employee_salary_cents=13000000)
    api.vacate_incumbent(inc["id"], factories.vacate_payload("2026-06-30"), hrbp_headers)

    employee = get_success_data(api.get_employee(emp["id"], hrbp_headers))
    assert employee["status"] == "AVAILABLE", \
        f"Expected employee AVAILABLE after vacate, got {employee['status']}"


# ===========================================================================
# Fund admission — combinatorial nested min/max (mode a)
# ===========================================================================
def test_fund_at_exact_budget_and_fte_headroom_admitted(api, finance_headers):
    """PRD §3.3: "The position is admitted only when the added FTE is less than
    or equal to the FTE headroom and the added cost is less than or equal to the
    budget headroom — with both comparisons admitting equality, so a position
    whose FTE or cost exactly consumes the remaining headroom is allowed."

    Design: Difficulty/combinatorial_formula/cf_fund_admission_nested_minmax_mode_a
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Ops", annual_budget_cents=12000000, fte_cap=1.0)
    # P1 funded: committed_fte 0.5, committed_cost 6000000, available 6000000.
    fixtures.create_funded_position(cc["id"], grade["id"], title="P1", fte=0.5)
    # P2: delta fte 0.5 == headroom 0.5, delta cost 6000000 == headroom 6000000.
    p2 = fixtures.create_requisitioned_position(cc["id"], grade["id"], title="P2", fte=0.5)

    v = fixtures.cost_center_version(cc["id"])
    resp = api.position_lifecycle(
        p2["id"], factories.lifecycle_payload("FUND", expected_cost_center_version=v), finance_headers
    )
    data = validate_success(resp, 200)
    assert data["lifecycle_status"] == "FUNDED", \
        f"Expected FUNDED at exact headroom, got {data['lifecycle_status']}"

    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["committed_fte"] == 1.0, f"Expected committed_fte 1.0, got {cost_center['committed_fte']}"
    assert cost_center["committed_cost_cents"] == 12000000, \
        f"Expected committed_cost 12000000, got {cost_center['committed_cost_cents']}"
    assert cost_center["available_budget_cents"] == 0, \
        f"Expected available 0, got {cost_center['available_budget_cents']}"


def test_fund_combinatorial_admission_returns_funded_position(api, finance_headers):
    """PRD §3.3: "the cost being added is the position's planned_cost_cents. The
    position is admitted only when the added FTE is less than or equal to the FTE
    headroom and the added cost is less than or equal to the budget headroom".

    Design: Difficulty/combinatorial_formula/cf_fund_admission_nested_minmax_mode_a
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Ops", annual_budget_cents=12000000, fte_cap=1.0)
    fixtures.create_funded_position(cc["id"], grade["id"], title="P1", fte=0.5)
    p2 = fixtures.create_requisitioned_position(cc["id"], grade["id"], title="P2", fte=0.5)

    p2_funded = fixtures.fund_position(p2["id"], cc["id"])
    assert p2_funded["lifecycle_status"] == "FUNDED"


# ===========================================================================
# Boundary precision — FTE cap exact-equal admit, one-step-over reject
# ===========================================================================
def test_fund_makes_committed_fte_exactly_equal_cap_admitted(api, finance_headers):
    """PRD §3.3: "with both comparisons admitting equality, so a position whose
    FTE or cost exactly consumes the remaining headroom is allowed."

    Design: Difficulty/boundary_precision_check/bpc_fte_cap_exact_equal_admitted
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Cap", annual_budget_cents=100000000, fte_cap=1.0)
    p1 = fixtures.create_funded_position(cc["id"], grade["id"], title="P1", fte=1.0)
    assert p1["lifecycle_status"] == "FUNDED"

    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["committed_fte"] == 1.0, \
        f"Expected committed_fte exactly 1.0, got {cost_center['committed_fte']}"


def test_fund_crossing_fte_cap_rejected(api, finance_headers):
    """PRD §3.3: "If the FTE being added exceeds the FTE headroom, funding is
    rejected with ERR_FTE_CAP_EXCEEDED (HTTP 409)."

    Design: Difficulty/boundary_precision_check/bpc_fte_cap_exact_equal_admitted
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Cap", annual_budget_cents=100000000, fte_cap=1.0)
    fixtures.create_funded_position(cc["id"], grade["id"], title="P1", fte=1.0)
    # committed_fte now exactly 1.0; a further 0.01 crosses to 1.01 > 1.0.
    p2 = fixtures.create_requisitioned_position(cc["id"], grade["id"], title="P2", fte=0.01)

    v = fixtures.cost_center_version(cc["id"])
    resp = api.position_lifecycle(
        p2["id"], factories.lifecycle_payload("FUND", expected_cost_center_version=v), finance_headers
    )
    validate_error(resp, ApiErrorId.ERR_FTE_CAP_EXCEEDED.value)

    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["committed_fte"] == 1.0, \
        f"committed_fte must stay 1.0 after rejected fund, got {cost_center['committed_fte']}"


# ===========================================================================
# Cross-entity state dependency — fund gated on cost-center posture
# ===========================================================================
def test_fund_blocked_when_cost_center_frozen(api, finance_headers):
    """PRD §2.9: "While a cost center is FROZEN, a set of growth-oriented
    operations is blocked and rejected with ERR_COST_CENTER_FROZEN (HTTP 409):
    requisitioning a position, funding a position, filling a position with an
    incumbent, approving a requisition, and approving a reclassification."

    Design: Difficulty/cross_entity_state_dependency/cesd_fund_requires_cost_center_open
    """
    fixtures.set_clock("2026-02-01T00:00:00Z")
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    p1 = fixtures.create_requisitioned_position(cc["id"], grade["id"], title="P1", fte=0.5)
    fixtures.open_freeze_order(cc["id"], "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z")

    v = fixtures.cost_center_version(cc["id"])
    resp = api.position_lifecycle(
        p1["id"], factories.lifecycle_payload("FUND", expected_cost_center_version=v), finance_headers
    )
    validate_error(resp, ApiErrorId.ERR_COST_CENTER_FROZEN.value)

    position = fixtures.get_position(p1["id"])
    assert position["lifecycle_status"] == "REQUISITIONED", \
        f"Position must stay REQUISITIONED, got {position['lifecycle_status']}"


def test_requisition_blocked_when_cost_center_frozen(api, hrbp_headers):
    """PRD §3.3: "this is permitted only while the position is DRAFT and the
    owning cost center's posture is OPEN, otherwise the request is rejected with
    ERR_COST_CENTER_FROZEN."

    Design: Difficulty/cross_entity_state_dependency/cesd_fund_requires_cost_center_open
    """
    fixtures.set_clock("2026-02-01T00:00:00Z")
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    p1 = fixtures.create_position(cc["id"], grade["id"], title="P1", fte=0.5)  # DRAFT
    fixtures.open_freeze_order(cc["id"], "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z")

    resp = api.position_lifecycle(p1["id"], factories.lifecycle_payload("REQUISITION"), hrbp_headers)
    validate_error(resp, ApiErrorId.ERR_COST_CENTER_FROZEN.value)

    position = fixtures.get_position(p1["id"])
    assert position["lifecycle_status"] == "DRAFT", \
        f"Position must stay DRAFT under freeze, got {position['lifecycle_status']}"


def test_fill_blocked_when_position_not_funded(api, hrbp_headers):
    """PRD §3.4: "The preconditions are layered: the position must be FUNDED
    (else ERR_POSITION_NOT_FUNDED)".

    Design: Difficulty/cross_entity_state_dependency/cesd_fill_requires_position_funded
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center()
    p1 = fixtures.create_requisitioned_position(cc["id"], grade["id"], title="P1", fte=0.5)
    emp = fixtures.create_employee(annual_salary_cents=13000000)

    resp = api.create_incumbent(p1["id"], factories.create_incumbent_payload(emp["id"], "2026-01-01"), hrbp_headers)
    validate_error(resp, ApiErrorId.ERR_POSITION_NOT_FUNDED.value)

    position = fixtures.get_position(p1["id"])
    assert position["occupancy_status"] == "VACANT", \
        f"Position must stay VACANT, got {position['occupancy_status']}"
    employee = get_success_data(api.get_employee(emp["id"], hrbp_headers))
    assert employee["status"] == "AVAILABLE", \
        f"Employee must stay AVAILABLE, got {employee['status']}"


def test_fill_on_draft_position_blocked_not_funded(api, hrbp_headers):
    """PRD §3.4: "the position must be FUNDED (else ERR_POSITION_NOT_FUNDED)".

    Design: Difficulty/cross_entity_state_dependency/cesd_fill_requires_position_funded
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center()
    p1 = fixtures.create_position(cc["id"], grade["id"], title="P1", fte=0.5)  # DRAFT
    emp = fixtures.create_employee(annual_salary_cents=13000000)

    resp = api.create_incumbent(p1["id"], factories.create_incumbent_payload(emp["id"], "2026-01-01"), hrbp_headers)
    validate_error(resp, ApiErrorId.ERR_POSITION_NOT_FUNDED.value)

    position = fixtures.get_position(p1["id"])
    assert position["occupancy_status"] == "VACANT", \
        f"Position must stay VACANT, got {position['occupancy_status']}"


# ===========================================================================
# Optimistic concurrency on the cost-center pool (Corner)
# ===========================================================================
def test_fund_with_stale_cost_center_version_rejected(api, finance_headers):
    """PRD §2.6: "If another writer has advanced that version since the client
    last read it — for example by funding a different position, which shrank
    available_budget_cents and raised committed_fte — the fund request is
    rejected with ERR_STALE_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_fund_correct_version_succeeds_then_stale_rejected
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    v0 = cc["version"]
    p1 = fixtures.create_requisitioned_position(cc["id"], grade["id"], title="P1", fte=0.5)
    p2 = fixtures.create_requisitioned_position(cc["id"], grade["id"], title="P2", fte=0.5)

    # First fund with the observed version succeeds and bumps CC.version.
    resp1 = api.position_lifecycle(
        p1["id"], factories.lifecycle_payload("FUND", expected_cost_center_version=v0), finance_headers
    )
    validate_success(resp1, 200)

    # Second fund carrying the now-stale (pre-bump) version is rejected.
    resp2 = api.position_lifecycle(
        p2["id"], factories.lifecycle_payload("FUND", expected_cost_center_version=v0), finance_headers
    )
    validate_error(resp2, ApiErrorId.ERR_STALE_VERSION.value)

    position = fixtures.get_position(p2["id"])
    assert position["lifecycle_status"] == "REQUISITIONED", \
        f"P2 must stay REQUISITIONED after stale fund, got {position['lifecycle_status']}"


def test_position_version_increments_by_one_per_mutation(api, hrbp_headers):
    """PRD §2.4: "an integer version that begins at 1 on creation and increments
    by exactly 1 on each mutation."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_write
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center()
    pos = fixtures.create_position(cc["id"], grade["id"], title="P1", fte=0.5)
    assert pos["version"] == 1, f"Position.version must start at 1, got {pos['version']}"

    requisitioned = get_success_data(
        api.position_lifecycle(pos["id"], factories.lifecycle_payload("REQUISITION"), hrbp_headers)
    )
    assert requisitioned["version"] == 2, \
        f"Position.version must be 2 after REQUISITION, got {requisitioned['version']}"
