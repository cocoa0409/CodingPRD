"""Income guarantee and ramp milestones: the ACTUAL/PROJECTED dual variants,
multi-factor draw math, the pinned repayment evaluation order, ledger
conservation, the ACTIVE-guarantee attestation gate, attainment equality,
window enforcement, and settlement."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_executed_offer, setup_active_guarantee, set_clock, run_epoch,
    get_case, get_milestone_for_month,
    report_milestone, attest_milestone, report_and_attest,
)

PM = TEST_USERS["practice_manager_headers"]
FINANCE = TEST_USERS["finance_analyst_headers"]


def _get_guarantee(guarantee_id):
    return get_success_data(api_client.get_income_guarantee(guarantee_id, FINANCE))


# --- Queue A: dual variant (guarantee) ---------------------------------------

def test_guarantee_draw_projected_vs_actual_diverge_variants(api):
    """PRD §3.8: "The ACTUAL variant total, `total_advanced_cents`, is the sum of the draws over reconciled months only. The PROJECTED variant, `projected_total_draw_cents`, takes that actual total and adds one full `monthly_guarantee_cents` for every unreconciled term month — assuming zero future collections — so identical data yields a strictly larger projected total whenever any term month remains unreconciled."
    PRD §3.8: "For an `ATTESTED` month, the collection credit is the month's `collections_cents` capped at 1,800,000 cents (eighteen thousand dollars); if the month was attained the credit is that capped amount"

    Design: Difficulty/dual_variant_calc/guarantee_draw_projected_vs_actual_diverge
    """
    ctx = setup_active_guarantee(full_name="Dr. Ada")
    case_id = ctx["case"]["id"]
    guarantee_id = ctx["guarantee"]["id"]
    report_and_attest(case_id, 1, actual_wrvu=120, collections_cents=1200000)

    guarantee = _get_guarantee(guarantee_id)
    # ACTUAL: draw = 2000000 - min(1200000, 1800000) = 800000 over one reconciled month.
    assert guarantee["total_advanced_cents"] == 800000
    # PROJECTED: 800000 + 11 * 2000000 = 22800000 over the same stored data.
    assert guarantee["projected_total_draw_cents"] == 22800000
    assert guarantee["projected_total_draw_cents"] > guarantee["total_advanced_cents"], (
        "the variants must diverge whenever any term month is unreconciled"
    )


def test_guarantee_draw_projected_vs_actual_diverge_forgiveness(api):
    """PRD §3.8: "Forgiveness accrues at 100,000 cents (one thousand dollars) per attained month: `forgiveness_accrued_cents` is that amount times the number of `ATTESTED` months with `attained` true."
    PRD §3.8: "The `outstanding_balance_cents` is then the total advanced minus `total_repaid_cents` minus the accrued forgiveness, floored at zero."
    PRD §3.8: "`months_reconciled` counts the term months whose milestone is `ATTESTED` or `LAPSED`, and when that count reaches `term_months` the guarantee moves `ACTIVE` → `SETTLED` with its outstanding balance final."

    Design: Difficulty/dual_variant_calc/guarantee_draw_projected_vs_actual_diverge
    """
    ctx = setup_active_guarantee(full_name="Dr. Ada")
    case_id = ctx["case"]["id"]
    guarantee_id = ctx["guarantee"]["id"]
    report_and_attest(case_id, 1, actual_wrvu=120, collections_cents=1200000)

    guarantee = _get_guarantee(guarantee_id)
    assert guarantee["forgiveness_accrued_cents"] == 100000, "one attained month accrues 100000"
    assert guarantee["total_repaid_cents"] == 0
    assert guarantee["outstanding_balance_cents"] == 700000, "800000 - 0 - 100000"
    assert guarantee["months_reconciled"] == 1


# --- Queue A: combinatorial draw formula --------------------------------------

def test_guarantee_draw_multifactor_credit_penalty_cap_totals(api):
    """PRD §3.8: "For an `ATTESTED` month, the collection credit is the month's `collections_cents` capped at 1,800,000 cents (eighteen thousand dollars); if the month was attained the credit is that capped amount, and if it was missed the credit is the capped amount reduced by a ten-percent penalty, rounded half-up to whole cents. The month's draw is then the `monthly_guarantee_cents` minus the credit, floored at zero"
    PRD §3.8: "The ACTUAL variant total, `total_advanced_cents`, is the sum of the draws over reconciled months only."

    Design: Difficulty/combinatorial_formula/guarantee_draw_multifactor_credit_penalty_cap
    """
    ctx = setup_active_guarantee(full_name="Dr. Cam")
    case_id = ctx["case"]["id"]
    report_and_attest(case_id, 1, actual_wrvu=120, collections_cents=1200000)   # attained: 800000
    report_and_attest(case_id, 2, actual_wrvu=100, collections_cents=1200000)   # missed: 920000
    report_and_attest(case_id, 3, actual_wrvu=250, collections_cents=2500000)   # attained, capped: 200000

    guarantee = _get_guarantee(ctx["guarantee"]["id"])
    assert guarantee["total_advanced_cents"] == 1920000, "800000 + 920000 + 200000"
    assert guarantee["months_reconciled"] == 3


def test_guarantee_draw_multifactor_credit_penalty_cap_ledger(api):
    """PRD §3.8: "Forgiveness accrues at 100,000 cents (one thousand dollars) per attained month: `forgiveness_accrued_cents` is that amount times the number of `ATTESTED` months with `attained` true. The `outstanding_balance_cents` is then the total advanced minus `total_repaid_cents` minus the accrued forgiveness, floored at zero."
    PRD §3.8: "The PROJECTED variant, `projected_total_draw_cents`, takes that actual total and adds one full `monthly_guarantee_cents` for every unreconciled term month"

    Design: Difficulty/combinatorial_formula/guarantee_draw_multifactor_credit_penalty_cap
    """
    ctx = setup_active_guarantee(full_name="Dr. Cam")
    case_id = ctx["case"]["id"]
    report_and_attest(case_id, 1, actual_wrvu=120, collections_cents=1200000)
    report_and_attest(case_id, 2, actual_wrvu=100, collections_cents=1200000)
    report_and_attest(case_id, 3, actual_wrvu=250, collections_cents=2500000)

    guarantee = _get_guarantee(ctx["guarantee"]["id"])
    assert guarantee["forgiveness_accrued_cents"] == 200000, "2 attained months * 100000"
    assert guarantee["outstanding_balance_cents"] == 1720000, "1920000 - 0 - 200000"
    assert guarantee["projected_total_draw_cents"] == 19920000, "1920000 + 9 * 2000000"


# --- Queue A: pinned repayment evaluation order --------------------------------

def test_guarantee_repayment_evaluation_order_exact_outstanding_succeeds(api):
    """PRD §3.8: "The evaluation order is pinned — chronological draws first, then forgiveness from the attained count, then the outstanding balance from the three ledger totals — and a repayment is always validated against the outstanding balance computed before that repayment is applied."

    Design: Difficulty/combinatorial_formula/guarantee_repayment_evaluation_order_pinned
    """
    ctx = setup_active_guarantee(full_name="Dr. Eli")
    case_id = ctx["case"]["id"]
    guarantee_id = ctx["guarantee"]["id"]
    report_and_attest(case_id, 1, actual_wrvu=120, collections_cents=1200000)
    assert _get_guarantee(guarantee_id)["outstanding_balance_cents"] == 700000

    data = validate_success(
        api_client.post_guarantee_repayment(guarantee_id, {"amount_cents": 700000}, FINANCE), 201
    )
    assert data["total_repaid_cents"] == 700000, (
        "a repayment of exactly the pre-repayment outstanding must succeed"
    )
    assert data["outstanding_balance_cents"] == 0, "max(0, 800000 - 700000 - 100000)"


def test_guarantee_repayment_evaluation_order_next_cent_rejected(api):
    """PRD §3.8: "if the amount exceeds the outstanding balance computed before this repayment, the posting is rejected with `ERR_REPAYMENT_EXCEEDS_OUTSTANDING` (HTTP 422)"

    Design: Difficulty/combinatorial_formula/guarantee_repayment_evaluation_order_pinned
    """
    ctx = setup_active_guarantee(full_name="Dr. Eli")
    case_id = ctx["case"]["id"]
    guarantee_id = ctx["guarantee"]["id"]
    report_and_attest(case_id, 1, actual_wrvu=120, collections_cents=1200000)
    validate_success(
        api_client.post_guarantee_repayment(guarantee_id, {"amount_cents": 700000}, FINANCE), 201
    )
    resp = api_client.post_guarantee_repayment(guarantee_id, {"amount_cents": 1}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_REPAYMENT_EXCEEDS_OUTSTANDING)


# --- Queue A: ledger conservation ---------------------------------------------

def test_guarantee_outstanding_conserved_by_repayments_stepwise(api):
    """PRD §3.8: "The `outstanding_balance_cents` is then the total advanced minus `total_repaid_cents` minus the accrued forgiveness, floored at zero."
    PRD §3.8: "otherwise `total_repaid_cents` grows by `amount_cents` and the outstanding balance is recomputed."

    Design: Difficulty/compensating_invariant/guarantee_outstanding_conserved_by_repayments
    """
    ctx = setup_active_guarantee(full_name="Dr. Sam")
    case_id = ctx["case"]["id"]
    guarantee_id = ctx["guarantee"]["id"]
    report_and_attest(case_id, 1, actual_wrvu=120, collections_cents=1200000)

    guarantee = _get_guarantee(guarantee_id)
    assert guarantee["outstanding_balance_cents"] == 700000, "800000 advanced - 100000 forgiveness"

    data = validate_success(
        api_client.post_guarantee_repayment(guarantee_id, {"amount_cents": 300000}, FINANCE), 201
    )
    assert data["outstanding_balance_cents"] == 400000


def test_guarantee_outstanding_conserved_by_repayments_to_zero(api):
    """PRD §3.8: "The `outstanding_balance_cents` is then the total advanced minus `total_repaid_cents` minus the accrued forgiveness, floored at zero."
    PRD §3.8: "otherwise `total_repaid_cents` grows by `amount_cents` and the outstanding balance is recomputed."

    Design: Difficulty/compensating_invariant/guarantee_outstanding_conserved_by_repayments
    """
    ctx = setup_active_guarantee(full_name="Dr. Sam")
    case_id = ctx["case"]["id"]
    guarantee_id = ctx["guarantee"]["id"]
    report_and_attest(case_id, 1, actual_wrvu=120, collections_cents=1200000)
    validate_success(
        api_client.post_guarantee_repayment(guarantee_id, {"amount_cents": 300000}, FINANCE), 201
    )
    data = validate_success(
        api_client.post_guarantee_repayment(guarantee_id, {"amount_cents": 400000}, FINANCE), 201
    )
    assert data["total_repaid_cents"] == 700000
    assert data["outstanding_balance_cents"] == 0, (
        "the forward draw plus compensating repayments plus forgiveness returns the ledger to zero"
    )


# --- Queue A: cross-entity gate -----------------------------------------------

def test_milestone_attest_requires_active_guarantee_rejected(api):
    """PRD §3.8: "Attestation belongs to the `FinanceAnalyst`. The milestone must be `REPORTED` (else `ERR_MILESTONE_NOT_REPORTED`) and the case's guarantee must be `ACTIVE` (else `ERR_GUARANTEE_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/milestone_attest_requires_active_guarantee
    """
    ctx = setup_executed_offer(full_name="Dr. Ora")
    case_id = ctx["case"]["id"]
    set_clock("2027-06-05T00:00:00Z")
    report_milestone(case_id, 1, actual_wrvu=120, collections_cents=1200000)
    assert _get_guarantee(ctx["guarantee"]["id"])["status"] == "DRAFT"

    milestone = get_milestone_for_month(case_id, 1)
    resp = api_client.attest_ramp_milestone(milestone["id"], FINANCE)
    validate_error(resp, ApiErrorId.ERR_GUARANTEE_NOT_ACTIVE)
    assert resp.status_code == 409


def test_milestone_attest_succeeds_once_guarantee_active(api):
    """PRD §3.8: "Activation matters because the guarantee's `ACTIVE` status is the gate for milestone attestation."
    PRD §3.8: "Attestation computes `attained` as the threshold test of whether `actual_wrvu` reached `target_wrvu` — exact equality attains — moves the milestone to `ATTESTED`, and then cascades: the guarantee's draws are recomputed chronologically and `total_advanced_cents` updated"

    Design: Difficulty/cross_entity_state_dependency/milestone_attest_requires_active_guarantee
    """
    ctx = setup_executed_offer(full_name="Dr. Ora")
    case_id = ctx["case"]["id"]
    guarantee_id = ctx["guarantee"]["id"]
    set_clock("2027-06-05T00:00:00Z")
    report_milestone(case_id, 1, actual_wrvu=120, collections_cents=1200000)
    milestone = get_milestone_for_month(case_id, 1)
    validate_error(
        api_client.attest_ramp_milestone(milestone["id"], FINANCE),
        ApiErrorId.ERR_GUARANTEE_NOT_ACTIVE,
    )

    validate_success(api_client.activate_income_guarantee(guarantee_id, FINANCE), 200)
    data = validate_success(api_client.attest_ramp_milestone(milestone["id"], FINANCE), 200)
    assert data["status"] == "ATTESTED"
    assert data["attained"] is True, "120 >= 100 attains"
    assert _get_guarantee(guarantee_id)["total_advanced_cents"] == 800000


# --- Queue B: attainment equality ----------------------------------------------

def test_milestone_attainment_equality_boundary(api):
    """PRD §3.8: "Attestation computes `attained` as the threshold test of whether `actual_wrvu` reached `target_wrvu` — exact equality attains"
    PRD §3.8: "On the case, `attained_milestone_count` counts `ATTESTED` milestones whose `attained` is true, while `missed_milestone_count` counts `ATTESTED` milestones whose `attained` is false plus every `LAPSED` one."

    Design: Corner/calculations/milestone_attainment_equality_boundary
    """
    ctx = setup_active_guarantee(full_name="Dr. Sue")
    case_id = ctx["case"]["id"]
    report_milestone(case_id, 1, actual_wrvu=100, collections_cents=500000)  # target 100
    report_milestone(case_id, 2, actual_wrvu=149, collections_cents=500000)  # target 150

    data1 = attest_milestone(case_id, 1)
    assert data1["attained"] is True, "actual 100 >= target 100 attains (equality)"
    data2 = attest_milestone(case_id, 2)
    assert data2["attained"] is False, "149 < 150 does not attain"

    case = get_case(case_id)
    assert case["attained_milestone_count"] == 1
    assert case["missed_milestone_count"] == 1


# --- Queue B: reporting window and settlement -----------------------------------

def test_report_after_window_closed_rejected(api):
    """PRD §3.8: "The reporting window closes fifteen days after the month's end: a report dated after month end plus the fifteen-day grace period is rejected with `ERR_REPORTING_WINDOW_CLOSED` (HTTP 422)."
    PRD §3.8: "A milestone still `PENDING` when its reporting window closes is flipped to `LAPSED` by the epoch sweep"

    Design: Corner/validations/report_after_window_closed_rejected
    """
    ctx = setup_executed_offer(full_name="Dr. Abe")
    case_id = ctx["case"]["id"]
    # Month 1 is June 2027; its window closes 2027-07-15. No epoch has run.
    set_clock("2027-08-01T00:00:00Z")
    milestone = get_milestone_for_month(case_id, 1)
    assert milestone["status"] == "PENDING"

    resp = api_client.report_ramp_milestone(
        milestone["id"], {"actual_wrvu": 120, "collections_cents": 1200000}, PM
    )
    validate_error(resp, ApiErrorId.ERR_REPORTING_WINDOW_CLOSED)
    milestone = get_milestone_for_month(case_id, 1)
    assert milestone["status"] == "PENDING", "without a sweep the milestone stays PENDING"


def test_guarantee_settles_after_all_months_lapsed(api):
    """PRD §3.8: "For a `LAPSED` month, the draw is the full `monthly_guarantee_cents`: no collection credit, no forgiveness."
    PRD §3.8: "`months_reconciled` counts the term months whose milestone is `ATTESTED` or `LAPSED`, and when that count reaches `term_months` the guarantee moves `ACTIVE` → `SETTLED` with its outstanding balance final."
    PRD §3.8: "Reconciliation against a guarantee that is not `ACTIVE` is rejected with `ERR_GUARANTEE_NOT_ACTIVE`."

    Design: Corner/state_machines/guarantee_settles_after_all_months_lapsed
    """
    ctx = setup_active_guarantee(full_name="Dr. Mel")
    guarantee_id = ctx["guarantee"]["id"]

    # Advance past every reporting window (month 12 of a 2027-06 term closes
    # 2028-06-15) and sweep: all 12 milestones lapse.
    set_clock("2028-08-01T00:00:00Z")
    sweep = run_epoch()
    assert len(sweep["lapsed_milestone_ids"]) == 12

    data = validate_success(api_client.reconcile_income_guarantee(guarantee_id, FINANCE), 200)
    assert data["status"] == "SETTLED"
    assert data["months_reconciled"] == 12
    assert data["total_advanced_cents"] == 24000000, "12 LAPSED months at the full 2000000"
    assert data["forgiveness_accrued_cents"] == 0
    assert data["outstanding_balance_cents"] == 24000000

    resp = api_client.reconcile_income_guarantee(guarantee_id, FINANCE)
    validate_error(resp, ApiErrorId.ERR_GUARANTEE_NOT_ACTIVE)
