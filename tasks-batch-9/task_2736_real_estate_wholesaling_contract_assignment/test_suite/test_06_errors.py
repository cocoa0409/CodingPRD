"""
Error mapping: the two principal-comparison guards that reject a well-formed
request from the wrong human, and the schema-level pagination bound that is
rejected rather than silently clamped.
"""

from test_helpers import (
    ApiErrorId,
    assert_compliance_review,
    assert_earnest_money_deposit,
    assert_escrow_conserved,
    assert_nulls,
    assert_purchase_contract,
    assert_seller_lead,
    assert_title_order,
    assert_wholesaler,
    build_signed_contract,
    clear_title_order,
    elect,
    factories,
    find_deposit,
    make_wholesaler_headers,
    open_review,
    open_title_order,
    read_contract,
    read_lead,
    read_review,
    read_title_order,
    read_wholesaler,
    record_lead,
    register_wholesaler,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    COMPLIANCE_OFFICER_ALPHA,
    TITLE_AGENT_ALPHA,
)


class TestDualControlOnFunding:
    """The clearing principal may not also wire the funds."""

    def test_clearing_agent_funding_the_same_order_is_forbidden(self, api):
        """
        "A title order records the agent who cleared the file to fund in
        `cleared_by_user_id` and the agent who wired the funds in
        `funded_by_user_id`, both from the `X-User-ID` header. These must
        differ; the clearing agent attempting to also fund fails with
        `ERR_DUAL_CONTROL_REQUIRED`. Both roles involved are `TitleAgent` — the
        constraint is on the principal, not on the role."

        "**`ERR_DUAL_CONTROL_REQUIRED`** (403) — the funding `X-User-ID` equals
        the title order's `cleared_by_user_id`. Guards fund-and-close only."

        Design: Corner/errors/title_order_fund_and_close_by_clearing_agent_returns_dual_control_error
        """
        scenario = build_signed_contract(
            api,
            clock="2026-08-08T00:00:00Z",
            contract_kwargs={
                "purchase_price_cents": 18000000,
                "earnest_money_cents": 500000,
            },
        )
        elect(api, scenario.pc_id, scenario.w_id, "DOUBLE_CLOSE_ELECTED")
        order = open_title_order(
            api,
            scenario.pc_id,
            scenario.w_id,
            funding_window_start_at="2026-09-16T00:00:00Z",
            funding_window_end_at="2026-09-18T00:00:00Z",
        )
        cleared = clear_title_order(api, order["id"], TITLE_AGENT_ALPHA)
        assert_title_order(
            cleared,
            status="CLEARED_TO_FUND",
            structure="DOUBLE_CLOSE",
            cleared_by_user_id="ta-alpha",
            funded_by_user_id=None,
        )
        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id),
            contract_status="PENDING_CLOSE",
        )

        response = api.fund_and_close(order["id"], TITLE_AGENT_ALPHA)
        validate_error(response, ApiErrorId.DUAL_CONTROL_REQUIRED, 403)

        assert_title_order(
            read_title_order(api, order["id"], scenario.w_id),
            status="CLEARED_TO_FUND",
            cleared_by_user_id="ta-alpha",
            funded_by_user_id=None,
        )
        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id),
            contract_status="PENDING_CLOSE",
        )
        assert_seller_lead(
            read_lead(api, scenario.lead_id, scenario.w_id), status="UNDER_CONTRACT"
        )

        deposit = find_deposit(api, scenario.pc_id, scenario.w_id)
        assert_earnest_money_deposit(
            deposit,
            status="HELD",
            held_cents=500000,
            applied_at_closing_cents=0,
            disposition_event_count=0,
        )
        assert_escrow_conserved(deposit)


class TestSegregationOfDutiesOnAdjudication:
    """The opening officer may not rule on their own review."""

    def test_opening_officer_adjudicating_their_own_review_is_forbidden(self, api):
        """
        "A compliance review records the officer who opened it in
        `opened_by_user_id`, captured from the `X-User-ID` header and never
        accepted from the request body. The officer who adjudicates it is
        recorded in `adjudicated_by_user_id`, and must be a different principal;
        an attempt by the opening officer to rule on their own review fails with
        `ERR_SEGREGATION_OF_DUTIES`."

        "**`ERR_SEGREGATION_OF_DUTIES`** (403) — the adjudicating `X-User-ID`
        equals the review's `opened_by_user_id`. Guards compliance-review
        adjudication only, and applies even while the review is still `OPENED`."

        Design: Corner/errors/compliance_review_adjudicated_by_opening_officer_returns_segregation_error
        """
        set_clock(api, "2026-08-08T00:00:00Z")
        wholesaler = register_wholesaler(api)
        review = open_review(
            api,
            wholesaler["id"],
            COMPLIANCE_OFFICER_ALPHA,
            review_type="MARKETING_COMPLIANCE",
        )
        assert_compliance_review(
            review, status="OPENED", opened_by_user_id="co-alpha"
        )

        response = api.adjudicate_compliance_review(
            review["id"],
            factories.adjudicate_review_payload("CLEAR", "NO_VIOLATION"),
            COMPLIANCE_OFFICER_ALPHA,
        )
        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES, 403)

        after = read_review(api, review["id"], wholesaler["id"])
        assert_compliance_review(after, status="OPENED", opened_by_user_id="co-alpha")
        assert_nulls(
            after,
            "finding",
            "adjudicated_by_user_id",
            "adjudicated_at",
            label="compliance_review",
        )
        assert_wholesaler(
            read_wholesaler(api, wholesaler["id"]),
            adverse_finding_count=0,
            compliance_hold=False,
        )


class TestPaginationBounds:
    """A limit past the declared maximum is refused, never clamped."""

    def test_limit_above_one_hundred_is_out_of_range(self, api):
        """
        "Every collection-listing endpoint accepts two optional query
        parameters. `limit` defaults to 10, may not be smaller than 1, and may
        not exceed 100. `offset` defaults to 0 and may not be negative. A
        `limit` below 1 or above 100, or an `offset` below 0, is rejected with
        `ERR_PAGINATION_OUT_OF_RANGE` (HTTP 400). Pagination bounds are part of
        schema validation and are therefore checked before any path identifier
        is resolved, so a bad `limit` against a nonexistent parent reports 400
        rather than 404."

        Design: Corner/errors/pagination_limit_above_maximum_returns_out_of_range
        """
        set_clock(api, "2026-08-01T00:00:00Z")
        wholesaler = register_wholesaler(api)
        w_id = wholesaler["id"]
        lead = record_lead(api, w_id)

        response = api.list_seller_leads(
            make_wholesaler_headers(w_id),
            {"wholesaler_id": w_id, "limit": 101, "offset": 0},
        )
        validate_error(response, ApiErrorId.PAGINATION_OUT_OF_RANGE, 400)
        body = response.json()
        assert not isinstance(body.get("data"), list), (
            "the rejection must be an error envelope, not a page clamped to "
            f"limit 100: {body}"
        )

        assert_seller_lead(
            read_lead(api, lead["id"], w_id), status="PROSPECT", version=1
        )
        rows, _ = validate_paginated(
            api.list_seller_leads(
                make_wholesaler_headers(w_id), {"wholesaler_id": w_id, "limit": 100}
            )
        )
        assert [row["id"] for row in rows] == [lead["id"]], (
            "a limit of exactly 100 is the inclusive maximum and must succeed"
        )
        validate_success(api.get_wholesaler(w_id, make_wholesaler_headers(w_id)), 200)
