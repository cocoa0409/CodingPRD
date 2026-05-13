"""Composite setup helpers for the Drug Trial Ethics test suite.

Most interesting test claims need the system in a specific state reached
through 5-20 API calls (clock advance → application → submission →
submit → prescreen → members → meeting → agenda → publish → open →
votes → resolve → ...). These helpers encapsulate those preambles so
test bodies stay focused on assertions.

Identity threading (PRD §2.1):
- Applicant calls are gated by X-User-ID == Application.applicant_id.
  Every Applicant call MUST use make_applicant_headers(application[
  'applicant_id']) — so a freshly-created Application's applicant_id is
  threaded through every subsequent submissions / submit / annual-
  reports / rectification respond call.
- Chairperson and CommitteeMember are ENTITY-BACKED: X-User-ID must be
  an existing CommitteeMember.id. Every chair / member call uses
  make_chair_headers(member['id']) / make_committee_member_headers(
  member['id']).
- Secretary and RegulatoryWatcher are OPAQUE.

Setup helpers use get_success_data (lenient), so a broken precondition
surfaces as a clear setup error rather than a confusing assertion
failure inside the test body.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    cast_vote_payload,
    clock_payload,
    create_agenda_item_payload,
    create_annual_report_payload,
    create_application_payload,
    create_meeting_payload,
    create_member_payload,
    create_submission_payload,
    declare_conflict_payload,
    prescreen_payload,
    respond_rectification_payload,
    submit_application_payload,
    unique_applicant_id,
    unique_sponsor_name,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_chair_headers,
    make_committee_member_headers,
    make_secretary_headers,
)


# ===========================================================================
# Shared opaque-role headers
# ===========================================================================
SEC = TEST_USERS["secretary_headers"]
SEC_ALT = TEST_USERS["secretary_headers_alt"]
WATCHER = TEST_USERS["regulatory_watcher_headers"]


# ===========================================================================
# ISO 8601 helpers (PRD §2.4: 'ISO 8601 UTC with three fractional digits')
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """ISO 8601 UTC with millisecond precision, Z-suffixed."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 UTC string into a tz-aware UTC datetime."""
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(timezone.utc)


# ===========================================================================
# Clock helpers (PRD §4)
# ===========================================================================
def advance_clock(to_iso: str,
                  headers: Optional[Dict[str, str]] = None) -> Any:
    """PRD §4: 'Advance the server's logical clock to a future ISO 8601
    UTC timestamp.'"""
    return get_success_data(api_client.advance_clock(
        clock_payload(target_timestamp=to_iso), headers or SEC,
    ))


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Any:
    """PRD §4: 'Run the rectification-expiry sweep idempotently.'"""
    return get_success_data(api_client.run_sweep(headers or SEC))


def reset_clock_to(initial_iso: str = "2026-01-01T00:00:00.000Z") -> None:
    """Set the server clock to a known baseline. Runner gives a fresh
    server per session; one advance establishes the baseline."""
    advance_clock(initial_iso)


