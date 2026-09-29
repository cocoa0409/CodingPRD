"""
The two money quantities the programme audits across a compensating operation.

Programme cash — an account's balance plus every cent still held in an in-flight
transfer leg — must read the same before a rollover leaves, while it is away and
after it comes back. Contribution room — the annual ceiling less the year's
allocated contributions — must read the same before an overshooting payroll batch
is posted and after that posting is reversed. Each scenario measures its quantity
on both sides of the compensating write and requires the two readings to agree.
"""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import (
    ADMIN,
    assert_amounts,
    assert_fields,
    build_active_saver_environment,
    excess_cases_for_account,
    fund_account_by_remittance,
    post_earnings,
    read_account,
    read_employer,
    read_excess_case,
    read_participant,
    read_remittance,
    read_remittance_line,
    read_transfer,
    request_transfer,
    return_transfer,
    reverse_remittance,
    set_clock,
)

# The annual ceiling of the 2026 program year for a saver who is not yet 50, so
# no catch-up amount is added to it.
ANNUAL_CEILING_CENTS = 700000

RETURN_REASON = "Receiving institution could not accept an indirect rollover"
REVERSAL_REASON = "Employer submitted a duplicated payroll file"


def _program_cash(api, account_id, participant_id):
    """
    The saver's programme cash: the cents held in the account plus the cents
    still held in the in-flight leg of any transfer that has not yet ended.
    """
    total = read_account(api, account_id)["balance_cents"]
    rows, _ = validate_paginated(
        api.list_portability_transfers(ADMIN, {"participant_id": participant_id}))
    for row in rows:
        if row["status"] == "REQUESTED":
            total += row["in_transit_cents"]
    return total


def _contribution_room(api, account_id):
    """
    The saver's unused annual contribution room: the annual ceiling less the
    contributions already allocated to the account for the program year.
    """
    return ANNUAL_CEILING_CENTS - read_account(api, account_id)[
        "ytd_contribution_cents"]


def _account_holding_contributions_and_earnings(api):
    """
    A live saver whose account holds 600000 cents of posted payroll deductions
    and 600000 cents of credited earnings, with the clock on 1 May 2026.
    """
    env = build_active_saver_environment(api,
                                         annual_compensation_cents=144000000)
    env.update(fund_account_by_remittance(
        api, env, "2026-02-01", "2026-02-28", "2026-03-05",
        12000000, 600000, "2026-03-06T00:00:00Z", "PR-2026-0600"))
    post_earnings(api, env["account_id"], 600000, "2026-03-06")
    set_clock(api, "2026-05-01T00:00:00Z")
    return env


def _send_a_million_cents_out(api, env):
    """Request an indirect rollover of 1000000 cents out of the account."""
    transfer = request_transfer(api, env["participant_id"], env["account_id"],
                               1000000, transfer_kind="INDIRECT_60_DAY")
    env["transfer"] = transfer
    env["transfer_id"] = transfer["id"]
    return transfer


def _saver_with_one_posted_february_batch(api):
    """
    A live saver with one posted February batch of 500000 cents, which uses all
    but 200000 cents of the annual room.
    """
    env = build_active_saver_environment(api,
                                         annual_compensation_cents=120000000)
    first = fund_account_by_remittance(
        api, env, "2026-02-01", "2026-02-28", "2026-03-05",
        10000000, 500000, "2026-03-06T00:00:00Z", "PR-2026-A001")
    env["first_remittance_id"] = first["remittance_id"]
    env["first_line_id"] = first["line_id"]
    return env


def _post_the_overshooting_march_batch(api, env):
    """
    Post a March batch of 400000 cents, which carries the saver 200000 cents
    past the annual ceiling and opens one excess case.
    """
    second = fund_account_by_remittance(
        api, env, "2026-03-01", "2026-03-31", "2026-04-03",
        8000000, 400000, "2026-04-05T00:00:00Z", "PR-2026-B001")
    env["second_remittance_id"] = second["remittance_id"]
    env["second_line_id"] = second["line_id"]
    cases = excess_cases_for_account(api, env["account_id"])
    assert len(cases) == 1, (
        f"Expected exactly one excess case on the account, found {len(cases)}"
    )
    env["excess_case_id"] = cases[0]["id"]
    return env


