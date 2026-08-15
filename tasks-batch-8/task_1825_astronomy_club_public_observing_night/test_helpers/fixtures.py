"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Member calls are entity-backed by Member, so every
ownership-gated call uses make_member_headers(member["id"]) — never the
shared constant. Opaque roles (ClubOfficer, EventCoordinator, EquipmentChair)
use the shared constants throughout.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_dark_sky_report_payload,
    create_dues_invoice_payload,
    create_dues_payment_payload,
    create_group_visit_booking_payload,
    create_loan_reservation_payload,
    create_maintenance_ticket_payload,
    create_member_payload,
    create_membership_tier_payload,
    create_observing_event_payload,
    create_operator_assignment_payload,
    create_sky_quality_reading_payload,
    create_telescope_payload,
    create_training_certification_payload,
)
from .test_users import (
    TEST_USERS,
    make_member_headers,
)

OFFICER = TEST_USERS["club_officer_headers"]
COORDINATOR = TEST_USERS["event_coordinator_headers"]
CHAIR = TEST_USERS["equipment_chair_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_tier(code="INDIVIDUAL", annual_dues_cents=None,
                observatory_access_level=2, loan_privilege=True,
                max_concurrent_loans=2):
    """Create a membership tier. Returns the tier."""
    if annual_dues_cents is None:
        annual_dues_cents = TEST_DEFAULTS["TIER_DUES_INDIVIDUAL"]
    payload = create_membership_tier_payload(
        code=code, annual_dues_cents=annual_dues_cents,
        observatory_access_level=observatory_access_level,
        loan_privilege=loan_privilege,
        max_concurrent_loans=max_concurrent_loans)
    return get_success_data(api_client.create_membership_tier(payload, OFFICER))


def create_member(tier_id, full_name="Test Member", email=None):
    """Register a member (born ACTIVE, dues_paid_through == joined_at)."""
    payload = create_member_payload(tier_id, full_name=full_name)
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_member(payload, OFFICER))


def create_telescope(name="Test Telescope", equipment_class="REFRACTOR"):
    """Register a telescope (born AVAILABLE, condition_score 100)."""
    payload = create_telescope_payload(name=name, equipment_class=equipment_class)
    return get_success_data(api_client.create_telescope(payload, CHAIR))


def create_certification(member_id, equipment_class="REFRACTOR",
                         expires_at="2027-08-01T00:00:00Z"):
    """Issue an ACTIVE certification to a member."""
    payload = create_training_certification_payload(
        member_id, equipment_class, expires_at)
    return get_success_data(
        api_client.create_training_certification(payload, CHAIR))


def create_event(title="Test Event", event_kind="PUBLIC_NIGHT",
                 window_start="2026-08-10T01:00:00Z",
                 window_end="2026-08-10T05:00:00Z",
                 moon_illumination_pct=20, min_operators=1):
    """Draft an observing event (born DRAFT, weather_cancellation_pct 0)."""
    payload = create_observing_event_payload(
        title=title, event_kind=event_kind, window_start=window_start,
        window_end=window_end, moon_illumination_pct=moon_illumination_pct,
        min_operators=min_operators)
    return get_success_data(api_client.create_observing_event(payload, COORDINATOR))


def set_clock(to_iso8601):
    """Advance the server logical clock (ClubOfficer-only)."""
    return get_success_data(api_client.set_clock(to_iso8601, OFFICER))


# ---------------------------------------------------------------------------
# Tier 2: dues ledger helpers
# ---------------------------------------------------------------------------

def issue_invoice(member_id, period_start, period_end):
    """Issue a dues invoice; amount computed by the proration rule."""
    payload = create_dues_invoice_payload(member_id, period_start, period_end)
    return get_success_data(api_client.create_dues_invoice(payload, OFFICER))


def pay_invoice(invoice_id, member_id, amount_cents):
    """Post a dues payment as the paying member (ownership-gated)."""
    payload = create_dues_payment_payload(invoice_id, member_id, amount_cents)
    return get_success_data(api_client.create_dues_payment(
        payload, make_member_headers(member_id)))


