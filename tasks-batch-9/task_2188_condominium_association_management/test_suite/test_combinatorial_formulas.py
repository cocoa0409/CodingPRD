"""Multi-input formulas whose evaluation order is pinned by the contract.

The assessment allocator rounds each line and then reconciles a signed drift by
cycling; the deductible waterfall floors each line and tops the drift up in a
single pass.  Both are exercised on inputs where a plausible alternative order
gives a different answer to the cent.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    allocation_row,
    fetch_ledger_entries,
    find_entry,
    read_claim,
    snapshot_row,
)
from test_helpers.factories import billing_run_payload
from test_helpers.fixtures import (
    add_element,
    add_owner,
    add_unit,
    adjust_claim,
    adopt_budget,
    create_association,
    patch_association,
    report_claim,
    set_clock,
)
from test_helpers.test_users import ADJUSTER_HEADERS, MANAGER_HEADERS


# ======================================================================
# The assessment allocator: per-line half-up, then a signed cycling drift
# ======================================================================
def _four_equal_units_association(api: ApiClient):
    """Four units at exactly 2500 bp -- the split that forces a negative drift."""
    ctx = create_association(api)
    add_owner(ctx, "d1", full_name="Dana Reyes", board_role="PRESIDENT", is_seated=True)
    add_owner(ctx, "d2", full_name="Elliot Shaw", board_role="DIRECTOR", is_seated=True)
    add_owner(ctx, "tr", full_name="Priya Nandan", board_role="TREASURER", is_seated=True)
    add_owner(ctx, "oa", full_name="Owner Alpha")
    for label in ("201", "202", "203", "204"):
        add_unit(ctx, label, "oa", 2500, 1000)
    return ctx


def _adopt_9800024_budget(ctx):
    return adopt_budget(
        ctx,
        fiscal_year=2026,
        operating_total_cents=9_800_024,
        reserve_contribution_cents=1_000_000,
        meeting_start="2026-09-05T18:00:00Z",
        meeting_end="2026-09-05T21:00:00Z",
    )


def test_assessment_pool_is_fixed_in_cents_before_any_per_unit_arithmetic(
    api: ApiClient,
) -> None:
    """The monthly pool is one half-up division of the annual total, done first.

    PRD 3.2: "First, the pool is fixed in integer cents *before* any per-unit
    arithmetic: for a budget adoption the pool is `assessment_total_cents`
    divided by 12 and rounded half up."

    9800024 + 1000000 == 10800024, and round_half_up(10800024 / 12) == 900002.

    Design: Difficulty/combinatorial_formula/assessment_allocation_round_per_line_then_negative_drift_cycle_mode_b
    """
    ctx = _four_equal_units_association(api)

    budget = _adopt_9800024_budget(ctx)

    assert budget["status"] == "ADOPTED"
    assert budget["assessment_total_cents"] == 10_800_024
    assert budget["monthly_assessable_cents"] == 900_002


def test_assessment_allocation_rounds_per_line_then_removes_a_negative_drift(
    api: ApiClient,
) -> None:
    """Four equal shares of 225000.5 round up, so two cents must come back off.

    PRD 3.2: "Third, each participant's share is computed as the pool multiplied
    by that unit's `interest_bp`, divided by 10000, and rounded half up; this
    per-line rounding is mandatory and summing before rounding is wrong. Fourth,
    the rounding drift is measured as the pool minus the sum of the per-line
    shares. Fifth, the drift is distributed one cent at a time by cycling
    through the participants in the same pinned order, starting at the first
    participant and wrapping around as often as necessary: a positive drift adds
    one cent per step, a negative drift removes one cent per step, until the
    drift is exhausted."

    Each line rounds to 225001, summing to 900004, so the drift is -2 and one
    cent leaves each of the first two participants in creation order.

    Design: Difficulty/combinatorial_formula/assessment_allocation_round_per_line_then_negative_drift_cycle_mode_b
    """
    ctx = _four_equal_units_association(api)

    _adopt_9800024_budget(ctx)

    assert ctx.unit("201")["monthly_assessment_cents"] == 225_000
    assert ctx.unit("202")["monthly_assessment_cents"] == 225_000
    assert ctx.unit("203")["monthly_assessment_cents"] == 225_001
    assert ctx.unit("204")["monthly_assessment_cents"] == 225_001


def test_assessment_allocation_shares_sum_back_to_the_pool_exactly(
    api: ApiClient,
) -> None:
    """The post-condition on the allocator is exact equality with the pool.

    PRD 3.2: "When the procedure ends, the sum of the shares equals the pool
    exactly -- that post-condition must hold."

    Design: Difficulty/combinatorial_formula/assessment_allocation_round_per_line_then_negative_drift_cycle_mode_b
    """
    ctx = _four_equal_units_association(api)

    budget = _adopt_9800024_budget(ctx)

    total = sum(
        ctx.unit(label)["monthly_assessment_cents"]
        for label in ("201", "202", "203", "204")
    )
    assert total == budget["monthly_assessable_cents"] == 900_002


def test_allocation_snapshot_flags_only_the_units_whose_share_was_adjusted(
    api: ApiClient,
) -> None:
    """remainder_cent_awarded marks the lines the drift pass actually touched.

    PRD 3.2: "Each unit's `monthly_assessment_cents` receives its final share,
    and the budget's `allocation_snapshot` freezes one object per participant
    carrying `unit_id`, `interest_bp`, `monthly_cents` holding the final share,
    and `remainder_cent_awarded`, a boolean that is true exactly when the final
    share differs from the per-line rounded value computed in the third step."

    Design: Difficulty/combinatorial_formula/assessment_allocation_round_per_line_then_negative_drift_cycle_mode_b
    """
    ctx = _four_equal_units_association(api)

    budget = _adopt_9800024_budget(ctx)
    snapshot = budget["allocation_snapshot"]

    assert len(snapshot) == 4
    first = snapshot_row(snapshot, ctx.units["201"])
    second = snapshot_row(snapshot, ctx.units["202"])
    third = snapshot_row(snapshot, ctx.units["203"])
    fourth = snapshot_row(snapshot, ctx.units["204"])

    assert first["remainder_cent_awarded"] is True
    assert second["remainder_cent_awarded"] is True
    assert third["remainder_cent_awarded"] is False
    assert fourth["remainder_cent_awarded"] is False
    assert first["monthly_cents"] == 225_000
    assert fourth["monthly_cents"] == 225_001
    assert first["interest_bp"] == 2500


def test_billing_run_reports_the_absolute_allocation_drift(api: ApiClient) -> None:
    """The run publishes the absolute value of the drift, so a -2 reads as 2.

    PRD 3.2: "A billing run driven by this budget reports the absolute value of
    the drift measured in the fourth step as its `remainder_cents_allocated`."

    Design: Difficulty/combinatorial_formula/assessment_allocation_round_per_line_then_negative_drift_cycle_mode_b
    """
    ctx = _four_equal_units_association(api)
    budget = _adopt_9800024_budget(ctx)

    set_clock(api, "2026-10-01T00:00:00Z")
    run = validate_success(
        api.create_billing_run(
            ctx.association_id,
            billing_run_payload(
                budget["id"], period="2026-10", due_on="2026-10-10T00:00:00Z"
            ),
            MANAGER_HEADERS,
        ),
        expected_status=201,
    )

    assert run["assessment_charged_cents"] == 900_002
    assert run["remainder_cents_allocated"] == 2
    assert run["charged_unit_count"] == 4
    assert run["late_fees_charged_cents"] == 0


def test_billing_run_posts_each_units_own_adjusted_share(api: ApiClient) -> None:
    """The charge rows carry the snapshot's monthly_cents, drift cent included.

    PRD 3.5: "First, one `ASSESSMENT` row per unit is posted from the budget's
    `allocation_snapshot`, each carrying that unit's `monthly_cents` as its
    positive `amount_cents`, the run's `due_on` as its `due_on`, the run's
    `period` as its `effective_period`, and the run's identifier as its
    `billing_run_id`; the run reports `assessment_charged_cents` as the sum of
    those amounts, `charged_unit_count` as the number of units that received at
    least one charge in this run, and `remainder_cents_allocated` as the absolute
    rounding drift the allocator reconciled."

    Design: Difficulty/combinatorial_formula/assessment_allocation_round_per_line_then_negative_drift_cycle_mode_b
    """
    ctx = _four_equal_units_association(api)
    budget = _adopt_9800024_budget(ctx)

    set_clock(api, "2026-10-01T00:00:00Z")
    run = get_success_data(
        api.create_billing_run(
            ctx.association_id,
            billing_run_payload(
                budget["id"], period="2026-10", due_on="2026-10-10T00:00:00Z"
            ),
            MANAGER_HEADERS,
        )
    )

    trimmed = find_entry(ctx.ledger("201"), entry_type="ASSESSMENT")
    untrimmed = find_entry(ctx.ledger("204"), entry_type="ASSESSMENT")
    assert trimmed["amount_cents"] == 225_000
    assert untrimmed["amount_cents"] == 225_001
    assert trimmed["effective_period"] == "2026-10"
    assert trimmed["billing_run_id"] == run["id"]


# ======================================================================
# The deductible waterfall: tier basis pinned to gross damage
# ======================================================================
def _split_claim_association(api: ApiClient):
    """Three units of unequal area under a 3000000 deductible capped at 2500000."""
    ctx = create_association(
        api,
        legal_name="Beacon Row Condominium Association",
        master_policy_deductible_cents=3_000_000,
        association_deductible_cap_cents=2_500_000,
    )
    patch_association(ctx, operating_cash_cents=10_000_000)
    add_owner(ctx, "oa", full_name="Owner Alpha")
    add_unit(ctx, "big", "oa", 4000, 1500)
    add_unit(ctx, "mid", "oa", 3500, 1100)
    add_unit(ctx, "small", "oa", 2500, 700)
    add_element(
        ctx,
        "facade",
        name="South Facade",
        element_class="FACADE",
        replacement_cost_cents=8_000_000,
        useful_life_years=40,
        effective_age_years=12,
    )
    claim = report_claim(
        ctx,
        "big",
        "facade",
        loss_type="WATER",
        loss_at="2026-07-20T00:00:00Z",
        gross_damage_cents=4_800_000,
        within_unit_boundary_cents=400_000,
        # Deliberately not in area order: the waterfall must re-sort.
        affected_unit_ids=[ctx.units["small"], ctx.units["big"], ctx.units["mid"]],
    )
    return ctx, claim


def test_deductible_tier_is_keyed_on_gross_damage_not_the_owner_exposure(
    api: ApiClient,
) -> None:
    """Gross damage of 4800000 stays in the hundred-percent band.

    PRD 3.7: "The tier basis is the claim's `gross_damage_cents` and **only**
    that figure; the owner exposure the waterfall itself produces is a reported
    output and is never fed back into the tier decision."

    The pinned basis yields 10000 bp, so the raw slice is the whole 3000000
    deductible and the cap binds at 2500000; folding the 500000 owner exposure
    back into the basis would reach 5300000, select 6000 bp, and absorb 1800000
    instead.

    Design: Difficulty/combinatorial_formula/deductible_waterfall_tier_basis_pinned_to_gross_damage_mode_c
    """
    ctx, claim = _split_claim_association(api)

    adjusted = adjust_claim(ctx, claim["id"], "SPLIT")

    assert adjusted["adjustment_status"] == "ADJUSTED_SPLIT"
    assert adjusted["common_element_damage_cents"] == 4_400_000
    assert adjusted["association_absorbed_cents"] == 2_500_000
    assert adjusted["owner_chargeback_cents"] == 500_000


def test_deductible_absorbed_slice_is_capped_after_the_single_rounding(
    api: ApiClient,
) -> None:
    """The cap is applied to the raw slice, and the residue is what is left.

    PRD 3.7: "The raw association slice is `master_policy_deductible_cents`
    multiplied by that share, divided by 10000, and rounded half up -- one such
    rounding, on this figure only -- and `association_absorbed_cents` is the
    lesser of that raw slice and `association_deductible_cap_cents`. The residue
    is `master_policy_deductible_cents` minus `association_absorbed_cents`."

    Design: Difficulty/combinatorial_formula/deductible_waterfall_tier_basis_pinned_to_gross_damage_mode_c
    """
    ctx, claim = _split_claim_association(api)

    adjusted = adjust_claim(ctx, claim["id"], "SPLIT")

    absorbed = adjusted["association_absorbed_cents"]
    assert absorbed == 2_500_000
    assert adjusted["owner_chargeback_cents"] == 3_000_000 - absorbed
    assert (
        sum(row["allocated_cents"] for row in adjusted["deductible_allocation"])
        == 3_000_000 - absorbed
    )


def test_deductible_allocation_orders_participants_by_area_descending(
    api: ApiClient,
) -> None:
    """Input order is irrelevant: the waterfall sorts by heated_sqft descending.

    PRD 3.7: "The participants are the units named in `affected_unit_ids` with
    no delinquency filter, ordered by `heated_sqft` descending and then by
    `created_at` ascending; the total square footage is the sum of their
    `heated_sqft`."

    Design: Difficulty/combinatorial_formula/deductible_waterfall_tier_basis_pinned_to_gross_damage_mode_c
    """
    ctx, claim = _split_claim_association(api)

    adjusted = adjust_claim(ctx, claim["id"], "SPLIT")
    allocation = adjusted["deductible_allocation"]

    assert len(allocation) == 3
    assert [row["unit_id"] for row in allocation] == [
        ctx.units["big"],
        ctx.units["mid"],
        ctx.units["small"],
    ]
    assert [row["heated_sqft"] for row in allocation] == [1500, 1100, 700]


def test_deductible_lines_are_floored_and_drift_tops_up_one_cent_each(
    api: ApiClient,
) -> None:
    """A floor per line plus a single top-up pass -- never a cycling half-up.

    PRD 3.7: "Each unit's provisional allocation is the residue multiplied by
    that unit's `heated_sqft`, divided by the total square footage, and
    **floored** -- a floor here, not a rounding. The drift is the residue minus
    the sum of the floored allocations and is at least 0 and strictly less than
    the number of participants; one additional cent is given to each of the
    first drift participants in that pinned order, at most one cent each."

    floor(500000*1500/3300) == 227272, floor(500000*1100/3300) == 166666 and
    floor(500000*700/3300) == 106060 sum to 499998, so the two drift cents land
    on the first two participants only.

    Design: Difficulty/combinatorial_formula/deductible_waterfall_tier_basis_pinned_to_gross_damage_mode_c
    """
    ctx, claim = _split_claim_association(api)

    adjusted = adjust_claim(ctx, claim["id"], "SPLIT")
    allocation = adjusted["deductible_allocation"]

    assert allocation_row(allocation, ctx.units["big"])["allocated_cents"] == 227_273
    assert allocation_row(allocation, ctx.units["mid"])["allocated_cents"] == 166_667
    assert allocation_row(allocation, ctx.units["small"])["allocated_cents"] == 106_060


def test_split_adjustment_charges_each_unit_and_debits_the_absorbed_slice(
    api: ApiClient,
) -> None:
    """One chargeback row per allocation row, and the absorbed cents leave cash.

    PRD 3.7: "It runs the deductible waterfall below, posts one
    `INSURANCE_DEDUCTIBLE_CHARGEBACK` row per allocation row in allocation
    order, recomputes each affected unit's `balance_due_cents` and re-derives
    each `delinquency_stage` with each `Unit.version` advancing by 1, reduces the
    association's `operating_cash_cents` by `association_absorbed_cents` with
    `Association.version` advancing by 1, and advances `InsuranceClaim.version`
    by 1."

    Design: Difficulty/combinatorial_formula/deductible_waterfall_tier_basis_pinned_to_gross_damage_mode_c
    """
    ctx, claim = _split_claim_association(api)

    adjust_claim(ctx, claim["id"], "SPLIT")

    for label, expected in (("big", 227_273), ("mid", 166_667), ("small", 106_060)):
        rows = fetch_ledger_entries(
            api, MANAGER_HEADERS, unit_id=ctx.units[label]
        )
        chargeback = find_entry(rows, entry_type="INSURANCE_DEDUCTIBLE_CHARGEBACK")
        assert chargeback["amount_cents"] == expected
        assert chargeback["bucket"] == "ASSESSMENT"
        assert ctx.unit(label)["balance_due_cents"] == expected

    assert ctx.association()["operating_cash_cents"] == 7_500_000
    assert (
        read_claim(api, claim["id"], ADJUSTER_HEADERS)["association_absorbed_cents"]
        == 2_500_000
    )
