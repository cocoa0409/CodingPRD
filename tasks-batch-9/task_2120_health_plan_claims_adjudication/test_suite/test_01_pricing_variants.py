"""How a service line is priced: contracts, fee schedules, case rates and rounding order."""
import pytest

from test_helpers import (
    claim_line_payload,
    create_active_contract,
    get_claim,
    lines_by_number,
    setup_contract_then_fee_schedule_pricing,
    setup_open_plan_environment,
    setup_three_line_rounding_claim,
    submit_and_adjudicate,
)


class TestContractVersusFeeSchedulePricing:
    def test_active_percent_of_fee_schedule_contract_prices_the_line_at_the_multiplier(self, api):
        """PRD §3.5: "The allowed amount is the base amount multiplied by the contract's
        `contract_pct`, rounded half up to whole cents."
        PRD §3.5: "From there, the line's **base amount** is the selected rate's
        `allowed_amount_cents` multiplied by the line's `units`, and one of three pricing
        variants applies. The variant chosen is recorded on the claim in `pricing_variant`."

        Design: Difficulty/dual_variant_calc/contract_pricing_vs_fee_schedule_pricing_diverge_on_identical_line
        """
        env = setup_contract_then_fee_schedule_pricing()
        contracted = env["contracted_claim"]
        assert contracted["pricing_variant"] == "CONTRACT_PRICED", (
            "A live PCT_OF_FEE_SCHEDULE contract must record CONTRACT_PRICED on the claim"
        )
        assert contracted["total_allowed_cents"] == 30200, (
            "40000 base at contract_pct 0.755 rounds half up to 30200"
        )
        assert lines_by_number(contracted["id"])[1]["allowed_amount_cents"] == 30200

    def test_terminated_contract_falls_back_to_fee_schedule_pricing_on_an_identical_line(
        self, api
    ):
        """PRD §3.1: "Termination moves a contract `ACTIVE → TERMINATED`, overwrites
        `term_date` with the supplied date, and is refused with `ERR_CONTRACT_NOT_ACTIVE`
        from any other status; claims adjudicated afterwards fall back to the
        `FEE_SCHEDULE_PRICED` variant, which reintroduces the out-of-network penalty for
        out-of-network providers."
        PRD §3.5: "For an `IN_NETWORK` provider the allowed amount is simply the base amount."

        Design: Difficulty/dual_variant_calc/contract_pricing_vs_fee_schedule_pricing_diverge_on_identical_line
        """
        env = setup_contract_then_fee_schedule_pricing()
        uncontracted = env["uncontracted_claim"]
        assert uncontracted["pricing_variant"] == "FEE_SCHEDULE_PRICED"
        assert uncontracted["total_allowed_cents"] == 40000, (
            "With no ACTIVE contract the IN_NETWORK allowed amount is the bare base amount"
        )
        assert uncontracted["duplicate_of_claim_id"] is None, (
            "Billed charges 1000 cents apart are outside the 500-cent duplicate tolerance"
        )
        assert env["contracted_claim"]["total_allowed_cents"] != uncontracted[
            "total_allowed_cents"
        ], "The two variants must diverge on the identical line"


class TestPerLineRoundingOrder:
    def test_three_identical_lines_round_per_line_before_summation(self, api):
        """PRD §2.5: "When a claim's allowed amount is assembled from several service
        lines, each line is rounded to whole cents *first* and the rounded per-line values
        are then summed."
        PRD §2.5: "Consider three lines, each billed at one unit against a fee schedule
        rate of 3333 cents, priced under a contract multiplier of 0.755: each line computes
        2516.415 cents and rounds to 2516, so the claim total is 7548."

        Design: Difficulty/combinatorial_formula/per_line_rounding_before_summation_pinned_on_contract_pricing
        """
        env = setup_three_line_rounding_claim()
        claim = env["claim"]
        assert claim["total_allowed_cents"] == 7548, (
            "Round-per-line-then-sum gives 3 x 2516 = 7548"
        )
        assert claim["total_allowed_cents"] != 7549, (
            "Summing the un-rounded products and rounding once would wrongly give 7549"
        )

    def test_each_rounded_line_carries_the_same_whole_cent_allowed_amount(self, api):
        """PRD §2.5: "Wherever a money value is produced by multiplying by a percentage or
        a contract multiplier, the result is rounded to a whole number of cents using
        **round half up** — a value whose fractional part is exactly one half rounds away
        from zero, so 2516.5 becomes 2517."
        PRD §2.5: "The opposite order — summing un-rounded products and rounding the total
        once — is forbidden, and the two orders genuinely diverge."

        Design: Difficulty/combinatorial_formula/per_line_rounding_before_summation_pinned_on_contract_pricing
        """
        env = setup_three_line_rounding_claim()
        claim = env["claim"]
        assert claim["pricing_variant"] == "CONTRACT_PRICED"
        lines = lines_by_number(claim["id"])
        assert len(lines) == 3, "The claim carries three service lines"
        for number in (1, 2, 3):
            assert lines[number]["allowed_amount_cents"] == 2516, (
                f"line {number} computes 2516.415 cents and rounds to 2516"
            )


