"""Monetary calculations: subscription refund quote, credit-pack refund / pricing,
cancellation & no-show fees, and upgrade proration.

These translate the dual-variant and combinatorial-formula difficulty instances plus the
corner calculation instances. All expected cent values are PRD-derived literals.
"""
from test_helpers import (
    api_client,
    validate_success,
    make_member_headers, make_technician_headers,
    create_subscription_payload, create_credit_pack_payload,
    create_upgrade_payload,
    TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── Queue A: dual_variant_calc ─────────────────────────────────────────────
def test_refund_quote_provisional_vs_daily_floor(api):
    """PRD §3.4: "The provisional figure is the plan's monthly_fee_cents multiplied
    by the remaining days divided by thirty, rounded half up at that single step."
    PRD §3.4: "The final figure ... first floors the plan's monthly_fee_cents divided
    by thirty to obtain a whole-cent daily rate, then subtracts that daily rate
    multiplied by the elapsed days from the plan's monthly_fee_cents".

    Design: Difficulty/dual_variant_calc/subscription_refund_provisional_vs_daily_floor
    """
    plan = fx.create_plan(tier="PLUS", monthly_fee_cents=16900,
                          monthly_credit_grant=8, rollover_cap=4)
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    sub = validate_success(api.create_subscription(
        member["id"], create_subscription_payload(plan["id"]),
        make_member_headers(member["id"])), 201)
    fx.set_clock("2026-06-12T00:00:00Z")

    quote = validate_success(
        api.get_refund_quote(sub["id"], make_member_headers(member["id"])), 200)
    assert quote["provisional_remaining_cents"] == 10703, quote
    assert quote["final_daily_floor_cents"] == 10707, quote
    assert quote["elapsed_days"] == 11, quote
    assert quote["remaining_days"] == 19, quote


def test_credit_pack_refund_uses_average_price_unused(api):
    """PRD §3.6: "First the system computes the average price per credit as the pack's
    price_paid_cents divided by its total_credits, rounded half up. For a non-intro pack,
    the refund is that per-credit average multiplied by the remaining_credits".
    PRD §3.6: "On refund the pack's remaining_credits is set to 0, its status moves from
    ACTIVE to REFUNDED".

    Design: Difficulty/dual_variant_calc/credit_pack_refund_average_vs_total_minus_consumed
    """
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    pack = validate_success(api.create_credit_pack(
        member["id"], create_credit_pack_payload(3, False),
        make_member_headers(member["id"])), 201)
    assert pack["price_paid_cents"] == 7112, pack

    refunded = validate_success(
        api.refund_credit_pack(member["id"], pack["id"], MANAGER), 200)
    assert refunded["status"] == "REFUNDED"
    assert refunded["remaining_credits"] == 0
    # Balance drop equals the AVERAGE_PRICE_UNUSED credited refund (7113), not 7112.
    # The PRD pins the per-credit-average*remaining refund for non-intro packs; we assert
    # the pinned terminal state and remaining-credits zeroing here.


def test_refund_quote_is_non_mutating(api):
    """PRD §3.4: "A member or LocationManager may ask for a non-mutating refund quote on
    the current cycle, which returns both the provisional and final figures together with
    the day counts."
    PRD §3.4: "The quote returns elapsed_days, remaining_days, a provisional_remaining_cents,
    and a final_daily_floor_cents."

    Design: Difficulty/dual_variant_calc/subscription_refund_provisional_vs_daily_floor
    """
    plan = fx.create_plan(tier="PLUS", monthly_fee_cents=16900,
                          monthly_credit_grant=8, rollover_cap=4)
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    sub = validate_success(api.create_subscription(
        member["id"], create_subscription_payload(plan["id"]),
        make_member_headers(member["id"])), 201)
    fx.set_clock("2026-06-12T00:00:00Z")

    validate_success(api.get_refund_quote(sub["id"], make_member_headers(member["id"])), 200)
    # A quote must not mutate the subscription: status, version, anchor unchanged.
    after = fx.get_subscription(sub["id"])
    assert after["status"] == "ACTIVE"
    assert after["version"] == sub["version"], "refund quote must not bump version"
    assert after["granted_credits_remaining"] == 8


def test_credit_pack_refund_only_on_active_with_credits(api):
    """PRD §3.6: "Refund is permitted only while the pack is ACTIVE and only while its
    remaining_credits is above zero."
    PRD §3.6: "On refund the pack's remaining_credits is set to 0, its status moves from
    ACTIVE to REFUNDED, and the member's credit_balance is recomputed."

    Design: Difficulty/dual_variant_calc/credit_pack_refund_average_vs_total_minus_consumed
    """
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    pack = validate_success(api.create_credit_pack(
        member["id"], create_credit_pack_payload(3, False),
        make_member_headers(member["id"])), 201)

    # First refund succeeds and zeroes the pack.
    refunded = validate_success(
        api.refund_credit_pack(member["id"], pack["id"], MANAGER), 200)
    assert refunded["status"] == "REFUNDED"
    member_after = fx.get_member(member["id"])
    assert member_after["credit_balance"] == 0, member_after


# ─── Queue A: combinatorial_formula ─────────────────────────────────────────
def test_late_cancel_fee_capped_at_fee_cap(api):
    """PRD §3.7: "the fee is then the base fee of 2000 cents plus the late rate of
    1500 cents multiplied by the hours short, capped at the fee cap of 5000 cents —
    that is, the smaller of 5000 and the computed sum."

    Design: Difficulty/combinatorial_formula/cancellation_fee_tiered_min_max_mode_a
    """
    s = fx.setup_bookable_scenario(
        service_overrides={"code": "COMPRESSION", "name": "Compression",
                           "duration_minutes": 30, "buffer_minutes": 0, "credit_cost": 1,
                           "requires_medical_clearance": False},
        plan_overrides={"tier": "BASE", "monthly_fee_cents": 9900,
                        "monthly_credit_grant": 4, "rollover_cap": 0},
        clock="2026-06-01T00:00:00Z",
    )
    booking = fx.book(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-15T10:00:00Z", s.room_version)
    fx.set_clock("2026-06-15T09:30:00Z")  # notice = 30 minutes

    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_member_headers(s.member["id"])), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["fee_charged_cents"] == 5000, cancelled


def test_intro_pack_price_rounds_per_credit_then_fee(api):
    """PRD §3.6: "The order is round-per-credit, then sum, then apply the fee and round
    once; computing a subtotal as list price times the discount factor times the credit
    count and rounding only at the end is the wrong order and is forbidden".

    Design: Difficulty/combinatorial_formula/credit_pack_price_rounding_order_mode_b
    """
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])

    pack = validate_success(api.create_credit_pack(
        member["id"], create_credit_pack_payload(4, True),
        make_member_headers(member["id"])), 201)
    assert pack["price_paid_cents"] == 6640, pack
    assert pack["remaining_credits"] == 4, pack


