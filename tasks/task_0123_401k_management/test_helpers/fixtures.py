"""Composite setup helpers — multi-step preambles tests can reuse.

The 401(k) pipeline is long. A typical test claim (e.g., "max-loan
boundary at $50,000", "first-year RMD due-date is April 1 of the
following year", "deferral-suspension gate") requires the system in a
state that takes many API calls to reach:

  POST /plans (DRAFT)
    -> POST /plans/{id}/activate  (-> ACTIVE; PlanClock created)
    -> POST /plans/{id}/_clock/advance  (move clock to a known date)
    -> POST /plans/{id}/participants  (ENROLLED)
    -> POST /plans/{id}/participants/{id}/activate  (-> ACTIVE)
    -> POST .../contribution-records  N times  (accumulate balance)
    -> POST .../loans / hardship-withdrawals / rmd-schedules
    -> POST .../approve  / .../fulfill  / etc.

There is no test-only "seed balance" endpoint in PRD §4 — the only way
to grow Participant.total_account_balance_cents is to post
ContributionRecord rows under the live formulas. The annual caps
(PRD §3.3: employee $23,500, employer $46,000) cap each calendar year,
so fixtures that need a large pre-existing balance advance the plan
clock across calendar boundaries and post contributions in each year.

IDENTITY THREADING — PRD §2.1:

- PlanAdministrator / PayrollProcessor / ComplianceOfficer are OPAQUE.
  Shared constants (admin_headers, payroll_headers, compliance_headers)
  are canonical for every operator-only call.

- Participant is ENTITY-BACKED. Every Participant-driven call whose
  success depends on owning the targeted resource MUST mint headers
  via make_participant_headers(participant["id"]) — never via the
  shared PARTICIPANT_FALLBACK_ID constant. The fixtures here always
  thread the actual Participant.id into the header builder when a
  participant-acting call is needed.

SEGREGATION OF DUTIES — PRD §2.1: the same X-User-ID may not perform
two adjacent steps in the same workflow on the same plan. Concretely,
a Participant requests a loan (their own id is the requester); a
PlanAdministrator approves it (different opaque admin id). A
PayrollProcessor posting contributions and a PlanAdministrator
approving a loan against the resulting balance must be different
X-User-IDs within the same plan year.

Setup calls use get_success_data (lenient 2xx validator), so a failed
setup surfaces as "Setup step failed" rather than a misleading test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    EMPLOYEE_ANNUAL_LIMIT_CENTS,
    EMPLOYER_ANNUAL_LIMIT_CENTS,
    TEST_DEFAULTS,
)
from .factories import (
    clock_advance_payload,
    create_contribution_payload,
    create_hardship_payload,
    create_loan_payload,
    create_loan_repayment_payload,
    create_participant_payload,
    create_plan_payload,
    create_rmd_payload,
    fulfill_rmd_payload,
)
from .test_users import TEST_USERS, make_participant_headers


# ===========================================================================
# Tier 0: low-level helpers
# ===========================================================================
def advance_clock(plan_id: str, new_date: str,
                  headers: Optional[Dict[str, str]] = None,
                  ) -> Dict[str, Any]:
    """POST /plans/{planId}/_clock/advance — PlanAdministrator only
    (PRD §4).

    PRD §3.1: a plan's PlanClock is initialized to today's UTC date at
    plan activation; PRD §3.1/§4 require advances to be strictly
    forward (ERR_CLOCK_NOT_MONOTONIC otherwise). Tests pin their
    intended clock position with fixed calendar dates; once the
    harness's wall-clock drifts past those dates the implementation
    correctly rejects the advance. To keep test setup idempotent
    regardless of when the test container is run, this helper SILENTLY
    NO-OPS when the implementation reports ERR_CLOCK_NOT_MONOTONIC,
    meaning the clock is already at-or-beyond the requested anchor. The
    implementation continues to reject backwards advances per PRD; this
    fixture-only guard never weakens the implementation contract.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.advance_clock(
        plan_id, clock_advance_payload(new_date=new_date), headers,
    )
    if resp.status_code == 422:
        try:
            body = resp.json()
            data = body.get("data", {}) if isinstance(body, dict) else {}
            if isinstance(data, dict) and data.get("error_id") == "ERR_CLOCK_NOT_MONOTONIC":
                # No-op: clock is already at or beyond the requested
                # anchor; treat as success for fixture chaining.
                return {"current_date": new_date, "no_op": True}
        except Exception:
            pass
    return get_success_data(resp)


