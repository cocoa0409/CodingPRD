"""Cross-cutting access control and response-envelope guarantees:
authentication, authorization per role, existence checks, and the paginated
list envelope."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    approve_decision_payload,
    certification_entry,
    create_assignment_payload,
    create_field_test_payload,
    create_project,
    create_ssi_revision,
    create_technician,
    get_revision,
    is_iso8601_timestamp,
    make_technician_headers,
    setup_approved_project,
    setup_dispatched_assignment,
    soil_scope_item,
    submit_revision,
    validate_error,
    validate_paginated,
    weld_scope_item,
)

ADMIN = TEST_USERS["agency_admin_headers"]
PM = TEST_USERS["project_manager_headers"]
CONTRACTOR = TEST_USERS["contractor_headers"]
LAB_ANALYST = TEST_USERS["lab_analyst_headers"]


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID`,
        identifying the acting principal, and `X-User-Role`, declaring the
        caller's role. A request missing either header, or presenting a role
        outside the declared set, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/unauthenticated_missing_auth_header
        """
        project = create_project(name="AuthProbe", permit_number="P-VAL-1")
        resp = api.get_project(project["id"], None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401


class TestExistenceChecks:
    def test_dispatch_of_unknown_assignment_returns_not_found(self, api):
        """PRD §2.8: "Where a URL nests resources — a project's SSI revisions,
        an assignment's field tests, a lab's samples — path identifiers are
        validated left to right: the project first, then the revision,
        assignment, sample, test, report, or ticket. The first segment that
        fails to resolve yields `ERR_NOT_FOUND`."

        Design: Corner/validations/dispatch_nonexistent_assignment_returns_not_found
        """
        resp = api.dispatch_assignment(NON_EXISTENT_UUID, PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404


class TestListEnvelope:
    def test_empty_list_envelope_uses_pagination_defaults(self, api):
        """PRD §2.3: "List endpoints accept two query parameters, `limit` and
        `offset`. The `limit` defaults to 10, must be at least 1, and may not
        exceed 100; the `offset` defaults to 0. Every list response carries
        `limit`, `offset`, `total_count`, and `has_more` in its `meta` object."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/endpoints/list_envelope_pagination_defaults
        """
        project = create_project(name="Envelope", permit_number="P-EP-1")
        resp = api.list_project_ncrs(project["id"], PM)
        data, meta = validate_paginated(resp)
        assert data == [], "a fresh project has no NCRs"
        assert meta["limit"] == 10, "the default limit is 10"
        assert meta["offset"] == 0
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert meta["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        body = resp.json()
        assert body["response_type"] == "array"


class TestRoleSegregation:
    def test_technician_cannot_approve_revision(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list, or that fails an entity-backed ownership check (for example, a
        technician attempting to complete another technician's assignment), is
        rejected with `ERR_FORBIDDEN`."
        PRD §3.1: "The `EngineerOfRecord` then decides. The decision request
        carries `decision` — `APPROVE` or `REJECT` — plus the
        optimistic-concurrency field described in §2.7."

        Design: Corner/rbac/technician_cannot_approve_ssi
        """
        project = create_project(name="RBAC1", permit_number="P-RBAC-1")
        ssi = create_ssi_revision(
            project["id"], [weld_scope_item(description="frames")], specified_fc_psi=4000
        )
        submit_revision(ssi["id"])
        tech = create_technician()

        resp = api.approve_ssi_revision(
            ssi["id"],
            approve_decision_payload("APPROVE", project["version"]),
            make_technician_headers(tech["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_revision(ssi["id"])["status"] == "SUBMITTED"

    def test_contractor_cannot_create_assignment(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list, or that fails an entity-backed ownership check (for example, a
        technician attempting to complete another technician's assignment), is
        rejected with `ERR_FORBIDDEN`."
        PRD §3.3: "A `ProjectManager` builds the dispatch board by creating
        inspection assignments."

        Design: Corner/rbac/contractor_cannot_create_assignment
        """
        ctx = setup_approved_project(
            [soil_scope_item()],
            project_overrides={"name": "RBAC2", "permit_number": "P-RBAC-2"},
        )
        tech = create_technician(certifications=[
            certification_entry("SOIL_COMPACTION", level=2)
        ])
        resp = api.create_assignment(
            create_assignment_payload(
                ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
                "2026-05-04", "09:00", "10:00",
            ),
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_lab_analyst_cannot_record_field_test(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list, or that fails an entity-backed ownership check (for example, a
        technician attempting to complete another technician's assignment), is
        rejected with `ERR_FORBIDDEN`."
        PRD §3.4: "On a dispatched assignment, the assigned technician records
        field tests directly: the request carries the `assignment_id` and a
        method-shaped `measured_values` object."

        Design: Corner/rbac/lab_analyst_cannot_record_field_test
        """
        ctx = setup_dispatched_assignment(
            project_overrides={"name": "RBAC3", "permit_number": "P-RBAC-3"}
        )
        resp = api.create_field_test(
            create_field_test_payload(
                ctx["assignment"]["id"], {"field_dry_density_pcf": 118.0}
            ),
            LAB_ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
