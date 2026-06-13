"""Promotional-window expiry, retroactive deferred interest, and the promo boundary.

Queue A (Difficulty) — dual_variant_calc / deferred_interest_chronological_vs_forward_projection,
                       transitive_cascade / promo_expiry_depth2_purchase_forfeit_account_balance,
                       boundary_precision_check / promo_payoff_strictly_before_vs_at_promo_end,
                       non_linear_state_machine / financed_purchase_parallel_settlement_and_promo_axes.
"""
import pytest
from test_helpers import (
    validate_success,
    TEST_USERS,
    make_patient_headers,
    set_clock,
    advance_clock,
    create_authorized_purchase,
    post_payment,
)

ADMIN = TEST_USERS["admin_headers"]


# ──────────── Queue A: deferred_interest chronological vs forward projection ────────────
def test_deferred_interest_chronological_posted_after_midwindow_payment(api):
    """PRD §3.8: "The posted interest is the **chronological actual** amount: interest
    accrues retroactively on the actual outstanding principal as it was reduced day by day
    by real payments, walked from `promo_start` through `promo_end` at the daily
    promotional rate."
    PRD §3.8: "Beginning with the outstanding principal equal to the full `principal_cents`
    and the previous timestamp at `promo_start`, the rule processes each event in turn: it
    adds to the accrual the outstanding principal multiplied by the daily rate multiplied
    by the whole number of days from the previous timestamp up to (but not including) this
    event's time, then reduces the outstanding principal by the principal applied at this
    event".

    Principal 1,000,000, apr 0.2699, 400,000 paid at 2026-07-01, promo_end 2027-01-01 →
    posted chronological forfeit 218469.

    Design: Difficulty/dual_variant_calc/deferred_interest_chronological_vs_forward_projection
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=1_000_000, promo_apr=0.2699, deferred_period_months=12,
        requested_limit_cents=2_000_000, income_cents=6_000_000)
    set_clock("2026-07-01T00:00:00Z")
    post_payment(account, 400_000, "MANUAL")
    advance_clock("2027-01-01T00:00:00Z")
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    assert fp["promo_status"] == "INTEREST_FORFEITED"
    assert fp["deferred_interest_posted_cents"] == 218_469


def test_forward_projection_exceeds_chronological_actual(api):
    """PRD §3.8: "It assumes no further payments after the projection instant: it charges
    the full `promo_apr` against the entire remaining `principal_cents` for the whole
    window still remaining. Because it ignores the principal reductions that real payments
    would make, the projected figure is always greater than or equal to the
    chronological-actual interest the same purchase would actually forfeit."

    After the 400,000 payment the projection at 2026-07-01 reports 82769, while the posted
    chronological forfeit is 218469; the projection ignores future principal reductions and
    so the forward figure computed at promo_start (273649) exceeds the chronological 218469.

    Design: Difficulty/dual_variant_calc/deferred_interest_chronological_vs_forward_projection
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=1_000_000, promo_apr=0.2699, deferred_period_months=12,
        requested_limit_cents=2_000_000, income_cents=6_000_000)
    set_clock("2026-07-01T00:00:00Z")
    post_payment(account, 400_000, "MANUAL")
    proj = validate_success(
        api.get_payoff_projection(purchase["id"], make_patient_headers(account["id"])), 200)
    assert proj["projected_forfeit_interest_cents"] == 82_769

    advance_clock("2027-01-01T00:00:00Z")
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    # Posted chronological forfeit is strictly less than the full-window forward figure.
    assert fp["deferred_interest_posted_cents"] == 218_469
    assert fp["deferred_interest_posted_cents"] < 273_649


# ──────────── Queue A: promo_expiry depth-2 cascade ────────────
def test_promo_expiry_forfeits_interest_and_posts_to_balance(api):
    """PRD §3.8: "Forfeiture fires when an operator advances the clock past a purchase's
    `promo_end` while the purchase is still `DEFERRED`, its `principal_paid_cents` is below
    its `principal_cents`, and its settlement status is neither `REFUNDED` nor `VOID`."
    PRD §3.8: "On forfeiture the purchase's promotional axis moves
    `DEFERRED → INTEREST_FORFEITED`, the computed retroactive interest is written to
    `deferred_interest_posted_cents`, and that same amount is added to the account's
    `current_balance_cents`."

    Purchase 600,000 never paid forfeits 164189; account balance becomes 764189.

    Design: Difficulty/transitive_cascade/promo_expiry_depth2_purchase_forfeit_account_balance
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=600_000, promo_apr=0.2699, deferred_period_months=12,
        requested_limit_cents=1_000_000)
    advance_clock("2027-01-01T00:00:00Z")
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    assert fp["promo_status"] == "INTEREST_FORFEITED"
    assert fp["deferred_interest_posted_cents"] == 164_189
    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert acct["current_balance_cents"] == 764_189


def test_promo_expiry_reports_forfeited_purchase_id(api):
    """PRD §3.11: "To fire expiries, a `PlatformAdmin` advances the clock to a supplied
    `to_iso8601`, which moves the clock forward and, for every `DEFERRED` purchase whose
    `promo_end` falls at or before the new clock and whose principal is not fully paid,
    performs the forfeiture of §3.8; the advance reports the `current_utc` and the list of
    `forfeited_purchase_ids`."

    Design: Difficulty/transitive_cascade/promo_expiry_depth2_purchase_forfeit_account_balance
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=600_000, promo_apr=0.2699, deferred_period_months=12,
        requested_limit_cents=1_000_000)
    advance_body = advance_clock("2027-01-01T00:00:00Z")
    assert purchase["id"] in advance_body["forfeited_purchase_ids"]


