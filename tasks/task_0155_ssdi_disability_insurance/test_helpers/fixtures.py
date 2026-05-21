"""Composite setup helpers — multi-step preambles tests can reuse.

Most interesting test claims require the system to be in a late state
that takes many API calls to reach. Each fixture composes the lower-
level steps so the test body can focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "When X-User-Role is Claimant, the X-User-ID is the id of the acting
    Claimant; ownership checks on any resource that references a Claimant
    compare the resource's claimant_id to X-User-ID, and a mismatched
    claimant in the URL path also yields ERR_FORBIDDEN."

After a Claimant is created, fixtures MUST use make_claimant_headers(
claimant["id"]) when issuing claimant-scoped calls — never fall back to
the shared TEST_USERS["claimant_headers"] constant for ownership-gated
operations.

CLOCK ANCHORING — PRD §2.10:

    "An admin-only test-driving capability advances the logical clock to
    a supplied to instant; the clock is monotonically non-decreasing and
    never moves backward."

Setup calls use get_success_data (a lenient 2xx validator), so a failed
setup surfaces as 'Setup failed' rather than a confusing test assertion
failure downstream.
"""
from __future__ import annotations

import itertools
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    APPEAL_WINDOW_DAYS,
    EVIDENCE_DATE_FILING_OFFSET_DAYS,
    HEARING_SLOT_MINUTES,
    QC_EARNINGS_THRESHOLD_CENTS_BY_YEAR,
)
from .factories import (
    add_days,
    add_minutes,
    appeal_payload,
    book_hearing_slot_payload,
    clock_advance_payload,
    complete_cdr_payload,
    create_application_payload,
    create_child_auxiliary_payload,
    create_claimant_payload,
    create_determination_payload,
    create_hearing_slot_payload,
    create_listing_match_evidence_payload,
    create_quarter_credit_payload,
    create_rfc_assessment_evidence_payload,
    create_ssi_supplement_payload,
    date_to_iso,
    iso_utc,
    parse_iso,
    patch_ssi_supplement_payload,
    reschedule_hearing_slot_payload,
    terminate_child_auxiliary_payload,
    utcnow,
)
from .test_users import (
    TEST_USERS,
    make_alj_headers,
    make_claimant_headers,
    make_dds_examiner_headers,
    make_platform_admin_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.10
# ===========================================================================
_CLOCK_LOCK = threading.Lock()
_CURRENT_CLOCK: Optional[datetime] = None

# Per-process counter for minting unique opaque ALJ identifiers across
# composite setups. Each composite that books a HearingSlot for the
# default ALJ would otherwise collide with prior tests on the shared
# `alj-0001`, producing ERR_HEARING_SLOT_CONFLICT during setup.
_ALJ_SEQ_LOCK = threading.Lock()
_ALJ_SEQ = itertools.count(1)


def _next_alj_id(prefix: str = "alj-auto") -> str:
    with _ALJ_SEQ_LOCK:
        n = next(_ALJ_SEQ)
    return f"{prefix}-{n:06d}-{uuid.uuid4().hex[:8]}"


def _seed_clock() -> datetime:
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        if _CURRENT_CLOCK is None:
            _CURRENT_CLOCK = utcnow()
        return _CURRENT_CLOCK


def current_clock() -> datetime:
    return _seed_clock()


def current_clock_iso() -> str:
    return iso_utc(current_clock())


def advance_clock_to(
    target_dt: datetime,
    headers: Optional[Dict[str, str]] = None,
) -> str:
    """PRD §2.10: 'advances the logical clock to a supplied to instant;
    the clock is monotonically non-decreasing and never moves backward.'
    """
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        now = _CURRENT_CLOCK if _CURRENT_CLOCK is not None else utcnow()
        if target_dt < now:
            target_dt = now
        target_iso = iso_utc(target_dt)
        resp = api_client.advance_clock(
            clock_advance_payload(target_iso),
            headers or TEST_USERS["platform_admin_headers"],
        )
        get_success_data(resp)
        _CURRENT_CLOCK = target_dt
    return target_iso


def advance_clock_by_seconds(seconds: int) -> str:
    return advance_clock_to(current_clock() + timedelta(seconds=seconds))


def advance_clock_by_minutes(minutes: int) -> str:
    return advance_clock_to(current_clock() + timedelta(minutes=minutes))


def advance_clock_by_hours(hours: float) -> str:
    return advance_clock_to(current_clock() + timedelta(hours=hours))


def advance_clock_by_days(days: int) -> str:
    return advance_clock_to(current_clock() + timedelta(days=days))


def reset_clock_tracker_to(dt: datetime) -> None:
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        _CURRENT_CLOCK = dt


# ===========================================================================
# Claimant primitives — PRD §3.1
# ===========================================================================
def create_claimant(
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    filing_date: Optional[str] = None,
    alleged_onset_date: Optional[str] = None,
    ssn_last4: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a Claimant. By default uses the shared claimant header
    (acceptable for create — the server stamps the new Claimant.id and
    the caller does not need an entity-backed identity for this POST).

    For all downstream ownership-gated calls (submit, appeal, medical-
    evidence, application creation), tests should re-key headers via
    make_claimant_headers(claimant["id"]).
    """
    payload = create_claimant_payload(
        full_name=full_name,
        date_of_birth=date_of_birth,
        filing_date=filing_date,
        alleged_onset_date=alleged_onset_date,
        ssn_last4=ssn_last4,
    )
    resp = api_client.create_claimant(
        payload, headers or TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def get_claimant(claimant_id: str) -> Dict[str, Any]:
    """Read a claimant via PlatformAdmin (opaque role bypasses
    ownership)."""
    resp = api_client.get_claimant(
        claimant_id, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def patch_claimant(claimant_id: str, **fields) -> Dict[str, Any]:
    """Patch a Claimant by minting headers that resolve to this very
    claimant id, per PRD §2.1 ownership rules."""
    from .factories import patch_claimant_payload
    headers = make_claimant_headers(claimant_id)
    resp = api_client.patch_claimant(
        claimant_id, patch_claimant_payload(**fields), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Quarter credits — PRD §3.1
# ===========================================================================
def add_quarter_credit(
    claimant_id: str,
    year: int,
    quarter: int,
    earnings_cents: int,
) -> Dict[str, Any]:
    """Append one QuarterCredit row using owner-headers."""
    headers = make_claimant_headers(claimant_id)
    payload = create_quarter_credit_payload(year, quarter, earnings_cents)
    resp = api_client.create_quarter_credit(claimant_id, payload, headers)
    return get_success_data(resp)


def add_full_qc_year(
    claimant_id: str,
    year: int,
    per_quarter_cents: int = 1_000_000,
) -> List[Dict[str, Any]]:
    """Add four quarters of substantial earnings to credit all 4 QCs for
    a year. Defaults to $10,000 per quarter which exceeds the 2024 QC
    threshold of $1,730.
    """
    rows = []
    for q in (1, 2, 3, 4):
        rows.append(add_quarter_credit(claimant_id, year, q, per_quarter_cents))
    return rows


def seed_qcs_for_insured_status(
    claimant_id: str,
    target_total_qcs: int = 40,
    start_year: int = 2010,
    end_year_inclusive: int = 2023,
) -> List[Dict[str, Any]]:
    """Seed enough credited QCs to satisfy both the fully-insured and
    recent-work tests for a typical age-35 claimant.

    PRD §3.1: per-year QC threshold is $1,730 for 2024 (used here as a
    safe floor — any year between 2010 and 2024 needs only earnings >=
    $1,730 per quarter to credit a QC). We deposit $10,000 per quarter
    which exceeds the threshold every year.
    """
    rows: List[Dict[str, Any]] = []
    qcs_remaining = target_total_qcs
    year = start_year
    while qcs_remaining > 0 and year <= end_year_inclusive:
        # 4 QCs per year max
        for q in (1, 2, 3, 4):
            if qcs_remaining <= 0:
                break
            rows.append(
                add_quarter_credit(claimant_id, year, q, 1_000_000),
            )
            qcs_remaining -= 1
        year += 1
    return rows


# ===========================================================================
# Medical evidence — PRD §3.3
# ===========================================================================
def add_listing_evidence(
    claimant_id: str,
    listing_code: str = "1.15",
    evidence_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit a LISTING_MATCH evidence row as the claimant (owner).
    PRD §3.3 makes the claimant the only POSTer."""
    headers = make_claimant_headers(claimant_id)
    payload = create_listing_match_evidence_payload(
        listing_code=listing_code,
        evidence_date=evidence_date,
    )
    resp = api_client.create_medical_evidence(claimant_id, payload, headers)
    return get_success_data(resp)


def add_rfc_evidence(
    claimant_id: str,
    rfc_exertional_level: str = "SEDENTARY",
    age_category_at_decision: str = "YOUNGER",
    evidence_date: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    headers = make_claimant_headers(claimant_id)
    payload = create_rfc_assessment_evidence_payload(
        rfc_exertional_level=rfc_exertional_level,
        age_category_at_decision=age_category_at_decision,
        evidence_date=evidence_date,
        **overrides,
    )
    resp = api_client.create_medical_evidence(claimant_id, payload, headers)
    return get_success_data(resp)


def accept_evidence(claimant_id: str, evidence_id: str,
                    examiner_headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    """DDS_Examiner accepts evidence. PRD §3.3 SUBMITTED -> ACCEPTED."""
    resp = api_client.accept_medical_evidence(
        claimant_id, evidence_id,
        examiner_headers or TEST_USERS["dds_examiner_headers"],
    )
    return get_success_data(resp)


def reject_evidence(claimant_id: str, evidence_id: str,
                    examiner_headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    resp = api_client.reject_medical_evidence(
        claimant_id, evidence_id,
        examiner_headers or TEST_USERS["dds_examiner_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Application primitives — PRD §3.3, §3.4, §3.6
# ===========================================================================
def create_draft_application(claimant_id: str) -> Dict[str, Any]:
    headers = make_claimant_headers(claimant_id)
    resp = api_client.create_application(
        claimant_id, headers, create_application_payload(),
    )
    return get_success_data(resp)


def submit_application(claimant_id: str, app_id: str) -> Dict[str, Any]:
    headers = make_claimant_headers(claimant_id)
    resp = api_client.submit_application(claimant_id, app_id, headers)
    return get_success_data(resp)


def get_application(claimant_id: str, app_id: str) -> Dict[str, Any]:
    """Read via PlatformAdmin (opaque) to bypass ownership."""
    resp = api_client.get_application(
        claimant_id, app_id, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def issue_determination(
    claimant_id: str,
    app_id: str,
    level: str,
    decision: str,
    *,
    medical_basis: Optional[str] = None,
    established_onset_date: Optional[str] = None,
    rationale: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.4 / §3.6: issue a determination at the given level. The
    caller must supply role-appropriate headers — INITIAL/RECONSIDERATION
    require DDS_Examiner; ALJ requires ALJ; APPEALS_COUNCIL requires
    AppealsCouncil.
    """
    payload = create_determination_payload(
        level=level,
        decision=decision,
        medical_basis=medical_basis,
        established_onset_date=established_onset_date,
        rationale=rationale,
    )
    if headers is None:
        # Sensible role default per level.
        if level == "INITIAL" or level == "RECONSIDERATION":
            headers = TEST_USERS["dds_examiner_headers"]
        elif level == "ALJ":
            headers = TEST_USERS["alj_headers"]
        else:
            headers = TEST_USERS["appeals_council_headers"]
    resp = api_client.create_determination(
        claimant_id, app_id, payload, headers,
    )
    return get_success_data(resp)


def appeal_application(claimant_id: str, app_id: str,
                       target_level: str) -> Dict[str, Any]:
    headers = make_claimant_headers(claimant_id)
    resp = api_client.appeal_application(
        claimant_id, app_id, appeal_payload(target_level), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Hearing slots — PRD §3.7
# ===========================================================================
def create_open_slot(
    alj_id: str,
    start_at_dt: datetime,
    hearing_office: Optional[str] = None,
    duration_minutes: int = HEARING_SLOT_MINUTES,
) -> Dict[str, Any]:
    """Create a single OPEN slot. PRD §3.7: end_at = start_at + 60m."""
    headers = make_alj_headers(alj_id)
    payload = create_hearing_slot_payload(
        alj_id=alj_id,
        start_at=iso_utc(start_at_dt),
        end_at=iso_utc(start_at_dt + timedelta(minutes=duration_minutes)),
        hearing_office=hearing_office,
    )
    resp = api_client.create_hearing_slot(payload, headers)
    return get_success_data(resp)


def book_slot(slot_id: str, alj_id: str, application_id: str) -> Dict[str, Any]:
    headers = make_alj_headers(alj_id)
    resp = api_client.book_hearing_slot(
        slot_id, book_hearing_slot_payload(application_id), headers,
    )
    return get_success_data(resp)


def hold_slot(slot_id: str, alj_id: str) -> Dict[str, Any]:
    headers = make_alj_headers(alj_id)
    resp = api_client.hold_hearing_slot(slot_id, headers)
    return get_success_data(resp)


def no_show_slot(slot_id: str, alj_id: str) -> Dict[str, Any]:
    headers = make_alj_headers(alj_id)
    resp = api_client.no_show_hearing_slot(slot_id, headers)
    return get_success_data(resp)


def reschedule_slot(slot_id: str, alj_id: str,
                    new_slot_id: str) -> Dict[str, Any]:
    headers = make_alj_headers(alj_id)
    resp = api_client.reschedule_hearing_slot(
        slot_id, reschedule_hearing_slot_payload(new_slot_id), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Child auxiliaries — PRD §3.5
# ===========================================================================
def create_child_aux(
    application_id: str,
    child_name: Optional[str] = None,
    child_date_of_birth: Optional[str] = None,
    child_relationship: str = "BIOLOGICAL",
    is_full_time_student: Optional[bool] = None,
    is_disabled_before_22: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a ChildAuxiliary. PRD §3.5 says a Claimant or DDS_Examiner
    can post this; we default to DDS_Examiner since it's opaque.
    """
    payload = create_child_auxiliary_payload(
        application_id=application_id,
        child_name=child_name,
        child_date_of_birth=child_date_of_birth,
        child_relationship=child_relationship,
        is_full_time_student=is_full_time_student,
        is_disabled_before_22=is_disabled_before_22,
    )
    resp = api_client.create_child_auxiliary(
        payload, headers or TEST_USERS["dds_examiner_headers"],
    )
    return get_success_data(resp)


def entitle_child(child_id: str) -> Dict[str, Any]:
    resp = api_client.entitle_child_auxiliary(
        child_id, TEST_USERS["dds_examiner_headers"],
    )
    return get_success_data(resp)


def terminate_child(child_id: str, reason: str) -> Dict[str, Any]:
    resp = api_client.terminate_child_auxiliary(
        child_id,
        terminate_child_auxiliary_payload(reason),
        TEST_USERS["dds_examiner_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# SSI — PRD §3.5
# ===========================================================================
def create_ssi_supplement(
    claimant_id: str,
    countable_income_cents: int = 0,
    countable_resources_cents: int = 0,
    living_arrangement: str = "OWN_HOUSEHOLD",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = create_ssi_supplement_payload(
        claimant_id=claimant_id,
        countable_income_cents=countable_income_cents,
        countable_resources_cents=countable_resources_cents,
        living_arrangement=living_arrangement,
    )
    resp = api_client.create_ssi_supplement(
        payload, headers or TEST_USERS["dds_examiner_headers"],
    )
    return get_success_data(resp)


def activate_ssi(supplement_id: str) -> Dict[str, Any]:
    resp = api_client.activate_ssi_supplement(
        supplement_id, TEST_USERS["dds_examiner_headers"],
    )
    return get_success_data(resp)


def patch_ssi(
    supplement_id: str,
    countable_income_cents: Optional[int] = None,
    countable_resources_cents: Optional[int] = None,
    living_arrangement: Optional[str] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    payload = patch_ssi_supplement_payload(
        countable_income_cents=countable_income_cents,
        countable_resources_cents=countable_resources_cents,
        living_arrangement=living_arrangement,
        version=version,
    )
    resp = api_client.patch_ssi_supplement(
        supplement_id, payload, TEST_USERS["dds_examiner_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# CDR reviews — PRD §3.8
# ===========================================================================
def schedule_cdr(cdr_id: str) -> Dict[str, Any]:
    resp = api_client.schedule_cdr_review(
        cdr_id, TEST_USERS["cdr_reviewer_headers"],
    )
    return get_success_data(resp)


def complete_cdr(cdr_id: str, medical_improvement_found: bool,
                 working_at_sga: bool) -> Dict[str, Any]:
    resp = api_client.complete_cdr_review(
        cdr_id,
        complete_cdr_payload(medical_improvement_found, working_at_sga),
        TEST_USERS["cdr_reviewer_headers"],
    )
    return get_success_data(resp)


def list_cdr_reviews(status: Optional[str] = None,
                     due_before: Optional[str] = None,
                     ) -> List[Dict[str, Any]]:
    """Iterate through all pages so newly-created CDRs are visible even when
    >10 rows already exist (PRD §2.3: default limit=10, max=100)."""
    rows: List[Dict[str, Any]] = []
    offset = 0
    page_size = 100
    while True:
        params: Dict[str, Any] = {"limit": page_size, "offset": offset}
        if status is not None:
            params["status"] = status
        if due_before is not None:
            params["due_before"] = due_before
        resp = api_client.list_cdr_reviews(
            TEST_USERS["cdr_reviewer_headers"], params=params,
        )
        body = resp.json()
        page = list(body.get("data") or [])
        rows.extend(page)
        meta = body.get("meta") or {}
        has_more = meta.get("has_more")
        if has_more is False or len(page) < page_size:
            break
        offset += len(page)
        # Safety break in case the server doesn't report has_more correctly.
        if offset > 10_000:
            break
    return rows


# ===========================================================================
# Composite setups — multi-step preambles
# ===========================================================================
def setup_insured_claimant(
    *,
    age_at_aod_years: int = 35,
    filing_date: Optional[str] = None,
    alleged_onset_date: Optional[str] = None,
    seed_qcs: bool = True,
    total_qcs: int = 40,
) -> Dict[str, Any]:
    """Create a Claimant + seed enough QCs to clear insured-status tests.

    Defaults:
      - age 35 at AOD (so qc_required=20, qc_recent_required=20)
      - AOD = today - 30d, filing_date = today
      - Seeds 40 credited QCs in years 2010..2023 (all within the
        40-quarter window ending at AOD for an AOD in early 2024+)
    """
    today = utcnow().date()
    if alleged_onset_date is None:
        alleged_onset_date = date_to_iso(today - timedelta(days=30))
    if filing_date is None:
        filing_date = date_to_iso(today)
    aod_date = date.fromisoformat(alleged_onset_date)
    dob = date(aod_date.year - age_at_aod_years, aod_date.month, aod_date.day)
    claimant = create_claimant(
        date_of_birth=date_to_iso(dob),
        filing_date=filing_date,
        alleged_onset_date=alleged_onset_date,
    )
    if seed_qcs:
        seed_qcs_for_insured_status(
            claimant["id"],
            target_total_qcs=total_qcs,
            start_year=max(1978, aod_date.year - 14),
            end_year_inclusive=max(1978, aod_date.year - 1),
        )
        claimant = get_claimant(claimant["id"])
    return claimant


def setup_application_at_initial_review(
    *,
    age_at_aod_years: int = 35,
    filing_date: Optional[str] = None,
    alleged_onset_date: Optional[str] = None,
    listing_code: str = "1.15",
    total_qcs: int = 40,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Returns (claimant, application_after_submit, accepted_evidence)
    with Application in INITIAL_REVIEW state, ready for an INITIAL
    determination.
    """
    claimant = setup_insured_claimant(
        age_at_aod_years=age_at_aod_years,
        filing_date=filing_date,
        alleged_onset_date=alleged_onset_date,
        seed_qcs=True,
        total_qcs=total_qcs,
    )
    # Submit one LISTING_MATCH evidence and accept it.
    evidence = add_listing_evidence(
        claimant["id"],
        listing_code=listing_code,
        evidence_date=claimant["alleged_onset_date"],
    )
    evidence = accept_evidence(claimant["id"], evidence["id"])
    application = create_draft_application(claimant["id"])
    application = submit_application(claimant["id"], application["id"])
    return claimant, application, evidence


def setup_application_approved_at_initial(
    *,
    age_at_aod_years: int = 35,
    filing_date: Optional[str] = None,
    alleged_onset_date: Optional[str] = None,
    listing_code: str = "1.15",
    established_onset_date: Optional[str] = None,
    examiner_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Returns (claimant, application_after_initial_approval) where the
    application is APPROVED via INITIAL ALLOW with medical_basis=
    MEETS_LISTING.
    """
    claimant, application, _ = setup_application_at_initial_review(
        age_at_aod_years=age_at_aod_years,
        filing_date=filing_date,
        alleged_onset_date=alleged_onset_date,
        listing_code=listing_code,
    )
    if established_onset_date is None:
        established_onset_date = claimant["alleged_onset_date"]
    issue_determination(
        claimant["id"], application["id"],
        level="INITIAL", decision="ALLOW",
        medical_basis="MEETS_LISTING",
        established_onset_date=established_onset_date,
        headers=examiner_headers or TEST_USERS["dds_examiner_headers"],
    )
    application = get_application(claimant["id"], application["id"])
    return claimant, application


def setup_application_initial_denied(
    *,
    age_at_aod_years: int = 35,
    examiner_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Returns (claimant, application_at_initial_denied)."""
    claimant, application, _ = setup_application_at_initial_review(
        age_at_aod_years=age_at_aod_years,
    )
    issue_determination(
        claimant["id"], application["id"],
        level="INITIAL", decision="DENY",
        medical_basis="NOT_DISABLED",
        headers=examiner_headers or TEST_USERS["dds_examiner_headers"],
    )
    application = get_application(claimant["id"], application["id"])
    return claimant, application


def setup_application_at_reconsideration(
    *, examiner_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Returns (claimant, application_in_reconsideration_state) — denied
    at INITIAL, then appealed to RECONSIDERATION."""
    claimant, application = setup_application_initial_denied(
        examiner_headers=examiner_headers,
    )
    application = appeal_application(
        claimant["id"], application["id"], target_level="RECONSIDERATION",
    )
    return claimant, application


def setup_application_at_alj_pending(
    *,
    initial_examiner_headers: Optional[Dict[str, str]] = None,
    recon_examiner_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Walks an application all the way to ALJ_PENDING via two denials
    and two appeals.
    """
    claimant, application = setup_application_at_reconsideration(
        examiner_headers=initial_examiner_headers,
    )
    # Deny at reconsideration with a DIFFERENT examiner (SoD).
    issue_determination(
        claimant["id"], application["id"],
        level="RECONSIDERATION", decision="DENY",
        medical_basis="NOT_DISABLED",
        headers=recon_examiner_headers or TEST_USERS["dds_examiner_2_headers"],
    )
    application = appeal_application(
        claimant["id"], application["id"], target_level="ALJ",
    )
    return claimant, application


def setup_application_at_appeals_council(
    *,
    alj_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walks an application to APPEALS_COUNCIL via ALJ_DENIED → appeal.
    Returns (claimant, application, held_slot).
    """
    if alj_id is None:
        alj_id = _next_alj_id("alj-ac")
    claimant, application = setup_application_at_alj_pending()
    # Create a slot in the future, advance time, hold it, then DENY at ALJ.
    slot_start = current_clock() + timedelta(hours=1)
    slot = create_open_slot(alj_id=alj_id, start_at_dt=slot_start)
    slot = book_slot(slot["id"], alj_id, application["id"])
    advance_clock_to(slot_start + timedelta(minutes=1))
    slot = hold_slot(slot["id"], alj_id)
    issue_determination(
        claimant["id"], application["id"],
        level="ALJ", decision="DENY",
        medical_basis="NOT_DISABLED",
        headers=make_alj_headers(alj_id),
    )
    application = appeal_application(
        claimant["id"], application["id"], target_level="APPEALS_COUNCIL",
    )
    return claimant, application, slot


def setup_held_hearing_for_alj_pending(
    *, alj_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Returns (claimant, application_in_ALJ_PENDING_with_HELD_slot,
    held_slot). Time has been advanced past slot start_at.
    """
    if alj_id is None:
        alj_id = _next_alj_id("alj-held")
    claimant, application = setup_application_at_alj_pending()
    slot_start = current_clock() + timedelta(hours=1)
    slot = create_open_slot(alj_id=alj_id, start_at_dt=slot_start)
    slot = book_slot(slot["id"], alj_id, application["id"])
    advance_clock_to(slot_start + timedelta(minutes=1))
    slot = hold_slot(slot["id"], alj_id)
    application = get_application(claimant["id"], application["id"])
    return claimant, application, slot


def setup_alj_approved_application(
    *, alj_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Walks an application all the way to ALJ_APPROVED (FINAL variant
    of pia/back_pay).
    """
    if alj_id is None:
        alj_id = _next_alj_id("alj-app")
    claimant, application, slot = setup_held_hearing_for_alj_pending(
        alj_id=alj_id,
    )
    issue_determination(
        claimant["id"], application["id"],
        level="ALJ", decision="ALLOW",
        medical_basis="MEETS_LISTING",
        established_onset_date=claimant["alleged_onset_date"],
        headers=make_alj_headers(alj_id),
    )
    application = get_application(claimant["id"], application["id"])
    return claimant, application


# ---------------------------------------------------------------------------
# Targeted scenarios for difficulty-design coverage
# ---------------------------------------------------------------------------
def setup_claimant_with_qcs_for_recent_window(
    *,
    qc_count_in_recent_window: int,
    aod: date,
    dob: date,
) -> Dict[str, Any]:
    """For the QC recent-window boundary test (instance
    qc_recent_window_boundary_on_submit). Seeds exactly
    qc_count_in_recent_window credited QCs within the 40-quarter window
    ending at AOD, plus 40+ overall lifetime QCs so the fully-insured
    test is also satisfied.

    Strategy: deposit each lifetime QC outside the 40-quarter window in
    years far before AOD; deposit the recent-window QCs in years
    immediately before AOD.
    """
    claimant = create_claimant(
        date_of_birth=date_to_iso(dob),
        filing_date=date_to_iso(aod + timedelta(days=30)),
        alleged_onset_date=date_to_iso(aod),
    )
    # Recent QCs (within 40 quarters before AOD) — years aod.year-1 backwards.
    # 40 quarters = 10 years.
    recent_seeded = 0
    year = aod.year - 1
    while recent_seeded < qc_count_in_recent_window:
        for q in (1, 2, 3, 4):
            if recent_seeded >= qc_count_in_recent_window:
                break
            add_quarter_credit(claimant["id"], year, q, 1_000_000)
            recent_seeded += 1
        year -= 1
    # Older QCs to clear the fully-insured 40-QC lifetime test — far
    # outside the 40-quarter window.
    older_year = max(1978, aod.year - 30)
    older_needed = max(0, 40 - qc_count_in_recent_window)
    seeded = 0
    while seeded < older_needed and older_year < aod.year - 12:
        for q in (1, 2, 3, 4):
            if seeded >= older_needed:
                break
            add_quarter_credit(claimant["id"], older_year, q, 1_000_000)
            seeded += 1
        older_year += 1
    return get_claimant(claimant["id"])


def setup_two_open_slots_same_alj(
    *,
    alj_id: Optional[str] = None,
    first_start_offset_hours: int = 1,
    second_start_offset_hours: int = 3,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Returns (slot1, slot2) — both OPEN, owned by the same ALJ, with
    distinct non-overlapping time windows.
    """
    if alj_id is None:
        alj_id = _next_alj_id("alj-two")
    base = current_clock()
    slot1 = create_open_slot(
        alj_id=alj_id,
        start_at_dt=base + timedelta(hours=first_start_offset_hours),
    )
    slot2 = create_open_slot(
        alj_id=alj_id,
        start_at_dt=base + timedelta(hours=second_start_offset_hours),
    )
    return slot1, slot2


def setup_application_with_pending_cdr(
    *,
    listing_code: str = "1.15",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Set up an APPROVED application and locate its auto-created PENDING
    CDRReview. Returns (claimant, application, cdr_review).
    """
    claimant, application = setup_application_approved_at_initial(
        listing_code=listing_code,
    )
    # The PRD §3.4 step 11 says approval auto-creates one CDRReview row.
    # Find it by listing as PlatformAdmin.
    cdrs = list_cdr_reviews()
    cdr = None
    for c in cdrs:
        if c.get("application_id") == application["id"]:
            cdr = c
            break
    assert cdr is not None, (
        f"Approval should have auto-created a CDRReview for application "
        f"{application['id']}; none found in list (got {len(cdrs)} CDRs)"
    )
    return claimant, application, cdr


def setup_two_distinct_examiners() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Two DDS_Examiner headers with distinct opaque ids — for SoD tests
    and for any setup that needs the reconsideration examiner to differ
    from the initial examiner.
    """
    return (TEST_USERS["dds_examiner_headers"],
            TEST_USERS["dds_examiner_2_headers"])


# ===========================================================================
# Listing endpoints
# ===========================================================================
def list_child_auxiliaries_for_application(
    application_id: str,
) -> List[Dict[str, Any]]:
    resp = api_client.list_child_auxiliaries(
        TEST_USERS["dds_examiner_headers"],
        params={"application_id": application_id},
    )
    body = resp.json()
    return list(body.get("data") or [])


def list_determinations(claimant_id: str, app_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_determinations(
        claimant_id, app_id, TEST_USERS["platform_admin_headers"],
    )
    body = resp.json()
    return list(body.get("data") or [])


__all__ = [
    # Clock
    "current_clock", "current_clock_iso",
    "advance_clock_to",
    "advance_clock_by_seconds", "advance_clock_by_minutes",
    "advance_clock_by_hours", "advance_clock_by_days",
    "reset_clock_tracker_to",
    # Claimant
    "create_claimant", "get_claimant", "patch_claimant",
    # QC
    "add_quarter_credit", "add_full_qc_year",
    "seed_qcs_for_insured_status",
    # Evidence
    "add_listing_evidence", "add_rfc_evidence",
    "accept_evidence", "reject_evidence",
    # Application
    "create_draft_application", "submit_application",
    "get_application", "issue_determination", "appeal_application",
    # Slot
    "create_open_slot", "book_slot", "hold_slot",
    "no_show_slot", "reschedule_slot",
    # Child
    "create_child_aux", "entitle_child", "terminate_child",
    # SSI
    "create_ssi_supplement", "activate_ssi", "patch_ssi",
    # CDR
    "schedule_cdr", "complete_cdr", "list_cdr_reviews",
    # Composite
    "setup_insured_claimant",
    "setup_application_at_initial_review",
    "setup_application_approved_at_initial",
    "setup_application_initial_denied",
    "setup_application_at_reconsideration",
    "setup_application_at_alj_pending",
    "setup_application_at_appeals_council",
    "setup_held_hearing_for_alj_pending",
    "setup_alj_approved_application",
    "setup_claimant_with_qcs_for_recent_window",
    "setup_two_open_slots_same_alj",
    "setup_application_with_pending_cdr",
    "setup_two_distinct_examiners",
    # List helpers
    "list_child_auxiliaries_for_application",
    "list_determinations",
]
