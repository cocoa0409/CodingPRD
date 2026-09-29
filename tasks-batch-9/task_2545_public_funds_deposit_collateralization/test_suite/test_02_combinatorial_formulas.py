"""Composed formulas: the required percentage, the per-allocation rounding order and the
deficiency-surcharge snapshot."""

from test_helpers import assertions, fixtures, get_success_data
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.fixtures import OFFICER, REGULATOR


def _thin_capital_bank_with_both_pledging_modes(client):
    """An UNDERCAPITALIZED pool member holding one dedicated and one pooled account."""
    fixtures.set_clock(client, DEFAULT_CLOCK_UTC)
    pool = fixtures.create_pooled_program(
        client, name="Ohio Public Deposit Pool", minimum_pool_pct_bps=10000
    )
    dedicated_unit = fixtures.create_public_unit(
        client,
        name="Ridge County",
        unit_type="COUNTY",
        collateral_program_preference="DEDICATED",
    )
    pooled_unit = fixtures.create_public_unit(
        client,
        name="Ridge Schools",
        unit_type="SCHOOL_DISTRICT",
        collateral_program_preference="POOLED",
    )
    depository = fixtures.create_approved_depository(
        client,
        name="Thin Capital Bank",
        capital_ratio_bps=700,
        pooled_program_id=pool["id"],
    )
    dedicated_account = fixtures.create_deposit_account(
        client,
        depository["id"],
        dedicated_unit["id"],
        deposit_class="DEMAND",
        pledging_mode="DEDICATED",
    )
    pooled_account = fixtures.create_deposit_account(
        client,
        depository["id"],
        pooled_unit["id"],
        deposit_class="DEMAND",
        pledging_mode="POOLED",
    )
    return {
        "depository": depository,
        "dedicated_unit": dedicated_unit,
        "pooled_unit": pooled_unit,
        "dedicated_account": dedicated_account,
        "pooled_account": pooled_account,
    }


def test_undercapitalized_dedicated_account_requires_the_bare_tier_percentage(client):
    """A capital ratio of 700 basis points is UNDERCAPITALIZED, so a DEDICATED account
    holding 100,000,000 cents — 75,000,000 of it uninsured — requires 12500 basis points and
    93,750,000 cents, with no mode surcharge and no deficiency surcharge in the sum.

    PRD: "From the capital ratio the service derives `capital_tier` immediately, with
    inclusive lower bounds: a ratio of at least 1000 basis points is `WELL_CAPITALIZED`, a
    ratio below that but at least 800 basis points is `ADEQUATELY_CAPITALIZED`, and anything
    below 800 basis points is `UNDERCAPITALIZED`."
    PRD: "Step two adds a pledging-mode surcharge keyed on *the account's own*
    `pledging_mode` rather than on the unit's stated preference: nothing for a `DEDICATED`
    account and 500 basis points for a `POOLED` one."
    PRD: "The account's `required_collateral_cents` is then the uninsured amount scaled by
    that percentage — `uninsured_amount_cents` multiplied by `required_collateral_pct_bps`,
    divided by 10000, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/required_pct_tier_and_pledging_mode_surcharge_composition
    """
    setup = _thin_capital_bank_with_both_pledging_modes(client)
    assert setup["depository"]["capital_tier"] == "UNDERCAPITALIZED"
    assertions.assert_capital_tier_matches_ratio(setup["depository"])

    account = fixtures.deposit(
        client,
        setup["dedicated_account"]["id"],
        setup["dedicated_unit"]["id"],
        100_000_000,
    )

    assert account["uninsured_amount_cents"] == 75_000_000
    assert account["required_collateral_pct_bps"] == 12500
    assert account["required_collateral_cents"] == 93_750_000
    assert account["pledging_mode"] == "DEDICATED"
    assert account["pooled_allocated_collateral_cents"] == 0


def test_undercapitalized_pooled_account_adds_the_pooled_mode_surcharge(client):
    """The identical 75,000,000-cent uninsured balance on a POOLED account at the same
    UNDERCAPITALIZED bank composes 12500 plus the 500-basis-point mode surcharge into 13000
    basis points and 97,500,000 cents — still under the 15000-basis-point cap.

    PRD: "Step four combines the three additively and then applies a hard cap: the stored
    percentage is the lesser of 15000 basis points and the sum of the tier, mode and
    deficiency components."
    PRD: "The account also carries `pool_priority_rank`, derived once from its public unit's
    `unit_type`: a `SCHOOL_DISTRICT` ranks 1, a `COUNTY` ranks 2, a `MUNICIPALITY` ranks 3
    and a `STATE_AGENCY` ranks 4, which is also the field's default."

    Design: Difficulty/combinatorial_formula/required_pct_tier_and_pledging_mode_surcharge_composition
    """
    setup = _thin_capital_bank_with_both_pledging_modes(client)

    account = fixtures.deposit(
        client, setup["pooled_account"]["id"], setup["pooled_unit"]["id"], 100_000_000
    )

    assert account["uninsured_amount_cents"] == 75_000_000
    assert account["required_collateral_pct_bps"] == 13000
    assert account["required_collateral_cents"] == 97_500_000
    assert account["pool_priority_rank"] == 1
    assert account["required_collateral_pct_bps"] < 15000