# ──────────── Queue A: boundary precision — payoff strictly before promo_end ────────────
def test_payoff_strictly_before_promo_end_yields_paid_in_full(api):
    """PRD §3.4: "If a payment drives a purchase's `principal_paid_cents` up to its full
    `principal_cents` while the promotional axis is still `DEFERRED` and the current clock
    is strictly before `promo_end`, the purchase's promotional axis flips
    `DEFERRED → PAID_IN_FULL`, and no deferred interest is ever posted for that purchase."

    Paying 100,000 in full at 2026-12-31 (strictly before promo_end 2027-01-01) yields
    PAID_IN_FULL with zero interest even after the clock advances past promo_end.

    Design: Difficulty/boundary_precision_check/promo_payoff_strictly_before_vs_at_promo_end
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000, promo_apr=0.2699, deferred_period_months=12)
    set_clock("2026-12-31T00:00:00Z")
    post_payment(account, 100_000, "PAYOFF")
    advance_clock("2027-01-01T00:00:00Z")
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    assert fp["promo_status"] == "PAID_IN_FULL"
    assert fp["deferred_interest_posted_cents"] == 0


def test_unpaid_at_promo_end_forfeits_interest(api):
    """PRD §3.8: "A purchase whose principal is not fully paid by `promo_end` forfeits its
    interest. Forfeiture fires when an operator advances the clock past a purchase's
    `promo_end` while the purchase is still `DEFERRED`, its `principal_paid_cents` is below
    its `principal_cents`".

    The boundary's other side: reaching clock ≥ promo_end with unpaid principal forfeits
    rather than flipping PAID_IN_FULL.

    Design: Difficulty/boundary_precision_check/promo_payoff_strictly_before_vs_at_promo_end
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000, promo_apr=0.2699, deferred_period_months=12)
    advance_clock("2027-01-01T00:00:00Z")
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    assert fp["promo_status"] == "INTEREST_FORFEITED"
    assert fp["deferred_interest_posted_cents"] > 0


# ──────────── Queue A: parallel settlement and promo axes ────────────
def test_settle_advances_settlement_axis_only(api):
    """PRD §3.3: "On success the purchase is created on two independent state axes carried
    in two separate fields: its settlement axis, held in `settlement_status`, starts
    `AUTHORIZED`, and its promotional axis, held in `promo_status`, starts `DEFERRED`."
    PRD §3.5: "The settle transition sets the purchase's settlement axis to `SETTLED` and
    bumps the purchase's `version`."

    Settling moves settlement_status AUTHORIZED→SETTLED and leaves promo_status DEFERRED.

    Design: Difficulty/non_linear_state_machine/financed_purchase_parallel_settlement_and_promo_axes
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000, promo_apr=0.2699, deferred_period_months=12,
        requested_limit_cents=1_000_000)
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    validate_success(api.settle_financed_purchase(
        fp["id"], {"expected_financed_purchase_version": fp["version"]}, ADMIN), 201)
    after = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    assert after["settlement_status"] == "SETTLED"
    assert after["promo_status"] == "DEFERRED"


def test_payoff_advances_promo_axis_only(api):
    """PRD §3.4: "If a payment drives a purchase's `principal_paid_cents` up to its full
    `principal_cents` while the promotional axis is still `DEFERRED` and the current clock
    is strictly before `promo_end`, the purchase's promotional axis flips
    `DEFERRED → PAID_IN_FULL`".
    PRD §3.5: "The settle transition sets the purchase's settlement axis to `SETTLED`".

    After settling then paying in full, promo_status is PAID_IN_FULL while settlement_status
    stays SETTLED — the two axes advance independently on one row.

    Design: Difficulty/non_linear_state_machine/financed_purchase_parallel_settlement_and_promo_axes
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000, promo_apr=0.2699, deferred_period_months=12,
        requested_limit_cents=1_000_000)
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    validate_success(api.settle_financed_purchase(
        fp["id"], {"expected_financed_purchase_version": fp["version"]}, ADMIN), 201)
    post_payment(account, 100_000, "MANUAL")
    after = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    assert after["promo_status"] == "PAID_IN_FULL"
    assert after["settlement_status"] == "SETTLED"
