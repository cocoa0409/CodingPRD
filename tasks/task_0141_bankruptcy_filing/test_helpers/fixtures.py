"""Composite setup helpers — multi-step preambles tests can reuse.

The bankruptcy lifecycle is long: register Debtor → open Case in DRAFT
→ submit all ten Schedules A-J → run means test → file (stay flips on)
→ schedule 341 → conduct 341 (claims cascade to ALLOWED) → either
discharge (Ch7) or propose plan → confirm → first APPLIED payment →
IN_REPAYMENT → fulfill plan → discharge (waterfall + partition + stay
lifts). Many tests need the system in a late lifecycle state.

IDENTITY THREADING — PRD §2.1:

- Trustee and Judge are OPAQUE. Shared constants
  (trustee_headers, judge_headers) are canonical for every operator-only
  call.

- Debtor and Creditor are ENTITY-BACKED. Every Debtor- or
  Creditor-driven call whose success depends on owning the targeted
  resource MUST mint headers via make_debtor_headers(debtor["id"]) or
  make_creditor_headers(creditor["id"]) — never via the shared
  *_FALLBACK_ID constants. The fixtures here capture the actual entity
  rows and route ownership-gated calls through the per-instance header
  builders.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    MEETING_341_MIN_GAP_DAYS,
    SCHEDULE_TYPES_REQUIRED,
    TEST_DEFAULTS,
)
from .factories import (
    clock_advance_payload,
    create_case_payload,
    create_claim_payload,
    create_collection_action_payload,
    create_creditor_payload,
    create_debtor_payload,
    create_payment_payload,
    create_plan_payload,
    create_schedule_payload,
    income_line,
    iso_offset,
    iso_utc,
    parse_iso,
    schedule_341_payload,
    six_month_income_lines,
)
from .test_users import (
    TEST_USERS,
    make_creditor_headers,
    make_debtor_headers,
)


# ===========================================================================
# Clock — PRD §3.5 (test-only, Trustee)
# ===========================================================================
def advance_clock_to(to_iso8601: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /_clock/advance.

    PRD §3.5: 'tests need to drive the clock without waiting in
    wall-clock time, the system exposes an admin-only clock-advancement
    capability that accepts a to_iso8601 parameter'. PRD §4 RBAC:
    Trustee.
    """
    headers = headers or TEST_USERS["trustee_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to_iso8601=to_iso8601), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 1: Debtor / Creditor / Case primitives
# ===========================================================================
def create_debtor(
    *,
    household_size: Optional[int] = None,
    state_code: Optional[str] = None,
    full_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /debtors — Debtor only per PRD §4.

    Identity threading note: when creating a new Debtor, ownership has
    not yet been established (the row is being minted). The shared
    debtor_fallback_headers is acceptable here only because the act of
    POST /debtors does not require X-User-ID to equal any existing
    Debtor.id (it produces a new Debtor.id). After this call, every
    downstream Debtor-acting call MUST use make_debtor_headers on the
    returned Debtor.id.
    """
    headers = headers or TEST_USERS["debtor_fallback_headers"]
    resp = api_client.create_debtor(
        create_debtor_payload(
            full_name=full_name,
            household_size=household_size,
            state_code=state_code,
        ),
        headers,
    )
    return get_success_data(resp)


def create_creditor(
    *,
    creditor_type: str = "GENERAL_UNSECURED",
    name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /creditors — Creditor only per PRD §4.

    Same identity bootstrapping note as create_debtor — the act of
    minting the row is permitted via the fallback header. Every
    downstream Creditor-acting call MUST use make_creditor_headers on
    the returned Creditor.id.
    """
    headers = headers or TEST_USERS["creditor_fallback_headers"]
    resp = api_client.create_creditor(
        create_creditor_payload(name=name, creditor_type=creditor_type),
        headers,
    )
    return get_success_data(resp)


def create_case(
    *,
    debtor: Dict[str, Any],
    chapter_requested: str = "CHAPTER_7",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases — Debtor only per PRD §4.

    Identity threading: PRD §2.1 'ownership checks on any case-scoped
    resource compare Case.debtor_id to X-User-ID, so debtors may only
    act on their own cases'. We mint headers with the actual Debtor.id.
    """
    headers = headers or make_debtor_headers(debtor["id"])
    resp = api_client.create_case(
        create_case_payload(
            debtor_id=debtor["id"],
            chapter_requested=chapter_requested,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 1: Schedule submission — PRD §3.2
# ===========================================================================
def submit_schedule(
    *,
    case: Dict[str, Any],
    debtor: Dict[str, Any],
    schedule_type: str,
    line_items: Optional[List[Dict[str, Any]]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/schedules — Debtor only per PRD §4.

    PRD §2.1 ownership: Debtor's X-User-ID must equal Case.debtor_id.
    """
    headers = headers or make_debtor_headers(debtor["id"])
    resp = api_client.submit_schedule(
        case["id"],
        create_schedule_payload(
            schedule_type=schedule_type,
            line_items=line_items if line_items is not None else [],
        ),
        headers,
    )
    return get_success_data(resp)


def submit_all_other_schedules(
    *,
    case: Dict[str, Any],
    debtor: Dict[str, Any],
    skip: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Submit schedules A-H with empty line items (the 'asset' & 'debt'
    style schedules that have no impact on means-test). Schedule I and J
    must be supplied separately by the caller — they drive the means
    test. Use `skip` to omit specific letters (default omits I and J).
    """
    skip_set = set(skip) if skip is not None else {"I", "J"}
    out: List[Dict[str, Any]] = []
    for letter in SCHEDULE_TYPES_REQUIRED:
        if letter in skip_set:
            continue
        out.append(
            submit_schedule(
                case=case, debtor=debtor, schedule_type=letter,
                line_items=[],
            )
        )
    return out


def submit_schedule_i(
    *,
    case: Dict[str, Any],
    debtor: Dict[str, Any],
    per_month_cents: Optional[int] = None,
    monthly_amounts_cents: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Submit a Schedule I with six monthly income line items.

    If monthly_amounts_cents is supplied, use those six values directly
    (allows uneven months to drive rounding tests). Otherwise pad with
    six identical entries of per_month_cents.
    """
    if monthly_amounts_cents is not None:
        assert len(monthly_amounts_cents) >= 1
        line_items = [
            income_line(c, f"wages-month-{i+1}")
            for i, c in enumerate(monthly_amounts_cents)
        ]
    else:
        per = (
            per_month_cents
            if per_month_cents is not None
            else TEST_DEFAULTS["MONTHLY_INCOME_CENTS"]
        )
        line_items = six_month_income_lines(per_month_cents=per)
    return submit_schedule(
        case=case, debtor=debtor,
        schedule_type="I", line_items=line_items,
    )


def submit_schedule_j(
    *,
    case: Dict[str, Any],
    debtor: Dict[str, Any],
    expenses_cents: Optional[int] = None,
    line_items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Submit a Schedule J with a single expenses line (or a custom set
    of line_items provided by caller)."""
    if line_items is None:
        amt = (
            expenses_cents
            if expenses_cents is not None
            else TEST_DEFAULTS["MONTHLY_EXPENSES_CENTS"]
        )
        line_items = [income_line(amt, "monthly expenses")]
    return submit_schedule(
        case=case, debtor=debtor,
        schedule_type="J", line_items=line_items,
    )


def submit_all_schedules_for(
    *,
    case: Dict[str, Any],
    debtor: Dict[str, Any],
    monthly_income_cents: Optional[int] = None,
    monthly_expenses_cents: Optional[int] = None,
    income_amounts_cents: Optional[List[int]] = None,
    schedule_j_line_items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Submit all ten schedules A-J. Returns a dict mapping
    schedule_type -> active Schedule row. Schedule I drives the
    means-test six-month average; Schedule J drives the expenses sum.
    """
    out: Dict[str, Any] = {}
    submit_all_other_schedules(case=case, debtor=debtor)
    out["I"] = submit_schedule_i(
        case=case, debtor=debtor,
        per_month_cents=monthly_income_cents,
        monthly_amounts_cents=income_amounts_cents,
    )
    out["J"] = submit_schedule_j(
        case=case, debtor=debtor,
        expenses_cents=monthly_expenses_cents,
        line_items=schedule_j_line_items,
    )
    return out


# ===========================================================================
# Tier 1: Means test — PRD §3.3
# ===========================================================================
def run_means_test(
    *,
    case: Dict[str, Any],
    debtor: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/means-test — Debtor or Trustee per PRD §4."""
    headers = headers or make_debtor_headers(debtor["id"])
    resp = api_client.run_means_test(case["id"], None, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 1: Case lifecycle (DRAFT → FILED → MEETING_SCHEDULED → ...)
# ===========================================================================
def file_case(
    *,
    case: Dict[str, Any],
    debtor: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/file — Debtor only per PRD §4."""
    headers = headers or make_debtor_headers(debtor["id"])
    resp = api_client.file_case(case["id"], None, headers)
    return get_success_data(resp)


def schedule_341(
    *,
    case: Dict[str, Any],
    meeting_date_iso: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/schedule-341 — Trustee only per PRD §4."""
    headers = headers or TEST_USERS["trustee_headers"]
    resp = api_client.schedule_341(
        case["id"],
        schedule_341_payload(meeting_date=meeting_date_iso),
        headers,
    )
    return get_success_data(resp)


def conduct_341(
    *,
    case: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/conduct-341 — Trustee only per PRD §4."""
    headers = headers or TEST_USERS["trustee_headers"]
    resp = api_client.conduct_341(case["id"], None, headers)
    return get_success_data(resp)


def dismiss_case(
    *,
    case: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/dismiss — Trustee only per PRD §4."""
    headers = headers or TEST_USERS["trustee_headers"]
    resp = api_client.dismiss_case(case["id"], None, headers)
    return get_success_data(resp)


def discharge_case(
    *,
    case: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/discharge — Judge only per PRD §4."""
    headers = headers or TEST_USERS["judge_headers"]
    resp = api_client.discharge_case(case["id"], None, headers)
    return get_success_data(resp)


def withdraw_case(
    *,
    case: Dict[str, Any],
    debtor: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """DELETE /cases/{case_id} — Debtor only per PRD §4."""
    headers = headers or make_debtor_headers(debtor["id"])
    resp = api_client.withdraw_case(case["id"], headers)
    return get_success_data(resp)


def re_get_case(
    case_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """GET /cases/{case_id}. Default to Trustee header (universally
    permitted for reads per PRD §4).
    """
    headers = headers or TEST_USERS["trustee_headers"]
    resp = api_client.get_case(case_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 1: Claim primitives — PRD §3.6
# ===========================================================================
def file_claim(
    *,
    case: Dict[str, Any],
    creditor: Dict[str, Any],
    amount_cents: int,
    is_dischargeable: bool = True,
    claim_class: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/claims — Creditor only per PRD §4.

    PRD §3.6: 'creditor_id must match the acting X-User-ID, the
    claim_class must equal the registered creditor_type of that
    creditor'. claim_class defaults to creditor.creditor_type so the
    happy-path fixture does not trip the class-mismatch rule.
    """
    headers = headers or make_creditor_headers(creditor["id"])
    resp = api_client.create_claim(
        case["id"],
        create_claim_payload(
            creditor_id=creditor["id"],
            claim_class=claim_class or creditor["creditor_type"],
            amount_cents=amount_cents,
            is_dischargeable=is_dischargeable,
        ),
        headers,
    )
    return get_success_data(resp)


def disallow_claim(
    *,
    case: Dict[str, Any],
    claim: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/claims/{claim_id}/disallow — Trustee."""
    headers = headers or TEST_USERS["trustee_headers"]
    resp = api_client.disallow_claim(case["id"], claim["id"], None, headers)
    return get_success_data(resp)


def re_get_claim(
    case_id: str,
    claim_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["trustee_headers"]
    resp = api_client.get_claim(case_id, claim_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 1: Plan / payment primitives — PRD §3.8 / §3.9
# ===========================================================================
def submit_plan(
    *,
    case: Dict[str, Any],
    debtor: Dict[str, Any],
    proposed_monthly_payment_cents: int,
    plan_months: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/plans — Debtor only per PRD §4."""
    headers = headers or make_debtor_headers(debtor["id"])
    resp = api_client.create_plan(
        case["id"],
        create_plan_payload(
            proposed_monthly_payment_cents=proposed_monthly_payment_cents,
            plan_months=plan_months,
        ),
        headers,
    )
    return get_success_data(resp)


def withdraw_plan(
    *,
    case: Dict[str, Any],
    plan: Dict[str, Any],
    debtor: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """DELETE /cases/{case_id}/plans/{plan_id} — Debtor only."""
    headers = headers or make_debtor_headers(debtor["id"])
    resp = api_client.withdraw_plan(case["id"], plan["id"], headers)
    return get_success_data(resp)


def confirm_plan(
    *,
    case: Dict[str, Any],
    plan: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/plans/{plan_id}/confirm — Judge."""
    headers = headers or TEST_USERS["judge_headers"]
    resp = api_client.confirm_plan(case["id"], plan["id"], None, headers)
    return get_success_data(resp)


def record_payment(
    *,
    case: Dict[str, Any],
    plan: Dict[str, Any],
    debtor: Dict[str, Any],
    sequence_number: int,
    amount_cents: int,
    status: str = "APPLIED",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/plans/{plan_id}/payments — Debtor or
    Trustee per PRD §4.
    """
    headers = headers or make_debtor_headers(debtor["id"])
    resp = api_client.record_payment(
        case["id"], plan["id"],
        create_payment_payload(
            sequence_number=sequence_number,
            amount_cents=amount_cents,
            status=status,
        ),
        headers,
    )
    return get_success_data(resp)


def re_get_plan(
    case_id: str,
    plan_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["trustee_headers"]
    resp = api_client.get_plan(case_id, plan_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 1: CollectionAction — PRD §2.7
# ===========================================================================
def attempt_collection_action(
    *,
    case: Dict[str, Any],
    creditor: Dict[str, Any],
    action_kind: str = "GARNISH",
    headers: Optional[Dict[str, str]] = None,
):
    """POST /collection-actions — Creditor only per PRD §4. Returns the
    raw response object (callers may need to inspect failure outcomes;
    PRD §2.7 maps REJECTED_STAY to a 409 error).
    """
    headers = headers or make_creditor_headers(creditor["id"])
    return api_client.create_collection_action(
        create_collection_action_payload(
            creditor_id=creditor["id"],
            case_id=case["id"],
            action_kind=action_kind,
        ),
        headers,
    )


def list_collection_actions(
    *,
    case: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
):
    """GET /cases/{case_id}/collection-actions — Trustee, Judge, or
    Creditor per PRD §4.
    """
    headers = headers or TEST_USERS["trustee_headers"]
    return api_client.list_collection_actions(case["id"], headers, params)


# ===========================================================================
# Tier 2/3: Composite scenarios — common multi-step preambles.
# ===========================================================================
def setup_draft_case_filing_ready(
    *,
    chapter_requested: str = "CHAPTER_7",
    state_code: str = "TX",
    household_size: int = 1,
    monthly_income_cents: Optional[int] = None,
    monthly_expenses_cents: Optional[int] = None,
    income_amounts_cents: Optional[List[int]] = None,
    schedule_j_line_items: Optional[List[Dict[str, Any]]] = None,
    run_means: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Optional[Dict[str, Any]]]:
    """Build a DRAFT case with all ten schedules and (optionally) the
    means-test result. Returns (debtor, case, schedules_dict,
    means_test_result_or_None).

    Defaults: TX household_size=1, monthly_income=4,000 USD,
    monthly_expenses=2,000 USD. With those defaults CMI annualized is
    48,000 USD which is below the TX-1 median of 60,000 USD, so
    presumption_of_abuse=false and Ch7 filing succeeds.
    """
    debtor = create_debtor(
        household_size=household_size, state_code=state_code,
    )
    case = create_case(
        debtor=debtor, chapter_requested=chapter_requested,
    )
    schedules = submit_all_schedules_for(
        case=case, debtor=debtor,
        monthly_income_cents=monthly_income_cents,
        monthly_expenses_cents=monthly_expenses_cents,
        income_amounts_cents=income_amounts_cents,
        schedule_j_line_items=schedule_j_line_items,
    )
    mtr = None
    if run_means:
        mtr = run_means_test(case=case, debtor=debtor)
    return debtor, case, schedules, mtr


def setup_filed_case(
    *,
    chapter_requested: str = "CHAPTER_7",
    state_code: str = "TX",
    household_size: int = 1,
    monthly_income_cents: Optional[int] = None,
    monthly_expenses_cents: Optional[int] = None,
    income_amounts_cents: Optional[List[int]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a Case in FILED state. Returns (debtor, case_after_file,
    means_test_result).

    Defaults are tuned so the means test does NOT produce presumption
    (income below TX-1 median), letting Ch7 filing succeed.
    """
    debtor, case, _schedules, mtr = setup_draft_case_filing_ready(
        chapter_requested=chapter_requested, state_code=state_code,
        household_size=household_size,
        monthly_income_cents=monthly_income_cents,
        monthly_expenses_cents=monthly_expenses_cents,
        income_amounts_cents=income_amounts_cents,
    )
    case_filed = file_case(case=case, debtor=debtor)
    assert mtr is not None
    return debtor, case_filed, mtr


def setup_meeting_scheduled_case(
    *,
    chapter_requested: str = "CHAPTER_7",
    days_after_filing: int = MEETING_341_MIN_GAP_DAYS,
    state_code: str = "TX",
    household_size: int = 1,
    monthly_income_cents: Optional[int] = None,
    monthly_expenses_cents: Optional[int] = None,
    income_amounts_cents: Optional[List[int]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], str]:
    """Build a Case in MEETING_SCHEDULED state. Returns (debtor, case,
    means_test_result, meeting_date_iso).

    PRD §3.5 boundary: meeting_date >= filing_date + 21 days. The
    fixture defaults to exactly +21 days (inclusive boundary).
    """
    debtor, case_filed, mtr = setup_filed_case(
        chapter_requested=chapter_requested,
        state_code=state_code, household_size=household_size,
        monthly_income_cents=monthly_income_cents,
        monthly_expenses_cents=monthly_expenses_cents,
        income_amounts_cents=income_amounts_cents,
    )
    filing_date = parse_iso(case_filed["filing_date"])
    meeting_date_iso = iso_offset(
        days=days_after_filing, base=filing_date,
    )
    case_after = schedule_341(
        case=case_filed, meeting_date_iso=meeting_date_iso,
    )
    return debtor, case_after, mtr, meeting_date_iso


def setup_meeting_held_case(
    *,
    chapter_requested: str = "CHAPTER_7",
    state_code: str = "TX",
    household_size: int = 1,
    monthly_income_cents: Optional[int] = None,
    monthly_expenses_cents: Optional[int] = None,
    income_amounts_cents: Optional[List[int]] = None,
    days_after_filing: int = MEETING_341_MIN_GAP_DAYS,
    claims: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    List[Dict[str, Any]], List[Dict[str, Any]],
]:
    """Build a Case in MEETING_HELD with optional FILED claims that
    will auto-cascade to ALLOWED on conduct_341.

    Returns (debtor, case, means_test_result, creditors, claims).
    `claims` argument is a list of dicts shaped {amount_cents:int,
    is_dischargeable:bool, claim_class:str}. Each claim gets its own
    Creditor whose creditor_type matches its claim_class.

    PRD §3.5 cascade: conducting the 341 meeting auto-transitions every
    Claim still in FILED to ALLOWED.
    """
    debtor, case_sched, mtr, meeting_date_iso = setup_meeting_scheduled_case(
        chapter_requested=chapter_requested,
        state_code=state_code, household_size=household_size,
        monthly_income_cents=monthly_income_cents,
        monthly_expenses_cents=monthly_expenses_cents,
        income_amounts_cents=income_amounts_cents,
        days_after_filing=days_after_filing,
    )

    # File any specified claims while case is still in MEETING_SCHEDULED.
    creditors: List[Dict[str, Any]] = []
    filed_claims: List[Dict[str, Any]] = []
    for spec in claims or []:
        cls = spec.get("claim_class", "GENERAL_UNSECURED")
        cr = create_creditor(creditor_type=cls)
        cl = file_claim(
            case=case_sched, creditor=cr,
            amount_cents=spec["amount_cents"],
            is_dischargeable=spec.get("is_dischargeable", True),
            claim_class=cls,
        )
        creditors.append(cr)
        filed_claims.append(cl)

    # Advance the clock so server clock >= meeting_341_date, then
    # conduct.
    advance_clock_to(meeting_date_iso)
    case_held = conduct_341(case=case_sched)

    # Re-fetch each claim so caller sees the post-cascade status.
    refreshed = [
        re_get_claim(case_held["id"], cl["id"])
        for cl in filed_claims
    ]
    return debtor, case_held, mtr, creditors, refreshed


def setup_ch13_plan_proposed(
    *,
    monthly_payment_cents: Optional[int] = None,
    plan_months: Optional[int] = None,
    state_code: str = "TX",
    household_size: int = 1,
    monthly_income_cents: Optional[int] = None,
    monthly_expenses_cents: Optional[int] = None,
    income_amounts_cents: Optional[List[int]] = None,
    claims: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    List[Dict[str, Any]], List[Dict[str, Any]],
]:
    """Build a Chapter 13 case in PLAN_PROPOSED with one PROPOSED Plan.

    Returns (debtor, case, means_test_result, plan, creditors, claims).

    The Plan's plan_months defaults to means_test.required_plan_months
    (so it does not trip ERR_PLAN_MONTHS_MISMATCH). monthly_payment
    defaults to a value that meets minimum_plan_total_cents exactly.
    """
    debtor, case_held, mtr, creditors, refreshed = setup_meeting_held_case(
        chapter_requested="CHAPTER_13",
        state_code=state_code, household_size=household_size,
        monthly_income_cents=monthly_income_cents,
        monthly_expenses_cents=monthly_expenses_cents,
        income_amounts_cents=income_amounts_cents,
        claims=claims,
    )
    if plan_months is None:
        plan_months = mtr["required_plan_months"]
    if monthly_payment_cents is None:
        # Just meet the floor exactly.
        min_total = mtr["minimum_plan_total_cents"]
        # +plan_months-1 to round up integer division.
        monthly_payment_cents = max(
            0, (min_total + plan_months - 1) // plan_months,
        )
        # If disposable income is 0, min_total is 0; use a small
        # nominal payment so payments can still be recorded.
        if monthly_payment_cents == 0:
            monthly_payment_cents = 10_000  # $100/month nominal
    plan = submit_plan(
        case=case_held, debtor=debtor,
        proposed_monthly_payment_cents=monthly_payment_cents,
        plan_months=plan_months,
    )
    # Re-fetch case to capture PLAN_PROPOSED status.
    case_after = re_get_case(case_held["id"])
    return debtor, case_after, mtr, plan, creditors, refreshed


def setup_ch13_plan_confirmed(
    *,
    monthly_payment_cents: Optional[int] = None,
    plan_months: Optional[int] = None,
    state_code: str = "TX",
    household_size: int = 1,
    monthly_income_cents: Optional[int] = None,
    monthly_expenses_cents: Optional[int] = None,
    income_amounts_cents: Optional[List[int]] = None,
    claims: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    List[Dict[str, Any]], List[Dict[str, Any]],
]:
    """Build a Chapter 13 case in PLAN_CONFIRMED state. Plan in
    CONFIRMED. Returns (debtor, case, means_test_result, plan,
    creditors, claims).
    """
    (
        debtor, case_proposed, mtr, plan, creditors, refreshed,
    ) = setup_ch13_plan_proposed(
        monthly_payment_cents=monthly_payment_cents,
        plan_months=plan_months,
        state_code=state_code, household_size=household_size,
        monthly_income_cents=monthly_income_cents,
        monthly_expenses_cents=monthly_expenses_cents,
        income_amounts_cents=income_amounts_cents,
        claims=claims,
    )
    plan_confirmed = confirm_plan(case=case_proposed, plan=plan)
    case_after = re_get_case(case_proposed["id"])
    return debtor, case_after, mtr, plan_confirmed, creditors, refreshed


def setup_ch13_in_repayment(
    *,
    monthly_payment_cents: int = 10_000,
    plan_months: Optional[int] = None,
    first_payment_applied: bool = True,
    state_code: str = "TX",
    household_size: int = 1,
    monthly_income_cents: Optional[int] = None,
    monthly_expenses_cents: Optional[int] = None,
    income_amounts_cents: Optional[List[int]] = None,
    claims: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    List[Dict[str, Any]], List[Dict[str, Any]],
]:
    """Build a Chapter 13 case in IN_REPAYMENT (first APPLIED payment
    has been recorded). Returns (debtor, case, mtr, plan_after_first,
    creditors, claims).

    PRD §3.9: 'The first APPLIED payment with sequence_number 1 on a
    CONFIRMED plan advances the case from PLAN_CONFIRMED to
    IN_REPAYMENT.'
    """
    (
        debtor, case_conf, mtr, plan_conf, creditors, refreshed,
    ) = setup_ch13_plan_confirmed(
        monthly_payment_cents=monthly_payment_cents,
        plan_months=plan_months,
        state_code=state_code, household_size=household_size,
        monthly_income_cents=monthly_income_cents,
        monthly_expenses_cents=monthly_expenses_cents,
        income_amounts_cents=income_amounts_cents,
        claims=claims,
    )
    if first_payment_applied:
        record_payment(
            case=case_conf, plan=plan_conf, debtor=debtor,
            sequence_number=1,
            amount_cents=plan_conf["proposed_monthly_payment_cents"],
            status="APPLIED",
        )
    plan_after = re_get_plan(case_conf["id"], plan_conf["id"])
    case_after = re_get_case(case_conf["id"])
    return debtor, case_after, mtr, plan_after, creditors, refreshed


def setup_ch13_plan_fully_paid(
    *,
    monthly_payment_cents: int = 10_000,
    plan_months: Optional[int] = None,
    state_code: str = "TX",
    household_size: int = 1,
    monthly_income_cents: Optional[int] = None,
    monthly_expenses_cents: Optional[int] = None,
    claims: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    List[Dict[str, Any]], List[Dict[str, Any]],
]:
    """Build a Chapter 13 case in IN_REPAYMENT where Plan is fully paid
    (paid_to_date_cents >= planned_total_cents and
    missed_payment_count == 0). The case is ready for Ch13 discharge.
    Returns (debtor, case, mtr, plan, creditors, claims).
    """
    (
        debtor, case_in_rep, mtr, plan_after_first, creditors, refreshed,
    ) = setup_ch13_in_repayment(
        monthly_payment_cents=monthly_payment_cents,
        plan_months=plan_months,
        first_payment_applied=True,
        state_code=state_code, household_size=household_size,
        monthly_income_cents=monthly_income_cents,
        monthly_expenses_cents=monthly_expenses_cents,
        claims=claims,
    )
    plan_id = plan_after_first["id"]
    months = plan_after_first["plan_months"]
    per_payment = plan_after_first["proposed_monthly_payment_cents"]
    # Record the remaining APPLIED payments to reach planned_total.
    for seq in range(2, months + 1):
        record_payment(
            case=case_in_rep, plan=plan_after_first, debtor=debtor,
            sequence_number=seq, amount_cents=per_payment,
            status="APPLIED",
        )
    plan_final = re_get_plan(case_in_rep["id"], plan_id)
    case_final = re_get_case(case_in_rep["id"])
    return debtor, case_final, mtr, plan_final, creditors, refreshed


def setup_ch7_discharged_case(
    *,
    state_code: str = "TX",
    household_size: int = 1,
    monthly_income_cents: Optional[int] = None,
    monthly_expenses_cents: Optional[int] = None,
    claims: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    List[Dict[str, Any]], List[Dict[str, Any]],
]:
    """Walk a Ch7 case from DRAFT → DISCHARGED. Returns (debtor, case,
    mtr, creditors, post_discharge_claims).
    """
    debtor, case_held, mtr, creditors, refreshed = setup_meeting_held_case(
        chapter_requested="CHAPTER_7",
        state_code=state_code, household_size=household_size,
        monthly_income_cents=monthly_income_cents,
        monthly_expenses_cents=monthly_expenses_cents,
        claims=claims,
    )
    discharge_case(case=case_held)
    case_final = re_get_case(case_held["id"])
    post_claims = [
        re_get_claim(case_final["id"], cl["id"]) for cl in refreshed
    ]
    return debtor, case_final, mtr, creditors, post_claims


# ===========================================================================
# Tier 4: Threshold / accumulation helpers
# ===========================================================================
def setup_ch13_with_missed_payments(
    *,
    monthly_payment_cents: int = 10_000,
    plan_months: Optional[int] = None,
    missed_count: int = 2,
    state_code: str = "TX",
    household_size: int = 1,
    monthly_income_cents: Optional[int] = None,
    monthly_expenses_cents: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a Ch13 case in IN_REPAYMENT with a precise number of MISSED
    payments recorded. Returns (debtor, case, mtr, plan_with_misses).

    Sequence used:
    - sequence 1: APPLIED (drives transition to IN_REPAYMENT)
    - sequence 2..(missed_count+1): MISSED

    PRD §3.11 boundary: dismissal from IN_REPAYMENT requires
    missed_payment_count >= 3 (strict three-strikes).
    """
    (
        debtor, case_in_rep, mtr, plan_after_first, _cr, _cl,
    ) = setup_ch13_in_repayment(
        monthly_payment_cents=monthly_payment_cents,
        plan_months=plan_months,
        first_payment_applied=True,
        state_code=state_code, household_size=household_size,
        monthly_income_cents=monthly_income_cents,
        monthly_expenses_cents=monthly_expenses_cents,
    )
    for offset in range(missed_count):
        seq = 2 + offset
        record_payment(
            case=case_in_rep, plan=plan_after_first, debtor=debtor,
            sequence_number=seq, amount_cents=0, status="MISSED",
        )
    plan_after = re_get_plan(case_in_rep["id"], plan_after_first["id"])
    return debtor, case_in_rep, mtr, plan_after


__all__ = [
    "advance_clock_to",
    "create_debtor",
    "create_creditor",
    "create_case",
    "submit_schedule",
    "submit_all_other_schedules",
    "submit_schedule_i",
    "submit_schedule_j",
    "submit_all_schedules_for",
    "run_means_test",
    "file_case",
    "schedule_341",
    "conduct_341",
    "dismiss_case",
    "discharge_case",
    "withdraw_case",
    "re_get_case",
    "file_claim",
    "disallow_claim",
    "re_get_claim",
    "submit_plan",
    "withdraw_plan",
    "confirm_plan",
    "record_payment",
    "re_get_plan",
    "attempt_collection_action",
    "list_collection_actions",
    "setup_draft_case_filing_ready",
    "setup_filed_case",
    "setup_meeting_scheduled_case",
    "setup_meeting_held_case",
    "setup_ch13_plan_proposed",
    "setup_ch13_plan_confirmed",
    "setup_ch13_in_repayment",
    "setup_ch13_plan_fully_paid",
    "setup_ch7_discharged_case",
    "setup_ch13_with_missed_payments",
]