def get_plan(plan_id: str,
             headers: Optional[Dict[str, str]] = None
             ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(api_client.get_plan(plan_id, headers))


def get_participant(plan_id: str, participant_id: str,
                    headers: Optional[Dict[str, str]] = None
                    ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.get_participant(plan_id, participant_id, headers),
    )


def get_loan(plan_id: str, participant_id: str, loan_id: str,
             headers: Optional[Dict[str, str]] = None
             ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.get_loan(plan_id, participant_id, loan_id, headers),
    )


# ===========================================================================
# Tier 1: Plan creation and activation
# ===========================================================================
def create_draft_plan(
    *,
    match_formula_type: str = "SAFE_HARBOR_BASIC",
    tiered_brackets: Optional[List[Dict[str, Any]]] = None,
    vesting_schedule_type: str = "CLIFF",
    cliff_years: Optional[int] = 3,
    graded_percentages: Optional[List[int]] = None,
    plan_year: int = 2026,
    plan_name: Optional[str] = None,
    rmd_age: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /plans — DRAFT state. PlanAdministrator only (PRD §4)."""
    headers = headers or TEST_USERS["admin_headers"]
    payload = create_plan_payload(
        plan_name=plan_name,
        plan_year=plan_year,
        match_formula_type=match_formula_type,
        tiered_brackets=tiered_brackets,
        vesting_schedule_type=vesting_schedule_type,
        cliff_years=cliff_years,
        graded_percentages=graded_percentages,
        rmd_age=rmd_age,
    )
    return get_success_data(api_client.create_plan(payload, headers))


def create_and_activate_plan(
    *,
    match_formula_type: str = "SAFE_HARBOR_BASIC",
    tiered_brackets: Optional[List[Dict[str, Any]]] = None,
    vesting_schedule_type: str = "CLIFF",
    cliff_years: Optional[int] = 3,
    graded_percentages: Optional[List[int]] = None,
    plan_year: int = 2026,
    plan_name: Optional[str] = None,
    rmd_age: Optional[int] = None,
    advance_clock_to: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a draft plan and transition it to ACTIVE. Optionally
    advance the plan clock to a known YYYY-MM-DD afterwards so tests
    that depend on hire_date / next_due_date / due_date arithmetic
    have a deterministic starting clock.

    PRD §3.1: 'A successful activation creates the singleton PlanClock
    row for this plan with current_date set to today's UTC date.' This
    is the only time wall-clock leaks into the system; afterward only
    advance_clock moves it.
    """
    headers = headers or TEST_USERS["admin_headers"]
    plan = create_draft_plan(
        match_formula_type=match_formula_type,
        tiered_brackets=tiered_brackets,
        vesting_schedule_type=vesting_schedule_type,
        cliff_years=cliff_years,
        graded_percentages=graded_percentages,
        plan_year=plan_year,
        plan_name=plan_name,
        rmd_age=rmd_age,
        headers=headers,
    )
    plan = get_success_data(
        api_client.activate_plan(plan["id"], None, headers),
    )
    if advance_clock_to is not None:
        advance_clock(plan["id"], advance_clock_to, headers=headers)
        plan = get_plan(plan["id"], headers=headers)
    return plan


# ===========================================================================
# Tier 2: Participant enrollment + activation
# ===========================================================================
def enroll_participant(
    plan_id: str,
    *,
    employee_external_id: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    hire_date: Optional[str] = None,
    annual_compensation_cents: Optional[int] = None,
    elected_deferral_pct: Optional[float] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /plans/{planId}/participants — ENROLLED state.
    PlanAdministrator only (PRD §4)."""
    headers = headers or TEST_USERS["admin_headers"]
    payload = create_participant_payload(
        employee_external_id=employee_external_id,
        date_of_birth=date_of_birth,
        hire_date=hire_date,
        annual_compensation_cents=annual_compensation_cents,
        elected_deferral_pct=elected_deferral_pct,
    )
    return get_success_data(
        api_client.create_participant(plan_id, payload, headers),
    )


def activate_participant(
    plan_id: str, participant_id: str,
    *,
    payroll_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /plans/{planId}/participants/{id}/activate — ENROLLED ->
    ACTIVE. PayrollProcessor only (PRD §4)."""
    payroll_headers = payroll_headers or TEST_USERS["payroll_headers"]
    return get_success_data(
        api_client.activate_participant(
            plan_id, participant_id, None, payroll_headers,
        ),
    )


def enroll_and_activate_participant(
    plan_id: str,
    *,
    date_of_birth: Optional[str] = None,
    hire_date: Optional[str] = None,
    annual_compensation_cents: Optional[int] = None,
    elected_deferral_pct: Optional[float] = None,
    employee_external_id: Optional[str] = None,
    admin_headers: Optional[Dict[str, str]] = None,
    payroll_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Enroll + activate in one call. Returns the ACTIVE participant."""
    p = enroll_participant(
        plan_id,
        employee_external_id=employee_external_id,
        date_of_birth=date_of_birth,
        hire_date=hire_date,
        annual_compensation_cents=annual_compensation_cents,
        elected_deferral_pct=elected_deferral_pct,
        headers=admin_headers,
    )
    return activate_participant(
        plan_id, p["id"], payroll_headers=payroll_headers,
    )


# ===========================================================================
# Tier 3: Contributions
# ===========================================================================
def post_contribution(
    plan_id: str, participant_id: str,
    *,
    pay_period_end: str,
    gross_pay_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../contribution-records — PayrollProcessor only."""
    headers = headers or TEST_USERS["payroll_headers"]
    return get_success_data(
        api_client.create_contribution_record(
            plan_id, participant_id,
            create_contribution_payload(
                pay_period_end=pay_period_end,
                gross_pay_cents=gross_pay_cents,
            ),
            headers,
        ),
    )


# ===========================================================================
# Tier 4: Balance accumulation (Threshold targeting)
#
# PRD §4 does not expose a 'seed balance' endpoint. The only way to
# raise total_account_balance_cents is real ContributionRecord posts.
# Annual caps (PRD §3.3) limit each calendar year to roughly:
#   max_employee_per_year  = $23,500 = 2,350,000 cents
#   max_employer_per_year  = $46,000 = 4,600,000 cents
# so the per-year ceiling per participant is ~$69,500. Larger targets
# require advancing the plan clock across calendar boundaries and
# posting in subsequent years.
# ===========================================================================
def _year_of(iso_d: str) -> int:
    return int(iso_d.split("-", 1)[0])


def _add_days(iso_d: str, days: int) -> str:
    return (date.fromisoformat(iso_d) + timedelta(days=days)).isoformat()


def _last_day_of(year: int) -> str:
    return f"{year}-12-31"


def accumulate_balance(
    plan_id: str, participant_id: str,
    *,
    target_cents: int,
    starting_year: int = 2026,
    pay_period_end_template: str = "{year}-{month:02d}-15",
    max_years: int = 30,
    admin_headers: Optional[Dict[str, str]] = None,
    payroll_headers: Optional[Dict[str, str]] = None,
) -> int:
    """Post ContributionRecord rows until the participant's
    total_account_balance_cents reaches at least target_cents.

    Strategy (PRD §3.3-aware, clock-stable):

      - PRD §3.3 imposes annual caps per CALENDAR YEAR of
        pay_period_end: $23,500 employee + $46,000 employer. Year-to-
        date is computed strictly from rows whose pay_period_end falls
        in the same calendar year as the proposed row — the PlanClock
        is NOT consulted. We therefore accumulate by walking forward
        through pay_period_end calendar years without ever advancing
        the PlanClock.
      - This is important: tests downstream call advance_clock with
        their own fixed calendar targets. If accumulate_balance moved
        the clock, the test's subsequent advance could land in the
        past (or skip past the test's intended date) and break
        deterministic vesting/loan-default arithmetic.
      - To approach the annual caps without rejection, we PATCH the
        participant's elected_deferral_pct to 5.0 (the smallest pct
        that yields the full SAFE_HARBOR_BASIC employer match of 4 %
        of gross — see PRD §3.3 SAFE_HARBOR formula). One post at
        gross = $470,000 then yields employee = $23,500 (annual cap)
        and employer = $18,800; per year ~ $42,300.

    Returns the final total_account_balance_cents.
    """
    admin_headers = admin_headers or TEST_USERS["admin_headers"]
    payroll_headers = payroll_headers or TEST_USERS["payroll_headers"]

    # Update deferral to a value safe for both caps. Use PayrollProcessor
    # (PRD §3.2: PayrollProcessor or the owning Participant). We pick
    # PayrollProcessor for headers parity with the contribution path.
    try:
        api_client.update_deferral(
            plan_id, participant_id,
            {"elected_deferral_pct": 5.0},
            payroll_headers,
        )
    except Exception:
        pass

    current = get_participant(plan_id, participant_id, admin_headers)
    year = starting_year
    years_used = 0
    while (
        current["total_account_balance_cents"] < target_cents
        and years_used < max_years
    ):
        pay_period_end = pay_period_end_template.format(year=year, month=1)
        # gross 40_000_00 cents = $400,000.  With deferral 5%:
        # employee = 5% * 400,000 = $20,000 (3500 cents under the $23,500
        # cap — leaves room for subsequent test-driven posts in the same
        # calendar year, e.g. duplicate-pay-period or hardship+suspended
        # contribution tests that need to issue one more contribution
        # before the cap binds).
        # employer (SAFE_HARBOR_BASIC) = 4% * 400,000 = $16,000
        # (under $46,000 employer cap).
        # Under TIERED variants the employer figure varies, but it is
        # bounded by the $46K annual cap (silent cap, PRD §3.3) so the
        # request never rejects on the employer side.
        gross = 40_000_000  # $400,000
        try:
            post_contribution(
                plan_id, participant_id,
                pay_period_end=pay_period_end,
                gross_pay_cents=gross,
                headers=payroll_headers,
            )
        except AssertionError:
            # Year may already have a row with the same pay_period_end
            # (test reused the fixture in the same plan year).  Try a
            # different month/day in the same year before moving on.
            for alt_month in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
                alt_pay = pay_period_end_template.format(
                    year=year, month=alt_month,
                )
                try:
                    post_contribution(
                        plan_id, participant_id,
                        pay_period_end=alt_pay,
                        gross_pay_cents=gross,
                        headers=payroll_headers,
                    )
                    break
                except AssertionError:
                    continue
        year += 1
        years_used += 1
        current = get_participant(
            plan_id, participant_id, admin_headers,
        )

    return current["total_account_balance_cents"]


def setup_participant_with_balance(
    *,
    target_balance_cents: int,
    match_formula_type: str = "SAFE_HARBOR_BASIC",
    tiered_brackets: Optional[List[Dict[str, Any]]] = None,
    vesting_schedule_type: str = "CLIFF",
    cliff_years: Optional[int] = 1,
    graded_percentages: Optional[List[int]] = None,
    plan_year: int = 2026,
    starting_clock: str = "2026-01-01",
    date_of_birth: str = "1985-06-15",
    hire_date: str = "2020-01-01",
    elected_deferral_pct: float = 100.0,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """End-to-end: build a plan + active participant whose
    total_account_balance_cents is at least target_balance_cents.

    Used by every test that needs a non-trivial balance for hardship,
    loan, RMD, or vesting calculations. Returns (plan, participant).

    NOTE: because PRD §3.3 caps per-year contributions, very large
    targets transparently consume multiple plan-clock years; tests
    that care about the exact clock date should call advance_clock
    themselves after this fixture.
    """
    plan = create_and_activate_plan(
        match_formula_type=match_formula_type,
        tiered_brackets=tiered_brackets,
        vesting_schedule_type=vesting_schedule_type,
        cliff_years=cliff_years,
        graded_percentages=graded_percentages,
        plan_year=plan_year,
        advance_clock_to=starting_clock,
    )
    participant = enroll_and_activate_participant(
        plan["id"],
        date_of_birth=date_of_birth,
        hire_date=hire_date,
        annual_compensation_cents=1_000_000_000,  # huge -> caps bind first
        elected_deferral_pct=elected_deferral_pct,
    )
    accumulate_balance(
        plan["id"], participant["id"],
        target_cents=target_balance_cents,
        starting_year=int(starting_clock[:4]),
    )
    participant = get_participant(plan["id"], participant["id"])
    return plan, participant


def setup_basic_active_participant(
    *,
    match_formula_type: str = "SAFE_HARBOR_BASIC",
    tiered_brackets: Optional[List[Dict[str, Any]]] = None,
    vesting_schedule_type: str = "CLIFF",
    cliff_years: Optional[int] = 3,
    graded_percentages: Optional[List[int]] = None,
    plan_year: int = 2026,
    starting_clock: str = "2026-01-15",
    date_of_birth: str = "1985-06-15",
    hire_date: str = "2022-01-01",
    annual_compensation_cents: int = 6_000_000,
    elected_deferral_pct: float = 5.0,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Smallest useful setup: ACTIVE plan + ACTIVE participant, no
    contributions yet. Returns (plan, participant).
    """
    plan = create_and_activate_plan(
        match_formula_type=match_formula_type,
        tiered_brackets=tiered_brackets,
        vesting_schedule_type=vesting_schedule_type,
        cliff_years=cliff_years,
        graded_percentages=graded_percentages,
        plan_year=plan_year,
        advance_clock_to=starting_clock,
    )
    participant = enroll_and_activate_participant(
        plan["id"],
        date_of_birth=date_of_birth,
        hire_date=hire_date,
        annual_compensation_cents=annual_compensation_cents,
        elected_deferral_pct=elected_deferral_pct,
    )
    return plan, participant


# ===========================================================================
# Tier 5: Loan lifecycle shortcuts
# ===========================================================================
def request_loan(
    plan_id: str, participant_id: str,
    *,
    requested_amount_cents: int,
    term_months: int,
    participant_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../loans — Participant role acting on themselves
    (PRD §4 + §2.1 entity-backed ownership)."""
    headers = participant_headers or make_participant_headers(
        participant_id,
    )
    return get_success_data(
        api_client.create_loan(
            plan_id, participant_id,
            create_loan_payload(
                requested_amount_cents=requested_amount_cents,
                term_months=term_months,
            ),
            headers,
        ),
    )


def approve_loan(
    plan_id: str, participant_id: str, loan_id: str,
    *,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../loans/{loanId}/approve — PlanAdministrator (PRD §4).

    NOTE: PRD §2.1 SOD: the approver's X-User-ID may not equal the
    requester's. Default admin_headers uses an admin operator id
    (admin-001), which is distinct from any Participant.id, so the
    SOD check passes.
    """
    headers = admin_headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.approve_loan(
            plan_id, participant_id, loan_id, None, headers,
        ),
    )


def request_and_approve_loan(
    plan_id: str, participant_id: str,
    *,
    requested_amount_cents: int,
    term_months: int,
    participant_headers: Optional[Dict[str, str]] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """One-shot: request a loan then approve it. Returns the
    ACTIVE Loan."""
    loan = request_loan(
        plan_id, participant_id,
        requested_amount_cents=requested_amount_cents,
        term_months=term_months,
        participant_headers=participant_headers,
    )
    return approve_loan(
        plan_id, participant_id, loan["id"],
        admin_headers=admin_headers,
    )


def post_loan_repayment(
    plan_id: str, participant_id: str, loan_id: str,
    *,
    payment_amount_cents: int,
    participant_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../loans/{loanId}/repayments — Participant or
    PayrollProcessor (PRD §4)."""
    headers = participant_headers or make_participant_headers(
        participant_id,
    )
    return get_success_data(
        api_client.create_loan_repayment(
            plan_id, participant_id, loan_id,
            create_loan_repayment_payload(
                payment_amount_cents=payment_amount_cents,
            ),
            headers,
        ),
    )


# ===========================================================================
# Tier 5: Hardship lifecycle shortcuts
# ===========================================================================
def request_hardship(
    plan_id: str, participant_id: str,
    *,
    requested_amount_cents: int,
    hardship_reason_code: str = "MEDICAL",
    participant_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../hardship-withdrawals — Participant role acting on
    themselves (PRD §4)."""
    headers = participant_headers or make_participant_headers(
        participant_id,
    )
    return get_success_data(
        api_client.create_hardship_withdrawal(
            plan_id, participant_id,
            create_hardship_payload(
                requested_amount_cents=requested_amount_cents,
                hardship_reason_code=hardship_reason_code,
            ),
            headers,
        ),
    )


def approve_hardship(
    plan_id: str, participant_id: str, withdrawal_id: str,
    *,
    compliance_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../hardship-withdrawals/{id}/approve —
    ComplianceOfficer (PRD §4)."""
    headers = compliance_headers or TEST_USERS["compliance_headers"]
    return get_success_data(
        api_client.approve_hardship_withdrawal(
            plan_id, participant_id, withdrawal_id, None, headers,
        ),
    )


# ===========================================================================
# Tier 5: RMD lifecycle shortcuts
# ===========================================================================
def create_rmd_schedule(
    plan_id: str, participant_id: str,
    *,
    rmd_year: int,
    compliance_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../rmd-schedules — ComplianceOfficer (PRD §4)."""
    headers = compliance_headers or TEST_USERS["compliance_headers"]
    return get_success_data(
        api_client.create_rmd_schedule(
            plan_id, participant_id,
            create_rmd_payload(rmd_year=rmd_year),
            headers,
        ),
    )


def fulfill_rmd_schedule(
    plan_id: str, participant_id: str, schedule_id: str,
    *,
    distributed_amount_cents: int,
    compliance_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../rmd-schedules/{id}/fulfill — ComplianceOfficer."""
    headers = compliance_headers or TEST_USERS["compliance_headers"]
    return get_success_data(
        api_client.fulfill_rmd_schedule(
            plan_id, participant_id, schedule_id,
            fulfill_rmd_payload(
                distributed_amount_cents=distributed_amount_cents,
            ),
            headers,
        ),
    )


# ===========================================================================
# Tier 5: Vesting snapshot
# ===========================================================================
def create_vesting_snapshot(
    plan_id: str, participant_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../vesting-snapshots — PlanAdministrator,
    ComplianceOfficer, or the owning Participant (PRD §4).

    Default uses admin_headers (opaque). To exercise the
    entity-backed Participant path, pass
    participant_headers=make_participant_headers(participant_id).
    """
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.create_vesting_snapshot(
            plan_id, participant_id, None, headers,
        ),
    )


# ===========================================================================
# Tier 5: Cross-cutting "scenario" builders for difficulty design recipes
# ===========================================================================
def setup_two_plans_same_participant_inputs(
    *,
    plan_a_match: str,
    plan_b_match: str,
    plan_a_brackets: Optional[List[Dict[str, Any]]] = None,
    plan_b_brackets: Optional[List[Dict[str, Any]]] = None,
    vesting_schedule_type: str = "CLIFF",
    cliff_years: int = 3,
    graded_percentages: Optional[List[int]] = None,
    starting_clock: str = "2026-06-01",
    hire_date: str = "2022-01-01",
    annual_compensation_cents: int = 6_000_000,
    elected_deferral_pct: float = 6.0,
) -> Tuple[
    Tuple[Dict[str, Any], Dict[str, Any]],
    Tuple[Dict[str, Any], Dict[str, Any]],
]:
    """Build two parallel (plan, participant) pairs that share every
    input EXCEPT the match formula. The dual-variant difficulty
    instance uses this to prove identical inputs produce different
    employer_match_cents.
    """
    plan_a, p_a = setup_basic_active_participant(
        match_formula_type=plan_a_match,
        tiered_brackets=plan_a_brackets,
        vesting_schedule_type=vesting_schedule_type,
        cliff_years=cliff_years,
        graded_percentages=graded_percentages,
        starting_clock=starting_clock,
        hire_date=hire_date,
        annual_compensation_cents=annual_compensation_cents,
        elected_deferral_pct=elected_deferral_pct,
    )
    plan_b, p_b = setup_basic_active_participant(
        match_formula_type=plan_b_match,
        tiered_brackets=plan_b_brackets,
        vesting_schedule_type=vesting_schedule_type,
        cliff_years=cliff_years,
        graded_percentages=graded_percentages,
        starting_clock=starting_clock,
        hire_date=hire_date,
        annual_compensation_cents=annual_compensation_cents,
        elected_deferral_pct=elected_deferral_pct,
    )
    return (plan_a, p_a), (plan_b, p_b)


def setup_loan_lifecycle(
    *,
    target_balance_cents: int,
    requested_amount_cents: int,
    term_months: int,
    starting_clock: str = "2026-01-01",
    hire_date: str = "2020-01-01",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """End-to-end: plan + participant funded to target_balance_cents +
    ACTIVE Loan. Returns (plan, participant, loan)."""
    plan, participant = setup_participant_with_balance(
        target_balance_cents=target_balance_cents,
        starting_clock=starting_clock,
        hire_date=hire_date,
    )
    loan = request_and_approve_loan(
        plan["id"], participant["id"],
        requested_amount_cents=requested_amount_cents,
        term_months=term_months,
    )
    return plan, participant, loan


__all__ = [
    # low-level
    "advance_clock",
    "get_plan",
    "get_participant",
    "get_loan",
    # Tier 1
    "create_draft_plan",
    "create_and_activate_plan",
    # Tier 2
    "enroll_participant",
    "activate_participant",
    "enroll_and_activate_participant",
    # Tier 3
    "post_contribution",
    # Tier 4
    "accumulate_balance",
    "setup_participant_with_balance",
    "setup_basic_active_participant",
    # Tier 5
    "request_loan",
    "approve_loan",
    "request_and_approve_loan",
    "post_loan_repayment",
    "request_hardship",
    "approve_hardship",
    "create_rmd_schedule",
    "fulfill_rmd_schedule",
    "create_vesting_snapshot",
    "setup_two_plans_same_participant_inputs",
    "setup_loan_lifecycle",
]
