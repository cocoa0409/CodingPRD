"""Composite setup helpers.

Every helper builds its preconditions from scratch through declared endpoints,
because each test starts against an empty database at the logical clock's
initial value 2026-08-01T00:00:00Z. OrgRequester calls always act through
per-instance headers carrying the real Organization id.

The PRD does not document list-endpoint filter query parameters, so helpers
that locate a related resource (for example an event's invoice) list the
collection unfiltered and select client-side on stored fields — that only
relies on PRD-covered behavior (PRD section 2.3 pagination and section 2.2
response envelope).
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_academic_block_payload,
    create_access_grant_payload,
    create_event_payload,
    create_organization_payload,
    create_room_payload,
    create_scheduling_run_payload,
    create_service_crew_payload,
    create_service_order_payload,
    create_term_payload,
)
from .test_users import (
    FACILITIES_MANAGER,
    FINANCE_ADMIN,
    SCHEDULER,
    SERVICE_COORDINATOR,
    make_org_requester_headers,
)


class Scenario(dict):
    """Dict with attribute access, so tests can read scn.event["id"]."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value


# ---------------------------------------------------------------------------
# Tier 1 — primitives (clock, orgs, rooms, terms)
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, SCHEDULER))


def daily_close() -> dict:
    """Run the ops daily-close checkpoint; returns the per-step counters."""
    return get_success_data(api_client.daily_close(SCHEDULER))


def create_org(**overrides) -> dict:
    return get_success_data(
        api_client.create_organization(create_organization_payload(**overrides), SCHEDULER)
    )


def get_org(org_id: str) -> dict:
    return get_success_data(api_client.get_organization(org_id, SCHEDULER))


def org_headers(org: dict) -> dict:
    """Ownership-correct OrgRequester headers for this organization."""
    return make_org_requester_headers(org["id"])


def create_room(**overrides) -> dict:
    return get_success_data(
        api_client.create_room(create_room_payload(**overrides), FACILITIES_MANAGER)
    )


def get_room(room_id: str) -> dict:
    return get_success_data(api_client.get_room(room_id, FACILITIES_MANAGER))


def create_term(**overrides) -> dict:
    return get_success_data(api_client.create_term(create_term_payload(**overrides), SCHEDULER))


def get_term(term_id: str) -> dict:
    return get_success_data(api_client.get_term(term_id, SCHEDULER))


def advance_term_to_scheduling(term_id: str, at: str = "2026-08-12T00:00:00Z") -> dict:
    """Advance the clock and close the day so the term flips DRAFT -> SCHEDULING."""
    set_clock(at)
    daily_close()
    return get_term(term_id)


# ---------------------------------------------------------------------------
# Tier 1 — events
# ---------------------------------------------------------------------------


def create_event(org: dict, room_id: str, expected_room_version=None, **overrides) -> dict:
    """Create a REQUESTED event for the org, reading the room's current version
    unless an explicit expected_room_version is supplied."""
    if expected_room_version is None:
        expected_room_version = get_room(room_id)["version"]
    return get_success_data(
        api_client.create_event_reservation(
            create_event_payload(
                room_id, expected_room_version, **overrides
            ),
            make_org_requester_headers(org["id"]),
        )
    )


def get_event(event_id: str) -> dict:
    return get_success_data(api_client.get_event_reservation(event_id, SCHEDULER))


def approve_event(event_id: str, headers=None) -> dict:
    return get_success_data(api_client.approve_event(event_id, headers or SCHEDULER))


def confirm_event(event_id: str, org: dict) -> dict:
    return get_success_data(
        api_client.confirm_event(event_id, make_org_requester_headers(org["id"]))
    )


def check_in_event(event_id: str, org: dict = None) -> dict:
    headers = (
        make_org_requester_headers(org["id"]) if org is not None else FACILITIES_MANAGER
    )
    return get_success_data(api_client.check_in_event(event_id, headers))


