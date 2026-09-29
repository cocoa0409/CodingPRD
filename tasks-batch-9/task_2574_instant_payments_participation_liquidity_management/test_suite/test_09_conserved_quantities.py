"""Quantities the rail must conserve, and the ones it deliberately does not.

The funded position is an accounting identity over an append-only ledger, so a fully
honoured return has to come back through a *new* credit entry that leaves the original
debit exactly where it was. The headline balance would look right either way; the entry
list is what distinguishes a compensating credit from an unwound debit.

A partial honour then separates two conserved quantities that a single request moves by
different amounts: the position rises only by the returned amount, while the customer's
daily sent usage drops all the way to zero because the honoured row leaves the input set.
"""

from test_helpers import (
    assert_account_position,
    assert_immutable_system_fields,
    assert_ledger_entry,
    assert_ledger_identity,
    assert_running_balances,
    assert_sequence_numbers_are_dense,
    assert_transfer_dimensions,
    honor_return_request,
    list_alerts,
    list_ledger_entries,
    list_transfers,
    read_account,
    read_customer_account,
    read_participant,
    read_transfer,
    return_requested_scenario,
    set_clock,
)


def _full_return_world(api):
    """Alpha's settled 250,000,000-cent payment with a full return request lodged."""
    return return_requested_scenario(
        api,
        reason_code="TECHNICAL_ERROR",
        returned_amount_cents=250_000_000,
        narrative="Duplicate posting caused by a channel retry.",
    )


def test_full_honour_closes_the_ledger_identity_with_two_entries(api):
    """The position returns to its opening figure through a second, additive entry.

    PRD 2.8: "It is always **derived**, and the derivation is the accounting identity of
    this system: `current_balance_cents` equals the account's `opening_balance_cents` plus
    the sum of the `amount_cents` of every `LiquidityLedgerEntry` whose `account_id` is this
    account."

    Design: Difficulty/compensating_invariant/ledger_identity_and_balance_round_trip_after_full_return
    """
    scenario, transfer, request = _full_return_world(api)

    set_clock(api, "2026-08-03T13:25:00Z")
    honored = honor_return_request(api, request["id"])
    assert honored["status"] == "HONORED"

    entries = list_ledger_entries(api, scenario.alpha.account_id)
    assert len(entries) == 2
    assert_ledger_entry(
        entries[0],
        entry_type="TRANSFER_DEBIT",
        amount_cents=-250_000_000,
        balance_after_cents=950_000_000,
        sequence_no=1,
        business_date="2026-08-03",
    )
    assert_ledger_entry(
        entries[1],
        entry_type="RETURN_CREDIT",
        amount_cents=250_000_000,
        balance_after_cents=1_200_000_000,
        sequence_no=2,
        business_date="2026-08-03",
    )
    assert_sequence_numbers_are_dense(entries)
    assert_running_balances(1_200_000_000, entries)

    account = read_account(api, scenario.alpha.account_id)
    assert_ledger_identity(account, entries)
    assert account["current_balance_cents"] == account["opening_balance_cents"] == 1_200_000_000
    assert account["last_ledger_sequence_no"] == 2
    assert_account_position(
        account,
        current_balance_cents=1_200_000_000,
        reserved_cents=0,
        available_cents=1_200_000_000,
        alert_tier="GREEN",
    )

    assert all(alert["status"] == "CLEARED" for alert in list_alerts(api, scenario.alpha.account_id))
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "NORMAL"
    assert_transfer_dimensions(read_transfer(api, transfer["id"]), "SETTLED", "RETURN_HONORED")

    compensating = list_transfers(api, {"compensating_for_transfer_id": transfer["id"]})
    assert len(compensating) == 1
    assert compensating[0]["direction"] == "INBOUND"
    assert compensating[0]["clearing_status"] == "SETTLED"
    assert compensating[0]["amount_cents"] == 250_000_000


