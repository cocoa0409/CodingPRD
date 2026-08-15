"""Authentication envelope, role-based access control, and error envelope."""
from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    create_approved_dmr,
    create_dmr_draft,
    create_line,
    create_part,
    create_protocol,
    create_qualified_supplier,
    create_releasable_lot,
    create_supplier,
    create_supplier_payload,
    create_validated_stack,
    get_lot,
    make_production_operator_headers,
    make_qms_admin_headers,
    make_regulatory_affairs_headers,
    make_supplier_quality_engineer_headers,
    po,
    qe,
    qm,
    ra,
    sqe,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)


class TestAuthContext:
    def test_missing_auth_header_returns_400(self, api):
        """PRD section 2.1: "Every request must carry two headers: `X-User-ID`,
        identifying the acting operator, and `X-User-Role`, declaring the
        capacity in which they act. A request missing either header, or
        presenting a role the system does not recognize, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        create_supplier("SUP-AH", "AH Co")
        role_only_headers = {
            "X-User-Role": "SupplierQualityEngineer",
            "Content-Type": "application/json",
        }
        resp = api._request("GET", "/api/suppliers", headers=role_only_headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestErrorEnvelope:
    def test_error_envelope_shape(self, api):
        """PRD section 2.2: "All error API responses (4xx status codes) follow
        this standard envelope format" with "`response_type`: "error"" and "The
        `error_id` is a unique, machine-readable string that identifies the
        specific error. The `message` provides a human-readable explanation of
        what went wrong." and "The `meta` object for error responses contains
        only `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/error_envelope_shape
        """
        resp = api.get_supplier(UNKNOWN_UUID, qm())
        body = resp.json()
        assert resp.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]

    def test_get_unknown_lot_not_found(self, api):
        """PRD section 2.11: "Path identifiers are validated strictly left to
        right: the request is rejected with a 404 `ERR_NOT_FOUND` for the *first*
        path identifier that does not correspond to an existing resource" — a
        well-formed but unknown lot id returns the 404 error envelope.

        Design: Corner/entities/get_unknown_lot_not_found
        """
        resp = api.get_lot(UNKNOWN_UUID, qm())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"


class TestRoleDenials:
    def test_production_operator_cannot_approve_dmr(self, api):
        """PRD section 2.1: "An attempt to invoke an operation outside the
        caller's role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." — DMR
        approval is a `QualityManager` operation per PRD section 4.

        Design: Corner/rbac/production_operator_cannot_approve_dmr
        """
        dmr = create_dmr_draft(device_code="DEV-RB1")
        resp = api.approve_dmr(dmr["id"], po())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        current = validate_success(api.get_dmr(dmr["id"], qm()))
        assert current["status"] == "DRAFT"

    def test_quality_engineer_cannot_release_lot(self, api):
        """PRD section 2.1: "An attempt to invoke an operation outside the
        caller's role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." — lot
        release is a `QualityManager` operation per PRD section 4, and the role
        check precedes every business gate.

        Design: Corner/rbac/quality_engineer_cannot_release_lot
        """
        stack = create_validated_stack("DEV-RB2")
        qs = create_qualified_supplier("SUP-RB2", "RB2 Co")
        part = create_part(qs["supplier"]["id"], "PN-RB2", description="knob2", receive_qty=100)
        bundle = create_releasable_lot(stack, part, lot_number="LT-RB2", supplier_lot_number="SL-RB2")

        resp = api.release_lot(bundle["lot"]["id"], qe())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_lot(bundle["lot"]["id"])["disposition_status"] == "COMPLETED"

    def test_regulatory_affairs_cannot_create_supplier(self, api):
        """PRD section 2.1: "An attempt to invoke an operation outside the
        caller's role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." —
        supplier registration is a `SupplierQualityEngineer` operation per PRD
        section 4.

        Design: Corner/rbac/regulatory_affairs_cannot_create_supplier
        """
        resp = api.create_supplier(
            create_supplier_payload(supplier_code="SUP-RB3", name="Nope Co"), ra()
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_sqe_cannot_execute_protocol_phase(self, api):
        """PRD section 2.1: "An attempt to invoke an operation outside the
        caller's role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." — phase
        execution is a `QualityEngineer` operation per PRD section 4.

        Design: Corner/rbac/sqe_cannot_execute_protocol_phase
        """
        line = create_line("L-RB4")
        dmr = create_approved_dmr(device_code="DEV-RB4")
        protocol = create_protocol("VP-RB4", dmr["id"], line["id"])

        resp = api.execute_phase(protocol["id"], sqe())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        current = validate_success(api.get_protocol(protocol["id"], qm()))
        assert current["status"] == "DRAFT"

    def test_qmsadmin_cannot_perform_business_writes(self, api):
        """PRD section 2.1: "`QMSAdmin` — quality-system administrator: logical
        clock and manufacturing-line configuration only." and "An attempt to
        invoke an operation outside the caller's role is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/qmsadmin_cannot_perform_business_writes
        """
        resp = api.create_supplier(
            create_supplier_payload(supplier_code="SUP-RB5", name="Admin Co"),
            make_qms_admin_headers("admin-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_get_endpoints_allow_all_roles(self, api):
        """PRD section 2.1: "Every list and single-resource read endpoint is
        available to all six roles."

        Design: Corner/rbac/get_endpoints_allow_all_roles
        """
        supplier = create_supplier("SUP-RB6", "Read Co")
        fetched = validate_success(
            api.get_supplier(supplier["id"], make_production_operator_headers("po-1"))
        )
        assert fetched["status"] == "PENDING_QUALIFICATION"

        page, meta = validate_paginated(
            api.list_protocols(make_regulatory_affairs_headers("ra-1"))
        )
        assert page == []
        assert meta["total_count"] == 0