# ---------------------------------------------------------------------------
# Tier 1 — academic blocks and scheduling runs
# ---------------------------------------------------------------------------


def create_block(term_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_academic_block(
            create_academic_block_payload(term_id, **overrides), SCHEDULER
        )
    )


def get_block(block_id: str) -> dict:
    return get_success_data(api_client.get_academic_block(block_id, SCHEDULER))


def create_run(term_id: str, expected_term_version=None) -> dict:
    """Create a DRAFT scheduling run, reading the term's current version unless
    an explicit expected_term_version is supplied."""
    if expected_term_version is None:
        expected_term_version = get_term(term_id)["version"]
    return get_success_data(
        api_client.create_scheduling_run(
            create_scheduling_run_payload(term_id, expected_term_version), SCHEDULER
        )
    )


def get_run(run_id: str) -> dict:
    return get_success_data(api_client.get_scheduling_run(run_id, SCHEDULER))


def finalize_run(run_id: str) -> dict:
    return get_success_data(api_client.finalize_scheduling_run(run_id, SCHEDULER))


# ---------------------------------------------------------------------------
# Tier 1 — service orders and crews
# ---------------------------------------------------------------------------


def create_order(event_id: str, org: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_order(
            create_service_order_payload(event_id, **overrides),
            make_org_requester_headers(org["id"]),
        )
    )


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_service_order(order_id, SERVICE_COORDINATOR))


def quote_order(order_id: str, unit_cost_cents: int) -> dict:
    return get_success_data(
        api_client.quote_service_order(
            order_id, {"unit_cost_cents": unit_cost_cents}, SERVICE_COORDINATOR
        )
    )


def approve_order(order_id: str, org: dict) -> dict:
    return get_success_data(
        api_client.approve_service_order(order_id, make_org_requester_headers(org["id"]))
    )


def schedule_order(order_id: str, crew_id: str) -> dict:
    return get_success_data(
        api_client.schedule_service_order(order_id, {"crew_id": crew_id}, SERVICE_COORDINATOR)
    )


def create_crew(**overrides) -> dict:
    return get_success_data(
        api_client.create_service_crew(
            create_service_crew_payload(**overrides), SERVICE_COORDINATOR
        )
    )


# ---------------------------------------------------------------------------
# Tier 1 — invoices
# ---------------------------------------------------------------------------


def list_all_invoices() -> list:
    """Unfiltered invoice list (FinanceAdmin); client-side selection only."""
    return get_success_data(api_client.list_invoices(FINANCE_ADMIN))


def find_invoice_for_event(event_id: str, status: str = None) -> dict:
    """Select an event's invoice client-side from the unfiltered list."""
    matches = [inv for inv in list_all_invoices() if inv["event_id"] == event_id]
    if status is not None:
        matches = [inv for inv in matches if inv["status"] == status]
    assert len(matches) >= 1, f"no invoice found for event {event_id} (status={status})"
    return matches[0]


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, FINANCE_ADMIN))


def pay_invoice(invoice_id: str, amount_cents: int, org: dict = None) -> dict:
    headers = (
        make_org_requester_headers(org["id"]) if org is not None else FINANCE_ADMIN
    )
    return get_success_data(
        api_client.pay_invoice(invoice_id, {"amount_cents": amount_cents}, headers)
    )


# ---------------------------------------------------------------------------
# Tier 1 — access grants
# ---------------------------------------------------------------------------


def create_grant(event_id: str, org: dict = None, **overrides) -> dict:
    """Request an access grant; FacilitiesManager files on behalf unless an org
    is given, in which case the owning OrgRequester files."""
    headers = (
        make_org_requester_headers(org["id"]) if org is not None else FACILITIES_MANAGER
    )
    return get_success_data(
        api_client.create_access_grant(
            create_access_grant_payload(event_id, **overrides), headers
        )
    )


def get_grant(grant_id: str) -> dict:
    return get_success_data(api_client.get_access_grant(grant_id, FACILITIES_MANAGER))


