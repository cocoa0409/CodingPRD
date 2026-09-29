"""
Gates that read a neighbouring entity's state rather than the target's: an
acceptance held up by the buyer's proof-of-funds expiry, and a clear-to-fund
held up by the contract's assignment status.
"""

from test_helpers import (
    ApiErrorId,
    assert_assignment_agreement,
    assert_assignment_offer,
    assert_cash_buyer,
    assert_nulls,
    assert_proof_of_funds,
    assert_purchase_contract,
    assert_title_order,
    build_accepted_offer,
    build_marketed_contract,
    execute_agreement,
    make_wholesaler_headers,
    open_title_order,
    read_buyer,
    read_contract,
    read_offer,
    read_title_order,
    set_clock,
    upload_proof_of_funds,
    validate_error,
    validate_success,
    verify_proof_of_funds,
    TITLE_AGENT_1,
    TITLE_AGENT_1_USER_ID,
)

CONTRACT_TERMS = {
    "purchase_price_cents": 18000000,
    "earnest_money_cents": 500000,
    "inspection_period_days": 7,
    "closing_window_start_at": "2026-09-15T00:00:00Z",
    "closing_window_end_at": "2026-09-30T00:00:00Z",
}


def _offer_whose_proof_has_gone_stale(api):
    """
    A live offer created while the buyer's only proof of funds was still good,
    read back after the clock has stepped past that proof's expiry. Nothing
    about the offer changed; only the document went stale.
    """
    scenario = build_marketed_contract(
        api,
        clock="2026-08-10T00:00:00Z",
        buyer_price_cents=20000000,
        buyer_deposit_cents=1000000,
        structure_election="ASSIGNMENT_ELECTED",
        buyer_kwargs={"expires_at": "2026-08-15T00:00:00Z"},
        contract_kwargs=dict(CONTRACT_TERMS),
    )
    assert_assignment_offer(scenario.offer, status="SUBMITTED")
    assert_proof_of_funds(
        scenario.proof_of_funds,
        verification_status="VERIFIED",
        verified_funds_cents=25500000,
        expires_at="2026-08-15T00:00:00Z",
    )
    set_clock(api, "2026-08-16T00:00:00Z")
    return scenario


class TestAcceptanceReadsTheBuyersProofOfFunds:
    """The offer is untouched; its buyer's newest verified letter has expired."""

    def test_expired_proof_blocks_an_otherwise_acceptable_offer(self, api):
        """
        "**`ERR_PROOF_OF_FUNDS_EXPIRED`** (422) — every one of the buyer's
        `VERIFIED` proofs has an `expires_at` at or before the current instant,
        or a verification request targets a proof whose `expires_at` is at or
        before the current instant. Guards offer acceptance and proof-of-funds
        verification."

        "And a proof of funds counts only while its `expires_at` is strictly
        after the current instant."

        "A buyer's `verified_funds_cents` is the **largest**
        `verified_funds_cents` among that buyer's proof-of-funds records that are
        in `VERIFIED` status and whose `expires_at` is strictly after the current
        logical instant; where no such record exists it is 0."

        "The move is not inert: crossing a proof-of-funds expiry recomputes
        `verified_funds_cents`, `available_funds_cents` and `buyer_tier` on every
        cash buyer whose liquidity picture changed, which can drop a buyer to
        `SUSPENDED` and make a subsequent acceptance fail on
        `ERR_PROOF_OF_FUNDS_EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/offer_accept_requires_unexpired_verified_proof_of_funds
        """
        scenario = _offer_whose_proof_has_gone_stale(api)

        # The dependency entity, not the offer, is what moved.
        assert_cash_buyer(
            read_buyer(api, scenario.buyer_id, scenario.w_id),
            verified_funds_cents=0,
            committed_deposit_cents=1000000,
            active_offer_count=1,
            buyer_tier="SUSPENDED",
        )

        response = api.accept_assignment_offer(
            scenario.offer_id, make_wholesaler_headers(scenario.w_id)
        )
        validate_error(response, ApiErrorId.PROOF_OF_FUNDS_EXPIRED, 422)

        untouched = read_offer(api, scenario.offer_id, scenario.w_id)
        assert_assignment_offer(
            untouched, status="SUBMITTED", buyer_price_cents=20000000
        )
        assert_nulls(
            untouched, "accepted_at", "assignment_fee_cents", label="assignment_offer"
        )
        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id),
            assignment_status="MARKETED",
            contract_status="SIGNED",
        )

    def test_a_fresh_verified_letter_alone_unblocks_the_same_offer(self, api):
        """
        "On approval the record's `verified_funds_cents` is set to the supplied
        override, or, when no override is supplied, defaults to
        `stated_funds_cents`; `verified_at` is stamped from the logical clock and
        `verified_by_user_id` records the verifying wholesaler user's
        `X-User-ID`."

        "Both outcomes recompute the owning buyer's `verified_funds_cents`,
        `available_funds_cents` and `buyer_tier`."

        "**Acceptance.** The wholesaler accepts, driving the offer to `ACCEPTED`
        from `SUBMITTED`, from `COUNTERED_BY_WHOLESALER` or from
        `REVISED_BY_BUYER`. All three edges carry identical preconditions and
        identical effects."

        "The implied assignment fee is the offer's `buyer_price_cents` less the
        contract's `purchase_price_cents`."

        Design: Difficulty/cross_entity_state_dependency/offer_accept_requires_unexpired_verified_proof_of_funds
        """
        scenario = _offer_whose_proof_has_gone_stale(api)
        validate_error(
            api.accept_assignment_offer(
                scenario.offer_id, make_wholesaler_headers(scenario.w_id)
            ),
            ApiErrorId.PROOF_OF_FUNDS_EXPIRED,
            422,
        )

        replacement = upload_proof_of_funds(
            api,
            scenario.buyer_id,
            stated_funds_cents=25500000,
            document_ref="pof-ridgeline-002",
            expires_at="2026-12-01T00:00:00Z",
        )
        verified = verify_proof_of_funds(
            api, replacement["id"], scenario.w_id, verification_decision="VERIFIED"
        )
        assert_proof_of_funds(
            verified,
            verification_status="VERIFIED",
            verified_funds_cents=25500000,
            verified_at="2026-08-16T00:00:00Z",
            expires_at="2026-12-01T00:00:00Z",
        )
        assert_cash_buyer(
            read_buyer(api, scenario.buyer_id, scenario.w_id),
            verified_funds_cents=25500000,
            committed_deposit_cents=1000000,
            available_funds_cents=24500000,
        )

        response = api.accept_assignment_offer(
            scenario.offer_id, make_wholesaler_headers(scenario.w_id)
        )
        accepted = validate_success(response, 200)

        # 20000000 - 18000000 == 2000000, well inside the twelve percent cap.
        assert_assignment_offer(
            accepted,
            status="ACCEPTED",
            buyer_price_cents=20000000,
            assignment_fee_cents=2000000,
            accepted_at="2026-08-16T00:00:00Z",
        )


