"""Derived figures whose pinned order of operations is the whole rule.

Release, capping, scoring, projection and velocity are all computed rather than
stored, and each of them has a reading that looks reasonable and is wrong: a
release pass that skips a candidate instead of stopping, a policy limit consulted
without the posture cap, a ceiling applied before the segment multiplier, a
projection that counts committed reservations twice, and a velocity window that
counts every row ever created rather than the countable clearing states.
"""

from test_helpers import (
    alpha_scenario,
    assert_instant,
    assert_ledger_entry,
    configure_participant,
    credit_transfer_payload,
    declare_outage,
    deliver_request_for_payment,
    divert_transfer,
    ERR_THROTTLED_CAP_EXCEEDED,
    ERR_VELOCITY_LIMIT_EXCEEDED,
    FRAUD_BLOCK_THRESHOLD,
    FRAUD_SCORE_CEILING,
    fund_account,
    list_fraud_reviews,
    list_transfers_with_meta,
    PAYMENT_OPERATOR_ALPHA,
    PAYMENT_OPERATOR_BETA,
    PROJECTION_HORIZON_MINUTES,
    raise_request_for_payment,
    read_account,
    read_customer_account,
    read_participant,
    read_projection,
    read_transfer,
    resolve_outage,
    respond_to_request_for_payment,
    SEGMENT_MULTIPLIERS,
    send_from_alpha,
    set_clock,
    THROTTLED_PER_TXN_CAP_CENTS,
    validate_error,
    VELOCITY_WINDOW_MINUTES,
    withdraw_from_account,
)

WATERFALL_ACCOUNT = {
    "opening_balance_cents": 1_300_000_000,
    "warning_threshold_cents": 1_140_000_000,
    "critical_threshold_cents": 1_100_000_000,
    "floor_cents": 1_000_000_000,
}
HIGH_RISK_POLICY = {"segment": "HIGH_RISK"}
SINGLE_SEND_WINDOW_POLICY = {"rolling_window_count_limit": 1}


def test_the_release_pass_stops_at_the_first_transfer_that_does_not_fit(api):
    """A strict waterfall, not a skip-and-continue: the small third stays parked.

    PRD 2.9: "Each candidate in turn is admitted only if the running availability minus
    that transfer's `amount_cents` is greater than or equal to `floor_cents`; on admission
    the transfer returns to `INITIATED`, its `queued_at` is cleared, its amount re-enters
    the reservation set, and the running availability is reduced by that amount."

    PRD 2.9: "It does not skip that candidate in order to release a smaller, later one — a
    skip-and-continue reading releases a different set of transfers and is explicitly not
    the rule."

    Design: Corner/calculations/waterfall_release_stops_at_first_transfer_that_does_not_fit
    """
    scenario = alpha_scenario(api, account=WATERFALL_ACCOUNT)
    first = send_from_alpha(api, scenario, 100_000_000)
    second = send_from_alpha(api, scenario, 60_000_000)
    third = send_from_alpha(api, scenario, 50_000_000)
    for transfer in (first, second, third):
        assert transfer["clearing_status"] == "INITIATED"
        assert transfer["fraud_score"] == 57

    set_clock(api, "2026-08-03T13:05:00Z")
    withdraw_from_account(
        api,
        scenario.alpha.account_id,
        250_000_000,
        reference="Sweep to correspondent account",
    )
    frozen = read_account(api, scenario.alpha.account_id)
    assert frozen["current_balance_cents"] == 1_050_000_000
    assert frozen["alert_tier"] == "RED"
    assert frozen["reserved_cents"] == 0
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "SEND_FROZEN"
    for transfer in (first, second, third):
        parked = read_transfer(api, transfer["id"])
        assert parked["clearing_status"] == "QUEUED_THROTTLED"
        assert_instant(parked["queued_at"], "2026-08-03T13:05:00Z", "queued_at")

    set_clock(api, "2026-08-03T13:10:00Z")
    entry = fund_account(
        api, scenario.alpha.account_id, 100_000_000, reference="Intraday top-up"
    )

    assert_ledger_entry(
        entry,
        entry_type="FUNDING_CREDIT",
        amount_cents=100_000_000,
        balance_after_cents=1_150_000_000,
        sequence_no=2,
        business_date="2026-08-03",
    )

    released = read_transfer(api, first["id"])
    assert released["clearing_status"] == "INITIATED"
    assert released["queued_at"] is None

    blocked = read_transfer(api, second["id"])
    assert blocked["clearing_status"] == "QUEUED_THROTTLED"
    assert_instant(blocked["queued_at"], "2026-08-03T13:05:00Z", "queued_at")

    skipped = read_transfer(api, third["id"])
    assert skipped["clearing_status"] == "QUEUED_THROTTLED"
    assert_instant(skipped["queued_at"], "2026-08-03T13:05:00Z", "queued_at")

    account = read_account(api, scenario.alpha.account_id)
    assert account["current_balance_cents"] == 1_150_000_000
    assert account["alert_tier"] == "GREEN"
    assert account["reserved_cents"] == 100_000_000
    assert account["available_cents"] == 1_050_000_000
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "NORMAL"


