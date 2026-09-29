"""State graphs that revisit states instead of marching forward.

A request for payment can walk `DELIVERED -> AMENDMENT_REQUESTED -> DELIVERED` more
than once; the loop is bounded by a counter rather than by the graph, so the third
traversal is refused on a business ground while the graph itself still allows it.

A credit transfer carries two independent dimensions, so the clearing dimension can
sit terminal on `SETTLED` while the exception dimension walks on by itself. And the
enrolment lifecycle re-enters certification testing after a failure, which the
round counter makes observable.
"""

from test_helpers import (
    activate_participant,
    amend_request_for_payment,
    assert_instant,
    assert_ledger_entry,
    assert_transfer_dimensions,
    certification_result_payload,
    decline_return_request,
    delivered_rfp_scenario,
    enroll_participant,
    ERR_AMENDMENT_ROUNDS_EXHAUSTED,
    ERR_INVALID_STATE_TRANSITION,
    file_attestation,
    list_ledger_entries,
    NETWORK_OPERATOR,
    open_certification_window,
    open_position_account,
    PAYMENT_OPERATOR_BETA,
    read_account,
    read_customer_account,
    read_participant,
    read_rfp,
    read_transfer,
    record_certification_result,
    respond_to_request_for_payment,
    return_requested_scenario,
    rfp_response_payload,
    set_clock,
    validate_error,
)


def test_third_amendment_round_is_refused_after_the_loop_runs_twice(api):
    """Two traversals of the amendment loop are allowed; the third is not.

    PRD 3.7: "At most two amendment rounds are permitted: a third attempt is refused
    with `ERR_AMENDMENT_ROUNDS_EXHAUSTED` even though the state machine itself would
    allow the hop, and an amendment attempted at or after `expiry_at` is refused with
    `ERR_RFP_EXPIRED`."

    PRD 3.7: "A `REQUEST_AMENDMENT` requires `amendment_round` to be strictly below 2,
    moves the request `DELIVERED -> AMENDMENT_REQUESTED`, and clears
    `response_deadline_at`."

    Because the round cap guards the `REQUEST_AMENDMENT` response as well as the
    amendment itself, `amendment_round` 2 is where the loop closes: the request cannot
    re-enter `AMENDMENT_REQUESTED` a third time, so the third attempt is refused on the
    response hop and the request stays `DELIVERED` at the twice-amended amount.

    Design: Difficulty/non_linear_state_machine/rfp_amendment_cycle_returns_to_delivered_until_round_cap
    """
    scenario, rfp = delivered_rfp_scenario(api, amount_cents=5_000_000, memo="Invoice INV-9001")

    respond_to_request_for_payment(api, rfp["id"], "REQUEST_AMENDMENT")
    first = amend_request_for_payment(api, rfp["id"], 4_500_000, memo="Invoice INV-9001 rev A")
    assert first["status"] == "DELIVERED"
    assert first["amendment_round"] == 1
    assert first["amount_cents"] == 4_500_000

    respond_to_request_for_payment(api, rfp["id"], "REQUEST_AMENDMENT")
    second = amend_request_for_payment(api, rfp["id"], 4_000_000, memo="Invoice INV-9001 rev B")
    assert second["status"] == "DELIVERED"
    assert second["amendment_round"] == 2
    assert second["amount_cents"] == 4_000_000

    validate_error(
        api.respond_to_request_for_payment(
            rfp["id"], rfp_response_payload("REQUEST_AMENDMENT"), PAYMENT_OPERATOR_BETA
        ),
        ERR_AMENDMENT_ROUNDS_EXHAUSTED,
    )

    unchanged = read_rfp(api, rfp["id"])
    assert unchanged["status"] == "DELIVERED"
    assert unchanged["amount_cents"] == 4_000_000
    assert unchanged["amendment_round"] == 2
    assert_instant(unchanged["expiry_at"], "2026-08-04T13:00:00Z", "expiry_at")


def test_amendment_loop_stops_and_restarts_the_response_clock(api):
    """Asking for an amendment clears the deadline; redelivery re-derives it.

    PRD 3.7: "A `REQUEST_AMENDMENT` requires `amendment_round` to be strictly below 2,
    moves the request `DELIVERED -> AMENDMENT_REQUESTED`, and clears
    `response_deadline_at` — the response clock stops while the requestor reworks the
    ask, and stays null until the amended request is redelivered."

    Design: Difficulty/non_linear_state_machine/rfp_amendment_cycle_returns_to_delivered_until_round_cap
    """
    scenario, rfp = delivered_rfp_scenario(api, amount_cents=5_000_000)
    assert rfp["status"] == "DELIVERED"
    assert_instant(rfp["delivered_at"], "2026-08-03T13:00:00Z", "delivered_at")
    assert_instant(rfp["response_deadline_at"], "2026-08-03T13:30:00Z", "response_deadline_at")

    set_clock(api, "2026-08-03T13:05:00Z")
    respond_to_request_for_payment(api, rfp["id"], "REQUEST_AMENDMENT")
    paused = read_rfp(api, rfp["id"])
    assert paused["status"] == "AMENDMENT_REQUESTED"
    assert paused["response_deadline_at"] is None
    assert paused["last_response"] == "REQUEST_AMENDMENT"

    set_clock(api, "2026-08-03T13:10:00Z")
    redelivered = amend_request_for_payment(api, rfp["id"], 4_500_000)
    assert redelivered["status"] == "DELIVERED"
    assert_instant(redelivered["delivered_at"], "2026-08-03T13:10:00Z", "delivered_at")
    assert_instant(redelivered["response_deadline_at"], "2026-08-03T13:40:00Z", "response_deadline_at")
    assert_instant(redelivered["expiry_at"], "2026-08-04T13:00:00Z", "expiry_at")
    assert redelivered["last_response"] is None


