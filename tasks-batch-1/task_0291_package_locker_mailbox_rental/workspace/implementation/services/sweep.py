"""Clock-advance deferred bookkeeping (PRD §2.6, §3)."""
from db import db
from common import touch
import clock
import constants as C
from services import billing
from services import packages as pkg_svc
from services import agreements as agr_svc


def run_sweep(facility):
    """Run all deferred sweeps after the facility clock has advanced.

    Order: recompute provisional overstay on NOTIFIED packages; abandon
    overdue packages; suspend over-balance ACTIVE agreements; abandon
    over-grace agreements with outstanding balance.
    """
    now = clock.parse_iso(facility["current_utc"])
    fid = facility["id"]

    # 1. Recompute provisional overstay on all NOTIFIED packages (bumps version).
    for p in list(db.packages.values()):
        if p["facility_id"] == fid and p["status"] == "NOTIFIED":
            pkg_svc.recompute_provisional_overstay(p, facility)
            touch(p)

    # 2. Abandon RECEIVED/NOTIFIED packages past notified_at + PACKAGE_ABANDON_DAYS.
    for p in list(db.packages.values()):
        if p["facility_id"] != fid:
            continue
        if p["status"] not in ("RECEIVED", "NOTIFIED"):
            continue
        notified = clock.parse_iso(p["notified_at"]) if p.get("notified_at") else None
        if notified is None:
            continue
        threshold = clock.add_days(notified, C.PACKAGE_ABANDON_DAYS)
        if now >= threshold:
            invoice = pkg_svc.invoice_for_agreement(p["rental_agreement_id"])
            agr_svc.abandon_package(p, facility, invoice)

    # 3. Suspend ACTIVE agreements whose balance exceeds the threshold.
    for a in list(db.rental_agreements.values()):
        if a["facility_id"] != fid or a["status"] != "ACTIVE":
            continue
        invoice = pkg_svc.invoice_for_agreement(a["id"])
        if invoice is None:
            continue
        if billing.invoice_balance(invoice) > C.SUSPEND_BALANCE_THRESHOLD_CENTS:
            a["status"] = "SUSPENDED"
            agr_svc.cascade_suspend(a)
            touch(a)

    # 4. Abandon agreements past term_end + ABANDONMENT_GRACE_DAYS with balance > 0.
    for a in list(db.rental_agreements.values()):
        if a["facility_id"] != fid:
            continue
        if a["status"] not in ("PENDING_AUTH", "ACTIVE", "SUSPENDED"):
            continue
        if not a.get("term_end"):
            continue
        term_end = clock.parse_iso(a["term_end"])
        threshold = clock.add_days(term_end, C.ABANDONMENT_GRACE_DAYS)
        if now < threshold:
            continue
        invoice = pkg_svc.invoice_for_agreement(a["id"])
        if invoice is None or billing.invoice_balance(invoice) <= 0:
            continue
        agr_svc.abandon_agreement(a, facility)
