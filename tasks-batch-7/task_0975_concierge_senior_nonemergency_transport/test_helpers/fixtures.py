"""Composite setup helpers.

Every helper builds its preconditions from scratch against a fresh database
(the runner restarts the server before each test) using only PRD-declared
endpoints, and uses get_success_data() so setup failures surface as clear
"Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import WAV_CARD
from .factories import (
    create_client_payload,
    create_compliance_doc_payload,
    create_driver_payload,
    create_family_member_payload,
    create_invoice_payload,
    create_payment_payload,
    create_rate_card_payload,
    create_ride_payload,
    create_standing_ride_payload,
)
from .test_users import (
    TEST_USERS,
    make_billing_admin_headers,
    make_client_headers,
    make_compliance_officer_headers,
    make_coordinator_headers,
    make_driver_headers,
    make_family_member_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
BILLING = TEST_USERS["billing_admin_headers"]

REQUIRED_DOC_TYPES = ("BACKGROUND_CHECK", "BONDING", "INSURANCE")


def set_clock(to_iso8601: str):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_client(**overrides):
    resp = api_client.create_client(create_client_payload(**overrides), COORD)
    return get_success_data(resp)


def create_family_member(client_id, **overrides):
    resp = api_client.create_family_member(
        create_family_member_payload(client_id, **overrides), COORD)
    return get_success_data(resp)


def create_driver(**overrides):
    resp = api_client.create_driver(create_driver_payload(**overrides), COORD)
    return get_success_data(resp)


def suspend_client(client_id, version):
    resp = api_client.patch_client(
        client_id, {"status": "SUSPENDED", "expected_client_version": version}, COORD)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: rate cards
# ---------------------------------------------------------------------------

def create_active_rate_card(**overrides):
    card = get_success_data(api_client.create_rate_card(create_rate_card_payload(**overrides), ADMIN))
    resp = api_client.activate_rate_card(card["id"], ADMIN)
    return get_success_data(resp)


def create_active_wav_rate_card(**overrides):
    merged = dict(WAV_CARD)
    merged.update(overrides)
    card = get_success_data(api_client.create_rate_card(merged, ADMIN))
    resp = api_client.activate_rate_card(card["id"], ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: driver compliance + activation
# ---------------------------------------------------------------------------

def create_compliant_driver(
    valid_from="2026-01-01",
    valid_until="2027-01-01",
    activate=True,
    doc_validity=None,
    **driver_overrides,
):
    """Driver with APPROVED BACKGROUND_CHECK/BONDING/INSURANCE, optionally ACTIVE.

    doc_validity: optional dict mapping doc_type -> (valid_from, valid_until)
    to override a single document's window (e.g. a short-lived BONDING).
    Returns (driver, docs_by_type).
    """
    driver = create_driver(**driver_overrides)
    docs = {}
    for doc_type in REQUIRED_DOC_TYPES:
        vf, vu = valid_from, valid_until
        if doc_validity and doc_type in doc_validity:
            vf, vu = doc_validity[doc_type]
        doc = get_success_data(api_client.create_compliance_doc(
            create_compliance_doc_payload(driver["id"], doc_type, valid_from=vf, valid_until=vu),
            COORD))
        doc = get_success_data(api_client.review_compliance_doc(
            doc["id"], {"decision": "APPROVE"}, OFFICER))
        docs[doc_type] = doc
    if activate:
        driver = get_success_data(api_client.driver_status_event(
            driver["id"], {"event_type": "ACTIVATE"}, COORD))
    return driver, docs


def create_client_with_billing_payer(**client_overrides):
    """Client plus a BILLING_PAYER family member. Returns (client, member)."""
    client = create_client(**client_overrides)
    member = create_family_member(client["id"], access_level="BILLING_PAYER")
    return client, member


def seed_credit_via_payment(client_id, amount_cents, payer_member_id=None):
    """Park amount_cents in the client's credit pool (no open invoices)."""
    if payer_member_id is not None:
        headers = make_family_member_headers(payer_member_id)
    else:
        headers = BILLING
    payment = get_success_data(api_client.create_payment(
        create_payment_payload(client_id, amount_cents=amount_cents), headers))
    return payment


