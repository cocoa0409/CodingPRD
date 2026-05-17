"""Segregation-of-duties tracking (§2.1 closing paragraph)."""

import db


def record_loan_request(user_id: str, plan_id: str, loan_id: str, participant_id: str) -> None:
    db.sod_audit.append({
        "action": "loan_request",
        "user_id": user_id,
        "plan_id": plan_id,
        "loan_id": loan_id,
        "participant_id": participant_id,
    })


def has_user_requested_loan(user_id: str, plan_id: str, loan_id: str) -> bool:
    for e in db.sod_audit:
        if e["action"] == "loan_request" and e["user_id"] == user_id and \
           e["plan_id"] == plan_id and e["loan_id"] == loan_id:
            return True
    return False


def record_hardship_request(user_id: str, plan_id: str, hardship_id: str, participant_id: str) -> None:
    db.sod_audit.append({
        "action": "hardship_request",
        "user_id": user_id,
        "plan_id": plan_id,
        "hardship_id": hardship_id,
        "participant_id": participant_id,
    })


def has_user_requested_hardship(user_id: str, plan_id: str, hardship_id: str) -> bool:
    for e in db.sod_audit:
        if e["action"] == "hardship_request" and e["user_id"] == user_id and \
           e["plan_id"] == plan_id and e["hardship_id"] == hardship_id:
            return True
    return False


def record_contribution_post(user_id: str, plan_id: str, participant_id: str, plan_year: int) -> None:
    db.sod_audit.append({
        "action": "contribution_post",
        "user_id": user_id,
        "plan_id": plan_id,
        "participant_id": participant_id,
        "plan_year": plan_year,
    })


def has_user_posted_contribution(user_id: str, plan_id: str, plan_year: int) -> bool:
    """True iff user_id posted any ContributionRecord under plan_id in the given plan_year."""
    for e in db.sod_audit:
        if e["action"] == "contribution_post" and e["user_id"] == user_id and \
           e["plan_id"] == plan_id and int(e.get("plan_year", -1)) == int(plan_year):
            return True
    return False
