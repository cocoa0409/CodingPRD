"""Cost reconciliation and pricing-calculation tests.

Covers the final-vs-estimated tow cost (revised and held variants), the pinned
round-then-multiply-then-round overage regime, the capped-vs-full reimbursement
payout, and the ETA derivation. All expected values are pre-computed in the design
indices and asserted as literals.
"""
from test_helpers import (
    validate_success,
    setup_en_route_call, setup_claim_under_review, complete_call,
    create_call, set_clock, create_plan, create_member, create_provider,
    TEST_USERS,
)

OP = TEST_USERS["dispatch_operator_headers"]


# =========================================================================
# Queue A — dual_variant_calc
# =========================================================================
def test_final_cost_revised_on_completion_with_reported_miles(api):
    """PRD §3.8: "It recomputes `final_cost_cents` using `final_towed_miles` in place
    of the creation-time estimate, applying the identical base-plus-overage shape and
    the identical pinned rounding regime of §2.6 — overage mileage beyond the plan's
    `per_incident_mileage_cap_miles` (never below zero) rounded to three decimals,
    multiplied by `overage_rate_cents_per_mile`, rounded to whole cents — and sets
    `member_out_of_pocket_cents` equal to `final_cost_cents`."

    PLUS plan: cap=5mi, rate=200c/mi, TOW covered (no base fee). Completing with
    final_towed_miles=20 -> overage (20-5)=15 * 200 = 3000.

    Design: Difficulty/dual_variant_calc/final_service_cost_estimate_revised_vs_held_on_service_call
    """
    ctx = setup_en_route_call()
    data = complete_call(ctx["call"]["id"], ctx["provider"]["id"], final_towed_miles=20)
    assert data["status"] == "COMPLETED", f"expected COMPLETED, got {data['status']}"
    assert data["final_cost_cents"] == 3000, f"expected 3000, got {data['final_cost_cents']}"
    assert data["member_out_of_pocket_cents"] == 3000, \
        f"expected mooc 3000, got {data['member_out_of_pocket_cents']}"


def test_reimbursement_payout_capped_at_documented_cost(api):
    """PRD §3.10: "On approval the system sets `approved_amount_cents` to the smaller
    of the claimed amount and the linked call's `member_out_of_pocket_cents` — the
    over-claim is trimmed to the documented cost, while a claim at or below the
    documented cost is approved in full — subtracts `approved_amount_cents` from the
    member's `outstanding_balance_cents` as the compensating side of the balance
    invariant, and moves the claim to `APPROVED`."

    Documented cost is 3000 (final_towed_miles=20); an over-claim of 5000 is trimmed.

    Design: Difficulty/dual_variant_calc/reimbursement_payout_capped_vs_full_on_reimbursement_claim
    """
    ctx = setup_claim_under_review(claimed_amount_cents=5000, final_towed_miles=20)
    data = validate_success(api.approve_claim(ctx["claim"]["id"], OP))
    assert data["status"] == "APPROVED", f"expected APPROVED, got {data['status']}"
    assert data["approved_amount_cents"] == 3000, \
        f"over-claim should trim to 3000, got {data['approved_amount_cents']}"
    member = validate_success(api.get_member(ctx["member"]["id"], OP))
    assert member["outstanding_balance_cents"] == 0, \
        f"balance should net to 0, got {member['outstanding_balance_cents']}"


def test_final_cost_held_variant_when_miles_match_estimate(api):
    """PRD §3.8: "When `final_towed_miles` is omitted or equals `tow_distance_miles`,
    the final cost equals the earlier `estimated_cost_cents` and there is no
    reconciliation delta; when it differs, the final cost diverges from the estimate
    and that difference is what flows to the member's balance."

    The held variant on the SAME ServiceCall cost-accounting domain (contrasted with
    the revised variant above): omitting final_towed_miles leaves final_cost_cents at
    the at-creation estimate.

    Design: Difficulty/dual_variant_calc/final_service_cost_estimate_revised_vs_held_on_service_call
    """
    ctx = setup_en_route_call()
    estimate = ctx["call"]["estimated_cost_cents"]
    data = complete_call(ctx["call"]["id"], ctx["provider"]["id"], final_towed_miles=None)
    assert data["status"] == "COMPLETED", f"expected COMPLETED, got {data['status']}"
    assert data["final_cost_cents"] == estimate, \
        f"held variant: final {data['final_cost_cents']} should equal estimate {estimate}"
    assert data["member_out_of_pocket_cents"] == estimate, \
        f"mooc should equal held final cost {estimate}, got {data['member_out_of_pocket_cents']}"


