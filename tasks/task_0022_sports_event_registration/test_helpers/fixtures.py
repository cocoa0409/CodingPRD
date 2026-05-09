"""Composite setup helpers for multi-step preconditions.

Walking the PRD's lifecycle from DRAFT all the way to COMPLETED with all
the cross-aggregate cascades in flight is too expensive to repeat in every
test. This module captures the common multi-call sequences once.

Identity threading (PRD §2.1): when a fixture creates a Referee or
Participant, ANY downstream ownership-gated call (result submission,
dispute filing, appeal filing) MUST use make_<role>_headers(entity["id"]),
not the shared TEST_USERS fallback. That is enforced here at the helper
level so tests inherit it for free.

Setup calls use get_success_data (lenient) so failed pre-conditions surface
as 'Setup failed' messages rather than confusing assertion mismatches.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .factories import (
    create_event_payload,
    create_referee_assignment_payload,
    create_referee_payload,
    custody_payload,
    decide_appeal_payload,
    file_appeal_payload,
    file_dispute_payload,
    lab_result_payload,
    open_sample_payload,
    register_participant_payload,
    resolve_dispute_payload,
    submit_result_payload,
    unique_event_name,
    unique_referee_full_name,
)
from .test_users import (
    TEST_USERS,
    make_disciplinary_headers,
    make_doping_headers,
    make_appeals_headers,
    make_organizer_headers,
    make_participant_headers,
    make_referee_headers,
)


# ===========================================================================
# Time helpers (PRD §2.11 logical clock)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def add_seconds(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(seconds=n))


def add_minutes(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(minutes=n))


def add_hours(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(hours=n))


def add_days(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(days=n))


def advance_clock(to_iso: str) -> Dict[str, Any]:
    """POST /_clock/advance with Organizer headers."""
    res = api_client.advance_clock(to_iso, TEST_USERS["organizer_headers"])
    return get_success_data(res)


def run_sweep() -> Dict[str, Any]:
    """POST /_sweep/run with Organizer headers."""
    return get_success_data(api_client.run_sweep(TEST_USERS["organizer_headers"]))


# ===========================================================================
# Tier 1: Event creation and state progression
# ===========================================================================
DEFAULT_T0 = "2030-03-01T08:00:00.000Z"


def make_event_times(
    *,
    base_iso: str = DEFAULT_T0,
    registration_window_hours: int = 24 * 7,
    starts_offset_hours: int = 24 * 14,
) -> Dict[str, str]:
    """Build a coherent (registration_opens_at, registration_closes_at,
    starts_at) triple anchored on a base instant.
    """
    opens = base_iso
    closes = add_hours(base_iso, registration_window_hours)
    starts = add_hours(base_iso, starts_offset_hours)
    return {
        "registration_opens_at": opens,
        "registration_closes_at": closes,
        "starts_at": starts,
    }


def create_event(
    *,
    name: Optional[str] = None,
    event_type: str = "ROUND_ROBIN",
    country_code: str = "ES",
    settlement_currency: str = "USD",
    capacity_min: int = 2,
    capacity_max: int = 8,
    entry_fee_cents: int = 1000,
    prize_pool_cents: int = 100_000,
    tax_withholding_pct: float = 0.0,
    base_iso: str = DEFAULT_T0,
    registration_window_hours: int = 24 * 7,
    starts_offset_hours: int = 24 * 14,
    **extra: Any,
) -> Dict[str, Any]:
    """Create an Event (DRAFT). Tests can override any field."""
    times = make_event_times(
        base_iso=base_iso,
        registration_window_hours=registration_window_hours,
        starts_offset_hours=starts_offset_hours,
    )
    payload = create_event_payload(
        name=name or unique_event_name(),
        event_type=event_type,
        country_code=country_code,
        registration_opens_at=times["registration_opens_at"],
        registration_closes_at=times["registration_closes_at"],
        starts_at=times["starts_at"],
        entry_fee_cents=entry_fee_cents,
        settlement_currency=settlement_currency,
        capacity_min=capacity_min,
        capacity_max=capacity_max,
        prize_pool_cents=prize_pool_cents,
        tax_withholding_pct=tax_withholding_pct,
        **extra,
    )
    res = api_client.create_event(payload, TEST_USERS["organizer_headers"])
    return get_success_data(res)


def open_event(event_id: str) -> Dict[str, Any]:
    res = api_client.open_event(event_id, TEST_USERS["organizer_headers"])
    return get_success_data(res)


def close_registration(event_id: str) -> Dict[str, Any]:
    res = api_client.close_registration(event_id, TEST_USERS["organizer_headers"])
    return get_success_data(res)


def draw_event(event_id: str) -> Dict[str, Any]:
    res = api_client.draw_event(event_id, TEST_USERS["organizer_headers"])
    return get_success_data(res)


def start_event(event_id: str) -> Dict[str, Any]:
    res = api_client.start_event(event_id, TEST_USERS["organizer_headers"])
    return get_success_data(res)


def complete_event(event_id: str) -> Dict[str, Any]:
    res = api_client.complete_event(event_id, TEST_USERS["organizer_headers"])
    return get_success_data(res)


def cancel_event(event_id: str) -> Dict[str, Any]:
    res = api_client.cancel_event(event_id, TEST_USERS["organizer_headers"])
    return get_success_data(res)


# ===========================================================================
# Tier 1: Participant creation
# ===========================================================================
def register_participant(
    event_id: str,
    *,
    country_code: str = "FR",
    team_code: Optional[str] = None,
    world_ranking: Optional[int] = None,
    region: str = "UEFA",
    entry_fee_paid_cents: int = 1000,
    display_name: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = register_participant_payload(
        country_code=country_code,
        team_code=team_code,
        world_ranking=world_ranking,
        region=region,
        entry_fee_paid_cents=entry_fee_paid_cents,
        display_name=display_name,
        **extra,
    )
    res = api_client.register_participant(
        event_id, payload, TEST_USERS["organizer_headers"]
    )
    return get_success_data(res)


def withdraw_participant(participant_id: str) -> Dict[str, Any]:
    res = api_client.withdraw_participant(
        participant_id, TEST_USERS["organizer_headers"]
    )
    return get_success_data(res)


# ===========================================================================
# Tier 1: Referee creation
# ===========================================================================
def create_referee(
    *,
    full_name: Optional[str] = None,
    country_code: str = "DE",
    team_affiliation: Optional[str] = None,
    qualifications: Optional[List[str]] = None,
    grade: str = "A",
    is_active: bool = True,
) -> Dict[str, Any]:
    payload = create_referee_payload(
        full_name=full_name or unique_referee_full_name(),
        country_code=country_code,
        team_affiliation=team_affiliation,
        qualifications=qualifications or ["SINGLE_ELIM", "ROUND_ROBIN", "SETS_MATCH"],
        grade=grade,
        is_active=is_active,
    )
    res = api_client.create_referee(payload, TEST_USERS["organizer_headers"])
    return get_success_data(res)


# ===========================================================================
# Tier 2: Open registration; register N participants with distinct attributes
# ===========================================================================
def event_open_for_registration(
    *,
    event_type: str = "ROUND_ROBIN",
    country_code: str = "ES",
    capacity_min: int = 2,
    capacity_max: int = 8,
    entry_fee_cents: int = 1000,
    prize_pool_cents: int = 100_000,
    tax_withholding_pct: float = 0.0,
    settlement_currency: str = "USD",
    base_iso: str = DEFAULT_T0,
    starts_offset_hours: int = 24 * 14,
) -> Dict[str, Any]:
    """Create event in DRAFT, advance clock to within registration window,
    open it.
    """
    event = create_event(
        event_type=event_type,
        country_code=country_code,
        capacity_min=capacity_min,
        capacity_max=capacity_max,
        entry_fee_cents=entry_fee_cents,
        prize_pool_cents=prize_pool_cents,
        tax_withholding_pct=tax_withholding_pct,
        settlement_currency=settlement_currency,
        base_iso=base_iso,
        starts_offset_hours=starts_offset_hours,
    )
    # Move clock to registration window start so /open's precondition holds.
    advance_clock(add_minutes(event["registration_opens_at"], 1))
    return open_event(event["id"])


def register_n_distinct_participants(
    event_id: str,
    n: int,
    *,
    countries: Optional[List[str]] = None,
    teams: Optional[List[Optional[str]]] = None,
    world_rankings: Optional[List[Optional[int]]] = None,
    regions: Optional[List[str]] = None,
    entry_fee_paid_cents: int = 1000,
) -> List[Dict[str, Any]]:
    """Register N participants with all-distinct country_codes (avoidance
    holds in the first sweep). Defaults pick a wide spread of ISO-2 codes.
    """
    if countries is None:
        pool = ["FR", "IT", "PT", "NL", "BE", "PL", "CH", "AT", "CZ", "SE",
                "NO", "DK", "FI", "IE", "HU", "BG"]
        countries = pool[:n]
    if teams is None:
        teams = [None] * n
    if world_rankings is None:
        world_rankings = list(range(1, n + 1))  # 1..n, lower = better
    if regions is None:
        regions = ["UEFA"] * n
    out: List[Dict[str, Any]] = []
    for i in range(n):
        out.append(
            register_participant(
                event_id,
                country_code=countries[i],
                team_code=teams[i],
                world_ranking=world_rankings[i],
                region=regions[i],
                entry_fee_paid_cents=entry_fee_paid_cents,
                display_name=f"Player-{i + 1}",
            )
        )
    return out


# ===========================================================================
# Tier 3: Draw + start, build a fully drawn-and-started event
# ===========================================================================
def event_drawn(
    *,
    event_type: str = "ROUND_ROBIN",
    n_participants: int = 4,
    capacity_min: int = 2,
    capacity_max: int = 8,
    countries: Optional[List[str]] = None,
    teams: Optional[List[Optional[str]]] = None,
    world_rankings: Optional[List[Optional[int]]] = None,
    base_iso: str = DEFAULT_T0,
    starts_offset_hours: int = 24 * 14,
    prize_pool_cents: int = 100_000,
    tax_withholding_pct: float = 0.0,
    settlement_currency: str = "USD",
    country_code: str = "ES",
    entry_fee_cents: int = 1000,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Open + register N + close + draw. Returns (event_after_draw, participants)."""
    event = event_open_for_registration(
        event_type=event_type,
        country_code=country_code,
        capacity_min=capacity_min,
        capacity_max=max(capacity_max, n_participants),
        entry_fee_cents=entry_fee_cents,
        prize_pool_cents=prize_pool_cents,
        tax_withholding_pct=tax_withholding_pct,
        settlement_currency=settlement_currency,
        base_iso=base_iso,
        starts_offset_hours=starts_offset_hours,
    )
    parts = register_n_distinct_participants(
        event["id"],
        n_participants,
        countries=countries,
        teams=teams,
        world_rankings=world_rankings,
        entry_fee_paid_cents=entry_fee_cents,
    )
    advance_clock(event["registration_closes_at"])
    close_registration(event["id"])
    drawn = draw_event(event["id"])
    return drawn, parts