def test_the_throttled_cap_refuses_an_amount_the_policy_would_have_allowed(api):
    """A posture cap of 50,000,000 cents overrides a far more generous policy limit.

    PRD 3.4: "First the amount is compared with the pinned policy's
    `per_transaction_limit_cents`; the comparison is at-most, so an amount exactly equal to
    the limit is admitted and anything larger is refused with
    `ERR_PER_TRANSACTION_LIMIT_EXCEEDED`."

    PRD 3.4: "Next, if the originating bank's posture is `THROTTLED`, the amount is
    additionally capped at 50,000,000 cents (five hundred thousand currency units)
    regardless of how generous the policy is; exceeding that cap is refused with
    `ERR_THROTTLED_CAP_EXCEEDED`."

    Design: Corner/calculations/throttled_posture_caps_transaction_below_policy_limit
    """
    assert THROTTLED_PER_TXN_CAP_CENTS == 50_000_000
    scenario = alpha_scenario(api)
    withdraw_from_account(
        api,
        scenario.alpha.account_id,
        150_000_000,
        reference="Sweep to correspondent account",
    )
    throttled = read_account(api, scenario.alpha.account_id)
    assert throttled["current_balance_cents"] == 1_050_000_000
    assert throttled["alert_tier"] == "AMBER"
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "THROTTLED"

    policy = scenario.alpha.policy
    assert policy["per_transaction_limit_cents"] == 250_000_000

    response = api.create_credit_transfer(
        credit_transfer_payload(
            scenario.alpha.id,
            scenario.alpha.customer_account_id,
            60_000_000,
            throttled["version"],
        ),
        PAYMENT_OPERATOR_ALPHA,
    )
    validate_error(response, ERR_THROTTLED_CAP_EXCEEDED)

    _rows, meta = list_transfers_with_meta(api)
    assert meta["total_count"] == 0
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 0

    admitted = send_from_alpha(api, scenario, THROTTLED_PER_TXN_CAP_CENTS)
    assert admitted["clearing_status"] == "INITIATED"
    assert admitted["amount_cents"] == 50_000_000
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 50_000_000


