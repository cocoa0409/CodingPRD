"""Payments, derived balances, round-per-day late penalties, money conservation on
refund, and the payment OCC guard (queue A depth + queue B corner)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    resident_headers, code_officer_headers,
    assert_money_conservation,
)
from test_helpers import fixtures as fx


def _industrial_level1_citation(api, clock):
    """Clock -> INDUSTRIAL policy -> property -> WARNING then level-1 CITATION (7500)."""
    fx.set_clock(api, clock)
    fx.config_policy(api, "INDUSTRIAL", day_limit=75, night_limit=65)
    prop = fx.new_property(api, "INDUSTRIAL", address="4 Grind Way")
    fx.substantiate_once(api, prop["id"], "2026-06-01T12:00:00Z", 90, noise_type="MACHINERY")
    _, enf = fx.substantiate_once(api, prop["id"], "2026-06-01T13:00:00Z", 90, noise_type="MACHINERY")
    return enf


# --- Round-per-day-then-sum late penalty (queue A) ---

def test_late_penalty_rounds_each_day_before_summing(api):
    """PRD §3.7: "The per-day penalty is `effective_fine_cents` multiplied by 1.5% (0.015),
    rounded half up to whole cents. The total `late_penalty_cents` is that per-day penalty
    summed once for each overdue day — the per-day amount is rounded to whole cents **before**
    the days are summed, not after."

    Design: Difficulty/combinatorial_formula/late_penalty_round_per_day_then_sum_mode_b
    """
    enf = _industrial_level1_citation(api, "2026-06-01T00:00:00Z")
    assert enf["assessed_fine_cents"] == 7500
    fx.set_clock(api, "2026-07-03T00:00:00Z")  # due 2026-07-01 -> 2 overdue days
    fresh = fx.read_enforcement(api, enf["id"])
    assert fresh["effective_fine_cents"] == 7500
    assert fresh["late_penalty_cents"] == 226


def test_no_late_penalty_at_or_before_due_date(api):
    """PRD §3.7: "If the current clock is at or before `due_date`, `late_penalty_cents` is 0."

    Design: Difficulty/combinatorial_formula/late_penalty_round_per_day_then_sum_mode_b
    """
    enf = _industrial_level1_citation(api, "2026-06-01T00:00:00Z")
    fx.set_clock(api, "2026-07-01T00:00:00Z")  # exactly at due_date (issued + 30 days)
    fresh = fx.read_enforcement(api, enf["id"])
    assert fresh["late_penalty_cents"] == 0


# --- Money conservation on REDUCED refund (queue A) ---

def test_reduce_after_full_payment_reconciles_balance(api):
    """PRD §3.6: "If the payments already cleared exceed the new `effective_fine_cents` plus any
    `late_penalty_cents`, a refund row is created for exactly that surplus and the balance is
    recomputed."
    PRD §3.7: "The `amount_outstanding_cents` equals `effective_fine_cents` plus
    `late_penalty_cents` minus `amount_paid_cents`."

    Design: Difficulty/compensating_invariant/enforcement_money_conservation_on_reduce_refund
    """
    ctx = fx.setup_scheduled_hearing(api, zoning="COMMERCIAL", clock="2026-06-01T00:00:00Z",
                                     scheduled_at="2026-06-05T10:00:00Z")
    enf = fx.read_enforcement(api, ctx["enforcement"]["id"])
    validate_success(api.create_payment(enf["id"],
                     {"amount_cents": 15000, "expected_enforcement_version": enf["version"]},
                     resident_headers()), 201)
    fx.decide(api, ctx["hearing_id"], "REDUCED", deciding_user_id="hof-9", reduction_pct=0.25)
    fresh = fx.read_enforcement(api, enf["id"])
    assert fresh["effective_fine_cents"] == 11250
    assert fresh["amount_paid_cents"] == 11250
    assert fresh["amount_outstanding_cents"] == 0


def test_reduce_refund_row_and_money_conservation(api):
    """PRD §3.7: "The `amount_paid_cents` on an enforcement equals the sum of all cleared
    `PAYMENT` ledger rows minus the sum of all cleared `REFUND` ledger rows."
    PRD §3.6: "a refund row is created for exactly that surplus and the balance is recomputed."

    Design: Difficulty/compensating_invariant/enforcement_money_conservation_on_reduce_refund
    """
    ctx = fx.setup_scheduled_hearing(api, zoning="COMMERCIAL", clock="2026-06-01T00:00:00Z",
                                     scheduled_at="2026-06-05T10:00:00Z")
    enf = fx.read_enforcement(api, ctx["enforcement"]["id"])
    validate_success(api.create_payment(enf["id"],
                     {"amount_cents": 15000, "expected_enforcement_version": enf["version"]},
                     resident_headers()), 201)
    fx.decide(api, ctx["hearing_id"], "REDUCED", deciding_user_id="hof-9", reduction_pct=0.25)
    fresh = fx.read_enforcement(api, enf["id"])
    assert_money_conservation(fresh)
    rows, _ = validate_paginated(api.list_payments(enf["id"], code_officer_headers()))
    refunds = [r for r in rows if r["kind"] == "REFUND"]
    assert len(refunds) == 1
    assert refunds[0]["amount_cents"] == 3750


# --- Payment fiscal guard + OCC (queue B) ---

def test_payment_exceeding_outstanding_rejected(api):
    """PRD §3.7: "A payment whose `amount_cents` exceeds the current `amount_outstanding_cents`
    is rejected with `ERR_PAYMENT_EXCEEDS_OUTSTANDING`."

    Design: Corner/validations/payment_exceeds_outstanding_rejected
    """
    ctx = fx.setup_level1_citation(api, zoning="COMMERCIAL")
    enf = fx.read_enforcement(api, ctx["enforcement"]["id"])
    assert enf["amount_outstanding_cents"] == 15000
    resp = api.create_payment(enf["id"],
                              {"amount_cents": 20000, "expected_enforcement_version": enf["version"]},
                              resident_headers())
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING.value)


def test_stale_enforcement_version_payment_rejected(api):
    """PRD §2.8: "Recording a payment against a citation requires the request to carry
    `expected_enforcement_version` ... If that value does not match the enforcement's current
    `version` ... the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/payment_occ_stale_enforcement_version
    """
    ctx = fx.setup_level1_citation(api, zoning="COMMERCIAL")
    enf = fx.read_enforcement(api, ctx["enforcement"]["id"])
    ev = enf["version"]
    validate_success(api.create_payment(enf["id"],
                     {"amount_cents": 1000, "expected_enforcement_version": ev}, resident_headers()), 201)
    resp = api.create_payment(enf["id"],
                              {"amount_cents": 1000, "expected_enforcement_version": ev},
                              resident_headers())
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
