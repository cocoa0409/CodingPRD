"""Conserved quantities that must survive a compensating action: one asset's par across an
allocate-and-release cycle, and one pool's pot across the same cycle."""

from test_helpers import assertions, fixtures, get_success_data, validate_paginated
from test_helpers.constants import DEFAULT_CLOCK_UTC, clock_stamp
from test_helpers.fixtures import OFFICER, REGULATOR

ASSET_PAR = 10_000_000
SLICE_PAR = 4_000_000


def _agreement_with_ten_million_par_of_treasury(client):
    """A dedicated arrangement requiring 78,750,000 cents, holding one treasury of 10,000,000
    cents of par priced at par."""
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="US_TREASURY",
        par_value_cents=ASSET_PAR,
        market_price_bps=10000,
    )
    assert asset["pledged_par_cents"] == 0
    assert asset["available_par_cents"] == ASSET_PAR
    assert asset["collateral_value_cents"] == 9_800_000
    assertions.assert_asset_par_conservation(asset)
    perimeter["asset_id"] = asset["id"]
    return perimeter


def test_releasing_a_pledge_reverses_every_figure_it_created(client):
    """Pledging 4,000,000 of the 10,000,000 cents of par splits the asset 4,000,000 against
    6,000,000 and drives the account to 497 basis points; releasing the pledge restores the par
    exactly, zeroes the agreement, the bank mirrors and the account's assigned value, and leaves
    the requirement itself untouched.

    PRD: "`available_par_cents` is then `par_value_cents` less `pledged_par_cents`, and it can
    never go negative even when two `ACTIVE` allocations each committing the full par sit on
    disjoint intervals."
    PRD: "A release sets `status` to `RELEASED`, stamps `released_at` from the clock, records
    `release_reason` as `OFFICER_RELEASE`, and increments the allocation's `version`; it then
    decreases the asset's `pledged_par_cents` by the allocated par, re-derives
    `available_par_cents` and `pledge_status`, recomputes the agreement's totals, recomputes the
    beneficiary (dedicated account coverage, or a fresh pool waterfall run), and finally
    recomputes the affected public units' `exposure_status`."
    PRD: "`SECURED → UNSECURED` and `DEFICIENT → UNSECURED` when every allocation that was
    covering the account has left `ACTIVE`, so `assigned_collateral_value_cents` is zero while
    `required_collateral_cents` is still greater than zero."

    Design: Difficulty/compensating_invariant/asset_par_conservation_through_allocate_and_release
    """
    perimeter = _agreement_with_ten_million_par_of_treasury(client)

    allocation = fixtures.create_allocation(
        client, perimeter["agreement_id"], perimeter["asset_id"], SLICE_PAR
    )
    assert allocation["status"] == "ACTIVE"
    assert allocation["allocated_collateral_value_cents"] == 3_920_000

    pledged = get_success_data(client.get_collateral_asset(perimeter["asset_id"], OFFICER), 200)
    assert pledged["pledged_par_cents"] == SLICE_PAR
    assert pledged["available_par_cents"] == 6_000_000
    assertions.assert_asset_par_conservation(pledged)

    covered = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert covered["assigned_collateral_value_cents"] == 3_920_000
    assert covered["coverage_ratio_bps"] == 497
    assert covered["collateral_status"] == "DEFICIENT"

    released = fixtures.release_allocation(client, allocation["id"])
    assert released["status"] == "RELEASED"
    assert released["released_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert released["release_reason"] == "OFFICER_RELEASE"

    restored = get_success_data(
        client.get_collateral_asset(perimeter["asset_id"], OFFICER), 200
    )
    assert restored["pledged_par_cents"] == 0
    assert restored["available_par_cents"] == ASSET_PAR
    assert restored["pledge_status"] == "UNPLEDGED"
    assertions.assert_asset_par_conservation(restored)

    agreement = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert agreement["total_collateral_value_cents"] == 0
    assert agreement["total_pledged_par_cents"] == 0
    assert agreement["active_allocation_count"] == 0

    depository = get_success_data(
        client.get_depository(perimeter["depository_id"], REGULATOR), 200
    )
    assert depository["total_pledged_collateral_value_cents"] == 0
    assert depository["total_pledged_par_cents"] == 0

    account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert account["assigned_collateral_value_cents"] == 0
    assert account["coverage_ratio_bps"] == 0
    assert account["collateral_status"] == "UNSECURED"
    assert account["required_collateral_cents"] == 78_750_000


def test_the_freed_capacity_takes_the_whole_par_afterwards(client):
    """After the release the asset will accept a pledge of its entire par — worth 9,800,000
    cents and 1244 basis points of the requirement — and the asset's history keeps both rows,
    one RELEASED and one ACTIVE.

    PRD: "The asset's `pledged_par_cents` grows by the allocated par and its
    `available_par_cents` shrinks correspondingly, with `pledge_status` re-derived."
    PRD: "From `pledged_par_cents` the service also derives `pledge_status`: `UNPLEDGED` when
    nothing is pledged, `PARTIALLY_PLEDGED` when some but not all of the par is pledged, and
    `FULLY_PLEDGED` when the pledged par equals `par_value_cents` exactly."
    PRD: "`RELEASED` and `SUBSTITUTED` are both terminal for an allocation, and the four values
    `release_reason` can take are `OFFICER_RELEASE`, `AGREEMENT_TERMINATED`, `ASSET_INELIGIBLE`
    and `SUBSTITUTION_SETTLED`."

    Design: Difficulty/compensating_invariant/asset_par_conservation_through_allocate_and_release
    """
    perimeter = _agreement_with_ten_million_par_of_treasury(client)

    first = fixtures.create_allocation(
        client, perimeter["agreement_id"], perimeter["asset_id"], SLICE_PAR
    )
    fixtures.release_allocation(client, first["id"])

    whole = fixtures.create_allocation(
        client, perimeter["agreement_id"], perimeter["asset_id"], ASSET_PAR
    )
    assert whole["status"] == "ACTIVE"
    assert whole["allocated_collateral_value_cents"] == 9_800_000

    asset = get_success_data(client.get_collateral_asset(perimeter["asset_id"], OFFICER), 200)
    assert asset["pledged_par_cents"] == ASSET_PAR
    assert asset["available_par_cents"] == 0
    assert asset["pledge_status"] == "FULLY_PLEDGED"
    assertions.assert_asset_par_conservation(asset)

    account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert account["coverage_ratio_bps"] == 1244
    assert account["collateral_status"] == "DEFICIENT"

    rows, meta = validate_paginated(
        client.list_pledge_allocations(
            OFFICER, {"collateral_asset_id": perimeter["asset_id"]}
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["status"] for row in rows) == ["ACTIVE", "RELEASED"]


POOL_ASSET_PAR = 100_000_000
POOLED_REQUIREMENT = 82_500_000


def _pool_with_a_school_district_ahead_of_a_county(client):
    """A pool of two funded POOLED accounts, each requiring 82,500,000 cents, with one treasury
    of 100,000,000 cents of par standing by unpledged."""
    perimeter = fixtures.build_pooled_perimeter(
        client,
        [("SCHOOL_DISTRICT", 100_000_000), ("COUNTY", 100_000_000)],
        minimum_pool_pct_bps=11000,
    )
    school_unit, school_account = perimeter["accounts"][0]
    county_unit, county_account = perimeter["accounts"][1]
    assert school_account["required_collateral_cents"] == POOLED_REQUIREMENT
    assert school_account["required_collateral_pct_bps"] == 11000
    assert school_account["pool_priority_rank"] == 1
    assert county_account["required_collateral_cents"] == POOLED_REQUIREMENT
    assert county_account["pool_priority_rank"] == 2

    asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="US_TREASURY",
        par_value_cents=POOL_ASSET_PAR,
        market_price_bps=10000,
    )
    perimeter["asset_id"] = asset["id"]
    perimeter["school_unit_id"] = school_unit["id"]
    perimeter["school_account_id"] = school_account["id"]
    perimeter["county_unit_id"] = county_unit["id"]
    perimeter["county_account_id"] = county_account["id"]
    return perimeter


def test_the_pot_equals_the_shares_plus_the_residual_after_the_waterfall(client):
    """One pledge of 100,000,000 cents of par fills the pot with 98,000,000, the statutory rank
    order hands the school district its full 82,500,000 and leaves the county only 15,500,000,
    nothing survives as unallocated, and the pool reads SHORTFALL against its 11000-basis-point
    floor.

    PRD: "Each participant in turn takes as its `pooled_allocated_collateral_cents` the lesser of
    the remainder and its own `required_collateral_cents`; that amount is also written to its
    `assigned_collateral_value_cents`; and the remainder is reduced by the amount just taken."
    PRD: "Whatever survives the walk becomes the pool's `unallocated_collateral_cents`. Because
    only comparison and subtraction of whole cents occur, the identity is exact: the pot always
    equals the sum of the participants' allocated shares plus the unallocated residual, with
    nothing created and nothing lost."
    PRD: "The primary key is `pool_priority_rank` ascending, so school districts are made whole
    before counties, counties before municipalities, and municipalities before state agencies."
    PRD: "`pool_posture` is `SHORTFALL` when `aggregate_collateral_value_cents` multiplied by
    10000 is strictly less than `aggregate_required_collateral_cents` multiplied by the pool's
    `minimum_pool_pct_bps`, and `ADEQUATE` otherwise."

    Design: Difficulty/compensating_invariant/pooled_program_value_conservation_across_waterfall
    """
    perimeter = _pool_with_a_school_district_ahead_of_a_county(client)

    fixtures.create_allocation(
        client, perimeter["agreement_id"], perimeter["asset_id"], POOL_ASSET_PAR
    )

    pool = get_success_data(client.get_pooled_program(perimeter["pool_id"], REGULATOR), 200)
    assertions.assert_pooled_program(pool)
    assert pool["aggregate_collateral_value_cents"] == 98_000_000
    assert pool["aggregate_required_collateral_cents"] == 165_000_000
    assert pool["participant_account_count"] == 2
    assert pool["unallocated_collateral_cents"] == 0
    assert pool["pool_posture"] == "SHORTFALL"

    school = get_success_data(
        client.get_deposit_account(perimeter["school_account_id"], OFFICER), 200
    )
    assert school["pooled_allocated_collateral_cents"] == 82_500_000
    assert school["assigned_collateral_value_cents"] == 82_500_000
    assert school["coverage_ratio_bps"] == 10000
    assert school["collateral_status"] == "SECURED"

    county = get_success_data(
        client.get_deposit_account(perimeter["county_account_id"], OFFICER), 200
    )
    assert county["pooled_allocated_collateral_cents"] == 15_500_000
    assert county["assigned_collateral_value_cents"] == 15_500_000
    assert county["coverage_ratio_bps"] == 1878
    assert county["collateral_status"] == "DEFICIENT"

    assert (
        pool["aggregate_collateral_value_cents"]
        == school["pooled_allocated_collateral_cents"]
        + county["pooled_allocated_collateral_cents"]
        + pool["unallocated_collateral_cents"]
    )


def test_the_waterfall_leaves_no_residue_across_a_release_and_a_re_pledge(client):
    """Releasing the single pledge drains the pot to zero with both shares zeroed and neither
    requirement touched, and re-pledging the identical par reproduces the identical unequal
    split, with the participant set and the aggregate requirement never having moved.

    PRD: "The waterfall is re-run whenever a pooled agreement's value or a participant's
    requirement can have moved. That means after creating an allocation, after releasing one,
    after posting a new market price, after declaring an asset ineligible, after settling a
    substitution, after terminating an agreement, after a deposit, after a withdrawal, and after
    suspending a depository."
    PRD: "A pool whose pot runs dry mid-walk leaves every remaining participant at a share of
    zero, which drives those accounts to `UNSECURED` or `DEFICIENT` according to the rules of
    §3.2."
    PRD: "`aggregate_required_collateral_cents` is the sum of `required_collateral_cents` over
    the participants, and `participant_account_count` is how many participants there were."

    Design: Difficulty/compensating_invariant/pooled_program_value_conservation_across_waterfall
    """
    perimeter = _pool_with_a_school_district_ahead_of_a_county(client)

    allocation = fixtures.create_allocation(
        client, perimeter["agreement_id"], perimeter["asset_id"], POOL_ASSET_PAR
    )
    fixtures.release_allocation(client, allocation["id"])

    drained = get_success_data(client.get_pooled_program(perimeter["pool_id"], REGULATOR), 200)
    assert drained["aggregate_collateral_value_cents"] == 0
    assert drained["unallocated_collateral_cents"] == 0
    assert drained["aggregate_required_collateral_cents"] == 165_000_000
    assert drained["participant_account_count"] == 2

    for account_id in (perimeter["school_account_id"], perimeter["county_account_id"]):
        emptied = get_success_data(client.get_deposit_account(account_id, OFFICER), 200)
        assert emptied["pooled_allocated_collateral_cents"] == 0
        assert emptied["assigned_collateral_value_cents"] == 0
        assert emptied["coverage_ratio_bps"] == 0
        assert emptied["collateral_status"] == "UNSECURED"
        assert emptied["required_collateral_cents"] == POOLED_REQUIREMENT

    fixtures.create_allocation(
        client, perimeter["agreement_id"], perimeter["asset_id"], POOL_ASSET_PAR
    )

    refilled = get_success_data(client.get_pooled_program(perimeter["pool_id"], REGULATOR), 200)
    assert refilled["aggregate_collateral_value_cents"] == 98_000_000
    assert refilled["unallocated_collateral_cents"] == 0
    assert refilled["aggregate_required_collateral_cents"] == 165_000_000
    assert refilled["participant_account_count"] == 2
    assert refilled["pool_posture"] == "SHORTFALL"

    school = get_success_data(
        client.get_deposit_account(perimeter["school_account_id"], OFFICER), 200
    )
    county = get_success_data(
        client.get_deposit_account(perimeter["county_account_id"], OFFICER), 200
    )
    assert school["pooled_allocated_collateral_cents"] == 82_500_000
    assert school["collateral_status"] == "SECURED"
    assert county["pooled_allocated_collateral_cents"] == 15_500_000
    assert county["collateral_status"] == "DEFICIENT"
