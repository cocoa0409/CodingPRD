"""Authentication headers and role-permission enforcement."""
from test_helpers import (
    ApiErrorId,
    create_client,
    create_project,
    create_talent,
    create_talent_payload,
    make_client_headers,
    make_talent_headers,
    setup_delivered_project,
    validate_error,
)
from test_helpers.factories import create_project_payload, create_talent_payload
from test_helpers.fixtures import ENGINEER
from test_helpers.test_users import TEST_USERS


class TestAuthentication:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the
        platform does not recognize, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        talent = create_talent()
        resp = api.get_talent(talent["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRolePermissions:
    def test_client_cannot_create_talent_returns_unauthorized(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the attempted operation is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)". PRD §4: `POST /api/talents` is authorized for
        `CastingDirector` only.

        Design: Corner/validations/client_cannot_create_talent_returns_unauthorized
        """
        client = create_client()
        resp = api.create_talent(create_talent_payload(),
                                 make_client_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_talent_cannot_open_casting(self, api):
        """PRD §4: `POST /api/projects/{id}/open_casting` is authorized for
        `CastingDirector` only. PRD §2.1: "A request whose role is recognized
        but not permitted for the attempted operation is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)".

        Design: Corner/rbac/talent_cannot_open_casting
        """
        client = create_client()
        talent = create_talent()
        project = create_project(client)
        resp = api.open_casting(project["id"], make_talent_headers(talent["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_agent_cannot_create_project(self, api):
        """PRD §4: `POST /api/projects` is authorized for `Client` only.
        PRD §2.1: "A request whose role is recognized but not permitted for the
        attempted operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)".

        Design: Corner/rbac/agent_cannot_create_project
        """
        client = create_client()
        agent_headers = TEST_USERS["agent_headers"]
        resp = api.create_project(create_project_payload(client["id"]), agent_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_studio_engineer_cannot_issue_invoice(self, api):
        """PRD §4: `POST /api/invoices/{id}/issue` is authorized for `Agent`
        only. PRD §2.1: "A request whose role is recognized but not permitted
        for the attempted operation is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)".

        Design: Corner/rbac/studio_engineer_cannot_issue_invoice
        """
        ctx = setup_delivered_project()
        invoice = ctx["invoices"][0]
        resp = api.issue_invoice(invoice["id"], ENGINEER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
