"""Consistency model: the deposit's own response already carries every derived rollup it caused."""

from test_helpers import fixtures, get_success_data
from test_helpers.fixtures import REGULATOR
from test_helpers.test_users import make_public_unit_treasurer_headers


def test_a_deposit_publishes_its_whole_derivation_inside_its_own_response(client):
    """The service is immediately consistent: the 200 that acknowledges a deposit already shows the
    written account's insurance split, percentage and requirement, and the very next reads show the
    sibling account, the unit and the bank re-derived — no polling and no sweep in between.

    PRD: "Whenever a balance moves, the service re-derives the whole dependent chain in a fixed order.
    First the deposited or withdrawn amount is added to or subtracted from `ledger_balance_cents`.
    Second, **insured-amount determination** is re-run for every member of the touched account's
    insurance group, in ascending `group_sequence` order, where group membership means an account of
    that same triple whose `funding_status` is `PENDING_FUNDING`, `FUNDED` or `RESTRICTED`. Accounts
    of another deposit class, another depository or another public unit never share coverage. Third,
    each touched account's required percentage and requirement are re-derived. Fourth, the account's
    assigned collateral value is re-derived — for a `DEDICATED` account from its own agreements'
    allocations, for a `POOLED` account by re-running the pool waterfall of §3.5. Fifth,
    `coverage_ratio_bps` and `collateral_status` are recomputed for every touched account. Sixth, the
    owning public unit's `total_deposit_balance_cents`, `total_uninsured_cents` and `exposure_status`
    are recomputed, along with the depository's `total_required_collateral_cents`. Finally the
    account's `version` is incremented."
    PRD: "- Under `AGGREGATED_BY_UNIT`, the default, one single coverage bucket of 25,000,000 cents is
    shared by the whole insurance group and consumed in ascending `group_sequence` order. Starting
    with the full bucket as the remaining coverage, each account in turn takes as its
    `insured_amount_cents` the lesser of the coverage still remaining and its own
    `ledger_balance_cents`; that amount is then deducted from the remaining coverage before the next
    account is considered. Later accounts in the group can therefore end up entirely uninsured."
    PRD: "At creation the service assigns `group_sequence`, a monotone integer beginning at 1 within
    the account's **insurance group**, which is the triple of `public_unit_id`, `depository_id` and
    `deposit_class`."
    PRD: "Step one reads the depository's capital tier from `capital_ratio_bps` using the inclusive
    lower bounds already described, and converts the tier into a base percentage: a
    `WELL_CAPITALIZED` depository requires 10500 basis points of the uninsured balance, an
    `ADEQUATELY_CAPITALIZED` one requires 11000, and an `UNDERCAPITALIZED` one requires 12500."
    PRD: "The account's `required_collateral_cents` is then the uninsured amount scaled by that
    percentage — `uninsured_amount_cents` multiplied by `required_collateral_pct_bps`, divided by
    10000, rounded half up to whole cents."
    PRD: "Thereafter the unit's exposure is a strictly ordered read of its accounts: it is
    `ESCALATED` whenever any of its accounts has `funding_status` `RESTRICTED`; otherwise it is
    `WATCH` whenever any of its accounts has `collateral_status` `DEFICIENT`; otherwise it is
    `NORMAL`."
    PRD: "Coverage is measured by `coverage_ratio_bps`. When `required_collateral_cents` is zero the
    ratio is defined as 10000; otherwise it is `assigned_collateral_value_cents` multiplied by 10000,
    divided by `required_collateral_cents`, floored to whole basis points."

    Design: Corner/consistency_model/immediate_visibility_of_derived_rollups_in_the_deposit_response
    """
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client, name="Ridge County", unit_type="COUNTY")
    depository = fixtures.create_approved_depository(client, capital_ratio_bps=1200)
    assert depository["insurance_determination_basis"] == "AGGREGATED_BY_UNIT"
    treasurer = make_public_unit_treasurer_headers(public_unit["id"])

    first_account = fixtures.create_deposit_account(
        client, depository["id"], public_unit["id"]
    )
    second_account = fixtures.create_deposit_account(
        client, depository["id"], public_unit["id"]
    )
    assert first_account["group_sequence"] == 1
    assert second_account["group_sequence"] == 2

    prefunded = fixtures.deposit(
        client, second_account["id"], public_unit["id"], 10_000_000
    )
    assert prefunded["insured_amount_cents"] == 10_000_000
    assert prefunded["required_collateral_cents"] == 0
    sibling_version_before = prefunded["version"]
    first_version_before = fixtures.account_version(
        client, first_account["id"], treasurer
    )

    written = fixtures.deposit(
        client, first_account["id"], public_unit["id"], 100_000_000
    )
    assert written["ledger_balance_cents"] == 100_000_000
    assert written["insured_amount_cents"] == 25_000_000
    assert written["uninsured_amount_cents"] == 75_000_000
    assert written["required_collateral_pct_bps"] == 10500
    assert written["required_collateral_cents"] == 78_750_000
    assert written["assigned_collateral_value_cents"] == 0
    assert written["coverage_ratio_bps"] == 0
    assert written["collateral_status"] == "UNSECURED"
    assert written["funding_status"] == "FUNDED"
    assert written["version"] == first_version_before + 1

    sibling = get_success_data(
        client.get_deposit_account(second_account["id"], treasurer), 200
    )
    assert sibling["insured_amount_cents"] == 0
    assert sibling["uninsured_amount_cents"] == 10_000_000
    assert sibling["required_collateral_pct_bps"] == 10500
    assert sibling["required_collateral_cents"] == 10_500_000
    assert sibling["coverage_ratio_bps"] == 0
    assert sibling["collateral_status"] == "UNSECURED"
    assert sibling["version"] == sibling_version_before + 1

    unit = get_success_data(client.get_public_unit(public_unit["id"], REGULATOR), 200)
    assert unit["total_deposit_balance_cents"] == 110_000_000
    assert unit["total_uninsured_cents"] == 85_000_000
    assert unit["exposure_status"] == "NORMAL"

    bank = get_success_data(client.get_depository(depository["id"], REGULATOR), 200)
    assert bank["total_required_collateral_cents"] == 89_250_000
    assert bank["total_pledged_collateral_value_cents"] == 0
