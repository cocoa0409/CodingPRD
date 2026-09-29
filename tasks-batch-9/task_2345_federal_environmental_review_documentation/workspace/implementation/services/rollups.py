"""Derived-field reconciliation for every aggregate in the system."""

from decimal import Decimal

import db
from services import calc


def refresh_action(action):
    """Recompute every ProposedAction rollup from the underlying rows."""
    action_id = action["id"]
    issues = [i for i in db.db["issues"].values() if i["action_id"] == action_id]
    analyses = [a for a in db.db["analyses"].values() if a["action_id"] == action_id]
    finals = [a for a in analyses if a["status"] == "FINAL"]
    final_areas = {a["resource_area"] for a in finals}

    action["significant_issue_count"] = sum(
        1
        for i in issues
        if i["significance"] == "SIGNIFICANT" and i["status"] in ("OPEN", "ANALYZED")
    )
    action["unaddressed_issue_count"] = sum(
        1
        for i in issues
        if i["significance"] == "SIGNIFICANT"
        and i["status"] == "OPEN"
        and i["resource_area"] not in final_areas
    )
    action["alternatives_screened_in_count"] = sum(
        1
        for alt in db.db["alternatives"].values()
        if alt["action_id"] == action_id and alt["screening_status"] == "SCREENED_IN"
    )
    action["finalized_analysis_count"] = len(finals)
    if finals:
        action["max_unmitigated_score"] = float(
            max(calc.D(a["unmitigated_score"]) for a in finals)
        )
        total = sum((calc.D(a["cumulative_effect_score"]) for a in finals), Decimal("0"))
        action["cumulative_intensity_index"] = calc.r2(total / calc.D(len(finals)))
    else:
        action["max_unmitigated_score"] = 0.0
        action["cumulative_intensity_index"] = 0.0
    action["record_entry_count"] = sum(
        1 for e in db.db["record_entries"].values() if e["action_id"] == action_id
    )
    db.touch(action)


def refresh_document(document):
    """Recompute the four comment counters of a NepaDocument."""
    comments = [
        c
        for c in db.db["comments"].values()
        if c["document_id"] == document["id"] and c["is_substantive"]
    ]
    substantive = [c for c in comments if c["disposition"] in ("RECEIVED", "RESPONDED")]
    responded = [c for c in comments if c["disposition"] == "RESPONDED"]
    document["substantive_comment_count"] = len(substantive)
    document["responded_substantive_count"] = len(responded)
    document["unresolved_substantive_count"] = len(substantive) - len(responded)
    if not substantive:
        document["response_completeness_pct"] = 100.0
    else:
        document["response_completeness_pct"] = calc.r2(
            Decimal("100.0") * calc.D(len(responded)) / calc.D(len(substantive))
        )
    db.touch(document)


def refresh_agency(agency):
    agency["active_consultation_count"] = sum(
        1
        for c in db.db["consultations"].values()
        if c["agency_id"] == agency["id"] and c["status"] == "PENDING"
    )
    db.touch(agency)


def refresh_decision_objection_count(decision):
    decision["objection_count"] = sum(
        1
        for o in db.db["objections"].values()
        if o["decision_id"] == decision["id"] and o["status"] in ("FILED", "REMANDED", "DENIED")
    )
    db.touch(decision)


def office_of_action(action):
    return db.find("offices", action["office_id"])


def action_of(row):
    return db.find("actions", row["action_id"])
