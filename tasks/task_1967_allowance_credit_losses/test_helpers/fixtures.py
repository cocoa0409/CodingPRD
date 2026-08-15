"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against an empty database
(the harness restarts the server before each test) using only PRD-declared
endpoints, and uses get_success_data() so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.

Operator ids follow the segregation-of-duties model (PRD §2.8): executions and
proposals are recorded under one analyst id, approvals under a different officer
id, so approval chains succeed by default and SoD tests can force collisions.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    adverse_scenario_payload,
    backtest_payload,
    charge_off_payload,
    create_adjustment_payload,
    create_factor_payload,
    create_loan_payload,
    create_loss_model_payload,
    create_model_run_payload,
    create_scenario_payload,
    create_segment_payload,
    finalize_payload,
    recovery_payload,
)
from .test_users import (
    TEST_USERS,
    make_chief_credit_officer_headers,
    make_credit_analyst_headers,
    make_model_validator_headers,
)

ANALYST = "analyst-1"
VALIDATOR = "validator-1"
CCO = "cco-1"

# Documentation text satisfying the >= 50 trimmed character minimum (PRD §3.5).
DEFAULT_DOC_TEXT = (
    "Energy-sector concentration elevated relative to risk appetite; "
    "committee approved overlay per memo Q1-2026."
)
# Analysis notes satisfying the non-empty submit precondition (PRD §3.7).
DEFAULT_ANALYSIS_NOTES = (
    "Collateral-based reserve documented with sufficient detail for review."
)


# ─── Tier 1: State Progression ────────────────────────

def create_draft_model(**overrides) -> dict:
    """Create a LossModel in DRAFT."""
    res = api_client.create_loss_model(
        create_loss_model_payload(**overrides),
        TEST_USERS["model_validator_headers"],
    )
    return get_success_data(res)


def create_active_model(**overrides) -> dict:
    """Create a LossModel and activate it. Returns the ACTIVE model."""
    model = create_draft_model(**overrides)
    res = api_client.activate_loss_model(model["id"], TEST_USERS["model_validator_headers"])
    return get_success_data(res)


def create_segment(**overrides) -> dict:
    """Create a PortfolioSegment in OPEN."""
    res = api_client.create_portfolio_segment(
        create_segment_payload(**overrides),
        TEST_USERS["credit_analyst_headers"],
    )
    return get_success_data(res)


def create_loan(segment_id: str, **overrides) -> dict:
    """Create a Loan (ACTIVE) inside an OPEN segment."""
    res = api_client.create_loan(
        create_loan_payload(segment_id, **overrides),
        TEST_USERS["credit_analyst_headers"],
    )
    return get_success_data(res)


def create_scenario(**overrides) -> dict:
    """Create an EconomicScenario (born ACTIVE)."""
    res = api_client.create_economic_scenario(
        create_scenario_payload(**overrides),
        TEST_USERS["model_validator_headers"],
    )
    return get_success_data(res)


def create_factor(segment_id: str, **overrides) -> dict:
    """Create a QualitativeFactor in DRAFT."""
    res = api_client.create_qualitative_factor(
        create_factor_payload(segment_id, **overrides),
        TEST_USERS["credit_analyst_headers"],
    )
    return get_success_data(res)


def create_documented_factor(segment_id: str, documentation_text: str = DEFAULT_DOC_TEXT, **overrides) -> dict:
    """Create a factor and move it DRAFT -> DOCUMENTED."""
    factor = create_factor(segment_id, **overrides)
    res = api_client.document_qualitative_factor(
        factor["id"], {"documentation_text": documentation_text},
        TEST_USERS["credit_analyst_headers"],
    )
    return get_success_data(res)


def create_approved_factor(segment_id: str, **overrides) -> dict:
    """Create a factor and walk it DRAFT -> DOCUMENTED -> APPROVED."""
    factor = create_documented_factor(segment_id, **overrides)
    res = api_client.approve_qualitative_factor(
        factor["id"], TEST_USERS["chief_credit_officer_headers"]
    )
    return get_success_data(res)


# ─── Tier 2/3: ModelRun lifecycle shortcuts ───────────

