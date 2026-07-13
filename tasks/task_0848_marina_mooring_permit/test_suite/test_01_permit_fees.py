"""Permit fee computation: provisional (full-season) vs final (prorated),
tiered/residency multiplier, and per-component proration rounding."""
from test_helpers import (
    validate_success,
    setup_active_permit,
    setup_offered_permit,
)

CLOCK_APR = "2026-04-01T00:00:00Z"
CLOCK_MAY15 = "2026-05-15T00:00:00Z"
CLOCK_MAY01 = "2026-05-01T00:00:00Z"


class TestProvisionalVsFinal:
    def test_provisional_and_final_fees_differ_on_activation(self, api):
        """PRD §3.4: "If the permit is a liveaboard, a flat surcharge of 50,000
        cents is added; the sum of the scaled length charge and the liveaboard
        surcharge is the provisional fee."
        PRD §3.4: "The final fee is the sum of those two separately-rounded
        components — never the rounding of a single combined gross figure."

        Design: Difficulty/dual_variant_calc/permit_fee_provisional_vs_final
        """
        bundle = setup_active_permit(
            api,
            clock=CLOCK_APR,
            activate_clock=CLOCK_MAY15,
            marina_overrides={"liveaboard_cap": 2},
            vessel_overrides={"length_ft": 30, "has_holding_tank": True},
            permit_overrides={"is_liveaboard": True},
        )
        permit = bundle["permit"]
        assert permit["provisional_fee_cents"] == 170000, permit["provisional_fee_cents"]
        assert permit["final_fee_cents"] == 157066, permit["final_fee_cents"]
        assert permit["status"] == "ACTIVE"

    def test_overpayment_refunded_on_invoice_at_activation(self, api):
        """PRD §3.4: "Whenever the resulting final fee is below the provisional
        fee the difference is refunded on the invoice: `amount_refunded_cents`
        rises by the positive difference between `provisional_fee_cents` and
        `final_fee_cents`, and the invoice becomes `PARTIALLY_REFUNDED`, or fully
        `REFUNDED` when the refund equals the amount paid."

        Design: Difficulty/dual_variant_calc/permit_fee_provisional_vs_final
        """
        bundle = setup_active_permit(
            api,
            clock=CLOCK_APR,
            activate_clock=CLOCK_MAY15,
            marina_overrides={"liveaboard_cap": 2},
            vessel_overrides={"length_ft": 30, "has_holding_tank": True},
            permit_overrides={"is_liveaboard": True},
        )
        invoice = bundle["invoice"]
        assert invoice["amount_refunded_cents"] == 12934, invoice["amount_refunded_cents"]
        assert invoice["status"] == "PARTIALLY_REFUNDED", invoice["status"]


class TestTieredMultiplierGross:
    def test_nonresident_mooring_provisional_fee(self, api):
        """PRD §3.4: "Its length component is the per-foot rate for the requested
        berth type — 4,000 cents per foot for a `SLIP`, 2,500 cents per foot for a
        `MOORING` — multiplied by the vessel's `length_ft` rounded up to a whole
        foot; that length component is then multiplied by the residency
        multiplier, which is 1.00 for a resident and 1.75 for a non-resident, and
        the product is rounded half up to whole cents to give the scaled length
        charge."

        Design: Difficulty/combinatorial_formula/permit_fee_gross_tiered_multiplier_mode_a
        """
        bundle = setup_offered_permit(
            api,
            clock=CLOCK_APR,
            berth_overrides={"berth_type": "MOORING", "size_class": "SMALL", "max_length_ft": 30},
            boater_overrides={"residency_status": "NON_RESIDENT"},
            vessel_overrides={"length_ft": 24},
            permit_overrides={"requested_berth_type": "MOORING", "requested_size_class": "SMALL"},
        )
        # 2500 * 24 * 1.75 = 105000
        assert bundle["permit"]["provisional_fee_cents"] == 105000

    def test_nonresident_mooring_fee_basis_and_offered(self, api):
        """PRD §3.3: "`fee_basis` copies the boater's residency (`RESIDENT` or
        `NON_RESIDENT`), and `priority_tier` is 0 for a resident and 1 for a
        non-resident, where the lower number ranks ahead."
        PRD §3.3: "the applicant is immediately assignable and the permit is
        created `OFFERED`."

        Design: Difficulty/combinatorial_formula/permit_fee_gross_tiered_multiplier_mode_a
        """
        bundle = setup_offered_permit(
            api,
            clock=CLOCK_APR,
            berth_overrides={"berth_type": "MOORING", "size_class": "SMALL", "max_length_ft": 30},
            boater_overrides={"residency_status": "NON_RESIDENT"},
            vessel_overrides={"length_ft": 24},
            permit_overrides={"requested_berth_type": "MOORING", "requested_size_class": "SMALL"},
        )
        assert bundle["permit"]["fee_basis"] == "NON_RESIDENT"
        assert bundle["permit"]["status"] == "OFFERED"


