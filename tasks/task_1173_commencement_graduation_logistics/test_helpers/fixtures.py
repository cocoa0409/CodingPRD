"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch using only PRD-declared
endpoints. Setup calls use get_success_data() (lenient) so failures surface
as clear "Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import GPA_LEDGERS, TEST_DEFAULTS
from .factories import (
    create_venue_payload, create_ceremony_payload, create_graduate_payload,
    create_ticket_request_payload, create_regalia_order_payload,
    create_seat_assignment_payload, create_reader_card_payload,
    create_rehearsal_session_payload, create_accommodation_request_payload,
    create_vendor_contract_payload, create_queue_diploma_payload,
)
from .test_users import (
    TEST_USERS, make_graduate_headers, make_registrar_headers,
    make_coordinator_headers,
)

CHAIR = TEST_USERS["committee_chair_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
COORDINATOR = TEST_USERS["venue_coordinator_headers"]

# Segregation-of-duties operator ids (PRD §2.7)
REG_A = "reg-a-1"   # batch creator
REG_B = "reg-b-1"   # batch releaser
COORD_A = "coord-a"  # strike recorder / accommodation approver
COORD_B = "coord-b"  # strike waver / accommodation fulfiller


# --- Tier 1: single-resource creation and posture progression ---

def create_venue(total_capacity=10, accessible_capacity=2, indoor=True,
                 name="Main Arena", address="1 College Ave") -> dict:
    res = api_client.create_venue(
        create_venue_payload(name=name, address=address,
                             total_capacity=total_capacity,
                             accessible_capacity=accessible_capacity,
                             indoor=indoor), COORDINATOR)
    return get_success_data(res)


def create_ceremony(venue_id, rain_venue_id=None, ticket_ratio=1.0,
                    guest_ticket_base_cap=4, honor_bonus_tickets=2,
                    name="Spring Commencement") -> dict:
    """Create a ceremony (starts PLANNING / FAIR, pools initialized)."""
    payload = create_ceremony_payload(
        venue_id, name=name, ticket_ratio=ticket_ratio,
        guest_ticket_base_cap=guest_ticket_base_cap,
        honor_bonus_tickets=honor_bonus_tickets)
    if rain_venue_id is not None:
        payload["rain_venue_id"] = rain_venue_id
    res = api_client.create_ceremony(payload, CHAIR)
    return get_success_data(res)


def open_ceremony_audit(ceremony_id) -> dict:
    return get_success_data(api_client.open_audit(ceremony_id, CHAIR))


def lock_ceremony_audit(ceremony_id) -> dict:
    return get_success_data(api_client.lock_audit(ceremony_id, CHAIR))


def setup_ceremony(ticket_ratio=1.0, guest_ticket_base_cap=4, honor_bonus_tickets=2,
                   venue_capacity=10, venue_accessible=2, venue_indoor=True,
                   rain_capacity=None, rain_accessible=None, open_audit=False,
                   lock_audit=False):
    """Create venue(s) + ceremony, optionally walking to AUDIT_OPEN / AUDIT_LOCKED.

    Returns dict with keys: ceremony, venue, rain_venue (or None).
    """
    venue = create_venue(total_capacity=venue_capacity,
                         accessible_capacity=venue_accessible,
                         indoor=venue_indoor)
    rain_venue = None
    if rain_capacity is not None:
        rain_venue = create_venue(total_capacity=rain_capacity,
                                  accessible_capacity=(rain_accessible if rain_accessible is not None else 1),
                                  indoor=True, name="Rain Hall", address="2 College Ave")
    ceremony = create_ceremony(
        venue["id"], rain_venue_id=(rain_venue["id"] if rain_venue else None),
        ticket_ratio=ticket_ratio, guest_ticket_base_cap=guest_ticket_base_cap,
        honor_bonus_tickets=honor_bonus_tickets)
    if open_audit or lock_audit:
        ceremony = open_ceremony_audit(ceremony["id"])
    if lock_audit:
        ceremony = lock_ceremony_audit(ceremony["id"])
    return {"ceremony": ceremony, "venue": venue, "rain_venue": rain_venue}


# --- Tier 2: graduates, audits, allocations ---

def import_graduate(ceremony_id, full_name="Test Graduate", email=None, tier=None,
                    institutional_gpa_credits=45, institutional_quality_points=160.0,
                    transfer_gpa_credits=0, transfer_quality_points=0,
                    credits_completed=120, credits_required=120,
                    outstanding_hold_count=0) -> dict:
    """Import a graduate record (auto-creates the PENDING ticket allocation)."""
    if tier is not None:
        ledger = GPA_LEDGERS[tier]
        institutional_gpa_credits = ledger["institutional_gpa_credits"]
        institutional_quality_points = ledger["institutional_quality_points"]
    payload = create_graduate_payload(
        ceremony_id, full_name=full_name,
        email=email or f"{full_name.replace(' ', '.').lower()}@x.edu",
        institutional_gpa_credits=institutional_gpa_credits,
        institutional_quality_points=institutional_quality_points,
        transfer_gpa_credits=transfer_gpa_credits,
        transfer_quality_points=transfer_quality_points,
        credits_completed=credits_completed, credits_required=credits_required,
        outstanding_hold_count=outstanding_hold_count)
    res = api_client.create_graduate(payload, REGISTRAR)
    return get_success_data(res)


def audit_graduate(graduate_id, notes=None) -> dict:
    """Run the eligibility audit as RegistrarOfficer (requires AUDIT_OPEN)."""
    payload = {}
    if notes is not None:
        payload["notes"] = notes
    res = api_client.create_audit(graduate_id, payload, REGISTRAR)
    return get_success_data(res)


def import_and_audit(ceremony_id, **kwargs):
    """Import a graduate and run the audit. Returns (graduate, audit)."""
    graduate = import_graduate(ceremony_id, **kwargs)
    audit = audit_graduate(graduate["id"])
    graduate = get_success_data(api_client.get_graduate(graduate["id"], REGISTRAR))
    return graduate, audit


def get_graduate_allocation(graduate_id) -> dict:
    """Fetch the graduate's single ticket allocation via the sub-resource list."""
    res = api_client.list_graduate_ticket_allocations(graduate_id, REGISTRAR)
    data = get_success_data(res)
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly one allocation for graduate {graduate_id}, got {data!r}")
    return data[0]


def request_tickets(graduate_id, requested_count) -> dict:
    """Post a guest-ticket request as the graduate (OCC-guarded)."""
    allocation = get_graduate_allocation(graduate_id)
    res = api_client.request_tickets(
        allocation["id"],
        create_ticket_request_payload(requested_count, allocation["version"]),
        make_graduate_headers(graduate_id))
    return get_success_data(res)


def run_waterfall(ceremony_id) -> dict:
    return get_success_data(api_client.run_ticket_waterfall(ceremony_id, CHAIR))


def setup_ceremony_with_graduates(grad_specs, posture="AUDIT_LOCKED", **ceremony_kwargs):
    """Ceremony + one imported, audited graduate per spec; optional ticket requests.

    Each spec is a dict accepted by import_graduate plus optional keys:
      request: int — post a ticket request for this many tickets while AUDIT_OPEN
    Returns dict: ceremony, venue, rain_venue, graduates (list), allocations (list).
    """
    ctx = setup_ceremony(open_audit=True, **ceremony_kwargs)
    ceremony = ctx["ceremony"]
    graduates, allocations = [], []
    for spec in grad_specs:
        spec = dict(spec)
        request = spec.pop("request", None)
        graduate, _audit = import_and_audit(ceremony["id"], **spec)
        if request is not None:
            request_tickets(graduate["id"], request)
        graduates.append(graduate)
        allocations.append(get_graduate_allocation(graduate["id"]))
    if posture == "AUDIT_LOCKED":
        ceremony = lock_ceremony_audit(ceremony["id"])
    ctx["ceremony"] = ceremony
    ctx["graduates"] = graduates
    ctx["allocations"] = allocations
    return ctx


# --- Tier 3: reader cards, seating, rehearsal ---

def create_reader_card(graduate_id, phonetic_spelling="TEH-st GRAD-yoo-it") -> dict:
    res = api_client.create_reader_card(
        graduate_id, create_reader_card_payload(phonetic_spelling),
        make_graduate_headers(graduate_id))
    return get_success_data(res)


def get_graduate_reader_card(graduate_id):
    res = api_client.list_graduate_reader_cards(graduate_id, REGISTRAR)
    data = get_success_data(res)
    assert isinstance(data, list), f"Setup failed: reader card list not an array: {data!r}"
    return data[0] if data else None


def assign_seat(ceremony_id, graduate_id, section="A", row_label="1", seat_number=1,
                accessible=None) -> dict:
    payload = create_seat_assignment_payload(
        ceremony_id, graduate_id, section=section, row_label=row_label,
        seat_number=seat_number)
    if accessible is not None:
        payload["accessible"] = accessible
    res = api_client.create_seat_assignment(payload, COORDINATOR)
    return get_success_data(res)


def create_rehearsal_session(ceremony_id, venue_id, start_utc="2026-05-25T10:00:00Z",
                             end_utc="2026-05-25T11:00:00Z", capacity=30) -> dict:
    res = api_client.create_rehearsal_session(
        ceremony_id,
        create_rehearsal_session_payload(venue_id, start_utc=start_utc,
                                         end_utc=end_utc, capacity=capacity),
        COORDINATOR)
    return get_success_data(res)


def register_for_session(session_id, graduate_id) -> dict:
    res = api_client.register_for_session(session_id, make_graduate_headers(graduate_id))
    return get_success_data(res)


def complete_session(session_id, coordinator_id=COORD_A) -> dict:
    res = api_client.complete_session(session_id, make_coordinator_headers(coordinator_id))
    return get_success_data(res)


def setup_graduate_with_strikes(strikes=2, venue_capacity=50, venue_accessible=4):
    """Eligible graduate registered for `strikes` sessions, all completed by
    COORD_A so each attendance stands ABSENT. Returns dict with ceremony,
    venue, graduate, sessions, attendances."""
    ctx = setup_ceremony(open_audit=True, venue_capacity=venue_capacity,
                         venue_accessible=venue_accessible)
    ceremony, venue = ctx["ceremony"], ctx["venue"]
    graduate, _ = import_and_audit(ceremony["id"], full_name="Strike Stan")
    sessions, attendances = [], []
    for i in range(strikes):
        session = create_rehearsal_session(
            ceremony["id"], venue["id"],
            start_utc=f"2026-05-2{5 + i}T10:00:00Z",
            end_utc=f"2026-05-2{5 + i}T11:00:00Z")
        sessions.append(session)
        attendances.append(register_for_session(session["id"], graduate["id"]))
    for session in sessions:
        complete_session(session["id"], coordinator_id=COORD_A)
    ctx["graduate"] = graduate
    ctx["sessions"] = sessions
    ctx["attendances"] = attendances
    return ctx


# --- Tier 4: regalia ---

def create_regalia_order(graduate_id, items=None) -> dict:
    res = api_client.create_regalia_order(
        graduate_id, create_regalia_order_payload(items=items),
        make_graduate_headers(graduate_id))
    return get_success_data(res)


def pay_regalia_order(order, amount_cents=None) -> dict:
    res = api_client.pay_regalia_order(
        order["id"], {"amount_cents": amount_cents if amount_cents is not None else order["total_cents"]},
        make_graduate_headers(order["graduate_id"]))
    return get_success_data(res)


# --- Tier 5: print batches, diplomas, full lifecycle ---

def create_open_batch(ceremony_id, creator=REG_A) -> dict:
    res = api_client.create_print_batch(
        ceremony_id, {}, make_registrar_headers(creator))
    return get_success_data(res)


def queue_diploma(batch_id, graduate_id, printed_name=None) -> dict:
    payload = create_queue_diploma_payload(graduate_id)
    if printed_name is not None:
        payload["printed_name"] = printed_name
    res = api_client.queue_diploma(batch_id, payload, REGISTRAR)
    return get_success_data(res)


def release_batch(batch_id, releaser=REG_B) -> dict:
    res = api_client.release_batch(batch_id, make_registrar_headers(releaser))
    return get_success_data(res)


def mark_batch_printed(batch_id) -> dict:
    return get_success_data(api_client.mark_batch_printed(batch_id, REGISTRAR))


def setup_diploma_queued(grad_tier="SUMMA", full_name="Dee Ploma",
                         phonetic="DEE PLOH-muh", printed_name=None):
    """Ceremony AUDIT_LOCKED; one eligible graduate; OPEN batch (REG_A) with the
    graduate's diploma QUEUED. Returns dict(ctx + batch + diploma)."""
    ctx = setup_ceremony(open_audit=True)
    ceremony = ctx["ceremony"]
    graduate, _ = import_and_audit(ceremony["id"], full_name=full_name, tier=grad_tier)
    ceremony = lock_ceremony_audit(ceremony["id"])
    batch = create_open_batch(ceremony["id"])
    diploma = queue_diploma(batch["id"], graduate["id"], printed_name=printed_name)
    ctx.update({"ceremony": ceremony, "graduate": graduate,
                "batch": batch, "diploma": diploma, "phonetic": phonetic})
    return ctx


def setup_diploma_printed(grad_tier="SUMMA", full_name="Dee Ploma",
                          phonetic="DEE PLOH-muh", printed_name=None):
    """Ceremony READY; diploma PRINTED (batch released by REG_B, marked printed).

    Reader card is submitted before mark-ready (PRD §3.1 readiness gate).
    """
    ctx = setup_diploma_queued(grad_tier=grad_tier, full_name=full_name,
                               phonetic=phonetic, printed_name=printed_name)
    ceremony, batch, diploma = ctx["ceremony"], ctx["batch"], ctx["diploma"]
    release_batch(batch["id"])
    mark_batch_printed(batch["id"])
    card = create_reader_card(ctx["graduate"]["id"], ctx["phonetic"])
    ceremony = get_success_data(api_client.mark_ready(ceremony["id"], CHAIR))
    diploma = get_success_data(api_client.get_diploma(diploma["id"], REGISTRAR))
    ctx.update({"ceremony": ceremony, "diploma": diploma, "reader_card": card})
    return ctx


def setup_diploma_issued(grad_tier="SUMMA", full_name="Dee Ploma",
                         phonetic="DEE PLOH-muh", printed_name=None):
    """Ceremony COMMENCED; diploma ISSUED (full print + readiness lifecycle)."""
    ctx = setup_diploma_printed(grad_tier=grad_tier, full_name=full_name,
                                phonetic=phonetic, printed_name=printed_name)
    ceremony = get_success_data(api_client.commence_ceremony(ctx["ceremony"]["id"], CHAIR))
    diploma = get_success_data(api_client.issue_diploma(ctx["diploma"]["id"], CHAIR))
    ctx.update({"ceremony": ceremony, "diploma": diploma})
    return ctx


def get_ceremony(ceremony_id) -> dict:
    return get_success_data(api_client.get_ceremony(ceremony_id, CHAIR))


def get_graduate(graduate_id) -> dict:
    return get_success_data(api_client.get_graduate(graduate_id, REGISTRAR))


def get_print_batch(batch_id) -> dict:
    return get_success_data(api_client.get_print_batch(batch_id, REGISTRAR))


def get_diploma(diploma_id) -> dict:
    return get_success_data(api_client.get_diploma(diploma_id, REGISTRAR))


def list_ceremony_seats(ceremony_id, status=None):
    params = {"status": status} if status else None
    res = api_client.list_ceremony_seat_assignments(ceremony_id, COORDINATOR, params=params)
    return get_success_data(res)


def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, CHAIR))
