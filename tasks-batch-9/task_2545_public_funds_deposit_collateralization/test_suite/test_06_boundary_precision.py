"""Inclusive bounds and single-cent precision on the capital floor and the coverage cut."""

from test_helpers import assertions, fixtures, get_success_data
from test_helpers.fixtures import OFFICER, REGULATOR


def _three_banks_astride_the_capital_floor(client):
    """One county holding one funded demand account at each of three otherwise identical banks
    whose capital ratios are 999, 1000 and 1001 basis points."""
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client)
    accounts = {}
    for label, ratio, name in (
        ("below", 999, "Below Floor Bank"),
        ("at", 1000, "At Floor Bank"),
        ("above", 1001, "Above Floor Bank"),
    ):
        depository = fixtures.create_approved_depository(
            client, capital_ratio_bps=ratio, name=name
        )
        accounts[label] = fixtures.create_funded_account(
            client, depository["id"], public_unit["id"], 100_000_000
        )
    accounts["public_unit_id"] = public_unit["id"]
    return accounts


def test_the_well_capitalized_floor_is_inclusive_at_one_thousand_basis_points(client):
    """A bank sitting exactly on the 1000 basis point floor is well capitalized and requires
    10500 basis points, the same as one a single basis point above it, while a bank one basis
    point below falls to the adequately capitalized tier's 11000 — a 3,750,000-cent difference
    on identical balances.

    PRD: "From the capital ratio the service derives `capital_tier` immediately, with inclusive
    lower bounds: a ratio of at least 1000 basis points is `WELL_CAPITALIZED`, a ratio below that
    but at least 800 basis points is `ADEQUATELY_CAPITALIZED`, and anything below 800 basis
    points is `UNDERCAPITALIZED`."
    PRD: "Step one reads the depository's capital tier from `capital_ratio_bps` using the
    inclusive lower bounds already described, and converts the tier into a base percentage: a
    `WELL_CAPITALIZED` depository requires 10500 basis points of the uninsured balance, an
    `ADEQUATELY_CAPITALIZED` one requires 11000, and an `UNDERCAPITALIZED` one requires 12500."

    Design: Difficulty/boundary_precision_check/capital_ratio_exactly_at_well_capitalized_floor
    """
    accounts = _three_banks_astride_the_capital_floor(client)

    below = accounts["below"]
    assert below["required_collateral_pct_bps"] == 11000
    assert below["required_collateral_cents"] == 82_500_000

    at_floor = accounts["at"]
    assert at_floor["required_collateral_pct_bps"] == 10500
    assert at_floor["required_collateral_cents"] == 78_750_000

    above = accounts["above"]
    assert above["required_collateral_pct_bps"] == 10500
    assert above["required_collateral_cents"] == 78_750_000

    assert (
        below["required_collateral_cents"] - at_floor["required_collateral_cents"]
        == 3_750_000
    )


def test_the_three_banks_agree_on_everything_except_the_tier(client):
    """Because three depositories are three separate insurance groups, every one of the three
    accounts insures the same 25,000,000 cents and leaves the same 75,000,000 uninsured, and all
    three sit uncollateralised at a zero coverage ratio.

    PRD: "Under `AGGREGATED_BY_UNIT`, the default, one single coverage bucket of 25,000,000 cents
    is shared by the whole insurance group and consumed in ascending `group_sequence` order."
    PRD: "Accounts of another deposit class, another depository or another public unit never
    share coverage."
    PRD: "`UNSECURED → DEFICIENT` when `assigned_collateral_value_cents` is greater than zero and
    the ratio is below 10000."

    Design: Difficulty/boundary_precision_check/capital_ratio_exactly_at_well_capitalized_floor
    """
    accounts = _three_banks_astride_the_capital_floor(client)

    for label in ("below", "at", "above"):
        account = get_success_data(
            client.get_deposit_account(accounts[label]["id"], OFFICER), 200
        )
        assert account["insured_amount_cents"] == 25_000_000
        assert account["uninsured_amount_cents"] == 75_000_000
        assert account["assigned_collateral_value_cents"] == 0
        assert account["coverage_ratio_bps"] == 0
        assert account["collateral_status"] == "UNSECURED"
        assertions.assert_insured_plus_uninsured_reconciles(account)
        assertions.assert_deposit_account(account)


