"""Composite setup helpers — multi-step state builders.

These helpers encapsulate the 5–15 API-call sequences required to reach
the system states tests need to assert on. They use get_success_data
(the lenient validator) so setup failures surface as clear "Setup
failed" errors rather than confusing assertion failures.

PRD §2.1 identity threading: ANY call performed as Pilot or
FlightAttendant uses headers minted via
make_pilot_headers(crew_member["id"]) (or the FA equivalent).
The shared *_fallback_headers entries in TEST_USERS are reserved for
tests that do not exercise ownership.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CREW_REST_MIN_MINUTES,
    MAX_BLOCK_MINUTES_30D,
    TEST_DEFAULTS,
)
from .factories import (
    add_days_iso,
    add_hours_iso,
    add_minutes_iso,
    call_out_reserve_payload,
    clock_advance_payload,
    counter_trade_payload,
    create_assignment_payload,
    create_bid_payload,
    create_crew_member_payload,
    create_duty_period_payload,
    create_flight_leg_payload,
    create_pairing_payload,
    create_reserve_pool_payload,
    create_sick_call_payload,
    create_trade_request_payload,
    iso_from_dt,
    iso_now_utc,
    open_bidding_payload,
    parse_iso,
    random_bid_window_id,
    random_iata,
    random_pairing_code,
)
from .test_users import (
    DEFAULT_UNION_LOCAL_ID,
    TEST_USERS,
    make_flight_attendant_headers,
    make_pilot_headers,
    make_union_steward_headers,
)


# ---------------------------------------------------------------------------
# Convenience header accessors (opaque roles per PRD §2.1).
#
# These are exposed as dict-like CALLABLES so tests can pass either
# `scheduler_headers` (the dict identity, used directly by api.* helpers
# that consume `headers={...}` mappings) or `scheduler_headers()` (the
# legacy call form used inside fixtures.py). Both forms yield the same
# canonical header dict.
# ---------------------------------------------------------------------------
class _CallableHeaders(dict):
    """A dict that can also be invoked like a function and returns itself
    (or a copy with an X-Union-Local-Id override for union-steward use).
    Sub-keys remain accessible via normal dict operations."""

    def __call__(self, local_id: Optional[str] = None) -> Dict[str, str]:
        if local_id is None:
            return self
        h = dict(self)
        h["X-Union-Local-Id"] = local_id
        return h


scheduler_headers = _CallableHeaders(TEST_USERS["crew_scheduler_headers"])
scheduler_headers_alt = _CallableHeaders(
    TEST_USERS["crew_scheduler_headers_alt"]
)
steward_headers = _CallableHeaders({
    **TEST_USERS["union_steward_headers"],
    "X-Union-Local-Id": DEFAULT_UNION_LOCAL_ID,
})


# ---------------------------------------------------------------------------
# Pilot / FlightAttendant headers — entity-backed; pass the actual
# CrewMember id minted by POST /crew-members.
# ---------------------------------------------------------------------------
def pilot_headers_for(crew_member: Dict[str, Any]) -> Dict[str, str]:
    return make_pilot_headers(crew_member["id"])


def fa_headers_for(crew_member: Dict[str, Any]) -> Dict[str, str]:
    return make_flight_attendant_headers(crew_member["id"])


def crew_role_headers(crew_member: Dict[str, Any]) -> Dict[str, str]:
    """Pick the right role header given a CrewMember.rank."""
    rank = crew_member.get("rank")
    if rank in ("PURSER", "FLIGHT_ATTENDANT"):
        return fa_headers_for(crew_member)
    return pilot_headers_for(crew_member)


# ===========================================================================
# Tier 1: Single-entity factories (always-fresh primary entities).
# ===========================================================================
def create_crew_member(rank: str = "CAPTAIN",
                        base_airport: Optional[str] = None,
                        union_seniority_number: Optional[int] = None,
                        union_local_id: Optional[str] = None,
                        **overrides) -> Dict[str, Any]:
    """POST /crew-members as CrewScheduler; returns the created
    CrewMember dict. The caller binds the returned id to
    make_pilot_headers() / make_flight_attendant_headers() for any
    follow-up ownership-gated call.
    """
    payload = create_crew_member_payload(
        rank=rank, base_airport=base_airport,
        union_seniority_number=union_seniority_number,
        union_local_id=union_local_id, **overrides,
    )
    resp = api_client.create_crew_member(payload, scheduler_headers())
    return get_success_data(resp)


def get_crew_member(crew_member_id: str) -> Dict[str, Any]:
    resp = api_client.get_crew_member(crew_member_id, scheduler_headers())
    return get_success_data(resp)


def get_pairing(pairing_id: str) -> Dict[str, Any]:
    resp = api_client.get_pairing(pairing_id, scheduler_headers())
    return get_success_data(resp)


def get_assignment(assignment_id: str) -> Dict[str, Any]:
    resp = api_client.get_assignment(assignment_id, scheduler_headers())
    return get_success_data(resp)


def get_trade_request(tr_id: str,
                        as_member: Optional[Dict[str, Any]] = None,
                        ) -> Dict[str, Any]:
    headers = (
        crew_role_headers(as_member)
        if as_member is not None
        else scheduler_headers()
    )
    resp = api_client.get_trade_request(tr_id, headers)
    return get_success_data(resp)


def list_assignments(params: Optional[Dict[str, Any]] = None,
                      ) -> List[Dict[str, Any]]:
    resp = api_client.list_assignments(
        scheduler_headers(), params=params or {"limit": 100},
    )
    body = resp.json()
    return body["data"]


def list_bids(params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    # No GET /bids endpoint declared in PRD §4; callers should fetch
    # assignments and infer awarding outcomes from there.
    raise NotImplementedError("No GET /bids endpoint in PRD §4")


def list_reserve_pool(params: Optional[Dict[str, Any]] = None,
                       ) -> List[Dict[str, Any]]:
    resp = api_client.list_reserve_pool(
        scheduler_headers(), params=params or {"limit": 100},
    )
    body = resp.json()
    return body["data"]


# ===========================================================================
# Tier 2: Pairing construction primitives.
# ===========================================================================
def create_pairing_draft(base_airport: str = "DFW",
                          required_rank_composition: Optional[Dict] = None,
                          pairing_code: Optional[str] = None,
                          ) -> Dict[str, Any]:
    """POST /pairings (DRAFT)."""
    payload = create_pairing_payload(
        pairing_code=pairing_code or random_pairing_code(),
        base_airport=base_airport,
        required_rank_composition=required_rank_composition or {"CAPTAIN": 1},
    )
    resp = api_client.create_pairing(payload, scheduler_headers())
    return get_success_data(resp)


def add_duty_period(pairing_id: str, sequence_no: int,
                     report_at: str, release_at: str) -> Dict[str, Any]:
    payload = create_duty_period_payload(
        sequence_no=sequence_no,
        report_at=report_at, release_at=release_at,
    )
    resp = api_client.add_duty_period(pairing_id, payload, scheduler_headers())
    return get_success_data(resp)


def add_flight_leg(duty_period_id: str, leg_sequence_no: int,
                    dep_airport: str, arr_airport: str,
                    dep_at: str, arr_at: str,
                    leg_type: Optional[str] = None,
                    flight_number: Optional[str] = None,
                    ) -> Dict[str, Any]:
    payload = create_flight_leg_payload(
        leg_sequence_no=leg_sequence_no,
        flight_number=flight_number,
        dep_airport=dep_airport, arr_airport=arr_airport,
        dep_at=dep_at, arr_at=arr_at, leg_type=leg_type,
    )
    resp = api_client.add_flight_leg(
        duty_period_id, payload, scheduler_headers(),
    )
    return get_success_data(resp)


def publish_pairing(pairing_id: str) -> Dict[str, Any]:
    resp = api_client.publish_pairing(pairing_id, scheduler_headers())
    return get_success_data(resp)


def open_bidding(pairing_id: str,
                  bid_window_id: Optional[str] = None) -> Dict[str, Any]:
    payload = open_bidding_payload(
        bid_window_id=bid_window_id or TEST_DEFAULTS["DEFAULT_BID_WINDOW_ID"],
    )
    resp = api_client.open_bidding(pairing_id, payload, scheduler_headers())
    return get_success_data(resp)


def cancel_pairing(pairing_id: str) -> Dict[str, Any]:
    resp = api_client.cancel_pairing(pairing_id, scheduler_headers())
    return get_success_data(resp)


# ===========================================================================
# Tier 3: Composite pairing builder (DRAFT with N duty periods / legs).
# ===========================================================================
def build_pairing_with_one_duty_period(
    base_airport: str = "DFW",
    start_at: Optional[str] = None,
    duty_minutes: int = 600,
    revenue_block_minutes: int = 300,
    deadhead_block_minutes: int = 0,
    required_rank_composition: Optional[Dict] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Build a single-DutyPeriod pairing in DRAFT — one duty period with
    optional REVENUE and/or DEADHEAD legs adding up to the requested
    block minutes. Returns (pairing_after_draft, duty_period, legs).

    Default: start the pairing 48 hours in the future so subsequent
    open-bidding passes the 24h cutoff.
    """
    if start_at is None:
        # Default 48 hours ahead from server-wall-now so bid window can
        # be opened.
        start_at = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(hours=48),
        )
    report_at = start_at
    release_at = add_minutes_iso(report_at, duty_minutes)

    pairing = create_pairing_draft(
        base_airport=base_airport,
        required_rank_composition=required_rank_composition,
    )
    dp = add_duty_period(
        pairing["id"], sequence_no=1,
        report_at=report_at, release_at=release_at,
    )

    legs: List[Dict[str, Any]] = []
    cursor = add_minutes_iso(report_at, 30)  # 30 min after report
    leg_seq = 1
    if revenue_block_minutes > 0:
        end_rev = add_minutes_iso(cursor, revenue_block_minutes)
        leg = add_flight_leg(
            dp["id"], leg_sequence_no=leg_seq,
            dep_airport=base_airport, arr_airport=random_iata(),
            dep_at=cursor, arr_at=end_rev, leg_type="REVENUE",
        )
        legs.append(leg)
        cursor = end_rev
        leg_seq += 1
    if deadhead_block_minutes > 0:
        end_dh = add_minutes_iso(cursor, deadhead_block_minutes)
        leg = add_flight_leg(
            dp["id"], leg_sequence_no=leg_seq,
            dep_airport=legs[-1]["arr_airport"] if legs else base_airport,
            arr_airport=base_airport,
            dep_at=cursor, arr_at=end_dh, leg_type="DEADHEAD",
        )
        legs.append(leg)

    return get_pairing(pairing["id"]), dp, legs


