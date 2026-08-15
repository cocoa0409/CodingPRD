"""Foundations: response envelope, project defaults, auth, RBAC, SoD."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    is_iso8601_timestamp, TEST_USERS,
    ApiErrorId,
    create_project_payload, create_structure_survey_payload, complete_survey_payload,
    create_abatement_payload, create_utility_disconnect_payload,
    create_engineering_survey_payload,
    make_abatement_supervisor_headers, make_clearance_officer_headers,
    make_utility_coordinator_headers, make_structural_engineer_headers,
    make_peer_review_engineer_headers,
    create_project, create_and_complete_survey,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
SUPERVISOR = TEST_USERS["site_supervisor_headers"]
SURVEYOR = TEST_USERS["surveyor_headers"]


class TestEnvelopeAndDefaults:
    def test_project_create_applies_defaults(self):
        """PRD §3.1: "A new project is born in `DRAFT` status with `work_posture`
        `WORKABLE`: every tonnage counter (`in_transit_tons`, `landfill_tons`,
        `diverted_tons`, `removed_tons`) reads zero, the `cumulative_exposure_score`
        is zero, `diversion_rate` is zero, `diversion_tier` reads `STANDARD`, no
        engineering pin exists (`pinned_engineering_survey_id` and
        `pinned_engineering_revision` are unset), and `version` is 1."
        PRD §3.1: "an optional `required_diversion_rate` — the minimum debris
        diversion fraction the municipality demands for lot closure, a number
        between 0 and 1 inclusive that defaults to 0.5"

        Design: Corner/entities/project_create_applies_defaults
        """
        resp = api_client.create_project(
            create_project_payload(name="Defaults", address="2 Pine St", lot_area_sqft=12000),
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["work_posture"] == "WORKABLE"
        assert data["required_diversion_rate"] == 0.5
        assert data["in_transit_tons"] == 0
        assert data["landfill_tons"] == 0
        assert data["diverted_tons"] == 0
        assert data["removed_tons"] == 0
        assert data["cumulative_exposure_score"] == 0
        assert data["diversion_rate"] == 0
        assert data["diversion_tier"] == "STANDARD"
        assert data["version"] == 1

    def test_envelope_success_shape_on_create(self):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/endpoints/envelope_success_shape_on_create
        """
        resp = api_client.create_project(
            create_project_payload(name="Envelope", address="78 Pine St", lot_area_sqft=12000),
            ADMIN,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert isinstance(body["data"]["id"], str)

    def test_envelope_error_shape_on_validation_failure(self):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §2.9: "required fields are present, types are correct, enum members
        are valid, and ranges hold ... (`ERR_VALIDATION`)."

        Design: Corner/endpoints/envelope_error_shape_on_validation_failure
        """
        resp = api_client.create_project(
            {"address": "no name given", "lot_area_sqft": 12000}, ADMIN
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["response_type"] == "error"
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert isinstance(body["data"]["message"], str) and len(body["data"]["message"]) > 0

    def test_project_create_computed_input_ignored(self):
        """PRD §3.1: "A new project is born in `DRAFT` status with `work_posture`
        `WORKABLE`: every tonnage counter ... reads zero, the
        `cumulative_exposure_score` is zero, `diversion_rate` is zero"

        Design: Corner/entities/project_create_computed_input_ignored
        """
        resp = api_client.create_project(
            create_project_payload(
                name="Computed", address="6 Pine St", lot_area_sqft=12000,
                diversion_rate=0.99, cumulative_exposure_score=500,
            ),
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert data["diversion_rate"] == 0
        assert data["cumulative_exposure_score"] == 0


class TestAuth:
    def test_request_missing_auth_headers_returns_unauthenticated(self):
        """PRD §2.1: "A request missing either header, or carrying a role string
        the system does not declare, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
        """
        resp = api_client.create_project(
            create_project_payload(name="NoAuth", address="50 Pine St", lot_area_sqft=12000),
            headers={"Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbac:
    def test_rbac_surveyor_cannot_create_project(self):
        """PRD §2.1: "each endpoint restricts which roles may call it; a caller
        whose role is not listed for the endpoint is rejected with `ERR_FORBIDDEN`."
        PRD §4: POST /demolition/projects — "Create a demolition project | ContractorAdmin"

        Design: Corner/rbac/rbac_surveyor_cannot_create_project
        """
        resp = api_client.create_project(
            create_project_payload(name="Nope", address="1 Role St", lot_area_sqft=12000),
            SURVEYOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_rbac_hauler_cannot_certify_engineering(self):
        """PRD §2.1: "each endpoint restricts which roles may call it; a caller
        whose role is not listed for the endpoint is rejected with `ERR_FORBIDDEN`."
        PRD §4: POST /demolition/engineering-surveys/{id}/transition —
        "Engineering transitions: SUBMIT, CERTIFY, REQUEST_REVISION |
        StructuralEngineer, PeerReviewEngineer"

        Design: Corner/rbac/rbac_hauler_cannot_certify_engineering
        """
        project = create_project(name="RoleGate", address="3 Role St", lot_area_sqft=12000)
        es = get_success_data(
            api_client.create_engineering_survey(
                project["id"], create_engineering_survey_payload(),
                make_structural_engineer_headers("rg-a-1"),
            )
        )
        get_success_data(
            api_client.transition_engineering_survey(
                es["id"], {"action": "SUBMIT"}, make_structural_engineer_headers("rg-a-1")
            )
        )
        resp = api_client.transition_engineering_survey(
            es["id"], {"action": "CERTIFY"}, TEST_USERS["hauling_dispatcher_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(
            api_client.list_engineering_surveys(project["id"], SUPERVISOR)
        )
        assert after[0]["status"] == "SUBMITTED"

    def test_rbac_monitor_cannot_read_debris_tickets(self):
        """PRD §2.1: "each endpoint restricts which roles may call it; a caller
        whose role is not listed for the endpoint is rejected with `ERR_FORBIDDEN`."
        PRD §4: GET /demolition/projects/{id}/debris-tickets — "List the debris
        tickets of a project; optional filter `status` | ContractorAdmin,
        SiteSupervisor, HaulingDispatcher"

        Design: Corner/rbac/rbac_monitor_cannot_read_debris_tickets
        """
        project = create_project(name="ReadGate", address="5 Role St", lot_area_sqft=12000)
        resp = api_client.list_debris_tickets(
            project["id"], TEST_USERS["environmental_monitor_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_rbac_clock_set_non_admin_forbidden(self):
        """PRD §2.4: "An admin-only test-driving capability advances the logical
        clock to a supplied `to_iso8601` instant (an ISO 8601 UTC timestamp)"
        PRD §2.1: "a caller whose role is not listed for the endpoint is rejected
        with `ERR_FORBIDDEN`."

        Design: Corner/rbac/rbac_clock_set_non_admin_forbidden
        """
        resp = api_client.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSegregationOfDuties:
    def test_sod_abatement_certify_by_starter_rejected(self):
        """PRD §2.8: "The `ClearanceOfficer` certifying an abatement clearance
        must present an `X-User-ID` different from the order's
        `started_by_user_id`."
        PRD §3.2: "an `X-User-ID` matching `started_by_user_id` is rejected with
        `ERR_SOD_VIOLATION`."

        Design: Corner/rbac/sod_abatement_certify_by_starter_rejected
        """
        project = create_project(name="SoD1", address="7 Role St", lot_area_sqft=12000)
        survey = create_and_complete_survey(project["id"], hazmat_found=True)
        ab = get_success_data(
            api_client.create_abatement(survey["id"], create_abatement_payload(), SURVEYOR)
        )
        get_success_data(
            api_client.transition_abatement(
                ab["id"], {"action": "START"}, make_abatement_supervisor_headers("ab-1")
            )
        )
        get_success_data(
            api_client.transition_abatement(
                ab["id"], {"action": "REQUEST_CLEARANCE"},
                make_abatement_supervisor_headers("ab-1"),
            )
        )
        resp = api_client.transition_abatement(
            ab["id"], {"action": "CERTIFY_CLEARANCE"}, make_clearance_officer_headers("ab-1")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        listed = get_success_data(api_client.list_abatements(survey["id"], SURVEYOR))
        assert listed[0]["status"] == "CLEARANCE_PENDING"

    def test_sod_utility_confirm_by_verifier_rejected(self):
        """PRD §2.8: "The `UtilityCoordinator` confirming a utility disconnect
        must differ from the operator recorded as `verified_by_user_id` on that
        same disconnect."
        PRD §3.3: "an `X-User-ID` equal to `verified_by_user_id` is rejected with
        `ERR_SOD_VIOLATION`."

        Design: Corner/rbac/sod_utility_confirm_by_verifier_rejected
        """
        project = create_project(name="SoD2", address="9 Role St", lot_area_sqft=12000)
        ud = get_success_data(
            api_client.create_utility_disconnect(
                project["id"], create_utility_disconnect_payload(),
                TEST_USERS["utility_coordinator_headers"],
            )
        )
        get_success_data(
            api_client.transition_utility_disconnect(
                ud["id"], {"action": "REPORT_DISCONNECTED"},
                make_utility_coordinator_headers("ut-0"),
            )
        )
        get_success_data(
            api_client.transition_utility_disconnect(
                ud["id"], {"action": "VERIFY"}, make_utility_coordinator_headers("ut-1")
            )
        )
        resp = api_client.transition_utility_disconnect(
            ud["id"], {"action": "CONFIRM"}, make_utility_coordinator_headers("ut-1")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        ok = api_client.transition_utility_disconnect(
            ud["id"], {"action": "CONFIRM"}, make_utility_coordinator_headers("ut-2")
        )
        data = validate_success(ok)
        assert data["verification_status"] == "CONFIRMED"

    def test_sod_engineering_certify_by_author_rejected(self):
        """PRD §2.8: "The `PeerReviewEngineer` certifying an engineering survey
        must differ from its `author_user_id`. Any of these collisions is rejected
        with `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/sod_engineering_certify_by_author_rejected
        """
        project = create_project(name="SoD3", address="11 Role St", lot_area_sqft=12000)
        es = get_success_data(
            api_client.create_engineering_survey(
                project["id"], create_engineering_survey_payload(),
                make_structural_engineer_headers("eng-9"),
            )
        )
        get_success_data(
            api_client.transition_engineering_survey(
                es["id"], {"action": "SUBMIT"}, make_structural_engineer_headers("eng-9")
            )
        )
        resp = api_client.transition_engineering_survey(
            es["id"], {"action": "CERTIFY"}, make_peer_review_engineer_headers("eng-9")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        ok = api_client.transition_engineering_survey(
            es["id"], {"action": "CERTIFY"}, make_peer_review_engineer_headers("eng-10")
        )
        assert validate_success(ok)["status"] == "CERTIFIED"