def _two_pledges_a_cent_apart(client):
    """One county holding a demand account and a time-and-savings account at the same bank —
    separate insurance groups, so each owes 78,750,000 cents — each covered by its own executed
    agreement and its own treasury, the two pars differing by a single cent."""
    fixtures.set_clock(client)
    custodian = fixtures.create_approved_custodian(client)
    public_unit = fixtures.create_public_unit(client)
    depository = fixtures.create_approved_depository(client, capital_ratio_bps=1200)

    built = {"public_unit_id": public_unit["id"], "depository_id": depository["id"]}
    for label, deposit_class, par in (
        ("at", "DEMAND", 80_357_143),
        ("below", "TIME_AND_SAVINGS", 80_357_142),
    ):
        account = fixtures.create_funded_account(
            client,
            depository["id"],
            public_unit["id"],
            100_000_000,
            deposit_class=deposit_class,
        )
        agreement = fixtures.create_executed_dedicated_agreement(
            client,
            depository["id"],
            custodian["id"],
            account["id"],
            public_unit["id"],
        )
        asset = fixtures.create_collateral_asset(
            client,
            depository["id"],
            custodian["id"],
            asset_type="US_TREASURY",
            par_value_cents=par,
            market_price_bps=10000,
        )
        built[label] = {
            "account_id": account["id"],
            "allocation": fixtures.create_allocation(
                client, agreement["id"], asset["id"], par
            ),
        }
    return built


def test_a_coverage_ratio_of_exactly_ten_thousand_secures_the_account(client):
    """Par of 80,357,143 cents haircuts to exactly 78,750,000, matching the requirement to the
    cent, and because the secured side of the cut is inclusive the account is SECURED at exactly
    10000 basis points.

    PRD: "Coverage is measured by `coverage_ratio_bps`."
    PRD: "The service recomputes this dimension after every operation that can disturb either
    side of the ratio: creating a pledge allocation, releasing a pledge allocation, posting a new
    market price, crediting a deposit, debiting a withdrawal, settling a substitution, and curing
    a margin call, and equally after the allocation releases that agreement termination and asset
    ineligibility cascade into."
    PRD: "`UNSECURED → SECURED` when the recomputed `coverage_ratio_bps` is at least 10000."

    Design: Difficulty/boundary_precision_check/coverage_ratio_exactly_10000_secures_account
    """
    built = _two_pledges_a_cent_apart(client)

    assert built["at"]["allocation"]["allocated_collateral_value_cents"] == 78_750_000

    account = get_success_data(
        client.get_deposit_account(built["at"]["account_id"], OFFICER), 200
    )
    assert account["required_collateral_cents"] == 78_750_000
    assert account["assigned_collateral_value_cents"] == 78_750_000
    assert account["coverage_ratio_bps"] == 10000
    assert account["collateral_status"] == "SECURED"
    assertions.assert_coverage_ratio_floored(account)


def test_one_cent_less_of_par_floors_the_ratio_to_9999(client):
    """A single cent less of par values at 78,749,999, and because the ratio is floored rather
    than rounded it reports 9999 instead of 10000, so that account is DEFICIENT, its unit drops
    onto WATCH, and the bank's pledged total is the sum of the two already-rounded values —
    157,499,999, not 157,500,000.

    PRD: "**Floor to whole basis points** applies to the two derived ratios that measure adequacy:
    an account's `coverage_ratio_bps` and a run's `deficiency_ratio_bps`."
    PRD: "Aggregates are assembled by **summing the already-rounded per-allocation values**, never
    by re-deriving the total from unrounded par, price and haircut."
    PRD: "Each of these six transitions is followed by a recomputation of the owning public unit's
    `exposure_status`: a unit holding no restricted account drops to `WATCH` when one of its
    accounts is deficient, and its watch clears back to `NORMAL` only when none of its accounts is
    deficient and none is restricted."

    Design: Difficulty/boundary_precision_check/coverage_ratio_exactly_10000_secures_account
    """
    built = _two_pledges_a_cent_apart(client)

    assert built["below"]["allocation"]["allocated_collateral_value_cents"] == 78_749_999

    account = get_success_data(
        client.get_deposit_account(built["below"]["account_id"], OFFICER), 200
    )
    assert account["assigned_collateral_value_cents"] == 78_749_999
    assert account["coverage_ratio_bps"] == 9999
    assert account["collateral_status"] == "DEFICIENT"
    assertions.assert_coverage_ratio_floored(account)

    unit = get_success_data(client.get_public_unit(built["public_unit_id"], REGULATOR), 200)
    assert unit["exposure_status"] == "WATCH"

    depository = get_success_data(
        client.get_depository(built["depository_id"], REGULATOR), 200
    )
    assert depository["total_pledged_collateral_value_cents"] == 157_499_999
    assert depository["total_pledged_par_cents"] == 160_714_285