def _agreement_with_odd_priced_treasury(client):
    """A dedicated arrangement whose only asset is priced at 9950 basis points, so each
    valuation step lands on a half cent."""
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=30_000_000)
    asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="US_TREASURY",
        par_value_cents=5_000_000,
        market_price_bps=9950,
    )
    perimeter["asset"] = asset
    return perimeter


def test_two_allocations_round_per_allocation_before_the_agreement_total(client):
    """Pledging 1,000,001 and then 2,000,020 cents of par at 9950 basis points values the
    slices at 975,101 and 1,950,220 cents, and the agreement total is their already-rounded
    sum, 2,925,321 — one cent above the 2,925,320 a sum-then-round order would produce.

    PRD: "For an individual allocation, the same two steps run against the pledged slice
    rather than the full par: the allocation's market value is `allocated_par_cents`
    multiplied by the asset's `market_price_bps`, divided by 10000, rounded half up; then
    `allocated_collateral_value_cents` is that figure multiplied by 10000 minus the asset's
    `haircut_bps`, divided by 10000, rounded half up."
    PRD: "Aggregates are assembled by **summing the already-rounded per-allocation
    values**, never by re-deriving the total from unrounded par, price and haircut."
    PRD: "The agreement's totals and `active_allocation_count` are updated and **the
    agreement's `version` is incremented by 1**, which is precisely why a client that has
    just created one allocation must re-read the agreement before creating a second."

    Design: Difficulty/combinatorial_formula/collateral_value_per_allocation_then_sum_rounding_order
    """
    perimeter = _agreement_with_odd_priced_treasury(client)

    first = fixtures.create_allocation(
        client, perimeter["agreement_id"], perimeter["asset"]["id"], 1_000_001
    )
    second = fixtures.create_allocation(
        client, perimeter["agreement_id"], perimeter["asset"]["id"], 2_000_020
    )

    assert first["allocated_collateral_value_cents"] == 975_101
    assert second["allocated_collateral_value_cents"] == 1_950_220

    agreement = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert agreement["total_collateral_value_cents"] == 2_925_321
    assert agreement["total_collateral_value_cents"] != 2_925_320
    assert agreement["total_pledged_par_cents"] == 3_000_021
    assert agreement["active_allocation_count"] == 2


def test_asset_mirrors_and_account_coverage_follow_the_per_allocation_total(client):
    """The same two pledges leave the asset itself valued 4,975,000 then 4,875,500 cents on
    its full par, its par mirrors split 3,000,021 pledged against 1,999,979 available, and
    the beneficiary account covered 2,925,321 against 5,250,000 required — a floored 5572
    basis points, which is DEFICIENT.

    PRD: "For the asset as a whole, `market_value_cents` is `par_value_cents` multiplied by
    `market_price_bps`, divided by 10000, rounded half up to whole cents; then
    `collateral_value_cents` is that market value multiplied by the quantity 10000 minus
    `haircut_bps`, divided by 10000, again rounded half up to whole cents."
    PRD: "`available_par_cents` is then `par_value_cents` less `pledged_par_cents`, and it
    can never go negative even when two `ACTIVE` allocations each committing the full par sit
    on disjoint intervals."
    PRD: "When `required_collateral_cents` is zero the ratio is defined as 10000; otherwise
    it is `assigned_collateral_value_cents` multiplied by 10000, divided by
    `required_collateral_cents`, floored to whole basis points."

    Design: Difficulty/combinatorial_formula/collateral_value_per_allocation_then_sum_rounding_order
    """
    perimeter = _agreement_with_odd_priced_treasury(client)

    fixtures.create_allocation(
        client, perimeter["agreement_id"], perimeter["asset"]["id"], 1_000_001
    )
    fixtures.create_allocation(
        client, perimeter["agreement_id"], perimeter["asset"]["id"], 2_000_020
    )

    asset = get_success_data(
        client.get_collateral_asset(perimeter["asset"]["id"], OFFICER), 200
    )
    assert asset["market_value_cents"] == 4_975_000
    assert asset["collateral_value_cents"] == 4_875_500
    assert asset["pledged_par_cents"] == 3_000_021
    assert asset["available_par_cents"] == 1_999_979
    assert asset["pledge_status"] == "PARTIALLY_PLEDGED"
    assertions.assert_asset_par_conservation(asset)

    account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert account["required_collateral_cents"] == 5_250_000
    assert account["assigned_collateral_value_cents"] == 2_925_321
    assert account["coverage_ratio_bps"] == 5572
    assert account["collateral_status"] == "DEFICIENT"
    assertions.assert_coverage_ratio_floored(account)


