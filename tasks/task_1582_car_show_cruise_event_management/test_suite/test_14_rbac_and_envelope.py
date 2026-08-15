"""Authentication, role-level authorization, and the response envelope."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, MISSING_UUID,
    make_participant_headers, make_judge_headers,
    create_event_payload, create_class_payload,
    create_event_with_class_and_zone, create_open_event,
    create_registrant_with_vehicle, assert_event,
)

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or naming a role the system
        does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_401
        """
        resp = api.list_events(headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleGates:
    def test_participant_publish_returns_403(self, api):
        """PRD §2.1: "A recognized role attempting an operation outside its grant
        is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4: publish is
        authorized for Organizer only.

        Design: Corner/validations/participant_publish_returns_403
        """
        ev, cls, zone = create_event_with_class_and_zone()
        registrant, veh = create_registrant_with_vehicle(name="RB", email="rb@example.com")
        resp = api.publish_event(ev["id"], make_participant_headers(registrant["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_event(ev["id"], ORG))
        assert after["lifecycle_status"] == "DRAFT"

    def test_desk_cannot_finalize_returns_403(self, api):
        """PRD §4: `POST /events/{id}/tabulations/finalize` is authorized for
        Organizer only. PRD §2.1: "A recognized role attempting an operation
        outside its grant is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/desk_cannot_finalize_returns_403
        """
        ev, cls, zone = create_open_event()
        get_success_data(api.lock_registration(ev["id"], ORG))
        get_success_data(api.start_judging(ev["id"], ORG))
        observed = validate_success(api.get_event(ev["id"], ORG))
        resp = api.finalize_tabulations(
            ev["id"], {"expected_event_version": observed["version"]}, DESK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_event(ev["id"], ORG))
        assert after["version"] == observed["version"]
        assert after["lifecycle_status"] == observed["lifecycle_status"]

    def test_judge_cannot_cast_ballot_returns_403(self, api):
        """PRD §4: `POST /ballots` is authorized for Participant only. PRD §2.1:
        "A recognized role attempting an operation outside its grant is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/judge_cannot_cast_ballot_returns_403
        """
        ev, cls, zone = create_open_event()
        judge = get_success_data(api.create_judge(ev["id"], {
            "name": "JR", "email": "jr@example.com", "assigned_class_ids": []}, ORG))
        resp = api.create_ballot(
            {"event_id": ev["id"], "registration_id": MISSING_UUID},
            make_judge_headers(judge["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_participant_cannot_create_class_returns_403(self, api):
        """PRD §4: `POST /events/{id}/classes` is authorized for Organizer only.
        PRD §2.1: "A recognized role attempting an operation outside its grant is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/participant_cannot_create_class_returns_403
        """
        ev = get_success_data(api.create_event(create_event_payload(), ORG))
        registrant, veh = create_registrant_with_vehicle(name="PR2", email="pr2@example.com")
        resp = api.create_class(ev["id"], create_class_payload(code="HACK", capacity=99),
                                make_participant_headers(registrant["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        classes = get_success_data(api.list_classes(ev["id"], ORG))
        assert all(c["code"] != "HACK" for c in classes)


class TestResponseEnvelope:
    def test_response_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`." PRD §2.2: "The `response_type`
        is either "object" for a single resource or "array" for a list of
        resources." PRD §2.2: "The `error_id` is a unique, machine-readable
        string that identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape
        """
        resp = api.create_event(create_event_payload(name="Envelope"), ORG)
        assert resp.status_code == 201
        body = resp.json()
        assert "meta" in body and "data" in body
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "object"
        assert_event(body["data"])

        err_resp = api.get_event(MISSING_UUID, ORG)
        assert err_resp.status_code == 404
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"].get("message"), str)
        assert err_body["data"]["message"]
