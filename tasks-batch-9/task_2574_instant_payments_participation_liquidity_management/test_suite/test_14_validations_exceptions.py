"""Refusals on the exception, fraud and limit layers, where the ladder picks the words.

The requests here are all plausible: the sending bank asking for its own money
back, an analyst deciding an item nobody has taken, a payment quoting an accepted
request but re-pricing it, a return lodged exactly seventy-two hours after
settlement, an honour landing exactly on its deadline. Each is refused, and in
every case the interesting part is which of the several applicable rules is the
one reported and what the refusal leaves untouched: no row, no ledger entry, no
compensating transfer, and no counter relief.
"""

from test_helpers import (
    alpha_and_beta_scenario,
    alpha_scenario,
    assert_instant,
    assert_pagination_meta,
    assert_reconciliation_figures,
    assert_sweep_counts,
    assert_transfer_dimensions,
    assign_review,
    close_cycle,
    CORE_BANKING_SYSTEM,
    CORE_BANKING_SYSTEM_BETA,
    credit_transfer_payload,
    cutoff_cycle,
    decide_review,
    decline_return_request,
    deliver_request_for_payment,
    ERR_CUSTOMER_ACCOUNT_RESTRICTED,
    ERR_DAILY_LIMIT_EXCEEDED,
    ERR_DUPLICATE_RETURN_REQUEST,
    ERR_FRAUD_REVIEW_NOT_ASSIGNED,
    ERR_PER_TRANSACTION_LIMIT_EXCEEDED,
    ERR_RETURN_AMOUNT_INVALID,
    ERR_RETURN_REQUESTOR_NOT_RECEIVER,
    ERR_RETURN_RESPONSE_DEADLINE_PASSED,
    ERR_RETURN_WINDOW_EXPIRED,
    ERR_RFP_EXPIRED,
    ERR_RFP_FULFILMENT_MISMATCH,
    ERR_VARIANCE_UNRESOLVED,
    fraud_decision_payload,
    FRAUD_REVIEWER,
    held_transfer_scenario,
    list_fraud_reviews,
    list_ledger_entries,
    list_return_requests,
    list_transfers_with_meta,
    lodge_return_request,
    NETWORK_OPERATOR,
    PAYMENT_OPERATOR_ALPHA,
    PAYMENT_OPERATOR_BETA,
    raise_request_for_payment,
    read_account,
    read_customer_account,
    read_cycle,
    read_participant,
    read_return_request,
    read_rfp,
    read_transfer,
    register_customer_account,
    respond_to_request_for_payment,
    return_request_payload,
    RETURN_REQUEST_WINDOW_MINUTES,
    return_requested_scenario,
    RETURN_RESPONSE_SLA_MINUTES,
    rfp_response_payload,
    RFP_RESPONSE_SLA_MINUTES,
    ROUTING_ALPHA,
    ROUTING_BETA,
    run_sweep,
    send_from_alpha,
    set_clock,
    settled_transfer_scenario,
    submit_reconciliation_run,
    validate_error,
)

DAILY_TIGHT_POLICY = {
    "daily_aggregate_limit_cents": 400_000_000,
    "rolling_window_amount_limit_cents": 1_000_000_000,
}


def test_the_sending_bank_cannot_claw_back_its_own_settled_payment(api):
    """The lodging side is identified by routing number, not by who has the interest.

    PRD 3.8: "Only the counterparty side may lodge it: the requesting participant's
    `routing_number` must equal the transfer's `receiver_routing_number`, so the bank that
    sent the payment cannot ask for its own money back, and a wrong-side attempt is
    refused with `ERR_RETURN_REQUESTOR_NOT_RECEIVER`."

    Design: Corner/validations/originator_cannot_request_return_of_own_transfer
    """
    scenario, transfer = settled_transfer_scenario(api, amount_cents=50_000_000)
    assert scenario.beta is not None
    assert_transfer_dimensions(transfer, "SETTLED", "NONE")
    assert read_participant(api, scenario.alpha.id)["routing_number"] == ROUTING_ALPHA
    assert transfer["receiver_routing_number"] == ROUTING_BETA

    validate_error(
        api.create_return_request(
            return_request_payload(
                transfer["id"],
                scenario.alpha.id,
                reason_code="FRAUD_SUSPECTED",
                narrative="Originator attempts to claw back its own payment.",
            ),
            PAYMENT_OPERATOR_ALPHA,
        ),
        ERR_RETURN_REQUESTOR_NOT_RECEIVER,
    )

    assert list_return_requests(api) == []
    assert_transfer_dimensions(read_transfer(api, transfer["id"]), "SETTLED", "NONE")
    assert read_account(api, scenario.alpha.account_id)["current_balance_cents"] == 1_150_000_000

    admitted = lodge_return_request(
        api,
        transfer["id"],
        scenario.beta.id,
        reason_code="FRAUD_SUSPECTED",
        narrative="Receiving side lodges the exception.",
    )
    assert admitted["status"] == "REQUESTED"
    assert admitted["requested_by_participant_id"] == scenario.beta.id
    assert_transfer_dimensions(
        read_transfer(api, transfer["id"]), "SETTLED", "RETURN_REQUESTED"
    )


