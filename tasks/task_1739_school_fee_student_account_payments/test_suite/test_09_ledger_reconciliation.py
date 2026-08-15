"""Department distribution ledger and year-end reconciliation invariant."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, ApiErrorId,
    create_department_payload, create_fee_catalog_item_payload,
    create_offering_payload,
    setup_open_year, add_student_with_account, pay_and_settle, set_clock,
    make_bookkeeper_headers, make_family_headers,
)

BK = make_bookkeeper_headers()


def _two_department_year():
    """OPEN year with departments D1/D2, fees 6000 (D1) + 4000 (D2) on
    disjoint-window offerings, and one account enrolled in both."""
    env = setup_open_year()
    year_id = env["year"]["id"]
    d1 = env["department"]
    d2 = get_success_data(api_client.create_department(
        year_id, create_department_payload(code="ATH", name="Athletics"), BK))
    f1 = get_success_data(api_client.create_fee_catalog_item(
        year_id, create_fee_catalog_item_payload(
            name="F1", amount_cents=6000, department_id=d1["id"]), BK))
    f2 = get_success_data(api_client.create_fee_catalog_item(
        year_id, create_fee_catalog_item_payload(
            name="F2", amount_cents=4000, department_id=d2["id"]), BK))
    o1 = get_success_data(api_client.create_offering(year_id, create_offering_payload(
        title="Chem", department_id=d1["id"], fee_item_id=f1["id"],
        start_date="2026-09-01", end_date="2026-12-15"), BK))
    o2 = get_success_data(api_client.create_offering(year_id, create_offering_payload(
        kind="ACTIVITY", title="Track", department_id=d2["id"], fee_item_id=f2["id"],
        start_date="2027-01-05", end_date="2027-04-30"), BK))
    student, account = add_student_with_account(year_id)
    get_success_data(api_client.create_enrollment(account["id"], {"offering_id": o1["id"]}, BK))
    get_success_data(api_client.create_enrollment(account["id"], {"offering_id": o2["id"]}, BK))
    return {"year": env["year"], "d1": d1, "d2": d2, "f1": f1, "f2": f2,
            "o1": o1, "o2": o2, "student": student, "account": account}


class TestLedgerWrites:
    def test_ledger_entries_written_per_allocation(self):
        """PRD §3.5: "Every allocation also writes a `DISTRIBUTION_CREDIT` ledger
        entry for its assessment's department_id, tagged with the payment's
        source_payment_id."
        PRD §2.11: "A LedgerEntry carries the student_account_id giving account
        context, the credited or debited department_id, an entry_type, a signed
        amount_cents, the source_payment_id of the payment whose allocation
        produced a distribution (null on write-off rows), and a
        reconciliation_run_id that stays null until a reconciliation run stamps
        it."

        Design: Corner/endpoints/ledger_entries_written_per_allocation
        """
        env = _two_department_year()
        account_id = env["account"]["id"]
        payment = get_success_data(api_client.create_payment(
            account_id, {"amount_cents": 10000, "method": "CARD",
                         "idempotency_key": "k1"}, make_family_headers()))
        get_success_data(api_client.settle_payment(
            account_id, payment["id"], {"outcome": "SUCCEEDED"}, make_family_headers()))
        entries, meta = validate_paginated(api_client.list_ledger_entries(account_id, BK))
        assert meta["total_count"] == 2, f"Expected 2 credit rows; got {meta['total_count']}"
        amounts = sorted(e["amount_cents"] for e in entries)
        assert amounts == [4000, 6000], f"6000 to D1 and 4000 to D2; got {amounts}"
        for e in entries:
            assert e["entry_type"] == "DISTRIBUTION_CREDIT"
            assert e["source_payment_id"] == payment["id"]
            assert e["reconciliation_run_id"] is None
        d1_entry = [e for e in entries if e["amount_cents"] == 6000][0]
        assert d1_entry["department_id"] == env["d1"]["id"]
        d2_entry = [e for e in entries if e["amount_cents"] == 4000][0]
        assert d2_entry["department_id"] == env["d2"]["id"]


class TestReconciliationInvariant:
    def test_distribution_ledger_conserved_across_payment_and_refund(self):
        """PRD §3.8: "The invariant the run verifies is exact and holds after
        every mutation: the sum of all departments' distributed_cents equals the
        sum of allocations over succeeded payments, plus the sum of purchase
        amounts over completed and refunded purchases, minus the sum of executed
        refunds, minus the sum of written_off_cents across cases."
        PRD §2.11: "A department's distributed_cents is the sum of its
        DISTRIBUTION_CREDIT entries plus the sum of its DISTRIBUTION_REVERSAL
        entries (reversals being negative)."
        PRD §3.7: "Assessment- and purchase-sourced executions also write
        `DISTRIBUTION_REVERSAL` ledger entries (negative amounts) against the
        original departments."

        Design: Difficulty/compensating_invariant/distribution_ledger_conserved_across_payment_and_refund
        """
        env = _two_department_year()
        account_id, year_id = env["account"]["id"], env["year"]["id"]
        pay_and_settle(account_id, 10000, idempotency_key="k1")
        # Day 3 -> PARTIAL tier: withdraw the D1 enrollment, refund floor(6000*0.5)=3000
        set_clock("2026-09-04T00:00:00Z")
        enrollments = get_success_data(api_client.list_enrollments(account_id, BK))
        e1 = [e for e in enrollments if e["offering_id"] == env["o1"]["id"]][0]
        get_success_data(api_client.withdraw_enrollment(account_id, e1["id"], BK))
        refund = get_success_data(api_client.list_refunds(account_id, BK))[0]
        assert refund["refund_cents"] == 3000
        get_success_data(api_client.execute_refund(account_id, refund["id"], BK))
        d1 = get_success_data(api_client.get_department(year_id, env["d1"]["id"], BK))
        d2 = get_success_data(api_client.get_department(year_id, env["d2"]["id"], BK))
        assert d1["distributed_cents"] == 3000, (
            f"6000 credit - 3000 reversal; got {d1['distributed_cents']}")
        assert d2["distributed_cents"] == 4000
        assert d1["distributed_cents"] + d2["distributed_cents"] == 7000
        run = get_success_data(api_client.create_reconciliation_run(year_id, BK))
        assert run["drift_detected"] is False, (
            "Invariant sum(distributed) == allocations - refunds - write-offs must hold")
        assert run["status"] == "COMPLETED"

    def test_reconciliation_stamps_entries_and_advances_counters(self):
        """PRD §3.8: "Every ledger entry whose reconciliation_run_id is still null
        is stamped with the run's id, and the run's entries_reconciled counts
        them." and "either way each department's reconciled_cents advances to its
        actual figure and unreconciled_cents recomputes."
        PRD §2.11: "unreconciled_cents is distributed_cents minus
        reconciled_cents."

        Design: Difficulty/compensating_invariant/distribution_ledger_conserved_across_payment_and_refund
        """
        env = _two_department_year()
        account_id, year_id = env["account"]["id"], env["year"]["id"]
        payment = get_success_data(api_client.create_payment(
            account_id, {"amount_cents": 10000, "method": "CARD",
                         "idempotency_key": "k1"}, make_family_headers()))
        get_success_data(api_client.settle_payment(
            account_id, payment["id"], {"outcome": "SUCCEEDED"}, make_family_headers()))
        run = get_success_data(api_client.create_reconciliation_run(year_id, BK))
        assert run["entries_reconciled"] == 2
        d1 = get_success_data(api_client.get_department(year_id, env["d1"]["id"], BK))
        assert d1["reconciled_cents"] == 6000
        assert d1["unreconciled_cents"] == d1["distributed_cents"] - d1["reconciled_cents"]
        entries, _ = validate_paginated(api_client.list_ledger_entries(account_id, BK))
        assert all(e["reconciliation_run_id"] == run["id"] for e in entries)
