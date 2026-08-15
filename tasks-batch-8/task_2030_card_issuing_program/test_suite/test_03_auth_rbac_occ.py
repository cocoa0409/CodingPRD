"""Authentication, authorization, RBAC denials, and OCC guards (corner:
validations + rbac + cross_cutting occ)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_bin_range_payload,
    create_mandate_ack_payload,
    create_mandate_payload,
    create_program_payload,
    get_success_data,
    make_compliance_officer_headers,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
PA = TEST_USERS["platform_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
OA = TEST_USERS["operations_analyst_headers"]
FC = TEST_USERS["finance_controller_headers"]
CH = TEST_USERS["cardholder_ops_headers"]


class TestAuthentication:
    def test_missing_role_header_returns_401(self, api):
        """PRD §2.1: "If the `X-User-Role` header is absent or does not name one
        of the declared roles, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_role_header_returns_401
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", PA))
        # Call with NO X-User-Role header.
        resp = api.create_program(
            create_program_payload(program_code="P-1"),
            {"X-User-ID": "u-no-role", "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


class TestRbacDenials:
    def test_program_manager_cannot_submit_mandate_ack(self, api):
        """PRD §2.1: "`ComplianceOfficer` — owns network mandates and their
        acknowledgements (submit, return, verify, reject), authorization rules,
        and card compromise actions." and "If the role is declared but not
        permitted to invoke the requested endpoint, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/validations/program_manager_cannot_submit_mandate_ack
        """
        from test_helpers import create_mandate, create_mandate_ack, create_program_with_bin_and_publish
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", PA))
        prog, _bin = create_program_with_bin_and_publish("P-RB1")
        mandate = create_mandate("M-RB1")
        ack = create_mandate_ack(mandate["id"], prog["id"])
        resp = api.submit_mandate_ack(mandate["id"], ack["id"], PM)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    def test_cardholder_ops_cannot_create_program(self, api):
        """PRD §2.1: "`CardholderOps` — performs card activation, PIN
        management, and initiates authorizations on behalf of the cardholder."
        and "If the role is declared but not permitted to invoke the requested
        endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/validations/cardholder_ops_cannot_create_program
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", PA))
        resp = api.create_program(create_program_payload(program_code="P-X"), CH)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    def test_operations_analyst_cannot_set_clock(self, api):
        """PRD §2.1: "`PlatformAdmin` — break-glass operator. Exclusively owns
        the logical-clock test-driving capability, vendor registration, and the
        forced PIN-block capability" and "If the role is declared but not
        permitted to invoke the requested endpoint, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/validations/operations_analyst_cannot_set_clock
        """
        resp = api.set_clock("2026-08-01T00:00:00Z", OA)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    def test_compliance_officer_cannot_publish_program(self, api):
        """PRD §2.1: "`ProgramManager` — owns the card program lifecycle
        (create, update, publish, sunset, cancel-sunset, terminate), BIN range
        management, card account lifecycle, card issuance, and conversion job
        scheduling." and "If the role is declared but not permitted to invoke
        the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/rbac/compliance_officer_cannot_publish_program
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", PA))
        prog = get_success_data(
            api.create_program(create_program_payload(program_code="P-RB2"), PM),
        )
        get_success_data(
            api.create_bin_range(prog["id"], create_bin_range_payload(), PM),
        )
        resp = api.publish_program(prog["id"], CO)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    def test_finance_controller_cannot_create_mandate(self, api):
        """PRD §2.1: "`ComplianceOfficer` — owns network mandates and their
        acknowledgements (submit, return, verify, reject), authorization rules,
        and card compromise actions." and "If the role is declared but not
        permitted to invoke the requested endpoint, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/finance_controller_cannot_create_mandate
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", PA))
        resp = api.create_mandate(create_mandate_payload(mandate_code="M-FC"), FC)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    def test_platform_admin_get_any_resource(self, api):
        """PRD §2.1: "`PlatformAdmin` — break-glass operator. Exclusively owns
        the logical-clock test-driving capability, vendor registration, and the
        forced PIN-block capability; shares account funding and settlement with
        `FinanceController`, and authorization creation with `CardholderOps`;
        may read all resources."

        Design: Corner/rbac/platform_admin_get_any_resource
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", PA))
        prog = get_success_data(
            api.create_program(create_program_payload(program_code="P-PA"), PM),
        )
        resp = api.get_program(prog["id"], PA)
        data = validate_success(resp)
        assert data["program_code"] == "P-PA"


class TestOptimisticConcurrency:
    def test_missing_occ_field_returns_400(self, api):
        """PRD §2.6: "if it is missing entirely, the request is rejected with
        `ERR_MISSING_OCC_FIELD` (HTTP 400)."

        Design: Corner/validations/missing_occ_field_returns_400
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", PA))
        prog = get_success_data(
            api.create_program(create_program_payload(program_code="P-OCC"), PM),
        )
        resp = api.update_program(prog["id"], {"daily_spend_cap_cents": 999999}, PM)
        validate_error(resp, ApiErrorId.ERR_MISSING_OCC_FIELD.value, expected_status=400)

    def test_stale_occ_version_returns_412(self, api):
        """PRD §2.6: "If it is present but no longer matches the entity's
        current `version` — because another writer has advanced the entity
        since the client last read it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), so the client can never overwrite state
        it has not observed."

        Design: Corner/validations/stale_occ_version_returns_412
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", PA))
        prog = get_success_data(
            api.create_program(create_program_payload(program_code="P-SOCC"), PM),
        )
        original_version = prog["version"]
        # First writer succeeds and bumps the version.
        first = api.update_program(
            prog["id"],
            {"expected_program_version": original_version, "daily_spend_cap_cents": 600000},
            PM,
        )
        validate_success(first)
        # Second writer with the stale version is rejected.
        resp = api.update_program(
            prog["id"],
            {"expected_program_version": original_version, "daily_spend_cap_cents": 700000},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    def test_occ_account_update_stale_version(self, api):
        """PRD §2.6: "Updating a card account's spend cap or credit limit
        requires `expected_account_version`, carrying the client's last-observed
        `version` of the `CardAccount`." and "If it is present but no longer
        matches the entity's current `version` — because another writer has
        advanced the entity since the client last read it — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), so the client can never
        overwrite state it has not observed."

        Design: Corner/cross_cutting_complexity_layers/occ_account_update_stale_version
        """
        from test_helpers import create_account, create_program_with_bin_and_publish
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", PA))
        prog, _bin = create_program_with_bin_and_publish("P-OACC")
        acct = create_account(prog["id"], "A-OACC", daily_spend_cap_cents=10000)
        original_version = acct["version"]
        first = api.update_account(
            acct["id"],
            {"expected_account_version": original_version, "daily_spend_cap_cents": 20000},
            PM,
        )
        validate_success(first)
        resp = api.update_account(
            acct["id"],
            {"expected_account_version": original_version, "daily_spend_cap_cents": 30000},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