def test_a_queued_review_cannot_be_decided_before_anyone_takes_it(api):
    """The not-assigned rung fires ahead of any segregation comparison.

    PRD 3.5: "Deciding the item requires it to be `UNDER_REVIEW`; a decision attempted
    while the review is still `QUEUED` is refused with `ERR_FRAUD_REVIEW_NOT_ASSIGNED`,
    which is the precise reason the assignment step cannot be skipped."

    PRD 3.4: "A score of at least 60 but below 85 is held: the transfer moves `INITIATED
    → FRAUD_HOLD`, its amount **stays** inside the reservation set because `FRAUD_HOLD` is
    one of the three reserving states, and one `FraudReview` is created in `QUEUED` status
    with `credit_transfer_id` pointing at the transfer, `score_at_origination` copied from
    the frozen score, `sla_deadline_at` still null, and `queue_priority` set to 1 when
    `score_at_origination` is at least 75 — that is, within 10 points of the block
    threshold — and 2 otherwise, with the lower value worked first."

    Design: Corner/validations/fraud_review_decision_before_assignment_rejected
    """
    scenario, transfer, review = held_transfer_scenario(api)
    assert transfer["clearing_status"] == "FRAUD_HOLD"
    assert transfer["fraud_score"] == 63

    validate_error(
        api.decide_fraud_review(
            review["id"],
            fraud_decision_payload("RELEASE", "Known counterparty."),
            FRAUD_REVIEWER,
        ),
        ERR_FRAUD_REVIEW_NOT_ASSIGNED,
    )

    queued = list_fraud_reviews(api, transfer["id"])[0]
    assert queued["status"] == "QUEUED"
    assert queued["assigned_reviewer_user_id"] is None
    assert queued["sla_deadline_at"] is None
    assert queued["score_at_origination"] == 63
    assert queued["queue_priority"] == 2

    still_held = read_transfer(api, transfer["id"])
    assert still_held["clearing_status"] == "FRAUD_HOLD"
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 50_000_000

    assigned = assign_review(api, review["id"])
    assert assigned["status"] == "UNDER_REVIEW"
    released = decide_review(api, review["id"], "RELEASE", "Known counterparty.")
    assert released["status"] == "RELEASED"
    assert read_transfer(api, transfer["id"])["clearing_status"] == "INITIATED"


