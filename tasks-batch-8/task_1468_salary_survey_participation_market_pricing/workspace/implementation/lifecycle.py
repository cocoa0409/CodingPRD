"""Cascading lifecycle helpers (PRD §2.11) and the logical-clock sweep."""
from common import current_date, db, emit_audit, parse_date, touch


def _survey_submissions(survey_id):
    return [s for s in db["submissions"].values() if s["survey_id"] == survey_id]


def close_survey(survey):
    """OPEN -> CLOSED -> (SUBMITTED | REJECTED), returning unfinished packages."""
    for sub in _survey_submissions(survey["id"]):
        if sub["status"] in ("DRAFT", "READY"):
            sub["status"] = "RETURNED"
            sub["rejection_reason"] = "SURVEY_CLOSED"
            touch(sub)
    has_submitted = any(s["status"] == "SUBMITTED" for s in _survey_submissions(survey["id"]))
    survey["status"] = "SUBMITTED" if has_submitted else "REJECTED"
    touch(survey)


def reject_surveys_for_vendor(vendor, reason):
    """Reject not-yet-final surveys of a vendor and return their packages."""
    for s in db["surveys"].values():
        if s["vendor_id"] == vendor["id"] and s["status"] in ("DRAFT", "OPEN"):
            s["status"] = "REJECTED"
            touch(s)
            for sub in _survey_submissions(s["id"]):
                if sub["status"] in ("DRAFT", "READY"):
                    sub["status"] = "RETURNED"
                    sub["rejection_reason"] = reason
                    touch(sub)


def tick():
    """Automatic system transitions evaluated against the logical clock.

    - Vendor expiry: ACTIVE vendor whose contract_end_date has been reached.
    - Survey auto-close: OPEN survey the day after its submission_deadline.
    """
    d = current_date()
    for v in list(db["vendors"].values()):
        if v["status"] == "ACTIVE" and d >= parse_date(v["contract_end_date"]):
            v["status"] = "EXPIRED"
            touch(v)
            reject_surveys_for_vendor(v, "VENDOR_TERMINATED")
            emit_audit(v["org_id"], None, "VENDOR_EXPIRE", "SurveyVendor", v["id"],
                       {"status": "EXPIRED"})
    for s in list(db["surveys"].values()):
        if s["status"] == "OPEN" and d > parse_date(s["submission_deadline"]):
            close_survey(s)
