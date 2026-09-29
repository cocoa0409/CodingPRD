"""Depth tests for the ``dual_variant_calc`` rule.

Two calculations in this contract exist in two variants that must not be
collapsed into one another: the early-payment discount on the pay-date basis
versus the value-date basis, and supplier concentration on the face basis
versus the funded basis. Each test below drives one variant pair to completion
and asserts that the two variants genuinely disagree.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_analytics,
    assert_cash_breakdown,
    assert_invoice_face_conserved,
    assert_payment_axes,
    assert_two_decimal_percentage,
)
# The three-line row the PRD itself uses as its worked rounding example.
THREE_LINE_ROW = [
    f.invoice_line(1, 33333, 875),
    f.invoice_line(2, 33333, 875),
    f.invoice_line(3, 33334, 875),
]
FACE_108751 = 108751


def _self_only_buyer_overrides():
    return {
        "credit_limit_cents": 100_000_000,
        "self_funding_enabled": True,
        "reclass_days_threshold": 30,
        "reclass_apr_threshold_bps": 900,
    }


def _self_only_program_overrides():
    return {
        "program_type": "SUPPLIER_NAMED",
        "max_acceptable_apr_bps": 1200,
        "min_days_early": 5,
        "concentration_cap_pct": 100.00,
        "funding_policy": "SELF_ONLY",
    }


def _build_108751_reserved_payment():
    """An OPEN SELF_ONLY programme, an onboarded supplier, a LIVE session, the
    three-line 108751-cent invoice and a RESERVED payment on an ACCEPTED offer
    at 800 bps with requested_pay_date 2026-08-05."""
    ctx = fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides=_self_only_buyer_overrides(),
        program_overrides=_self_only_program_overrides(),
        session_window=("2026-08-02T00:00:00Z", "2026-08-31T00:00:00Z"),
    )
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                lines=THREE_LINE_ROW,
            )
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    fx.load_invoices(ctx)
    assert ctx.invoice["face_amount_cents"] == FACE_108751, (
        "the pinned per-line rounding order must give face 108751, got {}".format(
            ctx.invoice["face_amount_cents"]
        )
    )
    ctx.offer = fx.name_offer(
        ctx.invoice_id,
        ctx.session_id,
        ctx.supplier_id,
        ctx.invoice_version,
        offered_apr_bps=800,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-10T00:00:00Z",
    )
    ctx.offer_id = ctx.offer["id"]
    ctx.offer = fx.accept_offer_as_buyer(ctx.offer_id, ctx.buyer_id)
    ctx.payment = fx.reserve_payment(ctx.offer_id, ctx.offer["version"], ctx.buyer_id)
    ctx.payment_id = ctx.payment["id"]
    return ctx


def test_early_payment_discount_pay_date_vs_value_date_basis():
    """Execution prices the discount on the pay-date basis and settlement
    confirmation re-prices it on the value-date basis, two days shorter.

    PRD (§3.8): "On the **pay-date basis**, the basis date is the offer's
    `requested_pay_date` at reservation time and the payment's actual
    `execution_date` at execution time; this variant ignores the settlement lag,
    so the supplier is charged for the days between the payment instruction and
    maturity."
    PRD (§3.8): "As an illustration, a face of 108751 cents at 800 basis points
    with a `net_due_date` of 2026-09-30 and an `execution_date` of 2026-08-05
    gives 56 days on the pay-date basis and a discount of 1353 cents, and 54
    days on the value-date basis and a discount of 1305 cents."

    Design: Difficulty/dual_variant_calc/early_payment_discount_pay_date_vs_value_date_basis
    """
    ctx = _build_108751_reserved_payment()

    # ── variant A: pay-date basis, measured from the real execution_date ──
    fx.set_clock("2026-08-05T00:00:00Z")
    deployed = fx.execute_payment(ctx.payment_id, ctx.buyer_id)
    assert_payment_axes(deployed, funding_status="DEPLOYED", settlement_status="REMITTED")
    assert_cash_breakdown(
        deployed,
        days_early=56,
        discount_amount_cents=1353,
        funder_fee_cents=0,
        net_payment_cents=FACE_108751 - 1353,
    )
    assert deployed["execution_date"].startswith("2026-08-05"), (
        "execution_date is stamped from the logical clock, got {}".format(
            deployed["execution_date"]
        )
    )
    assert deployed["value_date"].startswith("2026-08-07"), (
        "value_date is execution_date advanced by the two-day lag, got {}".format(
            deployed["value_date"]
        )
    )
    invoice_deployed = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert invoice_deployed["provisional_discount_cents"] == 1353, (
        "provisional_discount_cents is the pay-date figure 1353, got {}".format(
            invoice_deployed["provisional_discount_cents"]
        )
    )

    # ── variant B: value-date basis, written at settlement confirmation ──
    fx.set_clock("2026-08-07T00:00:00Z")
    released = fx.confirm_settlement(ctx.payment_id, ctx.buyer_id)
    assert_payment_axes(released, funding_status="RELEASED", settlement_status="CONFIRMED")
    assert released["days_early"] == 54, (
        "the value-date basis spans exactly two fewer days, got {}".format(
            released["days_early"]
        )
    )
    assert released["discount_amount_cents"] == 1305, (
        "the value-date discount is 1305, got {}".format(
            released["discount_amount_cents"]
        )
    )
    assert released["funder_fee_cents"] == 0, "a BUYER_SELF payment carries no funder fee"
    assert released["net_payment_cents"] == FACE_108751 - 1305 == 107446, (
        "net after the value-date rewrite is 107446, got {}".format(
            released["net_payment_cents"]
        )
    )

    invoice_final = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert invoice_final["status"] == "EARLY_PAID", (
        "a confirmed settlement drives the invoice to EARLY_PAID, got {}".format(
            invoice_final["status"]
        )
    )
    assert invoice_final["final_discount_cents"] == 1305, (
        "final_discount_cents is the value-date figure 1305, got {}".format(
            invoice_final["final_discount_cents"]
        )
    )
    assert invoice_final["provisional_discount_cents"] == 1353, (
        "provisional_discount_cents keeps the pay-date figure 1353, got {}".format(
            invoice_final["provisional_discount_cents"]
        )
    )
    assert invoice_final["discount_true_up_cents"] == -48, (
        "the true-up is 1305 - 1353 = -48, got {}".format(
            invoice_final["discount_true_up_cents"]
        )
    )


def test_pay_date_basis_follows_the_real_execution_date_not_the_requested_one():
    """The pay-date variant is re-measured from the actual execution_date, and
    the value-date variant stays exactly two days shorter than it.

    PRD (§3.8): "Because the actual execution date usually differs from the
    originally requested pay date, `days_early`, `discount_amount_cents` — still
    on the pay-date basis, now measured from the real `execution_date` —
    `funder_fee_cents` and `net_payment_cents` are all recomputed, and the
    encumbrance standing on the funder or the buyer is adjusted by exactly the
    resulting net delta."
    PRD (§3.8): "On the **value-date basis**, used only at settlement
    confirmation, the basis date is the payment's `value_date`, which is the
    `execution_date` advanced by the two-day settlement lag; this variant charges
    only for the days the funds were genuinely out, and is therefore exactly two
    days shorter than the pay-date figure."

    Design: Difficulty/dual_variant_calc/early_payment_discount_pay_date_vs_value_date_basis
    """
    ctx = _build_108751_reserved_payment()

    # At reservation the pay-date basis reads the offer's requested_pay_date.
    assert ctx.payment["days_early"] == 56, (
        "reservation measures the pay-date basis from requested_pay_date "
        "2026-08-05, so 56 days, got {}".format(ctx.payment["days_early"])
    )
    assert ctx.payment["discount_amount_cents"] == 1353, (
        "the reservation-time provisional discount is 1353, got {}".format(
            ctx.payment["discount_amount_cents"]
        )
    )
    assert ctx.payment["execution_date"] is None, "an unexecuted payment has no execution_date"
    assert ctx.payment["value_date"] is None, "an unexecuted payment has no value_date"

    # Execute a week later than requested: the pay-date figure is re-measured.
    fx.set_clock("2026-08-12T00:00:00Z")
    deployed = fx.execute_payment(ctx.payment_id, ctx.buyer_id)
    assert deployed["days_early"] == 49, (
        "2026-09-30 minus the real execution date 2026-08-12 is 49 days, got {}".format(
            deployed["days_early"]
        )
    )
    assert deployed["discount_amount_cents"] == 1184, (
        "108751 * 800 * 49 / (10000 * 360) rounds half up to 1184, got {}".format(
            deployed["discount_amount_cents"]
        )
    )
    assert deployed["discount_amount_cents"] != 1353, (
        "the discount must not stay frozen at the requested-pay-date figure 1353"
    )
    assert deployed["value_date"].startswith("2026-08-14"), (
        "value_date is 2026-08-12 plus two days, got {}".format(deployed["value_date"])
    )
    assert deployed["net_payment_cents"] == FACE_108751 - 1184, (
        "net at deployment is 108751 - 1184, got {}".format(deployed["net_payment_cents"])
    )

    fx.set_clock("2026-08-14T00:00:00Z")
    released = fx.confirm_settlement(ctx.payment_id, ctx.buyer_id)
    assert released["days_early"] == 47, (
        "the value-date basis is exactly two days shorter than 49, got {}".format(
            released["days_early"]
        )
    )
    assert released["discount_amount_cents"] == 1136, (
        "108751 * 800 * 47 / (10000 * 360) rounds half up to 1136, got {}".format(
            released["discount_amount_cents"]
        )
    )
    assert released["net_payment_cents"] == FACE_108751 - 1136, (
        "net after the value-date rewrite is 108751 - 1136, got {}".format(
            released["net_payment_cents"]
        )
    )

    invoice = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert invoice["provisional_discount_cents"] == 1184, (
        "provisional_discount_cents holds the pay-date figure 1184, got {}".format(
            invoice["provisional_discount_cents"]
        )
    )
    assert invoice["final_discount_cents"] == 1136, (
        "final_discount_cents holds the value-date figure 1136, got {}".format(
            invoice["final_discount_cents"]
        )
    )
    assert invoice["discount_true_up_cents"] == 1136 - 1184 == -48, (
        "the true-up is final minus provisional, got {}".format(
            invoice["discount_true_up_cents"]
        )
    )
    assert invoice["discount_true_up_cents"] < 0, (
        "the true-up is negative whenever the APR is positive"
    )


def _build_two_supplier_program():
    """An OPEN SELF_ONLY programme carrying supplier A's 60000-cent invoice and
    supplier B's 40000-cent invoice, cap 100.00 so neither award is blocked."""
    ctx = fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides=_self_only_buyer_overrides(),
        program_overrides=_self_only_program_overrides(),
        session_window=("2026-08-02T00:00:00Z", "2026-08-31T00:00:00Z"),
    )
    ctx.supplier_b = fx.onboard_supplier(
        routing_number="011000015", account_last4="9876", identity_score=91
    )
    ctx.supplier_b_id = ctx.supplier_b["id"]
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=60_000,
            ),
            f.payable_row(
                ctx.supplier_b_id,
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=40_000,
            ),
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    invoices = fx.load_invoices(ctx)
    assert len(invoices) == 2, "the file must produce exactly two invoices"
    ctx.invoice_a, ctx.invoice_b = invoices[0], invoices[1]
    assert ctx.invoice_a["face_amount_cents"] == 60_000, (
        "supplier A's invoice is 60000 cents, got {}".format(
            ctx.invoice_a["face_amount_cents"]
        )
    )
    assert ctx.invoice_b["face_amount_cents"] == 40_000, (
        "supplier B's invoice is 40000 cents, got {}".format(
            ctx.invoice_b["face_amount_cents"]
        )
    )
    return ctx