def test_a_restricted_debtor_outranks_an_over_limit_amount(api):
    """One request breaks two rules and the account-safety rung is the one reported.

    PRD 2.11: "When a single request violates more than one rule, the caller must receive
    a predictable answer, so the checks form one global ladder and the **first** violated
    rung determines the response."

    PRD 3.4: "The debtor customer account must be `ACTIVE`, or the send fails with
    `ERR_CUSTOMER_ACCOUNT_RESTRICTED`."

    PRD 3.5: "The transfer moves `FRAUD_HOLD → REJECTED` with `rejection_reason_code`
    written as `FRAUD_BLOCK_REVIEW`, and its amount leaves the reservation set, so the
    account's `reserved_cents` drops and `available_cents` rises."

    PRD 3.4: "First the amount is compared with the pinned policy's
    `per_transaction_limit_cents`; the comparison is at-most, so an amount exactly equal to
    the limit is admitted and anything larger is refused with
    `ERR_PER_TRANSACTION_LIMIT_EXCEEDED`."

    Design: Corner/validations/restricted_account_error_outranks_per_transaction_limit
    """
    scenario, transfer, review = held_transfer_scenario(api)
    assert scenario.alpha.policy["per_transaction_limit_cents"] == 250_000_000

    assign_review(api, review["id"])
    blocked = decide_review(api, review["id"], "BLOCK", "Confirmed mule account.")
    assert blocked["status"] == "BLOCKED"
    assert blocked["final_fraud_score"] == 63

    rejected = read_transfer(api, transfer["id"])
    assert rejected["clearing_status"] == "REJECTED"
    assert rejected["rejection_reason_code"] == "FRAUD_BLOCK_REVIEW"

    restricted = read_customer_account(api, scenario.alpha.customer_account_id)
    assert restricted["status"] == "RESTRICTED"

    account = read_account(api, scenario.alpha.account_id)
    assert account["reserved_cents"] == 0
    assert account["available_cents"] == 1_200_000_000

    validate_error(
        api.create_credit_transfer(
            credit_transfer_payload(
                scenario.alpha.id,
                scenario.alpha.customer_account_id,
                300_000_000,
                account["version"],
            ),
            PAYMENT_OPERATOR_ALPHA,
        ),
        ERR_CUSTOMER_ACCOUNT_RESTRICTED,
    )

    replacement = register_customer_account(
        api, scenario.alpha.id, account_reference="CUST-ALPHA-0003"
    )
    assert replacement["status"] == "ACTIVE"
    assert replacement["segment"] == "CORPORATE"

    validate_error(
        api.create_credit_transfer(
            credit_transfer_payload(
                scenario.alpha.id,
                replacement["id"],
                300_000_000,
                account["version"],
            ),
            PAYMENT_OPERATOR_ALPHA,
        ),
        ERR_PER_TRANSACTION_LIMIT_EXCEEDED,
    )

    _rows, meta = list_transfers_with_meta(api)
    assert_pagination_meta(meta, total_count=1, has_more=False)


def test_two_admissible_sends_together_break_the_daily_aggregate(api):
    """Daily exposure counts the still-unsettled first send, so the second is refused.

    PRD 3.4: "The in-flight part adds the summed `amount_cents` of that customer's outbound
    transfers in `INITIATED`, `FRAUD_HOLD`, `QUEUED_THROTTLED` or `ACCEPTED` whose
    `created_at` falls on the current business date."

    PRD 3.4: "The sum of those two parts is the customer's daily exposure, and the exposure
    plus this send's amount must not exceed the pinned policy's
    `daily_aggregate_limit_cents`, otherwise the send is refused with
    `ERR_DAILY_LIMIT_EXCEEDED`."

    PRD 3.4: "The conserved part, mirrored on the customer account as
    `daily_sent_amount_cents`, is the summed `amount_cents` of that customer's outbound
    transfers whose `clearing_status` is `SETTLED`, whose `settlement_business_date` equals
    the current business date, and whose `exception_status` is anything other than
    `RETURN_HONORED`."

    Design: Corner/validations/daily_aggregate_limit_exceeded_by_second_transfer
    """
    scenario = alpha_scenario(api, policy=DAILY_TIGHT_POLICY)
    policy = scenario.alpha.policy
    assert policy["per_transaction_limit_cents"] == 250_000_000
    assert policy["daily_aggregate_limit_cents"] == 400_000_000
    assert policy["rolling_window_count_limit"] == 5
    assert policy["rolling_window_amount_limit_cents"] == 1_000_000_000

    first = send_from_alpha(api, scenario, 250_000_000)
    assert first["clearing_status"] == "INITIATED"
    assert first["fraud_score"] == 57

    customer = read_customer_account(api, scenario.alpha.customer_account_id)
    assert customer["daily_sent_amount_cents"] == 0

    account = read_account(api, scenario.alpha.account_id)
    validate_error(
        api.create_credit_transfer(
            credit_transfer_payload(
                scenario.alpha.id,
                scenario.alpha.customer_account_id,
                200_000_000,
                account["version"],
            ),
            PAYMENT_OPERATOR_ALPHA,
        ),
        ERR_DAILY_LIMIT_EXCEEDED,
    )

    _rows, meta = list_transfers_with_meta(api)
    assert_pagination_meta(meta, total_count=1, has_more=False)
    reserved = read_account(api, scenario.alpha.account_id)
    assert reserved["reserved_cents"] == 250_000_000
    assert reserved["available_cents"] == 950_000_000

    exact = send_from_alpha(api, scenario, 150_000_000)
    assert exact["clearing_status"] == "INITIATED"
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 400_000_000


