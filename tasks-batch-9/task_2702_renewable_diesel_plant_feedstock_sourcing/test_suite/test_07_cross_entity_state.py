"""Transitions gated by the state of an entity the request never names.

An allocation blocked by a supplier two hops away, a campaign start blocked by a
turnaround window on the unit, and a credit mint blocked by a batch's shipping
state — in each case nothing about the acted-on record has to change for the
identical request to succeed later.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BATCH_NOT_SHIPPED,
    ERR_INVALID_UNIT_STATE,
    ERR_SUPPLIER_DUE_DILIGENCE_INCOMPLETE,
)
from test_helpers.assertions import (
    assert_fields_null,
    assert_mass,
    assert_timestamp_equals,
)
from test_helpers.test_users import (
    OFFICER_A_HEADERS,
    OPERATOR_HEADERS,
    TRADER_HEADERS,
)
from test_helpers.types import (
    BLOCK_DRAFT,
    DD_PENDING,
    DD_VERIFIED,
    DIST_RESERVED,
    DIST_SHIPPED,
    LOT_ACCEPTED,
    PROGRAM_LCFS,
    RUN_HYDROGEN_SECURED,
    RUN_RUNNING,
    UNIT_DOWN_TURNAROUND,
    UNIT_RUNNING,
    WINDOW_COMPLETED,
)


def test_allocation_is_refused_while_the_lots_supplier_is_still_pending(api):
    """PRD §3.5: "The supplier behind the cited lot must have `dd_status` of `VERIFIED`. A
    lot from a `PENDING` or `SUSPENDED` supplier may not feed the reactor:
    `ERR_SUPPLIER_DUE_DILIGENCE_INCOMPLETE`."
    PRD §3.5: "Its `reserved_mass_mt` and `consumed_mass_mt` are 0.000;
    `blend_ci_gco2e_per_mj` and `required_h2_kg_per_day` are null, because a campaign with no
    counted allocation has no blend and is feeding nothing"

    Design: Difficulty/cross_entity_state_dependency/allocation_blocked_by_pending_supplier_due_diligence_state
    """
    ctx = fx.pending_supplier_lot_and_run(api)

    assert ctx["supplier"]["dd_status"] == DD_PENDING
    assert ctx["lot"]["status"] == LOT_ACCEPTED, "the lot itself is faultless"

    validate_error(
        api.create_allocation(
            ctx["run"]["id"],
            f.allocation_payload(ctx["lot"]["id"], 120.000, ctx["run"]["version"]),
            TRADER_HEADERS,
        ),
        ERR_SUPPLIER_DUE_DILIGENCE_INCOMPLETE,
    )

    lot = validate_success(api.get_feedstock_lot(ctx["lot"]["id"], TRADER_HEADERS))
    assert_mass(lot["remaining_mass_mt"], 500.000, "remaining_mass_mt")

    run = validate_success(api.get_processing_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert_mass(run["reserved_mass_mt"], 0.000, "reserved_mass_mt")


def test_verifying_the_supplier_lets_the_identical_allocation_through(api):
    """PRD §3.1: "Verification moves `dd_status` from `PENDING` to `VERIFIED`, sets
    `dd_verified_at` to the current logical clock, sets `dd_expires_at` to the current
    logical clock advanced by `valid_months` multiplied by 30 days (months are treated as
    exactly 30 days each, never as calendar months), clears `suspension_reason`, and bumps
    the supplier's `version`."
    PRD §3.5: "Its effect is immediate and four-sided: the mass is added to the lot's
    `allocated_mass_mt` and subtracted from the lot's `remaining_mass_mt` with the lot's
    `version` bumped; it is added to the campaign's `reserved_mass_mt`; the campaign's
    `blend_ci_gco2e_per_mj` and `required_h2_kg_per_day` are recomputed; and the campaign's
    `version` is bumped."

    Design: Difficulty/cross_entity_state_dependency/allocation_blocked_by_pending_supplier_due_diligence_state
    """
    ctx = fx.pending_supplier_lot_and_run(api)

    supplier = validate_success(
        api.verify_due_diligence(
            ctx["supplier"]["id"], f.due_diligence_payload(valid_months=12), OFFICER_A_HEADERS
        )
    )
    assert supplier["dd_status"] == DD_VERIFIED
    assert_timestamp_equals(supplier["dd_expires_at"], "2027-07-27T00:00:00Z", "dd_expires_at")

    fx.allocate(api, ctx["run"]["id"], ctx["lot"]["id"], 120.000)

    lot = validate_success(api.get_feedstock_lot(ctx["lot"]["id"], TRADER_HEADERS))
    assert_mass(lot["allocated_mass_mt"], 120.000, "allocated_mass_mt")
    assert_mass(lot["remaining_mass_mt"], 380.000, "remaining_mass_mt")

    run = validate_success(api.get_processing_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert_mass(run["reserved_mass_mt"], 120.000, "reserved_mass_mt")
    assert run["blend_ci_gco2e_per_mj"] == 32.50, f"got {run['blend_ci_gco2e_per_mj']}"


def test_secured_campaign_cannot_start_while_its_unit_is_down_for_turnaround(api):
    """PRD §3.6: "A `PlantOperator` may start a campaign only when it is `HYDROGEN_SECURED`,
    the unit is `IDLE`, the cited catalyst charge is still `ACTIVE`, the current logical
    clock is at or after the campaign's `window_start`, and no turnaround window on that
    unit is `IN_PROGRESS`. A unit that is `RUNNING` or `DOWN_TURNAROUND` yields
    `ERR_INVALID_UNIT_STATE`"
    PRD §3.3: "the window moves `APPROVED → IN_PROGRESS` while the unit moves `IDLE →
    DOWN_TURNAROUND`, and both versions are bumped."

    Design: Difficulty/cross_entity_state_dependency/run_start_blocked_by_unit_taken_down_for_turnaround
    """
    ctx = fx.unit_down_for_turnaround(api)

    unit = validate_success(api.get_unit(ctx["unit"]["id"], OPERATOR_HEADERS))
    assert unit["status"] == UNIT_DOWN_TURNAROUND, f"got {unit['status']}"

    validate_error(api.start_run(ctx["run"]["id"], OPERATOR_HEADERS), ERR_INVALID_UNIT_STATE)

    run = validate_success(api.get_processing_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert run["status"] == RUN_HYDROGEN_SECURED, f"got {run['status']}"
    assert_mass(run["consumed_mass_mt"], 0.000, "consumed_mass_mt")

    lot = validate_success(api.get_feedstock_lot(ctx["lot"]["id"], TRADER_HEADERS))
    assert lot["status"] == LOT_ACCEPTED, "no material moved"


def test_closing_the_turnaround_window_releases_the_campaign_start(api):
    """PRD §3.3: "Completing an `IN_PROGRESS` window moves it `IN_PROGRESS → COMPLETED` and
    returns the unit `DOWN_TURNAROUND → IDLE`, bumping both versions"
    PRD §3.6: "The campaign's `reserved_mass_mt` becomes 0.000 and its `consumed_mass_mt` is
    recomputed from the newly consumed lines; note that a lot's `allocated_mass_mt` and
    `remaining_mass_mt` are **unchanged** by this, because both `RESERVED` and `CONSUMED`
    count as allocated."

    Design: Difficulty/cross_entity_state_dependency/run_start_blocked_by_unit_taken_down_for_turnaround
    """
    ctx = fx.unit_down_for_turnaround(api)

    window = validate_success(api.complete_window(ctx["inspection"]["id"], OPERATOR_HEADERS))
    assert window["status"] == WINDOW_COMPLETED, f"got {window['status']}"

    run = validate_success(api.start_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert run["status"] == RUN_RUNNING, f"got {run['status']}"
    assert_mass(run["consumed_mass_mt"], 400.000, "consumed_mass_mt")
    assert_mass(run["provisional_yield_pct"], 82.000, "provisional_yield_pct")

    unit = validate_success(api.get_unit(ctx["unit"]["id"], OPERATOR_HEADERS))
    assert unit["status"] == UNIT_RUNNING, f"got {unit['status']}"

    lot = validate_success(api.get_feedstock_lot(ctx["lot"]["id"], TRADER_HEADERS))
    assert lot["status"] == LOT_ACCEPTED, "100.000 MT is still free, so the lot is not CHARGED"
    assert_mass(lot["remaining_mass_mt"], 100.000, "remaining_mass_mt")


def test_credit_block_is_refused_while_the_batch_is_only_reserved(api):
    """PRD §3.8: "Second, the cited batch's `distribution_status` must be `SHIPPED`; credits
    are minted on transfer, not in tank, so a batch still `IN_TANK` or merely `RESERVED` is
    refused with `ERR_BATCH_NOT_SHIPPED`."

    Design: Difficulty/cross_entity_state_dependency/credit_block_requires_shipped_batch_not_merely_reserved
    """
    ctx = fx.reserved_rd_batch_with_pathway(api, target_saf_share_pct=10.00)
    assert ctx["batch"]["distribution_status"] == DIST_RESERVED

    validate_error(
        api.create_credit_block(
            f.credit_block_payload(ctx["batch"]["id"], ctx["pathway"]["id"]), OFFICER_A_HEADERS
        ),
        ERR_BATCH_NOT_SHIPPED,
    )


def test_shipping_the_batch_unlocks_the_mint_with_the_same_provisional_quantity(api):
    """PRD §3.8: "Second, the cited batch's `distribution_status` must be `SHIPPED`; credits
    are minted on transfer, not in tank, so a batch still `IN_TANK` or merely `RESERVED` is
    refused with `ERR_BATCH_NOT_SHIPPED`."
    PRD §3.8: "A new block starts at `DRAFT` with its `program` copied from the cited
    pathway, `retired_credits_mtco2e` of 0.000, `verification_outcome` of `NONE`, and
    `verified_ci_gco2e_per_mj`, `verification_findings` and `signed_off_by_user_id` all
    null."

    Design: Difficulty/cross_entity_state_dependency/credit_block_requires_shipped_batch_not_merely_reserved
    """
    ctx = fx.reserved_rd_batch_with_pathway(api, target_saf_share_pct=10.00)

    shipped = validate_success(api.ship_batch(ctx["batch"]["id"], OFFICER_A_HEADERS))
    assert shipped["distribution_status"] == DIST_SHIPPED

    block = validate_success(
        api.create_credit_block(
            f.credit_block_payload(ctx["batch"]["id"], ctx["pathway"]["id"]), OFFICER_A_HEADERS
        ),
        201,
    )

    assert block["status"] == BLOCK_DRAFT, f"got {block['status']}"
    assert block["program"] == PROGRAM_LCFS
    assert block["provisional_ci_gco2e_per_mj"] == 41.25, (
        f"got {block['provisional_ci_gco2e_per_mj']}"
    )
    assert_mass(block["provisional_credits_mtco2e"], 547.171, "provisional_credits_mtco2e")
    assert block["provisional_rin_credits"] == 0
    assert_mass(block["retired_credits_mtco2e"], 0.000, "retired_credits_mtco2e")
    assert_fields_null(block, "signed_off_by_user_id")
