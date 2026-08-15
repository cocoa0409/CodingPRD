"""Cascading state consistency (PRD §2.10, §3.1-§3.3, §3.8).

Every cascade step is an ordinary mutation of the resource it touches: updated_at
is refreshed and version incremented on each affected resource.
"""
import db
from db import store

WITHDRAWABLE = ("INTAKE_STARTED", "IN_PREPARATION", "PENDING_QR",
                "QR_FAILED", "QR_PASSED", "REJECTED")


def void_referrals(tax_return_id):
    """Referral-voiding invariant: OFFERED/ACCEPTED referrals of a return moving to
    WITHDRAWN or REFERRED become VOID; ENROLLED/DECLINED are untouched."""
    for ref in store.financial_referrals.values():
        if (ref["tax_return_id"] == tax_return_id
                and ref["status"] in ("OFFERED", "ACCEPTED")):
            ref["status"] = "VOID"
            db.touch(ref)


def withdraw_return(ret, reason):
    """Cascade-driven withdrawal: the cascade supplies its own reason."""
    ret["status"] = "WITHDRAWN"
    ret["withdrawal_reason"] = reason
    db.touch(ret)
    void_referrals(ret["id"])


def cancel_appointment(appt, withdraw_reason):
    """Cancel an appointment and withdraw any INTAKE_STARTED return it originated."""
    appt["status"] = "CANCELLED"
    db.touch(appt)
    for r in store.tax_returns.values():
        if r["appointment_id"] == appt["id"] and r["status"] == "INTAKE_STARTED":
            withdraw_return(r, withdraw_reason)


def volunteer_inactivation_cascade(volunteer_id):
    """Volunteer inactivation: cancel the volunteer's SCHEDULED appointments
    (CHECKED_IN untouched); each cancelled appointment that originated an
    INTAKE_STARTED return withdraws it (reason VOLUNTEER_INACTIVATED)."""
    for a in list(store.appointments.values()):
        if a["volunteer_id"] == volunteer_id and a["status"] == "SCHEDULED":
            cancel_appointment(a, "VOLUNTEER_INACTIVATED")


def site_suspension_cascade(site_id):
    """Site suspension, three links (PRD §3.1):
    link 1 cancels SCHEDULED/CHECKED_IN appointments of the site;
    link 2 withdraws INTAKE_STARTED returns originated by those appointments
    (reason SITE_SUSPENDED);
    link 3 voids those returns' OFFERED/ACCEPTED financial-service referrals."""
    for a in list(store.appointments.values()):
        if a["site_id"] == site_id and a["status"] in ("SCHEDULED", "CHECKED_IN"):
            cancel_appointment(a, "SITE_SUSPENDED")
