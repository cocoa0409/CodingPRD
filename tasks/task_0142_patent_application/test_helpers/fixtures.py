"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce
clear "setup failed" errors rather than confusing assertion failures.

Identity threading rule (PRD §2.1): after creating an Applicant, every
Applicant-owned call MUST use make_applicant_headers(applicant['id']);
the shared fallback constant in TEST_USERS is reserved for tests that
do NOT exercise ownership.

Fixture tiers:
- Tier 1: primitive entity creation with ownership-correct headers.
- Tier 2: entity hierarchies (applicant + application; +fees).
- Tier 3: lifecycle shortcuts (file, examine, allow, grant, abandon).
- Tier 4: accumulation / boundary targeting (clock-anchored maintenance
  due dates, office-action deadlines, PCT deadlines).
- Tier 5: terminal-state scenarios (granted then expired, abandoned).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    MAINTENANCE_GRACE_DAYS,
    MAINTENANCE_STAGE_ANCHOR_YEARS,
    MAINTENANCE_WINDOW_LEAD_DAYS,
    MICRO_SAFE_INCOME_CENTS,
    MICRO_SAFE_PRIOR_FILINGS_COUNT,
    OFFICE_ACTION_EXTENDED_DEADLINE_DAYS,
    OFFICE_ACTION_RESPONSE_DEADLINE_DAYS,
    PCT_NATIONAL_DEADLINE_MONTHS,
)
from .factories import (
    DEFAULT_BASE_CLOCK,
    advance_clock_payload,
    add_calendar_years,
    add_days,
    create_applicant_payload,
    create_application_payload,
    create_fee_payload,
    create_office_action_payload,
    examination_fee_cents,
    excess_claim_fee_cents,
    extension_fee_cents,
    filing_fee_cents,
    iso_utc,
    issue_fee_cents,
    maintenance_fee_cents,
    needs_excess_claim_fee,
    pct_national_fee_cents,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
)


USPTO_ADMIN = TEST_USERS["uspto_admin_headers"]
EXAMINER = TEST_USERS["examiner_headers"]


# ===========================================================================
# Clock helpers — PRD §2.8 USPTOAdmin only
# ===========================================================================
def advance_clock_to(target_dt: datetime) -> Dict[str, Any]:
    """Advance the simulated clock (PRD §2.8 USPTOAdmin only) and
    return the new SystemClock state."""
    res = api_client.advance_clock(iso_utc(target_dt), USPTO_ADMIN)
    return get_success_data(res)


def advance_clock_iso(target_iso: str) -> Dict[str, Any]:
    res = api_client.advance_clock(target_iso, USPTO_ADMIN)
    return get_success_data(res)


def reset_clock_to_base() -> Dict[str, Any]:
    """Best-effort baseline clock reset for tests that need to anchor
    everything on DEFAULT_BASE_CLOCK."""
    res = api_client.advance_clock(iso_utc(DEFAULT_BASE_CLOCK), USPTO_ADMIN)
    return get_success_data(res)


def get_clock_now() -> str:
    res = api_client.get_clock(USPTO_ADMIN)
    return get_success_data(res)["now"]


