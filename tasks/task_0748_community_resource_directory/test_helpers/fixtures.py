"""Composite setup helpers.

Each helper walks a multi-step API sequence to reach a specific state so tests can
focus on the trigger + assertion. Every fixture:
- uses `get_success_data()` internally (lenient 2xx acceptance) so setup failures
  surface as clear "Setup failed" errors, not confusing assertion mismatches;
- accepts **overrides for the values a test cares about, with sensible defaults;
- threads entity-backed identity properly — ProviderStaff headers use the real
  provider id; Client headers use the real client id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_funder_payload,
    create_provider_payload,
    create_program_payload,
    create_client_payload,
    create_intake_payload,
    create_consent_grant_payload,
    create_referral_payload,
    create_availability_window_payload,
    create_transport_plan_payload,
    create_outcome_report_payload,
    create_funder_report_payload,
)
from .test_users import (
    TEST_USERS,
    make_caseworker_headers,
    make_client_headers,
    make_platform_admin_headers,
    make_provider_staff_headers,
)


DEFAULT_CLOCK = "2026-06-01T00:00:00Z"

_ADMIN = TEST_USERS["platform_admin_headers"]
_CASEWORKER = TEST_USERS["caseworker_headers"]


# ---------------------------------------------------------------------------
# Atomic setup helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK) -> None:
    get_success_data(api_client.set_clock(to_iso8601, _ADMIN))


def create_funder(**overrides) -> dict:
    payload = create_funder_payload(**overrides)
    return get_success_data(api_client.create_funder(payload, _ADMIN))


def create_provider(**overrides) -> dict:
    payload = create_provider_payload(**overrides)
    return get_success_data(api_client.create_provider(payload, _ADMIN))


def create_program(provider_id: str, funder_id: str, **overrides) -> dict:
    payload = create_program_payload(provider_id, funder_id, **overrides)
    return get_success_data(api_client.create_program(payload, _ADMIN))


def create_client(**overrides) -> dict:
    payload = create_client_payload(**overrides)
    return get_success_data(api_client.create_client(payload, _CASEWORKER))


def create_intake(client_id: str, **overrides) -> dict:
    payload = create_intake_payload(**overrides)
    return get_success_data(api_client.create_intake(client_id, payload, _CASEWORKER))


def screen_intake(intake_id: str) -> dict:
    return get_success_data(api_client.screen_intake(intake_id, _CASEWORKER))


def create_consent_grant(client_id: str, provider_id: str, **overrides) -> dict:
    payload = create_consent_grant_payload(provider_id, **overrides)
    headers = make_client_headers(client_id)
    return get_success_data(api_client.create_consent_grant(client_id, payload, headers))


def create_referral(intake_id: str, program_id: str, consent_grant_id: str, **overrides) -> dict:
    payload = create_referral_payload(program_id, consent_grant_id, **overrides)
    return get_success_data(api_client.create_referral(intake_id, payload, _CASEWORKER))


def accept_referral(referral_id: str, provider_id: str) -> dict:
    return get_success_data(api_client.accept_referral(referral_id, make_provider_staff_headers(provider_id)))


def start_service(referral_id: str, provider_id: str) -> dict:
    return get_success_data(api_client.start_service(referral_id, make_provider_staff_headers(provider_id)))


def complete_referral(referral_id: str, provider_id: str, outcome_class: str = "SUCCESS") -> dict:
    return get_success_data(
        api_client.complete_referral(referral_id, outcome_class, make_provider_staff_headers(provider_id))
    )


def create_outcome_report(referral_id: str, provider_id: str, outcome: str,
                          service_hours: float, follow_up_needed: bool = False) -> dict:
    payload = create_outcome_report_payload(outcome, service_hours, follow_up_needed)
    return get_success_data(
        api_client.create_outcome_report(referral_id, payload, make_provider_staff_headers(provider_id))
    )


def create_transport_plan(referral_id: str, pickup_start_ts: str, pickup_end_ts: str,
                          mode: str = "AGENCY_SHUTTLE", cost_cents: int = 500) -> dict:
    payload = create_transport_plan_payload(pickup_start_ts, pickup_end_ts, mode, cost_cents)
    return get_success_data(api_client.create_transport_plan(referral_id, payload, _CASEWORKER))


# ---------------------------------------------------------------------------
# Tier 2 — full baseline: one funder + provider + program + client + screened intake + granted consent.
# The recurring 8-call prelude across essentially every difficulty/corner instance.
# ---------------------------------------------------------------------------

class Baseline:
    """Convenience bundle for the standard prelude."""
    def __init__(self, funder, provider, program, client, intake, consent):
        self.funder = funder
        self.provider = provider
        self.program = program
        self.client = client
        self.intake = intake
        self.consent = consent

    @property
    def provider_id(self) -> str:
        return self.provider["id"]

    @property
    def client_id(self) -> str:
        return self.client["id"]


def setup_baseline(
    clock: str = DEFAULT_CLOCK,
    funder_overrides: dict = None,
    provider_overrides: dict = None,
    program_overrides: dict = None,
    client_overrides: dict = None,
    intake_overrides: dict = None,
    screen: bool = True,
    grant_consent: bool = True,
) -> Baseline:
    """Bootstrap the canonical directory scenario:
       clock -> funder -> provider -> program -> client -> intake (+screen) -> consent.

    Everything downstream in this domain is a variation of this preamble.
    """
    set_clock(clock)
    funder = create_funder(**(funder_overrides or {}))
    provider = create_provider(**(provider_overrides or {}))
    program = create_program(provider["id"], funder["id"], **(program_overrides or {}))
    client = create_client(**(client_overrides or {}))
    intake = create_intake(client["id"], **(intake_overrides or {}))
    if screen:
        intake = screen_intake(intake["id"])
    consent = None
    if grant_consent:
        consent = create_consent_grant(client["id"], provider["id"])
    return Baseline(funder, provider, program, client, intake, consent)


# ---------------------------------------------------------------------------
# Tier 3 — full lifecycle shortcuts.
# ---------------------------------------------------------------------------

def setup_baseline_with_referral(**baseline_kwargs) -> tuple:
    """baseline + one PROPOSED referral. Returns (baseline, referral)."""
    b = setup_baseline(**baseline_kwargs)
    r = create_referral(b.intake["id"], b.program["id"], b.consent["id"])
    return b, r


def setup_baseline_with_accepted_referral(**baseline_kwargs) -> tuple:
    """baseline + one ACCEPTED referral. Returns (baseline, referral)."""
    b, r = setup_baseline_with_referral(**baseline_kwargs)
    r = accept_referral(r["id"], b.provider_id)
    return b, r


def setup_baseline_with_service_in_progress_referral(**baseline_kwargs) -> tuple:
    """baseline + one SERVICE_IN_PROGRESS referral. Returns (baseline, referral)."""
    b, r = setup_baseline_with_accepted_referral(**baseline_kwargs)
    r = start_service(r["id"], b.provider_id)
    return b, r


# ---------------------------------------------------------------------------
# Tier 4 — capacity accumulation / posture targeting.
# ---------------------------------------------------------------------------

def setup_program_at_capacity_utilization(
    n_referrals: int,
    program_capacity: int = 5,
    **baseline_kwargs,
) -> tuple:
    """Setup baseline then create `n_referrals` PROPOSED referrals under the same intake+consent+program.

    Returns (baseline, [referral, ...]).
    """
    kwargs = dict(baseline_kwargs)
    program_overrides = dict(kwargs.pop("program_overrides", {}) or {})
    program_overrides.setdefault("capacity_slots_total", program_capacity)
    kwargs["program_overrides"] = program_overrides
    b = setup_baseline(**kwargs)
    referrals = []
    for _ in range(n_referrals):
        r = create_referral(b.intake["id"], b.program["id"], b.consent["id"])
        referrals.append(r)
    return b, referrals


def setup_program_closed_by_capacity(program_capacity: int = 1, **baseline_kwargs) -> tuple:
    """Program with N referrals equal to capacity -> intake_posture == CLOSED.
    Returns (baseline, [referral, ...])."""
    return setup_program_at_capacity_utilization(program_capacity, program_capacity, **baseline_kwargs)


# ---------------------------------------------------------------------------
# Tier 5 — Multi-referral scenarios needed by Rule 4 / Rule 3 instance 2.
# ---------------------------------------------------------------------------

def setup_four_accepted_started_referrals(program_capacity: int = 5, **baseline_kwargs) -> tuple:
    """baseline + 4 referrals each ACCEPTED then start-serviced.
    After: capacity_slots_taken == 4 -> intake_posture == RESTRICTED (4/5 = 0.80).
    Returns (baseline, [referral, ...])."""
    kwargs = dict(baseline_kwargs)
    program_overrides = dict(kwargs.pop("program_overrides", {}) or {})
    program_overrides.setdefault("capacity_slots_total", program_capacity)
    kwargs["program_overrides"] = program_overrides
    b = setup_baseline(**kwargs)
    refs = []
    for _ in range(4):
        r = create_referral(b.intake["id"], b.program["id"], b.consent["id"])
        r = accept_referral(r["id"], b.provider_id)
        r = start_service(r["id"], b.provider_id)
        refs.append(r)
    return b, refs


def setup_three_unmet_outcomes_for_report(unit_cost_cents: int = 1001,
                                          program_capacity: int = 5,
                                          **baseline_kwargs) -> tuple:
    """Baseline with unit_cost_cents overridden, then 3 referrals each brought to
    ACCEPTED -> SERVICE_IN_PROGRESS -> UNMET/0hrs outcome. Returns (baseline, [outcome, ...])."""
    kwargs = dict(baseline_kwargs)
    program_overrides = dict(kwargs.pop("program_overrides", {}) or {})
    program_overrides.setdefault("unit_cost_cents", unit_cost_cents)
    program_overrides.setdefault("capacity_slots_total", program_capacity)
    kwargs["program_overrides"] = program_overrides
    b = setup_baseline(**kwargs)
    outcomes = []
    for _ in range(3):
        r = create_referral(b.intake["id"], b.program["id"], b.consent["id"])
        accept_referral(r["id"], b.provider_id)
        start_service(r["id"], b.provider_id)
        o = create_outcome_report(r["id"], b.provider_id, outcome="UNMET",
                                  service_hours=0.0, follow_up_needed=False)
        outcomes.append(o)
    return b, outcomes
