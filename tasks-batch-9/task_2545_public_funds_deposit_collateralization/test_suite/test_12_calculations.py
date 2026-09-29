"""Derived arithmetic: custody reconciliation, the haircut constant table, two-step rounding,
running ledger aggregation, the shared insurance bucket, a tier threshold and cure accounting.
"""

from test_helpers import fixtures, get_success_data, validate_paginated
from test_helpers.constants import DEFAULT_CLOCK_UTC, clock_stamp
from test_helpers.fixtures import OFFICER, REGULATOR
from test_helpers.test_users import REGULATOR_USER_ID

SECOND_DAY = "2026-08-02T00:00:00Z"
SIX_HOURS_IN = "2026-08-01T06:00:00Z"


def _receipts_of(client, agreement_id):
    """Every safekeeping receipt issued under one agreement, oldest first."""
    receipts, meta = validate_paginated(
        client.list_agreement_safekeeping_receipts(agreement_id, REGULATOR)
    )
    return receipts, meta


def test_a_receipt_reconciles_against_the_ledger_at_the_instant_it_was_issued(client):
    """A receipt that matches the covering set confirms; a receipt issued after the pledge was
    released reports the whole 3,000,000-cent par as a positive discrepancy and lands in
    EXCEPTION; an honest zero-zero report against an agreement holding nothing confirms; and
    the first receipt is never retro-fitted to the later ledger.

    PRD: "Issuance stamps `as_of` from the logical clock and computes the ledger side of the
    reconciliation at that instant."
    PRD: "The covering set is the agreement's allocations that are `ACTIVE` **and** whose
    half-open effective interval covers `as_of`; allocations in `SUBSTITUTED` or `RELEASED`
    status are excluded even when their interval would cover it."
    PRD: "`discrepancy_par_cents` is then a **signed** figure: `reported_par_cents` less
    `ledger_par_cents`, negative when the custodian reports less than the bank's ledger
    claims."
    PRD: "When `discrepancy_par_cents` is zero **and** `reported_asset_count` equals
    `ledger_asset_count`, the receipt moves to `CONFIRMED`; when either the discrepancy is
    non-zero or the counts disagree, it moves to `EXCEPTION`."
    PRD: "Both outcomes stamp `confirmed_at` from the clock, record the confirming regulator's
    `X-User-ID` as `confirmed_by_user_id`, and increment the receipt's `version`."
    PRD: "Note the boundary case that follows from the empty-set rule: a receipt against an
    agreement holding no active allocations, reporting zero par and zero assets, **confirms** —
    it does not raise an exception."

    Design: Corner/calculations/correct_result_safekeeping_receipt_reconciles_to_ledger
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        par_value_cents=5_000_000,
        market_price_bps=10000,
    )
    allocation = fixtures.create_allocation(
        client, perimeter["agreement_id"], asset["id"], 3_000_000
    )

    matching = fixtures.issue_receipt(
        client,
        perimeter["agreement_id"],
        perimeter["custodian_id"],
        3_000_000,
        1,
        receipt_number="RCPT-1",
    )
    assert matching["as_of"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert matching["ledger_par_cents"] == 3_000_000
    assert matching["ledger_asset_count"] == 1
    assert matching["discrepancy_par_cents"] == 0
    assert matching["confirmation_status"] == "ISSUED"

    confirmed = fixtures.confirm_receipt(client, matching["id"])
    assert confirmed["confirmation_status"] == "CONFIRMED"
    assert confirmed["confirmed_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert confirmed["confirmed_by_user_id"] == REGULATOR_USER_ID

    fixtures.release_allocation(client, allocation["id"])

    overstated = fixtures.issue_receipt(
        client,
        perimeter["agreement_id"],
        perimeter["custodian_id"],
        3_000_000,
        1,
        receipt_number="RCPT-2",
    )
    assert overstated["ledger_par_cents"] == 0
    assert overstated["ledger_asset_count"] == 0
    assert overstated["discrepancy_par_cents"] == 3_000_000

    exception = fixtures.confirm_receipt(client, overstated["id"])
    assert exception["confirmation_status"] == "EXCEPTION"

    honest = fixtures.issue_receipt(
        client,
        perimeter["agreement_id"],
        perimeter["custodian_id"],
        0,
        0,
        receipt_number="RCPT-3",
    )
    assert honest["ledger_par_cents"] == 0
    assert honest["ledger_asset_count"] == 0
    assert honest["discrepancy_par_cents"] == 0
    assert fixtures.confirm_receipt(client, honest["id"])["confirmation_status"] == "CONFIRMED"

    receipts, meta = _receipts_of(client, perimeter["agreement_id"])
    assert meta["total_count"] == 3
    assert [receipt["confirmation_status"] for receipt in receipts] == [
        "CONFIRMED",
        "EXCEPTION",
        "CONFIRMED",
    ]
    assert receipts[0]["ledger_par_cents"] == 3_000_000


def test_an_allocation_whose_interval_has_elapsed_is_outside_the_covering_set(client):
    """An allocation that nothing released but whose half-open interval ended exactly at the
    receipt's as_of contributes no par and no asset count, because the closing bound is
    exclusive — so the custodian's honest-looking 3,000,000-cent report is an exception while a
    zero-zero report confirms.

    PRD: "The covering set is the agreement's allocations that are `ACTIVE` **and** whose
    half-open effective interval covers `as_of`; allocations in `SUBSTITUTED` or `RELEASED`
    status are excluded even when their interval would cover it."
    PRD: "Where the covering set is empty the arithmetic still applies rather than erroring:
    `ledger_par_cents` is zero and `ledger_asset_count` is zero, not null."
    PRD: "An asset's `pledged_par_cents` is the sum of `allocated_par_cents` over its `ACTIVE`
    allocations whose effective interval covers the current logical clock, meaning the
    allocation's `effective_from` is at or before the clock and its `effective_to` is strictly
    after it."
    PRD: "Concretely: an agreement's `total_collateral_value_cents` is the sum of
    `allocated_collateral_value_cents` over its allocations that are `ACTIVE` and whose asset
    is `ELIGIBLE`; its `total_pledged_par_cents` is the sum of `allocated_par_cents` over all
    of its `ACTIVE` allocations, whether or not the underlying asset is still eligible; and its
    `active_allocation_count` is the number of its allocations in `ACTIVE` status."

    Design: Corner/calculations/input_set_filtering_expired_interval_allocation_excluded_from_receipt
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        par_value_cents=5_000_000,
        market_price_bps=10000,
    )
    allocation = fixtures.create_allocation(
        client,
        perimeter["agreement_id"],
        asset["id"],
        3_000_000,
        effective_from=DEFAULT_CLOCK_UTC,
        effective_to=SECOND_DAY,
    )

    fixtures.set_clock(client, SECOND_DAY)

    still_active = get_success_data(
        client.get_pledge_allocation(allocation["id"], OFFICER), 200
    )
    assert still_active["status"] == "ACTIVE"
    assert still_active["released_at"] is None

    stale_report = fixtures.issue_receipt(
        client,
        perimeter["agreement_id"],
        perimeter["custodian_id"],
        3_000_000,
        1,
        receipt_number="RCPT-1",
    )
    assert stale_report["as_of"] == clock_stamp(SECOND_DAY)
    assert stale_report["ledger_par_cents"] == 0
    assert stale_report["ledger_asset_count"] == 0
    assert stale_report["discrepancy_par_cents"] == 3_000_000
    assert (
        fixtures.confirm_receipt(client, stale_report["id"])["confirmation_status"]
        == "EXCEPTION"
    )

    honest_report = fixtures.issue_receipt(
        client,
        perimeter["agreement_id"],
        perimeter["custodian_id"],
        0,
        0,
        receipt_number="RCPT-2",
    )
    assert honest_report["ledger_par_cents"] == 0
    assert honest_report["discrepancy_par_cents"] == 0
    assert (
        fixtures.confirm_receipt(client, honest_report["id"])["confirmation_status"]
        == "CONFIRMED"
    )

    elapsed_asset = get_success_data(client.get_collateral_asset(asset["id"], OFFICER), 200)
    assert elapsed_asset["pledged_par_cents"] == 0
    assert elapsed_asset["available_par_cents"] == 5_000_000

    agreement = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert agreement["total_pledged_par_cents"] == 3_000_000


