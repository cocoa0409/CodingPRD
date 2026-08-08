"""Two-stage expense reimbursement: provisional estimate vs final tiered/capped
amount, the approve/reject fork, conserved committed budget, and the
state-over-fiscal precedence on approval.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula, branching
non_linear_state_machine, compensating_invariant (money), and
priority_pair_validation_conflict (state beats fiscal).
Queue B (Corner): tier/cap correctness and unknown-case existence.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    onboard_active_volunteer,
    make_volunteer_headers,
    setup_active_volunteer_assigned_case,
    setup_submitted_expense,
    log_visit,
    NIL_UUID,
)

ADMIN = TEST_USERS["program_admin_headers"]


# -------------------- Difficulty: provisional flat estimate vs final tiered amount
def test_expense_provisional_estimate_flat_rate(api):
    """PRD 3.7: "The provisional figure applies a flat rate of 50 cents per mile
    with no caps: it is the product of total_miles and 50 cents, rounded half up
    to whole cents, plus the full other_expense_cents unchanged."

    Design: Difficulty/dual_variant_calc/expense_provisional_vs_final_diverge
    """
    base = setup_submitted_expense(api, budget=20000, total_miles=120, other_expense_cents=6000)
    claim = get_success_data(api.get_expense_claim(base["expense_claim_id"], base["supervisor_headers"]))
    assert claim["estimated_reimbursement_cents"] == 12000  # 120*50 + 6000


def test_expense_final_diverges_from_estimate(api):
    """PRD 3.7: "first the mileage component is the first 100 miles at 50 cents
    each plus every mile beyond 100 at 35 cents each, with that mileage sum rounded
    half up to whole cents; then the other-expense component is other_expense_cents
    but no more than 5000 cents; then those two are summed; and finally the whole
    is capped at 15000 cents."

    Design: Difficulty/dual_variant_calc/expense_provisional_vs_final_diverge
    """
    base = setup_submitted_expense(api, budget=20000, total_miles=120, other_expense_cents=6000)
    approved = get_success_data(api.approve_expense(base["expense_claim_id"], base["supervisor_headers"]))
    assert approved["final_reimbursement_cents"] == 10700  # 5000+700 mileage + 5000 other
    assert approved["final_reimbursement_cents"] != approved["estimated_reimbursement_cents"]


# --------------------------- Difficulty: >=3-input non-linear tiered final formula
def test_expense_final_tiered_value(api):
    """PRD 3.7: "first the mileage component is the first 100 miles at 50 cents
    each plus every mile beyond 100 at 35 cents each, with that mileage sum rounded
    half up to whole cents; then the other-expense component is other_expense_cents
    but no more than 5000 cents; then those two are summed; and finally the whole
    is capped at 15000 cents."

    Design: Difficulty/combinatorial_formula/expense_final_tiered_nonlinear_mode_a
    """
    base = setup_submitted_expense(api, budget=20000, total_miles=120, other_expense_cents=6000)
    approved = get_success_data(api.approve_expense(base["expense_claim_id"], base["supervisor_headers"]))
    assert approved["final_reimbursement_cents"] == 10700


def test_expense_final_not_flat_rate(api):
    """PRD 3.7: "the other-expense component is `other_expense_cents` but no more
    than 5000 cents".

    Design: Difficulty/combinatorial_formula/expense_final_tiered_nonlinear_mode_a
    """
    base = setup_submitted_expense(api, budget=20000, total_miles=120, other_expense_cents=6000)
    approved = get_success_data(api.approve_expense(base["expense_claim_id"], base["supervisor_headers"]))
    # The 6000c other-expense is capped at 5000c, so final (10700) is below the
    # flat provisional estimate (12000) — the tiered/capped result is non-linear.
    assert approved["final_reimbursement_cents"] < approved["estimated_reimbursement_cents"]


# ------------------------- Difficulty: SUBMITTED forks to APPROVED / REJECTED
def test_expense_approve_branch_commits_budget(api):
    """PRD 3.7: "On a successful approval the claim advances `SUBMITTED → APPROVED`
    and the case's `reimbursement_committed_cents` increases by the pinned final
    amount."

    Design: Difficulty/non_linear_state_machine/expense_branching_forkjoin
    """
    base = setup_submitted_expense(api, budget=20000, total_miles=120, other_expense_cents=6000)
    approved = get_success_data(api.approve_expense(base["expense_claim_id"], base["supervisor_headers"]))
    assert approved["status"] == "APPROVED"
    assert approved["final_reimbursement_cents"] == 10700
    case = get_success_data(api.get_case(base["case_id"], base["supervisor_headers"]))
    assert case["reimbursement_committed_cents"] == 10700


def test_expense_reject_branch_leaves_budget_untouched(api):
    """PRD 3.7: "Rejecting a submitted claim advances SUBMITTED → REJECTED and
    records an optional reason; because a rejected claim never entered the ledger,
    committed reimbursement is unchanged."

    Design: Difficulty/non_linear_state_machine/expense_branching_forkjoin
    """
    base = setup_submitted_expense(api, budget=20000, total_miles=120, other_expense_cents=6000)
    rejected = get_success_data(api.reject_expense(
        base["expense_claim_id"], {"reason": "duplicate"}, base["supervisor_headers"]))
    assert rejected["status"] == "REJECTED"
    assert rejected["final_reimbursement_cents"] is None
    case = get_success_data(api.get_case(base["case_id"], base["supervisor_headers"]))
    assert case["reimbursement_committed_cents"] == 0


# ------------------ Difficulty: committed money conserved by approve-then-void
def test_committed_increases_on_approve(api):
    """PRD 2.7: "It starts at 0, increases by a claim's final amount at approval,
    and decreases by that same amount if the approved claim is later voided;
    approving and then voiding the same claim leaves it unchanged."

    Design: Difficulty/compensating_invariant/budget_money_conserved_by_approve_then_void
    """
    base = setup_submitted_expense(api, budget=20000, total_miles=120, other_expense_cents=6000)
    get_success_data(api.approve_expense(base["expense_claim_id"], base["supervisor_headers"]))
    case = get_success_data(api.get_case(base["case_id"], base["supervisor_headers"]))
    assert case["reimbursement_committed_cents"] == 10700


def test_committed_restored_on_void(api):
    """PRD 3.7: "An approved claim may instead be voided by the case's supervisor,
    advancing APPROVED → VOIDED and decreasing the case's
    reimbursement_committed_cents by the claim's final_reimbursement_cents, which
    restores the conserved budget exactly."

    Design: Difficulty/compensating_invariant/budget_money_conserved_by_approve_then_void
    """
    base = setup_submitted_expense(api, budget=20000, total_miles=120, other_expense_cents=6000)
    get_success_data(api.approve_expense(base["expense_claim_id"], base["supervisor_headers"]))
    get_success_data(api.void_expense(base["expense_claim_id"], {"reason": "reversed"}, base["supervisor_headers"]))
    case = get_success_data(api.get_case(base["case_id"], base["supervisor_headers"]))
    assert case["reimbursement_committed_cents"] == 0


# --------------------- Difficulty: state (CASE_CLOSED) beats fiscal (budget)
def _closed_case_over_budget_claim(api):
    base = setup_active_volunteer_assigned_case(api, budget=10000)
    log_visit(api, base, contact_start="2026-06-05T10:00:00Z", contact_end="2026-06-05T11:00:00Z")
    claim = get_success_data(api.create_expense_claim(
        {"case_id": base["case_id"], "period_month": "2026-06",
         "total_miles": 120, "other_expense_cents": 6000}, base["volunteer_headers"]))
    get_success_data(api.close_case(base["case_id"], {"outcome": "REUNIFICATION"}, base["supervisor_headers"]))
    return base, claim


def test_approve_on_closed_case_reports_case_closed(api):
    """PRD 2.10: "because a closed case fails the state tier, an expense against a
    CLOSED case surfaces ERR_CASE_CLOSED before any budget arithmetic."

    Design: Difficulty/priority_pair_validation_conflict/state_closed_beats_fiscal_on_expense_approve
    """
    base, claim = _closed_case_over_budget_claim(api)
    resp = api.approve_expense(claim["id"], base["supervisor_headers"])
    validate_error(resp, ApiErrorId.ERR_CASE_CLOSED.value)


def test_approve_on_closed_case_not_budget_error(api):
    """PRD 2.10: "because a closed case fails the state tier, an expense against a
    CLOSED case surfaces ERR_CASE_CLOSED before any budget arithmetic."

    Design: Difficulty/priority_pair_validation_conflict/state_closed_beats_fiscal_on_expense_approve
    """
    base, claim = _closed_case_over_budget_claim(api)
    err = validate_error(api.approve_expense(claim["id"], base["supervisor_headers"]),
                         ApiErrorId.ERR_CASE_CLOSED.value)
    assert err["error_id"] != ApiErrorId.ERR_EXPENSE_EXCEEDS_BUDGET.value, \
        "the state failure must pre-empt the fiscal (budget) failure"


# ------------------------------------------------- Corner: tier/cap correctness
def test_expense_below_tier_estimate_equals_final(api):
    """PRD 3.7: "the product of total_miles and 50 cents, rounded half up to whole
    cents, plus the full other_expense_cents unchanged."

    Design: Corner/calculations/expense_below_tier_estimate_equals_final
    """
    base = setup_active_volunteer_assigned_case(api, budget=20000)
    claim = get_success_data(api.create_expense_claim(
        {"case_id": base["case_id"], "period_month": "2026-06",
         "total_miles": 50, "other_expense_cents": 3000}, base["volunteer_headers"]))
    assert claim["estimated_reimbursement_cents"] == 5500  # 50*50 + 3000
    approved = get_success_data(api.approve_expense(claim["id"], base["supervisor_headers"]))
    assert approved["final_reimbursement_cents"] == 5500  # all under tier1 and caps


def test_expense_monthly_cap_applied_on_final(api):
    """PRD 3.7: "then those two are summed; and finally the whole is capped at
    15000 cents."

    Design: Corner/calculations/expense_monthly_cap_applied_on_final
    """
    base = setup_active_volunteer_assigned_case(api, budget=20000)
    claim = get_success_data(api.create_expense_claim(
        {"case_id": base["case_id"], "period_month": "2026-06",
         "total_miles": 400, "other_expense_cents": 6000}, base["volunteer_headers"]))
    approved = get_success_data(api.approve_expense(claim["id"], base["supervisor_headers"]))
    assert approved["final_reimbursement_cents"] == 15000  # raw 15500+5000 -> capped


def test_expense_unknown_case_rejected(api):
    """PRD 2.9: "the system validates identifiers left to right and rejects on the
    first identifier that does not resolve, using the not-found error for that
    resource: ... ERR_CASE_NOT_FOUND".

    Design: Corner/errors/expense_unknown_case_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    vol = onboard_active_volunteer(api, email="v1@casa.org")
    resp = api.create_expense_claim(
        {"case_id": NIL_UUID, "period_month": "2026-06", "total_miles": 10, "other_expense_cents": 0},
        make_volunteer_headers(vol["id"]))
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND.value)
