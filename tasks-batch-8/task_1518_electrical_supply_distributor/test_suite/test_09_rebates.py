"""Manufacturer rebates: provisional vs final rounding variants, tier
thresholds, closed-interval program overlap, and claim lifecycle guards."""
from test_helpers import (
    BRANCH_MGR,
    REBATE_CLERK,
    ApiErrorId,
    api_client,
    assert_rebate_claim,
    create_rebate_program_payload,
    get_rebate_claim,
    setup_rebate_claim_world,
    validate_error,
    validate_success,
)


class TestProvisionalVsFinalRounding:

    def test_provisional_rounds_the_sum_once(self):
        """PRD section 3.9: "The provisional amount applies the achieved
        percentage to that base with exactly one rounding, half-up to a whole
        cent, taken on the sum as a whole."
        PRD section 3.9: "At this stage `qualifying_base_cents`,
        `tier_pct_applied`, and `final_amount_cents` remain null."

        Design: Difficulty/dual_variant_calc/rebate_provisional_vs_final_rounding
        """
        world = setup_rebate_claim_world(unit_price=1010, num_releases=2,
                                         tiers=((0, 0.05),))
        claim = world["claim"]
        assert_rebate_claim(claim)
        # Two invoiced 1010-cent lines: base 2020; round_half_up(2020 x 0.05)
        # = 101 with the single rounding taken on the sum.
        assert claim["provisional_amount_cents"] == 101, (
            f"provisional must round the 2020-cent sum once: expected 101, "
            f"got {claim['provisional_amount_cents']}")
        assert claim["qualifying_base_cents"] is None
        assert claim["tier_pct_applied"] is None
        assert claim["final_amount_cents"] is None

    def test_final_rounds_per_line_then_sums(self):
        """PRD section 3.9: "Submission recomputes everything against the data
        as it then stands: `qualifying_base_cents` is recalculated,
        `tier_pct_applied` records the achieved percentage, and
        `final_amount_cents` is computed by the final variant — each
        qualifying line's `billed_amount_cents` is multiplied by the achieved
        percentage and rounded half-up to a whole cent, and those per-line
        results are then summed."

        Design: Difficulty/dual_variant_calc/rebate_provisional_vs_final_rounding
        """
        world = setup_rebate_claim_world(unit_price=1010, num_releases=2,
                                         tiers=((0, 0.05),))
        resp = api_client.submit_rebate_claim(world["claim"]["id"],
                                              REBATE_CLERK)
        data = validate_success(resp, expected_status=200)
        assert_rebate_claim(data)
        assert data["status"] == "SUBMITTED"
        assert data["qualifying_base_cents"] == 2020
        assert data["tier_pct_applied"] == 0.05
        # Per line: round_half_up(1010 x 0.05) = round_half_up(50.5) = 51;
        # the final claim sums the per-line results: 2 x 51 = 102.
        assert data["final_amount_cents"] == 102, (
            f"final must round per line then sum: expected 102, got "
            f"{data['final_amount_cents']}")


class TestRoundingOrderPinned:

    def test_provisional_sum_rounding_on_odd_halves(self):
        """PRD section 3.9: "The provisional amount applies the achieved
        percentage to that base with exactly one rounding, half-up to a whole
        cent, taken on the sum as a whole."

        Design: Difficulty/combinatorial_formula/rebate_round_per_line_then_sum_pinned
        """
        world = setup_rebate_claim_world(sku="SWD-RELAY", unit_price=1015,
                                         num_releases=2, tiers=((0, 0.10),))
        claim = world["claim"]
        # Base 2030; round_half_up(2030 x 0.10) = 203.
        assert claim["provisional_amount_cents"] == 203, (
            f"sum-then-round provisional must be 203, got "
            f"{claim['provisional_amount_cents']}")

    def test_final_per_line_rounding_differs_from_provisional(self):
        """PRD section 2.7: "All line-level amounts and stored totals are
        integer cents, produced with round-half-up rounding; where an amount
        is built from several lines, each line is rounded first and the
        rounded per-line results are then summed. This per-line-then-sum order
        is pinned for release billing (§3.8) and for final rebate computation
        (§3.9). The single exception is the provisional rebate estimate, which
        applies exactly one rounding to the total rather than per line
        (§3.9)."

        Design: Difficulty/combinatorial_formula/rebate_round_per_line_then_sum_pinned
        """
        world = setup_rebate_claim_world(sku="SWD-RELAY", unit_price=1015,
                                         num_releases=2, tiers=((0, 0.10),))
        resp = api_client.submit_rebate_claim(world["claim"]["id"],
                                              REBATE_CLERK)
        data = validate_success(resp, expected_status=200)
        # Per line: round_half_up(1015 x 0.10) = round_half_up(101.5) = 102;
        # final = 2 x 102 = 204, legitimately different from the 203
        # provisional on the same data.
        assert data["final_amount_cents"] == 204, (
            f"per-line-then-sum final must be 204, got "
            f"{data['final_amount_cents']}")
        assert data["final_amount_cents"] != data["provisional_amount_cents"]


