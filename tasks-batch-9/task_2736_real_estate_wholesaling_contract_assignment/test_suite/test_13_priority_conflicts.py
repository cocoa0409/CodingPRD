"""
Requests that violate two rules at once, where the response must name the
higher-ranked one: a state precondition over a fiscal cap, and a seller-safety
window over a temporal cutoff.
"""

from decimal import Decimal

from test_helpers import (
    ApiErrorId,
    assert_assignment_offer,
    assert_cash_buyer,
    assert_equity_pct_four_places,
    assert_nulls,
    assert_pagination_meta,
    assert_purchase_contract,
    assert_seller_lead,
    build_marketed_contract,
    factories,
    make_wholesaler_headers,
    read_buyer,
    read_contract,
    read_lead,
    read_offer,
    set_clock,
    validate_error,
    validate_paginated,
)

PROTECTED_LEAD_KWARGS = {
    "owner_name": factories.THIRD_LEAD_OWNER_NAME,
    "property_address": factories.THIRD_LEAD_PROPERTY_ADDRESS,
    "estimated_market_value_cents": 30000000,
    "recorded_senior_lien_cents": 500000,
    "distress_flags": ["FORECLOSURE_NOTICE", "PROBATE"],
}


def _over_cap_offer(api):
    """A still-SUBMITTED offer one cent above the STANDARD twelve percent cap."""
    return build_marketed_contract(
        api,
        clock="2026-08-10T00:00:00Z",
        buyer_price_cents=20160001,
        buyer_deposit_cents=1000000,
        structure_election="ASSIGNMENT_ELECTED",
        contract_kwargs={
            "purchase_price_cents": 18000000,
            "earnest_money_cents": 500000,
            "inspection_period_days": 7,
        },
    )


def _protected_deal_past_its_cutoff(api):
    """A PROTECTED lead whose contract cutoff fell on 2026-08-10."""
    return build_marketed_contract(
        api,
        clock="2026-08-10T00:00:00Z",
        buyer_price_cents=19110000,
        buyer_deposit_cents=1000000,
        structure_election="ASSIGNMENT_ELECTED",
        lead_kwargs=dict(PROTECTED_LEAD_KWARGS),
        contract_kwargs={
            "purchase_price_cents": 18200000,
            "earnest_money_cents": 500000,
            "inspection_period_days": 7,
            "closing_window_start_at": "2026-08-12T00:00:00Z",
            "closing_window_end_at": "2026-08-20T00:00:00Z",
        },
    )


class TestOfferStateOutranksTheFeeCap:
    """Papering an unaccepted offer that also busts the cap."""

    def test_unaccepted_offer_reports_the_state_failure_not_the_fiscal_one(self, api):
        """
        "The guards, in order: a wholesaler on a compliance hold reports
        `ERR_WHOLESALER_COMPLIANCE_HOLD`; a referenced offer whose status is not
        `ACCEPTED` reports `ERR_OFFER_NOT_ACCEPTED`, and this outranks every
        fiscal check on the same request"

        "**`ERR_OFFER_NOT_ACCEPTED`** (409) — the referenced offer's status is
        not `ACCEPTED`. Guards agreement execution, and outranks every fiscal
        check on the same request."

        Design: Difficulty/priority_pair_validation_conflict/agreement_state_precondition_outranks_fee_cap_check
        """
        scenario = _over_cap_offer(api)
        assert_assignment_offer(scenario.offer, status="SUBMITTED")

        response = api.create_assignment_agreement(
            factories.assignment_agreement_payload(scenario.offer_id, "ASSIGNMENT"),
            make_wholesaler_headers(scenario.w_id),
        )
        validate_error(response, ApiErrorId.OFFER_NOT_ACCEPTED, 409)

        _, meta = validate_paginated(
            api.list_assignment_agreements(
                make_wholesaler_headers(scenario.w_id),
                {"assignment_offer_id": scenario.offer_id},
            )
        )
        assert_pagination_meta(meta, total_count=0)

        untouched = read_offer(api, scenario.offer_id, scenario.w_id)
        assert_assignment_offer(untouched, status="SUBMITTED")
        assert_nulls(
            untouched,
            "accepted_at",
            "assignment_fee_cents",
            label="assignment_offer",
        )
        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id),
            assignment_status="MARKETED",
        )

    def test_the_outranked_cap_violation_is_real_and_surfaces_on_acceptance(
        self, api
    ):
        """
        "The implied assignment fee is the offer's `buyer_price_cents` less the
        contract's `purchase_price_cents`. The cap is a share of the contract
        price that tightens as the seller's protection tier rises: twelve percent
        for a `STANDARD` lead, eight percent for `ELEVATED`, five percent for
        `PROTECTED`. The cap in cents is the contract's `purchase_price_cents`
        multiplied by that share and taken to the floor, and the operation is
        rejected only when the implied fee is **strictly greater** than the cap —
        a fee landing exactly on the cap is permitted."

        "and an implied fee above the seller's protection-tier cap reports
        `ERR_ASSIGNMENT_FEE_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/agreement_state_precondition_outranks_fee_cap_check
        """
        scenario = _over_cap_offer(api)
        assert_seller_lead(scenario.lead, protection_tier="STANDARD")
        implied_fee = (
            scenario.offer["buyer_price_cents"]
            - scenario.contract["purchase_price_cents"]
        )
        # floor(18000000 x 0.12) == 2160000, and the bid implies one cent more.
        assert implied_fee == 2160001, (
            f"the bid must imply a fee one cent over the cap, got {implied_fee}"
        )

        response = api.accept_assignment_offer(
            scenario.offer_id, make_wholesaler_headers(scenario.w_id)
        )
        validate_error(response, ApiErrorId.ASSIGNMENT_FEE_CAP_EXCEEDED, 422)

        assert_assignment_offer(
            read_offer(api, scenario.offer_id, scenario.w_id), status="SUBMITTED"
        )
        assert_cash_buyer(
            read_buyer(api, scenario.buyer_id, scenario.w_id),
            committed_deposit_cents=1000000,
            active_offer_count=1,
        )


