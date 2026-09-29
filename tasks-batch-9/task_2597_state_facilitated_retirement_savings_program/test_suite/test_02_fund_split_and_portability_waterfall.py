"""
Two multi-stage formulas whose stages are not independent of one another.

The fund-level split of an account balance rounds every holding but the last and
hands the last one the arithmetic remainder, so the holdings always sum to the
balance to the cent. The portability money figures are a five-stage waterfall in
which each stage consumes the previous one's output, and the fee tier is read
from the gross amount before anything has been taken out of it.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    ADMIN,
    FUND_EQIDX1,
    FUND_MMKT01,
    FUND_TDF2045,
    build_active_saver_environment,
    build_funded_account_environment,
    find_row,
    fund_account_by_remittance,
    make_participant_headers,
    read_account,
    read_transfer,
    set_clock,
)


def _fund_balance(account, fund_code):
    """The cents the account holds in one named fund."""
    return find_row(account["fund_balances"], fund_code=fund_code)["balance_cents"]


def _build_odd_balance_account(api):
    """
    A three-fund menu and an account holding the odd sum of 100003 cents, which
    is what a 2000060-cent wage at the 500-basis-point default withholds exactly.
    """
    env = build_active_saver_environment(
        api, annual_compensation_cents=24000720,
        funds=[FUND_TDF2045, FUND_MMKT01, FUND_EQIDX1])
    fund_account_by_remittance(
        api, env, "2026-02-01", "2026-02-28", "2026-03-05",
        2000060, 100003, "2026-03-06T00:00:00Z",
        posting_reference="PR-2026-ODD1")
    env["account"] = read_account(api, env["account_id"])
    return env


def _reallocate_across_three_funds(api, env):
    """Move the odd balance onto a half / third / sixth split of the three funds."""
    return validate_success(api.create_investment_election(
        env["account_id"],
        {
            "allocations": [
                {"fund_code": "EQIDX1", "allocation_bp": 5000},
                {"fund_code": "TDF2045", "allocation_bp": 3333},
                {"fund_code": "MMKT01", "allocation_bp": 1667},
            ],
            "expected_account_version": env["account"]["version"],
        },
        make_participant_headers(env["participant_id"])), 201)


def _build_half_basis_account(api):
    """
    An account holding 1200000 cents of which exactly half is contribution basis,
    with the clock at 1 May 2026 and nothing restricting the account.
    """
    env = build_funded_account_environment(api, earnings_cents=600000)
    set_clock(api, "2026-05-01T00:00:00Z")
    return env


def _request_million_cent_indirect_rollover(api, env):
    """Ask for 1000000 cents to leave the account as a sixty-day indirect rollover."""
    return validate_success(api.create_portability_transfer(
        {
            "participant_id": env["participant_id"],
            "source_account_id": env["account_id"],
            "destination_type": "EXTERNAL_IRA",
            "external_institution_name": "Northline Trust Company",
            "transfer_kind": "INDIRECT_60_DAY",
            "amount_cents": 1000000,
        },
        make_participant_headers(env["participant_id"])), 201)


def test_every_holding_but_the_last_is_rounded_from_its_own_weight(api):
    """The two heaviest holdings are each rounded half up from the balance.

    Ordered by weight descending, the equity index holds 5000 basis points of
    100003 cents, which is 50001.5 and rounds up to 50002, and the 2045 target
    fund holds 3333 basis points, which is 33330.9999 and rounds to 33331.

    "Order that election's allocation entries by allocation weight in basis
    points descending, and where two entries carry the same weight, by fund code
    ascending."

    "For every entry except the last in that order, the fund's balance is the
    account balance multiplied by the entry's weight in basis points, divided by
    10000, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/three_fund_split_last_holder_absorbs_remainder
    """
    env = _build_odd_balance_account(api)

    _reallocate_across_three_funds(api, env)

    account = read_account(api, env["account_id"])
    assert account["balance_cents"] == 100003
    assert _fund_balance(account, "EQIDX1") == 50002
    assert _fund_balance(account, "TDF2045") == 33331


def test_the_lightest_holding_absorbs_the_remainder_instead_of_rounding(api):
    """The last holding in weight order takes what is left, not its own product.

    Rounding the money-market holding on its own weight of 1667 basis points
    would give 16670.5 and therefore 16671 cents, putting the three holdings one
    cent above the account. Taking the remainder instead gives 16670 and the
    holdings sum to exactly 100003.

    "The last entry in the order does not get its own multiplication: it absorbs
    the remainder, taking the account balance minus the sum of all the balances
    already assigned."

    "Rounding each fund independently is a defect, not a simplification: it can
    produce a fund total one cent above the account balance."

    Design: Difficulty/combinatorial_formula/three_fund_split_last_holder_absorbs_remainder
    """
    env = _build_odd_balance_account(api)

    _reallocate_across_three_funds(api, env)

    account = read_account(api, env["account_id"])
    assert _fund_balance(account, "MMKT01") == 16670
    assert _fund_balance(account, "MMKT01") != 16671
    total = sum(entry["balance_cents"] for entry in account["fund_balances"])
    assert total == 100003
    assert total == account["balance_cents"]


def test_the_savers_choice_supersedes_the_automatic_default_election(api):
    """The election the batch chose is retired, not deleted, and the account moves on.

    The account's history holds two elections: the single-fund default the
    auto-enrolment batch seeded on the glide path, now retired, and the saver's
    own three-fund choice, now governing. The account's version has advanced by
    exactly one from the value the request was composed against.

    "On success the account's previously active election moves from `ACTIVE` to
    `SUPERSEDED` with `superseded_at` stamped from the clock — that stamp is an
    exclusive upper bound on the old election's effectivity window, and, as §3.6
    explains, it is also the signal that steers net-income-attributable
    arithmetic onto its deemed-rate variant."

    Design: Difficulty/combinatorial_formula/three_fund_split_last_holder_absorbs_remainder
    """
    env = _build_odd_balance_account(api)
    version_before = env["account"]["version"]

    election = _reallocate_across_three_funds(api, env)

    assert election["status"] == "ACTIVE"
    assert election["source"] == "PARTICIPANT_ELECTED"

    rows, meta = validate_paginated(
        api.list_investment_elections(env["account_id"], ADMIN))
    assert meta["total_count"] == 2
    assert len([row for row in rows if row["status"] == "ACTIVE"]) == 1
    retired = find_row(rows, status="SUPERSEDED")
    assert retired["source"] == "SYSTEM_DEFAULT"
    assert retired["selection_basis"] == "TARGET_DATE_GLIDE_PATH"

    account = read_account(api, env["account_id"])
    assert account["version"] == version_before + 1
    assert account["active_election_id"] == election["id"]


def test_the_transfer_fee_tier_is_read_from_the_gross_amount(api):
    """A million-cent rollover pays the top tier because the tier reads the gross.

    The gross amount of 1000000 cents sits above the 950000-cent boundary, so the
    highest band of 60 basis points applies and the fee is 6000 cents. Reading the
    tier from the 950000 cents that remain once withholding is taken out would
    have charged only 50 basis points, or 4750 cents.

    "First, the fee tier is keyed on the **gross** `amount_cents` and never on any
    net figure: a gross amount of 500000 cents or less charges 40 basis points;
    from 500001 through 950000 cents inclusive charges 50 basis points; 950001
    cents or more charges 60 basis points."

    Design: Difficulty/combinatorial_formula/portability_waterfall_fee_tier_keyed_on_gross_not_net
    """
    env = _build_half_basis_account(api)

    transfer = _request_million_cent_indirect_rollover(api, env)

    assert transfer["fee_cents"] == 6000
    assert transfer["fee_cents"] != 4750


def test_basis_taxable_withholding_and_net_follow_in_that_order(api):
    """Each later figure is built from the earlier ones, ending on 944000 cents.

    Exactly half of the 1200000-cent balance is contribution basis, so the basis
    portion of a 1000000-cent gross movement is 500000 cents, the taxable part is
    the other 500000, the mandatory ten-percent withholding on that is 50000, and
    the net proceeds are the gross less the 6000-cent fee and that withholding.

    "Second, `basis_portion_cents` is the gross amount multiplied by the source
    account's pre-debit `contribution_basis_cents`, divided by the source
    account's pre-debit `balance_cents`, rounded half up."

    "Keying the fee tier on a post-withholding figure is the classic error this
    ordering exists to prevent: a gross indirect rollover of 1000000 cents has
    50000 cents withheld, and treating the remaining 950000 as the tier key drops
    it into the 50-basis-point band instead of the 60-basis-point band,
    understating the fee and overstating the net proceeds by 1250 cents."

    Design: Difficulty/combinatorial_formula/portability_waterfall_fee_tier_keyed_on_gross_not_net
    """
    env = _build_half_basis_account(api)

    created = _request_million_cent_indirect_rollover(api, env)

    transfer = read_transfer(api, created["id"])
    assert transfer["basis_portion_cents"] == 500000
    assert transfer["taxable_cents"] == 500000
    assert transfer["withholding_cents"] == 50000
    assert transfer["net_cents"] == 944000
    assert transfer["net_cents"] != 945250


def test_the_in_flight_rollover_debits_and_restricts_the_source_account(api):
    """The gross leaves the account at once and the account is held while it flies.

    The whole 1000000 cents of gross is parked in the in-transit leg, the account
    drops to 200000 cents with 100000 cents of basis left, the sixty-day clock
    lands on 30 June 2026, and the account is restricted until the movement ends.

    "On acceptance the transfer is created in status `REQUESTED`,
    `in_transit_cents` is set to the gross `amount_cents` — the in-flight leg that
    keeps programme cash conserved — `requested_on` is set to the clock's date,
    and `settle_by_date` is set to `requested_on` plus 60 days for an
    `INDIRECT_60_DAY` transfer and to null for the other kinds."

    Design: Difficulty/combinatorial_formula/portability_waterfall_fee_tier_keyed_on_gross_not_net
    """
    env = _build_half_basis_account(api)

    transfer = _request_million_cent_indirect_rollover(api, env)

    assert transfer["status"] == "REQUESTED"
    assert transfer["in_transit_cents"] == 1000000
    assert transfer["requested_on"] == "2026-05-01"
    assert transfer["settle_by_date"] == "2026-06-30"

    account = read_account(api, env["account_id"])
    assert account["balance_cents"] == 200000
    assert account["contribution_basis_cents"] == 100000
    assert account["posture"] == "RESTRICTED"