def test_an_amount_exactly_equal_to_the_limit_is_admitted(api):
    """The comparison is at-most, and the same send stays far clear of the floor.

    PRD 3.4: "First the amount is compared with the pinned policy's
    `per_transaction_limit_cents`; the comparison is at-most, so an amount exactly equal to
    the limit is admitted and anything larger is refused with
    `ERR_PER_TRANSACTION_LIMIT_EXCEEDED`."

    PRD 2.7: "As a convenience summary of the tightest cases: a transfer amount exactly
    equal to a per-transaction limit is admitted; a send that lands available liquidity
    exactly on the regulatory floor is admitted; a balance exactly equal to the critical
    threshold is a `RED` band rather than `AMBER`; a balance exactly equal to the floor is
    also `RED`, because only a balance strictly below the floor is a `BREACH`; a
    reconciliation variance whose magnitude is exactly the tolerance is `BALANCED`; and an
    operation attempted at exactly a deadline or expiry instant is late."

    Design: Corner/validations/transfer_at_exact_per_transaction_limit_admitted
    """
    scenario = alpha_scenario(api)
    assert scenario.alpha.policy["per_transaction_limit_cents"] == 250_000_000
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "NORMAL"

    admitted = send_from_alpha(api, scenario, 250_000_000)
    assert_transfer_dimensions(admitted, "INITIATED", "NONE")
    assert admitted["amount_cents"] == 250_000_000
    assert admitted["fraud_score"] == 57
    assert admitted["fraud_reason_codes"] == ["AMOUNT_BAND", "NEW_BENEFICIARY"]
    assert list_fraud_reviews(api, admitted["id"]) == []

    account = read_account(api, scenario.alpha.account_id)
    assert account["reserved_cents"] == 250_000_000
    assert account["available_cents"] == 950_000_000
    assert account["current_balance_cents"] == 1_200_000_000
    assert account["alert_tier"] == "GREEN"

    validate_error(
        api.create_credit_transfer(
            credit_transfer_payload(
                scenario.alpha.id,
                scenario.alpha.customer_account_id,
                250_000_001,
                account["version"],
            ),
            PAYMENT_OPERATOR_ALPHA,
        ),
        ERR_PER_TRANSACTION_LIMIT_EXCEEDED,
    )