def _award_invoice_a(ctx):
    offer = fx.name_offer(
        ctx.invoice_a["id"],
        ctx.session_id,
        ctx.supplier_id,
        ctx.invoice_a["version"],
        offered_apr_bps=1000,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-10T00:00:00Z",
    )
    accepted = fx.accept_offer_as_buyer(offer["id"], ctx.buyer_id)
    return accepted


def _analytics(ctx):
    return validate_success(
        api_client.get_program_analytics(ctx.program_id, ctx.admin)
    )


def test_supplier_concentration_face_basis_vs_funded_basis():
    """The face basis reports supplier A at 60.00 percent of programme face while
    the funded basis reports the same supplier at 100.00 percent of deployed cash.

    PRD (§3.10): "`concentration_top_supplier_face_pct` is the largest face-basis
    share held by any single supplier on the programme, computed exactly as the
    acceptance gate of §3.6 computes it but without the forward-looking addition:
    the numerator is that supplier's invoices on the programme in `AWARDED` or
    `EARLY_PAID` summed at `face_amount_cents`, and the denominator is every
    invoice on the programme in `ELIGIBLE`, `OFFERED`, `AWARDED` or `EARLY_PAID`
    summed at `face_amount_cents`."
    PRD (§3.10): "`concentration_top_supplier_funded_pct` is the largest
    funded-basis share: the numerator is the sum of `net_payment_cents` over that
    supplier's early payments on the programme whose `funding_status` is
    `DEPLOYED` or `RELEASED`, and the denominator is the sum of
    `net_payment_cents` over every early payment on the programme with those same
    funding statuses."

    Design: Difficulty/dual_variant_calc/supplier_concentration_face_basis_vs_funded_basis
    """
    ctx = _build_two_supplier_program()
    accepted = _award_invoice_a(ctx)
    payment = fx.reserve_payment(accepted["id"], accepted["version"], ctx.buyer_id)
    fx.set_clock("2026-08-05T00:00:00Z")
    fx.execute_payment(payment["id"], ctx.buyer_id)
    fx.set_clock("2026-08-07T00:00:00Z")
    released = fx.confirm_settlement(payment["id"], ctx.buyer_id)

    assert released["funding_status"] == "RELEASED", (
        "supplier A's payment must reach RELEASED, got {}".format(
            released["funding_status"]
        )
    )
    assert released["net_payment_cents"] == 59_100, (
        "60000 minus the value-date discount 900 is 59100, got {}".format(
            released["net_payment_cents"]
        )
    )
    assert released["funder_fee_cents"] == 0, "a BUYER_SELF payment carries no funder fee"

    invoice_a = fx.read_invoice(ctx.invoice_a["id"], ctx.buyer_id)
    assert invoice_a["provisional_discount_cents"] == 933, (
        "60000 * 1000 * 56 / (10000 * 360) rounds half up to 933, got {}".format(
            invoice_a["provisional_discount_cents"]
        )
    )
    assert invoice_a["final_discount_cents"] == 900, (
        "60000 * 1000 * 54 / (10000 * 360) is exactly 900, got {}".format(
            invoice_a["final_discount_cents"]
        )
    )
    assert invoice_a["discount_true_up_cents"] == -33, (
        "the true-up is 900 - 933 = -33, got {}".format(
            invoice_a["discount_true_up_cents"]
        )
    )
    invoice_b = fx.read_invoice(ctx.invoice_b["id"], ctx.buyer_id)
    assert invoice_b["status"] == "ELIGIBLE", (
        "supplier B's invoice is untouched and still ELIGIBLE, got {}".format(
            invoice_b["status"]
        )
    )

    analytics = _analytics(ctx)
    # Face basis: numerator 60000 (A, EARLY_PAID) over denominator 100000.
    assert_two_decimal_percentage(
        analytics["concentration_top_supplier_face_pct"], 60.00
    )
    # Funded basis: only A has deployed cash, so numerator equals denominator.
    assert_two_decimal_percentage(
        analytics["concentration_top_supplier_funded_pct"], 100.00
    )
    assert (
        analytics["concentration_top_supplier_face_pct"]
        != analytics["concentration_top_supplier_funded_pct"]
    ), "the two variants must disagree on this portfolio: 60.00 != 100.00"
    assert_two_decimal_percentage(analytics["concentration_cap_pct"], 100.00)


