"""
Edges evaluated to the cent and to the single record: an implied fee landing
exactly on the protection-tier cap, and a comparable set landing exactly on the
three-comparable minimum.
"""

from test_helpers import (
    ApiErrorId,
    add_buyer,
    assert_assignment_offer,
    assert_cash_buyer,
    assert_deal_analysis,
    assert_nulls,
    build_marketed_contract,
    build_screened_lead,
    comparable,
    factories,
    make_wholesaler_headers,
    read_analysis,
    read_buyer,
    read_offer,
    repair_item,
    submit_offer,
    upload_proof_of_funds,
    validate_error,
    validate_success,
    verify_proof_of_funds,
    MIN_QUALIFYING_COMPS,
)

CONTRACT_TERMS = {
    "purchase_price_cents": 18000000,
    "earnest_money_cents": 500000,
    "inspection_period_days": 7,
}


def _two_bids_astride_the_cap(api):
    """
    The over-cap bidder is on the contract first; the exactly-on-cap bidder is a
    second buyer of the same desk.
    """
    scenario = build_marketed_contract(
        api,
        clock="2026-08-10T00:00:00Z",
        buyer_price_cents=20160001,
        buyer_deposit_cents=1000000,
        structure_election="ASSIGNMENT_ELECTED",
        buyer_kwargs={
            "legal_name": factories.SECOND_CASH_BUYER_LEGAL_NAME,
            "contact_email": factories.SECOND_CASH_BUYER_CONTACT_EMAIL,
            "document_ref": "pof-brazos-001",
        },
        contract_kwargs=dict(CONTRACT_TERMS),
    )
    on_cap_buyer = add_buyer(
        api,
        scenario.w_id,
        legal_name=factories.CASH_BUYER_LEGAL_NAME,
        contact_email=factories.CASH_BUYER_CONTACT_EMAIL,
    )
    proof = upload_proof_of_funds(
        api,
        on_cap_buyer["id"],
        stated_funds_cents=25500000,
        document_ref="pof-ridgeline-001",
        expires_at="2026-12-01T00:00:00Z",
    )
    verify_proof_of_funds(
        api,
        proof["id"],
        scenario.w_id,
        verification_decision="VERIFIED",
        verified_funds_cents=25500000,
    )
    on_cap_offer = submit_offer(
        api,
        scenario.pc_id,
        on_cap_buyer["id"],
        20160000,
        scenario.refresh_contract()["version"],
        buyer_deposit_cents=1000000,
    )
    return scenario, on_cap_buyer, on_cap_offer


class TestFeeCapBoundaryIsStrictlyGreater:
    """One cent decides between an accepted bid and a rejected one."""

    def test_one_cent_over_the_cap_is_refused(self, api):
        """
        "The cap in cents is the contract's `purchase_price_cents` multiplied by
        that share and taken to the floor, and the operation is rejected only
        when the implied fee is **strictly greater** than the cap — a fee landing
        exactly on the cap is permitted."

        "**`ERR_ASSIGNMENT_FEE_CAP_EXCEEDED`** (422) — the implied assignment fee
        exceeds the seller's protection-tier cap. Guards offer acceptance and
        agreement execution, and sits at the very bottom of the ladder"

        Design: Difficulty/boundary_precision_check/assignment_fee_exactly_at_statutory_cap_is_permitted
        """
        scenario, _, _ = _two_bids_astride_the_cap(api)

        response = api.accept_assignment_offer(
            scenario.offer_id, make_wholesaler_headers(scenario.w_id)
        )
        validate_error(response, ApiErrorId.ASSIGNMENT_FEE_CAP_EXCEEDED, 422)

        refused = read_offer(api, scenario.offer_id, scenario.w_id)
        assert_assignment_offer(
            refused, status="SUBMITTED", buyer_price_cents=20160001
        )
        assert_nulls(
            refused, "accepted_at", "assignment_fee_cents", label="assignment_offer"
        )

    def test_a_fee_landing_exactly_on_the_cap_is_accepted(self, api):
        """
        "Acceptance stamps `accepted_at` from the logical clock and writes
        `assignment_fee_cents` on the offer as the implied fee fixed at that
        moment. It then lapses the competition: every sibling offer on the same
        contract still in a live status is driven to `LAPSED`, releasing each of
        their deposits and recomputing each affected buyer's committed capital and
        tier."

        "The cap is a share of the contract price that tightens as the seller's
        protection tier rises: twelve percent for a `STANDARD` lead, eight percent
        for `ELEVATED`, five percent for `PROTECTED`."

        Design: Difficulty/boundary_precision_check/assignment_fee_exactly_at_statutory_cap_is_permitted
        """
        scenario, on_cap_buyer, on_cap_offer = _two_bids_astride_the_cap(api)

        response = api.accept_assignment_offer(
            on_cap_offer["id"], make_wholesaler_headers(scenario.w_id)
        )
        accepted = validate_success(response, 200)

        # 20160000 - 18000000 == 2160000 == floor(18000000 x 0.12).
        assert_assignment_offer(
            accepted,
            status="ACCEPTED",
            buyer_price_cents=20160000,
            assignment_fee_cents=2160000,
            accepted_at="2026-08-10T00:00:00Z",
        )
        assert_assignment_offer(
            read_offer(api, scenario.offer_id, scenario.w_id), status="LAPSED"
        )
        assert_cash_buyer(
            read_buyer(api, on_cap_buyer["id"], scenario.w_id),
            committed_deposit_cents=1000000,
            active_offer_count=1,
        )
        assert_cash_buyer(
            read_buyer(api, scenario.buyer_id, scenario.w_id),
            committed_deposit_cents=0,
            active_offer_count=0,
            available_funds_cents=25500000,
        )


