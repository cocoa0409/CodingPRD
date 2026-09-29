"""
Composite state builders and pytest fixtures.

The runner relaunches the service with an empty database before every test, so
every precondition has to be built from scratch through the documented
endpoints. The builders below assemble the compositions this domain keeps
needing — a configured program year with a fund menu, a registered employer, an
activated saver with an open account, a funded account, an account carrying a
detected excess case, an affirmed assessment under an open referral — so that an
individual test only has to describe what is unusual about its own scenario.

Nothing here asserts a rule under test: a failure inside a builder means the
precondition could not be established, not that the rule is wrong.
"""

from typing import Any, Dict, List, Optional

import pytest

from . import constants as C
from . import factories as F
from .api_client import ApiClient
from .assertions import find_row
from .test_users import (
    ADMIN,
    OFFICER_A,
    OFFICER_B,
    make_employer_headers,
    make_participant_headers,
)
from .types import Headers, JsonDict


# ---------------------------------------------------------------------------
# Tier 1 — programme configuration
# ---------------------------------------------------------------------------
def build_program_configuration(
    api: ApiClient,
    clock: str = C.CLOCK_2026_01_01,
    program_years: Optional[List[JsonDict]] = None,
    funds: Optional[List[JsonDict]] = None,
) -> JsonDict:
    """
    Move the clock to `clock`, configure the program years and stand up the fund
    menu. Defaults to program year 2026 and the TDF2045/MMKT01 pair.
    """
    F.set_clock(api, clock)
    years = [F.create_program_year(api, year)
             for year in (program_years or [C.PROGRAM_YEAR_2026])]
    menu = F.create_fund_menu(api, funds)
    return {
        "clock": clock,
        "program_years": years,
        "program_year": years[0],
        "funds": menu,
        "fund_ids": {fund["fund_code"]: fund["id"] for fund in menu},
    }


# ---------------------------------------------------------------------------
# Tier 2 — an employer inside the register
# ---------------------------------------------------------------------------
def build_employer_environment(
    api: ApiClient,
    employer: Optional[JsonDict] = None,
    register: bool = True,
    clock: str = C.CLOCK_2026_01_01,
    program_years: Optional[List[JsonDict]] = None,
    funds: Optional[List[JsonDict]] = None,
    registration: Optional[JsonDict] = None,
) -> JsonDict:
    """
    Configuration plus one employer. When `register` is true the employer also
    completes its own registration, so its mandate dimension reads `REGISTERED`.
    """
    env = build_program_configuration(api, clock, program_years, funds)
    row = F.create_employer(api, employer or C.EMPLOYER_DELTA)
    env["employer"] = row
    env["employer_id"] = row["id"]
    env["employer_headers"] = make_employer_headers(row["id"])
    if register:
        env["registration"] = F.register_employer(
            api, row["id"], registration or C.REGISTRATION_DELTA)
        env["employer"] = env["registration"]
    return env


def add_employer(api: ApiClient, env: JsonDict, employer: JsonDict,
                 register: bool = True,
                 registration: Optional[JsonDict] = None) -> JsonDict:
    """Add a second employer to an existing environment and return its row."""
    row = F.create_employer(api, employer)
    if register:
        row = F.register_employer(api, row["id"],
                                  registration or C.REGISTRATION_GENERIC)
    return row


# ---------------------------------------------------------------------------
# Tier 3 — a saver, first notified and then activated
# ---------------------------------------------------------------------------
def build_notified_saver(
    api: ApiClient,
    env: JsonDict,
    participant: Optional[JsonDict] = None,
    hire_date: str = "2026-01-05",
    annual_compensation_cents: int = 9600000,
) -> JsonDict:
    """
    Register a saver and enrol them at the environment's employer. The enrolment
    is left in its pre-activation state. Mutates and returns `env`.
    """
    saver = F.create_participant(api, participant or C.PARTICIPANT_ROSA)
    enrollment = F.create_enrollment(
        api, env["employer_id"], saver["id"], hire_date,
        annual_compensation_cents)
    env["participant"] = saver
    env["participant_id"] = saver["id"]
    env["participant_headers"] = make_participant_headers(saver["id"])
    env["enrollment"] = enrollment
    env["enrollment_id"] = enrollment["id"]
    return env