class TestPricingVariantSelection:
    def test_out_of_network_penalty_bites_only_when_no_contract_prices_the_line(self, api):
        """PRD §3.5: "For an `OUT_OF_NETWORK` provider the allowed amount is the base
        amount multiplied by one minus the plan's `out_of_network_penalty_pct`, rounded
        half up to whole cents — on a plan left at its default, that is 70 percent of the
        base amount."
        PRD §3.5: "The out-of-network penalty is **never** applied under this variant, even
        when the provider's `network_status` is `OUT_OF_NETWORK`, because a negotiated
        contract supersedes network status."

        Design: Corner/calculations/out_of_network_penalty_applies_only_when_no_active_contract_prices_the_line
        """
        env = setup_open_plan_environment(
            plan_overrides={"plan_code": "OON-1", "name": "Out Of Network Plan"},
            provider_overrides={
                "npi": "2000000015",
                "name": "Sigma Imaging",
                "network_status": "OUT_OF_NETWORK",
            },
            member_overrides={"member_number": "M-OON-1"},
            rates=[("73721", 40000, "2026-01-01")],
        )
        penalised = submit_and_adjudicate(
            env, [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")], "CLM-OON-1"
        )
        assert penalised["total_allowed_cents"] == 28000, "40000 x 0.70 = 28000"
        assert penalised["pricing_variant"] == "FEE_SCHEDULE_PRICED"

        create_active_contract(
            env["provider"]["id"],
            env["plan"]["id"],
            effective_date="2026-01-01",
            term_date="2026-12-31",
            pricing_method="PCT_OF_FEE_SCHEDULE",
            contract_pct=0.755,
        )
        contracted = submit_and_adjudicate(
            env, [claim_line_payload(1, "73721", 1, 61000, "2026-02-10")], "CLM-OON-2"
        )
        assert contracted["total_allowed_cents"] == 30200, (
            "Under a contract the penalty is skipped entirely: 40000 x 0.755 = 30200"
        )
        assert contracted["pricing_variant"] == "CONTRACT_PRICED"

    def test_case_rate_pool_is_split_by_largest_remainder_with_line_number_tie_break(self, api):
        """PRD §3.5: "Worked through: a `case_rate_cents` of 50000 against three lines
        billed 30000, 20000 and 10000 gives exact shares of 25000, 16666.666… and
        8333.333…; the integer parts are 25000, 16666 and 8333, summing to 49999; the single
        leftover cent goes to the second line, which has the largest fractional part,
        producing final line amounts of 25000, 16667 and 8333."
        PRD §3.5: "Here the claim, not the line, is priced: the claim's `total_allowed_cents`
        becomes the smaller of the contract's `case_rate_cents` and the claim's
        `total_billed_cents`, and the per-line amounts come from the pro-rata allocation
        described below."

        Design: Corner/calculations/case_rate_prorata_uses_largest_remainder_with_line_number_tie_break
        """
        env = setup_open_plan_environment(
            plan_overrides={"plan_code": "CASE-1", "name": "Case Rate Plan"},
            provider_overrides={"npi": "2000000016", "name": "Tau Surgical"},
            member_overrides={"member_number": "M-CASE-1"},
            rates=[
                ("73721", 40000, "2026-01-01"),
                ("82947", 3333, "2026-01-01"),
                ("80053", 6000, "2026-01-01"),
            ],
        )
        create_active_contract(
            env["provider"]["id"],
            env["plan"]["id"],
            effective_date="2026-01-01",
            term_date="2026-12-31",
            pricing_method="CASE_RATE",
            case_rate_cents=50000,
        )
        claim = submit_and_adjudicate(
            env,
            [
                claim_line_payload(1, "73721", 1, 30000, "2026-02-10"),
                claim_line_payload(2, "82947", 1, 20000, "2026-02-10"),
                claim_line_payload(3, "80053", 1, 10000, "2026-02-10"),
            ],
            "CLM-CASE-1",
        )
        assert claim["pricing_variant"] == "CASE_RATE_PRICED"
        assert claim["total_allowed_cents"] == 50000
        lines = lines_by_number(claim["id"])
        assert lines[1]["allowed_amount_cents"] == 25000
        assert lines[2]["allowed_amount_cents"] == 16667, (
            "the single leftover cent goes to the line with the largest fractional part"
        )
        assert lines[3]["allowed_amount_cents"] == 8333
        assert sum(lines[n]["allowed_amount_cents"] for n in (1, 2, 3)) == 50000

    def test_fee_schedule_selector_takes_the_latest_rate_on_or_before_the_service_date(
        self, api
    ):
        """PRD §3.5: "The engine gathers the rates published under the plan of the claim's
        member whose `procedure_code` equals the line's and whose `effective_date` falls on
        or before the line's `service_date`, ranks them by `effective_date` descending with
        `created_at` ascending as the tie-break, and takes the first."

        Design: Corner/calculations/fee_schedule_selector_picks_latest_effective_date_on_or_before_service_date
        """
        env = setup_open_plan_environment(
            plan_overrides={"plan_code": "RATE-1", "name": "Rate Selector Plan"},
            provider_overrides={"npi": "2000000018", "name": "Phi Imaging"},
            member_overrides={"member_number": "M-RATE-1"},
            rates=[("73721", 40000, "2026-01-01"), ("73721", 55000, "2026-02-01")],
        )
        later = submit_and_adjudicate(
            env, [claim_line_payload(1, "73721", 1, 90000, "2026-02-10")], "CLM-RATE-A"
        )
        earlier = submit_and_adjudicate(
            env, [claim_line_payload(1, "73721", 1, 90000, "2026-01-20")], "CLM-RATE-B"
        )
        assert later["total_allowed_cents"] == 55000, (
            "A 2026-02-10 service date reaches the 2026-02-01 revision"
        )
        assert earlier["total_allowed_cents"] == 40000, (
            "A 2026-01-20 service date cannot reach a rate effective 2026-02-01"
        )
        assert get_claim(later["id"])["total_allowed_cents"] == 55000
