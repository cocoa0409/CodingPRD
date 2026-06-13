"""Bill use-tax computation, vendor 1099 cash/accrual variants, bill overpay, and
draft-bill void.

Translates queue-A (Difficulty) combinatorial_formula /
bill_use_tax_per_line_round_then_sum and dual_variant_calc /
vendor_1099_cash_vs_accrual; plus queue-B (Corner) calculations /
vendor_1099_cash_basis_unpaid_excluded, calculations / vendor_1099_ineligible_zero,
validations / bill_overpay_rejected, and state_machines /
void_draft_bill_then_approve_invalid_state.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_company_with_accounts, create_vendor, create_approved_bill, create_draft_bill,
    create_tax_rate_payload, record_bill_payment_payload,
    make_accountant_headers,
)

ACCT = make_accountant_headers("u_acct")


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / bill_use_tax_per_line_round_then_sum
# ---------------------------------------------------------------------------

def _approved_use_tax_bill(api):
    """ACCRUAL company, DEFAULT-jurisdiction 875 bps, three use_taxable lines of 100."""
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    accts = env["accounts"]
    validate_success(api.create_tax_rate(
        create_tax_rate_payload(co, "DEFAULT", 875), ACCT), 201)
    vendor = create_vendor(co, accts["ap"]["id"], is_1099_eligible=False)
    lines = [
        {"description": "a", "amount_cents": 100, "use_taxable": True},
        {"description": "b", "amount_cents": 100, "use_taxable": True},
        {"description": "c", "amount_cents": 100, "use_taxable": True},
    ]
    return create_approved_bill(co, vendor["id"], accts["exp"]["id"], lines)


def test_bill_use_tax_rounds_per_line_then_sums(api):
    """PRD §3.8: "the `use_tax_cents` is the sum of those per-line rounded amounts
    (rounded per line, then summed, in that pinned order); and `total_cents` is
    `subtotal_cents` plus `use_tax_cents`".

    Design: Difficulty/combinatorial_formula/bill_use_tax_per_line_round_then_sum
    """
    bill = _approved_use_tax_bill(api)
    # round_half_up(100 * 875/10000) = round_half_up(8.75) = 9 per line; 3 lines -> 27.
    assert bill["use_tax_cents"] == 27, \
        f"per-line round-then-sum must be 27 (not 26), got {bill['use_tax_cents']}"


def test_bill_subtotal_and_total(api):
    """PRD §3.8: "the `subtotal_cents` is the sum of every line's `amount_cents`".
    PRD §3.8: "the `use_tax_cents` is the sum of those per-line rounded amounts
    (rounded per line, then summed, in that pinned order); and `total_cents` is
    `subtotal_cents` plus `use_tax_cents`".

    Design: Difficulty/combinatorial_formula/bill_use_tax_per_line_round_then_sum
    """
    bill = _approved_use_tax_bill(api)
    assert bill["subtotal_cents"] == 300, f"got {bill['subtotal_cents']}"
    assert bill["total_cents"] == 327, f"got {bill['total_cents']}"
    assert bill["status"] == "APPROVED", f"got {bill['status']}"


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / vendor_1099_cash_vs_accrual
# ---------------------------------------------------------------------------

def _accrual_vendor_with_paid_and_unpaid(api):
    """ACCRUAL company; 1099 vendor; bill A 200000 (approved+paid), bill B 150000
    (approved, unpaid). Returns (co, vendor_id, bank_id)."""
    env = setup_company_with_accounts(with_bank=True)
    co = env["company"]["id"]
    accts = env["accounts"]
    bank = env["bank"]["id"]
    vendor = create_vendor(co, accts["ap"]["id"], is_1099_eligible=True,
                           display_name="Contractor Bob")
    bill_a = create_approved_bill(
        co, vendor["id"], accts["exp"]["id"],
        [{"description": "work A", "amount_cents": 200000, "use_taxable": False}],
        bill_date="2026-01-05T00:00:00.000Z")
    validate_success(api.record_bill_payment(
        bill_a["id"], record_bill_payment_payload(bank, 200000), ACCT))
    create_approved_bill(
        co, vendor["id"], accts["exp"]["id"],
        [{"description": "work B", "amount_cents": 150000, "use_taxable": False}],
        bill_date="2026-01-08T00:00:00.000Z")
    return co, vendor["id"]


def test_vendor_1099_accrual_reports_basis_and_total(api):
    """PRD §3.8: "Under the **accrual** variant (`accounting_basis` is `ACCRUAL`),
    the total is the sum of `total_cents` over the vendor's bills whose `status` is
    not `VOID` and whose `bill_date` falls in the tax year — bill totals counted by
    `bill_date` regardless of payment."

    Design: Difficulty/dual_variant_calc/vendor_1099_cash_vs_accrual
    """
    co, ven = _accrual_vendor_with_paid_and_unpaid(api)
    rep = validate_success(api.get_vendor_1099(ven, ACCT))
    assert rep["basis"] == "ACCRUAL", f"got {rep['basis']}"
    assert rep["ytd_1099_total_cents"] == 350000, \
        f"accrual counts both bills by bill_date (350000), got {rep['ytd_1099_total_cents']}"


def test_vendor_1099_accrual_total_reflected_on_vendor(api):
    """PRD §3.8: "Under the **accrual** variant (`accounting_basis` is `ACCRUAL`),
    the total is the sum of `total_cents` over the vendor's bills whose `status` is
    not `VOID` and whose `bill_date` falls in the tax year — bill totals counted by
    `bill_date` regardless of payment."

    Design: Difficulty/dual_variant_calc/vendor_1099_cash_vs_accrual
    """
    co, ven = _accrual_vendor_with_paid_and_unpaid(api)
    vendor = validate_success(api.get_vendor(ven, ACCT))
    assert vendor["ytd_1099_total_cents"] == 350000, \
        f"unpaid bill B still counts under accrual, expected 350000, got {vendor['ytd_1099_total_cents']}"


# ---------------------------------------------------------------------------
# Corner: calculations / vendor_1099_cash_basis_unpaid_excluded
# ---------------------------------------------------------------------------

def test_vendor_1099_cash_basis_excludes_unpaid(api):
    """PRD §3.8: "Under the **cash** variant (`accounting_basis` is `CASH`), the
    total is the sum of `paid_in_tax_year` over the vendor's bills — only amounts
    actually paid within the tax year count, so an approved-but-unpaid bill
    contributes nothing."

    Design: Corner/calculations/vendor_1099_cash_basis_unpaid_excluded
    """
    env = setup_company_with_accounts(accounting_basis="CASH")
    co = env["company"]["id"]
    accts = env["accounts"]
    vendor = create_vendor(co, accts["ap"]["id"], is_1099_eligible=True, display_name="Bob")
    create_approved_bill(
        co, vendor["id"], accts["exp"]["id"],
        [{"description": "w", "amount_cents": 150000, "use_taxable": False}])
    rep = validate_success(api.get_vendor_1099(vendor["id"], ACCT))
    assert rep["basis"] == "CASH", f"got {rep['basis']}"
    assert rep["ytd_1099_total_cents"] == 0, \
        f"unpaid bill should contribute 0 under cash basis, got {rep['ytd_1099_total_cents']}"


# ---------------------------------------------------------------------------
# Corner: calculations / vendor_1099_ineligible_zero
# ---------------------------------------------------------------------------

def test_vendor_1099_ineligible_is_zero(api):
    """PRD §3.8: "If the vendor's `is_1099_eligible` is false, the total is 0."

    Design: Corner/calculations/vendor_1099_ineligible_zero
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    accts = env["accounts"]
    vendor = create_vendor(co, accts["ap"]["id"], is_1099_eligible=False, display_name="Corp Inc")
    create_approved_bill(
        co, vendor["id"], accts["exp"]["id"],
        [{"description": "w", "amount_cents": 80000, "use_taxable": False}])
    rep = validate_success(api.get_vendor_1099(vendor["id"], ACCT))
    assert rep["ytd_1099_total_cents"] == 0, \
        f"ineligible vendor must report 0, got {rep['ytd_1099_total_cents']}"
    vendor_now = validate_success(api.get_vendor(vendor["id"], ACCT))
    assert vendor_now["ytd_1099_total_cents"] == 0, f"got {vendor_now['ytd_1099_total_cents']}"