def test_a_fulfilling_transfer_may_not_re_price_the_accepted_request(api):
    """An accepted request unlocks exactly one transfer, to the cent.

    PRD 3.4: "When the send names an `rfp_id`, three coherence conditions apply together:
    the referenced request must be in `ACCEPTED` status, its `debtor_customer_account_id`
    must equal the transfer's `customer_account_id`, and the transfer's `amount_cents` must
    equal the request's `amount_cents` exactly — partial and over-payment of a request are
    both refused with `ERR_RFP_FULFILMENT_MISMATCH`."

    PRD 3.7: "Delivery stamps `delivered_at` with the clock and sets `response_deadline_at`
    to whichever is earlier of the request's `expiry_at` and the delivery instant plus 30
    minutes — the message response service level — and increments the request's `version`."

    Design: Corner/validations/fulfilling_transfer_amount_differs_from_accepted_rfp_rejected
    """
    assert RFP_RESPONSE_SLA_MINUTES == 30
    scenario = alpha_and_beta_scenario(api)
    assert scenario.beta is not None

    raised = raise_request_for_payment(
        api,
        scenario.beta.id,
        scenario.alpha.customer_account_id,
        5_000_000,
        "2026-08-04T13:00:00Z",
        operator=PAYMENT_OPERATOR_BETA,
        memo="Invoice INV-9001",
    )
    delivered = deliver_request_for_payment(api, raised["id"])
    assert_instant(delivered["response_deadline_at"], "2026-08-03T13:30:00Z", "response_deadline_at")
    accepted = respond_to_request_for_payment(
        api, raised["id"], "ACCEPT", operator=PAYMENT_OPERATOR_ALPHA
    )
    assert accepted["status"] == "ACCEPTED"

    account = read_account(api, scenario.alpha.account_id)
    validate_error(
        api.create_credit_transfer(
            credit_transfer_payload(
                scenario.alpha.id,
                scenario.alpha.customer_account_id,
                6_000_000,
                account["version"],
                rfp_id=raised["id"],
            ),
            PAYMENT_OPERATOR_ALPHA,
        ),
        ERR_RFP_FULFILMENT_MISMATCH,
    )

    unchanged = read_rfp(api, raised["id"])
    assert unchanged["status"] == "ACCEPTED"
    assert unchanged["amount_cents"] == 5_000_000
    assert unchanged["last_response"] == "ACCEPT"
    assert_instant(unchanged["response_deadline_at"], "2026-08-03T13:30:00Z", "response_deadline_at")

    _rows, meta = list_transfers_with_meta(api)
    assert_pagination_meta(meta, total_count=0, has_more=False)
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 0

    fulfilling = send_from_alpha(api, scenario, 5_000_000, rfp_id=raised["id"])
    assert fulfilling["clearing_status"] == "INITIATED"
    assert fulfilling["amount_cents"] == 5_000_000
    assert fulfilling["rfp_id"] == raised["id"]


def test_a_response_landing_exactly_on_the_deadline_is_late(api):
    """The deadline is the earlier of expiry and delivery plus thirty minutes.

    PRD 3.7: "All three branches require the request to be `DELIVERED` and require the
    clock to be strictly before `response_deadline_at`; a response at or after that instant,
    or at or after `expiry_at`, is refused with `ERR_RFP_EXPIRED`."

    PRD 3.7: "From any of `CREATED`, `DELIVERED` or `AMENDMENT_REQUESTED`, a request whose
    `expiry_at` has been reached by the clock becomes `EXPIRED` during the housekeeping
    sweep, and no other record is touched by that hop."

    Design: Corner/validations/rfp_response_at_response_deadline_instant_rejected
    """
    scenario = alpha_and_beta_scenario(api)
    assert scenario.beta is not None

    raised = raise_request_for_payment(
        api,
        scenario.beta.id,
        scenario.alpha.customer_account_id,
        5_000_000,
        "2026-08-03T13:20:00Z",
        operator=PAYMENT_OPERATOR_BETA,
        memo="Invoice INV-9002",
    )
    delivered = deliver_request_for_payment(api, raised["id"])
    assert_instant(delivered["delivered_at"], "2026-08-03T13:00:00Z", "delivered_at")
    assert_instant(delivered["response_deadline_at"], "2026-08-03T13:20:00Z", "response_deadline_at")

    set_clock(api, "2026-08-03T13:20:00Z")
    validate_error(
        api.respond_to_request_for_payment(
            raised["id"], rfp_response_payload("ACCEPT"), PAYMENT_OPERATOR_ALPHA
        ),
        ERR_RFP_EXPIRED,
    )

    stalled = read_rfp(api, raised["id"])
    assert stalled["status"] == "DELIVERED"
    assert stalled["last_response"] is None
    assert_instant(stalled["delivered_at"], "2026-08-03T13:00:00Z", "delivered_at")
    assert_instant(stalled["response_deadline_at"], "2026-08-03T13:20:00Z", "response_deadline_at")

    report = run_sweep(api)
    assert_sweep_counts(
        report,
        expired_rfp_count=1,
        expired_return_request_count=0,
        expired_transfer_count=0,
        escalated_alert_count=0,
    )
    assert read_rfp(api, raised["id"])["status"] == "EXPIRED"