def test_concentration_funded_basis_ignores_awarded_but_unexecuted_face():
    """An award alone moves the face basis to 60.00 while the funded basis stays
    at 0.00, and a merely RESERVED payment still contributes no funded cash.

    PRD (§3.10): "The face basis measures gross commitment and counts an awarded
    invoice at full face before any cash moves; the funded basis measures net cash
    actually deployed, so discounts and funder fees shrink each supplier's
    numerator by a different proportion, and awarded-but-unexecuted invoices are
    excluded from it entirely."
    PRD (§3.10): "Both are one hundred times numerator over denominator, rounded
    half up to exactly two decimals, and both are exactly 0.00 when their
    denominator is zero."

    Design: Difficulty/dual_variant_calc/supplier_concentration_face_basis_vs_funded_basis
    """
    ctx = _build_two_supplier_program()

    # Nothing awarded yet: both bases are 0.00, the funded one on an empty
    # denominator and the face one on an empty numerator.
    before = _analytics(ctx)
    assert_analytics(
        before,
        eligible_invoice_count=2,
        adopted_invoice_count=0,
        concentration_top_supplier_face_pct=0.00,
        concentration_top_supplier_funded_pct=0.00,
    )

    accepted = _award_invoice_a(ctx)
    awarded_invoice = fx.read_invoice(ctx.invoice_a["id"], ctx.buyer_id)
    assert awarded_invoice["status"] == "AWARDED", (
        "accepting the offer must drive the invoice to AWARDED, got {}".format(
            awarded_invoice["status"]
        )
    )
    assert_invoice_face_conserved(awarded_invoice)
    assert awarded_invoice["face_covered_cents"] == 0, (
        "an award moves no cash, so face_covered_cents is still 0, got {}".format(
            awarded_invoice["face_covered_cents"]
        )
    )

    after_award = _analytics(ctx)
    assert_two_decimal_percentage(
        after_award["concentration_top_supplier_face_pct"], 60.00
    )
    assert_two_decimal_percentage(
        after_award["concentration_top_supplier_funded_pct"], 0.00
    )

    # A RESERVED payment is neither DEPLOYED nor RELEASED, so the funded basis
    # still sees no cash even though the face ledger has moved.
    payment = fx.reserve_payment(accepted["id"], accepted["version"], ctx.buyer_id)
    assert payment["funding_status"] == "RESERVED", (
        "a fresh payment opens in RESERVED, got {}".format(payment["funding_status"])
    )
    after_reserve = _analytics(ctx)
    assert_two_decimal_percentage(
        after_reserve["concentration_top_supplier_face_pct"], 60.00
    )
    assert_two_decimal_percentage(
        after_reserve["concentration_top_supplier_funded_pct"], 0.00
    )

    # Execution is what puts the payment in the DEPLOYED set the funded basis reads.
    fx.set_clock("2026-08-05T00:00:00Z")
    deployed = fx.execute_payment(payment["id"], ctx.buyer_id)
    assert deployed["funding_status"] == "DEPLOYED", (
        "execution moves the cash axis to DEPLOYED, got {}".format(
            deployed["funding_status"]
        )
    )
    assert deployed["net_payment_cents"] == 60_000 - 933, (
        "the deployed net is 60000 minus the pay-date discount 933, got {}".format(
            deployed["net_payment_cents"]
        )
    )
    after_execute = _analytics(ctx)
    assert_two_decimal_percentage(
        after_execute["concentration_top_supplier_face_pct"], 60.00
    )
    assert_two_decimal_percentage(
        after_execute["concentration_top_supplier_funded_pct"], 100.00
    )
    assert (
        after_execute["concentration_top_supplier_face_pct"]
        != after_execute["concentration_top_supplier_funded_pct"]
    ), "the same portfolio yields two different percentages, and neither is wrong"
