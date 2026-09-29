"""Depth tests for the ``boundary_precision_check`` rule.

Two percentages in this contract are compared against a threshold *after* being
rounded half up to two decimals, and both comparisons are decided by cents that
a naive implementation would never notice. The concentration gate refuses an
award only when the rounded projected share is strictly greater than the cap, so
a portfolio one cent past the cap still passes while one five cents past it does
not. The adoption rate has two degenerate denominators — a programme with no
invoices at all, and a programme whose only other invoice is suppressed and
therefore leaves both sides of the ratio — and its band edges are inclusive at
the bottom, so an adoption rate of exactly 60.00 percent is already
``THROTTLED``.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_CONCENTRATION_CAP_EXCEEDED
from test_helpers.assertions import (
    assert_analytics,
    assert_invoice,
    assert_offer,
    assert_payment_axes,
    assert_program,
    assert_two_decimal_percentage,
)
from test_helpers.test_users import make_buyer_admin_headers

EDGE_PROGRAM = {
    "program_type": "SUPPLIER_NAMED",
    "max_acceptable_apr_bps": 1200,
    "min_days_early": 5,
    "concentration_cap_pct": 60.00,
    "funding_policy": "SELF_ONLY",
}


def _concentration_ctx(specs):
    """One buyer, supplier A onboarded to ACTIVE, filler supplier B merely
    registered, and one OPEN programme per ``spec`` — each with a LIVE session, a
    two-row payable file splitting 100000 cents between A and B, and a NAMED
    900 bps offer on A's invoice.

    ``specs`` is a list of ``(name, prefix, a_face, b_face)`` tuples.
    """
    ctx = fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={
            "legal_name": "Concentration Edge Buyer",
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
        },
        supplier_overrides={
            "legal_name": "Dominant Supplier A",
            "remittance_email": "ar@dominant.example",
        },
        open_the_program=False,
        session_window=None,
    )
    ctx.a_id = ctx.supplier_id
    ctx.b_id = fx.new_supplier(
        legal_name="Filler Supplier B", tax_id_last4="2020"
    )["id"]

    bundles = {}
    for name, prefix, a_face, b_face in specs:
        program = fx.new_open_program(ctx.buyer_id, name=name, **EDGE_PROGRAM)
        session = fx.new_session(
            program["id"],
            ctx.buyer_id,
            "2026-08-02T00:00:00Z",
            "2026-08-31T00:00:00Z",
        )
        payable_file = fx.ingest_file(
            program["id"],
            ctx.buyer_id,
            [
                f.payable_row(
                    ctx.a_id,
                    invoice_number="{}-A".format(prefix),
                    approval_date="2026-07-20T00:00:00Z",
                    net_due_date="2026-09-30T00:00:00Z",
                    line_amount_cents=a_face,
                ),
                f.payable_row(
                    ctx.b_id,
                    invoice_number="{}-B".format(prefix),
                    approval_date="2026-07-20T00:00:00Z",
                    net_due_date="2026-09-30T00:00:00Z",
                    line_amount_cents=b_face,
                ),
            ],
        )
        bundles[prefix] = {
            "program_id": program["id"],
            "session_id": session["id"],
            "file_id": payable_file["id"],
            "a_face": a_face,
            "b_face": b_face,
        }

    fx.set_clock("2026-08-02T00:00:00Z")
    ctx.clock = "2026-08-02T00:00:00Z"

    for prefix, bundle in bundles.items():
        rows = fx.invoices_of_file(bundle["file_id"], ctx.buyer_id)
        by_number = {row["invoice_number"]: row for row in rows}
        invoice_a = by_number["{}-A".format(prefix)]
        bundle["invoice_a"] = invoice_a
        bundle["invoice_b"] = by_number["{}-B".format(prefix)]
        bundle["offer"] = fx.name_offer(
            invoice_a["id"],
            bundle["session_id"],
            ctx.a_id,
            invoice_a["version"],
            offered_apr_bps=900,
            requested_pay_date="2026-08-05T00:00:00Z",
            acceptance_deadline="2026-08-20T00:00:00Z",
        )
    ctx.bundles = bundles
    return ctx


def _analytics(ctx, program_id):
    return validate_success(
        api_client.get_program_analytics(
            program_id, make_buyer_admin_headers(ctx.buyer_id)
        )
    )


def test_projected_concentration_share_at_and_just_past_the_cap_both_pass():
    """A projected share of exactly 60.00 percent passes because the comparison is
    strict, and a share of 60.001 percent also passes because it is rounded half
    up to 60.00 *before* that comparison is made.

    PRD §3.6: "The projected share is one hundred times the numerator divided by
    the denominator, rounded half up to exactly two decimals, and is 0.00 when
    the denominator is zero. The award is refused with
    `ERR_CONCENTRATION_CAP_EXCEEDED` when that projected share is strictly
    greater than the programme's `concentration_cap_pct`; a projected share
    exactly equal to the cap is allowed."

    PRD §2.7 check 25: "a projected share exactly equal to the cap passes."

    Design: Difficulty/boundary_precision_check/concentration_cap_rounds_to_two_decimals_before_the_strict_comparison
    """
    ctx = _concentration_ctx(
        [
            ("Edge P1", "P1", 60_000, 40_000),
            ("Edge P2", "P2", 60_001, 39_999),
        ]
    )

    at_cap = ctx.bundles["P1"]
    accepted = fx.accept_offer_as_buyer(at_cap["offer"]["id"], ctx.buyer_id)
    assert_offer(accepted, status="ACCEPTED", accepted_apr_bps=900)
    assert_invoice(
        fx.read_invoice(at_cap["invoice_a"]["id"], ctx.buyer_id),
        status="AWARDED",
        face_amount_cents=60_000,
    )

    rounds_down = ctx.bundles["P2"]
    accepted_2 = fx.accept_offer_as_buyer(rounds_down["offer"]["id"], ctx.buyer_id)
    assert_offer(accepted_2, status="ACCEPTED", accepted_apr_bps=900)
    assert_invoice(
        fx.read_invoice(rounds_down["invoice_a"]["id"], ctx.buyer_id),
        status="AWARDED",
        face_amount_cents=60_001,
    )

    # 60000/100000 is exactly the cap; nothing has been executed, so the funded
    # basis is still 0.00 while the face basis already reads 60.00.
    view_1 = _analytics(ctx, at_cap["program_id"])
    assert_analytics(
        view_1,
        eligible_invoice_count=2,
        adopted_invoice_count=0,
        adoption_rate_pct=0.00,
        rate_posture="DISCOVERY",
        concentration_top_supplier_face_pct=60.00,
        concentration_top_supplier_funded_pct=0.00,
        concentration_cap_pct=60.00,
    )
    assert view_1["concentration_top_supplier_face_pct"] != view_1[
        "concentration_top_supplier_funded_pct"
    ], "the two concentration bases deliberately disagree once one is populated"

    # 100 * 60001 / 100000 is 60.001, which the two-decimal rounding collapses
    # onto the cap rather than above it.
    view_2 = _analytics(ctx, rounds_down["program_id"])
    assert_analytics(
        view_2,
        eligible_invoice_count=2,
        concentration_top_supplier_face_pct=60.00,
        concentration_cap_pct=60.00,
    )
    assert view_2["concentration_top_supplier_face_pct"] != 60.01, (
        "60.001 must round half up to 60.00, not up to 60.01"
    )


def test_projected_concentration_share_five_cents_past_the_cap_is_refused():
    """Five cents further on, the same ratio rounds half up to 60.01 percent and
    the award is refused — which is what proves the rounding runs before the
    comparison and uses half up rather than half even.

    PRD §3.6: "The award is refused with `ERR_CONCENTRATION_CAP_EXCEEDED` when
    that projected share is strictly greater than the programme's
    `concentration_cap_pct`"

    PRD §2.2: "the rounding method is **round half up**: the value is scaled to
    the target precision, and a value whose fractional part is exactly one half
    is rounded away from zero"

    PRD §3.10: "`concentration_top_supplier_face_pct` is the largest face-basis
    share held by any single supplier on the programme ... the numerator is that
    supplier's invoices on the programme in `AWARDED` or `EARLY_PAID` summed at
    `face_amount_cents`"

    Design: Difficulty/boundary_precision_check/concentration_cap_rounds_to_two_decimals_before_the_strict_comparison
    """
    ctx = _concentration_ctx([("Edge P3", "P3", 60_005, 39_995)])
    rounds_up = ctx.bundles["P3"]
    offer = rounds_up["offer"]

    refused = api_client.accept_offer(
        offer["id"], make_buyer_admin_headers(ctx.buyer_id)
    )
    validate_error(refused, ERR_CONCENTRATION_CAP_EXCEEDED, 409)

    # A refused award leaves both rows exactly where they were.
    assert_offer(
        fx.read_offer(offer["id"], ctx.buyer_id),
        status="NAMED",
        version=offer["version"],
        accepted_apr_bps=0,
    )
    invoice_a = fx.read_invoice(rounds_up["invoice_a"]["id"], ctx.buyer_id)
    assert_invoice(
        invoice_a,
        status="OFFERED",
        face_amount_cents=60_005,
        accepted_apr_bps=0,
        face_covered_cents=0,
    )

    # No invoice of P3 ever reached AWARDED, so the face basis is still 0.00.
    view = _analytics(ctx, rounds_up["program_id"])
    assert_analytics(
        view,
        eligible_invoice_count=2,
        adopted_invoice_count=0,
        concentration_top_supplier_face_pct=0.00,
        concentration_top_supplier_funded_pct=0.00,
        concentration_cap_pct=60.00,
    )
    assert view["concentration_top_supplier_face_pct"] != 60.01, (
        "the refused award must not be counted into the face basis"
    )
    assert_two_decimal_percentage(view["concentration_cap_pct"], 60.00)


def _read_program(ctx, program_id):
    return validate_success(
        api_client.get_program(program_id, make_buyer_admin_headers(ctx.buyer_id))
    )


def test_a_programme_with_no_invoices_reports_zero_adoption_rather_than_null():
    """The empty denominator is pinned: an OPEN programme carrying no payable file
    at all reports an adoption rate of exactly 0.00, a weighted average of 0 and
    the untouched configured ceiling.

    PRD §3.10: "`adoption_rate_pct` is one hundred times the adopted count
    divided by the eligible count, rounded half up to exactly two decimals — and
    when the eligible count is zero it is exactly 0.00, never null and never a
    division error."

    PRD §3.10: "When no invoice on the programme is `EARLY_PAID`, the figure is
    0."

    PRD §3.10: "A brand-new programme with no invoices therefore sits at 0.00
    percent in `DISCOVERY`." and "While `rate_posture` is `DISCOVERY`, the
    candidate ceiling is the programme's existing `max_acceptable_apr_bps`, left
    alone."

    PRD §3.10: "both are exactly 0.00 when their denominator is zero."

    Design: Difficulty/boundary_precision_check/adoption_rate_empty_denominator_and_inclusive_throttled_edge
    """
    ctx = fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={
            "legal_name": "Empty Denominator Buyer",
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
        },
        program_overrides={
            "name": "Empty Programme",
            "program_type": "FIXED_RATE",
            "fixed_apr_bps": 1000,
            "max_acceptable_apr_bps": 1200,
            "min_days_early": 5,
            "concentration_cap_pct": 100.00,
            "funding_policy": "SELF_ONLY",
        },
        onboard=False,
        session_window=None,
    )

    view = _analytics(ctx, ctx.program_id)
    assert_analytics(
        view,
        eligible_invoice_count=0,
        adopted_invoice_count=0,
        adoption_rate_pct=0.00,
        rate_posture="DISCOVERY",
        weighted_avg_accepted_apr_bps=0,
        max_acceptable_apr_bps=1200,
        concentration_top_supplier_face_pct=0.00,
        concentration_top_supplier_funded_pct=0.00,
        concentration_cap_pct=100.00,
    )
    assert view["adoption_rate_pct"] is not None, (
        "an empty denominator yields 0.00, never null"
    )
    assert view["weighted_avg_accepted_apr_bps"] is not None, (
        "the weighted average of an empty set is 0, never null"
    )

    # DISCOVERY leaves the ceiling exactly where it was configured.
    program = _read_program(ctx, ctx.program_id)
    assert_program(
        program,
        status="OPEN",
        max_acceptable_apr_bps=1200,
        rate_posture="DISCOVERY",
        eligible_invoice_count=0,
        adopted_invoice_count=0,
        adoption_rate_pct=0.00,
        weighted_avg_accepted_apr_bps=0,
    )


def test_a_suppressed_invoice_leaves_both_sides_of_the_adoption_ratio():
    """The suppressed row is excluded from the numerator *and* the denominator, so
    a two-row file yields an eligible count of 1; paying that single invoice puts
    adoption at 100.00 percent, which is `THROTTLED` and tightens the ceiling by
    the 75 percent factor to 750 rather than the 90 percent factor's 900.

    PRD §3.10: "Note which invoices are excluded from **both** the numerator and
    the denominator: invoices in `SUPPRESSED` and invoices in `MATURED`."

    PRD §3.10: "An adoption rate at 60.00 percent or above is `THROTTLED`."

    PRD §3.10: "Under `THROTTLED`, the candidate is the same computation at 75
    percent instead of 90, likewise floored at 200 basis points. The programme's
    `max_acceptable_apr_bps` is then set to the smaller of its current value and
    that candidate."

    PRD §3.3: "When a row's `suppression_flag` is true, its invoice is created
    directly in `SUPPRESSED` with `dispute_suppressed` true, and the platform
    simultaneously raises a dispute on it with `reason_code`
    `BUYER_FILE_SUPPRESSION`, `status` `OPEN` and `disputed_amount_cents` equal
    to the full invoice face."

    Design: Difficulty/boundary_precision_check/adoption_rate_empty_denominator_and_inclusive_throttled_edge
    """
    ctx = fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={
            "legal_name": "Empty Denominator Buyer",
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
        },
        program_overrides={
            "name": "Mixed Programme",
            "program_type": "SUPPLIER_NAMED",
            "max_acceptable_apr_bps": 1200,
            "min_days_early": 5,
            "concentration_cap_pct": 100.00,
            "funding_policy": "SELF_ONLY",
        },
        supplier_overrides={
            "legal_name": "Sole Supplier",
            "remittance_email": "ar@sole.example",
            "identity_score": 97,
        },
        session_window=("2026-08-02T00:00:00Z", "2026-08-31T00:00:00Z"),
    )
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                invoice_number="SP-1",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=100_000,
                suppression_flag=True,
            ),
            f.payable_row(
                ctx.supplier_id,
                invoice_number="SP-2",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=100_000,
            ),
        ],
    )
    assert ctx.payable_file["suppressed_row_count"] == 1, (
        "suppressed_row_count counts exactly the flagged accepted rows, got {}".format(
            ctx.payable_file["suppressed_row_count"]
        )
    )

    fx.set_clock("2026-08-02T00:00:00Z")
    ctx.clock = "2026-08-02T00:00:00Z"
    by_number = {row["invoice_number"]: row for row in fx.load_invoices(ctx)}
    suppressed = by_number["SP-1"]
    payable = by_number["SP-2"]
    assert_invoice(suppressed, status="SUPPRESSED", dispute_suppressed=True)
    assert_invoice(payable, status="ELIGIBLE", dispute_suppressed=False)

    disputes = validate_success(
        api_client.list_invoice_disputes(
            suppressed["id"], make_buyer_admin_headers(ctx.buyer_id)
        )
    )
    assert len(disputes) == 1, (
        "ingestion raises exactly one dispute on a flagged row, got {}".format(
            len(disputes)
        )
    )
    assert disputes[0]["reason_code"] == "BUYER_FILE_SUPPRESSION"
    assert disputes[0]["status"] == "OPEN"
    assert disputes[0]["disputed_amount_cents"] == 100_000, (
        "a file-suppression dispute always carries the full face"
    )

    # Before anything is paid, the denominator is 1 rather than 2.
    before = _analytics(ctx, ctx.program_id)
    assert_analytics(
        before,
        eligible_invoice_count=1,
        adopted_invoice_count=0,
        adoption_rate_pct=0.00,
        rate_posture="DISCOVERY",
        weighted_avg_accepted_apr_bps=0,
        max_acceptable_apr_bps=1200,
    )
    assert before["eligible_invoice_count"] != 2, (
        "the SUPPRESSED invoice must not sit in the denominator"
    )

    offer = fx.name_offer(
        payable["id"],
        ctx.session_id,
        ctx.supplier_id,
        payable["version"],
        offered_apr_bps=1000,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    accepted = fx.accept_offer_as_buyer(offer["id"], ctx.buyer_id)
    payment = fx.reserve_payment(offer["id"], accepted["version"], ctx.buyer_id)

    fx.set_clock("2026-08-05T00:00:00Z")
    fx.execute_payment(payment["id"], ctx.buyer_id)
    fx.set_clock("2026-08-07T00:00:00Z")
    released = fx.confirm_settlement(payment["id"], ctx.buyer_id)
    assert_payment_axes(
        released, funding_status="RELEASED", settlement_status="CONFIRMED"
    )

    assert_invoice(
        fx.read_invoice(payable["id"], ctx.buyer_id),
        status="EARLY_PAID",
        accepted_apr_bps=1000,
        provisional_discount_cents=1556,
        final_discount_cents=1500,
        discount_true_up_cents=-56,
    )

    # One of one adopted is 100.00 percent, well past the inclusive 60.00 edge.
    after = _analytics(ctx, ctx.program_id)
    assert_analytics(
        after,
        eligible_invoice_count=1,
        adopted_invoice_count=1,
        adoption_rate_pct=100.00,
        rate_posture="THROTTLED",
        weighted_avg_accepted_apr_bps=1000,
        max_acceptable_apr_bps=750,
    )
    assert after["max_acceptable_apr_bps"] != 900, (
        "THROTTLED applies the 75 percent factor, not the OPTIMISED 90 percent"
    )
    assert after["max_acceptable_apr_bps"] != 1200, (
        "the ceiling must have tightened away from its configured 1200"
    )
    assert_program(
        _read_program(ctx, ctx.program_id),
        max_acceptable_apr_bps=750,
        rate_posture="THROTTLED",
        adoption_rate_pct=100.00,
        adopted_invoice_count=1,
        eligible_invoice_count=1,
    )

    # The suppressed invoice is still held out of both counts.
    assert_invoice(
        fx.read_invoice(suppressed["id"], ctx.buyer_id),
        status="SUPPRESSED",
        dispute_suppressed=True,
    )
