"""Free-look and short-rate refund calculations and the cancellation cascades (§3.5).

Covers difficulty rules dual_variant_calc (free-look vs short-rate refund),
boundary_precision_check (free-look window inclusive boundary), compensating_invariant
(free-look refund conserves net premium), and the corner short-rate / consistency instances.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_active_policy, set_clock, list_refunds_for_policy, get_policy,
    create_plan, create_traveler, create_quoted_policy, add_insured, record_payment,
    issue_policy, make_traveler_headers,
    TEST_USERS,
)

UNDERWRITER = TEST_USERS["underwriter_headers"]


# ─── dual_variant_calc: free-look full vs short-rate prorated ──────────────

def test_free_look_refund_returns_full_premium(api):
    """PRD §3.5: "the system auto-creates a refund of `refund_type` `FREE_LOOK` for the full
    `premium_cents` and immediately sets that refund's `status` to `COMPLETED`" ... "its
    `amount_cents` equals the policy's `premium_cents`."

    A BASIC policy premium 20000 cancelled inside the free-look window refunds the full 20000.

    Design: Difficulty/dual_variant_calc/premium_refund_free_look_full_vs_short_rate_prorated
    """
    active = setup_active_policy(
        plan_overrides={"tier": "BASIC", "base_rate_bps": 400, "free_look_days": 10},
        clock="2026-06-01T00:00:00Z",
    )
    set_clock("2026-06-05T00:00:00Z")
    policy = active["policy"]
    validate_success(api.free_look_cancel_policy(policy["id"], active["owner_headers"]), 200)
    refunds = list_refunds_for_policy(policy["id"])
    assert len(refunds) == 1, f"exactly one refund expected, got {len(refunds)}"
    assert refunds[0]["refund_type"] == "FREE_LOOK"
    assert refunds[0]["amount_cents"] == 20000, \
        f"free-look refund must be full premium 20000, got {refunds[0]['amount_cents']}"


def test_short_rate_refund_prorated_minus_admin_fee(api):
    """PRD §3.5: "the unearned premium is the floor of `premium_cents` times the quantity
    (coverage-period days minus elapsed days) divided by coverage-period days; and the refund
    `amount_cents` is the larger of zero and that unearned premium minus a flat short-rate
    administrative fee of 2500 cents."

    Premium 57000 (senior 76 + CFAR), issued 2026-06-01, trip_end 2026-07-01 -> coverage 30
    days; cancelled after free-look at 2026-06-13 -> elapsed 12 days;
    short-rate = max(0, floor(57000*(30-12)/30) - 2500) = max(0, 34200-2500) = 31700.

    Design: Difficulty/dual_variant_calc/premium_refund_free_look_full_vs_short_rate_prorated
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="STANDARD", base_rate_bps=600, senior_loading_bps=5000,
                       cfar_loading_bps=4000, free_look_days=10)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000,
                                  trip_start_at="2026-06-25T00:00:00Z",
                                  trip_end_at="2026-07-01T00:00:00Z", cfar_opted=True)
    add_insured(policy["id"], traveler["id"], age_at_departure=76, covered_trip_cost_cents=500000)
    record_payment(policy["id"], traveler["id"])
    issue_policy(policy["id"])
    set_clock("2026-06-13T00:00:00Z")
    headers = make_traveler_headers(traveler["id"])
    validate_success(api.cancel_policy(policy["id"], headers), 200)

    refreshed = get_policy(policy["id"])
    assert refreshed["premium_cents"] == 57000
    refunds = list_refunds_for_policy(policy["id"])
    assert len(refunds) == 1
    assert refunds[0]["refund_type"] == "SHORT_RATE"
    assert refunds[0]["amount_cents"] == 31700, \
        f"short-rate refund must be 31700, got {refunds[0]['amount_cents']}"


# ─── boundary_precision_check: free-look window inclusive boundary ─────────

