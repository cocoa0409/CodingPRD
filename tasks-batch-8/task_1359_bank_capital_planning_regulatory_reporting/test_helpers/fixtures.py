"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data() so a
setup failure surfaces as a clear "Setup step failed" error.

Segregation of duties (PRD §3.3, §3.5, §3.8): the analyst who prepares a
call report / submits a plan to the board / prepares an ICAAP document must
be a different X-User-ID than the one who submits / board-approves / attests.
These helpers use distinct named users per workflow step.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_bank_payload,
    create_reporting_period_payload,
    create_capital_instrument_payload,
    create_risk_exposure_payload,
    create_stress_scenario_payload,
    create_capital_plan_payload,
    create_distribution_request_payload,
    create_sub_debt_issuance_payload,
    create_icaap_document_payload,
)
from .test_users import (
    TEST_USERS,
    make_capital_analyst_headers,
    make_regulator_reviewer_headers,
    make_board_approver_headers,
    make_system_operator_headers,
)

SYSOP = TEST_USERS["system_operator_headers"]
ANALYST = TEST_USERS["capital_analyst_headers"]
REGULATOR = TEST_USERS["regulator_reviewer_headers"]
BOARD = TEST_USERS["board_approver_headers"]
AUDITOR = TEST_USERS["external_auditor_headers"]

# Distinct operator ids so segregation-of-duties checks pass.
PREPARER_USER_ID = "analyst-preparer-1"
SUBMITTER_USER_ID = "analyst-submitter-1"
BOARD_USER_ID = "board-1"