def build_pairing_with_revenue_legs(
    leg_durations_minutes: List[int],
    base_airport: str = "DFW",
    start_at: Optional[str] = None,
    duty_pad_minutes: int = 60,
    required_rank_composition: Optional[Dict] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """One DutyPeriod with N REVENUE legs of the supplied minute lengths,
    sized so DutyPeriod.duty_minutes = sum(legs) + 2*duty_pad_minutes.
    """
    if start_at is None:
        start_at = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(hours=48),
        )
    total_block = sum(leg_durations_minutes)
    duty_minutes = total_block + 2 * duty_pad_minutes

    report_at = start_at
    release_at = add_minutes_iso(report_at, duty_minutes)
    pairing = create_pairing_draft(
        base_airport=base_airport,
        required_rank_composition=required_rank_composition,
    )
    dp = add_duty_period(
        pairing["id"], sequence_no=1,
        report_at=report_at, release_at=release_at,
    )

    legs: List[Dict[str, Any]] = []
    cursor = add_minutes_iso(report_at, duty_pad_minutes)
    for i, length in enumerate(leg_durations_minutes, start=1):
        end = add_minutes_iso(cursor, length)
        leg = add_flight_leg(
            dp["id"], leg_sequence_no=i,
            dep_airport=base_airport if i == 1 else legs[-1]["arr_airport"],
            arr_airport=base_airport
                if i == len(leg_durations_minutes)
                else random_iata(),
            dep_at=cursor, arr_at=end, leg_type="REVENUE",
        )
        legs.append(leg)
        cursor = end

    return get_pairing(pairing["id"]), dp, legs


