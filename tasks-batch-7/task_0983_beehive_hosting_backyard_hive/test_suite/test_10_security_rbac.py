"""Auth context headers, role authorization, ownership, and existence-order
claims."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_active_host,
    create_agreement_for,
    create_hive_payload,
    create_inspection_payload,
    create_site_for,
    make_host_headers,
    record_inspection,
    setup_hive_scenario,
    setup_host_with_site,
    sign_agreement_for,
    submit_inspection,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["ops_headers"]
MGR = TEST_USERS["manager_headers"]
ANON = TEST_USERS["anonymous_headers"]
BK1 = TEST_USERS["beekeeper_headers"]
BK2 = TEST_USERS["beekeeper2_headers"]


class TestContextHeaders:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this set, is rejected with
        `ERR_MISSING_OR_INVALID_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_unauthenticated
        """
        host = create_active_host()
        res = api.get_host(host["id"], headers={})
        validate_error(res, "ERR_MISSING_OR_INVALID_CONTEXT_HEADER")

    def test_undeclared_role_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this set, is rejected with
        `ERR_MISSING_OR_INVALID_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_unauthenticated
        """
        host = create_active_host()
        res = api.get_host(
            host["id"],
            {"X-User-ID": "x-1", "X-User-Role": "SuperUser"},
        )
        validate_error(res, "ERR_MISSING_OR_INVALID_CONTEXT_HEADER")


class TestRoleAuthorization:
    def test_role_check_beats_existence(self, api):
        """PRD §2.12: "Every request passes through a fixed pipeline of checks,
        evaluated in this order, and the first failure determines the error
        returned"
        PRD §2.12 step 2: "the role appears in the endpoint's authorized list;
        otherwise `ERR_FORBIDDEN_ROLE` (403)."
        PRD §2.12 step 4: "path identifiers are validated left to right, then
        body foreign keys (`host_id`, `site_id`, `agreement_id`, `hive_id`,
        `source_hive_id`); a missing resource yields `ERR_NOT_FOUND` (404)."
        PRD §4: POST /api/hives is authorized for ApiaryManager only.

        Design: Corner/validations/role_check_beats_existence
        """
        host = create_active_host()
        res = api.create_hive(
            create_hive_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID),
            make_host_headers(host["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    def test_host_cannot_install_hive(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /api/hives is authorized for ApiaryManager only.

        Design: Corner/rbac/host_cannot_install_hive_forbidden
        """
        ctx = setup_hive_scenario()
        res = api.create_hive(
            create_hive_payload(ctx["site"]["id"], ctx["agreement"]["id"]),
            make_host_headers(ctx["host"]["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    def test_beekeeper_cannot_verify_inspection(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /api/inspections/{id}/verify is authorized for
        ApiaryManager only.

        Design: Corner/rbac/beekeeper_cannot_verify_inspection_forbidden
        """
        ctx = setup_hive_scenario()
        insp = record_inspection(ctx["hive"]["id"], mites_counted=1)
        submit_inspection(insp["id"])
        # A different beekeeper (not the recorder) is still role-denied.
        res = api.verify_inspection(insp["id"], BK2)
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    def test_platformops_cannot_record_inspection(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /api/inspections is authorized for Beekeeper only.

        Design: Corner/rbac/platformops_cannot_record_inspection_forbidden
        """
        ctx = setup_hive_scenario()
        res = api.create_inspection(
            create_inspection_payload(ctx["hive"]["id"]), OPS,
        )
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    def test_anonymous_cannot_read_host(self, api):
        """PRD §2.1: "`Anonymous` callers are unauthenticated and may only
        self-register as a host."
        PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/anonymous_cannot_read_host_forbidden
        """
        host = create_active_host()
        res = api.get_host(host["id"], ANON)
        validate_error(res, "ERR_FORBIDDEN_ROLE")


class TestOwnership:
    def test_host_cannot_sign_others_agreement(self, api):
        """PRD §2.1: "When a caller acting as `Host` attempts a mutating
        operation on a resource owned by a different host, the request is
        rejected with `ERR_NOT_RESOURCE_OWNER`; ownership applies to the
        caller's agreements, sites, subscriptions, invoices, enrollments,
        removal jobs, and swarm reports."
        PRD §3.2: "Signing belongs to the host named on the agreement
        (`host_id` equal to `X-User-ID`)."

        Design: Corner/validations/host_cannot_sign_others_agreement_forbidden
        """
        host_a = create_active_host(full_name="Owner A", email="a@example.com")
        host_b = create_active_host(full_name="Owner B", email="b@example.com")
        site_b = create_site_for(host_b, address="14 B St")
        agreement_b = create_agreement_for(host_b, site_b)
        res = api.sign_agreement(
            agreement_b["id"], make_host_headers(host_a["id"]),
        )
        validate_error(res, "ERR_NOT_RESOURCE_OWNER")
        current = validate_success(api.get_agreement(agreement_b["id"], OPS))
        assert current["status"] == "PENDING_SIGNATURE"


class TestExistence:
    def test_hive_create_missing_site_not_found(self, api):
        """PRD §2.12 step 4: "path identifiers are validated left to right,
        then body foreign keys (`host_id`, `site_id`, `agreement_id`,
        `hive_id`, `source_hive_id`); a missing resource yields `ERR_NOT_FOUND`
        (404)."

        Design: Corner/validations/hive_create_missing_site_not_found
        """
        host, site = setup_host_with_site()
        agreement = sign_agreement_for(create_agreement_for(host, site), host)
        res = api.create_hive(
            create_hive_payload(NON_EXISTENT_UUID, agreement["id"]), MGR,
        )
        validate_error(res, "ERR_NOT_FOUND")