def test_a_high_risk_score_is_capped_at_one_hundred_and_blocks_without_a_review(api):
    """The ceiling lands after the multiplier, and an automatic block queues nothing.

    PRD 3.4: "Those four terms are summed into a raw subtotal, the subtotal is multiplied by
    the customer's segment multiplier — 1.00 for `CONSUMER`, 1.05 for `SMALL_BUSINESS`, 1.10
    for `CORPORATE` and 1.25 for `HIGH_RISK` — the product is rounded half up to a whole
    number, and only then is the result capped at 100."

    PRD 3.4: "A score of 85 or more is blocked outright: the transfer moves `INITIATED →
    REJECTED`, `rejection_reason_code` is written as `FRAUD_BLOCK_AUTOMATIC`, and its amount
    leaves the reservation set so the account's `reserved_cents` returns to the value it had
    before the call."

    PRD 3.4: "An automatic block creates **no** fraud review and leaves the debtor
    `CustomerAccount.status` `ACTIVE` — only a reviewer's explicit block restricts a
    customer."

    Design: Corner/calculations/fraud_score_clamped_at_one_hundred_blocks_at_origination
    """
    assert SEGMENT_MULTIPLIERS["HIGH_RISK"] == "1.25"
    assert FRAUD_SCORE_CEILING == 100
    assert FRAUD_BLOCK_THRESHOLD == 85
    scenario = alpha_scenario(
        api,
        policy=HIGH_RISK_POLICY,
        customer_reference="CUST-ALPHA-9001",
        customer_segment="HIGH_RISK",
        fraud_risk_baseline=60,
    )

    blocked = send_from_alpha(api, scenario, 50_000_000)

    assert blocked["fraud_score"] == 100
    assert blocked["clearing_status"] == "REJECTED"
    assert blocked["rejection_reason_code"] == "FRAUD_BLOCK_AUTOMATIC"
    assert blocked["fraud_reason_codes"] == [
        "BASELINE_RISK",
        "AMOUNT_BAND",
        "NEW_BENEFICIARY",
    ]

    assert list_fraud_reviews(api, blocked["id"]) == []

    account = read_account(api, scenario.alpha.account_id)
    assert account["reserved_cents"] == 0
    assert account["available_cents"] == 1_200_000_000

    customer = read_customer_account(api, scenario.alpha.customer_account_id)
    assert customer["status"] == "ACTIVE"
    assert customer["restricted_at"] is None


def test_the_projection_adds_open_requests_and_never_double_counts_reservations(api):
    """The horizon is half-open, and committed in-flight money is not subtracted twice.

    PRD 3.3: "The **projection** looks out over the half-open window that begins at the
    current logical clock and ends at `horizon_end`, which is 1,440 minutes (twenty-four
    hours) later; a request whose `expiry_at` falls exactly on the clock is inside the
    window, while one falling exactly on `horizon_end` is outside it."

    PRD 3.3: "`scheduled_outflow_cents` is the summed `amount_cents` of every request for
    payment naming one of this participant's customer accounts as
    `debtor_customer_account_id`, whose `status` is `DELIVERED` or `ACCEPTED`, and whose
    `expiry_at` falls inside that window — money the bank's customers are expected to pay
    out."

    PRD 3.3: "`expected_inflow_cents` is the summed `amount_cents` of every request for
    payment this participant raised as `requestor_participant_id` whose `status` is
    `ACCEPTED` and whose `expiry_at` falls inside the same window — money it expects to
    receive."

    PRD 3.3: "Committed in-flight transfers are deliberately **not** added into the outflow:
    they already sit inside `reserved_cents`, and counting them twice is the classic
    misreading of this figure."

    Design: Corner/calculations/liquidity_projection_excludes_committed_reservations
    """
    assert PROJECTION_HORIZON_MINUTES == 1440
    scenario = alpha_scenario(api, with_beta=True)
    assert scenario.beta is not None
    configure_participant(api, scenario.beta, customer_reference="CUST-BETA-0001")

    in_flight = send_from_alpha(api, scenario, 100_000_000)
    assert in_flight["clearing_status"] == "INITIATED"

    inside_horizon = raise_request_for_payment(
        api,
        scenario.beta.id,
        scenario.alpha.customer_account_id,
        5_000_000,
        "2026-08-04T09:00:00Z",
        operator=PAYMENT_OPERATOR_BETA,
        memo="Invoice INV-8001",
    )
    deliver_request_for_payment(api, inside_horizon["id"])

    on_the_horizon = raise_request_for_payment(
        api,
        scenario.beta.id,
        scenario.alpha.customer_account_id,
        7_000_000,
        "2026-08-04T13:00:00Z",
        operator=PAYMENT_OPERATOR_BETA,
        memo="Invoice INV-8002",
    )
    deliver_request_for_payment(api, on_the_horizon["id"])

    raised_by_alpha = raise_request_for_payment(
        api,
        scenario.alpha.id,
        scenario.beta.customer_account_id,
        8_000_000,
        "2026-08-04T10:00:00Z",
        memo="Invoice INV-8003",
    )
    deliver_request_for_payment(api, raised_by_alpha["id"])
    assert respond_to_request_for_payment(api, raised_by_alpha["id"], "ACCEPT")["status"] == "ACCEPTED"

    projection = read_projection(api, scenario.alpha.account_id)

    assert_instant(projection["horizon_end"], "2026-08-04T13:00:00Z", "horizon_end")
    assert projection["scheduled_outflow_cents"] == 5_000_000
    assert projection["expected_inflow_cents"] == 8_000_000
    assert projection["projected_balance_cents"] == 1_203_000_000
    assert projection["projected_available_cents"] == 1_103_000_000
    assert projection["projected_alert_tier"] == "GREEN"
    assert projection["current_balance_cents"] == 1_200_000_000
    assert projection["reserved_cents"] == 100_000_000
    assert projection["available_cents"] == 1_100_000_000


