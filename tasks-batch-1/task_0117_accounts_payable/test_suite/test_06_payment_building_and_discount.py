"""Building a payment run: add-payment guards, discount/net, batch total (PRD §3.6, §3.7).
Difficulty instances (vendor-on-hold, batch-total sum-of-rounded, exact-deadline
discount) get >=2 tests each.
"""
from test_helpers import (
    validate_success, validate_error,
    create_gl_account, create_vendor, create_approval_route,
    setup_approved_non_po_invoice, setup_scheduled_payment,
    open_batch, add_payment,
    api_client,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]
APPROVER = TEST_USERS["approver_headers"]


# ---------------------------------------------------------------------------
# Corner: validations / payment_method_mismatch_rejected
# ---------------------------------------------------------------------------
def test_payment_method_mismatch_rejected(api):
    """PRD §3.6: "the invoice's vendor must use the same disbursement rail as the batch,
    or the addition is rejected with `ERR_PAYMENT_METHOD_MISMATCH`".

    Design: Corner/validations/payment_method_mismatch_rejected
    """
    vendor, invoice = setup_approved_non_po_invoice(amount_cents=50000)  # ACH vendor
    batch = open_batch(payment_method="CHECK")
    resp = api.add_payment(batch["id"], {"invoice_id": invoice["id"]}, MGR)
    validate_error(resp, "ERR_PAYMENT_METHOD_MISMATCH", 422)


# ---------------------------------------------------------------------------
# (deleted) test_double_schedule_same_invoice_rejected — see note below.
# ---------------------------------------------------------------------------
# DELETED: ERROR PRECEDENCE SILENCE (STEP 1b). The test added an already-
# SCHEDULED invoice (non-APPROVED) to a second batch and asserted
# ERR_INVOICE_ALREADY_SCHEDULED. But PRD §2.4 mandates state-machine legality
# (ERR_INVALID_STATE) be evaluated BEFORE any Section-3 domain business rule,
# and PRD §3.6 makes APPROVED a state precondition of add-payment. Any invoice
# that "already has a live payment" is necessarily non-APPROVED, so a faithful
# PRD-only implementer returns ERR_INVALID_STATE here, never reaching the
# (priority-12) already-scheduled check. The PRD does not uniquely determine the
# asserted outcome (it contradicts it). Scaffold rule that drove generation:
# validations priority 12 / ERR_INVOICE_ALREADY_SCHEDULED.


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / payment_add_blocked_by_vendor_on_hold
# (>=2 tests on this instance.)
# ---------------------------------------------------------------------------
def test_payment_add_blocked_by_vendor_on_hold(api):
    """PRD §3.6: "a vendor that is `ON_HOLD` cannot be paid, and an attempt is rejected
    with `ERR_VENDOR_ON_HOLD`".

    Design: Difficulty/cross_entity_state_dependency/payment_add_blocked_by_vendor_on_hold
    """
    vendor, invoice = setup_approved_non_po_invoice(amount_cents=50000)
    validate_success(api.hold_vendor(vendor["id"], {"on_hold": True}, MGR), 200)
    batch = open_batch(payment_method="ACH")
    resp = api.add_payment(batch["id"], {"invoice_id": invoice["id"]}, MGR)
    validate_error(resp, "ERR_VENDOR_ON_HOLD", 409)


