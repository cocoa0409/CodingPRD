"""Composite setup helpers — encapsulate multi-step setup sequences so tests
can focus on assertions, not plumbing.

All fixtures use get_success_data() so setup failures produce clear
"Setup failed" errors instead of confusing assertion failures.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_airport_payload,
    create_terminal_payload,
    create_segment_payload,
    create_passenger_payload,
    create_agent_payload,
    create_wheelchair_payload,
    create_assist_request_payload,
    create_leg_payload,
)
from .test_users import (
    TEST_USERS,
    make_agent_headers,
    make_confirmer_headers,
    make_dispatcher_headers,
    make_requester_headers,
    make_billing_clerk_headers,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1 — basic creation primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    resp = api_client.set_current_utc(to_iso8601, ADMIN)
    return get_success_data(resp)


def create_airport(iata_code: str = "TST", tz_offset_minutes: int = -300,
                   meet_buffer_minutes: int = 15, **overrides) -> dict:
    payload = create_airport_payload(
        iata_code=iata_code,
        tz_offset_minutes=tz_offset_minutes,
        meet_buffer_minutes=meet_buffer_minutes,
        **overrides,
    )
    resp = api_client.create_airport(payload, ADMIN)
    return get_success_data(resp)


def create_terminal(airport_id: str, code: str = "T1",
                    requires_secure_escort: bool = False, **overrides) -> dict:
    payload = create_terminal_payload(
        code=code, requires_secure_escort=requires_secure_escort, **overrides,
    )
    resp = api_client.create_terminal(airport_id, payload, ADMIN)
    return get_success_data(resp)


def create_segment(airport_id: str, terminal_id: str,
                   flight_no: str = "UA100", direction: str = "ARRIVAL",
                   scheduled_utc: str = "2026-06-16T10:00:00Z",
                   **overrides) -> dict:
    payload = create_segment_payload(
        flight_no=flight_no, direction=direction,
        terminal_id=terminal_id, scheduled_utc=scheduled_utc,
        **overrides,
    )
    resp = api_client.create_segment(airport_id, payload, ADMIN)
    return get_success_data(resp)


def create_passenger(**overrides) -> dict:
    payload = create_passenger_payload(**overrides)
    resp = api_client.create_passenger(payload, REQ)
    return get_success_data(resp)


def create_agent(airport_id: str, **overrides) -> dict:
    payload = create_agent_payload(**overrides)
    resp = api_client.create_agent(airport_id, payload, ADMIN)
    return get_success_data(resp)


def create_wheelchair(airport_id: str, **overrides) -> dict:
    payload = create_wheelchair_payload(**overrides)
    resp = api_client.create_wheelchair(airport_id, payload, ADMIN)
    return get_success_data(resp)


def create_assist_request(passenger_id: str, **overrides) -> dict:
    payload = create_assist_request_payload(passenger_id=passenger_id, **overrides)
    resp = api_client.create_assist_request(payload, REQ)
    return get_success_data(resp)


def create_leg(request_id: str, segment_id: str, **overrides) -> dict:
    payload = create_leg_payload(segment_id=segment_id, **overrides)
    resp = api_client.create_leg(request_id, payload, REQ)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2 — request-level composites
# ---------------------------------------------------------------------------

def setup_airport_with_terminal_and_segment(
    iata_code: str = "TST",
    meet_buffer_minutes: int = 15,
    requires_secure_escort: bool = False,
    flight_no: str = "UA100",
    direction: str = "ARRIVAL",
    scheduled_utc: str = "2026-06-16T10:00:00Z",
    segment_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict]:
    """Create airport + terminal + segment. Returns (airport, terminal, segment)."""
    airport = create_airport(iata_code=iata_code, meet_buffer_minutes=meet_buffer_minutes)
    terminal = create_terminal(airport["id"], requires_secure_escort=requires_secure_escort)
    seg_ov = segment_overrides or {}
    segment = create_segment(
        airport["id"], terminal["id"],
        flight_no=flight_no, direction=direction, scheduled_utc=scheduled_utc,
        **seg_ov,
    )
    return airport, terminal, segment


def setup_request_with_one_leg(
    iata_code: str = "TST",
    meet_buffer_minutes: int = 15,
    requires_secure_escort: bool = False,
    scheduled_utc: str = "2026-06-16T10:00:00Z",
    leg_kind: str = "MEET_ARRIVAL",
    passenger_overrides: Optional[dict] = None,
    request_overrides: Optional[dict] = None,
    leg_overrides: Optional[dict] = None,
) -> dict:
    """Create airport/terminal/segment/passenger/request/leg.
    Returns dict of all created entities."""
    airport, terminal, segment = setup_airport_with_terminal_and_segment(
        iata_code=iata_code,
        meet_buffer_minutes=meet_buffer_minutes,
        requires_secure_escort=requires_secure_escort,
        scheduled_utc=scheduled_utc,
    )
    passenger = create_passenger(**(passenger_overrides or {}))
    request = create_assist_request(passenger["id"], **(request_overrides or {}))
    leg = create_leg(request["id"], segment["id"],
                     leg_kind=leg_kind, **(leg_overrides or {}))
    return {
        "airport": airport,
        "terminal": terminal,
        "segment": segment,
        "passenger": passenger,
        "request": request,
        "leg": leg,
    }


def submit_request(request_id: str, expected_version: Optional[int] = None,
                   headers: Optional[dict] = None) -> dict:
    """SUBMIT an assist request. If expected_version is None, fetch fresh."""
    hdrs = headers or REQ
    if expected_version is None:
        cur = get_success_data(api_client.get_assist_request(request_id, hdrs))
        expected_version = cur["version"]
    resp = api_client.post_assist_request_event(
        request_id,
        {"event_type": "SUBMIT", "expected_assist_request_version": expected_version},
        hdrs,
    )
    return get_success_data(resp)


def setup_submitted_request(
    iata_code: str = "TST",
    meet_buffer_minutes: int = 15,
    requires_secure_escort: bool = False,
    scheduled_utc: str = "2026-06-16T10:00:00Z",
    leg_kind: str = "MEET_ARRIVAL",
    passenger_overrides: Optional[dict] = None,
    request_overrides: Optional[dict] = None,
    leg_overrides: Optional[dict] = None,
    clock_at_submit: str = "2026-06-16T09:00:00Z",
) -> dict:
    """Full setup through SUBMITTED. Returns dict of entities + updated request."""
    out = setup_request_with_one_leg(
        iata_code=iata_code,
        meet_buffer_minutes=meet_buffer_minutes,
        requires_secure_escort=requires_secure_escort,
        scheduled_utc=scheduled_utc,
        leg_kind=leg_kind,
        passenger_overrides=passenger_overrides,
        request_overrides=request_overrides,
        leg_overrides=leg_overrides,
    )
    set_clock(clock_at_submit)
    out["request"] = submit_request(out["request"]["id"])
    return out


# ---------------------------------------------------------------------------
# Tier 3 — dispatch / lifecycle shortcuts
# ---------------------------------------------------------------------------

def dispatch_leg(leg_id: str, request_id: str,
                 dispatcher_headers: Optional[dict] = None) -> dict:
    """Dispatch a PLANNED leg with the parent's current version."""
    hdrs = dispatcher_headers or DISP
    cur = get_success_data(api_client.get_assist_request(request_id, hdrs))
    resp = api_client.dispatch_leg(
        leg_id,
        {"expected_assist_request_version": cur["version"]},
        hdrs,
    )
    return get_success_data(resp)