def build_pairing_with_deadhead_legs(
    deadhead_durations_minutes: List[int],
    revenue_durations_minutes: Optional[List[int]] = None,
    base_airport: str = "DFW",
    start_at: Optional[str] = None,
    duty_pad_minutes: int = 60,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """One DutyPeriod with optional leading REVENUE legs and N DEADHEAD
    legs of the supplied minute lengths.
    """
    if start_at is None:
        start_at = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(hours=48),
        )
    rev = list(revenue_durations_minutes or [])
    dh = list(deadhead_durations_minutes)
    total_block = sum(rev) + sum(dh)
    duty_minutes = total_block + 2 * duty_pad_minutes
    report_at = start_at
    release_at = add_minutes_iso(report_at, duty_minutes)
    pairing = create_pairing_draft(base_airport=base_airport)
    dp = add_duty_period(
        pairing["id"], sequence_no=1,
        report_at=report_at, release_at=release_at,
    )

    legs: List[Dict[str, Any]] = []
    cursor = add_minutes_iso(report_at, duty_pad_minutes)
    seq = 1
    for length in rev:
        end = add_minutes_iso(cursor, length)
        leg = add_flight_leg(
            dp["id"], leg_sequence_no=seq,
            dep_airport=base_airport if seq == 1 else legs[-1]["arr_airport"],
            arr_airport=random_iata(),
            dep_at=cursor, arr_at=end, leg_type="REVENUE",
        )
        legs.append(leg)
        cursor = end
        seq += 1
    for length in dh:
        end = add_minutes_iso(cursor, length)
        leg = add_flight_leg(
            dp["id"], leg_sequence_no=seq,
            dep_airport=base_airport if seq == 1 else legs[-1]["arr_airport"],
            arr_airport=base_airport,
            dep_at=cursor, arr_at=end, leg_type="DEADHEAD",
        )
        legs.append(leg)
        cursor = end
        seq += 1

    return get_pairing(pairing["id"]), dp, legs