def set_clock(to_iso8601):
    """Advance the logical clock (SystemOperator only)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, make_system_operator_headers("sysop-1"))
    )


def advance_clock_past(iso_date):
    """Advance the logical clock to just past the given calendar date so the
    OPEN -> FILING_DUE time-triggered transition fires for periods ending
    that day (PRD §2.5: advancing the clock fires every time-triggered
    transition whose moment has arrived). Monotonicity is preserved by
    nudging one second forward when the clock already passed the date."""
    from datetime import datetime, timedelta, timezone

    current = get_success_data(api_client.get_clock(SYSOP))["current_utc"]
    current_dt = datetime.fromisoformat(current.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(f"{iso_date}T00:00:00+00:00") + timedelta(days=1)
    target = max(end_dt, current_dt + timedelta(seconds=1))
    target_iso = target.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if target_iso != current:
        set_clock(target_iso)
    return target_iso


# ─── Tier 1: Bank + period primitives ──────────────────

def create_bank(charter_id, methodology=None, legal_name=None):
    """Create a Bank. Returns the bank dict."""
    payload = create_bank_payload(
        legal_name=legal_name or f"Bank {charter_id}",
        charter_id=charter_id,
    )
    if methodology is not None:
        payload["rwa_methodology"] = methodology
    res = api_client.create_bank(payload, SYSOP)
    return get_success_data(res)


def create_period(bank_id, period_end_date="2026-06-30", period_year=2026, period_quarter="Q2"):
    """Create a ReportingPeriod. Returns the period dict."""
    res = api_client.create_reporting_period(
        bank_id,
        create_reporting_period_payload(
            period_end_date=period_end_date,
            period_year=period_year,
            period_quarter=period_quarter,
        ),
        ANALYST,
    )
    return get_success_data(res)


def add_instrument(bank_id, **overrides):
    """Create a CapitalInstrument. Defaults to a CET1 common-stock row."""
    res = api_client.create_capital_instrument(
        bank_id, create_capital_instrument_payload(**overrides), ANALYST
    )
    return get_success_data(res)


def add_exposure(bank_id, period_id, **overrides):
    """Create a RiskExposure for a period. Defaults to one 100%-weighted CORPORATE line."""
    res = api_client.create_risk_exposure(
        bank_id, period_id, create_risk_exposure_payload(period_id, **overrides), ANALYST
    )
    return get_success_data(res)


# ─── Tier 2: Call report lifecycle ─────────────────────

def create_prepared_call_report(bank_id, period_id, preparer_user_id=PREPARER_USER_ID):
    """Create a draft call report and prepare it. Returns the report dict
    (VALIDATED when no edits are open, EDITS_OUTSTANDING otherwise)."""
    report = get_success_data(api_client.create_call_report(bank_id, period_id, {}, ANALYST))
    prepared = get_success_data(
        api_client.prepare_call_report(
            bank_id, period_id, report["id"], make_capital_analyst_headers(preparer_user_id)
        )
    )
    return prepared


def setup_accepted_report(charter_id, cet1_cents, rwa_cents, methodology=None):
    """Bank + 2026Q2 period + one 100%-weighted CORPORATE exposure sized to
    `rwa_cents` + one CET1 instrument sized to `cet1_cents`; call report
    prepared, submitted, accepted.

    The clock is advanced past the period end before submission so the
    period has explicitly transitioned to FILING_DUE (PRD §2.5) and the
    FILING_DUE -> SUBMITTED path is taken unambiguously.

    Returns (bank, period, report)."""
    bank = create_bank(charter_id, methodology=methodology)
    period = create_period(bank["id"])
    add_exposure(bank["id"], period["id"], exposure_at_default_cents=rwa_cents)
    add_instrument(bank["id"], outstanding_amount_cents=cet1_cents)
    report = create_prepared_call_report(bank["id"], period["id"])
    advance_clock_past(period["period_end_date"])
    submitted = get_success_data(
        api_client.submit_call_report(
            bank["id"], period["id"], report["id"],
            make_capital_analyst_headers(SUBMITTER_USER_ID),
        )
    )
    accepted = get_success_data(
        api_client.accept_call_report(bank["id"], period["id"], submitted["id"], REGULATOR)
    )
    bank = get_success_data(api_client.get_bank(bank["id"], ANALYST))
    return bank, period, accepted


# ─── Tier 3: Stress scenarios and capital plans ────────

def create_active_scenario(bank_id, scenario_code, **overrides):
    """Create + activate a StressScenario. Returns the activated scenario."""
    scenario = get_success_data(
        api_client.create_stress_scenario(
            bank_id, create_stress_scenario_payload(scenario_code=scenario_code, **overrides), ANALYST
        )
    )
    return get_success_data(api_client.activate_stress_scenario(bank_id, scenario["id"], ANALYST))


def create_draft_plan(bank_id, period_id, scenario_id, plan_year=2027):
    """Create a CapitalPlan in DRAFT."""
    return get_success_data(
        api_client.create_capital_plan(
            bank_id,
            create_capital_plan_payload(
                baseline_period_id=period_id, stress_scenario_id=scenario_id, plan_year=plan_year
            ),
            ANALYST,
        )
    )


def setup_plan_in_board_review(charter_id, cet1_cents, rwa_cents, scenario_code="BASE-SCEN",
                               methodology=None, scenario_overrides=None):
    """Accepted report + ACTIVE scenario + CapitalPlan in BOARD_REVIEW.
    Returns (bank, period, report, scenario, plan)."""
    bank, period, report = setup_accepted_report(
        charter_id, cet1_cents, rwa_cents, methodology=methodology
    )
    scenario = create_active_scenario(bank["id"], scenario_code, **(scenario_overrides or {}))
    plan = create_draft_plan(bank["id"], period["id"], scenario["id"])
    plan = get_success_data(
        api_client.submit_plan_board(
            bank["id"], plan["id"], make_capital_analyst_headers(PREPARER_USER_ID)
        )
    )
    bank = get_success_data(api_client.get_bank(bank["id"], ANALYST))
    return bank, period, report, scenario, plan


def setup_plan_submitted(charter_id, cet1_cents, rwa_cents, scenario_code="BASE-SCEN",
                         methodology=None, scenario_overrides=None):
    """CapitalPlan walked to SUBMITTED (board approved).
    Returns (bank, period, report, scenario, plan)."""
    bank, period, report, scenario, plan = setup_plan_in_board_review(
        charter_id, cet1_cents, rwa_cents, scenario_code=scenario_code,
        methodology=methodology, scenario_overrides=scenario_overrides,
    )
    plan = get_success_data(
        api_client.board_approve_plan(
            bank["id"], plan["id"], make_board_approver_headers(BOARD_USER_ID)
        )
    )
    bank = get_success_data(api_client.get_bank(bank["id"], ANALYST))
    return bank, period, report, scenario, plan


def setup_plan_in_supervisory_review(charter_id, cet1_cents, rwa_cents, scenario_code="BASE-SCEN",
                                     methodology=None, scenario_overrides=None):
    """CapitalPlan walked to SUPERVISORY_REVIEW (submitted to regulator with
    a fresh expected_bank_version).
    Returns (bank, period, report, scenario, plan)."""
    bank, period, report, scenario, plan = setup_plan_submitted(
        charter_id, cet1_cents, rwa_cents, scenario_code=scenario_code,
        methodology=methodology, scenario_overrides=scenario_overrides,
    )
    bank = get_success_data(api_client.get_bank(bank["id"], ANALYST))
    plan = get_success_data(
        api_client.submit_plan_regulator(
            bank["id"], plan["id"], {"expected_bank_version": bank["version"]}, ANALYST
        )
    )
    bank = get_success_data(api_client.get_bank(bank["id"], ANALYST))
    return bank, period, report, scenario, plan


def setup_plan_approved(charter_id, cet1_cents, rwa_cents, scenario_code="BASE-SCEN",
                        methodology=None, scenario_overrides=None):
    """CapitalPlan walked to APPROVED (regulator approved).
    Returns (bank, period, report, scenario, plan)."""
    bank, period, report, scenario, plan = setup_plan_in_supervisory_review(
        charter_id, cet1_cents, rwa_cents, scenario_code=scenario_code,
        methodology=methodology, scenario_overrides=scenario_overrides,
    )
    plan = get_success_data(api_client.regulator_approve_plan(bank["id"], plan["id"], REGULATOR))
    bank = get_success_data(api_client.get_bank(bank["id"], ANALYST))
    return bank, period, report, scenario, plan


def create_payment_period(bank_id, period_end_date="2027-03-31", period_year=2027,
                          period_quarter="Q1"):
    """Create the reporting period in which distributions are paid. Payment
    dates must fall within the period's quarter and not precede the current
    date (PRD §3.6); Q1 2027 paired with payment date 2027-03-15 satisfies
    both at the default clock and after the plan-year activation crossing."""
    return create_period(bank_id, period_end_date, period_year, period_quarter)


def setup_accepted_report_with_live_scenario(charter_id, cet1_cents, rwa_cents, scenario_code,
                                             scenario_overrides=None):
    """Bank + period + exposure + CET1 instrument; scenario created and
    ACTIVATED while the period is still OPEN (so the activation-time loss
    projection includes the period's exposures, per PRD §3.5's inventory
    filter); then the call report is prepared, submitted, and accepted.

    Returns (bank, period, accepted_report, scenario)."""
    bank = create_bank(charter_id)
    period = create_period(bank["id"])
    add_exposure(bank["id"], period["id"], exposure_at_default_cents=rwa_cents)
    add_instrument(bank["id"], outstanding_amount_cents=cet1_cents)
    scenario = create_active_scenario(bank["id"], scenario_code, **(scenario_overrides or {}))
    report = create_prepared_call_report(bank["id"], period["id"])
    advance_clock_past(period["period_end_date"])
    validate = api_client.submit_call_report(
        bank["id"], period["id"], report["id"],
        make_capital_analyst_headers(SUBMITTER_USER_ID),
    )
    submitted = get_success_data(validate)
    accepted = get_success_data(
        api_client.accept_call_report(bank["id"], period["id"], submitted["id"], REGULATOR)
    )
    bank = get_success_data(api_client.get_bank(bank["id"], ANALYST))
    return bank, period, accepted, scenario


def setup_distributable_bank(charter_id, cet1_cents=10_000_000_000,
                             rwa_cents=100_000_000_000, scenario_code="BASE-DIST",
                             extra_cet1_cents=5_000_000_000, pre_cross_hook=None):
    """Build a bank whose mdba_cents is positive, so distribution approvals
    can succeed.

    The maximum distributable amount is the smaller of PCA capacity and
    stress-buffer capacity minus pending distributions (PRD §3.6);
    stress-buffer capacity is zero until a plan is EFFECTIVE, and the buffer
    recorded at approval exactly consumes the stressed headroom, so a
    positive pool requires the plan's stressed minimum to improve after
    approval. The reachable route: an amendment on the baseline period after
    an additional CET1 issuance refreshes the plan's baseline upward
    (PRD §3.4); the plan then activates to EFFECTIVE on the first day of its
    plan year (PRD §2.5) and the pool opens.

    `pre_cross_hook`, when given, is invoked as
    `pre_cross_hook(bank_id, plan, pay_period)` just before the clock crosses
    into the plan year — while the plan is still APPROVED. PRD §3.6 gates
    distribution proposals to plans in DRAFT, BOARD_REVIEW, SUBMITTED,
    SUPERVISORY_REVIEW, or APPROVED, so any distribution a test needs must be
    proposed inside this hook (proposing against an EFFECTIVE plan is
    correctly rejected with ERR_INVALID_STATE_TRANSITION).

    Returns (bank, base_period, pay_period, scenario, plan)."""
    bank, period, report, scenario = setup_accepted_report_with_live_scenario(
        charter_id, cet1_cents, rwa_cents, scenario_code
    )
    plan = create_draft_plan(bank["id"], period["id"], scenario["id"])
    plan = get_success_data(
        api_client.submit_plan_board(
            bank["id"], plan["id"], make_capital_analyst_headers(PREPARER_USER_ID)
        )
    )
    plan = get_success_data(
        api_client.board_approve_plan(
            bank["id"], plan["id"], make_board_approver_headers(BOARD_USER_ID)
        )
    )
    bank = get_success_data(api_client.get_bank(bank["id"], ANALYST))
    plan = get_success_data(
        api_client.submit_plan_regulator(
            bank["id"], plan["id"], {"expected_bank_version": bank["version"]}, ANALYST
        )
    )
    plan = get_success_data(api_client.regulator_approve_plan(bank["id"], plan["id"], REGULATOR))
    assert plan["status"] == "APPROVED", f"Setup: plan not APPROVED: {plan}"
    # CET1 top-up, then a full amendment cycle on the baseline period so the
    # plan's refreshed stressed minimum rises above the recorded buffer.
    add_instrument(bank["id"], outstanding_amount_cents=extra_cet1_cents)
    amend = get_success_data(
        api_client.open_amendment(bank["id"], period["id"], report["id"], ANALYST)
    )
    prepared = get_success_data(
        api_client.prepare_call_report(
            bank["id"], period["id"], amend["id"],
            make_capital_analyst_headers(PREPARER_USER_ID),
        )
    )
    submitted = get_success_data(
        api_client.submit_call_report(
            bank["id"], period["id"], prepared["id"],
            make_capital_analyst_headers(SUBMITTER_USER_ID),
        )
    )
    get_success_data(
        api_client.accept_call_report(bank["id"], period["id"], submitted["id"], REGULATOR)
    )
    plan = get_success_data(api_client.get_capital_plan(bank["id"], plan["id"], ANALYST))
    assert plan["status"] == "APPROVED", f"Setup: plan superseded by amendment: {plan}"
    pay_period = create_payment_period(bank["id"])
    if pre_cross_hook is not None:
        pre_cross_hook(bank["id"], plan, pay_period)
    # Cross into the plan year: APPROVED -> EFFECTIVE (PRD §2.5).
    set_clock("2027-01-01T00:00:01Z")
    plan = get_success_data(api_client.get_capital_plan(bank["id"], plan["id"], ANALYST))
    assert plan["status"] == "EFFECTIVE", f"Setup: plan not EFFECTIVE after clock cross: {plan}"
    bank = get_success_data(api_client.get_bank(bank["id"], ANALYST))
    return bank, period, pay_period, scenario, plan


# ─── Tier 4: Distributions and sub-debt ────────────────

def create_proposed_distribution(bank_id, plan_id, period_id, **overrides):
    """Create a CapitalDistributionRequest in PROPOSED."""
    return get_success_data(
        api_client.create_distribution_request(
            bank_id,
            create_distribution_request_payload(plan_id, period_id, **overrides),
            ANALYST,
        )
    )


def approve_distribution(bank_id, request_id):
    """Approve a distribution using the bank's current version. Returns the
    approved request dict."""
    bank = get_success_data(api_client.get_bank(bank_id, ANALYST))
    return get_success_data(
        api_client.approve_distribution(
            bank_id, request_id, {"expected_bank_version": bank["version"]}, ANALYST
        )
    )


def setup_approved_distribution(charter_id, dist_amount_cents=50_000_000,
                                payment_date="2027-03-15", scenario_code="BASE-DIST"):
    """EFFECTIVE plan on a bank with a positive distributable pool, plus one
    APPROVED_NOT_EXECUTED distribution due on `payment_date`.

    The distribution is proposed while the plan is still APPROVED (PRD §3.6
    gates proposals to DRAFT…APPROVED), then approved after the plan-year
    clock crossing has made the plan EFFECTIVE and opened the pool
    (PRD §3.6: approval requires the plan to have "reached APPROVED").

    Returns (bank, base_period, pay_period, scenario, plan, distribution)."""
    created = {}

    def _propose(bank_id, plan, pay_period):
        created["dist"] = create_proposed_distribution(
            bank_id, plan["id"], pay_period["id"],
            distribution_amount_cents=dist_amount_cents,
            proposed_payment_date=payment_date,
        )

    bank, base_period, pay_period, scenario, plan = setup_distributable_bank(
        charter_id, scenario_code=scenario_code, pre_cross_hook=_propose
    )
    dist = approve_distribution(bank["id"], created["dist"]["id"])
    assert dist["status"] == "APPROVED_NOT_EXECUTED", f"Setup: approve failed: {dist}"
    bank = get_success_data(api_client.get_bank(bank["id"], ANALYST))
    return bank, base_period, pay_period, scenario, plan, dist


def create_proposed_sub_debt(bank_id, **overrides):
    """Create a SubordinatedDebtIssuance in PROPOSED."""
    return get_success_data(
        api_client.create_sub_debt_issuance(
            bank_id, create_sub_debt_issuance_payload(**overrides), ANALYST
        )
    )


def approve_sub_debt(bank_id, issuance_id):
    """Approve a sub-debt issuance using the bank's current version."""
    bank = get_success_data(api_client.get_bank(bank_id, ANALYST))
    return get_success_data(
        api_client.approve_sub_debt(
            bank_id, issuance_id, {"expected_bank_version": bank["version"]}, ANALYST
        )
    )


