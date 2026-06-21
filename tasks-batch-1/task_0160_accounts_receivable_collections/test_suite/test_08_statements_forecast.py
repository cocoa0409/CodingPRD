"""Statements and cash forecasting: the pinned per-invoice finance-charge
rounding order and the EXPECTED-vs-CONSERVATIVE forecast divergence.

Queue A (Difficulty): statement finance charge rounds per invoice then sums;
cash forecast diverges by method. Queue B (Corner): conservative forecast with
an excluded PAID invoice.
"""
from test_helpers import (
    validate_success,
    set_clock,
    create_customer,
    create_invoice,
    create_payment,
    apply_payment,
    create_promise,
    create_statement_payload,
)


# --------------------------------------------------------------------------- #
# Queue A — statement finance charge, per-invoice rounding then sum
# --------------------------------------------------------------------------- #
def test_finance_charge_rounds_per_invoice_then_sums(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.8: "take its dunnable balance (`balance_cents` minus
    `disputed_amount_cents`), multiply by the monthly rate of one and one-half
    percent, and round that product half up to whole cents *for that invoice*;
    the finance charge is the integer sum of those per-invoice roundings. This
    per-invoice-then-sum order is authoritative".

    8500*0.015 = 127.5 -> 128, 17500*0.015 = 262.5 -> 263; the per-invoice order
    sums to 391 (sum-then-round would give 390).

    Design: Difficulty/combinatorial_formula/statement_finance_charge_round_per_invoice_then_sum
    """
    set_clock("2026-05-10T00:00:00Z")
    customer = create_customer(name="FC")
    create_invoice(
        customer["id"], face_amount_cents=8500,
        invoice_date="2026-02-01T00:00:00Z", due_date="2026-03-01T00:00:00Z",
    )
    create_invoice(
        customer["id"], face_amount_cents=17_500,
        invoice_date="2026-02-01T00:00:00Z", due_date="2026-03-01T00:00:00Z",
    )
    res = api.create_statement(
        customer["id"], create_statement_payload(period_end="2026-05-10T00:00:00Z"), ar_manager_headers
    )
    statement = validate_success(res, 201)
    assert statement["finance_charge_cents"] == 391, "128 + 263, not the 390 of sum-then-round"


def test_finance_charge_single_invoice_half_cent_rounds_up(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.8: "multiply by the monthly rate of one and one-half percent, and
    round that product half up to whole cents *for that invoice*".

    A single overdue invoice of dunnable 8500 yields 8500*0.015 = 127.5, which
    rounds half up to 128.

    Design: Difficulty/combinatorial_formula/statement_finance_charge_round_per_invoice_then_sum
    """
    set_clock("2026-05-10T00:00:00Z")
    customer = create_customer(name="FC1")
    create_invoice(
        customer["id"], face_amount_cents=8500,
        invoice_date="2026-02-01T00:00:00Z", due_date="2026-03-01T00:00:00Z",
    )
    res = api.create_statement(
        customer["id"], create_statement_payload(period_end="2026-05-10T00:00:00Z"), ar_manager_headers
    )
    statement = validate_success(res, 201)
    assert statement["finance_charge_cents"] == 128


# --------------------------------------------------------------------------- #
# Queue A — cash forecast EXPECTED vs CONSERVATIVE divergence
# --------------------------------------------------------------------------- #
def _setup_forecast_scenario(name):
    """Clock 2026-04-15; customer with invoice A (60000, due 2026-04-01, B1_30)
    and invoice B (40000, due 2026-03-10, B31_60); one ACTIVE promise 50000
    covering [2026-03-25, 2026-06-01) which contains A's due_date but not B's."""
    set_clock("2026-04-15T00:00:00Z")
    customer = create_customer(name=name, credit_limit_cents=1_000_000)
    create_invoice(
        customer["id"], face_amount_cents=60_000,
        invoice_date="2026-02-01T00:00:00Z", due_date="2026-04-01T00:00:00Z",
    )
    create_invoice(
        customer["id"], face_amount_cents=40_000,
        invoice_date="2026-02-01T00:00:00Z", due_date="2026-03-10T00:00:00Z",
    )
    create_promise(
        customer["id"], 50_000,
        "2026-03-25T00:00:00Z", "2026-06-01T00:00:00Z",
    )
    return customer