# ===========================================================================
# Tier 4: Lifecycle progression — draft -> published -> bidding_open.
# ===========================================================================
def publish_and_open_bidding(pairing_id: str,
                              bid_window_id: Optional[str] = None,
                              ) -> Tuple[Dict[str, Any], str]:
    """DRAFT -> PUBLISHED -> BIDDING_OPEN. Returns (pairing, bid_window_id)."""
    publish_pairing(pairing_id)
    bw = bid_window_id or random_bid_window_id()
    pairing = open_bidding(pairing_id, bid_window_id=bw)
    return pairing, bw


def submit_bid(crew_member: Dict[str, Any], pairing_id: str,
                bid_window_id: str, preference_rank: int = 1,
                ) -> Dict[str, Any]:
    """POST /bids as the crew member (Pilot or FA per rank)."""
    payload = create_bid_payload(
        pairing_id=pairing_id,
        bid_window_id=bid_window_id,
        preference_rank=preference_rank,
    )
    resp = api_client.create_bid(payload, crew_role_headers(crew_member))
    return get_success_data(resp)


def award_bid_window(bid_window_id: str) -> Dict[str, Any]:
    """POST /bid-windows/{id}/award as CrewScheduler."""
    resp = api_client.award_bid_window(bid_window_id, scheduler_headers())
    return get_success_data(resp)


# ===========================================================================
# Tier 5: ReservePool helpers.
# ===========================================================================
def place_on_reserve(crew_member_id: str,
                       reserve_date: Optional[str] = None,
                       standby_start_at: Optional[str] = None,
                       standby_end_at: Optional[str] = None,
                       ) -> Dict[str, Any]:
    """POST /reserve-pool as CrewScheduler."""
    if reserve_date is None:
        # UTC midnight-aligned for tomorrow.
        tmrw = datetime.now(timezone.utc) + timedelta(days=1)
        reserve_date = iso_from_dt(
            tmrw.replace(hour=0, minute=0, second=0, microsecond=0),
        )
    if standby_start_at is None:
        standby_start_at = reserve_date
    if standby_end_at is None:
        # 12-hour standby block.
        standby_end_at = add_hours_iso(standby_start_at, 12)
    payload = create_reserve_pool_payload(
        crew_member_id=crew_member_id,
        reserve_date=reserve_date,
        standby_start_at=standby_start_at,
        standby_end_at=standby_end_at,
    )
    resp = api_client.create_reserve_pool(payload, scheduler_headers())
    return get_success_data(resp)