class TestProgramPeriodOverlap:

    def _create_program(self, period_start, period_end):
        return api_client.create_rebate_program(
            create_rebate_program_payload(
                manufacturer_name="Southwire", period_start=period_start,
                period_end=period_end,
                tiers=[{"threshold_cents": 0, "rebate_pct": 0.05}]),
            REBATE_CLERK)

    def test_shared_boundary_date_conflicts(self):
        """PRD section 3.9: "Two programs for the same manufacturer may not
        have overlapping closed intervals — shared boundary dates count as a
        conflict — and such a creation is rejected with
        `ERR_REBATE_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rebate_period_closed_interval_overlap
        """
        first = self._create_program("2026-01-01", "2026-03-31")
        validate_success(first, expected_status=201)

        resp = self._create_program("2026-03-31", "2026-06-30")
        validate_error(resp, ApiErrorId.ERR_REBATE_PERIOD_OVERLAP)

    def test_next_day_start_accepted(self):
        """PRD section 3.9: "Two programs for the same manufacturer may not
        have overlapping closed intervals — shared boundary dates count as a
        conflict — and such a creation is rejected with
        `ERR_REBATE_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rebate_period_closed_interval_overlap
        """
        first = self._create_program("2026-01-01", "2026-03-31")
        validate_success(first, expected_status=201)

        resp = self._create_program("2026-04-01", "2026-06-30")
        data = validate_success(resp, expected_status=201)
        assert data["period_start"] == "2026-04-01", (
            "a period starting the day after the existing closed interval "
            "ends does not overlap")


class TestClaimLifecycleGuards:

    def test_rebate_submit_before_period_end_rejected(self):
        """PRD section 3.9: "Submitting the claim is allowed only once the
        logical clock's date has passed the program's `period_end` — earlier
        attempts fail with `ERR_REBATE_PERIOD_NOT_ENDED` — and only from
        `DRAFT`, else `ERR_REBATE_CLAIM_NOT_DRAFT`."

        Design: Corner/state_machines/rebate_submit_before_period_end_rejected
        """
        world = setup_rebate_claim_world(move_clock_past_end=False)
        resp = api_client.submit_rebate_claim(world["claim"]["id"],
                                              REBATE_CLERK)
        validate_error(resp, ApiErrorId.ERR_REBATE_PERIOD_NOT_ENDED)
        assert get_rebate_claim(world["claim"]["id"])["status"] == "DRAFT"

    def test_rebate_decide_before_submit_rejected(self):
        """PRD section 3.9: "A `BranchManager` then decides the claim by
        supplying a `decision` of `APPROVE` or `REJECT`, moving it to
        `APPROVED` or `REJECTED`; deciding a claim that is not `SUBMITTED`
        fails with `ERR_REBATE_CLAIM_NOT_SUBMITTED`."

        Design: Corner/validations/rebate_decide_before_submit_rejected
        """
        world = setup_rebate_claim_world(move_clock_past_end=False)
        resp = api_client.decide_rebate_claim(world["claim"]["id"],
                                              {"decision": "APPROVE"},
                                              BRANCH_MGR)
        validate_error(resp, ApiErrorId.ERR_REBATE_CLAIM_NOT_SUBMITTED)
        assert get_rebate_claim(world["claim"]["id"])["status"] == "DRAFT"

    def test_rebate_claim_submit_then_approve_happy_path(self):
        """PRD section 3.9: "A `BranchManager` then decides the claim by
        supplying a `decision` of `APPROVE` or `REJECT`, moving it to
        `APPROVED` or `REJECTED`; deciding a claim that is not `SUBMITTED`
        fails with `ERR_REBATE_CLAIM_NOT_SUBMITTED`. Both outcomes are
        terminal."

        Design: Corner/state_machines/rebate_claim_submit_then_approve_happy_path
        """
        world = setup_rebate_claim_world()  # no invoiced releases
        submitted = validate_success(
            api_client.submit_rebate_claim(world["claim"]["id"], REBATE_CLERK),
            expected_status=200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["qualifying_base_cents"] == 0
        assert submitted["final_amount_cents"] == 0

        decided = validate_success(
            api_client.decide_rebate_claim(world["claim"]["id"],
                                           {"decision": "APPROVE"},
                                           BRANCH_MGR),
            expected_status=200)
        assert decided["status"] == "APPROVED"


class TestTierThreshold:

    def test_rebate_tier_at_exact_threshold(self):
        """PRD section 3.9: "Each tier pairs a `threshold_cents` with a
        `rebate_pct`, and tiers are kept in ascending threshold order; the
        achieved tier for a given qualifying base is the last tier whose
        `threshold_cents` does not exceed that base, and if no threshold is
        reached the applied percentage is zero."

        Design: Corner/calculations/rebate_tier_at_exact_threshold
        """
        world = setup_rebate_claim_world(
            manufacturer="SquareD", sku="SQD-PANEL", unit_price=20_000,
            num_releases=1, tiers=((10_000, 0.05), (20_000, 0.07)))
        resp = api_client.submit_rebate_claim(world["claim"]["id"],
                                              REBATE_CLERK)
        data = validate_success(resp, expected_status=200)
        assert data["qualifying_base_cents"] == 20_000
        assert data["tier_pct_applied"] == 0.07, (
            f"a base exactly equal to the 20000 threshold achieves the 0.07 "
            f"tier, got {data['tier_pct_applied']}")
        assert data["final_amount_cents"] == 1_400
