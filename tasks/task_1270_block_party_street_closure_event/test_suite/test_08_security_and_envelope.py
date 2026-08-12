"""RBAC enforcement and response envelope shape (PRD §2.1, §2.2, §2.11, §4)."""
import pytest

from test_helpers import (
    NEIGHBOR,
    NON_EXISTENT_UUID,
    OFFICER,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_application_record,
    create_segment_record,
    create_tcp_record,
    is_iso8601_timestamp,
    make_organizer_headers,
    setup_draft_application,
    setup_petition,
    setup_under_review_application,
    submit_tcp_record,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["city_admin_headers"]
TRAFFIC = TEST_USERS["traffic_reviewer_headers"]
DEPOT_1 = TEST_USERS["depot_officer_1_headers"]


class TestAuthenticationAndAuthorization:
    def test_unknown_role_rejected_401(self, api):
        """PRD §2.1: "A request missing either header, or presenting an `X-User-Role` value
        outside that set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unknown_role_returns_401
        """
        res = api.create_street_segment(
            {
                "name": "X", "jurisdiction": "CITY", "segment_kind": "RESIDENTIAL",
                "household_count": 5, "length_m": 10,
            },
            build_user_headers("rogue-1", "SuperUser"),
        )
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_organizer_cannot_verify_own_petition(self, api):
        """PRD §4: "| POST | `/petitions/{id}/verify` | Verify a petition or mark it deficient | PermitOfficer |".
        PRD §2.1: "A request whose role is recognized but not permitted for the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/validations/organizer_cannot_verify_own_petition_returns_403
        """
        ctx = setup_petition(outcome="submitted")
        res = api.verify_petition(
            ctx["petition"]["id"], {"decision": "APPROVE"},
            make_organizer_headers(ctx["organizer"]["id"]),
        )
        validate_error(res, "ERR_UNAUTHORIZED")

    def test_other_organizer_cannot_submit_petition(self, api):
        """PRD §2.1: "The `Organizer` role is entity-backed: when `X-User-Role` is
        `Organizer`, `X-User-ID` is the `id` of the acting Organizer record, and ownership
        checks on any resource that traces back to an Organizer — a petition, a permit
        application, and everything created beneath an application such as plans, insurance
        records, reservations, the pool, the deposit, and the post-event report — compare
        the resource's owning `organizer_id` to `X-User-ID`; a mismatch is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/validations/organizer_b_cannot_touch_organizer_a_petition_returns_403
        """
        ctx = setup_petition(outcome="collecting", signatures=[])
        other = validate_success(
            api.create_organizer(
                {"full_name": "Ben B", "email": "b@example.com", "phone": "555-37",
                 "address": "2 Pine St"},
                TEST_USERS["anonymous_headers"],
            ),
            201,
        )
        res = api.submit_petition(ctx["petition"]["id"], make_organizer_headers(other["id"]))
        validate_error(res, "ERR_NOT_RESOURCE_OWNER")

    def test_depot_officer_cannot_review_tcp(self, api):
        """PRD §4: "| POST | `/traffic-control-plans/{id}/review` | Traffic reviewer decision (approve or request changes) | TrafficReviewer |".
        PRD §2.1: "A request whose role is recognized but not permitted for the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/depot_officer_cannot_review_tcp_returns_403
        """
        ctx = setup_under_review_application(segment_overrides={"length_m": 12})
        tcp = create_tcp_record(ctx["application"], ctx["organizer"], barricade_count=1)
        submit_tcp_record(tcp["id"], ctx["organizer"])
        res = api.review_traffic_control_plan(tcp["id"], {"decision": "APPROVE"}, DEPOT_1)
        validate_error(res, "ERR_UNAUTHORIZED")
        plan = validate_success(
            api.get_traffic_control_plan(
                tcp["id"], make_organizer_headers(ctx["organizer"]["id"])), 200
        )
        assert plan["status"] == "SUBMITTED"

    def test_neighbor_cannot_create_segment(self, api):
        """PRD §4: "| POST | `/street-segments` | Register a street segment (city configuration) | CityAdmin |".
        PRD §2.1: "A request whose role is recognized but not permitted for the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/neighbor_cannot_create_segment_returns_403
        """
        res = api.create_street_segment(
            {
                "name": "Rogue Seg", "jurisdiction": "CITY", "segment_kind": "RESIDENTIAL",
                "household_count": 5, "business_count": 0, "intersects_arterial": False,
                "length_m": 12,
            },
            NEIGHBOR,
        )
        validate_error(res, "ERR_UNAUTHORIZED")

    def test_traffic_reviewer_shared_read_access(self, api, traffic_reviewer_headers):
        """PRD §4: "| GET | `/permit-applications/{id}` | Get an application (lazy expiry evaluated on access) | Organizer, TrafficReviewer, SafetyReviewer, PermitOfficer, DepotOfficer, CityAdmin |".
        PRD §4: "| GET | `/permit-applications/{id}/traffic-control-plans` | List traffic control plans of an application (0 or 1) | Organizer, TrafficReviewer, PermitOfficer, CityAdmin |".

        Design: Corner/rbac/reviewer_shared_read_access
        """
        ctx = setup_draft_application()
        app, organizer = ctx["application"], ctx["organizer"]
        tcp = create_tcp_record(app, organizer, barricade_count=1)

        application = validate_success(api.get_permit_application(app["id"], traffic_reviewer_headers), 200)
        assert application["status"] == "DRAFT"
        plans = validate_success(api.list_traffic_control_plans(app["id"], traffic_reviewer_headers), 200)
        assert len(plans) == 1
        assert plans[0]["id"] == tcp["id"]
        assert plans[0]["status"] == "DRAFT"


class TestEnvelopeAndExistence:
    def test_get_nonexistent_petition_404(self, api, permit_officer_headers):
        """PRD §2.11: "existence is validated left to right, one segment at a time, and the
        request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does
        not resolve to an existing resource".

        Design: Corner/entities/get_nonexistent_petition_returns_404
        """
        res = api.get_petition(NON_EXISTENT_UUID, permit_officer_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_error_envelope_shape(self, api, permit_officer_headers):
        """PRD §2.2: "The `meta` object for error responses contains only `api_request_id`
        and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
        specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_shape
        """
        res = api.get_petition(NON_EXISTENT_UUID, permit_officer_headers)
        assert res.status_code == 404
        body = res.json()
        assert body["response_type"] == "error"
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))
        assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