def create_draft_run(loss_model_id: str, scenario_weights: list,
                     as_of_period: str = "2026-Q1", user_id: str = ANALYST) -> dict:
    """Create a ModelRun in DRAFT with pinned scenario weights."""
    res = api_client.create_model_run(
        create_model_run_payload(loss_model_id, scenario_weights, as_of_period=as_of_period),
        make_credit_analyst_headers(user_id),
    )
    return get_success_data(res)


def execute_run(run_id: str, user_id: str = ANALYST) -> dict:
    """Execute a DRAFT run. Returns the EXECUTED run (snapshot computed)."""
    res = api_client.execute_model_run(run_id, make_credit_analyst_headers(user_id))
    return get_success_data(res)


def submit_run_for_review(run_id: str, user_id: str = ANALYST) -> dict:
    """Move an EXECUTED run to UNDER_REVIEW."""
    res = api_client.submit_model_run_for_review(run_id, make_credit_analyst_headers(user_id))
    return get_success_data(res)


def approve_run(run_id: str, user_id: str = CCO) -> dict:
    """Approve an UNDER_REVIEW run as a different operator than the executor."""
    res = api_client.approve_model_run(run_id, make_chief_credit_officer_headers(user_id))
    return get_success_data(res)


def finalize_run(run_id: str, period_charge_offs_cents: int = 0,
                 period_recoveries_cents: int = 0, user_id: str = CCO) -> dict:
    """Finalize an APPROVED run; spawns the PREPARED disclosure report."""
    res = api_client.finalize_model_run(
        run_id,
        finalize_payload(
            period_charge_offs_cents=period_charge_offs_cents,
            period_recoveries_cents=period_recoveries_cents,
        ),
        make_chief_credit_officer_headers(user_id),
    )
    return get_success_data(res)


def list_run_evaluations(run_id: str, loan_id: str = None) -> list:
    """List IndividualEvaluations of a run (optionally narrowed by loan)."""
    params = {"run_id": run_id}
    if loan_id is not None:
        params["loan_id"] = loan_id
    res = api_client.list_individual_evaluations(
        TEST_USERS["credit_analyst_headers"], params=params
    )
    return get_success_data(res)


def get_single_evaluation(run_id: str, loan_id: str = None) -> dict:
    """Fetch the single evaluation of a run (asserts exactly one exists)."""
    rows = list_run_evaluations(run_id, loan_id=loan_id)
    assert len(rows) == 1, f"Expected exactly 1 evaluation, got {len(rows)}"
    return rows[0]


def patch_evaluation(evaluation_id: str, expected_version: int, **fields) -> dict:
    """OCC-guarded PATCH of an evaluation (recomputes the specific reserve)."""
    payload = {"expected_evaluation_version": expected_version}
    payload.update(fields)
    res = api_client.patch_individual_evaluation(
        evaluation_id, payload, TEST_USERS["credit_analyst_headers"]
    )
    return get_success_data(res)


def submit_evaluation(evaluation_id: str) -> dict:
    res = api_client.submit_individual_evaluation(
        evaluation_id, TEST_USERS["credit_analyst_headers"]
    )
    return get_success_data(res)


def review_evaluation(evaluation_id: str) -> dict:
    res = api_client.review_individual_evaluation(
        evaluation_id, TEST_USERS["chief_credit_officer_headers"]
    )
    return get_success_data(res)


def propose_adjustment(run_id: str, amount_cents: int, run_version: int,
                       user_id: str = ANALYST, **overrides) -> dict:
    """Propose a management adjustment (PENDING) against a run."""
    res = api_client.create_management_adjustment(
        run_id,
        create_adjustment_payload(amount_cents, run_version, **overrides),
        make_credit_analyst_headers(user_id),
    )
    return get_success_data(res)


def approve_adjustment(adjustment_id: str, user_id: str = CCO) -> dict:
    res = api_client.approve_management_adjustment(
        adjustment_id, make_chief_credit_officer_headers(user_id)
    )
    return get_success_data(res)


def reject_adjustment(adjustment_id: str, user_id: str = CCO) -> dict:
    res = api_client.reject_management_adjustment(
        adjustment_id, make_chief_credit_officer_headers(user_id)
    )
    return get_success_data(res)


def get_run(run_id: str) -> dict:
    res = api_client.get_model_run(run_id, TEST_USERS["credit_analyst_headers"])
    return get_success_data(res)


