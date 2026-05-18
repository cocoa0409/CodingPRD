"""Composite setup helpers — multi-step preambles tests can reuse.

Many tests require the system in a late state (e.g., a Case in
AWAITING_JUDGMENT with both disclosures ACCEPTED, parenting plan
AGREED, and a CHILD SupportOrder DRAFT). Each fixture composes the
lower-level steps so the test body can focus on the rule under
assertion.

IDENTITY THREADING — PRD §2.1:

- Judge, Mediator, PlatformAdmin are OPAQUE; shared constants
  (judge_headers, mediator_headers, admin_headers) are canonical.

- Petitioner is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  Petitioner, X-User-ID is the id of the acting Party row (specifically,
  the Party on the targeted case whose role is PETITIONER). Ownership
  checks on any resource that references a Party ... compare the
  resource's party foreign-key field to X-User-ID."
  Every Petitioner-driven call (POST /cases is the create-as-petitioner
  one, but ALSO any /default, /start-mediation, /disclosures,
  /parenting-plans, /accept on plan) MUST use
  make_petitioner_headers(case["petitioner_party_id"]).

- Respondent is ENTITY-BACKED analogously; use
  make_respondent_headers(case["respondent_party_id"]).

- AttorneyOfRecord is OPAQUE but its X-User-ID must match the
  Party.counsel_user_id set on the case at petition acceptance. To use
  an AttorneyOfRecord, create the case with petitioner_counsel_user_id
  or respondent_counsel_user_id set to the attorney's ID, then call
  with make_attorney_headers(attorney_id) (or shared
  attorney_for_*_headers constants).

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ANSWER_WINDOW_DAYS,
    SESSION_START_LEAD_MINUTES,
    TEST_DEFAULTS,
)
from .factories import (
    clock_advance_payload,
    complete_mediation_session_payload,
    create_case_payload,
    create_disclosure_payload,
    create_final_judgment_payload,
    create_parenting_plan_payload,
    create_support_order_payload,
    create_temp_order_payload,
    iso_offset,
    iso_utc,
    issue_final_judgment_payload,
    issue_temp_order_payload,
    parse_iso,
    party_payload,
    patch_disclosure_payload,
    reject_disclosure_payload,
    schedule_mediation_session_payload,
)
from .test_users import (
    TEST_USERS,
    make_judge_headers,
    make_mediator_headers,
    make_petitioner_headers,
    make_respondent_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.6 (PlatformAdmin only for advance)
# ===========================================================================
def get_clock_now(
    headers: Optional[Dict[str, str]] = None,
) -> str:
    """GET /_clock. Returns the now field as ISO 8601 string.

    PRD §2.6: 'The clock can be read by any authenticated role'.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.get_clock(headers)
    data = get_success_data(resp)
    return data["now"]


def server_now_dt() -> datetime:
    """Return the server's current clock as a UTC datetime."""
    return parse_iso(get_clock_now())


def server_offset_iso(*, days: int = 0, hours: int = 0,
                      minutes: int = 0, seconds: int = 0,
                      millis: int = 0) -> str:
    """Return an ISO 8601 UTC instant offset from the SERVER's current
    clock — not the test runner's local clock. Use this any time you
    want a future instant for scheduling or for advance_clock targets.
    """
    base = server_now_dt()
    return iso_utc(
        base + timedelta(days=days, hours=hours, minutes=minutes,
                         seconds=seconds, milliseconds=millis),
    )


