"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server, so nothing carries over).
Lenient get_success_data is used internally so setup failures surface as
clear "Setup failed" errors instead of confusing assertion failures.

Identity threading (PRD §2.1): all roles are opaque, but user ids are recorded
for segregation-of-duties — creators default to analyst "an-1" and approvers
to chair "ch-1" so the approval boundary is always cross-operator.
"""
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ALL_PRESET_CODES,
    BOOK1_BORROWING,
    BOOK1_CURVE_BPS,
    BOOK1_DEPOSIT,
    BOOK1_LOAN,
    BOOK1_SECURITY,
    DEFAULT_PERIOD_MONTH,
)
from .factories import (
    create_alco_report_payload,
    create_assumption_set_payload,
    create_backtest_payload,
    create_book_payload,
    create_hedge_payload,
    create_policy_limit_payload,
    create_position_payload,
    create_scenario_payload,
    create_simulation_run_payload,
    deposit_beta_params,
    deposit_decay_params,
    designate_hedge_payload,
    prepayment_params,
)
from .test_users import (
    TEST_USERS,
    make_analyst_headers,
    make_chair_headers,
    make_validator_headers,
)

AN1 = TEST_USERS["analyst_headers"]
AN2 = TEST_USERS["analyst2_headers"]
MV1 = TEST_USERS["validator_headers"]
CH1 = TEST_USERS["chair_headers"]
CH2 = TEST_USERS["chair2_headers"]
REG1 = TEST_USERS["regulator_headers"]


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str, headers: Dict = AN1) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, headers))


# ---------------------------------------------------------------------------
# Books and positions (PRD §3.1)
# ---------------------------------------------------------------------------

def create_book(name: str = "Book A", base_curve_rate_bps: int = BOOK1_CURVE_BPS,
                min_hedged_notional_cents: Optional[int] = None) -> dict:
    resp = api_client.create_book(
        create_book_payload(name, base_curve_rate_bps,
                            min_hedged_notional_cents),
        AN1,
    )
    return get_success_data(resp)


def get_book(book_id: str) -> dict:
    return get_success_data(api_client.get_book(book_id, AN1))


def get_book_version(book_id: str) -> int:
    return get_book(book_id)["version"]


def add_position(book_id: str, **kwargs) -> dict:
    resp = api_client.create_position(
        book_id, create_position_payload(**kwargs), AN1)
    return get_success_data(resp)


def activate_book(book_id: str) -> dict:
    return get_success_data(api_client.activate_book(book_id, AN1))


def add_book1_positions(book_id: str) -> Dict[str, dict]:
    """Add the canonical four-position balance sheet. Returns the positions
    keyed l1/s1/d1/b1."""
    l1 = add_position(book_id, **BOOK1_LOAN)
    s1 = add_position(book_id, **BOOK1_SECURITY)
    d1 = add_position(book_id, **BOOK1_DEPOSIT)
    b1 = add_position(book_id, **BOOK1_BORROWING)
    return {"l1": l1, "s1": s1, "d1": d1, "b1": b1}


def setup_book1_active(min_hedged_notional_cents: Optional[int] = 0,
                       with_security_and_borrowing: bool = True) -> dict:
    """Canonical worked-example book, ACTIVE, with its positions.

    Returns {"book", "l1", "d1", "s1", "b1"}; s1/b1 are None when
    with_security_and_borrowing is False (two-position book: one loan and
    one retail non-maturity deposit).
    """
    book = create_book(min_hedged_notional_cents=min_hedged_notional_cents)
    if with_security_and_borrowing:
        positions = add_book1_positions(book["id"])
    else:
        positions = {
            "l1": add_position(book["id"], **BOOK1_LOAN),
            "d1": add_position(book["id"], **BOOK1_DEPOSIT),
            "s1": None,
            "b1": None,
        }
    book = activate_book(book["id"])
    return {"book": book, **positions}


# ---------------------------------------------------------------------------
# Assumption sets (PRD §3.2)
# ---------------------------------------------------------------------------

def create_assumption_set(book_id: str, domain: str, params: dict,
                          creator_user_id: str = "an-1") -> dict:
    resp = api_client.create_assumption_set(
        book_id, create_assumption_set_payload(domain, params),
        make_analyst_headers(creator_user_id))
    return get_success_data(resp)


def submit_assumption_set(set_id: str, user_id: str = "an-1") -> dict:
    return get_success_data(
        api_client.submit_assumption_set(set_id, make_analyst_headers(user_id)))


def approve_assumption_set(set_id: str, approver_user_id: str = "ch-1") -> dict:
    return get_success_data(
        api_client.approve_assumption_set(set_id,
                                          make_chair_headers(approver_user_id)))


def create_approved_set(book_id: str, domain: str, params: dict,
                        creator_user_id: str = "an-1",
                        approver_user_id: str = "ch-1") -> dict:
    """DRAFT -> SUBMITTED -> APPROVED, crossing the segregation boundary."""
    s = create_assumption_set(book_id, domain, params, creator_user_id)
    submit_assumption_set(s["id"], creator_user_id)
    return approve_assumption_set(s["id"], approver_user_id)


def get_assumption_set(set_id: str) -> dict:
    return get_success_data(api_client.get_assumption_set(set_id, AN1))


def setup_book1_approved_sets(book_id: str) -> Dict[str, dict]:
    """The three canonical approved assumption sets for the worked-example
    book. Returns {"ps", "ds", "bs"}."""
    ps = create_approved_set(book_id, "PREPAYMENT", prepayment_params())
    ds = create_approved_set(book_id, "DEPOSIT_DECAY", deposit_decay_params())
    bs = create_approved_set(book_id, "DEPOSIT_BETA", deposit_beta_params())
    return {"ps": ps, "ds": ds, "bs": bs}


# ---------------------------------------------------------------------------
# Scenarios (PRD §3.3)
# ---------------------------------------------------------------------------

def create_shock_scenario(book_id: str, shock_bps: int,
                          name: Optional[str] = None) -> dict:
    resp = api_client.create_scenario(
        book_id,
        create_scenario_payload(name or f"SHOCK{shock_bps:+d}",
                                "PARALLEL_SHOCK", shock_bps=shock_bps),
        AN1)
    return get_success_data(resp)


def create_ramp_scenario(book_id: str, ramp_total_bps: int, ramp_months: int,
                         name: Optional[str] = None) -> dict:
    resp = api_client.create_scenario(
        book_id,
        create_scenario_payload(name or f"RAMP{ramp_total_bps:+d}/{ramp_months}",
                                "RAMP", ramp_total_bps=ramp_total_bps,
                                ramp_months=ramp_months),
        AN1)
    return get_success_data(resp)


def create_preset_scenario(book_id: str, preset_code: str,
                           name: Optional[str] = None) -> dict:
    resp = api_client.create_scenario(
        book_id,
        create_scenario_payload(name or preset_code, "REGULATORY_PRESET",
                                preset_code=preset_code),
        AN1)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Simulation runs (PRD §3.4)
# ---------------------------------------------------------------------------

def create_run(book_id: str, scenario_id: str, prepayment_set_id: str,
               decay_set_id: str, beta_set_id: str,
               balance_sheet_convention: str = "STATIC",
               annual_growth_pct: Optional[float] = None,
               expected_book_version: Optional[int] = None) -> dict:
    """Create and synchronously compute a run. When expected_book_version is
    None the book is re-read first so the OCC field is current."""
    if expected_book_version is None:
        expected_book_version = get_book_version(book_id)
    resp = api_client.create_simulation_run(
        book_id,
        create_simulation_run_payload(
            scenario_id, prepayment_set_id, decay_set_id, beta_set_id,
            balance_sheet_convention, expected_book_version,
            annual_growth_pct=annual_growth_pct),
        AN1)
    return get_success_data(resp)


def get_run(run_id: str) -> dict:
    return get_success_data(api_client.get_simulation_run(run_id, AN1))


def publish_run(run_id: str) -> dict:
    return get_success_data(api_client.publish_simulation_run(run_id, AN1))


def list_runs(params: Optional[Dict] = None) -> List[dict]:
    return get_success_data(api_client.list_simulation_runs(AN1, params=params))


def setup_book1_runnable(with_security_and_borrowing: bool = True,
                         min_hedged_notional_cents: Optional[int] = 0,
                         shock_bps: int = 200) -> dict:
    """Book1 ACTIVE + three approved assumption sets + one ACTIVE parallel
    shock scenario. Returns {"book", positions..., "ps", "ds", "bs", "sc"}."""
    ctx = setup_book1_active(
        min_hedged_notional_cents=min_hedged_notional_cents,
        with_security_and_borrowing=with_security_and_borrowing)
    ctx.update(setup_book1_approved_sets(ctx["book"]["id"]))
    ctx["sc"] = create_shock_scenario(ctx["book"]["id"], shock_bps, "UP200")
    return ctx


# ---------------------------------------------------------------------------
# Policy limits and breaches (PRD §3.5)
# ---------------------------------------------------------------------------

def create_policy_limit(book_id: str, metric: str, threshold_pct: float,
                        applies_to_kinds: Optional[List[str]] = None) -> dict:
    resp = api_client.create_policy_limit(
        book_id,
        create_policy_limit_payload(metric, applies_to_kinds or ["ALL"],
                                    threshold_pct),
        CH1)
    return get_success_data(resp)


def list_breaches(params: Optional[Dict] = None,
                  headers: Dict = AN1) -> List[dict]:
    return get_success_data(api_client.list_breaches(headers, params=params))


def get_breach(breach_id: str) -> dict:
    return get_success_data(api_client.get_breach(breach_id, AN1))


def acknowledge_breach(breach_id: str, user_id: str = "ch-1") -> dict:
    return get_success_data(
        api_client.acknowledge_breach(breach_id, make_chair_headers(user_id)))


def plan_breach_remediation(breach_id: str, remediation_note: str,
                            due_date: str, user_id: str = "ch-1") -> dict:
    return get_success_data(api_client.plan_breach_remediation(
        breach_id, {"remediation_note": remediation_note, "due_date": due_date},
        make_chair_headers(user_id)))


def close_breach(breach_id: str, resolution_note: str,
                 user_id: str = "ch-1") -> dict:
    return get_success_data(api_client.close_breach(
        breach_id, {"resolution_note": resolution_note},
        make_chair_headers(user_id)))


# ---------------------------------------------------------------------------
# Hedges (PRD §3.6)
# ---------------------------------------------------------------------------

def create_hedge(book_id: str, position_id: str, **kwargs) -> dict:
    resp = api_client.create_hedge(
        book_id, create_hedge_payload(position_id, **kwargs), AN1)
    return get_success_data(resp)


def designate_hedge(hedge_id: str, start_month: str, end_month: str,
                    effectiveness_method: str,
                    user_id: str = "ch-1") -> dict:
    return get_success_data(api_client.designate_hedge(
        hedge_id, designate_hedge_payload(start_month, end_month,
                                          effectiveness_method),
        make_chair_headers(user_id)))


def activate_hedge(hedge_id: str, user_id: str = "ch-1") -> dict:
    return get_success_data(
        api_client.activate_hedge(hedge_id, make_chair_headers(user_id)))


def get_hedge(hedge_id: str) -> dict:
    return get_success_data(api_client.get_hedge(hedge_id, AN1))


def setup_active_hedge(book_id: str, position_id: str,
                       notional_cents: int = 60_000_000,
                       start_month: str = "2026-08",
                       end_month: str = "2027-08",
                       effectiveness_method: str = "DOLLAR_OFFSET",
                       **create_kwargs) -> dict:
    """PROPOSED -> DESIGNATED -> ACTIVE hedge on the given position. The
    caller must ensure the logical month has reached start_month."""
    h = create_hedge(book_id, position_id, notional_cents=notional_cents,
                     **create_kwargs)
    designate_hedge(h["id"], start_month, end_month, effectiveness_method)
    return activate_hedge(h["id"])


# ---------------------------------------------------------------------------
# Backtest reviews (PRD §3.7)
# ---------------------------------------------------------------------------

def create_backtest(book_id: str, assumption_set_id: str, start_month: str,
                    observation_months: int, observed_value_pct: float,
                    user_id: str = "mv-1") -> dict:
    resp = api_client.create_backtest(
        book_id,
        create_backtest_payload(assumption_set_id, start_month,
                                observation_months, observed_value_pct),
        make_validator_headers(user_id))
    return get_success_data(resp)


def get_backtest(backtest_id: str) -> dict:
    return get_success_data(api_client.get_backtest(backtest_id, AN1))


def close_backtest(backtest_id: str, outcome: str,
                   user_id: str = "ch-1") -> dict:
    return get_success_data(api_client.close_backtest(
        backtest_id, {"outcome": outcome}, make_chair_headers(user_id)))


# ---------------------------------------------------------------------------
# ALCO reports (PRD §3.8)
# ---------------------------------------------------------------------------

def create_alco_report(book_id: str,
                       period_month: str = DEFAULT_PERIOD_MONTH) -> dict:
    resp = api_client.create_alco_report(
        book_id, create_alco_report_payload(period_month), AN1)
    return get_success_data(resp)


def get_alco_report(report_id: str) -> dict:
    return get_success_data(api_client.get_alco_report(report_id, AN1))


def list_alco_reports(book_id: str,
                      params: Optional[Dict] = None) -> List[dict]:
    return get_success_data(
        api_client.list_alco_reports(book_id, AN1, params=params))


def submit_alco_report(report_id: str, user_id: str = "an-1") -> dict:
    return get_success_data(
        api_client.submit_alco_report(report_id,
                                      make_analyst_headers(user_id)))


# ---------------------------------------------------------------------------
# Full regulatory cycle (PRD §3.8)
# ---------------------------------------------------------------------------

def setup_full_alco_cycle(
    nii_threshold_pct: Optional[float] = None,
    eve_threshold_pct: Optional[float] = None,
    preset_codes: Optional[List[str]] = None,
    period_month: str = DEFAULT_PERIOD_MONTH,
    submit: bool = True,
    submitter_user_id: str = "an-1",
) -> dict:
    """Book1 ACTIVE with approved sets, optional policy limits, a period
    report, and one PUBLISHED run per requested regulatory preset.

    Returns {"book", "ps", "ds", "bs", "report", "scenarios", "runs",
    "breaches"}; scenarios/runs are keyed by preset code.
    """
    ctx = setup_book1_active(min_hedged_notional_cents=0)
    book_id = ctx["book"]["id"]
    ctx.update(setup_book1_approved_sets(book_id))
    if nii_threshold_pct is not None:
        ctx["nii_limit"] = create_policy_limit(book_id, "NII_DELTA_PCT",
                                               nii_threshold_pct)
    if eve_threshold_pct is not None:
        ctx["eve_limit"] = create_policy_limit(book_id, "EVE_DELTA_PCT",
                                               eve_threshold_pct)
    ctx["report"] = create_alco_report(book_id, period_month)
    ctx["scenarios"] = {}
    ctx["runs"] = {}
    for code in (preset_codes or ALL_PRESET_CODES):
        sc = create_preset_scenario(book_id, code)
        run = create_run(book_id, sc["id"], ctx["ps"]["id"], ctx["ds"]["id"],
                         ctx["bs"]["id"])
        ctx["scenarios"][code] = sc
        ctx["runs"][code] = publish_run(run["id"])
    ctx["breaches"] = list_breaches({"book_id": book_id})
    if submit:
        ctx["report"] = submit_alco_report(ctx["report"]["id"],
                                           submitter_user_id)
    return ctx
