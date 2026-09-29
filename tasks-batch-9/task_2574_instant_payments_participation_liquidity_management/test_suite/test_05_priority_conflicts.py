"""One request, several broken rules, exactly one answer.

A send can be simultaneously frozen out on posture grounds and short of the floor on
funding grounds; it can be forbidden by the bank's participation model and over three
limits at once. The rejection order is normative, so each pair is tested together with
the counterfactual that proves the losing rule was genuinely violated and merely
outranked, not accidentally satisfied.
"""

from test_helpers import (
    CORPORATE_POLICY,
    ERR_INSUFFICIENT_LIQUIDITY,
    ERR_PARTICIPANT_SEND_FROZEN,
    ERR_PER_TRANSACTION_LIMIT_EXCEEDED,
    ERR_SEND_NOT_PERMITTED_FOR_MODEL,
    PAYMENT_OPERATOR_ALPHA,
    PAYMENT_OPERATOR_GAMMA,
    ROUTING_BETA,
    account_version,
    alpha_scenario,
    assert_account_position,
    configure_participant,
    credit_transfer_payload,
    frozen_alpha_scenario,
    list_transfers,
    live_gamma,
    open_settlement_cycle,
    read_account,
    read_participant,
    set_clock,
    validate_error,
)

WIDE_CORPORATE_POLICY = dict(
    CORPORATE_POLICY,
    per_transaction_limit_cents=1_200_000_000,
    daily_aggregate_limit_cents=2_000_000_000,
    rolling_window_amount_limit_cents=2_000_000_000,
)


def test_frozen_bank_is_told_it_is_frozen_not_that_it_lacks_funds(api):
    """Posture beats funding: the 409 is returned even though the floor is also broken.

    PRD 2.11: "A send-side freeze is a *posture* condition on rung 7, so it outranks
    every liquidity, limit and velocity check on rungs 11 and 12: a frozen participant is
    told it is frozen, never that it lacks funds."

    Design: Difficulty/priority_pair_validation_conflict/send_frozen_state_outranks_insufficient_liquidity_fiscal
    """
    scenario = frozen_alpha_scenario(api, withdrawal_cents=1_000_000_000)
    before = read_account(api, scenario.alpha.account_id)
    assert_account_position(
        before,
        current_balance_cents=200_000_000,
        reserved_cents=0,
        available_cents=200_000_000,
        alert_tier="RED",
    )
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "SEND_FROZEN"

    payload = credit_transfer_payload(
        scenario.alpha.id,
        scenario.alpha.customer_account_id,
        100_000_000,
        account_version(api, scenario.alpha.account_id),
        receiver_routing_number=ROUTING_BETA,
    )
    response = api.create_credit_transfer(payload, PAYMENT_OPERATOR_ALPHA)
    validate_error(response, ERR_PARTICIPANT_SEND_FROZEN)

    assert list_transfers(api, {"originator_participant_id": scenario.alpha.id}) == []
    after = read_account(api, scenario.alpha.account_id)
    assert_account_position(
        after,
        current_balance_cents=200_000_000,
        reserved_cents=0,
        available_cents=200_000_000,
        alert_tier="RED",
    )


def test_same_shortfall_without_the_freeze_returns_the_liquidity_error(api):
    """The suppressed rung is real: an unfrozen bank hears about the floor instead.

    PRD 3.4: "**Liquidity** is checked last of all: the originating account's
    `available_cents` minus this `amount_cents` must be at least `floor_cents`."

    Design: Difficulty/priority_pair_validation_conflict/send_frozen_state_outranks_insufficient_liquidity_fiscal
    """
    scenario = alpha_scenario(api, policy=WIDE_CORPORATE_POLICY)
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "NORMAL"
    assert read_account(api, scenario.alpha.account_id)["alert_tier"] == "GREEN"

    payload = credit_transfer_payload(
        scenario.alpha.id,
        scenario.alpha.customer_account_id,
        1_000_000_001,
        account_version(api, scenario.alpha.account_id),
        receiver_routing_number=ROUTING_BETA,
    )
    response = api.create_credit_transfer(payload, PAYMENT_OPERATOR_ALPHA)
    validate_error(response, ERR_INSUFFICIENT_LIQUIDITY)

    assert list_transfers(api, {"originator_participant_id": scenario.alpha.id}) == []
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 0


def _live_receive_only_gamma(api):
    """Gamma Savings Bank live on RECEIVE_ONLY, fully configured to send if it could."""
    set_clock(api, "2026-08-03T13:00:00Z")
    gamma = live_gamma(api, participation_model="RECEIVE_ONLY")
    gamma = configure_participant(api, gamma, customer_reference="CUST-GAMMA-0001")
    open_settlement_cycle(api)
    return gamma


def test_receive_only_model_is_reported_ahead_of_three_broken_limits(api):
    """Network compliance beats every limit rung, and the request breaks three of them.

    PRD 3.4: "Its `participation_model` must permit sending: a `RECEIVE_ONLY` bank and a
    `RECEIVE_AND_REQUEST_FOR_PAYMENT` bank may never originate, and both are refused with
    `ERR_SEND_NOT_PERMITTED_FOR_MODEL` rather than with a limit error, because the model
    check is network compliance and outranks every limit rung."

    Design: Difficulty/priority_pair_validation_conflict/model_safety_outranks_per_transaction_constraint
    """
    gamma = _live_receive_only_gamma(api)
    participant = read_participant(api, gamma.id)
    assert participant["enrollment_status"] == "LIVE"
    assert participant["operational_posture"] == "NORMAL"
    assert read_account(api, gamma.account_id)["alert_tier"] == "GREEN"

    payload = credit_transfer_payload(
        gamma.id,
        gamma.customer_account_id,
        900_000_000,
        account_version(api, gamma.account_id),
        receiver_routing_number=ROUTING_BETA,
    )
    response = api.create_credit_transfer(payload, PAYMENT_OPERATOR_GAMMA)
    validate_error(response, ERR_SEND_NOT_PERMITTED_FOR_MODEL)

    assert list_transfers(api, {"originator_participant_id": gamma.id}) == []
    assert read_account(api, gamma.account_id)["reserved_cents"] == 0


def test_identical_amount_from_a_sending_bank_hits_the_per_transaction_limit(api):
    """With the model check satisfied, the first limit rung is the one that answers.

    PRD 3.4: "First the amount is compared with the pinned policy's
    `per_transaction_limit_cents`; the comparison is at-most, so an amount exactly equal
    to the limit is admitted and anything larger is refused with
    `ERR_PER_TRANSACTION_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/model_safety_outranks_per_transaction_constraint
    """
    scenario = alpha_scenario(api)
    assert read_participant(api, scenario.alpha.id)["participation_model"] == "SEND_AND_RECEIVE"

    payload = credit_transfer_payload(
        scenario.alpha.id,
        scenario.alpha.customer_account_id,
        900_000_000,
        account_version(api, scenario.alpha.account_id),
        receiver_routing_number=ROUTING_BETA,
    )
    response = api.create_credit_transfer(payload, PAYMENT_OPERATOR_ALPHA)
    validate_error(response, ERR_PER_TRANSACTION_LIMIT_EXCEEDED)

    assert list_transfers(api, {"originator_participant_id": scenario.alpha.id}) == []
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 0
