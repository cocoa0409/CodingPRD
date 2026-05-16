"""Composite setup helpers — multi-step preambles tests can reuse.

The NCAA Recruiting pipeline is long: program -> athlete -> eligibility ->
slot offer -> slot signed -> athlete COMMITTED -> athlete ENROLLED ->
(optional) NIL deal submit -> review -> approved -> ... -> portal entry,
violation pipeline, etc. Many test claims need the system in a late-
pipeline state — for example, testing a SUSTAINED-on-appeal cascade
requires the violation to be in APPEALED, which requires SUBSTANTIATED,
which requires INVESTIGATING, which requires REPORTED.

IDENTITY THREADING — PRD §2.1:

- ComplianceOfficer / Coach / Booster / Auditor are OPAQUE. Shared
  constants in TEST_USERS are canonical. The PRIMARY / SECONDARY /
  TERTIARY officer headers exist to satisfy segregation-of-duties
  checks: the NIL deal submitter must be a *different* X-User-ID from
  the reviewer (PRD §3.6), and the violation appellate reviewer must be
  a *different* X-User-ID from the original reviewer (PRD §3.7).

- Athlete is ENTITY-BACKED. PRD §2.1: "an Athlete who supplies someone
  else's athlete_id when submitting an NIL deal or entering the portal
  is rejected with ERR_FORBIDDEN." Every Athlete-role call whose
  success depends on owning the targeted resource MUST mint headers via
  make_athlete_headers(athlete["id"]).

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    APPEAL_WINDOW_DAYS,
    PORTAL_HOLDING_PERIOD_HOURS,
    TEST_DEFAULTS,
)
from .factories import (
    advance_clock_payload,
    create_athlete_payload,
    create_eligibility_record_payload,
    create_nil_deal_payload,
    create_program_payload,
    create_recruiting_calendar_payload,
    create_recruiting_contact_payload,
    create_scholarship_slot_payload,
    create_transfer_portal_entry_payload,
    create_violation_payload,
    iso_now,
    iso_offset,
    iso_utc,
    random_suffix,
    transition_athlete_payload,
    transition_nil_deal_payload,
    transition_scholarship_slot_payload,
    transition_transfer_portal_entry_payload,
    transition_violation_payload,
    utcnow,
)
from .test_users import (
    TEST_USERS,
    make_athlete_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.10
# ===========================================================================
def advance_clock_to(to_timestamp: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /_clock/advance with the supplied ISO 8601 instant.
    PRD §2.10: ComplianceOfficer or Auditor.
    """
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.advance_clock(
        advance_clock_payload(to_timestamp=to_timestamp), headers,
    )
    return get_success_data(resp)


def server_now_iso() -> str:
    """Return the server's current logical-clock time as ISO 8601.

    PRD §2.10: "A read endpoint exposes the current clock." This is the
    only endpoint with optional headers per PRD §2.1.
    """
    resp = api_client.get_clock()
    body = resp.json()
    # The clock endpoint returns { now: datetime } per PRD §4.
    if "data" in body and "now" in body["data"]:
        return body["data"]["now"]
    # Fall back to meta.api_request_timestamp if the schema diverges
    # (PRD §2.2 guarantees this field on every response).
    return body["meta"]["api_request_timestamp"]


def parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional
    seconds, with Z or +00:00) into a tz-aware datetime."""
    s = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


# ===========================================================================
# Tier 1: Program / Athlete / EligibilityRecord setup
# ===========================================================================
def create_program(
    *,
    sport: str = "FOOTBALL",
    division: str = "DI",
    scholarship_cap_equivalencies: float = 85.0,
    roster_cap_count: int = 85,
    institution_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /programs — ComplianceOfficer only per PRD §3.1."""
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.create_program(
        create_program_payload(
            sport=sport,
            division=division,
            scholarship_cap_equivalencies=scholarship_cap_equivalencies,
            roster_cap_count=roster_cap_count,
            institution_name=institution_name,
        ),
        headers,
    )
    return get_success_data(resp)