HAIRCUT_MATRIX = [
    ("US_TREASURY", 200, 980_000),
    ("AGENCY_DEBENTURE", 300, 970_000),
    ("AGENCY_MBS", 800, 920_000),
    ("MUNI_GO", 1000, 900_000),
    ("MUNI_REVENUE", 1500, 850_000),
    ("LETTER_OF_CREDIT", 0, 1_000_000),
]


def test_every_asset_type_carries_its_own_haircut_at_the_same_par_and_price(client):
    """Registered at an identical 1,000,000 cents of par priced exactly at par, the six asset
    types produce six different collateral values straight from the haircut table — including
    the zero-haircut letter of credit, which keeps its whole market value, and the revenue bond,
    which is registrable and valued even though it may never be pledged.

    PRD: "`haircut_bps` is derived at registration from the asset type and is never supplied by
    a client: a `US_TREASURY` carries 200 basis points, an `AGENCY_DEBENTURE` 300, an
    `AGENCY_MBS` 800, a `MUNI_GO` 1000, a `MUNI_REVENUE` 1500, and a `LETTER_OF_CREDIT` none at
    all."
    PRD: "For the asset as a whole, `market_value_cents` is `par_value_cents` multiplied by
    `market_price_bps`, divided by 10000, rounded half up to whole cents; then
    `collateral_value_cents` is that market value multiplied by the quantity 10000 minus
    `haircut_bps`, divided by 10000, again rounded half up to whole cents."
    PRD: "A newly registered asset has `priced_at` stamped from the logical clock,
    `pledged_par_cents` at zero, `available_par_cents` equal to its full `par_value_cents`,
    `eligibility_status` `ELIGIBLE`, `pledge_status` `UNPLEDGED` and `ineligible_reason` null,
    with its two value mirrors computed as described below."
    PRD: "A depository's `total_pledged_collateral_value_cents` is the sum of
    `total_collateral_value_cents` over its agreements in `EXECUTED` status."

    Design: Corner/calculations/constants_applied_haircut_matrix_across_all_six_asset_types
    """
    fixtures.set_clock(client)
    custodian = fixtures.create_approved_custodian(client)
    depository = fixtures.create_approved_depository(client)

    for asset_type, haircut_bps, collateral_value_cents in HAIRCUT_MATRIX:
        asset = fixtures.create_collateral_asset(
            client,
            depository["id"],
            custodian["id"],
            asset_type=asset_type,
            par_value_cents=1_000_000,
            market_price_bps=10000,
        )
        assert asset["asset_type"] == asset_type
        assert asset["haircut_bps"] == haircut_bps
        assert asset["market_value_cents"] == 1_000_000
        assert asset["collateral_value_cents"] == collateral_value_cents
        assert asset["eligibility_status"] == "ELIGIBLE"
        assert asset["pledged_par_cents"] == 0
        assert asset["available_par_cents"] == 1_000_000
        assert asset["priced_at"] == clock_stamp(DEFAULT_CLOCK_UTC)

    bank = get_success_data(client.get_depository(depository["id"], REGULATOR), 200)
    assert bank["total_pledged_collateral_value_cents"] == 0


