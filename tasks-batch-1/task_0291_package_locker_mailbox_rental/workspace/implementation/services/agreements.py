"""RentalAgreement cascade side-effects shared by routes and the clock sweep."""
from db import db
from common import touch
import calculations as calc
import clock
import constants as C
from services import billing
from services import packages as pkg_svc


def mailbox_to_vacant(agreement):
    mb = db.mailbox_units.get(agreement["mailbox_unit_id"])
    if mb is not None and mb["status"] == "RENTED":
        mb["status"] = "VACANT"
        touch(mb)


def forwarding_requests_for_agreement(agreement_id):
    """All forwarding requests whose mail item belongs to this agreement."""
    result = []
    for fr in db.forwarding_requests.values():
        mi = db.mail_items.get(fr["mail_item_id"])
        if mi is not None and mi["rental_agreement_id"] == agreement_id:
            result.append(fr)
    return result


def cascade_suspend(agreement):
    """REQUESTED forwarding on this agreement's mail -> ON_HOLD."""
    for fr in forwarding_requests_for_agreement(agreement["id"]):
        if fr["status"] == "REQUESTED":
            fr["status"] = "ON_HOLD"
            touch(fr)


def cascade_reactivate(agreement):
    """ON_HOLD forwarding on this agreement's mail -> REQUESTED."""
    for fr in forwarding_requests_for_agreement(agreement["id"]):
        if fr["status"] == "ON_HOLD":
            fr["status"] = "REQUESTED"
            touch(fr)


def cascade_shred_and_cancel(agreement):
    """STORED mail -> SHREDDED; REQUESTED/ON_HOLD forwarding on those -> CANCELLED."""
    for mi in db.mail_items.values():
        if mi["rental_agreement_id"] == agreement["id"] and mi["status"] == "STORED":
            mi["status"] = "SHREDDED"
            touch(mi)
    for fr in forwarding_requests_for_agreement(agreement["id"]):
        if fr["status"] in ("REQUESTED", "ON_HOLD"):
            fr["status"] = "CANCELLED"
            touch(fr)


def close_agreement(agreement, facility):
    """Apply CLOSE side-effects (assumes preconditions already checked)."""
    invoice = pkg_svc.invoice_for_agreement(agreement["id"])
    agreement["status"] = "CLOSED"
    mailbox_to_vacant(agreement)
    # Prorated refund (chronological variant) posted as a CREDIT.
    if invoice is not None and agreement.get("term_start"):
        term_start = clock.parse_iso(agreement["term_start"])
        close_instant = clock.parse_iso(facility["current_utc"])
        refund = calc.prorated_refund_chronological(
            agreement["monthly_fee_cents"], agreement["term_months"],
            term_start, close_instant, facility["time_zone"])
        if refund > 0:
            billing.post_ledger_entry(invoice, "CREDIT", "PRORATED_REFUND", refund, agreement["id"])
    cascade_shred_and_cancel(agreement)
    if invoice is not None and billing.invoice_balance(invoice) <= 0:
        if invoice["status"] == "OPEN":
            invoice["status"] = "SETTLED"
            touch(invoice)
    touch(agreement)


def abandon_agreement(agreement, facility):
    """Apply ABANDONED side-effects (clock sweep only)."""
    invoice = pkg_svc.invoice_for_agreement(agreement["id"])
    agreement["status"] = "ABANDONED"
    mailbox_to_vacant(agreement)
    # Cascade every package in RECEIVED/NOTIFIED -> ABANDONED.
    for p in db.packages.values():
        if p["rental_agreement_id"] == agreement["id"] and p["status"] in ("RECEIVED", "NOTIFIED"):
            abandon_package(p, facility, invoice)
    # Shred STORED mail.
    for mi in db.mail_items.values():
        if mi["rental_agreement_id"] == agreement["id"] and mi["status"] == "STORED":
            mi["status"] = "SHREDDED"
            touch(mi)
    # Write off remaining balance.
    if invoice is not None:
        balance = billing.invoice_balance(invoice)
        if balance > 0:
            billing.post_ledger_entry(invoice, "CREDIT", "WRITE_OFF", balance, agreement["id"])
        invoice["status"] = "WRITTEN_OFF"
        touch(invoice)
    touch(agreement)


def abandon_package(package, facility, invoice):
    """Package -> ABANDONED: finalize fees, post charges, release locker."""
    resolved = clock.parse_iso(facility["current_utc"])
    pkg_svc.finalize_overstay(package, facility, resolved)
    package["resolved_at"] = facility["current_utc"]
    package["status"] = "ABANDONED"
    if invoice is None:
        invoice = pkg_svc.invoice_for_agreement(package["rental_agreement_id"])
    agreement = db.rental_agreements.get(package["rental_agreement_id"])
    if invoice is not None:
        pkg_svc.post_resolution_charges(package, agreement, invoice)
        if agreement is not None:
            billing.capture_autopay(agreement, invoice)
    pkg_svc.release_locker(package)
    touch(package)
