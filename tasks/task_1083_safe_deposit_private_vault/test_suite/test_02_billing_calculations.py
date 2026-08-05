"""Billing charges, late-fee escalation, refunds, valuation, and the proceeds
waterfall — combinatorial and dual-variant calculations (Difficulty queue A)
plus calculation/validation corner cases (Corner queue B).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    assert_waterfall_conserved,
)
from test_helpers import fixtures as X

ADMIN = TEST_USERS["vault_admin_headers"]
OFFICER = TEST_USERS["vault_officer_headers"]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / invoice_charge_per_component_rounding
# ---------------------------------------------------------------------------
def test_invoice_charges_rounded_per_component_then_summed(api):
    """PRD §2.7: "When an invoice's charges are assembled, the insurance rider
    and each individual precious-metal item surcharge are each rounded to whole
    cents *first*, and only then are the rounded components added together."
    PRD §3.4: "`total_cents` is the sum of `base_rent_cents`,
    `insurance_rider_cents`, `precious_metal_surcharge_cents`, and
    `late_fee_cents`."

    Design: Difficulty/combinatorial_formula/invoice_charge_per_component_rounding
    """
    ctx = X.setup_pending_rental(
        api, rental_overrides={"insurance_rider_enabled": True,
                               "declared_contents_value_cents": 100033})
    rental_id = ctx["rental"]["id"]
    X.declare_precious_metal(api, rental_id, 50017, weight_grams=50, purity=0.999)
    validate_success(api.activate_rental(rental_id, ADMIN), 200)

    inv = X.get_first_invoice(api, rental_id)
    assert inv["base_rent_cents"] == 24000
    assert inv["insurance_rider_cents"] == 1500     # round_half_up(100033 * 150 / 10000)
    assert inv["precious_metal_surcharge_cents"] == 250  # round_half_up(50017 * 50 / 10000)
    assert inv["total_cents"] == 25750


def test_invoice_surcharge_sums_each_item_rounded_first(api):
    """PRD §3.4: "`precious_metal_surcharge_cents` is the sum, over every
    non-`RELEASED` inventory item on the rental whose `category` is
    `PRECIOUS_METAL`, of that item's declared value multiplied by the
    precious-metal surcharge annual rate of 50 basis points (0.50% of
    `declared_value_cents` per year) divided by 10,000 — with each item's
    surcharge rounded half-up to whole cents *before* the items are summed."

    Design: Difficulty/combinatorial_formula/invoice_charge_per_component_rounding
    """
    ctx = X.setup_pending_rental(api)
    rental_id = ctx["rental"]["id"]
    X.declare_precious_metal(api, rental_id, 50017)   # round(250.085) = 250
    X.declare_precious_metal(api, rental_id, 70001)   # round(350.005) = 350
    validate_success(api.activate_rental(rental_id, ADMIN), 200)

    inv = X.get_first_invoice(api, rental_id)
    assert inv["base_rent_cents"] == 24000
    assert inv["insurance_rider_cents"] == 0
    assert inv["precious_metal_surcharge_cents"] == 600   # 250 + 350
    assert inv["total_cents"] == 24600


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / late_fee_tiered_size_clamp
# ---------------------------------------------------------------------------
def test_late_fee_tier2_medium_multiplier_within_clamp(api):
    """PRD §3.4: "If it is at most 30, the rate is 0.05; if it is at most 60, the
    rate is 0.10; otherwise the rate is 0.15. A size multiplier is drawn from the
    box's size class — 1.00 for `SMALL`, 1.25 for `MEDIUM`, 1.50 for `LARGE`, and
    2.00 for `JUMBO`."
    PRD §3.4: "The raw fee is the outstanding amount times the rate times the size
    multiplier; when the rate is nonzero, the late fee is that raw fee rounded
    half-up to whole cents and then clamped to lie between a minimum of 2,500
    cents and a maximum of 25,000 cents."

    Design: Difficulty/combinatorial_formula/late_fee_tiered_size_clamp
    """
    ctx = X.setup_active_rental(api)
    rental_id = ctx["rental"]["id"]
    X.set_clock(api, "2026-07-10T00:00:00Z")   # days_past_due = 40 (tier 0.10)
    validate_success(api.run_billing_cycle(ADMIN), 200)

    inv = X.get_first_invoice(api, rental_id)
    assert inv["late_fee_cents"] == 3000        # round(24000 * 0.10 * 1.25) = 3000
    rental = validate_success(api.get_rental(rental_id, ADMIN), 200)
    assert rental["status"] == "DELINQUENT"


def test_late_fee_below_minimum_is_clamped_up(api):
    """PRD §3.4: "the late fee is that raw fee rounded half-up to whole cents and
    then clamped to lie between a minimum of 2,500 cents and a maximum of 25,000
    cents."

    Design: Difficulty/combinatorial_formula/late_fee_tiered_size_clamp
    """
    ctx = X.setup_active_rental(api)
    rental_id = ctx["rental"]["id"]
    X.set_clock(api, "2026-06-05T00:00:00Z")   # days_past_due = 5 (tier 0.05)
    validate_success(api.run_billing_cycle(ADMIN), 200)

    inv = X.get_first_invoice(api, rental_id)
    # raw = 24000 * 0.05 * 1.25 = 1500 → clamped up to MIN 2500
    assert inv["late_fee_cents"] == 2500
    rental = validate_success(api.get_rental(rental_id, ADMIN), 200)
    assert rental["status"] == "PAST_DUE"


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / surrender_refund_provisional_vs_final
# ---------------------------------------------------------------------------
def _setup_surrender_ready(api):
    """MEDIUM 24000, 12mo rental ACTIVE, first invoice paid in full (balance 0),
    clock advanced to 2026-08-10 (101 days elapsed since start)."""
    ctx = X.setup_active_rental(api)
    X.pay_full_and_clear(api, ctx["rental"]["id"], 24000)
    X.set_clock(api, "2026-08-10T00:00:00Z")
    return ctx


def test_surrender_request_computes_provisional_whole_month_refund(api):
    """PRD §3.6: "The provisional refund is the greater of zero and
    (`plan_term_months` minus that whole-month count), multiplied by the monthly
    rate."

    Design: Difficulty/dual_variant_calc/surrender_refund_provisional_vs_final
    """
    ctx = _setup_surrender_ready(api)
    rental_id = ctx["rental"]["id"]
    data = validate_success(api.request_surrender(rental_id, ADMIN), 200)
    # monthly = round(24000/12) = 2000; days_elapsed 101 → months_ceil 4;
    # provisional = (12 - 4) * 2000 = 16000
    assert data["provisional_refund_cents"] == 16000
    assert data["status"] == "SURRENDER_PENDING"


def test_close_computes_final_exact_day_refund(api):
    """PRD §3.6: "the unused days are the greater of zero and (365 minus the days
    elapsed since `start_date`); the gross refund is the annual rate times those
    unused days divided by 365, rounded half-up to whole cents; and the final
    refund is the greater of zero and the gross minus any outstanding (unpaid)
    late fees on the rental."

    Design: Difficulty/dual_variant_calc/surrender_refund_provisional_vs_final
    """
    ctx = _setup_surrender_ready(api)
    rental_id = ctx["rental"]["id"]
    validate_success(api.request_surrender(rental_id, ADMIN), 200)
    data = validate_success(api.close_rental(rental_id, ADMIN), 200)
    # unused_days = 365 - 101 = 264; gross = round(24000 * 264 / 365) = 17359
    assert data["final_refund_cents"] == 17359
    assert data["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / metal_valuation_declared_vs_appraised
# ---------------------------------------------------------------------------
def test_appraisal_uses_weight_purity_spot_not_declared(api):
    """PRD §3.8: "The **appraised basis** is independent of the declared value:
    it is the item's `weight_grams` times its `purity` times the spot price per
    gram, rounded half-up to whole cents. Appraising an item (by `VaultOfficer`
    or `ComplianceOfficer`) moves a `DECLARED` item to `APPRAISED` and sets
    `appraised_value_cents`".

    Design: Difficulty/dual_variant_calc/metal_valuation_declared_vs_appraised
    """
    ctx = X.setup_active_rental(api)
    item = X.declare_precious_metal(api, ctx["rental"]["id"], 50017,
                                    weight_grams=100, purity=0.9999)
    data = validate_success(
        api.appraise_item(item["id"], {"spot_price_per_gram_cents": 7000}, OFFICER), 200)
    # appraised = round(100 * 0.9999 * 7000) = 699930; declared value unchanged
    assert data["declared_value_cents"] == 50017
    assert data["appraised_value_cents"] == 699930
    assert data["status"] == "APPRAISED"


def test_appraisal_recomputes_for_different_metal(api):
    """PRD §3.8: "The **appraised basis** is independent of the declared value:
    it is the item's `weight_grams` times its `purity` times the spot price per
    gram, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/metal_valuation_declared_vs_appraised
    """
    ctx = X.setup_active_rental(api)
    item = X.declare_precious_metal(api, ctx["rental"]["id"], 30000,
                                    weight_grams=200, purity=0.5, metal_type="SILVER")
    data = validate_success(
        api.appraise_item(item["id"], {"spot_price_per_gram_cents": 6000}, OFFICER), 200)
    # appraised = round(200 * 0.5 * 6000) = 600000
    assert data["appraised_value_cents"] == 600000
    assert data["status"] == "APPRAISED"


# ---------------------------------------------------------------------------
# Corner: calculations / proceeds_waterfall_full_buckets
# ---------------------------------------------------------------------------
def test_proceeds_waterfall_fills_buckets_in_priority_order(api):
    """PRD §3.9: "First, `proceeds_to_arrears_cents` takes the lesser of the
    remainder and the rental's arrears (its `balance_due_cents` — outstanding
    rent plus accrued late fees at completion), and the remainder is reduced
    accordingly. Next, `proceeds_to_drilling_cents` takes the lesser of the
    remainder and the order's `drilling_fee_cents`. Next, `proceeds_to_admin_cents`
    takes the lesser of the remainder and the fixed administrative fee of 5,000
    cents. Finally, `proceeds_to_escrow_cents` receives whatever remainder is
    left, held for the renter or the state."

    Design: Corner/calculations/proceeds_waterfall_full_buckets
    """
    ctx = X.setup_scheduled_drilling(api, clock_iso="2026-07-10T00:00:00Z",
                                     drilling_fee_cents=15000)
    order = validate_success(
        api.complete_drilling_order(ctx["order"]["id"], {"proceeds_cents": 50000}, ADMIN), 200)
    # arrears = 24000 + 3000 late fee = 27000
    assert order["proceeds_to_arrears_cents"] == 27000
    assert order["proceeds_to_drilling_cents"] == 15000
    assert order["proceeds_to_admin_cents"] == 5000
    assert order["proceeds_to_escrow_cents"] == 3000
    assert_waterfall_conserved(order, 50000)


# ---------------------------------------------------------------------------
# Corner: calculations / balance_due_excludes_voided_invoice
# ---------------------------------------------------------------------------
def test_voiding_only_open_invoice_zeroes_balance(api):
    """PRD §3.4: "`VOID`, `WRITTEN_OFF`, and `PAID` invoices are excluded from
    the first sum".
    PRD §3.4: "This balance is recomputed on every invoice issue, payment clear
    or reverse, and invoice void or write-off."

    Design: Corner/calculations/balance_due_excludes_voided_invoice
    """
    ctx = X.setup_active_rental(api)
    rental_id = ctx["rental"]["id"]
    inv = X.get_first_invoice(api, rental_id)
    data = validate_success(api.void_invoice(inv["id"], ADMIN), 200)
    assert data["status"] == "VOID"
    rental = validate_success(api.get_rental(rental_id, ADMIN), 200)
    assert rental["balance_due_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: validations
# ---------------------------------------------------------------------------
def test_create_payment_with_zero_amount_rejected(api):
    """PRD §3.5: "A **payment** is created (by `BillingClerk` or `Renter`)
    against a `rental_id`, with an `amount_cents` strictly greater than zero".

    Design: Corner/validations/create_payment_zero_amount_rejected
    """
    ctx = X.setup_active_rental(api)
    resp = api.create_payment(
        {"rental_id": ctx["rental"]["id"], "amount_cents": 0, "method": "CASH"},
        TEST_USERS["billing_clerk_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_void_invoice_with_applied_payment_rejected(api):
    """PRD §3.4: "an invoice with `amount_paid_cents` greater than zero cannot be
    voided and yields `ERR_INVOICE_HAS_PAYMENTS`".

    Design: Corner/validations/invoice_void_with_applied_payment_rejected
    """
    ctx = X.setup_active_rental(api)
    rental_id = ctx["rental"]["id"]
    inv = X.get_first_invoice(api, rental_id)
    # Partial payment: invoice stays OPEN but amount_paid_cents > 0, isolating the
    # payments gate from the OPEN-state gate.
    X.pay_full_and_clear(api, rental_id, 10000, invoice_id=inv["id"])
    paid = validate_success(api.get_invoice(inv["id"], ADMIN), 200)
    assert paid["status"] == "OPEN" and paid["amount_paid_cents"] == 10000
    resp = api.void_invoice(inv["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVOICE_HAS_PAYMENTS.value, 409)


def test_close_with_outstanding_balance_rejected(api):
    """PRD §3.6: "Closing a `SURRENDER_PENDING` rental (by `VaultAdmin`) requires
    two gates: the rental's `balance_due_cents` must be zero, else
    `ERR_OUTSTANDING_BALANCE`".

    Design: Corner/validations/close_with_outstanding_balance_rejected
    """
    ctx = X.setup_active_rental(api)
    rental_id = ctx["rental"]["id"]
    validate_success(api.request_surrender(rental_id, ADMIN), 200)
    resp = api.close_rental(rental_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_BALANCE.value, 409)
    rental = validate_success(api.get_rental(rental_id, ADMIN), 200)
    assert rental["status"] == "SURRENDER_PENDING"
