"""Origination pricing: the volume tier, the statutory ceiling above it, and the
basis-point minimum-down-payment test that gates submission.
"""

from test_helpers import (
    ApiErrorId,
    add_on_finance_charge_cents,
    assert_installments_sum,
    factories,
    fixtures,
    get_success_data,
    simple_interest_periods,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import ANALYST_ORIGIN, COMPLIANCE


def _dual_regime_context(api):
    """Clock at 2026-08-15, a licensed TX regime, a licensed CA regime, parties."""
    fixtures.set_clock(api, "2026-08-15T00:00:00Z")
    tx = fixtures.create_state_regime(
        api,
        rule_payload=factories.tx_state_rate_rule(),
        license_payload=factories.license_payload(license_number="PFC-TX-001"),
    )
    ca = fixtures.create_state_regime(
        api,
        rule_payload=factories.ca_state_rate_rule(),
        license_payload=factories.license_payload(license_number="PFC-CA-001"),
    )
    parties = fixtures.create_parties(api)
    return tx, ca, parties


def _draft_with_one_policy(
    api, parties, rule_id, down_payment_cents, service_fee_cents, policy_number
):
    """A DRAFT note under `rule_id` carrying one policy quoted at 600000."""
    agreement = get_success_data(
        api.create_agreement(
            factories.agreement(
                parties["insured_id"],
                parties["agent_id"],
                rule_id,
                down_payment_cents=down_payment_cents,
                service_fee_cents=service_fee_cents,
                installment_count=6,
                first_installment_due_date="2026-10-01",
            ),
            ANALYST_ORIGIN,
        )
    )
    policy = get_success_data(
        api.attach_policy(
            agreement["id"],
            factories.financed_policy(
                parties["insurer_id"],
                policy_number=policy_number,
                gross_premium_cents=600000,
            ),
            ANALYST_ORIGIN,
        )
    )
    return agreement, policy


class TestVolumeTierUnderTheStatutoryCeiling:
    """The tier lookup runs on the amount financed, then the statute caps it."""

    def test_amount_financed_exactly_on_the_tier_one_ceiling_keeps_1800_bps(self, api):
        """An amount financed sitting exactly on the first tier boundary prices at
        the first tier rate.

        The PRD states: "Third, a volume tier is selected from the amount
        financed: an amount financed of 5,000 dollars or less takes a tier rate
        of 1800 basis points, an amount above 5,000 dollars but not above 20,000
        dollars takes 1500 basis points, and anything above 20,000 dollars takes
        1200 basis points".  With a premium basis of 600000, a down payment of
        102000 and a service fee of 2000 the amount financed is exactly 500000,
        which is "5,000 dollars or less", so the tier rate is 1800 and the TX
        ceiling of 1800 leaves it untouched.

        Design: Difficulty/combinatorial_formula/tiered_rate_boundary_nested_under_statutory_ceiling
        """
        tx, _ca, parties = _dual_regime_context(api)
        agreement, _policy = _draft_with_one_policy(
            api, parties, tx["rule_id"], 102000, 2000, "MC-X-3001"
        )

        priced = validate_success(
            api.submit_agreement(agreement["id"], ANALYST_ORIGIN), 200
        )

        assert priced["amount_financed_cents"] == 500000, (
            "amount_financed_cents is the premium basis minus down_payment_cents "
            "plus service_fee_cents: 600000 - 102000 + 2000"
        )
        assert priced["effective_annual_rate_bps"] == 1800, (
            "an amount financed of exactly 500000 cents is '5,000 dollars or "
            "less' and therefore takes the 1800 basis point tier rate"
        )
        expected_fc = add_on_finance_charge_cents(500000, 1800, 6)
        assert expected_fc == 45000, "the derivation itself must land on 45000"
        assert priced["finance_charge_cents"] == expected_fc, (
            "ADD_ON multiplies amount_financed_cents by effective_annual_rate_bps "
            "and installment_count, divides by 10000 and by 12, and rounds the "
            f"single result half up: expected {expected_fc}"
        )
        assert priced["total_of_payments_cents"] == 545000, (
            "total_of_payments_cents is amount_financed_cents plus "
            "finance_charge_cents: 500000 + 45000"
        )

    def test_one_cent_past_the_tier_ceiling_drops_the_rate_to_1500_bps(self, api):
        """One cent more financed selects the cheaper second tier, so the note
        with the larger balance carries the smaller finance charge.

        The PRD states: "an amount above 5,000 dollars but not above 20,000
        dollars takes 1500 basis points".  The tier is keyed on the amount
        financed, so a down payment one cent smaller pushes the amount financed
        to 500001 and moves the note into the next tier.

        Design: Difficulty/combinatorial_formula/tiered_rate_boundary_nested_under_statutory_ceiling
        """
        tx, _ca, parties = _dual_regime_context(api)
        note_x, _px = _draft_with_one_policy(
            api, parties, tx["rule_id"], 102000, 2000, "MC-X-3001"
        )
        note_y, _py = _draft_with_one_policy(
            api, parties, tx["rule_id"], 101999, 2000, "MC-Y-3002"
        )

        priced_x = validate_success(
            api.submit_agreement(note_x["id"], ANALYST_ORIGIN), 200
        )
        priced_y = validate_success(
            api.submit_agreement(note_y["id"], ANALYST_ORIGIN), 200
        )

        assert priced_y["amount_financed_cents"] == 500001, (
            "600000 - 101999 + 2000 == 500001, one cent past the first tier"
        )
        assert priced_y["effective_annual_rate_bps"] == 1500, (
            "one cent above the first tier ceiling selects the 1500 basis point "
            "tier rate"
        )
        expected_fc = add_on_finance_charge_cents(500001, 1500, 6)
        assert expected_fc == 37500, "round_half_up(37500.075) is 37500"
        assert priced_y["finance_charge_cents"] == expected_fc, (
            f"the ADD_ON charge on 500001 at 1500 bps over 6 months is {expected_fc}"
        )
        assert priced_y["total_of_payments_cents"] == 537501, (
            "total_of_payments_cents is 500001 + 37500"
        )
        assert (
            priced_x["finance_charge_cents"] - priced_y["finance_charge_cents"] == 7500
        ), (
            "financing one cent more must cost 7500 cents less, which only "
            "happens when the tier lookup runs on the amount financed before the "
            "comparison against the statutory ceiling"
        )

    def test_statutory_ceiling_clamps_the_tier_rate_and_cuts_a_declining_schedule(
        self, api
    ):
        """A regime whose ceiling sits below the tier rate wins, and its
        SIMPLE_INTEREST schedule declines period by period.

        The PRD states: "The statutory ceiling always wins, in both branches."
        The CA note finances 481500, which is inside the first tier and would
        take 1800 basis points, but the regime caps the annual rate at 1200.

        Design: Difficulty/combinatorial_formula/tiered_rate_boundary_nested_under_statutory_ceiling
        """
        _tx, ca, parties = _dual_regime_context(api)
        note_z, policy_z = _draft_with_one_policy(
            api, parties, ca["rule_id"], 120000, 1500, "MC-Z-3003"
        )

        priced = validate_success(
            api.submit_agreement(note_z["id"], ANALYST_ORIGIN), 200
        )

        assert priced["amount_financed_cents"] == 481500, (
            "600000 - 120000 + 1500 == 481500"
        )
        assert priced["effective_annual_rate_bps"] == 1200, (
            "the tier rate for 481500 is 1800, but the effective rate is the "
            "smaller of the tier rate and the regime's max_annual_rate_bps, so "
            "the statutory 1200 governs"
        )
        periods = simple_interest_periods(481500, 1200, 6)
        assert periods == [4815, 4013, 3210, 2408, 1605, 803], (
            "each period's interest accrues on the declining balance and is "
            f"rounded before it is summed, got {periods}"
        )
        assert priced["finance_charge_cents"] == sum(periods) == 16854, (
            "SIMPLE_INTEREST sums the per-period rounded interest; summing exact "
            "products and rounding once at the end is a forbidden result"
        )
        assert priced["total_of_payments_cents"] == 498354, (
            "total_of_payments_cents is 481500 + 16854"
        )

        # Activate so the schedule is cut, then read it back.
        bundle = dict(parties)
        fixtures.verify_policy(api, bundle, policy_z["id"])
        fixtures.set_clock(api, "2026-09-01T00:00:00Z")
        validate_success(api.activate_agreement(note_z["id"], ANALYST_ORIGIN), 200)

        rows, meta = validate_paginated(
            api.list_installments(note_z["id"], ANALYST_ORIGIN, {"limit": 100})
        )
        assert meta["total_count"] == 6, "six installments were requested"
        rows.sort(key=lambda row: row["installment_number"])
        assert [row["amount_cents"] for row in rows] == [
            85065,
            84263,
            83460,
            82658,
            81855,
            81053,
        ], "under SIMPLE_INTEREST the installments decline"
        assert [row["finance_charge_component_cents"] for row in rows] == periods, (
            "each installment's finance charge component is that period's "
            "interest on the outstanding balance at the start of the period"
        )
        assert_installments_sum(rows, 498354, 16854)


class TestMinimumDownPaymentEquality:
    """The statutory minimum is a basis-point cross-multiplication and equality
    passes it."""

    def test_one_cent_below_the_statutory_minimum_is_refused(self, api):
        """A down payment ten thousand short of the line is refused and the note
        stays exactly as it was.

        The PRD states: "The minimum-down-payment test is a basis-point
        comparison and equality passes it: the down payment multiplied by 10000
        must be greater than or equal to the premium basis multiplied by the
        regime's `min_down_payment_bps`, where the premium basis at submission is
        the sum of the agency-quoted `gross_premium_cents` across the note's
        policies."  119999 * 10000 is 1199990000, below 600000 * 2000.

        Design: Difficulty/boundary_precision_check/minimum_down_payment_exact_equality_on_submit
        """
        _tx, ca, parties = _dual_regime_context(api)
        note_low, _policy = _draft_with_one_policy(
            api, parties, ca["rule_id"], 119999, 1500, "MC-CA-8001"
        )

        validate_error(
            api.submit_agreement(note_low["id"], ANALYST_ORIGIN),
            ApiErrorId.DOWN_PAYMENT_BELOW_MINIMUM.value,
            422,
        )

        after = validate_success(
            api.get_agreement(note_low["id"], ANALYST_ORIGIN), 200
        )
        assert after["status"] == "DRAFT", (
            "a refused submission leaves the financing status in DRAFT"
        )
        assert after["quote_basis"] is None, (
            "quote_basis is stamped only by a successful submission, so it must "
            "still be null on the refused note"
        )

    def test_down_payment_exactly_at_the_minimum_is_accepted_and_priced(self, api):
        """Exactly one fifth of the premium passes the ratio test.

        The PRD states: "A regime demanding 2000 basis points — one fifth of the
        premium — therefore accepts a down payment of exactly one fifth and
        refuses one cent less."

        Design: Difficulty/boundary_precision_check/minimum_down_payment_exact_equality_on_submit
        """
        _tx, ca, parties = _dual_regime_context(api)
        note_eq, _policy = _draft_with_one_policy(
            api, parties, ca["rule_id"], 120000, 1500, "MC-CA-8002"
        )

        priced = validate_success(
            api.submit_agreement(note_eq["id"], ANALYST_ORIGIN), 200
        )

        assert priced["status"] == "PENDING_VERIFICATION", (
            "120000 * 10000 == 600000 * 2000 exactly, and equality passes, so "
            "the financing status advances DRAFT -> PENDING_VERIFICATION"
        )
        assert priced["quote_basis"] == "PROVISIONAL", (
            "a successful submission stamps quote_basis as PROVISIONAL"
        )
        assert priced["amount_financed_cents"] == 481500
        assert priced["effective_annual_rate_bps"] == 1200
        assert priced["finance_charge_cents"] == 16854
        assert priced["total_of_payments_cents"] == 498354

    def test_down_payment_one_cent_above_the_minimum_is_accepted(self, api):
        """One cent above the line also passes, and does not move the rounded
        per-period interest sum.

        The PRD states: "the down payment multiplied by 10000 must be greater
        than or equal to the premium basis multiplied by the regime's
        `min_down_payment_bps`".

        Design: Difficulty/boundary_precision_check/minimum_down_payment_exact_equality_on_submit
        """
        _tx, ca, parties = _dual_regime_context(api)
        note_high, _policy = _draft_with_one_policy(
            api, parties, ca["rule_id"], 120001, 1500, "MC-CA-8003"
        )

        priced = validate_success(
            api.submit_agreement(note_high["id"], ANALYST_ORIGIN), 200
        )

        assert priced["status"] == "PENDING_VERIFICATION"
        assert priced["amount_financed_cents"] == 481499, (
            "600000 - 120001 + 1500 == 481499"
        )
        assert priced["finance_charge_cents"] == 16854, (
            "one more cent of down payment does not change the rounded "
            "per-period interest sum, so the boundary is about the ratio test "
            "and not about pricing"
        )

    def test_only_accepted_submissions_increment_the_active_agreement_count(self, api):
        """The regime counter moves on submission and only on submission.

        The PRD states: "A successful submission runs the pricing engine in its
        **provisional** variant, stamps `quote_basis` as `PROVISIONAL`,
        increments the regime's `active_agreement_count` by 1 and advances the
        note's `version`."

        Design: Difficulty/boundary_precision_check/minimum_down_payment_exact_equality_on_submit
        """
        _tx, ca, parties = _dual_regime_context(api)
        note_low, _pl = _draft_with_one_policy(
            api, parties, ca["rule_id"], 119999, 1500, "MC-CA-8001"
        )
        note_eq, _pe = _draft_with_one_policy(
            api, parties, ca["rule_id"], 120000, 1500, "MC-CA-8002"
        )
        note_high, _ph = _draft_with_one_policy(
            api, parties, ca["rule_id"], 120001, 1500, "MC-CA-8003"
        )

        validate_error(
            api.submit_agreement(note_low["id"], ANALYST_ORIGIN),
            ApiErrorId.DOWN_PAYMENT_BELOW_MINIMUM.value,
            422,
        )
        validate_success(api.submit_agreement(note_eq["id"], ANALYST_ORIGIN), 200)
        validate_success(api.submit_agreement(note_high["id"], ANALYST_ORIGIN), 200)

        regime = validate_success(
            api.get_state_rate_rule(ca["rule_id"], COMPLIANCE), 200
        )
        assert regime["active_agreement_count"] == 2, (
            "only the two accepted submissions may be counted; the refused one "
            "must leave the counter alone"
        )