def test_programme_cash_reads_the_same_before_during_and_after_the_round_trip(api):
    """
    Measured on the account alone the money vanishes and comes back, but measured
    as the account plus the in-flight leg it never moves: 1200000 cents at rest,
    1200000 cents while a million is away, and 1200000 cents once it is returned.

    "Programme cash is conserved: money that leaves an account into an in-flight
    transfer is held in that transfer's in-transit leg and is either delivered or
    fully restored, never partially lost."

    Design: Difficulty/compensating_invariant/program_cash_conserved_across_transfer_request_and_return
    """
    env = _account_holding_contributions_and_earnings(api)
    at_rest = _program_cash(api, env["account_id"], env["participant_id"])

    _send_a_million_cents_out(api, env)
    in_flight = _program_cash(api, env["account_id"], env["participant_id"])
    assert_amounts(read_account(api, env["account_id"]), {
        "balance_cents": 200000,
        "contribution_basis_cents": 100000,
    }, label="account while the rollover is away")

    return_transfer(api, env["transfer_id"], RETURN_REASON)

    after = _program_cash(api, env["account_id"], env["participant_id"])
    assert at_rest == 1200000
    assert in_flight == 1200000
    assert after == at_rest, (
        "Programme cash must read the same after the return as before the "
        f"request: {after} against {at_rest}"
    )
    assert_amounts(read_account(api, env["account_id"]), {
        "balance_cents": 1200000,
        "contribution_basis_cents": 600000,
        "ytd_contribution_cents": 600000,
        "remaining_headroom_cents": 100000,
    }, label="account after the return")


def test_the_return_restores_the_whole_gross_amount_and_not_the_net_proceeds(api):
    """
    The million left charged a 6000-cent fee and 50000 cents of withholding and
    carried 500000 cents of basis with it, yet the return credits the whole gross
    million back and rebuilds the basis, so nothing is left behind.

    "Programme cash is restored with zero drift — the saver is not charged for a
    transfer that never happened."

    Design: Difficulty/compensating_invariant/program_cash_conserved_across_transfer_request_and_return
    """
    env = _account_holding_contributions_and_earnings(api)
    before = _program_cash(api, env["account_id"], env["participant_id"])

    transfer = _send_a_million_cents_out(api, env)
    assert_amounts(transfer, {
        "amount_cents": 1000000,
        "fee_cents": 6000,
        "basis_portion_cents": 500000,
        "taxable_cents": 500000,
        "withholding_cents": 50000,
        "net_cents": 944000,
        "in_transit_cents": 1000000,
    }, label="indirect rollover as requested")

    return_transfer(api, env["transfer_id"], RETURN_REASON)

    restored = read_account(api, env["account_id"])
    assert restored["balance_cents"] == 1200000, (
        "The full gross amount must come back, not the net proceeds"
    )
    assert_amounts(restored, {
        "contribution_basis_cents": 600000,
        "ytd_contribution_cents": 600000,
        "remaining_headroom_cents": 100000,
    }, label="account after the return")
    after = _program_cash(api, env["account_id"], env["participant_id"])
    assert after == before == 1200000


def test_the_returned_rollover_never_counts_as_a_settled_distribution(api):
    """
    A returned rollover is not a distribution: the in-flight leg is emptied, the
    settlement fields stay unset, the return reason is kept, the account is
    released for new money movement and the saver's rollover tally is still zero.

    "`is_taxable_distribution` starts false, and `settled_on`,
    `settlement_reference` and `return_reason` start null."

    Design: Difficulty/compensating_invariant/program_cash_conserved_across_transfer_request_and_return
    """
    env = _account_holding_contributions_and_earnings(api)
    _send_a_million_cents_out(api, env)
    before = _program_cash(api, env["account_id"], env["participant_id"])

    return_transfer(api, env["transfer_id"], RETURN_REASON)

    transfer = read_transfer(api, env["transfer_id"])
    assert_fields(transfer, {
        "status": "RETURNED",
        "is_taxable_distribution": False,
        "return_reason": RETURN_REASON,
    }, label="returned rollover")
    assert transfer["settled_on"] is None
    assert transfer["settlement_reference"] is None
    assert_amounts(transfer, {"in_transit_cents": 0}, label="returned rollover")
    assert_fields(read_account(api, env["account_id"]), {
        "account_status": "OPEN",
        "posture": "UNRESTRICTED",
    }, label="account after the return")
    assert read_participant(api, env["participant_id"])[
        "indirect_rollover_count"] == 0
    after = _program_cash(api, env["account_id"], env["participant_id"])
    assert after == before == 1200000


