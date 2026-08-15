"""RBAC exclusivity and segregation-of-duties rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_ordering_at_window_end,
    create_approved_claim,
    create_claim,
    create_group,
    create_payment_payload,
    create_product,
    create_return_request,
    create_seller,
    create_submitted_paid_order,
    drive_campaign_to_distribution_complete,
    drive_campaign_to_sorted,
    get_order_line_id,
    get_success_data,
    make_admin_headers,
    make_supplier_rep_headers,
    make_treasurer_headers,
    record_and_clear_payment,
    reset_clock,
    setup_campaign_group_product,
    setup_open_campaign_with_seller,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
TREAS = TEST_USERS["treasurer_headers"]
SUPP = TEST_USERS["supplier_rep_headers"]
TREAS2 = make_treasurer_headers("treas-2")


class TestAuthPriority:
    def test_unauthenticated_beats_not_found(self, api):
        """PRD §2.10: "First the authentication and role checks of §2.1
        (`ERR_UNAUTHENTICATED`, then `ERR_UNAUTHORIZED_ROLE`). Second,
        path-segment existence, left to right (the 404 family above)."
        PRD §2.1: "A request missing either header, or carrying a role value
        outside this declared set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/unauthenticated_beats_not_found
        """
        resp = api._request(
            "GET",
            "/fundraiser/campaigns/8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_open_campaign_wrong_role_forbidden(self, api):
        """PRD §2.10: "First the authentication and role checks of §2.1
        (`ERR_UNAUTHENTICATED`, then `ERR_UNAUTHORIZED_ROLE`). Second,
        path-segment existence, left to right (the 404 family above)."
        PRD §2.1: "When the headers are present but the acting role is not
        listed among an endpoint's permitted roles, the request is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/validations/open_campaign_wrong_role_forbidden
        """
        resp = api.open_campaign(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", TREAS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_seller_create_schema_beats_body_fk_existence(self, api):
        """PRD §2.10: "Third, request-body schema validation — required
        fields present, types and enum members valid, integer ranges
        respected, non-empty line arrays — rejected with `ERR_VALIDATION`
        (HTTP 400)".
        PRD §2.10: "Fifth, body foreign keys must resolve to existing
        entities, each yielding its entity-specific 404".

        Design: Corner/validations/seller_create_schema_beats_body_fk_existence
        """
        resp = api.create_seller(
            {"group_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"}, COORD)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestRoleExclusivity:
    def test_supplier_rep_cannot_create_product_forbidden(self, api):
        """PRD §4: "| POST | `/fundraiser/products` | Create product (campaign
        DRAFT only) | FundraiserAdmin |".
        PRD §2.1: "When the headers are present but the acting role is not
        listed among an endpoint's permitted roles, the request is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/supplier_rep_cannot_create_product_forbidden
        """
        reset_clock()
        campaign = get_success_data(api.create_campaign({
            "name": "Fall Sale", "school_name": "Lincoln",
            "order_window_start": "2026-08-01T00:00:00Z",
            "order_window_end": "2026-08-20T00:00:00Z",
            "expected_delivery_date": "2026-09-05T00:00:00Z",
            "default_profit_share_bps": 5000,
        }, ADMIN))
        resp = api.create_product(
            {"campaign_id": campaign["id"], "name": "Bar", "sku": "BAR-01",
             "unit_price_cents": 1000, "supplier_unit_cost_cents": 600,
             "case_pack_size": 12},
            SUPP)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_coordinator_cannot_record_payment_forbidden(self, api):
        """PRD §3.2: "Payments are the `Treasurer`'s domain."
        PRD §2.1: "When the headers are present but the acting role is not
        listed among an endpoint's permitted roles, the request is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/coordinator_cannot_record_payment_forbidden
        """
        reset_clock()
        _c, _g, product, seller = setup_open_campaign_with_seller()
        order = get_success_data(api.create_order(
            {"seller_id": seller["id"], "family_contact_name": "Fam1",
             "lines": [{"product_id": product["id"], "quantity": 1}]}, COORD))
        get_success_data(api.submit_order(order["id"], COORD))
        resp = api.create_payment(
            create_payment_payload(order_id=order["id"]), COORD)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_admin_cannot_record_payment_forbidden(self, api):
        """PRD §3.2: "Payments are the `Treasurer`'s domain."
        PRD §2.1: "When the headers are present but the acting role is not
        listed among an endpoint's permitted roles, the request is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/admin_cannot_record_payment_forbidden
        """
        reset_clock()
        _c, _g, product, seller = setup_open_campaign_with_seller()
        order = get_success_data(api.create_order(
            {"seller_id": seller["id"], "family_contact_name": "Fam1",
             "lines": [{"product_id": product["id"], "quantity": 1}]}, COORD))
        get_success_data(api.submit_order(order["id"], COORD))
        resp = api.create_payment(
            create_payment_payload(order_id=order["id"]), ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_treasurer_cannot_approve_claim_forbidden(self, api):
        """PRD §3.6: "A `FundraiserAdmin` other than the reporter (segregation
        per §2.9) approves or denies a `SUBMITTED` claim, stamping
        `reviewed_by_user_id`".
        PRD §2.1: "When the headers are present but the acting role is not
        listed among an endpoint's permitted roles, the request is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/treasurer_cannot_approve_claim_forbidden
        """
        reset_clock()
        campaign, group, product, seller = setup_open_campaign_with_seller()
        order = create_submitted_paid_order(seller["id"], product["id"], 2)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_sorted(campaign["id"], product["id"], 12)
        line_id = get_order_line_id(order["id"])
        claim = create_claim(order["id"], line_id, 1, "DAMAGED")
        resp = api.approve_claim(claim["id"], TREAS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = get_success_data(api.get_claim(claim["id"], ADMIN))
        assert after["status"] == "SUBMITTED"

    def test_coordinator_cannot_read_ledger_forbidden(self, api):
        """PRD §4: "| GET | `/fundraiser/groups/{id}/ledger` | Ledger entries
        of a group, ordered (created_at ASC, seq ASC) | FundraiserAdmin,
        Treasurer |".
        PRD §2.1: "When the headers are present but the acting role is not
        listed among an endpoint's permitted roles, the request is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/coordinator_cannot_read_ledger_forbidden
        """
        reset_clock()
        campaign, group, _p = setup_campaign_group_product()
        resp_coord = api.list_group_ledger(group["id"], COORD)
        validate_error(resp_coord, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        resp_supp = api.list_group_ledger(group["id"], SUPP)
        validate_error(resp_supp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestSegregationOfDuties:
    def test_supplier_deliver_by_acknowledger_sod_rejected(self, api):
        """PRD §2.9: "The `SupplierRep` confirming delivery of a supplier
        order must not be the representative who acknowledged it — the acting
        `X-User-ID` must differ from the supplier order's
        `acknowledged_by_user_id`."

        Design: Corner/rbac/supplier_deliver_by_acknowledger_sod_rejected
        """
        reset_clock()
        campaign, group, product, seller = setup_open_campaign_with_seller()
        create_submitted_paid_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        so = get_success_data(
            api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN))
        get_success_data(api.submit_supplier_order(so["id"], ADMIN))
        ack_payload = {
            "confirmed_delivery_date": "2026-09-05T00:00:00Z",
            "line_costs": [{"product_id": product["id"],
                            "unit_cost_actual_cents": 600}],
        }
        get_success_data(api.acknowledge_supplier_order(so["id"], ack_payload,
                                                        SUPP))
        deliver_payload = {
            "actual_delivery_date": "2026-09-05T00:00:00Z",
            "delivered": [{"product_id": product["id"], "delivered_units": 12}],
        }
        # Same X-User-ID (supp-1) acknowledged; delivery by supp-1 is SOD-blocked.
        resp = api.deliver_supplier_order(so["id"], deliver_payload, SUPP)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = get_success_data(api.get_supplier_order(so["id"], ADMIN))
        assert after["status"] == "ACKNOWLEDGED"

    def test_claim_approve_by_reporter_sod_rejected(self, api):
        """PRD §2.9: "The `FundraiserAdmin` approving or denying a
        reconciliation claim must not be the `GroupCoordinator` who reported
        it — the acting `X-User-ID` must differ from the claim's
        `reported_by_user_id`."

        Design: Corner/rbac/claim_approve_by_reporter_sod_rejected
        """
        reset_clock()
        campaign, group, product, seller = setup_open_campaign_with_seller()
        order = create_submitted_paid_order(seller["id"], product["id"], 2)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_sorted(campaign["id"], product["id"], 12)
        line_id = get_order_line_id(order["id"])
        claim = create_claim(order["id"], line_id, 1, "MISSING")
        # Reporter was coord-1; an admin acting with the same user id is SOD-blocked.
        same_id_admin = make_admin_headers("coord-1")
        resp = api.approve_claim(claim["id"], same_id_admin)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_return_approve_by_requester_sod_rejected(self, api):
        """PRD §2.9: "The `Treasurer` approving or rejecting a return request
        must not be the `GroupCoordinator` who filed it — the acting
        `X-User-ID` must differ from the return's `requested_by_user_id`."

        Design: Corner/rbac/return_approve_by_requester_sod_rejected
        """
        reset_clock()
        campaign, group, product, seller = setup_open_campaign_with_seller()
        order = create_submitted_paid_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_distribution_complete(
            campaign["id"], product["id"], 12)
        reset_clock("2026-09-08T10:00:00Z")
        line_id = get_order_line_id(order["id"])
        ret = create_return_request(seller["id"], order["id"], line_id, 1,
                                    "UNSOLD")
        # Requester was coord-1; a treasurer acting as coord-1 is SOD-blocked.
        same_id_treasurer = make_treasurer_headers("coord-1")
        resp = api.approve_return_request(ret["id"], same_id_treasurer)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        approved = get_success_data(
            api.approve_return_request(ret["id"], TREAS2))
        assert approved["status"] == "APPROVED"

    def test_payment_refund_by_recorder_sod_rejected(self, api):
        """PRD §2.9: "The `Treasurer` refunding a payment must not be the
        treasurer who recorded it — the acting `X-User-ID` must differ from
        the payment's `recorded_by_user_id`."

        Design: Corner/rbac/payment_refund_by_recorder_sod_rejected
        """
        reset_clock()
        campaign, group, product, seller = setup_open_campaign_with_seller()
        order = create_submitted_paid_order(seller["id"], product["id"], 1)
        from test_helpers import validate_paginated
        payments, _m = validate_paginated(
            api.list_order_payments(order["id"], TREAS))
        payment_id = payments[0]["id"]
        # treas-1 recorded the payment; treas-1 cannot refund it.
        resp = api.refund_payment(payment_id, {"amount_cents": 1000}, TREAS)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        refunded = get_success_data(
            api.refund_payment(payment_id, {"amount_cents": 1000}, TREAS2))
        assert refunded["status"] == "REFUNDED"

    def test_payment_void_by_non_recorder_rejected(self, api):
        """PRD §2.9: "A related but distinct rule governs voids: only the
        treasurer who recorded a payment may void it. A void attempted by any
        other user is rejected with `ERR_NOT_PAYMENT_RECORDER` (HTTP 403)."

        Design: Corner/rbac/payment_void_by_non_recorder_rejected
        """
        reset_clock()
        campaign, group, product, seller = setup_open_campaign_with_seller()
        from test_helpers import create_and_submit_order
        order = create_and_submit_order(seller["id"], product["id"], 1)
        resp = api.create_payment(
            create_payment_payload(order_id=order["id"], amount_cents=500,
                                   method="CASH"),
            TREAS)
        payment = validate_success(resp, 201)
        # treas-2 did not record the payment.
        other = api.void_payment(payment["id"], TREAS2)
        validate_error(other, ApiErrorId.ERR_NOT_PAYMENT_RECORDER)
        voided = get_success_data(api.void_payment(payment["id"], TREAS))
        assert voided["status"] == "VOIDED"
