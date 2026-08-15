"""Role-based access control and authentication-context validation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_disposition_request_payload,
    create_legal_hold_payload,
    create_program,
    create_retention_rule_payload,
    make_custodian_headers,
    make_platform_admin_headers,
    register_custodian,
    setup_issued_hold,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RM = TEST_USERS["records_manager_headers"]
LC = TEST_USERS["legal_counsel_headers"]
AUD = TEST_USERS["auditor_headers"]


class TestAuthContext:
    def test_missing_auth_headers_returns_400(self, api):
        """PRD §2.1: "If either header is missing, empty, or names a role
        outside the declared set, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        # The X-User-Role header is deliberately omitted from this call.
        resp = api.list_programs({"X-User-ID": "rm-1",
                                  "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

        # An undeclared role value is equally invalid.
        bad_role = api.list_programs({"X-User-ID": "rm-1",
                                      "X-User-Role": "SuperUser",
                                      "Content-Type": "application/json"})
        validate_error(bad_role, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestReadDenial:
    def test_rbac_read_denial_for_custodian_on_records(self, api):
        """PRD §2.1: "If the role is well-formed but not authorized for the
        endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP
        403)."
        PRD §4 endpoint table: GET /ig/records is authorized for PlatformAdmin,
        RecordsManager, LegalCounsel, Auditor only (Custodian excluded), while
        GET /ig/legal-holds also lists Custodian.

        Design: Corner/rbac/rbac_read_denial_for_custodian_on_records
        """
        program = create_program(name="P")
        custodian = register_custodian(program["id"])
        headers = make_custodian_headers(custodian["id"])

        denied = api.list_records(headers)
        validate_error(denied, ApiErrorId.ERR_FORBIDDEN_ROLE)

        allowed, meta = validate_paginated(api.list_legal_holds(headers))
        assert meta["total_count"] == 0, (
            "the same role reads legal holds successfully (empty list, 200)"
        )


class TestWriteDenials:
    def test_rbac_write_denials_across_roles(self, api):
        """PRD §2.1: "If the role is well-formed but not authorized for the
        endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP
        403)."
        PRD §4 endpoint table: POST /ig/legal-holds is authorized for
        LegalCounsel only, POST /ig/retention-rules and POST
        /ig/disposition-requests for RecordsManager only, and POST
        /ig/hold-custodians/{assignmentId}/acknowledge for Custodian only.

        Design: Corner/rbac/rbac_write_denials_across_roles
        """
        scen = setup_issued_hold(matter_ref="M-RBAC")
        ctx = scen["ctx"]
        record = scen["records"][0]
        custodian = scen["custodians"][0]
        assignment = scen["assignments"][0]

        hold_by_rm = api.create_legal_hold(
            create_legal_hold_payload(ctx["program"]["id"], "M-RM",
                                      [custodian["id"]], [record["id"]],
                                      title="RM Hold", reason="Attempt"),
            RM)
        validate_error(hold_by_rm, ApiErrorId.ERR_FORBIDDEN_ROLE)

        rule_by_lc = api.create_retention_rule(
            create_retention_rule_payload(
                ctx["program"]["id"], ctx["record_class"]["id"],
                ctx["jurisdiction"]["id"], rule_code="R-LC",
                retention_months=24),
            LC)
        validate_error(rule_by_lc, ApiErrorId.ERR_FORBIDDEN_ROLE)

        request_by_auditor = api.create_disposition_request(
            create_disposition_request_payload(ctx["program"]["id"],
                                               [record["id"]]),
            AUD)
        validate_error(request_by_auditor, ApiErrorId.ERR_FORBIDDEN_ROLE)

        ack_by_admin = api.acknowledge_hold_custodian(
            assignment["id"], make_platform_admin_headers("admin-9"))
        validate_error(ack_by_admin, ApiErrorId.ERR_FORBIDDEN_ROLE)
