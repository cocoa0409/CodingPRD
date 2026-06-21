"""Variable-rate interest accrual: chronological replay vs forward-projected payoff,
and the rounding-pinned waterfall feed (Queue A: dual_variant_calc, combinatorial_formula)."""
from test_helpers import (
    validate_success,
    setup_active_line,
    book_draw,
    set_clock,
    TEST_USERS,
)

SERVICER = TEST_USERS["loan_servicer_headers"]


def _line_for_accrual():
    """PRIME 850 + margin 150 -> APR 1000bps; credit_limit 50000000; activated DRAW."""
    ctx = setup_active_line(
        heloc_overrides={
            "credit_limit_cents": 50000000,
            "margin_bps": 150,
            "rate_ceiling_bps": 1800,
        }
    )
    return ctx


def test_chronological_accrual_two_staggered_draws(api):
    """PRD §3.5: "Walking from one event to the next, the running principal is held
    constant across the gap, and the interest for that segment is the running
    principal in cents multiplied by the daily rate multiplied by the number of days
    elapsed in the segment, rounded half up to whole cents."
    PRD §3.5: "The segment amounts are summed — each already rounded — to produce the
    accrued figure from the last-payment anchor up to the as-of clock, which is stored
    as accrued_interest_cents."

    Two staggered draws (200000 at 2026-01-01, 100000 at 2026-01-11), clock at
    2026-01-31, APR 1000bps -> accrued 2192.

    Design: Difficulty/dual_variant_calc/interest_accrual_chronological_vs_forward_payoff
    """
    ctx = _line_for_accrual()
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 200000)
    set_clock("2026-01-11T00:00:00Z")
    book_draw(hl_id, 100000)
    set_clock("2026-01-31T00:00:00Z")

    quote = validate_success(api.get_interest_quote(hl_id, SERVICER))
    assert quote["accrued_interest_cents"] == 2192, (
        f"expected 2192 chronological accrued, got {quote['accrued_interest_cents']}"
    )


def test_forward_payoff_projects_single_segment_on_current_principal(api):
    """PRD §3.5: "it projects accrual forward from now to that instant on the current
    running principal alone, assuming no intervening draws or payments — a single
    segment equal to current_balance_cents multiplied by the daily rate multiplied by
    the number of days from now to the as-of instant, rounded half up to whole cents."

    Same ledger (300000 principal) projected 30 days forward to 2026-03-02 -> 2466.

    Design: Difficulty/dual_variant_calc/interest_accrual_chronological_vs_forward_payoff
    """
    ctx = _line_for_accrual()
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 200000)
    set_clock("2026-01-11T00:00:00Z")
    book_draw(hl_id, 100000)
    set_clock("2026-01-31T00:00:00Z")

    payoff = validate_success(
        api.get_payoff_quote(hl_id, SERVICER, params={"as_of": "2026-03-02T00:00:00Z"})
    )
    assert payoff["projected_interest_cents"] == 2466, (
        f"expected 2466 forward-projected interest, got {payoff['projected_interest_cents']}"
    )


def test_chronological_and_forward_quotes_diverge(api):
    """PRD §3.5: "The contrast is intentional: the chronological quote reconstructs the
    historical accrual, while the payoff quote projects a single forward segment."

    Design: Difficulty/dual_variant_calc/interest_accrual_chronological_vs_forward_payoff
    """
    ctx = _line_for_accrual()
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 200000)
    set_clock("2026-01-11T00:00:00Z")
    book_draw(hl_id, 100000)
    set_clock("2026-01-31T00:00:00Z")

    chrono = validate_success(api.get_interest_quote(hl_id, SERVICER))
    payoff = validate_success(
        api.get_payoff_quote(hl_id, SERVICER, params={"as_of": "2026-03-02T00:00:00Z"})
    )
    assert (
        chrono["accrued_interest_cents"] != payoff["projected_interest_cents"]
    ), "chronological accrual must differ from forward-projected interest"


def test_payment_waterfall_consumes_rounded_summed_interest(api):
    """PRD §3.5: "interest is rounded half up once per inter-event segment and only
    then summed across segments — segments are never summed before rounding."
    PRD §3.6: "The remittance is then allocated across three buckets in a pinned order:
    outstanding fees first, then accrued interest, then principal."

    Single draw 200000 at 2026-01-01, clock 2026-01-31, APR 1000bps -> accrued 1644;
    a 10000 payment with no outstanding fees splits 0 fee / 1644 interest / 8356 principal.

    Design: Difficulty/combinatorial_formula/payment_waterfall_rounding_order_pinned
    """
    ctx = _line_for_accrual()
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 200000)
    set_clock("2026-01-31T00:00:00Z")

    payment = validate_success(api.create_payment(hl_id, {"amount_cents": 10000}, SERVICER), 201)
    assert payment["fee_applied_cents"] == 0
    assert payment["interest_applied_cents"] == 1644, (
        f"expected 1644 interest applied, got {payment['interest_applied_cents']}"
    )
    assert payment["principal_applied_cents"] == 8356, (
        f"expected 8356 principal applied, got {payment['principal_applied_cents']}"
    )


def test_payment_waterfall_buckets_conserve_remittance(api):
    """PRD §3.6: "The three buckets always sum exactly to amount_cents; the allocation
    is exact integer-cents arithmetic with no rounding."

    Design: Difficulty/combinatorial_formula/payment_waterfall_rounding_order_pinned
    """
    ctx = _line_for_accrual()
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 200000)
    set_clock("2026-01-31T00:00:00Z")

    payment = validate_success(api.create_payment(hl_id, {"amount_cents": 10000}, SERVICER), 201)
    total = (
        payment["fee_applied_cents"]
        + payment["interest_applied_cents"]
        + payment["principal_applied_cents"]
    )
    assert total == 10000, f"buckets must sum to 10000, got {total}"