# ===========================================================================
# Tier 1: primitive entity creation with ownership-correct headers
# ===========================================================================
def create_applicant(
    entity_size: str = "SMALL",
    gross_income_cents: Optional[int] = None,
    prior_filings_count: Optional[int] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an Applicant via USPTOAdmin (PRD §3.1).
    For MICRO entity_size, gross_income_cents and prior_filings_count
    default to safe values (well under any reasonable cap) so the
    eligibility precondition passes.
    """
    if entity_size == "MICRO":
        if gross_income_cents is None:
            gross_income_cents = MICRO_SAFE_INCOME_CENTS
        if prior_filings_count is None:
            prior_filings_count = MICRO_SAFE_PRIOR_FILINGS_COUNT
    payload = create_applicant_payload(
        name=name,
        entity_size=entity_size,
        gross_income_cents=gross_income_cents,
        prior_filings_count=prior_filings_count,
    )
    res = api_client.create_applicant(payload, USPTO_ADMIN)
    return get_success_data(res)


def create_draft_application(
    applicant: Dict[str, Any],
    application_type: str = "UTILITY",
    claim_count: int = 1,
    independent_claim_count: int = 1,
    title: Optional[str] = None,
    parent_application_id: Optional[str] = None,
    continuation_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a DRAFT Application owned by `applicant` (PRD §3.2).
    Uses ownership-correct headers per PRD §2.1."""
    if application_type == "PROVISIONAL":
        claim_count = 0
        independent_claim_count = 0
    payload = create_application_payload(
        applicant_id=applicant["id"],
        application_type=application_type,
        title=title,
        claim_count=claim_count,
        independent_claim_count=independent_claim_count,
        parent_application_id=parent_application_id,
        continuation_type=continuation_type,
    )
    headers = make_applicant_headers(applicant["id"])
    res = api_client.create_application(payload, headers)
    return get_success_data(res)


def pay_fee(
    applicant: Dict[str, Any],
    application: Dict[str, Any],
    fee_category: str,
    amount_cents: int,
    maintenance_fee_id: Optional[str] = None,
    office_action_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_fee_payload(
        fee_category=fee_category,
        amount_cents=amount_cents,
        maintenance_fee_id=maintenance_fee_id,
        office_action_id=office_action_id,
    )
    headers = make_applicant_headers(applicant["id"])
    res = api_client.create_fee_transaction(application["id"], payload, headers)
    return get_success_data(res)


def get_application(application_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    res = api_client.get_application(application_id, headers or USPTO_ADMIN)
    return get_success_data(res)


def get_applicant(applicant_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    res = api_client.get_applicant(applicant_id, headers or USPTO_ADMIN)
    return get_success_data(res)


def get_office_action(office_action_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    res = api_client.get_office_action(office_action_id, headers or USPTO_ADMIN)
    return get_success_data(res)


def get_maintenance_fee(maintenance_fee_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    res = api_client.get_maintenance_fee(maintenance_fee_id, headers or USPTO_ADMIN)
    return get_success_data(res)


def get_pct_phase(pct_phase_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    res = api_client.get_pct_phase(pct_phase_id, headers or USPTO_ADMIN)
    return get_success_data(res)


def list_audit_events(application_id: str) -> List[Dict[str, Any]]:
    res = api_client.list_audit_events(application_id, USPTO_ADMIN, params={"limit": 100})
    body = res.json()
    return body["data"]


def list_maintenance_fees(application_id: str) -> List[Dict[str, Any]]:
    res = api_client.list_maintenance_fees(application_id, USPTO_ADMIN, params={"limit": 100})
    body = res.json()
    return body["data"]


def list_fee_transactions(application_id: str) -> List[Dict[str, Any]]:
    res = api_client.list_fee_transactions(application_id, USPTO_ADMIN, params={"limit": 100})
    body = res.json()
    return body["data"]


def list_office_actions(application_id: str) -> List[Dict[str, Any]]:
    res = api_client.list_office_actions(application_id, USPTO_ADMIN, params={"limit": 100})
    body = res.json()
    return body["data"]


# ===========================================================================
# Tier 2: pay full required fee set
# ===========================================================================
def pay_filing_fees(
    applicant: Dict[str, Any],
    application: Dict[str, Any],
    *,
    include_excess_claim: Optional[bool] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Pay the FILING fee, plus EXCESS_CLAIM when claim counts demand
    it (PRD §3.2). Returns the FeeTransactions created keyed by
    category."""
    out: Dict[str, List[Dict[str, Any]]] = {"FILING": [], "EXCESS_CLAIM": []}
    out["FILING"].append(pay_fee(
        applicant, application, "FILING",
        filing_fee_cents(application["application_type"], applicant["entity_size"]),
    ))
    auto_excess = needs_excess_claim_fee(
        application["claim_count"], application["independent_claim_count"],
    )
    do_excess = auto_excess if include_excess_claim is None else include_excess_claim
    if do_excess:
        out["EXCESS_CLAIM"].append(pay_fee(
            applicant, application, "EXCESS_CLAIM",
            excess_claim_fee_cents(
                application["claim_count"], application["independent_claim_count"],
                applicant["entity_size"],
            ),
        ))
    return out


# ===========================================================================
# Tier 3: lifecycle shortcuts
# ===========================================================================
def file_application(
    applicant: Dict[str, Any], application: Dict[str, Any],
) -> Dict[str, Any]:
    """Transition DRAFT -> FILED (PRD §3.2). Requires that filing fees
    have been paid first."""
    headers = make_applicant_headers(applicant["id"])
    res = api_client.file_application(application["id"], headers)
    return get_success_data(res)


def setup_filed_application(
    entity_size: str = "SMALL",
    application_type: str = "UTILITY",
    claim_count: int = 1,
    independent_claim_count: int = 1,
    applicant: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Applicant + drafted application + filing fees + file (FILED).
    Returns (applicant, application_filed)."""
    if applicant is None:
        applicant = create_applicant(entity_size=entity_size)
    app = create_draft_application(
        applicant,
        application_type=application_type,
        claim_count=claim_count,
        independent_claim_count=independent_claim_count,
    )
    pay_filing_fees(applicant, app)
    filed = file_application(applicant, app)
    return applicant, filed


def begin_examination_full(
    applicant: Dict[str, Any], application: Dict[str, Any],
) -> Dict[str, Any]:
    """Pay EXAMINATION fee + transition FILED -> UNDER_EXAMINATION
    (PRD §3.3)."""
    pay_fee(
        applicant, application, "EXAMINATION",
        examination_fee_cents(applicant["entity_size"]),
    )
    res = api_client.begin_examination(application["id"], EXAMINER)
    return get_success_data(res)


def setup_under_examination(
    entity_size: str = "SMALL",
    application_type: str = "UTILITY",
    claim_count: int = 1,
    independent_claim_count: int = 1,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Reach UNDER_EXAMINATION. Returns (applicant, application)."""
    applicant, app = setup_filed_application(
        entity_size=entity_size,
        application_type=application_type,
        claim_count=claim_count,
        independent_claim_count=independent_claim_count,
    )
    app = begin_examination_full(applicant, app)
    return applicant, app


def issue_office_action(
    application: Dict[str, Any], action_type: str = "NON_FINAL",
) -> Dict[str, Any]:
    """Examiner issues an OA, transitions UNDER_EXAMINATION ->
    OFFICE_ACTION_PENDING (PRD §3.3)."""
    payload = create_office_action_payload(action_type=action_type)
    res = api_client.issue_office_action(application["id"], payload, EXAMINER)
    return get_success_data(res)


def setup_office_action_pending(
    entity_size: str = "SMALL",
    application_type: str = "UTILITY",
    action_type: str = "NON_FINAL",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Reach OFFICE_ACTION_PENDING with one PENDING OA. Returns
    (applicant, application_in_oa_pending, office_action)."""
    applicant, app = setup_under_examination(
        entity_size=entity_size, application_type=application_type,
    )
    oa = issue_office_action(app, action_type=action_type)
    return applicant, app, oa


def respond_to_office_action(
    applicant: Dict[str, Any], office_action: Dict[str, Any],
) -> Dict[str, Any]:
    """File a Response (PRD §3.3). Caller must have already paid any
    extension fee required by the current clock vs deadline state."""
    headers = make_applicant_headers(applicant["id"])
    res = api_client.file_response(office_action["id"], headers)
    return get_success_data(res)


def allow_application(application: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.allow_application(application["id"], EXAMINER)
    return get_success_data(res)


def grant_application_full(
    applicant: Dict[str, Any], application: Dict[str, Any],
) -> Dict[str, Any]:
    """Pay ISSUE fee + transition ALLOWED -> GRANTED (PRD §3.4)."""
    pay_fee(
        applicant, application, "ISSUE",
        issue_fee_cents(applicant["entity_size"]),
    )
    res = api_client.grant_application(application["id"], EXAMINER)
    return get_success_data(res)


def abandon_application(
    applicant: Dict[str, Any], application: Dict[str, Any],
) -> Dict[str, Any]:
    headers = make_applicant_headers(applicant["id"])
    res = api_client.abandon_application(application["id"], headers)
    return get_success_data(res)


def setup_allowed_application(
    entity_size: str = "SMALL", application_type: str = "UTILITY",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Reach ALLOWED. Returns (applicant, application)."""
    applicant, app = setup_under_examination(
        entity_size=entity_size, application_type=application_type,
    )
    app = allow_application(app)
    return applicant, app


def setup_granted_application(
    entity_size: str = "SMALL",
    application_type: str = "UTILITY",
    grant_clock_dt: Optional[datetime] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Reach GRANTED, optionally anchoring the grant moment by
    advancing the SystemClock to grant_clock_dt before the grant call.
    Returns (applicant, granted_application)."""
    if grant_clock_dt is not None:
        advance_clock_to(grant_clock_dt)
    applicant, app = setup_allowed_application(
        entity_size=entity_size, application_type=application_type,
    )
    app = grant_application_full(applicant, app)
    return applicant, app


# ===========================================================================
# Tier 4: accumulation / boundary targeting
# ===========================================================================
def setup_granted_utility_with_maintenance_anchor(
    entity_size: str = "SMALL",
    grant_dt: datetime = DEFAULT_BASE_CLOCK,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Anchor a granted UTILITY application at grant_dt so that
    maintenance windows have predictable timestamps. Returns
    (applicant, granted_application, maintenance_fees_sorted_by_stage).

    PRD §3.4: "the server provisions a MaintenanceFee row whose stage
    is one of STAGE_3_5, STAGE_7_5, or STAGE_11_5, whose window_open_at
    is the grant instant plus the stage anchor in years minus six
    months ... whose due_at is the grant instant plus the stage anchor
    in years exactly ... whose grace_period_end_at is the due date
    plus 180 days, and whose status defaults to SCHEDULED."
    """
    reset_clock_to_base()
    advance_clock_to(grant_dt)
    applicant, app = setup_granted_application(
        entity_size=entity_size, application_type="UTILITY",
    )
    mfs = list_maintenance_fees(app["id"])
    mfs.sort(key=lambda x: x["due_at"])
    return applicant, app, mfs


def setup_office_action_at_clock(
    entity_size: str = "SMALL",
    issued_at_dt: datetime = DEFAULT_BASE_CLOCK,
    action_type: str = "NON_FINAL",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Anchor an OA issuance moment so response/extended deadlines are
    predictable. Returns (applicant, application, office_action)."""
    reset_clock_to_base()
    applicant, app = setup_under_examination(entity_size=entity_size)
    advance_clock_to(issued_at_dt)
    oa = issue_office_action(app, action_type=action_type)
    return applicant, app, oa


def initiate_pct_phase(
    applicant: Dict[str, Any], application: Dict[str, Any],
) -> Dict[str, Any]:
    """PRD §3.6: initiate PCT international phase. Returns PCTPhase."""
    headers = make_applicant_headers(applicant["id"])
    res = api_client.initiate_pct_phase(application["id"], headers)
    return get_success_data(res)


def setup_pct_phase_filed(
    entity_size: str = "SMALL",
    file_dt: datetime = DEFAULT_BASE_CLOCK,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Reach a PCTPhase in INTERNATIONAL with priority_date pinned to
    `file_dt`. Returns (applicant, application_filed, pct_phase)."""
    reset_clock_to_base()
    advance_clock_to(file_dt)
    applicant, app = setup_filed_application(entity_size=entity_size)
    pct = initiate_pct_phase(applicant, app)
    return applicant, app, pct


def pay_maintenance_and_settle(
    applicant: Dict[str, Any],
    application: Dict[str, Any],
    maintenance_fee: Dict[str, Any],
    in_grace: bool,
) -> Dict[str, Any]:
    """Pay the maintenance fee transaction AND invoke the pay
    transition. Returns the updated MaintenanceFee row."""
    pay_fee(
        applicant, application, "MAINTENANCE",
        maintenance_fee_cents(
            maintenance_fee["stage"], applicant["entity_size"], in_grace,
        ),
        maintenance_fee_id=maintenance_fee["id"],
    )
    headers = make_applicant_headers(applicant["id"])
    res = api_client.pay_maintenance_fee(maintenance_fee["id"], headers)
    return get_success_data(res)


def pay_pct_national_and_enter(
    applicant: Dict[str, Any],
    application: Dict[str, Any],
    pct_phase: Dict[str, Any],
) -> Dict[str, Any]:
    """Pay PCT_NATIONAL fee + transition INTERNATIONAL ->
    NATIONAL_ENTERED. Returns the updated PCTPhase row."""
    pay_fee(
        applicant, application, "PCT_NATIONAL",
        pct_national_fee_cents(applicant["entity_size"]),
    )
    headers = make_applicant_headers(applicant["id"])
    res = api_client.enter_national_phase(pct_phase["id"], headers)
    return get_success_data(res)


# ===========================================================================
# Tier 5: deeper composite setups for difficulty-design recipes
# ===========================================================================
def setup_late_response_ready(
    entity_size: str = "SMALL",
    months_extension: int = 1,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Reach OFFICE_ACTION_PENDING and advance the clock past the
    shortened response_deadline_at by `months_extension` months so a
    response now requires an EXTENSION fee.

    Returns (applicant, application, office_action) with clock just
    past the boundary for the chosen month-extension band.
    """
    reset_clock_to_base()
    applicant, app, oa = setup_office_action_pending(entity_size=entity_size)
    # Move clock to roughly `months_extension*30` days past
    # response_deadline_at but BEFORE extended_deadline_at.
    rd_iso = oa["response_deadline_at"]
    rd = datetime.fromisoformat(rd_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    target = rd + timedelta(days=(months_extension - 1) * 30 + 5)
    advance_clock_to(target)
    return applicant, app, oa


def setup_two_filed_apps_for_continuation_race(
    parent_app_type: str = "UTILITY",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Set up a single applicant with a FILED parent application
    eligible to be referenced by two competing continuation drafts.

    Returns (applicant, parent_application_filed, applicant_2).
    The two competing CHILD drafts can be created and FILED by the test
    via setup-time helpers.
    """
    applicant, parent = setup_filed_application(application_type=parent_app_type)
    # A second applicant is rarely needed for the continuation race —
    # PRD allows continuations only when the actor is the parent's
    # applicant (own resource per PRD §2.1) — so return only the
    # primary actor.
    return applicant, parent, applicant


def setup_two_office_action_pending_apps(
    entity_size: str = "SMALL",
    issued_at_dt: datetime = DEFAULT_BASE_CLOCK,
) -> Tuple[
    Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]],
    Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]],
]:
    """Create two independent applications, each in OFFICE_ACTION_PENDING
    with one PENDING OA issued at issued_at_dt. Returns
    ((applicant_a, app_a, oa_a), (applicant_b, app_b, oa_b))."""
    reset_clock_to_base()
    a_app, a_app_obj, a_oa = setup_office_action_at_clock(
        entity_size=entity_size, issued_at_dt=issued_at_dt,
    )
    b_app, b_app_obj, b_oa = setup_office_action_at_clock(
        entity_size=entity_size, issued_at_dt=issued_at_dt,
    )
    return (a_app, a_app_obj, a_oa), (b_app, b_app_obj, b_oa)


def setup_granted_utility_at_calendar_anchor(
    entity_size: str = "SMALL",
    grant_year: int = 2024,
    grant_month: int = 1,
    grant_day: int = 1,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Anchor a granted UTILITY application at a calendar-clean grant
    moment (YYYY-MM-DD T00:00:00Z). Returns (applicant, application,
    maintenance_fees)."""
    grant_dt = datetime(
        grant_year, grant_month, grant_day, 0, 0, 0, tzinfo=timezone.utc,
    )
    return setup_granted_utility_with_maintenance_anchor(
        entity_size=entity_size, grant_dt=grant_dt,
    )


__all__ = [
    # clock
    "advance_clock_to",
    "advance_clock_iso",
    "reset_clock_to_base",
    "get_clock_now",
    # Tier 1
    "create_applicant",
    "create_draft_application",
    "pay_fee",
    "get_application",
    "get_applicant",
    "get_office_action",
    "get_maintenance_fee",
    "get_pct_phase",
    "list_audit_events",
    "list_maintenance_fees",
    "list_fee_transactions",
    "list_office_actions",
    # Tier 2
    "pay_filing_fees",
    # Tier 3
    "file_application",
    "setup_filed_application",
    "begin_examination_full",
    "setup_under_examination",
    "issue_office_action",
    "setup_office_action_pending",
    "respond_to_office_action",
    "allow_application",
    "grant_application_full",
    "abandon_application",
    "setup_allowed_application",
    "setup_granted_application",
    # Tier 4
    "setup_granted_utility_with_maintenance_anchor",
    "setup_office_action_at_clock",
    "initiate_pct_phase",
    "setup_pct_phase_filed",
    "pay_maintenance_and_settle",
    "pay_pct_national_and_enter",
    # Tier 5
    "setup_late_response_ready",
    "setup_two_filed_apps_for_continuation_race",
    "setup_two_office_action_pending_apps",
    "setup_granted_utility_at_calendar_anchor",
    # constants re-exported
    "USPTO_ADMIN",
    "EXAMINER",
]
