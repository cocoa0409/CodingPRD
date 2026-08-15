"""Auth headers, role authorization, ownership scope, and segregation walls."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_active_agreement,
    create_agreement_payload,
    create_annual_invoice,
    create_applicant_client,
    create_approved_ingredient,
    create_certifiable_product,
    create_facility_for,
    create_prospect_client,
    create_submitted_ingredient,
    get_client_version,
    make_client_contact_headers,
    make_officer_headers,
    make_supervisor_headers,
    setup_certified_client,
    validate_error,
    validate_success,
)


class TestAuthHeaders:
    def test_missing_auth_headers_returns_unauthenticated(
            self, api, account_manager_headers):
        """PRD section 2.1: "A request missing either header, or carrying an
        `X-User-Role` value outside the six declared roles, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        client = create_prospect_client(legal_name="Auth Co")
        resp = api.get_client(client["id"], {})
        validate_error(resp,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_error_envelope_shape_on_failure(self, api,
                                             account_manager_headers):
        """PRD section 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
        unique, machine-readable string that identifies the specific error."

        Design: Corner/endpoints/error_envelope_shape_on_failure
        """
        resp = api.get_client(NON_EXISTENT_UUID, account_manager_headers)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        data = body["data"]
        assert data["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(data.get("message"), str) and data["message"].strip()


class TestRoleAuthorization:
    def test_client_contact_cannot_create_agreement_forbidden(self, api):
        """PRD section 2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)". PRD section
        4: POST /api/agreements is an `AccountManager` endpoint.

        Design: Corner/validations/client_contact_cannot_create_agreement_forbidden
        """
        client = create_applicant_client(legal_name="RB1 Co")
        resp = api.create_agreement(
            create_agreement_payload(client["id"],
                                     get_client_version(client["id"])),
            make_client_contact_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_field_supervisor_cannot_approve_ingredient(
            self, api, reviewer_headers):
        """PRD section 2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)". PRD section
        4: POST /api/ingredients/{id}/approve is a `CertificationReviewer`
        endpoint.

        Design: Corner/rbac/field_supervisor_cannot_approve_ingredient
        """
        client = create_prospect_client(legal_name="RB5 Co")
        ing = create_submitted_ingredient(client["id"], name="IR5")
        validate_success(api.start_ingredient_review(ing["id"],
                                                     reviewer_headers))
        resp = api.approve_ingredient(ing["id"],
                                      make_supervisor_headers("sup-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_certificate_officer_cannot_record_payment(self, api):
        """PRD section 2.9: "On the fiscal side, the `AccountManager` records
        payments and the `CertificateOfficer` issues certificates". PRD section
        4: POST /api/invoices/{id}/record-payment is an `AccountManager`
        endpoint.

        Design: Corner/rbac/certificate_officer_cannot_record_payment
        """
        client = create_applicant_client(legal_name="RB6 Co")
        create_facility_for(client["id"], name="FR6")
        agreement = create_active_agreement(client["id"])
        invoice = create_annual_invoice(client["id"], agreement["id"])
        assert invoice["status"] == "ISSUED"
        resp = api.record_payment(invoice["id"], make_officer_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestOwnershipScope:
    def test_cross_client_ingredient_create_scope_violation(self, api):
        """PRD section 2.1: "ownership checks on any client-owned resource —
        facilities, ingredients, products, product-ingredient junctions,
        findings raised at the client's facilities, holiday windows at the
        client's facilities — compare the resource's owning `client_id` to
        `X-User-ID`, and a mismatch is rejected with
        `ERR_CLIENT_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/validations/cross_client_ingredient_create_scope_violation
        """
        client_a = create_prospect_client(legal_name="A Co",
                                          contact_email="a2@x.com")
        client_b = create_prospect_client(legal_name="B Co",
                                          contact_email="b3@x.com")
        resp = api.create_ingredient(
            {"client_id": client_b["id"], "name": "Sneaky",
             "manufacturer": "M", "source_category": "PLANT"},
            make_client_contact_headers(client_a["id"]))
        validate_error(resp, ApiErrorId.ERR_CLIENT_SCOPE_VIOLATION)


class TestAddProductGateOrdering:
    def test_add_product_state_suspended_beats_referential_cross_client(
            self, api, officer_headers):
        """PRD section 2.8: "Only then are entity-state gates evaluated (the
        family of `ERR_*_INVALID_STATE` errors), then business-safety compliance
        gates (documentation, open findings, equipment, segregation, risk), then
        cross-entity referential integrity". PRD section 3.7:
        "Adding products to an `ACTIVE` certificate is atomic".

        Design: Difficulty/priority_pair_validation_conflict/add_product_state_suspended_beats_referential_cross_client
        """
        ctx = setup_certified_client(legal_name="State A Co")
        other = create_prospect_client(legal_name="Other B Co",
                                       contact_email="ob@x.com")
        ing_b = create_approved_ingredient(other["id"], name="IngSB")
        product_b = create_certifiable_product(other["id"], [ing_b["id"]],
                                               name="PSB1")

        validate_success(api.suspend_certificate(ctx["certificate"]["id"],
                                                 officer_headers))
        resp = api.add_certificate_products(
            ctx["certificate"]["id"], [product_b["id"]],
            make_officer_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_INVALID_STATE)

        cert = validate_success(api.get_certificate(ctx["certificate"]["id"],
                                                    officer_headers))
        assert cert["active_product_count"] == 1, "no partial addition"

    def test_add_product_state_gate_without_referential_violation(
            self, api, officer_headers):
        """PRD section 2.8: "Only then are entity-state gates evaluated (the
        family of `ERR_*_INVALID_STATE` errors)". PRD section 3.7: "Adding
        products to an `ACTIVE` certificate is atomic: the call names one or
        more `product_ids`, and any failure rejects the whole call."

        Design: Difficulty/priority_pair_validation_conflict/add_product_state_suspended_beats_referential_cross_client
        """
        ctx = setup_certified_client(legal_name="State A Co 2")
        same_client_product = create_certifiable_product(
            ctx["client"]["id"], [ctx["ingredients"][0]["id"]], name="PSA2")

        validate_success(api.suspend_certificate(ctx["certificate"]["id"],
                                                 officer_headers))
        resp = api.add_certificate_products(
            ctx["certificate"]["id"], [same_client_product["id"]],
            make_officer_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_INVALID_STATE)

        cert = validate_success(api.get_certificate(ctx["certificate"]["id"],
                                                    officer_headers))
        assert cert["active_product_count"] == 1
