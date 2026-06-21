"""Composite setup helpers for multi-step preconditions.

Every test runs against an empty database (the runner restarts the server before
each pytest test). Every fixture here builds preconditions from scratch using
only PRD-declared endpoints, pinning the server clock at the start so that
time-driven transitions behave deterministically.

Fixtures use `get_success_data` (lenient validator) internally so a setup
failure surfaces as a clear "Setup step failed" error rather than a confusing
assertion failure inside a test body.

Identity threading (PRD §2.1): after creating a CrewMember entity, any
ownership-gated call uses `make_crew_member_headers(cm_id)` with the entity's id.
"""
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_crew_member_payload,
    create_pairing_payload,
    create_flight_leg_payload,
    create_bid_payload,
    create_sick_call_payload,
    create_trip_trade_payload,
)
from .test_users import TEST_USERS, make_crew_member_headers


# ---------------------------------------------------------------------
# Low-level wrappers
# ---------------------------------------------------------------------

def set_clock(iso8601: str) -> None:
    """Pin the server clock to the given ISO 8601 UTC instant (PRD §2.6)."""
    res = api_client.set_clock(iso8601, TEST_USERS["scheduling_planner_headers"])
    if not (200 <= res.status_code < 300):
        raise AssertionError(
            f"Setup step failed: could not set clock to {iso8601}: "
            f"HTTP {res.status_code}: {res.text}"
        )


def create_crew_member(**overrides) -> dict:
    """Create a CrewMember (any planner). Returns the entity dict."""
    return get_success_data(
        api_client.create_crew_member(
            create_crew_member_payload(**overrides),
            TEST_USERS["scheduling_planner_headers"],
        )
    )


def create_pairing(**overrides) -> dict:
    """Create a Pairing in DRAFT. Returns the entity dict."""
    return get_success_data(
        api_client.create_pairing(
            create_pairing_payload(**overrides),
            TEST_USERS["scheduling_planner_headers"],
        )
    )


def add_revenue_leg(
    pairing_id: str,
    leg_sequence: int = 1,
    departure: str = "LAX",
    arrival: str = "JFK",
    scheduled_departure_utc: str = "2026-06-02T01:00:00Z",
    scheduled_arrival_utc: str = "2026-06-02T07:00:00Z",
) -> dict:
    """Add one REVENUE FlightLeg to a DRAFT Pairing."""
    return get_success_data(
        api_client.create_flight_leg(
            pairing_id,
            create_flight_leg_payload(
                leg_sequence=leg_sequence,
                departure_airport=departure,
                arrival_airport=arrival,
                scheduled_departure_utc=scheduled_departure_utc,
                scheduled_arrival_utc=scheduled_arrival_utc,
                leg_type="REVENUE",
            ),
            TEST_USERS["scheduling_planner_headers"],
        )
    )


def open_bidding(pairing_id: str) -> dict:
    return get_success_data(
        api_client.open_pairing_bidding(
            pairing_id, TEST_USERS["scheduling_planner_headers"]
        )
    )


def close_bidding(pairing_id: str) -> dict:
    return get_success_data(
        api_client.close_pairing_bidding(
            pairing_id, TEST_USERS["scheduling_planner_headers"]
        )
    )


def submit_bid(pairing_id: str, crew_member: dict, requested_seat: str = "CAPTAIN") -> dict:
    """Crew member submits a Bid for a BID_OPEN Pairing."""
    return get_success_data(
        api_client.create_bid(
            create_bid_payload(pairing_id, crew_member["id"], requested_seat=requested_seat),
            make_crew_member_headers(crew_member["id"]),
        )
    )


def get_pairing(pairing_id: str) -> dict:
    return get_success_data(
        api_client.get_pairing(
            pairing_id, TEST_USERS["scheduling_planner_headers"]
        )
    )


def get_crew_member(crew_member_id: str) -> dict:
    return get_success_data(
        api_client.get_crew_member(
            crew_member_id, TEST_USERS["scheduling_planner_headers"]
        )
    )


