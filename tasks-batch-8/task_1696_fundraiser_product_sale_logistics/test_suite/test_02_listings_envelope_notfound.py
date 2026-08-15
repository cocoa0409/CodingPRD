"""Listings, pagination, response envelope, the 404 family, and ledger
read-shape rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_ledger_entry,
    create_and_submit_order,
    create_order,
    get_group_ledger,
    reset_clock,
    setup_campaign_group_product,
    setup_open_campaign_with_seller,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
TREAS = TEST_USERS["treasurer_headers"]
SUPP = TEST_USERS["supplier_rep_headers"]

UNKNOWN = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestOrderListingPagination:
    def test_orders_list_pagination_limit_offset_has_more(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of
        1 and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Paginated list responses include the following fields in
        the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/orders_list_pagination_limit_offset_has_more
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        for name in ("Fam1", "Fam2", "Fam3"):
            create_order(seller["id"], product["id"], 1,
                         family_contact_name=name)

        page1, meta1 = validate_paginated(
            api.list_orders(COORD, params={"seller_id": seller["id"],
                                           "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_orders(COORD, params={"seller_id": seller["id"],
                                           "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        _page_default, meta_default = validate_paginated(
            api.list_orders(COORD, params={"seller_id": seller["id"]}))
        assert meta_default["limit"] == 10, (
            f"default limit must be 10, got {meta_default['limit']}")


class TestResponseEnvelope:
    def test_response_envelope_shape_verified(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/response_envelope_shape_verified
        """
        import json
        resp = api.create_campaign({
            "name": "Fall Sale", "school_name": "Lincoln",
            "order_window_start": "2026-08-01T00:00:00Z",
            "order_window_end": "2026-08-20T00:00:00Z",
            "expected_delivery_date": "2026-09-05T00:00:00Z",
            "default_profit_share_bps": 5000,
        }, ADMIN)
        assert resp.status_code == 201
        body = json.loads(resp.content)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "object"
        assert isinstance(body["data"], dict)

        err_resp = api.get_campaign(UNKNOWN, ADMIN)
        assert err_resp.status_code == 404
        err_body = json.loads(err_resp.content)
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_CAMPAIGN_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)


class TestNotFoundFamily:
    def test_entity_get_unknown_id_not_found_family(self, api):
        """PRD §2.10: "the server validates their existence left to right and
        rejects with the per-segment 404 error for the first identifier that
        does not correspond to an existing resource: `ERR_CAMPAIGN_NOT_FOUND`,
        `ERR_GROUP_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_PRIZE_NOT_FOUND`,
        `ERR_SELLER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`,
        `ERR_SUPPLIER_ORDER_NOT_FOUND`, `ERR_DISTRIBUTION_EVENT_NOT_FOUND`,
        `ERR_SORT_TICKET_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
        `ERR_RETURN_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, or
        `ERR_PRIZE_AWARD_NOT_FOUND`, as applicable."

        Design: Corner/errors/entity_get_unknown_id_not_found_family
        """
        cases = [
            (api.get_product, ApiErrorId.ERR_PRODUCT_NOT_FOUND),
            (api.get_seller, ApiErrorId.ERR_SELLER_NOT_FOUND),
            (api.get_order, ApiErrorId.ERR_ORDER_NOT_FOUND),
            (api.get_prize, ApiErrorId.ERR_PRIZE_NOT_FOUND),
            (api.get_sort_ticket, ApiErrorId.ERR_SORT_TICKET_NOT_FOUND),
            (api.get_claim, ApiErrorId.ERR_CLAIM_NOT_FOUND),
            (api.get_return_request, ApiErrorId.ERR_RETURN_NOT_FOUND),
            (api.get_pickup_appointment, ApiErrorId.ERR_APPOINTMENT_NOT_FOUND),
            (api.get_prize_award, ApiErrorId.ERR_PRIZE_AWARD_NOT_FOUND),
            (api.get_supplier_order, ApiErrorId.ERR_SUPPLIER_ORDER_NOT_FOUND),
            (api.get_distribution_event,
             ApiErrorId.ERR_DISTRIBUTION_EVENT_NOT_FOUND),
        ]
        for getter, error_id in cases:
            resp = getter(UNKNOWN, ADMIN)
            validate_error(resp, error_id)

    def test_payment_and_order_line_unknown_ids_not_found(self, api):
        """PRD §2.10: "When a path does contain multiple identifiers, the
        server validates their existence left to right and rejects with the
        per-segment 404 error for the first identifier that does not
        correspond to an existing resource".
        PRD §2.10: "A body-supplied order line identifier that does not exist
        yields `ERR_ORDER_LINE_NOT_FOUND`."

        Design: Corner/errors/payment_and_order_line_unknown_ids_not_found
        """
        from test_helpers import (
            create_submitted_paid_order,
            drive_campaign_to_sorted,
            get_order_line_id,
        )
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_submitted_paid_order(seller["id"], product["id"], 1)
        reset_clock()
        from test_helpers import close_ordering_at_window_end
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_sorted(campaign["id"], product["id"],
                                 delivered_units=12)
        line_id = get_order_line_id(order["id"])

        resp_pay = api.clear_payment(UNKNOWN, TREAS)
        validate_error(resp_pay, ApiErrorId.ERR_PAYMENT_NOT_FOUND)

        resp_line = api.create_claim({
            "order_id": order["id"], "order_line_id": UNKNOWN,
            "claim_type": "MISSING", "quantity": 1,
        }, COORD)
        validate_error(resp_line, ApiErrorId.ERR_ORDER_LINE_NOT_FOUND)
        assert line_id  # order has a real line; the unknown id is the failure


