"""Two-variant money arithmetic in the commuter benefit program.

This module covers the two places where the same stored inputs are deliberately
priced twice under two different rules, and where the observable answer differs:

* the pre-tax exclusion split of an election, run once under the elected basis
  when the election is filed and again under the funded basis when the election
  window locks; and
* the benefit-month close of a benefit account, which sends a byte-identical
  unused balance to completely different destinations depending on whether the
  account holder is still an active employee or has departed.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERROR_HTTP_STATUS  # installs the status map
from test_helpers.assertions import (
    assert_account_conservation,
    assert_exclusion_split,
    assert_ledger_matches_account,
    assert_ledger_sequence,
)
from test_helpers.constants import REGION_CHI, REGION_SFO
from test_helpers.test_users import PROGRAM_ADMIN

# =============================================================================
# Scenario builders.  Every test starts against an empty database, so each of
# these walks the documented endpoints from scratch.
# =============================================================================
VANPOOL_SPEC = {"category_type": "VANPOOL", "monthly_exclusion_limit_cents": 20000}
TRANSIT_PASS_SPEC = {
    "category_type": "TRANSIT_PASS",
    "monthly_exclusion_limit_cents": 32500,
}


def _build_two_category_transit_program(api):
    """One SFO employer sharing a 32500-cent transit group limit across a
    vanpool category and a transit-pass category, with one commuter holding a
    benefit account in each and an OPEN window for benefit month 2026-08."""
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[VANPOOL_SPEC, TRANSIT_PASS_SPEC],
        legal_name="Bay Transit Co",
        region_code=REGION_SFO,
        transit_group_limit_cents=32500,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
        pretax_ratio_cap_pct=100,
        spill_policy="SPILL_TO_POSTTAX",
    )
    employer = built["employer"]
    vanpool, transit_pass = built["categories"]
    employee = fx.make_employee(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        external_ref="EMP-001",
        work_region_code=REGION_SFO,
        hire_date="2026-01-15T00:00:00Z",
    )
    vanpool_account = fx.make_benefit_account(
        api, employee["id"], vanpool["id"], PROGRAM_ADMIN, opening_rollover_cents=0
    )
    transit_account = fx.make_benefit_account(
        api, employee["id"], transit_pass["id"], PROGRAM_ADMIN, opening_rollover_cents=0
    )
    window = fx.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-08",
        opens_at="2026-07-01T00:00:00Z",
        cutoff_at="2026-08-20T00:00:00Z",
        mid_month_change_allowed=False,
    )
    return {
        "employer": employer,
        "vanpool": vanpool,
        "transit_pass": transit_pass,
        "employee": employee,
        "vanpool_account": vanpool_account,
        "transit_account": transit_account,
        "window": window,
    }


def _file_election(api, scenario, category, account, pretax_amount_cents):
    """File one election with a freshly observed account version."""
    expected_version = fx.current_account_version(api, account["id"])
    payload = fac.election_payload(
        scenario["employee"]["id"],
        scenario["window"]["id"],
        category["id"],
        expected_version,
        pretax_amount_cents=pretax_amount_cents,
        posttax_amount_cents=0,
        media_quantity=0,
    )
    return validate_success(api.create_election(payload, PROGRAM_ADMIN), 201)


def _build_parking_close_program(
    api, termination_date="2026-08-05T00:00:00Z", opening_rollover_cents=12000
):
    """One CHI employer capping rollover at 5000 cents with a 30 whole-day
    forfeiture grace period, two commuters holding identically seeded parking
    accounts, and a LOCKED 2026-08 window.  One commuter is terminated on
    ``termination_date``; the other stays active."""
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[{"category_type": "PARKING", "monthly_exclusion_limit_cents": 30000}],
        legal_name="Lakeside Parking Benefits",
        region_code=REGION_CHI,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
        rollover_policy="CAP_ROLLOVER",
        rollover_cap_cents=5000,
        forfeiture_grace_days=30,
    )
    employer = built["employer"]
    parking = built["categories"][0]
    staying = fx.make_enrolled_employee(
        api,
        employer["id"],
        parking["id"],
        PROGRAM_ADMIN,
        account_overrides={"opening_rollover_cents": opening_rollover_cents},
        external_ref="EMP-ACT",
        work_region_code=REGION_CHI,
        hire_date="2026-01-05T00:00:00Z",
    )
    leaving = fx.make_enrolled_employee(
        api,
        employer["id"],
        parking["id"],
        PROGRAM_ADMIN,
        account_overrides={"opening_rollover_cents": opening_rollover_cents},
        external_ref="EMP-TRM",
        work_region_code=REGION_CHI,
        hire_date="2026-01-06T00:00:00Z",
    )
    window = fx.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-08",
        opens_at="2026-07-01T00:00:00Z",
        cutoff_at="2026-08-20T00:00:00Z",
    )
    window = get_success_data(api.lock_election_window(window["id"], PROGRAM_ADMIN))
    fx.set_clock(api, termination_date)
    leaver = fx.terminate(api, leaving["employee"]["id"], termination_date)
    return {
        "employer": employer,
        "parking": parking,
        "active_employee": staying["employee"],
        "active_account": staying["account"],
        "terminated_employee": leaver,
        "terminated_account": leaving["account"],
        "window": window,
    }


# =============================================================================
# The pre-tax exclusion split under its two bases
# =============================================================================
def test_01_transit_pass_exclusion_charged_against_a_live_vanpool_sibling(api):
    """Filing a transit-pass election behind a live vanpool election prices it
    under the elected basis: the vanpool election's 20000 cents has already
    eaten the shared 32500-cent transit group limit, so only 12500 of the
    18000-cent pre-tax request qualifies and the remaining 5500 spills.

    PRD §3.4: "Precisely, it sums `excluded_amount_cents` over every other election belonging to the same `employee_id` and the same `election_window_id` whose `benefit_category_id` differs from this election's and whose category sits in the same `limit_group`, restricted to the funding postures listed in the variant rule below."
    PRD §3.4: "Under the **elected basis** — which runs when an election is created and again on every amendment, and which sets `exclusion_basis` to `ELECTED_BASIS` — the prior-consumption sum includes sibling elections whose `funding_status` is `PENDING`, `HELD` or `FUNDED`."
    PRD §3.4: "`excluded_amount_cents` is then the smallest of those four values: the requested `pretax_amount_cents`, the group headroom, the category cap, and the ratio cap."
    PRD §3.4: "Whatever pre-tax the employee asked for beyond that becomes the overage: `posttax_spill_cents` is the requested `pretax_amount_cents` minus `excluded_amount_cents`."
    PRD §3.4: "Under `SPILL_TO_POSTTAX` the overage is simply reclassified, and `posttax_effective_cents` becomes the requested `posttax_amount_cents` plus `posttax_spill_cents`, so the employee's total deduction is unchanged and only its tax treatment shifts."

    Design: Difficulty/dual_variant_calc/election_exclusion_split_elected_vs_funded_basis_divergence
    """
    scenario = _build_two_category_transit_program(api)

    vanpool_election = _file_election(
        api, scenario, scenario["vanpool"], scenario["vanpool_account"], 20000
    )
    assert_exclusion_split(
        vanpool_election,
        excluded_amount_cents=20000,
        posttax_spill_cents=0,
        total_amount_cents=20000,
        exclusion_basis="ELECTED_BASIS",
    )

    transit_election = _file_election(
        api, scenario, scenario["transit_pass"], scenario["transit_account"], 18000
    )
    assert_exclusion_split(
        transit_election,
        excluded_amount_cents=12500,
        posttax_spill_cents=5500,
        total_amount_cents=18000,
        exclusion_basis="ELECTED_BASIS",
    )
    assert transit_election["posttax_effective_cents"] == 5500, (
        "the 5500-cent overage is reclassified as post-tax, got "
        f"{transit_election['posttax_effective_cents']}"
    )
    assert transit_election["funding_status"] == "PENDING"


def test_02_window_lock_reprices_transit_pass_after_the_vanpool_sibling_is_cancelled(api):
    """Cancelling the vanpool election releases the transit group headroom it
    was holding.  Locking the window then re-prices the untouched transit-pass
    election under the funded basis, and the stored 18000-cent pre-tax request
    goes from 12500 cents excluded to the full 18000 with no client action.

    PRD §3.4: "Under the **funded basis** — which runs at lock time and sets `exclusion_basis` to `FUNDED_BASIS` — the prior-consumption sum includes only siblings whose `funding_status` is exactly `FUNDED`."
    PRD §3.4: "The consequence is deliberate and worth stating plainly: a sibling election that was `PENDING` when this election was created but was cancelled or superseded before the lock releases its headroom, and this election's `excluded_amount_cents` therefore *increases* at lock time from exactly the same stored inputs, with no client action at all."
    PRD §3.4: "**The second level is caused by that window change**: every election in the window whose `funding_status` is `PENDING` is re-priced under the funded-basis variant, rewriting `excluded_amount_cents`, `posttax_spill_cents` and `posttax_effective_cents` and setting `exclusion_basis` to `FUNDED_BASIS`."
    PRD §3.4: "Each re-priced election then lands in one of two postures: `PENDING → HELD` when the electing employee's `substantiation_hold` is true, and `PENDING → FUNDED` otherwise."
    PRD §3.4: "One ledger entry is appended to that election's benefit account with `entry_type` `CONTRIBUTION`, a positive `amount_cents` equal to the election's `total_amount_cents`, `source_entity` `Election` and `source_id` the election's identifier; the account's `contributed_cents` increases by that same `total_amount_cents`, `available_balance_cents` is recomputed against the conservation identities, `ledger_entry_count` is incremented, and `BenefitAccount.version` advances by 1."

    Design: Difficulty/dual_variant_calc/election_exclusion_split_elected_vs_funded_basis_divergence
    """
    scenario = _build_two_category_transit_program(api)
    vanpool_election = _file_election(
        api, scenario, scenario["vanpool"], scenario["vanpool_account"], 20000
    )
    transit_election = _file_election(
        api, scenario, scenario["transit_pass"], scenario["transit_account"], 18000
    )
    assert transit_election["excluded_amount_cents"] == 12500, (
        "precondition: the elected basis must have charged the live vanpool sibling"
    )

    cancelled = validate_success(
        api.cancel_election(vanpool_election["id"], PROGRAM_ADMIN)
    )
    assert cancelled["funding_status"] == "CANCELLED"
    assert cancelled["excluded_amount_cents"] == 0

    locked = validate_success(
        api.lock_election_window(scenario["window"]["id"], PROGRAM_ADMIN)
    )
    assert locked["status"] == "LOCKED", f"window sits in {locked['status']}"

    repriced = fx.read_election(api, transit_election["id"])
    assert_exclusion_split(
        repriced,
        excluded_amount_cents=18000,
        posttax_spill_cents=0,
        total_amount_cents=18000,
        exclusion_basis="FUNDED_BASIS",
    )
    assert repriced["posttax_effective_cents"] == 0, (
        "no overage survives the funded basis, so nothing is reclassified"
    )
    assert repriced["funding_status"] == "FUNDED"
    assert (
        repriced["excluded_amount_cents"] - transit_election["excluded_amount_cents"]
        == 5500
    ), "the variant delta on identical stored inputs must be exactly 5500 cents"

    account = fx.read_account(api, scenario["transit_account"]["id"])
    assert account["contributed_cents"] == 18000
    assert account["available_balance_cents"] == 18000
    assert account["ledger_entry_count"] == 1
    assert_account_conservation(account)
    entries = fx.read_ledger(api, account["id"])
    assert_ledger_sequence(entries, [("CONTRIBUTION", 18000, 18000)])
    assert_ledger_matches_account(account, entries)

    cancelled_account = fx.read_account(api, scenario["vanpool_account"]["id"])
    assert cancelled_account["contributed_cents"] == 0, (
        "a cancelled election is never funded, so its account stays untouched"
    )


# =============================================================================
# The benefit-month close under its two employment branches
# =============================================================================
def test_03_standard_close_caps_the_carry_forward_and_forfeits_the_remainder(api):
    """An active commuter's 12000-cent unused parking balance meets a 5000-cent
    rollover cap: 5000 carries forward, the other 7000 is forfeited, and nothing
    at all goes back to the employer.

    PRD §3.8: "For each account, the unused amount is exactly its `available_balance_cents` at the close instant — the value the ledger conservation identities pin it to."
    PRD §3.8: "Under the **standard close**, which runs when the employee's `status` is `ACTIVE`, the carried-forward amount depends on the employer's `rollover_policy`: under `NO_ROLLOVER` nothing carries forward; under `FULL_ROLLOVER` the entire unused balance carries forward; and under `CAP_ROLLOVER` the carried-forward amount is the smaller of the unused balance and the employer's `rollover_cap_cents`."
    PRD §3.8: "Whatever does not carry forward is forfeited — the forfeiture amount is the unused balance minus the carried-forward amount — and nothing at all is refunded to the employer."
    PRD §3.8: "If the forfeiture amount is greater than zero, one entry is appended first with `entry_type` `FORFEITURE` and a negative `amount_cents` equal to that amount."
    PRD §3.8: "Two invariants make this checkable: after a standard close the account's `available_balance_cents` equals exactly the carried-forward amount, and after a termination close it equals exactly zero."

    Design: Difficulty/dual_variant_calc/month_close_standard_vs_termination_variant_bucket_split
    """
    scenario = _build_parking_close_program(api)
    fx.set_clock(api, "2026-08-20T00:00:00Z")

    validate_success(
        api.month_close_employer(
            scenario["employer"]["id"], {"benefit_month": "2026-08"}, PROGRAM_ADMIN
        )
    )

    account = fx.read_account(api, scenario["active_account"]["id"])
    assert account["forfeited_cents"] == 7000, (
        f"12000 unused minus a 5000 cap must forfeit 7000, got {account['forfeited_cents']}"
    )
    assert account["refunded_cents"] == 0, "a standard close refunds nothing"
    assert account["available_balance_cents"] == 5000, (
        "after a standard close the balance equals the carried-forward amount"
    )
    assert account["rollover_in_cents"] == 12000, (
        "rollover_in_cents is a lifetime bucket and a close never resets it"
    )
    assert account["ledger_entry_count"] == 2
    assert_account_conservation(account)

    entries = fx.read_ledger(api, account["id"])
    assert_ledger_sequence(
        entries, [("ROLLOVER_IN", 12000, 12000), ("FORFEITURE", -7000, 5000)]
    )
    assert_ledger_matches_account(account, entries)

    window = fx.read_window(api, scenario["window"]["id"])
    assert window["status"] == "CLOSED"


def test_04_termination_close_at_the_grace_boundary_refunds_the_whole_balance(api):
    """A commuter who left exactly 30 whole days before the close still sits
    inside a 30-day grace period, so the entire 12000-cent unused balance is
    refunded to the employer, nothing is forfeited, and the 5000-cent rollover
    cap is ignored outright.

    PRD §3.8: "Under the **termination close**, which runs when the employee's `status` is `TERMINATED`, the carried-forward amount is unconditionally zero no matter what `rollover_policy` says, because a departed employee has no next benefit month."
    PRD §3.8: "The service computes the whole days elapsed since the employee's `termination_date` by taking the difference between the current logical clock instant and `termination_date`, dividing by the 86400 seconds in a day, and discarding any fraction."
    PRD §3.8: "If that whole-day count is less than or equal to the employer's `forfeiture_grace_days`, the entire unused balance is refunded to the employer and nothing is forfeited."
    PRD §3.8: "If the refund amount is greater than zero, one entry is appended next with `entry_type` `REFUND` and a negative `amount_cents` equal to that amount."
    PRD §3.8: "Two invariants make this checkable: after a standard close the account's `available_balance_cents` equals exactly the carried-forward amount, and after a termination close it equals exactly zero."

    Design: Difficulty/dual_variant_calc/month_close_standard_vs_termination_variant_bucket_split
    """
    scenario = _build_parking_close_program(api)
    # 2026-08-05 plus exactly 30 whole days.
    fx.set_clock(api, "2026-09-04T00:00:00Z")

    validate_success(
        api.month_close_employer(
            scenario["employer"]["id"], {"benefit_month": "2026-08"}, PROGRAM_ADMIN
        )
    )

    assert scenario["terminated_employee"]["status"] == "TERMINATED"
    account = fx.read_account(api, scenario["terminated_account"]["id"])
    assert account["refunded_cents"] == 12000, (
        f"the whole unused balance is refunded, got {account['refunded_cents']}"
    )
    assert account["forfeited_cents"] == 0, "inside the grace period nothing is forfeited"
    assert account["available_balance_cents"] == 0, (
        "after a termination close the balance equals exactly zero"
    )
    assert account["rollover_in_cents"] == 12000
    assert account["ledger_entry_count"] == 2
    assert_account_conservation(account)

    entries = fx.read_ledger(api, account["id"])
    assert_ledger_sequence(
        entries, [("ROLLOVER_IN", 12000, 12000), ("REFUND", -12000, 0)]
    )
    assert_ledger_matches_account(account, entries)


def test_05_termination_close_one_day_past_the_grace_boundary_forfeits_everything(api):
    """One day beyond the 30-day grace period the destination flips: the same
    12000-cent unused balance is forfeited in full and the employer gets nothing
    back, while the balance still lands on exactly zero.

    PRD §3.8: "The service computes the whole days elapsed since the employee's `termination_date` by taking the difference between the current logical clock instant and `termination_date`, dividing by the 86400 seconds in a day, and discarding any fraction."
    PRD §3.8: "If it exceeds the grace period, the entire unused balance is forfeited and nothing is refunded."
    PRD §3.8: "If the forfeiture amount is greater than zero, one entry is appended first with `entry_type` `FORFEITURE` and a negative `amount_cents` equal to that amount."
    PRD §3.8: "Two invariants make this checkable: after a standard close the account's `available_balance_cents` equals exactly the carried-forward amount, and after a termination close it equals exactly zero."

    Design: Difficulty/dual_variant_calc/month_close_standard_vs_termination_variant_bucket_split
    """
    scenario = _build_parking_close_program(api)
    # 2026-08-05 plus 31 whole days -- one day past the grace period.
    fx.set_clock(api, "2026-09-05T00:00:00Z")

    validate_success(
        api.month_close_employer(
            scenario["employer"]["id"], {"benefit_month": "2026-08"}, PROGRAM_ADMIN
        )
    )

    account = fx.read_account(api, scenario["terminated_account"]["id"])
    assert account["forfeited_cents"] == 12000, (
        f"past the grace period the whole balance is forfeited, got {account['forfeited_cents']}"
    )
    assert account["refunded_cents"] == 0, "past the grace period nothing is refunded"
    assert account["available_balance_cents"] == 0
    assert account["ledger_entry_count"] == 2
    assert_account_conservation(account)

    entries = fx.read_ledger(api, account["id"])
    assert_ledger_sequence(
        entries, [("ROLLOVER_IN", 12000, 12000), ("FORFEITURE", -12000, 0)]
    )
    assert_ledger_matches_account(account, entries)


def test_06_identical_balances_split_by_the_account_holders_employment_status(api):
    """One close, two parking accounts seeded with the identical 12000 cents:
    the active commuter's balance splits 5000 carried / 7000 forfeited, while
    the departed commuter's whole 12000 is refunded to the employer.  The only
    discriminator is the account holder's employment status.

    PRD §3.8: "Which branch runs is decided by the account holder's employment `status`, and the two branches send identical balances to completely different destinations."
    PRD §3.8: "Under the **standard close**, which runs when the employee's `status` is `ACTIVE`, the carried-forward amount depends on the employer's `rollover_policy`: under `NO_ROLLOVER` nothing carries forward; under `FULL_ROLLOVER` the entire unused balance carries forward; and under `CAP_ROLLOVER` the carried-forward amount is the smaller of the unused balance and the employer's `rollover_cap_cents`."
    PRD §3.8: "Under the **termination close**, which runs when the employee's `status` is `TERMINATED`, the carried-forward amount is unconditionally zero no matter what `rollover_policy` says, because a departed employee has no next benefit month."
    PRD §3.8: "If that whole-day count is less than or equal to the employer's `forfeiture_grace_days`, the entire unused balance is refunded to the employer and nothing is forfeited."

    Design: Difficulty/dual_variant_calc/month_close_standard_vs_termination_variant_bucket_split
    """
    scenario = _build_parking_close_program(api)
    # 15 whole days after the termination, comfortably inside the 30-day grace.
    fx.set_clock(api, "2026-08-20T00:00:00Z")

    before_active = fx.read_account(api, scenario["active_account"]["id"])
    before_terminated = fx.read_account(api, scenario["terminated_account"]["id"])
    assert (
        before_active["available_balance_cents"]
        == before_terminated["available_balance_cents"]
        == 12000
    ), "precondition: both accounts must hold the identical unused balance"

    validate_success(
        api.month_close_employer(
            scenario["employer"]["id"], {"benefit_month": "2026-08"}, PROGRAM_ADMIN
        )
    )

    active = fx.read_account(api, scenario["active_account"]["id"])
    terminated = fx.read_account(api, scenario["terminated_account"]["id"])

    assert (active["forfeited_cents"], active["refunded_cents"]) == (7000, 0), (
        "the standard branch forfeits the uncapped remainder and refunds nothing"
    )
    assert active["available_balance_cents"] == 5000
    assert (terminated["forfeited_cents"], terminated["refunded_cents"]) == (0, 12000), (
        "the termination branch inside the grace period refunds everything"
    )
    assert terminated["available_balance_cents"] == 0

    for account in (active, terminated):
        assert_account_conservation(account)
        assert_ledger_matches_account(account, fx.read_ledger(api, account["id"]))
