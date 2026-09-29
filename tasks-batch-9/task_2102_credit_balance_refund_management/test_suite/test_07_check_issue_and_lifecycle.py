"""Issuing a check run and the three-way fork an issued check then faces."""
from test_helpers import (
    TEST_USERS,
    add_batch_item,
    issue_batch,
    assert_credit_liability_invariant,
    assert_instant_equals,
    attribute_all,
    lock_batch,
    list_transactions,
    open_batch,
    read_account,
    read_batch,
    read_check,
    read_credit_balance,
    read_obligation,
    read_refund_request,
    reissue_check,
    set_clock,
    setup_approved_refund_request,
    setup_multi_credit_scenario,
    setup_refunded_credit,
    validate_paginated,
    validate_success,
    void_check,
)

OFFICER = TEST_USERS["disbursement_officer_headers"]
ANALYST = TEST_USERS["credit_analyst_headers"]


def _medicare_refund_scenario(**overrides):
    """MEDICARE credit of 12,000 cents refunded through one issued check."""
    defaults = dict(
        payer_type="MEDICARE", payer_code="MCR", account_number="ACCT-IS1",
        financial_class="INPATIENT", payment_source="PAYER",
        root_cause_confirmed=True, payee_type="PAYER", approver_tier=2,
        requested_amount_cents=12_000, batch_number="B-IS",
        starting_check_number=400001,
    )
    defaults.update(overrides)
    return setup_refunded_credit(**defaults)


def _two_issued_checks():
    """Two COMMERCIAL 12,000-cent PATIENT credits issued in one check run."""
    scenario = setup_multi_credit_scenario(
        accounts=[{"account_number": "ACCT-BR1"}, {"account_number": "ACCT-BR2"}],
        state_code="TX",
    )
    scenario["credit_balances"] = attribute_all(
        [cb["id"] for cb in scenario["credit_balances"]]
    )
    scenario["refund_requests"] = [
        setup_approved_refund_request(
            credit_balance, requested_amount_cents=12_000, payee_type="PATIENT",
            payee_state_code="TX", payee_name=name,
        )
        for credit_balance, name in zip(
            scenario["credit_balances"], ("Bree Ross", "Brad Ross")
        )
    ]
    batch = open_batch("B-BRA", "2026-08-18T00:00:00Z", "2026-08-20T00:00:00Z")
    checks = [
        add_batch_item(batch["id"], request["id"])
        for request in scenario["refund_requests"]
    ]
    lock_batch(batch["id"])
    set_clock("2026-08-20T00:00:00Z")
    scenario["batch"] = issue_batch(batch["id"], 200001)
    scenario["checks"] = [read_check(check["id"]) for check in checks]
    return scenario


def test_issue_cascade_cuts_the_check_and_drives_the_request_and_ledger(api):
    """PRD §3.8: "- **Hop 1 — the checks.** Every `PENDING` check line in the run moves `PENDING → ISSUED`. Check numbers are assigned sequentially beginning at `starting_check_number`, handed out in ascending `created_at` order over the lines, and written to `check_number`. Each issued check takes an `issued_at` from the logical clock and a `stale_at` of exactly 180 days after its `issued_at`."
    PRD §3.8: "- **Hop 2 — the requests.** Each issued check drives its owning refund request `BATCHED → ISSUED` on the disbursement dimension."
    PRD §3.8: "- **Hop 3 — the ledger and the credit.** Each of those request transitions posts a `REFUND_DISBURSEMENT` ledger row of positive `gross_amount_cents` on the credit balance's account, then recomputes that credit balance's `refunded_cents` and `outstanding_cents`. When the recomputed `outstanding_cents` reaches 0, the credit balance moves `REFUND_PENDING → REFUNDED` and its `version` is bumped by 1."

    Design: Difficulty/transitive_cascade/batch_issue_cascade_check_to_request_to_credit_balance_to_obligation_satisfied
    """
    scenario = _medicare_refund_scenario()

    assert scenario["batch"]["state"] == "ISSUED"
    check = scenario["check"]
    assert check["state"] == "ISSUED"
    assert str(check["check_number"]) == "400001"
    assert_instant_equals(check["issued_at"], "2026-08-20T00:00:00Z", "issued_at")
    assert_instant_equals(check["stale_at"], "2027-02-16T00:00:00Z", "stale_at")
    assert read_refund_request(scenario["refund_request"]["id"])[
        "disbursement_state"
    ] == "ISSUED"

    disbursements = list_transactions(
        scenario["account"]["id"], txn_type="REFUND_DISBURSEMENT"
    )
    assert len(disbursements) == 1
    assert disbursements[0]["amount_cents"] == 12_000


