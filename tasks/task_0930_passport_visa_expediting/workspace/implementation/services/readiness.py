"""Applicant readiness and the order's INTAKE <-> READY_FOR_SUBMISSION gate
(PRD 3.7, 3.9)."""
import store
from constants import STAGE_RANK
from services import lookup, projection


def is_complete(applicant):
    """All four conditions of PRD 3.7."""
    order = lookup.order_of_applicant(applicant)
    if order is None:
        return False
    catalog = lookup.catalog_of(order)

    for doc in lookup.documents_of(applicant):
        if doc["is_required"] and doc["review_status"] != "ACCEPTED":
            return False

    passed = [p for p in lookup.photos_of(applicant) if p["compliance_status"] == "PASSED"]
    if len(passed) != 1:
        return False

    active = lookup.active_form(catalog["form_code"]) if catalog else None
    if active is None:
        return False
    live_forms = [
        f for f in lookup.prepared_forms_of(applicant)
        if f["prep_status"] in ("PREPARED", "SIGNED") and f["revision_used"] == active["revision"]
    ]
    if len(live_forms) != 1:
        return False

    if catalog and catalog.get("requires_appointment"):
        attended = [
            a for a in lookup.appointments_of(applicant) if a["booking_status"] == "ATTENDED"
        ]
        if not attended:
            return False
    return True


def recompute_accepted_doc_count(applicant):
    required_types = {
        d["doc_type"] for d in lookup.documents_of(applicant) if d["is_required"]
    }
    count = len([
        d for d in lookup.documents_of(applicant)
        if d["doc_type"] in required_types and d["review_status"] == "ACCEPTED"
    ])
    changed = applicant["accepted_doc_count"] != count
    applicant["accepted_doc_count"] = count
    return changed


def recompute_readiness(applicant, bump=True):
    """Returns True when a persisted value on the applicant actually changed."""
    if applicant["readiness_status"] == "WITHDRAWN":
        return False
    count_changed = recompute_accepted_doc_count(applicant)
    target = "COMPLETE" if is_complete(applicant) else "PENDING"
    status_changed = applicant["readiness_status"] != target
    applicant["readiness_status"] = target
    changed = count_changed or status_changed
    if changed and bump:
        store.touch(applicant)
    return changed


def raise_stage(order, stage):
    if STAGE_RANK[stage] > STAGE_RANK.get(order["furthest_stage_reached"], -1):
        order["furthest_stage_reached"] = stage


def cancel_created_legs(order):
    """Hop 5 of the publish cascade / the RFS -> INTAKE regression."""
    for leg in lookup.legs_of(order):
        if leg["leg_status"] == "CREATED":
            leg["leg_status"] = "CANCELLED"
            store.touch(leg)


def reevaluate_gate(order, bump=True):
    """Runs the system transition in whichever direction applies.
    Returns True when workflow_status actually moved."""
    counted = lookup.counted_applicants(order)
    all_complete = all(a["readiness_status"] == "COMPLETE" for a in counted)

    if order["workflow_status"] == "INTAKE":
        if all_complete and order["custody_holder"] == "SERVICE":
            order["workflow_status"] = "READY_FOR_SUBMISSION"
            raise_stage(order, "READY_FOR_SUBMISSION")
            projection.run_projection_and_feasibility(order)
            if bump:
                store.touch(order)
            return True
        return False

    if order["workflow_status"] == "READY_FOR_SUBMISSION":
        if (not all_complete) or order["custody_holder"] != "SERVICE":
            order["workflow_status"] = "INTAKE"
            cancel_created_legs(order)
            order["feasibility_status"] = "UNKNOWN"
            order["acknowledged_by_user_id"] = None
            if bump:
                store.touch(order)
            return True
        return False

    return False
