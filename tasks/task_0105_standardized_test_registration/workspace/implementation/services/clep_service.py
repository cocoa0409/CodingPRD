"""CLEP credit award posting."""

import db
from config import ACE_RECOMMENDED_SCORE_BY_SUBJECT, CLEP_CREDIT_UNITS_BY_SUBJECT
from errors import (
    err_clep_award_already_posted,
    err_clep_invalid_context,
    err_clep_subject_unrecognized,
    err_score_report_not_found,
)
from services.registration_service import get_scoped_registration_or_404
from services.score_report_service import get_score_report_or_404
from services.test_event_service import get_test_event_or_404


def post_clep_credit(
    test_event_id: str,
    registration_id: str,
    score_report_id: str,
    caller_user_id: str,
) -> dict:
    e = get_test_event_or_404(test_event_id)
    r = get_scoped_registration_or_404(test_event_id, registration_id)
    s = get_score_report_or_404(score_report_id)
    if s["registration_id"] != registration_id:
        raise err_score_report_not_found()

    # Uniqueness check first (operational state — already posted)
    for existing in db.clep_credit_awards.all():
        if existing["score_report_id"] == score_report_id:
            raise err_clep_award_already_posted()

    if e["test_type"] != "CLEP":
        raise err_clep_invalid_context()
    subject = e.get("subject")
    if subject not in ACE_RECOMMENDED_SCORE_BY_SUBJECT:
        raise err_clep_subject_unrecognized()

    recommended = ACE_RECOMMENDED_SCORE_BY_SUBJECT[subject]
    if s["total_score"] >= recommended:
        credit_status = "AWARDED"
        credit_units = CLEP_CREDIT_UNITS_BY_SUBJECT[subject]
    else:
        credit_status = "DENIED"
        credit_units = 0

    award = db.append_create()
    award.update(
        {
            "score_report_id": score_report_id,
            "candidate_id": r["candidate_id"],
            "credit_status": credit_status,
            "credit_units": credit_units,
            "posted_by_user_id": caller_user_id,
        }
    )
    db.clep_credit_awards.insert(award)
    return award


def list_clep_credit_awards(candidate_id: str):
    items = [a for a in db.clep_credit_awards.all() if a["candidate_id"] == candidate_id]
    items.sort(key=lambda a: a["created_at"])
    return items
