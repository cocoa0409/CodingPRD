"""Invoice pricing: per-line surcharge/refund, package discount, deposit
deduction, contract-pricing variant, and void semantics (PRD §3.10)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_invoice,
    assert_invoice_total_invariant,
    create_invoice_for_tasks,
    credit_deposit,
    get_client,
    setup_completed_task,
    setup_completed_urgent_task,
    setup_issued_report,
    setup_n_completed_tasks_for_client,
    setup_task_with_retest_abnormal_final,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Base pricing: subtotal / surcharge / refund / package_discount
# ---------------------------------------------------------------------------
class TestBasePricing:
    def test_single_non_urgent_task_no_surcharge_no_discount(self, api):
        """PRD §3.10: 'The base_fee_cents is read from the per-method
        price table — 20000 cents for COMPRESSION_STRENGTH ... The
        surcharge_cents is the base_fee_cents multiplied by the
        urgent-handling surcharge rate of fifty percent ... if the
        task's urgent flag is true; otherwise it is zero.'

        Claim: one non-urgent COMPRESSION_STRENGTH task → subtotal=20000,
        surcharge=0, refund=0, package_discount=0, total_due=20000.
        """
        env = setup_completed_task()
        invoice = create_invoice_for_tasks(
            client_id=env["client"]["id"], task_ids=[env["task"]["id"]],
        )
        assert_invoice(invoice)
        assert invoice["subtotal_cents"] == 20000
        assert invoice["surcharge_total_cents"] == 0
        assert invoice["refund_total_cents"] == 0
        assert invoice["package_discount_cents"] == 0
        assert invoice["deposit_applied_cents"] == 0
        assert invoice["total_due_cents"] == 20000
        assert invoice["status"] == "ISSUED"
        assert_invoice_total_invariant(invoice)

    def test_single_urgent_task_adds_50pct_surcharge(self, api):
        """PRD §3.10: 'The surcharge_cents is the base_fee_cents
        multiplied by the urgent-handling surcharge rate of fifty
        percent and rounded half up to the nearest cent if the task's
        urgent flag is true.'

        Claim: urgent COMPRESSION_STRENGTH task → surcharge=10000,
        total_due=30000.
        """
        env = setup_completed_urgent_task()
        invoice = create_invoice_for_tasks(
            client_id=env["client"]["id"], task_ids=[env["task"]["id"]],
        )
        assert invoice["subtotal_cents"] == 20000
        assert invoice["surcharge_total_cents"] == 10000
        assert invoice["package_discount_cents"] == 0
        assert invoice["total_due_cents"] == 30000

    def test_outstanding_balance_updates(self, api, lab_manager_headers):
        """PRD §3.10: 'the side effects fire: the client's
        deposit_balance_cents is decreased by deposit_applied_cents,
        and the client's outstanding_balance_cents is increased by
        total_due_cents.'

        Claim: after issuing a 20000-cent invoice the client's
        outstanding_balance_cents == 20000.
        """
        env = setup_completed_task()
        invoice = create_invoice_for_tasks(
            client_id=env["client"]["id"], task_ids=[env["task"]["id"]],
        )
        client = get_client(env["client"]["id"])
        assert client["outstanding_balance_cents"] == invoice["total_due_cents"]


# ---------------------------------------------------------------------------
# Package discount gate
# ---------------------------------------------------------------------------
class TestPackageDiscount:
    def test_five_lines_triggers_package_discount(self, api):
        """PRD §3.10: 'If the number of entries in line_items is at
        least 5, or if the client's contract_id is non-null (the
        contract-pricing variant, where the line-count gate is skipped),
        the package_discount_cents is the gross-of-deposit amount
        multiplied by ten percent.'

        Difficulty-design:
        invoice_total_three_input_nonlinear_with_package_threshold.

        Claim: five urgent COMPRESSION_STRENGTH non-abnormal tasks with
        deposit_balance=20000 yields the pinned literals: subtotal
        100000, surcharge_total 50000, refund_total 0, package_discount
        15000, deposit_applied 20000, total_due 115000.
        """
        # difficulty: combinatorial_formula/invoice_total_three_input_nonlinear_with_package_threshold
        env = setup_n_completed_tasks_for_client(
            n=5, urgent=True, deposit_cents=20000,
        )
        invoice = create_invoice_for_tasks(
            client_id=env["client"]["id"],
            task_ids=[t["id"] for t in env["tasks"]],
        )
        assert invoice["subtotal_cents"] == 100000
        assert invoice["surcharge_total_cents"] == 50000
        assert invoice["refund_total_cents"] == 0
        assert invoice["package_discount_cents"] == 15000
        assert invoice["deposit_applied_cents"] == 20000
        assert invoice["total_due_cents"] == 115000
        assert_invoice_total_invariant(invoice)
        # Client side effects.
        client = get_client(env["client"]["id"])
        assert client["deposit_balance_cents"] == 0
        assert client["outstanding_balance_cents"] == 115000

    def test_four_lines_no_package_discount(self, api):
        """PRD §3.10: 'If the number of entries in line_items is at
        least 5 ... Otherwise package_discount_cents is zero.'

        Claim: four non-urgent COMPRESSION_STRENGTH tasks (below the
        5-line threshold) yields package_discount==0.
        """
        env = setup_n_completed_tasks_for_client(n=4)
        invoice = create_invoice_for_tasks(
            client_id=env["client"]["id"],
            task_ids=[t["id"] for t in env["tasks"]],
        )
        assert len(invoice["line_items"]) == 4
        assert invoice["package_discount_cents"] == 0

    def test_contract_pricing_applies_below_threshold(self, api):
        """PRD §3.10: 'or if the client's contract_id is non-null (the
        contract-pricing variant, where the line-count gate is
        skipped), the package_discount_cents is the gross-of-deposit
        amount multiplied by ten percent.'

        Difficulty-design: invoice_total_standard_vs_contract_pricing.

        Claim: a single urgent COMPRESSION_STRENGTH task on a client
        with a non-null contract_id yields:
        subtotal=20000, surcharge=10000, refund=0,
        package_discount=round_half_up((20000+10000)*0.10)=3000,
        total_due=27000.
        """
        # difficulty: dual_variant_calc/invoice_total_standard_vs_contract_pricing
        env = setup_completed_urgent_task(contract_id="MASTER-001")
        invoice = create_invoice_for_tasks(
            client_id=env["client"]["id"], task_ids=[env["task"]["id"]],
        )
        assert invoice["subtotal_cents"] == 20000
        assert invoice["surcharge_total_cents"] == 10000
        assert invoice["refund_total_cents"] == 0
        assert invoice["package_discount_cents"] == 3000
        assert invoice["total_due_cents"] == 27000

    def test_no_contract_below_threshold_no_discount(self, api):
        """PRD §3.10: 'If the number of entries in line_items is at
        least 5, or if the client's contract_id is non-null ...
        Otherwise package_discount_cents is zero.'

        Difficulty-design: invoice_total_standard_vs_contract_pricing
        (counter-branch).

        Claim: a single urgent COMPRESSION_STRENGTH task on a client
        with contract_id=null yields package_discount=0 and
        total_due=30000.
        """
        # difficulty: dual_variant_calc/invoice_total_standard_vs_contract_pricing
        env = setup_completed_urgent_task(contract_id=None)
        invoice = create_invoice_for_tasks(
            client_id=env["client"]["id"], task_ids=[env["task"]["id"]],
        )
        assert invoice["subtotal_cents"] == 20000
        assert invoice["surcharge_total_cents"] == 10000
        assert invoice["package_discount_cents"] == 0
        assert invoice["total_due_cents"] == 30000


# ---------------------------------------------------------------------------
# Per-line rounding order (cement urgency)
# ---------------------------------------------------------------------------
class TestPerLineRoundingOrder:
    def test_per_line_surcharge_is_stored_per_line(self, api):
        """PRD §3.10: 'The per-line surcharge and refund are each
        rounded individually to integer cents before any aggregation.'

        Difficulty-design: invoice_total_per_line_round_before_aggregate.

        Claim: three urgent SETTING_TIME tasks (base=15000) yield three
        line_items each with surcharge_cents==7500, subtotal=45000,
        surcharge_total=22500, refund_total=0, package_discount=0,
        total_due=67500.
        """
        # difficulty: combinatorial_formula/invoice_total_per_line_round_before_aggregate
        env = setup_n_completed_tasks_for_client(
            n=3, urgent=True, material_category="CEMENT",
            test_method="SETTING_TIME",
            # SETTING_TIME default raw_data — we let the result fall in
            # band by using a representative peak_load (the calc is not
            # part of this test's claim, only the pricing is).
        )
        invoice = create_invoice_for_tasks(
            client_id=env["client"]["id"],
            task_ids=[t["id"] for t in env["tasks"]],
        )
        assert invoice["subtotal_cents"] == 45000
        assert invoice["surcharge_total_cents"] == 22500
        assert invoice["refund_total_cents"] == 0
        assert invoice["package_discount_cents"] == 0
        assert invoice["total_due_cents"] == 67500
        assert len(invoice["line_items"]) == 3
        for line in invoice["line_items"]:
            assert line["base_fee_cents"] == 15000
            assert line["surcharge_cents"] == 7500


# ---------------------------------------------------------------------------
# Refund-on-failed-retest
# ---------------------------------------------------------------------------
# NOTE: TestRefundAfterFailedRetest was removed under STEP 1b unique-
# derivability failure (silence-pattern: cross-entity-cascade). PRD §3.10
# refund rule requires task status==COMPLETED AND the final non-superseded
# record abnormal_flag==true, but PRD §3.7 task completion fires only when
# exactly one SUBMITTED record has abnormal_flag false. Two PRD-only
# readers could legitimately ship implementations where this state is
# unreachable (Reading A) or reachable via "explicit completion" prose
# (Reading B). Source scaffold rule: invoice_total formula refund branch.


# ---------------------------------------------------------------------------
# Invoice ineligibility
# ---------------------------------------------------------------------------
class TestInvoiceIneligibleTasks:
    def test_invoice_includes_non_completed_task_rejected(self, api):
        """PRD §3.10: 'Every task in the supplied list must belong to
        the named client, must be in COMPLETED status, and must not
        have appeared in any previously-issued invoice's line_items;
        if any task fails any of these conditions the issuance is
        rejected with ERR_INVOICE_INELIGIBLE_TASKS.'

        Claim: invoicing a task that is still ASSIGNED yields
        ERR_INVOICE_INELIGIBLE_TASKS.
        """
        from test_helpers import setup_assigned_task
        env = setup_assigned_task()
        resp = api.create_invoice(
            env["client"]["id"], {"task_ids": [env["task"]["id"]]},
            TEST_USERS["lab_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_INELIGIBLE_TASKS.value)

    def test_invoice_with_already_invoiced_task_rejected(self, api):
        """PRD §3.10: 'must not have appeared in any previously-issued
        invoice's line_items; if any task fails any of these conditions
        the issuance is rejected with ERR_INVOICE_INELIGIBLE_TASKS.'

        Claim: re-invoicing a task that has already been invoiced
        yields ERR_INVOICE_INELIGIBLE_TASKS.
        """
        env = setup_completed_task()
        create_invoice_for_tasks(
            client_id=env["client"]["id"], task_ids=[env["task"]["id"]],
        )
        resp = api.create_invoice(
            env["client"]["id"], {"task_ids": [env["task"]["id"]]},
            TEST_USERS["lab_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_INELIGIBLE_TASKS.value)


# ---------------------------------------------------------------------------
# Void
# ---------------------------------------------------------------------------
class TestVoidInvoice:
    def test_void_unpaid_invoice_restores_deposit(self, api):
        """PRD §3.10: 'Voiding moves the invoice from ISSUED to VOIDED,
        restores the previously-debited deposit (the client's
        deposit_balance_cents is increased by deposit_applied_cents)
        and reduces the client's outstanding_balance_cents by
        total_due_cents.'

        Difficulty-design:
        client_deposit_conservation_under_invoice_void.

        Claim: void of an invoice with deposit_applied=30000 restores
        deposit_balance to its pre-issuance value and zeros
        outstanding_balance.
        """
        # difficulty: compensating_invariant/client_deposit_conservation_under_invoice_void
        env = setup_n_completed_tasks_for_client(
            n=5, urgent=False, deposit_cents=30000,
        )
        invoice = create_invoice_for_tasks(
            client_id=env["client"]["id"],
            task_ids=[t["id"] for t in env["tasks"]],
        )
        # subtotal=5*20000=100000, no surcharge, no refund, gross=100000,
        # package_discount=10000 (5+ lines), pre_deposit=90000,
        # deposit_applied=30000, total_due=60000
        assert invoice["package_discount_cents"] == 10000
        assert invoice["deposit_applied_cents"] == 30000
        assert invoice["total_due_cents"] == 60000

        before_client = get_client(env["client"]["id"])
        assert before_client["deposit_balance_cents"] == 0
        assert before_client["outstanding_balance_cents"] == 60000

        resp = api.void_invoice(
            invoice["id"], TEST_USERS["lab_manager_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "VOIDED"

        after_client = get_client(env["client"]["id"])
        assert after_client["deposit_balance_cents"] == 30000
        assert after_client["outstanding_balance_cents"] == 0