def setup_dispatched_assignment(
    iata_code: str = "TST",
    meet_buffer_minutes: int = 15,
    requires_secure_escort: bool = False,
    scheduled_utc: str = "2026-06-16T10:00:00Z",
    leg_kind: str = "MEET_ARRIVAL",
    passenger_overrides: Optional[dict] = None,
    request_overrides: Optional[dict] = None,
    leg_overrides: Optional[dict] = None,
    agent_overrides: Optional[dict] = None,
    wheelchair_overrides: Optional[dict] = None,
    clock_at_submit: str = "2026-06-16T09:00:00Z",
    dispatcher_user_id: Optional[str] = None,
) -> dict:
    """Setup through DISPATCHED. Returns entities + agent + wheelchair + assignment."""
    # PRD §3.4 agent eligibility: "The current logical clock lies within the
    # agent's shift window, inclusive of both `shift_start_utc` and
    # `shift_end_utc`." The dispatch happens at `clock_at_submit`, so when the
    # caller does not pin an explicit shift, derive one that covers that
    # instant (factory defaults are anchored to a fixed calendar day and would
    # leave scenario clocks on other days outside the window).
    agent_ov = dict(agent_overrides or {})
    if "shift_start_utc" not in agent_ov or "shift_end_utc" not in agent_ov:
        base = datetime.fromisoformat(clock_at_submit.replace("Z", "+00:00"))
        start = base - timedelta(hours=1)
        end = base + timedelta(hours=8)  # 9h window, within the 12h PRD cap
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        agent_ov.setdefault("shift_start_utc", start.strftime(fmt))
        agent_ov.setdefault("shift_end_utc", end.strftime(fmt))
    out = setup_submitted_request(
        iata_code=iata_code,
        meet_buffer_minutes=meet_buffer_minutes,
        requires_secure_escort=requires_secure_escort,
        scheduled_utc=scheduled_utc,
        leg_kind=leg_kind,
        passenger_overrides=passenger_overrides,
        request_overrides=request_overrides,
        leg_overrides=leg_overrides,
        clock_at_submit=clock_at_submit,
    )
    agent = create_agent(out["airport"]["id"], **agent_ov)
    out["agent"] = agent
    # Wheelchair only when leg requires it
    leg = get_success_data(api_client.get_leg(out["leg"]["id"], DISP))
    if leg.get("requires_wheelchair"):
        wc = create_wheelchair(out["airport"]["id"], **(wheelchair_overrides or {}))
        out["wheelchair"] = wc
    else:
        out["wheelchair"] = None
    disp_hdrs = (make_dispatcher_headers(dispatcher_user_id)
                 if dispatcher_user_id else DISP)
    out["dispatcher_headers"] = disp_hdrs
    out["assignment"] = dispatch_leg(out["leg"]["id"], out["request"]["id"], disp_hdrs)
    # Refresh leg/request to reflect dispatch side effects
    out["leg"] = get_success_data(api_client.get_leg(out["leg"]["id"], DISP))
    out["request"] = get_success_data(api_client.get_assist_request(out["request"]["id"], DISP))
    return out


