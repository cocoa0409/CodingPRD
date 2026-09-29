"""
Transitive cascades: a purchase reversal reaching the posture four hops later, and
a fraud confirmation reaching the ledger four hops later.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_account_aggregates,
    assert_ledger_entry,
    assert_ledger_entry_types,
    read_ledger,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    APPROVER_HEADERS,
    APPROVER_USER_ID,
)
from test_helpers.types import (
    BENEFIT_BAGGAGE_FEE_CREDIT,
    BENEFIT_LOUNGE_ACCESS,
    BENEFIT_TRAVEL_INSURANCE,
    CASE_CONFIRMED,
    ENTITLEMENT_ACTIVE,
    ENTITLEMENT_SUSPENDED,
    ENTRY_CLAWBACK,
    ENTRY_EARN_BASE,
    ENTRY_TRANSFER_DEBIT,
    ENTRY_TRANSFER_REVERSAL,
    HOLD_INSUFFICIENT_BALANCE_AFTER_CLAWBACK,
    POSTURE_CLEAR,
    POSTURE_LOCKED,
    POSTURE_WATCH,
    RESOLUTION_POSTURE_LOCKED,
    SIGNAL_PASSWORD_RESET,
    SOURCE_TRANSACTION,
    SOURCE_TRANSFER_REQUEST,
    SUSPENSION_POSTURE_LOCKED,
    SUSPENSION_POSTURE_WATCH,
    SYSTEM_USER_ID,
    TRANSACTION_POSTED,
    TRANSACTION_REVERSED,
    TRANSFER_HELD,
    TRANSFER_REJECTED,
    TRANSFER_SUBMITTED,
)


def _two_purchases_and_two_transfers(api):
    """10,000 earned points, 8,000 of them reserved by two in-flight transfers."""
    account, cardholder = fx.funded_account(api, 0)
    first = fx.fund_account(api, account["id"], 5000)
    second = fx.fund_account(api, account["id"], 5000)
    lounge = fx.grant_entitlement(
        api,
        account["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_LOUNGE_ACCESS,
        annual_allowance=6,
    )
    baggage = fx.grant_entitlement(
        api,
        account["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_BAGGAGE_FEE_CREDIT,
        annual_allowance=3,
    )
    agreement = fx.active_agreement(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        partner_name="Skyward Miles",
        partner_program_code="SKYW",
    )
    transfer_one = fx.submit_transfer(
        api, account["id"], agreement["id"], 4000, cardholder
    )
    transfer_two = fx.submit_transfer(
        api, account["id"], agreement["id"], 4000, cardholder
    )
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=2000,
        points_pending_redemption=8000,
    )
    return {
        "account": account,
        "first": first,
        "second": second,
        "lounge": lounge,
        "baggage": baggage,
        "transfers": [transfer_one, transfer_two],
    }


def test_the_clawback_hop_drives_the_balance_negative_and_spares_the_other_purchase(api):
    """
    "The first hop sets `reversed_at` to the clock instant, records
    `reversal_reason`, and appends a `CLAWBACK` ledger entry whose `points_delta` is
    the negative of the purchase's `total_points_earned` ..."

    Design: Difficulty/transitive_cascade/cascade_transaction_reversal_to_negative_balance_to_holds_to_posture
    """
    world = _two_purchases_and_two_transfers(api)

    reversed_row = validate_success(
        api.reverse_transaction(
            world["second"]["id"],
            f.reversal_payload("MERCHANT_CHARGEBACK"),
            ADMIN_HEADERS,
        )
    )
    assert reversed_row["status"] == TRANSACTION_REVERSED
    assert reversed_row["reversal_reason"] == "MERCHANT_CHARGEBACK"
    assert reversed_row["reversed_at"] is not None
    assert (
        validate_success(api.get_transaction(world["first"]["id"], ADMIN_HEADERS))[
            "status"
        ]
        == TRANSACTION_POSTED
    )

    entries = read_ledger(api, ADMIN_HEADERS, world["account"]["id"])
    assert_ledger_entry(
        entries[-1],
        entry_type=ENTRY_CLAWBACK,
        points_delta=-5000,
        balance_after=-3000,
        source_entity_type=SOURCE_TRANSACTION,
        source_entity_id=world["second"]["id"],
    )
    # §2.7 pins the aggregate: "Its `lifetime_points_earned` is the sum of
    # `points_delta` over entries whose `entry_type` is `EARN_BASE` or
    # `EARN_BONUS`."  A `CLAWBACK` entry is neither, so recomputing the aggregate
    # after the reversal still yields the two 5,000-point earn legs.
    assert_account_aggregates(
        fx.read_account(api, world["account"]["id"]),
        points_balance=-3000,
        points_pending_redemption=8000,
        lifetime_points_earned=10000,
    )


def test_a_negative_balance_holds_every_in_flight_transfer_in_the_system_name(api):
    """
    "If the recomputed `points_balance` is strictly negative, every transfer request
    of this account whose `status` is `SUBMITTED` or `QUEUED` is moved to `HELD` with
    `hold_reason` `INSUFFICIENT_BALANCE_AFTER_CLAWBACK` and `held_by_user_id` set to
    the literal string `SYSTEM` ..."

    Design: Difficulty/transitive_cascade/cascade_transaction_reversal_to_negative_balance_to_holds_to_posture
    """
    world = _two_purchases_and_two_transfers(api)
    validate_success(
        api.reverse_transaction(
            world["second"]["id"],
            f.reversal_payload("MERCHANT_CHARGEBACK"),
            ADMIN_HEADERS,
        )
    )

    for transfer in world["transfers"]:
        held = fx.read_transfer(api, transfer["id"])
        assert held["status"] == TRANSFER_HELD
        assert held["hold_reason"] == HOLD_INSUFFICIENT_BALANCE_AFTER_CLAWBACK
        assert held["held_by_user_id"] == SYSTEM_USER_ID

    assert_account_aggregates(
        fx.read_account(api, world["account"]["id"]),
        transfer_hold_count=2,
    )


def test_the_hold_count_hop_watches_the_account_and_touches_only_lounge_access(api):
    """
    "the posture calculation re-runs against the new `transfer_hold_count`, and when
    that count reaches 2 the account moves `CLEAR` → `WATCH`, which suspends every
    `LOUNGE_ACCESS` benefit entitlement the account holds."

    Design: Difficulty/transitive_cascade/cascade_transaction_reversal_to_negative_balance_to_holds_to_posture
    """
    world = _two_purchases_and_two_transfers(api)
    validate_success(
        api.reverse_transaction(
            world["second"]["id"],
            f.reversal_payload("MERCHANT_CHARGEBACK"),
            ADMIN_HEADERS,
        )
    )

    assert_account_aggregates(
        fx.read_account(api, world["account"]["id"]),
        fraud_posture=POSTURE_WATCH,
        transfer_hold_count=2,
    )
    lounge = fx.read_entitlement(api, world["lounge"]["id"])
    assert lounge["status"] == ENTITLEMENT_SUSPENDED
    assert lounge["suspension_reason"] == SUSPENSION_POSTURE_WATCH
    assert (
        fx.read_entitlement(api, world["baggage"]["id"])["status"]
        == ENTITLEMENT_ACTIVE
    )


def _case_under_review_on_a_transferring_account(api):
    """A low-scoring case under review while 4,000 points sit in a transfer."""
    account, cardholder = fx.funded_account(api, 20000)
    insurance = fx.grant_entitlement(
        api,
        account["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_TRAVEL_INSURANCE,
        annual_allowance=2,
    )
    agreement = fx.active_agreement(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        partner_name="Skyward Miles",
        partner_program_code="SKYW",
    )
    transfer = fx.submit_transfer(
        api, account["id"], agreement["id"], 4000, cardholder
    )
    case = fx.open_case(
        api,
        account["id"],
        ANALYST_HEADERS,
        signals=[SIGNAL_PASSWORD_RESET],
        device_fingerprint_changed=False,
    )
    reviewed = fx.review_case(api, case["id"], ANALYST_HEADERS)
    return account, transfer, case, reviewed, insurance


def test_the_device_stability_credit_lowers_the_review_score_below_every_threshold(api):
    """
    "The third term is a device-stability credit of 10, granted only when
    `device_fingerprint_changed` is false and suppressed entirely when it is true."

    Design: Difficulty/transitive_cascade/cascade_fraud_confirmation_to_lock_to_rejection_to_ledger_restoration
    """
    account, transfer, _, reviewed, insurance = _case_under_review_on_a_transferring_account(api)

    assert reviewed["instant_score"] == 15
    assert reviewed["review_score"] == 5
    assert reviewed["risk_score"] == 5

    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=16000,
        points_pending_redemption=4000,
        fraud_posture=POSTURE_CLEAR,
    )
    assert fx.read_transfer(api, transfer["id"])["status"] == TRANSFER_SUBMITTED
    assert fx.read_entitlement(api, insurance["id"])["status"] == ENTITLEMENT_ACTIVE


def test_a_confirmed_case_locks_rejects_and_restores_the_points_whatever_it_scored(api):
    """
    "The second hop, caused by the first, pins the account's posture at `LOCKED`
    because a `CONFIRMED` case now exists. The third hop ... moves every `SUBMITTED`,
    `QUEUED`, or `HELD` transfer request of the account to `REJECTED` with
    `resolution_reason` `POSTURE_LOCKED`. The fourth hop ... appends a
    `TRANSFER_REVERSAL` ledger entry for each rejection ..."

    Design: Difficulty/transitive_cascade/cascade_fraud_confirmation_to_lock_to_rejection_to_ledger_restoration
    """
    account, transfer, case, _, insurance = _case_under_review_on_a_transferring_account(api)

    confirmed = fx.confirm_case(api, case["id"], APPROVER_HEADERS)
    assert confirmed["status"] == CASE_CONFIRMED
    assert confirmed["instant_score"] == 15
    assert confirmed["review_score"] == 5
    assert confirmed["risk_score"] == 5
    assert confirmed["resolved_by_user_id"] == APPROVER_USER_ID

    rejected = fx.read_transfer(api, transfer["id"])
    assert rejected["status"] == TRANSFER_REJECTED
    assert rejected["resolution_reason"] == RESOLUTION_POSTURE_LOCKED

    entries = read_ledger(api, ADMIN_HEADERS, account["id"])
    assert_ledger_entry_types(
        entries, [ENTRY_EARN_BASE, ENTRY_TRANSFER_DEBIT, ENTRY_TRANSFER_REVERSAL]
    )
    assert_ledger_entry(
        entries[2],
        entry_type=ENTRY_TRANSFER_REVERSAL,
        points_delta=4000,
        balance_after=20000,
        source_entity_type=SOURCE_TRANSFER_REQUEST,
        source_entity_id=transfer["id"],
    )
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=20000,
        points_pending_redemption=0,
        fraud_posture=POSTURE_LOCKED,
    )
    locked = fx.read_entitlement(api, insurance["id"])
    assert locked["status"] == ENTITLEMENT_SUSPENDED
    assert locked["suspension_reason"] == SUSPENSION_POSTURE_LOCKED