class TestProrationRoundingOrder:
    def test_final_fee_uses_per_component_rounding(self, api):
        """PRD §3.4: "Each component is prorated and rounded on its own: the
        scaled length charge multiplied by remaining days divided by season days,
        rounded half up to whole cents, plus the liveaboard surcharge multiplied
        by remaining days divided by season days, rounded half up to whole cents."
        PRD §3.4: "The final fee is the sum of those two separately-rounded
        components — never the rounding of a single combined gross figure."

        Design: Difficulty/combinatorial_formula/permit_fee_proration_rounding_order_mode_b
        """
        bundle = setup_active_permit(
            api,
            clock=CLOCK_APR,
            activate_clock=CLOCK_MAY15,
            marina_overrides={"liveaboard_cap": 2},
            vessel_overrides={"length_ft": 30, "has_holding_tank": True},
            permit_overrides={"is_liveaboard": True},
        )
        # length_prorated 110870 + live_prorated 46196 = 157066 (sum-then-round = 157065)
        assert bundle["permit"]["final_fee_cents"] == 157066

    def test_reconciled_refund_reflects_per_component_final(self, api):
        """PRD §3.4: "Whenever the resulting final fee is below the provisional
        fee the difference is refunded on the invoice: `amount_refunded_cents`
        rises by the positive difference between `provisional_fee_cents` and
        `final_fee_cents`, and the invoice becomes `PARTIALLY_REFUNDED`, or fully
        `REFUNDED` when the refund equals the amount paid."

        Design: Difficulty/combinatorial_formula/permit_fee_proration_rounding_order_mode_b
        """
        bundle = setup_active_permit(
            api,
            clock=CLOCK_APR,
            activate_clock=CLOCK_MAY15,
            marina_overrides={"liveaboard_cap": 2},
            vessel_overrides={"length_ft": 30, "has_holding_tank": True},
            permit_overrides={"is_liveaboard": True},
        )
        # 170000 - 157066 = 12934
        assert bundle["invoice"]["amount_refunded_cents"] == 12934


class TestImmediateOfferConsistency:
    def test_apply_returns_offered_with_invoice_immediately(self, api):
        """PRD §3.3: "the applicant is immediately assignable and the permit is
        created `OFFERED`."
        PRD §3.4: "Its length component is the per-foot rate for the requested
        berth type — 4,000 cents per foot for a `SLIP`, 2,500 cents per foot for a
        `MOORING` — multiplied by the vessel's `length_ft` rounded up to a whole
        foot; that length component is then multiplied by the residency
        multiplier, which is 1.00 for a resident and 1.75 for a non-resident, and
        the product is rounded half up to whole cents to give the scaled length
        charge."

        Design: Corner/consistency_model/permit_apply_returns_offered_state_immediately
        """
        bundle = setup_offered_permit(api, clock=CLOCK_MAY01)
        permit = bundle["permit"]
        assert permit["status"] == "OFFERED"
        assert permit["berth_id"] == bundle["berth"]["id"]
        # SLIP MEDIUM 30ft RESIDENT: 4000 * 30 * 1.00 = 120000
        assert permit["provisional_fee_cents"] == 120000