def advance_clock_to(
    to_iso: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §2.6: 'The clock ... is advanced only
    by PlatformAdmin'. Monotone-only — if to_iso is earlier than
    current, the server returns ERR_CLOCK_NOT_MONOTONE.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.advance_clock(
        clock_advance_payload(to=to_iso), headers,
    )
    return get_success_data(resp)


def advance_clock_forward_by(*, days: int = 0, hours: int = 0,
                             minutes: int = 0, seconds: int = 0,
                             millis: int = 0) -> Dict[str, Any]:
    """Advance the server clock by an offset from its current value."""
    target = server_offset_iso(days=days, hours=hours, minutes=minutes,
                               seconds=seconds, millis=millis)
    return advance_clock_to(target)


def advance_clock_safe(to_iso: str) -> Dict[str, Any]:
    """Advance the clock to to_iso only if to_iso is strictly after the
    current server clock; otherwise no-op. Used by fixtures that pin a
    deterministic instant — if a previous test advanced past it, we
    don't try to go backwards (which would be rejected).
    """
    now_dt = server_now_dt()
    target_dt = parse_iso(to_iso)
    if target_dt > now_dt:
        return advance_clock_to(to_iso)
    return {"now": iso_utc(now_dt)}


# ===========================================================================
# Re-read entities
# ===========================================================================
def re_get_case(case_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Fetch the case as Judge (PRD §2.1 grants Judge read access)."""
    headers = headers or TEST_USERS["judge_headers"]
    return get_success_data(api_client.get_case(case_id, headers))


def re_get_disclosure(case_id: str, disclosure_id: str,
                      headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["judge_headers"]
    # GET disclosures list and find by id (PRD §4 lists disclosures by
    # case; no single-disclosure GET in §4 endpoint table).
    listing = get_success_data(api_client.list_disclosures(case_id, headers))
    if isinstance(listing, dict) and "data" in listing:
        listing = listing["data"]
    if isinstance(listing, list):
        for d in listing:
            if d.get("id") == disclosure_id:
                return d
    raise AssertionError(
        f"Setup failed: disclosure {disclosure_id} not in list on "
        f"case {case_id}"
    )


def re_get_parenting_plan(case_id: str, plan_id: str,
                          headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["judge_headers"]
    return get_success_data(
        api_client.get_parenting_plan(case_id, plan_id, headers),
    )


def re_get_support_order(case_id: str, order_id: str,
                         headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["judge_headers"]
    return get_success_data(
        api_client.get_support_order(case_id, order_id, headers),
    )


def re_get_temp_order(case_id: str, temp_order_id: str,
                      headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["judge_headers"]
    return get_success_data(
        api_client.get_temp_order(case_id, temp_order_id, headers),
    )


def re_get_final_judgment(case_id: str, judgment_id: str,
                          headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["judge_headers"]
    return get_success_data(
        api_client.get_final_judgment(case_id, judgment_id, headers),
    )


# ===========================================================================
# Case creation — PRD §3.1
# ===========================================================================
def create_case(
    *,
    jurisdiction_state: str = "CA",
    marriage_date: str = TEST_DEFAULTS["DEFAULT_MARRIAGE_DATE"],
    separation_date: str = TEST_DEFAULTS["DEFAULT_SEPARATION_DATE"],
    has_minor_children: bool = True,
    petitioner_gross_cents: int = 300_000,
    respondent_gross_cents: int = 600_000,
    petitioner_counsel_user_id: Optional[str] = None,
    respondent_counsel_user_id: Optional[str] = None,
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases as Petitioner (or AttorneyOfRecord). Returns the
    Case dict, which carries petitioner_party_id and
    respondent_party_id ready for downstream Petitioner/Respondent
    identity threading.

    PRD §2.1: 'When X-User-Role is Petitioner, X-User-ID is the id of
    the acting Party row'. Since the Party.id is server-minted at case
    creation, we open the case using the petitioner-fallback or an
    AttorneyOfRecord caller (whose X-User-ID matches the counsel_user_id
    we send in the payload). After this call, downstream Petitioner
    calls MUST switch to make_petitioner_headers(case[
    'petitioner_party_id']).
    """
    payload = create_case_payload(
        jurisdiction_state=jurisdiction_state,
        marriage_date=marriage_date,
        separation_date=separation_date,
        has_minor_children=has_minor_children,
        petitioner_gross_cents=petitioner_gross_cents,
        respondent_gross_cents=respondent_gross_cents,
        petitioner_counsel_user_id=petitioner_counsel_user_id,
        respondent_counsel_user_id=respondent_counsel_user_id,
    )
    # PRD §4: POST /cases is allowed for AttorneyOfRecord or
    # Petitioner. When the test supplies a counsel for petitioner,
    # use the matching AttorneyOfRecord header to open the case; this
    # avoids ownership conflicts because Petitioner-id is not yet
    # known. Otherwise use the petitioner fallback (PRD does not
    # require X-User-ID == petitioner_party_id at creation time, since
    # that id has not yet been minted).
    if actor_headers is None:
        if petitioner_counsel_user_id:
            from .test_users import make_attorney_headers
            actor_headers = make_attorney_headers(petitioner_counsel_user_id)
        else:
            actor_headers = TEST_USERS["petitioner_fallback_headers"]
    resp = api_client.create_case(payload, actor_headers)
    return get_success_data(resp)


# ===========================================================================
# Answer / default — PRD §3.1
# ===========================================================================
def answer_case(case_id: str, respondent_party_id: str) -> Dict[str, Any]:
    """POST /cases/{caseId}/answer as the actual Respondent.

    PRD §2.1: 'When X-User-Role is Respondent, X-User-ID is the id of
    the acting Party row'.
    """
    headers = make_respondent_headers(respondent_party_id)
    resp = api_client.answer_case(case_id, headers)
    return get_success_data(resp)


def default_case(case_id: str, petitioner_party_id: str) -> Dict[str, Any]:
    """POST /cases/{caseId}/default as the actual Petitioner."""
    headers = make_petitioner_headers(petitioner_party_id)
    resp = api_client.default_case(case_id, headers)
    return get_success_data(resp)


# ===========================================================================
# FinancialDisclosure — PRD §3.2
# ===========================================================================
def create_disclosure(
    case_id: str,
    party_id: str,
    *,
    actor_role: str,
    gross_monthly_income_cents: int = 300_000,
    deductible_taxes_cents: int = 0,
    monthly_health_insurance_cents: int = 0,
    monthly_childcare_cents: int = 0,
    assets_total_cents: int = 0,
    debts_total_cents: int = 0,
) -> Dict[str, Any]:
    """POST /cases/{caseId}/disclosures.

    PRD §3.2: 'A Petitioner, Respondent, or AttorneyOfRecord creates
    the disclosure'. PRD §2.1 ownership: X-User-ID for Petitioner role
    must equal case.petitioner_party_id; for Respondent role it must
    equal case.respondent_party_id. The body's party_id then identifies
    which party the disclosure is FOR — typically the acting party's
    own.

    actor_role: 'petitioner' uses make_petitioner_headers(party_id)
    where party_id is the petitioner Party.id;
    'respondent' uses make_respondent_headers(party_id) where party_id
    is the respondent Party.id. Caller MUST pass the matching
    party_id for the role.
    """
    if actor_role == "petitioner":
        headers = make_petitioner_headers(party_id)
    elif actor_role == "respondent":
        headers = make_respondent_headers(party_id)
    else:
        raise AssertionError(
            f"Setup failed: unknown actor_role {actor_role!r}; "
            f"must be 'petitioner' or 'respondent'"
        )
    payload = create_disclosure_payload(
        party_id=party_id,
        gross_monthly_income_cents=gross_monthly_income_cents,
        deductible_taxes_cents=deductible_taxes_cents,
        monthly_health_insurance_cents=monthly_health_insurance_cents,
        monthly_childcare_cents=monthly_childcare_cents,
        assets_total_cents=assets_total_cents,
        debts_total_cents=debts_total_cents,
    )
    resp = api_client.create_disclosure(case_id, payload, headers)
    return get_success_data(resp)


def submit_disclosure(case_id: str, disclosure_id: str,
                      party_id: str, *,
                      actor_role: str = "petitioner") -> Dict[str, Any]:
    if actor_role == "petitioner":
        headers = make_petitioner_headers(party_id)
    elif actor_role == "respondent":
        headers = make_respondent_headers(party_id)
    else:
        raise AssertionError(
            f"Setup failed: unknown actor_role {actor_role!r}"
        )
    resp = api_client.submit_disclosure(case_id, disclosure_id, headers)
    return get_success_data(resp)


def accept_disclosure(case_id: str, disclosure_id: str) -> Dict[str, Any]:
    """POST /cases/{caseId}/disclosures/{id}/accept — Judge only."""
    resp = api_client.accept_disclosure(
        case_id, disclosure_id, TEST_USERS["judge_headers"],
    )
    return get_success_data(resp)


def reject_disclosure(case_id: str, disclosure_id: str,
                      *, reason: str = "documentation gap") -> Dict[str, Any]:
    resp = api_client.reject_disclosure(
        case_id, disclosure_id,
        reject_disclosure_payload(rejection_reason=reason),
        TEST_USERS["judge_headers"],
    )
    return get_success_data(resp)


def create_submit_accept_disclosure(
    case_id: str, party_id: str,
    *,
    actor_role: str = "petitioner",
    gross_monthly_income_cents: int = 300_000,
    deductible_taxes_cents: int = 0,
    monthly_health_insurance_cents: int = 0,
    monthly_childcare_cents: int = 0,
    assets_total_cents: int = 0,
    debts_total_cents: int = 0,
) -> Dict[str, Any]:
    """End-to-end: create DRAFT → submit → judge accepts. Returns the
    ACCEPTED disclosure dict."""
    d = create_disclosure(
        case_id, party_id,
        actor_role=actor_role,
        gross_monthly_income_cents=gross_monthly_income_cents,
        deductible_taxes_cents=deductible_taxes_cents,
        monthly_health_insurance_cents=monthly_health_insurance_cents,
        monthly_childcare_cents=monthly_childcare_cents,
        assets_total_cents=assets_total_cents,
        debts_total_cents=debts_total_cents,
    )
    submit_disclosure(case_id, d["id"], party_id, actor_role=actor_role)
    return accept_disclosure(case_id, d["id"])


# ===========================================================================
# Setup: case in DISCLOSURE with both disclosures ACCEPTED
# ===========================================================================
def setup_case_with_both_disclosures_accepted(
    *,
    jurisdiction_state: str = "CA",
    marriage_date: str = TEST_DEFAULTS["DEFAULT_MARRIAGE_DATE"],
    separation_date: str = TEST_DEFAULTS["DEFAULT_SEPARATION_DATE"],
    has_minor_children: bool = True,
    p_gross_cents: int = 300_000,
    r_gross_cents: int = 600_000,
    p_taxes_cents: int = 0,
    r_taxes_cents: int = 0,
    p_health_cents: int = 0,
    r_health_cents: int = 0,
    p_childcare_cents: int = 0,
    r_childcare_cents: int = 0,
    p_assets_cents: int = 0,
    r_assets_cents: int = 0,
    p_debts_cents: int = 0,
    r_debts_cents: int = 0,
    answer_first: bool = True,
) -> Dict[str, Any]:
    """Walk: petition -> respondent answers (optional) -> petitioner
    disclosure submit+accept -> respondent disclosure submit+accept.

    Returns a context dict: {
        'case': Case dict (latest re-read),
        'petitioner_party_id': str,
        'respondent_party_id': str,
        'petitioner_disclosure': dict,
        'respondent_disclosure': dict,
    }

    PRD §3.2 controls the disclosure flow. Petitioner and Respondent
    are entity-backed, so per-instance headers are used throughout.
    """
    case = create_case(
        jurisdiction_state=jurisdiction_state,
        marriage_date=marriage_date,
        separation_date=separation_date,
        has_minor_children=has_minor_children,
        petitioner_gross_cents=p_gross_cents,
        respondent_gross_cents=r_gross_cents,
    )
    p_id = case["petitioner_party_id"]
    r_id = case["respondent_party_id"]

    if answer_first:
        answer_case(case["id"], r_id)

    p_disc = create_submit_accept_disclosure(
        case["id"], p_id, actor_role="petitioner",
        gross_monthly_income_cents=p_gross_cents,
        deductible_taxes_cents=p_taxes_cents,
        monthly_health_insurance_cents=p_health_cents,
        monthly_childcare_cents=p_childcare_cents,
        assets_total_cents=p_assets_cents,
        debts_total_cents=p_debts_cents,
    )
    r_disc = create_submit_accept_disclosure(
        case["id"], r_id, actor_role="respondent",
        gross_monthly_income_cents=r_gross_cents,
        deductible_taxes_cents=r_taxes_cents,
        monthly_health_insurance_cents=r_health_cents,
        monthly_childcare_cents=r_childcare_cents,
        assets_total_cents=r_assets_cents,
        debts_total_cents=r_debts_cents,
    )
    return {
        "case": re_get_case(case["id"]),
        "petitioner_party_id": p_id,
        "respondent_party_id": r_id,
        "petitioner_disclosure": p_disc,
        "respondent_disclosure": r_disc,
    }


# ===========================================================================
# Parenting plan helpers — PRD §3.3
# ===========================================================================
def propose_parenting_plan(
    case_id: str,
    proposing_party_id: str,
    *,
    actor_role: str = "petitioner",
    legal_custody: str = "JOINT",
    physical_custody: str = "JOINT",
    petitioner_overnights: int = 100,
    respondent_overnights: int = 265,
) -> Dict[str, Any]:
    if actor_role == "petitioner":
        headers = make_petitioner_headers(proposing_party_id)
    elif actor_role == "respondent":
        headers = make_respondent_headers(proposing_party_id)
    else:
        raise AssertionError(f"unknown actor_role {actor_role!r}")
    payload = create_parenting_plan_payload(
        proposing_party_id=proposing_party_id,
        legal_custody=legal_custody,
        physical_custody=physical_custody,
        petitioner_overnights_per_year=petitioner_overnights,
        respondent_overnights_per_year=respondent_overnights,
    )
    resp = api_client.create_parenting_plan(case_id, payload, headers)
    return get_success_data(resp)


def accept_parenting_plan(case_id: str, plan_id: str,
                          acceptor_party_id: str,
                          *, actor_role: str = "respondent") -> Dict[str, Any]:
    if actor_role == "petitioner":
        headers = make_petitioner_headers(acceptor_party_id)
    elif actor_role == "respondent":
        headers = make_respondent_headers(acceptor_party_id)
    else:
        raise AssertionError(f"unknown actor_role {actor_role!r}")
    resp = api_client.accept_parenting_plan(case_id, plan_id, headers)
    return get_success_data(resp)


def propose_and_accept_parenting_plan(
    case_id: str,
    petitioner_party_id: str,
    respondent_party_id: str,
    *,
    petitioner_overnights: int = 100,
    respondent_overnights: int = 265,
) -> Dict[str, Any]:
    """Propose by Petitioner, accept by Respondent. Returns the AGREED
    plan. Requires both disclosures already ACCEPTED (PRD §3.3)."""
    plan = propose_parenting_plan(
        case_id, petitioner_party_id, actor_role="petitioner",
        petitioner_overnights=petitioner_overnights,
        respondent_overnights=respondent_overnights,
    )
    return accept_parenting_plan(
        case_id, plan["id"], respondent_party_id, actor_role="respondent",
    )


# ===========================================================================
# Setup: AGREED parenting plan with both disclosures accepted
# ===========================================================================
def setup_case_with_agreed_plan(
    *,
    jurisdiction_state: str = "CA",
    marriage_date: str = TEST_DEFAULTS["DEFAULT_MARRIAGE_DATE"],
    separation_date: str = TEST_DEFAULTS["DEFAULT_SEPARATION_DATE"],
    has_minor_children: bool = True,
    p_gross_cents: int = 300_000,
    r_gross_cents: int = 600_000,
    p_taxes_cents: int = 0,
    r_taxes_cents: int = 0,
    p_health_cents: int = 0,
    r_health_cents: int = 0,
    p_childcare_cents: int = 0,
    r_childcare_cents: int = 0,
    p_assets_cents: int = 0,
    r_assets_cents: int = 0,
    p_debts_cents: int = 0,
    r_debts_cents: int = 0,
    petitioner_overnights: int = 100,
    respondent_overnights: int = 265,
) -> Dict[str, Any]:
    """Walk: petition -> answer -> both disclosures ACCEPTED ->
    propose plan by petitioner -> accept by respondent. Returns the
    same context as setup_case_with_both_disclosures_accepted plus
    'parenting_plan'.
    """
    ctx = setup_case_with_both_disclosures_accepted(
        jurisdiction_state=jurisdiction_state,
        marriage_date=marriage_date,
        separation_date=separation_date,
        has_minor_children=has_minor_children,
        p_gross_cents=p_gross_cents,
        r_gross_cents=r_gross_cents,
        p_taxes_cents=p_taxes_cents,
        r_taxes_cents=r_taxes_cents,
        p_health_cents=p_health_cents,
        r_health_cents=r_health_cents,
        p_childcare_cents=p_childcare_cents,
        r_childcare_cents=r_childcare_cents,
        p_assets_cents=p_assets_cents,
        r_assets_cents=r_assets_cents,
        p_debts_cents=p_debts_cents,
        r_debts_cents=r_debts_cents,
    )
    plan = propose_and_accept_parenting_plan(
        ctx["case"]["id"],
        ctx["petitioner_party_id"],
        ctx["respondent_party_id"],
        petitioner_overnights=petitioner_overnights,
        respondent_overnights=respondent_overnights,
    )
    ctx["parenting_plan"] = plan
    ctx["case"] = re_get_case(ctx["case"]["id"])
    return ctx


# ===========================================================================
# Mediation helpers — PRD §3.4
# ===========================================================================
def start_mediation(case_id: str, petitioner_party_id: str) -> Dict[str, Any]:
    """POST /cases/{caseId}/start-mediation as the actual Petitioner."""
    headers = make_petitioner_headers(petitioner_party_id)
    resp = api_client.start_mediation(case_id, headers)
    return get_success_data(resp)


def schedule_mediation_session(
    case_id: str,
    *,
    mediator_user_id: str = "mediator-001",
    scheduled_start_at: str,
    scheduled_end_at: str,
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = actor_headers or TEST_USERS["mediator_headers"]
    payload = schedule_mediation_session_payload(
        mediator_user_id=mediator_user_id,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
    )
    resp = api_client.schedule_mediation_session(case_id, payload, headers)
    return get_success_data(resp)


def start_mediation_session(
    case_id: str, session_id: str,
    *, mediator_user_id: str = "mediator-001",
) -> Dict[str, Any]:
    headers = make_mediator_headers(mediator_user_id)
    resp = api_client.start_mediation_session(case_id, session_id, headers)
    return get_success_data(resp)


def complete_mediation_session(
    case_id: str, session_id: str,
    *,
    outcome: str,
    parenting_plan_id: Optional[str] = None,
    mediator_user_id: str = "mediator-001",
) -> Dict[str, Any]:
    headers = make_mediator_headers(mediator_user_id)
    payload = complete_mediation_session_payload(
        outcome=outcome,
        parenting_plan_id=parenting_plan_id,
    )
    resp = api_client.complete_mediation_session(
        case_id, session_id, payload, headers,
    )
    return get_success_data(resp)


def run_one_full_mediation_session(
    case_id: str,
    *,
    mediator_user_id: str = "mediator-001",
    outcome: str = "IMPASSE",
    parenting_plan_id: Optional[str] = None,
    start_offset_minutes: int = 60,
    duration_minutes: int = 60,
) -> Dict[str, Any]:
    """Schedule a session, advance clock into its window, start it,
    advance to end, complete it. Returns the completed session dict
    (after the /complete call).

    PRD §3.4 controls the entire flow. Sessions count toward
    Case.mediation_round once COMPLETED.
    """
    start_iso = server_offset_iso(minutes=start_offset_minutes)
    end_iso = server_offset_iso(
        minutes=start_offset_minutes + duration_minutes,
    )
    session = schedule_mediation_session(
        case_id,
        mediator_user_id=mediator_user_id,
        scheduled_start_at=start_iso, scheduled_end_at=end_iso,
    )
    # Advance into the start window (>= scheduled_start_at - 15 min,
    # and <= scheduled_end_at). We jump to scheduled_start_at exactly.
    advance_clock_safe(start_iso)
    start_mediation_session(
        case_id, session["id"], mediator_user_id=mediator_user_id,
    )
    return complete_mediation_session(
        case_id, session["id"],
        outcome=outcome,
        parenting_plan_id=parenting_plan_id,
        mediator_user_id=mediator_user_id,
    )


# ===========================================================================
# Setup: case in MEDIATION (after start-mediation) with both
# disclosures ACCEPTED and a PROPOSED plan present
# ===========================================================================
def setup_case_in_mediation_with_proposed_plan(
    *,
    jurisdiction_state: str = "CA",
    marriage_date: str = TEST_DEFAULTS["DEFAULT_MARRIAGE_DATE"],
    separation_date: str = TEST_DEFAULTS["DEFAULT_SEPARATION_DATE"],
    p_gross_cents: int = 300_000,
    r_gross_cents: int = 600_000,
    petitioner_overnights: int = 100,
    respondent_overnights: int = 265,
) -> Dict[str, Any]:
    """Walk: petition -> answer -> both disclosures ACCEPTED ->
    propose plan by petitioner (PROPOSED only — NOT accepted) ->
    start-mediation. Returns context with 'parenting_plan' (PROPOSED).

    PRD §3.4: 'Once both parties have ACCEPTED disclosures and the
    case has at least one parenting plan in PROPOSED, COUNTERED, or
    AGREED, the Petitioner (or their attorney) can move the case into
    mediation.'
    """
    ctx = setup_case_with_both_disclosures_accepted(
        jurisdiction_state=jurisdiction_state,
        marriage_date=marriage_date,
        separation_date=separation_date,
        has_minor_children=True,
        p_gross_cents=p_gross_cents,
        r_gross_cents=r_gross_cents,
    )
    plan = propose_parenting_plan(
        ctx["case"]["id"], ctx["petitioner_party_id"],
        actor_role="petitioner",
        petitioner_overnights=petitioner_overnights,
        respondent_overnights=respondent_overnights,
    )
    start_mediation(ctx["case"]["id"], ctx["petitioner_party_id"])
    ctx["parenting_plan"] = plan
    ctx["case"] = re_get_case(ctx["case"]["id"])
    return ctx


# ===========================================================================
# Setup: case in MEDIATION with mediation_round == N and CONTESTED plan
#
# Used by §16/impose tests and difficulty rules 3 + 5.
# ===========================================================================
def setup_case_mediation_round_3_impasse(
    *,
    jurisdiction_state: str = "CA",
    p_gross_cents: int = 300_000,
    r_gross_cents: int = 600_000,
) -> Dict[str, Any]:
    """Walk: setup_case_in_mediation_with_proposed_plan -> run 3
    IMPASSE sessions in sequence. After the 3rd IMPASSE,
    Case.mediation_round == 3 and the latest PROPOSED plan has
    cascaded to CONTESTED (PRD §3.4).

    Returns ctx with 'parenting_plan' (re-read; should be CONTESTED).
    """
    ctx = setup_case_in_mediation_with_proposed_plan(
        jurisdiction_state=jurisdiction_state,
        p_gross_cents=p_gross_cents,
        r_gross_cents=r_gross_cents,
    )
    case_id = ctx["case"]["id"]
    # Each loop iteration: schedule 1h session in future, start it,
    # complete with IMPASSE. Each advances the clock forward.
    for _ in range(3):
        run_one_full_mediation_session(
            case_id, outcome="IMPASSE",
            start_offset_minutes=60, duration_minutes=60,
        )
    ctx["case"] = re_get_case(case_id)
    ctx["parenting_plan"] = re_get_parenting_plan(
        case_id, ctx["parenting_plan"]["id"],
    )
    return ctx


# ===========================================================================
# SupportOrder helpers — PRD §3.5
# ===========================================================================
def create_support_order(
    case_id: str,
    *,
    support_type: str,
    order_kind: str,
    parenting_plan_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /cases/{caseId}/support-orders — Judge only."""
    payload = create_support_order_payload(
        support_type=support_type,
        order_kind=order_kind,
        parenting_plan_id=parenting_plan_id,
    )
    resp = api_client.create_support_order(
        case_id, payload, TEST_USERS["judge_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Setup: case in AWAITING_JUDGMENT with TemporaryOrder EFFECTIVE +
# temporary SupportOrders ISSUED, and FinalJudgment DRAFT referencing
# new FINAL SupportOrders DRAFT
#
# Used by Difficulty Rule 4 / 9 cascade tests.
# ===========================================================================
def setup_case_temp_ordered_with_final_judgment_draft(
    *,
    jurisdiction_state: str = "CA",
    marriage_date: str = "2010-01-01",
    separation_date: str = "2025-01-01",
    p_gross_cents: int = 300_000,
    r_gross_cents: int = 600_000,
    has_minor_children: bool = True,
) -> Dict[str, Any]:
    """Build:
      1. Case + both disclosures ACCEPTED.
      2. (if has_minor_children) AGREED parenting plan.
      3. TEMPORARY CHILD SupportOrder DRAFT (S1) and TEMPORARY SPOUSAL
         SupportOrder DRAFT (S2, only if marriage_duration >= 5y).
      4. TemporaryOrder T1 DRAFT referencing them; issue-temp-order ->
         T1 EFFECTIVE, S1+S2 ISSUED, Case TEMP_ORDERED.
      5. FINAL CHILD SupportOrder DRAFT (S3) and FINAL SPOUSAL
         SupportOrder DRAFT (S4); FinalJudgment FJ1 DRAFT referencing
         them. Case advances to AWAITING_JUDGMENT.

    Returns dict with: case (re-read), petitioner_party_id,
    respondent_party_id, parenting_plan, temp_order, final_judgment,
    temp_child_so, temp_spousal_so, final_child_so, final_spousal_so.
    """
    # Steps 1-2: case + AGREED plan (PRD §3.3).
    if has_minor_children:
        ctx = setup_case_with_agreed_plan(
            jurisdiction_state=jurisdiction_state,
            marriage_date=marriage_date,
            separation_date=separation_date,
            has_minor_children=True,
            p_gross_cents=p_gross_cents,
            r_gross_cents=r_gross_cents,
        )
        plan_id = ctx["parenting_plan"]["id"]
    else:
        ctx = setup_case_with_both_disclosures_accepted(
            jurisdiction_state=jurisdiction_state,
            marriage_date=marriage_date,
            separation_date=separation_date,
            has_minor_children=False,
            p_gross_cents=p_gross_cents,
            r_gross_cents=r_gross_cents,
        )
        plan_id = None
        ctx["parenting_plan"] = None

    case_id = ctx["case"]["id"]

    # Step 3: TEMPORARY support orders DRAFT.
    if has_minor_children:
        s1 = create_support_order(
            case_id, support_type="CHILD",
            order_kind="TEMPORARY", parenting_plan_id=plan_id,
        )
    else:
        s1 = None

    # Spousal only if eligible (marriage_duration_years >= 5).
    p_months = _years_between(marriage_date, separation_date)
    if p_months >= 5:
        s2 = create_support_order(
            case_id, support_type="SPOUSAL", order_kind="TEMPORARY",
        )
    else:
        s2 = None

    # Step 4: TemporaryOrder DRAFT bundling them.
    t1_payload = create_temp_order_payload(
        parenting_plan_id=plan_id if has_minor_children else None,
        child_support_order_id=s1["id"] if s1 else None,
        spousal_support_order_id=s2["id"] if s2 else None,
    )
    t1_resp = api_client.create_temp_order(
        case_id, t1_payload, TEST_USERS["judge_headers"],
    )
    t1 = get_success_data(t1_resp)
    # Issue temp order — cascade DRAFT->EFFECTIVE / DRAFT->ISSUED.
    api_client.issue_temp_order(
        case_id, issue_temp_order_payload(temporary_order_id=t1["id"]),
        TEST_USERS["judge_headers"],
    )

    # Step 5: FINAL support orders DRAFT.
    if has_minor_children:
        s3 = create_support_order(
            case_id, support_type="CHILD",
            order_kind="FINAL", parenting_plan_id=plan_id,
        )
    else:
        s3 = None
    if p_months >= 5:
        s4 = create_support_order(
            case_id, support_type="SPOUSAL", order_kind="FINAL",
        )
    else:
        s4 = None

    # FinalJudgment DRAFT.
    fj_payload = create_final_judgment_payload(
        parenting_plan_id=plan_id if has_minor_children else None,
        child_support_order_id=s3["id"] if s3 else None,
        spousal_support_order_id=s4["id"] if s4 else None,
    )
    fj_resp = api_client.create_final_judgment(
        case_id, fj_payload, TEST_USERS["judge_headers"],
    )
    fj = get_success_data(fj_resp)

    return {
        "case": re_get_case(case_id),
        "petitioner_party_id": ctx["petitioner_party_id"],
        "respondent_party_id": ctx["respondent_party_id"],
        "parenting_plan": ctx.get("parenting_plan"),
        "temp_order": re_get_temp_order(case_id, t1["id"]),
        "final_judgment": fj,
        "temp_child_so": re_get_support_order(case_id, s1["id"]) if s1 else None,
        "temp_spousal_so": re_get_support_order(case_id, s2["id"]) if s2 else None,
        "final_child_so": re_get_support_order(case_id, s3["id"]) if s3 else None,
        "final_spousal_so": re_get_support_order(case_id, s4["id"]) if s4 else None,
    }


def _years_between(marriage_date: str, separation_date: str) -> int:
    """PRD §3.5 marriage_duration_years = floor((sep - mar).days /
    365.25)."""
    # Accept YYYY-MM-DD or full ISO.
    mar = parse_iso(marriage_date if "T" in marriage_date
                    else marriage_date + "T00:00:00.000Z")
    sep = parse_iso(separation_date if "T" in separation_date
                    else separation_date + "T00:00:00.000Z")
    delta_days = (sep - mar).days
    import math
    return int(math.floor(delta_days / 365.25))


# ===========================================================================
# Setup: AWAITING_JUDGMENT (no temp order) — for asset-division-only
# tests (Difficulty Rule 1b / 2b / 9a).
# ===========================================================================
def setup_case_in_awaiting_judgment_no_minors(
    *,
    jurisdiction_state: str = "NY",
    marriage_date: str = "2010-01-01",
    separation_date: str = "2025-01-01",
    p_gross_cents: int = 300_000,
    r_gross_cents: int = 600_000,
    p_taxes_cents: int = 0,
    r_taxes_cents: int = 0,
    p_assets_cents: int = 1_000_000,
    r_assets_cents: int = 2_000_000,
    p_debts_cents: int = 0,
    r_debts_cents: int = 0,
) -> Dict[str, Any]:
    """Build a case with has_minor_children=False, both disclosures
    ACCEPTED. PRD §3.6: 'The case then progresses to AWAITING_JUDGMENT
    automatically ... directly (when has_minor_children is false).'

    PRD §3.4: 'mediation only required for child-affecting cases'.
    A case with has_minor_children=False never needs start-mediation,
    so once both disclosures are ACCEPTED, the case is ready for
    final judgment.

    PRD §3.6: 'The transition [FinalJudgment DRAFT -> EFFECTIVE]
    requires the judgment to be in DRAFT on this case, both disclosures
    to be ACCEPTED, and — when there are minor children — the
    referenced parenting_plan_id to be AGREED or COURT_IMPOSED.'
    For has_minor_children=False, no parenting plan is required.

    Note: PRD §3 narrative does not explicitly enumerate the
    automatic ANSWERED -> AWAITING_JUDGMENT path for the
    no-minor-children branch. The fixture builds the prerequisites
    (both disclosures ACCEPTED on an ANSWERED case with
    has_minor_children=False); whether Case.status reads
    'AWAITING_JUDGMENT' or remains 'DISCLOSURE' at this point is left
    to the implementation. What matters for downstream tests is that
    the inputs allow FinalJudgment creation, which PRD §3.6 gates on
    disclosure acceptance and parenting-plan absence in the no-minor
    case.
    """
    return setup_case_with_both_disclosures_accepted(
        jurisdiction_state=jurisdiction_state,
        marriage_date=marriage_date,
        separation_date=separation_date,
        has_minor_children=False,
        p_gross_cents=p_gross_cents,
        r_gross_cents=r_gross_cents,
        p_taxes_cents=p_taxes_cents,
        r_taxes_cents=r_taxes_cents,
        p_assets_cents=p_assets_cents,
        r_assets_cents=r_assets_cents,
        p_debts_cents=p_debts_cents,
        r_debts_cents=r_debts_cents,
    )


def create_final_judgment_no_minors(case_id: str) -> Dict[str, Any]:
    """For a has_minor_children=False case with both disclosures
    ACCEPTED — create the FinalJudgment DRAFT (no child/spousal/plan
    refs). Server computes asset shares on DRAFT creation per PRD §3.6.
    """
    payload = create_final_judgment_payload()
    resp = api_client.create_final_judgment(
        case_id, payload, TEST_USERS["judge_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Convenience for difficulty-design Rule 6 boundary test
# ===========================================================================
def pin_clock_for_filed_case(case_id: str) -> Dict[str, Any]:
    """For the answer-window inclusive-boundary test:
    1. Read case to get answer_deadline_at.
    2. Advance clock to exactly answer_deadline_at.
    Returns the case re-read.
    """
    case = re_get_case(case_id)
    advance_clock_safe(case["answer_deadline_at"])
    return re_get_case(case_id)


__all__ = [
    # Clock
    "get_clock_now",
    "server_now_dt",
    "server_offset_iso",
    "advance_clock_to",
    "advance_clock_forward_by",
    "advance_clock_safe",
    # Re-reads
    "re_get_case",
    "re_get_disclosure",
    "re_get_parenting_plan",
    "re_get_support_order",
    "re_get_temp_order",
    "re_get_final_judgment",
    # Single-step helpers
    "create_case",
    "answer_case",
    "default_case",
    "create_disclosure",
    "submit_disclosure",
    "accept_disclosure",
    "reject_disclosure",
    "create_submit_accept_disclosure",
    "propose_parenting_plan",
    "accept_parenting_plan",
    "propose_and_accept_parenting_plan",
    "start_mediation",
    "schedule_mediation_session",
    "start_mediation_session",
    "complete_mediation_session",
    "run_one_full_mediation_session",
    "create_support_order",
    "create_final_judgment_no_minors",
    "pin_clock_for_filed_case",
    # Composite setups
    "setup_case_with_both_disclosures_accepted",
    "setup_case_with_agreed_plan",
    "setup_case_in_mediation_with_proposed_plan",
    "setup_case_mediation_round_3_impasse",
    "setup_case_temp_ordered_with_final_judgment_draft",
    "setup_case_in_awaiting_judgment_no_minors",
]
