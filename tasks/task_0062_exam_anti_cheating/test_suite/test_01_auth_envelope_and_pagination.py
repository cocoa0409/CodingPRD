"""Authentication, RBAC, response envelope, and pagination.

Covers PRD §2.1 (headers + RBAC), §2.2 (envelope), §2.3 (pagination).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    build_user_headers,
    create_exam_payload,
    create_objective_question_payload,
    exam_ready_for_candidates,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth headers
# ===========================================================================
def test_missing_user_id_header_rejected(api):
    """PRD §2.1: "If either header is missing or empty, the server
    rejects the request with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

    Claim: omitting X-User-ID → ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
    """
    res = api.create_exam(
        create_exam_payload(),
        headers={"X-User-Role": "ExamAdmin"},
    )
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


def test_missing_user_role_header_rejected(api):
    """PRD §2.1: "If either header is missing or empty, the server
    rejects the request with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."
    """
    res = api.create_exam(
        create_exam_payload(),
        headers={"X-User-ID": "exam-admin-001"},
    )
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


def test_empty_user_id_header_rejected(api):
    """PRD §2.1: "If either header is missing or empty ..."
    """
    res = api.create_exam(
        create_exam_payload(),
        headers={"X-User-ID": "", "X-User-Role": "ExamAdmin"},
    )
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


def test_empty_user_role_header_rejected(api):
    """PRD §2.1: "If either header is missing or empty ..."
    """
    res = api.create_exam(
        create_exam_payload(),
        headers={"X-User-ID": "exam-admin-001", "X-User-Role": ""},
    )
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


# ===========================================================================
# RBAC matrix (PRD §2.1 + §4)
# ===========================================================================
def test_proctor_cannot_create_exam(api, proctor_headers):
    """PRD §4: POST /exams is authorized for ExamAdmin only. PRD §2.1:
    "When the role is recognised but lacks permission for the requested
    operation under the RBAC matrix, the server returns
    ERR_INSUFFICIENT_PERMISSIONS."
    """
    res = api.create_exam(create_exam_payload(), proctor_headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_candidate_cannot_create_exam(api, candidate_fallback_headers):
    """PRD §4: POST /exams is authorized for ExamAdmin only."""
    res = api.create_exam(create_exam_payload(), candidate_fallback_headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_proctor_cannot_open_registration(api, proctor_headers,
                                          exam_admin_headers):
    """PRD §4: POST /exams/{examId}/open-registration is ExamAdmin only."""
    exam = validate_success(
        api.create_exam(create_exam_payload(), exam_admin_headers), 201,
    )
    res = api.open_registration(exam["id"], proctor_headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_marker_cannot_record_abnormal_event(api, marker_headers,
                                             exam_admin_headers):
    """PRD §4: POST /exams/{examId}/attempts/{attemptId}/abnormal-events
    is Proctor only."""
    # Need a real-looking but non-existent attempt id to hit the auth
    # check before the existence check; since auth precedes existence
    # (PRD §2.7), the role failure surfaces regardless.
    res = api.record_abnormal_event(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID,
        {"detected_at": 1000, "monitoring_channel": "SCREEN",
         "behavior_rule_code": "MULTI_PERSON",
         "marking_mode": "REALTIME_ALERT",
         "evidence_clip_uri": "s3://e"},
        marker_headers,
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_candidate_cannot_read_audit_log(api, candidate_fallback_headers):
    """PRD §2.9: "The audit log is readable only by an ExamAdmin."
    """
    res = api.list_audit_log(candidate_fallback_headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_proctor_cannot_read_audit_log(api, proctor_headers):
    """PRD §2.9: "The audit log is readable only by an ExamAdmin."
    """
    res = api.list_audit_log(proctor_headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


# ===========================================================================
# Response envelope (PRD §2.2)
# ===========================================================================
def test_success_envelope_shape(api, exam_admin_headers):
    """PRD §2.2: success responses carry meta.api_request_id (starts
    with req_), meta.api_request_timestamp (ISO 8601), response_type,
    and data."""
    res = api.create_exam(create_exam_payload(), exam_admin_headers)
    assert res.status_code == 201
    body = res.json()
    assert "meta" in body
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in meta
    assert body["response_type"] in {"object", "array"}
    assert "data" in body


def test_error_envelope_shape(api):
    """PRD §2.2: error responses carry response_type='error' and
    data.error_id + data.message."""
    res = api.create_exam(create_exam_payload(), headers={})
    assert res.status_code == 400
    body = res.json()
    assert body["response_type"] == "error"
    assert "error_id" in body["data"]
    assert "message" in body["data"]


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
def test_list_exams_pagination_meta(api, exam_admin_headers):
    """PRD §2.3: "Each list response surfaces, inside its meta envelope,
    the four pagination fields limit, offset, total_count, and has_more."
    """
    for _ in range(3):
        api.create_exam(create_exam_payload(), exam_admin_headers)
    res = api.list_exams(exam_admin_headers)
    data, meta = validate_paginated(res)
    assert "limit" in meta and "offset" in meta
    assert "total_count" in meta and "has_more" in meta
    assert isinstance(meta["total_count"], int)
    assert meta["total_count"] >= 3


def test_list_exams_default_limit_is_10(api, exam_admin_headers):
    """PRD §2.3: "The default limit is 10."
    """
    res = api.list_exams(exam_admin_headers)
    _, meta = validate_paginated(res)
    assert meta["limit"] == 10


@pytest.mark.parametrize("bad_limit", [0, -1, 101, 1000])
def test_list_exams_limit_out_of_range_rejected(api, exam_admin_headers,
                                                bad_limit):
    """PRD §2.3: "A request whose limit falls outside the range from 1
    to 100 inclusive ... is rejected with
    ERR_INVALID_PAGINATION_PARAMETERS."
    """
    res = api.list_exams(exam_admin_headers, params={"limit": bad_limit})
    validate_error(res, "ERR_INVALID_PAGINATION_PARAMETERS")


def test_list_exams_negative_offset_rejected(api, exam_admin_headers):
    """PRD §2.3: "whose offset is below 0, is rejected with
    ERR_INVALID_PAGINATION_PARAMETERS."
    """
    res = api.list_exams(exam_admin_headers, params={"offset": -1})
    validate_error(res, "ERR_INVALID_PAGINATION_PARAMETERS")


def test_list_exams_limit_boundary_low(api, exam_admin_headers):
    """PRD §2.3: limit=1 is within the inclusive [1,100] range."""
    api.create_exam(create_exam_payload(), exam_admin_headers)
    res = api.list_exams(exam_admin_headers, params={"limit": 1})
    data, meta = validate_paginated(res)
    assert meta["limit"] == 1
    assert len(data) <= 1


def test_list_exams_limit_boundary_high(api, exam_admin_headers):
    """PRD §2.3: limit=100 is within the inclusive [1,100] range."""
    res = api.list_exams(exam_admin_headers, params={"limit": 100})
    data, meta = validate_paginated(res)
    assert meta["limit"] == 100


# ===========================================================================
# Nested path resolution (PRD §2.6)
# ===========================================================================
def test_nested_path_unknown_exam_id(api, exam_admin_headers):
    """PRD §2.6: "A request against an attempt-scoped path first
    verifies the parent exam exists (ERR_EXAM_NOT_FOUND)."
    """
    res = api.get_attempt(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID, exam_admin_headers,
    )
    validate_error(res, "ERR_EXAM_NOT_FOUND")


def test_nested_path_unknown_attempt_id(api, exam_admin_headers):
    """PRD §2.6: "then the attempt (ERR_ATTEMPT_NOT_FOUND), and only
    then evaluates business-state preconditions."
    """
    exam, _, _ = exam_ready_for_candidates(num_objective=1)
    res = api.get_attempt(
        exam["id"], NON_EXISTENT_UUID, exam_admin_headers,
    )
    validate_error(res, "ERR_ATTEMPT_NOT_FOUND")


def test_nested_path_unknown_question_id(api, exam_admin_headers):
    """PRD §2.6: "The same left-to-right walk applies for Question
    under Exam (ERR_QUESTION_NOT_FOUND)."
    """
    exam, _, _ = exam_ready_for_candidates(num_objective=1)
    res = api.get_question(
        exam["id"], NON_EXISTENT_UUID, exam_admin_headers,
    )
    validate_error(res, "ERR_QUESTION_NOT_FOUND")
