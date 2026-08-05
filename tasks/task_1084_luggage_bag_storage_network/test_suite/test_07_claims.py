"""Claims: the UNDER_REVIEW<->NEEDS_INFO revision loop, the coverage cap, the no-coverage
precondition, and the depth-3 approve cascade plus the provisional-vs-final payout net.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId,
    setup_completed_booking, file_claim, review_claim, get_only_payout,
    assert_payout_partition,
)

THREE_BAGS_ONE_OVERSIZE = [
    {"declared_value_cents": 20000, "dimension_sum_cm": 100},
    {"declared_value_cents": 20000, "dimension_sum_cm": 100},
    {"declared_value_cents": 20000, "dimension_sum_cm": 160},
]


# --- Revision loop -------------------------------------------------------------

def test_claim_needs_info_review_cycle_returns_to_under_review(api):
    """PRD §3.8: "This revision loop may repeat any number of times — a claim may cycle
    between `UNDER_REVIEW` and `NEEDS_INFO` freely — until an adjudication is reached."

    Design: Difficulty/non_linear_state_machine/claim_needs_info_review_cycle
    """
    ctx, booking, bags = setup_completed_booking(
        api, tier="PREMIUM", per_bag_coverage_cents=50000, premium_cents_per_bag_day=200,
        bags=[{"declared_value_cents": 40000, "dimension_sum_cm": 100}], seal_codes=["K1"],
        check_in_date="2026-06-10", check_out_date="2026-06-11")
    claim = file_claim(api, ctx, booking["id"], bags[0]["id"], reason="DAMAGE",
                       description="cracked", claimed_amount_cents=10000)
    review_claim(api, ctx, claim["id"])
    get_success_data(api.request_info_claim(claim["id"], ctx["admin_headers"]))
    get_success_data(api.resubmit_claim(claim["id"], ctx["traveler_headers"]))
    get_success_data(api.request_info_claim(claim["id"], ctx["admin_headers"]))
    final = get_success_data(api.resubmit_claim(claim["id"], ctx["traveler_headers"]))
    assert final["status"] == "UNDER_REVIEW"


def test_claim_request_info_enters_needs_info(api):
    """PRD §3.8: "From under review, the reviewer may request more information, transitioning
    `UNDER_REVIEW → NEEDS_INFO`."

    Design: Difficulty/non_linear_state_machine/claim_needs_info_review_cycle
    """
    ctx, booking, bags = setup_completed_booking(
        api, tier="PREMIUM", per_bag_coverage_cents=50000, premium_cents_per_bag_day=200,
        bags=[{"declared_value_cents": 40000, "dimension_sum_cm": 100}], seal_codes=["K1"],
        check_in_date="2026-06-10", check_out_date="2026-06-11")
    claim = file_claim(api, ctx, booking["id"], bags[0]["id"], reason="DAMAGE",
                       description="cracked", claimed_amount_cents=10000)
    review_claim(api, ctx, claim["id"])
    needs_info = get_success_data(api.request_info_claim(claim["id"], ctx["admin_headers"]))
    assert needs_info["status"] == "NEEDS_INFO"


# --- Coverage cap and no-coverage precondition --------------------------------

def test_claim_award_capped_to_declared_value(api):
    """PRD §3.8: "The approved amount is bounded by a coverage cap: the smallest of the
    plan's `per_bag_coverage_cents`, the bag's `declared_value_cents`, and the traveler's
    `claimed_amount_cents`. The supplied `approved_amount_cents` must be greater than zero
    and no more than that cap; an amount exceeding the cap is rejected with
    `ERR_COVERAGE_CAP_EXCEEDED`."

    Design: Corner/calculations/claim_award_capped_to_declared_value
    """
    ctx, booking, bags = setup_completed_booking(
        api, tier="PREMIUM", per_bag_coverage_cents=50000, premium_cents_per_bag_day=200,
        bags=[{"declared_value_cents": 10000, "dimension_sum_cm": 100}], seal_codes=["K0"],
        check_in_date="2026-06-10", check_out_date="2026-06-11")
    claim = file_claim(api, ctx, booking["id"], bags[0]["id"], reason="DAMAGE",
                       description="d", claimed_amount_cents=9000)
    review_claim(api, ctx, claim["id"])
    resp = api.decide_claim(claim["id"], {"decision": "APPROVE", "approved_amount_cents": 20000},
                            ctx["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_COVERAGE_CAP_EXCEEDED.value)


def test_claim_on_none_plan_returns_no_coverage(api):
    """PRD §3.8: "only when the booking's insurance plan tier is not `NONE`; a claim against
    an uninsured booking is rejected with `ERR_NO_INSURANCE_COVERAGE`."

    Design: Corner/validations/claim_on_none_plan_returns_no_coverage
    """
    ctx, booking, bags = setup_completed_booking(
        api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0,
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100}], seal_codes=["K0"],
        check_in_date="2026-06-10", check_out_date="2026-06-11")
    resp = api.create_claim(
        booking["id"],
        {"bag_id": bags[0]["id"], "reason": "DAMAGE", "description": "d", "claimed_amount_cents": 500},
        ctx["traveler_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_INSURANCE_COVERAGE.value)


# --- Dual variant: provisional net vs final net after a claim approval --------

def test_payout_provisional_net_before_claim(api):
    """PRD §3.7: "At creation, with no approved claim yet, the claim deduction is zero and
    the net is simply gross minus fee; this is the provisional net."

    Design: Difficulty/dual_variant_calc/payout_provisional_vs_final_net_after_claim
    """
    ctx, booking, bags = setup_completed_booking(
        api, platform_fee_bps=2000, tier="PREMIUM", per_bag_coverage_cents=50000,
        premium_cents_per_bag_day=200, bags=THREE_BAGS_ONE_OVERSIZE,
        seal_codes=["SL-0", "SL-1", "SL-2"],
        check_in_date="2026-06-10", check_out_date="2026-06-13", pickup_clock="2026-06-14")
    payout = get_only_payout(api, ctx)
    # gross 8400 (4500 + 900 + 3000 late), fee 1680, deduction 0, net 6720
    assert payout["gross_cents"] == 8400
    assert payout["claim_deduction_cents"] == 0
    assert payout["net_cents"] == 6720


def test_payout_final_net_after_claim_approval(api):
    """PRD §3.7: "After one or more claims on the booking are approved, the deduction grows
    and the net drops by that same sum — the same gross yielding a different, final net."
    PRD §3.8: "First, the payout whose booking matches the claim's booking has its
    `claim_deduction_cents` increased by the approved amount and its `net_cents` recomputed
    downward."

    Design: Difficulty/dual_variant_calc/payout_provisional_vs_final_net_after_claim
    """
    ctx, booking, bags = setup_completed_booking(
        api, platform_fee_bps=2000, tier="PREMIUM", per_bag_coverage_cents=50000,
        premium_cents_per_bag_day=200, bags=THREE_BAGS_ONE_OVERSIZE,
        seal_codes=["SL-0", "SL-1", "SL-2"],
        check_in_date="2026-06-10", check_out_date="2026-06-13", pickup_clock="2026-06-14")
    claim = file_claim(api, ctx, booking["id"], bags[0]["id"], reason="DAMAGE",
                       description="scuffed", claimed_amount_cents=2000)
    review_claim(api, ctx, claim["id"])
    get_success_data(api.decide_claim(
        claim["id"], {"decision": "APPROVE", "approved_amount_cents": 2000}, ctx["admin_headers"]))
    payout = get_only_payout(api, ctx)
    assert payout["claim_deduction_cents"] == 2000
    assert payout["net_cents"] == 4720             # 6720 - 2000
    assert_payout_partition(payout)


# --- Depth-3 cascade: approve -> payout -> host suspend -> location suspend ----

def test_claim_approve_drives_host_pending_negative_and_suspends(api):
    """PRD §3.8: "Second, the host's `pending_payout_cents` is reduced by the approved
    amount; if this drives the host's pending balance below zero, the system suspends the
    host, transitioning it `ACTIVE → SUSPENDED`."

    Design: Difficulty/transitive_cascade/claim_approve_payout_host_suspend_location_depth3
    """
    ctx, booking, bags = setup_completed_booking(
        api, platform_fee_bps=2000, tier="PREMIUM", per_bag_coverage_cents=50000,
        premium_cents_per_bag_day=200,
        bags=[{"declared_value_cents": 50000, "dimension_sum_cm": 100}], seal_codes=["K0"],
        check_in_date="2026-06-10", check_out_date="2026-06-11")
    claim = file_claim(api, ctx, booking["id"], bags[0]["id"], reason="LOSS",
                       description="lost bag", claimed_amount_cents=50000)
    review_claim(api, ctx, claim["id"])
    get_success_data(api.decide_claim(
        claim["id"], {"decision": "APPROVE", "approved_amount_cents": 50000}, ctx["admin_headers"]))
    payout = get_only_payout(api, ctx)
    assert payout["net_cents"] == -49600            # 500 - 100 - 50000
    host = get_success_data(api.get_host(ctx["host"]["id"], ctx["admin_headers"]))
    assert host["pending_payout_cents"] == -49600
    assert host["status"] == "SUSPENDED"


def test_claim_approve_cascades_location_suspension(api):
    """PRD §3.8: "Third, upon that host suspension, every location of the host currently in
    `OPEN` is transitioned to `SUSPENDED` by the system."

    Design: Difficulty/transitive_cascade/claim_approve_payout_host_suspend_location_depth3
    """
    ctx, booking, bags = setup_completed_booking(
        api, platform_fee_bps=2000, tier="PREMIUM", per_bag_coverage_cents=50000,
        premium_cents_per_bag_day=200,
        bags=[{"declared_value_cents": 50000, "dimension_sum_cm": 100}], seal_codes=["K0"],
        check_in_date="2026-06-10", check_out_date="2026-06-11")
    claim = file_claim(api, ctx, booking["id"], bags[0]["id"], reason="LOSS",
                       description="lost bag", claimed_amount_cents=50000)
    review_claim(api, ctx, claim["id"])
    get_success_data(api.decide_claim(
        claim["id"], {"decision": "APPROVE", "approved_amount_cents": 50000}, ctx["admin_headers"]))
    location = get_success_data(api.get_location(ctx["location"]["id"], ctx["admin_headers"]))
    assert location["status"] == "SUSPENDED"