def test_issue_cascade_settles_the_medicare_obligation_and_zeroes_the_account(api):
    """PRD §3.8: "- **Hop 4 — the obligation.** Every credit balance that reaches `REFUNDED` settles any Medicare repayment obligation attached to it. An obligation in `OPEN` or `REPORTED` moves to `SATISFIED`; an obligation in `LATE` or `REPORTED_LATE` moves to `SATISFIED_LATE` with its `penalty_cents` recomputed at satisfaction. In every case `satisfied_at` is stamped from the logical clock and `satisfaction_mode` is set to `REFUND_CHECK`."
    PRD §2.9: "Its `refunded_cents` is the sum of `gross_amount_cents` over the checks written against it whose `state` is `ISSUED`, `CLEARED`, `STALE`, `REISSUED` or `ESCHEATED` — a `PENDING` or `VOIDED` check contributes nothing."

    Design: Difficulty/transitive_cascade/batch_issue_cascade_check_to_request_to_credit_balance_to_obligation_satisfied
    """
    scenario = _medicare_refund_scenario()

    credit_balance = read_credit_balance(scenario["credit_balance"]["id"])
    assert credit_balance["status"] == "REFUNDED"
    assert credit_balance["refunded_cents"] == 12_000
    assert credit_balance["outstanding_cents"] == 0
    assert_credit_liability_invariant(credit_balance)

    obligation = read_obligation(scenario["obligation"]["id"])
    assert obligation["state"] == "SATISFIED"
    assert obligation["satisfaction_mode"] == "REFUND_CHECK"
    assert_instant_equals(
        obligation["satisfied_at"], "2026-08-20T00:00:00Z", "satisfied_at"
    )

    account = read_account(scenario["account"]["id"])
    assert account["balance_cents"] == 0
    assert account["credit_balance_cents"] == 0


def test_issue_cascade_effects_are_visible_in_the_same_request_cycle(api):
    """PRD §2.9: "The service treats these as ordered hops and applies them all before responding; a partially applied cascade is never observable."
    PRD §3.8: "- **Hop 3 — the ledger and the credit.** Each of those request transitions posts a `REFUND_DISBURSEMENT` ledger row of positive `gross_amount_cents` on the credit balance's account, then recomputes that credit balance's `refunded_cents` and `outstanding_cents`. When the recomputed `outstanding_cents` reaches 0, the credit balance moves `REFUND_PENDING → REFUNDED` and its `version` is bumped by 1."

    Design: Corner/consistency_model/issue_cascade_effects_are_visible_immediately_in_the_same_request_cycle
    """
    scenario = setup_refunded_credit(
        account_number="ACCT-IC1", batch_number="B-IC", starting_check_number=900001,
    )

    issue_response = scenario["batch"]
    assert issue_response["state"] == "ISSUED"
    assert issue_response["item_count"] == 1
    assert issue_response["total_gross_cents"] == 12_000
    assert issue_response["total_fee_cents"] == 280
    assert issue_response["total_net_cents"] == 11_720

    credit_balance = read_credit_balance(scenario["credit_balance"]["id"])
    assert credit_balance["status"] == "REFUNDED"
    assert credit_balance["refunded_cents"] == 12_000
    assert credit_balance["outstanding_cents"] == 0

    account = read_account(scenario["account"]["id"])
    assert account["balance_cents"] == 0
    assert account["credit_balance_cents"] == 0

    check = read_check(scenario["check"]["id"])
    assert check["state"] == "ISSUED"
    assert str(check["check_number"]) == "900001"
    assert_instant_equals(check["issued_at"], "2026-08-20T00:00:00Z", "issued_at")
    assert read_refund_request(scenario["refund_request"]["id"])[
        "disbursement_state"
    ] == "ISSUED"


