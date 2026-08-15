"""Program creation defaults, response envelope, listing/pagination, not-found,
and the user-context header rule."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_seed_program,
    create_grower,
    create_order_payload,
    create_program_payload,
    get_success_data,
    is_iso8601_timestamp,
    setup_market,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SALESREP = TEST_USERS["salesrep_headers"]


class TestProgramBasics:
    def test_program_created_in_draft_with_default_optional_tiers(self, api):
        """PRD §3.1: "A new program is born in `DRAFT`."
        PRD §3.1: "the optional `prepay_tiers`, each pairing a `pay_by` deadline
        with a `discount_bps` so prepayment at or before the deadline earns that
        rate (defaulting to an empty list); and the optional
        `volume_rebate_tiers`, each pairing a `min_units` threshold with a
        `rebate_bps` applied against the order's total units (also defaulting to
        empty)."

        Design: Corner/entities/program_created_in_draft_with_default_optional_tiers
        """
        resp = api.create_program(create_program_payload(name="P"), ADMIN)
        program = validate_success(resp, expected_status=201)
        assert_seed_program(program)
        assert program["status"] == "DRAFT"
        assert program["prepay_tiers"] == []
        assert program["volume_rebate_tiers"] == []
        assert program["commission_volume_tiers"] == []

    def test_order_create_when_program_not_open_rejected(self, api):
        """PRD §3.5: "The program must be `OPEN` for selling (otherwise
        `ERR_PROGRAM_NOT_OPEN`)."

        Design: Corner/validations/order_create_when_program_not_open_rejected
        """
        program = validate_success(
            api.create_program(create_program_payload(), ADMIN), expected_status=201
        )
        grower = create_grower()
        resp = api.create_order(
            create_order_payload(grower["id"], program["id"]), SALESREP
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN)


class TestAuthContext:
    def test_request_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty value
        for either, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/request_missing_auth_headers_rejected
        """
        resp = api.list_programs(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestNotFound:
    def test_get_order_with_unknown_id_not_found(self, api):
        """PRD §2.8: "Every path identifier and every body foreign key must
        resolve to an existing resource, otherwise `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_order_with_unknown_id_not_found
        """
        resp = api.get_order(NON_EXISTENT_UUID, SALESREP)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestEnvelopeShape:
    def test_response_envelope_shape_on_success_and_error(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.8: "Every path identifier and every body foreign key must
        resolve to an existing resource, otherwise `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        program = validate_success(
            api.create_program(create_program_payload(name="P"), ADMIN),
            expected_status=201,
        )

        ok_resp = api.get_program(program["id"], SALESREP)
        data = validate_success(ok_resp, expected_status=200)
        body = ok_resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"]
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert data["id"] == program["id"]

        err_resp = api.get_program(NON_EXISTENT_UUID, SALESREP)
        error = validate_error(err_resp, ApiErrorId.ERR_NOT_FOUND)
        assert err_resp.json()["response_type"] == "error"
        assert error["message"].strip(), "error envelope carries a human-readable message"


class TestListingAndPagination:
    def test_orders_list_pagination_envelope_fields(self, api):
        """PRD §2.3: "List responses always report `limit`, `offset`,
        `total_count`, and `has_more` inside the `meta` object, where
        `total_count` is the size of the full filtered result set and `has_more`
        indicates whether records exist beyond the returned page."

        Design: Corner/entities/orders_list_pagination_envelope_fields
        """
        ctx = setup_market(with_lot=False)
        for _ in range(3):
            api.create_order(
                create_order_payload(ctx["grower"]["id"], ctx["program"]["id"]), SALESREP
            )

        page1_resp = api.list_orders(
            SALESREP, params={"grower_id": ctx["grower"]["id"], "limit": 2, "offset": 0}
        )
        page1, meta1 = validate_paginated(page1_resp)
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert page1_resp.json()["response_type"] == "array"
        assert isinstance(meta1["api_request_id"], str) and meta1["api_request_id"]

        page2_resp = api.list_orders(
            SALESREP, params={"grower_id": ctx["grower"]["id"], "limit": 2, "offset": 2}
        )
        page2, meta2 = validate_paginated(page2_resp)
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_fk_reverse_reachability_filtered_lists_return_children(self, api):
        """PRD §2.3: "foreign-key filters such as `grower_id`, `program_id`,
        `field_id`, `variety_id`, `trait_package_id`, `order_id`,
        `order_line_id`, `treatment_option_id`, `inventory_lot_id`, `lot_id`,
        `delivery_ticket_id`, `recommendation_id`, `replacement_order_id`,
        `supersedes_agreement_id`, `supersedes_recommendation_id`, and `crop`
        narrow the collection to records referencing the supplied value."

        Design: Corner/endpoints/fk_reverse_reachability_filtered_lists_return_children
        """
        ctx = setup_market(with_lot=False)
        order = get_success_data(
            api.create_order(
                create_order_payload(ctx["grower"]["id"], ctx["program"]["id"]), SALESREP
            )
        )
        line = get_success_data(
            api.add_order_line(
                order["id"],
                {"variety_id": ctx["variety"]["id"], "units": 10},
                SALESREP,
            )
        )

        lines, lines_meta = validate_paginated(
            api.list_order_lines(SALESREP, params={"order_id": order["id"]})
        )
        assert lines_meta["total_count"] == 1
        assert [row["id"] for row in lines] == [line["id"]]

        orders, orders_meta = validate_paginated(
            api.list_orders(
                SALESREP,
                params={"grower_id": ctx["grower"]["id"], "program_id": ctx["program"]["id"]},
            )
        )
        assert orders_meta["total_count"] == 1
        assert [row["id"] for row in orders] == [order["id"]]
