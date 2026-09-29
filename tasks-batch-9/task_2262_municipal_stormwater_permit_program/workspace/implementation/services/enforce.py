"""Issuing an enforcement action, shared by the officer route and the
inspection-finalize cascade."""

import enums
from db import DB, CLOCK, new_row, touch
from services import calc, derive

SYSTEM_USER_ID = "system"


def prior_total(subject_key, subject_id, exclude_id=None):
    """Penalties already assessed against the same subject, excluding one row."""
    total = 0
    for action in DB.enforcement_actions.values():
        if action.get(subject_key) != subject_id:
            continue
        if exclude_id is not None and action["id"] == exclude_id:
            continue
        if action["status"] not in enums.ENFORCEMENT_ASSESSED:
            continue
        total += int(action.get("penalty_cents") or 0)
    return total


SUBJECT_KINDS = {
    "illicit_discharge_case_id": "ILLICIT_DISCHARGE_CASE",
    "construction_site_id": "CONSTRUCTION_SITE",
    "post_construction_facility_id": "POST_CONSTRUCTION_FACILITY",
}


def issue(
    action_type,
    subject_key,
    subject_id,
    violation_days=0,
    source_inspection_id=None,
    user_id=SYSTEM_USER_ID,
    auto_generated=False,
):
    prior = prior_total(subject_key, subject_id)
    billable, prior_total_cents, multiplier, amount = calc.penalty(
        action_type, violation_days, prior
    )
    fields = {
        "action_type": action_type,
        "illicit_discharge_case_id": None,
        "construction_site_id": None,
        "post_construction_facility_id": None,
        "source_inspection_id": source_inspection_id,
        "subject_kind": SUBJECT_KINDS[subject_key],
        "violation_days": int(violation_days or 0),
        "billable_violation_days": billable,
        "prior_assessed_total_cents": prior_total_cents,
        "escalation_multiplier": float(multiplier),
        "penalty_cents": amount,
        "status": "ISSUED",
        "issued_at": CLOCK.stamp(),
        "issued_by_user_id": user_id,
        "last_escalated_at": None,
        "escalation_count": 0,
        "auto_generated": auto_generated,
        "compliance_note": None,
        "closed_at": None,
        "rescinded_reason": None,
        "rescinded_at": None,
    }
    fields[subject_key] = subject_id
    row = new_row(fields)
    DB.enforcement_actions[row["id"]] = row

    if subject_key == "illicit_discharge_case_id":
        case = DB.cases.get(subject_id)
        if case is not None and case["status"] == "SOURCE_IDENTIFIED":
            case["status"] = "ENFORCEMENT"
            touch(case)
    return row


def term_of(subject_key, subject_id):
    if subject_key == "illicit_discharge_case_id":
        case = DB.cases.get(subject_id)
        return derive.term_of_case(case) if case else None
    if subject_key == "construction_site_id":
        site = DB.sites.get(subject_id)
        return derive.term_of_site(site) if site else None
    facility = DB.facilities.get(subject_id)
    return derive.term_of_facility(facility) if facility else None