def test_a_diverted_transfer_leaves_the_velocity_window_behind(api):
    """Only the five countable clearing states consume the customer's headroom.

    PRD 3.4: "The countable rows are the debtor customer account's own outbound transfers in
    one of five clearing states — `INITIATED`, `FRAUD_HOLD`, `QUEUED_THROTTLED`, `ACCEPTED`
    or `SETTLED`."

    PRD 3.4: "Rows in `REJECTED`, `DIVERTED` or `EXPIRED` never count toward velocity, so a
    blocked or expired attempt does not consume the customer's headroom."

    PRD 3.4: "Two comparisons follow, and **count is checked before amount**: the number of
    countable prior rows plus one for this send must not exceed `rolling_window_count_limit`,
    and their summed `amount_cents` plus this amount must not exceed
    `rolling_window_amount_limit_cents`."

    Design: Corner/calculations/velocity_window_excludes_diverted_transfer
    """
    assert VELOCITY_WINDOW_MINUTES == 60
    scenario = alpha_scenario(api, policy=SINGLE_SEND_WINDOW_POLICY)
    assert scenario.alpha.policy["rolling_window_count_limit"] == 1
    first = send_from_alpha(api, scenario, 10_000_000)
    assert first["clearing_status"] == "INITIATED"

    set_clock(api, "2026-08-03T13:05:00Z")
    event = declare_outage(
        api, "2026-08-03T13:05:00Z", participant_id=scenario.alpha.id
    )
    assert read_transfer(api, first["id"])["clearing_status"] == "QUEUED_THROTTLED"

    set_clock(api, "2026-08-03T13:06:00Z")
    diverted = divert_transfer(api, first["id"], "FALLBACK_ACH", PAYMENT_OPERATOR_ALPHA)
    assert diverted["clearing_status"] == "DIVERTED"
    assert diverted["rail"] == "FALLBACK_ACH"

    set_clock(api, "2026-08-03T13:10:00Z")
    resolved = resolve_outage(api, event["id"], "2026-08-03T13:10:00Z")
    assert resolved["status"] == "RESOLVED"
    assert_instant(resolved["ended_at"], "2026-08-03T13:10:00Z", "ended_at")
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "NORMAL"

    set_clock(api, "2026-08-03T13:20:00Z")
    second = send_from_alpha(api, scenario, 10_000_000)
    assert second["clearing_status"] == "INITIATED"
    assert second["fraud_score"] == 57

    account = read_account(api, scenario.alpha.account_id)
    assert account["reserved_cents"] == 10_000_000
    assert account["current_balance_cents"] == 1_200_000_000

    set_clock(api, "2026-08-03T13:21:00Z")
    validate_error(
        api.create_credit_transfer(
            credit_transfer_payload(
                scenario.alpha.id,
                scenario.alpha.customer_account_id,
                10_000_000,
                account["version"],
            ),
            PAYMENT_OPERATOR_ALPHA,
        ),
        ERR_VELOCITY_LIMIT_EXCEEDED,
    )