# ===========================================================================
# Tier 6: Assignment short-cuts.
# ===========================================================================
def admin_assign(pairing_id: str, crew_member_id: str,
                  assigned_rank_slot: str = "CAPTAIN") -> Dict[str, Any]:
    """POST /assignments as CrewScheduler — admin-override path.

    After a successful admin-override, force the pairing to AWARDED via
    the test-only backdoor so PRD §3.6 clock-gated transitions
    (AWARDED → IN_PROGRESS → CLOSED) can fire for tests that drive the
    clock forward. The PRD names the transition as "from AWARDED"; tests
    that bind via admin-override need this state-bump so the time
    progression matches what the bid/award path naturally produces.
    """
    payload = create_assignment_payload(
        pairing_id=pairing_id,
        crew_member_id=crew_member_id,
        assigned_rank_slot=assigned_rank_slot,
    )
    resp = api_client.create_assignment(payload, scheduler_headers)
    data = get_success_data(resp)
    # Best-effort: flip pairing to AWARDED. Swallow any failure so
    # implementations without the backdoor are tolerated.
    try:
        api_client._request(
            "POST", "/__test__/force-pairing-awarded",
            {"pairing_id": pairing_id},
            dict(scheduler_headers),
        )
    except Exception:
        pass
    return data


def release_assignment(assignment_id: str) -> Dict[str, Any]:
    resp = api_client.release_assignment(assignment_id, scheduler_headers())
    return get_success_data(resp)


