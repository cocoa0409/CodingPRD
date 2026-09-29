"""Compensating actions: the undo appends, and the invariant comes back exactly."""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import api_client
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_claim_incurred_identity,
    assert_erosion_reconciles,
    assert_ledger_balances,
    assert_ledger_sequence,
    assert_premium_transaction,
)
from test_helpers.factories import loss_item

LEDGER_PART_PLAN = (
    ("SOFT_COST", 300000000),
    ("DELAY_IN_COMPLETION", 250000000),
    ("MATERIALS_ON_SITE", 1000000000),
)


def _account_with_two_approved_extensions():
    """Two approvals, both in the 1.15 tier: 45 days then 30 more."""
    account = fx.in_force_account(parts=LEDGER_PART_PLAN)
    assert account.policy["quoted_premium_cents"] == 2750440, account.policy

    first = fx.file_endorsement(account, 45, slip_reason="MATERIAL_DELAY")
    assert first["additional_premium_cents"] == 471287, first
    first = fx.decide_endorsement(account, first, "APPROVE", headers=fx.UM)

    after_first = fx.premium_summary(account)
    assert after_first["written_premium_cents"] == 3221727, after_first
    assert after_first["transaction_count"] == 2, after_first
    assert after_first["balanced"] is True, after_first

    second = fx.file_endorsement(account, 30, slip_reason="LABOR_SHORTAGE")
    assert second["additional_premium_cents"] == 314192, second
    second = fx.decide_endorsement(account, second, "APPROVE", headers=fx.UM)
    return account, first, second


def test_rescission_restores_the_written_premium_by_appending_a_reversal():
    """Before the rescission the ledger holds three rows summing to 3535919. The
    rescission appends a fourth row instead of editing the third, so the balance
    returns to its exact pre-approval 3221727 while the count grows and the
    signed EXTENSION_AP total, which per the PRD nets the EXTENSION_AP_REVERSAL
    row against the charges, falls from 785479 back to 471287. The other
    endorsement is untouched.

    Design: Difficulty/compensating_invariant/extension_rescission_conserves_the_premium_ledger_balance
    """
    account, first, second = _account_with_two_approved_extensions()

    before = fx.premium_summary(account)
    assert before["written_premium_cents"] == 3535919, before
    assert before["ledger_sum_cents"] == 3535919, before
    assert before["transaction_count"] == 3, before
    assert before["extension_ap_total_cents"] == 785479, before

    rescinded = get_success_data(
        api_client.rescind_endorsement(second["id"], fx.UM2))
    assert rescinded["status"] == "RESCINDED", rescinded

    after = fx.premium_summary(account)
    assert after["written_premium_cents"] == 3221727, after
    assert after["ledger_sum_cents"] == 3221727, after
    assert after["transaction_count"] == 4, after
    assert after["extension_ap_total_cents"] == 471287, after
    assert after["balanced"] is True, after

    held = get_success_data(
        api_client.get_extension_endorsement(first["id"], fx.UW))
    assert held["status"] == "APPROVED", held
    assert held["additional_premium_cents"] == 471287, held


def test_rescission_restores_the_schedule_and_leaves_the_charged_row_in_place():
    """The compensation is not only monetary: the cumulative days, the term end
    and the delay baseline all come back to the values the first approval left.
    The ledger keeps the charge and its exact negative side by side, in
    sequence_no order, with the reversal pointing at a strictly smaller
    sequence_no than its own.

    Design: Difficulty/compensating_invariant/extension_rescission_conserves_the_premium_ledger_balance
    """
    account, _first, second = _account_with_two_approved_extensions()
    get_success_data(api_client.rescind_endorsement(second["id"], fx.UM2))

    policy = account.refresh_policy()
    assert policy["cumulative_extension_days"] == 45, policy
    assert policy["term_end_date"].startswith("2027-08-14"), policy
    assert policy["adjusted_completion_date"].startswith("2027-07-16"), policy
    assert policy["written_premium_cents"] == 3221727, policy

    ledger = sorted(fx.premium_ledger(account), key=lambda row: row["sequence_no"])
    for row in ledger:
        assert_premium_transaction(row)
    assert_ledger_sequence(ledger)
    assert_ledger_balances(ledger, policy["written_premium_cents"])

    assert [row["amount_cents"] for row in ledger] == [
        2750440, 471287, 314192, -314192], ledger
    assert [row["txn_type"] for row in ledger] == [
        "INITIAL", "EXTENSION_AP", "EXTENSION_AP", "EXTENSION_AP_REVERSAL"], ledger

    charge, reversal = ledger[2], ledger[3]
    assert charge["reverses_sequence_no"] is None, charge
    assert reversal["reverses_sequence_no"] == charge["sequence_no"], reversal
    assert reversal["reverses_sequence_no"] < reversal["sequence_no"], reversal


THREE_BUCKET_PART_PLAN = (
    ("MATERIALS_ON_SITE", 1000000000),
    ("IN_TRANSIT", 200000000),
    ("SOFT_COST", 300000000),
)

