"""Error-precedence conflicts (state vs fiscal, safety vs temporal), run-out
eligibility, and 1099 reporting boundary."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_examiner_headers,
    create_plan, create_provider, create_member,
    submit_claim, adjudicate_claim, create_adjudicated_claim,
    create_fund_account, deposit, create_check_run, release_check_run,
    terminate_plan, set_clock,
)

ADMIN = TEST_USERS["tpa_admin_headers"]
FUND = TEST_USERS["fund_manager_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
EX1 = make_examiner_headers("ex-1")


# ---- priority_pair: state (claim not adjudicated) beats fiscal (funds) -----
def _setup_state_vs_fiscal(api):
    plan = create_plan(individual_deductible_cents=0)
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    c_adj = create_adjudicated_claim(member["id"], prov["id"], service_date="2026-03-01",
                                     billed_lines=[{"billed_cents": 100000}])  # plan_paid 48000
    c_sub = submit_claim(member["id"], prov["id"], service_date="2026-03-02",
                         billed_lines=[{"billed_cents": 100000}])  # left SUBMITTED
    fund = create_fund_account(plan["id"])
    fund = deposit(fund["id"], 100)  # far below the total
    cr = create_check_run(fund["id"], [c_adj["id"], c_sub["id"]])
    return fund, cr


def test_release_state_error_beats_fiscal_insufficient_funds(api):
    """PRD 3.6: "Every included claim must be `ADJUDICATED`; if any is not, the release is
    rejected with `ERR_CLAIM_NOT_ADJUDICATED`." "In precedence terms these are evaluated in the
    order state (claims adjudicated), then concurrency (stale version), then fiscal sufficiency
    (insufficient funds)."

    Design: Difficulty/priority_pair_validation_conflict/state_claim_not_adjudicated_beats_fiscal_insufficient_funds
    """
    fund, cr = _setup_state_vs_fiscal(api)
    resp = api.release_check_run(cr["id"], {"expected_fund_account_version": fund["version"]}, FUND)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ADJUDICATED.value)


def test_release_state_precedence_leaves_fund_balance_unchanged(api):
    """PRD 3.6: "In precedence terms these are evaluated in the order state (claims adjudicated),
    then concurrency (stale version), then fiscal sufficiency (insufficient funds)."

    Design: Difficulty/priority_pair_validation_conflict/state_claim_not_adjudicated_beats_fiscal_insufficient_funds
    """
    fund, cr = _setup_state_vs_fiscal(api)
    api.release_check_run(cr["id"], {"expected_fund_account_version": fund["version"]}, FUND)
    fdata = validate_success(api.get_fund_account(fund["id"], ADMIN))
    assert fdata["balance_cents"] == 100, (
        f"a rejected release moves no funds; balance stays 100, got {fdata['balance_cents']}")


# ---- priority_pair: safety (duplicate) beats temporal (run-out) ------------
def _setup_duplicate_vs_runout(api):
    plan = create_plan(individual_deductible_cents=0)
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    terminate_plan(plan["id"], "2026-03-31")  # run-out ends 2026-06-29
    set_clock("2026-05-01T00:00:00Z")         # run-out still open
    c_orig = submit_claim(member["id"], prov["id"], service_date="2026-03-01",
                          billed_lines=[{"billed_cents": 100000}])
    adjudicate_claim(c_orig["id"])            # succeeds (in run-out, service before term)
    c_dup = submit_claim(member["id"], prov["id"], service_date="2026-03-01",
                         billed_lines=[{"billed_cents": 100000}])  # identical twin
    set_clock("2026-08-01T00:00:00Z")         # now past run-out
    return c_dup


def test_adjudicate_duplicate_beats_run_out_closed(api):
    """PRD 3.4: "No adjudication may proceed if another claim already in `ADJUDICATED` or `PAID`
    status shares the same `member_id`, `provider_id`, `service_date`, and `billed_total_cents`;
    such a twin is rejected as `ERR_DUPLICATE_CLAIM`." "These guards follow the global precedence
    of Section 2.7: the state check first, then separation-of-duties and duplicate detection, then
    eligibility and run-out."

    Design: Difficulty/priority_pair_validation_conflict/safety_duplicate_claim_beats_temporal_run_out_closed
    """
    c_dup = _setup_duplicate_vs_runout(api)
    resp = api.adjudicate_claim(c_dup["id"], EX1)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM.value)


def test_adjudicate_duplicate_conflict_leaves_claim_submitted(api):
    """PRD 3.4: "such a twin is rejected as `ERR_DUPLICATE_CLAIM`."

    Design: Difficulty/priority_pair_validation_conflict/safety_duplicate_claim_beats_temporal_run_out_closed
    """
    c_dup = _setup_duplicate_vs_runout(api)
    api.adjudicate_claim(c_dup["id"], EX1)
    data = validate_success(api.get_claim(c_dup["id"], ADMIN))
    assert data["status"] == "SUBMITTED", (
        f"a rejected adjudication leaves the twin SUBMITTED, got {data['status']}")


# ---- boundary_precision_check: 1099 $600.00 threshold ----------------------
def _setup_1099_at_threshold(api):
    plan = create_plan(individual_deductible_cents=0)
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    claim = create_adjudicated_claim(member["id"], prov["id"],
                                     billed_lines=[{"billed_cents": 125000}])  # plan_paid 60000
    fund = create_fund_account(plan["id"])
    fund = deposit(fund["id"], 60000)
    cr = create_check_run(fund["id"], [claim["id"]])
    set_clock("2026-08-01T00:00:00Z")  # tax year 2026
    release_check_run(cr["id"], fund["version"])
    return prov


def test_form_1099_total_paid_at_threshold(api):
    """PRD 3.8: "The form's `total_paid_cents` is the sum of `plan_paid_cents` over all claims
    for that provider that are in `PAID` status and whose `paid_at` falls in the given calendar
    `tax_year`."

    Design: Difficulty/boundary_precision_check/form_1099_600_dollar_threshold_boundary_on_generate
    """
    prov = _setup_1099_at_threshold(api)
    form = validate_success(api.generate_form_1099(
        {"provider_id": prov["id"], "tax_year": 2026}, AUDITOR), expected_status=201)
    assert form["total_paid_cents"] == 60000, (
        f"total_paid at the 600.00 boundary -> 60000, got {form['total_paid_cents']}")


def test_form_1099_reportable_at_600_dollar_boundary(api):
    """PRD 3.8: "The form is marked `reportable` when its `total_paid_cents` is at least the
    reporting threshold of 60,000 cents — that is, 600.00 US dollars — where exactly 600.00
    dollars is itself reportable."

    Design: Difficulty/boundary_precision_check/form_1099_600_dollar_threshold_boundary_on_generate
    """
    prov = _setup_1099_at_threshold(api)
    form = validate_success(api.generate_form_1099(
        {"provider_id": prov["id"], "tax_year": 2026}, AUDITOR), expected_status=201)
    assert form["reportable"] is True, "exactly 60000 cents (600.00 USD) is reportable"


# ---- Corner: run-out closed ------------------------------------------------
def test_adjudicate_after_runout_closed_returns_run_out_closed(api):
    """PRD 3.4: "If the plan is `TERMINATED`, the claim may still be adjudicated only when its
    `service_date` is on or before the plan's `terminated_at` and the current logical-clock time
    is on or before `terminated_at` plus `run_out_days` days; a claim incurred after termination,
    or adjudicated after the run-out window has passed, is rejected with `ERR_RUN_OUT_CLOSED`
    (HTTP 422)."

    Design: Corner/validations/adjudicate_after_runout_closed_returns_run_out_closed
    """
    plan = create_plan(individual_deductible_cents=0)
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    claim = submit_claim(member["id"], prov["id"], service_date="2026-04-01",
                         billed_lines=[{"billed_cents": 100000}])
    terminate_plan(plan["id"], "2026-03-31")   # service 2026-04-01 is after termination
    set_clock("2026-08-01T00:00:00Z")
    resp = api.adjudicate_claim(claim["id"], EX1)
    validate_error(resp, ApiErrorId.ERR_RUN_OUT_CLOSED.value)
