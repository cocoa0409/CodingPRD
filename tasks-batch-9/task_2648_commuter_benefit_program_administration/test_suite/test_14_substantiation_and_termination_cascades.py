"""Substantiation review and the two multi-level cascades that hang off it:
the audit reopen that compensates a denial hop for hop, and the employee
termination that reaches down through elections into media orders.

Each test builds its own employer, employee, account, election and card
activity through the documented endpoints; the service is restarted against an
empty database before each test runs.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    PROGRAM_ADMIN,
    assert_account_conservation,
    assert_ledger_matches_account,
    assert_ledger_sequence,
    constants,
    fixtures,
    make_compliance_reviewer_headers,
    make_order_desk_headers,
)


def test_01_approving_the_claim_substantiates_the_swipe_and_moves_no_money(api):
    """PRD §3.7: "On approval the claim moves `SUBMITTED → APPROVED` with `reviewed_by_user_id` recording the acting `X-User-ID`, and the underlying swipe moves `PENDING_DOCS → SUBSTANTIATED` with `approved_by_user_id` recording that same acting `X-User-ID`."
    PRD §3.7: "Approval deliberately moves no money: `posted_spend_cents` and the benefit account are left exactly as they were, because the spend was already posted at ingestion."

    Design: Corner/state_machines/claim_approval_drives_card_transaction_to_substantiated_without_money_movement
    """
    built = fixtures.make_submitted_claim(
        api,
        region_code=constants.REGION_CHI,
        amount_cents=3000,
        merchant_category_code=4111,
        opening_rollover_cents=10000,
        pretax_amount_cents=5000,
    )
    transaction = built["transaction"]
    claim = built["claim"]
    assert transaction["substantiation_status"] == "PENDING_DOCS", (
        transaction["substantiation_status"]
    )
    assert transaction["posted_spend_cents"] == 3000, (
        transaction["posted_spend_cents"]
    )
    assert transaction["approved_by_user_id"] is None, (
        transaction["approved_by_user_id"]
    )
    assert claim["status"] == "SUBMITTED", claim["status"]
    assert claim["reviewed_by_user_id"] is None, claim["reviewed_by_user_id"]
    assert claim["version"] == 1, claim["version"]

    account_before = fixtures.read_account(api, built["account"]["id"])
    assert account_before["available_balance_cents"] == 7000, (
        account_before["available_balance_cents"]
    )
    assert account_before["ledger_entry_count"] == 2, (
        account_before["ledger_entry_count"]
    )
    assert account_before["spent_cents"] == 3000, account_before["spent_cents"]

    reviewer = make_compliance_reviewer_headers("rev-approve")
    approved = validate_success(api.approve_substantiation_claim(claim["id"], reviewer))

    assert approved["status"] == "APPROVED", approved["status"]
    assert approved["reviewed_by_user_id"] == "rev-approve", (
        approved["reviewed_by_user_id"]
    )
    assert approved["version"] == 2, (
        f"the claim version must advance to 2, got {approved['version']}"
    )

    transaction_after = fixtures.read_transaction(api, transaction["id"])
    assert transaction_after["substantiation_status"] == "SUBSTANTIATED", (
        "approving the claim is what moves the transaction, got "
        f"{transaction_after['substantiation_status']}"
    )
    assert transaction_after["approved_by_user_id"] == "rev-approve", (
        transaction_after["approved_by_user_id"]
    )
    assert transaction_after["posted_spend_cents"] == 3000, (
        "the posted spend must stay exactly as ingestion left it, got "
        f"{transaction_after['posted_spend_cents']}"
    )
    assert transaction_after["version"] == transaction["version"] + 1, (
        f"the transaction version must advance by 1: {transaction['version']} -> "
        f"{transaction_after['version']}"
    )

    account_after = fixtures.read_account(api, built["account"]["id"])
    assert account_after["available_balance_cents"] == 7000, (
        account_after["available_balance_cents"]
    )
    assert account_after["spent_cents"] == 3000, account_after["spent_cents"]
    assert account_after["ledger_entry_count"] == 2, (
        "approval must append no ledger entry, count is "
        f"{account_after['ledger_entry_count']}"
    )
    assert account_after["version"] == account_before["version"], (
        f"the account must not be written: {account_before['version']} -> "
        f"{account_after['version']}"
    )
    assert_account_conservation(account_after)

    entries = fixtures.read_ledger(api, built["account"]["id"])
    assert_ledger_sequence(
        entries, [("ROLLOVER_IN", 10000, 10000), ("SPEND", -3000, 7000)]
    )
    assert_ledger_matches_account(account_after, entries)

    election_after = fixtures.read_election(api, built["election"]["id"])
    assert election_after["funding_status"] == "PENDING", (
        "substantiating a swipe does not touch the funding axis"
    )


def test_02_reopening_an_ineligible_swipe_reverses_every_hop_of_the_deny_cascade(api):
    """PRD §3.7: "Its first level sets `substantiation_status` to `PENDING_DOCS`, restores `posted_spend_cents` to the transaction's full `amount_cents`, increments `reopen_count` by 1, and advances `CardTransaction.version` by 1."
    PRD §3.7: "Its third level, caused by that ledger debit, decreases the employee's `repayment_due_cents` by the same amount and sets `substantiation_hold` to true exactly when `repayment_due_cents` remains greater than zero — so a single outstanding receivable cleared by a single reopen drops the flag to false — and advances `Employee.version` by 1."
    PRD §3.7: "Its fourth level, caused by the flag clearing, drives every election of that employee whose `funding_status` is `HELD` back through `HELD → PENDING`, but only where the election's window `status` is `OPEN` or `LOCKED`; each such election advances its `version` by 1."

    Design: Corner/state_machines/reopen_from_ineligible_compensates_every_deny_side_effect
    """
    built = fixtures.make_denied_transaction(
        api,
        deny_user_id="rev-deny",
        amount_cents=3000,
        region_code=constants.REGION_CHI,
        merchant_category_code=4111,
        opening_rollover_cents=10000,
        pretax_amount_cents=5000,
    )
    transaction = built["transaction"]
    assert transaction["substantiation_status"] == "INELIGIBLE", (
        transaction["substantiation_status"]
    )
    assert transaction["posted_spend_cents"] == 0, transaction["posted_spend_cents"]
    assert transaction["denied_by_user_id"] == "rev-deny", (
        transaction["denied_by_user_id"]
    )
    assert transaction["reopen_count"] == 0, transaction["reopen_count"]

    account_denied = fixtures.read_account(api, built["account"]["id"])
    assert account_denied["available_balance_cents"] == 10000, (
        account_denied["available_balance_cents"]
    )
    assert account_denied["ledger_entry_count"] == 3, (
        account_denied["ledger_entry_count"]
    )
    assert account_denied["spent_cents"] == 0, account_denied["spent_cents"]

    employee_denied = fixtures.read_employee(api, built["employee"]["id"])
    assert employee_denied["repayment_due_cents"] == 3000, (
        employee_denied["repayment_due_cents"]
    )
    assert employee_denied["substantiation_hold"] is True, (
        employee_denied["substantiation_hold"]
    )

    election_denied = fixtures.read_election(api, built["election"]["id"])
    assert election_denied["funding_status"] == "HELD", (
        election_denied["funding_status"]
    )

    reopened = validate_success(
        api.reopen_card_transaction(
            transaction["id"],
            {"reason": "receipt produced on appeal"},
            make_compliance_reviewer_headers("rev-audit"),
        )
    )

    assert reopened["substantiation_status"] == "PENDING_DOCS", (
        reopened["substantiation_status"]
    )
    assert reopened["posted_spend_cents"] == 3000, (
        "the posted spend must be restored to the full settled amount, got "
        f"{reopened['posted_spend_cents']}"
    )
    assert reopened["reopen_count"] == 1, reopened["reopen_count"]
    assert reopened["version"] == transaction["version"] + 1, (
        f"the transaction version must advance by 1: {transaction['version']} -> "
        f"{reopened['version']}"
    )

    account_reopened = fixtures.read_account(api, built["account"]["id"])
    assert account_reopened["available_balance_cents"] == 7000, (
        "the account must land back on its exact pre-deny balance, got "
        f"{account_reopened['available_balance_cents']}"
    )
    assert account_reopened["spent_cents"] == 3000, account_reopened["spent_cents"]
    assert account_reopened["ledger_entry_count"] == 4, (
        account_reopened["ledger_entry_count"]
    )
    assert account_reopened["version"] == account_denied["version"] + 1, (
        f"the account version must advance by 1: {account_denied['version']} -> "
        f"{account_reopened['version']}"
    )
    assert_account_conservation(account_reopened)

    employee_reopened = fixtures.read_employee(api, built["employee"]["id"])
    assert employee_reopened["repayment_due_cents"] == 0, (
        employee_reopened["repayment_due_cents"]
    )
    assert employee_reopened["substantiation_hold"] is False, (
        "a single receivable cleared by a single reopen drops the hold flag"
    )
    assert employee_reopened["version"] == employee_denied["version"] + 1, (
        f"the employee version must advance by 1: {employee_denied['version']} -> "
        f"{employee_reopened['version']}"
    )

    election_reopened = fixtures.read_election(api, built["election"]["id"])
    assert election_reopened["funding_status"] == "PENDING", (
        "the frozen election must be released back to PENDING, got "
        f"{election_reopened['funding_status']}"
    )
    assert election_reopened["version"] == election_denied["version"] + 1, (
        f"the election version must advance by 1: {election_denied['version']} -> "
        f"{election_reopened['version']}"
    )


def test_03_the_reopen_appends_a_fresh_spend_row_rather_than_editing_the_reversal(api):
    """PRD §3.7: "Its second level, caused by that change, appends one ledger entry with `entry_type` `SPEND` and a negative `amount_cents` equal to the transaction's `amount_cents`, with `source_entity` `CardTransaction` and `source_id` the transaction's identifier; the account's `spent_cents` increases by that amount, `available_balance_cents` is recomputed, `ledger_entry_count` is incremented and `BenefitAccount.version` advances by 1."
    PRD §3.7: "Taken together, a denial followed by a reopen must leave the benefit account's conservation identities holding and the employee's `repayment_due_cents` back at zero."

    Design: Corner/state_machines/reopen_from_ineligible_compensates_every_deny_side_effect
    """
    built = fixtures.make_denied_transaction(
        api,
        deny_user_id="rev-deny",
        amount_cents=3000,
        region_code=constants.REGION_CHI,
        merchant_category_code=4111,
        opening_rollover_cents=10000,
        pretax_amount_cents=5000,
    )
    transaction_id = built["transaction"]["id"]
    account_id = built["account"]["id"]
    denied_entries = fixtures.read_ledger(api, account_id)
    assert_ledger_sequence(
        denied_entries,
        [
            ("ROLLOVER_IN", 10000, 10000),
            ("SPEND", -3000, 7000),
            ("SPEND_REVERSAL", 3000, 10000),
        ],
    )
    reversal_row = denied_entries[2]

    validate_success(
        api.reopen_card_transaction(
            transaction_id,
            {"reason": "receipt produced on appeal"},
            make_compliance_reviewer_headers("rev-audit"),
        )
    )

    entries = fixtures.read_ledger(api, account_id)
    assert_ledger_sequence(
        entries,
        [
            ("ROLLOVER_IN", 10000, 10000),
            ("SPEND", -3000, 7000),
            ("SPEND_REVERSAL", 3000, 10000),
            ("SPEND", -3000, 7000),
        ],
    )
    assert entries[2] == reversal_row, (
        "the earlier SPEND_REVERSAL row must be left byte-identical, not edited"
    )
    fresh_spend = entries[3]
    assert fresh_spend["source_entity"] == "CardTransaction", (
        fresh_spend["source_entity"]
    )
    assert fresh_spend["source_id"] == transaction_id, fresh_spend["source_id"]

    account = fixtures.read_account(api, account_id)
    assert account["available_balance_cents"] == 7000, (
        account["available_balance_cents"]
    )
    assert_account_conservation(account)
    assert_ledger_matches_account(account, entries)

    employee = fixtures.read_employee(api, built["employee"]["id"])
    assert employee["repayment_due_cents"] == 0, employee["repayment_due_cents"]


def test_04_terminating_one_employee_cascades_into_their_elections_and_media_orders(api):
    """PRD §3.1: "Then the cascade runs: every election of that employee whose `funding_status` is `PENDING` or `HELD` is moved to `CANCELLED` and has `excluded_amount_cents`, `posttax_spill_cents`, `posttax_effective_cents` and `total_amount_cents` all zeroed; for every election so cancelled, every media order of that election whose `status` is `PENDING` or `SUBMITTED` is moved to `CANCELLED`; the `fulfillment_status` of every touched election is re-derived; the employer's `enrolled_employee_count` is recomputed; and `Employee.version` advances by 1, as does the `version` of every election, media order and employer row the cascade actually changed."
    PRD §3.1: "On success the employee moves `ACTIVE → TERMINATED` with `termination_date` recorded."
    PRD §3.1: "Note what termination does *not* do: it does not touch elections already `FUNDED`, `REVERSED` or `SETTLED`, and it does not immediately move money."
    PRD §3.2: "A new window is created in `status` `SCHEDULED` with `locked_at` null and `election_count` at zero; that counter tracks elections in the window whose `funding_status` is `PENDING`, `HELD`, `FUNDED` or `SETTLED`."

    Design: Corner/state_machines/employee_termination_cascades_down_to_elections_and_media_orders
    """
    built = fixtures.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000}
        ],
        region_code=constants.REGION_AUS,
    )
    employer_id = built["employer"]["id"]
    category_id = built["categories"][0]["id"]
    media = fixtures.make_transit_media(
        api,
        region_code=constants.REGION_AUS,
        eligible_category_type="TRANSIT_PASS",
        unit_price_cents=6000,
    )
    window = fixtures.make_open_window(api, employer_id, PROGRAM_ADMIN)

    leaver = fixtures.make_enrolled_employee(
        api,
        employer_id,
        category_id,
        PROGRAM_ADMIN,
        external_ref="AUS-CD-1",
        work_region_code=constants.REGION_AUS,
        hire_date="2026-02-01T00:00:00Z",
    )
    stayer = fixtures.make_enrolled_employee(
        api,
        employer_id,
        category_id,
        PROGRAM_ADMIN,
        external_ref="AUS-CD-2",
        work_region_code=constants.REGION_AUS,
        hire_date="2026-02-02T00:00:00Z",
    )

    election_leaver = fixtures.make_election(
        api,
        leaver["employee"]["id"],
        window["id"],
        category_id,
        leaver["account"]["id"],
        PROGRAM_ADMIN,
        pretax_amount_cents=6000,
        posttax_amount_cents=0,
        transit_media_id=media["id"],
        media_quantity=1,
    )
    election_stayer = fixtures.make_election(
        api,
        stayer["employee"]["id"],
        window["id"],
        category_id,
        stayer["account"]["id"],
        PROGRAM_ADMIN,
        pretax_amount_cents=6000,
        posttax_amount_cents=0,
        transit_media_id=media["id"],
        media_quantity=1,
    )

    desk = make_order_desk_headers("desk-ops")
    batch = fixtures.make_open_batch(
        api, window["id"], constants.REGION_AUS, "desk-ops"
    )
    order_leaver = fixtures.make_media_order(
        api,
        election_leaver["id"],
        media["id"],
        batch["id"],
        "desk-ops",
        quantity=1,
        coverage_start_at="2026-08-01T00:00:00Z",
        coverage_end_at="2026-08-15T00:00:00Z",
    )
    order_stayer = fixtures.make_media_order(
        api,
        election_stayer["id"],
        media["id"],
        batch["id"],
        "desk-ops",
        quantity=1,
        coverage_start_at="2026-08-01T00:00:00Z",
        coverage_end_at="2026-08-15T00:00:00Z",
    )
    assert order_leaver["status"] == "PENDING", order_leaver["status"]
    assert order_stayer["status"] == "PENDING", order_stayer["status"]

    employer_before = fixtures.read_employer(api, employer_id)
    assert employer_before["enrolled_employee_count"] == 2, (
        employer_before["enrolled_employee_count"]
    )
    leaver_before = fixtures.read_employee(api, leaver["employee"]["id"])
    election_leaver_before = fixtures.read_election(api, election_leaver["id"])
    assert election_leaver_before["funding_status"] == "PENDING", (
        election_leaver_before["funding_status"]
    )
    assert election_leaver_before["fulfillment_status"] == "ORDERED", (
        election_leaver_before["fulfillment_status"]
    )
    assert election_leaver_before["total_amount_cents"] == 6000, (
        election_leaver_before["total_amount_cents"]
    )
    stayer_before = fixtures.read_employee(api, stayer["employee"]["id"])
    election_stayer_before = fixtures.read_election(api, election_stayer["id"])
    account_leaver_before = fixtures.read_account(api, leaver["account"]["id"])

    terminated = validate_success(
        api.terminate_employee(
            leaver["employee"]["id"],
            {"termination_date": "2026-08-10T00:00:00Z"},
            PROGRAM_ADMIN,
        )
    )

    assert terminated["status"] == "TERMINATED", terminated["status"]
    assert terminated["termination_date"] == "2026-08-10T00:00:00Z", (
        terminated["termination_date"]
    )
    assert terminated["version"] == leaver_before["version"] + 1, (
        f"the employee version must advance by 1: {leaver_before['version']} -> "
        f"{terminated['version']}"
    )

    election_after = fixtures.read_election(api, election_leaver["id"])
    assert election_after["funding_status"] == "CANCELLED", (
        election_after["funding_status"]
    )
    assert election_after["fulfillment_status"] == "CANCELLED", (
        election_after["fulfillment_status"]
    )
    assert election_after["total_amount_cents"] == 0, (
        election_after["total_amount_cents"]
    )
    assert election_after["excluded_amount_cents"] == 0, (
        election_after["excluded_amount_cents"]
    )
    assert election_after["posttax_spill_cents"] == 0, (
        election_after["posttax_spill_cents"]
    )
    assert election_after["posttax_effective_cents"] == 0, (
        election_after["posttax_effective_cents"]
    )
    assert election_after["version"] == election_leaver_before["version"] + 1, (
        f"the cancelled election version must advance by 1: "
        f"{election_leaver_before['version']} -> {election_after['version']}"
    )

    order_after = fixtures.read_media_order(api, order_leaver["id"], desk)
    assert order_after["status"] == "CANCELLED", (
        "the third level of the cascade must cancel the live media line, got "
        f"{order_after['status']}"
    )
    assert order_after["version"] == order_leaver["version"] + 1, (
        f"the cancelled line version must advance by 1: {order_leaver['version']} -> "
        f"{order_after['version']}"
    )

    employer_after = fixtures.read_employer(api, employer_id)
    assert employer_after["enrolled_employee_count"] == 1, (
        "the employer roster counter must drop to the one remaining ACTIVE employee, "
        f"got {employer_after['enrolled_employee_count']}"
    )
    assert employer_after["version"] == employer_before["version"] + 1, (
        f"the employer version must advance by 1: {employer_before['version']} -> "
        f"{employer_after['version']}"
    )

    coworker_after = fixtures.read_employee(api, stayer["employee"]["id"])
    assert coworker_after["status"] == "ACTIVE", coworker_after["status"]
    assert coworker_after["version"] == stayer_before["version"], (
        "the co-worker row must not be written by another employee's termination"
    )
    coworker_election_after = fixtures.read_election(api, election_stayer["id"])
    assert coworker_election_after["funding_status"] == "PENDING", (
        coworker_election_after["funding_status"]
    )
    assert coworker_election_after["fulfillment_status"] == "ORDERED", (
        coworker_election_after["fulfillment_status"]
    )
    assert coworker_election_after["version"] == election_stayer_before["version"], (
        "the co-worker's election must not be written"
    )
    coworker_order_after = fixtures.read_media_order(api, order_stayer["id"], desk)
    assert coworker_order_after["status"] == "PENDING", (
        coworker_order_after["status"]
    )
    assert coworker_order_after["version"] == order_stayer["version"], (
        "the co-worker's media line must not be written"
    )

    window_after = fixtures.read_window(api, window["id"])
    assert window_after["election_count"] == 1, (
        "only the co-worker's election still counts toward the window, got "
        f"{window_after['election_count']}"
    )

    account_leaver_after = fixtures.read_account(api, leaver["account"]["id"])
    assert account_leaver_after["version"] == account_leaver_before["version"], (
        "termination moves no money"
    )
    assert account_leaver_after["available_balance_cents"] == (
        account_leaver_before["available_balance_cents"]
    ), account_leaver_after["available_balance_cents"]
    assert_account_conservation(account_leaver_after)
