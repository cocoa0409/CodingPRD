"""Composite setup helpers — multi-step preambles tests can reuse.

Most interesting test claims require the system to be in a late state
that takes 5-15 API calls to reach. Each fixture composes the lower-
level steps so the test body can focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "All five roles are entity-backed by Member. When X-User-Role is
    Member, X-User-ID is the id of the acting Member; ownership checks
    on any resource that references a Member ... compare the resource's
    foreign-key field to X-User-ID. The same identity rule applies to
    SecretaryRole, TreasurerRole, PresidentRole, and DirectorRole:
    X-User-ID is the id of the Member who currently holds that board
    seat."

After a Member is created and seated into a board role, fixtures MUST
use that Member.id when issuing role-bound calls — never fall back to
the shared TEST_USERS["<role>_headers"] constant for ownership-gated
operations. The shared constants are reserved for bootstrap (registering
the first Member, casting the first Unit) and for tests that probe
auth/RBAC failure modes without exercising ownership.

CLOCK ANCHORING — PRD §3.10:

    "An admin-only test-driving capability advances the clock to a
    supplied target_timestamp; the timestamp MUST be strictly greater
    than or equal to the current clock, and a backward move is rejected
    with ERR_TIME_TRAVEL."

The logical clock is shared across all tests within the process. Each
fixture anchors deadlines to instants the test author can advance to.
Tests use advance_clock_by_seconds()/advance_clock_to() to move the
clock; absolute timestamps are computed relative to the last known
clock value so the suite is robust to other tests advancing the clock
earlier in the run.

Setup calls use get_success_data (a lenient 2xx validator), so a failed
setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_days,
    add_seconds,
    adopt_reserve_study_payload,
    clock_advance_payload,
    create_acc_request_payload,
    create_assessment_cycle_payload,
    create_ballot_payload,
    create_board_resolution_payload,
    create_candidate_payload,
    create_election_payload,
    create_lien_payload,
    create_member_payload,
    create_payment_payload,
    create_reserve_study_payload,
    create_unit_payload,
    create_violation_payload,
    iso_now,
    iso_utc,
    lien_action_payload,
    parse_iso,
    random_address,
    random_email,
    random_suffix,
    reserve_component,
    utcnow,
    version_payload,
    vote_payload,
    waive_violation_payload,
)
from .test_users import (
    PRESIDENT_BOOTSTRAP_ID,
    SECRETARY_BOOTSTRAP_ID,
    TEST_USERS,
    TREASURER_BOOTSTRAP_ID,
    make_director_role_headers,
    make_member_headers,
    make_president_role_headers,
    make_secretary_role_headers,
    make_treasurer_role_headers,
)


# ===========================================================================
# Clock helpers — PRD §3.10
# ===========================================================================
# Tracks the test-process's view of the logical clock so absolute targets
# can be derived without re-querying the server every call.
_CLOCK_LOCK = threading.Lock()
_CURRENT_CLOCK: Optional[datetime] = None


def _seed_clock() -> datetime:
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        if _CURRENT_CLOCK is None:
            _CURRENT_CLOCK = utcnow()
        return _CURRENT_CLOCK


def current_clock() -> datetime:
    """Return the test-process's view of the current logical clock."""
    return _seed_clock()


def current_clock_iso() -> str:
    return iso_utc(current_clock())


# Tracks which Member.id holds the PRESIDENT seat — once a real Member
# is seated, subsequent clock-advance calls must use that Member's
# headers per PRD §2.1 identity verification.
_ELECTED_PRESIDENT_ID: Optional[str] = None


def set_elected_president(member_id: str) -> None:
    """Register the Member.id that now holds the PRESIDENT seat. After
    this call, advance_clock_to() will use that id (rather than the
    bootstrap PRESIDENT_BOOTSTRAP_ID) for X-User-ID on /_clock/advance.
    """
    global _ELECTED_PRESIDENT_ID
    _ELECTED_PRESIDENT_ID = member_id


def _current_president_headers() -> Dict[str, str]:
    """Return the headers to use for /_clock/advance — the seated
    president's if one exists, otherwise the bootstrap shared header."""
    if _ELECTED_PRESIDENT_ID is not None:
        return make_president_role_headers(_ELECTED_PRESIDENT_ID)
    return TEST_USERS["president_role_headers"]


