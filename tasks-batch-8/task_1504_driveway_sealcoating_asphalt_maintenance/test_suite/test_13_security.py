"""Security: authentication context, role authorization, and customer
ownership checks."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_customer,
    create_crew,
    create_material_lot,
    create_material_payload,
    create_route_sheet,
    get_quote,
    get_work_order,
    make_customer_headers,
    post_weather_snapshot,
    send_quote,
    setup_accepted_job,
    setup_quote_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["office_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestMissingAuthHeaders:
    def test_request_without_user_context_rejected(self, api):
        """PRD §2.1: "Every request to the API must carry two headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring
        the operational capacity in which they act. A request missing either
        header, or presenting a role the system does not recognize, is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP
        400)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.create_customer(
            {
                "name": "No Header",
                "customer_type": "RESIDENTIAL",
                "email": "x@example.com",
                "phone": "1",
            },
            headers={"Content-Type": "application/json"},
        )
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400
        )
        data, _meta = validate_paginated(api.list_customers(ADMIN))
        assert data == [], "a rejected request must not persist anything"


class TestRoleDenial:
    def test_customer_cannot_create_material(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD
        §4: `POST /api/materials` is authorized for OfficeAdmin only.

        Design: Corner/rbac/rbac_customer_cannot_create_material
        """
        customer = create_customer()
        resp = api.create_material(
            create_material_payload(product_name="Sneaky"),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        data, _meta = validate_paginated(api.list_materials(ADMIN))
        assert data == [], "no material may be persisted by a Customer role"

    def test_estimator_cannot_schedule_work_order(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD
        §4: `POST /api/work-orders/{workOrderId}/schedule` is authorized for
        Dispatcher only.

        Design: Corner/rbac/rbac_estimator_cannot_schedule
        """
        ctx = setup_accepted_job(lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St")
        lot = create_material_lot(ctx["material"]["id"])
        crew = create_crew()
        sheet = create_route_sheet(crew["id"], "2026-08-10")
        post_weather_snapshot("2026-08-10")

        resp = api.schedule_work_order(
            ctx["work_order"]["id"],
            {
                "route_sheet_id": sheet["id"],
                "material_lot_id": lot["id"],
                "scheduled_date": "2026-08-10",
                "window_start_hour": 7,
                "window_end_hour": 10,
                "drive_minutes_est": 15,
                "vehicles_to_move": 1,
            },
            ESTIMATOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        assert get_work_order(ctx["work_order"]["id"])["execution_status"] == "PENDING"


class TestCustomerOwnership:
    def test_customer_cannot_accept_other_customers_quote(self, api):
        """PRD §2.1: "A customer acting on a resource owned by a different
        customer is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)." PRD
        §3.3: "Acceptance, decline, and revision-request all require the quote
        to be `SENT` (else `ERR_QUOTE_NOT_ACCEPTABLE`) and require the acting
        customer to own the quote's property (else `ERR_NOT_RESOURCE_OWNER`)."

        Design: Corner/rbac/rbac_customer_cannot_accept_other_customers_quote
        """
        ctx = setup_quote_scenario(
            lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St",
            measured_area_sqft=900, crack_linear_ft=10, pothole_count=1,
            pothole_area_sqft=2,
            customer_overrides={"name": "Dana A", "email": "a@example.com",
                                "phone": "555-1"},
        )
        other = create_customer(name="Erik B", email="b@example.com", phone="555-2")
        sent = send_quote(ctx["quote"]["id"])
        assert sent["status"] == "SENT"

        resp = api.accept_quote(ctx["quote"]["id"], make_customer_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

        assert get_quote(ctx["quote"]["id"])["status"] == "SENT", (
            "a rejected acceptance must not move the quote"
        )
