"""Endpoints that exist only to undo another endpoint, exactly.

Releasing the sole allocation has to hand the lot, the campaign, the nomination
and the hydrogen contract back their pre-booking figures; reversing a retirement
has to hand the pathway back the exact balance it carried before, and restore the
block to whatever its recorded verification outcome was.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_NOTHING_TO_REVERSE
from test_helpers.assertions import assert_fields_null, assert_mass, assert_one_decimal
from test_helpers.test_users import OFFICER_A_HEADERS, OPERATOR_HEADERS, TRADER_HEADERS
from test_helpers.types import (
    ALLOC_RELEASED,
    BLOCK_RETIRED,
    BLOCK_VERIFIED,
    LOT_ACCEPTED,
    NOMINATION_CANCELLED,
    OUTCOME_VERIFIED,
    RELEASE_MANUAL,
    RUN_PLANNED,
)

REVERSAL_REASON = "Registry rejected the retirement filing; credits returned to the account."


def test_releasing_the_only_allocation_returns_the_lot_and_campaign_to_zero(api):
    """PRD §3.5: "Release sets `release_reason` to `MANUAL`, restores the mass to the lot
    (lowering `allocated_mass_mt`, raising `remaining_mass_mt`), lowers the campaign's
    `reserved_mass_mt`, recomputes the campaign's `blend_ci_gco2e_per_mj` and
    `required_h2_kg_per_day` over the allocations that still count — both returning to null
    when none remain — and bumps the allocation's, the lot's and the campaign's `version`."
    PRD §2.10: "Releasing an allocation restores mass to the lot exactly; it is the
    compensating inverse of reserving it."

    Design: Difficulty/compensating_invariant/allocation_release_restores_lot_mass_and_unwinds_hydrogen_securement
    """
    ctx = fx.baseline_campaign(api)

    released = validate_success(
        api.release_allocation(ctx["allocation"]["id"], TRADER_HEADERS)
    )
    assert released["status"] == ALLOC_RELEASED, f"got {released['status']}"
    assert released["release_reason"] == RELEASE_MANUAL
    assert_fields_null(released, "line_cost_usd")

    lot = validate_success(api.get_feedstock_lot(ctx["lot"]["id"], TRADER_HEADERS))
    assert_mass(lot["allocated_mass_mt"], 0.000, "allocated_mass_mt")
    assert_mass(lot["remaining_mass_mt"], 500.000, "remaining_mass_mt")
    assert lot["status"] == LOT_ACCEPTED, f"got {lot['status']}"

    run = validate_success(api.get_processing_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert run["status"] == RUN_PLANNED, f"got {run['status']}"
    assert_mass(run["reserved_mass_mt"], 0.000, "reserved_mass_mt")
    assert_fields_null(run, "blend_ci_gco2e_per_mj", "required_h2_kg_per_day")


def test_releasing_the_only_allocation_gives_back_the_booked_hydrogen_capacity(api):
    """PRD §3.5: "if the campaign was `HYDROGEN_SECURED` and its recomputed
    `reserved_mass_mt` has fallen below the 100.0 metric tonne minimum charge, it is
    downgraded `HYDROGEN_SECURED → PLANNED`, its `provisional_yield_pct`,
    `planned_total_product_mt`, `planned_rd_mt` and `planned_saf_mt` are reset to 0.000, and
    every `CONFIRMED` hydrogen nomination on that campaign transitions to `CANCELLED` with
    each affected contract's `peak_committed_kg_per_day` recomputed."
    PRD §2.10: "That is what makes cancelling a nomination restore booked capacity exactly,
    whether the cancellation was requested directly or produced by a cascade."

    Design: Difficulty/compensating_invariant/allocation_release_restores_lot_mass_and_unwinds_hydrogen_securement
    """
    ctx = fx.baseline_campaign(api)

    validate_success(api.release_allocation(ctx["allocation"]["id"], TRADER_HEADERS))

    run = validate_success(api.get_processing_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert_mass(run["provisional_yield_pct"], 0.000, "provisional_yield_pct")
    assert_mass(run["planned_total_product_mt"], 0.000, "planned_total_product_mt")
    assert_mass(run["planned_rd_mt"], 0.000, "planned_rd_mt")
    assert_mass(run["planned_saf_mt"], 0.000, "planned_saf_mt")

    nominations = get_success_data(api.list_run_nominations(ctx["run"]["id"], OPERATOR_HEADERS))
    assert len(nominations) == 1, f"expected the single booking, got {len(nominations)}"
    assert nominations[0]["status"] == NOMINATION_CANCELLED

    contract = validate_success(api.get_hydrogen_contract(ctx["contract"]["id"], TRADER_HEADERS))
    assert_one_decimal(contract["peak_committed_kg_per_day"], 0.0, "peak_committed_kg_per_day")


def test_retiring_the_whole_verified_balance_empties_the_pathway_ledger(api):
    """PRD §3.8: "Retirement adds the supplied `credits` to `retired_credits_mtco2e`,
    recomputes the pathway's `credits_outstanding_mtco2e`, and bumps both the block's and the
    pathway's `version`. The block moves to `RETIRED` only when `retired_credits_mtco2e` has
    become equal to `verified_credits_mtco2e`; a partial retirement leaves the block where it
    was so that the remainder can be retired later."
    PRD §2.10: "For any pathway registration, `credits_outstanding_mtco2e` is the sum, over
    the credit blocks citing that pathway whose status is `VERIFIED`, `ADJUSTED` or
    `RETIRED`, of each block's `verified_credits_mtco2e` less its `retired_credits_mtco2e`,
    rounded to 3 decimal places."

    Design: Difficulty/compensating_invariant/retirement_reversal_restores_pathway_credit_balance_exactly
    """
    ctx = fx.credit_ready_campaign(api)
    block = fx.verified_credit_block(api, ctx["batch"]["id"], ctx["pathway"]["id"])

    assert block["status"] == BLOCK_VERIFIED, f"got {block['status']}"
    assert block["verification_outcome"] == OUTCOME_VERIFIED
    assert_mass(block["provisional_credits_mtco2e"], 547.171, "provisional_credits_mtco2e")
    assert_mass(block["verified_credits_mtco2e"], 536.228, "verified_credits_mtco2e")

    retired = validate_success(
        api.retire_credits(block["id"], f.retirement_payload(536.228), OFFICER_A_HEADERS)
    )
    assert retired["status"] == BLOCK_RETIRED, f"got {retired['status']}"
    assert_mass(retired["retired_credits_mtco2e"], 536.228, "retired_credits_mtco2e")

    pathway = validate_success(api.get_pathway(ctx["pathway"]["id"], OFFICER_A_HEADERS))
    assert_mass(pathway["credits_outstanding_mtco2e"], 0.000, "credits_outstanding_mtco2e")


def test_reversing_the_retirement_restores_the_balance_and_cannot_be_repeated(api):
    """PRD §3.8: "The block's `retired_credits_mtco2e` is set to 0.000, the pathway's
    `credits_outstanding_mtco2e` is recomputed — returning to exactly its pre-retirement value
    — and both versions are bumped. The block's status is restored from its own
    `verification_outcome`: a block whose outcome was `VERIFIED` returns `RETIRED →
    VERIFIED`, and one whose outcome was `ADJUSTED` returns `RETIRED → ADJUSTED`."
    PRD §3.8: "A block with no retired balance at all has nothing to reverse and is refused
    with `ERR_NOTHING_TO_REVERSE`."

    Design: Difficulty/compensating_invariant/retirement_reversal_restores_pathway_credit_balance_exactly
    """
    ctx = fx.credit_ready_campaign(api)
    block = fx.verified_credit_block(api, ctx["batch"]["id"], ctx["pathway"]["id"])
    validate_success(
        api.retire_credits(block["id"], f.retirement_payload(536.228), OFFICER_A_HEADERS)
    )

    reversed_block = validate_success(
        api.reverse_retirement(
            block["id"], f.reversal_payload(reason=REVERSAL_REASON), OFFICER_A_HEADERS
        )
    )
    assert reversed_block["status"] == BLOCK_VERIFIED, f"got {reversed_block['status']}"
    assert_mass(reversed_block["retired_credits_mtco2e"], 0.000, "retired_credits_mtco2e")
    assert_mass(reversed_block["verified_credits_mtco2e"], 536.228, "verified_credits_mtco2e")
    assert reversed_block["verification_findings"] == REVERSAL_REASON

    pathway = validate_success(api.get_pathway(ctx["pathway"]["id"], OFFICER_A_HEADERS))
    assert_mass(pathway["credits_outstanding_mtco2e"], 536.228, "credits_outstanding_mtco2e")

    validate_error(
        api.reverse_retirement(
            block["id"], f.reversal_payload(reason="Duplicate reversal attempt."), OFFICER_A_HEADERS
        ),
        ERR_NOTHING_TO_REVERSE,
    )
