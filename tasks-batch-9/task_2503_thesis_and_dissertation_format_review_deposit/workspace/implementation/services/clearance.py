"""The derived graduation-clearance projection (PRD section 3.9).

Nobody ever edits a GraduationClearance: status, outstanding_items,
projection_variant and cleared_at are rewritten from scratch by this projection.
"""

import lookup
from db import db, new_row, reconcile
from logical_clock import clock

ITEM_ORDER = [
    "COMMITTEE_APPROVAL",
    "DEFENSE_OUTCOME",
    "PERMISSIONS",
    "FORMAT_ACCEPTANCE",
    "EMBARGO_DECISION",
    "INTEGRITY",
    "DEPOSIT",
]


def latest_thesis_for_student(student_id):
    rows = lookup.theses_of_student(student_id)
    if not rows:
        return None
    return max(rows, key=lambda r: (r["created_at"], r["version"], r["_seq"]))


def variant_for_term(term):
    if term is None:
        return "PROVISIONAL"
    return "PROVISIONAL" if term["status"] == "OPEN" else "FINAL"


def evaluate(thesis, variant):
    """Return the outstanding_items list in the fixed emission order."""
    provisional = variant == "PROVISIONAL"
    thesis_id = thesis["id"]

    committee = lookup.committee_of_thesis(thesis_id)
    committee_ok = committee is not None and (
        committee["status"] == "APPROVED"
        or (provisional and committee["status"] == "SUBMITTED")
    )

    events = lookup.events_of_thesis(thesis_id)
    defense_ok = any(
        event["status"] in ("HELD_PASS", "HELD_PASS_WITH_REVISIONS") for event in events
    )
    if not defense_ok and provisional:
        defense_ok = any(event["status"] == "ANNOUNCED" for event in events)

    records = lookup.permissions_of_thesis(thesis_id)
    counted_statuses = ["ACCEPTED", "WAIVED"]
    if provisional:
        counted_statuses.append("SUBMITTED")
    documented = sum(1 for row in records if row["status"] in counted_statuses)
    permissions_ok = (
        thesis["third_party_item_count"] == 0
        or documented >= thesis["third_party_item_count"]
    )

    reviews = lookup.reviews_of_thesis(thesis_id)
    format_ok = any(row["status"] == "ACCEPTED" for row in reviews)
    if not format_ok and provisional:
        format_ok = any(row["status"] == "PENDING_REVIEW" for row in reviews)

    embargoes = lookup.embargoes_of_thesis(thesis_id)
    embargo_ok = not any(
        row["status"] in ("REQUESTED", "MORE_INFO_REQUIRED") for row in embargoes
    )

    integrity_ok = thesis["integrity_state"] in ("SCREEN_CLEARED", "INTEGRITY_CLEARED")
    if not integrity_ok and provisional:
        integrity_ok = thesis["integrity_state"] == "NOT_SCREENED"

    deposits = lookup.deposits_of_thesis(thesis_id)
    deposit_ok = any(row["status"] == "DEPOSITED" for row in deposits)

    satisfied = {
        "COMMITTEE_APPROVAL": committee_ok,
        "DEFENSE_OUTCOME": defense_ok,
        "PERMISSIONS": permissions_ok,
        "FORMAT_ACCEPTANCE": format_ok,
        "EMBARGO_DECISION": embargo_ok,
        "INTEGRITY": integrity_ok,
        "DEPOSIT": deposit_ok,
    }
    return [item for item in ITEM_ORDER if not satisfied[item]]


def status_for(thesis, outstanding):
    if thesis["integrity_state"] == "INTEGRITY_UPHELD" or thesis["workflow_state"] == "TERMINATED":
        return "WITHHELD"
    if thesis["workflow_state"] == "CONFERRED":
        return "CONFERRED"
    if not outstanding:
        return "CLEARED"
    if thesis["workflow_state"] in ("DRAFT", "COMMITTEE_PENDING"):
        return "BLOCKED"
    return "PENDING_ITEMS"


def ensure_clearance(student_id):
    existing = lookup.clearance_of_student(student_id)
    if existing is not None:
        return existing
    row = new_row(
        student_id=student_id,
        status="BLOCKED",
        outstanding_items=[],
        projection_variant="PROVISIONAL",
        cleared_at=None,
        conferral_posted_at=None,
        transcript_notation=None,
        withheld_reason=None,
    )
    db.graduation_clearances[row["id"]] = row
    return row


def recompute(student_id, variant=None):
    """Rewrite the candidate's clearance from the evidence and mirror the status."""
    clearance = lookup.clearance_of_student(student_id)
    if clearance is None:
        return None
    thesis = latest_thesis_for_student(student_id)
    if thesis is None:
        return clearance
    if variant is None:
        variant = variant_for_term(db.terms.get(thesis["term_id"]))

    outstanding = evaluate(thesis, variant)
    status = status_for(thesis, outstanding)

    if outstanding:
        cleared_at = None
    elif clearance["cleared_at"] is not None:
        cleared_at = clearance["cleared_at"]
    else:
        cleared_at = clock.now()

    reconcile(
        clearance,
        status=status,
        outstanding_items=outstanding,
        projection_variant=variant,
        cleared_at=cleared_at,
    )

    student = db.students.get(student_id)
    if student is not None:
        reconcile(student, graduation_clearance_state=clearance["status"])
    return clearance


def recompute_for_thesis(thesis, variant=None):
    return recompute(thesis["student_id"], variant=variant)