def activate_savers(api: ApiClient, env: JsonDict,
                    activation_clock: str = C.CLOCK_2026_02_01) -> JsonDict:
    """
    Move the clock past the opt-out window and run the auto-enrolment batch, then
    capture the account the batch opened for the environment's saver.
    """
    F.set_clock(api, activation_clock)
    env["clock"] = activation_clock
    env["auto_enrollment_run"] = F.run_auto_enrollment(api)
    if "participant_id" in env:
        account = F.account_for_participant(api, env["participant_id"])
        env["account"] = account
        env["account_id"] = account["id"]
    return env


def build_active_saver_environment(
    api: ApiClient,
    employer: Optional[JsonDict] = None,
    participant: Optional[JsonDict] = None,
    hire_date: str = "2026-01-05",
    annual_compensation_cents: int = 9600000,
    clock: str = C.CLOCK_2026_01_01,
    activation_clock: str = C.CLOCK_2026_02_01,
    program_years: Optional[List[JsonDict]] = None,
    funds: Optional[List[JsonDict]] = None,
) -> JsonDict:
    """
    The composition most scenarios start from: configuration, a registered
    employer, one enrolled saver, and the auto-enrolment batch run so that the
    enrolment is live and an account with a default fund election exists.
    """
    env = build_employer_environment(
        api, employer=employer, register=True, clock=clock,
        program_years=program_years, funds=funds)
    build_notified_saver(api, env, participant, hire_date,
                         annual_compensation_cents)
    return activate_savers(api, env, activation_clock)


# ---------------------------------------------------------------------------
# Tier 4 — money in the account
# ---------------------------------------------------------------------------
def fund_account_by_remittance(
    api: ApiClient,
    env: JsonDict,
    pay_period_start: str,
    pay_period_end: str,
    pay_date: str,
    gross_wages_cents: int,
    deducted_cents: int,
    posting_clock: Optional[str] = None,
    posting_reference: str = "PR-2026-0001",
) -> JsonDict:
    """
    Drive one single-line batch from draft to posted against the environment's
    enrolment, so the deducted cents land in the saver's account. Returns a dict
    carrying the batch, its line and the posted batch row.
    """
    if posting_clock is not None:
        F.set_clock(api, posting_clock)
        env["clock"] = posting_clock
    remittance = F.create_remittance(
        api, env["employer_id"], pay_period_start, pay_period_end, pay_date,
        deducted_cents)
    line = F.add_remittance_line(
        api, remittance["id"], env["employer_id"], env["enrollment_id"],
        gross_wages_cents, deducted_cents)
    F.submit_remittance(api, remittance["id"], env["employer_id"])
    posted = F.post_remittance(api, remittance["id"], posting_reference)
    return {"remittance": posted, "remittance_id": remittance["id"],
            "line": line, "line_id": line["id"]}


def build_funded_account_environment(
    api: ApiClient,
    participant: Optional[JsonDict] = None,
    annual_compensation_cents: int = 144000000,
    gross_wages_cents: int = 12000000,
    deducted_cents: int = 600000,
    earnings_cents: int = 900000,
    pay_period_start: str = "2026-02-01",
    pay_period_end: str = "2026-02-28",
    pay_date: str = "2026-03-05",
    posting_clock: str = C.CLOCK_2026_03_06,
    earnings_date: str = "2026-03-06",
    program_years: Optional[List[JsonDict]] = None,
) -> JsonDict:
    """
    An active saver whose account has been credited with one posted remittance
    and one earnings posting, so the balance carries both a contribution basis
    and an earnings layer. That split is what the pro-rata basis arithmetic on
    any distribution keys off.
    """
    env = build_active_saver_environment(
        api, participant=participant,
        annual_compensation_cents=annual_compensation_cents,
        program_years=program_years)
    env.update(fund_account_by_remittance(
        api, env, pay_period_start, pay_period_end, pay_date,
        gross_wages_cents, deducted_cents, posting_clock,
        posting_reference="PR-2026-0600"))
    if earnings_cents:
        F.post_earnings(api, env["account_id"], earnings_cents, earnings_date)
    env["account"] = F.account_for_participant(api, env["participant_id"])
    return env


