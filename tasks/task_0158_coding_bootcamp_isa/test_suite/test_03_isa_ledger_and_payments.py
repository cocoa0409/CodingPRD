"""ISA payment lifecycle (settle/fail/retry/refund), ledger reconciliation,
completion cascade, and the conserved-money invariant.

Translates corner-design `state_machines` (payment cycle), `cross_cutting`
(derived reconciliation), and difficulty `transitive_cascade` /
`compensating_invariant` instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    assert_isa_ledger_invariant,
    assert_payment,
    setup_graduated_isa,
    setup_isa_with_settled_payment,
    setup_isa_with_pending_payment,
    file_income_report,
    file_and_settle,
)

SERVICING = TEST_USERS["servicing_officer_headers"]


def test_payment_fail_then_retry_returns_to_pending():
    """PRD §3.9: "Failing a payment moves its `collection_status` from `PENDING` to `FAILED` with no ledger change, marking it uncollected. Retrying returns a failed payment from `FAILED` back to `PENDING` for re-collection, and is permitted only while the linked contract is `ACTIVE`."

    Design: Corner/state_machines/payment_fail_then_retry_returns_to_pending
    """
    isa, report, pay_id = setup_isa_with_pending_payment(gross_income_cents=600_000, email="retry@example.com")
    get_success_data(api_client.fail_payment(pay_id, SERVICING))
    retried = validate_success(api_client.retry_payment(pay_id, SERVICING), 200)
    assert retried["collection_status"] == "PENDING"
    assert_payment(retried)


def test_derived_remaining_cap_reconciled_after_settle():
    """PRD §2.5: "`amount_paid_cents` is the sum of the `amount_cents` of that contract's payments whose collection has settled, `payments_made_count` is the count of those settled payments, and `remaining_cap_cents` is `cap_cents` minus `amount_paid_cents`. These derived fields are reconciled immediately as the underlying payment ledger changes — the system never serves a contract whose ledger fields disagree with its payment rows."

    Design: Corner/cross_cutting_complexity_layers/derived_remaining_cap_reconciled_after_settle
    """
    isa, report, payment = setup_isa_with_settled_payment(gross_income_cents=600_000, email="recon@example.com")
    data = get_success_data(api_client.get_isa_contract(isa["id"], SERVICING))
    assert data["amount_paid_cents"] == 102_000
    assert data["remaining_cap_cents"] == 2_898_000
    assert data["payments_made_count"] == 1
    assert_isa_ledger_invariant(data)


def test_income_report_to_payment_to_ledger_to_completion_depth4():
    """PRD §3.9: "If after settlement `amount_paid_cents` has reached or exceeded `cap_cents`, the contract transitions `ACTIVE → COMPLETED`, no further payments are owed, `remaining_cap_cents` becomes zero, and the linked enrollment's `isa_status` mirrors the completion."

    Design: Difficulty/transitive_cascade/income_report_to_payment_to_ledger_to_completion_depth4
    """
    # Drive amount_paid to 2898000 (one 102000 obligation short of the 3000000 cap),
    # then a 600000 report settles to land exactly at the cap.
    _, _, enrollment, isa = setup_graduated_isa(email="depth4@example.com")
    isa_id = isa["id"]
    # gross 17047059 * 0.17 = 2898000.03 -> round_half_up 2898000; clamp to remaining 3000000.
    file_and_settle(isa_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 17_047_059)
    mid = get_success_data(api_client.get_isa_contract(isa_id, SERVICING))
    assert mid["amount_paid_cents"] == 2_898_000
    # Final 600000 report -> 102000 obligation -> settle -> cap reached.
    report = file_income_report(isa_id, "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", 600_000)
    pay2 = report["payment_id"]
    settled = validate_success(api_client.settle_payment(pay2, SERVICING), 200)
    assert settled["collection_status"] == "SETTLED"
    final = get_success_data(api_client.get_isa_contract(isa_id, SERVICING))
    assert final["amount_paid_cents"] == 3_000_000
    assert final["remaining_cap_cents"] == 0
    assert final["status"] == "COMPLETED"
    assert_isa_ledger_invariant(final)


def test_completion_cascade_mirrors_isa_status_on_enrollment():
    """PRD §3.9: "If after settlement `amount_paid_cents` has reached or exceeded `cap_cents`, the contract transitions `ACTIVE → COMPLETED`, no further payments are owed, `remaining_cap_cents` becomes zero, and the linked enrollment's `isa_status` mirrors the completion."

    Design: Difficulty/transitive_cascade/income_report_to_payment_to_ledger_to_completion_depth4
    """
    _, _, enrollment, isa = setup_graduated_isa(email="mirror@example.com")
    isa_id = isa["id"]
    enr_id = enrollment["id"]
    # One report that meets the cap in a single settlement (17647059*0.17=3000000.03->3000000,
    # clamped to remaining cap 3000000).
    file_and_settle(isa_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 17_647_059)
    contract = get_success_data(api_client.get_isa_contract(isa_id, SERVICING))
    assert contract["status"] == "COMPLETED"
    assert contract["amount_paid_cents"] == 3_000_000
    enr = get_success_data(api_client.get_enrollment(enr_id, SERVICING))
    assert enr["isa_status"] == "COMPLETED", "enrollment isa_status mirrors contract completion"


def test_isa_cap_money_conserved_under_payment_refund():
    """PRD §3.9: "Refunding reverses a settled collection: it requires the payment's `collection_status` to be `SETTLED` and its `refund_status` to be `NONE`, sets `refund_status` to `REFUNDED` so the rollup `status` becomes `REVERSED`, and applies a compensating reversal to the ledger by subtracting the payment's `amount_cents` from the contract's `amount_paid_cents`."
    PRD §2.5: "On an ISAContract, `amount_paid_cents` plus `remaining_cap_cents` always equals `cap_cents`; `amount_paid_cents` is the sum of the `amount_cents` of that contract's payments whose collection has settled, `payments_made_count` is the count of those settled payments, and `remaining_cap_cents` is `cap_cents` minus `amount_paid_cents`."

    Design: Difficulty/compensating_invariant/isa_cap_money_conserved_under_payment_refund
    """
    isa, report, payment = setup_isa_with_settled_payment(gross_income_cents=600_000, email="conserve@example.com")
    isa_id = isa["id"]
    before = get_success_data(api_client.get_isa_contract(isa_id, SERVICING))
    assert before["amount_paid_cents"] == 102_000
    assert_isa_ledger_invariant(before)

    refunded = validate_success(api_client.refund_payment(payment["id"], SERVICING), 200)
    assert refunded["refund_status"] == "REFUNDED"
    after = get_success_data(api_client.get_isa_contract(isa_id, SERVICING))
    assert after["amount_paid_cents"] == 0, "refund reverses the ledger"
    assert after["remaining_cap_cents"] == 3_000_000
    assert after["amount_paid_cents"] + after["remaining_cap_cents"] == 3_000_000
    assert_isa_ledger_invariant(after)


def test_payment_refund_rollup_status_becomes_reversed():
    """PRD §3.9: "The exposed `status` is a computed rollup: it mirrors `collection_status` as `PENDING`, `FAILED`, or `SETTLED`, unless `refund_status` is `REFUNDED`, in which case the rollup reads `REVERSED`."

    Design: Difficulty/compensating_invariant/isa_cap_money_conserved_under_payment_refund
    """
    isa, report, payment = setup_isa_with_settled_payment(gross_income_cents=600_000, email="reversed@example.com")
    refunded = validate_success(api_client.refund_payment(payment["id"], SERVICING), 200)
    assert refunded["refund_status"] == "REFUNDED"
    assert refunded["status"] == "REVERSED", "rollup status must read REVERSED after refund"
    assert_payment(refunded)
