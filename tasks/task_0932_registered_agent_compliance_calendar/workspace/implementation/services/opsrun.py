"""The ops-run checkpoint (PRD 3.13).

ADJUDICATION OF FRICTION 12 -- cascade depth within one run.  Reading:
MULTI-HOP WITHIN ONE SWEEP.  PRD 3.13 fixes the order of the seven steps ("Its
work, in the order the sweep performs it"), and a later step that reads state a
former step wrote is exactly what that ordering buys: an obligation that
reaches DELINQUENT in step 1 drives its registration to DELINQUENT in step 1
and is then eligible for step 4's dissolution sweep on the same run.  This is
the reading that keeps the most declared behaviour reachable -- the one-hop-per-
run reading would make "a clock jump that crosses several rungs in one step"
(PRD 3.4) unable to reach ADMIN_DISSOLVED without extra no-op runs the document
never mentions.  The sweep is still bounded: each of the seven steps runs
exactly once, in the declared order, so no step ever re-enters itself.  A run
that finds nothing to do mutates nothing at all.
"""

import lookup
import timeutil
from constants import OPEN_OBLIGATION_STATUSES
from services import boi, obligations as obligation_service, registrations as registration_service
from services import rollups
from store import DB, ordered, touch


def run():
    clock_date = timeutil.today()
    counters = {
        "obligations_advanced": 0,
        "reminders_sent": 0,
        "appointments_resigned": 0,
        "registrations_dissolved": 0,
        "registrations_closed_permanent": 0,
        "cases_expired": 0,
        "boi_axes_delinquent": 0,
    }

    # -- step 1: advance every open obligation along the monotone ladder ----
    for obligation in ordered(list(DB.obligations.values())):
        if obligation_service.advance(obligation, clock_date):
            counters["obligations_advanced"] += 1
            if obligation["status"] == "DELINQUENT":
                registration = DB.registrations.get(obligation["registration_id"])
                if registration is not None and registration["status"] == "ACTIVE":
                    registration_service.go_delinquent(registration)

    # -- step 2: the reminder send pass ------------------------------------
    for notice in ordered(list(DB.reminders.values())):
        if notice["status"] != "PENDING":
            continue
        obligation = DB.obligations.get(notice["compliance_obligation_id"])
        if obligation is None:
            continue
        if clock_date < notice["scheduled_for"]:
            continue
        if notice["due_date_snapshot"] != obligation["due_date"]:
            continue
        if obligation["status"] not in OPEN_OBLIGATION_STATUSES:
            continue
        notice["status"] = "SENT"
        notice["sent_on"] = clock_date
        touch(notice)
        counters["reminders_sent"] += 1

    # -- step 3: retire elapsed resignation notices -------------------------
    for appointment in ordered(list(DB.appointments.values())):
        if appointment["status"] != "RESIGNATION_NOTICED":
            continue
        effective = appointment["resignation_effective_on"]
        if effective is None or clock_date < effective:
            continue
        appointment["status"] = "RESIGNED"
        appointment["of_record"] = False
        touch(appointment)
        registration = DB.registrations.get(appointment["registration_id"])
        if registration is not None:
            registration_service.refresh_agent_of_record(registration)
            touch(registration)
        counters["appointments_resigned"] += 1

    # -- step 4: dissolve, then close permanently ---------------------------
    for registration in ordered(list(DB.registrations.values())):
        if registration["status"] != "DELINQUENT":
            continue
        if registration_service.dissolution_horizon_passed(registration, clock_date):
            registration_service.administratively_dissolve(registration)
            counters["registrations_dissolved"] += 1

    for registration in ordered(list(DB.registrations.values())):
        if registration["status"] != "ADMIN_DISSOLVED":
            continue
        deadline = registration["reinstatement_deadline"]
        if deadline is None or clock_date <= deadline:
            continue
        counters["cases_expired"] += registration_service.close_permanently(registration)
        counters["registrations_closed_permanent"] += 1

    # -- step 5: expire lapsed reinstatement windows ------------------------
    for case in ordered(list(DB.reinstatement_cases.values())):
        if case["status"] not in ("OPEN", "FEES_ASSESSED", "PAID", "FILED", "DENIED"):
            continue
        if case["window_close_date"] is None or clock_date <= case["window_close_date"]:
            continue
        case["status"] = "EXPIRED"
        touch(case)
        counters["cases_expired"] += 1

    # -- step 6: the beneficial-ownership axis ------------------------------
    for entity in ordered(list(DB.legal_entities.values())):
        if boi.advance_axis(entity, clock_date):
            counters["boi_axes_delinquent"] += 1

    # -- step 7: every rank and every rollup --------------------------------
    for registration in DB.registrations.values():
        registration_service.refresh_agent_of_record(registration)
    rollups.recompute_everything()

    return counters


def cure_check():
    """Not part of the sweep: exposed so state changes elsewhere can reuse it."""
    for registration in DB.registrations.values():
        if registration["status"] == "DELINQUENT":
            obligation_service.cure_registration(registration)
    rollups.recompute_everything()


def open_obligations_of(registration_id):
    return [
        o
        for o in lookup.obligations_of_registration(registration_id)
        if o["status"] in OPEN_OBLIGATION_STATUSES
    ]
