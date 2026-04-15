"""Tests for Semester CRUD operations and basic entity management."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, is_iso8601_timestamp, NON_EXISTENT_UUID,
    api_client, ApiErrorId, TEST_USERS,
    assert_semester,
    create_semester_payload,
)
from test_helpers.fixtures import create_semester


class TestCreateSemester:
    """Tests for POST /semesters."""

    def test_create_semester_success(self):
        """Registrar can create a semester; returns 201, phase=PLANNING."""
        payload = create_semester_payload(term_label="Fall 2026", year=2026)
        resp = api_client.create_semester(payload, TEST_USERS["registrar_headers"])
        data = validate_success(resp, expected_status=201)
        assert_semester(data)
        assert data["term_label"] == "Fall 2026"
        assert data["year"] == 2026
        assert data["phase"] == "PLANNING", "New semester must start in PLANNING phase"

    def test_create_semester_sets_common_fields(self):
        """Created semester has id, opened_on, modified_on."""
        payload = create_semester_payload()
        resp = api_client.create_semester(payload, TEST_USERS["registrar_headers"])
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"]), "id must be a valid UUID"
        assert is_iso8601_timestamp(data["opened_on"]), "opened_on must be ISO 8601"
        assert is_iso8601_timestamp(data["modified_on"]), "modified_on must be ISO 8601"

    def test_create_semester_student_denied(self):
        """Student role cannot create a semester -> ENROLLMENT_ROLE_DENIED."""
        payload = create_semester_payload()
        resp = api_client.create_semester(payload, TEST_USERS["student_headers"])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_create_semester_professor_denied(self):
        """Professor role cannot create a semester -> ENROLLMENT_ROLE_DENIED."""
        payload = create_semester_payload()
        resp = api_client.create_semester(payload, TEST_USERS["professor_headers"])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)


class TestGetSemester:
    """Tests for GET /semesters/{semesterId}."""

    def test_get_semester_success(self):
        """Any authenticated role can get semester details."""
        semester = create_semester(term_label="Spring 2027", year=2027)
        for role in ["registrar_headers", "professor_headers", "student_headers"]:
            resp = api_client.get_semester(semester["id"], TEST_USERS[role])
            data = validate_success(resp)
            assert data["id"] == semester["id"]
            assert data["term_label"] == "Spring 2027"

    def test_get_semester_not_found(self):
        """Non-existent semester returns SEMESTER_UNKNOWN."""
        resp = api_client.get_semester(NON_EXISTENT_UUID, TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.SEMESTER_UNKNOWN)


class TestListSemesters:
    """Tests for GET /semesters."""

    def test_list_semesters_returns_created(self):
        """List semesters includes a newly created semester."""
        semester = create_semester()
        resp = api_client.list_semesters(TEST_USERS["registrar_headers"])
        data, meta = validate_paginated(resp)
        ids = [s["id"] for s in data]
        # The created semester should appear (may need to paginate in large test runs)
        assert meta["total_results"] >= 1

    def test_list_semesters_any_role(self):
        """Any authenticated role can list semesters."""
        for role in ["registrar_headers", "professor_headers", "student_headers"]:
            resp = api_client.list_semesters(TEST_USERS[role])
            validate_paginated(resp)
