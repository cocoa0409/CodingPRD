"""Entity creation, defaults, computed fields, immutability, listing, and RBAC.

Covers exam creation/validation, accommodation defaults, the computed identity
result, the append-only IdentityVerification record, list pagination, and the
forbidden / unauthenticated access paths.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    api_client,
    NON_EXISTENT_UUID,
    make_candidate_headers,
    assert_exam,
    assert_accommodation,
    assert_identity_verification,
    setup_catalog,
    create_institution,
    create_candidate,
    create_appointment,
    create_exam,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def test_create_exam_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly created exam opens with `status` `OPEN`". PRD §2.4: "a
    `version` integer that starts at 1". PRD §3.1: "An optional `lockdown_required` flag
    defaults to true".

    Design: Corner/entities/create_exam_returns_201_with_all_fields
    """
    inst = create_institution()
    res = api.create_exam(
        {"institution_id": inst["id"], "title": "Math 101", "base_duration_minutes": 120,
         "window_start_utc": "2026-07-01T09:00:00Z", "window_end_utc": "2026-07-01T17:00:00Z",
         "monitoring_mode": "LIVE"}, COORD)
    exam = validate_success(res, 201)
    assert_exam(exam)
    assert exam["status"] == "OPEN"
    assert exam["version"] == 1
    assert exam["lockdown_required"] is True, "lockdown_required defaults to true"


def test_create_exam_missing_base_duration_rejected(api):
    """PRD §2.11: "A malformed body, a missing required field, or an out-of-range enum
    or numeric value is rejected with `ERR_VALIDATION`." PRD §3.1: "A coordinator creates
    an `Exam` under an `institution_id` with a `title`, a `base_duration_minutes` of at
    least 1".

    Design: Corner/entities/create_exam_missing_required_field_rejected
    """
    inst = create_institution()
    res = api.create_exam(
        {"institution_id": inst["id"], "title": "No Dur",
         "window_start_utc": "2026-07-01T09:00:00Z", "window_end_utc": "2026-07-01T17:00:00Z",
         "monitoring_mode": "LIVE"}, COORD)
    validate_error(res, "ERR_VALIDATION")


def test_create_exam_invalid_monitoring_mode_rejected(api):
    """PRD §2.11: "A malformed body, a missing required field, or an out-of-range enum
    or numeric value is rejected with `ERR_VALIDATION`." PRD §3.1: "a `monitoring_mode`
    of `LIVE` or `RECORD_REVIEW`".

    Design: Corner/entities/create_exam_invalid_monitoring_mode_enum_rejected
    """
    inst = create_institution()
    res = api.create_exam(
        {"institution_id": inst["id"], "title": "Bad Mode", "base_duration_minutes": 60,
         "window_start_utc": "2026-07-01T09:00:00Z", "window_end_utc": "2026-07-01T17:00:00Z",
         "monitoring_mode": "HYBRID"}, COORD)
    validate_error(res, "ERR_VALIDATION")


def test_accommodation_extra_time_defaults_to_zero(api):
    """PRD §3.1: "an optional `extra_time_pct` (an extra-time percentage added to the
    base duration, defaulting to 0 and constrained between 0 and 100 inclusive). An
    accommodation opens `APPROVED`".

    Design: Corner/entities/accommodation_extra_time_default_zero_applied
    """
    inst = create_institution()
    cand = create_candidate(inst["id"])
    exam = create_exam(inst["id"], lockdown_required=False)
    res = api.create_accommodation(
        {"candidate_id": cand["id"], "exam_id": exam["id"]}, COORD)
    acc = validate_success(res, 201)
    assert_accommodation(acc)
    assert acc["extra_time_pct"] == 0, "extra_time_pct defaults to 0"
    assert acc["status"] == "APPROVED"


def test_identity_verification_result_computed_pass(api):
    """PRD §3.3: "the result is `PASS` when both `photo_id_match` and `room_scan_clear`
    are true, and `FAIL` otherwise".

    Design: Corner/entities/identity_verification_result_computed_pass
    """
    cat = setup_catalog(monitoring_mode="LIVE", lockdown_required=True)
    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"],
                              cat["proctor"]["id"], "2026-07-01T09:00:00Z")
    res = api.verify_identity(
        appt["id"], {"photo_id_match": True, "room_scan_clear": True},
        make_candidate_headers(cat["candidate"]["id"]))
    idv = validate_success(res, 201)
    assert idv["result"] == "PASS"


def test_get_proctor_not_found_returns_404(api):
    """PRD §2.5: "The first identifier that does not resolve to an existing resource
    causes the request to fail immediately with `ERR_NOT_FOUND`".

    Design: Corner/entities/get_proctor_not_found_returns_404
    """
    res = api.get_proctor(NON_EXISTENT_UUID, COORD)
    validate_error(res, "ERR_NOT_FOUND")


def test_identity_verification_record_has_no_version_field(api):
    """PRD §2.4: "An `IdentityVerification` and an `IncidentFlag` each carry only an `id`
    and a `created_at`; neither has an `updated_at` and neither has a `version`, because
    once written they are never mutated in place."

    Design: Corner/entities/identity_verification_immutable_no_version_field
    """
    cat = setup_catalog(monitoring_mode="LIVE", lockdown_required=True)
    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"],
                              cat["proctor"]["id"], "2026-07-01T09:00:00Z")
    validate_success(api.verify_identity(
        appt["id"], {"photo_id_match": True, "room_scan_clear": True},
        make_candidate_headers(cat["candidate"]["id"])), 201)

    listed, _ = validate_paginated(
        api.list_identity_verifications(appt["id"], COORD))
    assert len(listed) >= 1
    record = listed[0]
    assert_identity_verification(record)
    assert "version" not in record, "IdentityVerification must not expose a version field"
    assert "updated_at" not in record, "IdentityVerification must not expose updated_at"


def test_list_exams_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned". PRD §2.3:
    "Every list-based response includes the following fields inside the `meta` object of
    the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_exams_pagination_envelope
    """
    inst = create_institution()
    create_exam(inst["id"], title="Ex 1", lockdown_required=False)
    create_exam(inst["id"], title="Ex 2", lockdown_required=False)
    data, meta = validate_paginated(
        api.list_exams(COORD, params={"institution_id": inst["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_candidate_cannot_create_exam_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted
    to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/candidate_cannot_create_exam
    """
    inst = create_institution()
    cand = create_candidate(inst["id"])
    res = api.create_exam(
        {"institution_id": inst["id"], "title": "Sneaky", "base_duration_minutes": 60,
         "window_start_utc": "2026-07-01T09:00:00Z", "window_end_utc": "2026-07-01T17:00:00Z",
         "monitoring_mode": "LIVE"},
        make_candidate_headers(cand["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_missing_headers_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` carries a value that is
    not one of these four recognized roles, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    res = api.list_exams({})
    validate_error(res, "ERR_UNAUTHENTICATED")
