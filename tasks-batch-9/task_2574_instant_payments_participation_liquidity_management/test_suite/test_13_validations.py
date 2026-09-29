"""Refusals that fire before any row is written.

Every case here is a request the rail must decline, and the interesting part is
always *which* complaint comes back: a backwards outage window is a malformed
interval rather than a scheduling conflict, an internally consistent set of
thresholds under the network minimum is a prefund complaint rather than an
ordering one, a bank covered by a declared outage is offline rather than frozen,
and a bank still in draft cannot even register a customer. Each refusal is
paired with the neighbouring request that is admitted, so the boundary is pinned
from both sides.
"""

from test_helpers import (
    activate_participant,
    alpha_scenario,
    assert_alert,
    assert_instant,
    assert_ledger_entry,
    assert_outage_event_shape,
    assert_pagination_meta,
    assert_position_account_shape,
    bring_participant_live,
    clock_payload,
    configure_participant,
    credit_transfer_payload,
    customer_account_payload,
    declare_outage,
    enroll_participant,
    ERR_BUSINESS_DATE_NOT_REACHED,
    ERR_CLOCK_NOT_MONOTONIC,
    ERR_CUSTOMER_ACCOUNT_PARTICIPANT_MISMATCH,
    ERR_DUPLICATE_RESOURCE,
    ERR_DUPLICATE_ROUTING_NUMBER,
    ERR_DUPLICATE_SETTLEMENT_CYCLE,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_THRESHOLD_ORDERING,
    ERR_LEDGER_ADJUSTMENT_WOULD_GO_NEGATIVE,
    ERR_PARTICIPANT_NOT_LIVE,
    ERR_PARTICIPANT_OFFLINE,
    ERR_PREFUND_BELOW_MINIMUM,
    ERR_REQUEST_NOT_PERMITTED_FOR_MODEL,
    file_attestation,
    ledger_adjustment_payload,
    LIQUIDITY_OFFICER,
    list_alerts,
    list_ledger_entries_with_meta,
    list_position_accounts_with_meta,
    list_transfers_with_meta,
    live_beta,
    make_participant_admin_headers,
    MIN_PREFUND_CENTS,
    NETWORK_OPERATOR,
    open_certification_window,
    open_position_account,
    open_settlement_cycle,
    outage_event_payload,
    participant_payload,
    PAYMENT_OPERATOR_ALPHA,
    PAYMENT_OPERATOR_BETA,
    position_account_payload,
    raise_request_for_payment,
    read_account,
    read_customer_account,
    read_cycle,
    read_participant,
    record_certification_result,
    register_customer_account,
    request_for_payment_payload,
    resolve_outage,
    ROUTING_ALPHA,
    ROUTING_GAMMA,
    send_from_alpha,
    set_clock,
    settlement_cycle_payload,
    validate_error,
    validate_paginated,
    withdraw_from_account,
)

THIN_ACCOUNT = {
    "opening_balance_cents": 100_000_000,
    "warning_threshold_cents": 90_000_000,
    "critical_threshold_cents": 80_000_000,
    "floor_cents": 50_000_000,
}


def test_the_clock_refuses_a_step_backwards_but_accepts_a_repeat_of_now(api):
    """Monotonicity is strict below, permissive at equality.

    PRD 2.5: "A `NetworkOperator` may move the clock by supplying a `current_utc`
    instant; the clock is monotonic, so a target instant strictly earlier than the
    currently stored instant is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422),
    while a target equal to the current instant is accepted and leaves the clock where
    it is."

    Design: Corner/validations/clock_move_backward_rejected
    """
    set_clock(api, "2026-08-03T13:00:00Z")

    validate_error(
        api.set_clock(clock_payload("2026-08-03T12:59:00Z"), NETWORK_OPERATOR),
        ERR_CLOCK_NOT_MONOTONIC,
    )

    set_clock(api, "2026-08-03T13:00:00Z")
    participant = enroll_participant(api)
    assert_instant(participant["created_at"], "2026-08-03T13:00:00Z", "created_at")


