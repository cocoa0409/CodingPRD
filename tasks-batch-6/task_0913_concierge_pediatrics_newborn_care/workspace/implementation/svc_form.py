"""The form issuance gate (PRD 3.9, calculations.form_issuance_gate).

An ordered three-rung ladder over three different entities.  The FIRST failing
rung supplies blocked_reason; later rungs are not evaluated at all.
"""
import calc
import constants as C
from store import db
from timeutil import add_days


def evaluate_gate(membership):
    """Return None when every rung passes, otherwise the blocked_reason."""
    if membership is None:
        return "MEMBERSHIP_NOT_ACTIVE"

    # rung 1
    if membership["status"] != "ACTIVE":
        return "MEMBERSHIP_NOT_ACTIVE"

    # rung 2
    child = db.children.get(membership["child_id"])
    if child is None or not calc.immunization_complete_for_age(child):
        return "IMMUNIZATION_INCOMPLETE"

    # rung 3 — both bounds inclusive
    today = db.today()
    earliest = add_days(today, -C.FORM_WELL_VISIT_RECENCY_DAYS)
    for visit in db.well_visits.values():
        if visit["membership_id"] != membership["id"]:
            continue
        if visit["status"] != "COMPLETED":
            continue
        completed = visit["completed_date"]
        if completed is not None and earliest <= completed <= today:
            return None
    return "WELL_VISIT_STALE"