def create_athlete(
    *,
    full_name: Optional[str] = None,
    high_school: str = "Anywhere High",
    graduation_year: int = 2025,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /athletes — ComplianceOfficer or Coach per PRD §3.2."""
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.create_athlete(
        create_athlete_payload(
            full_name=full_name,
            high_school=high_school,
            graduation_year=graduation_year,
        ),
        headers,
    )
    return get_success_data(resp)


def create_eligibility_record(
    athlete_id: str,
    *,
    decision: str = "QUALIFIER",
    core_gpa: float = 3.50,
    standardized_test_score: int = 1200,
    core_courses_completed: int = 16,
    decided_at: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /eligibility-records — ComplianceOfficer only per PRD §3.2."""
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.create_eligibility_record(
        create_eligibility_record_payload(
            athlete_id=athlete_id,
            decision=decision,
            core_gpa=core_gpa,
            standardized_test_score=standardized_test_score,
            core_courses_completed=core_courses_completed,
            decided_at=decided_at,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2: Slot lifecycle
# ===========================================================================
def offer_slot(
    program_id: str,
    athlete_id: str,
    *,
    fractional_equivalency: float = 1.00,
    annual_value_cents: int = 5_000_000,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /scholarship-slots — Coach only per PRD §3.3."""
    headers = headers or TEST_USERS["coach_headers"]
    resp = api_client.create_scholarship_slot(
        create_scholarship_slot_payload(
            program_id=program_id,
            athlete_id=athlete_id,
            fractional_equivalency=fractional_equivalency,
            annual_value_cents=annual_value_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def sign_slot(
    slot_id: str,
    *,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /scholarship-slots/{id}/state with to_status=SIGNED —
    Coach per PRD §3.3."""
    headers = headers or TEST_USERS["coach_headers"]
    resp = api_client.transition_scholarship_slot(
        slot_id,
        transition_scholarship_slot_payload(
            to_status="SIGNED", version=version,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 3: Athlete state-machine progression
# ===========================================================================
def commit_athlete(
    athlete_id: str,
    program_id: str,
    *,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /athletes/{id}/state with to_status=COMMITTED and program_id —
    ComplianceOfficer per PRD §3.2."""
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.transition_athlete(
        athlete_id,
        transition_athlete_payload(
            to_status="COMMITTED",
            program_id=program_id,
            version=version,
        ),
        headers,
    )
    return get_success_data(resp)


def enroll_athlete(
    athlete_id: str,
    *,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /athletes/{id}/state with to_status=ENROLLED —
    ComplianceOfficer per PRD §3.2."""
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.transition_athlete(
        athlete_id,
        transition_athlete_payload(
            to_status="ENROLLED", version=version,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 4: End-to-end "athlete enrolled at program" shortcut
# ===========================================================================
def setup_enrolled_athlete(
    *,
    sport: str = "FOOTBALL",
    scholarship_cap_equivalencies: float = 85.0,
    roster_cap_count: int = 85,
    fractional_equivalency: float = 1.00,
    annual_value_cents: int = 5_000_000,
    eligibility_decision: str = "QUALIFIER",
    program: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Full pipeline to land Athlete A in ENROLLED at Program P with a
    signed slot.

    Sequence per PRD §3.1, §3.2, §3.3:
      1. Create Program (or use the one supplied).
      2. Create Athlete (status=PROSPECTIVE, amateur_status=AMATEUR).
      3. Post EligibilityRecord with decision=QUALIFIER.
      4. Coach offers a ScholarshipSlot.
      5. Coach signs the slot (OFFERED -> SIGNED).
      6. ComplianceOfficer transitions athlete PROSPECTIVE -> COMMITTED.
      7. ComplianceOfficer transitions athlete COMMITTED -> ENROLLED;
         this cascades SIGNED -> ACTIVE on the slot.

    Returns (athlete, program, slot) all freshly refetched after the
    enrollment cascade.
    """
    if program is None:
        program = create_program(
            sport=sport,
            scholarship_cap_equivalencies=scholarship_cap_equivalencies,
            roster_cap_count=roster_cap_count,
        )
    athlete = create_athlete()
    create_eligibility_record(athlete["id"], decision=eligibility_decision)
    slot = offer_slot(
        program["id"], athlete["id"],
        fractional_equivalency=fractional_equivalency,
        annual_value_cents=annual_value_cents,
    )
    sign_slot(slot["id"])
    commit_athlete(athlete["id"], program["id"])
    enroll_athlete(athlete["id"])
    # Refresh entities.
    a_resp = api_client.get_athlete(
        athlete["id"], TEST_USERS["officer_headers"],
    )
    p_resp = api_client.get_program(
        program["id"], TEST_USERS["officer_headers"],
    )
    s_resp = api_client.get_scholarship_slot(
        slot["id"], TEST_USERS["officer_headers"],
    )
    return (
        get_success_data(a_resp),
        get_success_data(p_resp),
        get_success_data(s_resp),
    )


# ===========================================================================
# Tier 5: NILDeal lifecycle
# ===========================================================================
def submit_nil_deal(
    athlete_id: str,
    *,
    sponsor_name: Optional[str] = None,
    sponsor_is_booster: bool = False,
    deal_category: str = "ENDORSEMENT",
    stated_value_cents: int = 500_000,
    deliverables_hours: float = 10.0,
    market_rate_cents_per_hour: int = 50_000,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /nil-deals — Athlete, Booster, or ComplianceOfficer per
    PRD §3.5.

    If headers are not supplied, defaults to the Athlete identity
    (entity-backed) by minting headers from athlete_id. PRD §2.1: an
    Athlete must satisfy athlete_id == X-User-ID when submitting an
    NIL deal. Passing the booster_headers or officer_headers shared
    constant in `headers` overrides this default.
    """
    headers = headers or make_athlete_headers(athlete_id)
    resp = api_client.create_nil_deal(
        create_nil_deal_payload(
            athlete_id=athlete_id,
            sponsor_name=sponsor_name,
            sponsor_is_booster=sponsor_is_booster,
            deal_category=deal_category,
            stated_value_cents=stated_value_cents,
            deliverables_hours=deliverables_hours,
            market_rate_cents_per_hour=market_rate_cents_per_hour,
        ),
        headers,
    )
    return get_success_data(resp)


def review_nil_deal(
    deal_id: str,
    *,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /nil-deals/{id}/state with to_status=UNDER_REVIEW —
    ComplianceOfficer per PRD §3.6.

    PRD §3.6: "The acting officer's X-User-ID must differ from the
    X-User-ID that submitted the deal." If the submitter was an
    Athlete (default), any ComplianceOfficer X-User-ID is a different
    actor; if the submitter was an officer, use a DIFFERENT officer here.
    Default is the PRIMARY officer; tests that submit as an officer
    must override.
    """
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.transition_nil_deal(
        deal_id,
        transition_nil_deal_payload(
            to_status="UNDER_REVIEW", version=version,
        ),
        headers,
    )
    return get_success_data(resp)


def approve_nil_deal(
    deal_id: str,
    *,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /nil-deals/{id}/state with to_status=APPROVED —
    ComplianceOfficer per PRD §3.6."""
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.transition_nil_deal(
        deal_id,
        transition_nil_deal_payload(
            to_status="APPROVED", version=version,
        ),
        headers,
    )
    return get_success_data(resp)


def setup_approved_nil_deal(
    athlete_id: str,
    *,
    sponsor_is_booster: bool = False,
    deal_category: str = "ENDORSEMENT",
    stated_value_cents: int = 500_000,
    deliverables_hours: float = 10.0,
    market_rate_cents_per_hour: int = 50_000,
) -> Dict[str, Any]:
    """Submit -> UNDER_REVIEW -> APPROVED. Returns the approved deal.

    Per PRD §3.6 the submitter and the reviewer must be different
    X-User-IDs; this fixture submits as Athlete (entity-backed) and
    reviews/approves as ComplianceOfficer, satisfying the rule.
    """
    deal = submit_nil_deal(
        athlete_id,
        sponsor_is_booster=sponsor_is_booster,
        deal_category=deal_category,
        stated_value_cents=stated_value_cents,
        deliverables_hours=deliverables_hours,
        market_rate_cents_per_hour=market_rate_cents_per_hour,
    )
    review_nil_deal(deal["id"])
    approve_nil_deal(deal["id"])
    # Refresh
    resp = api_client.get_nil_deal(
        deal["id"], TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 6: ComplianceViolation lifecycle
# ===========================================================================
def report_violation(
    program_id: str,
    *,
    severity: str = "LEVEL_II",
    violation_type: str = "IMPERMISSIBLE_BENEFIT",
    subject_type: str = "BOOSTER",
    related_athlete_id: Optional[str] = None,
    related_deal_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /violations — ComplianceOfficer or Auditor per PRD §3.7.

    PRD §3.7: recidivism multiplier counts prior SUSTAINED violations
    on the same program whose `created_at` falls STRICTLY before this
    case's `created_at`. The system clock is logical and frozen between
    /_clock/advance calls, so two violations posted in immediate
    succession will share `created_at` and the second one will not
    recognise the first as prior. We advance the clock by one second
    here so that every reported violation gets a distinct `created_at`
    timestamp — this preserves PRD's strict-before semantics while
    making the test environment exercise the recidivism rule.
    """
    headers = headers or TEST_USERS["officer_headers"]
    # Advance clock 1 second so this violation's `created_at` is
    # strictly later than any previously posted violation's.
    try:
        now_iso = server_now_iso()
        now_dt = parse_iso(now_iso)
        advance_clock_to(
            iso_utc(now_dt + timedelta(seconds=1)),
        )
    except Exception:
        # Defensive: if the clock advance fails for any reason we
        # still attempt to report the violation; the test will fail
        # with a clearer assertion downstream if it depends on
        # timestamp ordering.
        pass
    resp = api_client.create_violation(
        create_violation_payload(
            program_id=program_id,
            severity=severity,
            violation_type=violation_type,
            subject_type=subject_type,
            related_athlete_id=related_athlete_id,
            related_deal_id=related_deal_id,
        ),
        headers,
    )
    return get_success_data(resp)


def transition_violation(
    violation_id: str,
    to_status: str,
    *,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /violations/{id}/state.

    Headers default to PRIMARY officer; tests that drive the case
    through INVESTIGATING / SUBSTANTIATED / DISMISSED need the SAME
    officer (continuity of investigation per PRD §3.7), while the
    appellate transitions APPEALED->SUSTAINED/OVERTURNED need a
    DIFFERENT officer than the original reviewer.
    """
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.transition_violation(
        violation_id,
        transition_violation_payload(
            to_status=to_status, version=version,
        ),
        headers,
    )
    return get_success_data(resp)


def drive_violation_to_appealed(
    program_id: str,
    *,
    severity: str = "LEVEL_II",
    violation_type: str = "IMPERMISSIBLE_BENEFIT",
    subject_type: str = "BOOSTER",
    related_athlete_id: Optional[str] = None,
    related_deal_id: Optional[str] = None,
    reviewer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a violation and drive REPORTED -> INVESTIGATING ->
    SUBSTANTIATED -> APPEALED.

    Reviewer (INVESTIGATING through SUBSTANTIATED) is bound to
    reviewer_user_id at the REPORTED->INVESTIGATING step (PRD §3.7).
    The APPEALED transition has no segregation constraint by itself
    (PRD §3.7 lists no precondition for SUBSTANTIATED->APPEALED other
    than the 14-day window). Default reviewer is PRIMARY officer.

    Returns the violation refreshed in APPEALED state. The caller is
    expected to dispatch APPEALED -> SUSTAINED or APPEALED ->
    OVERTURNED using a DIFFERENT officer (e.g.,
    TEST_USERS["officer_headers_secondary"]).
    """
    reviewer_headers = (
        reviewer_headers or TEST_USERS["officer_headers"]
    )
    v = report_violation(
        program_id,
        severity=severity,
        violation_type=violation_type,
        subject_type=subject_type,
        related_athlete_id=related_athlete_id,
        related_deal_id=related_deal_id,
        headers=reviewer_headers,
    )
    transition_violation(
        v["id"], "INVESTIGATING", headers=reviewer_headers,
    )
    transition_violation(
        v["id"], "SUBSTANTIATED", headers=reviewer_headers,
    )
    transition_violation(
        v["id"], "APPEALED", headers=reviewer_headers,
    )
    resp = api_client.get_violation(
        v["id"], TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


def drive_violation_to_sustained(
    program_id: str,
    *,
    severity: str = "LEVEL_II",
    violation_type: str = "IMPERMISSIBLE_BENEFIT",
    subject_type: str = "BOOSTER",
    related_athlete_id: Optional[str] = None,
    related_deal_id: Optional[str] = None,
    reviewer_headers: Optional[Dict[str, str]] = None,
    appellate_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Drive REPORTED -> INVESTIGATING -> SUBSTANTIATED -> APPEALED ->
    SUSTAINED.

    PRD §3.7: "performed by a ComplianceOfficer whose X-User-ID
    differs from reviewer_user_id". reviewer_headers (default PRIMARY)
    drives the case through SUBSTANTIATED; appellate_headers (default
    SECONDARY) flips APPEALED -> SUSTAINED.

    Returns the violation refreshed in SUSTAINED state.
    """
    reviewer_headers = (
        reviewer_headers or TEST_USERS["officer_headers"]
    )
    appellate_headers = (
        appellate_headers or TEST_USERS["officer_headers_secondary"]
    )
    v = drive_violation_to_appealed(
        program_id,
        severity=severity,
        violation_type=violation_type,
        subject_type=subject_type,
        related_athlete_id=related_athlete_id,
        related_deal_id=related_deal_id,
        reviewer_headers=reviewer_headers,
    )
    transition_violation(
        v["id"], "SUSTAINED", headers=appellate_headers,
    )
    resp = api_client.get_violation(
        v["id"], TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 7: RecruitingCalendar
# ===========================================================================
def declare_calendar_window(
    program_id: str,
    *,
    period_type: str,
    start_date: str,
    end_date: str,
    note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /recruiting-calendars — ComplianceOfficer per PRD §3.1."""
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.create_recruiting_calendar(
        create_recruiting_calendar_payload(
            program_id=program_id,
            period_type=period_type,
            start_date=start_date,
            end_date=end_date,
            note=note,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 8: Difficulty-design composite fixtures
# These match SCAFFOLD_DIFFICULTY_DESIGN test_recipe.setup lines for
# instances that demand non-trivial composite state.
# ===========================================================================
def setup_program_at_penalty_threshold(
    *,
    target_points: int = 10,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Build a Program whose penalty_points_total reaches `target_points`
    via SUSTAINED violations on that program.

    Only LEVEL_I violations with no recidivism (first-offense, mult=1.0)
    score 10 points, so a single LEVEL_I yields exactly 10 (per PRD §3.7
    "Severity points are 10 for LEVEL_I" and "a count of zero yields
    multiplier 1.0"). For target_points == 10 we use one LEVEL_I.

    Returns (program, [violations]).
    """
    program = create_program(sport="FOOTBALL")
    violations: List[Dict[str, Any]] = []
    if target_points == 10:
        v = drive_violation_to_sustained(
            program["id"], severity="LEVEL_I",
        )
        violations.append(v)
    else:
        raise NotImplementedError(
            f"target_points={target_points} not yet supported"
        )
    return program, violations


def setup_ineligible_athlete_via_violation(
    program: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Bring an athlete to ENROLLED at a Program then drive a LEVEL_I
    SUSTAINED violation with related_athlete_id set, so the cascade
    flips Athlete to INELIGIBLE / amateur_status=FORFEITED.

    PRD §3.7: "When a sustained violation is LEVEL_I and carries a
    related_athlete_id, the system cascades immediately on the
    SUSTAINED outcome flip. The implicated athlete moves
    ENROLLED -> INELIGIBLE."

    Returns (program, athlete, violation), all freshly refetched.
    """
    athlete, program, _slot = setup_enrolled_athlete(program=program)
    violation = drive_violation_to_sustained(
        program["id"],
        severity="LEVEL_I",
        related_athlete_id=athlete["id"],
    )
    # Refresh athlete (cascade should have flipped it).
    a_resp = api_client.get_athlete(
        athlete["id"], TEST_USERS["officer_headers"],
    )
    athlete = get_success_data(a_resp)
    return program, athlete, violation


def setup_athlete_with_approved_deal(
    *,
    sponsor_is_booster: bool = False,
    deal_category: str = "ENDORSEMENT",
    stated_value_cents: int = 500_000,
    deliverables_hours: float = 10.0,
    market_rate_cents_per_hour: int = 50_000,
    program: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Enrolled athlete + one APPROVED NILDeal. Returns (athlete,
    program, deal)."""
    athlete, program, _slot = setup_enrolled_athlete(program=program)
    deal = setup_approved_nil_deal(
        athlete["id"],
        sponsor_is_booster=sponsor_is_booster,
        deal_category=deal_category,
        stated_value_cents=stated_value_cents,
        deliverables_hours=deliverables_hours,
        market_rate_cents_per_hour=market_rate_cents_per_hour,
    )
    return athlete, program, deal


def setup_portal_entry_in_contact_window(
    *,
    program: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Enrolled athlete -> POST /transfer-portal-entries -> advance
    clock past the 24-hour holding period so the entry auto-transitions
    to CONTACT_WINDOW.

    Returns (athlete, program, entry) where entry.status == CONTACT_WINDOW.
    """
    athlete, program, _slot = setup_enrolled_athlete(program=program)
    entry = create_portal_entry(athlete["id"])
    # PRD §3.4: "The entry sits in ENTERED for 24 hours and then
    # automatically transitions to CONTACT_WINDOW when the logical
    # clock reaches entered_at + 24 hours."
    # PRD §2.10: ENTERED -> CONTACT_WINDOW fires on clock advance.
    entered_at = parse_iso(entry["entered_at"])
    target = entered_at + timedelta(
        hours=PORTAL_HOLDING_PERIOD_HOURS, seconds=1,
    )
    advance_clock_to(iso_utc(target))
    e_resp = api_client.get_transfer_portal_entry(
        entry["id"], TEST_USERS["officer_headers"],
    )
    return athlete, program, get_success_data(e_resp)


def create_portal_entry(
    athlete_id: str,
    *,
    reason: str = "PLAYING_TIME",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /transfer-portal-entries.

    PRD §2.1 + §3.4: when posted as Athlete, X-User-ID must equal
    athlete_id. Default headers mint that identity. Passing
    officer_headers in `headers` lets a ComplianceOfficer initiate
    the entry on behalf of the athlete.
    """
    headers = headers or make_athlete_headers(athlete_id)
    resp = api_client.create_transfer_portal_entry(
        create_transfer_portal_entry_payload(
            athlete_id=athlete_id, reason=reason,
        ),
        headers,
    )
    return get_success_data(resp)


__all__ = [
    "advance_clock_to",
    "server_now_iso",
    "parse_iso",
    "create_program",
    "create_athlete",
    "create_eligibility_record",
    "offer_slot",
    "sign_slot",
    "commit_athlete",
    "enroll_athlete",
    "setup_enrolled_athlete",
    "submit_nil_deal",
    "review_nil_deal",
    "approve_nil_deal",
    "setup_approved_nil_deal",
    "report_violation",
    "transition_violation",
    "drive_violation_to_appealed",
    "drive_violation_to_sustained",
    "declare_calendar_window",
    "setup_program_at_penalty_threshold",
    "setup_ineligible_athlete_via_violation",
    "setup_athlete_with_approved_deal",
    "setup_portal_entry_in_contact_window",
    "create_portal_entry",
]
