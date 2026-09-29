"""
Two contended resources with deliberately different interval semantics: the
wholesaler's funding capacity, buffered and half-open, and the lead's property,
fully closed so that adjacency itself collides.
"""

from test_helpers import (
    ApiErrorId,
    acknowledge_disclosures,
    assert_pagination_meta,
    assert_purchase_contract,
    assert_seller_lead,
    assert_title_order,
    assert_wholesaler,
    build_draft_contract,
    build_signed_contract,
    elect,
    factories,
    finalize,
    make_wholesaler_headers,
    open_contract,
    open_title_order,
    read_lead,
    read_wholesaler,
    record_lead,
    screen_lead,
    sign,
    underwrite,
    validate_error,
    validate_paginated,
    validate_success,
)

DOUBLE_CLOSE_TERMS = {
    "purchase_price_cents": 14800000,
    "earnest_money_cents": 500000,
    "inspection_period_days": 7,
    "option_start_at": "2026-08-10T00:00:00Z",
    "closing_window_start_at": "2026-09-15T00:00:00Z",
    "closing_window_end_at": "2026-09-30T00:00:00Z",
}

SECOND_TITLE_COMPANY = "Colorado River Title Co"
SECOND_ESCROW_OFFICER = "eo-ken-aoki"


def _first_occupied_funding_window(api):
    """
    A double-close contract with an OPENED title order holding the desk's only
    unit of funding capacity from 2026-09-15 through its buffered end.
    """
    scenario = build_signed_contract(
        api, clock="2026-08-10T00:00:00Z", contract_kwargs=dict(DOUBLE_CLOSE_TERMS)
    )
    scenario.contract = elect(
        api, scenario.pc_id, scenario.w_id, "DOUBLE_CLOSE_ELECTED"
    )
    order = open_title_order(
        api,
        scenario.pc_id,
        scenario.w_id,
        title_company_name="Lone Star Title & Escrow",
        escrow_officer_ref="eo-marisol-vega",
        funding_window_start_at="2026-09-15T00:00:00Z",
        funding_window_end_at="2026-09-16T00:00:00Z",
    )
    return scenario, order


def _second_double_close_contract(api, scenario):
    """A second property on the same desk, signed and elected to double close."""
    lead = record_lead(
        api,
        scenario.w_id,
        owner_name=factories.SECOND_LEAD_OWNER_NAME,
        property_address=factories.SECOND_LEAD_PROPERTY_ADDRESS,
    )
    lead = screen_lead(api, lead["id"], scenario.w_id, "STATUTORY")
    analysis = underwrite(api, lead["id"], scenario.w_id, lead["version"])
    analysis = finalize(api, analysis["id"], scenario.w_id, "AGGRESSIVE")
    contract = open_contract(
        api,
        lead["id"],
        analysis["id"],
        scenario.w_id,
        purchase_price_cents=14800000,
        earnest_money_cents=500000,
        inspection_period_days=7,
        option_start_at="2026-08-10T00:00:00Z",
        closing_window_start_at="2026-09-20T00:00:00Z",
        closing_window_end_at="2026-10-05T00:00:00Z",
    )
    acknowledge_disclosures(
        api, contract["id"], lead["id"], signature_ref="esig-omar-001"
    )
    sign(api, contract["id"], lead["id"])
    return elect(api, contract["id"], scenario.w_id, "DOUBLE_CLOSE_ELECTED")


