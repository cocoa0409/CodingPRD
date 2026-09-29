"""Composite setup helpers.

The harness restarts the server and empties the database before every single
test, so each helper builds the state it needs from scratch through the declared
endpoints. Helpers use the lenient ``get_success_data`` internally — a fixture is
setup, not the thing under test — and every one accepts ``**overrides`` so a
test can vary the one field it cares about.

Layered as: primitives, then state-progression builders, then entity-hierarchy
builders, then lifecycle shortcuts, then accumulation and finalization helpers.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import T_18_10_00
from .test_users import (
    BOX_OFFICE_AGENT,
    GATE_OPERATOR,
    SECURITY_INVESTIGATOR,
    TICKETING_APPROVER,
    VENUE_ADMIN,
    make_patron_headers,
)
from .types import (
    DistributionType,
    EventStatus,
    Marketplace,
    ScanDirection,
    SessionMode,
    TicketType,
)

# The order of the event status chain, used to walk an event forward.
EVENT_CHAIN = [
    EventStatus.DRAFT,
    EventStatus.ON_SALE,
    EventStatus.DOORS_OPEN,
    EventStatus.IN_PROGRESS,
    EventStatus.CLOSED,
]


# ─── Primitives ───────────────────────────────────────────────────────────────


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock and return the clock reading."""
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), VENUE_ADMIN))


def create_event(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_event(f.event_payload(**overrides), VENUE_ADMIN))


def create_zone(api: ApiClient, event_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_access_zone(event_id, f.access_zone_payload(**overrides), VENUE_ADMIN)
    )


def create_gate(api: ApiClient, event_id: str, access_zone_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_gate(event_id, f.gate_payload(access_zone_id, **overrides), VENUE_ADMIN)
    )


def advance_event(api: ApiClient, event_id: str, target_status: str) -> Dict[str, Any]:
    return get_success_data(
        api.advance_event_status(event_id, f.advance_status_payload(target_status), VENUE_ADMIN)
    )


def advance_event_to(api: ApiClient, event_id: str, target_status: str) -> Dict[str, Any]:
    """Walk the event forward one declared successor at a time."""
    event = get_success_data(api.get_event(event_id, VENUE_ADMIN))
    current = EVENT_CHAIN.index(event["status"])
    for status in EVENT_CHAIN[current + 1 : EVENT_CHAIN.index(target_status) + 1]:
        event = advance_event(api, event_id, status)
    return event


def register_patron(
    api: ApiClient,
    email: str = "ada@example.com",
    display_name: str = "Ada Lovelace",
    verify: bool = True,
    document_reference: str = "DL-ADA-1",
) -> Dict[str, Any]:
    """Register a patron, recording the identity check unless ``verify`` is false."""
    patron = get_success_data(
        api.create_patron(f.patron_payload(email=email, display_name=display_name), BOX_OFFICE_AGENT)
    )
    if verify:
        patron = get_success_data(
            api.verify_patron_identity(
                patron["id"],
                f.verify_identity_payload(document_reference=document_reference),
                BOX_OFFICE_AGENT,
            )
        )
    return patron


def issue_ticket(
    api: ApiClient, event_id: str, access_zone_id: str, holder_patron_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_ticket(
            f.ticket_payload(event_id, access_zone_id, holder_patron_id, **overrides),
            BOX_OFFICE_AGENT,
        )
    )


def bind_device(
    api: ApiClient, ticket_id: str, patron_id: str, device_fingerprint: str = "DEV-A"
) -> Dict[str, Any]:
    return get_success_data(
        api.bind_device(
            ticket_id,
            f.device_binding_payload(device_fingerprint),
            make_patron_headers(patron_id),
        )
    )


def release_device(api: ApiClient, ticket_id: str, patron_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.release_device_binding(ticket_id, {}, make_patron_headers(patron_id))
    )


def read_ticket(api: ApiClient, ticket_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_ticket(ticket_id, VENUE_ADMIN))


def read_event(api: ApiClient, event_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_event(event_id, VENUE_ADMIN))


def read_zone(api: ApiClient, zone_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_access_zone(zone_id, VENUE_ADMIN))


def read_gate(api: ApiClient, gate_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_gate(gate_id, VENUE_ADMIN))


def read_patron(api: ApiClient, patron_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_patron(patron_id, VENUE_ADMIN))


def read_occupancy(api: ApiClient, event_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_event_occupancy(event_id, VENUE_ADMIN))


def get_barcode(api: ApiClient, ticket_id: str) -> Dict[str, Any]:
    """The rotating barcode read, taken as the admin who may read it."""
    return get_success_data(api.get_ticket_barcode(ticket_id, VENUE_ADMIN))