class TestLedgerReplayArithmetic:
    def test_group_adjustment_running_balance_and_seq(self, api):
        """PRD §2.7: "Entries for a group are replayed in `created_at`
        ascending order with `seq` ascending as the tie-break — never by `id`
        — starting from a zero baseline: each entry's `seq` is one greater
        than the previous maximum for the group, and each
        `balance_after_cents` is the previous entry's `balance_after_cents`
        plus the entry's `amount_cents`."
        PRD §2.7: "A `Treasurer` may post a `MANUAL_ADJUSTMENT` entry to a
        group by supplying a signed `amount_cents` and a `memo`; such an entry
        is created with a 201 response and immediately moves the group's
        balance."

        Design: Corner/calculations/group_adjustment_running_balance_and_seq
        """
        reset_clock()
        campaign, group, _product = setup_campaign_group_product()
        validate_success(api.create_group_adjustment(
            group["id"], {"amount_cents": 500, "memo": "seed"}, TREAS), 201)
        validate_success(api.create_group_adjustment(
            group["id"], {"amount_cents": -200, "memo": "correction"},
            TREAS), 201)
        ledger = get_group_ledger(group["id"])
        assert len(ledger) == 2
        assert ledger[0]["seq"] == 1
        assert ledger[0]["balance_after_cents"] == 500
        assert ledger[1]["seq"] == 2
        assert ledger[1]["entry_type"] == "MANUAL_ADJUSTMENT"
        assert ledger[1]["balance_after_cents"] == 300
        group_view = get_success_data(api.get_group(group["id"], TREAS))
        assert group_view["proceeds_balance_cents"] == 300, (
            "the group balance equals the latest entry's balance_after_cents")


class TestLedgerReadShape:
    def test_ledger_entry_polymorphic_reference_resolves_to_order(self, api):
        """PRD §2.7: "a polymorphic `reference_type` — one of `ORDER`,
        `PAYMENT`, `RETURN_REQUEST`, `CLAIM`, `PRIZE_AWARD`, or `CAMPAIGN` —
        paired with `reference_id` identifying the originating entity of that
        type".
        PRD §3.2: "it posts the seller's group a single `PROVISIONAL_CREDIT`
        ledger entry referenced to the order".

        Design: Corner/entities/ledger_entry_polymorphic_reference_resolves_to_order
        """
        reset_clock()
        _campaign, group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        ledger = get_group_ledger(group["id"])
        assert len(ledger) == 1
        entry = ledger[0]
        assert entry["entry_type"] == "PROVISIONAL_CREDIT"
        assert entry["reference_type"] == "ORDER"
        assert entry["reference_id"] == order["id"]
        # round_half_up(1 * (1000-600) * 5000/10000) == 200
        assert entry["amount_cents"] == 200

    def test_ledger_entry_immutable_no_version_field(self, api):
        """PRD §2.4: "The one exception is `ProceedsLedgerEntry`, the
        append-only proceeds ledger row. Ledger entries carry only `id` and
        `created_at` from the common set — they are never mutated after
        insertion, so both `updated_at` and `version` are absent from the
        resource."
        PRD §2.7: "a per-group monotonic `seq` starting at 1".

        Design: Corner/entities/ledger_entry_immutable_no_version_field
        """
        reset_clock()
        campaign, group, _product = setup_campaign_group_product()
        resp = api.create_group_adjustment(
            group["id"], {"amount_cents": 500, "memo": "seed"}, TREAS)
        validate_success(resp, 201)
        ledger = get_group_ledger(group["id"])
        assert len(ledger) == 1
        entry = ledger[0]
        assert_ledger_entry(entry)
        assert entry["amount_cents"] == 500
        assert entry["seq"] == 1
        assert entry["balance_after_cents"] == 500