# ---------------------------------------------------------------------------
# Tier 3: ride lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_booked_ride(client_id, **overrides):
    """One-off ride booked by the client themselves. Returns ride dict."""
    resp = api_client.create_ride(
        create_ride_payload(client_id, **overrides), make_client_headers(client_id))
    return get_success_data(resp)


def dispatch_and_accept(ride_id, driver_id, coordinator_user_id="coord-1"):
    """Dispatch once and accept the resulting offer as driver_id.
    Returns (ride_after, assignment)."""
    offer = get_success_data(api_client.dispatch_ride(
        ride_id, make_coordinator_headers(coordinator_user_id)))
    assignment = get_success_data(api_client.respond_assignment(
        offer["id"], {"decision": "ACCEPT"}, make_driver_headers(driver_id)))
    ride = get_success_data(api_client.get_ride(ride_id, COORD))
    return ride, assignment


def exec_event(ride_id, driver_id, event_type, at_clock=None, **extra):
    """Advance the logical clock (when given) and append one execution event."""
    if at_clock is not None:
        set_clock(at_clock)
    payload = {"event_type": event_type}
    payload.update(extra)
    return get_success_data(api_client.ride_execution_event(
        ride_id, payload, make_driver_headers(driver_id)))


def execute_ride_happy_path(ride_id, driver_id, pickup_date,
                            actual_distance_miles,
                            arrive_offset_min=5,
                            service_minutes=60,
                            wait_segments=()):
    """Drive an ASSIGNED ride to COMPLETED.

    Timeline (all on pickup_date): EN_ROUTE at pickup-20, ARRIVED at
    pickup-arrive_offset, optional closed wait segments starting at pickup,
    SERVICE_STARTED at the end of the last wait segment (or at pickup),
    COMPLETE at service start + service_minutes.
    wait_segments: iterable of (start_offset_min, end_offset_min) relative to
    the pickup instant.
    """
    pickup_hhmm = pickup_date[11:16]
    ph, pm = int(pickup_hhmm[:2]), int(pickup_hhmm[3:5])

    def at(offset_min):
        total = ph * 60 + pm + offset_min
        return f"{pickup_date[:10]}T{total // 60:02d}:{total % 60:02d}:00Z"

    exec_event(ride_id, driver_id, "EN_ROUTE", at_clock=at(-20))
    exec_event(ride_id, driver_id, "ARRIVED", at_clock=at(-arrive_offset_min))
    service_start = 0
    for start_off, end_off in wait_segments:
        exec_event(ride_id, driver_id, "WAIT_STARTED", at_clock=at(start_off))
        exec_event(ride_id, driver_id, "WAIT_ENDED", at_clock=at(end_off))
        service_start = max(service_start, end_off)
    exec_event(ride_id, driver_id, "SERVICE_STARTED", at_clock=at(service_start))
    return exec_event(ride_id, driver_id, "COMPLETE",
                      at_clock=at(service_start + service_minutes),
                      actual_distance_miles=actual_distance_miles)


def create_completed_ride(client_id, driver_id, pickup_at,
                          estimated_duration_minutes=60, estimated_distance_miles=10,
                          actual_distance_miles=None, service_minutes=60,
                          wait_segments=(), kind="GROCERY", origin_zone="north",
                          coordinator_user_id="coord-1"):
    """Book -> dispatch -> accept -> execute to COMPLETED. Returns ride dict."""
    if actual_distance_miles is None:
        actual_distance_miles = estimated_distance_miles
    ride = create_booked_ride(
        client_id, kind=kind, scheduled_pickup_at=pickup_at,
        estimated_duration_minutes=estimated_duration_minutes,
        estimated_distance_miles=estimated_distance_miles,
        origin_zone=origin_zone)
    dispatch_and_accept(ride["id"], driver_id, coordinator_user_id)
    return execute_ride_happy_path(
        ride["id"], driver_id, pickup_at,
        actual_distance_miles=actual_distance_miles,
        service_minutes=service_minutes, wait_segments=wait_segments)


