"""Commission, payment net-to-talent, and residual money math.

Covers the dual-variant commission calculation, the pinned-order payment net
rounding, the tiered SAG residual formula, and the escrow/zero-residual
boundary cases. Each test drives the full booking lifecycle from scratch.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    create_payment_payload,
    create_residual_schedule_payload,
    setup_paid_booking,
    setup_completed_booking,
)

AGENT = TEST_USERS["agent_headers"]


def _commission_entries(api, booking_id):
    resp = api.list_commission_entries(AGENT, params={"booking_id": booking_id})
    return validate_paginated(resp)


# ─── dual_variant_calc: provisional vs final commission ──────────────────────
def test_provisional_commission_is_forward_looking_on_quoted_gross(api):
    """PRD §3.6: "The provisional commission is the forward-looking variant,
    projected from that quoted gross fee before any money has moved: it is
    `gross_fee_cents` multiplied by the owning agency's `commission_rate_bps`,
    divided by the basis-point denominator of 10,000, with the result rounded
    half-up to whole cents."

    Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_diverges
    """
    base = setup_completed_booking(commission_rate_bps=1000)
    booking = base["booking"]
    # gross_fee = 200000/day * 5 inclusive days = 1000000; provisional 10% = 100000.
    assert booking["gross_fee_cents"] == 1000000
    assert booking["provisional_commission_cents"] == 100000


def test_final_commission_settles_on_actual_remitted_gross_diverging_from_provisional(api):
    """PRD §3.8: "The final commission is the chronological variant, settled on
    the actual remitted gross rather than the projected one: it is
    `gross_amount_cents` multiplied by the agency's `commission_rate_bps`,
    divided by 10,000, rounded half-up to whole cents, and recorded on the
    booking as `final_commission_cents`."
    PRD §3.8: "It differs from the provisional commission whenever the actual
    remitted gross differs from the quoted gross fee"

    Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_diverges
    """
    # Quoted gross 1000000 -> provisional 100000; actual remitted 1050000 -> final 105000.
    base = setup_completed_booking(commission_rate_bps=1000)
    booking_id = base["booking"]["id"]
    talent_id = base["talent"]["id"]

    pay_resp = api.create_payment(
        create_payment_payload(booking_id, talent_id, 1050000), AGENT
    )
    payment = validate_success(pay_resp, 201)
    assert payment["commission_withheld_cents"] == 105000

    booking = validate_success(api.get_booking(booking_id, AGENT), 200)
    assert booking["provisional_commission_cents"] == 100000
    assert booking["final_commission_cents"] == 105000
    assert booking["final_commission_cents"] != booking["provisional_commission_cents"]


# ─── combinatorial_formula: payment net rounding order ───────────────────────
def test_payment_net_rounds_each_component_before_subtracting(api):
    """PRD §3.8: "First, the `commission_withheld_cents` is computed as
    `gross_amount_cents` times the agency's `commission_rate_bps` divided by
    10,000, rounded half-up to whole cents."
    PRD §3.8: "Third, the `net_to_talent_cents` is the `gross_amount_cents`
    minus the already-rounded commission and minus the already-rounded
    pension-and-health contribution."

    Design: Difficulty/combinatorial_formula/payment_net_rounding_order_pinned
    """
    # SAG talent, gross 100002: commission round(100002*0.10)=10000,
    # P&H round(100002*0.185)=18500, net = 100002-10000-18500 = 71502.
    base = setup_completed_booking(
        union_status="SAG", commission_rate_bps=1000, media_type="BROADCAST_TV",
        usage_term_months=12, offer_day_rate_cents=100002,
        shoot_start_date="2026-03-15T00:00:00Z", shoot_end_date="2026-03-15T00:00:00Z",
        hold_start="2026-03-15T00:00:00Z", hold_end="2026-03-15T00:00:00Z",
        booking_start="2026-03-15T00:00:00Z", booking_end="2026-03-15T00:00:00Z",
        complete_clock="2026-03-16T00:00:00Z",
    )
    booking_id = base["booking"]["id"]
    talent_id = base["talent"]["id"]

    pay_resp = api.create_payment(
        create_payment_payload(booking_id, talent_id, 100002), AGENT
    )
    payment = validate_success(pay_resp, 201)
    assert payment["commission_withheld_cents"] == 10000
    assert payment["net_to_talent_cents"] == 71502


def test_non_union_payment_has_no_pension_health_contribution(api):
    """PRD §3.8: "a pension-and-health contribution is computed but only for a
    `SAG` talent ... for a `NON_UNION` talent this contribution is zero."

    Design: Difficulty/combinatorial_formula/payment_net_rounding_order_pinned
    """
    # NON_UNION gross 100002: commission 10000, P&H 0, net = 100002-10000 = 90002.
    base = setup_completed_booking(
        union_status="NON_UNION", commission_rate_bps=1000, media_type="BROADCAST_TV",
        usage_term_months=12, offer_day_rate_cents=100002,
        shoot_start_date="2026-03-15T00:00:00Z", shoot_end_date="2026-03-15T00:00:00Z",
        hold_start="2026-03-15T00:00:00Z", hold_end="2026-03-15T00:00:00Z",
        booking_start="2026-03-15T00:00:00Z", booking_end="2026-03-15T00:00:00Z",
        complete_clock="2026-03-16T00:00:00Z",
    )
    pay_resp = api.create_payment(
        create_payment_payload(base["booking"]["id"], base["talent"]["id"], 100002), AGENT
    )
    payment = validate_success(pay_resp, 201)
    assert payment["commission_withheld_cents"] == 10000
    assert payment["net_to_talent_cents"] == 90002


# ─── combinatorial_formula: SAG residual tiered/media/period ─────────────────
def test_sag_residual_period_one_full_media_multiplier(api):
    """PRD §3.9: "For a `SAG` talent the amount starts from the originating
    booking's `gross_fee_cents` as the base, scales it by the media multiplier
    keyed to the casting call's `media_type`, and then scales it again by a
    period-tier multiplier that decays as reruns accumulate."
    PRD §3.9: "`STREAMING` at 1500" and "10000 (full) when `period_index` is 1"

    Design: Difficulty/combinatorial_formula/sag_residual_tiered_media_period_nonlinear
    """
    # base 1000000 * STREAMING(1500bps) * period-1(10000bps) = 150000.
    base = setup_paid_booking(
        union_status="SAG", commission_rate_bps=1000, media_type="STREAMING",
        gross_amount_cents=1000000,
    )
    res_resp = api.create_residual_schedule(
        create_residual_schedule_payload(
            base["payment"]["id"], base["booking"]["id"], 1
        ),
        AGENT,
    )
    residual = validate_success(res_resp, 201)
    assert residual["residual_amount_cents"] == 150000


def test_sag_residual_period_three_decayed_multiplier_nonlinear(api):
    """PRD §3.9: "The period-tier multiplier, in basis points, is 10000 (full)
    when `period_index` is 1, 7500 when it is 2, 5000 when it is 3, and a flat
    2500 for any period of 4 or higher."

    Design: Difficulty/combinatorial_formula/sag_residual_tiered_media_period_nonlinear
    """
    # base 1000000 * STREAMING(1500bps) * period-3(5000bps) = 75000 (not linear).
    base = setup_paid_booking(
        union_status="SAG", commission_rate_bps=1000, media_type="STREAMING",
        gross_amount_cents=1000000,
    )
    res_resp = api.create_residual_schedule(
        create_residual_schedule_payload(
            base["payment"]["id"], base["booking"]["id"], 3
        ),
        AGENT,
    )
    residual = validate_success(res_resp, 201)
    assert residual["residual_amount_cents"] == 75000


# ─── boundary_precision: escrow equality release succeeds ────────────────────
def test_escrow_release_succeeds_at_exact_equality(api):
    """PRD §3.8: "The agency's escrow must also be sufficient to release the
    booking's held commission entry — the agency's `escrow_balance_cents` must
    be at least the `held_cents` being released, with equality allowed —
    otherwise the post is refused with `ERR_ESCROW_INSUFFICIENT`."

    Design: Difficulty/boundary_precision_check/escrow_release_exact_equality_succeeds
    """
    # NON_UNION, gross_fee 1000000 -> HELD 100000, escrow exactly 100000.
    base = setup_completed_booking(
        union_status="NON_UNION", commission_rate_bps=1000, media_type="STREAMING",
    )
    agency_id = base["agency"]["id"]
    booking_id = base["booking"]["id"]
    talent_id = base["talent"]["id"]

    before = validate_success(api.get_agency(agency_id, AGENT), 200)
    assert before["escrow_balance_cents"] == 100000

    pay_resp = api.create_payment(
        create_payment_payload(booking_id, talent_id, 1000000), AGENT
    )
    payment = validate_success(pay_resp, 201)
    assert payment["commission_withheld_cents"] == 100000

    after = validate_success(api.get_agency(agency_id, AGENT), 200)
    assert after["escrow_balance_cents"] == 0


def test_escrow_equality_release_settles_commission_entry(api):
    """PRD §3.8: "transitions the booking's commission entry from `HELD` to
    `RELEASED` (setting that entry's `earned_cents` to the final commission and
    its `held_cents` to zero), and reconciles the agency's `escrow_balance_cents`
    downward by the previously held amount."

    Design: Difficulty/boundary_precision_check/escrow_release_exact_equality_succeeds
    """
    # NON_UNION, gross_fee 1000000 -> HELD 100000, escrow exactly 100000; release
    # with actual gross 1000000 -> final commission 100000 earned, escrow to 0.
    base = setup_completed_booking(
        union_status="NON_UNION", commission_rate_bps=1000, media_type="STREAMING",
    )
    booking_id = base["booking"]["id"]
    talent_id = base["talent"]["id"]

    pay_resp = api.create_payment(
        create_payment_payload(booking_id, talent_id, 1000000), AGENT
    )
    validate_success(pay_resp, 201)

    entries, _meta = _commission_entries(api, booking_id)
    assert len(entries) >= 1
    entry = entries[0]
    assert entry["status"] == "RELEASED"
    assert entry["earned_cents"] == 100000
    assert entry["held_cents"] == 0


# ─── boundary_precision: zero residual pay rejected ──────────────────────────
def test_pay_zero_residual_rejected_at_zero_boundary(api):
    """PRD §3.9: "For a `NON_UNION` talent the residual amount is zero —
    non-union work pays no residuals."
    PRD §3.9: "A `DUE` residual can be paid, moving it to the terminal `PAID`
    state, but only when its `residual_amount_cents` is greater than zero; a
    residual with nothing due is refused with `ERR_NO_RESIDUAL_DUE`."

    Design: Difficulty/boundary_precision_check/residual_zero_amount_empty_boundary
    """
    base = setup_paid_booking(
        union_status="NON_UNION", commission_rate_bps=1000, media_type="STREAMING",
        gross_amount_cents=1000000,
    )
    residual = get_success_data(
        api.create_residual_schedule(
            create_residual_schedule_payload(
                base["payment"]["id"], base["booking"]["id"], 1
            ),
            AGENT,
        )
    )
    assert residual["residual_amount_cents"] == 0

    pay_resp = api.pay_residual_schedule(residual["id"], AGENT)
    validate_error(pay_resp, ApiErrorId.ERR_NO_RESIDUAL_DUE.value, 409)


def test_zero_residual_accrues_as_due_with_zero_amount(api):
    """PRD §3.9: "A new schedule is `DUE` with its `residual_amount_cents`
    computed at creation."
    PRD §3.9: "For a `NON_UNION` talent the residual amount is zero — non-union
    work pays no residuals."

    Design: Difficulty/boundary_precision_check/residual_zero_amount_empty_boundary
    """
    base = setup_paid_booking(
        union_status="NON_UNION", commission_rate_bps=1000, media_type="STREAMING",
        gross_amount_cents=1000000,
    )
    res_resp = api.create_residual_schedule(
        create_residual_schedule_payload(
            base["payment"]["id"], base["booking"]["id"], 1
        ),
        AGENT,
    )
    residual = validate_success(res_resp, 201)
    assert residual["status"] == "DUE"
    assert residual["residual_amount_cents"] == 0