def create_member_with_paid_dues(tier=None, period_start="2026-08-01T00:00:00Z",
                                 period_end="2027-08-01T00:00:00Z",
                                 full_name="Paid Member", pay_amount=None):
    """Create a member whose annual invoice is issued and settled in full.

    Returns (member, tier, invoice, payment). The member's
    dues_paid_through lands at period_end.
    """
    if tier is None:
        tier = create_tier()
    member = create_member(tier["id"], full_name=full_name)
    invoice = issue_invoice(member["id"], period_start, period_end)
    amount = invoice["amount_cents"] if pay_amount is None else pay_amount
    payment = pay_invoice(invoice["id"], member["id"], amount)
    member = get_success_data(api_client.get_member(member["id"], OFFICER))
    return member, tier, invoice, payment


# ---------------------------------------------------------------------------
# Tier 3: loan program helpers
# ---------------------------------------------------------------------------

def create_reserved_loan(member, telescope, window_start, window_end):
    """Create a loan reservation as the borrowing member (ownership-gated)."""
    payload = create_loan_reservation_payload(
        member["id"], telescope["id"], window_start, window_end)
    return get_success_data(api_client.create_loan_reservation(
        payload, make_member_headers(member["id"])))


def setup_member_with_cert_and_scope(equipment_class="REFRACTOR",
                                     cert_expires="2027-08-01T00:00:00Z",
                                     member_name="Loan Member",
                                     tier_kwargs=None):
    """Member in good standing (annual dues paid) + ACTIVE certification +
    one telescope of the certified class. Returns (member, telescope, cert).
    """
    tier_kwargs = tier_kwargs or {}
    member, tier, _inv, _pay = create_member_with_paid_dues(
        full_name=member_name,
    ) if not tier_kwargs else create_member_with_paid_dues(
        tier=create_tier(**tier_kwargs), full_name=member_name)
    telescope = create_telescope(name=f"{member_name}'s scope",
                                 equipment_class=equipment_class)
    cert = create_certification(member["id"], equipment_class, cert_expires)
    return member, telescope, cert


def create_checked_out_loan(member, telescope, window_start, window_end,
                            checkout_clock=None):
    """Create a reservation and check it out. If checkout_clock is given,
    the logical clock is advanced to that instant first; otherwise the clock
    is set to the window midpoint-hour on the start date."""
    loan = create_reserved_loan(member, telescope, window_start, window_end)
    if checkout_clock is not None:
        set_clock(checkout_clock)
    get_success_data(api_client.checkout_loan(loan["id"], CHAIR))
    return get_success_data(api_client.get_loan_reservation(loan["id"], CHAIR))


# ---------------------------------------------------------------------------
# Tier 4: event pipeline helpers
# ---------------------------------------------------------------------------

def create_scheduled_event(**kwargs):
    """Create + schedule an event. Returns the SCHEDULED event."""
    event = create_event(**kwargs)
    get_success_data(api_client.schedule_event(event["id"], COORDINATOR))
    return get_success_data(api_client.get_observing_event(event["id"], COORDINATOR))


def invite_and_accept_operator(event_id, member, telescope):
    """Invite a member to operate a telescope at an event and have the
    member accept. Returns the CONFIRMED assignment."""
    payload = create_operator_assignment_payload(
        event_id, member["id"], telescope["id"])
    assignment = get_success_data(
        api_client.create_operator_assignment(payload, COORDINATOR))
    get_success_data(api_client.accept_assignment(
        assignment["id"], make_member_headers(member["id"])))
    return get_success_data(
        api_client.get_operator_assignment(assignment["id"], COORDINATOR))