class TestQualifyingComparableMinimumIsInclusive:
    """Two qualifying comparables cannot finalize; exactly three can."""

    def test_two_qualifying_comparables_cannot_lock_a_ceiling(self, api):
        """
        "Its `distance_miles` must be at most 0.50 miles from the subject,
        inclusive."

        "`qualifying_comp_count` is the number of comparables passing all three,
        and it is recomputed whenever the analysis is created."

        "**Finalization** locks the price ceiling. It is available only from
        status `DRAFT`, requires at least three qualifying comparables — fewer
        reports `ERR_INSUFFICIENT_QUALIFYING_COMPS` — and takes a single input,
        `valuation_variant`, which must be `CONSERVATIVE` or `AGGRESSIVE`."

        Design: Difficulty/boundary_precision_check/insufficient_qualifying_comparables_blocks_finalize
        """
        scenario = build_screened_lead(api, clock="2026-08-10T00:00:00Z")
        analysis = validate_success(
            api.create_deal_analysis(
                factories.deal_analysis_payload(
                    scenario.lead_id,
                    scenario.lead["version"],
                    subject_gla_sqft=1800,
                    comparables=[
                        comparable(30000000, 0.10, 10, 1800, 0),
                        comparable(30000000, 0.20, 10, 1800, 0),
                        comparable(30000000, 0.60, 10, 1800, 0),
                    ],
                    repair_scope_items=[repair_item("ROOF", 1000000, 1200000)],
                ),
                make_wholesaler_headers(scenario.w_id),
            ),
            201,
        )
        # The 0.60-mile sale falls outside the inclusive half-mile band.
        assert_deal_analysis(analysis, status="DRAFT", qualifying_comp_count=2)

        response = api.finalize_deal_analysis(
            analysis["id"],
            factories.finalize_payload("AGGRESSIVE"),
            make_wholesaler_headers(scenario.w_id),
        )
        validate_error(response, ApiErrorId.INSUFFICIENT_QUALIFYING_COMPS, 422)

        still_draft = read_analysis(api, analysis["id"], scenario.w_id)
        assert_deal_analysis(
            still_draft, status="DRAFT", qualifying_comp_count=2
        )
        assert_nulls(
            still_draft,
            "valuation_variant",
            "arv_cents",
            "repair_estimate_cents",
            "max_allowable_offer_cents",
            "finalized_at",
            label="deal_analysis",
        )

    def test_exactly_three_qualifying_comparables_finalize(self, api):
        """
        "A comparable qualifies only when all three filters pass, and the filters
        are identical under both valuation variants."

        "On success the analysis moves `DRAFT → FINALIZED`, and
        `valuation_variant`, `arv_cents`, `repair_estimate_cents`,
        `max_allowable_offer_cents` and `finalized_at` are all written."

        "`max_allowable_offer_cents` is the after-repair value multiplied by that
        variant's multiplier and taken to the floor, then reduced by the repair
        estimate, then reduced by a minimum assignment margin of one million
        cents"

        Design: Difficulty/boundary_precision_check/insufficient_qualifying_comparables_blocks_finalize
        """
        scenario = build_screened_lead(
            api,
            clock="2026-08-10T00:00:00Z",
            lead_kwargs={
                "owner_name": factories.SECOND_LEAD_OWNER_NAME,
                "property_address": factories.SECOND_LEAD_PROPERTY_ADDRESS,
            },
        )
        analysis = validate_success(
            api.create_deal_analysis(
                factories.deal_analysis_payload(
                    scenario.lead_id,
                    scenario.lead["version"],
                    subject_gla_sqft=1800,
                    comparables=[
                        comparable(30000000, 0.10, 10, 1800, 0),
                        comparable(30000000, 0.20, 10, 1800, 0),
                        comparable(30000000, 0.50, 180, 2160, 0),
                    ],
                    repair_scope_items=[repair_item("ROOF", 1000000, 1200000)],
                ),
                make_wholesaler_headers(scenario.w_id),
            ),
            201,
        )
        assert_deal_analysis(
            analysis, status="DRAFT", qualifying_comp_count=MIN_QUALIFYING_COMPS
        )

        response = api.finalize_deal_analysis(
            analysis["id"],
            factories.finalize_payload("AGGRESSIVE"),
            make_wholesaler_headers(scenario.w_id),
        )
        finalized = validate_success(response, 200)

        # floor(30000000 x 0.75) - 1000000 - 1000000 == 20500000.
        assert_deal_analysis(
            finalized,
            status="FINALIZED",
            valuation_variant="AGGRESSIVE",
            qualifying_comp_count=3,
            arv_cents=30000000,
            repair_estimate_cents=1000000,
            max_allowable_offer_cents=20500000,
            finalized_at="2026-08-10T00:00:00Z",
        )
