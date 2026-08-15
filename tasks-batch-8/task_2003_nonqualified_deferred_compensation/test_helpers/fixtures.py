"""Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

Every helper builds preconditions from scratch using only PRD-declared
endpoints, and uses get_success_data() so a setup failure surfaces as a clear
"Setup failed" error instead of a confusing assertion failure.
"""
from typing import Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULTS,
    add_member_payload,
    create_account_payload,
    create_cic_event_payload,
    create_crediting_run_payload,
    create_deferral_election_payload,
    create_distribution_request_payload,
    create_document_finding_payload,
    create_election_window_payload,
    create_notional_fund_payload,
    create_operational_failure_payload,
    create_participant_payload,
    create_plan_payload,
    create_rabbi_trust_payload,
    create_separation_case_payload,
    create_specified_list_payload,
    determination_payload,
    funding_event_payload,
    post_deferral_payload,
    quantify_payload,
    service_record_payload,
)
from .test_users import TEST_USERS, make_participant_headers

PS = TEST_USERS["plan_sponsor_headers"]
BA = TEST_USERS["benefits_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
TO = TEST_USERS["trust_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Atomic helpers ─────────────────────────────────────────────────────────

def create_plan(**overrides) -> dict:
    """Create a plan (lands in DRAFT). Returns the plan."""
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), PS))


def get_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_plan(plan_id, PS))


def plan_version(plan_id: str) -> int:
    return get_plan(plan_id)["version"]


def activate_plan(plan_id: str) -> dict:
    return get_success_data(api_client.activate_plan(plan_id, PS))


def create_active_plan(**overrides) -> dict:
    """Create + activate. Returns the ACTIVE plan."""
    plan = create_plan(**overrides)
    return activate_plan(plan["id"])


def add_fund(plan_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_notional_fund(create_notional_fund_payload(plan_id, **overrides), PS))


def add_window(plan_id: str, **overrides) -> dict:
    """OCC-aware window creation: reads the current plan version first."""
    payload = create_election_window_payload(plan_id, plan_version(plan_id), **overrides)
    return get_success_data(api_client.create_election_window(payload, PS))


def enroll_participant(plan_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_participant(create_participant_payload(plan_id, **overrides), BA))


def get_participant(participant_id: str) -> dict:
    return get_success_data(api_client.get_participant(participant_id, BA))


def open_account(participant_id: str, plan_id: str) -> dict:
    return get_success_data(
        api_client.create_account(create_account_payload(participant_id, plan_id), BA))


def get_account(account_id: str) -> dict:
    return get_success_data(api_client.get_account(account_id, BA))


def get_statement(account_id: str) -> dict:
    return get_success_data(api_client.get_account_statement(account_id, BA))


def advance_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_election(participant_id: str, window_id: str, fund_id: str, **overrides) -> dict:
    """Create a DRAFT election as the participant acting for self (PRD §3.2)."""
    payload = create_deferral_election_payload(participant_id, window_id, fund_id, **overrides)
    return get_success_data(
        api_client.create_deferral_election(payload, make_participant_headers(participant_id)))


def submit_election(election_id: str, participant_id: str) -> dict:
    return get_success_data(
        api_client.submit_election(election_id, make_participant_headers(participant_id)))


def post_deferral(election_id: str, amount_cents: int, **overrides) -> dict:
    return get_success_data(
        api_client.post_deferral(election_id, post_deferral_payload(amount_cents, **overrides), BA))


def settle_account(account_id: str) -> dict:
    return get_success_data(api_client.settle_entries(account_id, BA))


def list_ledger_entries(**params) -> list:
    data = get_success_data(api_client.list_ledger_entries(BA, params=params))
    return data


