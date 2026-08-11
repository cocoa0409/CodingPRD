"""Registration closure sweeps, administrative dissolution and the
reinstatement window (PRD 3.3, 3.11, 3.12)."""

import lookup
import timeutil
from constants import OPEN_OBLIGATION_STATUSES, RANK_ADMIN_DISSOLVED
from services import agents, obligations as obligation_service, rules
from store import DB, touch


def void_open_obligations(registration, exempt_final_report=False):
    """Every obligation in one of the four open statuses is voided.  On
    termination -- and only there -- FINAL_REPORT rows are left untouched."""
    voided = 0
    for obligation in lookup.obligations_of_registration(registration["id"]):
        if obligation["status"] not in OPEN_OBLIGATION_STATUSES:
            continue
        if exempt_final_report and obligation["obligation_type"] == "FINAL_REPORT":
            continue
        obligation_service.to_terminal(obligation, "VOIDED", zero_total=True)
        voided += 1
    return voided


def resign_live_appointments(registration):
    """ADJUDICATION OF FRICTION 13 -- the RESIGNATION_NOTICED leg of the
    registration-closure appointment sweep.  Reading: LIVE, not vestigial.
    PRD 3.3 names the exact residue it bites on: "a registration cannot in fact
    be withdrawn or terminated while a notice window is still open, because
    rung 31 rejects that [...]; the sweep's RESIGNATION_NOTICED branch
    therefore only bites on a notice whose window has closed but which the
    ops-run has not yet retired."  Keeping the leg live keeps that residue
    reachable; dropping it would leave a closed-window notice stranded in
    RESIGNATION_NOTICED on a terminal registration for ever.
    """
    for appointment in lookup.appointments_of_registration(registration["id"]):
        if appointment["status"] in ("PROPOSED", "APPOINTED", "RESIGNATION_NOTICED"):
            appointment["status"] = "RESIGNED"
            appointment["of_record"] = False
            touch(appointment)
    registration["agent_of_record_id"] = None


def reinstatement_deadline_for(registration, dissolved_on):
    rule = rules.select_or_none(registration["state_code"], dissolved_on)
    if rule is None:
        # No declared error covers this endpoint, so fall back to the most
        # recent published version for the jurisdiction and, failing that, to
        # the declared default window.
        rows = [r for r in DB.state_rules.values() if r["state_code"] == registration["state_code"]]
        if rows:
            rows.sort(key=lambda r: (r["effective_from"], r["_seq"]))
            window = rows[-1]["reinstatement_window_days"]
        else:
            window = 365
    else:
        window = rule["reinstatement_window_days"]
    return timeutil.add_days(dissolved_on, window)


def dissolution_horizon_passed(registration, clock_date):
    for obligation in lookup.obligations_of_registration(registration["id"]):
        if obligation["status"] == "DELINQUENT" and clock_date > obligation["delinquency_date"]:
            return True
    return False


def administratively_dissolve(registration):
    clock_date = timeutil.today()
    registration["status"] = "ADMIN_DISSOLVED"
    registration["admin_dissolved_on"] = clock_date
    registration["reinstatement_deadline"] = reinstatement_deadline_for(registration, clock_date)
    registration["delinquency_rank"] = RANK_ADMIN_DISSOLVED
    touch(registration)


def close_permanently(registration):
    """ADMIN_DISSOLVED -> CLOSED_PERMANENT on the ops-run.  Returns the number
    of reinstatement cases the closure expired."""
    clock_date = timeutil.today()
    registration["status"] = "CLOSED_PERMANENT"
    registration["closed_on"] = clock_date
    registration["delinquency_rank"] = RANK_ADMIN_DISSOLVED
    expired = 0
    for case in lookup.cases_of_registration(registration["id"]):
        if case["status"] in ("OPEN", "FEES_ASSESSED", "PAID", "FILED", "DENIED"):
            case["status"] = "EXPIRED"
            touch(case)
            expired += 1
    void_open_obligations(registration)
    touch(registration)
    return expired


def go_delinquent(registration):
    registration["status"] = "DELINQUENT"
    registration["delinquency_rank"] = 3
    touch(registration)


def refresh_agent_of_record(registration):
    agents.select_agent_of_record(registration)


def sop_priority_hold_value(registration):
    """True exactly while at least one LITIGATION document on the registration
    is in RECEIVED, SCANNED, FORWARDED or ESCALATED (PRD 3.9)."""
    for document in lookup.sop_documents_of_registration(registration["id"]):
        if document["sop_class"] == "LITIGATION" and document["status"] in (
            "RECEIVED",
            "SCANNED",
            "FORWARDED",
            "ESCALATED",
        ):
            return True
    return False


def refresh_sop_priority_hold(registration):
    """Re-evaluate the flag; bump the registration only when it actually moves.

    ADJUDICATION OF FRICTION 11 -- whether sop_priority_hold clears when a
    document is acknowledged out of ESCALATED.  Reading: IT IS RE-EVALUATED ON
    BOTH LEGS.  PRD 3.9's acknowledgment paragraph states the re-evaluation
    without distinguishing the origin state ("Because acknowledgment takes the
    document out of the open litigation set, the registration's
    sop_priority_hold is re-evaluated and clears when no other litigation
    document on the registration remains in RECEIVED, SCANNED, FORWARDED or
    ESCALATED"), and re-evaluating on both legs keeps the flag's own declared
    invariant -- "true exactly while at least one LITIGATION document ... is
    in [that set]" -- true at every instant, which the one-leg reading would
    violate for any litigation document acknowledged out of ESCALATED.
    """
    value = sop_priority_hold_value(registration)
    if registration["sop_priority_hold"] != value:
        registration["sop_priority_hold"] = value
        touch(registration)
        return True
    return False