def current_barcode(api: ApiClient, ticket_id: str) -> str:
    return get_barcode(api, ticket_id)["current_barcode"]


def barcode_at_epoch(api: ApiClient, ticket_id: str, epoch_index: int) -> str:
    """A barcode string for this ticket's seed at an arbitrary epoch index."""
    seed = get_barcode(api, ticket_id)["barcode_seed"]
    return f"{seed}-{epoch_index}"


def open_scan_session(api: ApiClient, gate_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open a session, reading the gate's current version for the guard."""
    gate = read_gate(api, gate_id)
    payload = f.scan_session_payload(gate_id, gate["version"], **overrides)
    return get_success_data(api.create_scan_session(payload, GATE_OPERATOR))


def close_scan_session(api: ApiClient, session_id: str) -> Dict[str, Any]:
    return get_success_data(api.close_scan_session(session_id, {}, GATE_OPERATOR))


def live_scan(
    api: ApiClient,
    session_id: str,
    presented_barcode: str,
    device_fingerprint: str = "DEV-A",
    dedupe_key: str = "S1-ONLINE-001",
    **overrides: Any,
) -> Dict[str, Any]:
    """Record one live scan that is expected to succeed."""
    payload = f.scan_event_payload(
        presented_barcode, device_fingerprint, dedupe_key, **overrides
    )
    return get_success_data(api.create_scan_event(session_id, payload, GATE_OPERATOR))


def admit_ticket(
    api: ApiClient,
    session_id: str,
    ticket_id: str,
    device_fingerprint: str = "DEV-A",
    dedupe_key: str = "S1-ONLINE-001",
) -> Dict[str, Any]:
    """Admit a bound ticket through an open session at the current epoch."""
    return live_scan(
        api,
        session_id,
        current_barcode(api, ticket_id),
        device_fingerprint,
        dedupe_key,
    )


def exit_ticket(
    api: ApiClient,
    session_id: str,
    ticket_id: str,
    device_fingerprint: str = "DEV-A",
    dedupe_key: str = "S1-ONLINE-OUT",
) -> Dict[str, Any]:
    """Record an exit scan for a ticket that is inside."""
    return live_scan(
        api,
        session_id,
        current_barcode(api, ticket_id),
        device_fingerprint,
        dedupe_key,
        direction=ScanDirection.OUT,
    )


def create_listing(
    api: ApiClient,
    ticket_id: str,
    seller_patron_id: str,
    ask_price_cents: int,
    marketplace: str = Marketplace.VERIFIED_PRIMARY,
    **overrides: Any,
) -> Dict[str, Any]:
    """List a ticket, reading its current version for the stale-version guard."""
    ticket = read_ticket(api, ticket_id)
    payload = f.resale_listing_payload(
        ticket_id,
        ask_price_cents,
        ticket["version"],
        marketplace=marketplace,
        **overrides,
    )
    return get_success_data(
        api.create_resale_listing(payload, make_patron_headers(seller_patron_id))
    )


def create_credential_draft(
    api: ApiClient, event_id: str, access_zone_id: str, recipient_patron_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_credential_request(
            f.credential_request_payload(
                event_id, access_zone_id, recipient_patron_id, **overrides
            ),
            BOX_OFFICE_AGENT,
        )
    )


def submit_credential_request(api: ApiClient, request_id: str, headers=BOX_OFFICE_AGENT) -> Dict[str, Any]:
    return get_success_data(api.submit_credential_request(request_id, {}, headers))


def approve_credential_request(api: ApiClient, request_id: str) -> Dict[str, Any]:
    """Approve as an approver whose identifier differs from the submitting agent."""
    return get_success_data(
        api.approve_credential_request(request_id, f.note_payload("Approved"), TICKETING_APPROVER)
    )


def void_ticket(
    api: ApiClient, ticket_id: str, refund_to_holder: bool = False, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.void_ticket(
            ticket_id, f.void_payload(refund_to_holder, **overrides), SECURITY_INVESTIGATOR
        )
    )


def create_report(api: ApiClient, event_id: str, reported_attendance: int) -> Dict[str, Any]:
    """Cut a reconciliation report, reading the event's current version."""
    event = read_event(api, event_id)
    return get_success_data(
        api.create_reconciliation_report(
            event_id,
            f.reconciliation_report_payload(reported_attendance, event["version"]),
            VENUE_ADMIN,
        )
    )


# ─── Tier 1: state progression ────────────────────────────────────────────────


def draft_venue(api: ApiClient, **event_overrides: Any) -> Dict[str, Any]:
    """A `DRAFT` event with one zone and one gate — the geography is laid out."""
    event = create_event(api, **event_overrides)
    zone = create_zone(api, event["id"])
    gate = create_gate(api, event["id"], zone["id"])
    return {"event": event, "zone": zone, "gate": gate}


def on_sale_venue(api: ApiClient, **event_overrides: Any) -> Dict[str, Any]:
    """A venue advanced to `ON_SALE`, which unlocks issuance and submission."""
    venue = draft_venue(api, **event_overrides)
    venue["event"] = advance_event(api, venue["event"]["id"], EventStatus.ON_SALE)
    return venue


def doors_open_venue(api: ApiClient, **event_overrides: Any) -> Dict[str, Any]:
    """A venue advanced to `DOORS_OPEN`, which unlocks scan-session creation."""
    venue = on_sale_venue(api, **event_overrides)
    venue["event"] = advance_event(api, venue["event"]["id"], EventStatus.DOORS_OPEN)
    return venue


def in_progress_venue(api: ApiClient, **event_overrides: Any) -> Dict[str, Any]:
    venue = doors_open_venue(api, **event_overrides)
    venue["event"] = advance_event(api, venue["event"]["id"], EventStatus.IN_PROGRESS)
    return venue


# ─── Tier 2: entity hierarchy ─────────────────────────────────────────────────


def ticketed_venue(
    api: ApiClient,
    face_value_cents: int = 12000,
    ticket_type: str = TicketType.PAID,
    verify_holder: bool = True,
    **event_overrides: Any,
) -> Dict[str, Any]:
    """An `ON_SALE` venue with a verified holder and one issued ticket."""
    venue = on_sale_venue(api, **event_overrides)
    holder = register_patron(api, verify=verify_holder)
    ticket = issue_ticket(
        api,
        venue["event"]["id"],
        venue["zone"]["id"],
        holder["id"],
        ticket_type=ticket_type,
        face_value_cents=face_value_cents,
    )
    venue.update({"holder": holder, "ticket": ticket})
    return venue


def two_patron_venue(
    api: ApiClient,
    face_value_cents: int = 12000,
    verify_recipient: bool = True,
    **event_overrides: Any,
) -> Dict[str, Any]:
    """A ticketed venue plus a second patron to hand the entitlement to."""
    venue = ticketed_venue(api, face_value_cents=face_value_cents, **event_overrides)
    venue["other"] = register_patron(
        api,
        email="ben@example.com",
        display_name="Ben Hall",
        verify=verify_recipient,
        document_reference="DL-BEN-1",
    )
    return venue


# ─── Tier 3: full lifecycle shortcuts ─────────────────────────────────────────


def scan_ready_venue(
    api: ApiClient,
    at_instant: str = T_18_10_00,
    device_fingerprint: str = "DEV-A",
    mode: str = SessionMode.ONLINE,
    face_value_cents: int = 12000,
    **event_overrides: Any,
) -> Dict[str, Any]:
    """Doors open, clock at the scan instant, a bound ticket and an open session."""
    venue = on_sale_venue(api, **event_overrides)
    holder = register_patron(api)
    ticket = issue_ticket(
        api,
        venue["event"]["id"],
        venue["zone"]["id"],
        holder["id"],
        face_value_cents=face_value_cents,
    )
    ticket = bind_device(api, ticket["id"], holder["id"], device_fingerprint)
    venue["event"] = advance_event(api, venue["event"]["id"], EventStatus.DOORS_OPEN)
    set_clock(api, at_instant)
    session = open_scan_session(api, venue["gate"]["id"], mode=mode)
    venue.update({"holder": holder, "ticket": ticket, "session": session})
    return venue


def listed_venue(
    api: ApiClient, ask_price_cents: int = 14500, face_value_cents: int = 12000, **event_overrides: Any
) -> Dict[str, Any]:
    """A ticketed venue whose ticket sits `LISTED` on a verified marketplace."""
    venue = ticketed_venue(api, face_value_cents=face_value_cents, **event_overrides)
    venue["listing"] = create_listing(
        api, venue["ticket"]["id"], venue["holder"]["id"], ask_price_cents
    )
    venue["ticket"] = read_ticket(api, venue["ticket"]["id"])
    return venue


def submitted_credential_request(
    api: ApiClient,
    quantity: int = 2,
    distribution_type: str = DistributionType.CREDENTIAL,
    **request_overrides: Any,
) -> Dict[str, Any]:
    """An `ON_SALE` venue with a recipient and a `SUBMITTED` credential request."""
    venue = on_sale_venue(api)
    recipient = register_patron(api)
    request = create_credential_draft(
        api,
        venue["event"]["id"],
        venue["zone"]["id"],
        recipient["id"],
        quantity=quantity,
        distribution_type=distribution_type,
        **request_overrides,
    )
    request = submit_credential_request(api, request["id"])
    venue.update({"recipient": recipient, "request": request})
    return venue


# ─── Tier 4: accumulation and threshold targeting ─────────────────────────────


def denied_scan_response(
    api: ApiClient,
    session_id: str,
    presented_barcode: str,
    device_fingerprint: str,
    dedupe_key: str,
    **overrides: Any,
):
    """Submit a live scan expected to be adjudicated as a denial; raw response."""
    payload = f.scan_event_payload(
        presented_barcode, device_fingerprint, dedupe_key, **overrides
    )
    return api.create_scan_event(session_id, payload, GATE_OPERATOR)


def venue_with_device_mismatch_incident(
    api: ApiClient, face_value_cents: int = 12000, **event_overrides: Any
) -> Dict[str, Any]:
    """A scan-ready venue where the wrong device presented the barcode once."""
    venue = scan_ready_venue(api, face_value_cents=face_value_cents, **event_overrides)
    denied_scan_response(
        api,
        venue["session"]["id"],
        current_barcode(api, venue["ticket"]["id"]),
        "DEV-WRONG",
        "S1-ONLINE-MISMATCH",
    )
    incidents, _ = _list(api.list_denied_entry_incidents(SECURITY_INVESTIGATOR))
    venue["incident"] = incidents[0]
    venue["patron"] = read_patron(api, venue["holder"]["id"])
    return venue


def incident_under_review(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """The device-mismatch incident taken for review by the investigator."""
    venue = venue_with_device_mismatch_incident(api, **kwargs)
    venue["incident"] = get_success_data(
        api.start_incident_review(venue["incident"]["id"], {}, SECURITY_INVESTIGATOR)
    )
    return venue


def unauthorized_resale_attempts(
    api: ApiClient, attempts: int = 1, **event_overrides: Any
) -> Dict[str, Any]:
    """A ticketed venue where the holder offered through an unverified channel."""
    venue = ticketed_venue(api, **event_overrides)
    for _ in range(attempts):
        ticket = read_ticket(api, venue["ticket"]["id"])
        api.create_resale_listing(
            f.resale_listing_payload(
                venue["ticket"]["id"],
                12000,
                ticket["version"],
                marketplace=Marketplace.UNVERIFIED,
            ),
            make_patron_headers(venue["holder"]["id"]),
        )
    venue["patron"] = read_patron(api, venue["holder"]["id"])
    return venue


def _list(response):
    """Rows plus meta from a list response, without asserting a status code."""
    body = response.json()
    return body["data"], body["meta"]


def list_scan_events(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    rows, _ = _list(api.list_scan_events(GATE_OPERATOR, params=params or None))
    return rows


def list_incidents(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    rows, _ = _list(api.list_denied_entry_incidents(SECURITY_INVESTIGATOR, params=params or None))
    return rows


def list_audit_entries(api: ApiClient, event_id: str, **params: Any) -> List[Dict[str, Any]]:
    rows, _ = _list(api.list_audit_log_entries(event_id, VENUE_ADMIN, params=params or None))
    return rows


def list_listings(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    rows, _ = _list(api.list_resale_listings(VENUE_ADMIN, params=params or None))
    return rows


def list_tickets(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    rows, _ = _list(api.list_tickets(VENUE_ADMIN, params=params or None))
    return rows


# ─── Tier 5: finalization and terminal state ──────────────────────────────────


def closed_venue_with_report(
    api: ApiClient, reported_attendance: int = 0, **event_overrides: Any
) -> Dict[str, Any]:
    """A `CLOSED` event carrying one `DRAFT` reconciliation report."""
    venue = in_progress_venue(api, **event_overrides)
    venue["event"] = advance_event(api, venue["event"]["id"], EventStatus.CLOSED)
    venue["report"] = create_report(api, venue["event"]["id"], reported_attendance)
    return venue


def reconciled_venue(
    api: ApiClient, reported_attendance: int = 0, override_reason: Optional[str] = None
) -> Dict[str, Any]:
    """A finalized report, which drives its event to `RECONCILED`."""
    venue = closed_venue_with_report(api, reported_attendance)
    venue["report"] = get_success_data(
        api.finalize_reconciliation_report(
            venue["report"]["id"], f.finalize_payload(override_reason), VENUE_ADMIN
        )
    )
    venue["event"] = read_event(api, venue["event"]["id"])
    return venue


def close_event(api: ApiClient, event_id: str, session_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Close every named session and walk the event to `CLOSED`."""
    for session_id in session_ids or []:
        api.close_scan_session(session_id, {}, GATE_OPERATOR)
    return advance_event_to(api, event_id, EventStatus.CLOSED)
