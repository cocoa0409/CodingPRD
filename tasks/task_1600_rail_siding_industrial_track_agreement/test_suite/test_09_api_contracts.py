"""System-wide contracts: response envelopes, status codes, auth context,
role authorization, and the not-found family (PRD §2.1, §2.2, §2.9, §4, §5).
"""
from test_helpers import (
    ENGINEER,
    INSPECTOR,
    NON_EXISTENT_UUID,
    RCM,
    TEST_USERS,
    ApiErrorId,
    assert_track_agreement,
    create_agreement_payload,
    make_active_agreement,
    make_agreement,
    make_completed_project,
    make_headers_without_role,
    make_segment,
    make_service_order,
    validate_error,
    validate_success,
)


class TestResponseEnvelope:
    def test_success_and_error_envelope_shapes(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body"
        PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format"
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/response_envelope_and_error_shape
        """
        res = api.create_agreement(create_agreement_payload(), RCM)
        body = res.json()
        assert res.status_code == 201
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert_track_agreement(body["data"])

        err_res = api.get_agreement(NON_EXISTENT_UUID, RCM)
        err_body = err_res.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_AGREEMENT_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert err_body["data"]["message"].strip()

    def test_create_returns_201_action_returns_200(self, api):
        """PRD §4: "Operations that create a new resource return a `201
        Created` status code. Operations that modify an existing resource —
        including all state transitions, sweeps applied during reads
        notwithstanding — return a `200 OK` status code, as do all reads."
        PRD §3.1: "Submission by a `RailroadContractsManager` moves the
        agreement from `DRAFT` to `PENDING_COUNTERSIGN`; attempting submission
        from any other status is rejected with `ERR_AGREEMENT_INVALID_STATE`."

        Design: Corner/endpoints/create_returns_201_action_returns_200
        """
        create_res = api.create_agreement(create_agreement_payload(), RCM)
        agreement = validate_success(create_res, 201)
        submit_res = api.submit_agreement(agreement["id"], RCM)
        submitted = validate_success(submit_res, 200)
        assert submitted["status"] == "PENDING_COUNTERSIGN", (
            "the action response carries the mutated entity"
        )


class TestAuthContext:
    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "Failure to provide both headers, or presenting a role
        outside these five, results in an
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        res = api.create_agreement(
            create_agreement_payload(), make_headers_without_role("operator-1")
        )
        validate_error(
            res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400
        )

    def test_shipper_cannot_create_agreement(self, api):
        """PRD §2.1: "Once the user context is well-formed, the caller's role
        must also be authorized for the specific operation; an attempt to
        perform an action outside of a role's designated operations is rejected
        with an `ERR_UNAUTHORIZED_ROLE` error."
        PRD §4 (endpoint table): "| POST | `/agreements` | Create a track
        agreement in DRAFT | RailroadContractsManager |"

        Design: Corner/validations/shipper_cannot_create_agreement_returns_unauthorized
        """
        shipper = TEST_USERS["shipper_facility_manager_headers"]
        res = api.create_agreement(create_agreement_payload(), shipper)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)


class TestExclusiveOperations:
    def test_exclusive_operations_denied_to_other_roles(self, api):
        """PRD §2.1: "Once the user context is well-formed, the caller's role
        must also be authorized for the specific operation; an attempt to
        perform an action outside of a role's designated operations is rejected
        with an `ERR_UNAUTHORIZED_ROLE` error."
        PRD §4 (endpoint table): "| POST |
        `/construction-projects/{projectId}/settle` | Record a cost-share
        payment (positive) or refund correction (negative); auto-settles when
        outstanding reaches exactly zero | RailroadContractsManager |"
        PRD §4 (endpoint table): "| POST | `/service-orders/{orderId}/complete`
        | Record execution (REQUESTED → COMPLETED) | RailroadServiceManager |"

        Design: Corner/rbac/exclusive_operations_denied_to_other_roles
        """
        agreement = make_active_agreement()
        project = make_completed_project(agreement["id"])
        # The engineer is a legitimate role elsewhere but may not settle.
        res1 = api.settle_project(project["id"], {"payment_cents": 100000}, ENGINEER)
        validate_error(res1, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
        segment = make_segment(agreement["id"])
        order = make_service_order(agreement["id"], segment["id"])
        # The inspector may not record service execution.
        res2 = api.complete_service_order(
            order["id"], {"cars_spotted": 2, "cars_pulled": 1}, INSPECTOR
        )
        validate_error(res2, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_all_five_roles_can_read_agreement(self, api):
        """PRD §2.1: "Once the user context is well-formed, the caller's role
        must also be authorized for the specific operation; an attempt to
        perform an action outside of a role's designated operations is rejected
        with an `ERR_UNAUTHORIZED_ROLE` error."
        PRD §4 (endpoint table): "| GET | `/agreements/{agreementId}` | Get one
        agreement (expiry sweep applied) | All five roles |"

        Design: Corner/rbac/all_roles_can_read_shared_endpoints
        """
        agreement = make_agreement()
        for headers in TEST_USERS.values():
            res = api.get_agreement(agreement["id"], headers)
            data = validate_success(res, 200)
            assert data["id"] == agreement["id"]
            assert data["status"] == "DRAFT"


class TestNotFoundSweep:
    def test_not_found_sweep_all_resources(self, api):
        """PRD §2.9: "Identifiers are validated in left-to-right order, and the
        request is rejected immediately with the 404 error corresponding to the
        first identifier that does not resolve to an existing resource:
        `ERR_AGREEMENT_NOT_FOUND` for a missing agreement,
        `ERR_AMENDMENT_NOT_FOUND` for a missing amendment,
        `ERR_PROJECT_NOT_FOUND` for a missing construction project,
        `ERR_SEGMENT_NOT_FOUND` for a missing segment, `ERR_INSPECTION_NOT_FOUND`
        for a missing inspection, `ERR_DEVICE_NOT_FOUND` for a missing derail
        device, `ERR_SERVICE_ORDER_NOT_FOUND` for a missing service order,
        `ERR_CAR_DWELL_NOT_FOUND` for a missing car dwell,
        `ERR_STORAGE_PLACEMENT_NOT_FOUND` for a missing storage placement, and
        `ERR_CLAIM_NOT_FOUND` for a missing liability claim."

        Design: Corner/errors/not_found_sweep_all_resources
        """
        checks = [
            (api.get_amendment(NON_EXISTENT_UUID, RCM),
             ApiErrorId.ERR_AMENDMENT_NOT_FOUND),
            (api.get_project(NON_EXISTENT_UUID, RCM),
             ApiErrorId.ERR_PROJECT_NOT_FOUND),
            (api.get_segment(NON_EXISTENT_UUID, RCM),
             ApiErrorId.ERR_SEGMENT_NOT_FOUND),
            (api.get_inspection(NON_EXISTENT_UUID, RCM),
             ApiErrorId.ERR_INSPECTION_NOT_FOUND),
            (api.get_device(NON_EXISTENT_UUID, RCM),
             ApiErrorId.ERR_DEVICE_NOT_FOUND),
            (api.get_service_order(NON_EXISTENT_UUID, RCM),
             ApiErrorId.ERR_SERVICE_ORDER_NOT_FOUND),
            (api.get_car_dwell(NON_EXISTENT_UUID, RCM),
             ApiErrorId.ERR_CAR_DWELL_NOT_FOUND),
            (api.get_storage_placement(NON_EXISTENT_UUID, RCM),
             ApiErrorId.ERR_STORAGE_PLACEMENT_NOT_FOUND),
            (api.get_liability_claim(NON_EXISTENT_UUID, RCM),
             ApiErrorId.ERR_CLAIM_NOT_FOUND),
        ]
        for response, error_id in checks:
            validate_error(response, error_id, 404)