def get_allowance_summary(run_id: str) -> dict:
    res = api_client.get_allowance_summary(run_id, TEST_USERS["credit_analyst_headers"])
    return get_success_data(res)


def get_segment(segment_id: str) -> dict:
    res = api_client.get_portfolio_segment(segment_id, TEST_USERS["credit_analyst_headers"])
    return get_success_data(res)


def get_model(model_id: str) -> dict:
    res = api_client.get_loss_model(model_id, TEST_USERS["model_validator_headers"])
    return get_success_data(res)


def get_run_disclosure_report(run_id: str) -> dict:
    """Fetch the single disclosure report of a FINALIZED run."""
    res = api_client.list_disclosure_reports(run_id, TEST_USERS["credit_analyst_headers"])
    rows = get_success_data(res)
    assert len(rows) == 1, f"Expected exactly 1 disclosure report, got {len(rows)}"
    return rows[0]


def record_charge_off(loan_id: str, amount_cents: int, **overrides) -> dict:
    res = api_client.charge_off_loan(
        loan_id, charge_off_payload(amount_cents, **overrides),
        TEST_USERS["credit_analyst_headers"],
    )
    return get_success_data(res)


def record_recovery(loan_id: str, amount_cents: int, **overrides) -> dict:
    res = api_client.record_recovery(
        loan_id, recovery_payload(amount_cents, **overrides),
        TEST_USERS["credit_analyst_headers"],
    )
    return get_success_data(res)


# ─── Tier 2: Entity hierarchy composite ───────────────

def setup_run_environment(model_overrides: dict = None,
                          segment_specs: list = None,
                          loan_specs: list = None,
                          scenario_specs: list = None,
                          weights_bps: list = None,
                          as_of_period: str = "2026-Q1",
                          creator_user_id: str = ANALYST) -> SimpleNamespace:
    """ACTIVE model + segments + loans + scenarios + one DRAFT run.

    - segment_specs: list of segment factory overrides; default one PRIME segment.
    - loan_specs: list of loan factory overrides, each optionally carrying
      "segment_index" (default 0) selecting the segment to book into.
    - scenario_specs: list of scenario factory overrides; default one neutral
      BASELINE scenario covering 2026-Q1..2027-Q1.
    - weights_bps: weights aligned with the created scenarios; default [10000].
    Returns a namespace(model, segments, loans, scenarios, run).
    """
    model = create_active_model(**(model_overrides or {}))

    segments = [create_segment(**spec)
                for spec in (segment_specs if segment_specs is not None else [{}])]

    loans = []
    for spec in (loan_specs if loan_specs is not None else [{}]):
        spec = dict(spec)
        segment_index = spec.pop("segment_index", 0)
        loans.append(create_loan(segments[segment_index]["id"], **spec))

    scenarios = [create_scenario(**spec)
                 for spec in (scenario_specs if scenario_specs is not None else [{}])]

    weights = weights_bps or [10_000]
    scenario_weights = [
        {"scenario_id": sc["id"], "weight_bps": w}
        for sc, w in zip(scenarios, weights)
    ]
    run = create_draft_run(model["id"], scenario_weights,
                           as_of_period=as_of_period, user_id=creator_user_id)
    return SimpleNamespace(
        model=model, segments=segments, loans=loans, scenarios=scenarios, run=run,
    )


def setup_executed_run(executor_user_id: str = ANALYST, **kwargs) -> SimpleNamespace:
    """Full environment with the run EXECUTED (segments_breakdown snapshot taken)."""
    env = setup_run_environment(**kwargs)
    env.run = execute_run(env.run["id"], user_id=executor_user_id)
    return env


def setup_under_review_run(executor_user_id: str = ANALYST, **kwargs) -> SimpleNamespace:
    """Run walked to UNDER_REVIEW (requires zero evaluations or pre-reviewed ones)."""
    env = setup_executed_run(executor_user_id=executor_user_id, **kwargs)
    env.run = submit_run_for_review(env.run["id"], user_id=executor_user_id)
    return env


def setup_approved_run(executor_user_id: str = ANALYST, approver_user_id: str = CCO,
                       **kwargs) -> SimpleNamespace:
    """Run walked to APPROVED under segregation of duties."""
    env = setup_under_review_run(executor_user_id=executor_user_id, **kwargs)
    env.run = approve_run(env.run["id"], user_id=approver_user_id)
    return env