# ---------------------------------------------------------------------------
# Tier 4b — an account carrying a detected excess case
# ---------------------------------------------------------------------------
def build_excess_case_environment(
    api: ApiClient,
    participant: Optional[JsonDict] = None,
    annual_compensation_cents: int = 120000000,
    first_gross_cents: int = 10000000,
    first_deducted_cents: int = 500000,
    second_gross_cents: int = 8000000,
    second_deducted_cents: int = 400000,
) -> JsonDict:
    """
    Two posted batches whose combined allocations exceed the annual ceiling, so
    the second posting flags excess, opens one case in its detected state and
    drives the account's posture to restricted.
    """
    env = build_active_saver_environment(
        api, participant=participant,
        annual_compensation_cents=annual_compensation_cents)
    first = fund_account_by_remittance(
        api, env, "2026-02-01", "2026-02-28", "2026-03-05",
        first_gross_cents, first_deducted_cents, C.CLOCK_2026_03_06,
        posting_reference="PR-2026-A001")
    second = fund_account_by_remittance(
        api, env, "2026-03-01", "2026-03-31", "2026-04-03",
        second_gross_cents, second_deducted_cents, C.CLOCK_2026_04_05,
        posting_reference="PR-2026-B001")
    cases = F.excess_cases_for_account(api, env["account_id"])
    assert len(cases) == 1, (
        f"Expected exactly one excess case on the account, found {len(cases)}"
    )
    env["first_remittance"] = first["remittance"]
    env["first_remittance_id"] = first["remittance_id"]
    env["first_line_id"] = first["line_id"]
    env["second_remittance"] = second["remittance"]
    env["second_remittance_id"] = second["remittance_id"]
    env["second_line_id"] = second["line_id"]
    env["excess_case"] = cases[0]
    env["excess_case_id"] = cases[0]["id"]
    env["account"] = F.account_for_participant(api, env["participant_id"])
    return env


# ---------------------------------------------------------------------------
# Tier 5 — enforcement postures
# ---------------------------------------------------------------------------
def build_assessed_penalty_environment(
    api: ApiClient,
    employer: Optional[JsonDict] = None,
    violation_type: str = "FAILURE_TO_REGISTER",
    notice_date: str = "2026-06-30",
    cure_days: Optional[int] = None,
    register: bool = False,
    clock: str = C.CLOCK_2026_07_01,
    assessor: Headers = OFFICER_A,
) -> JsonDict:
    """
    An employer carrying one freshly assessed penalty, still inside its cure
    period. The assessing officer is recorded so a separate officer can dispose
    of it without tripping the separation-of-duties rule.
    """
    env = build_employer_environment(api, employer=employer, register=register)
    F.set_clock(api, clock)
    env["clock"] = clock
    penalty = F.assess_penalty(api, env["employer_id"], violation_type,
                               notice_date, cure_days, headers=assessor)
    env["penalty"] = penalty
    env["penalty_id"] = penalty["id"]
    env["assessor"] = assessor
    return env


def build_affirmed_penalty_environment(
    api: ApiClient,
    employer: Optional[JsonDict] = None,
    violation_type: str = "FAILURE_TO_REGISTER",
    notice_date: str = "2026-06-30",
    cure_days: Optional[int] = None,
    register: bool = False,
    assessment_clock: str = C.CLOCK_2026_07_01,
    affirmation_clock: str = "2026-09-01T00:00:00Z",
    assessor: Headers = OFFICER_A,
    disposer: Headers = OFFICER_B,
) -> JsonDict:
    """
    An assessment whose cure period has run out and which a second officer has
    affirmed, so it is eligible to be referred to an outside authority.
    """
    env = build_assessed_penalty_environment(
        api, employer=employer, violation_type=violation_type,
        notice_date=notice_date, cure_days=cure_days, register=register,
        clock=assessment_clock, assessor=assessor)
    F.set_clock(api, affirmation_clock)
    env["clock"] = affirmation_clock
    env["penalty"] = F.dispose_penalty(api, env["penalty_id"], "AFFIRM",
                                       headers=disposer)
    env["disposer"] = disposer
    return env


def build_referred_employer_environment(
    api: ApiClient,
    employer: Optional[JsonDict] = None,
    agency: str = "STATE_LABOR_COMMISSIONER",
    referral_basis: str = "Employer failed to register by its statutory deadline",
    **kwargs: Any,
) -> JsonDict:
    """
    An employer under an open enforcement referral, which is the condition the
    enforcement interlock keys on.
    """
    env = build_affirmed_penalty_environment(api, employer=employer, **kwargs)
    referral = F.refer_penalty(api, env["penalty_id"], agency, referral_basis,
                               headers=env["disposer"])
    env["referral"] = referral
    env["referral_id"] = referral["id"]
    return env