def walk_assignment_to_handed_off(assignment_id: str, agent_id: str,
                                  umnr_second_signoff_user_id: Optional[str] = None) -> dict:
    """Drive assignment ARRIVE_PICKUP → DEPART_PICKUP → ARRIVE_GATE → HANDOFF.
    Returns the assignment payload after HANDOFF."""
    hdrs = make_agent_headers(agent_id)
    get_success_data(api_client.post_assignment_event(
        assignment_id, {"event_type": "ARRIVE_PICKUP"}, hdrs,
    ))
    get_success_data(api_client.post_assignment_event(
        assignment_id, {"event_type": "DEPART_PICKUP"}, hdrs,
    ))
    get_success_data(api_client.post_assignment_event(
        assignment_id, {"event_type": "ARRIVE_GATE"}, hdrs,
    ))
    handoff_payload = {"event_type": "HANDOFF"}
    if umnr_second_signoff_user_id is not None:
        handoff_payload["umnr_second_signoff_user_id"] = umnr_second_signoff_user_id
    return get_success_data(api_client.post_assignment_event(
        assignment_id, handoff_payload, hdrs,
    ))


def complete_assignment(assignment_id: str, confirmer_user_id: str = "confirmer-1") -> dict:
    """COMPLETE an assignment as a Confirmer distinct from the dispatcher."""
    hdrs = make_confirmer_headers(confirmer_user_id)
    resp = api_client.post_assignment_event(
        assignment_id, {"event_type": "COMPLETE"}, hdrs,
    )
    return get_success_data(resp)


def setup_completed_request(
    iata_code: str = "TST",
    meet_buffer_minutes: int = 15,
    requires_secure_escort: bool = False,
    scheduled_utc: str = "2026-06-16T10:00:00Z",
    actual_utc: Optional[str] = None,
    segment_event: str = "LANDED",
    leg_kind: str = "MEET_ARRIVAL",
    passenger_overrides: Optional[dict] = None,
    request_overrides: Optional[dict] = None,
    leg_overrides: Optional[dict] = None,
    agent_overrides: Optional[dict] = None,
    wheelchair_overrides: Optional[dict] = None,
    clock_at_submit: str = "2026-06-16T09:00:00Z",
    dispatcher_user_id: Optional[str] = None,
    confirmer_user_id: str = "confirmer-1",
    umnr_second_signoff_user_id: Optional[str] = None,
) -> dict:
    """Full lifecycle through COMPLETED. Returns entities including final request
    and invoice list."""
    out = setup_dispatched_assignment(
        iata_code=iata_code,
        meet_buffer_minutes=meet_buffer_minutes,
        requires_secure_escort=requires_secure_escort,
        scheduled_utc=scheduled_utc,
        leg_kind=leg_kind,
        passenger_overrides=passenger_overrides,
        request_overrides=request_overrides,
        leg_overrides=leg_overrides,
        agent_overrides=agent_overrides,
        wheelchair_overrides=wheelchair_overrides,
        clock_at_submit=clock_at_submit,
        dispatcher_user_id=dispatcher_user_id,
    )
    walk_assignment_to_handed_off(
        out["assignment"]["id"], out["agent"]["id"],
        umnr_second_signoff_user_id=umnr_second_signoff_user_id,
    )
    # Mark segment with actual_utc if provided (before COMPLETE so final charge uses it)
    if actual_utc is not None:
        get_success_data(api_client.post_segment_event(
            out["segment"]["id"],
            {"event_type": segment_event, "actual_utc": actual_utc},
            OPS,
        ))
    out["assignment"] = complete_assignment(
        out["assignment"]["id"], confirmer_user_id=confirmer_user_id,
    )
    out["leg"] = get_success_data(api_client.get_leg(out["leg"]["id"], DISP))
    out["request"] = get_success_data(api_client.get_assist_request(out["request"]["id"], DISP))
    invoices_resp = api_client.list_request_invoices(out["request"]["id"], CLERK)
    out["invoices"] = get_success_data(invoices_resp)
    if out["wheelchair"] is not None:
        out["wheelchair"] = get_success_data(
            api_client.get_wheelchair(out["wheelchair"]["id"], DISP),
        )
    out["agent"] = get_success_data(api_client.get_agent(out["agent"]["id"], DISP))
    return out