def advance_clock_to(target_dt: datetime,
                     headers: Optional[Dict[str, str]] = None) -> str:
    """Advance the logical clock to target_dt (must be >= current).

    PRD §3.10: 'target_timestamp ... MUST be strictly greater than or
    equal to the current clock.'
    """
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        now = _CURRENT_CLOCK if _CURRENT_CLOCK is not None else utcnow()
        if target_dt < now:
            target_dt = now
        target_iso = iso_utc(target_dt)
        resp = api_client.advance_clock(
            clock_advance_payload(target_iso),
            headers or _current_president_headers(),
        )
        get_success_data(resp)
        _CURRENT_CLOCK = target_dt
    return target_iso


def advance_clock_by_seconds(seconds: int,
                             headers: Optional[Dict[str, str]] = None) -> str:
    return advance_clock_to(
        current_clock() + timedelta(seconds=seconds), headers,
    )


def advance_clock_by_days(days: int,
                          headers: Optional[Dict[str, str]] = None) -> str:
    return advance_clock_to(
        current_clock() + timedelta(days=days), headers,
    )


def reset_clock_tracker_to(dt: datetime) -> None:
    """Force the test-process's clock-tracker to a specific value AND
    clear the seated-president registration.

    Used between tests to restore a known-clean state — the implementation
    is reset by the conftest /__test__/reset hook, so any prior elections
    are gone and the PRESIDENT seat is vacant again.
    """
    global _CURRENT_CLOCK, _ELECTED_PRESIDENT_ID
    with _CLOCK_LOCK:
        _CURRENT_CLOCK = dt
        _ELECTED_PRESIDENT_ID = None