# ---------------------------------------------------------------------------
# Corner: validations / bill_overpay_rejected
# ---------------------------------------------------------------------------

def test_bill_overpay_rejected(api):
    """PRD §3.8: "when it would exceed `total_cents`, the payment is rejected with
    `ERR_BILL_OVERPAY`."

    Design: Corner/validations/bill_overpay_rejected
    """
    env = setup_company_with_accounts(with_bank=True)
    co = env["company"]["id"]
    accts = env["accounts"]
    bank = env["bank"]["id"]
    vendor = create_vendor(co, accts["ap"]["id"], is_1099_eligible=False)
    bill = create_approved_bill(
        co, vendor["id"], accts["exp"]["id"],
        [{"description": "w", "amount_cents": 1000, "use_taxable": False}])
    resp = api.record_bill_payment(bill["id"], record_bill_payment_payload(bank, 1500), ACCT)
    validate_error(resp, ApiErrorId.ERR_BILL_OVERPAY.value)
    after = validate_success(api.get_bill(bill["id"], ACCT))
    assert after["status"] == "APPROVED", f"bill must stay APPROVED, got {after['status']}"


# ---------------------------------------------------------------------------
# Corner: state_machines / void_draft_bill_then_approve_invalid_state
# ---------------------------------------------------------------------------

def test_void_draft_bill_then_approve_invalid_state(api):
    """PRD §3.8: "A `DRAFT` bill may instead be voided by an `Accountant` or
    `Owner`, moving it to `VOID`; voiding is permitted only from `DRAFT`, and a void
    attempt on an `APPROVED` or paid bill is rejected as an invalid state."
    PRD §3.11: "Only once existence is established does the system check that a
    target resource is in a state from which the requested transition is defined
    (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/void_draft_bill_then_approve_invalid_state
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    accts = env["accounts"]
    vendor = create_vendor(co, accts["ap"]["id"], is_1099_eligible=False)
    bill = create_draft_bill(
        co, vendor["id"], accts["exp"]["id"],
        [{"description": "x", "amount_cents": 1000, "use_taxable": False}])
    voided = validate_success(api.void_bill(bill["id"], ACCT))
    assert voided["status"] == "VOID", f"got {voided['status']}"
    resp = api.approve_bill(bill["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
