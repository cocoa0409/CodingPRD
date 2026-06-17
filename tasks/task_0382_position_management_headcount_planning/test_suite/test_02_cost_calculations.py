"""The plan-versus-actual cost doctrine: dual-variant cost on positions and
cost centers, per-position rounding before aggregation, conservation across
fill/vacate, and derived-field reconciliation.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula (mode b),
compensating_invariant.
Queue B (Corner): cross_cutting_complexity_layers (derived reconciliation),
consistency_model, calculations (computed planned cost).
"""
from test_helpers import (
    validate_success, get_success_data,
    fixtures, factories,
)


# ===========================================================================
# Dual-variant cost: planned (midpoint) vs actual (incumbent salary)
# ===========================================================================
def test_filled_position_swaps_committed_cost_to_actual_basis(api, hrbp_headers):
    """PRD §3.4: "the cost center swaps this position's contribution from its
    planned basis to its actual basis when recomputing committed_cost_cents".
    PRD §3.4: "The position's actual_cost_cents is then computed as the incumbent
    employee's annual_salary_cents multiplied by the position's fte, rounded half
    up to whole cents."

    Design: Difficulty/dual_variant_calc/dvc_position_cost_planned_vs_actual
    """
    # G07 mid 12000000, fte 0.5 -> planned 6000000. Salary 15000000 (band_max)
    # -> actual 7500000.
    grade, cc, pos = fixtures.setup_funded_vacant_position(pos_overrides={"fte": 0.5})
    assert pos["planned_cost_cents"] == 6000000, \
        f"Expected planned 6000000, got {pos['planned_cost_cents']}"

    emp = fixtures.create_employee(annual_salary_cents=15000000)
    fixtures.fill_position(pos["id"], emp["id"])

    position = fixtures.get_position(pos["id"])
    assert position["planned_cost_cents"] == 6000000, \
        f"planned_cost_cents stays 6000000, got {position['planned_cost_cents']}"
    assert position["actual_cost_cents"] == 7500000, \
        f"Expected actual 7500000, got {position['actual_cost_cents']}"

    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["committed_cost_cents"] == 7500000, \
        f"committed_cost must follow actual basis 7500000, got {cost_center['committed_cost_cents']}"


