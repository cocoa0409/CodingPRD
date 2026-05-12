"""Composite setup helpers for the Carbon Emission Trading test suite.

The PRD's lifecycle has many interlocking phases — Enterprise (PENDING→OPEN
→CLOSED), AllocationCycle (DRAFT→PUBLISHED→OBJECTION_OPEN→FINALIZED→
COMPLIANCE_OPEN→SETTLED→CLOSED), Allocation (PROPOSED→PUBLISHED→
[OBJECTED→REVISED|PUBLISHED]→FINALIZED), EmissionReport (DRAFT→SUBMITTED→
UNDER_VERIFICATION→VERIFIED→[DISPUTED→VERIFIED]→FINALIZED), VerificationAssignment
(ASSIGNED→ON_SITE_DONE→REPORT_ISSUED→[DISPUTED→RESOLVED]), ComplianceDeclaration
(DRAFT→SUBMITTED→[COMPLIANT|NON_COMPLIANT→PENALIZED]→FINALIZED), PenaltyOrder
(UNPAID→[PAID|OVERDUE]) — and most interesting tests need the system in a
non-initial state. This module captures the common multi-call setup
sequences once.

Identity threading (PRD §2.1): Enterprise is the entity-backed role
(X-User-ID == Enterprise.id). Whenever a fixture creates an Enterprise and
the downstream call is enterprise-scoped (POST emission-reports, lines,
documents, submit, dispute, trading-orders, compliance-declarations,
pay penalty), the helper must thread the actual Enterprise.id through
make_enterprise_headers; never fall back to the shared TEST_USERS
["enterprise_headers"] for ownership-gated flows.

For VerifierAgency: identity is opaque but compared to
VerificationAssignment.agency_id on complete-onsite/issue-report. Pass
the same opaque id used at assign-verifier time through
make_verifier_agency_headers().

Setup calls use get_success_data (lenient validator) so that broken
preconditions surface as obvious "Setup failed" mismatches rather than
confusing assertion errors.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_emission_line_payload,
    assign_verifier_payload,
    complete_onsite_payload,
    create_allocation_cycle_payload,
    create_allocation_payload,
    create_compliance_declaration_payload,
    create_emission_report_payload,
    create_enterprise_payload,
    create_trading_order_payload,
    dispute_emission_report_payload,
    emit_event_payload,
    file_objection_payload,
    line_adjustment,
    reject_emission_report_payload,
    resolve_dispute_payload,
    submit_compliance_declaration_payload,
    unique_agency_id,
    unique_cycle_year,
    upload_supporting_document_payload,
    uphold_objection_payload,
)
from .test_users import (
    TEST_USERS,
    make_enterprise_headers,
    make_verifier_agency_headers,
)


# ===========================================================================
# Time helpers (PRD §2.4 — ISO 8601 UTC with three fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def add_seconds(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(seconds=n))


def add_minutes(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(minutes=n))


def add_hours(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(hours=n))


def add_days(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(days=n))


# ===========================================================================
# Test-driver wrappers (PRD §2.10)
# ===========================================================================
# Module-level mirror of the most-recent clock_advance target. The simulated
# clock is shared across all tests in a session, so we can't go backward.
_last_known_clock_iso: Optional[str] = None


def advance_clock(target_timestamp: str) -> Dict[str, Any]:
    """POST /_clock/advance with Regulator headers.
    PRD §2.10: 'A clock-advance capability sets the server's now() to a
    supplied target_timestamp and responds with the new clock value; it
    does not implicitly run the sweep.'

    Forward-only: if the requested time is earlier than the last known
    clock, the helper silently NO-OPS.
    """
    global _last_known_clock_iso
    if (_last_known_clock_iso is not None
            and parse_iso(target_timestamp) <= parse_iso(_last_known_clock_iso)):
        return {}
    res = api_client.advance_clock(
        target_timestamp, TEST_USERS["regulator_headers"]
    )
    data = get_success_data(res)
    _last_known_clock_iso = target_timestamp
    return data


def current_clock_iso() -> str:
    """Return the most recent clock instant we've advanced to (or a sane
    floor if nothing has been advanced yet)."""
    return _last_known_clock_iso or "2030-01-01T00:00:00.000Z"


def advance_clock_relative(*, seconds: float = 0, minutes: float = 0,
                           hours: float = 0, days: float = 0) -> str:
    """Advance the simulated clock to (last_known + delta). Returns the new
    clock instant. Always moves forward."""
    cur = parse_iso(current_clock_iso())
    new_iso = iso_z(cur + timedelta(
        seconds=seconds, minutes=minutes, hours=hours, days=days,
    ))
    advance_clock(new_iso)
    return new_iso


def run_sweep() -> Dict[str, Any]:
    """POST /_sweep/run with Regulator headers.
    PRD §2.10: 'A sweep capability scans for past-due penalty orders and
    other deadline-driven transitions and applies them, returning a
    swept_count.'"""
    return get_success_data(
        api_client.run_sweep(TEST_USERS["regulator_headers"])
    )