def test_invoice_stays_approved_when_blocked_by_vendor_on_hold(api):
    """PRD §3.6: "An invoice may only be added when it is `APPROVED` and its vendor's
    `status` is `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/payment_add_blocked_by_vendor_on_hold
    """
    vendor, invoice = setup_approved_non_po_invoice(amount_cents=50000)
    validate_success(api.hold_vendor(vendor["id"], {"on_hold": True}, MGR), 200)
    batch = open_batch(payment_method="ACH")
    validate_error(api.add_payment(batch["id"], {"invoice_id": invoice["id"]}, MGR),
                   "ERR_VENDOR_ON_HOLD", 409)
    inv_after = validate_success(api.get_invoice(invoice["id"], MGR), 200)
    assert inv_after["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / early_pay_discount_on_exact_deadline_earns_discount
# Vendor early_pay 0.02, window 10; invoice 2026-05-01 -> deadline 2026-05-11;
# run_date 2026-05-11 (== deadline) -> discount 1000 on 50000, net 49000. (>=2 tests.)
# ---------------------------------------------------------------------------
def test_discount_earned_when_run_date_equals_deadline(api):
    """PRD §3.7: "when the run date falls on or before the discount deadline — paying
    exactly on the deadline still earns the discount — the discount is the invoice's
    `total_amount_cents` multiplied by the vendor's `early_pay_terms_pct`, with that
    single product rounded half-up to the nearest cent."

    Design: Difficulty/boundary_precision_check/early_pay_discount_on_exact_deadline_earns_discount
    """
    vendor, invoice = setup_approved_non_po_invoice(
        amount_cents=50000,
        vendor_overrides={"legal_name": "Disc", "payment_method": "ACH",
                          "early_pay_terms_pct": 0.02, "early_pay_window_days": 10},
        invoice_date="2026-05-01")
    batch = open_batch(payment_method="ACH", run_date="2026-05-11")  # == discount_deadline
    resp = api.add_payment(batch["id"], {"invoice_id": invoice["id"]}, MGR)
    data = validate_success(resp, 201)
    assert data["discount_taken_cents"] == 1000, f"expected 1000, got {data['discount_taken_cents']}"
    assert data["net_amount_cents"] == 49000


def test_net_equals_gross_minus_discount_on_deadline(api):
    """PRD §3.7: "In every case the payment's `net_amount_cents` is its
    `gross_amount_cents` minus its `discount_taken_cents`; the rounding is applied to
    the discount product before the subtraction, never per line."

    Design: Difficulty/boundary_precision_check/early_pay_discount_on_exact_deadline_earns_discount
    """
    vendor, invoice = setup_approved_non_po_invoice(
        amount_cents=50000,
        vendor_overrides={"legal_name": "Disc2", "payment_method": "ACH",
                          "early_pay_terms_pct": 0.02, "early_pay_window_days": 10},
        invoice_date="2026-05-01")
    batch = open_batch(payment_method="ACH", run_date="2026-05-11")
    data = validate_success(api.add_payment(batch["id"], {"invoice_id": invoice["id"]}, MGR), 201)
    assert data["gross_amount_cents"] == 50000
    assert data["net_amount_cents"] == data["gross_amount_cents"] - data["discount_taken_cents"]


# ---------------------------------------------------------------------------
# Corner: calculations / early_pay_discount_past_window_yields_no_discount
# ---------------------------------------------------------------------------
def test_discount_zero_when_run_date_past_deadline(api):
    """PRD §3.7: "When the run date falls after the deadline, no discount applies and
    `discount_taken_cents` is 0."

    Design: Corner/calculations/early_pay_discount_past_window_yields_no_discount
    """
    vendor, invoice = setup_approved_non_po_invoice(
        amount_cents=50000,
        vendor_overrides={"legal_name": "Late", "payment_method": "ACH",
                          "early_pay_terms_pct": 0.02, "early_pay_window_days": 10},
        invoice_date="2026-05-01")
    batch = open_batch(payment_method="ACH", run_date="2026-05-12")  # past deadline 2026-05-11
    data = validate_success(api.add_payment(batch["id"], {"invoice_id": invoice["id"]}, MGR), 201)
    assert data["discount_taken_cents"] == 0
    assert data["net_amount_cents"] == 50000


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / batch_total_sum_of_rounded_not_round_of_sum_mode_b
# Two invoices each 2525, vendor 0.02 -> round(2525*0.02)=round(50.5)=51 -> net 2474.
# batch total = 2474+2474 = 4948 (sum-of-rounded). (>=2 tests.)
# ---------------------------------------------------------------------------
def _setup_two_discounted_invoices():
    create_gl_account()
    vendor = create_vendor(legal_name="Disc", payment_method="ACH",
                           early_pay_terms_pct=0.02, early_pay_window_days=30, net_terms_days=60)
    create_approval_route(min_amount_cents=0, max_amount_cents=1_000_000_000, required_levels=1)
    invs = []
    for n in ("NP-A", "NP-B"):
        from test_helpers import create_lined_invoice, code_invoice
        inv = create_lined_invoice(vendor["id"], 2525, invoice_number=n, invoice_date="2026-05-01")
        code_invoice(inv["id"])
        validate_success(api_client.submit_invoice_for_approval(inv["id"], CLERK), 200)
        step = validate_success(api_client.list_invoice_approval_steps(inv["id"], MGR), 200)[0]
        validate_success(api_client.approve_step(step["id"], APPROVER), 200)
        invs.append(inv)
    return vendor, invs


def test_each_payment_net_rounds_once_at_add_time(api):
    """PRD §3.7: "the discount is the invoice's `total_amount_cents` multiplied by the
    vendor's `early_pay_terms_pct`, with that single product rounded half-up to the
    nearest cent."

    Design: Difficulty/combinatorial_formula/batch_total_sum_of_rounded_not_round_of_sum_mode_b
    """
    vendor, invs = _setup_two_discounted_invoices()
    batch = open_batch(payment_method="ACH", run_date="2026-05-10")
    pay_a = validate_success(api.add_payment(batch["id"], {"invoice_id": invs[0]["id"]}, MGR), 201)
    pay_b = validate_success(api.add_payment(batch["id"], {"invoice_id": invs[1]["id"]}, MGR), 201)
    assert pay_a["net_amount_cents"] == 2474, f"expected 2474, got {pay_a['net_amount_cents']}"
    assert pay_b["net_amount_cents"] == 2474


def test_batch_total_is_sum_of_rounded_nets(api):
    """PRD §3.7: "A batch's `total_disbursed_cents` is the plain sum of its member
    payments' already-rounded `net_amount_cents` ... the batch total is a sum of rounded
    integers (sum-of-rounded), not a rounding of an unrounded sum."

    Design: Difficulty/combinatorial_formula/batch_total_sum_of_rounded_not_round_of_sum_mode_b
    """
    vendor, invs = _setup_two_discounted_invoices()
    batch = open_batch(payment_method="ACH", run_date="2026-05-10")
    add_payment(batch["id"], invs[0]["id"])
    add_payment(batch["id"], invs[1]["id"])
    batch_after = validate_success(api.get_payment_batch(batch["id"], MGR), 200)
    assert batch_after["total_disbursed_cents"] == 4948, (
        f"expected 4948 (sum-of-rounded), got {batch_after['total_disbursed_cents']}")