def get_assignment(assignment_id: str) -> dict:
    return get_success_data(
        api_client.get_assignment(
            assignment_id, TEST_USERS["scheduling_planner_headers"]
        )
    )


def get_sick_call(sick_call_id: str) -> dict:
    return get_success_data(
        api_client.get_sick_call(
            sick_call_id, TEST_USERS["operations_controller_headers"]
        )
    )


def get_reserve_callup(callup_id: str) -> dict:
    return get_success_data(
        api_client.get_reserve_callup(
            callup_id, TEST_USERS["operations_controller_headers"]
        )
    )


def get_trip_trade(trade_id: str) -> dict:
    return get_success_data(
        api_client.get_trip_trade(
            trade_id, TEST_USERS["operations_controller_headers"]
        )
    )


def award_pairing(pairing_id: str, expected_pairing_version: Optional[int] = None) -> dict:
    """Award a BID_CLOSED Pairing with the live version (PRD §2.10)."""
    if expected_pairing_version is None:
        expected_pairing_version = get_pairing(pairing_id)["version"]
    return get_success_data(
        api_client.award_pairing(
            pairing_id,
            {"expected_pairing_version": expected_pairing_version},
            TEST_USERS["scheduling_planner_headers"],
        )
    )


def complete_pairing(pairing_id: str) -> dict:
    return get_success_data(
        api_client.complete_pairing(
            pairing_id, TEST_USERS["operations_controller_headers"]
        )
    )


def cancel_pairing(pairing_id: str) -> dict:
    return get_success_data(
        api_client.cancel_pairing(
            pairing_id, TEST_USERS["scheduling_planner_headers"]
        )
    )


def confirm_assignment(assignment_id: str, crew_member: dict) -> dict:
    return get_success_data(
        api_client.confirm_assignment(
            assignment_id, make_crew_member_headers(crew_member["id"])
        )
    )


def report_sick_call(assignment_id: str, crew_member: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_sick_call(
            create_sick_call_payload(assignment_id, **overrides),
            make_crew_member_headers(crew_member["id"]),
        )
    )


def acknowledge_sick_call(sick_call_id: str) -> dict:
    return get_success_data(
        api_client.acknowledge_sick_call(
            sick_call_id, TEST_USERS["operations_controller_headers"]
        )
    )


def list_assignments_for(pairing_id: str, crew_member_id: str) -> list:
    """List assignments filtered by (pairing_id, crew_member_id)."""
    res = api_client.list_assignments(
        TEST_USERS["scheduling_planner_headers"],
        params={"pairing_id": pairing_id, "crew_member_id": crew_member_id},
    )
    data = get_success_data(res)
    # `data` is the data array directly per the API envelope shape.
    return data if isinstance(data, list) else data


def list_reserve_callups_for(sick_call_id: str) -> list:
    res = api_client.list_reserve_callups(
        TEST_USERS["operations_controller_headers"],
        params={"sick_call_id": sick_call_id},
    )
    data = get_success_data(res)
    return data if isinstance(data, list) else data


# ---------------------------------------------------------------------
# Tier 2/3 composites — build complete contextual states
# ---------------------------------------------------------------------

def setup_clean_world(clock: str = "2026-06-01T00:00:00Z") -> None:
    """Pin the clock to a deterministic 'now' — first call in any fixture."""
    set_clock(clock)


def first_assignment_for(pairing_id: str, crew_member_id: str) -> dict:
    """Return the (first) Assignment row joining a pairing and crew member."""
    rows = list_assignments_for(pairing_id, crew_member_id)
    if not rows:
        raise AssertionError(
            f"Setup step failed: no Assignment for pairing={pairing_id} "
            f"crew_member={crew_member_id}"
        )
    return rows[0]


