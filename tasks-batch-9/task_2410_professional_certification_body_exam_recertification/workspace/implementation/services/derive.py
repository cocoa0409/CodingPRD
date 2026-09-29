"""Derived-field derivation (PRD 2.9).

Every derived field is recomputed from scratch from the records it summarises;
nothing here increments a stored figure.  The only two monotonic counters in the
system -- `verified_application_counter` and `certificants_issued_count` -- are
deliberately not managed here.
"""

from decimal import Decimal

from db import DB, ordered, touch
from services import calc

OCCUPYING_SEAT_STATUSES = ("SCHEDULED", "CHECKED_IN", "COMPLETED")
CONSUMING_SEAT_STATUSES = ("COMPLETED", "NO_SHOW")


# ---------------------------------------------------------------------------
# collection scans
# ---------------------------------------------------------------------------

def items_of_program(program_id):
    return ordered([i for i in DB.items.values() if i["program_id"] == program_id])


def forms_of_program(program_id):
    return ordered([f for f in DB.forms.values() if f["program_id"] == program_id])


def forms_citing_item(item_id):
    return ordered([f for f in DB.forms.values() if item_id in f["item_ids"]])


def registrations_of_application(application_id):
    return ordered([r for r in DB.registrations.values()
                    if r["application_id"] == application_id])


def registrations_of_form(form_id):
    return ordered([r for r in DB.registrations.values() if r["form_id"] == form_id])


def registrations_of_candidate(candidate_id):
    return ordered([r for r in DB.registrations.values()
                    if r["candidate_id"] == candidate_id])


def registrations_of_session(session_id):
    return ordered([r for r in DB.registrations.values() if r["session_id"] == session_id])


def incidents_of_registration(registration_id):
    return ordered([s for s in DB.incidents.values()
                    if s["registration_id"] == registration_id])


def cycles_of_certificant(certificant_id):
    return ordered([c for c in DB.cycles.values()
                    if c["certificant_id"] == certificant_id])


def cases_of_certificant(certificant_id):
    return ordered([c for c in DB.cases.values()
                    if c["certificant_id"] == certificant_id])


def activities_of_cycle(cycle_id):
    return ordered([a for a in DB.activities.values() if a["cycle_id"] == cycle_id])


def certificants_of_candidate(candidate_id):
    return ordered([c for c in DB.certificants.values()
                    if c["candidate_id"] == candidate_id])


# ---------------------------------------------------------------------------
# CertificationProgram -- blueprint posture
# ---------------------------------------------------------------------------

def recompute_blueprint_posture(program, bump=True):
    operational = [i for i in items_of_program(program["id"])
                   if i["status"] == "OPERATIONAL"]
    count = len(operational)
    deficient = sorted(
        spec["domain_code"] for spec in program["domain_specs"]
        if len([i for i in operational if i["domain_code"] == spec["domain_code"]])
        < int(spec["min_operational_items"])
    )
    posture = "DEFICIENT" if deficient else "COMPLETE"
    changed = (
        program.get("operational_item_count") != count
        or program.get("deficient_domain_codes") != deficient
        or program.get("blueprint_posture") != posture
    )
    program["operational_item_count"] = count
    program["deficient_domain_codes"] = deficient
    program["blueprint_posture"] = posture
    if changed and bump:
        touch(program)
    return changed


# ---------------------------------------------------------------------------
# ExamForm -- retired position count
# ---------------------------------------------------------------------------

def form_retired_count(form):
    total = 0
    for item_id in form["item_ids"]:
        item = DB.items.get(item_id)
        if item is not None and item["status"] == "RETIRED":
            total += 1
    return total


def recompute_form_retired_count(form, bump=True):
    count = form_retired_count(form)
    changed = form.get("retired_item_count") != count
    form["retired_item_count"] = count
    if changed and bump:
        touch(form)
    return changed


# ---------------------------------------------------------------------------
# ExamSession -- seat ledger and availability
# ---------------------------------------------------------------------------

def session_seats_reserved(session):
    return len([r for r in DB.registrations.values()
                if r["session_id"] == session["id"]
                and r["seat_status"] in OCCUPYING_SEAT_STATUSES])


