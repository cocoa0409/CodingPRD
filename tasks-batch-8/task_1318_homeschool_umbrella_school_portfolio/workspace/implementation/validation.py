"""Request body field validators (pipeline step 5: ERR_INVALID_REQUEST)."""
import math
from datetime import datetime

from errors import raise_err

ROLES = {"Parent", "Reviewer", "Registrar", "AcademicDirector", "StateAuditor", "System"}

CORE_SUBJECTS = ["READING", "WRITING", "MATH", "SCIENCE", "SOCIAL_STUDIES"]
CREDIT_SUBJECTS = [
    "ENGLISH", "MATH", "SCIENCE", "SOCIAL_STUDIES",
    "FOREIGN_LANGUAGE", "FINE_ARTS", "PHYS_ED", "ELECTIVE",
]
LETTER_GRADES = ["A", "B", "C", "D", "F"]
MEETING_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
EVALUATION_OUTCOMES = ["ACCEPTED", "REMEDIATION_REQUIRED", "REJECTED"]
STANDINGS = ["GOOD_STANDING", "PROBATION", "NONCOMPLIANT"]
ATTENDANCE_OUTCOMES = ["ATTENDED", "NO_SHOW", "EXCUSED"]
PLAN_REVIEW_DECISIONS = ["APPROVE", "REQUEST_REVISION"]
CREDIT_VERIFY_DECISIONS = ["APPROVE", "REJECT"]
GRAD_DECISIONS = ["APPROVE", "DENY"]


def _bad(msg):
    raise_err("ERR_INVALID_REQUEST", msg)


def get_body():
    from flask import request
    if not request.is_json:
        return {}
    try:
        body = request.get_json(silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        _bad("Request body must be a JSON object")
    return body


def req_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        _bad(f"{field} is required and must be a non-empty string")
    return v


def opt_string(body, field, default=None):
    v = body.get(field, default)
    if v is None:
        return None
    if not isinstance(v, str):
        _bad(f"{field} must be a string")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        _bad(f"{field} is required and must be a boolean")
    return v


def opt_bool(body, field, default=None):
    v = body.get(field, default)
    if v is None:
        return default
    if not isinstance(v, bool):
        _bad(f"{field} must be a boolean")
    return v


def req_int(body, field, lo=None, hi=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(f"{field} is required and must be an integer")
    if lo is not None and v < lo:
        _bad(f"{field} must be >= {lo}")
    if hi is not None and v > hi:
        _bad(f"{field} must be <= {hi}")
    return v


def opt_int(body, field, default=None, lo=None, hi=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, lo=lo, hi=hi)


def req_enum(body, field, choices):
    v = body.get(field)
    if not isinstance(v, str) or v not in choices:
        _bad(f"{field} must be one of {choices}")
    return v


def req_date(body, field):
    v = req_string(body, field)
    _check_date(v, field)
    return v


def _check_date(v, field):
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except (ValueError, TypeError):
        _bad(f"{field} must be an ISO YYYY-MM-DD date")


def req_datetime(body, field):
    import clock
    v = req_string(body, field)
    try:
        clock.parse(v)
    except Exception:
        _bad(f"{field} must be an ISO8601 datetime")
    return v


def req_int_list(body, field, lo=None, hi=None, nonempty=True):
    v = body.get(field)
    if not isinstance(v, list) or (nonempty and len(v) == 0):
        _bad(f"{field} must be a non-empty array of integers")
    for item in v:
        if isinstance(item, bool) or not isinstance(item, int):
            _bad(f"{field} must contain integers only")
        if lo is not None and item < lo:
            _bad(f"{field} entries must be >= {lo}")
        if hi is not None and item > hi:
            _bad(f"{field} entries must be <= {hi}")
    return v


def opt_int_list(body, field, default=None, lo=None, hi=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int_list(body, field, lo=lo, hi=hi)


def req_subject_list(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        _bad(f"{field} must be an array of subject strings")
    for item in v:
        if not isinstance(item, str):
            _bad(f"{field} must contain strings only")
    return v


def req_subject_scores(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        _bad(f"{field} must be an array of {{subject, score}} entries")
    seen = set()
    for item in v:
        if not isinstance(item, dict):
            _bad(f"{field} entries must be objects")
        subj = item.get("subject")
        score = item.get("score")
        if not isinstance(subj, str) or subj not in CORE_SUBJECTS:
            _bad(f"{field} subject must be one of {CORE_SUBJECTS}")
        if isinstance(score, bool) or not isinstance(score, int) or not (0 <= score <= 4):
            _bad(f"{field} score must be an integer 0..4")
        if subj in seen:
            _bad(f"{field} subject {subj} appears more than once")
        seen.add(subj)
    if seen != set(CORE_SUBJECTS):
        _bad(f"{field} must carry one score per core subject {CORE_SUBJECTS}")
    return v


def check_core_subjects(subjects):
    """Business rule (priority 10): all five core subjects must be present."""
    if not set(CORE_SUBJECTS).issubset(set(subjects)):
        raise_err(
            "ERR_PLAN_MISSING_CORE_SUBJECT",
            "subjects must include READING, WRITING, MATH, SCIENCE, SOCIAL_STUDIES",
        )


def check_no_nan(v, field):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        _bad(f"{field} must be a finite number")