def setup_finalized_run(period_charge_offs_cents: int = 0,
                        period_recoveries_cents: int = 0,
                        **kwargs) -> SimpleNamespace:
    """Run walked through FINALIZED; the PREPARED disclosure report is attached."""
    env = setup_approved_run(**kwargs)
    env.run = finalize_run(
        env.run["id"],
        period_charge_offs_cents=period_charge_offs_cents,
        period_recoveries_cents=period_recoveries_cents,
    )
    env.report = get_run_disclosure_report(env.run["id"])
    return env


# ─── Tier 4: Named portfolio/threshold configurations ─

def prime_loan_spec(amount_cents: int = 10_000_000, **overrides) -> dict:
    spec = {"amortized_cost_cents": amount_cents, "risk_rating": "PASS"}
    spec.update(overrides)
    return spec


def substandard_loan_spec(amount_cents: int = 500_000,
                          collateral_value_cents: int = 460_000,
                          **overrides) -> dict:
    spec = {
        "amortized_cost_cents": amount_cents,
        "risk_rating": "SUBSTANDARD",
        "collateral_value_cents": collateral_value_cents,
    }
    spec.update(overrides)
    return spec


def weighted_scenario_env(as_of_period: str = "2026-Q1", **overrides):
    """BASELINE + ADVERSE scenarios with a 60/40 weighted run (EXECUTED).

    On 10,000,000 cents of PRIME exposure this yields a quantitative reserve of
    55000 cents (lifetime rate 55 bps, blended multiplier M = 1.4).
    """
    kwargs = dict(
        loan_specs=[prime_loan_spec(10_000_000)],
        scenario_specs=[{}, adverse_scenario_payload()],
        weights_bps=[6_000, 4_000],
        as_of_period=as_of_period,
    )
    kwargs.update(overrides)
    return setup_executed_run(**kwargs)


def finalized_weighted_run():
    """FINALIZED 60/40 run (allowance 55000 / exposure 10000000 -> predicted 55 bps)."""
    return setup_finalized_run(
        loan_specs=[prime_loan_spec(10_000_000)],
        scenario_specs=[{}, adverse_scenario_payload()],
        weights_bps=[6_000, 4_000],
    )


def finalized_baseline_run():
    """FINALIZED 100% BASELINE run (allowance 50000 / exposure 10000000 -> predicted 50 bps)."""
    return setup_finalized_run(loan_specs=[prime_loan_spec(10_000_000)])


def executed_individual_run():
    """EXECUTED run whose SUBPRIME segment holds one SUBSTANDARD loan of
    500000 cents with 460000 collateral -> exactly one DRAFT evaluation with a
    COLLATERAL_FAIR_VALUE reserve of 86000 cents."""
    return setup_executed_run(
        segment_specs=[{
            "name": "SmallBiz Subprime",
            "product_type": "SMALL_BUSINESS",
            "risk_rating_band": "SUBPRIME",
            "vintage_year": 2023,
        }],
        loan_specs=[substandard_loan_spec()],
    )


def setup_watch_segment() -> SimpleNamespace:
    """Segment holding two 100000-cent PASS loans; the first is fully charged
    off, pushing the segment charge-off rate to 5000 bps (> 200) and flipping
    the segment OPEN -> WATCH."""
    segment = create_segment(
        name="Auto NP 2023", product_type="AUTO",
        risk_rating_band="NEAR_PRIME", vintage_year=2023,
    )
    loan_1 = create_loan(segment["id"], amortized_cost_cents=100_000)
    loan_2 = create_loan(segment["id"], amortized_cost_cents=100_000)
    record_charge_off(loan_1["id"], 100_000)
    return SimpleNamespace(segment=get_segment(segment["id"]), charged_loan=loan_1, other_loan=loan_2)


def record_backtest(model_id: str, **overrides) -> dict:
    """Record a back-test of a model (PASS/BREACH computed server-side)."""
    res = api_client.create_backtest(
        model_id, backtest_payload(**overrides),
        TEST_USERS["model_validator_headers"],
    )
    return get_success_data(res)