def issue_grant(grant_id: str) -> dict:
    return get_success_data(api_client.issue_access_grant(grant_id, FACILITIES_MANAGER))


# ---------------------------------------------------------------------------
# Tier 2 — composite scenarios
# ---------------------------------------------------------------------------


def setup_org_room(org_overrides=None, room_overrides=None) -> Scenario:
    """One organization and one room. Returns Scenario(org, room)."""
    org = create_org(**(org_overrides or {}))
    room = create_room(**(room_overrides or {}))
    return Scenario(org=org, room=room)


def setup_approved_event(org_overrides=None, room_overrides=None, event_overrides=None):
    """Org + room + event driven to APPROVED. Returns Scenario(org, room, event, invoice)."""
    scn = setup_org_room(org_overrides, room_overrides)
    scn.event = create_event(scn.org, scn.room["id"], **(event_overrides or {}))
    scn.event = approve_event(scn.event["id"])
    scn.invoice = find_invoice_for_event(scn.event["id"])
    return scn


def setup_confirmed_event(org_overrides=None, room_overrides=None, event_overrides=None):
    """Org + room + event driven to CONFIRMED. Returns Scenario(org, room, event, invoice)."""
    scn = setup_approved_event(org_overrides, room_overrides, event_overrides)
    scn.event = confirm_event(scn.event["id"], scn.org)
    return scn


def setup_org_with_no_shows(strikes: int, room_overrides=None) -> Scenario:
    """Drive an organization to `strikes` no-show marks via adjacent one-hour
    CONFIRMED events on 2026-09-10 (room buffer 0) that are never checked in.

    Two strikes lands the org on PROBATION; three on SUSPENDED (PRD section 3.1).
    The logical clock ends at 2026-09-10T12:00:00Z. Returns Scenario(org, room,
    events, close_counters).
    """
    assert 1 <= strikes <= 3
    base_room = {"turnaround_buffer_minutes": 0}
    base_room.update(room_overrides or {})
    scn = setup_org_room(room_overrides=base_room)

    events = []
    for i in range(strikes):
        start = f"2026-09-10T{8 + i:02d}:00:00Z"
        end = f"2026-09-10T{9 + i:02d}:00:00Z"
        ev = create_event(scn.org, scn.room["id"], start_at=start, end_at=end,
                          expected_attendance=5)
        approve_event(ev["id"])
        events.append(ev)

    # Confirm within the 48h confirmation window of approval.
    set_clock("2026-08-02T00:00:00Z")
    for ev in events:
        confirm_event(ev["id"], scn.org)

    set_clock("2026-09-10T12:00:00Z")
    scn.events = events
    scn.close_counters = daily_close()
    scn.org = get_org(scn.org["id"])
    return scn


def drive_event_to_completed(event_id: str, org: dict, end_at: str) -> dict:
    """Check the event in inside its window and close the day past its end so
    the daily-close moves IN_PROGRESS -> COMPLETED. Returns the closed event.

    `end_at` must be an ISO instant strictly after the event's end_at and the
    current clock value.
    """
    event = get_event(event_id)
    # Check-in window opens 30 minutes before start_at; land on start_at.
    set_clock(event["start_at"])
    check_in_event(event_id, org)
    set_clock(end_at)
    daily_close()
    return get_event(event_id)


# ---------------------------------------------------------------------------
# Tier 4 — academic placement scenarios
# ---------------------------------------------------------------------------