def _opened_order_on_an_unassigned_contract(api):
    """
    An accepted offer that has not been papered, so the contract is still only
    MARKETED, and an escrow file legitimately opened against it.
    """
    scenario = build_accepted_offer(
        api,
        clock="2026-08-10T00:00:00Z",
        buyer_price_cents=20000000,
        buyer_deposit_cents=1000000,
        structure_election="ASSIGNMENT_ELECTED",
        contract_kwargs=dict(CONTRACT_TERMS),
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


class TestClearToFundReadsTheContractsAssignmentStatus:
    """Escrow may open early, but it may not clear until the deal is assigned."""

    def test_clearing_an_unassigned_contract_is_refused(self, api):
        """
        "The order's `structure` is copied from the contract's
        `structure_election` at creation — it is never client-supplied"

        "A new order enters status `OPENED` with `cleared_by_user_id` and
        `funded_by_user_id` null."

        "**`ERR_CONTRACT_NOT_ASSIGNED`** (409) — an `ASSIGNMENT`-structured title
        order is being cleared while the contract's `assignment_status` is not yet
        `ASSIGNED`. Guards clear-to-fund."

        Design: Difficulty/cross_entity_state_dependency/title_order_clear_to_fund_requires_assigned_contract
        """
        scenario, order = _opened_order_on_an_unassigned_contract(api)
        assert_title_order(order, status="OPENED", structure="ASSIGNMENT")
        assert_nulls(
            order, "cleared_by_user_id", "funded_by_user_id", label="title_order"
        )
        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id),
            assignment_status="MARKETED",
            contract_status="SIGNED",
        )

        response = api.clear_to_fund(order["id"], TITLE_AGENT_1)
        validate_error(response, ApiErrorId.CONTRACT_NOT_ASSIGNED, 409)

        still_open = read_title_order(api, order["id"], scenario.w_id)
        assert_title_order(still_open, status="OPENED", structure="ASSIGNMENT")
        assert_nulls(
            still_open, "cleared_by_user_id", "funded_by_user_id", label="title_order"
        )
        # The refused clear did not advance the contract either.
        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id),
            contract_status="SIGNED",
            assignment_status="MARKETED",
        )

    def test_papering_the_assignment_is_what_lets_the_same_order_clear(self, api):
        """
        "A successful execution copies `assignment_fee_cents` from the accepted
        offer onto the agreement — this copied figure is the base of every
        settlement component — stamps `executed_at` from the logical clock"

        "The first agent clears the file, driving `OPENED → CLEARED_TO_FUND`; this
        requires the order to still be `OPENED` and requires the
        structure-appropriate readiness — for an `ASSIGNMENT`-structured order the
        contract's `assignment_status` must already be `ASSIGNED`, and clearing
        one that is not reports `ERR_CONTRACT_NOT_ASSIGNED`, while for a
        `DOUBLE_CLOSE`-structured order the contract's `structure_election` must
        be `DOUBLE_CLOSE_ELECTED`."

        "Clearing records the acting `X-User-ID` in `cleared_by_user_id` and
        drives the contract's `contract_status` from `SIGNED` to `PENDING_CLOSE`."

        Design: Difficulty/cross_entity_state_dependency/title_order_clear_to_fund_requires_assigned_contract
        """
        scenario, order = _opened_order_on_an_unassigned_contract(api)
        validate_error(
            api.clear_to_fund(order["id"], TITLE_AGENT_1),
            ApiErrorId.CONTRACT_NOT_ASSIGNED,
            409,
        )

        agreement = execute_agreement(api, scenario.offer_id, scenario.w_id)
        assert_assignment_agreement(
            agreement,
            structure="ASSIGNMENT",
            assignment_fee_cents=2000000,
            settlement_status="PENDING_SETTLEMENT",
            executed_at="2026-08-10T00:00:00Z",
        )
        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id),
            assignment_status="ASSIGNED",
            contract_status="SIGNED",
        )

        response = api.clear_to_fund(order["id"], TITLE_AGENT_1)
        cleared = validate_success(response, 200)

        assert_title_order(
            cleared,
            status="CLEARED_TO_FUND",
            structure="ASSIGNMENT",
            cleared_by_user_id=TITLE_AGENT_1_USER_ID,
        )
        assert_nulls(cleared, "funded_by_user_id", label="title_order")
        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id),
            contract_status="PENDING_CLOSE",
            assignment_status="ASSIGNED",
        )