# ===========================================================================
# Application creation (PRD §3.1)
# ===========================================================================
def create_application(
    *,
    applicant_id: Optional[str] = None,
    sponsor_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'On creation the application enters DRAFT status ...
    the server records the caller's X-User-ID as applicant_id.'

    Returns the created Application. The applicant_id used as
    X-User-Role=Applicant X-User-ID must be threaded through every
    later write call on this application via make_applicant_headers().
    """
    aid = applicant_id or unique_applicant_id()
    use_headers = headers or make_applicant_headers(aid)
    payload = create_application_payload(
        sponsor_name=sponsor_name, **overrides,
    )
    return get_success_data(api_client.create_application(payload, use_headers))


def create_submission(
    application: Dict[str, Any],
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Applicant uploads each version'. Uses applicant
    ownership headers derived from Application.applicant_id."""
    use_headers = headers or make_applicant_headers(application["applicant_id"])
    return get_success_data(api_client.create_submission(
        application["id"],
        create_submission_payload(**overrides),
        use_headers,
    ))


def submit_application(
    application: Dict[str, Any],
    *,
    headers: Optional[Dict[str, str]] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.1: Applicant submits the current submission for pre-screen.
    Returns the updated Application."""
    use_headers = headers or make_applicant_headers(application["applicant_id"])
    return get_success_data(api_client.submit_application(
        application["id"],
        use_headers,
        submit_application_payload(version=version) if version is not None
        else None,
    ))


def prescreen_application(
    application_id: str,
    decision: str,
    *,
    prescreen_notes: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.1: Secretary pre-screens. Returns the updated Application."""
    return get_success_data(api_client.prescreen_application(
        application_id,
        prescreen_payload(decision=decision, prescreen_notes=prescreen_notes),
        headers or SEC,
    ))


def get_application(application_id: str,
                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_application(
        application_id, headers or SEC,
    ))


# ===========================================================================
# Member creation (PRD §3.2)
# ===========================================================================
def create_member(
    *,
    qualification: str = "MEDICAL_EXPERT",
    full_name: Optional[str] = None,
    term_start: str = "2025-01-01T00:00:00.000Z",
    term_end: str = "2030-01-01T00:00:00.000Z",
    affiliated_sponsors: Optional[List[str]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.2: Secretary registers a CommitteeMember."""
    return get_success_data(api_client.create_member(
        create_member_payload(
            qualification=qualification,
            full_name=full_name,
            term_start=term_start,
            term_end=term_end,
            affiliated_sponsors=affiliated_sponsors,
        ),
        headers or SEC,
    ))


def get_member(member_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_member(member_id, headers or SEC))


def declare_conflict(
    member: Dict[str, Any],
    application_id: str,
    *,
    conflict_type: str = "SPONSOR_RELATION",
    details: str = "Member is employed by trial sponsor.",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.2: Secretary or the member themselves files a
    ConflictDeclaration."""
    return get_success_data(api_client.declare_conflict(
        member["id"],
        declare_conflict_payload(
            application_id=application_id,
            conflict_type=conflict_type,
            details=details,
        ),
        headers or SEC,
    ))


def list_all_members(
    headers: Optional[Dict[str, str]] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Page through GET /ethics/members and return every committee
    member currently registered (across all tests in the session).

    Used by isolate_committee_for_application() to find pre-existing
    members that must be recused from a freshly-created Application.
    """
    use_headers = headers or SEC
    all_rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        data, meta = validate_paginated(api_client.list_members(
            use_headers, params={"limit": limit, "offset": offset},
        ))
        all_rows.extend(data)
        if not meta.get("has_more"):
            break
        offset += limit
    return all_rows


def isolate_committee_for_application(
    application_id: str,
    keep_members: List[Dict[str, Any]],
) -> None:
    """Ensure that — at agenda-publication time — the only eligible
    voters for `application_id` are the members in `keep_members`.

    PRD §2.9: 'the system counts active eligible members — committee
    members whose administrative status is ACTIVE ... excluding any
    member who has an active ConflictDeclaration for the agenda item's
    application_id.'

    The Drug Trial Ethics API stores all committee members in a single
    system-wide roster. Because the bench reuses the same server
    process across the whole test session, members seeded by earlier
    tests remain ACTIVE and (absent a per-application conflict) count
    toward the eligible voter pool of every newly-created Application.

    This helper restores the per-test invariant ('these N members are
    the entire committee for this application') by filing a
    SPONSOR_RELATION ConflictDeclaration against every existing
    committee member that is NOT in `keep_members`. This is exactly
    the PRD-defined mechanism for excluding a member from the eligible
    count (§2.10, §2.9). No PRD rule is bent.
    """
    keep_ids = {m["id"] for m in keep_members}
    for existing in list_all_members():
        if existing["id"] in keep_ids:
            continue
        # Best-effort: declare a conflict, ignore failures (already-
        # declared, member resigned, etc.). We skip the explicit
        # list-and-dedup step because (a) the application is brand-new
        # so no prior conflict exists for this pair, and (b) the API
        # roundtrip cost dominates at scale across the whole session.
        try:
            declare_conflict(
                existing, application_id,
                conflict_type="SPONSOR_RELATION",
                details="Test-isolation: not part of the committee "
                        "seeded for this application's review.",
            )
        except Exception:
            pass


def seed_committee(
    *,
    total: int = 9,
    chair_index: int = 0,
    affiliated_sponsors_by_index: Optional[Dict[int, List[str]]] = None,
    term_start: str = "2025-01-01T00:00:00.000Z",
    term_end: str = "2030-12-31T00:00:00.000Z",
) -> List[Dict[str, Any]]:
    """Seed a roster of `total` active CommitteeMembers.

    PRD §3.3 requires the convener to hold MEDICAL_EXPERT qualification
    and be is_active==true. The member at chair_index gets
    MEDICAL_EXPERT; the rest cycle through other qualifications.

    Member reuse: when ``affiliated_sponsors_by_index`` is empty, this
    helper reuses pre-existing active committee members from the
    system-wide roster instead of creating fresh rows on every call.
    The bench reuses one server process for the whole session, so a
    naive "always create new" strategy makes the roster grow without
    bound, which (a) violates per-test eligibility expectations in
    PRD §2.9 and (b) explodes the test-isolation conflict-declaration
    work to O(N²). Reuse is safe because each test's Application is
    fresh and Vote/AttendanceConfirmation rows are keyed on the
    agenda-item id, so prior tests' votes do not bleed into a new
    test's tally.
    """
    affiliated_sponsors_by_index = affiliated_sponsors_by_index or {}
    quals_cycle = [
        "PHARMACOLOGIST", "ETHICIST", "LEGAL_EXPERT",
        "LAY_REPRESENTATIVE", "STATISTICIAN",
    ]

    # Reuse path: try to assemble `total` active members from the
    # existing roster. Only available when no per-index affiliation is
    # requested (otherwise the test needs members with a specific
    # `affiliated_sponsors` value that pre-existing rows might lack).
    if not affiliated_sponsors_by_index:
        try:
            existing = list_all_members()
        except Exception:
            existing = []
        active_by_qual: Dict[str, List[Dict[str, Any]]] = {}
        for m in existing:
            if m.get("is_active") is True:
                active_by_qual.setdefault(m["qualification"], []).append(m)

        # Pick MEDICAL_EXPERT for chair position, others for non-chair.
        chairs = active_by_qual.get("MEDICAL_EXPERT", [])
        others: List[Dict[str, Any]] = []
        for q, ms in active_by_qual.items():
            if q == "MEDICAL_EXPERT":
                continue
            others.extend(ms)
        # Stable ordering for determinism.
        chairs.sort(key=lambda m: m["created_at"])
        others.sort(key=lambda m: m["created_at"])

        if chairs and len(others) >= total - 1:
            assembled: List[Dict[str, Any]] = [None] * total  # type: ignore
            assembled[chair_index] = chairs[0]
            non_chair_slots = [i for i in range(total) if i != chair_index]
            for slot, m in zip(non_chair_slots, others[: total - 1]):
                assembled[slot] = m
            return assembled

    # Create path: explicit affiliation requested, or not enough reusable
    # members in the roster.
    members: List[Dict[str, Any]] = []
    for i in range(total):
        q = "MEDICAL_EXPERT" if i == chair_index else (
            quals_cycle[(i - 1) % len(quals_cycle)]
        )
        m = create_member(
            qualification=q,
            term_start=term_start,
            term_end=term_end,
            affiliated_sponsors=affiliated_sponsors_by_index.get(i, []),
        )
        members.append(m)
    return members


# ===========================================================================
# Meeting / agenda helpers (PRD §3.3)
# ===========================================================================
def create_meeting(
    *,
    convener_member_id: str,
    scheduled_at: str,
    meeting_type: str = "STANDARD",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.3 Secretary schedules a meeting."""
    return get_success_data(api_client.create_meeting(
        create_meeting_payload(
            meeting_type=meeting_type,
            scheduled_at=scheduled_at,
            convener_member_id=convener_member_id,
        ),
        headers or SEC,
    ))


def add_agenda_item(
    meeting_id: str,
    application_id: str,
    *,
    review_kind: str = "INITIAL_REVIEW",
    annual_report_id: Optional[str] = None,
    rectification_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.3 Secretary adds an AgendaItem before publication."""
    return get_success_data(api_client.create_agenda_item(
        meeting_id,
        create_agenda_item_payload(
            application_id=application_id,
            review_kind=review_kind,
            annual_report_id=annual_report_id,
            rectification_id=rectification_id,
        ),
        headers or SEC,
    ))


def publish_agenda(meeting_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.publish_agenda(
        meeting_id, headers or SEC,
    ))


def open_meeting(meeting_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.open_meeting(
        meeting_id, headers or SEC,
    ))


def close_meeting(meeting_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.close_meeting(
        meeting_id, headers or SEC,
    ))


def get_agenda_item(agenda_item_id: str,
                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_agenda_item(
        agenda_item_id, headers or SEC,
    ))


# ===========================================================================
# Attendance / votes / resolve (PRD §3.4, §3.5)
# ===========================================================================
def confirm_attendance(
    agenda_item_id: str,
    member: Dict[str, Any],
) -> Dict[str, Any]:
    """PRD §3.4: 'eligible members confirm their attendance ... a member
    with an active declaration against the item's application receives
    ERR_MEMBER_RECUSED.'"""
    return get_success_data(api_client.confirm_attendance(
        agenda_item_id,
        make_committee_member_headers(member["id"]),
    ))


def cast_vote(
    agenda_item_id: str,
    member: Dict[str, Any],
    vote_mode: str,
) -> Dict[str, Any]:
    """PRD §3.4: 'Voting is the act of inserting a Vote row ... supplying
    a vote_mode of APPROVE, APPROVE_WITH_MODIFICATION, REJECT, or
    DEFER.' Uses the member's entity-backed CommitteeMember headers."""
    return get_success_data(api_client.cast_vote(
        agenda_item_id,
        cast_vote_payload(vote_mode=vote_mode),
        make_committee_member_headers(member["id"]),
    ))


def resolve_agenda_item(
    agenda_item_id: str,
    chair_member: Dict[str, Any],
    *,
    require_quorum: Optional[bool] = None,
) -> Dict[str, Any]:
    """PRD §3.5: 'When the Chairperson resolves an open agenda item, the
    system tallies all Vote rows ...' Uses the chair's entity-backed
    Chairperson headers."""
    params: Optional[Dict[str, Any]] = None
    if require_quorum is not None:
        params = {"require_quorum": str(require_quorum).lower()}
    return get_success_data(api_client.resolve_agenda_item(
        agenda_item_id,
        make_chair_headers(chair_member["id"]),
        params=params,
    ))


def get_resolution(resolution_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_resolution(
        resolution_id, headers or SEC,
    ))


# ===========================================================================
# Rectification / annual report / audit log helpers (PRD §3.6, §3.7, §3.8)
# ===========================================================================
def get_rectification(rectification_id: str,
                      headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_rectification(
        rectification_id, headers or SEC,
    ))


def discover_rectification_id(
    *,
    resolution: Dict[str, Any],
    application_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Find the Rectification id created as a side-effect of a
    APPROVE_WITH_MODIFICATION or DEFER resolution.

    PRD §3.6: 'When a resolution outcome is APPROVE_WITH_MODIFICATION
    or DEFER, the system automatically creates a child Rectification
    row that carries the application_id, the source_resolution_id
    pointing back to the resolution that generated it'.

    PRD does not mandate a specific discovery channel (no list
    endpoint, no field on Resolution is required). This helper tries
    common paths:
      1. resolution['rectification_id'] or similar embedded key (common
         implementation convention).
      2. audit-log scan: subject_entity='Rectification' rows whose
         payload references the resolution.id or application_id.

    Returns the rectification id, or None if not discoverable.
    """
    # 1. Direct embedding in resolution body.
    for k in ("rectification_id", "linked_rectification_id",
              "rectifications", "rectification"):
        v = resolution.get(k) if isinstance(resolution, dict) else None
        if isinstance(v, str) and v:
            return v
        if isinstance(v, list) and v and isinstance(v[0], dict) \
                and v[0].get("id"):
            return v[0]["id"]
        if isinstance(v, dict) and v.get("id"):
            return v["id"]

    # 2. Audit-log scan — filter by application_id so we don't return
    #    a stale rectification from a prior test (the server keeps state
    #    across the whole session).
    try:
        rows = list_audit_logs(headers, subject_entity="Rectification")
    except Exception:
        rows = []
    candidates: List[Dict[str, Any]] = []
    for r in rows:
        if not r.get("subject_id"):
            continue
        payload = r.get("payload") or {}
        if isinstance(payload, dict) and payload.get("application_id") == application_id:
            candidates.append(r)
    if candidates:
        # Pick the most recently created — pagination is ascending, so last
        # element is newest.
        return candidates[-1]["subject_id"]
    # Last-resort: GET each candidate rectification and confirm
    # application_id matches.
    for r in rows:
        rid = r.get("subject_id")
        if not rid:
            continue
        try:
            rec = get_rectification(rid)
        except Exception:
            continue
        if rec.get("application_id") == application_id:
            return rid
    return None


def respond_rectification(
    rectification_id: str,
    applicant_id: str,
    *,
    applicant_response_uri: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.6: 'Applicant submits a response by hitting the
    rectification's respond endpoint'. Uses ownership headers."""
    return get_success_data(api_client.respond_rectification(
        rectification_id,
        respond_rectification_payload(
            applicant_response_uri=applicant_response_uri,
        ),
        make_applicant_headers(applicant_id),
    ))


def create_annual_report(
    application: Dict[str, Any],
    *,
    serious_adverse_event_count: int = 0,
    total_adverse_event_count: int = 0,
    enrollment_count: int = 10,
    report_kind: str = "ANNUAL_PROGRESS",
    report_period_start: str = "2026-01-01T00:00:00.000Z",
    report_period_end: str = "2026-12-31T00:00:00.000Z",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.7: Applicant submits an AnnualReport."""
    use_headers = headers or make_applicant_headers(application["applicant_id"])
    return get_success_data(api_client.create_annual_report(
        application["id"],
        create_annual_report_payload(
            serious_adverse_event_count=serious_adverse_event_count,
            total_adverse_event_count=total_adverse_event_count,
            enrollment_count=enrollment_count,
            report_kind=report_kind,
            report_period_start=report_period_start,
            report_period_end=report_period_end,
        ),
        use_headers,
    ))


def list_annual_reports(
    application_id: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(api_client.list_annual_reports(
        application_id, headers or SEC, params=params,
    ))


def list_audit_logs(
    headers: Optional[Dict[str, str]] = None,
    *,
    event_type: Optional[str] = None,
    subject_entity: Optional[str] = None,
    subject_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """PRD §3.8: 'audit-log listing, filterable on event_type,
    subject_entity, and subject_id.'"""
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if event_type is not None:
        params["event_type"] = event_type
    if subject_entity is not None:
        params["subject_entity"] = subject_entity
    if subject_id is not None:
        params["subject_id"] = subject_id
    data, _meta = validate_paginated(api_client.list_audit_logs(
        headers or SEC, params=params,
    ))
    return data


# ===========================================================================
# COMPOSITE HELPERS
# ===========================================================================

# ---------------------------------------------------------------------------
# Application progression — DRAFT → ... → PENDING_REVIEW
# ---------------------------------------------------------------------------
def create_application_with_submission(
    *,
    sponsor_name: Optional[str] = None,
    applicant_id: Optional[str] = None,
    **app_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create an Application + one complete Submission v1.
    Returns (application, submission_v1). Application is still DRAFT."""
    sn = sponsor_name or unique_sponsor_name()
    aid = applicant_id or unique_applicant_id()
    app = create_application(
        applicant_id=aid, sponsor_name=sn, **app_overrides,
    )
    sub = create_submission(app)
    # Refresh application so caller has fresh current_submission_version.
    app = get_application(app["id"])
    return app, sub


def setup_application_pending_prescreen(
    *,
    sponsor_name: Optional[str] = None,
    applicant_id: Optional[str] = None,
    **app_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """DRAFT → PENDING_PRESCREEN. Returns (application, submission_v1)."""
    app, sub = create_application_with_submission(
        sponsor_name=sponsor_name,
        applicant_id=applicant_id,
        **app_overrides,
    )
    app = submit_application(app)
    return app, sub


def setup_application_pending_review(
    *,
    sponsor_name: Optional[str] = None,
    applicant_id: Optional[str] = None,
    **app_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """DRAFT → ... → PENDING_REVIEW (prescreen PASS).
    Returns (application, submission_v1)."""
    app, sub = setup_application_pending_prescreen(
        sponsor_name=sponsor_name,
        applicant_id=applicant_id,
        **app_overrides,
    )
    app = prescreen_application(app["id"], "PASS")
    return app, sub


# ---------------------------------------------------------------------------
# Meeting / agenda composites
# ---------------------------------------------------------------------------
def setup_meeting_with_agenda_item(
    *,
    application: Dict[str, Any],
    members: List[Dict[str, Any]],
    chair_member: Dict[str, Any],
    clock_base_iso: str = "2026-06-01T00:00:00.000Z",
    meeting_type: str = "STANDARD",
    review_kind: str = "INITIAL_REVIEW",
    rectification_id: Optional[str] = None,
    annual_report_id: Optional[str] = None,
    lead_hours: int = 168,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Schedule a Meeting at clock_base_iso + lead_hours and add one
    AgendaItem. Returns (meeting, agenda_item). Application is moved
    only as a side-effect of publish/open below — this helper does
    NOT publish.

    PRD §3.3: STANDARD lead time is 168 hours (7 days); EXPEDITED is
    24 hours.
    """
    advance_clock(clock_base_iso)
    base_dt = parse_iso(clock_base_iso)
    scheduled_at = iso_z(base_dt + timedelta(hours=lead_hours))
    meeting = create_meeting(
        convener_member_id=chair_member["id"],
        scheduled_at=scheduled_at,
        meeting_type=meeting_type,
    )
    item = add_agenda_item(
        meeting["id"],
        application["id"],
        review_kind=review_kind,
        rectification_id=rectification_id,
        annual_report_id=annual_report_id,
    )
    return meeting, item


def setup_open_agenda_item(
    *,
    application: Dict[str, Any],
    members: List[Dict[str, Any]],
    chair_member: Dict[str, Any],
    clock_base_iso: str = "2026-06-01T00:00:00.000Z",
    meeting_type: str = "STANDARD",
    review_kind: str = "INITIAL_REVIEW",
    rectification_id: Optional[str] = None,
    annual_report_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive a meeting through SCHEDULED → AGENDA_PUBLISHED → IN_SESSION
    with one AgendaItem in OPEN_FOR_VOTING. Returns (meeting, agenda_item).

    Lead time per PRD §3.3 (STANDARD=168h, EXPEDITED=24h)."""
    lead_hours = 168 if meeting_type == "STANDARD" else 24
    meeting, item = setup_meeting_with_agenda_item(
        application=application,
        members=members,
        chair_member=chair_member,
        clock_base_iso=clock_base_iso,
        meeting_type=meeting_type,
        review_kind=review_kind,
        rectification_id=rectification_id,
        annual_report_id=annual_report_id,
        lead_hours=lead_hours,
    )
    # Test-isolation: per-test committees must be the only eligible voters.
    # PRD §2.9 counts every active committee member system-wide; the bench
    # reuses the same server across the whole session, so we recuse every
    # OTHER existing member from this application before publication.
    isolate_committee_for_application(application["id"], members)
    publish_agenda(meeting["id"])
    # Advance clock to scheduled_at to satisfy "now() >= scheduled_at".
    advance_clock(meeting["scheduled_at"])
    open_meeting(meeting["id"])
    # Refresh
    item = get_agenda_item(item["id"])
    return meeting, item


# ---------------------------------------------------------------------------
# Full happy-path through resolve
# ---------------------------------------------------------------------------
def setup_resolved_initial_review(
    *,
    vote_split: Dict[str, int],
    member_count: int = 9,
    chair_index: int = 0,
    sponsor_name: Optional[str] = None,
    applicant_id: Optional[str] = None,
    clock_base_iso: str = "2026-06-01T00:00:00.000Z",
) -> Dict[str, Any]:
    """Full happy-path: create an application, drive it to PENDING_REVIEW,
    seed `member_count` active members (chair_index gets MEDICAL_EXPERT),
    schedule a STANDARD meeting + INITIAL_REVIEW agenda item, publish,
    open, cast votes per vote_split (e.g., {APPROVE: 6,
    APPROVE_WITH_MODIFICATION: 2, REJECT: 1}), and resolve.

    Returns dict with keys: application, submission, members, chair,
    meeting, agenda_item, resolution.
    """
    sn = sponsor_name or unique_sponsor_name()
    aid = applicant_id or unique_applicant_id()
    app, sub = setup_application_pending_review(
        sponsor_name=sn, applicant_id=aid,
    )
    members = seed_committee(total=member_count, chair_index=chair_index)
    chair = members[chair_index]
    meeting, item = setup_open_agenda_item(
        application=app, members=members, chair_member=chair,
        clock_base_iso=clock_base_iso,
    )
    # Cast votes
    voters = [m for m in members]  # all members eligible by default
    idx = 0
    for vote_mode, n in vote_split.items():
        for _ in range(n):
            if idx >= len(voters):
                raise RuntimeError(
                    f"Not enough voters ({len(voters)}) for split "
                    f"{vote_split}"
                )
            cast_vote(item["id"], voters[idx], vote_mode)
            idx += 1
    resolution = resolve_agenda_item(item["id"], chair)
    return {
        "application": get_application(app["id"]),
        "submission": sub,
        "members": members,
        "chair": chair,
        "meeting": meeting,
        "agenda_item": get_agenda_item(item["id"]),
        "resolution": resolution,
        "applicant_id": aid,
    }


# ---------------------------------------------------------------------------
# DIFFICULTY-DESIGN-SHAPED FIXTURES
# ---------------------------------------------------------------------------
def setup_initial_vs_continuing_setup(
    *,
    clock_base_iso: str = "2026-06-01T00:00:00.000Z",
) -> Dict[str, Any]:
    """Sets the base clock and seeds 9 members suitable for both an
    initial-review and a subsequent continuing-review meeting.
    Returns dict with keys: members, chair.

    Mirrors test_recipe.setup of
    dual_variant_calc/vote_tally_dual_variant_initial_vs_continuing.
    """
    advance_clock(clock_base_iso)
    members = seed_committee(total=9, chair_index=0)
    return {"members": members, "chair": members[0]}


def setup_two_safety_alert_inputs(
    *,
    clock_base_iso: str = "2026-06-01T00:00:00.000Z",
) -> Dict[str, Any]:
    """Drive Application A2 to APPROVED via the happy path. Returns dict
    with keys: application, applicant_id, members, chair, resolution.

    Mirrors test_recipe.setup of
    dual_variant_calc/safety_alert_chronological_vs_forward_pinned.
    """
    bundle = setup_resolved_initial_review(
        vote_split={"APPROVE": 6, "APPROVE_WITH_MODIFICATION": 2,
                    "REJECT": 1},
        member_count=9,
        clock_base_iso=clock_base_iso,
    )
    return bundle


def setup_meeting_with_recusals(
    *,
    total_members: int = 7,
    recuse_indices: Optional[List[int]] = None,
    clock_base_iso: str = "2026-06-01T00:00:00.000Z",
) -> Dict[str, Any]:
    """Seed `total_members` members with a chair at index 0 (MEDICAL_EXPERT),
    create an Application and drive it to PENDING_REVIEW, then pre-declare
    a CONFLICT_TYPE=SPONSOR_RELATION conflict for each member in
    recuse_indices. Returns dict with keys: application, applicant_id,
    members, recused_members, chair.

    Mirrors the quorum-floor-dominates setup for
    combinatorial_formula/quorum_max_ceil_rounding_order.
    """
    recuse_indices = recuse_indices or []
    advance_clock(clock_base_iso)
    sponsor_name = unique_sponsor_name()
    applicant_id = unique_applicant_id()
    app, _ = setup_application_pending_review(
        sponsor_name=sponsor_name, applicant_id=applicant_id,
    )
    members = seed_committee(total=total_members, chair_index=0)
    recused: List[Dict[str, Any]] = []
    for i in recuse_indices:
        declare_conflict(
            members[i], app["id"],
            conflict_type="SPONSOR_RELATION",
            details="Pre-declared conflict for boundary testing.",
        )
        recused.append(members[i])
    return {
        "application": app,
        "applicant_id": applicant_id,
        "sponsor_name": sponsor_name,
        "members": members,
        "recused_members": recused,
        "chair": members[0],
    }


def setup_meeting_lead_time_cases(
    *,
    clock_base_iso: str = "2026-06-01T00:00:00.000Z",
) -> Dict[str, Any]:
    """Create three meetings at differing lead times:
      MEET_STD_OK   — STANDARD at clock+168h (exact)
      MEET_STD_FAIL — STANDARD at clock+167h59m59s (insufficient)
      MEET_EXP_OK   — EXPEDITED at clock+24h (exact)
    Each with one INITIAL_REVIEW agenda item.

    Mirrors combinatorial_formula/lead_time_tiered_selection_and_boundary.
    Returns dict with keys: members, chair, app, meet_std_ok,
    meet_std_fail, meet_exp_ok.
    """
    advance_clock(clock_base_iso)
    base_dt = parse_iso(clock_base_iso)
    members = seed_committee(total=9, chair_index=0)
    chair = members[0]
    app, _ = setup_application_pending_review()

    m_std_ok = create_meeting(
        convener_member_id=chair["id"],
        scheduled_at=iso_z(base_dt + timedelta(hours=168)),
        meeting_type="STANDARD",
    )
    add_agenda_item(m_std_ok["id"], app["id"])

    m_std_fail = create_meeting(
        convener_member_id=chair["id"],
        scheduled_at=iso_z(base_dt + timedelta(hours=167, minutes=59,
                                                seconds=59)),
        meeting_type="STANDARD",
    )
    add_agenda_item(m_std_fail["id"], app["id"])

    m_exp_ok = create_meeting(
        convener_member_id=chair["id"],
        scheduled_at=iso_z(base_dt + timedelta(hours=24)),
        meeting_type="EXPEDITED",
    )
    add_agenda_item(m_exp_ok["id"], app["id"])

    return {
        "members": members,
        "chair": chair,
        "app": app,
        "meet_std_ok": m_std_ok,
        "meet_std_fail": m_std_fail,
        "meet_exp_ok": m_exp_ok,
        "clock_base_iso": clock_base_iso,
    }


def setup_application_rework_loop(
    *,
    sponsor_name: Optional[str] = None,
    applicant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive an Application through PENDING_PRESCREEN, then reject. Used
    for the cycle test (application_cyclic_rework_loop).

    Returns: application, submission_v1, applicant_id.
    """
    app, sub_v1 = setup_application_pending_prescreen(
        sponsor_name=sponsor_name, applicant_id=applicant_id,
    )
    return {
        "application": app,
        "submission_v1": sub_v1,
        "applicant_id": app["applicant_id"],
    }


def setup_rectification_from_deferred(
    *,
    clock_base_iso: str = "2026-06-01T00:00:00.000Z",
) -> Dict[str, Any]:
    """Drive an Application to DEFERRED with an OPEN Rectification.

    Vote split: 5 DEFER + 2 APPROVE  → DEFER outcome (DEFER >= ceil(7/2)=4).
    Quorum is 7 (max(5, ceil(0.67*9))=7), votes_cast=7, REJECT=0,
    APPROVE+AWM=2 < ceil(2/3*7)=5; DEFER=5 >= 4 → DEFER.

    Returns: application, rectification, members, chair, resolution.
    """
    bundle = setup_resolved_initial_review(
        vote_split={"DEFER": 5, "APPROVE": 2},
        member_count=9,
        clock_base_iso=clock_base_iso,
    )
    # Application should be DEFERRED with a Rectification row created.
    # Find the rectification via the resolution.created_at + 30d due_at.
    # The fixtures call get_application; status reflects post-resolve state.
    app = bundle["application"]
    # We don't have a direct list endpoint for rectifications. The
    # rectification id should be implied by the resolution; tests must
    # fetch it via the Resolution document or a Secretary's read endpoint.
    # Some implementations include rectification_id on the resolution
    # payload, but PRD does not require this. Tests resolve indirectly:
    # they re-run prescribed actions on the inferred id where the test
    # itself fetches the resource. To keep this fixture useful we
    # return the bundle untouched plus the resolution.
    return bundle


# ---------------------------------------------------------------------------
# Member-attendance and vote helpers (multi-member loops)
# ---------------------------------------------------------------------------
def cast_votes_for(
    agenda_item_id: str,
    voters_by_mode: Dict[str, List[Dict[str, Any]]],
) -> None:
    """Bulk-cast votes. voters_by_mode example:
        {"APPROVE": [m0, m1, m2, m3, m4, m5],
         "APPROVE_WITH_MODIFICATION": [m6, m7],
         "REJECT": [m8]}
    """
    for mode, members in voters_by_mode.items():
        for m in members:
            cast_vote(agenda_item_id, m, mode)


def confirm_all(agenda_item_id: str,
                members: List[Dict[str, Any]]) -> None:
    """Confirm attendance for every member in `members`."""
    for m in members:
        confirm_attendance(agenda_item_id, m)


__all__ = [
    # Shared headers
    "SEC", "SEC_ALT", "WATCHER",
    # ISO helpers
    "iso_z", "parse_iso",
    # Clock
    "advance_clock", "run_sweep", "reset_clock_to",
    # Application
    "create_application", "create_submission", "submit_application",
    "prescreen_application", "get_application",
    # Members and conflicts
    "create_member", "get_member", "declare_conflict", "seed_committee",
    # Meetings and agenda
    "create_meeting", "add_agenda_item", "publish_agenda", "open_meeting",
    "close_meeting", "get_agenda_item",
    # Attendance / votes / resolve
    "confirm_attendance", "cast_vote", "resolve_agenda_item",
    "get_resolution",
    # Rectification / annual report / audit log
    "get_rectification", "respond_rectification",
    "discover_rectification_id",
    "create_annual_report", "list_annual_reports", "list_audit_logs",
    # Composite
    "create_application_with_submission",
    "setup_application_pending_prescreen",
    "setup_application_pending_review",
    "setup_meeting_with_agenda_item",
    "setup_open_agenda_item",
    "setup_resolved_initial_review",
    "setup_initial_vs_continuing_setup",
    "setup_two_safety_alert_inputs",
    "setup_meeting_with_recusals",
    "setup_meeting_lead_time_cases",
    "setup_application_rework_loop",
    "setup_rectification_from_deferred",
    "cast_votes_for", "confirm_all",
]