def test_a_second_bank_cannot_claim_an_enrolled_routing_number(api):
    """Routing-number uniqueness is global, and it is the only thing that collides.

    PRD 3.1: "Enrolment begins with the rail operator recording the institution: its
    `legal_name`, its `routing_number` — exactly nine digits, and unique across every
    enrolled participant, so a second enrolment claiming a routing number already held
    is refused with `ERR_DUPLICATE_ROUTING_NUMBER` — and the
    `settlement_agent_reference` naming the settlement agent that will hold its
    prefunded position."

    PRD 3.1: "A newly enrolled participant lands in `DRAFT` `enrollment_status` with
    `operational_posture` `NORMAL` and `certification_round` 0."

    Design: Corner/validations/duplicate_routing_number_rejected
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    alpha = enroll_participant(api)
    assert alpha["enrollment_status"] == "DRAFT"

    validate_error(
        api.create_participant(
            participant_payload(
                legal_name="Gamma Savings Bank",
                routing_number=ROUTING_ALPHA,
                settlement_agent_reference="SA-GAMMA-01",
                participation_model="RECEIVE_ONLY",
            ),
            NETWORK_OPERATOR,
        ),
        ERR_DUPLICATE_ROUTING_NUMBER,
    )

    unchanged = read_participant(api, alpha["id"])
    assert unchanged["legal_name"] == "Alpha National Bank"
    assert unchanged["routing_number"] == ROUTING_ALPHA
    assert unchanged["enrollment_status"] == "DRAFT"

    gamma = enroll_participant(
        api,
        legal_name="Gamma Savings Bank",
        routing_number=ROUTING_GAMMA,
        settlement_agent_reference="SA-GAMMA-01",
        participation_model="RECEIVE_ONLY",
    )
    assert gamma["routing_number"] == ROUTING_GAMMA
    assert gamma["enrollment_status"] == "DRAFT"
    assert gamma["operational_posture"] == "NORMAL"
    assert gamma["certification_round"] == 0


def test_an_opening_deposit_one_cent_under_the_network_minimum_is_refused(api):
    """Four equal thresholds pass the ordering rule, so only the minimum bites.

    PRD 3.3: "The opening deposit must be at least the network minimum of 100,000,000
    cents, otherwise the request is refused with `ERR_PREFUND_BELOW_MINIMUM`."

    PRD 3.3: "The four figures must also be ordered: the floor at or below the critical
    threshold, the critical threshold at or below the warning threshold, and the warning
    threshold at or below the opening balance — equal adjacent values are accepted, and
    any other arrangement is refused with `ERR_INVALID_THRESHOLD_ORDERING`."

    Design: Corner/validations/prefund_below_minimum_rejected
    """
    assert MIN_PREFUND_CENTS == 100_000_000
    set_clock(api, "2026-08-03T13:00:00Z")
    participant = enroll_participant(api)

    validate_error(
        api.create_position_account(
            position_account_payload(
                participant["id"],
                opening_balance_cents=99_999_999,
                warning_threshold_cents=99_999_999,
                critical_threshold_cents=99_999_999,
                floor_cents=99_999_999,
            ),
            LIQUIDITY_OFFICER,
        ),
        ERR_PREFUND_BELOW_MINIMUM,
    )

    _rows, meta = list_position_accounts_with_meta(api, participant["id"])
    assert_pagination_meta(meta, total_count=0, has_more=False)

    account = open_position_account(
        api,
        participant["id"],
        opening_balance_cents=MIN_PREFUND_CENTS,
        warning_threshold_cents=99_999_999,
        critical_threshold_cents=99_999_999,
        floor_cents=99_999_999,
    )
    assert_position_account_shape(account)
    assert account["current_balance_cents"] == 100_000_000
    assert account["alert_tier"] == "GREEN"


def test_inverting_only_the_middle_threshold_pair_is_still_refused(api):
    """The ordering rule is a four-way chain, not a pair of independent bounds.

    PRD 3.3: "The four figures must also be ordered: the floor at or below the critical
    threshold, the critical threshold at or below the warning threshold, and the warning
    threshold at or below the opening balance — equal adjacent values are accepted, and
    any other arrangement is refused with `ERR_INVALID_THRESHOLD_ORDERING`."

    PRD 2.11: "Then the two structural well-formedness checks: position-account
    threshold ordering, yielding `ERR_INVALID_THRESHOLD_ORDERING`, and interval
    well-formedness, yielding `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/threshold_ordering_violation_rejected
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    participant = enroll_participant(api)

    validate_error(
        api.create_position_account(
            position_account_payload(
                participant["id"],
                opening_balance_cents=1_200_000_000,
                warning_threshold_cents=1_000_000_000,
                critical_threshold_cents=1_100_000_000,
                floor_cents=200_000_000,
            ),
            LIQUIDITY_OFFICER,
        ),
        ERR_INVALID_THRESHOLD_ORDERING,
    )

    _rows, meta = list_position_accounts_with_meta(api, participant["id"])
    assert_pagination_meta(meta, total_count=0, has_more=False)

    account = open_position_account(
        api,
        participant["id"],
        opening_balance_cents=1_200_000_000,
        warning_threshold_cents=1_100_000_000,
        critical_threshold_cents=1_000_000_000,
        floor_cents=200_000_000,
    )
    assert account["alert_tier"] == "GREEN"
    assert account["current_balance_cents"] == 1_200_000_000
    assert account["available_cents"] == 1_200_000_000


def test_a_backwards_outage_window_is_a_malformed_interval_not_a_conflict(api):
    """Well-formedness is judged on the pair of instants alone, on an empty table.

    PRD 3.9: "When an `ended_at` is supplied it must be strictly later than
    `started_at`, otherwise the declaration is refused with `ERR_INVALID_INTERVAL`."

    PRD 3.9: "Any conflict is reported as `ERR_OUTAGE_WINDOW_CONFLICT`."

    Design: Corner/validations/outage_interval_ends_before_start_rejected
    """
    set_clock(api, "2026-08-03T15:00:00Z")

    validate_error(
        api.create_outage_event(
            outage_event_payload(
                started_at="2026-08-03T14:00:00Z",
                scope="NETWORK_WIDE",
                severity="FULL_OUTAGE",
                fallback_rail="FALLBACK_ACH",
                ended_at="2026-08-03T13:00:00Z",
            ),
            NETWORK_OPERATOR,
        ),
        ERR_INVALID_INTERVAL,
    )

    event = declare_outage(api, "2026-08-03T14:00:00Z", scope="NETWORK_WIDE")
    assert_outage_event_shape(event)
    assert event["status"] == "DECLARED"
    assert event["scope"] == "NETWORK_WIDE"
    assert_instant(event["started_at"], "2026-08-03T14:00:00Z", "started_at")
    assert event["ended_at"] is None


def test_a_participant_may_not_open_a_second_prefunded_position(api):
    """One bank, one funded position — the second create collides on the resource.

    PRD 3.2: "Reusing an `account_reference` inside the same participant, exactly like
    attempting to open a second prefunded position account for a participant that
    already has one, is refused with `ERR_DUPLICATE_RESOURCE`."

    PRD 3.3: "A participant may hold at most one such account."

    Design: Corner/validations/second_position_account_for_participant_rejected
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    participant = enroll_participant(api)
    first = open_position_account(api, participant["id"])

    validate_error(
        api.create_position_account(
            position_account_payload(
                participant["id"],
                opening_balance_cents=500_000_000,
                warning_threshold_cents=300_000_000,
                critical_threshold_cents=200_000_000,
                floor_cents=100_000_000,
            ),
            LIQUIDITY_OFFICER,
        ),
        ERR_DUPLICATE_RESOURCE,
    )

    rows, meta = list_position_accounts_with_meta(api, participant["id"])
    assert_pagination_meta(meta, total_count=1, has_more=False)
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["opening_balance_cents"] == 1_200_000_000


def test_a_second_cycle_for_the_same_business_date_is_refused(api):
    """The business date, not the calendar day of the clock, is the unique key.

    PRD 3.10: "The rail operator opens one by supplying its `business_date`; a date
    already covered by a cycle is refused with `ERR_DUPLICATE_SETTLEMENT_CYCLE`, and a
    date later than the UTC date of the current logical clock is refused with
    `ERR_BUSINESS_DATE_NOT_REACHED` — cycles are opened for today or for a past date,
    never for tomorrow."

    PRD 3.10: "A new cycle starts `OPEN` with `assessed_fee_total_cents` 0,
    `settled_transfer_count` 0 and a null `cutoff_at` and `closed_at`."

    Design: Corner/validations/duplicate_settlement_cycle_business_date_rejected
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    cycle = open_settlement_cycle(api, "2026-08-03")
    assert cycle["status"] == "OPEN"
    assert cycle["assessed_fee_total_cents"] == 0
    assert cycle["settled_transfer_count"] == 0
    assert cycle["cutoff_at"] is None
    assert cycle["closed_at"] is None

    validate_error(
        api.create_settlement_cycle(
            settlement_cycle_payload("2026-08-03"), NETWORK_OPERATOR
        ),
        ERR_DUPLICATE_SETTLEMENT_CYCLE,
    )

    unchanged = read_cycle(api, cycle["id"])
    assert unchanged["status"] == "OPEN"
    assert unchanged["version"] == cycle["version"]
    assert unchanged["business_date"] == "2026-08-03"


def test_tomorrows_cycle_is_refused_while_yesterdays_is_permitted(api):
    """The comparison is against the UTC date of the logical clock, both ways.

    PRD 3.10: "The rail operator opens one by supplying its `business_date`; a date
    already covered by a cycle is refused with `ERR_DUPLICATE_SETTLEMENT_CYCLE`, and a
    date later than the UTC date of the current logical clock is refused with
    `ERR_BUSINESS_DATE_NOT_REACHED` — cycles are opened for today or for a past date,
    never for tomorrow."

    Design: Corner/validations/settlement_cycle_future_business_date_rejected
    """
    set_clock(api, "2026-08-03T13:00:00Z")

    validate_error(
        api.create_settlement_cycle(
            settlement_cycle_payload("2026-08-04"), NETWORK_OPERATOR
        ),
        ERR_BUSINESS_DATE_NOT_REACHED,
    )

    today = open_settlement_cycle(api, "2026-08-03")
    assert today["business_date"] == "2026-08-03"
    assert today["status"] == "OPEN"

    yesterday = open_settlement_cycle(api, "2026-08-02")
    assert yesterday["business_date"] == "2026-08-02"
    assert yesterday["status"] == "OPEN"
    assert yesterday["id"] != today["id"]


def test_zero_not_the_floor_is_the_hard_bound_on_a_withdrawal(api):
    """One cent past zero is refused; landing under the floor merely bands to BREACH.

    PRD 3.3: "An adjustment may take the balance below `floor_cents`, which is exactly
    the situation a `BREACH` band is meant to surface, but it may never take
    `current_balance_cents` below zero; an adjustment that would is refused with
    `ERR_LEDGER_ADJUSTMENT_WOULD_GO_NEGATIVE`."

    PRD 2.9: "When the recomputed tier is not `GREEN`, and the account does not already
    have a `LiquidityAlert` whose `tier` equals the recomputed tier and whose `status` is
    `OPEN`, `ACKNOWLEDGED` or `ESCALATED`, one alert row is opened with `status` `OPEN`,
    its `tier` set to the recomputed tier, its `observed_balance_cents` set to the
    `current_balance_cents` just computed, and its `threshold_cents` set to the constant
    that was crossed — `warning_threshold_cents` for an `AMBER` alert,
    `critical_threshold_cents` for a `RED` alert, and `floor_cents` for a `BREACH`
    alert."

    Design: Corner/validations/ledger_adjustment_below_zero_rejected
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    participant = enroll_participant(api)
    account = open_position_account(api, participant["id"], **THIN_ACCOUNT)
    assert account["current_balance_cents"] == 100_000_000
    assert account["alert_tier"] == "GREEN"

    validate_error(
        api.post_ledger_adjustment(
            account["id"],
            ledger_adjustment_payload(
                "WITHDRAWAL_DEBIT", 100_000_001, reference="Over-withdrawal attempt"
            ),
            LIQUIDITY_OFFICER,
        ),
        ERR_LEDGER_ADJUSTMENT_WOULD_GO_NEGATIVE,
    )

    _entries, meta = list_ledger_entries_with_meta(api, account["id"])
    assert_pagination_meta(meta, total_count=0, has_more=False)
    intact = read_account(api, account["id"])
    assert intact["current_balance_cents"] == 100_000_000
    assert intact["alert_tier"] == "GREEN"
    assert list_alerts(api, account["id"]) == []

    entry = withdraw_from_account(
        api, account["id"], 100_000_000, reference="Full sweep to correspondent account"
    )
    assert_ledger_entry(
        entry,
        entry_type="WITHDRAWAL_DEBIT",
        amount_cents=-100_000_000,
        balance_after_cents=0,
        sequence_no=1,
        business_date="2026-08-03",
    )

    emptied = read_account(api, account["id"])
    assert emptied["current_balance_cents"] == 0
    assert emptied["alert_tier"] == "BREACH"

    alerts = list_alerts(api, account["id"])
    assert len(alerts) == 1
    assert_alert(
        alerts[0],
        tier="BREACH",
        status="OPEN",
        threshold_cents=50_000_000,
        observed_balance_cents=0,
    )


def test_a_draft_bank_cannot_register_a_customer_until_it_is_live(api):
    """Onboarding order is forced: customer data comes after activation, not before.

    PRD 3.2: "Both publication and customer registration require the owning participant
    to be `LIVE` — a bank still in `DRAFT`, `ATTESTATION_PENDING`,
    `CERTIFICATION_TESTING`, `REMEDIATION`, `CERTIFIED`, `SUSPENDED` or `WITHDRAWN`
    cannot configure live payment controls, and the attempt is refused with
    `ERR_PARTICIPANT_NOT_LIVE`."

    Design: Corner/validations/customer_account_create_on_draft_participant_rejected
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    participant = enroll_participant(api)
    assert participant["enrollment_status"] == "DRAFT"
    admin = make_participant_admin_headers(participant["id"])

    validate_error(
        api.create_customer_account(
            customer_account_payload(
                participant["id"],
                account_reference="CUST-ALPHA-0001",
                segment="CORPORATE",
                fraud_risk_baseline=20,
            ),
            admin,
        ),
        ERR_PARTICIPANT_NOT_LIVE,
    )

    assert read_participant(api, participant["id"])["enrollment_status"] == "DRAFT"
    _rows, meta = validate_paginated(
        api.list_participant_customer_accounts(participant["id"], NETWORK_OPERATOR)
    )
    assert_pagination_meta(meta, total_count=0, has_more=False)

    open_position_account(api, participant["id"])
    file_attestation(api, participant["id"])
    open_certification_window(api, participant["id"])
    record_certification_result(api, participant["id"], "PASS")
    live = activate_participant(api, participant["id"], "2026-08-03")
    assert live["enrollment_status"] == "LIVE"

    customer = register_customer_account(api, participant["id"])
    assert customer["account_reference"] == "CUST-ALPHA-0001"
    assert customer["status"] == "ACTIVE"
    assert customer["participant_id"] == participant["id"]


def test_a_bank_under_a_declared_outage_is_offline_rather_than_send_frozen(api):
    """The posture ladder puts OFFLINE ahead of the freeze, on a fully GREEN account.

    PRD 3.4: "Its posture must not be `OFFLINE`, or the send fails with
    `ERR_PARTICIPANT_OFFLINE`."

    PRD 3.9: "Resolution is permitted only from `DECLARED` — `RESOLVED` is terminal — and
    it writes `ended_at`, moves the event `DECLARED → RESOLVED`, and then re-derives the
    posture of every participant the event covered."

    Design: Corner/validations/credit_transfer_during_declared_outage_rejected
    """
    scenario = alpha_scenario(api)
    set_clock(api, "2026-08-03T13:05:00Z")
    event = declare_outage(
        api, "2026-08-03T13:05:00Z", participant_id=scenario.alpha.id
    )
    assert event["status"] == "DECLARED"
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "OFFLINE"

    account = read_account(api, scenario.alpha.account_id)
    assert account["alert_tier"] == "GREEN"

    validate_error(
        api.create_credit_transfer(
            credit_transfer_payload(
                scenario.alpha.id,
                scenario.alpha.customer_account_id,
                50_000_000,
                account["version"],
            ),
            PAYMENT_OPERATOR_ALPHA,
        ),
        ERR_PARTICIPANT_OFFLINE,
    )

    _rows, meta = list_transfers_with_meta(api)
    assert_pagination_meta(meta, total_count=0, has_more=False)
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 0

    set_clock(api, "2026-08-03T13:06:00Z")
    resolved = resolve_outage(api, event["id"], "2026-08-03T13:06:00Z")
    assert resolved["status"] == "RESOLVED"
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "NORMAL"

    admitted = send_from_alpha(api, scenario, 50_000_000)
    assert admitted["clearing_status"] == "INITIATED"
    assert admitted["amount_cents"] == 50_000_000
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 50_000_000


def test_another_banks_customer_cannot_be_debited_but_may_be_asked(api):
    """Both foreign keys resolve, so this is a coherence refusal and not a lookup miss.

    PRD 3.4: "That customer account must also belong to the participant named in the same
    request — a customer of another bank cannot be debited here, and the mismatch is
    refused with `ERR_CUSTOMER_ACCOUNT_PARTICIPANT_MISMATCH`."

    PRD 3.7: "A newly raised request sits in `CREATED` with `amendment_round` 0, a null
    `delivered_at`, a null `response_deadline_at` and a null `last_response`."

    Design: Corner/validations/transfer_with_other_participants_customer_account_rejected
    """
    scenario = alpha_scenario(api, with_beta=True)
    assert scenario.beta is not None
    configure_participant(api, scenario.beta, customer_reference="CUST-BETA-0001")
    foreign_customer_id = scenario.beta.customer_account_id

    account = read_account(api, scenario.alpha.account_id)
    validate_error(
        api.create_credit_transfer(
            credit_transfer_payload(
                scenario.alpha.id,
                foreign_customer_id,
                50_000_000,
                account["version"],
            ),
            PAYMENT_OPERATOR_ALPHA,
        ),
        ERR_CUSTOMER_ACCOUNT_PARTICIPANT_MISMATCH,
    )

    foreign_customer = read_customer_account(api, foreign_customer_id)
    assert foreign_customer["participant_id"] == scenario.beta.id
    assert foreign_customer["participant_id"] != scenario.alpha.id

    _rows, meta = list_transfers_with_meta(api)
    assert_pagination_meta(meta, total_count=0, has_more=False)
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 0

    rfp = raise_request_for_payment(
        api,
        scenario.alpha.id,
        foreign_customer_id,
        5_000_000,
        "2026-08-04T13:00:00Z",
        memo="Invoice INV-9001",
    )
    assert rfp["status"] == "CREATED"
    assert rfp["amendment_round"] == 0
    assert rfp["delivered_at"] is None
    assert rfp["response_deadline_at"] is None
    assert rfp["last_response"] is None


def test_a_receive_only_bank_may_be_credited_but_may_not_ask(api):
    """Capability, not lifecycle: the bank is LIVE with a fully funded position.

    PRD 3.7: "It also requires model capability on both sides: the requesting bank's
    `participation_model` must be `RECEIVE_AND_REQUEST_FOR_PAYMENT` or
    `SEND_AND_RECEIVE`, and the debtor customer's own bank must itself be on one of those
    two models, since a `RECEIVE_ONLY` institution does not handle request-for-payment
    messages at all."

    PRD 3.7: "A failure on either side is refused with
    `ERR_REQUEST_NOT_PERMITTED_FOR_MODEL`."

    Design: Corner/validations/receive_only_participant_cannot_request_payment
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    alpha = bring_participant_live(api, participation_model="RECEIVE_ONLY")
    alpha_customer = register_customer_account(api, alpha.id)
    assert read_account(api, alpha.account_id)["current_balance_cents"] == 1_200_000_000

    validate_error(
        api.create_request_for_payment(
            request_for_payment_payload(
                alpha.id,
                alpha_customer["id"],
                5_000_000,
                "2026-08-04T13:00:00Z",
                memo="Invoice INV-9001",
            ),
            PAYMENT_OPERATOR_ALPHA,
        ),
        ERR_REQUEST_NOT_PERMITTED_FOR_MODEL,
    )

    still_live = read_participant(api, alpha.id)
    assert still_live["enrollment_status"] == "LIVE"
    assert still_live["participation_model"] == "RECEIVE_ONLY"
    assert still_live["operational_posture"] == "NORMAL"

    _rows, meta = validate_paginated(api.list_requests_for_payment(NETWORK_OPERATOR))
    assert_pagination_meta(meta, total_count=0, has_more=False)

    beta = live_beta(api)
    assert read_participant(api, beta.id)["participation_model"] == "SEND_AND_RECEIVE"
    beta_customer = register_customer_account(
        api, beta.id, account_reference="CUST-BETA-0001"
    )

    admitted = raise_request_for_payment(
        api,
        beta.id,
        beta_customer["id"],
        5_000_000,
        "2026-08-04T13:00:00Z",
        operator=PAYMENT_OPERATOR_BETA,
        memo="Invoice INV-9002",
    )
    assert admitted["status"] == "CREATED"
    assert admitted["amount_cents"] == 5_000_000
    assert admitted["requestor_participant_id"] == beta.id