def setup_pairing_in_bid_open(
    *,
    clock: str = "2026-06-01T00:00:00Z",
    pairing_overrides: Optional[dict] = None,
    leg_overrides: Optional[dict] = None,
) -> dict:
    """Pin clock; create a DRAFT pairing with one REVENUE leg; open bidding.

    Returns the Pairing entity AFTER open-bidding (state == BID_OPEN).
    """
    setup_clean_world(clock)
    pairing = create_pairing(**(pairing_overrides or {}))
    leg_overrides = dict(leg_overrides or {})
    leg_overrides.setdefault("leg_sequence", 1)
    add_revenue_leg(pairing["id"], **leg_overrides)
    open_bidding(pairing["id"])
    return get_pairing(pairing["id"])


def setup_scheduled_captain_assignment(
    *,
    clock: str = "2026-06-01T00:00:00Z",
    employee_code_suffix: str = "001",
    seniority_number: int = 1,
    pairing_overrides: Optional[dict] = None,
    leg_overrides: Optional[dict] = None,
    line_type: str = "LINEHOLDER",
    after_close_clock: str = "2026-06-01T12:00:01Z",
) -> Tuple[dict, dict, dict]:
    """Build the canonical "one captain on a single-seat pairing in SCHEDULED" state.

    Steps:
      1. Pin clock.
      2. Create one CAPTAIN crew member at LAX.
      3. Create a Pairing (defaults wire scheduled_start=2026-06-02T00:00,
         scheduled_end=2026-06-02T10:00, bidding_close=2026-06-01T12:00).
      4. Add one REVENUE FlightLeg.
      5. Open bidding; crew submits a CAPTAIN bid.
      6. Advance clock past bidding_close so the auto-cascade flips BID_OPEN
         to BID_CLOSED.
      7. Award the pairing using the live version.

    Returns (crew_member, pairing_after_award, assignment_in_SCHEDULED).
    """
    setup_clean_world(clock)
    # Ensure employee_code is exactly two letters + four digits per PRD §3.2.
    digits = employee_code_suffix.zfill(4)[-4:]
    cm = create_crew_member(
        employee_code=f"AB{digits}",
        seniority_number=seniority_number,
        line_type=line_type,
        rank="CAPTAIN",
    )
    pairing = create_pairing(**(pairing_overrides or {}))
    add_revenue_leg(pairing["id"], **(leg_overrides or {}))
    open_bidding(pairing["id"])
    submit_bid(pairing["id"], cm, requested_seat="CAPTAIN")
    set_clock(after_close_clock)
    pairing_after_award = award_pairing(pairing["id"])
    assignment = first_assignment_for(pairing["id"], cm["id"])
    return cm, pairing_after_award, assignment


def setup_confirmed_captain_assignment(
    **kwargs,
) -> Tuple[dict, dict, dict]:
    """Same as setup_scheduled_captain_assignment but advances the assignment
    through to CONFIRMED.

    Returns (crew_member, pairing, assignment_in_CONFIRMED).
    """
    cm, pairing, assignment = setup_scheduled_captain_assignment(**kwargs)
    assignment_after = confirm_assignment(assignment["id"], cm)
    return cm, pairing, assignment_after


def setup_completed_pairing_for_crew(
    *,
    clock: str = "2026-06-01T00:00:00Z",
    employee_code_suffix: str = "001",
    seniority_number: int = 1,
    pairing_overrides: Optional[dict] = None,
    leg_overrides: Optional[dict] = None,
    pre_complete_clock: Optional[str] = None,
    complete_clock: Optional[str] = None,
) -> Tuple[dict, dict, dict]:
    """Build a CrewMember whose Pairing has fully completed.

    The pairing is run all the way through to COMPLETED so that the
    crew member's total_duty_minutes_7d and total_flight_minutes_7d are
    populated from a single prior assignment.

    Returns (crew_member_after_complete, pairing_after_complete, assignment_after_complete).
    """
    cm, pairing, assignment = setup_confirmed_captain_assignment(
        clock=clock,
        employee_code_suffix=employee_code_suffix,
        seniority_number=seniority_number,
        pairing_overrides=pairing_overrides,
        leg_overrides=leg_overrides,
    )
    # Advance clock past scheduled_end_utc and then complete.
    pre_complete_clock = pre_complete_clock or pairing["scheduled_start_utc"]
    complete_clock = complete_clock or pairing["scheduled_end_utc"]
    set_clock(pre_complete_clock)
    set_clock(complete_clock)
    pairing_after = complete_pairing(pairing["id"])
    assignment_after = get_assignment(assignment["id"])
    crew_after = get_crew_member(cm["id"])
    return crew_after, pairing_after, assignment_after


