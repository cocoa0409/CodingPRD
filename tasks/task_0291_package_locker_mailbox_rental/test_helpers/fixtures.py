"""Composite setup helpers.

Most interesting claims require the system to be in a specific multi-step state.
These helpers encapsulate those preambles so tests focus on assertions. All
internal calls use get_success_data() (lenient) so a setup misstep surfaces as a
clear "Setup failed" rather than a confusing assertion deep in a test.

The harness re-launches the server before every test, so every helper builds its
preconditions from scratch via PRD endpoints only.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_facility_operator_headers, make_compliance_officer_headers,
    make_customer_headers,
)
from . import factories as F

OP = make_facility_operator_headers()
CO = make_compliance_officer_headers()


# ---------------------------------------------------------------------------
# Tier 0 — primitive creators
# ---------------------------------------------------------------------------
def create_facility(name="Facility", time_zone="UTC", clock=None):
    """Create a facility and optionally advance its clock to `clock`."""
    fac = get_success_data(api_client.create_facility(
        F.create_facility_payload(name=name, time_zone=time_zone), OP))
    if clock is not None:
        fac = get_success_data(api_client.advance_clock(fac["id"], {"to_iso8601": clock}, OP))
    return fac


def advance_clock(facility_id, to_iso8601):
    return get_success_data(api_client.advance_clock(facility_id, {"to_iso8601": to_iso8601}, OP))


def create_locker(facility_id, label="L1", size_tier="MEDIUM"):
    return get_success_data(api_client.create_locker_unit(
        F.create_locker_unit_payload(facility_id, label=label, size_tier=size_tier), OP))


def create_mailbox(facility_id, box_number="B1", size_tier="MEDIUM", monthly_fee_cents=3000):
    return get_success_data(api_client.create_mailbox_unit(
        F.create_mailbox_unit_payload(facility_id, box_number=box_number,
                                      size_tier=size_tier, monthly_fee_cents=monthly_fee_cents), OP))


def create_customer(facility_id, full_name="Cust", email="c@x.com", phone="111"):
    return get_success_data(api_client.create_customer(
        F.create_customer_payload(facility_id, full_name=full_name, email=email, phone=phone), OP))


def create_form(facility_id, customer_id, primary_id_type="PASSPORT", address_proof_type="LEASE"):
    return get_success_data(api_client.create_form_1583(
        F.create_form_1583_payload(facility_id, customer_id,
                                   primary_id_type=primary_id_type,
                                   address_proof_type=address_proof_type), OP))


def add_recipient(form_id, recipient_name="Cust", relationship="SELF"):
    return get_success_data(api_client.add_recipient(
        form_id, F.create_recipient_payload(recipient_name=recipient_name, relationship=relationship), OP))


def create_verified_form(facility_id, customer_id, primary_id_type="PASSPORT",
                         address_proof_type="LEASE", recipient_name="Cust"):
    """Create a Form 1583, add a recipient, submit, and verify -> VERIFIED."""
    form = create_form(facility_id, customer_id, primary_id_type, address_proof_type)
    add_recipient(form["id"], recipient_name=recipient_name)
    get_success_data(api_client.submit_form_1583(form["id"], OP))
    form = get_success_data(api_client.verify_form_1583(form["id"], CO))
    return form


# ---------------------------------------------------------------------------
# Tier 1/2 — agreement setup helpers
# ---------------------------------------------------------------------------
def create_pending_agreement(facility_id, customer_id, mailbox_id, form_id,
                             term_months=1, autopay_enabled=False):
    return get_success_data(api_client.create_rental_agreement(
        F.create_rental_agreement_payload(facility_id, customer_id, mailbox_id, form_id,
                                          term_months=term_months,
                                          autopay_enabled=autopay_enabled), OP))


def setup_active_agreement(clock="2026-06-01T00:00:00.000Z", monthly_fee_cents=3000,
                           term_months=1, autopay_enabled=False, mailbox_size="MEDIUM",
                           with_locker=True, locker_size="MEDIUM", name="Facility"):
    """Active rental from scratch.

    Returns a dict with keys: facility, mailbox, customer, form, agreement,
    locker (or None when with_locker=False). The agreement is ACTIVE, its
    mailbox RENTED, an OPEN invoice exists, and the first RENTAL charge is posted.
    """
    fac = create_facility(name=name, clock=clock)
    box = create_mailbox(fac["id"], size_tier=mailbox_size, monthly_fee_cents=monthly_fee_cents)
    locker = create_locker(fac["id"], size_tier=locker_size) if with_locker else None
    cust = create_customer(fac["id"])
    form = create_verified_form(fac["id"], cust["id"])
    agr = create_pending_agreement(fac["id"], cust["id"], box["id"], form["id"],
                                   term_months=term_months, autopay_enabled=autopay_enabled)
    agr = get_success_data(api_client.activate_rental_agreement(agr["id"], OP))
    return {
        "facility": fac, "mailbox": box, "locker": locker,
        "customer": cust, "form": form, "agreement": agr,
    }


def get_open_invoice(rental_agreement_id):
    """Return the single OPEN invoice for an agreement."""
    data, _ = _list_invoices(rental_agreement_id)
    assert data, f"no invoice found for agreement {rental_agreement_id}"
    return data[0]


def _list_invoices(rental_agreement_id):
    resp = api_client.list_invoices(OP, params={"rental_agreement_id": rental_agreement_id})
    body = resp.json()
    return body["data"], body.get("meta", {})


# ---------------------------------------------------------------------------
# Tier 3 — package lifecycle shortcuts
# ---------------------------------------------------------------------------
def receive_package(facility_id, agreement_id, carrier="UPS", size_tier="MEDIUM",
                    longest_dim_cm=40, weight_g=3000):
    return get_success_data(api_client.create_package(
        F.create_package_payload(facility_id, agreement_id, carrier=carrier,
                                 size_tier=size_tier, longest_dim_cm=longest_dim_cm,
                                 weight_g=weight_g), OP))


def receive_and_notify_package(facility_id, agreement_id, **pkg_overrides):
    """Receive a package and move it RECEIVED -> NOTIFIED. Returns the package."""
    pkg = receive_package(facility_id, agreement_id, **pkg_overrides)
    pkg = get_success_data(api_client.notify_package(pkg["id"], OP))
    return pkg


def setup_notified_package(clock="2026-06-01T00:00:00.000Z", monthly_fee_cents=3000,
                           term_months=1, autopay_enabled=False, locker_size="MEDIUM",
                           pkg_size="MEDIUM", longest_dim_cm=40, weight_g=3000, name="Facility"):
    """Active rental + one NOTIFIED package.

    Returns the setup dict from setup_active_agreement plus 'package'.
    """
    s = setup_active_agreement(clock=clock, monthly_fee_cents=monthly_fee_cents,
                               term_months=term_months, autopay_enabled=autopay_enabled,
                               with_locker=True, locker_size=locker_size, name=name)
    pkg = receive_and_notify_package(s["facility"]["id"], s["agreement"]["id"],
                                     size_tier=pkg_size, longest_dim_cm=longest_dim_cm,
                                     weight_g=weight_g)
    s["package"] = pkg
    return s


def current_package_version(package_id):
    pkg = get_success_data(api_client.get_package(package_id, OP))
    return pkg["version"]


# ---------------------------------------------------------------------------
# Tier 2 — mail + forwarding setup helpers
# ---------------------------------------------------------------------------
def create_mail_item(facility_id, agreement_id, mail_class="FIRST_CLASS"):
    return get_success_data(api_client.create_mail_item(
        F.create_mail_item_payload(facility_id, agreement_id, mail_class=mail_class), OP))


def create_forwarding_request(mail_item_id, kind="SCAN", destination_address=None):
    overrides = {"kind": kind}
    if destination_address is not None:
        overrides["destination_address"] = destination_address
    return get_success_data(api_client.create_forwarding_request(
        F.create_forwarding_request_payload(mail_item_id, **overrides), OP))


def setup_agreement_with_forwarding(kind="SCAN", destination_address=None, mailbox_size="MEDIUM",
                                    monthly_fee_cents=3000, term_months=1, name="Facility"):
    """Active rental + one STORED mail item + one REQUESTED forwarding request.

    Returns the setup dict plus 'mail_item' and 'forwarding_request'.
    """
    s = setup_active_agreement(monthly_fee_cents=monthly_fee_cents, term_months=term_months,
                               mailbox_size=mailbox_size, with_locker=False, name=name)
    mi = create_mail_item(s["facility"]["id"], s["agreement"]["id"])
    fr = create_forwarding_request(mi["id"], kind=kind, destination_address=destination_address)
    s["mail_item"] = mi
    s["forwarding_request"] = fr
    return s


# ---------------------------------------------------------------------------
# Tier 1 — Form 1583 progression (no agreement)
# ---------------------------------------------------------------------------
def setup_draft_form(name="Facility", with_recipient=False):
    """Facility + customer + DRAFT form (optionally with one recipient)."""
    fac = create_facility(name=name)
    cust = create_customer(fac["id"])
    form = create_form(fac["id"], cust["id"])
    if with_recipient:
        add_recipient(form["id"])
    return {"facility": fac, "customer": cust, "form": form}


def setup_submitted_form(name="Facility"):
    """Facility + customer + SUBMITTED form (one recipient, submitted)."""
    base = setup_draft_form(name=name, with_recipient=True)
    form = get_success_data(api_client.submit_form_1583(base["form"]["id"], OP))
    base["form"] = form
    return base


def setup_rejected_form(name="Facility", rejection_reason="blurry id"):
    """Facility + customer + REJECTED form."""
    base = setup_submitted_form(name=name)
    form = get_success_data(api_client.reject_form_1583(
        base["form"]["id"], {"rejection_reason": rejection_reason}, CO))
    base["form"] = form
    return base


def setup_verified_form(name="Facility"):
    """Facility + customer + VERIFIED form."""
    base = setup_submitted_form(name=name)
    form = get_success_data(api_client.verify_form_1583(base["form"]["id"], CO))
    base["form"] = form
    return base
