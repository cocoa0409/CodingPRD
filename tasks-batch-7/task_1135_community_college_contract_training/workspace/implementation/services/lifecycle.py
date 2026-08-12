"""State machine transitions, cancellation cascades, and clock-driven sweeps."""

from datetime import timedelta

from db import now, store, touch
from services import lookups
from services.calculations import attendance_completion
from util import fmt_dt, parse_dt

TERMINAL_COHORT_STATES = ("CREDENTIALED", "CANCELLED")


# ---------------------------------------------------------------------------
# Cohort / session cascade machinery (PRD 3.9)
# ---------------------------------------------------------------------------

def _release_assignment_cascade(assignment, session):
    """Link 3: PROPOSED/CONFIRMED -> RELEASED; CONFIRMED releases decrement committed_hours."""
    if assignment["status"] not in ("PROPOSED", "CONFIRMED"):
        return
    was_confirmed = assignment["status"] == "CONFIRMED"
    assignment["status"] = "RELEASED"
    touch(assignment)
    if was_confirmed:
        instructor = store["instructors"].get(assignment["instructor_id"])
        if instructor is not None:
            instructor["committed_hours"] = round(
                float(instructor["committed_hours"]) - float(session["hours"]), 10
            )
            touch(instructor)


def cancel_session_cascade(session):
    """PLANNED -> CANCELLED with assignment release (link 2/3)."""
    if session["status"] != "PLANNED":
        return
    session["status"] = "CANCELLED"
    touch(session)
    for assignment in lookups.assignments_of_session(session["id"]):
        _release_assignment_cascade(assignment, session)


def _withdraw_applications_cascade(cohort):
    """Link 2': pending applications -> WITHDRAWN; APPROVED release reserved first."""
    for application in lookups.applications_of_cohort(cohort["id"]):
        if application["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "RETURNED"):
            application["status"] = "WITHDRAWN"
            touch(application)
        elif application["status"] == "APPROVED":
            program = store["programs"].get(application["program_id"])
            if program is not None:
                program["reserved_cents"] -= application["reserved_cents"]
                program["available_cents"] += application["reserved_cents"]
                touch(program)
            application["reserved_cents"] = 0
            application["status"] = "WITHDRAWN"
            touch(application)


def _void_invoices_cascade(cohort):
    """Link 2'': open DRAFT/ISSUED invoice -> VOID; INVOICED cohort returns to UNBILLED."""
    for invoice in lookups.invoices_of_cohort(cohort["id"]):
        if invoice["status"] in ("DRAFT", "ISSUED"):
            invoice["status"] = "VOID"
            touch(invoice)
    if cohort["billing_status"] == "INVOICED":
        cohort["billing_status"] = "UNBILLED"


def cancel_cohort_cascade(cohort):
    """Cohort -> CANCELLED with the full link set (PRD 3.9)."""
    cohort["delivery_status"] = "CANCELLED"
    touch(cohort)
    for session in lookups.sessions_of_cohort(cohort["id"]):
        if session["status"] == "PLANNED":
            cancel_session_cascade(session)
    _withdraw_applications_cascade(cohort)
    _void_invoices_cascade(cohort)


def cancel_agreement_cascade(agreement):
    """SIGNED/IN_DELIVERY -> CANCELLED fires the full hierarchy cascade."""
    for cohort in lookups.cohorts_of_agreement(agreement["id"]):
        if cohort["delivery_status"] in ("SCHEDULED", "LAUNCHED", "IN_PROGRESS"):
            cancel_cohort_cascade(cohort)


# ---------------------------------------------------------------------------
# Delivery progression (PRD 3.6)
# ---------------------------------------------------------------------------

def maybe_advance_cohort_delivery(cohort):
    """After a session becomes HELD or CANCELLED: LAUNCHED->IN_PROGRESS on first HELD;
    IN_PROGRESS->DELIVERED when every session is in {HELD, CANCELLED} with >=1 HELD."""
    sessions = lookups.sessions_of_cohort(cohort["id"])
    held = [s for s in sessions if s["status"] == "HELD"]
    if cohort["delivery_status"] == "LAUNCHED" and held:
        cohort["delivery_status"] = "IN_PROGRESS"
        touch(cohort)
    if cohort["delivery_status"] == "IN_PROGRESS":
        if sessions and all(s["status"] in ("HELD", "CANCELLED") for s in sessions) and held:
            cohort["delivery_status"] = "DELIVERED"
            attendance_completion(cohort)
            touch(cohort)


# ---------------------------------------------------------------------------
# Agreement completion / billing settlement helpers (PRD 3.7, 3.8)
# ---------------------------------------------------------------------------

def maybe_settle_agreement_billing(agreement):
    """SETTLED when every non-CANCELLED cohort has billing_status == PAID."""
    cohorts = [c for c in lookups.cohorts_of_agreement(agreement["id"]) if c["delivery_status"] != "CANCELLED"]
    if cohorts and all(c["billing_status"] == "PAID" for c in cohorts):
        if agreement["billing_status"] != "SETTLED":
            agreement["billing_status"] = "SETTLED"


def maybe_complete_agreement(agreement):
    """IN_DELIVERY -> COMPLETED when every cohort is in a terminal delivery state."""
    cohorts = lookups.cohorts_of_agreement(agreement["id"])
    if not cohorts:
        return
    if all(c["delivery_status"] in TERMINAL_COHORT_STATES for c in cohorts):
        if agreement["contract_status"] == "IN_DELIVERY":
            agreement["contract_status"] = "COMPLETED"
            maybe_settle_agreement_billing(agreement)
            touch(agreement)


# ---------------------------------------------------------------------------
# Clock-driven sweeps (PRD 3.9)
# ---------------------------------------------------------------------------

def dormancy_sweep():
    current = now()
    horizon = current - timedelta(days=365)
    for employer in store["employers"].values():
        if employer["status"] != "ACTIVE":
            continue
        agreements = lookups.agreements_of_employer(employer["id"])
        if any(
            a["contract_status"] in ("QUOTED", "NEGOTIATING", "SIGNED", "IN_DELIVERY")
            for a in agreements
        ):
            continue
        recent_credential = False
        for agreement in agreements:
            for cohort in lookups.cohorts_of_agreement(agreement["id"]):
                cred_at = cohort.get("_credentialed_at")
                if cred_at:
                    parsed = parse_dt(cred_at)
                    if parsed is not None and parsed >= horizon:
                        recent_credential = True
                        break
            if recent_credential:
                break
        if not recent_credential:
            employer["status"] = "DORMANT"
            touch(employer)


def grant_expiry_sweep():
    current = now()
    for application in store["applications"].values():
        if application["status"] != "APPROVED" or not application.get("claim_by"):
            continue
        claim_by = parse_dt(application["claim_by"])
        if claim_by is not None and current > claim_by:
            program = store["programs"].get(application["program_id"])
            if program is not None:
                program["reserved_cents"] -= application["reserved_cents"]
                program["available_cents"] += application["reserved_cents"]
                touch(program)
            application["reserved_cents"] = 0
            application["status"] = "EXPIRED"
            touch(application)


def run_clock_sweeps():
    dormancy_sweep()
    grant_expiry_sweep()