def test_cash_forecast_expected_uses_committed_promise_amount(api, ar_manager_headers, ar_clerk_headers, collections_agent_headers):
    """PRD §3.9: "Under `EXPECTED`, an invoice is "covered" when some `ACTIVE`
    promise's half-open window from `coverage_start` to `coverage_end` both
    contains the invoice's `due_date` and ends at or before the horizon end; a
    covered invoice contributes the smaller of that promise's
    `promised_amount_cents` and the invoice's dunnable balance, while an
    uncovered invoice contributes nothing".

    Invoice A (due 2026-04-01) is covered by the 50000 promise -> min(50000,
    60000) = 50000; invoice B (due 2026-03-10) is uncovered -> 0. Total 50000.

    Design: Difficulty/dual_variant_calc/cash_forecast_expected_vs_conservative_diverge
    """
    customer = _setup_forecast_scenario("CFexp")
    res = api.get_cash_forecast(
        ar_manager_headers,
        params={"customer_id": customer["id"], "horizon_days": 60, "method": "EXPECTED"},
    )
    forecast = validate_success(res, 200)
    assert forecast["projected_cents"] == 50_000


def test_cash_forecast_conservative_uses_aging_decay(api, ar_manager_headers, ar_clerk_headers, collections_agent_headers):
    """PRD §3.9: "Under `CONSERVATIVE`, promises are ignored and each candidate
    contributes its dunnable balance multiplied by a collection probability keyed
    to its due-date-basis aging bucket — `CURRENT` collects at full value,
    `B1_30` at ninety percent, `B31_60` at seventy percent, `B61_90` at forty
    percent, and `B91_PLUS` at ten percent."

    Invoice A 60000 * 0.90 (B1_30) = 54000; invoice B 40000 * 0.70 (B31_60) =
    28000; total 82000 — different from the EXPECTED method's 50000.

    Design: Difficulty/dual_variant_calc/cash_forecast_expected_vs_conservative_diverge
    """
    customer = _setup_forecast_scenario("CFcons")
    res = api.get_cash_forecast(
        ar_manager_headers,
        params={"customer_id": customer["id"], "horizon_days": 60, "method": "CONSERVATIVE"},
    )
    forecast = validate_success(res, 200)
    assert forecast["projected_cents"] == 82_000


# --------------------------------------------------------------------------- #
# Queue B — conservative forecast excludes a PAID invoice
# --------------------------------------------------------------------------- #
def test_cash_forecast_conservative_excludes_paid_invoice(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.9: "The candidates are the customer's invoices in `OPEN`,
    `PARTIAL`, or `DISPUTED` whose dunnable balance (`balance_cents` minus
    `disputed_amount_cents`) is positive".
    PRD §3.9: "each candidate contributes its dunnable balance multiplied by a
    collection probability... `B1_30` at ninety percent".

    Only the OPEN invoice (10000, B1_30) is a candidate; the PAID invoice is
    excluded. 10000 * 0.90 = 9000.

    Design: Corner/calculations/cash_forecast_conservative_uncovered_invoice_only
    """
    set_clock("2026-06-25T00:00:00Z")
    customer = create_customer(name="CF2")
    create_invoice(
        customer["id"], face_amount_cents=10_000,
        invoice_date="2026-05-01T00:00:00Z", due_date="2026-06-20T00:00:00Z",
    )  # OPEN, B1_30 at clock
    inv_paid = create_invoice(
        customer["id"], face_amount_cents=9000,
        invoice_date="2026-05-01T00:00:00Z", due_date="2026-06-22T00:00:00Z",
    )
    payment = create_payment(customer["id"], amount_cents=9000, received_at="2026-06-23T00:00:00Z")
    apply_payment(payment["id"], inv_paid["id"], 9000)  # settles -> PAID
    res = api.get_cash_forecast(
        ar_manager_headers,
        params={"customer_id": customer["id"], "horizon_days": 30, "method": "CONSERVATIVE"},
    )
    forecast = validate_success(res, 200)
    assert forecast["projected_cents"] == 9000
