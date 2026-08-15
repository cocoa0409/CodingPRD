"""Item authoring defaults, input validation, auth pipeline, and RBAC denials."""
from test_helpers import (
    ApiErrorId,
    assert_item,
    create_item_payload,
    create_program_payload,
    create_response_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ASSEMBLER_H,
    OFFICER_H,
    create_draft_item,
    create_program,
    create_standard,
    create_window,
    ensure_grant,
    open_window,
)
from test_helpers.test_users import (
    make_content_reviewer_headers,
    make_item_writer_headers,
)


class TestItemCreation:
    def test_item_exposure_cap_defaults_to_3(self, api):
        """PRD: "an optional `exposure_cap` that defaults to 3 when not
        supplied."

        Design: Corner/entities/item_exposure_cap_defaults_to_3
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"],
                                 item_code="I-DEF")
        assert item["exposure_cap"] == 3, "exposure_cap defaults to 3"

    def test_item_system_fields_input_ignored(self, api):
        """PRD: "At creation the server stamps `author_user_id` with the
        caller's `X-User-ID`, sets `status` to `DRAFT` and `security_posture`
        to `UNSECURED`, initializes both `content_review_outcome` and
        `bias_review_outcome` to `PENDING`, and starts `revision_cycle_count`,
        `field_test_attempt_count`, and `operational_exposure_count` at zero."

        Design: Corner/entities/item_system_fields_input_ignored
        """
        program = create_program()
        standard = create_standard(program["id"])
        ensure_grant(program["id"], "writer-99", "ITEM_WRITE")
        payload = create_item_payload(program["id"], standard["id"],
                                      item_code="I-SYS")
        # Client attempts to override system-stamped fields; all ignored.
        payload["status"] = "OPERATIONAL"
        payload["author_user_id"] = "spoofed-user"
        payload["security_posture"] = "SECURED"
        payload["version"] = 99
        item = validate_success(
            api.create_item(payload, make_item_writer_headers("writer-99")), 201)
        assert_item(item)
        assert item["status"] == "DRAFT"
        assert item["security_posture"] == "UNSECURED"
        assert item["author_user_id"] == "writer-99", (
            "author is stamped from the X-User-ID header"
        )
        assert item["content_review_outcome"] == "PENDING"
        assert item["bias_review_outcome"] == "PENDING"
        assert item["revision_cycle_count"] == 0
        assert item["operational_exposure_count"] == 0
        assert isinstance(item["version"], int), "version is system-managed"

    def test_item_invalid_enum_item_type_returns_400(self, api):
        """PRD: "Requests with a missing required field, a type mismatch, or an
        unrecognized enum value are structurally invalid and fail with
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD: "an `item_type` of `MC`, `MS`, `EBSR`, `TE`, or `CR`"

        Design: Corner/entities/item_invalid_enum_item_type_returns_400
        """
        program = create_program()
        standard = create_standard(program["id"])
        payload = create_item_payload(program["id"], standard["id"],
                                      item_code="I-BAD", item_type="ESSAY")
        resp = api.create_item(payload, make_item_writer_headers("writer-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAuthPipeline:
    def test_validation_auth_missing_header(self, api):
        """PRD: "A request in which either header is missing or malformed is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/validation_auth_missing_header
        """
        resp = api.list_assessment_programs({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_validation_role_mismatch_returns_403(self, api):
        """PRD: "When the named role is not among the roles an endpoint admits,
        the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD endpoint table, role admissibility for this endpoint: "| POST |
        `/api/assessment-programs` | Create an assessment program (logical
        clock initialized) | ProgramDirector |"

        Design: Corner/validations/validation_role_mismatch_returns_403
        """
        resp = api.create_assessment_program(
            create_program_payload(program_code="P-X"),
            make_item_writer_headers("writer-x"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_validation_duplicate_item_code_returns_409(self, api):
        """PRD: "Item codes are unique within their program, and a colliding
        `item_code` is rejected with `ERR_DUPLICATE_CODE`."

        Design: Corner/validations/validation_duplicate_item_code_returns_409
        """
        program = create_program()
        standard = create_standard(program["id"])
        create_draft_item(program["id"], standard["id"], item_code="I-DUP")
        resp = api.create_item(
            create_item_payload(program["id"], standard["id"], item_code="I-DUP"),
            make_item_writer_headers("writer-1"),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)


class TestRbacExclusiveOperations:
    def test_rbac_security_officer_cannot_create_program(self, api):
        """PRD: "When the named role is not among the roles an endpoint admits,
        the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD endpoint table, role admissibility for this endpoint: "| POST |
        `/api/assessment-programs` | Create an assessment program (logical
        clock initialized) | ProgramDirector |"

        Design: Corner/roles/rbac_security_officer_cannot_create_program
        """
        resp = api.create_assessment_program(
            create_program_payload(program_code="P-X"), OFFICER_H)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_rbac_content_reviewer_cannot_create_item(self, api):
        """PRD: "When the named role is not among the roles an endpoint admits,
        the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD endpoint table, role admissibility for this endpoint: "| POST |
        `/api/items` | Create an item in `DRAFT` / `UNSECURED` | ItemWriter |"

        Design: Corner/roles/rbac_content_reviewer_cannot_create_item
        """
        program = create_program()
        standard = create_standard(program["id"])
        resp = api.create_item(
            create_item_payload(program["id"], standard["id"], item_code="I-X"),
            make_content_reviewer_headers("cr-x"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_rbac_itemwriter_cannot_close_window(self, api):
        """PRD: "When the named role is not among the roles an endpoint admits,
        the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD endpoint table, role admissibility for this endpoint: "| POST |
        `/api/field-test-windows/{wid}/close` | Close an `OPEN` window; compute
        statistics | ProgramDirector |"

        Design: Corner/roles/rbac_itemwriter_cannot_close_window
        """
        program = create_program()
        window = create_window(program["id"])
        resp = api.close_field_test_window(
            window["id"], make_item_writer_headers("writer-x"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_rbac_testassembler_cannot_ingest_response(self, api):
        """PRD: "When the named role is not among the roles an endpoint admits,
        the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD endpoint table, role admissibility for this endpoint: "| POST |
        `/api/field-test-windows/{wid}/responses` | Ingest an item response
        into an `OPEN` window | Psychometrician |"

        Design: Corner/roles/rbac_testassembler_cannot_ingest_response
        """
        program = create_program()
        window = create_window(program["id"])
        open_window(program["id"], window["id"])
        resp = api.ingest_item_response(
            window["id"],
            create_response_payload(
                "00000000-0000-0000-0000-000000000000", "s1", 1,
                response_timestamp="2026-08-05T00:00:00Z"),
            ASSEMBLER_H,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
