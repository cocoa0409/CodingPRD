"""Cascading state propagation (PRD 2.8) and shared graph helpers.

Two master cascades:
- supervisory: CUSO ACTIVE<->SUSPENDED drags agreements (ACTIVE<->SUSPENDED)
  and their offerings (OPEN<->SUSPENDED).
- delinquency: agreement ACTIVE->DELINQUENT suspends its OPEN offerings;
  DELINQUENT->ACTIVE reopens them.
"""
import db
from middleware import touch


# --- graph helpers -----------------------------------------------------------

def agreement_of_certificate(cert):
    off = db.offerings.get(cert["offering_id"])
    return db.agreements.get(off["servicing_agreement_id"]) if off else None


def offering_of_certificate(cert):
    return db.offerings.get(cert["offering_id"])


def certificates_of_agreement(agreement_id):
    offering_ids = {
        o["id"] for o in db.offerings.values() if o["servicing_agreement_id"] == agreement_id
    }
    return [c for c in db.certificates.values() if c["offering_id"] in offering_ids]


def offerings_of_agreement(agreement_id):
    return [o for o in db.offerings.values() if o["servicing_agreement_id"] == agreement_id]


# --- cascades ---------------------------------------------------------------

def suspend_offerings_of_agreement(agreement):
    for o in offerings_of_agreement(agreement["id"]):
        if o["status"] == "OPEN":
            o["status"] = "SUSPENDED"
            touch("offering", o)


def reopen_offerings_of_agreement(agreement):
    for o in offerings_of_agreement(agreement["id"]):
        if o["status"] == "SUSPENDED":
            o["status"] = "OPEN"
            touch("offering", o)


def cuso_suspend(cuso):
    """CUSO ACTIVE -> SUSPENDED cascade (exam finalization tripwire)."""
    if cuso["status"] != "ACTIVE":
        return
    cuso["status"] = "SUSPENDED"
    touch("cuso", cuso)
    for a in db.agreements.values():
        if a["cuso_id"] == cuso["id"] and a["status"] == "ACTIVE":
            a["status"] = "SUSPENDED"
            touch("agreement", a)
            suspend_offerings_of_agreement(a)


def cuso_reinstate(cuso):
    """CUSO SUSPENDED -> ACTIVE cascade (last open CRITICAL finding closed)."""
    if cuso["status"] != "SUSPENDED":
        return
    cuso["status"] = "ACTIVE"
    touch("cuso", cuso)
    for a in db.agreements.values():
        if a["cuso_id"] == cuso["id"] and a["status"] == "SUSPENDED":
            a["status"] = "ACTIVE"
            touch("agreement", a)
            reopen_offerings_of_agreement(a)


def agreement_maybe_delinquent(agreement):
    """After a late-count increment: flip ACTIVE -> DELINQUENT at threshold."""
    if (
        agreement["status"] == "ACTIVE"
        and agreement["late_remittance_count"] >= agreement["late_remittance_threshold"]
    ):
        agreement["status"] = "DELINQUENT"
        suspend_offerings_of_agreement(agreement)


def agreement_maybe_reinstate(agreement):
    """After a late-count decrement: DELINQUENT -> ACTIVE at zero."""
    if agreement["status"] == "DELINQUENT" and agreement["late_remittance_count"] == 0:
        agreement["status"] = "ACTIVE"
        reopen_offerings_of_agreement(agreement)


def certificate_maybe_reactivate(cert):
    """EXCEPTION -> ACTIVE when no open exceptions and no open repurchase cases."""
    if cert["status"] != "EXCEPTION":
        return
    open_exc = any(
        e["certificate_id"] == cert["id"]
        and e["status"] in ("OPEN", "CURE_SUBMITTED", "REJECTED", "ESCALATED")
        for e in db.exceptions.values()
    )
    open_case = any(
        r["certificate_id"] == cert["id"] and r["status"] in ("TRIGGERED", "DISPUTED")
        for r in db.repurchase_cases.values()
    )
    if not open_exc and not open_case:
        cert["status"] = "ACTIVE"
        touch("certificate", cert)


def recompute_commitment_aggregates(offering, buyer_ids):
    """Declared 'aggregates recomputed' side effect: the offering's committed
    figure and each buyer's total committed figure are derived at read time;
    touch the affected resources so version/updated_at reflect the mutation."""
    touch("offering", offering)
    for bid in buyer_ids:
        cu = db.credit_unions.get(bid)
        if cu is not None:
            touch("credit_union", cu)