def event_in_progress(
    **kwargs: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Open + register + close + draw + start. Returns
    (event_after_start, participants, matches).

    Each round-1 match gets a freshly-created HEAD referee (qualified for
    the event_type, distinct country and team from both participants) and
    is activated automatically by the system on first result.
    """
    drawn, parts = event_drawn(**kwargs)
    matches = list_matches(drawn["id"])
    # Assign one HEAD referee per round-1 match so /start precondition holds.
    for m in matches:
        if m["round_index"] == 1 and m["status"] != "BYE":
            ref = create_referee(
                country_code="DE",
                team_affiliation=None,
                qualifications=[drawn["event_type"]],
            )
            assign_head_referee(m["id"], ref["id"])
    advance_clock(drawn["starts_at"])
    started = start_event(drawn["id"])
    matches = list_matches(drawn["id"])
    return started, parts, matches


# ===========================================================================
# Listings used by fixtures
# ===========================================================================
def list_matches(event_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        res = api_client.list_matches(event_id, TEST_USERS["organizer_headers"],
                                      params={"limit": 100, "offset": offset})
        success_data = validate_success(res, expected_status=200)
        if not isinstance(success_data, list):
            break
        out.extend(success_data)
        if len(success_data) < 100:
            break
        offset += 100
    return out


def list_participants(event_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        res = api_client.list_participants(event_id, TEST_USERS["organizer_headers"],
                                           params={"limit": 100, "offset": offset})
        success_data = validate_success(res, expected_status=200)
        if not isinstance(success_data, list):
            break
        out.extend(success_data)
        if len(success_data) < 100:
            break
        offset += 100
    return out


def list_rankings(event_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        res = api_client.list_rankings(event_id, TEST_USERS["organizer_headers"],
                                       params={"limit": 100, "offset": offset})
        success_data = validate_success(res, expected_status=200)
        if not isinstance(success_data, list):
            break
        out.extend(success_data)
        if len(success_data) < 100:
            break
        offset += 100
    return out


def list_prize_payments(event_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        res = api_client.list_prize_payments(event_id,
                                             TEST_USERS["organizer_headers"],
                                             params={"limit": 100, "offset": offset})
        success_data = validate_success(res, expected_status=200)
        if not isinstance(success_data, list):
            break
        out.extend(success_data)
        if len(success_data) < 100:
            break
        offset += 100
    return out


def list_audit_logs(**params: Any) -> List[Dict[str, Any]]:
    """Page through /audit-logs collecting every match. PRD §4 caps `limit`
    at 100, so cumulative test state past that requires multi-page reads.
    """
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        p = {"limit": 100, "offset": offset, **params}
        res = api_client.list_audit_logs(TEST_USERS["organizer_headers"], params=p)
        success_data = validate_success(res, expected_status=200)
        if not isinstance(success_data, list):
            break
        out.extend(success_data)
        if len(success_data) < 100:
            break
        offset += 100
    return out


def list_sync_events(**params: Any) -> List[Dict[str, Any]]:
    """Page through /sync-events collecting every match. PRD §4 caps `limit`
    at 100, so cumulative test state past that requires multi-page reads.
    """
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        p = {"limit": 100, "offset": offset, **params}
        res = api_client.list_sync_events(TEST_USERS["organizer_headers"], params=p)
        success_data = validate_success(res, expected_status=200)
        if not isinstance(success_data, list):
            break
        out.extend(success_data)
        if len(success_data) < 100:
            break
        offset += 100
    return out


# ===========================================================================
# Tier 3: Referee assignment helpers
# ===========================================================================
def assign_head_referee(match_id: str, referee_id: str) -> Dict[str, Any]:
    payload = create_referee_assignment_payload(referee_id=referee_id, role="HEAD")
    res = api_client.assign_referee(
        match_id, payload, TEST_USERS["organizer_headers"]
    )
    return get_success_data(res)


def assign_assistant_referee(match_id: str, referee_id: str) -> Dict[str, Any]:
    payload = create_referee_assignment_payload(referee_id=referee_id, role="ASSISTANT")
    res = api_client.assign_referee(
        match_id, payload, TEST_USERS["organizer_headers"]
    )
    return get_success_data(res)


def activate_assignment(assignment_id: str) -> Dict[str, Any]:
    res = api_client.activate_assignment(
        assignment_id, TEST_USERS["organizer_headers"]
    )
    return get_success_data(res)


# ===========================================================================
# Tier 4: Lock a single match by submitting two cross-verifying results
# ===========================================================================
def lock_match(
    match: Dict[str, Any],
    *,
    home_score: int = 1,
    away_score: int = 0,
    home_sets_won: Optional[int] = None,
    away_sets_won: Optional[int] = None,
    event_type: str = "ROUND_ROBIN",
) -> Dict[str, Any]:
    """Create a HEAD ref + an ASSISTANT ref, advance the clock past the
    match's scheduled_end_at, submit two matching results to lock the match.
    Returns the locked Match dict.

    PRD §2.1 identity threading: result submissions are made under the
    referee role with X-User-ID = referee.id (per-instance builder).
    """
    # Ensure two distinct referees are queued (HEAD already exists from
    # event_in_progress; we only need to add an ASSISTANT).
    head_ref = create_referee(
        country_code="GR",
        team_affiliation=None,
        qualifications=[event_type],
    )
    asst_ref = create_referee(
        country_code="HR",
        team_affiliation=None,
        qualifications=[event_type],
    )
    head_asg = assign_head_referee(match["id"], head_ref["id"])
    asst_asg = assign_assistant_referee(match["id"], asst_ref["id"])
    # Move clock past match end so result submission's temporal gate holds.
    advance_clock(add_seconds(match["scheduled_end_at"], 1))
    # Two distinct submissions with identical scores -> LOCKED.
    payload1 = submit_result_payload(
        submitted_by_assignment_id=head_asg["id"],
        home_score=home_score,
        away_score=away_score,
        home_sets_won=home_sets_won,
        away_sets_won=away_sets_won,
    )
    get_success_data(api_client.submit_result(
        match["id"], payload1, make_referee_headers(head_ref["id"])
    ))
    payload2 = submit_result_payload(
        submitted_by_assignment_id=asst_asg["id"],
        home_score=home_score,
        away_score=away_score,
        home_sets_won=home_sets_won,
        away_sets_won=away_sets_won,
    )
    get_success_data(api_client.submit_result(
        match["id"], payload2, make_referee_headers(asst_ref["id"])
    ))
    # Re-list to read the locked match back.
    refreshed = [
        m for m in list_matches(match["event_id"]) if m["id"] == match["id"]
    ][0]
    return refreshed


def lock_round_1(
    event: Dict[str, Any],
    matches: List[Dict[str, Any]],
    *,
    home_score: int = 1,
    away_score: int = 0,
) -> List[Dict[str, Any]]:
    """Lock every non-BYE round-1 match with the same scores (P1 wins
    pattern by default). Returns the locked matches.
    """
    locked: List[Dict[str, Any]] = []
    for m in matches:
        if m["round_index"] == 1 and m["status"] != "BYE":
            locked.append(
                lock_match(
                    m,
                    home_score=home_score,
                    away_score=away_score,
                    event_type=event["event_type"],
                )
            )
    return locked


# ===========================================================================
# Tier 4: Lock all matches and complete the event
# ===========================================================================
def event_completed(
    *,
    event_type: str = "SINGLE_ELIM",
    n_participants: int = 4,
    countries: Optional[List[str]] = None,
    teams: Optional[List[Optional[str]]] = None,
    world_rankings: Optional[List[Optional[int]]] = None,
    base_iso: str = DEFAULT_T0,
    starts_offset_hours: int = 24 * 14,
    prize_pool_cents: int = 100_000,
    tax_withholding_pct: float = 0.0,
    settlement_currency: str = "USD",
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build, draw, start, lock-every-non-bye-match, and /complete the event.
    Returns (event_completed, participants, matches_after_complete).
    """
    started, parts, matches = event_in_progress(
        event_type=event_type,
        n_participants=n_participants,
        countries=countries,
        teams=teams,
        world_rankings=world_rankings,
        base_iso=base_iso,
        starts_offset_hours=starts_offset_hours,
        prize_pool_cents=prize_pool_cents,
        tax_withholding_pct=tax_withholding_pct,
        settlement_currency=settlement_currency,
    )
    # Iteratively lock all non-bye matches in the live bracket. Locking a
    # round-1 match may create round-2 matches; we re-list each round.
    while True:
        live = list_matches(started["id"])
        unlocked = [m for m in live if m["status"] in {"SCHEDULED", "RESULT_PENDING"}
                    and m["status"] != "BYE"
                    and m.get("home_participant_id")
                    and m.get("away_participant_id")]
        if not unlocked:
            break
        for m in unlocked:
            # Default: home (higher seed) wins.
            if started["event_type"] == "SETS_MATCH":
                lock_match(
                    m,
                    home_score=2,
                    away_score=1,
                    home_sets_won=2,
                    away_sets_won=1,
                    event_type=started["event_type"],
                )
            else:
                lock_match(
                    m,
                    home_score=2,
                    away_score=1,
                    event_type=started["event_type"],
                )
    completed = complete_event(started["id"])
    return completed, parts, list_matches(completed["id"])


# ===========================================================================
# Tier 5: Doping flow (sample → custody → result)
# ===========================================================================
def open_doping_sample(
    event_id: str,
    participant_id: str,
    *,
    collected_at: Optional[str] = None,
) -> Dict[str, Any]:
    res = api_client.open_sample(
        event_id,
        open_sample_payload(
            participant_id=participant_id,
            collected_at=collected_at or "2030-04-01T10:00:00.000Z",
        ),
        TEST_USERS["doping_headers"],
    )
    return get_success_data(res)


def custody_dispatch(sample_id: str, at: str,
                     officer_id: str = "dop-001") -> Dict[str, Any]:
    res = api_client.append_custody(
        sample_id,
        custody_payload(action="DISPATCH", at=at),
        make_doping_headers(officer_id),
    )
    return get_success_data(res)


def custody_receive(sample_id: str, at: str,
                    officer_id: str = "dop-001") -> Dict[str, Any]:
    res = api_client.append_custody(
        sample_id,
        custody_payload(action="RECEIVE", at=at),
        make_doping_headers(officer_id),
    )
    return get_success_data(res)


def submit_lab_result(sample_id: str, *, positive: bool,
                      officer_id: str = "dop-002") -> Dict[str, Any]:
    """Submit lab result. PRD §3.7 segregation of duties: officer_id MUST
    differ from the officer who appended the RECEIVE custody entry.
    """
    res = api_client.submit_lab_result(
        sample_id,
        lab_result_payload(positive=positive),
        make_doping_headers(officer_id),
    )
    return get_success_data(res)


def positive_doping_for(
    event_id: str,
    participant_id: str,
    *,
    base_iso: str = "2030-04-01T10:00:00.000Z",
) -> Dict[str, Any]:
    """End-to-end: open sample, dispatch, receive (officer A), result
    positive (officer B — distinct, satisfies segregation). Returns the
    POSITIVE DopingSample.
    """
    sample = open_doping_sample(event_id, participant_id, collected_at=base_iso)
    custody_dispatch(sample["id"], add_minutes(base_iso, 5), officer_id="dop-001")
    custody_receive(sample["id"], add_minutes(base_iso, 60), officer_id="dop-001")
    return submit_lab_result(sample["id"], positive=True, officer_id="dop-002")


def negative_doping_for(
    event_id: str,
    participant_id: str,
    *,
    base_iso: str = "2030-04-01T10:00:00.000Z",
) -> Dict[str, Any]:
    sample = open_doping_sample(event_id, participant_id, collected_at=base_iso)
    custody_dispatch(sample["id"], add_minutes(base_iso, 5), officer_id="dop-001")
    custody_receive(sample["id"], add_minutes(base_iso, 60), officer_id="dop-001")
    return submit_lab_result(sample["id"], positive=False, officer_id="dop-002")


# ===========================================================================
# Sanction / appeal helpers
# ===========================================================================
def get_sanction_for_sample(sample_id: str) -> Optional[Dict[str, Any]]:
    """Find the SanctionRecord auto-created by a positive sample.
    PRD §3.7 says it carries sample_id == sample.id. There's no list
    endpoint, so this function relies on /audit-logs SANCTION_CHANGE rows
    to discover the sanction id when needed.
    """
    rows = list_audit_logs(kind="SANCTION_CHANGE", subject_kind="SANCTION_RECORD",
                           limit=100)
    # Caller is expected to know the sanction_id from a side channel,
    # since there is no list endpoint per PRD §4. Helpers below take the
    # sanction id directly.
    return rows[-1] if rows else None


def file_appeal(sanction_id: str, participant_id: str,
                ground_text: str = "Procedural error.") -> Dict[str, Any]:
    """File an Appeal as the sanctioned participant. PRD §2.1 + §3.8:
    X-User-ID must equal SanctionRecord.participant_id == participant_id.
    """
    res = api_client.file_appeal(
        file_appeal_payload(sanction_id=sanction_id, ground_text=ground_text),
        make_participant_headers(participant_id),
    )
    return get_success_data(res)


def decide_appeal(appeal_id: str, *, uphold: bool) -> Dict[str, Any]:
    res = api_client.decide_appeal(
        appeal_id,
        decide_appeal_payload(uphold=uphold),
        TEST_USERS["appeals_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Dispute helpers (Participant identity threading)
# ===========================================================================
def file_dispute(match_id: str, participant_id: str,
                 reason: str = "Score appears miscounted.") -> Dict[str, Any]:
    """File a Dispute as the participant. PRD §2.1 + §3.4: X-User-ID must
    equal Dispute.filed_by_participant_id == participant_id.
    """
    res = api_client.file_dispute(
        match_id,
        file_dispute_payload(filed_by_participant_id=participant_id,
                             reason_text=reason),
        make_participant_headers(participant_id),
    )
    return get_success_data(res)


def resolve_dispute_uphold(
    dispute_id: str,
    *,
    corrected_home_score: int,
    corrected_away_score: int,
    corrected_home_sets_won: Optional[int] = None,
    corrected_away_sets_won: Optional[int] = None,
) -> Dict[str, Any]:
    payload = resolve_dispute_payload(
        uphold=True,
        corrected_home_score=corrected_home_score,
        corrected_away_score=corrected_away_score,
        corrected_home_sets_won=corrected_home_sets_won,
        corrected_away_sets_won=corrected_away_sets_won,
    )
    res = api_client.resolve_dispute(
        dispute_id, payload, TEST_USERS["disciplinary_headers"]
    )
    return get_success_data(res)


def resolve_dispute_reject(dispute_id: str) -> Dict[str, Any]:
    payload = resolve_dispute_payload(uphold=False)
    res = api_client.resolve_dispute(
        dispute_id, payload, TEST_USERS["disciplinary_headers"]
    )
    return get_success_data(res)


# ===========================================================================
# Composite scenario builders for difficulty-design test recipes
# ===========================================================================
def setup_round_robin_4_with_complete(
    *,
    base_iso: str = DEFAULT_T0,
    prize_pool_cents: int = 10_000,
    tax_withholding_pct: float = 0.0,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Difficulty Rule 1 instance 1 setup:
    ROUND_ROBIN of 4 participants P1..P4 with distinct teams, distinct
    countries, distinct world rankings. /draw, /start, lock all 6 matches
    so P1>P2>P3>P4 in the standings, /complete.
    """
    return event_completed(
        event_type="ROUND_ROBIN",
        n_participants=4,
        countries=["FR", "IT", "PT", "NL"],
        teams=["TFR", "TIT", "TPT", "TNL"],
        world_rankings=[1, 2, 3, 4],
        base_iso=base_iso,
        prize_pool_cents=prize_pool_cents,
        tax_withholding_pct=tax_withholding_pct,
        settlement_currency="USD",
    )


def setup_single_elim_8_with_complete(
    *,
    prize_pool_cents: int = 10003,
    tax_withholding_pct: float = 10.0,
    base_iso: str = DEFAULT_T0,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """SINGLE_ELIM of 8 distinct participants A..H, full bracket locked
    such that A wins. /complete generates PrizePayment rows.
    """
    return event_completed(
        event_type="SINGLE_ELIM",
        n_participants=8,
        countries=["FR", "IT", "PT", "NL", "BE", "PL", "CH", "AT"],
        teams=["TFR", "TIT", "TPT", "TNL", "TBE", "TPL", "TCH", "TAT"],
        world_rankings=[1, 2, 3, 4, 5, 6, 7, 8],
        base_iso=base_iso,
        prize_pool_cents=prize_pool_cents,
        tax_withholding_pct=tax_withholding_pct,
        settlement_currency="USD",
    )


def setup_event_completed_with_payments(
    *,
    prize_pool_cents: int = 10_000,
    tax_withholding_pct: float = 0.0,
    settlement_currency: str = "USD",
    n_participants: int = 8,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]],
          List[Dict[str, Any]]]:
    """SINGLE_ELIM with N participants → COMPLETED → PrizePayment rows
    listed. Returns (event, participants, matches, prize_payments).
    """
    completed, parts, matches = event_completed(
        event_type="SINGLE_ELIM",
        n_participants=n_participants,
        countries=["FR", "IT", "PT", "NL", "BE", "PL", "CH", "AT",
                   "CZ", "SE", "NO", "DK", "FI", "IE", "HU", "BG"][:n_participants],
        teams=[f"T{c}" for c in
               ["FR", "IT", "PT", "NL", "BE", "PL", "CH", "AT",
                "CZ", "SE", "NO", "DK", "FI", "IE", "HU", "BG"][:n_participants]],
        world_rankings=list(range(1, n_participants + 1)),
        prize_pool_cents=prize_pool_cents,
        tax_withholding_pct=tax_withholding_pct,
        settlement_currency=settlement_currency,
    )
    payments = list_prize_payments(completed["id"])
    return completed, parts, matches, payments


def find_participant_by_seed(participants: List[Dict[str, Any]],
                              seed: int) -> Optional[Dict[str, Any]]:
    for p in participants:
        if p.get("bracket_seed") == seed:
            return p
    return None


def find_participant_by_rank(participants: List[Dict[str, Any]],
                              rank: int) -> Optional[Dict[str, Any]]:
    for p in participants:
        if p.get("final_rank") == rank:
            return p
    return None


def find_payment_for_participant(payments: List[Dict[str, Any]],
                                  participant_id: str) -> Optional[Dict[str, Any]]:
    for pp in payments:
        if pp.get("participant_id") == participant_id:
            return pp
    return None


def get_participant(event_id: str, participant_id: str) -> Dict[str, Any]:
    """Re-fetch a single participant from /events/{event_id}/participants."""
    parts = list_participants(event_id)
    for p in parts:
        if p["id"] == participant_id:
            return p
    raise AssertionError(
        f"Setup failed: participant {participant_id} not visible in event {event_id}"
    )


def get_event(event_id: str) -> Dict[str, Any]:
    res = api_client.get_event(event_id, TEST_USERS["organizer_headers"])
    return get_success_data(res)


def get_sanction(sanction_id: str) -> Dict[str, Any]:
    res = api_client.get_sanction(sanction_id, TEST_USERS["disciplinary_headers"])
    return get_success_data(res)


def get_match(event_id: str, match_id: str) -> Dict[str, Any]:
    for m in list_matches(event_id):
        if m["id"] == match_id:
            return m
    raise AssertionError(f"Setup failed: match {match_id} not visible")


# ===========================================================================
# Helper: locate the SanctionRecord that resulted from a positive sample.
#
# PRD §3.7 says the auto-created sanction carries sample_id == sample.id;
# the only way to obtain its id from public API is via the AuditLog row
# the cascade writes (kind=SANCTION_CHANGE, subject_kind=SANCTION_RECORD).
# After the audit row is found, a GET /sanctions/{id} confirms the body.
# ===========================================================================
def latest_sanction_for_sample(sample_id: str) -> Dict[str, Any]:
    rows = list_audit_logs(kind="SANCTION_CHANGE", subject_kind="SANCTION_RECORD",
                           limit=100)
    # Walk the audit rows newest-first and inspect each candidate sanction.
    for row in reversed(rows):
        sanction_id = row["subject_id"]
        try:
            sanction = get_sanction(sanction_id)
        except Exception:
            continue
        if sanction.get("sample_id") == sample_id:
            return sanction
    raise AssertionError(
        f"Setup failed: no sanction discovered for sample_id={sample_id}"
    )


__all__ = [
    # time helpers
    "iso_z", "parse_iso", "add_seconds", "add_minutes", "add_hours", "add_days",
    "advance_clock", "run_sweep", "make_event_times", "DEFAULT_T0",
    # state progression
    "create_event", "open_event", "close_registration", "draw_event",
    "start_event", "complete_event", "cancel_event",
    "register_participant", "withdraw_participant",
    "create_referee",
    # listings
    "list_matches", "list_participants", "list_rankings",
    "list_prize_payments", "list_audit_logs", "list_sync_events",
    # composite
    "event_open_for_registration",
    "register_n_distinct_participants",
    "event_drawn", "event_in_progress", "event_completed",
    "lock_match", "lock_round_1",
    "assign_head_referee", "assign_assistant_referee", "activate_assignment",
    # doping
    "open_doping_sample", "custody_dispatch", "custody_receive",
    "submit_lab_result", "positive_doping_for", "negative_doping_for",
    # sanctions / appeals / disputes
    "file_appeal", "decide_appeal",
    "file_dispute", "resolve_dispute_uphold", "resolve_dispute_reject",
    # difficulty-design composites
    "setup_round_robin_4_with_complete",
    "setup_single_elim_8_with_complete",
    "setup_event_completed_with_payments",
    # lookups
    "find_participant_by_seed", "find_participant_by_rank",
    "find_payment_for_participant",
    "get_participant", "get_event", "get_sanction", "get_match",
    "latest_sanction_for_sample",
]