def setup_placement_contention() -> Scenario:
    """A SCHEDULING term where two STAGE blocks compete for a single STAGE room
    already holding a bumpable REQUESTED event on Monday 2026-10-05.

    Block BX (enrollment 180) outscores block BY (enrollment 140); both meet
    MON 10:00-11:00. The REQUESTED event 09:30-11:30 plus the room's 30-minute
    turnaround buffer occupies the room until 12:00.

    Returns Scenario(term, org, room, bx, by, event) BEFORE any run is created;
    the clock is left at 2026-08-12 with the term in SCHEDULING.
    """
    term = create_term()
    bx = create_block(
        term["id"],
        course_code="BIO-500",
        instructor_name="Dr. X",
        enrollment=180,
        days_of_week=["MON"],
        start_time="10:00",
        end_time="11:00",
        required_features=["STAGE"],
    )
    by = create_block(
        term["id"],
        course_code="BIO-501",
        instructor_name="Dr. Y",
        enrollment=140,
        days_of_week=["MON"],
        start_time="10:00",
        end_time="11:00",
        required_features=["STAGE"],
    )
    org = create_org(name="Dept Chem", contact_email="chem@univ.edu")
    room = create_room(
        name="HALL-C", building_code="HLL", capacity=200, features=["STAGE"]
    )
    advance_term_to_scheduling(term["id"])
    event = create_event(
        org,
        room["id"],
        title="Seminar",
        expected_attendance=100,
        start_at="2026-10-05T09:30:00Z",
        end_at="2026-10-05T11:30:00Z",
    )
    return Scenario(term=term, org=org, room=room, bx=bx, by=by, event=event)


def setup_completed_event_with_unfulfilled_quote() -> Scenario:
    """An INTERNAL event (2026-09-10 14:00-16:00, room rate 5000 -> room charge
    10000) carrying one CATERING order quoted at 2 x 3000 = 6000 that is never
    approved or fulfilled, checked in and completed by the daily-close.

    Returns Scenario(org, room, event, order, prov_invoice, invoice) where
    prov_invoice is the PROVISIONAL snapshot taken before completion and
    invoice is the finalized invoice after it; the clock ends at
    2026-09-10T17:00.
    """
    scn = setup_approved_event(
        org_overrides={"name": "Dept Math", "contact_email": "math@univ.edu"},
        room_overrides={"name": "MTH-101", "building_code": "MTH", "capacity": 50},
        event_overrides={
            "title": "Colloquium",
            "expected_attendance": 20,
            "start_at": "2026-09-10T14:00:00Z",
            "end_at": "2026-09-10T16:00:00Z",
        },
    )
    order = create_order(
        scn.event["id"], scn.org, category="CATERING", quantity=2,
        service_start_at="2026-09-10T14:00:00Z",
        service_end_at="2026-09-10T15:00:00Z",
    )
    quote_order(order["id"], 3000)
    # Snapshot the forward-looking provisional invoice before completion.
    scn.prov_invoice = find_invoice_for_event(scn.event["id"])
    confirm_event(scn.event["id"], scn.org)
    # Check-in window for a 14:00 start is [13:30, 14:15].
    set_clock("2026-09-10T13:45:00Z")
    check_in_event(scn.event["id"], scn.org)
    set_clock("2026-09-10T17:00:00Z")
    daily_close()
    scn.order = get_order(order["id"])
    scn.event = get_event(scn.event["id"])
    scn.invoice = find_invoice_for_event(scn.event["id"])
    return scn


def setup_approved_orders_on_rooms(windows, category="AV", quantity=1,
                                   unit_cost_cents=1000) -> Scenario:
    """One org plus one room, one APPROVED event, and one QUOTED-then-APPROVED
    service order per window tuple.

    `windows` is a list of (service_start_at, service_end_at) ISO pairs. Each
    order sits on its own room and event (2026-09-16 14:00-15:00, attendance 10,
    capacity 20), so events never conflict. The service margin around that event
    is [12:00, 17:00], which every design window respects.

    Returns Scenario(org, rooms, events, orders).
    """
    org = create_org(name="AV Users", contact_email="av@univ.edu")
    rooms, events, orders = [], [], []
    for idx, (svc_start, svc_end) in enumerate(windows):
        room = create_room(
            name=f"AV-{idx + 1}", building_code="AVB", capacity=20,
        )
        event = create_event(
            org, room["id"], title=f"S{idx + 1}", expected_attendance=10,
            start_at="2026-09-16T14:00:00Z", end_at="2026-09-16T15:00:00Z",
        )
        approve_event(event["id"])
        order = create_order(
            event["id"], org, category=category, quantity=quantity,
            service_start_at=svc_start, service_end_at=svc_end,
        )
        quote_order(order["id"], unit_cost_cents)
        approve_order(order["id"], org)
        rooms.append(room)
        events.append(event)
        orders.append(order)
    return Scenario(org=org, rooms=rooms, events=events, orders=orders)