def test_reimbursement_payout_full_when_claim_at_or_below_cost(api):
    """PRD §3.10: "On approval the system sets `approved_amount_cents` to the smaller
    of the claimed amount and the linked call's `member_out_of_pocket_cents` — the
    over-claim is trimmed to the documented cost, while a claim at or below the
    documented cost is approved in full"

    The full-reimbursement variant (claim 3000 == documented 3000): approved in full,
    netting the balance to 0.

    Design: Difficulty/dual_variant_calc/reimbursement_payout_capped_vs_full_on_reimbursement_claim
    """
    ctx = setup_claim_under_review(claimed_amount_cents=3000, final_towed_miles=20)
    data = validate_success(api.approve_claim(ctx["claim"]["id"], OP))
    assert data["status"] == "APPROVED", f"expected APPROVED, got {data['status']}"
    assert data["approved_amount_cents"] == 3000, \
        f"at-cost claim should approve in full (3000), got {data['approved_amount_cents']}"
    member = validate_success(api.get_member(ctx["member"]["id"], OP))
    assert member["outstanding_balance_cents"] == 0, \
        f"balance should net to 0, got {member['outstanding_balance_cents']}"


# =========================================================================
# Queue A — combinatorial_formula (nested rounding order)
# =========================================================================
def test_tow_overage_nested_rounding_round_then_multiply_then_round(api):
    """PRD §2.6: "first it determines the overage mileage (the towed distance beyond
    the plan's free allowance, never less than zero) and rounds that mileage to three
    decimal places using round-half-up; second it multiplies the rounded overage
    mileage by the plan's per-mile overage rate in cents; third it rounds that product
    to whole cents using round-half-up."

    cap=5, rate=200, final_towed_miles=12.3456 -> overage 7.3456 -> round3 7.346
    -> *200 = 1469.2 -> round 1469.

    Design: Difficulty/combinatorial_formula/tow_overage_nested_rounding_order_round_then_multiply_then_round
    """
    ctx = setup_en_route_call()
    data = complete_call(ctx["call"]["id"], ctx["provider"]["id"], final_towed_miles=12.3456)
    assert data["final_cost_cents"] == 1469, f"expected 1469, got {data['final_cost_cents']}"


def test_tow_overage_rounding_holds_estimate_to_final_consistency(api):
    """PRD §2.6: "This is a round-then-multiply-then-round sequence, and it must be
    applied in exactly this order — rounding the mileage before multiplying, never
    after — so that the estimated and final charges are reproducible to the cent."

    A second nested-rounding case driving final_towed_miles=20 (overage 15*200=3000)
    confirms the same pinned regime reproduces a whole-cent charge.

    Design: Difficulty/combinatorial_formula/tow_overage_nested_rounding_order_round_then_multiply_then_round
    """
    ctx = setup_en_route_call()
    data = complete_call(ctx["call"]["id"], ctx["provider"]["id"], final_towed_miles=20)
    assert data["final_cost_cents"] == 3000, f"expected 3000, got {data['final_cost_cents']}"


# =========================================================================
# Queue B — calculations
# =========================================================================
def test_offer_eta_minutes_is_ceil_of_distance_over_speed(api):
    """PRD §2.5: "`eta_minutes` is the offer distance in miles divided by an assumed
    average travel speed of 40 miles per hour, multiplied by 60 to convert hours to
    minutes, and then rounded up to the next whole minute."

    Provider at (0,0.10), breakdown (0,0): offer_distance 6.909mi ->
    ceil(6.909/40*60)=ceil(10.3635)=11.

    Design: Corner/calculations/offer_eta_minutes_ceil_of_distance_over_speed
    """
    set_clock()
    plan = create_plan()
    member = create_member(plan["id"])
    provider = create_provider(current_lat=0.0, current_lng=0.10)
    call = create_call(member["id"], "TOW")
    offer = validate_success(
        api.create_offer(call["id"], {"provider_id": provider["id"],
                                      "expected_service_call_version": call["version"]}, OP),
        201,
    )
    assert offer["eta_minutes"] == 11, f"expected eta 11, got {offer['eta_minutes']}"


def test_final_cost_holds_estimate_when_final_miles_omitted(api):
    """PRD §3.8: "When `final_towed_miles` is omitted or equals `tow_distance_miles`,
    the final cost equals the earlier `estimated_cost_cents` and there is no
    reconciliation delta; when it differs, the final cost diverges from the estimate
    and that difference is what flows to the member's balance."

    Design: Corner/calculations/final_cost_holds_estimate_when_final_miles_omitted
    """
    ctx = setup_en_route_call()
    estimate = ctx["call"]["estimated_cost_cents"]
    data = complete_call(ctx["call"]["id"], ctx["provider"]["id"], final_towed_miles=None)
    assert data["status"] == "COMPLETED", f"expected COMPLETED, got {data['status']}"
    assert data["final_cost_cents"] == estimate, \
        f"held variant: final {data['final_cost_cents']} should equal estimate {estimate}"