def setup_two_crew_with_confirmed_assignments(
    *,
    clock: str = "2026-06-01T00:00:00Z",
    second_pairing_start: str = "2026-06-03T00:00:00Z",
    second_pairing_end: str = "2026-06-03T10:00:00Z",
    second_leg_dep: str = "2026-06-03T01:00:00Z",
    second_leg_arr: str = "2026-06-03T07:00:00Z",
) -> Tuple[dict, dict, dict, dict, dict, dict]:
    """Two captains, each holding a CONFIRMED Captain Assignment on a separate Pairing.

    Designed for the trip-trade flow: cm_a + assignment_a on pairing P_A,
    cm_b + assignment_b on pairing P_B.

    Returns (cm_a, cm_b, pairing_a, pairing_b, assignment_a, assignment_b).
    """
    setup_clean_world(clock)
    cm_a = create_crew_member(seniority_number=1, employee_code="AB0040")
    cm_b = create_crew_member(seniority_number=2, employee_code="AB0041")

    pairing_a = create_pairing(pairing_code="P-2026-040")
    add_revenue_leg(pairing_a["id"])

    pairing_b = create_pairing(
        pairing_code="P-2026-041",
        scheduled_start_utc=second_pairing_start,
        scheduled_end_utc=second_pairing_end,
        bidding_close_utc="2026-06-01T12:00:00Z",
    )
    add_revenue_leg(
        pairing_b["id"],
        leg_sequence=1,
        departure="LAX",
        arrival="JFK",
        scheduled_departure_utc=second_leg_dep,
        scheduled_arrival_utc=second_leg_arr,
    )

    open_bidding(pairing_a["id"])
    open_bidding(pairing_b["id"])
    submit_bid(pairing_a["id"], cm_a, requested_seat="CAPTAIN")
    submit_bid(pairing_b["id"], cm_b, requested_seat="CAPTAIN")

    set_clock("2026-06-01T12:00:01Z")
    pairing_a_awarded = award_pairing(pairing_a["id"])
    pairing_b_awarded = award_pairing(pairing_b["id"])

    a_a = first_assignment_for(pairing_a_awarded["id"], cm_a["id"])
    a_b = first_assignment_for(pairing_b_awarded["id"], cm_b["id"])
    a_a_confirmed = confirm_assignment(a_a["id"], cm_a)
    a_b_confirmed = confirm_assignment(a_b["id"], cm_b)

    return cm_a, cm_b, pairing_a_awarded, pairing_b_awarded, a_a_confirmed, a_b_confirmed


