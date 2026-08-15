"""Role-based access control and structural request validation (PRD §2.1, §2.8)."""
from test_helpers import (
    ACCOUNT_MANAGER,
    NON_EXISTENT_UUID,
    OFFICER,
    PLANNER,
    SYSADMIN,
    ApiErrorId,
    build_user_headers,
    create_active_clinic,
    create_clinic_payload,
    create_order,
    create_product,
    create_product_payload,
    get_success_data,
    make_clinic_buyer_headers,
    order_line_spec,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestUserContext:
    def test_missing_or_invalid_user_context_header(self, api):
        """PRD §2.1: "A request with a missing header or an unrecognized role
        value is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/clinic_create_missing_auth_header
        """
        payload = create_clinic_payload(clinic_name="No Auth",
                                        license_number="LIC-NA")

        # No X-User-ID / X-User-Role headers at all.
        resp = api.create_clinic(payload, {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

        # Unrecognized role value.
        resp = api.create_clinic(payload, build_user_headers("test-x-1", "SuperUser"))
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleAuthorization:
    def test_rbac_exclusive_denials_sweep(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted on
        the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.8: "Every request is validated in a fixed order, and the first
        failing check determines the error returned" — role authorization (step
        2) precedes existence (step 4).

        Design: Corner/rbac/rbac_exclusive_denials_sweep
        """
        clinic = create_active_clinic(clinic_name="Clinic RB",
                                      license_number="LIC-RB")

        # ComplianceOfficer cannot create products (SupplyChainPlanner exclusive).
        resp = api.create_product(create_product_payload(
            sku="RB-1", product_name="Denied", unit_price_cents=1000), OFFICER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        # ClinicBuyer cannot onboard clinics (AccountManager exclusive).
        resp = api.create_clinic(
            create_clinic_payload(clinic_name="Self Serve", license_number="LIC-XX"),
            make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        # AccountManager cannot resolve quarantine (ComplianceOfficer exclusive);
        # role authorization fires before existence, so no 404 surfaces.
        resp = api.resolve_quarantine(NON_EXISTENT_UUID, "RELEASED", ACCOUNT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        # SystemAdmin drives the logical clock only; business reads are denied.
        resp = api.list_orders(SYSADMIN)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_approve_with_wrong_role_beats_state_check(self, api):
        """PRD §2.8: "Every request is validated in a fixed order, and the first
        failing check determines the error returned" — role authorization (step
        2: `ERR_UNAUTHORIZED_ROLE`) precedes state preconditions (step 5).
        PRD §4: POST /vet/orders/{id}/approve is authorized for AccountManager.

        Design: Corner/validations/approve_with_wrong_role_beats_state_check
        """
        clinic = create_active_clinic(clinic_name="Clinic PR",
                                      license_number="LIC-PR")
        product = create_product(sku="CONS-PR", product_name="Cotton Roll",
                                 unit_price_cents=2500)
        order = create_order(clinic["id"], [order_line_spec(product["id"], 1)])

        # Order is DRAFT (state gate would also fail) but the planner role gate
        # fires first.
        resp = api.approve_order(order["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestOwnership:
    def test_clinic_buyer_cannot_touch_other_clinic_order(self, api):
        """PRD §2.1: "A `ClinicBuyer` may run its mutation capabilities —
        creating an order, submitting an order, cancelling an order, cancelling
        a backorder line, requesting a short-date credit, and creating a bundle
        enrollment — only against resources whose `clinic_id` equals its own
        `X-User-ID`; acting on another clinic's resource is rejected with
        `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."
        PRD §2.8: ownership (step 3) precedes existence (step 4).

        Design: Corner/rbac/clinic_buyer_cannot_touch_other_clinic_order
        """
        clinic_a = create_active_clinic(clinic_name="Clinic OA",
                                        license_number="LIC-OA")
        clinic_b = create_active_clinic(clinic_name="Clinic OB",
                                        license_number="LIC-OB")

        # Clinic A's buyer orders as clinic B; the referenced product does not
        # even exist, but ownership fires first.
        resp = api.create_order(
            {
                "clinic_id": clinic_b["id"],
                "ship_to_address": clinic_b["ship_to_address"],
                "delivery_window_start": "2026-08-03T13:00:00Z",
                "delivery_window_end": "2026-08-03T15:00:00Z",
                "lines": [{"product_id": NON_EXISTENT_UUID, "qty_requested": 1}],
            },
            make_clinic_buyer_headers(clinic_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

    def test_clinic_buyer_cancels_own_draft_order(self, api):
        """PRD §3.6: "Whole-order cancellation — available to the same two
        actors — is accepted from `DRAFT`, `SUBMITTED`, `APPROVED`, or
        `BACKORDERED`, and from anywhere else is rejected with
        `ERR_ORDER_INVALID_STATE`."
        PRD §4: POST /vet/orders/{id}/cancel is authorized for ClinicBuyer and
        AccountManager.

        Design: Corner/rbac/clinic_buyer_cancels_own_draft_order
        """
        clinic = create_active_clinic(clinic_name="Clinic SC2",
                                      license_number="LIC-SC2")
        product = create_product(sku="CONS-SC2", product_name="Share Pack",
                                 unit_price_cents=2500)
        order = create_order(clinic["id"], [order_line_spec(product["id"], 1)])

        resp = api.cancel_order(order["id"], make_clinic_buyer_headers(clinic["id"]))
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"


class TestSharedReadScopes:
    def test_planner_and_officer_read_scopes_allowed(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted on
        the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP
        403)." — and the §4 endpoint table lists ComplianceOfficer among the
        authorized roles for GET /vet/inventory-lots and SupplyChainPlanner
        among those for GET /vet/orders, so both reads must succeed.

        Design: Corner/rbac/planner_and_officer_read_scopes_allowed
        """
        product = create_product(sku="RD-1", product_name="Read Pack",
                                 unit_price_cents=1000)
        lot = get_success_data(api.create_lot(
            {"product_id": product["id"], "lot_number": "LOT-RD",
             "expiry_date": "2027-06-30", "qty_on_hand": 3}, PLANNER))
        assert lot["lot_number"] == "LOT-RD"

        lots, _ = validate_paginated(
            api.list_lots(OFFICER, params={"product_id": product["id"]}))
        assert any(l["lot_number"] == "LOT-RD" for l in lots), (
            "ComplianceOfficer must be able to list lots")

        resp = api.list_orders(PLANNER)
        assert resp.status_code == 200
        assert resp.json()["response_type"] == "array"


class TestStructuralValidation:
    def test_order_create_missing_required_fields(self, api):
        """PRD §3.4: "A `ClinicBuyer` drafts an order for its own clinic by
        supplying the `clinic_id`, the `ship_to_address`, a delivery window from
        `delivery_window_start` to `delivery_window_end`, and the `lines` — each
        naming a `product_id` and a positive `qty_requested`."
        PRD §2.8: "Required fields present, enum values valid, quantities
        positive, and the ordering rules on dates and windows, otherwise
        `ERR_INVALID_REQUEST` or the specific constraint error of §3."

        Design: Corner/entities/order_create_missing_required_fields_returns_invalid_request
        """
        resp = api.create_order(
            {
                "ship_to_address": "22 Nowhere Rd",
                "delivery_window_start": "2026-08-03T13:00:00Z",
                "delivery_window_end": "2026-08-03T15:00:00Z",
            },
            make_clinic_buyer_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_order_window_inverted_and_product_enum_invalid(self, api):
        """PRD §3.4: "The window is half-open: the end must be strictly later
        than the start, and a window whose end equals or precedes its start is
        an `ERR_INVALID_REQUEST`."
        PRD §3.2: "a `product_type` of `RX_PHARMACEUTICAL`, `VACCINE`,
        `EQUIPMENT`, or `CONSUMABLE`"
        PRD §2.8: "Required fields present, enum values valid, quantities
        positive, and the ordering rules on dates and windows, otherwise
        `ERR_INVALID_REQUEST`..."

        Design: Corner/entities/order_window_inverted_and_product_enum_invalid
        """
        clinic = create_active_clinic(clinic_name="Clinic TC",
                                      license_number="LIC-TC")

        resp = api.create_order(
            {
                "clinic_id": clinic["id"],
                "ship_to_address": clinic["ship_to_address"],
                "delivery_window_start": "2026-08-03T15:00:00Z",
                "delivery_window_end": "2026-08-03T13:00:00Z",
                "lines": [],
            },
            make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        resp = api.create_product(create_product_payload(
            sku="BAD-ENUM", product_name="Mystery", product_type="NARCOTIC",
            unit_price_cents=1000), PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_order_create_with_unknown_product_returns_not_found(self, api):
        """PRD §2.8: "Resource identifiers referenced in the path and body are
        resolved strictly left to right, and the first identifier that does not
        resolve produces the 404 for its resource type: ..."

        Design: Corner/endpoints/order_create_with_unknown_product_returns_not_found
        """
        clinic = create_active_clinic(clinic_name="Clinic FK",
                                      license_number="LIC-FK")
        resp = api.create_order(
            {
                "clinic_id": clinic["id"],
                "ship_to_address": clinic["ship_to_address"],
                "delivery_window_start": "2026-08-03T13:00:00Z",
                "delivery_window_end": "2026-08-03T15:00:00Z",
                "lines": [{"product_id": NON_EXISTENT_UUID, "qty_requested": 1}],
            },
            make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND)
