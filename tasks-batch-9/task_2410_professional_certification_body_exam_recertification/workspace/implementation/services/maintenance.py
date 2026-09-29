"""The explicit maintenance run (PRD 3.13).

Nothing in this system expires on a timer.  Deadlines only take effect when
POST /recertification-runs is invoked, and the four steps run in the pinned order,
each visiting its candidates in created_at ascending order.  `dry_run` reports
exactly what a committing run would do without mutating a byte.
"""

from db import DB, ordered, touch
from services import calc, derive, lookup
from util import fmt_ts


def _due_no_show_registrations():
    due = []
    for registration in ordered(DB.registrations.values()):
        if registration["seat_status"] != "SCHEDULED":
            continue
        session_id = registration["session_id"]
        if not session_id or session_id not in DB.sessions:
            continue
        if DB.now() > DB.sessions[session_id]["ends_at"]:
            due.append(registration)
    return due


def _due_expired_applications():
    due = []
    for application in ordered(DB.applications.values()):
        if application["status"] != "APPROVED":
            continue
        expires = application["eligibility_expires_on"]
        if expires is not None and DB.now() > expires:
            due.append(application)
    return due


def _due_lapsed_cycles():
    return [cycle for cycle in ordered(DB.cycles.values())
            if cycle["status"] == "OPEN" and DB.now() > cycle["grace_ends_on"]]


def _due_reactivated_certificants():
    due = []
    for certificant in ordered(DB.certificants.values()):
        if certificant["status"] != "SUSPENDED":
            continue
        until = certificant["suspension_until"]
        if until is not None and DB.now() >= until:
            due.append(certificant)
    return due


def _due_unbarred_candidates():
    due = []
    for candidate in ordered(DB.candidates.values()):
        if candidate["status"] != "BARRED":
            continue
        until = candidate["barred_until"]
        if until is not None and DB.now() >= until:
            due.append(candidate)
    return due


def run(commit):
    report = {
        "run_at": fmt_ts(DB.now()),
        "no_show_registration_ids": [],
        "expired_application_ids": [],
        "lapsed_cycle_ids": [],
        "expired_certificant_ids": [],
        "reactivated_certificant_ids": [],
        "unbarred_candidate_ids": [],
    }

    # --- step 1: seats abandoned past the sitting -------------------------
    released_sessions = set()
    for registration in _due_no_show_registrations():
        report["no_show_registration_ids"].append(registration["id"])
        if not commit:
            continue
        held = registration["session_id"]
        registration["seat_status"] = "NO_SHOW"
        touch(registration)
        if held:
            released_sessions.add(held)
        application = DB.applications.get(registration["application_id"])
        if application is not None:
            touch(application)
    if commit:
        for session in ordered([DB.sessions[i] for i in released_sessions
                                if i in DB.sessions]):
            derive.recount_session(session)

    # --- step 2: eligibility that ran out ---------------------------------
    for application in _due_expired_applications():
        report["expired_application_ids"].append(application["id"])
        if commit:
            application["status"] = "EXPIRED"
            touch(application)

    # --- step 3: cycles past their grace window ---------------------------
    for cycle in _due_lapsed_cycles():
        report["lapsed_cycle_ids"].append(cycle["id"])
        certificant = lookup.certificant_of_cycle(cycle)
        expires_holder = certificant["status"] == "ACTIVE"
        if expires_holder:
            report["expired_certificant_ids"].append(certificant["id"])
        if not commit:
            continue
        cycle["status"] = "LAPSED"
        cycle["reinstatement_fee_cents"] = calc.reinstatement_fee_assessment(
            DB.now(), cycle["grace_ends_on"]
        )
        touch(cycle)
        if expires_holder:
            certificant["status"] = "EXPIRED"
            touch(certificant)
        derive.refresh_certificant_projection(certificant)

    # --- step 4: suspensions and bars that have run their course ----------
    for certificant in _due_reactivated_certificants():
        report["reactivated_certificant_ids"].append(certificant["id"])
        if commit:
            certificant["status"] = "ACTIVE"
            certificant["suspension_until"] = None
            touch(certificant)
            derive.refresh_certificant_projection(certificant)

    for candidate in _due_unbarred_candidates():
        report["unbarred_candidate_ids"].append(candidate["id"])
        if commit:
            candidate["status"] = "ACTIVE"
            candidate["barred_until"] = None
            touch(candidate)

    return report
