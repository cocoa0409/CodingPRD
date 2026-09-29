"""Where a lifecycle hop lands, and what refuses to happen twice.

Every machine in this rail has an entry state nobody may skip, hops that stamp
derived instants rather than merely relabelling a row, and terminal or one-shot
states that make a retry an error instead of a no-op. The tests below walk the
enrolment entry state, the request-for-payment delivery stamp, the irrevocability
of a settled payment, the one-shot nature of an alert acknowledgement, the two
machines the housekeeping sweep advances by clock comparison alone, and the
outage-and-diversion handshake that spans two entities.
"""

from test_helpers import (
    acknowledge_alert,
    alert_acknowledgement_payload,
    ALERT_ESCALATION_MINUTES,
    assert_alert,
    assert_instant,
    assert_ledger_entry,
    assert_outage_event_shape,
    assert_participant_shape,
    assert_request_for_payment_shape,
    assert_sweep_counts,
    assert_transfer_dimensions,
    deliver_request_for_payment,
    delivered_rfp_scenario,
    divert_transfer,
    enroll_participant,
    ERR_ALERT_NOT_ACKNOWLEDGEABLE,
    ERR_TRANSFER_IRREVOCABLE,
    LIQUIDITY_OFFICER,
    LIQUIDITY_OFFICER_TWO,
    list_alerts,
    list_ledger_entries,
    live_alpha,
    NETWORK_OPERATOR,
    outage_scenario,
    PAYMENT_OPERATOR_ALPHA,
    read_account,
    read_participant,
    read_rfp,
    read_transfer,
    run_sweep,
    set_clock,
    settled_transfer_scenario,
    validate_error,
    validate_paginated,
    withdraw_from_account,
)


def _sole_alert(api, account_id):
    """The single alert standing on an account, read through its own list path."""
    alerts = list_alerts(api, account_id, headers=LIQUIDITY_OFFICER_TWO)
    assert len(alerts) == 1
    return alerts[0]


def _outage_event(api, participant_id, event_id):
    """Re-read one outage event through the participant's outage list."""
    events, _meta = validate_paginated(
        api.list_participant_outage_events(participant_id, NETWORK_OPERATOR)
    )
    matches = [event for event in events if event["id"] == event_id]
    assert len(matches) == 1
    return matches[0]