class TestFundingCapacityIsBufferedAndHalfOpen:
    """The buffer, not the wired window, is what the next order collides with."""

    def test_a_window_starting_inside_the_buffer_exhausts_the_capacity(self, api):
        """
        "**Double-close funding windows** treat the interval from a title order's
        `funding_window_start_at` to its `funding_window_end_at` as **half-open on
        the right**, and additionally extend every interval by a forty-eight-hour
        trailing buffer to its `buffered_window_end_at`."

        "A candidate conflicts with an existing occupant when the candidate's
        `funding_window_start_at` is strictly before the existing order's
        `buffered_window_end_at` **and** the existing order's
        `funding_window_start_at` is strictly before the candidate's
        `buffered_window_end_at`."

        "Unlike property occupancy, a single conflict is tolerated — the request is
        rejected with `ERR_FUNDING_WINDOW_CONFLICT` only once the number of
        conflicting occupants reaches the wholesaler's `funding_window_capacity`,
        which defaults to 1 and may be raised at registration to reflect a larger
        transactional-lender line."

        "**`ERR_FUNDING_WINDOW_CONFLICT`** (409) — the candidate double-close
        funding window collides with at least as many live buffered windows as the
        wholesaler's capacity allows. Guards title-order creation."

        Design: Difficulty/resource_temporal_overlap/double_close_funding_window_buffer_conflict_on_wholesaler
        """
        scenario, order = _first_occupied_funding_window(api)
        assert_wholesaler(
            read_wholesaler(api, scenario.w_id), funding_window_capacity=1
        )
        # 2026-09-16T00:00:00Z plus forty-eight hours.
        assert_title_order(
            order,
            status="OPENED",
            structure="DOUBLE_CLOSE",
            funding_window_start_at="2026-09-15T00:00:00Z",
            funding_window_end_at="2026-09-16T00:00:00Z",
            buffered_window_end_at="2026-09-18T00:00:00Z",
        )
        # The occupant really is a double close: 14800000 x 1.021 == 15110800,
        # and tier two on that base gives 339993.
        assert_purchase_contract(
            scenario.contract,
            structure_election="DOUBLE_CLOSE_ELECTED",
            funding_base_cents=15110800,
            transactional_lender_fee_cents=339993,
            total_funding_required_cents=15450793,
        )

        second = _second_double_close_contract(api, scenario)
        response = api.create_title_order(
            factories.title_order_payload(
                second["id"],
                title_company_name=SECOND_TITLE_COMPANY,
                escrow_officer_ref=SECOND_ESCROW_OFFICER,
                funding_window_start_at="2026-09-17T12:00:00Z",
                funding_window_end_at="2026-09-18T12:00:00Z",
            ),
            make_wholesaler_headers(scenario.w_id),
        )
        validate_error(response, ApiErrorId.FUNDING_WINDOW_CONFLICT, 409)

        _, rejected_meta = validate_paginated(
            api.list_title_orders(
                make_wholesaler_headers(scenario.w_id),
                {"purchase_contract_id": second["id"]},
            )
        )
        assert_pagination_meta(rejected_meta, total_count=0)
        _, desk_meta = validate_paginated(
            api.list_title_orders(make_wholesaler_headers(scenario.w_id))
        )
        assert_pagination_meta(desk_meta, total_count=1)

    def test_a_window_starting_exactly_at_the_buffered_end_is_accepted(self, api):
        """
        "Touching edges do not conflict: a candidate starting exactly at an
        existing buffered end is accepted."

        "Only title orders whose `structure` is `DOUBLE_CLOSE` and whose status is
        `OPENED` or `CLEARED_TO_FUND` occupy a window; `ASSIGNMENT`-structured
        orders consume no funding capacity at all."

        "The order's `structure` is copied from the contract's `structure_election`
        at creation — it is never client-supplied — and for a `DOUBLE_CLOSE` order
        the desk computes `buffered_window_end_at` as `funding_window_end_at` plus
        forty-eight hours."

        Design: Difficulty/resource_temporal_overlap/double_close_funding_window_buffer_conflict_on_wholesaler
        """
        scenario, order = _first_occupied_funding_window(api)
        assert_title_order(order, buffered_window_end_at="2026-09-18T00:00:00Z")
        second = _second_double_close_contract(api, scenario)

        response = api.create_title_order(
            factories.title_order_payload(
                second["id"],
                title_company_name=SECOND_TITLE_COMPANY,
                escrow_officer_ref=SECOND_ESCROW_OFFICER,
                funding_window_start_at="2026-09-18T00:00:00Z",
                funding_window_end_at="2026-09-19T00:00:00Z",
            ),
            make_wholesaler_headers(scenario.w_id),
        )
        accepted = validate_success(response, 201)

        assert_title_order(
            accepted,
            status="OPENED",
            structure="DOUBLE_CLOSE",
            purchase_contract_id=second["id"],
            title_company_name=SECOND_TITLE_COMPANY,
            funding_window_start_at="2026-09-18T00:00:00Z",
            buffered_window_end_at="2026-09-21T00:00:00Z",
        )
        _, desk_meta = validate_paginated(
            api.list_title_orders(make_wholesaler_headers(scenario.w_id))
        )
        assert_pagination_meta(desk_meta, total_count=2)


LIVE_CONTRACT_TERMS = {
    "purchase_price_cents": 18000000,
    "earnest_money_cents": 500000,
    "inspection_period_days": 7,
    "option_start_at": "2026-08-10T00:00:00Z",
    "closing_window_start_at": "2026-09-15T00:00:00Z",
    "closing_window_end_at": "2026-09-30T00:00:00Z",
}

BACKUP_TERMS = {
    "purchase_price_cents": 17000000,
    "earnest_money_cents": 400000,
    "inspection_period_days": 10,
    "closing_window_start_at": "2026-11-15T00:00:00Z",
    "closing_window_end_at": "2026-11-30T00:00:00Z",
}


