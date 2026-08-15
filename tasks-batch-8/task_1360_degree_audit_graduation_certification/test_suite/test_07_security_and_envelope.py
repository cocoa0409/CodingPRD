"""Cross-cutting guards: auth headers, RBAC denials, resource existence (path
and body), pagination validation, and the response envelope (PRD §2.1, §2.2,
§2.3, §2.6, §2.7).
"""
import pytest

from test_helpers import (
    ABSENT_UUID,
    ApiErrorId,
    create_application_payload,
    create_audit_payload,
    create_enrollment_payload,
    create_program_payload,
    create_waiver_payload,
    declare,
    make_advisor_headers,
    make_course,
    make_program,
    make_student,
    make_student_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthHeaderGate:
    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "All interactions with the API are authenticated through two
        mandatory HTTP headers: `X-User-ID`, identifying the acting user, and
        `X-User-Role`, naming their operational capacity. A request in which
        either header is missing or empty is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        res = api.create_program(
            create_program_payload(program_code="BS-AU", name="AU"),
            {"X-User-Role": "RegistrarStaff", "Content-Type": "application/json"})
        validate_error(
            res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
            expected_status=400)


class TestRbacDenials:
    def test_role_and_ownership_denials_return_forbidden(self, api, registrar_headers):
        """PRD §2.1: "Any attempt to invoke an operation outside the caller's
        role is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "First, the audit kinds `FINAL` and `CONDITIONAL` are
        restricted to `RegistrarStaff`; a `Student` or `Advisor` requesting
        either kind is rejected with `ERR_FORBIDDEN`. Second, every `Student`
        interaction — reads included — is scoped to that student's own records
        under the ownership rule above."
        PRD §2.7: "2. **Role authorization.** The role must be permitted on the
        endpoint, including the `FINAL`/`CONDITIONAL` audit restriction and the
        `Student` ownership rule (`ERR_FORBIDDEN`)." — fired before "3. **Path
        existence.**", so a denied role surfaces ERR_FORBIDDEN even for a
        non-existent waiver id.

        Design: Corner/rbac/rbac_denied_operations_return_forbidden
        """
        program = make_program(program_code="BS-RB", name="BS RB")
        s1 = make_student(student_number="S-R1", legal_name="Rob One")
        s2 = make_student(student_number="S-R2", legal_name="Rob Two")
        sp = declare(s1["id"], program["id"], catalog_year=2024)

        # Advisor calling the RegistrarStaff-only registrar-decision endpoint:
        # role check (priority 2) fires before path existence (priority 3).
        res = api.registrar_decision(ABSENT_UUID, {"decision": "APPROVE"},
                                     make_advisor_headers("adv-4"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)

        # Student requesting a FINAL audit on their own declaration.
        res = api.create_audit(
            sp["id"], create_audit_payload("FINAL", sp["version"]),
            make_student_headers(s1["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)

        # Student reading another student's record.
        res = api.get_student(s2["id"], make_student_headers(s1["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)

        # SystemAdmin calling a business endpoint (POST /programs is RegistrarStaff-only).
        from test_helpers import TEST_USERS
        res = api.create_program(
            create_program_payload(program_code="BS-RX", name="RX"),
            TEST_USERS["sysadmin_headers"])
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


class TestNotFound:
    def test_get_missing_resources_return_resource_specific_404(self, api, registrar_headers):
        """PRD §2.6: "Each resource family has its own not-found identifier:
        `ERR_PROGRAM_NOT_FOUND`, `ERR_REQUIREMENT_GROUP_NOT_FOUND`,
        `ERR_COURSE_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
        `ERR_STUDENT_PROGRAM_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, and `ERR_DIPLOMA_NOT_FOUND`."

        Design: Corner/entities/get_missing_resources_return_not_found
        """
        cases = [
            (api.get_program(ABSENT_UUID, registrar_headers), "ERR_PROGRAM_NOT_FOUND"),
            (api.get_student(ABSENT_UUID, registrar_headers), "ERR_STUDENT_NOT_FOUND"),
            (api.get_student_program(ABSENT_UUID, registrar_headers), "ERR_STUDENT_PROGRAM_NOT_FOUND"),
            (api.get_application(ABSENT_UUID, registrar_headers), "ERR_APPLICATION_NOT_FOUND"),
        ]
        for res, error_id in cases:
            validate_error(res, error_id, expected_status=404)

    def test_path_and_body_reference_not_found_errors(self, api, registrar_headers):
        """PRD §2.6: "When a path contains multiple identifiers — a program
        followed by a requirement group collection, a student followed by an
        enrollment collection, a declaration followed by its audits, exceptions,
        or applications — the system validates the existence of each identifier
        sequentially, from left to right, and rejects the request with a `404 Not
        Found` for the *first* identifier that does not resolve to an existing
        resource." and
        "identifiers referenced inside the request body — `program_id`,
        `course_id`, `requirement_group_id`, `enrollment_id`, and
        `target_program_id` — must each resolve to an existing resource; an
        unresolvable body reference is rejected with the corresponding not-found
        identifier (for example, an unknown `requirement_group_id` yields
        `ERR_REQUIREMENT_GROUP_NOT_FOUND`)."

        Design: Corner/errors/body_fk_not_found_errors
        """
        program = make_program(program_code="BS-NF", name="BS NF")
        student = make_student(student_number="S-NF", legal_name="No Found")
        sp = declare(student["id"], program["id"], catalog_year=2024)

        res = api.post_grade(ABSENT_UUID, {"grade": "A"}, registrar_headers)
        validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND.value, expected_status=404)

        res = api.advisor_decision(ABSENT_UUID, {"decision": "APPROVE"},
                                   make_advisor_headers("adv-3"))
        validate_error(res, ApiErrorId.ERR_WAIVER_NOT_FOUND.value, expected_status=404)

        res = api.issue_diploma(ABSENT_UUID, registrar_headers)
        validate_error(res, ApiErrorId.ERR_DIPLOMA_NOT_FOUND.value, expected_status=404)

        res = api.create_waiver(
            sp["id"],
            create_waiver_payload(ABSENT_UUID, "WAIVER", credit_waiver_amount=1),
            make_advisor_headers("adv-3"))
        validate_error(res, ApiErrorId.ERR_REQUIREMENT_GROUP_NOT_FOUND.value, expected_status=404)

        res = api.create_enrollment(
            student["id"],
            create_enrollment_payload(ABSENT_UUID, term="2024-FA"),
            registrar_headers)
        validate_error(res, ApiErrorId.ERR_COURSE_NOT_FOUND.value, expected_status=404)


class TestPaginationValidation:
    def test_limit_zero_rejected(self, api, registrar_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        when omitted it defaults to 10, and it must lie between 1 and 100
        inclusive. The `offset` parameter states how many items to skip and
        defaults to 0; negative offsets are not allowed. A `limit` outside the
        permitted range or a negative `offset` is rejected with
        `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400)."

        Design: Corner/errors/invalid_pagination_limit_returns_400
        """
        res = api.list_waivers(registrar_headers, params={"limit": 0})
        validate_error(res, ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS.value,
                       expected_status=400)


class TestResponseEnvelope:
    def test_list_envelope_shape_and_pagination_defaults(self, api, registrar_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." and "The
        `response_type` is either "object" for a single resource or "array" for
        a list of resources."
        PRD §2.3: "when omitted it defaults to 10" and "Paginated list responses
        carry the fields `limit`, `offset`, `total_count`, and `has_more` in the
        `meta` object of the envelope."

        Design: Corner/endpoints/response_envelope_shape_on_list
        """
        res = api.list_waivers(registrar_headers)
        assert res.status_code == 200
        body = res.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "array"
        assert body["data"] == []
        meta = body["meta"]
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