def test_clearing_a_check_stamps_cleared_at_and_leaves_the_ledger_alone(api):
    """PRD §3.9: "The check moves `ISSUED → CLEARED` with `cleared_at` stamped from the logical clock, and the owning refund request moves `ISSUED → CLEARED` on the disbursement dimension. No ledger movement occurs and the credit stays consumed. `CLEARED` is terminal for the check."

    Design: Difficulty/non_linear_state_machine/check_disbursement_branch_fork_clear_versus_void_have_divergent_side_effects
    """
    scenario = _two_issued_checks()
    set_clock("2026-08-25T00:00:00Z")

    cleared = validate_success(
        api.clear_check(scenario["checks"][0]["id"], {}, OFFICER)
    )
    assert cleared["state"] == "CLEARED"
    assert_instant_equals(cleared["cleared_at"], "2026-08-25T00:00:00Z", "cleared_at")
    assert cleared["void_reason"] is None

    assert read_refund_request(scenario["refund_requests"][0]["id"])[
        "disbursement_state"
    ] == "CLEARED"

    credit_balance = read_credit_balance(scenario["credit_balances"][0]["id"])
    assert credit_balance["status"] == "REFUNDED"
    assert credit_balance["refunded_cents"] == 12_000
    assert read_account(scenario["accounts"][0]["id"])["balance_cents"] == 0


def test_voiding_the_sibling_check_rewinds_the_credit_the_clear_left_alone(api):
    """PRD §3.9: "The check moves to `VOIDED` with its `void_reason` recorded, and the full four-hop compensation of branch A's ledger effects runs."
    PRD §3.9: "Hop 2 moves the owning refund request `ISSUED → REISSUE_PENDING` on the disbursement dimension. Hop 3 recomputes the credit balance's `refunded_cents` — the voided check has left the counted set — and its `outstanding_cents`, moves it `REFUNDED → REFUND_PENDING` and bumps its `version` by 1."

    Design: Difficulty/non_linear_state_machine/check_disbursement_branch_fork_clear_versus_void_have_divergent_side_effects
    """
    scenario = _two_issued_checks()
    set_clock("2026-08-25T00:00:00Z")

    voided = validate_success(
        api.void_check(
            scenario["checks"][1]["id"], {"void_reason": "BATCH_ERROR"}, OFFICER
        )
    )
    assert voided["state"] == "VOIDED"
    assert voided["void_reason"] == "BATCH_ERROR"

    assert read_refund_request(scenario["refund_requests"][1]["id"])[
        "disbursement_state"
    ] == "REISSUE_PENDING"

    credit_balance = read_credit_balance(scenario["credit_balances"][1]["id"])
    assert credit_balance["status"] == "REFUND_PENDING"
    assert credit_balance["refunded_cents"] == 0
    assert credit_balance["outstanding_cents"] == 12_000
    assert_credit_liability_invariant(credit_balance)
    assert read_account(scenario["accounts"][1]["id"])["balance_cents"] == -12_000


def test_void_posts_a_reversal_and_walks_the_request_and_credit_backwards(api):
    """PRD §3.9: "Hop 1 posts a `REVERSAL` ledger row whose `reversal_of_transaction_id` names the check's original `REFUND_DISBURSEMENT` posting and whose `amount_cents` is that posting's exact negation."
    PRD §3.9: "Hop 2 moves the owning refund request `ISSUED → REISSUE_PENDING` on the disbursement dimension. Hop 3 recomputes the credit balance's `refunded_cents` — the voided check has left the counted set — and its `outstanding_cents`, moves it `REFUNDED → REFUND_PENDING` and bumps its `version` by 1."

    Design: Difficulty/transitive_cascade/void_check_cascade_check_to_request_to_credit_balance_to_medicare_obligation
    """
    scenario = _medicare_refund_scenario(
        account_number="ACCT-VC1", batch_number="B-VC", starting_check_number=300001,
    )
    set_clock("2026-08-25T00:00:00Z")

    voided = validate_success(
        api.void_check(scenario["check"]["id"], {"void_reason": "WRONG_PAYEE"}, OFFICER)
    )
    assert voided["state"] == "VOIDED"

    reversals = list_transactions(scenario["account"]["id"], txn_type="REVERSAL")
    assert len(reversals) == 1
    assert reversals[0]["amount_cents"] == -12_000
    assert reversals[0]["reversal_of_transaction_id"] is not None

    request = read_refund_request(scenario["refund_request"]["id"])
    assert request["disbursement_state"] == "REISSUE_PENDING"
    assert request["approval_state"] == "APPROVED"

    credit_balance = read_credit_balance(scenario["credit_balance"]["id"])
    assert credit_balance["status"] == "REFUND_PENDING"
    assert credit_balance["refunded_cents"] == 0
    assert credit_balance["outstanding_cents"] == 12_000


