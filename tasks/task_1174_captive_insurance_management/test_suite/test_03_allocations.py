"""Premium allocation computation, dispute/resolve governance invariant, and
fronting fee recomputation."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_allocation,
    create_allocation,
    create_operating_unit,
    get_captive,
    setup_active_captive_with_program,
    setup_in_force_program,
    setup_capitalized_captive,
    setup_provisional_allocation,
    validate_success,
    GOVERNANCE_SCORE_INITIAL,
)


class TestProvisionalAllocationRounding:

    def test_provisional_allocation_exact_multiple_of_100(self, api, underwriter_headers):
        """PRD §3.5: "Under `EXPOSURE_PRO_RATA`, the unit's share is the unit's
        `exposure_amount` divided by the sum of `exposure_amount` across every
        `ACTIVE` operating unit under the captive; the allocated amount is the
        program's `premium_budget_cents` multiplied by that share."
        PRD §3.5: "Provisional allocations use estimated exposure figures and
        round up to the nearest 100 cents for conservatism" — 200000 * 1000/4000
        = 50000 is already a multiple of 100, so the provisional amount is 50000.
        PRD §3.5: "The new allocation lands in `PROVISIONAL` status".

        Design: Difficulty/dual_variant_calc/premium_allocation_provisional_vs_final_rounding
        """
        captive, program, _fronting = setup_active_captive_with_program(
            program_name="WC Program", line_of_business="WORKERS_COMP",
        )
        unit_a = create_operating_unit(captive["id"], unit_name="Unit Alpha", unit_code="UA",
                                       exposure_basis="REVENUE", exposure_amount=1000)
        create_operating_unit(captive["id"], unit_name="Unit Beta", unit_code="UB",
                              exposure_basis="REVENUE", exposure_amount=3000)
        allocation = create_allocation(captive["id"], program["id"], unit_a["id"],
                                       allocation_method="EXPOSURE_PRO_RATA")
        assert_allocation(allocation)
        assert allocation["status"] == "PROVISIONAL"
        assert allocation["provisional_amount_cents"] == 50000, (
            f"200000 * 1000/4000 = 50000 (already a multiple of 100), "
            f"got {allocation['provisional_amount_cents']}"
        )

    def test_provisional_allocation_rounds_up_to_nearest_100(self, api, underwriter_headers):
        """PRD §3.5: "Provisional allocations use estimated exposure figures and
        round up to the nearest 100 cents for conservatism; final allocations use
        audited actual exposure and exact cent rounding."
        With a 200003-cent budget and a 1000/4000 share, the raw allocation is
        50000.75, which rounds up to the nearest 100 cents: 50100.

        Design: Difficulty/dual_variant_calc/premium_allocation_provisional_vs_final_rounding
        """
        captive, program, _fronting = setup_active_captive_with_program(
            program_name="WC Program Rounded", line_of_business="WORKERS_COMP",
            premium_budget_cents=200003,
        )
        unit_a = create_operating_unit(captive["id"], unit_name="Unit Alpha", unit_code="UA",
                                       exposure_basis="REVENUE", exposure_amount=1000)
        create_operating_unit(captive["id"], unit_name="Unit Beta", unit_code="UB",
                              exposure_basis="REVENUE", exposure_amount=3000)
        allocation = create_allocation(captive["id"], program["id"], unit_a["id"],
                                       allocation_method="EXPOSURE_PRO_RATA")
        assert allocation["status"] == "PROVISIONAL"
        assert allocation["provisional_amount_cents"] == 50100, (
            f"200003 * 0.25 = 50000.75 rounds up to nearest 100 -> 50100, "
            f"got {allocation['provisional_amount_cents']}"
        )


class TestDisputeResolveGovernanceInvariant:

    def test_dispute_then_resolve_restores_governance_score(self, api, captive_manager_headers):
        """PRD §2.9: "disputing a premium allocation decrements it by `3`;
        resolving a dispute restores `3`"
        PRD §3.5: "Resolving the dispute returns the allocation
        `DISPUTED → PROVISIONAL` and adds `3` back to the governance score (capped
        at `100`)."

        Design: Difficulty/compensating_invariant/allocation_dispute_resolve_restores_governance_score
        """
        ctx = setup_provisional_allocation()
        captive_id = ctx["captive"]["id"]
        alloc_id = ctx["allocation"]["id"]
        program_id = ctx["program"]["id"]
        assert get_captive(captive_id)["governance_score"] == GOVERNANCE_SCORE_INITIAL

        disputed = validate_success(
            api.dispute_allocation(captive_id, program_id, alloc_id, captive_manager_headers)
        )
        assert disputed["status"] == "DISPUTED"
        assert get_captive(captive_id)["governance_score"] == GOVERNANCE_SCORE_INITIAL - 3

        resolved = validate_success(
            api.resolve_dispute_allocation(captive_id, program_id, alloc_id, captive_manager_headers)
        )
        assert resolved["status"] == "PROVISIONAL"
        captive_after = get_captive(captive_id)
        assert captive_after["governance_score"] == GOVERNANCE_SCORE_INITIAL, (
            f"Dispute (-3) then resolve (+3) must restore governance_score to "
            f"{GOVERNANCE_SCORE_INITIAL}, got {captive_after['governance_score']}"
        )

    def test_dispute_alone_decrements_governance_score(self, api, captive_manager_headers):
        """PRD §3.5: "A `CaptiveManager` may dispute a `PROVISIONAL` allocation,
        moving it `PROVISIONAL → DISPUTED` and decrementing the captive's
        `governance_score` by `3`."

        Design: Difficulty/compensating_invariant/allocation_dispute_resolve_restores_governance_score
        """
        ctx = setup_provisional_allocation()
        captive_id = ctx["captive"]["id"]
        score_before = get_captive(captive_id)["governance_score"]
        disputed = validate_success(
            api.dispute_allocation(captive_id, ctx["program"]["id"],
                                   ctx["allocation"]["id"], captive_manager_headers)
        )
        assert disputed["status"] == "DISPUTED"
        score_after = get_captive(captive_id)["governance_score"]
        assert score_after == score_before - 3, (
            f"Dispute must decrement governance_score by 3: {score_before} -> {score_after}"
        )

    def test_premium_allocation_dispute_resolve_cycle(self, api, captive_manager_headers):
        """PRD §3.5: "A `CaptiveManager` may dispute a `PROVISIONAL` allocation,
        moving it `PROVISIONAL → DISPUTED` and decrementing the captive's
        `governance_score` by `3`. Resolving the dispute returns the allocation
        `DISPUTED → PROVISIONAL` and adds `3` back to the governance score
        (capped at `100`)."

        Design: Corner/state_machines/premium_allocation_dispute_resolve_cycle
        """
        ctx = setup_provisional_allocation()
        captive_id = ctx["captive"]["id"]
        program_id = ctx["program"]["id"]
        alloc_id = ctx["allocation"]["id"]
        validate_success(api.dispute_allocation(captive_id, program_id, alloc_id,
                                                captive_manager_headers))
        resolved = validate_success(
            api.resolve_dispute_allocation(captive_id, program_id, alloc_id,
                                           captive_manager_headers)
        )
        assert resolved["status"] == "PROVISIONAL", (
            f"Allocation must complete the PROVISIONAL -> DISPUTED -> PROVISIONAL "
            f"cycle, got {resolved['status']}"
        )


class TestFrontingFee:

    def test_fronting_fee_calculation_correctness(self, api, underwriter_headers):
        """PRD §3.4: "Activation triggers the fronting-fee calculation:
        `fronting_fee_amount_cents` equals the parent program's
        `premium_allocated_cents` multiplied by the arrangement's
        `fronting_fee_pct`, rounded to integer cents half-up; the fee is
        recomputed whenever the premium allocation total changes."
        With two equal-exposure units and one EQUAL_SHARE allocation of 100000
        cents against an 0.08 fee, the recomputed fee is exactly 8000 cents.

        Design: Corner/calculations/fronting_fee_calculation_correctness
        """
        captive, program, fronting = setup_active_captive_with_program(
            fronting_required=True,
            program_name="GL Prog FF",
            fronting_carrier_name="FrontCo FF",
            fronting_fee_pct=0.08,
        )
        assert fronting["status"] == "ACTIVE"
        unit_a = create_operating_unit(captive["id"], unit_name="Unit FFA", unit_code="UFA",
                                       exposure_basis="REVENUE", exposure_amount=1000)
        create_operating_unit(captive["id"], unit_name="Unit FFB", unit_code="UFB",
                              exposure_basis="REVENUE", exposure_amount=1000)
        create_allocation(captive["id"], program["id"], unit_a["id"],
                          allocation_method="EQUAL_SHARE")
        refreshed = validate_success(
            api.get_fronting(captive["id"], program["id"], fronting["id"], underwriter_headers)
        )
        # EQUAL_SHARE over 2 units: 200000 / 2 = 100000 allocated; 100000 * 0.08.
        assert refreshed["fronting_fee_amount_cents"] == 8000, (
            f"fronting_fee = 100000 * 0.08 = 8000, "
            f"got {refreshed['fronting_fee_amount_cents']}"
        )
