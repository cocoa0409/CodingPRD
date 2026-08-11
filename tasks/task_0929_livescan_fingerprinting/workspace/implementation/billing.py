"""Agency delinquency posture (PRD 3.9).

Friction point 7 is resolved in favour of the posture projection: max_aging_days
and outstanding_balance_cents are always the projection over the agency's open
(ISSUED or PAST_DUE) invoices, and billing_status follows the 45 / 1 / 0
thresholds -- on every path that recomputes it, the nightly batch, an invoice
payment and an invoice issuance alike.  suspended_at is a historical stamp of the
instant the posture most recently became SUSPENDED and is never cleared.
"""

import constants as C
import derive
from store import db


def open_invoices(agency):
    return [
        invoice
        for invoice in db.invoices.values()
        if invoice["agency_id"] == agency["id"] and invoice["status"] in ("ISSUED", "PAST_DUE")
    ]


def recompute_agency_posture(agency):
    """Returns True when the agency newly entered SUSPENDED in this call."""
    invoices = open_invoices(agency)
    max_aging = max((derive.invoice_aging_days(i) for i in invoices), default=0)
    outstanding = sum(i["total_cents"] - i["paid_cents"] for i in invoices)

    if max_aging >= C.AGENCY_SUSPENSION_AGING_DAYS:
        status = "SUSPENDED"
    elif max_aging >= 1:
        status = "PAST_DUE"
    else:
        status = "CURRENT"

    was_suspended = agency["billing_status"] == "SUSPENDED"
    changed = (
        agency["outstanding_balance_cents"] != outstanding
        or agency["max_aging_days"] != max_aging
        or agency["billing_status"] != status
    )

    agency["outstanding_balance_cents"] = outstanding
    agency["max_aging_days"] = max_aging
    agency["billing_status"] = status

    newly_suspended = status == "SUSPENDED" and not was_suspended
    if newly_suspended:
        agency["suspended_at"] = db.now()
        changed = True

    if changed:
        db.touch(agency)

    if newly_suspended:
        cancel_mobile_event_appointments(agency)
    return newly_suspended


def cancel_mobile_event_appointments(agency):
    """The suspension cascade cancels BOOKED appointments at MOBILE_EVENT sites
    hosted by this agency; appointments at FIXED sites are left exactly as they
    are, whichever ORI they were booked under."""
    site_ids = {
        site["id"]
        for site in db.sites.values()
        if site["site_kind"] == "MOBILE_EVENT" and site.get("host_agency_id") == agency["id"]
    }
    if not site_ids:
        return
    for appointment in db.appointments.values():
        if appointment["status"] == "BOOKED" and appointment["site_id"] in site_ids:
            appointment["status"] = "CANCELLED"
            db.touch(appointment)


def recompute_invoice_totals(invoice):
    attached = [
        a
        for a in db.assessments.values()
        if a["invoice_id"] == invoice["id"] and a["status"] in ("INVOICED", "PAID")
    ]
    invoice["subtotal_cents"] = sum(a["total_cents"] for a in attached)
    invoice["total_cents"] = invoice["subtotal_cents"] + invoice["late_fee_cents"]