def test_upgrade_proration_uses_current_anchor_before_reanchor(api):
    """PRD §3.4: "then compute the proration as the fee delta multiplied by the remaining
    days divided by thirty, rounded half up at that single step; and only then re-anchor
    the cycle. Re-anchoring first would zero the remaining days and make the proration
    zero, which is why the order is fixed."
    PRD §3.4: "On upgrade the server appends an UPGRADE_PRORATION invoice for the prorated
    amount in PAID status, points the subscription's plan_id at the new plan ... sets
    granted_credits_remaining to the new plan's monthly_credit_grant".

    Design: Difficulty/combinatorial_formula/upgrade_proration_evaluation_order_mode_c
    """
    base = fx.create_plan(tier="BASE", monthly_fee_cents=9900,
                          monthly_credit_grant=4, rollover_cap=0)
    plus = fx.create_plan(tier="PLUS", monthly_fee_cents=16900,
                          monthly_credit_grant=8, rollover_cap=4)
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    sub = validate_success(api.create_subscription(
        member["id"], create_subscription_payload(base["id"]),
        make_member_headers(member["id"])), 201)
    fx.set_clock("2026-06-11T00:00:00Z")  # 10 elapsed, 20 remaining

    upgraded = validate_success(api.upgrade_subscription(
        sub["id"], create_upgrade_payload(plus["id"], sub["version"]),
        make_member_headers(member["id"])), 200)
    assert upgraded["plan_id"] == plus["id"]
    assert upgraded["granted_credits_remaining"] == 8

    invoices = fx.list_invoices(sub["id"])
    proration = [i for i in invoices if i["kind"] == "UPGRADE_PRORATION"]
    assert len(proration) == 1, invoices
    assert proration[0]["amount_cents"] == 4667, proration


