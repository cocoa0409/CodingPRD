"""Billing: cycle-0 invoice totals (round-per-line), recurring cycles, period
overlap, past-due parallel dimension, void rules, HSA/FSA reimbursable portion,
and proration on early exit.

Queue A: combinatorial_formula (round-per-line-then-sum),
         dual_variant_calc (provisional full vs final prorated),
         non_linear_state_machine (parallel billing dimension),
         resource_temporal_overlap (half-open billing period overlap),
         compensating_invariant (withdraw refund conserves balance).
Queue B: state_machines (cannot void initial), endpoints (bill-next-cycle),
         calculations (HSA/FSA recurring only),
         cross_cutting (void credits member balance).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    factories as f,
    fixtures,
    find_line_item,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
BILLING = TEST_USERS["billing_agent_headers"]


def test_cycle0_invoice_round_per_line_then_sum(api):
    """PRD §3.4: "a `RECURRING_FEE` line equal to the plan's `monthly_fee_cents`
    rounded to whole cents; and, only on this first invoice (cycle index 0) and
    only when the plan's enrollment fee is greater than zero, an additional
    `ENROLLMENT_FEE` line equal to the plan's `enrollment_fee_cents` rounded to
    whole cents. The `subtotal_cents` is the sum of these already-rounded line
    amounts."

    Design: Difficulty/combinatorial_formula/invoice_round_per_line_then_sum_order_pinned
    """
    ctx = fixtures.create_active_enrollment(
        plan_overrides={"tier": "MEAL", "monthly_fee_cents": 7001, "enrollment_fee_cents": 2499}
    )
    enr_id = ctx["enrollment"]["id"]
    cycle0 = fixtures.cycle0_invoice(enr_id)
    recurring = find_line_item(cycle0, "RECURRING_FEE")
    enrollment = find_line_item(cycle0, "ENROLLMENT_FEE")
    assert recurring is not None and recurring["amount_cents"] == 7001, (
        f"RECURRING_FEE line must be 7001, got {recurring}"
    )
    assert enrollment is not None and enrollment["amount_cents"] == 2499, (
        f"ENROLLMENT_FEE line must be 2499, got {enrollment}"
    )
    assert cycle0["subtotal_cents"] == 9500, (
        f"subtotal must be 9500 (7001 + 2499), got {cycle0['subtotal_cents']}"
    )


def test_provisional_full_cycle0_vs_final_prorated_on_withdraw(api):
    """PRD §3.4: "The `subtotal_cents` is the sum of these already-rounded line
    amounts."
    PRD §3.11: "The daily rate is the plan's `monthly_fee_cents` divided by
    `cycle_length_days`, rounded to whole cents using round-half-up before any
    multiplication. The proration credit is that rounded daily rate multiplied by
    the unused days, and it is added to the member's `account_balance_cents`."

    Design: Difficulty/dual_variant_calc/invoice_provisional_full_vs_final_prorated_on_invoice
    """
    ctx = fixtures.create_active_enrollment(
        plan_overrides={"monthly_fee_cents": 6000, "enrollment_fee_cents": 2500},
        enrollment_overrides={"cycle_length_days": 30},
        clock_iso="2026-01-01T00:00:00.000Z",
    )
    enr_id = ctx["enrollment"]["id"]
    member_id = ctx["member"]["id"]
    cycle0 = fixtures.cycle0_invoice(enr_id)
    assert cycle0["subtotal_cents"] == 8500, (
        f"cycle-0 provisional subtotal must be 8500, got {cycle0['subtotal_cents']}"
    )
    # Advance 10 days into the 30-day cycle, then withdraw.
    fixtures.set_clock(ctx["program"]["id"], "2026-01-11T00:00:00.000Z")
    validate_success(api.withdraw_enrollment(enr_id, ADMIN), 200)
    data, _meta = fixtures.list_invoices(enr_id)
    settlement = [inv for inv in data if inv["cycle_index"] == 1]
    assert len(settlement) == 1, f"a cycle_index 1 settlement invoice must exist, got {len(settlement)}"
    proration = find_line_item(settlement[0], "PRORATION_CREDIT")
    assert proration is not None and proration["amount_cents"] == -4000, (
        f"PRORATION_CREDIT must be -4000 (daily 200 * 20 unused days), got {proration}"
    )
    assert settlement[0]["prorated"] is True, "settlement invoice must carry prorated == true"
    member = validate_success(api.get_member(member_id, ADMIN), 200)
    assert member["account_balance_cents"] == 4000, (
        f"member balance must gain the 4000 credit, got {member['account_balance_cents']}"
    )


def test_cycle0_provisional_full_recurring_no_enrollment_fee(api):
    """PRD §3.4: "This is the provisional, full-cycle billing variant: the full
    monthly fee is charged for the entire cycle ahead, regardless of how many days
    are actually used — a forward-looking charge that the proration logic later
    reconciles if the cycle ends early."

    Design: Difficulty/dual_variant_calc/invoice_provisional_full_vs_final_prorated_on_invoice
    """
    # No enrollment fee -> provisional subtotal is exactly the full monthly fee.
    ctx = fixtures.create_active_enrollment(
        plan_overrides={"monthly_fee_cents": 6000, "enrollment_fee_cents": 0}
    )
    cycle0 = fixtures.cycle0_invoice(ctx["enrollment"]["id"])
    assert cycle0["subtotal_cents"] == 6000, (
        f"provisional cycle-0 subtotal must be the full 6000 monthly fee, got {cycle0['subtotal_cents']}"
    )
    assert cycle0["prorated"] is False, "provisional cycle-0 invoice must not be prorated"


def test_cycle0_round_per_line_omits_enrollment_fee_when_zero(api):
    """PRD §3.4: "only on this first invoice (cycle index 0) and only when the
    plan's enrollment fee is greater than zero, an additional `ENROLLMENT_FEE` line
    equal to the plan's `enrollment_fee_cents` rounded to whole cents. The
    `subtotal_cents` is the sum of these already-rounded line amounts."

    Design: Difficulty/combinatorial_formula/invoice_round_per_line_then_sum_order_pinned
    """
    ctx = fixtures.create_active_enrollment(
        plan_overrides={"tier": "MEAL", "monthly_fee_cents": 7001, "enrollment_fee_cents": 0}
    )
    cycle0 = fixtures.cycle0_invoice(ctx["enrollment"]["id"])
    recurring = find_line_item(cycle0, "RECURRING_FEE")
    enrollment = find_line_item(cycle0, "ENROLLMENT_FEE")
    assert recurring is not None and recurring["amount_cents"] == 7001, (
        f"RECURRING_FEE line must be 7001, got {recurring}"
    )
    assert enrollment is None, "no ENROLLMENT_FEE line when enrollment fee is zero"
    assert cycle0["subtotal_cents"] == 7001, (
        f"subtotal must equal the single rounded line 7001, got {cycle0['subtotal_cents']}"
    )


def test_billing_past_due_moves_independently_of_clinical(api):
    """PRD §3.5: "it advances `billing_status` from `CURRENT` to `PAST_DUE` while
    leaving `clinical_status` untouched, since the two dimensions are parallel."

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_billing_dimension_moves_independently
    """
    ctx = fixtures.create_active_enrollment(plan_overrides={"monthly_fee_cents": 6000})
    enr_id = ctx["enrollment"]["id"]
    cycle0 = fixtures.cycle0_invoice(enr_id)
    validate_success(api.mark_invoice_past_due(cycle0["id"], BILLING), 200)
    enr = validate_success(api.get_enrollment(enr_id, ADMIN), 200)
    assert enr["billing_status"] == "PAST_DUE", f"billing_status must be PAST_DUE, got {enr['billing_status']}"
    assert enr["clinical_status"] == "ACTIVE", (
        f"clinical_status must stay ACTIVE (parallel), got {enr['clinical_status']}"
    )


def test_pay_past_due_invoice_restores_billing_current(api):
    """PRD §3.5: "Paying an invoice is a `BillingAgent` action requiring the
    invoice to be in `ISSUED` status (else `ERR_INVOICE_NOT_ISSUED`); it sets the
    invoice to `PAID`, and if the enrollment's `billing_status` was `PAST_DUE`,
    paying restores it to `CURRENT`."

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_billing_dimension_moves_independently
    """
    ctx = fixtures.create_active_enrollment(plan_overrides={"monthly_fee_cents": 6000})
    enr_id = ctx["enrollment"]["id"]
    cycle0 = fixtures.cycle0_invoice(enr_id)
    validate_success(api.mark_invoice_past_due(cycle0["id"], BILLING), 200)
    assert validate_success(api.get_enrollment(enr_id, ADMIN), 200)["billing_status"] == "PAST_DUE"
    validate_success(api.pay_invoice(cycle0["id"], BILLING), 200)
    enr = validate_success(api.get_enrollment(enr_id, ADMIN), 200)
    assert enr["billing_status"] == "CURRENT", (
        f"paying a PAST_DUE invoice must restore billing_status to CURRENT, got {enr['billing_status']}"
    )
    assert enr["clinical_status"] == "ACTIVE", "clinical_status must remain ACTIVE (parallel)"


def test_billing_period_half_open_overlap_rejected(api):
    """PRD §3.5: "A new cycle's half-open period must not overlap the period of any
    existing non-void invoice for the enrollment; periods that merely touch at the
    shared boundary instant are adjacent and allowed, but any genuine overlap is
    rejected with `ERR_BILLING_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/billing_period_half_open_overlap_rejects
    """
    ctx = fixtures.create_active_enrollment(
        plan_overrides={"monthly_fee_cents": 6000},
        enrollment_overrides={"cycle_length_days": 30},
        clock_iso="2026-01-01T00:00:00.000Z",
    )
    enr_id = ctx["enrollment"]["id"]
    # Clock still inside cycle 0 [2026-01-01, 2026-01-31): a new cycle overlaps.
    resp = api.bill_next_cycle(enr_id, BILLING)
    validate_error(resp, ApiErrorId.ERR_BILLING_PERIOD_OVERLAP.value, 409)
    enr = validate_success(api.get_enrollment(enr_id, ADMIN), 200)
    assert enr["cycles_billed"] == 1, "rejected bill must not increment cycles_billed"


def test_billing_period_adjacent_at_boundary_allowed(api):
    """PRD §3.5: "periods that merely touch at the shared boundary instant are
    adjacent and allowed, but any genuine overlap is rejected with
    `ERR_BILLING_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/billing_period_half_open_overlap_rejects
    """
    ctx = fixtures.create_active_enrollment(
        plan_overrides={"monthly_fee_cents": 6000},
        enrollment_overrides={"cycle_length_days": 30},
        clock_iso="2026-01-01T00:00:00.000Z",
    )
    enr_id = ctx["enrollment"]["id"]
    # Advance the clock to exactly the cycle-0 exclusive end (2026-01-31): the new
    # period starts at the shared boundary instant -> adjacent, allowed.
    fixtures.set_clock(ctx["program"]["id"], "2026-01-31T00:00:00.000Z")
    inv = validate_success(api.bill_next_cycle(enr_id, BILLING), 201)
    assert inv["cycle_index"] == 1, f"adjacent cycle must be created (cycle_index 1), got {inv['cycle_index']}"


def test_bill_next_cycle_after_clock_advance_creates_invoice(api):
    """PRD §3.5: "A new invoice takes its `cycle_index` from the enrollment's
    current `cycles_billed` count, and generating it increments `cycles_billed` by
    one."
    PRD §3.5: "The recurring invoice's `line_items` again carry a single
    `RECURRING_FEE` line at the plan's monthly fee rounded to whole cents, with no
    enrollment-fee line because that applies only to cycle 0; the `subtotal_cents`
    is the rounded line total."

    Design: Corner/endpoints/bill_next_cycle_after_clock_advance_creates_invoice
    """
    ctx = fixtures.create_active_enrollment(
        plan_overrides={"monthly_fee_cents": 6000},
        enrollment_overrides={"cycle_length_days": 30},
        clock_iso="2026-01-01T00:00:00.000Z",
    )
    enr_id = ctx["enrollment"]["id"]
    fixtures.set_clock(ctx["program"]["id"], "2026-01-31T00:00:00.000Z")
    inv = validate_success(api.bill_next_cycle(enr_id, BILLING), 201)
    assert inv["cycle_index"] == 1, f"new invoice cycle_index must be 1, got {inv['cycle_index']}"
    assert inv["subtotal_cents"] == 6000, f"recurring subtotal must be 6000, got {inv['subtotal_cents']}"
    enr = validate_success(api.get_enrollment(enr_id, ADMIN), 200)
    assert enr["cycles_billed"] == 2, f"cycles_billed must become 2, got {enr['cycles_billed']}"


def test_cannot_void_initial_invoice(api):
    """PRD §3.5: "Voiding an invoice is also a `BillingAgent` action requiring
    `ISSUED` status (else `ERR_INVOICE_NOT_ISSUED`), and additionally requires the
    invoice's `cycle_index` to be greater than zero — the cycle-0 enrollment
    invoice is immutable and any attempt to void it is rejected with
    `ERR_CANNOT_VOID_INITIAL_INVOICE`."

    Design: Corner/state_machines/cannot_void_initial_invoice
    """
    ctx = fixtures.create_active_enrollment(plan_overrides={"monthly_fee_cents": 6000})
    enr_id = ctx["enrollment"]["id"]
    cycle0 = fixtures.cycle0_invoice(enr_id)
    resp = api.void_invoice(cycle0["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_CANNOT_VOID_INITIAL_INVOICE.value, 409)


def test_void_noninitial_invoice_credits_member_balance(api):
    """PRD §3.5: "A successful void adds the invoice's `subtotal_cents` back to the
    member's `account_balance_cents` as a reversal credit and decrements the
    enrollment's `cycles_billed` by one."

    Design: Corner/cross_cutting_complexity_layers/void_invoice_credits_member_balance_derived_reconciliation
    """
    ctx = fixtures.create_active_enrollment(
        plan_overrides={"monthly_fee_cents": 6000},
        enrollment_overrides={"cycle_length_days": 30},
        clock_iso="2026-01-01T00:00:00.000Z",
    )
    enr_id = ctx["enrollment"]["id"]
    member_id = ctx["member"]["id"]
    fixtures.set_clock(ctx["program"]["id"], "2026-01-31T00:00:00.000Z")
    inv1 = validate_success(api.bill_next_cycle(enr_id, BILLING), 201)
    validate_success(api.void_invoice(inv1["id"], BILLING), 200)
    member = validate_success(api.get_member(member_id, ADMIN), 200)
    assert member["account_balance_cents"] == 6000, (
        f"void must credit subtotal 6000 to balance, got {member['account_balance_cents']}"
    )
    enr = validate_success(api.get_enrollment(enr_id, ADMIN), 200)
    assert enr["cycles_billed"] == 1, f"void must decrement cycles_billed to 1, got {enr['cycles_billed']}"


def test_hsa_fsa_eligible_amount_recurring_only(api):
    """PRD §3.9: "the reimbursable amount is the sum of the invoice's
    `RECURRING_FEE` line amounts plus the sum of its `PRORATION_CREDIT` line
    amounts (which are negative), with the final figure floored at zero so it can
    never go negative. Enrollment-fee lines are never reimbursable and are excluded
    from this computation."

    Design: Corner/calculations/invoice_hsa_fsa_eligible_amount_recurring_only
    """
    ctx = fixtures.create_pending_enrollment(
        plan_overrides={"monthly_fee_cents": 6000, "enrollment_fee_cents": 2500},
        intake_weight_kg=95,
    )
    enr_id = ctx["enrollment"]["id"]
    fixtures.create_approved_eligibility(ctx["member"]["id"], enr_id)
    validate_success(api.activate_enrollment(enr_id, ADMIN), 200)
    cycle0 = fixtures.cycle0_invoice(enr_id)
    assert cycle0["subtotal_cents"] == 8500, f"subtotal must be 8500, got {cycle0['subtotal_cents']}"
    assert cycle0["hsa_fsa_eligible_cents"] == 6000, (
        f"reimbursable must exclude enrollment fee (6000), got {cycle0['hsa_fsa_eligible_cents']}"
    )


def test_withdraw_refund_credit_conserves_member_balance(api):
    """PRD §3.11: "The unused days are `cycle_length_days` minus the elapsed days.
    The daily rate is the plan's `monthly_fee_cents` divided by `cycle_length_days`,
    rounded to whole cents using round-half-up before any multiplication. The
    proration credit is that rounded daily rate multiplied by the unused days, and
    it is added to the member's `account_balance_cents`."

    Design: Difficulty/compensating_invariant/withdraw_refund_credit_conserves_member_balance
    """
    ctx = fixtures.create_active_enrollment(
        plan_overrides={"monthly_fee_cents": 6000, "enrollment_fee_cents": 0},
        enrollment_overrides={"cycle_length_days": 30},
        clock_iso="2026-03-01T00:00:00.000Z",
    )
    enr_id = ctx["enrollment"]["id"]
    member_id = ctx["member"]["id"]
    # Clock unchanged from activation -> elapsed 0 days -> 30 unused days.
    validate_success(api.withdraw_enrollment(enr_id, ADMIN), 200)
    member = validate_success(api.get_member(member_id, ADMIN), 200)
    assert member["account_balance_cents"] == 6000, (
        f"full-cycle refund (200 * 30) must be 6000, got {member['account_balance_cents']}"
    )
    data, _meta = fixtures.list_invoices(enr_id)
    settlement = [inv for inv in data if inv["cycle_index"] == 1]
    assert len(settlement) == 1, "a settlement invoice must be issued"
    proration = find_line_item(settlement[0], "PRORATION_CREDIT")
    assert proration is not None and proration["amount_cents"] == -6000, (
        f"PRORATION_CREDIT must be -6000, got {proration}"
    )


def test_withdraw_pending_clinical_leaves_balance_unchanged(api):
    """PRD §3.11: "Because no invoice was ever issued for such an enrollment (its
    `cycles_billed` is zero), there is no proration, no refund, and no change to
    `account_balance_cents` — it simply moves `clinical_status` to `WITHDRAWN`,
    sets the member's `status` to `WITHDRAWN`, and moves `billing_status` to
    `CLOSED`."

    Design: Difficulty/compensating_invariant/withdraw_refund_credit_conserves_member_balance
    """
    ctx = fixtures.create_pending_enrollment(
        plan_overrides={"monthly_fee_cents": 6000, "enrollment_fee_cents": 0}
    )
    enr_id = ctx["enrollment"]["id"]
    member_id = ctx["member"]["id"]
    withdrawn = validate_success(api.withdraw_enrollment(enr_id, ADMIN), 200)
    assert withdrawn["clinical_status"] == "WITHDRAWN"
    assert withdrawn["billing_status"] == "CLOSED"
    member = validate_success(api.get_member(member_id, ADMIN), 200)
    assert member["account_balance_cents"] == 0, (
        f"PENDING_CLINICAL withdraw must not change balance, got {member['account_balance_cents']}"
    )
