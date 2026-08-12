"""Dual-variant and combinatorial cost-forecast calculations (PRD §3.6)."""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    create_active_program, create_and_execute_contract, create_contract,
    begin_negotiation, counter_contract, create_change_order, submit_change_order,
    recommend_change_order, decide_change_order, create_risk_entry, assess_risk,
    mitigate_risk, monitor_risk, create_drawdown, create_owner_report,
    pm_headers, exec_headers, owner_headers,
)


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / cost_forecast_commitment_vs_trend_variants
# ---------------------------------------------------------------------------

def _setup_eac_scenario():
    """Build the exact state from the difficulty instance.

    Returns (program_id, report_dict) with both EAC variants populated.
    """
    prog = create_active_program(
        total_budget_cents=10_000_000,
        contingency_total_cents=1_000_000,
        lines=[
            {"cost_code": "CC-100", "amount_cents": 6_000_000},
            {"cost_code": "CC-200", "amount_cents": 4_000_000},
        ],
        name="P-EAC",
    )
    pid = prog["id"]

    # CT1 EXECUTED 4_500_000 with CO1 APPROVED 200_000
    ct1 = create_and_execute_contract(pid, 4_500_000, solicitation_estimate_cents=5_000_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    co1 = create_change_order(ct1["id"], amount_cents=200_000, title="CO1", reason="scope")
    submit_change_order(co1["id"])
    recommend_change_order(co1["id"], recommendation="APPROVE", analysis_note="ok")
    decide_change_order(co1["id"], decision="APPROVE")

    # CT2 SOLICITED estimate 1_000_000
    create_contract(pid, solicitation_estimate_cents=1_000_000,
                     vendor_name="V2", contract_type="CONSULTANT")

    # CT3 COUNTERED latest counter 1_800_000
    ct3 = create_contract(pid, solicitation_estimate_cents=2_000_000,
                           vendor_name="V3", contract_type="CONTRACTOR")
    begin_negotiation(ct3["id"])
    counter_contract(ct3["id"], 1_800_000)

    # CO2 UNDER_REVIEW 150_000
    co2 = create_change_order(ct1["id"], amount_cents=150_000, title="CO2", reason="pending")
    submit_change_order(co2["id"])

    # R1 ASSESSED exposure 200_000; R2 ESCALATED exposure 50_000_000
    r1 = create_risk_entry(pid, probability_pct=50, impact_cents=400_000,
                            title="R1", category="COST")
    assess_risk(r1["id"], 50, 400_000)

    r2 = create_risk_entry(pid, probability_pct=50, impact_cents=100_000_000,
                            title="R2", category="SCHEDULE")
    assess_risk(r2["id"], 50, 100_000_000)

    return pid


def test_eac_commitment_based_literal_value(api):
    """PRD §3.6: "The COMMITMENT_BASED variant — the optimistic book of record,
    always computed into eac_commitment_based_cents — is committed plus estimated
    plus the full, unweighted sum of exposure_cents across the risk set (every
    considered status contributes at a multiplier of 1.0), with no
    pending-change-order allowance and no floor."

    Design: Difficulty/dual_variant_calc/cost_forecast_commitment_vs_trend_variants
    """
    pid = _setup_eac_scenario()
    rep = create_owner_report(pid, period="2026-08")
    # committed = 4_500_000 + 200_000 = 4_700_000
    # estimated = 1_000_000 (SOLICITED) + 1_800_000 (COUNTERED latest) = 2_800_000
    # full exposure = 200_000 + 50_000_000 = 50_200_000
    # total = 4_700_000 + 2_800_000 + 50_200_000 = 57_700_000
    assert rep["eac_commitment_based_cents"] == 57_700_000, (
        f"Expected 57700000, got {rep['eac_commitment_based_cents']}"
    )


def test_eac_trend_based_literal_value(api):
    """PRD §3.6: "The TREND_BASED variant — risk-adjusted, always computed into
    eac_trend_based_cents — weights each considered risk's exposure_cents by
    status: 1.00 for ESCALATED, 0.50 for MONITORING, 0.35 for MITIGATING, and
    0.25 for ASSESSED. It then adds a pending-change-order allowance: the sum of
    amount_cents over change orders in UNDER_REVIEW, RECOMMEND_APPROVAL, or
    RECOMMEND_REJECTION (change orders still in DRAFT are excluded as not yet
    submitted), taken in full when the program's posture is CRITICAL and halved
    otherwise."

    Design: Difficulty/dual_variant_calc/cost_forecast_commitment_vs_trend_variants
    """
    pid = _setup_eac_scenario()
    rep = create_owner_report(pid, period="2026-08")
    # weighted exposure = 200_000*0.25 + 50_000_000*1.00 = 50_000 + 50_000_000 = 50_050_000
    # pending_co = 150_000 (UNDER_REVIEW) * 0.50 (NORMAL posture) = 75_000
    # eac = 4_700_000 + 2_800_000 + 50_050_000 + 75_000 = 57_625_000
    assert rep["eac_trend_based_cents"] == 57_625_000, (
        f"Expected 57625000, got {rep['eac_trend_based_cents']}"
    )


def test_eac_variants_diverge_and_variances(api):
    """PRD §3.6: "Two variances complete the forecast:
    budget_variance_commitment_cents is current_budget_cents minus
    eac_commitment_based_cents, and budget_variance_trend_cents is
    current_budget_cents minus eac_trend_based_cents."

    Design: Difficulty/dual_variant_calc/cost_forecast_commitment_vs_trend_variants
    """
    pid = _setup_eac_scenario()
    rep = create_owner_report(pid, period="2026-08")
    assert rep["eac_commitment_based_cents"] - rep["eac_trend_based_cents"] == 75_000
    assert rep["budget_variance_commitment_cents"] == 10_000_000 - 57_700_000
    assert rep["budget_variance_trend_cents"] == 10_000_000 - 57_625_000
    # Posture must be NORMAL here: available = 1_000_000 - 200_000 (CO1) = 800_000 / 1_000_000 = 0.80
    assert rep["contingency_posture_snapshot"] == "NORMAL"


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / trend_eac_multibranch_formula
# ---------------------------------------------------------------------------

def _setup_trend_critical_scenario():
    """Program under CRITICAL posture; MONITORING risk; pending CO."""
    prog = create_active_program(
        total_budget_cents=10_000_000,
        contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}],
        name="P-TREND",
    )
    pid = prog["id"]
    ct1 = create_and_execute_contract(pid, 4_500_000,
                                       solicitation_estimate_cents=4_500_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    # CT2 SOLICITED 1_000_000
    create_contract(pid, solicitation_estimate_cents=1_000_000,
                     vendor_name="V2", contract_type="CONSULTANT")
    # CO UNDER_REVIEW 150_000 (submitted while NORMAL)
    co = create_change_order(ct1["id"], amount_cents=150_000, title="CO2", reason="pending")
    submit_change_order(co["id"])
    # Manual reserve 910_000 -> available 90_000 -> ratio 0.09 -> CRITICAL
    create_drawdown(pid, 910_000, purpose="reserve hold")
    # R1 -> MONITORING with exposure 200_000 (multiplier 0.50)
    r1 = create_risk_entry(pid, probability_pct=50, impact_cents=400_000,
                            title="R1", category="COST")
    assess_risk(r1["id"], 50, 400_000)
    mitigate_risk(r1["id"], mitigation_plan="mitigate")
    monitor_risk(r1["id"])
    return pid


def test_trend_critical_posture_snapshot(api):
    """PRD §2.7: "Otherwise, the ratio of contingency_available_cents to
    contingency_total_cents is compared against two inclusive floors: a ratio
    of at least 30 percent yields NORMAL; a ratio below 30 percent but at least
    10 percent yields WATCH; anything below 10 percent yields CRITICAL."

    Design: Difficulty/combinatorial_formula/trend_eac_multibranch_formula
    """
    pid = _setup_trend_critical_scenario()
    rep = create_owner_report(pid, period="2026-08")
    # available = 1_000_000 - 910_000 = 90_000; ratio = 0.09 < 0.10 -> CRITICAL
    assert rep["contingency_posture_snapshot"] == "CRITICAL"


def test_trend_critical_branch_uses_full_pending_allowance(api):
    """PRD §3.6: "It then adds a pending-change-order allowance: the sum of
    amount_cents over change orders in UNDER_REVIEW, RECOMMEND_APPROVAL, or
    RECOMMEND_REJECTION (change orders still in DRAFT are excluded as not yet
    submitted), taken in full when the program's posture is CRITICAL and halved
    otherwise."

    Design: Difficulty/combinatorial_formula/trend_eac_multibranch_formula
    """
    pid = _setup_trend_critical_scenario()
    rep = create_owner_report(pid, period="2026-08")
    # commitment variant: 4_500_000 + 1_000_000 + 200_000 = 5_700_000
    assert rep["eac_commitment_based_cents"] == 5_700_000
    # trend variant: 4_500_000 + 1_000_000 + 200_000*0.50 + 150_000*1.00 (CRITICAL) = 5_750_000
    assert rep["eac_trend_based_cents"] == 5_750_000


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / change_order_cost_code_rounding_order
# ---------------------------------------------------------------------------

def _setup_rounding_scenario():
    prog = create_active_program(
        total_budget_cents=3_000_000,
        contingency_total_cents=300_000,
        lines=[
            {"cost_code": "CC-100", "amount_cents": 1_000_000},
            {"cost_code": "CC-200", "amount_cents": 1_000_000},
            {"cost_code": "CC-300", "amount_cents": 1_000_000},
        ],
        name="P-ROUND",
    )
    pid = prog["id"]
    ct1 = create_and_execute_contract(pid, 1_000_000,
                                       solicitation_estimate_cents=1_000_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    co = create_change_order(ct1["id"], amount_cents=10, title="CO10", reason="rounding")
    submit_change_order(co["id"])
    recommend_change_order(co["id"], recommendation="APPROVE", analysis_note="ok")
    decided = decide_change_order(co["id"], decision="APPROVE")
    return pid, decided


def test_change_order_allocated_lines_pinned_rounding(api):
    """PRD §3.3: "Each exact share is then rounded half-up to a whole cent —
    per-line rounding happens first. If the rounded shares do not sum to the
    change amount, the residual difference is assigned to a single line, chosen
    deterministically: when the residual is positive it goes to the line whose
    exact share has the largest fractional part; when negative, to the line
    whose exact share has the smallest fractional part; ties are broken by
    cost_code in ascending lexicographic order, never by id."

    Design: Difficulty/combinatorial_formula/change_order_cost_code_rounding_order
    """
    _, co = _setup_rounding_scenario()
    # Each of 3 lines: exact = 10 * 1_000_000 / 3_000_000 = 3.333...
    # round_half_up each -> 3 (sum 9); residual +1; all fractions equal (0.333...),
    # tie broken by cost_code ascending -> CC-100 gets 4
    expected = [
        {"cost_code": "CC-100", "allocated_cents": 4},
        {"cost_code": "CC-200", "allocated_cents": 3},
        {"cost_code": "CC-300", "allocated_cents": 3},
    ]
    got = sorted(co["allocated_lines"], key=lambda x: x["cost_code"])
    assert got == expected, f"Expected {expected}, got {got}"


def test_change_order_allocated_lines_sum_matches_amount(api):
    """PRD §3.3: "Summing the partial allocations first and rounding once at
    the end is a different, forbidden order." Implies the per-line-first sum
    reconciles to exactly the change amount via the residual adjustment.

    Design: Difficulty/combinatorial_formula/change_order_cost_code_rounding_order
    """
    _, co = _setup_rounding_scenario()
    total = sum(line["allocated_cents"] for line in co["allocated_lines"])
    assert total == 10, f"Sum must equal amount_cents 10, got {total}"
    assert co["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / forecast_posture_evaluation_order
# ---------------------------------------------------------------------------

def _setup_eval_order_scenario():
    prog = create_active_program(
        total_budget_cents=10_000_000,
        contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}],
        name="P-ORDER",
    )
    pid = prog["id"]
    ct1 = create_and_execute_contract(pid, 4_500_000,
                                       solicitation_estimate_cents=4_500_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    # Manual reserve 750_000 -> available 250_000 -> ratio 0.25 -> WATCH
    create_drawdown(pid, 750_000, purpose="reserve")
    # Pending CO 200_000 (UNDER_REVIEW) — must NOT be deducted from pool
    co = create_change_order(ct1["id"], amount_cents=200_000, title="CO", reason="pending")
    submit_change_order(co["id"])
    return pid


def test_eval_order_pool_excludes_pending_cos(api):
    """PRD §3.6: "The evaluation order is pinned to resolve the apparent
    circularity among pool, posture, and forecast: first the contingency pool
    fields are recomputed from the program's drawdowns (this pool recompute
    excludes all pending change orders), then contingency_posture is derived
    from that pool per §2.7, and only then are both estimate-at-completion
    variants computed against that posture."

    Design: Difficulty/combinatorial_formula/forecast_posture_evaluation_order
    """
    pid = _setup_eval_order_scenario()
    rep = create_owner_report(pid, period="2026-08")
    # available 250_000 / total 1_000_000 = 0.25 -> WATCH (pool excludes pending CO)
    assert rep["contingency_posture_snapshot"] == "WATCH"


def test_eval_order_trend_uses_watch_branch(api):
    """PRD §3.6: "taken in full when the program's posture is CRITICAL and
    halved otherwise" — under WATCH the 200_000 pending CO is halved.

    Design: Difficulty/combinatorial_formula/forecast_posture_evaluation_order
    """
    pid = _setup_eval_order_scenario()
    rep = create_owner_report(pid, period="2026-08")
    # commitment variant: 4_500_000 (no estimated, no assessed risks)
    assert rep["eac_commitment_based_cents"] == 4_500_000
    # trend variant: 4_500_000 + 200_000 * 0.50 (WATCH) = 4_600_000
    assert rep["eac_trend_based_cents"] == 4_600_000


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / move_in_readiness_unweighted_vs_weighted
# ---------------------------------------------------------------------------

def _setup_readiness_scenario():
    """Plan with waves W1 COMPLETE weight 2, W2 SCHEDULED weight 1, W3 CANCELLED weight 5."""
    from test_helpers import (
        create_stakeholder_group, create_occupancy_plan, coordinate_occupancy_plan,
        mark_ready_occupancy_plan, execute_occupancy_plan, create_move_in_wave,
        confirm_move_in_wave, complete_move_in_wave, cancel_move_in_wave,
    )
    prog = create_active_program(
        total_budget_cents=3_000_000,
        contingency_total_cents=300_000,
        lines=[
            {"cost_code": "CC-100", "amount_cents": 1_000_000},
            {"cost_code": "CC-200", "amount_cents": 1_000_000},
            {"cost_code": "CC-300", "amount_cents": 1_000_000},
        ],
        name="P-READ",
    )
    pid = prog["id"]
    g1 = create_stakeholder_group(pid, group_name="G1", contact_email="g1@x.com")
    pl = create_occupancy_plan(pid, plan_name="PL", target_move_month="2026-10")
    coordinate_occupancy_plan(pl["id"])
    w1 = create_move_in_wave(pl["id"], g1["id"], wave_name="W1", dock_resource="DOCK_A",
                              move_start="2026-10-01T08:00:00Z", move_end="2026-10-01T12:00:00Z",
                              criticality_weight=2)
    w2 = create_move_in_wave(pl["id"], g1["id"], wave_name="W2", dock_resource="DOCK_B",
                              move_start="2026-10-02T08:00:00Z", move_end="2026-10-02T12:00:00Z",
                              criticality_weight=1)
    w3 = create_move_in_wave(pl["id"], g1["id"], wave_name="W3", dock_resource="DOCK_C",
                              move_start="2026-10-03T08:00:00Z", move_end="2026-10-03T12:00:00Z",
                              criticality_weight=5)
    mark_ready_occupancy_plan(pl["id"])
    execute_occupancy_plan(pl["id"])
    confirm_move_in_wave(w1["id"])
    complete_move_in_wave(w1["id"])
    cancel_move_in_wave(w3["id"])
    return pid, pl


def test_readiness_unweighted_variant(api):
    """PRD §3.8: "The UNWEIGHTED variant, readiness_unweighted_pct, is one
    hundred times the number of completed considered waves divided by the
    number of considered waves, rounded half-up to two decimal places, and is
    0.00 when no waves are considered."

    Design: Difficulty/dual_variant_calc/move_in_readiness_unweighted_vs_weighted
    """
    _, pl = _setup_readiness_scenario()
    got = get_success_data(api_client.get_occupancy_plan(pl["id"], pm_headers()))
    # 1 of 2 non-cancelled waves complete: 100 * 1/2 = 50.00
    assert got["readiness_unweighted_pct"] == pytest.approx(50.0, abs=0.01)


def test_readiness_weighted_variant(api):
    """PRD §3.8: "The WEIGHTED variant, readiness_weighted_pct, replaces counts
    with criticality_weight sums: one hundred times the total weight of
    completed considered waves divided by the total weight of all considered
    waves, likewise rounded half-up to two decimal places, and 0.00 when
    empty."

    Design: Difficulty/dual_variant_calc/move_in_readiness_unweighted_vs_weighted
    """
    _, pl = _setup_readiness_scenario()
    got = get_success_data(api_client.get_occupancy_plan(pl["id"], pm_headers()))
    # 100 * 2/(2+1) = 66.666... -> round_half_up to 2dp -> 66.67
    assert got["readiness_weighted_pct"] == pytest.approx(66.67, abs=0.001)
