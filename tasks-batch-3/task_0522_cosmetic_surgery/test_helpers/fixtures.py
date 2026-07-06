"""Composite setup helpers.

Each test starts against an empty database (the harness restarts the server before
every test). These builders assemble multi-step preconditions using only PRD-declared
endpoints. Every step uses get_success_data (lenient) so a setup break surfaces as a
clear "Setup failed" rather than an obscure assertion mismatch.

Canonical fixture literals (from executed formulas):
  ProcA (RHINO01): surgical 500000 / facility 200000 / anesthesia 150000  -> bundle 850000
  ProcB (LIPO01):  surgical 300000 / facility 150000 / anesthesia 100000  -> bundle 550000
  Quote A+B (2 lines): subtotal 1400000, discount 5%, total 1330000, required_deposit 266000
  Quote A only (1 line): subtotal 850000, discount 0%, total 850000, required_deposit 170000
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_surgeon_headers
from .factories import (
    create_procedure_payload, create_patient_payload, create_consultation_payload,
    create_line_item_payload, create_consent_payload, create_deposit_payload,
    create_clearance_payload, create_surgery_booking_payload, create_financing_payload,
    create_complication_case_payload,
)

ADMIN = TEST_USERS["practice_admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]
SURGEON = TEST_USERS["surgeon_headers"]
BILLING = TEST_USERS["billing_headers"]

CLOCK_DEFAULT = "2026-05-01T00:00:00Z"
SURGERY_START = "2026-08-01T00:00:00Z"
SURGERY_END = "2026-08-01T03:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: primitive builders
# ---------------------------------------------------------------------------
def create_procedure(**overrides):
    resp = api_client.create_procedure(create_procedure_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_patient(**overrides):
    resp = api_client.create_patient(create_patient_payload(**overrides), FRONT)
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


def issue_clearance(patient_id, tier_provided="STANDARD"):
    resp = api_client.issue_clearance(
        patient_id, create_clearance_payload(tier_provided=tier_provided), SURGEON)
    return get_success_data(resp)


def create_completed_consultation(patient_id, surgeon_user_id="surgeon-1",
                                  chief_complaint="nose"):
    """Consultation opened by FrontDesk then completed by its owning surgeon."""
    cons = get_success_data(api_client.create_consultation(
        create_consultation_payload(patient_id, surgeon_user_id, chief_complaint), FRONT))
    api_client.complete_consultation(cons["id"], make_surgeon_headers(surgeon_user_id))
    return get_success_data(api_client.get_consultation(cons["id"], FRONT))


# ---------------------------------------------------------------------------
# Tier 1/2: quote assembly
# ---------------------------------------------------------------------------
def create_draft_quote(procedure_ids, surgeon_user_id="surgeon-1"):
    """Empty-DB -> a DRAFT quote with one line per procedure_id.
    Returns (quote, consultation, patient, line_items)."""
    patient = create_patient()
    cons = create_completed_consultation(patient["id"], surgeon_user_id)
    quote = get_success_data(api_client.create_quote_package(
        {"consultation_id": cons["id"]}, FRONT))
    line_items = []
    for pid in procedure_ids:
        li = get_success_data(api_client.add_line_item(
            quote["id"], create_line_item_payload(pid), FRONT))
        line_items.append(li)
    quote = get_success_data(api_client.get_quote_package(quote["id"], FRONT))
    return quote, cons, patient, line_items


def create_presented_quote(procedure_ids, deposit_cents=None, sign_consent=True,
                           surgeon_user_id="surgeon-1"):
    """DRAFT -> (optional deposit) -> (optional signed consent) -> PRESENTED.
    Returns (quote, consultation, patient, line_items)."""
    quote, cons, patient, line_items = create_draft_quote(procedure_ids, surgeon_user_id)
    if sign_consent:
        api_client.create_consent(quote["id"], create_consent_payload(), FRONT)
    if deposit_cents is not None:
        api_client.record_deposit(quote["id"], create_deposit_payload(deposit_cents), BILLING)
    api_client.present_quote(quote["id"], FRONT)
    quote = get_success_data(api_client.get_quote_package(quote["id"], FRONT))
    return quote, cons, patient, line_items


def create_accepted_quote(procedure_ids, deposit_cents, sign_consent=True,
                          clearance=True, surgeon_user_id="surgeon-1"):
    """Full path to an ACCEPTED quote with consent + deposit and (optionally) a
    cleared patient. Returns (quote, consultation, patient, line_items)."""
    patient = create_patient()
    if clearance:
        issue_clearance(patient["id"], "STANDARD")
    cons = create_completed_consultation(patient["id"], surgeon_user_id)
    quote = get_success_data(api_client.create_quote_package(
        {"consultation_id": cons["id"]}, FRONT))
    line_items = []
    for pid in procedure_ids:
        li = get_success_data(api_client.add_line_item(
            quote["id"], create_line_item_payload(pid), FRONT))
        line_items.append(li)
    if sign_consent:
        api_client.create_consent(quote["id"], create_consent_payload(), FRONT)
    api_client.record_deposit(quote["id"], create_deposit_payload(deposit_cents), BILLING)
    api_client.present_quote(quote["id"], FRONT)
    api_client.accept_quote(quote["id"], FRONT)
    quote = get_success_data(api_client.get_quote_package(quote["id"], FRONT))
    return quote, cons, patient, line_items


# ---------------------------------------------------------------------------
# Tier 3: booking
# ---------------------------------------------------------------------------
def create_scheduled_booking(procedure_ids, deposit_cents,
                             scheduled_start=SURGERY_START, scheduled_end=SURGERY_END,
                             surgeon_user_id="surgeon-1", or_room="OR1",
                             financing=None):
    """Empty-DB -> ACCEPTED quote (cleared patient) -> (optional APPROVED financing)
    -> a SCHEDULED SurgeryBooking. Returns (booking, quote, patient, line_items).

    `financing` may be dict {lender, requested_amount_cents} to submit + approve a
    financing app on the accepted quote before booking.
    """
    quote, cons, patient, line_items = create_accepted_quote(
        procedure_ids, deposit_cents, surgeon_user_id=surgeon_user_id)
    fin = None
    if financing is not None:
        fin = get_success_data(api_client.submit_financing(
            create_financing_payload(quote["id"], **financing), BILLING))
        api_client.approve_financing(fin["id"], BILLING)
    quote = get_success_data(api_client.get_quote_package(quote["id"], FRONT))
    booking = get_success_data(api_client.create_surgery_booking(
        create_surgery_booking_payload(
            quote["id"], quote["version"],
            surgeon_user_id=surgeon_user_id, or_room=or_room,
            scheduled_start=scheduled_start, scheduled_end=scheduled_end),
        FRONT))
    quote = get_success_data(api_client.get_quote_package(quote["id"], FRONT))
    return booking, quote, patient, line_items, fin


def create_completed_booking(procedure_ids, deposit_cents,
                             surgeon_user_id="surgeon-1"):
    """SCHEDULED booking -> advance clock past start -> COMPLETED booking.
    Returns (booking, quote, patient, line_items)."""
    booking, quote, patient, line_items, _fin = create_scheduled_booking(
        procedure_ids, deposit_cents, surgeon_user_id=surgeon_user_id)
    set_clock("2026-08-01T04:00:00Z")
    api_client.complete_surgery_booking(booking["id"], make_surgeon_headers(surgeon_user_id))
    booking = get_success_data(api_client.get_surgery_booking(booking["id"], FRONT))
    return booking, quote, patient, line_items


def open_complication_case(booking_id, line_item_id, attribution="SURGICAL_ORIGIN"):
    resp = api_client.open_complication_case(
        create_complication_case_payload(booking_id, line_item_id, attribution), SURGEON)
    return get_success_data(resp)
