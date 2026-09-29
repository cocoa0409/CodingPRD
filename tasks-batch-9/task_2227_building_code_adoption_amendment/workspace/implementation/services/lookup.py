"""Record family -> 404 error id resolution (PRD 2.6)."""
import db
from errors import ApiError


def _get(store, record_id, error_id):
    if not isinstance(record_id, str):
        raise ApiError(error_id)
    record = store.get(record_id)
    if record is None:
        raise ApiError(error_id)
    return record


def code_cycle(record_id):
    return _get(db.code_cycles, record_id, "ERR_CODE_CYCLE_NOT_FOUND")


def committee(record_id):
    return _get(db.discipline_committees, record_id, "ERR_COMMITTEE_NOT_FOUND")


def member(record_id):
    return _get(db.committee_members, record_id, "ERR_COMMITTEE_MEMBER_NOT_FOUND")


def proposal(record_id):
    return _get(db.amendment_proposals, record_id, "ERR_PROPOSAL_NOT_FOUND")


def analysis(record_id):
    return _get(db.impact_analyses, record_id, "ERR_ANALYSIS_NOT_FOUND")


def comment(record_id):
    return _get(db.public_comments, record_id, "ERR_COMMENT_NOT_FOUND")


def hearing(record_id):
    return _get(db.hearings, record_id, "ERR_HEARING_NOT_FOUND")


def vote_record(record_id):
    return _get(db.vote_records, record_id, "ERR_VOTE_RECORD_NOT_FOUND")


def adoption_rule(record_id):
    return _get(db.adoption_rules, record_id, "ERR_ADOPTION_RULE_NOT_FOUND")


def jurisdiction(record_id):
    return _get(db.jurisdictions, record_id, "ERR_JURISDICTION_NOT_FOUND")


def local_amendment(record_id):
    return _get(db.local_amendments, record_id, "ERR_LOCAL_AMENDMENT_NOT_FOUND")


def interpretation_request(record_id):
    return _get(db.interpretation_requests, record_id, "ERR_INTERPRETATION_REQUEST_NOT_FOUND")


def training_session(record_id):
    return _get(db.training_sessions, record_id, "ERR_TRAINING_SESSION_NOT_FOUND")


def enrollment(record_id):
    return _get(db.training_enrollments, record_id, "ERR_ENROLLMENT_NOT_FOUND")
