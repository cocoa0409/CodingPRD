"""Envelope shape, existence resolution, request shape, pagination, listings."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_requisition,
    create_approved_requisition,
    create_department,
    create_elevation_payload,
    create_pcard,
    create_requisition_draft,
    create_requisition_payload,
    create_surplus_asset_payload,
    create_transaction_payload,
    create_vendor,
    is_valid_uuid,
    issue_po_ok,
    make_cardholder_headers,
    make_requester_headers,
    post_invoice,
    post_receipt,
    requisition_line,
    submit_requisition_ok,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN

ADMIN_H = ADMIN


class TestCreationShapeAndEnvelope:
    def test_create_requisition_ignores_smuggled_system_fields(self, api):
        """PRD §3.3: "At creation the requisition is `DRAFT`, the server mints its
        human-readable `requisition_number` in the sequential `RQ-000001` format, and
        `total_cents` is computed as the exact integer sum over all lines of quantity
        times unit price, with no rounding."
        PRD §1: "every financial rule — approval thresholds, grant indirect-cost
        recovery, invoice tolerance, card utilization, award scoring, surplus
        proceeds — is computed by the server from pinned inputs rather than trusted
        from the client".

        Design: Corner/entities/requisition_create_with_total_cents_input_ignored
        """
        dept = create_department(name="Kinesiology")
        vendor = create_vendor(legal_name="GymCo")
        payload = create_requisition_payload(
            department_id=dept["id"],
            requester_id="req-user-9",
            vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="KIN", description="rower",
                quantity=2, unit_price_cents=125000, cost_category="EQUIPMENT",
            )],
        )
        # Client attempts to smuggle server-managed fields.
        payload["total_cents"] = 99999999
        payload["status"] = "APPROVED"
        resp = api.create_requisition(payload, make_requester_headers("req-user-9"))
        data = validate_success(resp, 201)
        assert_requisition(data)
        assert data["total_cents"] == 250000, (
            f"server must compute 2 x 125,000 = 250,000, got {data['total_cents']}"
        )
        assert data["status"] == "DRAFT"
        assert isinstance(data["version"], int)
        assert is_valid_uuid(data["id"])

    def test_requisition_create_missing_department_returns_404(self, api):
        """PRD §2.9: "Identifiers referenced inside a request body are checked for
        existence at the same rung of the ladder" — `ERR_DEPARTMENT_NOT_FOUND`,
        each with HTTP 404.

        Design: Corner/entities/create_with_missing_foreign_key_returns_404
        """
        payload = create_requisition_payload(
            department_id=NON_EXISTENT_UUID,
            requester_id="req-user-1",
            lines=[requisition_line(unit_price_cents=100)],
        )
        resp = api.create_requisition(payload, make_requester_headers("req-user-1"))
        validate_error(resp, ApiErrorId.ERR_DEPARTMENT_NOT_FOUND, 404)

    def test_shape_errors_limit_enum_and_zero_amount(self, api):
        """PRD §3.7: "The single-transaction limit may not exceed the monthly limit;
        an inconsistent pair is rejected with `ERR_LIMIT_INCONSISTENT`, both at
        issuance and on any later limits change."
        PRD §2.8: "Request shape — required fields present, enum members valid,
        quantities and amounts positive, `effective_start` strictly before
        `effective_end`, `window_start` strictly before `window_end`, and
        pagination within bounds (`ERR_INVALID_REQUEST`,
        `ERR_INVALID_PAGINATION_PARAMETERS`)".
        PRD §3.7: "Transactions are posted by the cardholder with an
        `amount_cents` that must be strictly positive for either `entry_type`".

        Design: Corner/entities/pcard_and_surplus_shape_errors_rejected
        """
        dept = create_department(name="Nursing")
        card = create_pcard(department_id=dept["id"], cardholder_name="Ann")

        bad_card = api.create_pcard(
            {
                "department_id": dept["id"],
                "cardholder_name": "Bad",
                "single_txn_limit_cents": 600000,
                "monthly_limit_cents": 500000,
                "allowed_mccs": [],
            },
            ADMIN_H,
        )
        validate_error(bad_card, ApiErrorId.ERR_LIMIT_INCONSISTENT, 422)

        bad_asset = api.create_surplus_asset(
            create_surplus_asset_payload(
                asset_tag="A-1", department_id=dept["id"], condition="BROKEN",
                estimated_value_cents=10000,
            ),
            TEST_USERS["surplus_manager_headers"],
        )
        validate_error(bad_asset, ApiErrorId.ERR_INVALID_REQUEST, 400)

        zero_txn = api.create_pcard_transaction(
            card["id"],
            create_transaction_payload(amount_cents=0, merchant_name="Zero"),
            make_cardholder_headers(card["id"]),
        )
        validate_error(zero_txn, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestExistenceResolution:
    def test_purchase_order_not_found_bare_and_nested(self, api):
        """PRD §2.9: "Wherever a path does contain more than one identifier — for
        example a child collection under a parent resource — the identifiers are
        validated strictly left to right, and the request is rejected with the 404
        error corresponding to the first identifier that does not resolve:
        `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_REQUISITION_NOT_FOUND`,
        `ERR_SOLICITATION_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_PO_NOT_FOUND`,
        `ERR_RECEIPT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_PCARD_NOT_FOUND`,
        `ERR_TRANSACTION_NOT_FOUND`, `ERR_ELEVATION_NOT_FOUND`, or
        `ERR_SURPLUS_ASSET_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/purchase_order_not_found_returns_404
        """
        bare = api.get_purchase_order(NON_EXISTENT_UUID, ADMIN_H)
        validate_error(bare, ApiErrorId.ERR_PO_NOT_FOUND, 404)
        nested = api.create_receipt(
            NON_EXISTENT_UUID, {"lines": [{"line_no": 0, "quantity": 1}]},
            TEST_USERS["receiving_clerk_headers"],
        )
        validate_error(nested, ApiErrorId.ERR_PO_NOT_FOUND, 404)

    def test_not_found_sweep_remaining_catalog(self, api):
        """PRD §2.9: "the request is rejected with the 404 error corresponding to
        the first identifier that does not resolve: `ERR_DEPARTMENT_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_REQUISITION_NOT_FOUND`, `ERR_SOLICITATION_NOT_FOUND`,
        `ERR_QUOTE_NOT_FOUND`, `ERR_PO_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND`, `ERR_PCARD_NOT_FOUND`,
        `ERR_TRANSACTION_NOT_FOUND`, `ERR_ELEVATION_NOT_FOUND`, or
        `ERR_SURPLUS_ASSET_NOT_FOUND`, each with HTTP 404."

        Design: Corner/errors/not_found_sweep_covers_remaining_catalog
        """
        cases = [
            (api.get_requisition, ApiErrorId.ERR_REQUISITION_NOT_FOUND),
            (api.get_contract, ApiErrorId.ERR_CONTRACT_NOT_FOUND),
            (api.get_grant, ApiErrorId.ERR_GRANT_NOT_FOUND),
            (api.get_vendor, ApiErrorId.ERR_VENDOR_NOT_FOUND),
            (api.get_invoice, ApiErrorId.ERR_INVOICE_NOT_FOUND),
            (api.get_pcard, ApiErrorId.ERR_PCARD_NOT_FOUND),
            (api.get_pcard_transaction, ApiErrorId.ERR_TRANSACTION_NOT_FOUND),
            (api.get_surplus_asset, ApiErrorId.ERR_SURPLUS_ASSET_NOT_FOUND),
            (api.get_solicitation, ApiErrorId.ERR_SOLICITATION_NOT_FOUND),
        ]
        for getter, error_id in cases:
            resp = getter(NON_EXISTENT_UUID, ADMIN_H)
            validate_error(resp, error_id, 404)


class TestPaginationAndFilters:
    def test_list_pagination_filter_interaction(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it
        defaults to 10 when omitted and must lie between 1 and 100 inclusive."
        PRD §2.3: "A `limit` outside the allowed range or a negative `offset` is
        rejected with `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400)."
        PRD §2.3: "Several list endpoints additionally accept domain filters —
        for example `status`, `department_id`, `vendor_id`, `grant_id`,
        `contract_id`, `requisition_id`, `fulfillment_status`, `match_status`,
        `pcard_id`, or `claiming_department_id` — which restrict the listed
        collection to matching records, and the supplier-diversity report accepts
        `basis`, `window_start`, and `window_end`".

        Design: Corner/endpoints/list_pagination_filter_interaction
        """
        dept = create_department(name="Pages")
        vendor = create_vendor(legal_name="ListCo")
        reqs = [
            create_requisition_draft(
                department_id=dept["id"], vendor_id=vendor["id"],
                lines=[requisition_line(
                    commodity_code="P", description=tag, unit_price_cents=10000,
                )],
            )
            for tag in ("a", "b", "c", "d", "e")
        ]
        submit_requisition_ok(reqs[3]["id"])
        submit_requisition_ok(reqs[4]["id"])

        resp = api.list_requisitions(
            ADMIN_H, params={"status": "SUBMITTED", "limit": 2, "offset": 0}
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, "filter constrains the count"
        assert len(data) == 2
        assert meta["has_more"] is False

        resp_all = api.list_requisitions(ADMIN_H, params={"limit": 100})
        _, meta_all = validate_paginated(resp_all)
        assert meta_all["total_count"] == 5

        bad_low = api.list_requisitions(ADMIN_H, params={"limit": 0})
        validate_error(bad_low, ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS, 400)
        bad_high = api.list_requisitions(ADMIN_H, params={"limit": 101})
        validate_error(bad_high, ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS, 400)

    def test_reverse_reachability_subresources_return_arrays(self, api):
        """PRD §2.9: "Read-side reverse reachability is provided so that every
        stored reference can be walked: quotes are listable by vendor,
        solicitations by requisition, receipts and invoices by purchase order,
        transactions by card, and a cross-card transaction listing can be filtered
        by `grant_id`."

        Design: Corner/endpoints/reverse_reachability_subresources_return_arrays
        """
        dept = create_department(name="Reach")
        vendor = create_vendor(legal_name="ReachCo")
        req = create_approved_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="R", description="gear", unit_price_cents=600000,
                cost_category="EQUIPMENT",
            )],
        )
        po = issue_po_ok(req["id"])
        post_receipt(po["id"], [{"line_no": 0, "quantity": 1}])
        post_invoice(
            po["id"], [{"line_no": 0, "quantity": 1, "unit_price_cents": 600000}],
            invoice_number="INV-RR",
        )
        card = create_pcard(department_id=dept["id"], cardholder_name="Rex")
        txn = api.create_pcard_transaction(
            card["id"],
            create_transaction_payload(amount_cents=9000, merchant_name="M"),
            make_cardholder_headers(card["id"]),
        )
        validate_success(txn, 201)
        elev = api.create_elevation(
            card["id"],
            create_elevation_payload(
                window_start="2026-09-01T00:00:00Z",
                window_end="2026-09-02T00:00:00Z",
            ),
            ADMIN_H,
        )
        validate_success(elev, 201)

        approvals, _ = validate_paginated(
            api.list_requisition_approvals(req["id"], ADMIN_H)
        )
        assert len(approvals) == 2
        assert [a["decision"] for a in approvals] == ["APPROVED", "APPROVED"]

        sols, _ = validate_paginated(
            api.list_requisition_solicitations(req["id"], ADMIN_H)
        )
        assert sols == []

        receipts, _ = validate_paginated(api.list_po_receipts(po["id"], ADMIN_H))
        invoices, _ = validate_paginated(api.list_po_invoices(po["id"], ADMIN_H))
        assert len(receipts) == 1 and len(invoices) == 1

        txns, _ = validate_paginated(api.list_pcard_transactions(card["id"], ADMIN_H))
        elevs, _ = validate_paginated(api.list_pcard_elevations(card["id"], ADMIN_H))
        assert len(txns) == 1 and len(elevs) == 1

        vendor_quotes, _ = validate_paginated(
            api.list_vendor_quotes(vendor["id"], ADMIN_H)
        )
        assert vendor_quotes == []
