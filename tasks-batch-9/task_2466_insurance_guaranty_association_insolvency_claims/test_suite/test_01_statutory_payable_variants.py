"""The statutory net payable on a covered claim and its unelected mirror variant."""

from test_helpers import (
    advance_other_insurance,
    assert_covered_claim,
    assert_settlement_worksheet,
    read_claim,
    read_settlement_worksheet,
    register_other_insurance,
    setup_claim_with_resolved_other_insurance,
    setup_screened_claim,
)

OFFSET_THEN_CAP_PROFILE = {"cap_order_mode": "OFFSET_THEN_CAP"}
CAP_THEN_OFFSET_PROFILE = {
    "line_of_business": "COMMERCIAL_GENERAL_LIABILITY",
    "cap_order_mode": "CAP_THEN_OFFSET",
    "refund_priority_class": 3,
}

UNRETAINED_POLICY = {
    "policy_number": "PA-1001",
    "policyholder_name": "Ada Renner",
    "policyholder_net_worth_cents": 50_000_000,
    "large_deductible_cents": 0,
    "self_insured_retention_cents": 0,
    "collateral_held_cents": 0,
}
CGL_POLICY = {
    "policy_number": "CGL-2001",
    "line_of_business": "COMMERCIAL_GENERAL_LIABILITY",
    "policyholder_name": "Renner Fabrication LLC",
    "policyholder_net_worth_cents": 40_000_000,
    "annual_premium_cents": 900_000,
    "large_deductible_cents": 0,
    "self_insured_retention_cents": 0,
    "collateral_held_cents": 0,
}

PRIMARY_LAYER = {
    "carrier_name": "Northline Casualty",
    "policy_number": "NL-77",
    "coverage_type": "PRIMARY",
    "stated_limit_cents": 2_000_000,
}


class TestOffsetThenCapOrdering:
    """A line configured to offset before capping still pays the full per-claim cap."""

    def test_offset_then_cap_pays_the_full_cap_while_the_alternative_falls_short(self):
        """Under `OFFSET_THEN_CAP`, the statutory figure is obtained by subtracting both the
        other-insurance recovery and the statutory deductible from `covered_layer_cents`, taking
        whichever is smaller of that difference and `per_claim_cap_cents`, and flooring the result
        at 0; the alternative figure is obtained the other way round, by first taking whichever is
        smaller of `covered_layer_cents` and `per_claim_cap_cents`, then subtracting the
        other-insurance recovery and the statutory deductible, then flooring at 0.

        Design: Difficulty/dual_variant_calc/claim_payable_offset_then_cap_versus_cap_then_offset_on_same_loss
        """
        env = setup_claim_with_resolved_other_insurance(
            recovered_cents=1_200_000,
            claim_overrides={"claim_number": "C-1", "gross_loss_cents": 4_500_000},
            layer_overrides=dict(PRIMARY_LAYER),
            profile_overrides=dict(OFFSET_THEN_CAP_PROFILE),
            policy_overrides=dict(UNRETAINED_POLICY),
        )

        claim = read_claim(env["claim"]["id"])
        assert_covered_claim(claim)
        assert claim["net_payable_cents"] == 3_000_000, (
            "offsetting before capping must still reach the 3000000 per-claim cap, got "
            f"{claim['net_payable_cents']}"
        )
        assert claim["alt_net_payable_cents"] == 1_790_000, (
            "the unelected order caps first and then offsets, so the alternative is 1790000, got "
            f"{claim['alt_net_payable_cents']}"
        )
        assert claim["cap_binding"] == "PER_CLAIM", claim["cap_binding"]

    def test_settlement_worksheet_lays_out_every_term_and_the_variant_delta(self):
        """It returns `claim_id`, the governing `cap_order_mode`, `covered_basis_cents`,
        `attachment_point_cents`, `covered_layer_cents`, `other_insurance_recoverable_cents`, the
        line's `statutory_deductible_cents` and `per_claim_cap_cents`, `remaining_aggregate_cents`
        for the policy, `net_payable_cents`, `alt_net_payable_cents`, `variant_delta_cents` as the
        difference between the two payable variants, and `cap_binding`.

        Design: Difficulty/dual_variant_calc/claim_payable_offset_then_cap_versus_cap_then_offset_on_same_loss
        """
        env = setup_claim_with_resolved_other_insurance(
            recovered_cents=1_200_000,
            claim_overrides={"claim_number": "C-1", "gross_loss_cents": 4_500_000},
            layer_overrides=dict(PRIMARY_LAYER),
            profile_overrides=dict(OFFSET_THEN_CAP_PROFILE),
            policy_overrides=dict(UNRETAINED_POLICY),
        )

        worksheet = read_settlement_worksheet(env["claim"]["id"])
        assert_settlement_worksheet(worksheet)
        assert worksheet["claim_id"] == env["claim"]["id"]
        assert worksheet["cap_order_mode"] == "OFFSET_THEN_CAP", worksheet["cap_order_mode"]
        assert worksheet["covered_basis_cents"] == 4_500_000
        assert worksheet["attachment_point_cents"] == 0, (
            "with no retained layer and no collateral the attachment point is 0, got "
            f"{worksheet['attachment_point_cents']}"
        )
        assert worksheet["covered_layer_cents"] == 4_500_000
        assert worksheet["other_insurance_recoverable_cents"] == 1_200_000
        assert worksheet["statutory_deductible_cents"] == 10_000
        assert worksheet["per_claim_cap_cents"] == 3_000_000
        assert worksheet["net_payable_cents"] == 3_000_000
        assert worksheet["alt_net_payable_cents"] == 1_790_000
        assert abs(worksheet["variant_delta_cents"]) == 1_210_000, (
            "the two variants diverge by exactly 1210000 cents on this loss, got "
            f"{worksheet['variant_delta_cents']}"
        )

    def test_reported_exhaustion_reprices_the_claim_and_moves_only_the_alternative(self):
        """Both resolutions recompute the claim's `other_insurance_recoverable_cents`, re-run the
        statutory net payable computation so that `net_payable_cents`, `alt_net_payable_cents` and
        `cap_binding` reflect the new offset, and increment the claim's `version` by one.

        Design: Difficulty/dual_variant_calc/claim_payable_offset_then_cap_versus_cap_then_offset_on_same_loss
        """
        env = setup_screened_claim(
            claim_overrides={"claim_number": "C-1", "gross_loss_cents": 4_500_000},
            profile_overrides=dict(OFFSET_THEN_CAP_PROFILE),
            policy_overrides=dict(UNRETAINED_POLICY),
        )
        before = read_claim(env["claim"]["id"])
        assert before["net_payable_cents"] == 3_000_000
        assert before["alt_net_payable_cents"] == 2_990_000, (
            "with no recovery yet the alternative order only loses the statutory deductible, got "
            f"{before['alt_net_payable_cents']}"
        )

        layer = register_other_insurance(env, **PRIMARY_LAYER)
        advance_other_insurance(env, layer["id"], "PURSUING")
        pursuing = read_claim(env["claim"]["id"])
        assert pursuing["alt_net_payable_cents"] == 2_990_000, (
            "a layer merely being pursued changes no money"
        )

        advance_other_insurance(env, layer["id"], "EXHAUSTED", 1_200_000)
        after = read_claim(env["claim"]["id"])
        assert after["net_payable_cents"] == 3_000_000, (
            "the elected order absorbs the recovery under the cap and still pays 3000000"
        )
        assert after["alt_net_payable_cents"] == 1_790_000, (
            "the alternative order subtracts the 1200000 recovery from the already-capped figure"
        )
        assert after["version"] > pursuing["version"], "the resolution must bump the claim version"