class TestCoolingOffOutranksTheAssignmentCutoff:
    """An acceptance that is both too early for the seller and too late overall."""

    def test_protected_seller_window_is_reported_ahead_of_the_passed_cutoff(
        self, api
    ):
        """
        "The cooling-off check sitting above the deadline check is likewise
        intentional: a request that is both inside a protected seller's
        cooling-off window and past the assignment cutoff reports the
        seller-protection failure."

        "Where the lead's `protection_tier` is `PROTECTED`, acceptance is refused
        at every instant strictly before seventy-two hours after the lead's
        `screened_at`, and permitted from that instant onward."

        Design: Difficulty/priority_pair_validation_conflict/cooling_off_safety_outranks_assignment_deadline_temporal
        """
        scenario = _protected_deal_past_its_cutoff(api)
        lead = read_lead(api, scenario.lead_id, scenario.w_id)
        assert_seller_lead(
            lead,
            protection_tier="PROTECTED",
            net_equity_cents=29500000,
            screened_at="2026-08-10T00:00:00Z",
        )
        assert_equity_pct_four_places(lead["equity_pct"])
        assert Decimal(str(lead["equity_pct"])) == Decimal("0.9833"), (
            f"29500000 / 30000000 to four places is 0.9833, got {lead['equity_pct']!r}"
        )
        assert_purchase_contract(
            scenario.contract, assignment_deadline_at="2026-08-10T00:00:00Z"
        )

        # One day past the cutoff, two days short of the cooling-off end.
        set_clock(api, "2026-08-11T00:00:00Z")
        response = api.accept_assignment_offer(
            scenario.offer_id, make_wholesaler_headers(scenario.w_id)
        )
        validate_error(response, ApiErrorId.COOLING_OFF_NOT_ELAPSED, 422)

        untouched = read_offer(api, scenario.offer_id, scenario.w_id)
        assert_assignment_offer(untouched, status="SUBMITTED")
        assert_nulls(
            untouched,
            "accepted_at",
            "assignment_fee_cents",
            label="assignment_offer",
        )
        assert_cash_buyer(
            read_buyer(api, scenario.buyer_id, scenario.w_id),
            committed_deposit_cents=1000000,
            active_offer_count=1,
        )

    def test_the_outranked_cutoff_violation_surfaces_once_cooling_off_elapses(
        self, api
    ):
        """
        "The create also derives `assignment_deadline_at` as
        `closing_window_start_at` less forty-eight hours, and moves the lead to
        `UNDER_CONTRACT`."

        "Acceptance is permitted at every instant strictly before
        `assignment_deadline_at`, which is forty-eight hours before the earliest
        permitted close, and refused from that instant onward."

        "the assignment cutoff having been reached or passed reports
        `ERR_ASSIGNMENT_DEADLINE_PASSED`"

        Design: Difficulty/priority_pair_validation_conflict/cooling_off_safety_outranks_assignment_deadline_temporal
        """
        scenario = _protected_deal_past_its_cutoff(api)
        assert_purchase_contract(
            scenario.contract,
            purchase_price_cents=18200000,
            assignment_deadline_at="2026-08-10T00:00:00Z",
        )

        # Seventy-two hours after the 2026-08-10 screen, so the seller-protection
        # window has closed and only the cutoff is still violated.
        set_clock(api, "2026-08-13T00:00:00Z")
        response = api.accept_assignment_offer(
            scenario.offer_id, make_wholesaler_headers(scenario.w_id)
        )
        validate_error(response, ApiErrorId.ASSIGNMENT_DEADLINE_PASSED, 409)

        assert_assignment_offer(
            read_offer(api, scenario.offer_id, scenario.w_id), status="SUBMITTED"
        )
        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id),
            assignment_status="MARKETED",
            contract_status="SIGNED",
        )