def test_vacant_funded_position_contributes_planned_midpoint(api):
    """PRD §2.7: "A funded position that is currently vacant is costed at its
    grade's midpoint — a forward-looking estimate of what filling it will cost".

    Design: Difficulty/dual_variant_calc/dvc_position_cost_planned_vs_actual
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    pos = fixtures.create_funded_position(cc["id"], grade["id"], title="Engineer", fte=0.5)
    assert pos["actual_cost_cents"] == 0, \
        f"Vacant position actual_cost must be 0, got {pos['actual_cost_cents']}"

    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["committed_cost_cents"] == 6000000, \
        f"committed_cost follows planned midpoint 6000000, got {cost_center['committed_cost_cents']}"


# ===========================================================================
# Forecast plan-vs-actual FTE (distinct dual-variant domain)
# ===========================================================================
def test_snapshot_captures_actual_fte_and_negative_variance(api, finance_headers):
    """PRD §3.9: "the period's actual_fte is captured as the owning cost center's
    filled_fte at that instant ... and variance_fte is computed as that actual_fte
    minus the period's planned_fte, also to two decimals. The period's status
    becomes SNAPSHOTTED".

    Design: Difficulty/dual_variant_calc/dvc_forecast_planned_vs_actual_fte
    """
    # One FILLED position of fte 0.5 -> filled_fte 0.5. planned_fte 2.0 -> variance -1.5.
    grade, cc, pos, emp, inc = fixtures.setup_filled_position(employee_salary_cents=13000000)
    fp = fixtures.create_forecast_period(cc["id"], fiscal_label="FY26-Q1", planned_fte=2.0)

    v = fixtures.cost_center_version(cc["id"])
    resp = api.snapshot_forecast_period(fp["id"], factories.snapshot_payload(v), finance_headers)
    data = validate_success(resp, 200)

    assert data["actual_fte"] == 0.5, f"Expected actual_fte 0.5, got {data['actual_fte']}"
    assert data["variance_fte"] == -1.5, f"Expected variance_fte -1.5, got {data['variance_fte']}"
    assert data["status"] == "SNAPSHOTTED", f"Expected SNAPSHOTTED, got {data['status']}"


def test_snapshot_freezes_period_status_to_snapshotted(api, finance_headers):
    """PRD §3.9: "The period's status becomes SNAPSHOTTED, which freezes both
    figures."

    Design: Difficulty/dual_variant_calc/dvc_forecast_planned_vs_actual_fte
    """
    grade, cc, pos, emp, inc = fixtures.setup_filled_position(employee_salary_cents=13000000)
    fp = fixtures.create_forecast_period(cc["id"], fiscal_label="FY26-Q1", planned_fte=2.0)
    snapped = fixtures.snapshot_forecast_period(fp["id"], cc["id"])
    assert snapped["status"] == "SNAPSHOTTED"
    assert snapped["actual_fte"] == 0.5, f"Expected actual_fte 0.5, got {snapped['actual_fte']}"


# ===========================================================================
# Per-position rounding before aggregation (combinatorial mode b)
# ===========================================================================
def test_committed_cost_rounds_per_position_then_sums(api, finance_headers):
    """PRD §2.7: "each position's planned or actual cost is rounded to whole
    cents first, and a cost center's committed cost is then the exact integer
    sum of those already-rounded per-position contributions. The system never
    multiplies many positions together and rounds once at the end."

    Design: Difficulty/combinatorial_formula/cf_committed_cost_round_per_position_then_sum_mode_b
    """
    # GH mid 10000001, fte 0.5 -> 5000000.5 -> round half-up 5000001 per position.
    gh = fixtures.create_grade_gh()
    cc = fixtures.create_cost_center(name="Round", annual_budget_cents=50000000, fte_cap=5.0)
    pa = fixtures.create_funded_position(cc["id"], gh["id"], title="Pa", fte=0.5)
    pb = fixtures.create_funded_position(cc["id"], gh["id"], title="Pb", fte=0.5)

    assert pa["planned_cost_cents"] == 5000001, \
        f"Pa planned must round to 5000001, got {pa['planned_cost_cents']}"
    assert pb["planned_cost_cents"] == 5000001, \
        f"Pb planned must round to 5000001, got {pb['planned_cost_cents']}"

    cost_center = fixtures.get_cost_center(cc["id"])
    # round-then-sum: 5000001 + 5000001 = 10000002 (not the sum-then-round 10000001).
    assert cost_center["committed_cost_cents"] == 10000002, \
        f"committed_cost must be 10000002 (round-per-position-then-sum), got {cost_center['committed_cost_cents']}"


def test_single_position_planned_cost_rounds_half_up(api):
    """PRD §2.7: "Wherever a multiplication produces a fractional cent, the
    result is rounded half up to a whole number of cents."

    Design: Difficulty/combinatorial_formula/cf_committed_cost_round_per_position_then_sum_mode_b
    """
    gh = fixtures.create_grade_gh()
    cc = fixtures.create_cost_center(name="Round", annual_budget_cents=50000000, fte_cap=5.0)
    pa = fixtures.create_position(cc["id"], gh["id"], title="Pa", fte=0.5)
    # 10000001 * 0.5 = 5000000.5 -> 5000001.
    assert pa["planned_cost_cents"] == 5000001, \
        f"planned must round half-up to 5000001, got {pa['planned_cost_cents']}"


# ===========================================================================
# Compensating invariants
# ===========================================================================
def test_fill_then_vacate_conserves_committed_cost(api, hrbp_headers):
    """PRD §3.4: "Because the basis swings planned → actual → planned across a
    fill-then-vacate, the cost center's committed cost ends exactly where it
    began."

    Design: Difficulty/compensating_invariant/ci_fill_then_vacate_conserves_committed_cost
    """
    # planned 6000000; fill (salary 15000000 -> actual 7500000); vacate restores planned.
    grade, cc, pos = fixtures.setup_funded_vacant_position(pos_overrides={"fte": 0.5})
    before = fixtures.get_cost_center(cc["id"])
    assert before["committed_cost_cents"] == 6000000

    emp = fixtures.create_employee(annual_salary_cents=15000000)
    inc = fixtures.fill_position(pos["id"], emp["id"])
    api.vacate_incumbent(inc["id"], factories.vacate_payload("2026-06-30"), hrbp_headers)

    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["committed_cost_cents"] == 6000000, \
        f"committed_cost must return to 6000000, got {cost_center['committed_cost_cents']}"
    position = fixtures.get_position(pos["id"])
    assert position["actual_cost_cents"] == 0, \
        f"actual_cost must revert to 0, got {position['actual_cost_cents']}"
    employee = get_success_data(api.get_employee(emp["id"], hrbp_headers))
    assert employee["status"] == "AVAILABLE", \
        f"employee must be AVAILABLE, got {employee['status']}"


def test_fill_then_vacate_returns_available_budget_to_start(api, hrbp_headers):
    """PRD §2.7: "This is why filling a position and later vacating it leaves the
    cost center's committed cost exactly where it started: the basis swings from
    planned to actual and back to planned, conserving the commitment."

    Design: Difficulty/compensating_invariant/ci_fill_then_vacate_conserves_committed_cost
    """
    grade, cc, pos = fixtures.setup_funded_vacant_position(pos_overrides={"fte": 0.5})
    before = fixtures.get_cost_center(cc["id"])
    available_before = before["available_budget_cents"]

    emp = fixtures.create_employee(annual_salary_cents=15000000)  # actual diverges from planned
    inc = fixtures.fill_position(pos["id"], emp["id"])
    api.vacate_incumbent(inc["id"], factories.vacate_payload("2026-06-30"), hrbp_headers)

    after = fixtures.get_cost_center(cc["id"])
    assert after["available_budget_cents"] == available_before, \
        f"available_budget must return to {available_before}, got {after['available_budget_cents']}"
    assert after["filled_fte"] == 0, \
        f"filled_fte must return to 0 after vacate, got {after['filled_fte']}"


# ===========================================================================
# Derived-field reconciliation & immediate consistency (Corner)
# ===========================================================================
def test_available_budget_reconciles_inside_fund_request(api):
    """PRD §2.8: "available_budget_cents is the difference between the two" and
    "These derived fields ... are reconciled inside the very request that changes
    them, never lazily; a reader of a cost center always sees figures consistent
    with its children."

    Design: Corner/cross_cutting_complexity_layers/derived_available_budget_reconciles_after_fund
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    fixtures.create_funded_position(cc["id"], grade["id"], title="P1", fte=0.5)

    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["committed_cost_cents"] == 6000000, \
        f"Expected committed_cost 6000000, got {cost_center['committed_cost_cents']}"
    assert cost_center["available_budget_cents"] == 94000000, \
        f"Expected available 94000000, got {cost_center['available_budget_cents']}"
    assert cost_center["committed_fte"] == 0.5, \
        f"Expected committed_fte 0.5, got {cost_center['committed_fte']}"