def test_void_reopens_the_medicare_obligation_with_recomputed_day_counts(api):
    """PRD §3.9: "Hop 4 reopens the Medicare obligation: an obligation in `SATISFIED` returns to `OPEN` when the logical clock is at or before its `due_at` and to `LATE` when the clock is past `due_at`; an obligation in `SATISFIED_LATE` returns to `LATE` unconditionally. In all three cases `satisfied_at` and `satisfaction_mode` are cleared and `days_elapsed`, `days_late` and `penalty_cents` are recomputed against the current logical clock."
    PRD §3.11: "`days_elapsed` is the whole floored days from `identified_at` to the logical clock."

    Design: Difficulty/transitive_cascade/void_check_cascade_check_to_request_to_credit_balance_to_medicare_obligation
    """
    scenario = _medicare_refund_scenario(
        account_number="ACCT-VC1", batch_number="B-VC", starting_check_number=300001,
    )
    set_clock("2026-08-25T00:00:00Z")
    void_check(scenario["check"]["id"], "WRONG_PAYEE")

    obligation = read_obligation(scenario["obligation"]["id"])
    assert obligation["state"] == "OPEN"
    assert obligation["satisfied_at"] is None
    assert obligation["satisfaction_mode"] is None
    assert obligation["days_elapsed"] == 10
    assert obligation["days_late"] == 0
    assert obligation["penalty_cents"] == 0

    account = read_account(scenario["account"]["id"])
    assert account["balance_cents"] == -12_000
    assert account["credit_balance_cents"] == 12_000


def test_open_credit_liability_drops_to_zero_when_the_check_is_issued(api):
    """PRD §2.9: "An account's `credit_balance_cents` is the sum of `credit_amount_cents` over the credit balance rows on that account whose `status` is `IDENTIFIED`, `UNDER_REVIEW`, `ATTRIBUTED` or `REFUND_PENDING`; those four statuses constitute open credit liability, and a credit balance in any other status contributes nothing."
    PRD §3.8: "When the recomputed `outstanding_cents` reaches 0, the credit balance moves `REFUND_PENDING → REFUNDED` and its `version` is bumped by 1."

    Design: Difficulty/compensating_invariant/open_credit_liability_conserved_across_check_issue_and_void
    """
    scenario = setup_refunded_credit(
        account_number="ACCT-IV1", state_code="TX", batch_number="B-IV",
        starting_check_number=700001, request_at=None,
    )

    account = read_account(scenario["account"]["id"])
    assert account["credit_balance_cents"] == 0
    credit_balance = read_credit_balance(scenario["credit_balance"]["id"])
    assert credit_balance["status"] == "REFUNDED"
    assert credit_balance["credit_amount_cents"] == 12_000
    assert_credit_liability_invariant(credit_balance)


def test_voiding_the_check_restores_the_open_credit_liability_exactly(api):
    """PRD §3.14: "First, the credit liability invariant: for any credit balance, `credit_amount_cents` always equals `refunded_cents` plus `offset_cents` plus `outstanding_cents`, and the same equality survives every compensating action because voided checks and reversed offsets leave their respective counted sets."
    PRD §3.9: "Hop 3 recomputes the credit balance's `refunded_cents` — the voided check has left the counted set — and its `outstanding_cents`, moves it `REFUNDED → REFUND_PENDING` and bumps its `version` by 1."

    Design: Difficulty/compensating_invariant/open_credit_liability_conserved_across_check_issue_and_void
    """
    scenario = setup_refunded_credit(
        account_number="ACCT-IV1", state_code="TX", batch_number="B-IV",
        starting_check_number=700001, request_at=None,
    )
    assert read_account(scenario["account"]["id"])["credit_balance_cents"] == 0

    set_clock("2026-08-25T00:00:00Z")
    void_check(scenario["check"]["id"], "WRONG_PAYEE")

    account = read_account(scenario["account"]["id"])
    assert account["credit_balance_cents"] == 12_000
    credit_balance = read_credit_balance(scenario["credit_balance"]["id"])
    assert credit_balance["status"] == "REFUND_PENDING"
    assert credit_balance["refunded_cents"] == 0
    assert credit_balance["outstanding_cents"] == 12_000
    assert credit_balance["credit_amount_cents"] == 12_000
    assert_credit_liability_invariant(credit_balance)


