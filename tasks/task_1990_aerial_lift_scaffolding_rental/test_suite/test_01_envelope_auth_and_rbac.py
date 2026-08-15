"""Response envelope, authentication, and role/ownership authorization."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    ApiErrorId, create_equipment_class_payload,
    create_customer, create_equipment_class, create_contract,
    activate_contract, schedule_trip, set_clock,
    setup_active_rental, setup_draft_contract_with_line, get_line,
    make_customer_headers, make_driver_headers,
)


class TestAuthentication:
    def test_missing_headers_unauthenticated(self, api):
        """PRD §2.1: "A request with a missing or malformed header, or whose
        role is not one of the declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_headers_returns_401
        """
        res = api.list_equipment_classes(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


class TestResponseEnvelopeShape:
    def test_success_and_error_envelopes(self, api, branch_manager_headers,
                                         rental_coordinator_headers):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources." PRD §2.2: "The
        `error_id` is a unique, machine-readable string that identifies the
        specific error." PRD §2.2: "The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_shape
        """
        set_clock("2026-08-01T09:00:00Z")
        create_equipment_class(class_code="S19ENV")

        list_res = api.list_equipment_classes(branch_manager_headers)
        body = list_res.json()
        assert list_res.status_code == 200
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["response_type"] == "array", "list endpoint reads as an array"
        assert isinstance(body["data"], list) and len(body["data"]) == 1

        err_res = api.get_rental_contract(NON_EXISTENT_UUID,
                                          rental_coordinator_headers)
        err_body = err_res.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"].get("message"), str)
        assert err_body["data"]["message"].strip()


class TestRoleAuthorization:
    def test_coordinator_cannot_create_equipment_class(
            self, api, rental_coordinator_headers):
        """PRD §4: POST /equipment-classes is authorized for BranchManager
        only. PRD §2.1: "a caller whose role is not authorized for the
        operation, or who fails an ownership check described below, is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/coordinator_cannot_create_equipment_class
        """
        res = api.create_equipment_class(
            create_equipment_class_payload(class_code="NOPE"),
            rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_customer_read_other_contract_forbidden(
            self, api, rental_coordinator_headers):
        """PRD §2.1: "A `Customer` may read only its own customer record, may
        see only its own contracts and claims, and may act only on lines and
        claims belonging to its own contracts."

        Design: Corner/rbac/customer_read_other_contract_forbidden
        """
        set_clock("2026-08-01T09:00:00Z")
        reader_a = create_customer("Reader A", "a@reader.example")
        reader_b = create_customer("Reader B", "b@reader.example")
        contract = create_contract(reader_a["id"], "5 Private Pl")

        res = api.get_rental_contract(
            contract["id"], make_customer_headers(reader_b["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

        own = validate_success(api.get_rental_contract(
            contract["id"], make_customer_headers(reader_a["id"])))
        assert own["id"] == contract["id"], "the owner reads its own contract"

    def test_customer_cannot_off_rent_others_line(self, api):
        """PRD §3.4: "a `Customer` caller's identity must match the contract's
        `customer_id` (`ERR_FORBIDDEN`)."

        Design: Corner/rbac/customer_cannot_off_rent_others_line
        """
        ctx = setup_active_rental()
        intruder = create_customer("Intruder B", "b@intruder.example")

        res = api.off_rent_line(ctx["line"]["id"],
                                make_customer_headers(intruder["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        line = get_line(ctx["line"]["id"])
        assert line["status"] == "OUT_ON_RENT", "rejected off-rent changes nothing"

    def test_driver_cannot_start_unassigned_trip(self, api,
                                                 rental_coordinator_headers):
        """PRD §2.1: "the driver-only actions on that trip (starting the route
        leg, completing it, failing it) require the caller's `X-User-ID` to
        equal the trip's assigned `driver_id`, failing which the request is
        rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/driver_cannot_start_unassigned_trip
        """
        # Active contract with a RESERVED line and a SCHEDULED trip for drv-1.
        ctx = setup_draft_contract_with_line()
        activate_contract(ctx["contract"]["id"])
        trip = schedule_trip(ctx["contract"]["id"], ctx["line"]["id"],
                             "DELIVERY", "drv-1")

        res = api.start_delivery_trip(trip["id"], make_driver_headers("drv-2"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        stayed = validate_success(
            api.get_delivery_trip(trip["id"], rental_coordinator_headers))
        assert stayed["status"] == "SCHEDULED", "rejected start changes nothing"