def test_a_bank_enrolled_on_the_send_tier_still_lands_in_draft(api):
    """The requested tier is recorded; it does not advance the enrolment machine.

    PRD 3.1: "A newly enrolled participant lands in `DRAFT` `enrollment_status` with
    `operational_posture` `NORMAL` and `certification_round` 0."

    Design: Corner/state_machines/new_participant_starts_in_draft_state
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    participant = enroll_participant(api, participation_model="SEND_AND_RECEIVE")

    assert_participant_shape(participant)
    assert participant["participation_model"] == "SEND_AND_RECEIVE"
    assert participant["enrollment_status"] == "DRAFT"
    assert participant["operational_posture"] == "NORMAL"
    assert participant["certification_round"] == 0
    assert participant["attestation_document_reference"] is None
    assert participant["certification_test_suite_version"] is None
    assert participant["go_live_business_date"] is None
    assert participant["suspension_reason"] is None
    assert read_participant(api, participant["id"])["enrollment_status"] == "DRAFT"


def test_delivery_stamps_the_thirty_minute_deadline_not_the_distant_expiry(api):
    """Delivery is a stamping hop: the deadline is derived, not copied from expiry.

    PRD 3.7: "A newly raised request sits in `CREATED` with `amendment_round` 0, a null
    `delivered_at`, a null `response_deadline_at` and a null `last_response`."

    PRD 3.7: "Delivery stamps `delivered_at` with the clock and sets
    `response_deadline_at` to whichever is earlier of the request's `expiry_at` and the
    delivery instant plus 30 minutes — the message response service level — and
    increments the request's `version`."

    Design: Corner/state_machines/rfp_delivery_stamps_deadline_and_advances_state
    """
    _scenario, created = delivered_rfp_scenario(
        api,
        amount_cents=5_000_000,
        expiry_at="2026-08-04T13:00:00Z",
        memo="Invoice INV-7001",
        deliver=False,
    )
    assert_request_for_payment_shape(created)
    assert created["status"] == "CREATED"
    assert created["delivered_at"] is None
    assert created["response_deadline_at"] is None
    assert created["last_response"] is None
    assert created["amendment_round"] == 0

    delivered = deliver_request_for_payment(api, created["id"])

    assert delivered["status"] == "DELIVERED"
    assert_instant(delivered["delivered_at"], "2026-08-03T13:00:00Z", "delivered_at")
    assert_instant(delivered["response_deadline_at"], "2026-08-03T13:30:00Z", "response_deadline_at")
    assert_instant(delivered["expiry_at"], "2026-08-04T13:00:00Z", "expiry_at")
    assert delivered["amendment_round"] == 0
    assert delivered["last_response"] is None
    assert delivered["version"] == created["version"] + 1

    assert_instant(read_rfp(api, created["id"])["response_deadline_at"], "2026-08-03T13:30:00Z", "response_deadline_at")


def test_a_settled_payment_cannot_be_settled_or_accepted_a_second_time(api):
    """Irrevocability is a refusal, not a silent replay of the debit.

    PRD 3.6: "A settled transfer may not be cancelled, reversed, re-settled, nor have
    its amount amended by any operation; an acceptance, a settlement or a diversion
    attempted against an already `SETTLED` transfer is refused with
    `ERR_TRANSFER_IRREVOCABLE`."

    Design: Corner/state_machines/settling_an_already_settled_transfer_cannot_repeat
    """
    scenario, transfer = settled_transfer_scenario(api, amount_cents=100_000_000)
    assert_transfer_dimensions(transfer, "SETTLED", "NONE")
    assert_instant(transfer["settled_at"], "2026-08-03T13:10:00Z", "settled_at")

    validate_error(
        api.settle_credit_transfer(transfer["id"], NETWORK_OPERATOR),
        ERR_TRANSFER_IRREVOCABLE,
    )
    validate_error(
        api.accept_credit_transfer(transfer["id"], NETWORK_OPERATOR),
        ERR_TRANSFER_IRREVOCABLE,
    )

    unchanged = read_transfer(api, transfer["id"])
    assert unchanged["clearing_status"] == "SETTLED"
    assert_instant(unchanged["settled_at"], "2026-08-03T13:10:00Z", "settled_at")

    entries = list_ledger_entries(api, scenario.alpha.account_id)
    assert len(entries) == 1
    assert_ledger_entry(
        entries[0],
        entry_type="TRANSFER_DEBIT",
        amount_cents=-100_000_000,
        balance_after_cents=1_100_000_000,
        sequence_no=1,
        business_date="2026-08-03",
    )

    account = read_account(api, scenario.alpha.account_id)
    assert account["current_balance_cents"] == 1_100_000_000
    assert account["alert_tier"] == "AMBER"
    assert account["reserved_cents"] == 0


def test_acknowledging_an_acknowledged_alert_is_refused_and_keeps_the_first_plan(api):
    """The hop out of `OPEN` runs once, and it is a record rather than a remedy.

    PRD 3.3: "A treasury officer acknowledges an alert that is `OPEN` or `ESCALATED` by
    supplying a `remediation_plan`; the alert becomes `ACKNOWLEDGED`,
    `acknowledged_by_user_id` is taken from the acting `X-User-ID`, and neither the
    account's `alert_tier` nor the participant's posture changes — acknowledgement is a
    commitment to fund, not funding."

    PRD 3.3: "An alert that is already `ACKNOWLEDGED` or `CLEARED` cannot be acknowledged
    again and the attempt is refused with `ERR_ALERT_NOT_ACKNOWLEDGEABLE`."

    Design: Corner/state_machines/alert_acknowledged_twice_cannot_repeat
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    alpha = live_alpha(api)
    withdraw_from_account(
        api,
        alpha.account_id,
        250_000_000,
        reference="Sweep to correspondent account",
        officer=LIQUIDITY_OFFICER,
    )
    alert = _sole_alert(api, alpha.account_id)
    assert_alert(alert, "RED", "OPEN", 1_000_000_000, 950_000_000)

    set_clock(api, "2026-08-03T13:05:00Z")
    first_plan = "Intraday funding of 300,000,000 cents requested from treasury."
    acknowledged = acknowledge_alert(api, alert["id"], first_plan, LIQUIDITY_OFFICER_TWO)
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_by_user_id"] == "liq-02"
    assert acknowledged["remediation_plan"] == first_plan

    validate_error(
        api.acknowledge_alert(
            alert["id"],
            alert_acknowledgement_payload("Duplicate acknowledgement attempt."),
            LIQUIDITY_OFFICER_TWO,
        ),
        ERR_ALERT_NOT_ACKNOWLEDGEABLE,
    )

    after = _sole_alert(api, alpha.account_id)
    assert_alert(after, "RED", "ACKNOWLEDGED", 1_000_000_000, 950_000_000)
    assert after["remediation_plan"] == first_plan
    assert read_account(api, alpha.account_id)["alert_tier"] == "RED"
    assert read_participant(api, alpha.id)["operational_posture"] == "SEND_FROZEN"