def test_the_price_leg_rounds_before_the_haircut_and_each_slice_rounds_alone(client):
    """Par 12,345 at 9999 basis points must round the price leg to 12,344 before the haircut is
    applied, giving 12,097 cents of collateral value; splitting the same par into slices of
    6,172 and 6,173 rounds each slice separately to 6,048 and 6,049, whose sum reproduces
    exactly the same 12,097.

    PRD: "For the asset as a whole, `market_value_cents` is `par_value_cents` multiplied by
    `market_price_bps`, divided by 10000, rounded half up to whole cents; then
    `collateral_value_cents` is that market value multiplied by the quantity 10000 minus
    `haircut_bps`, divided by 10000, again rounded half up to whole cents."
    PRD: "For an individual allocation, the same two steps run against the pledged slice rather
    than the full par: the allocation's market value is `allocated_par_cents` multiplied by the
    asset's `market_price_bps`, divided by 10000, rounded half up; then
    `allocated_collateral_value_cents` is that figure multiplied by 10000 minus the asset's
    `haircut_bps`, divided by 10000, rounded half up."
    PRD: "Aggregates are assembled by **summing the already-rounded per-allocation values**,
    never by re-deriving the total from unrounded par, price and haircut."
    PRD: "When `required_collateral_cents` is zero the ratio is defined as 10000; otherwise it
    is `assigned_collateral_value_cents` multiplied by 10000, divided by
    `required_collateral_cents`, floored to whole basis points."

    Design: Corner/calculations/precision_two_step_round_half_up_then_per_allocation_sum
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        par_value_cents=12_345,
        market_price_bps=9999,
    )
    assert asset["market_value_cents"] == 12_344
    assert asset["collateral_value_cents"] == 12_097

    first_slice = fixtures.create_allocation(
        client, perimeter["agreement_id"], asset["id"], 6_172
    )
    second_slice = fixtures.create_allocation(
        client, perimeter["agreement_id"], asset["id"], 6_173
    )
    assert first_slice["allocated_collateral_value_cents"] == 6_048
    assert second_slice["allocated_collateral_value_cents"] == 6_049

    agreement = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert agreement["total_collateral_value_cents"] == 12_097
    assert agreement["total_collateral_value_cents"] == 6_048 + 6_049

    pledged = get_success_data(client.get_collateral_asset(asset["id"], OFFICER), 200)
    assert pledged["pledged_par_cents"] == 12_345
    assert pledged["available_par_cents"] == 0
    assert pledged["pledge_status"] == "FULLY_PLEDGED"

    account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert account["assigned_collateral_value_cents"] == 12_097
    assert account["coverage_ratio_bps"] == 1
    assert account["collateral_status"] == "DEFICIENT"


def test_the_requirement_is_recomputed_from_the_running_balance_after_every_move(client):
    """Depositing 100,000,000 cents and then withdrawing 40,000,000 and the remaining
    60,000,000 re-derives the whole chain from the balance each time — 78,750,000 then
    36,750,000 then nothing — and the drained account keeps its tier percentage, keeps FUNDED,
    and reads a vacuous 10000 basis points of coverage.

    PRD: "Whenever a balance moves, the service re-derives the whole dependent chain in a fixed
    order."
    PRD: "Starting with the full bucket as the remaining coverage, each account in turn takes as
    its `insured_amount_cents` the lesser of the coverage still remaining and its own
    `ledger_balance_cents`; that amount is then deducted from the remaining coverage before the
    next account is considered."
    PRD: "The account's `required_collateral_cents` is then the uninsured amount scaled by that
    percentage — `uninsured_amount_cents` multiplied by `required_collateral_pct_bps`, divided
    by 10000, rounded half up to whole cents."
    PRD: "Draining an account to zero does *not* return it to `PENDING_FUNDING`:
    `funding_status` stays `FUNDED`."
    PRD: "When `required_collateral_cents` is zero the ratio is defined as 10000; otherwise it
    is `assigned_collateral_value_cents` multiplied by 10000, divided by
    `required_collateral_cents`, floored to whole basis points."
    PRD: "- `UNSECURED → SECURED` when the recomputed `coverage_ratio_bps` is at least 10000."

    Design: Corner/calculations/aggregation_running_total_after_deposit_then_withdrawals
    """
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client, unit_type="COUNTY")
    depository = fixtures.create_approved_depository(
        client, capital_ratio_bps=1200, insurance_determination_basis="AGGREGATED_BY_UNIT"
    )
    account = fixtures.create_deposit_account(
        client,
        depository["id"],
        public_unit["id"],
        deposit_class="DEMAND",
        pledging_mode="DEDICATED",
    )
    assert account["version"] == 1

    funded = fixtures.deposit(client, account["id"], public_unit["id"], 100_000_000)
    assert funded["ledger_balance_cents"] == 100_000_000
    assert funded["insured_amount_cents"] == 25_000_000
    assert funded["uninsured_amount_cents"] == 75_000_000
    assert funded["required_collateral_pct_bps"] == 10500
    assert funded["required_collateral_cents"] == 78_750_000
    assert funded["assigned_collateral_value_cents"] == 0
    assert funded["coverage_ratio_bps"] == 0
    assert funded["collateral_status"] == "UNSECURED"
    assert funded["funding_status"] == "FUNDED"
    assert funded["version"] == 2

    partly_drawn = fixtures.withdraw(client, account["id"], public_unit["id"], 40_000_000)
    assert partly_drawn["ledger_balance_cents"] == 60_000_000
    assert partly_drawn["insured_amount_cents"] == 25_000_000
    assert partly_drawn["uninsured_amount_cents"] == 35_000_000
    assert partly_drawn["required_collateral_cents"] == 36_750_000
    assert partly_drawn["funding_status"] == "FUNDED"
    assert partly_drawn["version"] == 3

    emptied = fixtures.withdraw(client, account["id"], public_unit["id"], 60_000_000)
    assert emptied["ledger_balance_cents"] == 0
    assert emptied["insured_amount_cents"] == 0
    assert emptied["uninsured_amount_cents"] == 0
    assert emptied["required_collateral_pct_bps"] == 10500
    assert emptied["required_collateral_cents"] == 0
    assert emptied["coverage_ratio_bps"] == 10000
    assert emptied["collateral_status"] == "SECURED"
    assert emptied["funding_status"] == "FUNDED"
    assert emptied["version"] == 4

    unit = get_success_data(client.get_public_unit(public_unit["id"], REGULATOR), 200)
    assert unit["total_deposit_balance_cents"] == 0
    assert unit["total_uninsured_cents"] == 0
    assert unit["exposure_status"] == "NORMAL"

    bank = get_success_data(client.get_depository(depository["id"], REGULATOR), 200)
    assert bank["total_required_collateral_cents"] == 0


def test_the_shared_insurance_bucket_is_consumed_by_group_sequence_not_by_funding_order(
    client,
):
    """Funding the second-opened account first insures it only until the first-opened account is
    funded: the 25,000,000-cent bucket is consumed in group_sequence order, so the sibling
    deposit retroactively strips account two's insurance and hands it a 10,500,000-cent
    requirement it never had.

    PRD: "At creation the service assigns `group_sequence`, a monotone integer beginning at 1
    within the account's **insurance group**, which is the triple of `public_unit_id`,
    `depository_id` and `deposit_class`."
    PRD: "Second, **insured-amount determination** is re-run for every member of the touched
    account's insurance group, in ascending `group_sequence` order, where group membership means
    an account of that same triple whose `funding_status` is `PENDING_FUNDING`, `FUNDED` or
    `RESTRICTED`."
    PRD: "Starting with the full bucket as the remaining coverage, each account in turn takes as
    its `insured_amount_cents` the lesser of the coverage still remaining and its own
    `ledger_balance_cents`; that amount is then deducted from the remaining coverage before the
    next account is considered."
    PRD: "In both variants an account's `uninsured_amount_cents` is its `ledger_balance_cents`
    less its `insured_amount_cents`, so the two parts always sum back to the ledger balance
    exactly."

    Design: Corner/calculations/waterfall_insured_bucket_follows_group_sequence_not_funding_order
    """
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client, unit_type="COUNTY")
    depository = fixtures.create_approved_depository(
        client, capital_ratio_bps=1200, insurance_determination_basis="AGGREGATED_BY_UNIT"
    )
    first_account = fixtures.create_deposit_account(
        client,
        depository["id"],
        public_unit["id"],
        deposit_class="DEMAND",
        pledging_mode="DEDICATED",
    )
    second_account = fixtures.create_deposit_account(
        client,
        depository["id"],
        public_unit["id"],
        deposit_class="DEMAND",
        pledging_mode="DEDICATED",
    )
    assert first_account["group_sequence"] == 1
    assert second_account["group_sequence"] == 2

    junior = fixtures.deposit(client, second_account["id"], public_unit["id"], 10_000_000)
    assert junior["insured_amount_cents"] == 10_000_000
    assert junior["uninsured_amount_cents"] == 0
    assert junior["required_collateral_cents"] == 0
    assert junior["coverage_ratio_bps"] == 10000
    junior_version = junior["version"]

    senior_unfunded = get_success_data(
        client.get_deposit_account(first_account["id"], OFFICER), 200
    )
    assert senior_unfunded["insured_amount_cents"] == 0

    senior = fixtures.deposit(client, first_account["id"], public_unit["id"], 100_000_000)
    assert senior["insured_amount_cents"] == 25_000_000
    assert senior["uninsured_amount_cents"] == 75_000_000
    assert senior["required_collateral_cents"] == 78_750_000

    restated = get_success_data(
        client.get_deposit_account(second_account["id"], OFFICER), 200
    )
    assert restated["insured_amount_cents"] == 0
    assert restated["uninsured_amount_cents"] == 10_000_000
    assert restated["required_collateral_cents"] == 10_500_000
    assert restated["version"] > junior_version
    assert (
        restated["insured_amount_cents"] + restated["uninsured_amount_cents"]
        == restated["ledger_balance_cents"]
    )
    assert (
        senior["insured_amount_cents"] + senior["uninsured_amount_cents"]
        == senior["ledger_balance_cents"]
    )

    bank = get_success_data(client.get_depository(depository["id"], REGULATOR), 200)
    assert bank["total_required_collateral_cents"] == 89_250_000

    unit = get_success_data(client.get_public_unit(public_unit["id"], REGULATOR), 200)
    assert unit["total_deposit_balance_cents"] == 110_000_000
    assert unit["total_uninsured_cents"] == 85_000_000


def test_the_adequately_capitalized_floor_is_inclusive_at_eight_hundred_basis_points(client):
    """A bank at exactly 800 basis points of capital is ADEQUATELY_CAPITALIZED and requires
    11000 basis points — 82,500,000 cents — of the same 75,000,000-cent uninsured balance that a
    bank one basis point below the floor must cover at 12500 basis points, or 93,750,000 cents.

    PRD: "From the capital ratio the service derives `capital_tier` immediately, with inclusive
    lower bounds: a ratio of at least 1000 basis points is `WELL_CAPITALIZED`, a ratio below
    that but at least 800 basis points is `ADEQUATELY_CAPITALIZED`, and anything below 800 basis
    points is `UNDERCAPITALIZED`."
    PRD: "Step one reads the depository's capital tier from `capital_ratio_bps` using the
    inclusive lower bounds already described, and converts the tier into a base percentage: a
    `WELL_CAPITALIZED` depository requires 10500 basis points of the uninsured balance, an
    `ADEQUATELY_CAPITALIZED` one requires 11000, and an `UNDERCAPITALIZED` one requires 12500."
    PRD: "Step four combines the three additively and then applies a hard cap: the stored
    percentage is the lesser of 15000 basis points and the sum of the tier, mode and deficiency
    components."
    PRD: "Accounts of another deposit class, another depository or another public unit never
    share coverage."

    Design: Corner/calculations/threshold_capital_tier_at_and_just_below_adequately_capitalized_floor
    """
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client, unit_type="COUNTY")
    at_the_floor = fixtures.create_approved_depository(
        client, name="Floor Bank", capital_ratio_bps=800
    )
    below_the_floor = fixtures.create_approved_depository(
        client, name="Sub Floor Bank", capital_ratio_bps=799
    )
    assert at_the_floor["capital_tier"] == "ADEQUATELY_CAPITALIZED"
    assert below_the_floor["capital_tier"] == "UNDERCAPITALIZED"

    account_at_floor = fixtures.create_funded_account(
        client,
        at_the_floor["id"],
        public_unit["id"],
        100_000_000,
        deposit_class="DEMAND",
        pledging_mode="DEDICATED",
    )
    account_below_floor = fixtures.create_funded_account(
        client,
        below_the_floor["id"],
        public_unit["id"],
        100_000_000,
        deposit_class="DEMAND",
        pledging_mode="DEDICATED",
    )

    assert account_at_floor["insured_amount_cents"] == 25_000_000
    assert account_at_floor["uninsured_amount_cents"] == 75_000_000
    assert account_at_floor["required_collateral_pct_bps"] == 11000
    assert account_at_floor["required_collateral_cents"] == 82_500_000

    assert account_below_floor["insured_amount_cents"] == 25_000_000
    assert account_below_floor["uninsured_amount_cents"] == 75_000_000
    assert account_below_floor["required_collateral_pct_bps"] == 12500
    assert account_below_floor["required_collateral_cents"] == 93_750_000

    assert account_at_floor["required_collateral_pct_bps"] < 15000
    assert account_below_floor["required_collateral_pct_bps"] < 15000


def test_a_margin_call_is_cured_in_two_exact_instalments(client):
    """A 78,750,000-cent call issued by a fully uncovered supervisory run is cured with two
    letters of credit whose zero haircut makes the credited value equal the pledged par: the
    first instalment of 39,200,000 leaves the call PARTIALLY_CURED with 39,550,000 outstanding,
    and the second closes it to the cent, restoring the bank to COMPLIANT while leaving the risk
    grade the run wrote untouched.

    PRD: "Its `required_cure_cents` is frozen at issuance from the issuing run's
    `deficiency_cents` and never changes afterwards, however the market moves; `cured_cents`
    starts at zero and accumulates; `outstanding_cents` is always `required_cure_cents` less
    `cured_cents`, floored at zero."
    PRD: "Its `cure_deadline_at` is the run's `as_of` advanced by a number of hours that depends
    on how badly the bank is short: 24 hours when `deficiency_ratio_bps` is at least 2000,
    otherwise 48 hours when it is at least 500, and otherwise 120 hours, which is five full days
    for a trivial shortfall."
    PRD: "The credited value is the sum of the offered allocations' `allocated_collateral_value_cents`
    — the values already rounded per allocation, with no further rounding applied to the sum."
    PRD: "- A credit smaller than `outstanding_cents` carries an `ISSUED` call to
    `PARTIALLY_CURED`, and a `PARTIALLY_CURED` call self-loops in `PARTIALLY_CURED` — a call may
    be cured in arbitrarily many partial instalments for as long as `outstanding_cents` stays
    positive."
    PRD: "The depository's `open_margin_call_count` is then recounted as the number of its margin
    calls whose `status` is `ISSUED`, `PARTIALLY_CURED` or `ESCALATED`, and its
    `collateral_posture` is re-derived: `FROZEN` when `consecutive_deficiency_runs` stands at 3
    or more, otherwise `MARGIN_DEFICIENT` when at least one call is open, otherwise `COMPLIANT`."
    PRD: "Both the score and the grade are copied onto the depository as `risk_score_bps` and
    `risk_grade`, which is how a bank that lets its collateral rot eventually finds itself unable
    to open new deposit accounts at all."

    Design: Corner/calculations/correct_result_margin_call_partial_then_full_cure_accounting
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)

    run = fixtures.create_mtm_run(
        client,
        perimeter["depository_id"],
        "2026-07-31T00:00:00Z",
        DEFAULT_CLOCK_UTC,
        basis="SUPERVISORY",
    )
    assert run["as_of"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert run["outcome"] == "DEFICIENT"
    assert run["deficiency_cents"] == 78_750_000
    assert run["deficiency_ratio_bps"] == 10000
    assert run["coverage_component_bps"] == 0
    assert run["volatility_component_bps"] == 7500
    assert run["documentation_component_bps"] == 10000
    assert run["risk_score_bps"] == 4250
    assert run["risk_grade_assigned"] == "D"

    call = fixtures.latest_margin_call(client, perimeter["depository_id"])
    assert call["required_cure_cents"] == 78_750_000
    assert call["cured_cents"] == 0
    assert call["outstanding_cents"] == 78_750_000
    assert call["status"] == "ISSUED"
    assert call["cure_deadline_at"] == clock_stamp(SECOND_DAY)
    assert call["breach_deadline_at"] == clock_stamp("2026-08-03T00:00:00Z")

    issuing_bank = get_success_data(
        client.get_depository(perimeter["depository_id"], REGULATOR), 200
    )
    assert issuing_bank["consecutive_deficiency_runs"] == 1
    assert issuing_bank["open_margin_call_count"] == 1
    assert issuing_bank["collateral_posture"] == "MARGIN_DEFICIENT"
    assert issuing_bank["risk_score_bps"] == 4250
    assert issuing_bank["risk_grade"] == "D"

    fixtures.set_clock(client, SIX_HOURS_IN)
    first_letter = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="LETTER_OF_CREDIT",
        par_value_cents=39_200_000,
        market_price_bps=10000,
    )
    first_instalment = fixtures.create_allocation(
        client,
        perimeter["agreement_id"],
        first_letter["id"],
        39_200_000,
        effective_from=SIX_HOURS_IN,
    )
    assert first_instalment["allocated_collateral_value_cents"] == 39_200_000

    partly_cured = fixtures.cure_margin_call(
        client, call["id"], [first_instalment["id"]]
    )
    assert partly_cured["status"] == "PARTIALLY_CURED"
    assert partly_cured["cured_cents"] == 39_200_000
    assert partly_cured["outstanding_cents"] == 39_550_000
    assert partly_cured["cured_at"] is None

    midway_account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert midway_account["assigned_collateral_value_cents"] == 39_200_000
    assert midway_account["coverage_ratio_bps"] == 4977
    assert midway_account["collateral_status"] == "DEFICIENT"
    midway_unit = get_success_data(
        client.get_public_unit(perimeter["public_unit_id"], REGULATOR), 200
    )
    assert midway_unit["exposure_status"] == "WATCH"

    second_letter = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="LETTER_OF_CREDIT",
        par_value_cents=39_550_000,
        market_price_bps=10000,
    )
    second_instalment = fixtures.create_allocation(
        client,
        perimeter["agreement_id"],
        second_letter["id"],
        39_550_000,
        effective_from=SIX_HOURS_IN,
    )
    assert second_instalment["allocated_collateral_value_cents"] == 39_550_000

    cured = fixtures.cure_margin_call(client, call["id"], [second_instalment["id"]])
    assert cured["status"] == "CURED"
    assert cured["cured_cents"] == 78_750_000
    assert cured["outstanding_cents"] == 0
    assert cured["cured_at"] == clock_stamp(SIX_HOURS_IN)

    settled_bank = get_success_data(
        client.get_depository(perimeter["depository_id"], REGULATOR), 200
    )
    assert settled_bank["open_margin_call_count"] == 0
    assert settled_bank["collateral_posture"] == "COMPLIANT"
    assert settled_bank["consecutive_deficiency_runs"] == 1
    assert settled_bank["risk_score_bps"] == 4250
    assert settled_bank["risk_grade"] == "D"

    final_account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert final_account["assigned_collateral_value_cents"] == 78_750_000
    assert final_account["coverage_ratio_bps"] == 10000
    assert final_account["collateral_status"] == "SECURED"

    final_unit = get_success_data(
        client.get_public_unit(perimeter["public_unit_id"], REGULATOR), 200
    )
    assert final_unit["exposure_status"] == "NORMAL"