def mark_no_show(assignment_id: str) -> Dict[str, Any]:
    resp = api_client.mark_assignment_no_show(
        assignment_id, scheduler_headers(),
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 7: Clock advance and time-gated transitions.
# ===========================================================================
def advance_clock_to(target_at: str) -> Dict[str, Any]:
    """POST /_clock/advance as CrewScheduler — PRD §3.7."""
    payload = clock_advance_payload(target_at=target_at)
    resp = api_client.clock_advance(payload, scheduler_headers())
    return get_success_data(resp)


# ===========================================================================
# Tier 8: Composite lifecycle scenarios.
# ===========================================================================
def setup_pairing_in_bidding(
    pilot: Optional[Dict[str, Any]] = None,
    base_airport: str = "DFW",
    revenue_block_minutes: int = 300,
    duty_minutes: int = 600,
    required_rank_composition: Optional[Dict] = None,
    bid_window_id: Optional[str] = None,
    start_at: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """Build a pairing through DRAFT -> PUBLISHED -> BIDDING_OPEN.
    Returns (pairing, bid_window_id)."""
    pairing, _, _ = build_pairing_with_one_duty_period(
        base_airport=base_airport,
        revenue_block_minutes=revenue_block_minutes,
        duty_minutes=duty_minutes,
        required_rank_composition=required_rank_composition,
        start_at=start_at,
    )
    pairing, bw = publish_and_open_bidding(
        pairing["id"], bid_window_id=bid_window_id,
    )
    return pairing, bw


def setup_pairing_awarded_to(
    pilot: Dict[str, Any],
    base_airport: str = "DFW",
    revenue_block_minutes: int = 300,
    duty_minutes: int = 600,
    assigned_rank_slot: str = "CAPTAIN",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build a Pairing through BIDDING_OPEN, submit one bid by `pilot`,
    award the window, and return (pairing, assignment).

    Uses the admin-override path under the hood for determinism in
    fixtures: every awarding sweep goes through bid_award_calc which
    requires a SUBMITTED bid; this fixture is the public way for tests
    that don't care about award mechanics to get an Assignment.
    """
    pairing, bw = setup_pairing_in_bidding(
        base_airport=base_airport,
        revenue_block_minutes=revenue_block_minutes,
        duty_minutes=duty_minutes,
        required_rank_composition={assigned_rank_slot: 1},
    )
    submit_bid(pilot, pairing["id"], bw, preference_rank=1)
    award_bid_window(bw)
    pairing = get_pairing(pairing["id"])
    # Find the assignment matching this pilot.
    assignments = list_assignments(params={
        "limit": 100,
        "crew_member_id": pilot["id"],
        "pairing_id": pairing["id"],
    })
    if not assignments:
        # Filter manually if server doesn't support those params.
        all_a = list_assignments(params={"limit": 100})
        assignments = [
            a for a in all_a
            if a.get("crew_member_id") == pilot["id"]
            and a.get("pairing_id") == pairing["id"]
        ]
    if not assignments:
        raise AssertionError(
            "Setup failed: no assignment created for pilot "
            f"{pilot['id']} on pairing {pairing['id']}"
        )
    return pairing, assignments[0]


def setup_pairing_admin_assigned(
    crew_member: Dict[str, Any],
    base_airport: Optional[str] = None,
    revenue_block_minutes: int = 300,
    duty_minutes: int = 600,
    assigned_rank_slot: str = "CAPTAIN",
    publish: bool = True,
    deadhead_block_minutes: int = 0,
    start_at: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build a Pairing (optionally published) and create an admin-override
    Assignment for `crew_member`. Returns (pairing, assignment).

    admin_assign internally pushes the pairing to AWARDED via a
    test-only backdoor so PRD §3.6's AWARDED → IN_PROGRESS clock-gated
    transition can fire for tests that advance the clock past start_at.
    """
    base = base_airport or crew_member.get("base_airport", "DFW")
    pairing, _, _ = build_pairing_with_one_duty_period(
        base_airport=base,
        revenue_block_minutes=revenue_block_minutes,
        deadhead_block_minutes=deadhead_block_minutes,
        duty_minutes=duty_minutes,
        required_rank_composition={assigned_rank_slot: 1},
        start_at=start_at,
    )
    if publish:
        publish_pairing(pairing["id"])
    a = admin_assign(
        pairing["id"], crew_member["id"], assigned_rank_slot,
    )
    return get_pairing(pairing["id"]), a


# ===========================================================================
# Tier 9: Threshold targeting — raise the crew member's cumulative
# counters to a controlled value before the test's main action.
# ===========================================================================
def raise_cumulative_block_30d(
    crew_member: Dict[str, Any],
    target_minutes: int,
    base_airport: Optional[str] = None,
    chunk_size: int = 500,
) -> Dict[str, Any]:
    """Create back-to-back PUBLISHED pairings and admin-assign them to
    `crew_member` until their cumulative_block_minutes_30d reaches at
    least `target_minutes`.

    Each pairing's start_at is staggered far enough in the future that
    the CREW_REST_MIN_MINUTES gap between sequential admin-assignments
    is honoured; this keeps the FAA check happy across the build-up.
    """
    base = base_airport or crew_member.get("base_airport", "DFW")
    current = int(crew_member.get("cumulative_block_minutes_30d", 0))
    if current >= target_minutes:
        return get_crew_member(crew_member["id"])

    # Stagger pairings — start ahead of now + 1d and walk forward.
    next_start = datetime.now(timezone.utc) + timedelta(days=2)
    iterations = 0
    while current < target_minutes:
        add = min(chunk_size, target_minutes - current)
        start_iso = iso_from_dt(next_start)
        pairing, _, _ = build_pairing_with_one_duty_period(
            base_airport=base,
            revenue_block_minutes=add,
            duty_minutes=add + 120,
            required_rank_composition={crew_member["rank"]: 1},
            start_at=start_iso,
        )
        publish_pairing(pairing["id"])
        admin_assign(pairing["id"], crew_member["id"], crew_member["rank"])
        # Walk pairing start_at by (duty + crew rest gap) so the next
        # admin-assign sees enough rest from the prior release_at.
        next_start += timedelta(
            minutes=add + 120 + CREW_REST_MIN_MINUTES + 60,
        )
        cm = get_crew_member(crew_member["id"])
        current = int(cm.get("cumulative_block_minutes_30d", 0))
        iterations += 1
        if iterations > 60:
            raise AssertionError(
                "raise_cumulative_block_30d: setup did not converge; "
                f"target={target_minutes}, current={current}"
            )
    return get_crew_member(crew_member["id"])


# ===========================================================================
# Tier 10: Sick-call chain helpers (depth-3 cascade per scaffold
# difficulty design).
# ===========================================================================
def setup_sick_call_chain(
    member_rank: str = "CAPTAIN",
    base_airport: str = "DFW",
) -> Dict[str, Any]:
    """Stage: assigned pilot + matching reserve standby.

    Returns a dict with keys:
      sick_member, sick_assignment, sick_pairing,
      reserve_member, reserve_pool, bid_window_id

    The reserve member's standby_start_at is iso_now_utc() so a sick-call
    posted immediately after this fixture can call out the reserve
    within the half-open window.
    """
    sick_member = create_crew_member(
        rank=member_rank, base_airport=base_airport,
    )
    reserve_member = create_crew_member(
        rank=member_rank, base_airport=base_airport,
    )

    # Sick member gets an Assignment via admin path on a pairing well in
    # the future so admin-assign succeeds; the sick call then releases it.
    pairing, assignment = setup_pairing_admin_assigned(
        sick_member,
        base_airport=base_airport,
        assigned_rank_slot=member_rank,
    )

    # Reserve standby covers the next 12 hours from the SERVER's now.
    # The impl's logical clock is fixed at server boot and only moves
    # via /_clock/advance (PRD §2.7), so reading wall time on the test
    # side can be ahead of get_now() and break the half-open inclusion
    # check (PRD §3.4: standby_start_at is inclusive).
    server_now = api_client.clock_now(scheduler_headers).json()["data"]["now"]
    # Back up the standby start by 1 minute so the half-open window is
    # guaranteed to include the server's now even after small drift.
    standby_start = add_minutes_iso(server_now, -1)
    res_end = add_hours_iso(server_now, 12)
    reserve = place_on_reserve(
        reserve_member["id"],
        reserve_date=standby_start,
        standby_start_at=standby_start,
        standby_end_at=res_end,
    )

    return {
        "sick_member": sick_member,
        "sick_assignment": assignment,
        "sick_pairing": pairing,
        "reserve_member": reserve_member,
        "reserve_pool": reserve,
    }


def report_sick_call(crew_member: Dict[str, Any],
                       assignment_id: Optional[str] = None,
                       effective_from: Optional[str] = None,
                       expected_return_at: Optional[str] = None,
                       ):
    """POST /sick-calls. The Pilot/FA reports their own sick call per
    PRD §2.1 (own only). Returns the raw response so callers can also
    inspect non-2xx outcomes (e.g., warning when ERR_NO_RESERVE_AVAILABLE
    is signalled inside a 201).
    """
    eff = effective_from or add_hours_iso(iso_now_utc(), 1)
    ret = expected_return_at or add_hours_iso(iso_now_utc(), 72)
    payload = create_sick_call_payload(
        crew_member_id=crew_member["id"],
        effective_from=eff,
        expected_return_at=ret,
        assignment_id=assignment_id,
    )
    headers = crew_role_headers(crew_member)
    return api_client.create_sick_call(payload, headers)


# ===========================================================================
# Tier 11: TradeRequest helpers.
# ===========================================================================
def setup_two_pilots_with_assignments(
    base_airport: str = "DFW",
    rank: str = "CAPTAIN",
    union_local_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create two CrewMembers (same rank, same local by default), each
    with a SCHEDULED Assignment on a distinct PUBLISHED Pairing.
    Returns (m1, m2, a1, a2)."""
    m1 = create_crew_member(
        rank=rank, base_airport=base_airport,
        union_local_id=union_local_id or DEFAULT_UNION_LOCAL_ID,
    )
    m2 = create_crew_member(
        rank=rank, base_airport=base_airport,
        union_local_id=union_local_id or DEFAULT_UNION_LOCAL_ID,
    )
    # Stagger start_at so admin-assign on m2's pairing doesn't get
    # rejected by FAA against m1's last_duty_end_at (and vice versa,
    # since both pilots have last_duty_end_at == null at creation).
    p1, a1 = setup_pairing_admin_assigned(
        m1, base_airport=base_airport,
        assigned_rank_slot=rank,
    )
    # Use a later start for the second pairing.
    later_start = iso_from_dt(
        datetime.now(timezone.utc) + timedelta(days=5),
    )
    p2, a2 = setup_pairing_admin_assigned(
        m2, base_airport=base_airport,
        assigned_rank_slot=rank,
        start_at=later_start,
    )
    return m1, m2, a1, a2


def create_trade_request(initiator: Dict[str, Any],
                          counterparty: Dict[str, Any],
                          initiator_assignment: Dict[str, Any],
                          counterparty_assignment: Dict[str, Any],
                          ) -> Dict[str, Any]:
    """POST /trade-requests as the initiator."""
    payload = create_trade_request_payload(
        initiator_assignment_id=initiator_assignment["id"],
        counterparty_assignment_id=counterparty_assignment["id"],
        counterparty_id=counterparty["id"],
    )
    resp = api_client.create_trade_request(
        payload, crew_role_headers(initiator),
    )
    return get_success_data(resp)


def counter_trade_as(actor: Dict[str, Any], tr_id: str,
                       new_initiator_assignment_id: str,
                       new_counterparty_assignment_id: str,
                       ) -> Dict[str, Any]:
    payload = counter_trade_payload(
        new_initiator_assignment_id=new_initiator_assignment_id,
        new_counterparty_assignment_id=new_counterparty_assignment_id,
    )
    resp = api_client.counter_trade_request(
        tr_id, payload, crew_role_headers(actor),
    )
    return get_success_data(resp)


def accept_trade_as(actor: Dict[str, Any], tr_id: str) -> Dict[str, Any]:
    resp = api_client.accept_trade_request(
        tr_id, crew_role_headers(actor),
    )
    return get_success_data(resp)


def approve_trade(tr_id: str) -> Dict[str, Any]:
    resp = api_client.approve_trade_request(tr_id, scheduler_headers())
    return get_success_data(resp)


# ===========================================================================
# Tier 12: Pay-credit lifecycle helpers — assignment -> COMPLETED.
# ===========================================================================
def run_pairing_to_completion(pairing: Dict[str, Any]) -> Dict[str, Any]:
    """Advance the clock past pairing.start_at and then past
    pairing.end_at so that the per-PRD time-gated transitions fire
    (Pairing AWARDED -> IN_PROGRESS -> CLOSED, Assignment IN_PROGRESS ->
    COMPLETED, pay_credit_calc applied).
    """
    start_at = pairing.get("start_at")
    end_at = pairing.get("end_at")
    if not start_at or not end_at:
        # Refresh in case the caller passed an older snapshot.
        fresh = get_pairing(pairing["id"])
        start_at = fresh.get("start_at")
        end_at = fresh.get("end_at")
    # Advance to a moment after start_at and then after end_at.
    advance_clock_to(add_minutes_iso(start_at, 1))
    advance_clock_to(add_minutes_iso(end_at, 1))
    return get_pairing(pairing["id"])


__all__ = [
    "accept_trade_as",
    "add_duty_period",
    "add_flight_leg",
    "admin_assign",
    "advance_clock_to",
    "approve_trade",
    "award_bid_window",
    "build_pairing_with_deadhead_legs",
    "build_pairing_with_one_duty_period",
    "build_pairing_with_revenue_legs",
    "cancel_pairing",
    "counter_trade_as",
    "create_crew_member",
    "create_pairing_draft",
    "create_trade_request",
    "crew_role_headers",
    "fa_headers_for",
    "get_assignment",
    "get_crew_member",
    "get_pairing",
    "get_trade_request",
    "list_assignments",
    "list_reserve_pool",
    "mark_no_show",
    "open_bidding",
    "pilot_headers_for",
    "place_on_reserve",
    "publish_and_open_bidding",
    "publish_pairing",
    "raise_cumulative_block_30d",
    "release_assignment",
    "report_sick_call",
    "run_pairing_to_completion",
    "scheduler_headers",
    "scheduler_headers_alt",
    "setup_pairing_admin_assigned",
    "setup_pairing_awarded_to",
    "setup_pairing_in_bidding",
    "setup_sick_call_chain",
    "setup_two_pilots_with_assignments",
    "steward_headers",
    "submit_bid",
]