def setup_sick_call_with_reserve_offered(
    *,
    clock: str = "2026-06-01T00:00:00Z",
    add_extra_reserve: bool = False,
) -> Tuple[dict, dict, dict, dict, dict, dict, Optional[dict]]:
    """Lineholder CM_L has a CONFIRMED Captain Assignment; CM_L sick-calls;
    operations acknowledges and one ReserveCallup is created OFFERED to CM_R.

    If add_extra_reserve is True, a second reserve CM_R2 (less senior) is also
    created so that decline → next-offer can be exercised.

    Returns (cm_l, cm_r, pairing, sick_call, reserve_callup_offered, assignment, cm_r2_or_none).
    """
    setup_clean_world(clock)
    cm_l = create_crew_member(
        employee_code="AB0060", seniority_number=60, line_type="LINEHOLDER"
    )
    cm_r = create_crew_member(
        employee_code="AB0061", seniority_number=61, line_type="RESERVE"
    )
    cm_r2 = None
    if add_extra_reserve:
        cm_r2 = create_crew_member(
            employee_code="AB0062", seniority_number=62, line_type="RESERVE"
        )

    pairing = create_pairing(pairing_code="P-2026-060")
    add_revenue_leg(pairing["id"])
    open_bidding(pairing["id"])
    submit_bid(pairing["id"], cm_l, requested_seat="CAPTAIN")
    set_clock("2026-06-01T12:00:01Z")
    pairing_awarded = award_pairing(pairing["id"])
    assignment = first_assignment_for(pairing_awarded["id"], cm_l["id"])
    assignment_confirmed = confirm_assignment(assignment["id"], cm_l)
    sick_call = report_sick_call(assignment_confirmed["id"], cm_l)
    sick_call_ack = acknowledge_sick_call(sick_call["id"])
    callups = list_reserve_callups_for(sick_call_ack["id"])
    if not callups:
        raise AssertionError("Setup step failed: no ReserveCallup created at acknowledge")
    rc = callups[0]
    return cm_l, cm_r, pairing_awarded, sick_call_ack, rc, assignment_confirmed, cm_r2


def setup_trip_trade_in_state(
    target_state: str,
    *,
    clock: str = "2026-06-01T00:00:00Z",
    reason: Optional[str] = None,
) -> Tuple[dict, dict, dict, dict, dict, dict, dict]:
    """Build a TripTrade and walk it to the requested target_state.

    target_state must be one of: PROPOSED, COUNTERSIGNED, APPROVED.

    Returns (cm_a, cm_b, pairing_a, pairing_b, assignment_a, assignment_b, trade).
    """
    cm_a, cm_b, pa, pb, aa, ab = setup_two_crew_with_confirmed_assignments(clock=clock)
    trade = get_success_data(
        api_client.create_trip_trade(
            create_trip_trade_payload(aa["id"], ab["id"]),
            make_crew_member_headers(cm_a["id"]),
        )
    )
    if target_state == "PROPOSED":
        return cm_a, cm_b, pa, pb, aa, ab, trade
    # COUNTERSIGNED
    trade = get_success_data(
        api_client.countersign_trip_trade(
            trade["id"], make_crew_member_headers(cm_b["id"])
        )
    )
    if target_state == "COUNTERSIGNED":
        return cm_a, cm_b, pa, pb, aa, ab, trade
    # APPROVED
    trade = get_success_data(
        api_client.approve_trip_trade(
            trade["id"], TEST_USERS["operations_controller_headers"]
        )
    )
    if target_state == "APPROVED":
        return cm_a, cm_b, pa, pb, aa, ab, trade
    raise ValueError(f"Unsupported target_state: {target_state!r}")


# ---------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting
# ---------------------------------------------------------------------

