"""Multi-step formulas whose intermediate rounding and input selection are pinned.

Both groups below exist because a plausible-looking rearrangement of the same
arithmetic produces a different integer from the same inputs.
"""

from test_helpers import (
    TEST_USERS,
    assert_offer,
    assert_settlement_conservation,
    create_fee_settlement_payload,
    create_offer_payload,
    raise_rights_dispute,
    read_agreement,
    read_negotiation,
    resolve_rights_dispute,
    setup_executed_agreement,
    setup_issued_settlement,
    setup_negotiation_with_report,
    setup_submitted_station_offer,
    validate_success,
)

THIRTY_MONTH_OFFER = {
    "base_rate_per_sub_cents": 250,
    "escalator_bp_per_year": 700,
    "term_months": 30,
}
HIGH_RATE_OFFER = {
    "base_rate_per_sub_cents": 310,
    "escalator_bp_per_year": 700,
    "term_months": 36,
}


def test_offer_total_rounds_each_year_before_multiplying(api):
    """A 30-month term sums three already-rounded yearly rates, not one rounded product.

    PRD §3.5: "The rounding order here is pinned and not negotiable: each per-year
    rate is rounded to whole cents *first*, and only then multiplied by basis and
    months and summed across years."

    Design: Difficulty/combinatorial_formula/offer_ladder_rounding_order_round_each_year_then_multiply
    """
    ctx = setup_negotiation_with_report()

    response = api.create_offer(
        ctx["negotiation"]["id"],
        create_offer_payload(ctx["report"]["id"], **THIRTY_MONTH_OFFER),
        ctx["negotiator_headers"],
    )
    offer = validate_success(response, 201)

    assert_offer(offer)
    assert offer["projection_basis_subscribers"] == 100000
    assert offer["year_rate_schedule_compound_cents"] == [250, 268, 287]
    assert offer["projected_total_fee_cents"] == 793800000
    assert offer["projected_total_fee_cents"] != 792735000
    assert offer["projected_total_fee_cents"] != 792600000


def test_persisted_offer_keeps_the_rounded_ladder_and_takes_one_round(api):
    """Reading the offer back shows the same pinned total and one consumed round.

    PRD §3.5: "A successful submission creates one offer with `status` at `SUBMITTED`
    and `rejection_reason` null, increments the negotiation's `round_number` by one
    and stamps the resulting value onto the offer's own `round_number`, recomputes
    the side-specific offer counter, flips the negotiation's `status` to the
    counterparty's turn, and increments the negotiation's `version` by one."

    Design: Difficulty/combinatorial_formula/offer_ladder_rounding_order_round_each_year_then_multiply
    """
    ctx = setup_submitted_station_offer(offer=THIRTY_MONTH_OFFER)

    response = api.get_offer(ctx["offer"]["id"], TEST_USERS["group_counsel_headers"])
    offer = validate_success(response, 200)

    assert offer["year_rate_schedule_compound_cents"] == [250, 268, 287]
    assert offer["projected_total_fee_cents"] == 793800000
    assert offer["round_number"] == 1

    negotiation = read_negotiation(ctx["negotiation"]["id"])
    assert negotiation["status"] == "AWAITING_DISTRIBUTOR_RESPONSE"
    assert negotiation["round_number"] == 1
    assert negotiation["station_offer_count"] == 1


def test_split_tier_keys_on_the_pre_credit_per_subscriber_rate(api):
    """A 310-cent rate takes the top tier even though credits shrink the base.

    PRD §3.9: "The pinned rule is that the tier keys on the **pre-credit
    per-subscriber rate** from Step 0 - `rate_per_sub_cents` - and never on the
    creditable base and never on `net_retained_cents`."

    Design: Difficulty/combinatorial_formula/reverse_comp_split_tier_keys_on_pre_credit_rate_not_on_net
    """
    ctx = setup_executed_agreement(offer=HIGH_RATE_OFFER)
    dispute = raise_rights_dispute(
        ctx["agreement"]["id"], ctx["station"]["id"], "STREAMING"
    )
    resolve_rights_dispute(dispute["id"], "EXCLUDED")

    response = api.create_fee_settlement(
        ctx["agreement"]["id"],
        create_fee_settlement_payload(ctx["report"]["id"]),
        TEST_USERS["group_counsel_headers"],
    )
    settlement = validate_success(response, 201)

    assert settlement["contract_year_index"] == 1
    assert settlement["rate_per_sub_cents"] == 310
    assert settlement["gross_fee_cents"] == 31000000
    assert settlement["rights_credit_cents"] == 3720000
    assert settlement["reverse_comp_split_bp"] == 6000
    assert settlement["reverse_comp_split_bp"] != 5500
    assert settlement["reverse_comp_cents"] == 16368000
    assert settlement["reverse_comp_cents"] != 15004000
    assert settlement["penetration_penalty_cents"] == 0
    assert settlement["net_retained_cents"] == 10912000
    assert settlement["net_retained_cents"] != 12276000
    assert_settlement_conservation(settlement)

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["granted_rights_scope"] == ["DIGITAL"]
    assert agreement["rights_credit_bp_total"] == 1200


def test_split_tier_does_not_move_when_a_credit_shrinks_the_base(api):
    """Excluding a right after issuance recomputes the credit but not the split rate.

    PRD §3.8: "At the third level, because the agreement's `rights_credit_bp_total`
    changed, every fee settlement on that agreement still in status `ISSUED`
    recomputes `rights_credit_cents`, `reverse_comp_cents`,
    `penetration_penalty_cents` and `net_retained_cents` by the split arithmetic in
    §3.9, processed in creation-timestamp ascending order."

    Design: Difficulty/combinatorial_formula/reverse_comp_split_tier_keys_on_pre_credit_rate_not_on_net
    """
    ctx = setup_issued_settlement(offer=HIGH_RATE_OFFER)
    assert ctx["settlement"]["rights_credit_cents"] == 0
    assert ctx["settlement"]["reverse_comp_split_bp"] == 6000
    assert ctx["settlement"]["reverse_comp_cents"] == 18600000
    assert ctx["settlement"]["net_retained_cents"] == 12400000

    dispute = raise_rights_dispute(
        ctx["agreement"]["id"], ctx["station"]["id"], "STREAMING"
    )
    response = api.resolve_rights_dispute(
        dispute["id"],
        {
            "resolution": "EXCLUDED",
            "resolution_note": "The claimed definition is outside the grant",
        },
        TEST_USERS["compliance_officer_headers"],
    )
    validate_success(response, 200)

    settlements = validate_success(
        api.list_fee_settlements(
            ctx["agreement"]["id"], TEST_USERS["group_counsel_headers"]
        ),
        200,
    )
    settlement = settlements[0]
    assert settlement["rate_per_sub_cents"] == 310
    assert settlement["reverse_comp_split_bp"] == 6000
    assert settlement["rights_credit_cents"] == 3720000
    assert settlement["reverse_comp_cents"] == 16368000
    assert settlement["net_retained_cents"] == 10912000
    assert_settlement_conservation(settlement)