def setup_priced_sub_debt(charter_id, proposed_amount_cents, settlement_date="2026-08-15",
                          maturity_years=10, cet1_cents=10_000_000_000,
                          rwa_cents=100_000_000_000):
    """Bank with accepted report + one sub-debt issuance walked to PRICED.
    Returns (bank, period, report, issuance)."""
    bank, period, report = setup_accepted_report(charter_id, cet1_cents, rwa_cents)
    issuance = create_proposed_sub_debt(
        bank["id"],
        proposed_amount_cents=proposed_amount_cents,
        target_settlement_date=settlement_date,
        maturity_years=maturity_years,
    )
    issuance = approve_sub_debt(bank["id"], issuance["id"])
    issuance = get_success_data(api_client.price_sub_debt(bank["id"], issuance["id"], ANALYST))
    bank = get_success_data(api_client.get_bank(bank["id"], ANALYST))
    return bank, period, report, issuance


def set_clock(to_iso8601):
    """Advance the logical clock (SystemOperator only)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, make_system_operator_headers("sysop-1"))
    )


def bump_bank_version(bank_id):
    """Perform a trivial capacity-affecting mutation (create a small AT1
    instrument) so the bank's version increments — used to stale a
    previously captured expected_bank_version. Returns the new bank dict."""
    add_instrument(
        bank_id,
        instrument_class="AT1",
        instrument_subtype="PREFERRED",
        outstanding_amount_cents=100_000_000,
        issuance_date="2026-08-01",
        contractual_rate_bps=600,
    )
    return get_success_data(api_client.get_bank(bank_id, ANALYST))
