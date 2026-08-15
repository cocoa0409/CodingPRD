"""Response envelope shape, not-found handling, and role-based access control."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_payment_payload,
    create_season_payload,
    create_visit_session_payload,
    offline_session_record,
    setup_operating_day,
    setup_paid_session,
    upload_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["farm_manager_headers"]
GATE = TEST_USERS["gate_staff_headers"]
FIELD_STAFF = TEST_USERS["field_staff_headers"]
KIOSK = TEST_USERS["kiosk_device_headers"]
ANON = TEST_USERS["anonymous_headers"]


class TestResponseEnvelope:
    def test_response_envelope_shape_on_success_and_error(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body"
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        resp = api.create_season(create_season_payload(), MANAGER)
        season = validate_success(resp, 201)
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"]
        assert body["data"]["id"] == season["id"]

        err_resp = api.get_season(NON_EXISTENT_UUID, MANAGER)
        err = validate_error(err_resp, "ERR_NOT_FOUND", 404)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err["message"].strip(), "error message must be non-empty"


class TestNotFound:
    def test_field_get_not_found_returns_404(self, api):
        """PRD §2.7: "path-template identifiers are resolved left to right
        (season before field before window, and so on); an unresolvable path id
        yields `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/field_get_not_found_returns_404
        """
        resp = api.get_field("12345678-1234-1234-1234-123456789abc", MANAGER)
        validate_error(resp, "ERR_NOT_FOUND", 404)


class TestAuthentication:
    def test_seasons_create_unauthenticated_without_role(self, api):
        """PRD §2.1: "A missing `X-User-Role`, a role string that names no
        declared role, or a missing `X-User-ID` for any role other than
        `Anonymous` is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)"

        Design: Corner/rbac/seasons_create_unauthenticated_without_role
        """
        unknown_role = {
            "X-User-ID": "test-stranger-1",
            "X-User-Role": "UnknownRole",
            "Content-Type": "application/json",
        }
        resp = api.create_season(create_season_payload(), unknown_role)
        validate_error(resp, "ERR_UNAUTHENTICATED", 401)


class TestAuthorization:
    def test_field_staff_cannot_create_season(self, api):
        """PRD §2.1: "when the presented role is not in the endpoint's
        authorized role list, the request is rejected with `ERR_FORBIDDEN`
        (HTTP 403)"
        PRD §4: POST /farm/seasons is authorized for FarmManager only.

        Design: Corner/rbac/field_staff_cannot_create_season
        """
        resp = api.create_season(create_season_payload(), FIELD_STAFF)
        validate_error(resp, "ERR_FORBIDDEN", 403)

    def test_anonymous_cannot_create_session(self, api):
        """PRD §2.1: "when the presented role is not in the endpoint's
        authorized role list, the request is rejected with `ERR_FORBIDDEN`
        (HTTP 403); this authorization check applies to all endpoints"
        PRD §4: POST /farm/visit-sessions is authorized for GateStaff and
        FarmManager only.

        Design: Corner/rbac/anonymous_cannot_create_session
        """
        payload = create_visit_session_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID)
        resp = api.create_visit_session(payload, ANON)
        validate_error(resp, "ERR_FORBIDDEN", 403)

    def test_gate_staff_cannot_refund(self, api):
        """PRD §3.7: "Manual refunds are a `FarmManager`-only act against a
        `SETTLED` or `PARTIALLY_REFUNDED` charge payment."

        Design: Corner/rbac/gate_staff_cannot_refund
        """
        world = setup_operating_day()
        session = setup_paid_session(world, container_count=1)
        rows, _ = validate_paginated(
            api.list_payments(MANAGER, params={"session_id": session["id"]}))
        pay_id = rows[0]["id"]

        resp = api.refund_payment(pay_id, 100, GATE)
        validate_error(resp, "ERR_FORBIDDEN", 403)

        after = validate_success(api.get_payment(pay_id, MANAGER))
        assert after["refunded_amount_cents"] == 0, (
            "The forbidden refund mutated nothing")

    def test_kiosk_device_narrow_surface(self, api):
        """PRD §3.9: "A `KioskDevice` (or a `FarmManager`) submits a batch with
        `device_id`, a client-chosen `batch_id`, and a `records` array"
        PRD §2.1: "when the presented role is not in the endpoint's authorized
        role list, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)"

        Design: Corner/rbac/kiosk_device_narrow_surface
        """
        world = setup_operating_day()
        resp = api.create_payment(
            create_payment_payload(NON_EXISTENT_UUID, amount_cents=100,
                                   idempotency_key="kx"),
            KIOSK)
        validate_error(resp, "ERR_FORBIDDEN", 403)

        record = offline_session_record(
            1, "SK1", window_id=world["window_id"], waiver_id=world["waiver_id"],
            pricing_policy_id=world["policy_id"], party_size=1)
        batch = upload_batch("DEV-K", "BK-1", [record])
        assert batch["status"] == "APPLIED"

        fetched = validate_success(api.get_offline_batch(batch["id"], KIOSK))
        assert fetched["id"] == batch["id"], "KioskDevice can read its batch back"

    def test_priority_authz_before_not_found(self, api):
        """PRD §2.7: "Every request passes through an ordered validation
        pipeline, and the first failing gate wins — its error is the one
        returned, even if a later gate would also have failed."
        PRD §2.7: "the acting role must appear in the endpoint's role list
        (`ERR_FORBIDDEN`, 403), applied to every endpoint."

        Design: Corner/validations/priority_authz_before_not_found
        """
        # FieldStaff is outside the waiver-read role list; the probed id does
        # not exist either, and authorization must win over path resolution.
        resp = api.get_waiver("12345678-1234-1234-1234-123456789abc", FIELD_STAFF)
        validate_error(resp, "ERR_FORBIDDEN", 403)