def setup_noshow_chain_with_pending_request() -> Scenario:
    """An org with three CONFIRMED never-checked-in events (2026-09-10/11/12
    14:00-15:00) and a fourth event left REQUESTED whose decision deadline
    (2026-09-15T15:00) survives the close. The clock ends at 2026-09-12T16:00,
    BEFORE the daily-close is run — the caller triggers the checkpoint.

    Returns Scenario(org, room, no_show_events, pending_event).
    """
    scn = setup_org_room(
        org_overrides={"name": "Debate Union", "contact_email": "debate@univ.edu"},
        room_overrides={"name": "CLA-10", "building_code": "CLA", "capacity": 40},
    )
    no_show_events = []
    for day in ("10", "11", "12"):
        ev = create_event(
            scn.org, scn.room["id"], title=f"N{day}", expected_attendance=10,
            start_at=f"2026-09-{day}T14:00:00Z",
            end_at=f"2026-09-{day}T15:00:00Z",
        )
        approve_event(ev["id"])
        no_show_events.append(ev)
    set_clock("2026-08-02T00:00:00Z")
    for ev in no_show_events:
        confirm_event(ev["id"], scn.org)

    set_clock("2026-09-12T15:00:00Z")
    pending = create_event(
        scn.org, scn.room["id"], title="Future meet", expected_attendance=10,
        start_at="2026-09-20T14:00:00Z", end_at="2026-09-20T15:00:00Z",
    )
    set_clock("2026-09-12T16:00:00Z")
    scn.no_show_events = no_show_events
    scn.pending_event = pending
    return scn


def setup_finalize_bump_chain() -> Scenario:
    """A SCHEDULING term plus a CONFIRMED event (bumpable: far future, no issued
    grants) carrying a QUOTED catering order and a REQUESTED key grant, and an
    academic block whose only feasible room is the event's room.

    Returns Scenario(term, org, room, event, order, grant, invoice, block,
    out_before) BEFORE any run is created; the clock is left at 2026-08-12
    with the term in SCHEDULING.
    """
    term = create_term()
    org = create_org(name="Dept Bio", contact_email="bio@univ.edu")
    room = create_room(
        name="HALL-F", building_code="HLL", capacity=100, features=["STAGE"],
        key_count=1,
    )
    event = create_event(
        org,
        room["id"],
        title="Symposium",
        expected_attendance=90,
        start_at="2026-10-05T10:00:00Z",
        end_at="2026-10-05T12:00:00Z",
    )
    event = approve_event(event["id"])
    confirm_event(event["id"], org)
    order = create_order(
        event["id"],
        org,
        category="CATERING",
        quantity=2,
        service_start_at="2026-10-05T10:00:00Z",
        service_end_at="2026-10-05T12:00:00Z",
    )
    quote_order(order["id"], 3000)
    grant = create_grant(event["id"], org, grant_type="PHYSICAL_KEY")
    invoice = find_invoice_for_event(event["id"])
    out_before = get_org(org["id"])["outstanding_balance_cents"]

    block = create_block(
        term["id"],
        course_code="GEO-210",
        instructor_name="Dr. G",
        enrollment=80,
        days_of_week=["MON"],
        start_time="10:30",
        end_time="11:30",
        required_features=["STAGE"],
    )
    advance_term_to_scheduling(term["id"])
    return Scenario(
        term=term, org=org, room=room, event=event, order=order, grant=grant,
        invoice=invoice, block=block, out_before=out_before,
    )