def test_declining_a_return_moves_only_the_exception_dimension(api):
    """The clearing dimension stays terminal while the exception dimension advances.

    PRD 3.8: "Because a settled instant payment cannot be rewound, the exception
    process runs on a *second, independent* state dimension of the same transfer row."

    Design: Difficulty/non_linear_state_machine/credit_transfer_clearing_and_exception_dimensions_advance_independently
    """
    scenario, transfer, request = return_requested_scenario(
        api,
        reason_code="WRONG_BENEFICIARY",
        returned_amount_cents=250_000_000,
        narrative="Beneficiary account number transposed.",
    )
    assert_transfer_dimensions(transfer, "SETTLED", "RETURN_REQUESTED")

    set_clock(api, "2026-08-03T13:25:00Z")
    declined = decline_return_request(api, request["id"], "FUNDS_DISBURSED")

    assert declined["status"] == "DECLINED"
    assert declined["decline_reason_code"] == "FUNDS_DISBURSED"
    assert_transfer_dimensions(read_transfer(api, transfer["id"]), "SETTLED", "RETURN_DECLINED")

    account = read_account(api, scenario.alpha.account_id)
    assert account["current_balance_cents"] == 950_000_000
    entries = list_ledger_entries(api, scenario.alpha.account_id)
    assert len(entries) == 1
    assert_ledger_entry(
        entries[0],
        entry_type="TRANSFER_DEBIT",
        amount_cents=-250_000_000,
        balance_after_cents=950_000_000,
        sequence_no=1,
        business_date="2026-08-03",
    )
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "SEND_FROZEN"


def test_declined_return_leaves_the_daily_usage_consumed(api):
    """No ledger movement and no counter relief follow a decline.

    PRD 3.8: "The request becomes `DECLINED`, the transfer's `exception_status` becomes
    `RETURN_DECLINED`, and nothing else moves: no ledger entry is posted, and
    `current_balance_cents`, `reserved_cents` and `daily_sent_amount_cents` are all
    left exactly as they were."

    Design: Difficulty/non_linear_state_machine/credit_transfer_clearing_and_exception_dimensions_advance_independently
    """
    scenario, transfer, request = return_requested_scenario(api)
    before = read_customer_account(api, scenario.alpha.customer_account_id)
    assert before["daily_sent_amount_cents"] == 250_000_000

    set_clock(api, "2026-08-03T13:25:00Z")
    decline_return_request(api, request["id"], "BENEFICIARY_REFUSED")

    after = read_customer_account(api, scenario.alpha.customer_account_id)
    assert after["daily_sent_amount_cents"] == 250_000_000
    account = read_account(api, scenario.alpha.account_id)
    assert account["current_balance_cents"] == 950_000_000
    assert account["reserved_cents"] == 0
    assert_transfer_dimensions(read_transfer(api, transfer["id"]), "SETTLED", "RETURN_DECLINED")


def test_certification_round_counts_the_second_visit_to_testing(api):
    """A failed window sends the bank to remediation and the next window is round 2.

    PRD 3.1: "That is the closed loop `CERTIFICATION_TESTING -> REMEDIATION ->
    CERTIFICATION_TESTING`, and each of the two result outcomes increments `version`."

    Design: Difficulty/non_linear_state_machine/participant_certification_remediation_revisit_cycle
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    participant = enroll_participant(api)
    open_position_account(api, participant["id"])
    file_attestation(api, participant["id"])

    first_window = open_certification_window(api, participant["id"])
    assert first_window["certification_round"] == 1
    assert first_window["enrollment_status"] == "CERTIFICATION_TESTING"

    failed = record_certification_result(api, participant["id"], "FAIL")
    assert failed["enrollment_status"] == "REMEDIATION"

    second_window = open_certification_window(api, participant["id"])
    assert second_window["certification_round"] == 2
    assert second_window["enrollment_status"] == "CERTIFICATION_TESTING"

    passed = record_certification_result(api, participant["id"], "PASS")
    assert passed["enrollment_status"] == "CERTIFIED"

    live = activate_participant(api, participant["id"], "2026-08-03")
    assert live["enrollment_status"] == "LIVE"
    assert live["operational_posture"] == "NORMAL"
    assert live["go_live_business_date"] == "2026-08-03"
    assert live["certification_round"] == 2


def test_result_cannot_be_recorded_while_the_bank_sits_in_remediation(api):
    """Remediation is a real state, not a label: only a testing window takes results.

    PRD 3.1: "Recording the window's `outcome` is only permitted while the participant
    sits in `CERTIFICATION_TESTING`: an outcome of `PASS` advances `CERTIFICATION_TESTING
    -> CERTIFIED`, while `FAIL` sends it to `REMEDIATION`, from which a fresh window may
    be opened."

    Design: Difficulty/non_linear_state_machine/participant_certification_remediation_revisit_cycle
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    participant = enroll_participant(api)
    open_position_account(api, participant["id"])
    file_attestation(api, participant["id"])
    open_certification_window(api, participant["id"])
    record_certification_result(api, participant["id"], "FAIL")

    response = api.record_certification_result(
        participant["id"], certification_result_payload("PASS"), NETWORK_OPERATOR
    )
    validate_error(response, ERR_INVALID_STATE_TRANSITION)

    stalled = read_participant(api, participant["id"])
    assert stalled["enrollment_status"] == "REMEDIATION"
    assert stalled["certification_round"] == 1
