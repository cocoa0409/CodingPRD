"""Entity creation semantics, computed defaults, not-found behavior,
pagination envelope, archival filtering, and the degree-progress default."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    fixtures,
)

ADMIN = TEST_USERS["admin_headers"]
EVALUATOR = TEST_USERS["evaluator_headers"]


class TestPartnerCreation:
    def test_partner_creation_returns_201_with_server_fields(self):
        """PRD §2.5: "Before any client sets it, the logical clock reads exactly
        `2026-05-01T00:00:00Z`; it never falls back to wall-clock time."
        PRD §2.4: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits recording when the resource was created."
        PRD §4: "Operations that create a new resource return `201 Created`".

        Design: Corner/entities/partner_creation_returns_201_with_server_fields
        """
        resp = api_client.create_partner_institution(
            {"name": "Plain College", "institution_code": "PL", "credit_system": "SEMESTER"},
            ADMIN,
        )
        created = validate_success(resp, expected_status=201)
        assert isinstance(created["version"], int) and created["version"] >= 1
        # created_at is stamped from the logical clock, fixed at its default.
        assert created["created_at"].startswith("2026-05-01T00:00:00")

        fetched = get_success_data(api_client.get_partner_institution(created["id"], ADMIN))
        assert fetched["name"] == "Plain College"
        assert fetched["credit_system"] == "SEMESTER"


class TestStudentSystemFields:
    def test_student_create_extra_system_fields_input_ignored(self):
        """PRD §2.4: "`id` (string): a server-minted unique identifier formatted
        as a UUID" and "`version` (integer): a system-managed integer that
        increments by one on every mutation" — both are system-managed, so
        client-injected values are not honored.

        Design: Corner/entities/student_create_extra_system_fields_input_ignored
        """
        injected_id = "00000000-0000-0000-0000-000000000000"
        resp = api_client.create_student(
            {
                "full_name": "Inject Ivy",
                "email": "ivy@x.edu",
                "declared_major": "MATH",
                "catalog_year": 2026,
                "id": injected_id,
                "version": 99,
            },
            ADMIN,
        )
        created = validate_success(resp, expected_status=201)
        assert created["id"] != injected_id, "server mints its own id"
        assert created["version"] != 99, "injected version ignored; version is system-managed"

        fetched = get_success_data(api_client.get_student(created["id"], ADMIN))
        assert fetched["id"] == created["id"]

    def test_student_computed_totals_default_zero(self):
        """PRD §3.4: "the student's two ledger totals —
        `total_posted_transfer_credits` and `total_posted_pla_credits` — are
        initialized to zero."

        Design: Corner/entities/student_computed_totals_default_zero
        """
        student = fixtures.create_student(major="HIST")
        assert student["total_posted_transfer_credits"] == 0
        assert student["total_posted_pla_credits"] == 0

        fetched = get_success_data(api_client.get_student(student["id"], ADMIN))
        assert fetched["total_posted_transfer_credits"] == 0
        assert fetched["total_posted_pla_credits"] == 0


class TestNotFound:
    def test_get_partner_institution_not_found_returns_404(self):
        """PRD §2.8: "fourth, existence of every path identifier and every body
        foreign key (`ERR_NOT_FOUND`)".

        Design: Corner/entities/get_partner_institution_not_found_returns_404
        """
        fixtures.create_partner(name="Plain College", code="PL")
        resp = api_client.get_partner_institution(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestListPagination:
    def test_list_partner_institutions_pagination_defaults(self):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10 ... The `offset` parameter ... defaults to 0. ... The
        `meta` object of a list response carries four pagination fields: `limit`,
        `offset`, `total_count`, and `has_more`."
        PRD §3.1: "The partner list endpoint accepts an optional `credit_system`
        filter."

        Design: Corner/entities/list_partner_institutions_pagination_defaults
        """
        fixtures.create_partner(name="Alpha College", code="AL", credit_system="SEMESTER")
        fixtures.create_partner(name="Beta College", code="BE", credit_system="QUARTER")
        fixtures.create_partner(name="Gamma College", code="GA", credit_system="SEMESTER")

        resp = api_client.list_partner_institutions(EVALUATOR)
        data, meta = validate_paginated(resp)
        assert len(data) == 3
        assert meta["total_count"] == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False

        resp = api_client.list_partner_institutions(EVALUATOR, params={"credit_system": "QUARTER"})
        filtered, filtered_meta = validate_paginated(resp)
        assert filtered_meta["total_count"] == 1
        assert len(filtered) == 1
        assert filtered[0]["credit_system"] == "QUARTER"


class TestArchivedCourseListing:
    def test_archived_course_hidden_from_default_list(self):
        """PRD §3.1: "The catalog list endpoint's archival filter semantics are
        explicit: with no `is_active` parameter only active courses are returned,
        and passing `is_active` as false lists the archived rows".
        PRD §3.1: "existing equivalencies and line items that already reference
        the course continue to resolve" — the archived record stays addressable.

        Design: Corner/cross_cutting_complexity_layers/archived_course_hidden_from_default_list
        """
        c1 = fixtures.create_course(code="MATH-150")
        c2 = fixtures.create_course(code="ENGL-150", title="Literature", credit_hours=3.0,
                                    department="ENGL")
        get_success_data(api_client.deactivate_internal_course(c1["id"], ADMIN))

        default_resp = api_client.list_internal_courses(ADMIN)
        default_list, _ = validate_paginated(default_resp)
        default_ids = {c["id"] for c in default_list}
        assert c2["id"] in default_ids
        assert c1["id"] not in default_ids, "default list excludes archived courses"

        archived_resp = api_client.list_internal_courses(ADMIN, params={"is_active": "false"})
        archived_list, _ = validate_paginated(archived_resp)
        archived_ids = {c["id"] for c in archived_list}
        assert archived_ids == {c1["id"]}

        fetched = get_success_data(api_client.get_internal_course(c1["id"], ADMIN))
        assert fetched["is_active"] is False, "archival keeps the record addressable"


class TestDegreeProgressDefaultVariant:
    def test_degree_progress_default_variant_is_certified(self):
        """PRD §3.8: "It takes a `variant` selector: `CERTIFIED` (the default)".
        PRD §3.8: "when no credits are awarded at all, the GPA is null."
        PRD §3.8: "the `residency_min_institutional_credits` constant — 30.0
        institutional credits the student must still complete in residence".

        Design: Corner/endpoints/degree_progress_default_variant_is_certified
        """
        student = fixtures.create_student(major="MATH")

        resp = api_client.get_degree_progress(student["id"], EVALUATOR)
        progress = validate_success(resp)
        assert progress["variant"] == "CERTIFIED"
        assert progress["total_applied_credits"] == pytest.approx(0.0, abs=1e-9)
        assert progress["transfer_gpa"] is None
        assert progress["residency_min_institutional_credits"] == pytest.approx(30.0, abs=1e-9)
