"""Invoicing: provisional vs final billing, per-line proration rounding, the
occupancy-tax conditional, the 30-night tax-exemption boundary, and payment."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    checkin_retail_stay, depart_retail_stay, get_stay_invoice,
    assert_invoice, TEST_USERS,
)

PM = TEST_USERS["property_manager_headers"]

# Rate plan with zero-tax, equal rent/utility for the pure per-line rounding case.
RP2 = {"name": "RP2", "monthly_rate_cents": 100000, "utility_monthly_cents": 100000,
       "cleaning_fee_cents": 0, "occupancy_tax_rate_bps": 0}


# --- Provisional vs final billing on the same stay ---

def test_provisional_invoice_bills_planned_term(api):
    """PRD §3.4: "The provisional invoice is computed against `planned_nights` — it
    projects the full committed term before any actual departure or damages are
    known."
    PRD §3.8: "The `amount_due_cents` is the rent obligation — `rate_subtotal_cents`
    plus `cleaning_fee_cents` (the one-time cleaning fee copied from the rate plan)
    plus `occupancy_tax_cents` — and deliberately excludes the deposit."

    Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_billing
    """
    ctx = checkin_retail_stay(api, deposit_held_cents=100000)
    invoice = get_stay_invoice(api, ctx["stay"]["id"], PM)
    assert_invoice(invoice)
    assert invoice["invoice_kind"] == "PROVISIONAL"
    assert invoice["amount_due_cents"] == 642000


def test_final_invoice_after_early_departure_reprices(api):
    """PRD §3.6: "The stay's provisional invoice is finalized: its `invoice_kind`
    becomes `FINAL`, its `nights_billed` becomes `billable_nights`, its totals are
    recomputed on that actual night count, and its `status` advances `DRAFT` →
    `ISSUED`."
    PRD §3.7: "Only when `nights_billed` is fewer than 30 — for instance a 29-night
    early departure — is tax charged, computed as `rate_subtotal_cents` multiplied
    by `occupancy_tax_rate_bps`, divided by 10000, and rounded half-up to a whole
    cent."

    Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_billing
    """
    ctx = depart_retail_stay(api, actual_move_out="2026-05-30T00:00:00Z",
                             deposit_held_cents=100000)
    invoice = ctx["invoice"]
    assert invoice["invoice_kind"] == "FINAL"
    assert invoice["rate_subtotal_cents"] == 304500
    assert invoice["occupancy_tax_cents"] == 36540
    assert invoice["amount_due_cents"] == 353040


# --- Occupancy-tax conditional combination (29-night taxed) ---

def test_occupancy_tax_charged_on_short_stay(api):
    """PRD §3.7: "The taxable base is therefore `rate_subtotal_cents`."
    PRD §3.7: "Only when `nights_billed` is fewer than 30 — for instance a 29-night
    early departure — is tax charged, computed as `rate_subtotal_cents` multiplied
    by `occupancy_tax_rate_bps`, divided by 10000, and rounded half-up to a whole
    cent."

    Design: Difficulty/combinatorial_formula/occupancy_tax_conditional_combination
    """
    ctx = depart_retail_stay(api, actual_move_out="2026-05-30T00:00:00Z",
                             deposit_held_cents=0)
    invoice = ctx["invoice"]
    assert invoice["rate_subtotal_cents"] == 304500
    assert invoice["occupancy_tax_cents"] == 36540


def test_short_stay_amount_due_folds_tax_and_cleaning(api):
    """PRD §3.8: "The `amount_due_cents` is the rent obligation — `rate_subtotal_cents`
    plus `cleaning_fee_cents` (the one-time cleaning fee copied from the rate plan)
    plus `occupancy_tax_cents` — and deliberately excludes the deposit."

    Design: Difficulty/combinatorial_formula/occupancy_tax_conditional_combination
    """
    ctx = depart_retail_stay(api, actual_move_out="2026-05-30T00:00:00Z",
                             deposit_held_cents=0)
    assert ctx["invoice"]["amount_due_cents"] == 353040


# --- Per-line proration rounding order ---

def test_rate_subtotal_rounds_each_line_before_summing(api):
    """PRD §3.6: "The `rate_subtotal_cents` field is the sum of these four rounded
    line items. The order is pinned: round every line first, then add — never sum
    the exact values and round once at the end."

    Design: Difficulty/combinatorial_formula/proration_rounding_order_per_line
    """
    ctx = depart_retail_stay(api, actual_move_out="2026-06-07T00:00:00Z",
                             deposit_held_cents=0, rate_overrides=RP2)
    invoice = ctx["invoice"]
    assert invoice["rate_subtotal_cents"] == 246666


def test_partial_month_final_invoice_night_count_and_total(api):
    """PRD §3.6: "the number of full months be the integer quotient of
    `nights_billed` divided by `DAYS_PER_MONTH`, which is 30, and let the remainder
    be `nights_billed` modulo 30."
    PRD §3.8: "The `amount_due_cents` is the rent obligation — `rate_subtotal_cents`
    plus `cleaning_fee_cents` (the one-time cleaning fee copied from the rate plan)
    plus `occupancy_tax_cents` — and deliberately excludes the deposit."

    Design: Difficulty/combinatorial_formula/proration_rounding_order_per_line
    """
    ctx = depart_retail_stay(api, actual_move_out="2026-06-07T00:00:00Z",
                             deposit_held_cents=0, rate_overrides=RP2)
    invoice = ctx["invoice"]
    assert invoice["nights_billed"] == 37
    assert invoice["amount_due_cents"] == 246666


# --- 30-night tax-exemption boundary (29 taxed, 30 exempt) ---

def test_tax_charged_at_29_nights(api):
    """PRD §3.7: "when `nights_billed` is at least `TAX_EXEMPT_THRESHOLD_DAYS`,
    which is 30, the stay is tax-exempt and `occupancy_tax_cents` is forced to 0.
    Only when `nights_billed` is fewer than 30 — for instance a 29-night early
    departure — is tax charged, computed as `rate_subtotal_cents` multiplied by
    `occupancy_tax_rate_bps`, divided by 10000, and rounded half-up to a whole cent."

    Design: Difficulty/boundary_precision_check/tax_exemption_30_night_boundary
    """
    ctx = depart_retail_stay(api, actual_move_out="2026-05-30T00:00:00Z",
                             deposit_held_cents=0)
    invoice = ctx["invoice"]
    assert invoice["nights_billed"] == 29
    assert invoice["occupancy_tax_cents"] == 36540


def test_tax_exempt_at_30_nights(api):
    """PRD §3.7: "when `nights_billed` is at least `TAX_EXEMPT_THRESHOLD_DAYS`,
    which is 30, the stay is tax-exempt and `occupancy_tax_cents` is forced to 0."

    Design: Difficulty/boundary_precision_check/tax_exemption_30_night_boundary
    """
    ctx = depart_retail_stay(api, actual_move_out="2026-05-31T00:00:00Z",
                             deposit_held_cents=0)
    invoice = ctx["invoice"]
    assert invoice["nights_billed"] == 30
    assert invoice["occupancy_tax_cents"] == 0


# --- Corner: provisional invoice on check-in; paid-invoice lockdown ---

def test_provisional_invoice_uses_planned_nights(api):
    """PRD §3.4: "Its `nights_billed` equals `planned_nights` while `PROVISIONAL`
    and `billable_nights` once `FINAL`."
    PRD §3.7: "when `nights_billed` is at least `TAX_EXEMPT_THRESHOLD_DAYS`, which
    is 30, the stay is tax-exempt and `occupancy_tax_cents` is forced to 0."

    Design: Corner/calculations/provisional_invoice_uses_planned_nights
    """
    ctx = checkin_retail_stay(api, deposit_held_cents=0)
    invoice = get_stay_invoice(api, ctx["stay"]["id"], PM)
    assert invoice["invoice_kind"] == "PROVISIONAL"
    assert invoice["nights_billed"] == 60
    assert invoice["amount_due_cents"] == 642000
    assert invoice["occupancy_tax_cents"] == 0


def test_pay_already_paid_invoice_rejected(api):
    """PRD §3.8: "An issued invoice is settled by a `PropertyManager` or the owning
    `CorporateAdmin`, advancing it `ISSUED` → `PAID`. Payment is admissible only for
    an `ISSUED` invoice and is otherwise rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pay_already_paid_invoice_terminal_lockdown
    """
    ctx = depart_retail_stay(api, actual_move_out="2026-06-30T00:00:00Z",
                             deposit_held_cents=0)
    invoice_id = ctx["invoice"]["id"]
    paid = validate_success(api.pay_invoice(invoice_id, PM))
    assert paid["status"] == "PAID"
    resp = api.pay_invoice(invoice_id, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