def test_free_look_cancel_at_exact_window_end_accepted(api):
    """PRD §3.5: "It is admissible only while `coverage_status` is `ACTIVE` (else
    `ERR_INVALID_STATE`) and only while the current clock is at or before `free_look_ends_at`
    (else `ERR_FREE_LOOK_EXPIRED`)".
    PRD §3.3: "computes `free_look_ends_at` as `issued_at` plus the plan's `free_look_days`."

    Issued 2026-06-01, free_look_days 10 -> free_look_ends_at 2026-06-11; a free-look cancel at
    exactly 2026-06-11 is "at or before" the end and is accepted (full FREE_LOOK refund).

    Design: Difficulty/boundary_precision_check/free_look_window_inclusive_boundary_full_refund_at_exact_end
    """
    active = setup_active_policy(
        plan_overrides={"tier": "BASIC", "base_rate_bps": 400, "free_look_days": 10},
        clock="2026-06-01T00:00:00Z",
    )
    set_clock("2026-06-11T00:00:00Z")
    policy = active["policy"]
    updated = validate_success(
        api.free_look_cancel_policy(policy["id"], active["owner_headers"]), 200)
    assert updated["coverage_status"] == "CANCELLED"
    refunds = list_refunds_for_policy(policy["id"])
    assert len(refunds) == 1 and refunds[0]["refund_type"] == "FREE_LOOK"
    assert refunds[0]["amount_cents"] == 20000, \
        f"full free-look refund 20000 expected at exact boundary, got {refunds[0]['amount_cents']}"


def test_free_look_cancel_after_window_end_rejected(api):
    """PRD §3.5: "only while the current clock is at or before `free_look_ends_at` (else
    `ERR_FREE_LOOK_EXPIRED`)".

    One day past free_look_ends_at (2026-06-12, end was 2026-06-11) the free-look cancel is
    rejected with ERR_FREE_LOOK_EXPIRED — establishing the boundary is inclusive at the end.

    Design: Difficulty/boundary_precision_check/free_look_window_inclusive_boundary_full_refund_at_exact_end
    """
    active = setup_active_policy(
        plan_overrides={"tier": "BASIC", "base_rate_bps": 400, "free_look_days": 10},
        clock="2026-06-01T00:00:00Z",
    )
    set_clock("2026-06-12T00:00:00Z")
    policy = active["policy"]
    res = api.free_look_cancel_policy(policy["id"], active["owner_headers"])
    validate_error(res, "ERR_FREE_LOOK_EXPIRED")


# ─── compensating_invariant: free-look refund conserves net premium ────────