def test_closure_waits_for_every_live_bank_not_only_the_ones_that_reported(api):
    """Alpha balanced and drove the cycle to RECONCILING; Beta never filed at all.

    PRD 3.10: "It is permitted only from `RECONCILING`, and only when every participant
    whose `enrollment_status` is `LIVE` has at least one `FINAL` run for the cycle and each
    of those participants' highest-revision `FINAL` run reports `BALANCED`; otherwise the
    attempt is refused with `ERR_VARIANCE_UNRESOLVED`."

    PRD 3.10: "The first `FINAL` run moves the cycle `CUTOFF → RECONCILING`, except that the
    cycle lands in `OUT_OF_BALANCE` instead when any `LIVE` participant's highest-revision
    `FINAL` run for the cycle reports `OUT_OF_BALANCE`."

    PRD 3.10: "Closure stamps `closed_at`, moves the cycle `RECONCILING → RECONCILED` and
    increments its `version`."

    Design: Corner/validations/cycle_closure_with_participant_missing_final_run_rejected
    """
    scenario = alpha_and_beta_scenario(api)
    assert scenario.beta is not None
    cycle_id = scenario.cycle_id

    cut = cutoff_cycle(api, cycle_id)
    assert cut["status"] == "CUTOFF"
    assert cut["assessed_fee_total_cents"] == 0
    assert cut["settled_transfer_count"] == 0

    alpha_run = submit_reconciliation_run(
        api, cycle_id, scenario.alpha.id, 0, platform=CORE_BANKING_SYSTEM
    )
    assert_reconciliation_figures(
        alpha_run,
        rail_net_position_cents=0,
        variance_cents=0,
        outcome="BALANCED",
        included_transfer_count=0,
        fee_component_cents=0,
        revision=1,
    )
    assert alpha_run["variant"] == "FINAL"
    assert read_cycle(api, cycle_id)["status"] == "RECONCILING"

    validate_error(
        api.close_settlement_cycle(cycle_id, NETWORK_OPERATOR),
        ERR_VARIANCE_UNRESOLVED,
    )

    stalled = read_cycle(api, cycle_id)
    assert stalled["status"] == "RECONCILING"
    assert stalled["closed_at"] is None
    assert stalled["assessed_fee_total_cents"] == 0

    beta_run = submit_reconciliation_run(
        api, cycle_id, scenario.beta.id, 0, platform=CORE_BANKING_SYSTEM_BETA
    )
    assert beta_run["outcome"] == "BALANCED"
    assert beta_run["variance_cents"] == 0

    closed = close_cycle(api, cycle_id)
    assert closed["status"] == "RECONCILED"
    assert_instant(closed["closed_at"], "2026-08-03T13:00:00Z", "closed_at")


def test_a_return_may_not_ask_for_more_than_was_sent(api):
    """One cent above the original is refused; omitting the field asks for all of it.

    PRD 3.8: "`returned_amount_cents` is optional; when it is supplied it must be greater
    than zero and no greater than the original transfer's `amount_cents`, and a zero,
    negative or excessive figure is refused with `ERR_RETURN_AMOUNT_INVALID`."

    PRD 3.8: "When it is omitted it defaults to the full original amount."

    Design: Corner/validations/return_amount_above_original_rejected
    """
    scenario, transfer = settled_transfer_scenario(api, amount_cents=50_000_000)
    assert scenario.beta is not None
    assert transfer["amount_cents"] == 50_000_000

    validate_error(
        api.create_return_request(
            return_request_payload(
                transfer["id"],
                scenario.beta.id,
                reason_code="WRONG_BENEFICIARY",
                returned_amount_cents=50_000_001,
                narrative="Receiver asks back one cent more than it received.",
            ),
            PAYMENT_OPERATOR_BETA,
        ),
        ERR_RETURN_AMOUNT_INVALID,
    )

    assert list_return_requests(api) == []
    assert_transfer_dimensions(read_transfer(api, transfer["id"]), "SETTLED", "NONE")
    assert read_account(api, scenario.alpha.account_id)["current_balance_cents"] == 1_150_000_000
    entries = list_ledger_entries(api, scenario.alpha.account_id)
    assert len(entries) == 1
    assert entries[0]["entry_type"] == "TRANSFER_DEBIT"

    admitted = lodge_return_request(
        api, transfer["id"], scenario.beta.id, reason_code="WRONG_BENEFICIARY"
    )
    assert admitted["status"] == "REQUESTED"
    assert admitted["returned_amount_cents"] == 50_000_000
    assert admitted["original_amount_cents"] == 50_000_000