def open_separation_case(participant_id: str, alleged_date: str = "2027-03-15",
                         trigger_reason: str = "TERMINATION",
                         opener_headers: Optional[dict] = None) -> dict:
    """Open a case; participant moves ACTIVE -> SEPARATION_REVIEW (PRD §3.4)."""
    payload = create_separation_case_payload(
        participant_id, alleged_separation_date=alleged_date, trigger_reason=trigger_reason)
    return get_success_data(api_client.create_separation_case(payload, opener_headers or BA))


def append_record(case_id: str, period_start: str, period_end: str, fraction_bp: int) -> dict:
    return get_success_data(api_client.append_service_record(
        case_id, service_record_payload(period_start, period_end, fraction_bp), BA))


def append_records(case_id: str, records: List[Tuple[str, str, int]]) -> dict:
    case = None
    for start, end, fraction in records:
        case = append_record(case_id, start, end, fraction)
    return case


def standard_evidence(case_id: str, alleged_date: str = "2027-03-15",
                      fractions: Tuple[int, int, int] = (6000, 2000, 0)) -> dict:
    """Three contiguous years of records ending at the alleged date.

    Default coverage 2024-03-15 -> 2027-03-15 (1095 days), weighted average
    floor(8000000/3000) = 2666 bp — below the 5000 bp DEFAULT_50 threshold.
    """
    assert alleged_date == "2027-03-15", "standard_evidence is pinned to 2027-03-15 coverage"
    return append_records(case_id, [
        ("2024-03-15", "2025-03-15", fractions[0]),
        ("2025-03-15", "2026-03-15", fractions[1]),
        ("2026-03-15", "2027-03-15", fractions[2]),
    ])


def determine_case(case_id: str, outcome: str, determiner_headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.determine_case(case_id, determination_payload(outcome), determiner_headers or CO))


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_separation_case(case_id, BA))


def get_election(election_id: str) -> dict:
    return get_success_data(api_client.get_deferral_election(election_id, BA))


def get_election_window(window_id: str) -> dict:
    return get_success_data(api_client.get_election_window(window_id, BA))


def get_operational_failure(failure_id: str) -> dict:
    return get_success_data(api_client.get_operational_failure(failure_id, BA))


def get_distribution(request_id: str) -> dict:
    return get_success_data(api_client.get_distribution_request(request_id, BA))


def create_distribution(account_id: str, participant_id: str, event_type: str, **overrides) -> dict:
    payload = create_distribution_request_payload(account_id, event_type, **overrides)
    return get_success_data(api_client.create_distribution_request(
        payload, make_participant_headers(participant_id)))


def verify_distribution(request_id: str) -> dict:
    return get_success_data(api_client.verify_distribution_event(request_id, CO))


def schedule_distribution(request_id: str) -> dict:
    return get_success_data(api_client.schedule_distribution(request_id, BA))


def create_draft_specified_list(plan_id: str, **overrides) -> dict:
    """OCC-aware specified-list creation."""
    payload = create_specified_list_payload(plan_id, plan_version(plan_id), **overrides)
    return get_success_data(api_client.create_specified_employee_list(payload, CO))


def add_member(list_id: str, participant_id: str, basis: str, comp_cents: int) -> dict:
    return get_success_data(
        api_client.add_list_member(list_id, add_member_payload(participant_id, basis, comp_cents), CO))


def finalize_list(list_id: str) -> dict:
    return get_success_data(api_client.finalize_list(list_id, CO))


# ─── Tier 2/3 composite: funded account ─────────────────────────────────────

def setup_plan_fund_window(plan_overrides: Optional[dict] = None,
                           fund_overrides: Optional[dict] = None,
                           window_overrides: Optional[dict] = None) -> Dict:
    """ACTIVE plan + one notional fund + one 2027 window (2026-10-01..2026-12-31)."""
    plan = create_active_plan(**(plan_overrides or {}))
    fund = add_fund(plan["id"], **(fund_overrides or {}))
    window = add_window(plan["id"], **(window_overrides or {}))
    return {"plan": plan, "fund": fund, "window": window}


