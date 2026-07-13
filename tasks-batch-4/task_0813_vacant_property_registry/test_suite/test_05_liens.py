"""Lien recording, interest payoff variants, and principal-pool conservation.

Covers difficulty instances 1b/2b (accrued vs quoted payoff, round-per-day order),
9b (lien principal conservation) and corner foreclose-not-REO.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_registrant_headers, set_clock, get_property, setup_recorded_lien,
)

ADMIN = TEST_USERS["program_admin_headers"]


def _lien_at_100_days(api):
    """Record a lien (principal 30000, recorded_at 2026-03-06), then move the clock
    to 2026-06-14 (100 whole days) and return the refetched lien."""
    ctx = setup_recorded_lien(api, escalate_clock="2026-03-06T00:00:00Z",
                              base_fine_cents=30000, cure_period_days=5,
                              category="STRUCTURAL", severity_weight=9)
    set_clock(api, "2026-06-14T00:00:00Z")
    lien = validate_success(api.get_lien(ctx["lien"]["id"], ADMIN))
    return ctx, lien


# --- Difficulty 1b: accrued payoff variant ---------------------------------
def test_lien_accrued_payoff_rounds_each_day_then_sums(api):
    """PRD §3.6: "The authoritative `payoff_amount_cents` (the accrued variant)
    rounds each single day's interest to whole cents first — one day's interest is
    `principal_cents` times the daily rate, rounded half up — and then multiplies
    that rounded per-day interest by the number of days and adds it to
    `principal_cents`; this round-each-day-then-sum ordering is the pinned order."

    Design: Difficulty/dual_variant_calc/lien_accrued_vs_quoted_payoff
    """
    ctx, lien = _lien_at_100_days(api)
    assert lien["principal_cents"] == 30000
    assert lien["payoff_amount_cents"] == 30800


def test_lien_quoted_payoff_rounds_once_at_end(api):
    """PRD §3.6: "The informational `payoff_quoted_cents` (the quoted variant)
    instead multiplies the principal, the daily rate, and the whole number of days
    together, rounds that full-period interest half up exactly once, and adds it to
    `principal_cents`."

    Design: Difficulty/dual_variant_calc/lien_accrued_vs_quoted_payoff
    """
    _, lien = _lien_at_100_days(api)
    assert lien["payoff_quoted_cents"] == 30822


# --- Difficulty 2b: round-per-day-then-sum order matters -------------------
def test_lien_payoff_pinned_round_per_day_order(api):
    """PRD §3.6: "this round-each-day-then-sum ordering is the pinned order."

    Design: Difficulty/combinatorial_formula/lien_payoff_round_per_day_order
    """
    _, lien = _lien_at_100_days(api)
    assert lien["payoff_amount_cents"] == 30800


def test_lien_quoted_diverges_from_accrued_by_rounding_remainder(api):
    """PRD §3.6: "Because the accrued variant absorbs a rounding step every day
    while the quoted variant rounds only at the end, the two figures diverge by the
    accumulated per-day rounding remainder."

    Design: Difficulty/combinatorial_formula/lien_payoff_round_per_day_order
    """
    _, lien = _lien_at_100_days(api)
    assert lien["payoff_quoted_cents"] == 30822
    assert lien["payoff_quoted_cents"] > lien["payoff_amount_cents"]


# --- Difficulty 9b: lien principal-pool conservation -----------------------
def test_recording_lien_adds_principal_to_lien_balance(api):
    """PRD §2.6: "lien principal is conserved on the `lien_balance_cents` axis:
    recording a lien adds its `principal_cents` to the balance".
    PRD §3.6: "Recording the lien increases the property's `lien_balance_cents` by
    the new `principal_cents`, since a lien contributes to that balance only while
    `RECORDED`."

    Design: Difficulty/compensating_invariant/lien_principal_pool_conservation
    """
    ctx = setup_recorded_lien(api, escalate_clock="2026-03-06T00:00:00Z",
                              base_fine_cents=30000, cure_period_days=5,
                              category="STRUCTURAL", severity_weight=9)
    prop = get_property(api, ctx["property"]["id"])
    assert prop["lien_balance_cents"] == 30000


def test_paying_lien_removes_principal_from_lien_balance(api):
    """PRD §3.6: "The `Registrant` satisfies its own lien by paying it off: this
    requires the lien to be `RECORDED` (otherwise `ERR_INVALID_STATE`), moves it
    `RECORDED → SATISFIED`". Its principal "leaves the `RECORDED` pool, decreasing
    the property's `lien_balance_cents` by exactly that principal".

    Design: Difficulty/compensating_invariant/lien_principal_pool_conservation
    """
    ctx = setup_recorded_lien(api, escalate_clock="2026-03-06T00:00:00Z",
                              base_fine_cents=30000, cure_period_days=5,
                              category="STRUCTURAL", severity_weight=9)
    reg_id = ctx["registrant"]["id"]
    paid = validate_success(api.pay_lien(ctx["lien"]["id"], make_registrant_headers(reg_id)))
    assert paid["status"] == "SATISFIED"
    prop = get_property(api, ctx["property"]["id"])
    assert prop["lien_balance_cents"] == 0


# --- Corner: foreclose a lien while property is not REO --------------------
def test_foreclose_lien_when_property_not_reo_returns_error(api):
    """PRD §3.6: "a foreclosure attempt while the property's `foreclosure_status`
    is anything other than `REO` is rejected with `ERR_PROPERTY_NOT_REO`, a check
    evaluated only after the lien's state has been confirmed `RECORDED`."

    Design: Corner/validations/foreclose_lien_not_reo_returns_error
    """
    ctx = setup_recorded_lien(api, escalate_clock="2026-03-06T00:00:00Z",
                              base_fine_cents=30000, cure_period_days=5,
                              category="STRUCTURAL", severity_weight=9)
    resp = api.foreclose_lien(ctx["lien"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_REO.value)
