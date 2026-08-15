"""State-transition cascades (PRD sections 3.5, 3.7, 3.8) and the scheduled
compliance sweep of PRD section 2.5.

Every record touched by a cascade gets its own version increment and its own
updated_at refresh (PRD 2.4).
"""

from . import calc
from .store import db, bump


def forfeit_entry(entry, include_paid=False):
    """CommissionEntry -> FORFEITED.

    Decline and the producer-suspension cascade forfeit any non-terminal
    (HELD | PAYABLE) entry; rescission forfeits whatever the entry's status,
    including PAID.  Already-FORFEITED entries are untouched.
    """
    if entry is None or entry["status"] == "FORFEITED":
        return False
    if entry["status"] == "PAID" and not include_paid:
        return False
    if entry["status"] not in ("HELD", "PAYABLE", "PAID"):
        return False
    entry["status"] = "FORFEITED"
    entry["hold_reason"] = None
    bump(entry)
    return True


def decline_application(app):
    """SUBMITTED -> DECLINED with the commission forfeiture of PRD 3.5."""
    app["status"] = "DECLINED"
    app["decided_at"] = db.now
    bump(app)
    entry = calc.entry_for_application(app["id"])
    if forfeit_entry(entry):
        calc.recompute_producer_held(app["producer_id"])


def suspend_producer(producer):
    """ACTIVE -> SUSPENDED plus the application decline cascade (PRD 3.8)."""
    producer["status"] = "SUSPENDED"
    bump(producer)
    apps = [
        a for a in db.ordered("applications")
        if a["producer_id"] == producer["id"] and a["status"] == "SUBMITTED"
    ]
    for app in apps:
        decline_application(app)
    calc.recompute_producer_held(producer["id"])


def _inquiry_overdue(inquiry):
    inquiry["status"] = "OVERDUE"
    bump(inquiry)
    if inquiry["producer_id"] is not None:
        producer = db.producers.get(inquiry["producer_id"])
        if producer is not None and producer["status"] == "ACTIVE":
            suspend_producer(producer)


def sweep():
    """The scheduled compliance sweep, run whenever the logical clock is set.

    Strict comparison throughout: a record whose deadline equals the new clock
    value exactly is NOT swept.
    """
    now = db.now
    for lic in db.ordered("licenses"):
        if lic["status"] == "ACTIVE" and lic["expiration_date"] < now:
            lic["status"] = "EXPIRED"
            bump(lic)
    for appt in db.ordered("appointments"):
        if (
            appt["status"] == "JIT_PENDING"
            and appt["jit_filing_deadline"] is not None
            and appt["jit_filing_deadline"] < now
        ):
            appt["status"] = "LAPSED"
            bump(appt)
    for inquiry in db.ordered("inquiries"):
        if inquiry["status"] == "OPEN" and inquiry["response_due_at"] < now:
            _inquiry_overdue(inquiry)


def apply_license_discipline(action):
    """The disciplinary cascade of PRD 3.7 fired by confirming a SUSPENSION
    or REVOCATION: the matching license moves, its ACTIVE appointments in the
    state fall to TERMINATION_PENDING, the producer's PAYABLE entries are
    re-held as REGULATORY_HOLD, and on revocation UNLICENSED_AT_SALE holds are
    forfeited."""
    from .pipeline import subject_of

    subject_field, subject_id = subject_of(action)
    if subject_id is None:
        return

    if action["action_type"] == "SUSPENSION":
        lic = calc.active_license_in_state(subject_field, subject_id, action["state_code"])
        if lic is None:
            return
        lic["status"] = "SUSPENDED"
        bump(lic)
    else:  # REVOCATION: ACTIVE or already SUSPENDED -> REVOKED
        lic = None
        for cand in calc.licenses_of_subject(subject_field, subject_id, action["state_code"]):
            if cand["status"] in ("ACTIVE", "SUSPENDED"):
                lic = cand
                break
        if lic is None:
            return
        lic["status"] = "REVOKED"
        bump(lic)

    # Every ACTIVE appointment of the same subject in this state follows.
    for appt in calc.appointments_of_subject(subject_field, subject_id, action["state_code"]):
        if appt["status"] == "ACTIVE":
            appt["status"] = "TERMINATION_PENDING"
            appt["termination_reason"] = "LICENSE_INACTIVE"
            appt["termination_initiated_at"] = db.now
            bump(appt)

    # The commission cascade names the producer's entries; agencies hold none.
    if action.get("producer_id") is None:
        return
    producer_id = action["producer_id"]
    for entry in db.ordered("commission_entries"):
        if entry["producer_id"] == producer_id and entry["status"] == "PAYABLE":
            entry["status"] = "HELD"
            entry["hold_reason"] = "REGULATORY_HOLD"
            bump(entry)
    if action["action_type"] == "REVOCATION":
        for entry in db.ordered("commission_entries"):
            if (
                entry["producer_id"] == producer_id
                and entry["status"] == "HELD"
                and entry["hold_reason"] == "UNLICENSED_AT_SALE"
            ):
                entry["status"] = "FORFEITED"
                entry["hold_reason"] = None
                bump(entry)
    calc.recompute_producer_held(producer_id)
