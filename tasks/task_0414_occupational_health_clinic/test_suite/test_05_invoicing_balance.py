"""Invoicing, payments, employer outstanding balance, optimistic concurrency on issuance.
Translates difficulty queue (compensating_invariant / issue_then_full_pay_conserves_outstanding_balance)
plus corner invoice lifecycle, derived-field reconciliation, OCC, and rate-threshold instances.
"""
from test_helpers import (
    validate_error, validate_success, get_success_data,
    TEST_USERS, ApiErrorId, panel,
    setup_employer_with_active_protocol, create_worker, create_completed_physical_for_employer,
    setup_employer_with_n_completed_physicals, create_draft_invoice, issue_invoice,
    setup_issued_invoice, set_clock,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def test_encounter_void_already_billed_rejected(api):
    """PRD §3.4: "A completed encounter may be voided by a `ClinicAdmin`, but only when the
    encounter is `COMPLETED` (otherwise `ERR_ENCOUNTER_NOT_VOIDABLE`) and its `is_billed` flag is
    false (otherwise `ERR_ENCOUNTER_ALREADY_BILLED`)."

    Design: Corner/state_machines/encounter_void_already_billed_rejected
    """
    # setup_issued_invoice issues an invoice referencing the completed encounter, so its
    # is_billed flag flips to true.
    emp, wkr, enc, inv = setup_issued_invoice(price_cents=9000, current_date="2026-03-15")
    resp = api.void_encounter(enc["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ENCOUNTER_ALREADY_BILLED.value)


# ─── Compensating invariant: issue + full-pay conserves balance ─

def test_issue_then_full_pay_conserves_outstanding_balance(api):
    """PRD §3.13: "The employer's `outstanding_balance_cents` is, at all times, the sum over the
    employer's invoices in `ISSUED`, `OVERDUE`, or `PARTIALLY_PAID` status of that invoice's
    `total_cents` minus its `paid_cents`. Invoices in `DRAFT`, `VOIDED`, or `PAID` status
    contribute nothing."
    PRD §3.13: "if the new `paid_cents` equals `total_cents` the invoice becomes `PAID`".

    Design: Difficulty/compensating_invariant/issue_then_full_pay_conserves_outstanding_balance
    """
    emp, wkr, enc, inv = setup_issued_invoice(price_cents=10000, current_date="2026-03-15",
                                              net_terms_days=30)
    # Full payment moves the invoice to PAID; it then drops out of the balance.
    paid = get_success_data(api.pay_invoice(inv["id"], {"amount_cents": 10000}, ADMIN))
    assert paid["status"] == "PAID"
    assert paid["paid_cents"] == 10000
    emp_after = get_success_data(api.get_employer(emp["id"], ADMIN))
    assert emp_after["outstanding_balance_cents"] == 0


def test_issue_raises_balance_full_pay_returns_to_zero(api):
    """PRD §3.13: "This balance is recomputed on invoice issuance, on every payment, on void, and
    on the clock-driven overdue flips described in §2.7".
    PRD §3.13: "Invoices in `DRAFT`, `VOIDED`, or `PAID` status contribute nothing."

    Design: Difficulty/compensating_invariant/issue_then_full_pay_conserves_outstanding_balance
    """
    # Forward action: issuance raises outstanding to total; observe before paying.
    emp, wkr, enc, inv = setup_issued_invoice(price_cents=10000, current_date="2026-03-15",
                                              net_terms_days=30)
    emp_issued = get_success_data(api.get_employer(emp["id"], ADMIN))
    assert emp_issued["outstanding_balance_cents"] == 10000
    get_success_data(api.pay_invoice(inv["id"], {"amount_cents": 10000}, ADMIN))
    emp_after = get_success_data(api.get_employer(emp["id"], ADMIN))
    assert emp_after["outstanding_balance_cents"] == 0


# ─── Invoice lifecycle (corner) ───────────────────────

def test_invoice_issue_no_line_items_rejected(api):
    """PRD §3.13: "Issuance requires the invoice to be `DRAFT` (otherwise `ERR_INVOICE_NOT_DRAFT`)
    and requires `line_item_encounter_ids` to be non-empty (otherwise
    `ERR_INVOICE_NO_LINE_ITEMS`)."

    Design: Corner/state_machines/invoice_issue_no_line_items_rejected
    """
    emp, _ = setup_employer_with_active_protocol(
        panels=[panel("PHYSICAL", "OP", 9000, 0)], current_date="2026-03-15")
    inv = create_draft_invoice(emp["id"])  # no completed encounters -> empty line items
    emp_now = get_success_data(api.get_employer(emp["id"], ADMIN))
    resp = api.issue_invoice(inv["id"], {"expected_employer_version": emp_now["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NO_LINE_ITEMS.value)


def test_invoice_void_draft_succeeds(api):
    """PRD §3.13: "A draft invoice that is never issued may instead be voided by a `ClinicAdmin`,
    which requires it to be `DRAFT` (otherwise `ERR_INVOICE_NOT_VOIDABLE`) and sets its `status`
    to `VOIDED`."

    Design: Corner/state_machines/invoice_void_draft_succeeds
    """
    emp, wkr, encs = setup_employer_with_n_completed_physicals(1, price_cents=9000,
                                                               current_date="2026-03-15")
    inv = create_draft_invoice(emp["id"])
    out = validate_success(api.void_invoice(inv["id"], ADMIN))
    assert out["status"] == "VOIDED"


def test_invoice_void_when_not_draft_rejected(api):
    """PRD §3.13: "A draft invoice that is never issued may instead be voided by a `ClinicAdmin`,
    which requires it to be `DRAFT` (otherwise `ERR_INVOICE_NOT_VOIDABLE`)".

    Design: Corner/state_machines/invoice_void_when_not_draft_rejected
    """
    emp, wkr, enc, inv = setup_issued_invoice(price_cents=9000, current_date="2026-03-15")
    resp = api.void_invoice(inv["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_VOIDABLE.value)


def test_invoice_partial_payment_then_clock_flips_overdue(api):
    """PRD §2.7: "any invoice in `ISSUED` or `PARTIALLY_PAID` status whose `due_date` is now
    earlier than the new `current_date` flips to `OVERDUE`. A partially paid invoice that ages
    retains its accumulated `paid_cents` while moving to `OVERDUE`."
    PRD §3.13: "As described in §2.7, advancing the clock past an invoice's `due_date` flips an
    `ISSUED` or `PARTIALLY_PAID` invoice to `OVERDUE` while leaving its `paid_cents` intact and
    keeping it counted in the outstanding balance."

    Design: Corner/state_machines/invoice_partial_payment_then_clock_flips_overdue
    """
    emp, wkr, enc, inv = setup_issued_invoice(price_cents=10000, current_date="2026-03-15",
                                              net_terms_days=30)  # due 2026-04-14
    get_success_data(api.pay_invoice(inv["id"], {"amount_cents": 4000}, ADMIN))  # PARTIALLY_PAID
    set_clock(emp["id"], "2026-05-01")  # past due_date
    inv_after = get_success_data(api.get_invoice(inv["id"], ADMIN))
    assert inv_after["status"] == "OVERDUE"
    assert inv_after["paid_cents"] == 4000
    emp_after = get_success_data(api.get_employer(emp["id"], ADMIN))
    assert emp_after["outstanding_balance_cents"] == 6000


# ─── Derived field reconciliation ─────────────────────

def test_derived_is_billed_reconciles_after_issue(api):
    """PRD §3.13: "On success the invoice's `status` becomes `ISSUED` ... each line-item encounter
    has its `is_billed` flag set to true, the employer's `outstanding_balance_cents` is
    recomputed, and the employer's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/derived_is_billed_reconciles_after_issue
    """
    emp, _ = setup_employer_with_active_protocol(
        panels=[panel("PHYSICAL", "OP", 9000, 0)], current_date="2026-03-15")
    wkr = create_worker(emp["id"], job_category="OP")
    enc = create_completed_physical_for_employer(emp["id"], wkr["id"], price_cents=9000)
    assert enc["is_billed"] is False
    inv = create_draft_invoice(emp["id"])
    issue_invoice(inv["id"], emp["id"])
    enc_after = get_success_data(api.get_encounter(enc["id"], ADMIN))
    emp_after = get_success_data(api.get_employer(emp["id"], ADMIN))
    assert enc_after["is_billed"] is True
    assert emp_after["outstanding_balance_cents"] == 9000


# ─── Payment validation (corner validations) ──────────

def test_invoice_payment_exceeds_balance_rejected(api):
    """PRD §3.13: "`amount_cents` must be greater than 0 and the sum of the existing `paid_cents`
    and `amount_cents` must be at most `total_cents`, otherwise the payment is rejected with
    `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Corner/validations/invoice_payment_exceeds_balance_rejected
    """
    emp, wkr, enc, inv = setup_issued_invoice(price_cents=9000, current_date="2026-03-15")
    resp = api.pay_invoice(inv["id"], {"amount_cents": 12000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)


def test_invoice_payment_zero_amount_rejected(api):
    """PRD §3.13: "`amount_cents` must be greater than 0 and the sum of the existing `paid_cents`
    and `amount_cents` must be at most `total_cents`, otherwise the payment is rejected with
    `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Corner/validations/invoice_payment_zero_amount_rejected
    """
    emp, wkr, enc, inv = setup_issued_invoice(price_cents=9000, current_date="2026-03-15")
    resp = api.pay_invoice(inv["id"], {"amount_cents": 0}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)


# ─── Optimistic concurrency on employer (PRD §2.8) ────

def test_occ_invoice_issue_stale_version_returns_412(api):
    """PRD §2.8: "A request to issue an invoice must carry `expected_employer_version` matching
    the employer's current `version` ... a later issuance whose `expected_employer_version` is
    outdated would consume encounters that a prior issuance already billed, so it is rejected with
    `ERR_STALE_EMPLOYER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_invoice_issue_stale_version_returns_412
    """
    emp, _ = setup_employer_with_active_protocol(
        panels=[panel("PHYSICAL", "OP", 9000, 0)], current_date="2026-03-15")
    wkr = create_worker(emp["id"], job_category="OP")
    create_completed_physical_for_employer(emp["id"], wkr["id"], price_cents=9000)
    inv = create_draft_invoice(emp["id"])
    stale = get_success_data(api.get_employer(emp["id"], ADMIN))  # observe version now
    # A clock-set advances employer.version, making the observed value stale by one.
    set_clock(emp["id"], "2026-03-20")
    resp = api.issue_invoice(inv["id"], {"expected_employer_version": stale["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_EMPLOYER_VERSION.value)


def test_occ_outranks_state_stale_version_on_issued_invoice(api):
    """PRD §2.6: "the concurrency check runs after existence, authorization, and body-shape
    validation but before any state precondition or business rule."
    PRD §2.8: "a later issuance whose `expected_employer_version` is outdated would consume
    encounters that a prior issuance already billed, so it is rejected with
    `ERR_STALE_EMPLOYER_VERSION` (HTTP 412)."

    Design: Corner/validations/occ_outranks_state_stale_version_on_wrong_state_invoice
    """
    emp, _ = setup_employer_with_active_protocol(
        panels=[panel("PHYSICAL", "OP", 9000, 0)], current_date="2026-03-15")
    wkr = create_worker(emp["id"], job_category="OP")
    create_completed_physical_for_employer(emp["id"], wkr["id"], price_cents=9000)
    inv = create_draft_invoice(emp["id"])
    emp_pre_issue = get_success_data(api.get_employer(emp["id"], ADMIN))
    # First issue succeeds; it moves the invoice to ISSUED AND bumps employer.version.
    get_success_data(api.issue_invoice(
        inv["id"], {"expected_employer_version": emp_pre_issue["version"]}, ADMIN))
    # Re-issuing with the now-stale (pre-issue) version yields the OCC 412 (priority 6)
    # before the would-be state error (invoice no longer DRAFT, priority 7).
    resp = api.issue_invoice(
        inv["id"], {"expected_employer_version": emp_pre_issue["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_EMPLOYER_VERSION.value)


# ─── Rate threshold tiers (corner cross-cutting) ──────

def test_rate_threshold_tier_at_ten_line_items(api):
    """PRD §3.13: "if the count is 10 or more the rate is ten percent."
    PRD §3.13: "A volume discount keyed on the count of selected line items — not on the subtotal
    amount — is then applied."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_tier_at_ten_line_items
    """
    emp, wkr, encs = setup_employer_with_n_completed_physicals(10, price_cents=10000,
                                                               current_date="2026-03-15")
    inv = create_draft_invoice(emp["id"])
    assert inv["subtotal_cents"] == 100000
    assert inv["discount_cents"] == 10000
    assert inv["total_cents"] == 90000