def session_status(session):
    if DB.now() >= session["starts_at"]:
        return "CLOSED"
    if session_seats_reserved(session) >= session["seat_capacity"]:
        return "FULL"
    return "OPEN"


def recount_session(session):
    """Seat ledger changed: refresh the stored figure and bump the record."""
    session["seats_reserved"] = session_seats_reserved(session)
    session["status"] = session_status(session)
    touch(session)


def refresh_session_projection(session):
    session["seats_reserved"] = session_seats_reserved(session)
    session["status"] = session_status(session)
    return session


# ---------------------------------------------------------------------------
# EligibilityApplication -- consumed attempts
# ---------------------------------------------------------------------------

def application_attempts_consumed(application):
    return len([r for r in registrations_of_application(application["id"])
                if r["seat_status"] in CONSUMING_SEAT_STATUSES])


# ---------------------------------------------------------------------------
# Certificant -- publication, current cycle, credit mirror
# ---------------------------------------------------------------------------

def certificant_publication_status(certificant):
    if certificant["status"] == "REVOKED":
        return "REMOVED"
    if certificant["status"] in ("SUSPENDED", "EXPIRED"):
        return "WITHHELD"
    return "PUBLISHED"


def certificant_current_cycle(certificant):
    live = [c for c in cycles_of_certificant(certificant["id"])
            if c["status"] in ("OPEN", "SATISFIED", "LAPSED")]
    if not live:
        return None
    return max(live, key=lambda c: c["cycle_number"])


def certificant_ceu_credits_applied(certificant):
    live = [c for c in cycles_of_certificant(certificant["id"])
            if c["status"] in ("OPEN", "SATISFIED")]
    if not live:
        return Decimal("0.00")
    newest = max(live, key=lambda c: c["cycle_number"])
    return newest["credits_applied"]


def refresh_certificant_projection(certificant):
    certificant["publication_status"] = certificant_publication_status(certificant)
    current = certificant_current_cycle(certificant)
    certificant["current_cycle_id"] = current["id"] if current else None
    certificant["ceu_credits_applied"] = certificant_ceu_credits_applied(certificant)
    if certificant["status"] != "SUSPENDED":
        certificant["suspension_until"] = None
    return certificant


# ---------------------------------------------------------------------------
# RecertificationCycle -- credit ledger invariant
# ---------------------------------------------------------------------------

def activity_should_count(activity, cycle):
    return (activity["status"] in ("APPROVED", "VERIFIED")
            and calc.in_accrual_window(cycle, activity["activity_date"]))


def reconcile_cycle(cycle, program):
    """Re-run the accrual for a cycle and re-derive its satisfaction state.

    PRD 2.9: credits_applied is always re-derived from the cycle's counted
    children; the per-activity credits_counted figures are rewritten too, and
    any activity whose figure moves is itself a mutated record.
    """
    activities = activities_of_cycle(cycle["id"])
    credits_applied, counted_map = calc.ceu_credit_accrual(cycle, program, activities)
    for activity in activities:
        granted = counted_map[activity["id"]]
        if activity["credits_counted"] != granted:
            activity["credits_counted"] = granted
            touch(activity)
    changed = cycle["credits_applied"] != credits_applied
    cycle["credits_applied"] = credits_applied
    if derive_cycle_status(cycle):
        changed = True
    if changed:
        touch(cycle)
    return changed


def derive_cycle_status(cycle):
    """SATISFIED / OPEN are the only two re-derived states.

    LAPSED, CLOSED and VOID are terminal-ish outcomes of explicit transitions and
    are never re-derived by the credit invariant.
    """
    if cycle["status"] not in ("OPEN", "SATISFIED"):
        return False
    if cycle["path"] == "CEU":
        satisfied = cycle["credits_applied"] >= cycle["required_credits"]
    else:
        satisfied = cycle["reexam_registration_id"] is not None
    target = "SATISFIED" if satisfied else "OPEN"
    if cycle["status"] == target:
        return False
    cycle["status"] = target
    return True