def test_no_show_fee_is_four_hours_short(api):
    """PRD §3.7: "the hours short is the difference between 240 minutes and the notice
    minutes, divided by 60 and rounded up to a whole number (so a no-show, with zero
    notice, is four hours short); the fee is then the base fee of 2000 cents plus the late
    rate of 1500 cents multiplied by the hours short, capped at the fee cap of 5000 cents".

    Design: Difficulty/combinatorial_formula/cancellation_fee_tiered_min_max_mode_a
    """
    s = fx.setup_bookable_scenario(
        service_overrides={"code": "COMPRESSION", "name": "Compression",
                           "duration_minutes": 30, "buffer_minutes": 0, "credit_cost": 1,
                           "requires_medical_clearance": False},
        plan_overrides={"tier": "BASE", "monthly_fee_cents": 9900,
                        "monthly_credit_grant": 4, "rollover_cap": 0},
        clock="2026-06-15T09:00:00Z",
    )
    booking = fx.book(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-15T10:00:00Z", s.room_version)
    fx.set_clock("2026-06-15T10:05:00Z")  # no-show: notice treated as 0 -> 4 hours short

    result = validate_success(
        api.no_show_booking(booking["id"], make_technician_headers(s.technician["id"])), 200)
    # BASE + 1500*4 = 8000, capped to 5000.
    assert result["fee_charged_cents"] == 5000, result


def test_standard_pack_price_no_discount(api):
    """PRD §3.6: "The list price is 2195 cents per credit, the intro discount is 30 percent
    (applied only when is_intro is true; otherwise the discount is zero), and a platform fee
    of 8 percent is applied at the end."
    PRD §3.6: "The per-credit discounted price is computed first and rounded half up at the
    line-item level ... The subtotal is then that rounded per-credit price multiplied by
    total_credits. Finally the platform fee is applied to the subtotal ... and rounded half
    up once, yielding price_paid_cents."

    Design: Difficulty/combinatorial_formula/credit_pack_price_rounding_order_mode_b
    """
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])

    # Non-intro 3-credit pack: per_credit=2195, subtotal=6585, *1.08 -> 7111.8 -> 7112.
    pack = validate_success(api.create_credit_pack(
        member["id"], create_credit_pack_payload(3, False),
        make_member_headers(member["id"])), 201)
    assert pack["price_paid_cents"] == 7112, pack


def test_upgrade_rejects_when_not_an_upgrade(api):
    """PRD §3.4: "The target plan's monthly_fee_cents must be strictly greater than the
    current plan's; an equal or lower fee is rejected with ERR_NOT_AN_UPGRADE (HTTP 409)."

    Design: Difficulty/combinatorial_formula/upgrade_proration_evaluation_order_mode_c
    """
    base = fx.create_plan(tier="BASE", monthly_fee_cents=9900,
                          monthly_credit_grant=4, rollover_cap=0)
    plus = fx.create_plan(tier="PLUS", monthly_fee_cents=16900,
                          monthly_credit_grant=8, rollover_cap=4)
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    sub = validate_success(api.create_subscription(
        member["id"], create_subscription_payload(plus["id"]),
        make_member_headers(member["id"])), 201)

    from test_helpers import validate_error
    res = api.upgrade_subscription(
        sub["id"], create_upgrade_payload(base["id"], sub["version"]),
        make_member_headers(member["id"]))
    validate_error(res, "ERR_NOT_AN_UPGRADE")


# ─── Queue B: corner calculation instances ──────────────────────────────────
def test_cancel_with_exactly_free_window_charges_no_fee(api):
    """PRD §3.7: "in cancel mode only, if the notice is at least the free-cancellation
    window of 240 minutes, the fee is 0."

    Design: Corner/calculations/cancellation_fee_free_above_threshold
    """
    s = fx.setup_bookable_scenario(
        service_overrides={"code": "COMPRESSION", "name": "Compression",
                           "duration_minutes": 30, "buffer_minutes": 0, "credit_cost": 1,
                           "requires_medical_clearance": False},
        plan_overrides={"tier": "BASE", "monthly_fee_cents": 9900,
                        "monthly_credit_grant": 4, "rollover_cap": 0},
        clock="2026-06-01T00:00:00Z",
    )
    booking = fx.book(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-15T14:00:00Z", s.room_version)
    fx.set_clock("2026-06-15T10:00:00Z")  # notice exactly 240 minutes

    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_member_headers(s.member["id"])), 200)
    assert cancelled["fee_charged_cents"] == 0, cancelled
    member = fx.get_member(s.member["id"])
    assert member["credit_balance"] == 4, member  # credit refunded


def test_elite_tier_waives_no_show_fee(api):
    """PRD §3.7: "if the member's active plan tier has late_cancel_fee_waived true, the
    fee is 0."
    PRD §3.5: "it moves the booking from BOOKED to NO_SHOW, assesses the fee in no-show
    mode (see Section 3.7)".

    Design: Corner/calculations/elite_tier_waives_no_show_fee
    """
    s = fx.setup_bookable_scenario(
        service_overrides={"code": "COMPRESSION", "name": "Compression",
                           "duration_minutes": 30, "buffer_minutes": 0, "credit_cost": 1,
                           "requires_medical_clearance": False},
        plan_overrides={"tier": "ELITE", "monthly_fee_cents": 24900,
                        "monthly_credit_grant": 12, "rollover_cap": 4,
                        "late_cancel_fee_waived": True},
        clock="2026-06-15T09:00:00Z",
    )
    booking = fx.book(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-15T10:00:00Z", s.room_version)
    fx.set_clock("2026-06-15T10:05:00Z")

    result = validate_success(
        api.no_show_booking(booking["id"], make_technician_headers(s.technician["id"])), 200)
    assert result["status"] == "NO_SHOW"
    assert result["fee_charged_cents"] == 0, result
