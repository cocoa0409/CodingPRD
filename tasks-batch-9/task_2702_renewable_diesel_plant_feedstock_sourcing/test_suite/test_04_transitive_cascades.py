"""Cascades that travel several entities away from the record acted on.

One compliance action against a supplier document ends up releasing booked
hydrogen capacity; one arithmetic verdict on a credit block ends up freezing an
untouched block behind the same pathway.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_fields_null, assert_mass, assert_one_decimal
from test_helpers.test_users import (
    OFFICER_A_HEADERS,
    OPERATOR_HEADERS,
    TRADER_HEADERS,
    VERIFIER_HEADERS,
)
from test_helpers.types import (
    ALLOC_RELEASED,
    BLOCK_ADJUSTED,
    BLOCK_BLOCKED,
    BLOCK_DRAFT,
    DD_SUSPENDED,
    LOT_QUARANTINED,
    NOMINATION_CANCELLED,
    OUTCOME_ADJUSTED,
    PATHWAY_REGISTERED,
    PATHWAY_SUSPENDED,
    RELEASE_SUPPLIER_SUSPENDED,
    RUN_PLANNED,
    VERIFICATION_VERIFY,
)

SUSPENSION_REASON = "Chain-of-custody attestation withdrawn by the certification body."


def test_supplier_suspension_quarantines_the_lot_and_releases_its_allocation(api):
    """PRD §3.1: "Every feedstock lot belonging to that supplier whose status is `RECEIVED`,
    `TESTED`, `PRETREAT_REQUIRED`, `PRETREATED` or `ACCEPTED` transitions to `QUARANTINED`,
    processed in `created_at` ascending order, with each lot's `version` bumped."
    PRD §3.1: "For each lot quarantined at level 2, every feedstock allocation drawn from
    that lot whose status is `RESERVED` transitions to `RELEASED` with `release_reason` set
    to `SUPPLIER_SUSPENDED`, and the lot's `allocated_mass_mt` and `remaining_mass_mt` are
    recomputed."

    Design: Difficulty/transitive_cascade/supplier_suspension_cascades_five_levels_to_hydrogen_capacity
    """
    ctx = fx.baseline_campaign(api)

    supplier = validate_success(
        api.suspend_supplier(
            ctx["supplier"]["id"],
            f.suspension_payload(reason=SUSPENSION_REASON),
            OFFICER_A_HEADERS,
        )
    )
    assert supplier["dd_status"] == DD_SUSPENDED
    assert supplier["suspension_reason"] == SUSPENSION_REASON

    lot = validate_success(api.get_feedstock_lot(ctx["lot"]["id"], TRADER_HEADERS))
    assert lot["status"] == LOT_QUARANTINED, f"expected QUARANTINED, got {lot['status']}"
    assert_mass(lot["allocated_mass_mt"], 0.000, "allocated_mass_mt")
    assert_mass(lot["remaining_mass_mt"], 500.000, "remaining_mass_mt")

    lines = get_success_data(api.list_run_allocations(ctx["run"]["id"], TRADER_HEADERS))
    assert len(lines) == 1, f"expected the single reserved line, got {len(lines)}"
    assert lines[0]["status"] == ALLOC_RELEASED
    assert lines[0]["release_reason"] == RELEASE_SUPPLIER_SUSPENDED


def test_supplier_suspension_unwinds_the_hydrogen_securement_four_hops_away(api):
    """PRD §3.1: "If that campaign was in `HYDROGEN_SECURED` and its recomputed
    `reserved_mass_mt` has fallen below the 100.0 metric tonne minimum charge, the campaign
    is downgraded `HYDROGEN_SECURED → PLANNED` and its `provisional_yield_pct`,
    `planned_total_product_mt`, `planned_rd_mt` and `planned_saf_mt` are all reset to
    0.000."
    PRD §3.1: "For each campaign downgraded at level 4, every hydrogen nomination booked
    against that campaign whose status is `CONFIRMED` transitions to `CANCELLED`, and each
    affected hydrogen supply contract's `peak_committed_kg_per_day` is recomputed over the
    nominations that survive."

    Design: Difficulty/transitive_cascade/supplier_suspension_cascades_five_levels_to_hydrogen_capacity
    """
    ctx = fx.baseline_campaign(api)

    validate_success(
        api.suspend_supplier(
            ctx["supplier"]["id"],
            f.suspension_payload(reason=SUSPENSION_REASON),
            OFFICER_A_HEADERS,
        )
    )

    run = validate_success(api.get_processing_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert run["status"] == RUN_PLANNED, f"expected PLANNED, got {run['status']}"
    assert_mass(run["reserved_mass_mt"], 0.000, "reserved_mass_mt")
    assert_fields_null(run, "blend_ci_gco2e_per_mj", "required_h2_kg_per_day")
    assert_mass(run["provisional_yield_pct"], 0.000, "provisional_yield_pct")
    assert_mass(run["planned_total_product_mt"], 0.000, "planned_total_product_mt")
    assert_mass(run["planned_rd_mt"], 0.000, "planned_rd_mt")
    assert_mass(run["planned_saf_mt"], 0.000, "planned_saf_mt")

    nominations = get_success_data(api.list_run_nominations(ctx["run"]["id"], OPERATOR_HEADERS))
    assert len(nominations) == 1, f"expected one booking, got {len(nominations)}"
    assert nominations[0]["status"] == NOMINATION_CANCELLED

    contract = validate_success(api.get_hydrogen_contract(ctx["contract"]["id"], TRADER_HEADERS))
    assert_one_decimal(contract["peak_committed_kg_per_day"], 0.0, "peak_committed_kg_per_day")


def test_first_adjusted_verdict_records_one_strike_and_spares_the_pathway(api):
    """PRD §3.8: "When it exceeds the tolerance the block lands at `ADJUSTED` with
    `verification_outcome` set to `ADJUSTED`."
    PRD §3.8: "Level 3, caused by level 2, checks the incremented count: when
    `variance_strikes` has reached 2, the pathway transitions `REGISTERED → SUSPENDED` — a
    terminal state — and its `version` is bumped again."

    Design: Difficulty/transitive_cascade/second_adjusted_verification_suspends_pathway_and_blocks_sibling_block
    """
    ctx = fx.two_run_credit_portfolio(api)

    block_a = validate_success(
        api.decide_verification(
            ctx["block_a"]["id"],
            f.verification_decision_payload(VERIFICATION_VERIFY, verified_ci=50.00),
            VERIFIER_HEADERS,
        )
    )
    assert block_a["status"] == BLOCK_ADJUSTED, f"expected ADJUSTED, got {block_a['status']}"
    assert block_a["verification_outcome"] == OUTCOME_ADJUSTED
    assert_mass(block_a["provisional_credits_mtco2e"], 547.171, "provisional_credits_mtco2e")
    assert_mass(block_a["verified_credits_mtco2e"], 436.926, "verified_credits_mtco2e")

    pathway = validate_success(api.get_pathway(ctx["pathway"]["id"], OFFICER_A_HEADERS))
    assert pathway["variance_strikes"] == 1, f"got {pathway['variance_strikes']}"
    assert pathway["status"] == PATHWAY_REGISTERED, "one strike is not two"

    block_c = validate_success(api.get_credit_block(ctx["block_c"]["id"], OFFICER_A_HEADERS))
    assert block_c["status"] == BLOCK_DRAFT, "the untouched block survives the first strike"


def test_second_adjusted_verdict_suspends_the_pathway_and_blocks_the_draft_sibling(api):
    """PRD §3.8: "Level 3, caused by level 2, checks the incremented count: when
    `variance_strikes` has reached 2, the pathway transitions `REGISTERED → SUSPENDED` — a
    terminal state — and its `version` is bumped again."
    PRD §3.8: "Level 4, caused by level 3, transitions **every other** credit block citing
    that pathway whose status is `DRAFT` or `INTERNAL_SIGNED_OFF` to `BLOCKED`, processed in
    `created_at` ascending order, with each blocked block's `version` bumped."

    Design: Difficulty/transitive_cascade/second_adjusted_verification_suspends_pathway_and_blocks_sibling_block
    """
    ctx = fx.two_run_credit_portfolio(api)
    decision = f.verification_decision_payload(VERIFICATION_VERIFY, verified_ci=50.00)

    validate_success(api.decide_verification(ctx["block_a"]["id"], decision, VERIFIER_HEADERS))
    block_b = validate_success(
        api.decide_verification(ctx["block_b"]["id"], decision, VERIFIER_HEADERS)
    )

    assert block_b["status"] == BLOCK_ADJUSTED
    assert block_b["verified_ci_gco2e_per_mj"] == 50.00, f"got {block_b['verified_ci_gco2e_per_mj']}"
    assert_mass(block_b["provisional_credits_mtco2e"], 58.849, "provisional_credits_mtco2e")
    assert_mass(block_b["verified_credits_mtco2e"], 47.185, "verified_credits_mtco2e")

    pathway = validate_success(api.get_pathway(ctx["pathway"]["id"], OFFICER_A_HEADERS))
    assert pathway["variance_strikes"] == 2, f"got {pathway['variance_strikes']}"
    assert pathway["status"] == PATHWAY_SUSPENDED, f"expected SUSPENDED, got {pathway['status']}"
    assert_mass(pathway["credits_outstanding_mtco2e"], 484.111, "credits_outstanding_mtco2e")

    block_c = validate_success(api.get_credit_block(ctx["block_c"]["id"], OFFICER_A_HEADERS))
    assert block_c["status"] == BLOCK_BLOCKED, f"expected BLOCKED, got {block_c['status']}"
    assert_mass(block_c["provisional_credits_mtco2e"], 150.944, "provisional_credits_mtco2e")