def test_committed_cost_visible_immediately_after_fund(api, finance_headers):
    """PRD §2.8: "These derived fields ... are reconciled inside the very request
    that changes them, never lazily; a reader of a cost center always sees figures
    consistent with its children."

    Design: Corner/consistency_model/immediate_committed_cost_visible_in_fund_response
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    fixtures.create_funded_position(cc["id"], grade["id"], title="P1", fte=0.5)

    # A GET right after FUND already reflects the commitment.
    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["committed_cost_cents"] == 6000000, \
        f"committed_cost must be visible immediately, got {cost_center['committed_cost_cents']}"


def test_create_position_computes_planned_cost_ignoring_client_input(api, hrbp_headers):
    """PRD §3.2: "A position's planned_cost_cents is, at all times, its grade's
    band_mid_cents multiplied by its fte, rounded half up to whole cents."

    Design: Corner/entities/entity_position_computed_planned_cost_input_ignored
    """
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center()
    # G07 mid 12000000 * 0.5 = 6000000, regardless of any client-sent cost field.
    pos = fixtures.create_position(cc["id"], grade["id"], title="P1", fte=0.5)
    assert pos["planned_cost_cents"] == 6000000, \
        f"Expected planned 6000000, got {pos['planned_cost_cents']}"
    assert pos["actual_cost_cents"] == 0, \
        f"Expected actual 0 for vacant, got {pos['actual_cost_cents']}"
    assert pos["span_of_control"] == 0, \
        f"Expected span_of_control 0, got {pos['span_of_control']}"