class TestCapThenOffsetOrdering:
    """The same loss data under the opposite configuration flag."""

    def test_cap_then_offset_makes_the_lower_figure_the_statutory_one(self):
        """Under `CAP_THEN_OFFSET` the two are exchanged exactly: the statutory figure first
        truncates `covered_layer_cents` to `per_claim_cap_cents` and subtracts the two offsets
        afterwards, flooring at 0, while the alternative figure subtracts the two offsets first,
        truncates to `per_claim_cap_cents`, and floors at 0.

        Design: Difficulty/combinatorial_formula/cap_then_offset_profile_flips_which_payable_is_statutory
        """
        env = setup_claim_with_resolved_other_insurance(
            recovered_cents=1_200_000,
            claim_overrides={"claim_number": "C-9", "claimant_name": "Cora Diaz", "gross_loss_cents": 4_500_000},
            layer_overrides={**PRIMARY_LAYER, "policy_number": "NL-88"},
            profile_overrides=dict(CAP_THEN_OFFSET_PROFILE),
            policy_overrides=dict(CGL_POLICY),
        )

        claim = read_claim(env["claim"]["id"])
        assert_covered_claim(claim)
        assert claim["net_payable_cents"] == 1_790_000, (
            "capping before offsetting yields the strictly lower statutory payable, got "
            f"{claim['net_payable_cents']}"
        )
        assert claim["alt_net_payable_cents"] == 3_000_000, (
            "the unelected order offsets first and still reaches the cap, got "
            f"{claim['alt_net_payable_cents']}"
        )
        assert claim["cap_binding"] == "PER_CLAIM", claim["cap_binding"]

    def test_worksheet_reports_the_governing_flag_and_the_mirrored_pair(self):
        """Otherwise it is `PER_CLAIM` when the fully uncapped figure — `covered_layer_cents` less
        the other-insurance recovery less the statutory deductible, floored at 0 — is strictly
        greater than `per_claim_cap_cents`.

        Design: Difficulty/combinatorial_formula/cap_then_offset_profile_flips_which_payable_is_statutory
        """
        env = setup_claim_with_resolved_other_insurance(
            recovered_cents=1_200_000,
            claim_overrides={"claim_number": "C-9", "claimant_name": "Cora Diaz", "gross_loss_cents": 4_500_000},
            layer_overrides={**PRIMARY_LAYER, "policy_number": "NL-88"},
            profile_overrides=dict(CAP_THEN_OFFSET_PROFILE),
            policy_overrides=dict(CGL_POLICY),
        )

        worksheet = read_settlement_worksheet(env["claim"]["id"])
        assert_settlement_worksheet(worksheet)
        assert worksheet["cap_order_mode"] == "CAP_THEN_OFFSET", worksheet["cap_order_mode"]
        assert worksheet["net_payable_cents"] == 1_790_000
        assert worksheet["alt_net_payable_cents"] == 3_000_000
        assert worksheet["cap_binding"] == "PER_CLAIM", (
            "the uncapped figure of 3290000 exceeds the 3000000 per-claim cap, so the per-claim "
            f"ceiling is the one that bit, got {worksheet['cap_binding']}"
        )
        assert abs(worksheet["variant_delta_cents"]) == 1_210_000