def test_one_sweep_expires_the_request_and_escalates_the_stale_alert(api):
    """Two unrelated machines advance in a single clock-driven call, counted apart.

    PRD 3.3: "An alert left unacknowledged is escalated by the housekeeping sweep once
    60 minutes have elapsed since it was opened, which stamps `escalated_at`; escalation
    does not close the alert, and an `ESCALATED` alert may still be acknowledged."

    PRD 3.10: "Finally, the network housekeeping sweep is the one operation that advances
    time-driven state, and it does exactly four things at the current logical clock,
    reporting a count for each: it expires every request for payment in `CREATED`,
    `DELIVERED` or `AMENDMENT_REQUESTED` whose `expiry_at` the clock has reached,
    reported as `expired_rfp_count`; it expires every `REQUESTED` return request whose
    `response_deadline_at` the clock has reached, setting the underlying transfer's
    `exception_status` to `RETURN_EXPIRED`, reported as `expired_return_request_count`;
    it expires every `QUEUED_THROTTLED` transfer whose `queued_at` is at least 120
    minutes old, releasing its reservation, reported as `expired_transfer_count`; and it
    escalates every `OPEN` liquidity alert at least 60 minutes old, stamping
    `escalated_at`, reported as `escalated_alert_count`."

    Design: Corner/state_machines/network_sweep_expires_delivered_rfp_and_escalates_stale_alert
    """
    assert ALERT_ESCALATION_MINUTES == 60
    scenario, rfp = delivered_rfp_scenario(
        api,
        amount_cents=5_000_000,
        expiry_at="2026-08-03T14:00:00Z",
        memo="Invoice INV-7002",
    )
    assert rfp["status"] == "DELIVERED"
    withdraw_from_account(
        api,
        scenario.alpha.account_id,
        250_000_000,
        reference="Sweep to correspondent account",
    )
    alert = _sole_alert(api, scenario.alpha.account_id)
    assert alert["status"] == "OPEN"

    set_clock(api, "2026-08-03T14:00:00Z")
    report = run_sweep(api)

    assert_sweep_counts(
        report,
        expired_rfp_count=1,
        expired_return_request_count=0,
        expired_transfer_count=0,
        escalated_alert_count=1,
    )
    assert read_rfp(api, rfp["id"])["status"] == "EXPIRED"

    escalated = _sole_alert(api, scenario.alpha.account_id)
    assert escalated["status"] == "ESCALATED"
    assert_instant(escalated["escalated_at"], "2026-08-03T14:00:00Z", "escalated_at")
    assert escalated["cleared_at"] is None

    account = read_account(api, scenario.alpha.account_id)
    assert account["current_balance_cents"] == 950_000_000
    assert account["alert_tier"] == "RED"
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "SEND_FROZEN"


def test_a_parked_payment_is_diverted_to_the_declared_fallback_rail(api):
    """Outage contingency is a two-entity handshake: park first, then divert.

    PRD 3.9: "Each covered participant's `operational_posture` becomes `OFFLINE` — a
    value that outranks every other posture regardless of what the account band says —
    and each of that participant's transfers still in `INITIATED` is parked `INITIATED →
    QUEUED_THROTTLED` with `queued_at` stamped, which releases its reservation and
    therefore raises `available_cents` without any money moving."

    PRD 3.9: "The event's `diverted_transfer_count` is incremented by the number of
    transfers this declaration actually parked, which is zero when an earlier freeze had
    already parked them; a transfer that was already `QUEUED_THROTTLED` stays queued and
    is not counted again."

    PRD 3.9: "A diversion writes the supplied value into the transfer's `rail`, moves it
    `QUEUED_THROTTLED → DIVERTED`, and increments the covering event's
    `diverted_transfer_count`."

    PRD 3.9: "`DIVERTED` is terminal and non-reserving: the amount stays outside
    `reserved_cents` and the transfer never returns to the instant rail."

    Design: Corner/state_machines/transfer_diverted_to_fallback_rail_during_declared_outage
    """
    scenario, event, transfers = outage_scenario(
        api,
        started_at="2026-08-03T13:05:00Z",
        scope="PARTICIPANT",
        severity="FULL_OUTAGE",
        fallback_rail="FALLBACK_ACH",
        transfer_amounts=(100_000_000,),
    )
    parked = transfers[0]
    assert parked["clearing_status"] == "QUEUED_THROTTLED"
    assert_instant(parked["queued_at"], "2026-08-03T13:05:00Z", "queued_at")
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "OFFLINE"

    assert_outage_event_shape(event)
    assert event["status"] == "DECLARED"
    assert event["fallback_rail"] == "FALLBACK_ACH"
    assert event["diverted_transfer_count"] == 1

    diverted = divert_transfer(api, parked["id"], "FALLBACK_ACH", PAYMENT_OPERATOR_ALPHA)

    assert diverted["clearing_status"] == "DIVERTED"
    assert diverted["rail"] == "FALLBACK_ACH"
    assert diverted["settled_at"] is None
    assert diverted["irrevocable_at"] is None

    after = _outage_event(api, scenario.alpha.id, event["id"])
    assert after["status"] == "DECLARED"
    assert after["diverted_transfer_count"] == event["diverted_transfer_count"] + 1

    account = read_account(api, scenario.alpha.account_id)
    assert account["reserved_cents"] == 0
    assert account["current_balance_cents"] == 1_200_000_000
    assert list_ledger_entries(api, scenario.alpha.account_id) == []