def test_the_original_settlement_debit_survives_the_honour_untouched(api):
    """Entries are append-only, so the debit is not amended, reversed or deleted.

    PRD 2.8: "There is no status filter and no time window on that sum — entries are
    append-only and immutable, so the identity holds over all time."

    Design: Difficulty/compensating_invariant/ledger_identity_and_balance_round_trip_after_full_return
    """
    scenario, transfer, request = _full_return_world(api)
    before = list_ledger_entries(api, scenario.alpha.account_id)
    assert len(before) == 1
    debit_before = before[0]
    assert_immutable_system_fields(debit_before, "ledger entry")

    set_clock(api, "2026-08-03T13:25:00Z")
    honor_return_request(api, request["id"])

    after = list_ledger_entries(api, scenario.alpha.account_id)
    assert len(after) == 2
    debit_after = after[0]
    assert debit_after["id"] == debit_before["id"]
    assert debit_after["created_at"] == debit_before["created_at"]
    assert debit_after["entry_type"] == "TRANSFER_DEBIT"
    assert debit_after["amount_cents"] == -250_000_000
    assert debit_after["balance_after_cents"] == 950_000_000
    assert debit_after["sequence_no"] == 1
    assert debit_after["business_date"] == "2026-08-03"
    assert debit_after["related_transfer_id"] == transfer["id"]

    credit = after[1]
    assert credit["id"] != debit_before["id"]
    assert credit["entry_type"] == "RETURN_CREDIT"
    assert credit["sequence_no"] == 2


def _partial_return_world(api):
    """The same settled payment with only 100,000,000 cents of it disputed."""
    return return_requested_scenario(
        api,
        reason_code="FRAUD_SUSPECTED",
        returned_amount_cents=100_000_000,
        narrative="Only part of the credit is disputed as fraudulent; the beneficiary retains the remainder.",
    )


def test_partial_honour_credits_only_the_returned_amount(api):
    """The position rises by the returned figure, so the band lands AMBER, not GREEN.

    PRD 3.8: "**Third**, the compensating transfer posts one ledger entry with
    `entry_type` `RETURN_CREDIT` and an `amount_cents` equal to the positive returned
    amount, raising `current_balance_cents` and incrementing the position account's
    `version`."

    Design: Difficulty/compensating_invariant/daily_sent_usage_conserved_after_partial_return
    """
    scenario, transfer, request = _partial_return_world(api)
    assert request["original_amount_cents"] == 250_000_000
    assert request["returned_amount_cents"] == 100_000_000

    set_clock(api, "2026-08-03T13:25:00Z")
    honor_return_request(api, request["id"])

    entries = list_ledger_entries(api, scenario.alpha.account_id)
    assert len(entries) == 2
    assert_ledger_entry(
        entries[1],
        entry_type="RETURN_CREDIT",
        amount_cents=100_000_000,
        balance_after_cents=1_050_000_000,
        sequence_no=2,
        business_date="2026-08-03",
    )
    account = read_account(api, scenario.alpha.account_id)
    assert_ledger_identity(account, entries)
    assert_account_position(
        account,
        current_balance_cents=1_050_000_000,
        reserved_cents=0,
        available_cents=1_050_000_000,
        alert_tier="AMBER",
    )
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "THROTTLED"

    alerts = list_alerts(api, scenario.alpha.account_id)
    assert len(alerts) == 2
    by_tier = {alert["tier"]: alert for alert in alerts}
    assert by_tier["RED"]["status"] == "OPEN"
    assert by_tier["AMBER"]["status"] == "OPEN"

    compensating = list_transfers(api, {"compensating_for_transfer_id": transfer["id"]})
    assert len(compensating) == 1
    assert compensating[0]["amount_cents"] == 100_000_000
    assert compensating[0]["direction"] == "INBOUND"


def test_partial_honour_still_clears_the_whole_daily_sent_usage(api):
    """The counter is not conserved pro-rata: the honoured row leaves its input set.

    PRD 3.4: "The conserved part, mirrored on the customer account as
    `daily_sent_amount_cents`, is the summed `amount_cents` of that customer's outbound
    transfers whose `clearing_status` is `SETTLED`, whose `settlement_business_date` equals
    the current business date, and whose `exception_status` is anything other than
    `RETURN_HONORED`."

    Design: Difficulty/compensating_invariant/daily_sent_usage_conserved_after_partial_return
    """
    scenario, transfer, request = _partial_return_world(api)
    assert read_customer_account(api, scenario.alpha.customer_account_id)[
        "daily_sent_amount_cents"
    ] == 250_000_000

    set_clock(api, "2026-08-03T13:25:00Z")
    honored = honor_return_request(api, request["id"])

    assert honored["status"] == "HONORED"
    assert_transfer_dimensions(read_transfer(api, transfer["id"]), "SETTLED", "RETURN_HONORED")
    customer = read_customer_account(api, scenario.alpha.customer_account_id)
    assert customer["daily_sent_amount_cents"] == 0
    assert customer["status"] == "ACTIVE"
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 0