def setup_crew_with_accumulated_duty(
    *,
    target_duty_minutes: int,
    target_flight_minutes: Optional[int] = None,
    new_pairing_start: str = "2026-06-02T00:00:00Z",
    new_pairing_end: str = "2026-06-02T10:00:00Z",
    new_leg_dep: str = "2026-06-02T01:00:00Z",
    new_leg_arr: str = "2026-06-02T07:00:00Z",
    new_pairing_close: str = "2026-06-01T12:00:00Z",
) -> Tuple[dict, dict]:
    """Build a CrewMember with persisted total_duty_minutes_7d == target_duty_minutes,
    via a single prior COMPLETED Pairing whose total_duty_minutes equals that target.

    Per PRD §3.1 a Pairing's total_duty_minutes equals
        (scheduled_end - scheduled_start) minutes + 60 (report) + 30 (debrief)
    so to hit a target of N minutes we choose a window of N - 90 minutes.

    Then a new candidate Pairing is created (DRAFT -> awarded -> assignment SCHEDULED)
    so the caller can run preview-form checks against the persisted totals.

    Returns (crew_member_with_persisted_totals, new_pairing_assignment_SCHEDULED).
    """
    # Compute the prior window length we need.
    prior_window_minutes = target_duty_minutes - 90
    if prior_window_minutes <= 0:
        raise ValueError(
            f"target_duty_minutes={target_duty_minutes} too low; must exceed 90."
        )

    # Prior pairing window: starts 2026-05-26T00:00, ends prior_window_minutes later.
    prior_start = "2026-05-26T00:00:00Z"
    # Compute prior_end deterministically.
    h, m = divmod(prior_window_minutes, 60)
    days, h = divmod(h, 24)
    prior_end_day = 26 + days
    prior_end = f"2026-05-{prior_end_day:02d}T{h:02d}:{m:02d}:00Z"

    # Clock starts a week earlier so prior pairing is fully in trailing 7d window.
    setup_clean_world("2026-05-25T00:00:00Z")
    cm = create_crew_member(
        employee_code="AB0100", seniority_number=100, line_type="LINEHOLDER"
    )
    prior_pairing = create_pairing(
        pairing_code="P-2026-100",
        scheduled_start_utc=prior_start,
        scheduled_end_utc=prior_end,
        bidding_close_utc="2026-05-25T12:00:00Z",
    )
    # The REVENUE flight is intentionally short (60 minutes) so that this
    # helper's caller can independently control the flight-side preview total.
    # FAA flight checks remain under the 1800-min cap regardless of how large
    # the duty target is.
    flight_dep = "2026-05-26T01:00:00Z"
    flight_arr = "2026-05-26T02:00:00Z"
    add_revenue_leg(
        prior_pairing["id"],
        leg_sequence=1,
        departure="LAX",
        arrival="JFK",
        scheduled_departure_utc=flight_dep,
        scheduled_arrival_utc=flight_arr,
    )
    open_bidding(prior_pairing["id"])
    submit_bid(prior_pairing["id"], cm, requested_seat="CAPTAIN")
    set_clock("2026-05-25T12:00:01Z")
    award_pairing(prior_pairing["id"])
    a_prior = first_assignment_for(prior_pairing["id"], cm["id"])
    confirm_assignment(a_prior["id"], cm)
    set_clock(prior_end)
    complete_pairing(prior_pairing["id"])

    # Now build a new candidate Pairing for the caller to act on.
    set_clock("2026-06-01T00:00:00Z")
    new_pairing = create_pairing(
        pairing_code="P-2026-101",
        scheduled_start_utc=new_pairing_start,
        scheduled_end_utc=new_pairing_end,
        bidding_close_utc=new_pairing_close,
    )
    add_revenue_leg(
        new_pairing["id"],
        leg_sequence=1,
        departure="LAX",
        arrival="MIA",
        scheduled_departure_utc=new_leg_dep,
        scheduled_arrival_utc=new_leg_arr,
    )
    open_bidding(new_pairing["id"])
    submit_bid(new_pairing["id"], cm, requested_seat="CAPTAIN")
    # Advance one second past the new close time so BID_OPEN auto-closes.
    # Determine an instant strictly greater than new_pairing_close.
    set_clock(_one_second_past(new_pairing_close))
    award_pairing(new_pairing["id"])
    a_new = first_assignment_for(new_pairing["id"], cm["id"])
    cm_with_totals = get_crew_member(cm["id"])
    return cm_with_totals, a_new


def _one_second_past(iso: str) -> str:
    """Best-effort 'add one second' helper for ISO-8601 UTC instants of the form
    'YYYY-MM-DDTHH:MM:SSZ'. Used to ensure clock-set crosses bidding_close strictly.
    """
    from datetime import datetime, timedelta, timezone
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    dt = dt + timedelta(seconds=1)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