def no_show_ride(ride_id, driver_id, arrived_clock, no_show_clock):
    """Drive an ASSIGNED ride to NO_SHOW (ARRIVED at arrived_clock)."""
    exec_event(ride_id, driver_id, "EN_ROUTE",
               at_clock=arrived_clock[:11] + _hhmm_offset(arrived_clock, -15))
    exec_event(ride_id, driver_id, "ARRIVED", at_clock=arrived_clock)
    return exec_event(ride_id, driver_id, "NO_SHOW", at_clock=no_show_clock)


def _hhmm_offset(iso_ts, delta_min):
    total = int(iso_ts[11:13]) * 60 + int(iso_ts[14:16]) + delta_min
    return f"{total // 60:02d}:{total % 60:02d}:00Z"


# ---------------------------------------------------------------------------
# Tier 4: billing compositions
# ---------------------------------------------------------------------------

def create_late_cancel_invoice(client_id, cancel_at_clock, ride_pickup_at,
                               period_start, period_end, issue=False):
    """Book a ride, cancel it at cancel_at_clock (caller controls notice),
    generate the invoice for the period. Returns (invoice, ride)."""
    ride = create_booked_ride(client_id, scheduled_pickup_at=ride_pickup_at)
    set_clock(cancel_at_clock)
    get_success_data(api_client.cancel_ride(
        ride["id"], {"cancel_note": "changed mind"}, make_client_headers(client_id)))
    invoice = get_success_data(api_client.generate_invoice(
        create_invoice_payload(client_id, period_start=period_start, period_end=period_end),
        BILLING))
    if issue:
        invoice = get_success_data(api_client.issue_invoice(invoice["id"], BILLING))
    return invoice, ride


def setup_overdue_ar_client(limit_cents=1000):
    """Client over billing hold: a 240-minute-notice cancel (fee 1251) invoiced
    and issued with due_date 2026-05-22; clock left at 2026-05-23 (past due).
    Returns (client, invoice)."""
    create_active_rate_card()
    client = create_client(billing_hold_limit_cents=limit_cents)
    set_clock("2026-05-04T12:00:00Z")
    invoice, _ = create_late_cancel_invoice(
        client["id"], "2026-05-04T12:00:00Z", "2026-05-04T16:00:00Z",
        "2026-05-01", "2026-05-08", issue=True)
    set_clock("2026-05-23T09:00:00Z")
    return client, invoice


def setup_standard_dispatch_env(with_driver=True, clock="2026-06-01T09:00:00Z",
                                **driver_overrides):
    """ACTIVE STANDARD card + client (+ ACTIVE driver) + clock set.
    Returns (client, driver_or_None)."""
    create_active_rate_card()
    client = create_client()
    driver = None
    if with_driver:
        driver, _ = create_compliant_driver(**driver_overrides)
    set_clock(clock)
    return client, driver


def setup_two_driver_env(d2_zone="south", d2_cert="DOOR_THROUGH_DOOR",
                         clock="2026-06-01T09:00:00Z",
                         stagger_created_at=False):
    """ACTIVE STANDARD card + client + two ACTIVE drivers (D1 north, D2).
    When stagger_created_at, D1 is created one logical minute before D2.
    Returns (client, d1, d2)."""
    create_active_rate_card()
    client = create_client()
    if stagger_created_at:
        set_clock("2026-05-20T09:00:00Z")
    d1, _ = create_compliant_driver(full_name="Dan D", home_zone="north")
    if stagger_created_at:
        set_clock("2026-05-20T09:01:00Z")
    d2, _ = create_compliant_driver(full_name="Eli E", home_zone=d2_zone,
                                    assist_certification=d2_cert)
    set_clock(clock)
    return client, d1, d2