def test_the_exception_dimension_can_only_be_claimed_once(api):
    """A second lodgement is refused while the first is open, and after it closes too.

    PRD 3.8: "The exception dimension is one-shot: a transfer whose `exception_status` is
    anything other than `NONE` may not be lodged against again, whether a first request is
    still `REQUESTED` or the dimension has already reached `RETURN_HONORED`,
    `RETURN_DECLINED` or `RETURN_EXPIRED`, and the second attempt is refused with
    `ERR_DUPLICATE_RETURN_REQUEST`."

    PRD 3.8: "A successful lodgement creates the request in `REQUESTED` with
    `original_amount_cents` copied from the transfer as it stands, with
    `response_deadline_at` set to the lodgement instant plus 1,440 minutes (twenty-four
    hours), and with a null `decline_reason_code` and null `honored_transfer_id`; the
    transfer's `exception_status` moves `NONE → RETURN_REQUESTED` while its
    `clearing_status` stays `SETTLED`, and the transfer's `version` is incremented."

    Design: Corner/validations/second_return_request_for_same_transfer_rejected
    """
    assert RETURN_RESPONSE_SLA_MINUTES == 1440
    scenario, transfer, first = return_requested_scenario(
        api, amount_cents=50_000_000, reason_code="DUPLICATE_PAYMENT"
    )
    assert scenario.beta is not None
    assert first["status"] == "REQUESTED"
    assert_instant(first["response_deadline_at"], "2026-08-04T13:20:00Z", "response_deadline_at")

    def second_lodgement():
        return api.create_return_request(
            return_request_payload(
                transfer["id"],
                scenario.beta.id,
                reason_code="TECHNICAL_ERROR",
                returned_amount_cents=50_000_000,
                narrative="Second lodgement while the first is open.",
            ),
            PAYMENT_OPERATOR_BETA,
        )

    validate_error(second_lodgement(), ERR_DUPLICATE_RETURN_REQUEST)

    rows = list_return_requests(api)
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["status"] == "REQUESTED"
    assert rows[0]["reason_code"] == "DUPLICATE_PAYMENT"
    assert rows[0]["original_amount_cents"] == 50_000_000
    assert_transfer_dimensions(
        read_transfer(api, transfer["id"]), "SETTLED", "RETURN_REQUESTED"
    )

    declined = decline_return_request(api, first["id"], "FUNDS_DISBURSED")
    assert declined["status"] == "DECLINED"
    assert_transfer_dimensions(
        read_transfer(api, transfer["id"]), "SETTLED", "RETURN_DECLINED"
    )

    validate_error(second_lodgement(), ERR_DUPLICATE_RETURN_REQUEST)
    assert len(list_return_requests(api)) == 1


def test_a_return_lodged_exactly_seventy_two_hours_after_settlement_is_late(api):
    """The window is half-open on settled_at, so the boundary instant is out of time.

    PRD 3.8: "A return must be lodged within 4,320 minutes (three days) of the transfer's
    `settled_at`, and the window is half-open: a request lodged 4,319 minutes after
    settlement is in time, while one lodged at exactly 4,320 minutes is refused with
    `ERR_RETURN_WINDOW_EXPIRED`."

    Design: Corner/validations/return_request_at_window_boundary_rejected
    """
    assert RETURN_REQUEST_WINDOW_MINUTES == 4320
    scenario, transfer = settled_transfer_scenario(
        api, amount_cents=50_000_000, settlement_clock="2026-08-03T13:00:00Z"
    )
    assert scenario.beta is not None
    assert_instant(transfer["settled_at"], "2026-08-03T13:00:00Z", "settled_at")

    set_clock(api, "2026-08-06T13:00:00Z")
    validate_error(
        api.create_return_request(
            return_request_payload(
                transfer["id"],
                scenario.beta.id,
                reason_code="WRONG_BENEFICIARY",
                returned_amount_cents=50_000_000,
                narrative="Lodged exactly on the window boundary.",
            ),
            PAYMENT_OPERATOR_BETA,
        ),
        ERR_RETURN_WINDOW_EXPIRED,
    )

    assert list_return_requests(api) == []
    untouched = read_transfer(api, transfer["id"])
    assert_instant(untouched["settled_at"], "2026-08-03T13:00:00Z", "settled_at")
    assert_transfer_dimensions(untouched, "SETTLED", "NONE")
    assert read_account(api, scenario.alpha.account_id)["current_balance_cents"] == 1_150_000_000