def create_confirmed_event(operator_member=None, operator_scope=None,
                           equipment_class="DOBSONIAN",
                           window_start="2026-08-10T01:00:00Z",
                           window_end="2026-08-10T05:00:00Z",
                           min_operators=1, event_kind="PUBLIC_NIGHT",
                           moon_illumination_pct=20, title="Confirmed PN"):
    """Build a CONFIRMED event end-to-end: schedule, staff one certified
    operator (created if not given), accept, then confirm with the current
    version. Returns (event, assignment, operator_member, telescope)."""
    event = create_scheduled_event(
        title=title, event_kind=event_kind, window_start=window_start,
        window_end=window_end, moon_illumination_pct=moon_illumination_pct,
        min_operators=min_operators)
    if operator_member is None or operator_scope is None:
        operator_member, operator_scope, _cert = setup_member_with_cert_and_scope(
            equipment_class=equipment_class, member_name="Event Op")
    assignment = invite_and_accept_operator(
        event["id"], operator_member, operator_scope)
    current = get_success_data(
        api_client.get_observing_event(event["id"], COORDINATOR))
    confirmed = get_success_data(api_client.confirm_event(
        event["id"], current["version"], COORDINATOR))
    return confirmed, assignment, operator_member, operator_scope


def create_completed_event(window_start="2026-08-05T01:00:00Z",
                           window_end="2026-08-05T05:00:00Z",
                           after_clock="2026-08-05T06:00:00Z",
                           **event_kwargs):
    """Full lifecycle through COMPLETED. Returns (event, assignment, op, scope)."""
    confirmed, assignment, op, scope = create_confirmed_event(
        window_start=window_start, window_end=window_end, **event_kwargs)
    set_clock(after_clock)
    completed = get_success_data(api_client.complete_event(confirmed["id"], COORDINATOR))
    return completed, assignment, op, scope


# ---------------------------------------------------------------------------
# Tier 5: group bookings / dark-sky helpers
# ---------------------------------------------------------------------------

def create_group_booking(event_id, contact_member, party_size=5,
                         group_name="Test Group"):
    """Book a group visit as the contact member (ownership-gated)."""
    payload = create_group_visit_booking_payload(
        event_id, contact_member["id"], party_size=party_size,
        group_name=group_name)
    return get_success_data(api_client.create_group_visit_booking(
        payload, make_member_headers(contact_member["id"])))


def record_reading(member, event_id, sqm_value):
    """Record a sky-quality reading as the taking member (ownership-gated)."""
    payload = create_sky_quality_reading_payload(member["id"], event_id, sqm_value)
    return get_success_data(api_client.create_sky_quality_reading(
        payload, make_member_headers(member["id"])))


def open_dark_sky_report(period_start, period_end):
    """Open a dark-sky report over a half-open period."""
    payload = create_dark_sky_report_payload(period_start, period_end)
    return get_success_data(api_client.create_dark_sky_report(payload, OFFICER))


# ---------------------------------------------------------------------------
# Tier 6: maintenance workflow helpers
# ---------------------------------------------------------------------------

def open_ticket(telescope_id, kind="REPAIR", severity="MEDIUM",
                condition_delta=0):
    """Open a maintenance ticket (telescope AVAILABLE -> MAINTENANCE)."""
    payload = create_maintenance_ticket_payload(
        telescope_id, kind=kind, severity=severity,
        condition_delta=condition_delta)
    return get_success_data(api_client.create_maintenance_ticket(payload, CHAIR))


def push_ticket_to_verification(ticket_id):
    """OPEN -> IN_PROGRESS -> VERIFICATION. Returns the ticket."""
    get_success_data(api_client.start_maintenance_ticket(ticket_id, CHAIR))
    get_success_data(api_client.submit_ticket_verification(ticket_id, CHAIR))
    return get_success_data(api_client.get_maintenance_ticket(ticket_id, CHAIR))


def close_ticket(ticket_id):
    """Drive a ticket to CLOSED from any working state (assumes it can reach
    VERIFICATION then close). Returns the closed ticket."""
    ticket = get_success_data(api_client.get_maintenance_ticket(ticket_id, CHAIR))
    if ticket["status"] == "OPEN":
        get_success_data(api_client.start_maintenance_ticket(ticket_id, CHAIR))
    ticket = get_success_data(api_client.get_maintenance_ticket(ticket_id, CHAIR))
    if ticket["status"] == "IN_PROGRESS":
        get_success_data(api_client.submit_ticket_verification(ticket_id, CHAIR))
    get_success_data(api_client.close_maintenance_ticket(ticket_id, CHAIR))
    return get_success_data(api_client.get_maintenance_ticket(ticket_id, CHAIR))