def test_contribution_room_reads_the_same_before_the_posting_and_after_the_reversal(api):
    """
    The March batch consumes the last 200000 cents of room and 200000 cents more
    besides, and reversing it puts the room back exactly where it stood before the
    posting rather than somewhere near it.

    "Contribution room is conserved: whatever a posting adds to a saver's
    year-to-date contributions, a reversal of that posting subtracts exactly,
    leaving no drift."

    Design: Difficulty/compensating_invariant/contribution_room_conserved_across_remittance_posting_and_reversal
    """
    env = _saver_with_one_posted_february_batch(api)
    before = _contribution_room(api, env["account_id"])

    _post_the_overshooting_march_batch(api, env)
    assert _contribution_room(api, env["account_id"]) == -200000, (
        "The overshooting posting must carry the saver past the ceiling"
    )

    reversed_batch = reverse_remittance(api, env["second_remittance_id"],
                                        REVERSAL_REASON)

    after = _contribution_room(api, env["account_id"])
    assert before == 200000
    assert after == before, (
        "Contribution room must read the same after the reversal as before the "
        f"posting: {after} against {before}"
    )
    assert_fields(reversed_batch, {"status": "REVERSED",
                                   "reversal_reason": REVERSAL_REASON},
                  label="reversed March batch")
    assert_amounts(read_remittance(api, env["second_remittance_id"]), {
        "total_allocated_cents": 0,
        "total_excess_cents": 0,
    }, label="reversed March batch")
    assert_amounts(read_account(api, env["account_id"]), {
        "ytd_contribution_cents": 500000,
        "remaining_headroom_cents": 200000,
        "balance_cents": 500000,
        "contribution_basis_cents": 500000,
    }, label="account after the reversal")


def test_the_reversal_also_voids_the_excess_case_the_posting_opened(api):
    """
    Putting the money back is not enough on its own: the excess case the posting
    spawned is voided as well, the account carries no uncorrected excess and its
    gate relaxes, so the reversal reaches the downstream record and not merely the
    balance.

    "Every excess-contribution case that this batch opened becomes `VOIDED`,
    whether it was still in `DETECTED` or had already reached `METHOD_ELECTED`; a
    voided case keeps its `detected_excess_cents`, and its elected
    `correction_method` where one was chosen, purely as audit history, and no
    longer restricts anything."

    Design: Difficulty/compensating_invariant/contribution_room_conserved_across_remittance_posting_and_reversal
    """
    env = _saver_with_one_posted_february_batch(api)
    before = _contribution_room(api, env["account_id"])
    _post_the_overshooting_march_batch(api, env)
    assert read_account(api, env["account_id"])["posture"] == "RESTRICTED"
    assert read_excess_case(api, env["excess_case_id"])["status"] == "DETECTED"

    reverse_remittance(api, env["second_remittance_id"], REVERSAL_REASON)

    case = read_excess_case(api, env["excess_case_id"])
    assert case["status"] == "VOIDED"
    assert_amounts(case, {"detected_excess_cents": 200000},
                   label="voided excess case")
    account = read_account(api, env["account_id"])
    assert_fields(account, {"posture": "UNRESTRICTED", "account_status": "OPEN"},
                  label="account after the reversal")
    assert_amounts(account, {"uncorrected_excess_cents": 0},
                   label="account after the reversal")
    line = read_remittance_line(api, env["second_remittance_id"],
                                env["second_line_id"])
    assert line["status"] == "REVERSED"
    assert_amounts(line, {"allocated_cents": 0, "excess_cents": 0},
                   label="reversed March line")
    assert _contribution_room(api, env["account_id"]) == before


def test_the_reversal_leaves_the_february_batch_and_the_employer_ledger_alone(api):
    """
    Only the reversed batch is unwound: February keeps its posted allocation of
    500000 cents, and the employer owes nothing, because neither a posted nor a
    reversed batch counts as money still withheld from savers.

    "Batches in `POSTED`, `REJECTED` or `REVERSED` contribute nothing: posted
    money has arrived, rejected money was never accepted, and reversed money has
    been compensated."

    Design: Difficulty/compensating_invariant/contribution_room_conserved_across_remittance_posting_and_reversal
    """
    env = _saver_with_one_posted_february_batch(api)
    before = _contribution_room(api, env["account_id"])
    _post_the_overshooting_march_batch(api, env)

    reverse_remittance(api, env["second_remittance_id"], REVERSAL_REASON)

    february = read_remittance(api, env["first_remittance_id"])
    assert february["status"] == "POSTED"
    assert_amounts(february, {
        "total_allocated_cents": 500000,
        "total_excess_cents": 0,
    }, label="February batch")
    assert read_remittance_line(
        api, env["first_remittance_id"], env["first_line_id"])["status"] == (
            "POSTED")
    assert_amounts(read_employer(api, env["employer_id"]),
                   {"unremitted_deduction_cents": 0}, label="employer ledger")
    assert _contribution_room(api, env["account_id"]) == before == 200000