def build_exempt_certified_environment(
    api: ApiClient,
    employer: Optional[JsonDict] = None,
    exemption: Optional[JsonDict] = None,
    clock: str = C.CLOCK_2026_01_01,
) -> JsonDict:
    """
    An employer whose qualified-plan certification has been approved, so its
    mandate dimension reads exempt-certified and a revocation can be pulled.
    """
    env = build_employer_environment(api, employer=employer, register=False,
                                     clock=clock)
    filed = F.file_exemption(api, env["employer_id"], exemption or C.EXEMPTION_401K)
    env["exemption"] = F.decide_exemption(api, filed["id"], "APPROVE")
    env["exemption_id"] = filed["id"]
    return env


# ---------------------------------------------------------------------------
# Tier 5b — terminal account states
# ---------------------------------------------------------------------------
def build_closed_account_environment(
    api: ApiClient,
    participant: Optional[JsonDict] = None,
) -> JsonDict:
    """
    An active saver whose account has been carried through both closure steps, so
    it sits in its terminal closed state with a zero balance.
    """
    env = build_active_saver_environment(api, participant=participant)
    F.request_closure(api, env["account_id"], env["participant_id"],
                      "PARTICIPANT_REQUEST", "CASH_DISTRIBUTION")
    env["account"] = F.complete_closure(api, env["account_id"])
    return env


def build_closure_pending_environment(
    api: ApiClient,
    participant: Optional[JsonDict] = None,
) -> JsonDict:
    """An account that has been asked to close but has not been closed out yet."""
    env = build_active_saver_environment(api, participant=participant)
    env["account"] = F.request_closure(
        api, env["account_id"], env["participant_id"],
        "PARTICIPANT_REQUEST", "CASH_DISTRIBUTION")
    return env


# ---------------------------------------------------------------------------
# Convenience lookups
# ---------------------------------------------------------------------------
def active_election(api: ApiClient, account_id: str,
                    headers: Headers = ADMIN) -> JsonDict:
    """Return the account's currently governing fund election."""
    from prd_bench_local_runner.testing import validate_paginated
    rows, _ = validate_paginated(api.list_investment_elections(account_id, headers))
    return find_row(rows, status="ACTIVE")


def refresh_account(api: ApiClient, env: JsonDict) -> JsonDict:
    """Re-read the environment's account and store it back on the environment."""
    from prd_bench_local_runner.testing import validate_success
    account = validate_success(
        api.get_participant_account(env["account_id"], ADMIN))
    env["account"] = account
    return account


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test."""
    return ApiClient()


@pytest.fixture
def program_config(api: ApiClient) -> JsonDict:
    """Clock at the start of 2026, program year 2026, and a two-fund menu."""
    return build_program_configuration(api)


@pytest.fixture
def employer_env(api: ApiClient) -> JsonDict:
    """Configuration plus one registered 60-employee employer."""
    return build_employer_environment(api)


@pytest.fixture
def unregistered_employer_env(api: ApiClient) -> JsonDict:
    """Configuration plus one employer that has not registered yet."""
    return build_employer_environment(api, register=False)


@pytest.fixture
def active_saver_env(api: ApiClient) -> JsonDict:
    """A registered employer, one live enrolment and one open account."""
    return build_active_saver_environment(api)


@pytest.fixture
def funded_account_env(api: ApiClient) -> JsonDict:
    """An account carrying one posted remittance and one earnings posting."""
    return build_funded_account_environment(api)


@pytest.fixture
def excess_case_env(api: ApiClient) -> JsonDict:
    """An account whose second posting flagged excess and opened a case."""
    return build_excess_case_environment(api)


@pytest.fixture
def assessed_penalty_env(api: ApiClient) -> JsonDict:
    """An employer carrying one assessment still inside its cure period."""
    return build_assessed_penalty_environment(api)


@pytest.fixture
def affirmed_penalty_env(api: ApiClient) -> JsonDict:
    """An employer carrying one affirmed assessment."""
    return build_affirmed_penalty_environment(api)


@pytest.fixture
def referred_employer_env(api: ApiClient) -> JsonDict:
    """An employer under an open enforcement referral."""
    return build_referred_employer_environment(api)


@pytest.fixture
def exempt_certified_env(api: ApiClient) -> JsonDict:
    """An employer whose qualified-plan certification has been approved."""
    return build_exempt_certified_environment(api)


@pytest.fixture
def closed_account_env(api: ApiClient) -> JsonDict:
    """An account carried through both closure steps."""
    return build_closed_account_environment(api)


@pytest.fixture
def closure_pending_env(api: ApiClient) -> JsonDict:
    """An account that has been asked to close but is not closed out yet."""
    return build_closure_pending_environment(api)