def emit_event(*, external_system: str, event_type: str,
               payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST /_events/emit with Regulator headers."""
    body = emit_event_payload(
        external_system=external_system,
        event_type=event_type,
        payload=payload,
    )
    return get_success_data(
        api_client.emit_event(body, TEST_USERS["regulator_headers"])
    )


# ===========================================================================
# Tier 1 — single-entity creation
# ===========================================================================
def create_enterprise(
    *,
    legal_name: Optional[str] = None,
    jurisdiction_code: str = "JD_ALPHA",
    industry_code: str = "POWER",
    contact_email: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /enterprises as Regulator (PRD §4)."""
    payload = create_enterprise_payload(
        legal_name=legal_name,
        jurisdiction_code=jurisdiction_code,
        industry_code=industry_code,
        contact_email=contact_email,
    )
    res = api_client.create_enterprise(
        payload, TEST_USERS["regulator_headers"]
    )
    return get_success_data(res)


def get_enterprise(enterprise_id: str) -> Dict[str, Any]:
    """GET /enterprises/{id} as Regulator."""
    res = api_client.get_enterprise(
        enterprise_id, TEST_USERS["regulator_headers"]
    )
    return get_success_data(res)


def create_allocation_cycle(
    *,
    cycle_year: Optional[int] = None,
    free_paid_ratio: float = 0.80,
    ccer_cap_pct: float = 0.05,
    objection_deadline: Optional[str] = None,
    compliance_deadline: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /allocation-cycles as Regulator. Defaults set the windows far
    in the future relative to the simulated clock so window checks pass."""
    base = parse_iso(current_clock_iso())
    od = objection_deadline or iso_z(base + timedelta(days=180))
    cd = compliance_deadline or iso_z(base + timedelta(days=365))
    payload = create_allocation_cycle_payload(
        cycle_year=cycle_year,
        free_paid_ratio=free_paid_ratio,
        ccer_cap_pct=ccer_cap_pct,
        objection_deadline=od,
        compliance_deadline=cd,
    )
    res = api_client.create_allocation_cycle(
        payload, TEST_USERS["regulator_headers"]
    )
    return get_success_data(res)


def propose_allocation(
    *,
    cycle_id: str,
    enterprise_id: str,
    method: str = "INDUSTRY_BENCHMARK",
    activity_volume: Optional[float] = 1000.00,
    benchmark_factor: Optional[float] = 1.50,
    historical_baseline: Optional[float] = None,
) -> Dict[str, Any]:
    """POST /allocation-cycles/{id}/allocations as Regulator."""
    payload = create_allocation_payload(
        enterprise_id=enterprise_id,
        method=method,
        activity_volume=(activity_volume if method == "INDUSTRY_BENCHMARK"
                         else None),
        benchmark_factor=(benchmark_factor if method == "INDUSTRY_BENCHMARK"
                          else None),
        historical_baseline=(historical_baseline
                             if method == "HISTORICAL_EMISSION" else None),
    )
    res = api_client.create_allocation(
        cycle_id, payload, TEST_USERS["regulator_headers"]
    )
    return get_success_data(res)


def publish_cycle(cycle_id: str) -> Dict[str, Any]:
    res = api_client.publish_allocation_cycle(
        cycle_id, TEST_USERS["regulator_headers"]
    )
    return get_success_data(res)


def finalize_cycle(cycle_id: str) -> Dict[str, Any]:
    res = api_client.finalize_allocation_cycle(
        cycle_id, TEST_USERS["regulator_headers"]
    )
    return get_success_data(res)


def settle_cycle(cycle_id: str) -> Dict[str, Any]:
    res = api_client.settle_allocation_cycle(
        cycle_id, TEST_USERS["regulator_headers"]
    )
    return get_success_data(res)


def close_cycle(cycle_id: str) -> Dict[str, Any]:
    res = api_client.close_allocation_cycle(
        cycle_id, TEST_USERS["regulator_headers"]
    )
    return get_success_data(res)


def get_cycle(cycle_id: str) -> Dict[str, Any]:
    res = api_client.get_allocation_cycle(
        cycle_id, TEST_USERS["regulator_headers"]
    )
    return get_success_data(res)


# ===========================================================================
# Tier 2 — Allocation cycle scenarios
# ===========================================================================
def setup_cycle_with_one_proposed_allocation(
    *,
    free_paid_ratio: float = 0.80,
    ccer_cap_pct: float = 0.05,
    method: str = "INDUSTRY_BENCHMARK",
    activity_volume: float = 1000.00,
    benchmark_factor: float = 1.50,
    historical_baseline: Optional[float] = None,
    objection_deadline: Optional[str] = None,
    compliance_deadline: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create one Enterprise + one DRAFT cycle + one PROPOSED allocation.
    Returns (enterprise, cycle, allocation)."""
    ent = create_enterprise()
    cyc = create_allocation_cycle(
        free_paid_ratio=free_paid_ratio,
        ccer_cap_pct=ccer_cap_pct,
        objection_deadline=objection_deadline,
        compliance_deadline=compliance_deadline,
    )
    alloc = propose_allocation(
        cycle_id=cyc["id"],
        enterprise_id=ent["id"],
        method=method,
        activity_volume=activity_volume,
        benchmark_factor=benchmark_factor,
        historical_baseline=historical_baseline,
    )
    return ent, cyc, alloc


def setup_published_cycle(
    *,
    free_paid_ratio: float = 0.80,
    ccer_cap_pct: float = 0.05,
    method: str = "INDUSTRY_BENCHMARK",
    activity_volume: float = 1000.00,
    benchmark_factor: float = 1.50,
    historical_baseline: Optional[float] = None,
    objection_deadline: Optional[str] = None,
    compliance_deadline: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Cycle through DRAFT → PUBLISHED (auto → OBJECTION_OPEN). Returns
    (enterprise, cycle_after_publish, published_allocation)."""
    ent, cyc, _alloc = setup_cycle_with_one_proposed_allocation(
        free_paid_ratio=free_paid_ratio,
        ccer_cap_pct=ccer_cap_pct,
        method=method,
        activity_volume=activity_volume,
        benchmark_factor=benchmark_factor,
        historical_baseline=historical_baseline,
        objection_deadline=objection_deadline,
        compliance_deadline=compliance_deadline,
    )
    cyc2 = publish_cycle(cyc["id"])
    # Re-fetch allocation by enterprise
    alloc_after = _refetch_allocation_by_enterprise(cyc2["id"], ent["id"])
    return ent, cyc2, alloc_after


def _refetch_allocation_by_enterprise(
    cycle_id: str, enterprise_id: str
) -> Dict[str, Any]:
    """Re-read the cycle and return the allocation belonging to the given
    enterprise. The cycle GET is expected to expose its allocations under a
    discoverable shape; we try both common conventions and fall back."""
    cyc = get_cycle(cycle_id)
    allocations = cyc.get("allocations") or []
    for a in allocations:
        if a.get("enterprise_id") == enterprise_id:
            return a
    # Fallback: callers pass allocation id explicitly when discovery fails.
    return {}


def setup_finalized_cycle(
    *,
    free_paid_ratio: float = 0.80,
    ccer_cap_pct: float = 0.05,
    method: str = "INDUSTRY_BENCHMARK",
    activity_volume: float = 1000.00,
    benchmark_factor: float = 1.50,
    historical_baseline: Optional[float] = None,
    objection_deadline: Optional[str] = None,
    compliance_deadline: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Cycle through DRAFT → PUBLISHED → OBJECTION_OPEN → FINALIZED.
    Advances the simulated clock past objection_deadline before finalize.
    Returns (enterprise, cycle_after_finalize, allocation_after_finalize).
    """
    base_clock = parse_iso(current_clock_iso())
    od = objection_deadline or iso_z(base_clock + timedelta(days=180))
    cd = compliance_deadline or iso_z(base_clock + timedelta(days=365))
    ent, cyc, alloc = setup_published_cycle(
        free_paid_ratio=free_paid_ratio,
        ccer_cap_pct=ccer_cap_pct,
        method=method,
        activity_volume=activity_volume,
        benchmark_factor=benchmark_factor,
        historical_baseline=historical_baseline,
        objection_deadline=od,
        compliance_deadline=cd,
    )
    # Advance past objection deadline
    advance_clock(add_seconds(od, 1))
    cyc2 = finalize_cycle(cyc["id"])
    alloc2 = _refetch_allocation_by_enterprise(cyc2["id"], ent["id"])
    return ent, cyc2, alloc2


# ===========================================================================
# Tier 2b — Multi-enterprise cycle scenarios
# ===========================================================================
def setup_published_cycle_multi(
    *,
    enterprises_specs: List[Dict[str, Any]],
    free_paid_ratio: float = 0.80,
    ccer_cap_pct: float = 0.05,
    objection_deadline: Optional[str] = None,
    compliance_deadline: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]],
           List[Dict[str, Any]]]:
    """Create one cycle plus N enterprises and propose allocations
    according to enterprises_specs (each entry has enterprise overrides
    plus 'method'/'activity_volume'/'benchmark_factor'/'historical_baseline').
    Returns (cycle_after_publish, enterprises, allocations_after_publish)."""
    cyc = create_allocation_cycle(
        free_paid_ratio=free_paid_ratio,
        ccer_cap_pct=ccer_cap_pct,
        objection_deadline=objection_deadline,
        compliance_deadline=compliance_deadline,
    )
    enterprises: List[Dict[str, Any]] = []
    for spec in enterprises_specs:
        ent_kwargs = {
            k: v for k, v in spec.items()
            if k in {"legal_name", "jurisdiction_code",
                     "industry_code", "contact_email"}
        }
        ent = create_enterprise(**ent_kwargs)
        enterprises.append(ent)
        propose_allocation(
            cycle_id=cyc["id"],
            enterprise_id=ent["id"],
            method=spec.get("method", "INDUSTRY_BENCHMARK"),
            activity_volume=spec.get("activity_volume"),
            benchmark_factor=spec.get("benchmark_factor"),
            historical_baseline=spec.get("historical_baseline"),
        )
    cyc2 = publish_cycle(cyc["id"])
    allocations = []
    for ent in enterprises:
        allocations.append(
            _refetch_allocation_by_enterprise(cyc2["id"], ent["id"])
        )
    return cyc2, enterprises, allocations


# ===========================================================================
# Tier 3 — Open compliance window (post-finalize)
# ===========================================================================
def setup_compliance_open_cycle(
    *,
    free_paid_ratio: float = 0.80,
    ccer_cap_pct: float = 0.05,
    method: str = "INDUSTRY_BENCHMARK",
    activity_volume: float = 1000.00,
    benchmark_factor: float = 1.50,
    historical_baseline: Optional[float] = None,
    objection_deadline: Optional[str] = None,
    compliance_deadline: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive a cycle through to COMPLIANCE_OPEN by finalizing it and then
    creating an EmissionReport (which triggers the auto-transition per
    PRD §3.2). Returns (enterprise, cycle, allocation).
    """
    ent, cyc, alloc = setup_finalized_cycle(
        free_paid_ratio=free_paid_ratio,
        ccer_cap_pct=ccer_cap_pct,
        method=method,
        activity_volume=activity_volume,
        benchmark_factor=benchmark_factor,
        historical_baseline=historical_baseline,
        objection_deadline=objection_deadline,
        compliance_deadline=compliance_deadline,
    )
    # PRD §3.2: 'After finalization, the cycle auto-transitions to
    # COMPLIANCE_OPEN once emission reporting begins.' The implementation
    # auto-transitions to COMPLIANCE_OPEN at finalize time (the finalize
    # response status reflects this), so no extra trigger is needed here —
    # creating an extra "discard" draft would block subsequent draft
    # creates per PRD §3.3 (only one DRAFT report per cycle_year is
    # outstanding while the previous version is still DRAFT).
    cyc2 = get_cycle(cyc["id"])
    return ent, cyc2, alloc


# ===========================================================================
# Tier 4 — EmissionReport lifecycle
# ===========================================================================
def create_draft_report(
    *,
    enterprise_id: str,
    cycle_year: int,
) -> Dict[str, Any]:
    """POST /enterprises/{id}/emission-reports as the owning Enterprise."""
    headers = make_enterprise_headers(enterprise_id)
    payload = create_emission_report_payload(cycle_year=cycle_year)
    res = api_client.create_emission_report(enterprise_id, payload, headers)
    return get_success_data(res)


def add_line(
    *,
    report_id: str,
    enterprise_id: str,
    source_category: str,
    activity_data: float,
    emission_factor: float,
    supporting_document_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /emission-reports/{id}/lines as the owning Enterprise."""
    headers = make_enterprise_headers(enterprise_id)
    payload = add_emission_line_payload(
        source_category=source_category,
        activity_data=activity_data,
        emission_factor=emission_factor,
        supporting_document_id=supporting_document_id,
    )
    res = api_client.add_emission_line(report_id, payload, headers)
    return get_success_data(res)


def upload_document(
    *,
    report_id: str,
    enterprise_id: str,
    document_type: str = "FUEL_INVOICE",
    file_uri: str = "s3://bucket/doc.pdf",
) -> Dict[str, Any]:
    """POST /emission-reports/{id}/documents as the owning Enterprise."""
    headers = make_enterprise_headers(enterprise_id)
    payload = upload_supporting_document_payload(
        document_type=document_type,
        file_uri=file_uri,
    )
    res = api_client.upload_supporting_document(report_id, payload, headers)
    return get_success_data(res)


def submit_report(*, report_id: str, enterprise_id: str) -> Dict[str, Any]:
    """POST /emission-reports/{id}/submit as the owning Enterprise."""
    headers = make_enterprise_headers(enterprise_id)
    res = api_client.submit_emission_report(report_id, headers)
    return get_success_data(res)


def assign_verifier(
    *,
    report_id: str,
    agency_id: str,
    scheduled_visit_at: str,
) -> Dict[str, Any]:
    """POST /emission-reports/{id}/assign-verifier as Regulator."""
    payload = assign_verifier_payload(
        agency_id=agency_id,
        scheduled_visit_at=scheduled_visit_at,
    )
    res = api_client.assign_verifier(
        report_id, payload, TEST_USERS["regulator_headers"]
    )
    return get_success_data(res)


def complete_onsite(
    *,
    assignment_id: str,
    agency_id: str,
    line_adjustments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """POST /verification-assignments/{id}/complete-onsite as the assigned
    VerifierAgency."""
    headers = make_verifier_agency_headers(agency_id)
    payload = complete_onsite_payload(line_adjustments=line_adjustments)
    res = api_client.complete_onsite(assignment_id, payload, headers)
    return get_success_data(res)


def issue_verification_report(
    *,
    assignment_id: str,
    agency_id: str,
) -> Dict[str, Any]:
    """POST /verification-assignments/{id}/issue-report as the assigned
    VerifierAgency."""
    headers = make_verifier_agency_headers(agency_id)
    res = api_client.issue_verification_report(assignment_id, headers)
    return get_success_data(res)


def finalize_report(*, report_id: str) -> Dict[str, Any]:
    """POST /emission-reports/{id}/finalize as Regulator."""
    res = api_client.finalize_emission_report(
        report_id, TEST_USERS["regulator_headers"]
    )
    return get_success_data(res)


def get_report(report_id: str, *, headers: Optional[Dict[str, str]] = None
               ) -> Dict[str, Any]:
    res = api_client.get_emission_report(
        report_id, headers or TEST_USERS["regulator_headers"]
    )
    return get_success_data(res)


def setup_submitted_report(
    *,
    enterprise_id: str,
    cycle_year: int,
    lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create a DRAFT report → add lines (with documents for FUEL/PROCESS)
    → submit. Returns the SUBMITTED report. If `lines` is omitted a single
    ELECTRICITY line of activity_data=100 / emission_factor=0.50 is added
    (no supporting document required)."""
    report = create_draft_report(
        enterprise_id=enterprise_id, cycle_year=cycle_year
    )
    line_specs = lines or [{
        "source_category": "ELECTRICITY",
        "activity_data": 100.00,
        "emission_factor": 0.50,
    }]
    for spec in line_specs:
        sd_id = spec.get("supporting_document_id")
        sc = spec["source_category"]
        # PRD §3.3: FUEL/PROCESS require a supporting_document_id; provide
        # one automatically unless the caller already supplied it (some
        # tests pass the wrong document id intentionally).
        if sc in {"FUEL", "PROCESS"} and sd_id is None:
            doc = upload_document(
                report_id=report["id"], enterprise_id=enterprise_id
            )
            sd_id = doc["id"]
        add_line(
            report_id=report["id"],
            enterprise_id=enterprise_id,
            source_category=sc,
            activity_data=spec["activity_data"],
            emission_factor=spec["emission_factor"],
            supporting_document_id=sd_id,
        )
    return submit_report(
        report_id=report["id"], enterprise_id=enterprise_id
    )


def setup_under_verification_report(
    *,
    enterprise_id: str,
    cycle_year: int,
    agency_id: Optional[str] = None,
    lines: Optional[List[Dict[str, Any]]] = None,
    visit_offset_days: float = 8,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """SUBMITTED report → assign verifier → assignment in ASSIGNED state.
    The visit is scheduled `visit_offset_days` days after the current clock,
    well past the 7-day minimum.
    Returns (report, assignment)."""
    report = setup_submitted_report(
        enterprise_id=enterprise_id, cycle_year=cycle_year, lines=lines,
    )
    aid = agency_id or unique_agency_id()
    visit_at = add_days(current_clock_iso(), visit_offset_days)
    assignment = assign_verifier(
        report_id=report["id"],
        agency_id=aid,
        scheduled_visit_at=visit_at,
    )
    return report, assignment


def setup_verified_report(
    *,
    enterprise_id: str,
    cycle_year: int,
    agency_id: Optional[str] = None,
    lines: Optional[List[Dict[str, Any]]] = None,
    line_verified_factor: float = 1.10,
    line_verified_amounts: Optional[List[float]] = None,
    visit_offset_days: float = 8,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive a report all the way to VERIFIED:
    DRAFT → SUBMITTED → UNDER_VERIFICATION → ON_SITE_DONE → REPORT_ISSUED → VERIFIED.

    `line_verified_amounts` (one per line) takes precedence over
    `line_verified_factor` if supplied.

    Returns (verified_report, assignment_after_issue).
    """
    report, assignment = setup_under_verification_report(
        enterprise_id=enterprise_id,
        cycle_year=cycle_year,
        agency_id=agency_id,
        lines=lines,
        visit_offset_days=visit_offset_days,
    )
    aid = assignment["agency_id"]

    # Read the report's lines back so we can build adjustments.
    full_report = get_report(report["id"])
    line_rows = full_report.get("lines") or full_report.get(
        "emission_data_lines"
    ) or []
    if not line_rows:
        # The PRD does not pin a particular array name. Try yet another
        # common shape.
        line_rows = full_report.get("data_lines") or []
    adjustments: List[Dict[str, Any]] = []
    for i, row in enumerate(line_rows):
        if line_verified_amounts is not None and i < len(line_verified_amounts):
            verified_amount = round(line_verified_amounts[i], 2)
        else:
            ad = row.get("activity_data", 0.0)
            ef = row.get("emission_factor", 0.0)
            verified_amount = round(ad * ef * line_verified_factor, 2)
        adjustments.append(
            line_adjustment(line_id=row["id"], verified_amount=verified_amount)
        )

    # Advance the simulated clock to (or past) the scheduled visit so the
    # on-site can be performed. PRD does not gate on the clock directly for
    # complete-onsite, but moves the world forward to keep ordering sane.
    advance_clock(assignment["scheduled_visit_at"])

    complete_onsite(
        assignment_id=assignment["id"],
        agency_id=aid,
        line_adjustments=adjustments,
    )
    issued = issue_verification_report(
        assignment_id=assignment["id"], agency_id=aid
    )
    verified_report = get_report(report["id"])
    return verified_report, issued


def setup_finalized_report(
    *,
    enterprise_id: str,
    cycle_year: int,
    agency_id: Optional[str] = None,
    lines: Optional[List[Dict[str, Any]]] = None,
    line_verified_factor: float = 1.10,
    line_verified_amounts: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """VERIFIED → FINALIZED via the regulator's finalize action.
    Advances the clock past the 14-day dispute window before finalizing.
    Returns the FINALIZED report.
    """
    verified_report, issued = setup_verified_report(
        enterprise_id=enterprise_id,
        cycle_year=cycle_year,
        agency_id=agency_id,
        lines=lines,
        line_verified_factor=line_verified_factor,
        line_verified_amounts=line_verified_amounts,
    )
    issued_at = issued.get("report_issued_at") or current_clock_iso()
    advance_clock(add_days(issued_at, 14.5))
    return finalize_report(report_id=verified_report["id"])


# ===========================================================================
# Tier 5 — Compliance declaration & penalty
# ===========================================================================
def create_draft_declaration(
    *,
    enterprise_id: str,
    cycle_year: int,
) -> Dict[str, Any]:
    """POST /enterprises/{id}/compliance-declarations as Enterprise."""
    headers = make_enterprise_headers(enterprise_id)
    payload = create_compliance_declaration_payload(cycle_year=cycle_year)
    res = api_client.create_compliance_declaration(
        enterprise_id, payload, headers
    )
    return get_success_data(res)


def submit_declaration(
    *,
    declaration_id: str,
    enterprise_id: str,
    declared_offset_quota: float,
    declared_offset_ccer: float = 0.0,
    declared_borrow_amount: Optional[float] = None,
    declared_bank_amount: Optional[float] = None,
) -> Dict[str, Any]:
    """POST /compliance-declarations/{id}/submit as the owning Enterprise."""
    headers = make_enterprise_headers(enterprise_id)
    payload = submit_compliance_declaration_payload(
        declared_offset_quota=declared_offset_quota,
        declared_offset_ccer=declared_offset_ccer,
        declared_borrow_amount=declared_borrow_amount,
        declared_bank_amount=declared_bank_amount,
    )
    res = api_client.submit_compliance_declaration(
        declaration_id, payload, headers
    )
    return get_success_data(res)


def pay_penalty(
    *,
    penalty_id: str,
    enterprise_id: str,
) -> Dict[str, Any]:
    """POST /penalty-orders/{id}/pay as the owning Enterprise."""
    headers = make_enterprise_headers(enterprise_id)
    res = api_client.pay_penalty_order(penalty_id, headers)
    return get_success_data(res)


def get_penalty(penalty_id: str) -> Dict[str, Any]:
    res = api_client.get_penalty_order(
        penalty_id, TEST_USERS["regulator_headers"]
    )
    return get_success_data(res)


# ===========================================================================
# Tier 6 — End-to-end ready scenarios for difficulty-design tests
# ===========================================================================
def setup_two_enterprises_with_quota_balances(
    *,
    seller_quota: float = 2000.00,
    buyer_quota: float = 0.00,
    free_paid_ratio: float = 1.00,
    ccer_cap_pct: float = 0.05,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create two enterprises with the seller holding `seller_quota` of
    free quota (for trading tests). Achieved by issuing a FINALIZED
    allocation per enterprise: seller gets a benchmark allocation totalling
    `seller_quota`, buyer gets a tiny placeholder of total 0.01 just to
    open the account. Defaults free_paid_ratio=1.00 so the balances land
    in quota_balance only (no paid_quota_balance complexity).

    Returns (cycle, seller_enterprise, buyer_enterprise).
    """
    # Use explicit deadlines anchored to the simulated clock so finalize
    # works deterministically.
    base = parse_iso(current_clock_iso())
    od = iso_z(base + timedelta(days=10))
    cd = iso_z(base + timedelta(days=400))

    cyc = create_allocation_cycle(
        free_paid_ratio=free_paid_ratio,
        ccer_cap_pct=ccer_cap_pct,
        objection_deadline=od,
        compliance_deadline=cd,
    )
    seller = create_enterprise()
    buyer = create_enterprise()
    # Seller's allocation: total_quota = activity_volume * benchmark_factor.
    propose_allocation(
        cycle_id=cyc["id"],
        enterprise_id=seller["id"],
        method="INDUSTRY_BENCHMARK",
        activity_volume=seller_quota,
        benchmark_factor=1.00,
    )
    # Buyer's allocation: tiny so the account opens but balance ~0.
    propose_allocation(
        cycle_id=cyc["id"],
        enterprise_id=buyer["id"],
        method="INDUSTRY_BENCHMARK",
        activity_volume=max(buyer_quota, 0.01),
        benchmark_factor=1.00,
    )
    publish_cycle(cyc["id"])
    advance_clock(add_seconds(od, 1))
    cyc2 = finalize_cycle(cyc["id"])
    seller_after = get_enterprise(seller["id"])
    buyer_after = get_enterprise(buyer["id"])
    return cyc2, seller_after, buyer_after


def place_order(
    *,
    enterprise_id: str,
    side: str,
    instrument: str,
    order_type: str,
    quantity: float,
    channel: str,
    limit_price: Optional[float] = None,
) -> Dict[str, Any]:
    """POST /trading-orders as the owning Enterprise."""
    headers = make_enterprise_headers(enterprise_id)
    payload = create_trading_order_payload(
        enterprise_id=enterprise_id,
        side=side,
        instrument=instrument,
        order_type=order_type,
        quantity=quantity,
        channel=channel,
        limit_price=limit_price,
    )
    res = api_client.create_trading_order(payload, headers)
    return get_success_data(res)


def setup_for_trade_fee_test(
    *,
    quantity: float = 4000,
    price: float = 50.00,
    channel: str = "EXCHANGE",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build the world for a marginal-tier trade-fee test:
      - Seller with sufficient QUOTA balance
      - Buyer ready to receive
      - Seller posts a SELL LIMIT
      - Buyer posts a BUY MARKET that fully matches
    Returns (cycle, seller, buyer, sell_order, buy_order) — actually
    (cycle, seller, buyer, buy_order_after_match)."""
    # Seller needs at least `quantity`
    cyc, seller, buyer = setup_two_enterprises_with_quota_balances(
        seller_quota=max(quantity * 1.5, 2000.00),
        buyer_quota=0.00,
    )
    sell_order = place_order(
        enterprise_id=seller["id"],
        side="SELL",
        instrument="QUOTA",
        order_type="LIMIT",
        quantity=quantity,
        channel=channel,
        limit_price=price,
    )
    buy_order = place_order(
        enterprise_id=buyer["id"],
        side="BUY",
        instrument="QUOTA",
        order_type="MARKET",
        quantity=quantity,
        channel=channel,
    )
    return cyc, seller, buyer, {"sell": sell_order, "buy": buy_order}


def setup_compliance_ready_enterprise(
    *,
    jurisdiction_code: str = "JD_ALPHA",
    free_paid_ratio: float = 0.80,
    ccer_cap_pct: float = 0.05,
    activity_volume: float = 1000.00,
    benchmark_factor: float = 1.50,
    line_activity_data: float = 100.00,
    line_emission_factor: float = 0.50,
    line_verified_amount: float = 100.00,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive an enterprise all the way to a FINALIZED EmissionReport with a
    pinned total_verified_emissions, plus a DRAFT ComplianceDeclaration
    ready to submit. Returns (cycle, enterprise, finalized_report,
    draft_declaration)."""
    base = parse_iso(current_clock_iso())
    od = iso_z(base + timedelta(days=10))
    cd = iso_z(base + timedelta(days=400))
    cyc = create_allocation_cycle(
        free_paid_ratio=free_paid_ratio,
        ccer_cap_pct=ccer_cap_pct,
        objection_deadline=od,
        compliance_deadline=cd,
    )
    ent = create_enterprise(jurisdiction_code=jurisdiction_code)
    propose_allocation(
        cycle_id=cyc["id"],
        enterprise_id=ent["id"],
        method="INDUSTRY_BENCHMARK",
        activity_volume=activity_volume,
        benchmark_factor=benchmark_factor,
    )
    publish_cycle(cyc["id"])
    advance_clock(add_seconds(od, 1))
    cyc2 = finalize_cycle(cyc["id"])
    # Trigger COMPLIANCE_OPEN by creating then submitting an emission
    # report.
    finalized = setup_finalized_report(
        enterprise_id=ent["id"],
        cycle_year=cyc2["cycle_year"],
        lines=[{
            "source_category": "ELECTRICITY",
            "activity_data": line_activity_data,
            "emission_factor": line_emission_factor,
        }],
        line_verified_amounts=[line_verified_amount],
    )
    decl = create_draft_declaration(
        enterprise_id=ent["id"], cycle_year=cyc2["cycle_year"]
    )
    return cyc2, ent, finalized, decl


def setup_non_compliant_with_penalty(
    *,
    jurisdiction_code: str = "JD_ALPHA",
    line_activity_data: float = 100.00,
    line_emission_factor: float = 1.00,
    line_verified_amount: float = 100.00,
    declared_offset_quota: float = 95.00,
    declared_offset_ccer: float = 0.0,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Drive a single enterprise to the NON_COMPLIANT state with a fresh
    PenaltyOrder. Allocation provides enough quota to cover the offset
    (plus headroom). Returns (cycle, enterprise, finalized_report,
    submitted_declaration, penalty_order).

    Internally re-fetches the penalty order via the audit log + the
    declaration's response payload — PRD §3.6 says NON_COMPLIANT
    auto-creates a PenaltyOrder; the response shape for declaration submit
    isn't pinned to include the penalty id, so we discover it via
    /audit-logs (PRD §3.6 + §3.8).
    """
    # Allocation must be large enough to cover the declared_offset_quota
    # (PRD §3.6 ERR_INSUFFICIENT_BALANCE check); scale the activity volume
    # so the allocation comfortably exceeds the offset.
    needed_quota = max(declared_offset_quota * 1.5, 300.00)
    cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
        jurisdiction_code=jurisdiction_code,
        line_activity_data=line_activity_data,
        line_emission_factor=line_emission_factor,
        line_verified_amount=line_verified_amount,
        # Big enough allocation to fund the offset.
        activity_volume=needed_quota,
        benchmark_factor=1.00,
        free_paid_ratio=1.00,
    )
    submitted = submit_declaration(
        declaration_id=decl["id"],
        enterprise_id=ent["id"],
        declared_offset_quota=declared_offset_quota,
        declared_offset_ccer=declared_offset_ccer,
    )
    # PRD §3.6: NON_COMPLIANT cascade auto-creates a PenaltyOrder. The
    # response shape isn't tightly pinned; try common keys first, then
    # fall back to /audit-logs scan.
    penalty_id = (
        submitted.get("penalty_order_id")
        or submitted.get("penalty_id")
        or (submitted.get("penalty_order") or {}).get("id")
    )
    if penalty_id:
        penalty = get_penalty(penalty_id)
    else:
        penalty = _find_penalty_for_enterprise(enterprise_id=ent["id"])
    return cyc, ent, finalized, submitted, penalty


def _find_penalty_for_enterprise(*, enterprise_id: str) -> Dict[str, Any]:
    """Discover the PenaltyOrder created for a given enterprise.

    PRD §4 lists GET /penalty-orders/{id} but no list endpoint, so we use
    /audit-logs (Regulator-only, but that's our test driver) to find a
    PENALTY-creation entry (the cascade in PRD §3.6 is logged).
    Falls back to inspecting the declaration cascade trail if needed.
    """
    res = api_client.list_audit_logs(
        TEST_USERS["regulator_headers"],
        params={"enterprise_id": enterprise_id, "limit": 100},
    )
    data = get_success_data(res)
    entries = data if isinstance(data, list) else (
        data.get("entries") or []
    )
    # NON_COMPLIANT cascade does not have a fixed action label in PRD;
    # PRD §3.6 names PENALTY_PAID for the pay action. We look for any
    # subject_type=QUOTA_CHANGE whose subject_id maps to a penalty order
    # via GET. Since action labels are PRD-loose for the create event,
    # we instead try a heuristic: any subject_id we haven't seen as a
    # known entity gets probed against /penalty-orders/{id}.
    seen_ids = set()
    for e in entries:
        sid = e.get("subject_id")
        if sid:
            seen_ids.add(sid)
    for sid in seen_ids:
        probe = api_client.get_penalty_order(
            sid, TEST_USERS["regulator_headers"]
        )
        if 200 <= probe.status_code < 300:
            return probe.json().get("data", {})
    raise AssertionError(
        f"Setup failed: could not discover PenaltyOrder for enterprise "
        f"{enterprise_id} via audit logs."
    )


# ===========================================================================
# Tier 7 — Settlement-ready scenarios
# ===========================================================================
def setup_settled_cycle(
    *,
    jurisdiction_code: str = "JD_ALPHA",
    line_activity_data: float = 100.00,
    line_emission_factor: float = 0.50,
    line_verified_amount: float = 50.00,
    declared_offset_quota: float = 50.00,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive a single-enterprise cycle through finalize → compliance → settle.
    Compliance is satisfied (no penalty). Returns (cycle, enterprise,
    submitted_declaration)."""
    cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
        jurisdiction_code=jurisdiction_code,
        activity_volume=200.00,
        benchmark_factor=1.50,
        free_paid_ratio=1.00,
        line_activity_data=line_activity_data,
        line_emission_factor=line_emission_factor,
        line_verified_amount=line_verified_amount,
    )
    submitted = submit_declaration(
        declaration_id=decl["id"],
        enterprise_id=ent["id"],
        declared_offset_quota=declared_offset_quota,
        declared_offset_ccer=0.0,
    )
    # Advance to compliance deadline + 1s.
    advance_clock(add_seconds(cyc["compliance_deadline"], 1))
    settle_cycle(cyc["id"])
    return cyc, ent, submitted


__all__ = [
    # Time helpers
    "iso_z",
    "parse_iso",
    "add_seconds",
    "add_minutes",
    "add_hours",
    "add_days",
    # Test-driver
    "advance_clock",
    "advance_clock_relative",
    "current_clock_iso",
    "run_sweep",
    "emit_event",
    # Tier 1
    "create_enterprise",
    "get_enterprise",
    "create_allocation_cycle",
    "propose_allocation",
    "publish_cycle",
    "finalize_cycle",
    "settle_cycle",
    "close_cycle",
    "get_cycle",
    # Tier 2
    "setup_cycle_with_one_proposed_allocation",
    "setup_published_cycle",
    "setup_finalized_cycle",
    "setup_published_cycle_multi",
    # Tier 3
    "setup_compliance_open_cycle",
    # Tier 4
    "create_draft_report",
    "add_line",
    "upload_document",
    "submit_report",
    "assign_verifier",
    "complete_onsite",
    "issue_verification_report",
    "finalize_report",
    "get_report",
    "setup_submitted_report",
    "setup_under_verification_report",
    "setup_verified_report",
    "setup_finalized_report",
    # Tier 5
    "create_draft_declaration",
    "submit_declaration",
    "pay_penalty",
    "get_penalty",
    # Tier 6
    "setup_two_enterprises_with_quota_balances",
    "place_order",
    "setup_for_trade_fee_test",
    "setup_compliance_ready_enterprise",
    "setup_non_compliant_with_penalty",
    # Tier 7
    "setup_settled_cycle",
]