def _property_occupied_to_the_end_of_september(api):
    """
    A DRAFT contract encumbering the property from 2026-08-10 through
    2026-09-30, both instants inside the closed occupancy interval.
    """
    scenario = build_draft_contract(
        api, clock="2026-08-10T00:00:00Z", contract_kwargs=dict(LIVE_CONTRACT_TERMS)
    )
    assert_purchase_contract(
        scenario.contract,
        contract_status="DRAFT",
        option_start_at="2026-08-10T00:00:00Z",
        closing_window_end_at="2026-09-30T00:00:00Z",
    )
    return scenario


def _backup_contract_attempt(api, scenario, option_start_at):
    return api.create_purchase_contract(
        factories.purchase_contract_payload(
            scenario.lead_id,
            scenario.analysis_id,
            option_start_at=option_start_at,
            **BACKUP_TERMS,
        ),
        make_wholesaler_headers(scenario.w_id),
    )


class TestPropertyOccupancyIsFullyClosed:
    """A backup contract touching the live one's last instant collides."""

    def test_a_backup_starting_on_the_closing_end_instant_is_refused(self, api):
        """
        "**Property occupancy** treats the interval from a contract's
        `option_start_at` to its `closing_window_end_at` as **fully closed**, with
        no buffer and no capacity allowance — a property may be under exactly one
        live contract at a time."

        "Only contracts whose `contract_status` is `DRAFT`, `SIGNED` or
        `PENDING_CLOSE` occupy the property; a `CLOSED` or `CANCELLED` contract
        releases it immediately."

        "A candidate conflicts with an existing occupant when the candidate's
        `option_start_at` is at or before the existing contract's
        `closing_window_end_at` **and** the candidate's `closing_window_end_at` is
        at or after the existing contract's `option_start_at`."

        "A lead already `UNDER_CONTRACT` passes this rule, which is why a
        non-overlapping backup contract is reachable and the occupancy conflict at
        rank 34 is the rule that actually rejects double encumbrance."

        "Any conflict at all is rejected with `ERR_PROPERTY_OCCUPANCY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/property_occupancy_closed_interval_adjacency_conflict_on_seller_lead
        """
        scenario = _property_occupied_to_the_end_of_september(api)
        before = read_lead(api, scenario.lead_id, scenario.w_id)
        assert_seller_lead(before, status="UNDER_CONTRACT")

        response = _backup_contract_attempt(api, scenario, "2026-09-30T00:00:00Z")
        validate_error(response, ApiErrorId.PROPERTY_OCCUPANCY_CONFLICT, 409)

        _, meta = validate_paginated(
            api.list_purchase_contracts(
                make_wholesaler_headers(scenario.w_id),
                {"seller_lead_id": scenario.lead_id},
            )
        )
        assert_pagination_meta(meta, total_count=1)
        after = read_lead(api, scenario.lead_id, scenario.w_id)
        assert_seller_lead(after, status="UNDER_CONTRACT", version=before["version"])

    def test_one_second_past_the_closed_interval_is_accepted(self, api):
        """
        "Adjacency therefore collides: a candidate whose `option_start_at` equals
        an existing contract's `closing_window_end_at` to the second is a conflict,
        and one second later is accepted."

        "The create also derives `assignment_deadline_at` as
        `closing_window_start_at` less forty-eight hours, and moves the lead to
        `UNDER_CONTRACT`."

        "And it creates the contract's earnest money deposit, whose
        `purchase_contract_id` points back at the contract, whose `amount_cents` is
        copied from the contract's `earnest_money_cents` and never afterwards
        mutated, whose `status` is `HELD`, whose `held_cents` equals `amount_cents`
        with the other three buckets at zero, and whose `disposition_event_count`
        is 0."

        Design: Difficulty/resource_temporal_overlap/property_occupancy_closed_interval_adjacency_conflict_on_seller_lead
        """
        scenario = _property_occupied_to_the_end_of_september(api)

        response = _backup_contract_attempt(api, scenario, "2026-09-30T00:00:01Z")
        backup = validate_success(response, 201)

        assert_purchase_contract(
            backup,
            contract_status="DRAFT",
            assignment_status="NOT_MARKETED",
            structure_election="UNDECIDED",
            purchase_price_cents=17000000,
            earnest_money_cents=400000,
            option_start_at="2026-09-30T00:00:01Z",
            assignment_deadline_at="2026-11-13T00:00:00Z",
            signed_at=None,
        )
        _, contract_meta = validate_paginated(
            api.list_purchase_contracts(
                make_wholesaler_headers(scenario.w_id),
                {"seller_lead_id": scenario.lead_id},
            )
        )
        assert_pagination_meta(contract_meta, total_count=2)
        # Escrow is funded by the signing cascade, and neither contract is signed.
        _, deposit_meta = validate_paginated(
            api.list_earnest_money_deposits(
                make_wholesaler_headers(scenario.w_id),
                {"purchase_contract_id": backup["id"]},
            )
        )
        assert_pagination_meta(deposit_meta, total_count=0)
