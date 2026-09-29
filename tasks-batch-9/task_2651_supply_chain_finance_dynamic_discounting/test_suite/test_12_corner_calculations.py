"""Corner tests for the calculation surfaces of the dynamic-discounting API.

Every money figure asserted below is recomputed from the PRD formula in a
comment beside the literal, and every "wrong but superficially reasonable"
alternative the design highlights is asserted against explicitly.

The harness restarts the API server before each test, so every test builds all
of its own state through the public API starting from an empty database.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_SELF_FUNDING_DISABLED
from test_helpers.assertions import (
    assert_cash_breakdown,
    assert_funder_capital_conserved,
    assert_invoice,
    assert_offer,
    assert_payment,
    assert_payment_axes,
    assert_program,
    assert_two_decimal_percentage,
)
from test_helpers.test_users import (
    make_buyer_admin_headers,
    make_buyer_treasury_headers,
)


# ─────────────────────────────────────────────────────────────────────────────
# calculations / weighted_avg_accepted_apr
# ─────────────────────────────────────────────────────────────────────────────
def test_weighted_avg_accepted_apr_is_face_weighted_not_a_plain_mean():
    """Two settled invoices of unequal face must produce the face-weighted mean.

    INV-A (face 100000 at 1000 bps) and INV-B (face 300000 at 600 bps) give
    (1000*100000 + 600*300000) / (100000 + 300000) = 280000000 / 400000 = 700
    basis points. The arithmetic mean of the two rates, 800, is wrong, and the
    difference is visible a second time in the THROTTLED ceiling that follows:
    trunc(700 * 75 / 100) = 525, not trunc(800 * 75 / 100) = 600.

    PRD §3.10: "Take every invoice on the programme whose `status` is
    `EARLY_PAID`, multiply each one's `accepted_apr_bps` by its
    `face_amount_cents`, sum those products, divide by the sum of those same
    faces, and round the quotient half up to a whole basis point."
    PRD §3.10: "Under `THROTTLED`, the candidate is the same computation at 75
    percent instead of 90, likewise floored at 200 basis points."

    Design: Corner/calculations/weighted_avg_accepted_apr_is_face_weighted_not_a_plain_mean
    """
    ctx = fx.build_base(
        buyer_overrides={
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
            "reclass_days_threshold": 30,
            "reclass_apr_threshold_bps": 900,
        },
        program_overrides={
            "max_acceptable_apr_bps": 1200,
            "min_days_early": 5,
            "concentration_cap_pct": 100.00,
            "funding_policy": "SELF_ONLY",
        },
    )
    admin = make_buyer_admin_headers(ctx.buyer_id)
    treasury = make_buyer_treasury_headers(ctx.buyer_id)

    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                invoice_number="INV-A",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=100_000,
            ),
            f.payable_row(
                ctx.supplier_id,
                invoice_number="INV-B",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=300_000,
            ),
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    invoices = fx.load_invoices(ctx)
    assert len(invoices) == 2, "the file must have produced two invoices"
    invoice_a, invoice_b = invoices[0], invoices[1]
    assert invoice_a["face_amount_cents"] == 100_000
    assert invoice_b["face_amount_cents"] == 300_000

    # ── INV-A: 1000 bps, requested_pay_date 2026-08-05 ────────────────────
    # pay-date days early = 2026-09-30 - 2026-08-05 = 56 days
    # discount = 100000 * 1000 * 56 / (10000 * 360) = 1555.55… -> 1556
    offer_a = fx.name_offer(
        invoice_a["id"],
        ctx.session_id,
        ctx.supplier_id,
        invoice_a["version"],
        offered_apr_bps=1000,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    offer_a = fx.accept_offer_as_buyer(offer_a["id"], ctx.buyer_id)
    payment_a = fx.reserve_payment(offer_a["id"], offer_a["version"], ctx.buyer_id)
    assert payment_a["days_early"] == 56
    assert payment_a["discount_amount_cents"] == 1556 == f.expected_discount_cents(
        100_000, 1000, 56
    )
    fx.set_clock("2026-08-05T00:00:00Z")
    fx.execute_payment(payment_a["id"], ctx.buyer_id)
    fx.set_clock("2026-08-07T00:00:00Z")
    fx.confirm_settlement(payment_a["id"], ctx.buyer_id)

    # ── before the trigger: one EARLY_PAID invoice, so the mean is 1000 ───
    program_mid = get_success_data(api_client.get_program(ctx.program_id, admin))
    # value-date days = 2026-09-30 - 2026-08-07 = 54; discount 1500
    assert_program(
        program_mid,
        eligible_invoice_count=2,
        adopted_invoice_count=1,
        weighted_avg_accepted_apr_bps=1000,
        rate_posture="OPTIMISED",
        # OPTIMISED candidate = trunc(1000 * 90 / 100) = 900; min(1200, 900) = 900
        max_acceptable_apr_bps=900,
    )
    assert_two_decimal_percentage(program_mid["adoption_rate_pct"], 50.00)

    # ── INV-B: 600 bps, requested_pay_date 2026-08-10 ─────────────────────
    invoice_b = fx.read_invoice(invoice_b["id"], ctx.buyer_id)
    offer_b = fx.name_offer(
        invoice_b["id"],
        ctx.session_id,
        ctx.supplier_id,
        invoice_b["version"],
        offered_apr_bps=600,
        requested_pay_date="2026-08-10T00:00:00Z",
        acceptance_deadline="2026-08-25T00:00:00Z",
    )
    offer_b = fx.accept_offer_as_buyer(offer_b["id"], ctx.buyer_id)
    payment_b = fx.reserve_payment(offer_b["id"], offer_b["version"], ctx.buyer_id)
    # pay-date days early = 2026-09-30 - 2026-08-10 = 51
    # discount = 300000 * 600 * 51 / (10000 * 360) = 2550 exactly
    assert payment_b["days_early"] == 51
    assert payment_b["discount_amount_cents"] == 2550
    fx.set_clock("2026-08-10T00:00:00Z")
    fx.execute_payment(payment_b["id"], ctx.buyer_id)
    fx.set_clock("2026-08-12T00:00:00Z")

    # ── trigger: confirm the second settlement ────────────────────────────
    resp = api_client.confirm_settlement(payment_b["id"], treasury)
    payment_b = validate_success(resp, 200)

    # value-date days early = 2026-09-30 - 2026-08-12 = 49
    # discount = 300000 * 600 * 49 / (10000 * 360) = 2450 exactly
    assert_payment_axes(
        payment_b, funding_status="RELEASED", settlement_status="CONFIRMED"
    )
    assert_cash_breakdown(
        payment_b,
        days_early=49,
        discount_amount_cents=2450,
        funder_fee_cents=0,
        net_payment_cents=297_550,  # 300000 - 2450 - 0
    )
    assert payment_b["discount_amount_cents"] == f.expected_discount_cents(
        300_000, 600, 49
    )

    invoice_b = fx.read_invoice(invoice_b["id"], ctx.buyer_id)
    assert_invoice(
        invoice_b,
        status="EARLY_PAID",
        final_discount_cents=2450,
        provisional_discount_cents=2550,
        discount_true_up_cents=-100,  # 2450 - 2550
    )

    program = get_success_data(api_client.get_program(ctx.program_id, admin))
    assert_program(
        program,
        eligible_invoice_count=2,
        adopted_invoice_count=2,
        rate_posture="THROTTLED",
        weighted_avg_accepted_apr_bps=700,
        max_acceptable_apr_bps=525,
    )
    assert_two_decimal_percentage(program["adoption_rate_pct"], 100.00)
    assert program["weighted_avg_accepted_apr_bps"] != 800, (
        "800 is the arithmetic mean of 1000 and 600; the contract weights by face"
    )
    assert program["max_acceptable_apr_bps"] != 600, (
        "600 would follow from the arithmetic-mean 800; the face-weighted 700 "
        "yields trunc(700 * 75 / 100) = 525"
    )

    buyer = get_success_data(api_client.get_buyer(ctx.buyer_id, admin))
    assert buyer["credit_used_cents"] == 0, (
        "both payments are RELEASED, so no self-funding credit stays used"
    )


# ─────────────────────────────────────────────────────────────────────────────
# calculations / session_clearing_apr
# ─────────────────────────────────────────────────────────────────────────────
def test_session_clearing_apr_counts_only_accepted_offers():
    """Only offers that are exactly ACCEPTED at the instant of close are priced in.

    The session holds one ACCEPTED offer (invoice face 200000 at 900 bps) and
    one still-NAMED offer (invoice face 100000 at 1200 bps) when it settles, so
    clearing_apr_bps = 900 * 200000 / 200000 = 900. Including the unaccepted
    offer would give (900*200000 + 1200*100000) / 300000 = 1000, and the NAMED
    offer is expired by the same edge rather than being priced into it.

    PRD §3.5: "`clearing_apr_bps` is the face-weighted mean accepted APR of the
    window: take every offer on the session whose `status` is exactly
    `ACCEPTED` at the instant of close, multiply each one's locked APR by the
    `face_amount_cents` of the invoice it prices, sum those products, divide by
    the sum of those same invoice faces, and round the quotient half up to a
    whole basis point."
    PRD §3.5: "Offers in `EXPIRED`, `SUPERSEDED` or `VOIDED_BY_SUPPRESSION` are
    excluded."

    Design: Corner/calculations/session_clearing_apr_counts_only_accepted_offers
    """
    ctx = fx.build_base(
        buyer_overrides={
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
        },
        program_overrides={
            "program_type": "SUPPLIER_NAMED",
            "max_acceptable_apr_bps": 1200,
            "min_days_early": 5,
            "concentration_cap_pct": 100.00,
            "funding_policy": "SELF_ONLY",
        },
    )
    admin = make_buyer_admin_headers(ctx.buyer_id)

    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                invoice_number="CLR-1",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=200_000,
            ),
            f.payable_row(
                ctx.supplier_id,
                invoice_number="CLR-2",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=100_000,
            ),
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    invoices = fx.load_invoices(ctx)
    invoice_big, invoice_small = invoices[0], invoices[1]
    assert invoice_big["face_amount_cents"] == 200_000
    assert invoice_small["face_amount_cents"] == 100_000

    offer_big = fx.name_offer(
        invoice_big["id"],
        ctx.session_id,
        ctx.supplier_id,
        invoice_big["version"],
        offered_apr_bps=900,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    offer_small = fx.name_offer(
        invoice_small["id"],
        ctx.session_id,
        ctx.supplier_id,
        invoice_small["version"],
        offered_apr_bps=1200,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    offer_big = fx.accept_offer_as_buyer(offer_big["id"], ctx.buyer_id)
    assert_offer(offer_big, status="ACCEPTED", accepted_apr_bps=900)

    # ── trigger: settle the window early ──────────────────────────────────
    resp = api_client.close_session(
        ctx.session_id, f.session_close_payload("SETTLE"), admin
    )
    session = validate_success(resp, 200)

    assert session["status"] == "CLOSED"
    assert session["clearing_apr_bps"] == 900, (
        "only the ACCEPTED offer is weighted: 900 * 200000 / 200000 = 900"
    )
    assert session["clearing_apr_bps"] != 1000, (
        "1000 would come from also weighting the NAMED 1200-bp offer: "
        "(900*200000 + 1200*100000) / 300000"
    )

    reread_big = fx.read_offer(offer_big["id"], ctx.buyer_id)
    assert_offer(reread_big, status="ACCEPTED", accepted_apr_bps=900)
    reread_small = fx.read_offer(offer_small["id"], ctx.buyer_id)
    assert_offer(reread_small, status="EXPIRED")

    assert_invoice(fx.read_invoice(invoice_big["id"], ctx.buyer_id), status="AWARDED")
    assert_invoice(fx.read_invoice(invoice_small["id"], ctx.buyer_id), status="OFFERED")


# ─────────────────────────────────────────────────────────────────────────────
# calculations / funder_selection
# ─────────────────────────────────────────────────────────────────────────────
def test_funder_selection_tie_break_prefers_the_lower_fee_spread():
    """Equal scores are broken by the lower fee spread, not by the earlier created_at.

    accepted_apr_bps 900, invoice face 1000000, requested_pay_date 2026-08-05,
    net_due_date 2026-09-04 -> 30 days early, discount 7500, pre-fee net 992500.
      ALPHA (registered first, min_apr 500, spread 40):
        2 * min(400, 900 - 500) = 800, minus 3 * 40 = 120, plus the 150 depth
        bonus (60000000 free >= 2 * 992500) -> 830
      BRAVO (registered second, min_apr 560, spread 0):
        2 * min(400, 900 - 560) = 680, minus 3 * 0 = 0, plus 150 -> 830
    The 400-bp cap is what makes the two scores equal, so tie-break rung 2 (the
    lower fee_spread_bps) decides and BRAVO wins; rung 3 (created_at ascending)
    would have wrongly picked ALPHA.

    PRD §3.7: "Stage three ranks the survivors and picks the first: the highest
    score wins; ties are broken by the lower `fee_spread_bps`; remaining ties
    are broken by the earlier `created_at`, ascending — never by `id`."
    PRD §3.7: "The first term rewards rate headroom: take the payment's
    `accepted_apr_bps` minus that funder's `min_apr_bps`, cap the result at 400
    basis points by taking the smaller of the two, and double it."

    Design: Corner/calculations/funder_selection_tie_break_prefers_the_lower_fee_spread
    """
    ctx = fx.build_accepted_offer(
        face_cents=1_000_000,
        approval_date="2026-07-20T00:00:00Z",
        net_due_date="2026-09-04T00:00:00Z",
        offered_apr_bps=900,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
        buyer_overrides={
            # A deliberately tiny limit with self-funding off: the buyer-self
            # branch of the waterfall is never a candidate under FUNDER_ONLY.
            "credit_limit_cents": 1000,
            "self_funding_enabled": False,
        },
        program_overrides={
            "max_acceptable_apr_bps": 1200,
            "min_days_early": 5,
            "concentration_cap_pct": 100.00,
            "funding_policy": "FUNDER_ONLY",
        },
        funders=[
            {
                "legal_name": "Alpha Funding Partners",
                "capital_limit_cents": 60_000_000,
                "min_apr_bps": 500,
                "fee_spread_bps": 40,
                "max_single_invoice_cents": 5_000_000,
                "committed_amount_cents": 60_000_000,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-09-30T00:00:00Z",
            },
            {
                "legal_name": "Bravo Funding Partners",
                "capital_limit_cents": 60_000_000,
                "min_apr_bps": 560,
                "fee_spread_bps": 0,
                "max_single_invoice_cents": 5_000_000,
                "committed_amount_cents": 60_000_000,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-09-30T00:00:00Z",
            },
        ],
    )
    alpha, bravo = ctx.funders[0], ctx.funders[1]
    treasury = make_buyer_treasury_headers(ctx.buyer_id)
    admin = make_buyer_admin_headers(ctx.buyer_id)

    # ── trigger: reserve, forcing the funder selector to run ──────────────
    resp = api_client.create_early_payment(
        f.early_payment_payload(ctx.offer_id, ctx.offer_version), treasury
    )
    payment = validate_success(resp, 201)

    assert_payment(payment, funding_source="FUNDER", funder_id=bravo["id"])
    assert payment["funder_id"] != alpha["id"], (
        "ALPHA has the earlier created_at but the wider 40-bp spread; rung 2 "
        "settles the 830-830 tie before rung 3 is consulted"
    )
    # discount = 1000000 * 900 * 30 / (10000 * 360) = 7500 exactly
    # pre-fee net = 1000000 - 7500 = 992500, below 5000000 -> tier 45 bps
    # fee = 992500 * (45 + 0) / 10000 = 4466.25 -> 4466
    assert_cash_breakdown(
        payment,
        days_early=30,
        discount_amount_cents=7500,
        funder_fee_cents=4466,
        net_payment_cents=988_034,  # 1000000 - 7500 - 4466
    )
    assert payment["discount_amount_cents"] == f.expected_discount_cents(
        1_000_000, 900, 30
    )
    assert payment["funder_fee_cents"] == f.expected_funder_fee_cents(992_500, 0)
    assert payment["net_payment_cents"] != 984_064, (
        "984064 is the net had ALPHA won: fee 992500 * (45 + 40) / 10000 = 8436"
    )

    bravo_row = fx.read_funder(bravo["id"])
    assert bravo_row["encumbered_capital_cents"] == 988_034
    assert bravo_row["available_capital_cents"] == 59_011_966  # 60000000 - 988034
    assert_funder_capital_conserved(bravo_row, 60_000_000)

    alpha_row = fx.read_funder(alpha["id"])
    assert alpha_row["encumbered_capital_cents"] == 0
    assert alpha_row["available_capital_cents"] == 60_000_000
    assert_funder_capital_conserved(alpha_row, 60_000_000)

    buyer = get_success_data(api_client.get_buyer(ctx.buyer_id, admin))
    assert buyer["credit_used_cents"] == 0, (
        "the 1000-cent credit limit is never consulted on the funder branch"
    )


# ─────────────────────────────────────────────────────────────────────────────
# calculations / funding_source_resolution
# ─────────────────────────────────────────────────────────────────────────────
def test_waterfall_prefers_buyer_self_while_an_eligible_funder_stands_by():
    """Under SELF_THEN_FUNDER the first bucket fills before the second is consulted.

    face 100000 at 800 bps, requested_pay_date 2026-08-05, net_due_date
    2026-09-30 -> 56 days early and a discount of
    100000 * 800 * 56 / (10000 * 360) = 1244.44… -> 1244, so the pre-fee net is
    98756 and the buyer's 100000000-cent headroom covers it. A fully eligible
    funder (min_apr 500 below the 800-bp rate, a 60000000-cent tranche covering
    the projected value date, a 5000000-cent single-invoice ceiling) must
    therefore end the call with zero encumbrance. The funder fee is 0 on the
    self branch and the accounting default short-circuits to TRADE_PAYABLE even
    though 56 days early is well past the buyer's 30-day reclass threshold.

    PRD §3.7: "The candidates are tried strictly left to right, and the first
    one that can pay wins."
    PRD §3.7: "Buyer self-funding can pay when the buyer's
    `self_funding_enabled` is true and the buyer's `credit_used_cents` plus the
    pre-fee net of this payment is at most the buyer's `credit_limit_cents`;
    exact equality is acceptable."
    PRD §3.8: "A payment whose `funding_source` is `BUYER_SELF` has a
    `funder_fee_cents` of 0, always."
    PRD §3.9: "A payment funded from the buyer's own balance sheet —
    `funding_source` `BUYER_SELF` — always defaults to `TRADE_PAYABLE`, because
    no third party has interposed itself."

    Design: Corner/calculations/waterfall_prefers_buyer_self_while_an_eligible_funder_stands_by
    """
    ctx = fx.build_accepted_offer(
        face_cents=100_000,
        approval_date="2026-07-20T00:00:00Z",
        net_due_date="2026-09-30T00:00:00Z",
        offered_apr_bps=800,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
        buyer_overrides={
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
            "reclass_days_threshold": 30,
            "reclass_apr_threshold_bps": 900,
        },
        program_overrides={
            "max_acceptable_apr_bps": 1200,
            "min_days_early": 5,
            "concentration_cap_pct": 100.00,
            "funding_policy": "SELF_THEN_FUNDER",
        },
        funders=[
            {
                "legal_name": "Standby Capital",
                "capital_limit_cents": 60_000_000,
                "min_apr_bps": 500,
                "fee_spread_bps": 25,
                "max_single_invoice_cents": 5_000_000,
                "committed_amount_cents": 60_000_000,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-09-30T00:00:00Z",
            }
        ],
    )
    standby = ctx.funders[0]
    treasury = make_buyer_treasury_headers(ctx.buyer_id)
    admin = make_buyer_admin_headers(ctx.buyer_id)

    # ── trigger: reserve under SELF_THEN_FUNDER ───────────────────────────
    resp = api_client.create_early_payment(
        f.early_payment_payload(ctx.offer_id, ctx.offer_version), treasury
    )
    payment = validate_success(resp, 201)

    assert_payment(payment, funding_source="BUYER_SELF", funder_id=None)
    assert_payment_axes(
        payment,
        funding_status="RESERVED",
        settlement_status="UNSENT",
        accounting_status="UNCLASSIFIED",
    )
    # discount = 100000 * 800 * 56 / (10000 * 360) = 1244.44… -> 1244
    assert_cash_breakdown(
        payment,
        days_early=56,
        discount_amount_cents=1244,
        funder_fee_cents=0,
        net_payment_cents=98_756,  # 100000 - 1244 - 0
    )
    assert payment["discount_amount_cents"] == f.expected_discount_cents(
        100_000, 800, 56
    )
    assert payment["default_accounting_status"] == "TRADE_PAYABLE", (
        "the BUYER_SELF branch short-circuits; the 56 > 30 days comparison that "
        "would give DEBT_RECLASSIFIED is never evaluated"
    )
    assert payment["funder_fee_cents"] != f.expected_funder_fee_cents(98_756, 25), (
        "no funder fee at all is charged on the self branch"
    )

    buyer = get_success_data(api_client.get_buyer(ctx.buyer_id, admin))
    assert buyer["credit_used_cents"] == 98_756, (
        "the buyer's own balance sheet carries the pre-fee net"
    )

    funder_row = fx.read_funder(standby["id"])
    assert funder_row["encumbered_capital_cents"] == 0, (
        "the standby funder was never consulted, so nothing is encumbered"
    )
    assert funder_row["available_capital_cents"] == 60_000_000
    assert_funder_capital_conserved(funder_row, 60_000_000)


def test_self_funding_disabled_reports_its_own_error_not_the_credit_limit():
    """The empty-waterfall fallback is keyed on the last candidate, not on the amount.

    Under SELF_ONLY the only candidate is buyer self-funding, and the buyer's
    `self_funding_enabled` is false while its 100000000-cent credit limit easily
    covers the 98756-cent pre-fee net (face 100000 minus a 1244-cent discount).
    A fallback keyed on headroom would wrongly raise the 402 credit-limit error
    or wrongly succeed; with no funder registered at all a fallback keyed on the
    funder branch would wrongly raise the 422. The only correct answer is
    ERR_SELF_FUNDING_DISABLED with HTTP 409 and no EarlyPayment row.

    PRD §3.7: "When the waterfall exhausts its candidates without a payer, the
    error reported is the one belonging to the **last** candidate in the order,
    never the first."
    PRD §3.7: "Otherwise, if the buyer's `self_funding_enabled` is false, the
    answer is `ERR_SELF_FUNDING_DISABLED` (HTTP 409); and failing that, the
    answer is `ERR_BUYER_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Corner/calculations/self_funding_disabled_reports_its_own_error_not_the_credit_limit
    """
    ctx = fx.build_accepted_offer(
        face_cents=100_000,
        approval_date="2026-07-20T00:00:00Z",
        net_due_date="2026-09-30T00:00:00Z",
        offered_apr_bps=800,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
        buyer_overrides={
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": False,
        },
        program_overrides={
            "max_acceptable_apr_bps": 1200,
            "min_days_early": 5,
            "concentration_cap_pct": 100.00,
            "funding_policy": "SELF_ONLY",
        },
    )
    treasury = make_buyer_treasury_headers(ctx.buyer_id)
    admin = make_buyer_admin_headers(ctx.buyer_id)

    # ── trigger: reserve with the only candidate source disabled ──────────
    resp = api_client.create_early_payment(
        f.early_payment_payload(ctx.offer_id, ctx.offer_version), treasury
    )
    validate_error(resp, ERR_SELF_FUNDING_DISABLED, 409)

    rows, meta = validate_paginated(api_client.list_early_payments(treasury))
    assert meta["total_count"] == 0, (
        "the refused reservation must not have written an EarlyPayment row"
    )
    assert rows == []

    buyer = get_success_data(api_client.get_buyer(ctx.buyer_id, admin))
    assert buyer["credit_used_cents"] == 0

    # The failed reservation leaves the award intact.
    assert_invoice(fx.read_invoice(ctx.invoice_id, ctx.buyer_id), status="AWARDED")
    assert_offer(fx.read_offer(ctx.offer_id, ctx.buyer_id), status="ACCEPTED")


# ─────────────────────────────────────────────────────────────────────────────
# calculations / accounting_classification_default
# ─────────────────────────────────────────────────────────────────────────────
def test_accounting_default_uses_strict_thresholds_at_exact_equality():
    """Both threshold comparisons are strict, so exact equality stays TRADE_PAYABLE.

    One buyer with reclass_days_threshold 30 and reclass_apr_threshold_bps 900
    finances two 1000000-cent invoices through a funder at exactly 900 bps:
      BND-30 (net_due 2026-09-04, pay date 2026-08-05) -> 30 days early, and
        30 > 30 is false while 900 > 900 is false, so TRADE_PAYABLE
      BND-31 (net_due 2026-09-05, same pay date)       -> 31 days early, and
        31 > 30 is true, so DEBT_RECLASSIFIED on the days axis alone
    A >= implementation reclassifies the first as well. FUNDER_ONLY funding keeps
    the BUYER_SELF short-circuit from masking either comparison.

    PRD §3.9: "For a funder-financed payment, the default is
    `DEBT_RECLASSIFIED` when either the payment's `days_early` is strictly
    greater than the buyer's `reclass_days_threshold` or the payment's
    `accepted_apr_bps` is strictly greater than the buyer's
    `reclass_apr_threshold_bps`, and `TRADE_PAYABLE` otherwise."
    PRD §3.9: "Both comparisons are strict, so a payment whose days early
    exactly equals the buyer's threshold — 30 days on a default configuration —
    stays `TRADE_PAYABLE`, and the same holds for an accepted APR exactly at the
    buyer's threshold of 900 basis points on a default configuration."

    Design: Corner/calculations/accounting_default_uses_strict_thresholds_at_exact_equality
    """
    ctx = fx.build_base(
        buyer_overrides={
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
            "reclass_days_threshold": 30,
            "reclass_apr_threshold_bps": 900,
        },
        program_overrides={
            "max_acceptable_apr_bps": 1200,
            "min_days_early": 5,
            "concentration_cap_pct": 100.00,
            "funding_policy": "FUNDER_ONLY",
        },
        funders=[
            {
                "legal_name": "Boundary Capital",
                "capital_limit_cents": 60_000_000,
                "min_apr_bps": 500,
                "fee_spread_bps": 0,
                "max_single_invoice_cents": 5_000_000,
                "committed_amount_cents": 60_000_000,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-09-30T00:00:00Z",
            }
        ],
    )
    treasury = make_buyer_treasury_headers(ctx.buyer_id)

    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                invoice_number="BND-30",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-04T00:00:00Z",
                line_amount_cents=1_000_000,
            ),
            f.payable_row(
                ctx.supplier_id,
                invoice_number="BND-31",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-05T00:00:00Z",
                line_amount_cents=1_000_000,
            ),
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    invoices = fx.load_invoices(ctx)
    invoice_30, invoice_31 = invoices[0], invoices[1]

    offer_30 = fx.name_offer(
        invoice_30["id"],
        ctx.session_id,
        ctx.supplier_id,
        invoice_30["version"],
        offered_apr_bps=900,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    offer_31 = fx.name_offer(
        invoice_31["id"],
        ctx.session_id,
        ctx.supplier_id,
        invoice_31["version"],
        offered_apr_bps=900,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    offer_30 = fx.accept_offer_as_buyer(offer_30["id"], ctx.buyer_id)
    payment_30 = fx.reserve_payment(offer_30["id"], offer_30["version"], ctx.buyer_id)
    offer_31 = fx.accept_offer_as_buyer(offer_31["id"], ctx.buyer_id)

    # ── the exact-equality row: 30 days early at exactly 900 bps ──────────
    assert_payment(payment_30, accepted_apr_bps=900, funding_source="FUNDER")
    # discount = 1000000 * 900 * 30 / (10000 * 360) = 7500 exactly
    # pre-fee net 992500 -> tier 45 bps + spread 0; fee = 4466.25 -> 4466
    assert_cash_breakdown(
        payment_30,
        days_early=30,
        discount_amount_cents=7500,
        funder_fee_cents=4466,
        net_payment_cents=988_034,  # 1000000 - 7500 - 4466
    )
    assert payment_30["default_accounting_status"] == "TRADE_PAYABLE", (
        "30 is not strictly greater than 30 and 900 is not strictly greater "
        "than 900, so neither reclass trigger fires"
    )
    assert payment_30["default_accounting_status"] != "DEBT_RECLASSIFIED", (
        "DEBT_RECLASSIFIED here would mean the comparisons were coded as >="
    )

    # ── trigger: reserve the one-day-longer row ───────────────────────────
    resp = api_client.create_early_payment(
        f.early_payment_payload(offer_31["id"], offer_31["version"]), treasury
    )
    payment_31 = validate_success(resp, 201)

    # discount = 1000000 * 900 * 31 / (10000 * 360) = 7750 exactly
    # pre-fee net 992250 -> tier 45 bps; fee = 4465.125 -> 4465
    assert_payment(payment_31, accepted_apr_bps=900, funding_source="FUNDER")
    assert_cash_breakdown(
        payment_31,
        days_early=31,
        discount_amount_cents=7750,
        funder_fee_cents=4465,
        net_payment_cents=987_785,  # 1000000 - 7750 - 4465
    )
    assert payment_31["discount_amount_cents"] == f.expected_discount_cents(
        1_000_000, 900, 31
    )
    assert payment_31["funder_fee_cents"] == f.expected_funder_fee_cents(992_250, 0)
    assert payment_31["default_accounting_status"] == "DEBT_RECLASSIFIED", (
        "31 > 30 on the days axis alone flips the default"
    )

    # The default is a suggestion, not the applied classification.
    for row in (fx.read_payment(payment_30["id"], ctx.buyer_id), payment_31):
        assert_payment_axes(row, accounting_status="UNCLASSIFIED")

    funder_row = fx.read_funder(ctx.funders[0]["id"])
    assert funder_row["encumbered_capital_cents"] == 1_975_819  # 988034 + 987785
    assert funder_row["available_capital_cents"] == 58_024_181
    assert_funder_capital_conserved(funder_row, 60_000_000)


# ─────────────────────────────────────────────────────────────────────────────
# calculations / early_payment_discount (day-count basis and settlement lag)
# ─────────────────────────────────────────────────────────────────────────────
def test_discount_uses_the_360_day_basis_and_the_two_day_settlement_lag():
    """The 360-day year and the two-day lag are both visible in cents.

    A 30-day, 900-bp advance on a 1000000-cent face is
    1000000 * 900 * 30 / (10000 * 360) = 7500 cents exactly; a 365-day
    denominator would give 1000000 * 900 * 30 / (10000 * 365) = 7397.26… -> 7397.
    The same two constants show on the other axis: executing on 2026-08-05 sets
    value_date to 2026-08-07, so the settlement-confirmation recompute charges
    2026-09-04 - 2026-08-07 = 28 days, not 30, for
    1000000 * 900 * 28 / (10000 * 360) = 7000 cents.

    PRD §2.5: "Wherever a discount is derived from an annualised rate and a
    number of days, the annual rate is divided by 360 days, never by 365."
    PRD §3.8: "Multiply the invoice's `face_amount_cents` by the payment's
    frozen `accepted_apr_bps`, multiply by the days-early figure for the variant
    in force, then divide by the product of ten thousand — converting basis
    points to a rate — and the 360-day year, and round the result half up once,
    to a whole cent."
    PRD §3.8: "`value_date` is then set to `execution_date` advanced by two
    days."
    PRD §3.8: "On the **value-date basis**, used only at settlement
    confirmation, the basis date is the payment's `value_date`, which is the
    `execution_date` advanced by the two-day settlement lag; this variant charges
    only for the days the funds were genuinely out, and is therefore exactly two
    days shorter than the pay-date figure."

    Design: Corner/calculations/discount_uses_the_360_day_basis_and_the_two_day_settlement_lag
    """
    ctx = fx.build_deployed_payment(
        execute_at="2026-08-05T00:00:00Z",
        face_cents=1_000_000,
        approval_date="2026-07-20T00:00:00Z",
        net_due_date="2026-09-04T00:00:00Z",
        offered_apr_bps=900,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
        buyer_overrides={
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
        },
        program_overrides={
            "max_acceptable_apr_bps": 1200,
            "min_days_early": 5,
            "concentration_cap_pct": 100.00,
            "funding_policy": "SELF_ONLY",
        },
    )
    treasury = make_buyer_treasury_headers(ctx.buyer_id)
    admin = make_buyer_admin_headers(ctx.buyer_id)

    # ── at execution the pay-date basis still stands: 30 days, 7500 cents ─
    executed = ctx.payment
    assert_payment_axes(
        executed, funding_status="DEPLOYED", settlement_status="REMITTED"
    )
    assert_cash_breakdown(
        executed,
        days_early=30,
        discount_amount_cents=7500,
        funder_fee_cents=0,
        net_payment_cents=992_500,  # 1000000 - 7500 - 0
    )
    assert executed["discount_amount_cents"] == f.expected_discount_cents(
        1_000_000, 900, 30
    )
    assert executed["discount_amount_cents"] != 7397, (
        "7397 is the same advance on a 365-day year; the contract fixes 360"
    )
    assert str(executed["execution_date"]).startswith("2026-08-05"), (
        "execution_date is the logical-clock date of the execute call"
    )
    assert str(executed["value_date"]).startswith("2026-08-07"), (
        "value_date is execution_date advanced by the two-day settlement lag"
    )

    advices, _ = validate_paginated(
        api_client.list_remittance_advices(ctx.payment_id, treasury)
    )
    assert len(advices) == 1, "execution produces exactly one remittance advice"
    advice_before = advices[0]
    assert advice_before["gross_face_cents"] == 1_000_000
    assert advice_before["discount_cents"] == 7500
    assert advice_before["fee_cents"] == 0
    assert advice_before["net_paid_cents"] == 992_500
    assert str(advice_before["value_date"]).startswith("2026-08-07")

    # ── trigger: confirm on the value date, switching to the value basis ──
    fx.set_clock("2026-08-07T00:00:00Z")
    resp = api_client.confirm_settlement(ctx.payment_id, treasury)
    payment = validate_success(resp, 200)

    assert_payment_axes(
        payment, funding_status="RELEASED", settlement_status="CONFIRMED"
    )
    # value-date days early = 2026-09-04 - 2026-08-07 = 28
    # discount = 1000000 * 900 * 28 / (10000 * 360) = 7000 exactly
    assert_cash_breakdown(
        payment,
        days_early=28,
        discount_amount_cents=7000,
        funder_fee_cents=0,
        net_payment_cents=993_000,  # 1000000 - 7000 - 0
    )
    assert payment["discount_amount_cents"] == f.expected_discount_cents(
        1_000_000, 900, 28
    )
    assert payment["days_early"] != 30, (
        "the value-date basis is exactly two days shorter than the pay-date one"
    )

    invoice = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert_invoice(
        invoice,
        status="EARLY_PAID",
        provisional_discount_cents=7500,
        final_discount_cents=7000,
        discount_true_up_cents=-500,  # 7000 - 7500
    )

    buyer = get_success_data(api_client.get_buyer(ctx.buyer_id, admin))
    assert buyer["credit_used_cents"] == 0, (
        "a RELEASED payment frees the buyer's self-funding credit in full"
    )

    advices_after, _ = validate_paginated(
        api_client.list_remittance_advices(ctx.payment_id, treasury)
    )
    assert len(advices_after) == 1
    assert advices_after[0]["net_paid_cents"] == 992_500, (
        "the advice is an immutable snapshot of the remittance, not a live view "
        "of the recomputed net payment"
    )
    assert advices_after[0]["discount_cents"] == 7500