RECONSTRUCTION_ITEMS = [
    loss_item("MATERIALS_ON_SITE", 45678920),
    loss_item("IN_TRANSIT", 12345670),
]

SUBLIMITS = dict(THREE_BUCKET_PART_PLAN)


def _assert_bucket_identity(account):
    """available_cents + eroded_cents == sublimit_cents, bucket by bucket."""
    parts = account.refresh_parts()
    for part_type, sublimit in SUBLIMITS.items():
        part = parts[part_type]
        assert part["available_cents"] + part["eroded_cents"] == sublimit, part
    assert_erosion_reconciles(account.refresh_policy(), list(parts.values()))
    return parts


def _multi_part_claim():
    """One claim allocated across two buckets plus a synthetic soft-cost line."""
    account = fx.in_force_account(parts=THREE_BUCKET_PART_PLAN)
    claim = fx.adjusted_claim(
        account, RECONSTRUCTION_ITEMS, adjustment_basis="RECONSTRUCTION_COST",
        continuing_pm_weeks=6, peril="FIRE", loss_date="2027-01-18T00:00:00Z",
        description="Fire across staged materials and an inbound shipment")
    assert claim["indemnity_cents"] == 53230557, claim
    return account, claim


def _pay_both_buckets(account, claim):
    fx.issue_payment(account, claim, "MATERIALS_ON_SITE", 39333234)
    after_first = get_success_data(api_client.get_claim(claim["id"], fx.CA))
    assert after_first["paid_cents"] == 39333234, after_first
    assert after_first["outstanding_reserve_cents"] == 13897323, after_first
    second = fx.issue_payment(account, after_first, "SOFT_COST", 563999)
    return second


def test_voiding_one_payment_unwinds_only_its_own_bucket():
    """The compensation is per payment, not per claim: the voided soft-cost
    payment restores that bucket to exactly its pre-payment position while the
    materials bucket stays eroded by the payment that still stands. The policy's
    erosion total and the claim's paid and reserve figures follow the surviving
    ISSUED row, and neither claim axis is reset.

    Design: Difficulty/compensating_invariant/payment_void_conserves_erosion_and_reserve_across_a_multi_part_claim
    """
    account, claim = _multi_part_claim()
    second = _pay_both_buckets(account, claim)

    policy = account.refresh_policy()
    assert policy["eroded_total_cents"] == 39897233, policy

    voided = fx.void_payment(account, second, headers=fx.UM)
    assert voided["status"] == "VOIDED", voided

    parts = account.refresh_parts()
    assert parts["SOFT_COST"]["eroded_cents"] == 0, parts["SOFT_COST"]
    assert parts["SOFT_COST"]["available_cents"] == 300000000, parts["SOFT_COST"]
    assert parts["MATERIALS_ON_SITE"]["eroded_cents"] == 39333234, parts
    assert parts["MATERIALS_ON_SITE"]["available_cents"] == 960666766, parts
    assert parts["IN_TRANSIT"]["eroded_cents"] == 0, parts["IN_TRANSIT"]
    assert parts["IN_TRANSIT"]["available_cents"] == 200000000, parts["IN_TRANSIT"]

    restored = account.refresh_policy()
    assert restored["eroded_total_cents"] == 39333234, restored

    final = get_success_data(api_client.get_claim(claim["id"], fx.CA))
    assert final["paid_cents"] == 39333234, final
    assert final["outstanding_reserve_cents"] == 13897323, final
    assert final["payment_status"] == "PARTIALLY_PAID", final
    assert final["adjustment_status"] == "ADJUSTED", final


def test_the_voided_row_is_retained_and_contributes_nothing_to_the_identities():
    """The payment history is not rewritten: the voided row survives beside the
    issued one and simply stops counting. Through all four checkpoints the
    per-bucket identity available + eroded == sublimit holds, the policy's
    erosion equals the sum over its buckets, and total_incurred_cents stays
    pinned to the adjusted indemnity.

    Design: Difficulty/compensating_invariant/payment_void_conserves_erosion_and_reserve_across_a_multi_part_claim
    """
    account, claim = _multi_part_claim()
    _assert_bucket_identity(account)
    assert claim["total_incurred_cents"] == 53230557, claim

    second = _pay_both_buckets(account, claim)
    _assert_bucket_identity(account)
    mid = get_success_data(api_client.get_claim(claim["id"], fx.CA))
    assert mid["total_incurred_cents"] == 53230557, mid

    fx.void_payment(account, second, headers=fx.UM)
    _assert_bucket_identity(account)

    final = get_success_data(api_client.get_claim(claim["id"], fx.CA))
    assert final["total_incurred_cents"] == 53230557, final
    assert_claim_incurred_identity(final)

    rows, _meta = validate_paginated(api_client.list_loss_payments(
        fx.CA, params={"claim_id": claim["id"], "limit": 100}))
    assert len(rows) == 2, f"the voided row must be retained: {rows}"
    assert sorted(row["status"] for row in rows) == ["ISSUED", "VOIDED"], rows
    issued = [row for row in rows if row["status"] == "ISSUED"]
    assert sum(row["amount_cents"] for row in issued) == 39333234, rows