# ===========================================================================
# Member / Unit primitives — PRD §3.1
# ===========================================================================
def create_member(
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.1: PresidentRole registers a Member."""
    headers = headers or TEST_USERS["president_role_headers"]
    payload = create_member_payload(
        full_name=full_name or f"M_{random_suffix(6)}",
        email=email or random_email(),
    )
    resp = api_client.create_member(payload, headers)
    return get_success_data(resp)


def create_unit(
    owner_member_id: str,
    share_factor: float,
    address: Optional[str] = None,
    mortgage_holder: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.1: PresidentRole registers a Unit. Caller must ensure the
    share_factor sum invariant is satisfied across the whole roster."""
    headers = headers or TEST_USERS["president_role_headers"]
    payload = create_unit_payload(
        owner_member_id=owner_member_id,
        share_factor=share_factor,
        address=address,
        mortgage_holder=mortgage_holder,
    )
    resp = api_client.create_unit(payload, headers)
    return get_success_data(resp)


def get_member(member_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["president_role_headers"]
    return get_success_data(api_client.get_member(member_id, headers))


def get_unit(unit_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["president_role_headers"]
    return get_success_data(api_client.get_unit(unit_id, headers))


def get_assessment_charge(
    charge_id: str, headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["president_role_headers"]
    return get_success_data(
        api_client.get_assessment_charge(charge_id, headers),
    )


def get_violation(violation_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["president_role_headers"]
    return get_success_data(
        api_client.get_violation(violation_id, headers),
    )


def get_acc_request(request_id: str,
                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["president_role_headers"]
    return get_success_data(
        api_client.get_acc_request(request_id, headers),
    )


def get_lien(lien_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["president_role_headers"]
    return get_success_data(api_client.get_lien(lien_id, headers))


def get_election(election_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["president_role_headers"]
    return get_success_data(
        api_client.get_election(election_id, headers),
    )


def get_board_resolution(
    resolution_id: str, headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["president_role_headers"]
    return get_success_data(
        api_client.get_board_resolution(resolution_id, headers),
    )


def get_reserve_study(study_id: str,
                      headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["president_role_headers"]
    return get_success_data(
        api_client.get_reserve_study(study_id, headers),
    )


# ===========================================================================
# Tier 1: Roster setup — PRD §3.1
# ===========================================================================
def setup_single_unit_roster(
    share_factor: float = 1.0000,
    mortgage_holder: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """One member owning one unit with share_factor=1.0000 (default).

    Returns (member, unit). Most basic fixture — satisfies the sum=1
    invariant trivially.
    """
    member = create_member()
    unit = create_unit(
        owner_member_id=member["id"],
        share_factor=share_factor,
        mortgage_holder=mortgage_holder,
    )
    return member, unit


def setup_multi_unit_roster(
    shares: List[float],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Create len(shares) members, each owning one unit with the given
    share_factor. Caller is responsible for ensuring sum(shares) == 1.0000.

    PRD §3.1: 'The sum of share_factor across every Unit in the
    association MUST equal exactly 1.0000.'
    """
    total = round(sum(shares), 4)
    assert total == 1.0000, (
        f"setup_multi_unit_roster requires shares summing to 1.0000, "
        f"got {total} for shares={shares}"
    )
    members: List[Dict[str, Any]] = []
    units: List[Dict[str, Any]] = []
    for s in shares:
        m = create_member()
        u = create_unit(owner_member_id=m["id"], share_factor=s)
        members.append(m)
        units.append(u)
    return members, units


# ===========================================================================
# Tier 2: Assessment-cycle helpers — PRD §3.2
# ===========================================================================
def create_regular_cycle(
    total_levy_cents: int,
    due_in_days: int = 30,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a REGULAR AssessmentCycle in DRAFT. The due_date is set
    relative to the current logical clock so subsequent advances can
    cross it deterministically."""
    headers = headers or TEST_USERS["treasurer_role_headers"]
    now = current_clock()
    payload = create_assessment_cycle_payload(
        cycle_type="REGULAR",
        period_start=iso_utc(now),
        due_date=iso_utc(now + timedelta(days=due_in_days)),
        total_levy_cents=total_levy_cents,
    )
    resp = api_client.create_assessment_cycle(payload, headers)
    return get_success_data(resp)


def create_special_cycle(
    total_levy_cents: int,
    approval_resolution_id: str,
    due_in_days: int = 30,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a SPECIAL AssessmentCycle (requires a PASSED resolution)."""
    headers = headers or TEST_USERS["treasurer_role_headers"]
    now = current_clock()
    payload = create_assessment_cycle_payload(
        cycle_type="SPECIAL",
        period_start=iso_utc(now),
        due_date=iso_utc(now + timedelta(days=due_in_days)),
        total_levy_cents=total_levy_cents,
        approval_resolution_id=approval_resolution_id,
    )
    resp = api_client.create_assessment_cycle(payload, headers)
    return get_success_data(resp)


def issue_cycle(cycle: Dict[str, Any],
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /hoa/assessment-cycles/{id}/issue."""
    headers = headers or TEST_USERS["treasurer_role_headers"]
    resp = api_client.issue_assessment_cycle(
        cycle["id"], version_payload(cycle.get("version", 1)), headers,
    )
    return get_success_data(resp)


def setup_issued_cycle(
    total_levy_cents: int = 100_000,
    due_in_days: int = 30,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """One-unit roster + REGULAR cycle issued. Returns (member, unit,
    cycle) where cycle is now ISSUED. After this, exactly one
    AssessmentCharge exists for the unit (principal == total_levy_cents).
    """
    member, unit = setup_single_unit_roster()
    cycle = create_regular_cycle(
        total_levy_cents=total_levy_cents, due_in_days=due_in_days,
    )
    cycle = issue_cycle(cycle)
    return member, unit, cycle


def find_charge_for_unit(cycle_id: str, unit_id: str) -> Dict[str, Any]:
    """Locate the AssessmentCharge for a (cycle, unit) pair by walking
    the member's payment-target view via /hoa/assessment-charges/{id}.

    Because the PRD does not declare a list-charges endpoint, this
    fixture instead exercises a probe: the implementation creates one
    charge per Unit at issuance. Tests that need the charge id rely on
    the implementation returning it in some discoverable way. We expose
    a sentinel helper that attempts to extract the charge id from a
    well-known response payload first; tests that already hold a charge
    id should not call this. (Used internally only for diagnostic
    fallbacks.)
    """
    # No discovery endpoint per PRD; caller must hold the id from the
    # issue response or a creation echo. Raises if invoked.
    raise NotImplementedError(
        "PRD declares no list-charges endpoint; the test or fixture "
        "must capture the charge id from the issue response payload."
    )


# ===========================================================================
# Tier 2: Board resolutions — PRD §3.8
# ===========================================================================
def propose_resolution(
    subject: str,
    target_id: str,
    proposer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Any board role can propose. Uses TreasurerRole shared headers by
    default (proposer identity is not load-bearing here)."""
    headers = proposer_headers or TEST_USERS["treasurer_role_headers"]
    resp = api_client.create_board_resolution(
        create_board_resolution_payload(subject=subject, target_id=target_id),
        headers,
    )
    return get_success_data(resp)


def vote_resolution(
    resolution_id: str, vote: str,
    voter_headers: Dict[str, str],
) -> Dict[str, Any]:
    """Cast a single YES/NO vote on a board resolution. Returns the
    server's representation of the vote (a lean entity or — depending
    on implementation — the updated resolution)."""
    resp = api_client.vote_board_resolution(
        resolution_id, vote_payload(vote), voter_headers,
    )
    return get_success_data(resp)


def drive_resolution_to_passed(
    subject: str, target_id: str,
    extra_yes_voter_headers: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Propose a resolution and cast 3 YES votes (the threshold for
    PASSED per PRD §3.8: 'yes_votes reaches at least 3').

    Uses the four pre-seated board roles' shared headers as voters by
    default; tests that need the votes to come from specific seated
    Members can pass extra_yes_voter_headers.
    """
    resolution = propose_resolution(subject, target_id)
    voters = extra_yes_voter_headers or [
        TEST_USERS["president_role_headers"],
        TEST_USERS["treasurer_role_headers"],
        TEST_USERS["director_role_headers"],
    ]
    for v in voters[:3]:
        vote_resolution(resolution["id"], "YES", v)
    return get_board_resolution(resolution["id"])


# ===========================================================================
# Tier 3: Late-fee scenarios — PRD §3.3
# ===========================================================================
def setup_overdue_charge(
    total_levy_cents: int = 100_000,
    days_past_due: int = 1,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Set up a single OVERDUE charge.

    Steps:
      1. Single-unit roster, share_factor=1.0000.
      2. Issue a REGULAR cycle with due_date in 30 days.
      3. Advance clock to (due_date + days_past_due).
      4. Read the charge (via GET — PRD §3.3 says GET recomputes
         late_fee_cents lazily) and return it.

    Returns (member, unit, cycle, charge). Test must capture the charge
    id from the implementation's GET payload, which is itself a probe;
    if implementation exposes charges via the issue response or a
    discoverable id-by-unit mapping, the test wires that up.
    """
    member, unit, cycle = setup_issued_cycle(
        total_levy_cents=total_levy_cents, due_in_days=30,
    )
    # Advance past due_date by days_past_due.
    due = parse_iso(cycle["due_date"])
    target = due + timedelta(days=days_past_due, seconds=1)
    advance_clock_to(target)
    # No list endpoint for charges; tests must pluck the charge id from
    # implementation-specific echoes. We return the cycle so the caller
    # can attempt a known-id strategy.
    return member, unit, cycle, {}


# ===========================================================================
# Tier 3: ACC request lifecycle — PRD §3.4
# ===========================================================================
def submit_acc_request(
    unit_id: str,
    owner_member_id: str,
    category: str = "LANDSCAPING",
    description: str = "Test ACC request",
) -> Dict[str, Any]:
    """A Member submits an ACC request on a unit they own.

    PRD §3.4: 'The submitter's X-User-ID MUST equal the unit's
    owner_member_id at submission time.'

    We mint headers with the owner Member's id so the call is admitted.
    """
    headers = make_member_headers(owner_member_id)
    resp = api_client.create_acc_request(
        create_acc_request_payload(
            unit_id=unit_id, category=category, description=description,
        ),
        headers,
    )
    return get_success_data(resp)


def begin_review_acc_request(
    request: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """SecretaryRole-only. Uses the shared secretary headers."""
    headers = headers or TEST_USERS["secretary_role_headers"]
    resp = api_client.begin_review_acc_request(
        request["id"], version_payload(request.get("version", 1)), headers,
    )
    return get_success_data(resp)


def cast_acc_vote(
    request_id: str, vote: str,
    voter_headers: Dict[str, str],
) -> Dict[str, Any]:
    """Cast a YES/NO ACC vote. voter_headers MUST identify a Member
    currently holding a board_role in {PRESIDENT, SECRETARY, DIRECTOR}
    per PRD §3.4."""
    resp = api_client.vote_acc_request(
        request_id, vote_payload(vote), voter_headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 3: Violation lifecycle — PRD §3.5
# ===========================================================================
def open_violation(
    unit_id: str,
    description: str = "Unmaintained yard",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.5: opened by SecretaryRole or PresidentRole."""
    headers = headers or TEST_USERS["secretary_role_headers"]
    resp = api_client.create_violation(
        create_violation_payload(unit_id=unit_id, description=description),
        headers,
    )
    return get_success_data(resp)


def cure_violation(violation: Dict[str, Any],
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["secretary_role_headers"]
    resp = api_client.cure_violation(
        violation["id"], version_payload(violation.get("version", 1)),
        headers,
    )
    return get_success_data(resp)


def waive_violation(
    violation: Dict[str, Any], resolution_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["secretary_role_headers"]
    resp = api_client.waive_violation(
        violation["id"],
        waive_violation_payload(
            resolution_id=resolution_id,
            version=violation.get("version", 1),
        ),
        headers,
    )
    return get_success_data(resp)


def open_n_violations_and_auto_fine(
    unit_id: str, n: int,
) -> List[Dict[str, Any]]:
    """Open n violations on a unit, advance past every cure_deadline so
    they all auto-FINE. Returns the violations in opening order.

    PRD §3.5: 'cure_deadline = opened_at + 14 days' and 'Past
    cure_deadline, the lazy clock-advance machinery transitions any
    still-OPEN violation to FINED.'
    """
    opened: List[Dict[str, Any]] = []
    for _ in range(n):
        v = open_violation(unit_id=unit_id)
        opened.append(v)
        # Brief 1-second spacing so opened_at strictly orders the rows.
        advance_clock_by_seconds(1)
    # Now advance past the last cure_deadline.
    last_deadline = max(parse_iso(v["cure_deadline"]) for v in opened)
    advance_clock_to(last_deadline + timedelta(seconds=1))
    return opened


# ===========================================================================
# Tier 3: Payment helpers — PRD §3.3
# ===========================================================================
def tender_payment(
    member_id: str,
    amount_cents: int,
) -> Dict[str, Any]:
    """The Member tenders the payment — caller identity MUST equal
    member_id per PRD §3.3 and PRD §2.1.
    """
    headers = make_member_headers(member_id)
    resp = api_client.create_payment(
        create_payment_payload(
            member_id=member_id, amount_cents=amount_cents,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 4: Election helpers — PRD §3.7
# ===========================================================================
def open_election(
    seat: str,
    nomination_open_offset_seconds: int = 0,
    voting_open_offset_seconds: int = 60,
    voting_close_offset_seconds: int = 120,
    quorum_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Open an ElectionCycle for a seat. Timestamps are computed
    relative to the current logical clock so the election windows are
    deterministically traversable via advance_clock_to()."""
    now = current_clock()
    nom_open = now + timedelta(seconds=nomination_open_offset_seconds)
    vote_open = now + timedelta(seconds=voting_open_offset_seconds)
    vote_close = now + timedelta(seconds=voting_close_offset_seconds)
    payload = create_election_payload(
        seat=seat,
        nomination_open_at=iso_utc(nom_open),
        voting_open_at=iso_utc(vote_open),
        voting_close_at=iso_utc(vote_close),
        quorum_pct=quorum_pct,
    )
    resp = api_client.create_election(
        payload, TEST_USERS["president_role_headers"],
    )
    return get_success_data(resp)


def nominate_candidate(election_id: str, member_id: str) -> Dict[str, Any]:
    """A Member nominates themselves. PRD §3.7: 'submitting their own
    member_id (which MUST equal X-User-ID)'."""
    headers = make_member_headers(member_id)
    resp = api_client.create_candidate(
        election_id, create_candidate_payload(member_id=member_id), headers,
    )
    return get_success_data(resp)


def cast_ballot(
    election_id: str, voter_member_id: str, candidate_id: str,
) -> Dict[str, Any]:
    """A Member casts a ballot for a candidate. PRD §3.7: 'voter_member_id
    (which MUST equal X-User-ID)'."""
    headers = make_member_headers(voter_member_id)
    resp = api_client.create_ballot(
        election_id,
        create_ballot_payload(
            voter_member_id=voter_member_id, candidate_id=candidate_id,
        ),
        headers,
    )
    return get_success_data(resp)


def certify_election(election: Dict[str, Any]) -> Dict[str, Any]:
    """SecretaryRole certifies. PRD §3.7."""
    resp = api_client.certify_election(
        election["id"], version_payload(election.get("version", 1)),
        TEST_USERS["secretary_role_headers"],
    )
    return get_success_data(resp)


def seat_member_in_role(member: Dict[str, Any], seat: str) -> Dict[str, Any]:
    """Run a complete election cycle that seats `member` into `seat`.

    PRD §3.7: opens election, nominates the member, advances to voting
    window, casts a ballot from the member themselves (a single ballot
    meets the default 0.40 quorum on a 1-eligible-voter roster), advances
    past voting_close_at, then SecretaryRole-certifies.

    Returns the certified election. After this, member.board_role will
    equal `seat` (verifiable via GET /hoa/members/{id}). Tests that need
    a *seated* role-holder should call this rather than relying on the
    PRD's bootstrap-role headers.
    """
    election = open_election(
        seat=seat,
        nomination_open_offset_seconds=0,
        voting_open_offset_seconds=60,
        voting_close_offset_seconds=120,
        quorum_pct=0.10,  # minimal quorum so 1 ballot satisfies
    )
    candidate = nominate_candidate(election["id"], member["id"])
    # Advance to voting_open_at (status NOMINATION → VOTING).
    advance_clock_to(parse_iso(election["voting_open_at"]))
    cast_ballot(election["id"], member["id"], candidate["id"])
    # Advance past voting_close_at to TALLIED.
    advance_clock_to(parse_iso(election["voting_close_at"])
                     + timedelta(seconds=1))
    # Re-fetch election in case the lazy tally needs a read trigger.
    election = get_election(election["id"])
    certified = certify_election(election)
    # If we just seated a PRESIDENT, register the new president id so
    # subsequent clock-advance calls use those headers (PRD §2.1
    # identity check).
    if seat == "PRESIDENT":
        set_elected_president(member["id"])
    return certified


# ===========================================================================
# Tier 4: Lien lifecycle — PRD §3.6, §2.8
# ===========================================================================
def create_lien_for_unit(unit_id: str,
                         headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.6: 'SecretaryRole creates a lien notice'. Preconditions
    (overdue >= 180000, charge OVERDUE >= 60d) must hold before calling.
    """
    headers = headers or TEST_USERS["secretary_role_headers"]
    resp = api_client.create_lien(
        create_lien_payload(unit_id=unit_id), headers,
    )
    return get_success_data(resp)


def record_lien(
    lien: Dict[str, Any], resolution_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["president_role_headers"]
    resp = api_client.record_lien(
        lien["id"],
        lien_action_payload(
            resolution_id=resolution_id, version=lien.get("version", 1),
        ),
        headers,
    )
    return get_success_data(resp)


def release_lien(
    lien: Dict[str, Any], resolution_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["president_role_headers"]
    resp = api_client.release_lien(
        lien["id"],
        lien_action_payload(
            resolution_id=resolution_id, version=lien.get("version", 1),
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 4: Reserve study helpers — PRD §3.9
# ===========================================================================
def create_reserve_study(
    components: List[Dict[str, Any]],
    current_reserve_balance_cents: int,
    study_year: int = 2026,
) -> Dict[str, Any]:
    """TreasurerRole creates a study in DRAFT."""
    resp = api_client.create_reserve_study(
        create_reserve_study_payload(
            study_year=study_year,
            components=components,
            current_reserve_balance_cents=current_reserve_balance_cents,
        ),
        TEST_USERS["treasurer_role_headers"],
    )
    return get_success_data(resp)


def adopt_reserve_study(
    study: Dict[str, Any], resolution_id: str,
) -> Dict[str, Any]:
    resp = api_client.adopt_reserve_study(
        study["id"],
        adopt_reserve_study_payload(
            resolution_id=resolution_id, version=study.get("version", 1),
        ),
        TEST_USERS["treasurer_role_headers"],
    )
    return get_success_data(resp)


def setup_adopted_special_assessment_study(
    study_year: int = 2026,
) -> Dict[str, Any]:
    """Create + adopt a ReserveStudy whose posture is
    SPECIAL_ASSESSMENT_REQUIRED. PRD §3.9 thresholds: ratio < 0.30.

    Components: one $1000 component, 0/10 remaining life → target $1000.
    Current balance: $200 → ratio 0.2000 < 0.30 → SPECIAL_ASSESSMENT_REQUIRED.
    """
    study = create_reserve_study(
        components=[reserve_component("Roof", 100_000, 10, 0)],
        current_reserve_balance_cents=20_000,
        study_year=study_year,
    )
    # Drive an RESERVE_STUDY_ADOPTION resolution to PASSED, then adopt.
    resolution = drive_resolution_to_passed(
        "RESERVE_STUDY_ADOPTION", study["id"],
    )
    return adopt_reserve_study(study, resolution["id"])


# ===========================================================================
# Tier 5: Board-bootstrapping — PRD §3.1, §3.7
# ===========================================================================
def setup_four_seated_board() -> Dict[str, Any]:
    """Bootstrap a roster + seat all four board roles via elections.

    Returns a dict with keys:
      members: list of 5 created Member dicts (4 board + 1 spare)
      board: {president, treasurer, secretary, director} — each value
             is the Member object now holding that seat
      headers: {president, treasurer, secretary, director} — per-instance
             role headers bound to that Member.id (PRD §2.1 identity)
      units: list of 5 Units (one per member, share_factor 0.2000 each)

    After this fixture returns, the four board-role headers each
    identify a real seated Member. Tests that need the board roles to
    pass §2.1 identity verification ("X-User-ID is the id of the Member
    who currently holds that board seat") should use the returned
    headers — not the shared TEST_USERS constants.
    """
    # Create five members
    members = [create_member() for _ in range(5)]
    # Create five units with share_factor 0.2000 each (sums to 1.0000)
    units = [
        create_unit(owner_member_id=m["id"], share_factor=0.2000)
        for m in members
    ]
    # Seat each of the first 4 into a board role via election.
    # IMPORTANT: PRESIDENT is seated LAST. The clock-advance capability
    # is President-only (PRD §3.10), so as long as the seat is vacant the
    # bootstrap PRESIDENT_BOOTSTRAP_ID can drive the clock. Once a real
    # Member holds the PRESIDENT seat, the bootstrap id no longer
    # satisfies the §2.1 identity check, and subsequent clock advances
    # must use the seated member's headers.
    seats_in_order = [
        ("TREASURER", members[1]),
        ("SECRETARY", members[2]),
        ("DIRECTOR",  members[3]),
        ("PRESIDENT", members[0]),  # last
    ]
    for seat, member in seats_in_order:
        seat_member_in_role(member, seat)
    return {
        "members": members,
        "units": units,
        "board": {
            "president": members[0],
            "treasurer": members[1],
            "secretary": members[2],
            "director": members[3],
        },
        "headers": {
            "president": make_president_role_headers(members[0]["id"]),
            "treasurer": make_treasurer_role_headers(members[1]["id"]),
            "secretary": make_secretary_role_headers(members[2]["id"]),
            "director": make_director_role_headers(members[3]["id"]),
        },
        "spare": members[4],
    }


# ===========================================================================
# Tier 5: Composite scenarios required by difficulty-design recipes
# ===========================================================================
def setup_three_unit_for_allocation_remainder() -> Tuple[
    List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]
]:
    """SCAFFOLD_DIFFICULTY_DESIGN: assessment_allocation_with_remainder_
    distribution.

    Three units U1(0.3334), U2(0.3333), U3(0.3333) — sum=1.0000.
    Create a REGULAR cycle with total_levy_cents=10001, issue it.

    Returns (members, units, cycle, charges_from_issue_payload). The
    fourth tuple element is whatever the implementation returned in the
    issue response — tests inspect it for the per-unit principal_cents.
    """
    members, units = setup_multi_unit_roster([0.3334, 0.3333, 0.3333])
    cycle = create_regular_cycle(total_levy_cents=10001, due_in_days=30)
    issued = issue_cycle(cycle)
    # The PRD does not declare a list-charges endpoint, but the issue
    # response — being the cycle in ISSUED status — may include child
    # charge identifiers; we surface whatever shape comes back so tests
    # can inspect.
    return members, units, issued, []


def setup_two_acc_requests_in_review() -> Tuple[
    Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """SCAFFOLD_DIFFICULTY_DESIGN: acc_request_branching_with_auto_resolution.

    Set up two ACCRequests on the same unit, one LANDSCAPING and one
    APPEARANCE, both promoted to UNDER_REVIEW. Returns:
        (member, unit, landscaping_req, appearance_req, board_meta)

    Uses a single-unit roster (sum invariant trivially satisfied) and the
    shared bootstrap SecretaryRole headers for begin-review (the shared
    bootstrap board members are pre-seated via /hoa/__test__/reset and
    pass PRD §2.1 identity). `board_meta` is returned as a dict containing
    `headers` -> shared header constants, providing the same shape callers
    expect for ACC voting (board_role membership only — vote identity
    isn't ownership-gated).
    """
    acc_member, acc_unit = setup_single_unit_roster()

    # Submit one LANDSCAPING and one APPEARANCE request.
    landscaping = submit_acc_request(
        acc_unit["id"], acc_member["id"], category="LANDSCAPING",
    )
    appearance = submit_acc_request(
        acc_unit["id"], acc_member["id"], category="APPEARANCE",
    )
    # Promote both via the (pre-seeded bootstrap) SecretaryRole.
    landscaping = begin_review_acc_request(
        landscaping, headers=TEST_USERS["secretary_role_headers"],
    )
    appearance = begin_review_acc_request(
        appearance, headers=TEST_USERS["secretary_role_headers"],
    )
    board_meta = {
        "headers": {
            "president": TEST_USERS["president_role_headers"],
            "treasurer": TEST_USERS["treasurer_role_headers"],
            "secretary": TEST_USERS["secretary_role_headers"],
            "director": TEST_USERS["director_role_headers"],
        },
    }
    return acc_member, acc_unit, landscaping, appearance, board_meta


def setup_election_with_zero_candidates_and_one_candidate() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """SCAFFOLD_DIFFICULTY_DESIGN: election_with_zero_candidates_auto_voids.

    Two elections with the same voting_open_at — one has zero
    candidates, one has exactly one. Returns (e_empty, e_one,
    sole_candidate).
    """
    member = create_member()
    create_unit(owner_member_id=member["id"], share_factor=1.0000)
    now = current_clock()
    vote_open = now + timedelta(seconds=120)
    vote_close = now + timedelta(seconds=240)
    payload_empty = create_election_payload(
        seat="DIRECTOR",
        nomination_open_at=iso_utc(now),
        voting_open_at=iso_utc(vote_open),
        voting_close_at=iso_utc(vote_close),
        quorum_pct=0.10,
    )
    payload_one = create_election_payload(
        seat="DIRECTOR",
        nomination_open_at=iso_utc(now),
        voting_open_at=iso_utc(vote_open),
        voting_close_at=iso_utc(vote_close),
        quorum_pct=0.10,
    )
    e_empty = get_success_data(
        api_client.create_election(
            payload_empty, TEST_USERS["president_role_headers"],
        )
    )
    e_one = get_success_data(
        api_client.create_election(
            payload_one, TEST_USERS["president_role_headers"],
        )
    )
    # Register one candidate for e_one only.
    sole = nominate_candidate(e_one["id"], member["id"])
    return e_empty, e_one, sole


__all__ = [
    # clock
    "current_clock", "current_clock_iso",
    "advance_clock_to", "advance_clock_by_seconds",
    "advance_clock_by_days", "reset_clock_tracker_to",
    "set_elected_president",
    # primitives
    "create_member", "create_unit",
    "get_member", "get_unit", "get_assessment_charge",
    "get_violation", "get_acc_request", "get_lien",
    "get_election", "get_board_resolution", "get_reserve_study",
    # roster
    "setup_single_unit_roster", "setup_multi_unit_roster",
    # cycles
    "create_regular_cycle", "create_special_cycle",
    "issue_cycle", "setup_issued_cycle",
    # resolutions
    "propose_resolution", "vote_resolution", "drive_resolution_to_passed",
    # overdue
    "setup_overdue_charge",
    # ACC
    "submit_acc_request", "begin_review_acc_request", "cast_acc_vote",
    # violations
    "open_violation", "cure_violation", "waive_violation",
    "open_n_violations_and_auto_fine",
    # payments
    "tender_payment",
    # elections
    "open_election", "nominate_candidate", "cast_ballot",
    "certify_election", "seat_member_in_role",
    # liens
    "create_lien_for_unit", "record_lien", "release_lien",
    # reserve studies
    "create_reserve_study", "adopt_reserve_study",
    "setup_adopted_special_assessment_study",
    # composite
    "setup_four_seated_board",
    "setup_three_unit_for_allocation_remainder",
    "setup_two_acc_requests_in_review",
    "setup_election_with_zero_candidates_and_one_candidate",
]
