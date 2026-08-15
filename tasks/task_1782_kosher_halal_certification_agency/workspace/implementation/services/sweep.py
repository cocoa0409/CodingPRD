"""The deterministic five-step clock sweep (PRD §2.4), run in this exact order
whenever the logical clock is set:

(1) kosherization VALID -> EXPIRED where now > kosherized_valid_until (strict);
(2) findings OPEN/REOPENED past remediation_deadline -> ESCALATED with the
    facility -> certificate -> client cascade (no equipment compromise here);
(3) certificates ACTIVE past valid_until -> EXPIRED with client recompute;
(4) invoices ISSUED past due_date -> OVERDUE; OVERDUE ANNUAL_CERTIFICATION /
    RENEWAL invoices more than 14 days past due suspend the client's ACTIVE
    certificates, then recompute the client;
(5) agreements ACTIVE whose term_end_date is before the current date -> EXPIRED.
"""
from datetime import timedelta

from db import store, touch
from services.domain import (bubble_client_on_cert_loss, recompute_client_nc,
                             suspend_facility_cascade)

GRACE_DAYS = 14


def run_sweep(now):
    # (1) kosherization validity decay
    for line in store.equipment_lines.values():
        if (line["kosherization_state"] == "VALID"
                and line["kosherized_valid_until"] is not None
                and now > line["kosherized_valid_until"]):
            line["kosherization_state"] = "EXPIRED"
            line["kosherized_valid_until"] = None
            touch(line)

    # (2) finding escalation with facility -> certificate -> client cascade
    for finding in list(store.findings.values()):
        if finding["status"] in ("OPEN", "REOPENED") and now > finding["remediation_deadline"]:
            finding["status"] = "ESCALATED"
            touch(finding)
            facility = store.facilities.get(finding["facility_id"])
            if facility is not None:
                suspend_facility_cascade(facility)
                client = store.clients.get(facility["client_id"])
                if client is not None:
                    recompute_client_nc(client)

    # (3) certificate expiry (strictly later than valid_until)
    for cert in list(store.certificates.values()):
        if (cert["status"] == "ACTIVE" and cert["valid_until"] is not None
                and now > cert["valid_until"]):
            cert["status"] = "EXPIRED"
            touch(cert)
            client = store.clients.get(cert["client_id"])
            if client is not None:
                bubble_client_on_cert_loss(client)

    # (4) invoice overdue transition, then grace-expired fee suspension
    for invoice in list(store.invoices.values()):
        if invoice["status"] == "ISSUED" and now > invoice["due_date"]:
            invoice["status"] = "OVERDUE"
            touch(invoice)
    for invoice in list(store.invoices.values()):
        if (invoice["status"] == "OVERDUE"
                and invoice["invoice_type"] in ("ANNUAL_CERTIFICATION", "RENEWAL")
                and now > invoice["due_date"] + timedelta(days=GRACE_DAYS)):
            client = store.clients.get(invoice["client_id"])
            if client is None:
                continue
            for cert in store.certificates.values():
                if cert["client_id"] == client["id"] and cert["status"] == "ACTIVE":
                    cert["status"] = "SUSPENDED"
                    touch(cert)
            bubble_client_on_cert_loss(client)

    # (5) agreement expiry: term_end_date strictly before the current date
    for agreement in store.agreements.values():
        if agreement["status"] == "ACTIVE" and now.date() > agreement["term_end_date"]:
            agreement["status"] = "EXPIRED"
            touch(agreement)
