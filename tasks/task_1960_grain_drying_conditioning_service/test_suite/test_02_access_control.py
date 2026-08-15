"""Access control: authentication, role authorization, grower ownership,
and the error envelope shape (PRD §2.1, §2.2, §2.9)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_user_headers,
    create_charge_schedule_payload,
    create_customer,
    create_grain_lot_payload,
    create_lot,
    make_grower_headers,
    make_operator_headers,
    make_technician_headers,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which they act."
        PRD §2.1: "A request with missing or malformed headers is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        res = api.list_grain_lots(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestErrorEnvelope:
    def test_error_envelope_shape_on_not_found(self, api, manager_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "response_type": "error" and a data object
        carrying error_id and message.
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/error_envelope_shape_on_not_found
        """
        res = api.get_grain_lot(NON_EXISTENT_UUID, manager_headers)
        validate_error(res, ApiErrorId.ERR_LOT_NOT_FOUND, expected_status=404)
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_LOT_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert isinstance(body["meta"].get("api_request_id"), str)


class TestRoleAuthorization:
    def test_grower_cannot_manage_schedules(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /grain-drying/charge-schedules is authorized for
        ElevatorManager only.

        Design: Corner/rbac/grower_cannot_manage_schedules
        """
        cust = create_customer()
        res = api.create_charge_schedule(
            create_charge_schedule_payload(),
            make_grower_headers(cust["id"]),
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    def test_dryer_operator_cannot_assess_claims(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /grain-drying/damage-claims/{id}/assess is authorized for
        ClaimsAdjuster only.

        Design: Corner/rbac/dryer_operator_cannot_assess_claims
        """
        res = api.assess_damage_claim(NON_EXISTENT_UUID, make_operator_headers("op-1"))
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    def test_intake_technician_cannot_confirm_tickets(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /grain-drying/queue-tickets/{id}/confirm is authorized for
        ElevatorManager only.

        Design: Corner/rbac/intake_technician_cannot_confirm_tickets
        """
        res = api.confirm_queue_ticket(
            NON_EXISTENT_UUID, make_technician_headers("tech-1"))
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    def test_grower_other_customers_lot_forbidden(self, api, manager_headers):
        """PRD §2.1: "When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of
        the acting Customer; ownership checks on any resource that references a
        customer — a grain lot, queue ticket, damage claim, storage agreement,
        invoice, or payment — compare the resource's customer reference to
        `X-User-ID`, and a grower touching another account's resource is rejected
        with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/rbac/grower_other_customers_lot_forbidden
        """
        cust_x = create_customer(name="CX")
        cust_y = create_customer(name="CY")
        lot_y = create_lot(cust_y["id"])
        res = api.get_grain_lot(lot_y["id"], make_grower_headers(cust_x["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, expected_status=403)
        # The owning grower reads it fine.
        ok = api.get_grain_lot(lot_y["id"], make_grower_headers(cust_y["id"]))
        assert validate_success(ok, 200)["id"] == lot_y["id"]
