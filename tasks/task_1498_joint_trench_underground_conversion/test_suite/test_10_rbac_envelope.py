"""RBAC and authentication: missing role header, wrong-role denials on
role-exclusive endpoints.

PRD §2.1 (roles and authorization), §2.10 (auth precedes existence), §4
(endpoint role table).
"""
from test_helpers import (
    validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    create_project,
    create_project_payload,
    create_outage_window_payload,
    TEST_USERS, NO_ROLE_HEADERS,
    make_coordinator_headers,
    make_contractor_headers,
)

PM = TEST_USERS["pm_headers"]
ROW = TEST_USERS["row_headers"]
CONTRACTOR = TEST_USERS["contractor_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestAuthentication:
    def test_request_without_role_header_returns_unauthenticated(self, api):
        """PRD §2.1: "All interactions with the API must be authenticated
        through a pair of mandatory HTTP headers: `X-User-ID`, identifying the
        acting user, and `X-User-Role`, declaring their operational capacity. A
        request whose role header is missing or does not name a declared role
        is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/request_without_role_header_returns_unauthenticated
        """
        resp = api.list_projects(NO_ROLE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_wrong_role_create_project_forbidden(self, api):
        """PRD §2.1: "A request whose role is recognized but not authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /api/projects — "Create a project (PLANNING, posture
        CLEAR) | ProgramManager".

        Design: Corner/validations/wrong_role_create_project_forbidden
        """
        resp = api.create_project(
            create_project_payload(name="X", rule20_credit_cents=0,
                                   estimated_total_cost_cents=1000,
                                   target_cutover_on="2026-12-31T00:00:00Z"),
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_finance_analyst_cannot_run_lifecycle(self, api):
        """PRD §2.1: "`FinanceAnalyst` — the cost accountant: submits actual
        cost entries and drafts true-up runs, but may never publish one."
        PRD §4: POST /api/projects/{id}/lifecycle — "Lifecycle actions:
        MOBILIZE, START_TRENCHING, START_CONVERSION, START_RECONCILIATION,
        CLOSE, CANCEL | ProgramManager".
        PRD §2.1: "A request whose role is recognized but not authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/finance_analyst_cannot_run_lifecycle
        """
        project = create_project(name="R1", rule20_credit_cents=0,
                                 estimated_total_cost_cents=1000,
                                 target_cutover_on="2026-12-31T00:00:00Z")
        resp = api.project_lifecycle(project["id"], {"action": "MOBILIZE"}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_row_agent_cannot_create_outage(self, api):
        """PRD §2.1: "`RightOfWayAgent` — the land and right-of-way specialist:
        owns easements and permits, and may register parcels."
        PRD §4: POST /api/outage-windows — "Propose an outage window (PROPOSED)
        | UtilityCoordinator, ProgramManager".
        PRD §2.1: "A request whose role is recognized but not authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/row_agent_cannot_create_outage
        """
        project = create_project(name="R2", rule20_credit_cents=0,
                                 estimated_total_cost_cents=1000,
                                 target_cutover_on="2026-12-31T00:00:00Z")
        resp = api.create_outage_window(
            create_outage_window_payload(project["id"], feeder_id="F1",
                                         start_at="2026-09-05T10:00:00Z",
                                         end_at="2026-09-05T12:00:00Z"),
            ROW,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_coordinator_cannot_publish_trueup(self, api):
        """PRD §2.1: "`UtilityCoordinator` — a participating utility's trench
        coordinator: commits and withdraws its own participation, reserves and
        works its own occupancy slots, requests and runs outage windows, and
        pays or disputes its own invoices."
        PRD §4: POST /api/true-up-runs/{id}/transition — "Publish (segregation
        of duties; issues invoices) or settle a run | ProgramManager".
        PRD §2.1: "A request whose role is recognized but not authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.10: "Authentication comes first: a missing or unrecognized role
        yields `ERR_UNAUTHENTICATED`, and a recognized role without endpoint
        authorization yields `ERR_FORBIDDEN`."

        Design: Corner/rbac/coordinator_cannot_publish_trueup
        """
        resp = api.transition_true_up_run(
            NON_EXISTENT_UUID, {"to": "PUBLISHED"},
            make_coordinator_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_contractor_cannot_transition_easement(self, api):
        """PRD §2.1: "`ConversionContractor` — the service conversion and
        restoration contractor: owns service conversions and performs
        restoration work."
        PRD §4: POST /api/easements/{id}/transition — "Transition easement to
        REQUESTED, SIGNED, RECORDED, or REFUSED | RightOfWayAgent".
        PRD §2.1: "A request whose role is recognized but not authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/contractor_cannot_transition_easement
        """
        resp = api.transition_easement(
            NON_EXISTENT_UUID, {"to": "REQUESTED"},
            make_contractor_headers("cc-9"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