def test_a_return_lodged_one_minute_inside_the_window_is_admitted(api):
    """4,319 minutes after settlement is still in time, which pins the boundary.

    PRD 3.8: "A return must be lodged within 4,320 minutes (three days) of the transfer's
    `settled_at`, and the window is half-open: a request lodged 4,319 minutes after
    settlement is in time, while one lodged at exactly 4,320 minutes is refused with
    `ERR_RETURN_WINDOW_EXPIRED`."

    Design: Corner/validations/return_request_at_window_boundary_rejected
    """
    scenario, transfer = settled_transfer_scenario(
        api, amount_cents=50_000_000, settlement_clock="2026-08-03T13:00:00Z"
    )
    assert scenario.beta is not None
    assert_instant(transfer["settled_at"], "2026-08-03T13:00:00Z", "settled_at")

    set_clock(api, "2026-08-06T12:59:00Z")
    admitted = lodge_return_request(
        api,
        transfer["id"],
        scenario.beta.id,
        reason_code="WRONG_BENEFICIARY",
        returned_amount_cents=50_000_000,
        narrative="Lodged one minute inside the window.",
    )
    assert admitted["status"] == "REQUESTED"
    assert admitted["returned_amount_cents"] == 50_000_000
    assert_instant(admitted["response_deadline_at"], "2026-08-07T12:59:00Z", "response_deadline_at")
    assert_transfer_dimensions(
        read_transfer(api, transfer["id"]), "SETTLED", "RETURN_REQUESTED"
    )


def test_an_honour_at_the_response_deadline_never_compensates_the_money(api):
    """The refusal is the deadline rule, not a state rule: the request is still REQUESTED.

    PRD 3.8: "It requires the request to still be `REQUESTED`, requires the clock to be
    strictly before `response_deadline_at` (an honour at exactly the deadline is refused
    with `ERR_RETURN_RESPONSE_DEADLINE_PASSED`), and requires the stored
    `returned_amount_cents` to be non-null and no greater than `original_amount_cents`."

    PRD 3.10: "It expires every `REQUESTED` return request whose `response_deadline_at` the
    clock has reached, setting the underlying transfer's `exception_status` to
    `RETURN_EXPIRED`, reported as `expired_return_request_count`."

    Design: Corner/validations/return_honor_at_response_deadline_rejected
    """
    scenario, transfer, request = return_requested_scenario(
        api,
        amount_cents=50_000_000,
        settlement_clock="2026-08-03T13:00:00Z",
        lodgement_clock="2026-08-03T13:00:00Z",
    )
    assert_instant(request["response_deadline_at"], "2026-08-04T13:00:00Z", "response_deadline_at")

    set_clock(api, "2026-08-04T13:00:00Z")
    validate_error(
        api.honor_return_request(request["id"], NETWORK_OPERATOR),
        ERR_RETURN_RESPONSE_DEADLINE_PASSED,
    )

    stalled = read_return_request(api, request["id"])
    assert stalled["status"] == "REQUESTED"
    assert stalled["honored_transfer_id"] is None
    assert_instant(stalled["response_deadline_at"], "2026-08-04T13:00:00Z", "response_deadline_at")
    assert_transfer_dimensions(
        read_transfer(api, transfer["id"]), "SETTLED", "RETURN_REQUESTED"
    )

    _rows, meta = list_transfers_with_meta(api)
    assert_pagination_meta(meta, total_count=1, has_more=False)
    assert read_account(api, scenario.alpha.account_id)["current_balance_cents"] == 1_150_000_000

    report = run_sweep(api)
    assert_sweep_counts(
        report,
        expired_rfp_count=0,
        expired_return_request_count=1,
        expired_transfer_count=0,
        escalated_alert_count=0,
    )
    assert read_return_request(api, request["id"])["status"] == "EXPIRED"
    assert_transfer_dimensions(
        read_transfer(api, transfer["id"]), "SETTLED", "RETURN_EXPIRED"
    )