def test_free_look_refund_conserves_net_premium_collected(api):
    """PRD §3.3: "`payment_status` advances to `PAID`, `net_premium_collected_cents` is set
    equal to `premium_cents`".
    PRD §3.5: "`net_premium_collected_cents` is recomputed as `premium_cents` minus the sum of
    `amount_cents` across the policy's `COMPLETED` refunds."

    Premium 20000: record-payment sets net to 20000; the full free-look refund (20000) drives
    net_premium_collected_cents back to 0 (20000 - 20000).

    Design: Difficulty/compensating_invariant/free_look_refund_conserves_net_premium_collected
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="BASIC", base_rate_bps=400, free_look_days=10)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000)
    add_insured(policy["id"], traveler["id"], covered_trip_cost_cents=500000)
    paid = record_payment(policy["id"], traveler["id"])
    assert paid["premium_cents"] == 20000
    assert paid["net_premium_collected_cents"] == 20000, \
        "net_premium_collected_cents must equal premium_cents after record-payment"
    issue_policy(policy["id"])
    set_clock("2026-06-05T00:00:00Z")
    headers = make_traveler_headers(traveler["id"])
    after = validate_success(api.free_look_cancel_policy(policy["id"], headers), 200)
    assert after["net_premium_collected_cents"] == 0, \
        "net_premium_collected_cents must return to 0 after the full free-look refund completes"


def test_free_look_refund_drives_payment_status_refunded(api):
    """PRD §3.5: "because a completed refund now exists, the policy's `payment_status` advances
    to `REFUNDED`".

    A complementary view of conserved-premium invariant: the free-look cascade flips
    payment_status PAID -> REFUNDED alongside the net-premium recomputation.

    Design: Difficulty/compensating_invariant/free_look_refund_conserves_net_premium_collected
    """
    active = setup_active_policy(
        plan_overrides={"tier": "BASIC", "base_rate_bps": 400, "free_look_days": 10},
        clock="2026-06-01T00:00:00Z",
    )
    set_clock("2026-06-05T00:00:00Z")
    policy = active["policy"]
    after = validate_success(
        api.free_look_cancel_policy(policy["id"], active["owner_headers"]), 200)
    assert after["payment_status"] == "REFUNDED", \
        "payment_status must be REFUNDED after the free-look refund completes"


# ─── Corner: short-rate derived field & immediate consistency ──────────────

def test_short_rate_refund_amount_after_cancel(api):
    """PRD §3.5: "the unearned premium is the floor of `premium_cents` times the quantity
    (coverage-period days minus elapsed days) divided by coverage-period days; and the refund
    `amount_cents` is the larger of zero and that unearned premium minus a flat short-rate
    administrative fee of 2500 cents."

    Premium 20000, issued 2026-06-01, trip_end 2026-07-01 (coverage 30 days), free_look_days 3,
    cancelled at 2026-06-06 (elapsed 5 days): max(0, floor(20000*(30-5)/30) - 2500) =
    max(0, 16666 - 2500) = 14166.

    Design: Corner/cross_cutting_complexity_layers/short_rate_refund_derived_field_correct_after_cancel
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="BASIC", base_rate_bps=400, free_look_days=3)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000,
                                  trip_start_at="2026-06-25T00:00:00Z",
                                  trip_end_at="2026-07-01T00:00:00Z")
    add_insured(policy["id"], traveler["id"], covered_trip_cost_cents=500000)
    record_payment(policy["id"], traveler["id"])
    issue_policy(policy["id"])
    set_clock("2026-06-06T00:00:00Z")
    headers = make_traveler_headers(traveler["id"])
    validate_success(api.cancel_policy(policy["id"], headers), 200)
    refunds = list_refunds_for_policy(policy["id"])
    assert len(refunds) == 1 and refunds[0]["refund_type"] == "SHORT_RATE"
    assert refunds[0]["amount_cents"] == 14166, \
        f"short-rate refund must be 14166, got {refunds[0]['amount_cents']}"


def test_refund_complete_immediately_reflects_payment_refunded(api):
    """PRD §3.5: "On completion the refund's `status` becomes `COMPLETED`, and as a cascade the
    policy's `payment_status` advances to `REFUNDED` while `net_premium_collected_cents` is
    recomputed as `premium_cents` minus the sum of `amount_cents` across the policy's
    `COMPLETED` refunds".

    Short-rate refund 14166 on premium 20000: completing it immediately yields
    payment_status REFUNDED and net_premium_collected_cents 20000-14166 = 5834.

    Design: Corner/consistency_model/refund_complete_immediately_reflects_payment_refunded
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="BASIC", base_rate_bps=400, free_look_days=3)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000,
                                  trip_start_at="2026-06-25T00:00:00Z",
                                  trip_end_at="2026-07-01T00:00:00Z")
    add_insured(policy["id"], traveler["id"], covered_trip_cost_cents=500000)
    record_payment(policy["id"], traveler["id"])
    issue_policy(policy["id"])
    set_clock("2026-06-06T00:00:00Z")
    headers = make_traveler_headers(traveler["id"])
    validate_success(api.cancel_policy(policy["id"], headers), 200)
    refunds = list_refunds_for_policy(policy["id"])
    refund_id = refunds[0]["id"]
    completed = validate_success(api.complete_refund(refund_id, UNDERWRITER), 200)
    assert completed["status"] == "COMPLETED"
    refreshed = get_policy(policy["id"])
    assert refreshed["payment_status"] == "REFUNDED"
    assert refreshed["net_premium_collected_cents"] == 5834, \
        f"net_premium_collected_cents must be 20000-14166=5834, got {refreshed['net_premium_collected_cents']}"