def setup_funded_account(amount_cents: int = 100000,
                         plan_overrides: Optional[dict] = None,
                         fund_overrides: Optional[dict] = None,
                         window_overrides: Optional[dict] = None,
                         participant_overrides: Optional[dict] = None,
                         deferral_percent_bp: int = 5000,
                         settle: bool = True) -> Dict:
    """Full chain: plan -> fund -> window 2027 -> participant -> account ->
    clock into window -> GENERAL election -> submit -> clock past close (LOCKED)
    -> post-deferral(amount) [-> settle].

    Returns ctx dict with plan/fund/window/participant/account/election/entry.
    """
    ctx = setup_plan_fund_window(plan_overrides, fund_overrides, window_overrides)
    participant = enroll_participant(ctx["plan"]["id"], **(participant_overrides or {}))
    ctx["participant"] = participant
    account = open_account(participant["id"], ctx["plan"]["id"])
    ctx["account"] = account
    advance_clock("2026-10-15T00:00:00Z")  # window OPEN
    election = create_election(participant["id"], ctx["window"]["id"], ctx["fund"]["id"],
                               deferral_percent_bp=deferral_percent_bp)
    ctx["election"] = submit_election(election["id"], participant["id"])
    advance_clock("2027-01-01T00:00:00Z")  # window CLOSED -> election LOCKED
    ctx["election"] = get_election(election["id"])
    ctx["entry"] = post_deferral(election["id"], amount_cents)
    if settle:
        ctx["account"] = settle_account(account["id"])
    return ctx


def setup_separated_participant(ctx: Optional[Dict] = None,
                                alleged_date: str = "2027-03-15",
                                fractions: Tuple[int, int, int] = (6000, 2000, 0),
                                opener_headers: Optional[dict] = None,
                                determiner_headers: Optional[dict] = None) -> Dict:
    """Funded account + separation case determined CONFIRMED_SEPARATION.

    Participant ends SEPARATED with separation_date == alleged_date.
    """
    ctx = ctx or setup_funded_account()
    case = open_separation_case(ctx["participant"]["id"], alleged_date,
                                opener_headers=opener_headers)
    ctx["case"] = standard_evidence(case["id"], alleged_date, fractions)
    ctx["case"] = determine_case(case["id"], "CONFIRMED_SEPARATION",
                                 determiner_headers=determiner_headers)
    ctx["participant"] = get_participant(ctx["participant"]["id"])
    return ctx


def setup_separation_distribution(ctx: Optional[Dict] = None,
                                  requested_amount_cents: Optional[int] = None,
                                  schedule: bool = True) -> Dict:
    """Determined separation + SEPARATION distribution verified [+ scheduled]."""
    ctx = setup_separated_participant(ctx)
    overrides: Dict = {"separation_case_id": ctx["case"]["id"]}
    if requested_amount_cents is not None:
        overrides["requested_amount_cents"] = requested_amount_cents
    request = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                  "SEPARATION", **overrides)
    ctx["request"] = verify_distribution(request["id"])
    if schedule:
        ctx["request"] = schedule_distribution(request["id"])
    return ctx


def setup_operational_failure(account_id: str,
                              failure_type: str = "EARLY_PAYMENT",
                              failure_date: str = "2027-01-15",
                              amount_cents: int = 500000,
                              reporter_headers: Optional[dict] = None,
                              **overrides) -> dict:
    payload = create_operational_failure_payload(
        account_id, failure_type=failure_type, failure_date=failure_date,
        amount_cents=amount_cents, **overrides)
    return get_success_data(
        api_client.create_operational_failure(payload, reporter_headers or BA))


def setup_quantified_failure(account_id: str, correction_credit_cents: int = 0,
                             quantifier_headers: Optional[dict] = None,
                             **failure_overrides) -> dict:
    failure = setup_operational_failure(account_id, **failure_overrides)
    return get_success_data(api_client.quantify_failure(
        failure["id"], quantify_payload(correction_credit_cents),
        quantifier_headers or CO))