def _uncollateralized_bank_with_one_funded_account(client):
    """A well-capitalized bank carrying a single funded demand account and no collateral at
    all, so every valuation run is deficient."""
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    return perimeter


MTM_WINDOWS = [
    ("2026-07-30T00:00:00Z", "2026-07-30T06:00:00Z"),
    ("2026-07-30T12:00:00Z", "2026-07-30T18:00:00Z"),
    ("2026-07-31T00:00:00Z", "2026-07-31T06:00:00Z"),
]


def test_first_two_runs_price_the_requirement_without_any_surcharge(client):
    """The first valuation run finds no prior deficiency streak and the second still sees a
    snapshot of only one, so both require the bare 78,750,000 cents rather than a
    surcharge-inflated figure.

    PRD: "Before anything is mutated, the service reads the depository's current
    `consecutive_deficiency_runs` and holds that value for the entire run."
    PRD: "The run's `deficiency_surcharge_bps_applied` is 1000 basis points when the snapshot
    is 2 or more, and zero otherwise."
    PRD: "For every deposit account of the depository whose `funding_status` is `FUNDED` or
    `RESTRICTED`, the service re-runs insured-amount determination and then the
    required-collateral-percentage computation of §3.2, using the step-one snapshot as the
    deficiency counter throughout — never the incremented value."
    PRD: "The run's `total_required_collateral_cents` is the sum of
    `required_collateral_cents` over exactly those accounts."

    Design: Difficulty/combinatorial_formula/mtm_deficiency_surcharge_snapshot_evaluation_order
    """
    perimeter = _uncollateralized_bank_with_one_funded_account(client)

    first = fixtures.create_mtm_run(
        client, perimeter["depository_id"], MTM_WINDOWS[0][0], MTM_WINDOWS[0][1]
    )
    assertions.assert_mtm_run(first)
    assert first["run_index"] == 1
    assert first["deficiency_surcharge_bps_applied"] == 0
    assert first["total_required_collateral_cents"] == 78_750_000
    assert first["total_collateral_value_cents"] == 0
    assert first["deficiency_cents"] == 78_750_000
    assert first["outcome"] == "DEFICIENT"

    second = fixtures.create_mtm_run(
        client, perimeter["depository_id"], MTM_WINDOWS[1][0], MTM_WINDOWS[1][1]
    )
    assert second["run_index"] == 2
    assert second["deficiency_surcharge_bps_applied"] == 0
    assert second["total_required_collateral_cents"] == 78_750_000
    assert second["outcome"] == "DEFICIENT"


def test_third_run_adds_the_surcharge_and_freezes_the_posture(client):
    """Once two deficient runs are already on record the third run's percentage carries the
    1000 basis point surcharge, lifting the requirement to 86,250,000 cents at a fully
    uncovered 10000 basis point deficiency ratio, and the bank's posture turns FROZEN with
    three open margin calls.

    PRD: "Step three adds a deficiency surcharge of 1000 basis points when the depository's
    `consecutive_deficiency_runs` counter stands at 2 or more, and nothing otherwise; inside a
    mark-to-market run the counter used here is the snapshot taken before the run mutates it,
    never the post-run value."
    PRD: "`deficiency_ratio_bps` is zero when `total_required_collateral_cents` is zero;
    otherwise it is `deficiency_cents` multiplied by 10000, divided by
    `total_required_collateral_cents`, floored to whole basis points."
    PRD: "Either way the depository's `mtm_run_index` is set to the run's `run_index`, its
    `last_mtm_window_end` is set to the run's `window_end`, and its `collateral_posture` is
    re-derived: `FROZEN` when `consecutive_deficiency_runs` has reached 3 or more, otherwise
    `MARGIN_DEFICIENT` when `open_margin_call_count` is 1 or more, otherwise `COMPLIANT`."

    Design: Difficulty/combinatorial_formula/mtm_deficiency_surcharge_snapshot_evaluation_order
    """
    perimeter = _uncollateralized_bank_with_one_funded_account(client)

    for window_start, window_end in MTM_WINDOWS[:2]:
        fixtures.create_mtm_run(
            client, perimeter["depository_id"], window_start, window_end
        )

    third = fixtures.create_mtm_run(
        client, perimeter["depository_id"], MTM_WINDOWS[2][0], MTM_WINDOWS[2][1]
    )
    assert third["run_index"] == 3
    assert third["deficiency_surcharge_bps_applied"] == 1000
    assert third["total_required_collateral_cents"] == 86_250_000
    assert third["deficiency_cents"] == 86_250_000
    assert third["deficiency_ratio_bps"] == 10000
    assert third["outcome"] == "DEFICIENT"

    account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert account["required_collateral_pct_bps"] == 11500
    assert account["required_collateral_cents"] == 86_250_000

    depository = get_success_data(
        client.get_depository(perimeter["depository_id"], REGULATOR), 200
    )
    assert depository["consecutive_deficiency_runs"] == 3
    assert depository["collateral_posture"] == "FROZEN"
    assert depository["open_margin_call_count"] == 3
