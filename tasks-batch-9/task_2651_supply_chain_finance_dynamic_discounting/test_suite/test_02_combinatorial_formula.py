"""Depth tests for the ``combinatorial_formula`` rule.

Three formulas in this contract have a pinned evaluation order that a
superficially reasonable alternative order would get wrong: invoice face rounds
per line before summing, the funder fee tier is keyed on the pre-fee net rather
than the final net, and the funder selector ranks on a capped, three-term score
rather than on raw capital depth.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_FILE_TOTALS_MISMATCH
from test_helpers.assertions import (
    assert_append_only_common_fields,
    assert_cash_breakdown,
    assert_funder_capital_conserved,
)

THREE_LINE_ROW = [
    f.invoice_line(1, 33333, 875),
    f.invoice_line(2, 33333, 875),
    f.invoice_line(3, 33334, 875),
]
PER_LINE_ROUNDING_FACE = 108751
SUM_THEN_ROUND_FACE = 108750


def _self_only_base():
    """An OPEN SUPPLIER_NAMED programme with one fully onboarded supplier and no
    session, which is all the ingestion tests need."""
    return fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={"credit_limit_cents": 100_000_000},
        program_overrides={
            "program_type": "SUPPLIER_NAMED",
            "max_acceptable_apr_bps": 1200,
        },
        session_window=None,
    )


def _funder_only_ctx(funders):
    """An OPEN FUNDER_ONLY programme on a buyer that may not self-fund, plus a
    LIVE-capable session and the requested funders with their tranches."""
    return fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={"credit_limit_cents": 1000, "self_funding_enabled": False},
        program_overrides={
            "program_type": "SUPPLIER_NAMED",
            "max_acceptable_apr_bps": 1200,
            "min_days_early": 5,
            "concentration_cap_pct": 100.00,
            "funding_policy": "FUNDER_ONLY",
        },
        session_window=("2026-08-02T00:00:00Z", "2026-08-31T00:00:00Z"),
        funders=funders,
    )


def _single_line_invoice(ctx, face_cents, net_due_date, approval_date="2026-07-25T00:00:00Z"):
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                approval_date=approval_date,
                net_due_date=net_due_date,
                line_amount_cents=face_cents,
            )
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    fx.load_invoices(ctx)
    assert ctx.invoice["face_amount_cents"] == face_cents, (
        "a zero-tax single-line row prices at its line amount, got {}".format(
            ctx.invoice["face_amount_cents"]
        )
    )
    return ctx.invoice


def test_invoice_face_rounds_per_line_then_sums():
    """Three lines of 33333 / 33333 / 33334 at 875 bps each round to 2917 cents of
    tax, giving a face of 108751 rather than the 108750 a blended rate would give.

    PRD (§3.3): "The alternative order — summing the pre-tax amounts first and
    applying a blended rate once at the end — is explicitly not the rule and
    produces a different cent total for the same input: three lines of 33333,
    33333 and 33334 cents each at 875 basis points yield per-line taxes of 2917,
    2917 and 2917 cents and line totals of 36250, 36250 and 36251 cents, for a
    face of 108751 cents, whereas rounding after summation would yield 108750."

    Design: Difficulty/combinatorial_formula/invoice_face_rounds_per_line_then_sums
    """
    ctx = _self_only_base()
    payable_file = fx.ingest_file(
        ctx.program_id,
        ctx.buyer_id,
        [
            f.payable_row(
                ctx.supplier_id,
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                lines=THREE_LINE_ROW,
            )
        ],
        declared_row_count=1,
        declared_total_cents=PER_LINE_ROUNDING_FACE,
    )
    assert_append_only_common_fields(payable_file)
    assert payable_file["ingest_status"] == "ACCEPTED", (
        "a file with no rejected rows is ACCEPTED, got {}".format(
            payable_file["ingest_status"]
        )
    )
    assert payable_file["computed_total_cents"] == PER_LINE_ROUNDING_FACE, (
        "computed_total_cents is the per-line-rounded 108751, got {}".format(
            payable_file["computed_total_cents"]
        )
    )
    assert payable_file["computed_total_cents"] != SUM_THEN_ROUND_FACE, (
        "108750 is the forbidden sum-then-round total"
    )
    assert payable_file["accepted_row_count"] == 1
    assert payable_file["rejected_row_count"] == 0

    invoices = fx.invoices_of_file(payable_file["id"], ctx.buyer_id)
    assert len(invoices) == 1, "one accepted row produces one invoice"
    invoice = invoices[0]
    assert invoice["face_amount_cents"] == PER_LINE_ROUNDING_FACE, (
        "the invoice face is 108751, got {}".format(invoice["face_amount_cents"])
    )

    lines = validate_success(
        api_client.list_invoice_lines(invoice["id"], ctx.admin)
    )
    assert [line["line_no"] for line in lines] == [1, 2, 3], (
        "lines are read back in ascending line_no order, got {}".format(
            [line["line_no"] for line in lines]
        )
    )
    assert [line["line_tax_cents"] for line in lines] == [2917, 2917, 2917], (
        "each line's tax rounds half up to 2917, got {}".format(
            [line["line_tax_cents"] for line in lines]
        )
    )
    assert [line["line_total_cents"] for line in lines] == [36250, 36250, 36251], (
        "line totals are amount plus per-line tax, got {}".format(
            [line["line_total_cents"] for line in lines]
        )
    )
    assert sum(line["line_total_cents"] for line in lines) == PER_LINE_ROUNDING_FACE
    for line in lines:
        assert_append_only_common_fields(line)


def test_file_declaring_the_sum_then_round_total_is_rejected():
    """A file declaring 108750 — the blended-rate total — fails control-total
    reconciliation against the per-line-rounded 108751.

    PRD (§3.3): "The control-total reconciliation then runs: `declared_row_count`
    must equal `accepted_row_count` and `declared_total_cents` must equal
    `computed_total_cents`, and a mismatch on either side rejects the whole
    submission with `ERR_FILE_TOTALS_MISMATCH`."

    Design: Difficulty/combinatorial_formula/invoice_face_rounds_per_line_then_sums
    """
    ctx = _self_only_base()
    response = api_client.create_payable_file(
        f.payable_file_payload(
            ctx.program_id,
            [
                f.payable_row(
                    ctx.supplier_id,
                    approval_date="2026-07-20T00:00:00Z",
                    net_due_date="2026-09-30T00:00:00Z",
                    lines=THREE_LINE_ROW,
                )
            ],
            declared_row_count=1,
            declared_total_cents=SUM_THEN_ROUND_FACE,
        ),
        ctx.admin,
    )
    validate_error(response, ERR_FILE_TOTALS_MISMATCH, 422)

    # A rejected submission creates nothing.
    invoices = validate_success(
        api_client.list_invoices(ctx.admin, program_id=ctx.program_id)
    )
    assert invoices == [], (
        "a totals mismatch rejects the whole submission, so no invoice exists, got {}".format(
            invoices
        )
    )


def _funder_financed_reservation(face_cents, offered_apr_bps, funder_spec):
    """Reserve one funder-financed payment on an invoice of the given face at the
    given APR, with requested_pay_date 2026-08-10 and net_due_date 2026-11-08 so
    the pay-date basis is exactly 90 days."""
    ctx = _funder_only_ctx([funder_spec])
    _single_line_invoice(ctx, face_cents, "2026-11-08T00:00:00Z")
    offer = fx.name_offer(
        ctx.invoice_id,
        ctx.session_id,
        ctx.supplier_id,
        ctx.invoice_version,
        offered_apr_bps=offered_apr_bps,
        requested_pay_date="2026-08-10T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    accepted = fx.accept_offer_as_buyer(offer["id"], ctx.buyer_id)
    ctx.payment = fx.reserve_payment(accepted["id"], accepted["version"], ctx.buyer_id)
    ctx.payment_id = ctx.payment["id"]
    return ctx


def test_funder_fee_tier_keyed_on_pre_fee_net_not_final_net():
    """A pre-fee net of 25020060 sits in the 18 bps tier and yields a fee of 45036,
    where keying the tier on the post-fee net would have selected 30 bps.

    PRD (§3.8): "**The funder fee** is computed immediately after the discount,
    and its tier is keyed on the **pre-fee net** — the invoice's
    `face_amount_cents` minus the payment's `discount_amount_cents` — never on the
    final net after the fee has been taken out."
    PRD (§3.8): "Why the ordering is pinned is easiest to see near a boundary: a
    face of 25661600 cents at 1000 basis points over 90 days gives a discount of
    641540 cents and a pre-fee net of 25020060 cents, which sits in the
    18-basis-point tier and yields a fee of 45036 cents and a net payment of
    24975024 cents."

    Design: Difficulty/combinatorial_formula/funder_fee_tier_keyed_on_pre_fee_net_not_final_net
    """
    ctx = _funder_financed_reservation(
        25_661_600,
        1000,
        {
            "capital_limit_cents": 60_000_000,
            "min_apr_bps": 500,
            "fee_spread_bps": 0,
            "max_single_invoice_cents": 30_000_000,
            "committed_amount_cents": 60_000_000,
            "effective_from": "2026-08-01T00:00:00Z",
            "effective_to": "2026-12-31T00:00:00Z",
        },
    )
    payment = ctx.payment
    assert payment["funding_source"] == "FUNDER", (
        "a FUNDER_ONLY programme resolves to FUNDER, got {}".format(
            payment["funding_source"]
        )
    )
    assert payment["funder_id"] == ctx.funder_id, (
        "the only eligible funder must win, got funder_id {}".format(
            payment["funder_id"]
        )
    )
    assert_cash_breakdown(
        payment,
        days_early=90,
        discount_amount_cents=641_540,
        funder_fee_cents=45_036,
        net_payment_cents=24_975_024,
    )
    # The pre-fee net is what selects the tier.
    pre_fee_net = payment["face_covered_cents"] - payment["discount_amount_cents"]
    assert pre_fee_net == 25_020_060, (
        "the pre-fee net is face minus discount, got {}".format(pre_fee_net)
    )
    assert payment["funder_fee_cents"] != 75_060, (
        "75060 is the 30 bps answer produced by keying the tier on the post-fee net"
    )
    assert payment["net_payment_cents"] != 24_945_000, (
        "24945000 is the net the forbidden post-fee tier selection would produce"
    )
    assert payment["default_accounting_status"] == "DEBT_RECLASSIFIED", (
        "days_early 90 is strictly greater than the buyer's 30-day threshold, got {}".format(
            payment["default_accounting_status"]
        )
    )

    funder = fx.read_funder(ctx.funder_id)
    assert funder["encumbered_capital_cents"] == 24_975_024, (
        "reservation encumbers the net payment, got {}".format(
            funder["encumbered_capital_cents"]
        )
    )
    assert funder["available_capital_cents"] == 35_024_976, (
        "60000000 committed minus 24975024 encumbered is 35024976, got {}".format(
            funder["available_capital_cents"]
        )
    )
    assert_funder_capital_conserved(funder, 60_000_000)


def test_fee_tier_boundary_belongs_to_the_higher_bracket():
    """A pre-fee net of exactly 5000000 falls in the 30 bps bracket, not the 45 bps
    one, because the brackets are half-open at the top.

    PRD (§3.8): "Otherwise the tier rate is 45 basis points when the pre-fee net is
    below 5000000 cents, 30 basis points when it is at least 5000000 and below
    25000000 cents, and 18 basis points at 25000000 cents and above; the brackets
    are half-open at the top, so a pre-fee net exactly at a bracket boundary
    belongs to the higher bracket."

    Design: Difficulty/combinatorial_formula/funder_fee_tier_keyed_on_pre_fee_net_not_final_net
    """
    ctx = _funder_financed_reservation(
        5_128_205,
        1000,
        {
            "capital_limit_cents": 60_000_000,
            "min_apr_bps": 500,
            "fee_spread_bps": 0,
            "max_single_invoice_cents": 30_000_000,
            "committed_amount_cents": 60_000_000,
            "effective_from": "2026-08-01T00:00:00Z",
            "effective_to": "2026-12-31T00:00:00Z",
        },
    )
    payment = ctx.payment
    assert payment["days_early"] == 90, (
        "2026-11-08 minus 2026-08-10 is 90 days, got {}".format(payment["days_early"])
    )
    assert payment["discount_amount_cents"] == 128_205, (
        "5128205 * 1000 * 90 / (10000 * 360) rounds half up to 128205, got {}".format(
            payment["discount_amount_cents"]
        )
    )
    pre_fee_net = payment["face_covered_cents"] - payment["discount_amount_cents"]
    assert pre_fee_net == 5_000_000, (
        "this fixture is built so the pre-fee net lands exactly on the bracket "
        "boundary, got {}".format(pre_fee_net)
    )
    assert payment["funder_fee_cents"] == 15_000, (
        "5000000 at the 30 bps tier plus a 0 bps spread is 15000, got {}".format(
            payment["funder_fee_cents"]
        )
    )
    assert payment["funder_fee_cents"] != 22_500, (
        "22500 is the 45 bps answer, which would put the boundary in the lower bracket"
    )
    assert payment["net_payment_cents"] == 4_985_000, (
        "5000000 minus the 15000 fee is 4985000, got {}".format(
            payment["net_payment_cents"]
        )
    )


def _selection_reservation(funder_specs):
    """The PRD's selector illustration, built through the API: an invoice of
    1000000 cents, an accepted APR of 900 bps and a requested pay date 30 days
    before the net due date, so the provisional discount is 7500 cents and the
    pre-fee net is 992500 cents."""
    ctx = _funder_only_ctx(funder_specs)
    _single_line_invoice(ctx, 1_000_000, "2026-09-09T00:00:00Z")
    offer = fx.name_offer(
        ctx.invoice_id,
        ctx.session_id,
        ctx.supplier_id,
        ctx.invoice_version,
        offered_apr_bps=900,
        requested_pay_date="2026-08-10T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    accepted = fx.accept_offer_as_buyer(offer["id"], ctx.buyer_id)
    ctx.payment = fx.reserve_payment(accepted["id"], accepted["version"], ctx.buyer_id)
    ctx.payment_id = ctx.payment["id"]
    assert ctx.payment["days_early"] == 30, (
        "2026-09-09 minus 2026-08-10 is 30 days, got {}".format(
            ctx.payment["days_early"]
        )
    )
    assert ctx.payment["discount_amount_cents"] == 7_500, (
        "1000000 * 900 * 30 / (10000 * 360) is exactly 7500, got {}".format(
            ctx.payment["discount_amount_cents"]
        )
    )
    return ctx


def test_funder_selection_score_beats_raw_capital_depth():
    """The funder with 1500000 cents of capital beats the funder with 60000000,
    because 800 - 54 = 746 outscores 600 - 90 + 150 = 660.

    PRD (§3.7): "A first funder with `min_apr_bps` 600, `fee_spread_bps` 30 and
    60000000 cents of free capital scores 600 for rate headroom, loses 90 to fee
    drag, and earns the 150-point depth bonus, for 660. A second funder with
    `min_apr_bps` 500, `fee_spread_bps` 18 and only 1500000 cents of free capital
    scores 800 for rate headroom — its headroom of 400 basis points is exactly at
    the cap — loses 54 to fee drag, and earns no depth bonus because its free
    capital is below twice the pre-fee net, for 746. The second funder wins despite
    having a small fraction of the first funder's capital"

    Design: Difficulty/combinatorial_formula/funder_selection_score_beats_raw_capital_depth
    """
    ctx = _selection_reservation(
        [
            {
                "legal_name": "Deep Capital Partners",
                "capital_limit_cents": 60_000_000,
                "min_apr_bps": 600,
                "fee_spread_bps": 30,
                "max_single_invoice_cents": 5_000_000,
                "committed_amount_cents": 60_000_000,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-12-31T00:00:00Z",
            },
            {
                "legal_name": "Keen Pricing Partners",
                "capital_limit_cents": 1_500_000,
                "min_apr_bps": 500,
                "fee_spread_bps": 18,
                "max_single_invoice_cents": 5_000_000,
                "committed_amount_cents": 1_500_000,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-12-31T00:00:00Z",
            },
        ]
    )
    deep, keen = ctx.funders[0], ctx.funders[1]
    payment = ctx.payment
    assert payment["funder_id"] == keen["id"], (
        "the 746-point funder must win over the 660-point one; the winner was {} "
        "(deep={}, keen={})".format(payment["funder_id"], deep["id"], keen["id"])
    )
    assert payment["funder_id"] != deep["id"], (
        "ranking on raw capital depth would have picked the 60000000-cent funder"
    )
    assert_cash_breakdown(
        payment,
        days_early=30,
        discount_amount_cents=7_500,
        funder_fee_cents=6_253,
        net_payment_cents=986_247,
    )
    assert payment["funder_fee_cents"] != 7_444, (
        "7444 is the 45+30 bps fee the losing funder would have charged"
    )
    assert payment["net_payment_cents"] != 985_056, (
        "985056 is the net the losing funder would have produced"
    )

    winner = fx.read_funder(keen["id"])
    assert winner["encumbered_capital_cents"] == 986_247, (
        "the winner's ledger carries the reservation, got {}".format(
            winner["encumbered_capital_cents"]
        )
    )
    assert winner["available_capital_cents"] == 513_753, (
        "1500000 minus 986247 is 513753, got {}".format(
            winner["available_capital_cents"]
        )
    )
    assert_funder_capital_conserved(winner, 1_500_000)

    loser = fx.read_funder(deep["id"])
    assert loser["encumbered_capital_cents"] == 0, (
        "the funder that lost the ranking encumbers nothing, got {}".format(
            loser["encumbered_capital_cents"]
        )
    )
    assert loser["available_capital_cents"] == 60_000_000, (
        "the loser's whole tranche stays free, got {}".format(
            loser["available_capital_cents"]
        )
    )
    assert_funder_capital_conserved(loser, 60_000_000)


def test_rate_headroom_term_is_capped_before_the_depth_bonus_is_added():
    """A funder whose rate headroom is 800 basis points scores the same 800 points
    as one whose headroom is exactly 400, so the 150-point depth bonus decides the
    ranking; uncapped headroom would have doubled to 1600 and won.

    PRD (§3.7): "The first term rewards rate headroom: take the payment's
    `accepted_apr_bps` minus that funder's `min_apr_bps`, cap the result at 400
    basis points by taking the smaller of the two, and double it."
    PRD (§3.7): "The third term is a depth bonus of 150 points, added only when
    that funder's committed capital at the projected value date minus its
    `encumbered_capital_cents` is at least twice the pre-fee net, and zero
    otherwise."

    Design: Difficulty/combinatorial_formula/funder_selection_score_beats_raw_capital_depth
    """
    ctx = _selection_reservation(
        [
            {
                "legal_name": "Wide Headroom Partners",
                "capital_limit_cents": 1_500_000,
                "min_apr_bps": 100,
                "fee_spread_bps": 0,
                "max_single_invoice_cents": 5_000_000,
                "committed_amount_cents": 1_500_000,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-12-31T00:00:00Z",
            },
            {
                "legal_name": "Deep Book Partners",
                "capital_limit_cents": 60_000_000,
                "min_apr_bps": 500,
                "fee_spread_bps": 0,
                "max_single_invoice_cents": 5_000_000,
                "committed_amount_cents": 60_000_000,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-12-31T00:00:00Z",
            },
        ]
    )
    wide, deep = ctx.funders[0], ctx.funders[1]
    payment = ctx.payment
    # Both spreads are zero, so the fee term cannot separate them: 800 + 0 + 0 = 800
    # for the wide-headroom funder against 800 + 0 + 150 = 950 for the deep one.
    assert payment["funder_id"] == deep["id"], (
        "with headroom capped at 400 bps both rate terms are 800, so the depth "
        "bonus wins it for the deep funder; got {} (wide={}, deep={})".format(
            payment["funder_id"], wide["id"], deep["id"]
        )
    )
    assert payment["funder_id"] != wide["id"], (
        "an uncapped headroom term would have scored 1600 and wrongly won"
    )
    assert_cash_breakdown(
        payment,
        days_early=30,
        discount_amount_cents=7_500,
        funder_fee_cents=4_466,
        net_payment_cents=988_034,
    )

    winner = fx.read_funder(deep["id"])
    assert winner["encumbered_capital_cents"] == 988_034, (
        "the winner encumbers the net payment, got {}".format(
            winner["encumbered_capital_cents"]
        )
    )
    assert winner["available_capital_cents"] == 59_011_966, (
        "60000000 minus 988034 is 59011966, got {}".format(
            winner["available_capital_cents"]
        )
    )
    loser = fx.read_funder(wide["id"])
    assert loser["encumbered_capital_cents"] == 0, (
        "the wide-headroom funder was not selected, got encumbered {}".format(
            loser["encumbered_capital_cents"]
        )
    )
    assert loser["available_capital_cents"] == 1_500_000, (
        "its whole 1500000-cent tranche stays free, got {}".format(
            loser["available_capital_cents"]
        )
    )
