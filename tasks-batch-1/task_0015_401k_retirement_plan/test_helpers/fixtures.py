"""Composite setup helpers for multi-step preconditions.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup failed" errors rather than confusing assertion failures.

All fixtures are PlanAdmin-driven; PlanAdmin's X-User-ID is opaque
(PRD §2.1), so the shared TEST_USERS["plan_admin_headers"] constant is safe
for every step. The Participant role is only used by test_suite code in the
RBAC tests, where headers are built explicitly per-test via
test_users.make_participant_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_plan_payload,
    create_participant_payload,
    create_contribution_period_payload,
    create_loan_payload,
    create_hardship_withdrawal_payload,
    create_rmd_distribution_payload,
    terminate_plan_payload,
    repay_loan_payload,
    deferral_rate_payload,
    set_clock_payload,
    year_tick_payload,
)
from .test_users import TEST_USERS


_ADMIN = TEST_USERS["plan_admin_headers"]


# ─── Tier 0: Clock helpers (PRD §3.8) ───────────────────────────────────────

def set_clock(iso_instant: str) -> None:
    """Advance the system clock used for age, RMD trigger, vesting (PRD §3.8)."""
    res = api_client.set_clock(set_clock_payload(iso_instant), _ADMIN)
    get_success_data(res)


def system_year_tick(as_of_year: int) -> None:
    """Drive the annual year-tick (PRD §3.8)."""
    res = api_client.year_tick(year_tick_payload(as_of_year), _ADMIN)
    get_success_data(res)


# ─── Tier 1: State Progression ──────────────────────────────────────────────

def create_plan(**overrides) -> dict:
    """Create a DRAFT plan and return it (PRD §3.1)."""
    res = api_client.create_plan(create_plan_payload(**overrides), _ADMIN)
    return get_success_data(res)


def create_and_activate_plan(**overrides) -> dict:
    """Create + activate a plan. Returns ACTIVE plan (PRD §3.1)."""
    plan = create_plan(**overrides)
    res = api_client.activate_plan(plan["id"], _ADMIN)
    return get_success_data(res)


def create_pending_participant(plan_id: str, **overrides) -> dict:
    """Create a PENDING participant (PRD §3.2)."""
    res = api_client.create_participant(create_participant_payload(plan_id, **overrides), _ADMIN)
    return get_success_data(res)


def create_and_enroll_participant(plan_id: str, **overrides) -> dict:
    """Create + enroll a participant. Returns ENROLLED participant (PRD §3.2)."""
    p = create_pending_participant(plan_id, **overrides)
    res = api_client.enroll_participant(p["id"], _ADMIN)
    return get_success_data(res)


# ─── Tier 2: Plan + enrolled participant (most common preamble) ─────────────

def setup_active_plan_with_enrolled_participant(
    *,
    plan_overrides: dict = None,
    participant_overrides: dict = None,
    clock_iso: str = "2026-06-15T00:00:00Z",
) -> tuple:
    """Clock + ACTIVE plan + ENROLLED participant. Returns (plan, participant)."""
    set_clock(clock_iso)
    plan = create_and_activate_plan(**(plan_overrides or {}))
    participant = create_and_enroll_participant(plan["id"], **(participant_overrides or {}))
    return plan, participant


# ─── Tier 3: ContributionPeriod helpers (close = full match calc + cascades) ─

def create_open_contribution_period(participant_id: str, **overrides) -> dict:
    res = api_client.create_contribution_period(
        create_contribution_period_payload(participant_id, **overrides), _ADMIN
    )
    return get_success_data(res)


def close_contribution_period(cp_id: str) -> dict:
    res = api_client.close_contribution_period(cp_id, _ADMIN)
    return get_success_data(res)


def create_and_close_contribution_period(participant_id: str, **overrides) -> dict:
    """Create + close a contribution period. Returns CLOSED period (PRD §3.3)."""
    cp = create_open_contribution_period(participant_id, **overrides)
    return close_contribution_period(cp["id"])


# ─── Tier 4: Loan helpers ───────────────────────────────────────────────────

def create_requested_loan(participant_id: str, **overrides) -> dict:
    res = api_client.create_loan(create_loan_payload(participant_id, **overrides), _ADMIN)
    return get_success_data(res)


def disburse_loan(loan_id: str) -> dict:
    res = api_client.disburse_loan(loan_id, _ADMIN)
    return get_success_data(res)


def create_and_disburse_loan(participant_id: str, **overrides) -> dict:
    """Create + disburse a loan. Returns DISBURSED loan (PRD §3.4)."""
    loan = create_requested_loan(participant_id, **overrides)
    return disburse_loan(loan["id"])


def repay_loan_fully(loan_id: str, amount_cents: int) -> dict:
    res = api_client.repay_loan(loan_id, repay_loan_payload(amount_cents), _ADMIN)
    return get_success_data(res)


# ─── Tier 5: Composite — participant with seeded balances ──────────────────

def setup_participant_with_seeded_balances(
    *,
    clock_iso: str = "2026-06-15T00:00:00Z",
    plan_overrides: dict = None,
    participant_overrides: dict = None,
    contribution_periods: int = 1,
    gross_compensation_cents: int = 500_000,
    period_end_date: str = "2026-06-15T00:00:00Z",
) -> tuple:
    """ACTIVE plan + ENROLLED participant + N closed ContributionPeriods.
    Returns (plan, participant_after_last_close, list_of_closed_periods).

    Each closed period cascades to participant balances (PRD §3.3), so the
    returned participant carries the post-cascade employee/employer/vested
    balances visible after the last close.
    """
    plan, participant = setup_active_plan_with_enrolled_participant(
        plan_overrides=plan_overrides,
        participant_overrides=participant_overrides,
        clock_iso=clock_iso,
    )
    closed_periods = []
    for _i in range(contribution_periods):
        cp = create_and_close_contribution_period(
            participant["id"],
            gross_compensation_cents=gross_compensation_cents,
            period_end_date=period_end_date,
        )
        closed_periods.append(cp)
    # Re-fetch the participant for the post-cascade view
    participant = get_success_data(api_client.get_participant(participant["id"], _ADMIN))
    return plan, participant, closed_periods


# ─── Tier 6: Composite — hardship preconditions ─────────────────────────────

def setup_with_requested_hardship(
    *,
    clock_iso: str = "2026-06-15T00:00:00Z",
    plan_overrides: dict = None,
    participant_overrides: dict = None,
    contribution_periods: int = 0,
    gross_compensation_cents: int = 500_000,
    requested_amount_cents: int = 100_000,
    hardship_category: str = "MEDICAL_EXPENSES",
) -> tuple:
    """ACTIVE plan + ENROLLED participant + N closed contributions + REQUESTED hardship.
    Returns (plan, participant, hardship)."""
    plan, participant, _periods = setup_participant_with_seeded_balances(
        clock_iso=clock_iso,
        plan_overrides=plan_overrides,
        participant_overrides=participant_overrides,
        contribution_periods=contribution_periods,
        gross_compensation_cents=gross_compensation_cents,
    )
    h = get_success_data(api_client.create_hardship_withdrawal(
        create_hardship_withdrawal_payload(
            participant["id"],
            requested_amount_cents=requested_amount_cents,
            hardship_category=hardship_category,
        ),
        _ADMIN,
    ))
    return plan, participant, h


# ─── Tier 7: Composite — disbursed loan on enrolled participant ─────────────

def setup_with_disbursed_loan(
    *,
    clock_iso: str = "2026-06-15T00:00:00Z",
    plan_overrides: dict = None,
    participant_overrides: dict = None,
    seed_contribution_periods: int = 1,
    gross_compensation_cents: int = 10_000_000,
    loan_principal_cents: int = 20_000,
    loan_term_months: int = 12,
    loan_rate_bps: int = 700,
) -> tuple:
    """ACTIVE plan + ENROLLED participant + seeded balances + DISBURSED loan.
    Returns (plan, participant, loan).

    The participant's hire_date defaults to 2018-06-15 (yos=8 at clock 2026-06-15
    under the default GRADED_6 plan) so the loan headroom is large enough for
    most test loan amounts.
    """
    plan, participant, _periods = setup_participant_with_seeded_balances(
        clock_iso=clock_iso,
        plan_overrides=plan_overrides or {
            "match_formula": "TIERED",
            "vesting_schedule": "GRADED_6",
        },
        participant_overrides=participant_overrides or {
            "hire_date": "2018-06-15T00:00:00Z",
            "annual_compensation_cents": 50_000_000,
            "deferral_rate_bps": 400,
        },
        contribution_periods=seed_contribution_periods,
        gross_compensation_cents=gross_compensation_cents,
    )
    loan = create_and_disburse_loan(
        participant["id"],
        principal_cents=loan_principal_cents,
        term_months=loan_term_months,
        annual_interest_rate_bps=loan_rate_bps,
    )
    return plan, participant, loan


# ─── Tier 8: Composite — RMD-eligible participant ───────────────────────────

def setup_rmd_eligible_participant(
    *,
    clock_iso: str = "2026-06-15T00:00:00Z",
    plan_overrides: dict = None,
    date_of_birth: str = "1954-01-01T00:00:00Z",   # age 73 at 2026-12-31
    hire_date: str = "2010-01-01T00:00:00Z",
) -> tuple:
    """ACTIVE plan + ENROLLED participant whose age at year-end >= 73.
    Returns (plan, participant)."""
    plan, participant = setup_active_plan_with_enrolled_participant(
        plan_overrides=plan_overrides,
        participant_overrides={
            "date_of_birth": date_of_birth,
            "hire_date": hire_date,
        },
        clock_iso=clock_iso,
    )
    return plan, participant


# ─── Tier 9: Plan-version-pre-terminate read (OCC, PRD §2.7) ────────────────

def read_plan_version(plan_id: str) -> int:
    """Read the current plan version for use as expected_plan_version on terminate."""
    plan = get_success_data(api_client.get_plan(plan_id, _ADMIN))
    return plan["version"]


def terminate_plan_with_current_version(plan_id: str) -> dict:
    """GET version, then terminate with that as expected_plan_version (PRD §2.7)."""
    v = read_plan_version(plan_id)
    res = api_client.terminate_plan(plan_id, terminate_plan_payload(v), _ADMIN)
    return get_success_data(res)


# ─── Tier 10: Convenience getters ───────────────────────────────────────────

def get_participant(participant_id: str) -> dict:
    return get_success_data(api_client.get_participant(participant_id, _ADMIN))


def get_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_plan(plan_id, _ADMIN))


def get_loan(loan_id: str) -> dict:
    return get_success_data(api_client.get_loan(loan_id, _ADMIN))


def get_contribution_period(cp_id: str) -> dict:
    return get_success_data(api_client.get_contribution_period(cp_id, _ADMIN))


def get_hardship_withdrawal(h_id: str) -> dict:
    return get_success_data(api_client.get_hardship_withdrawal(h_id, _ADMIN))


def get_rmd_distribution(rmd_id: str) -> dict:
    return get_success_data(api_client.get_rmd_distribution(rmd_id, _ADMIN))


def update_deferral_rate(participant_id: str, deferral_rate_bps: int) -> dict:
    res = api_client.update_deferral_rate(
        participant_id, deferral_rate_payload(deferral_rate_bps), _ADMIN
    )
    return get_success_data(res)