def test_reissue_cuts_a_successor_line_into_an_open_run(api):
    """PRD §3.9: "A successor check row is created with `reissue_of_disbursement_id` pointing at the predecessor, its fee and net recomputed by the four pinned steps of §3.8 (and subject to the same `ERR_NET_BELOW_MIN_CHECK` floor guard), and the owning refund request moves `REISSUE_PENDING → BATCHED` on the disbursement dimension so the cycle `BATCHED → ISSUED → REISSUE_PENDING → BATCHED` can run again."
    PRD §3.8: "A line is a check row created in `state` `PENDING`, carrying the `refund_request_id`, the `refund_batch_id` of the run, a `payee_state_code` copied from the refund request, and a `gross_amount_cents` frozen at the request's `approved_amount_cents` as of this moment."

    Design: Difficulty/non_linear_state_machine/refund_request_parallel_dimensions_disbursement_cycles_while_approval_frozen
    """
    scenario = _medicare_refund_scenario(
        account_number="ACCT-MA1", batch_number="B-001", starting_check_number=100001,
    )
    set_clock("2026-08-25T00:00:00Z")
    void_check(scenario["check"]["id"], "WRONG_PAYEE")
    second_batch = open_batch("B-002", "2026-08-26T00:00:00Z", "2026-08-28T00:00:00Z")

    successor = validate_success(
        api.reissue_check(
            scenario["check"]["id"], {"refund_batch_id": second_batch["id"]}, OFFICER
        ),
        201,
    )

    assert successor["reissue_of_disbursement_id"] == scenario["check"]["id"]
    assert successor["refund_batch_id"] == second_batch["id"]
    assert successor["state"] == "PENDING"
    assert successor["gross_amount_cents"] == 12_000
    assert successor["net_check_amount_cents"] == 11_720
    assert read_check(scenario["check"]["id"])["state"] == "VOIDED"


def test_disbursement_dimension_cycles_while_the_approval_dimension_stays_frozen(api):
    """PRD §3.9: "the owning refund request moves `REISSUE_PENDING → BATCHED` on the disbursement dimension so the cycle `BATCHED → ISSUED → REISSUE_PENDING → BATCHED` can run again."
    PRD §3.7: "In general, `approvals_received` is the count of approval records on the request whose `decision` is `APPROVED`, and `approved_amount_cents` is `requested_amount_cents` once and only once the request reaches `APPROVED`, and 0 in every other approval state."

    Design: Difficulty/non_linear_state_machine/refund_request_parallel_dimensions_disbursement_cycles_while_approval_frozen
    """
    scenario = _medicare_refund_scenario(
        account_number="ACCT-MA1", batch_number="B-001", starting_check_number=100001,
    )
    request_id = scenario["refund_request"]["id"]
    assert read_refund_request(request_id)["disbursement_state"] == "ISSUED"

    set_clock("2026-08-25T00:00:00Z")
    void_check(scenario["check"]["id"], "WRONG_PAYEE")
    assert read_refund_request(request_id)["disbursement_state"] == "REISSUE_PENDING"

    second_batch = open_batch("B-002", "2026-08-26T00:00:00Z", "2026-08-28T00:00:00Z")
    reissue_check(scenario["check"]["id"], second_batch["id"])

    request = read_refund_request(request_id)
    assert request["approval_state"] == "APPROVED"
    assert request["approvals_received"] == 1
    assert request["approved_amount_cents"] == 12_000
    assert request["disbursement_state"] == "BATCHED"
