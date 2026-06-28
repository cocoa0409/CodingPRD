"""Booking pricing: forward-looking quote vs chronological charge, peak multiplier,
tiered discount, machine surcharge, party add-on, per-component rounding, token cost.

Covers Difficulty rules dual_variant_calc and combinatorial_formula, plus the
calculations corner instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_member_headers,
    setup_member_ready,
    create_facility,
    create_lane,
    create_machine,
    create_instructor,
    create_member,
    sign_waiver,
    top_up,
    request_booking,
    lane_version,
)

MANAGER = {"X-User-ID": "test-manager-1", "X-User-Role": "FacilityManager", "Content-Type": "application/json"}
FRONT_DESK = {"X-User-ID": "test-frontdesk-1", "X-User-Role": "FrontDesk", "Content-Type": "application/json"}


# ─── dual_variant_calc / booking_quote_vs_charge_diverge_on_peak ───────────────

def test_peak_charge_exceeds_quote_for_hourly_open_slot(api):
    """PRD §3.5: "Because the quote never applies the peak multiplier, a peak-hour
    hourly or token booking ends with final_cost_cents greater than its quoted_cost_cents".
    PRD §3.5: "a start at or after 1020 minutes (17:00 UTC) and strictly before 1260
    minutes (21:00 UTC) is a peak booking, and the peak multiplier is 1.5".

    Design: Difficulty/dual_variant_calc/booking_quote_vs_charge_diverge_on_peak
    """
    facility, lane, member = setup_member_ready(
        facility_overrides={"hourly_rate_cents": 4000, "token_price_cents": 500},
        lane_overrides={"kind": "CAGE", "buffer_minutes": 0},
        tier="NONE", waiver=True, tokens=100,
    )
    booking = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "HOURLY",
        "2026-04-02T17:30:00Z", "2026-04-02T18:30:00Z",
    )
    assert booking["quoted_cost_cents"] == 4000, "off-peak-style quote ignores peak"

    ver = lane_version(lane["id"])
    res = api.confirm_booking(
        booking["id"], {"expected_lane_version": ver}, make_member_headers(member["id"])
    )
    confirmed = validate_success(res, 200)
    assert confirmed["final_cost_cents"] == 6000, "peak charge = 4000 * 1.5"
    assert confirmed["final_cost_cents"] > confirmed["quoted_cost_cents"]


def test_quoted_cost_stamped_at_request_uses_lane_rate(api):
    """PRD §3.4: "it places the booking in REQUESTED status and stamps a provisional
    quoted_cost_cents using the forward-looking quote."
    PRD §3.4: "The forward-looking nature of the quote means it reads the lane rate,
    the member's tier, and the machine's model tier exactly as they stand at request
    time, and it never applies the peak-hour surcharge described in §3.5."

    Design: Difficulty/dual_variant_calc/booking_quote_vs_charge_diverge_on_peak
    """
    facility, lane, member = setup_member_ready(
        facility_overrides={"hourly_rate_cents": 4000, "token_price_cents": 500},
        tier="NONE", waiver=True, tokens=100,
    )
    booking = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "HOURLY",
        "2026-04-02T17:30:00Z", "2026-04-02T18:30:00Z",
    )
    # 60-min booking, lane rate 4000/hr, tier NONE: quote never applies peak -> 4000.
    assert booking["quoted_cost_cents"] == 4000
    assert booking["status"] == "REQUESTED"


# ─── combinatorial_formula / charge_three_input_nonlinear_lesson_gold_arm_peak ──

def test_charge_combines_peak_tier_and_machine_surcharge(api):
    """PRD §3.5: "The lane portion is the base lane rate multiplied by the hours, by
    the lane_count, and by the peak multiplier, rounded half-up to whole cents."
    PRD §3.5: "the membership-tier discount fraction (0, one-tenth, or one-quarter)
    is applied, and final_cost_cents is the discounted gross rounded half-up once to
    whole cents."

    Design: Difficulty/combinatorial_formula/charge_three_input_nonlinear_lesson_gold_arm_peak
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    machine = create_machine(facility["id"], lane["id"], model="ARM")
    instructor = create_instructor(facility["id"], rate_cents_per_hour=6000)
    member = create_member(facility["id"], tier="GOLD")
    sign_waiver(facility["id"], member["id"])
    top_up(member["id"], 100)

    booking = request_booking(
        facility, lane["id"], member, "LESSON", "TOKEN",
        "2026-04-02T17:30:00Z", "2026-04-02T19:00:00Z",
        instructor_id=instructor["id"], machine_id=machine["id"],
    )
    ver = lane_version(lane["id"])
    res = api.confirm_booking(
        booking["id"], {"expected_lane_version": ver}, make_member_headers(member["id"])
    )
    confirmed = validate_success(res, 200)
    # 90-min: lane 4000*1.5h*1.5peak=9000; coach 6000*1.5=9000; ARM=1200; gross 19200;
    # GOLD 0.25 discount -> 19200*0.75=14400.
    assert confirmed["final_cost_cents"] == 14400


def test_lesson_token_cost_ceils_from_final_cost(api):
    """PRD §3.5: "the booking's token_cost is the final_cost_cents divided by the
    facility's token_price_cents, rounded up to the next whole token — and for any
    booking whose final_cost_cents is above zero the token cost is never less than 1".

    Design: Difficulty/combinatorial_formula/charge_three_input_nonlinear_lesson_gold_arm_peak
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    machine = create_machine(facility["id"], lane["id"], model="ARM")
    instructor = create_instructor(facility["id"], rate_cents_per_hour=6000)
    member = create_member(facility["id"], tier="GOLD")
    sign_waiver(facility["id"], member["id"])
    top_up(member["id"], 100)

    booking = request_booking(
        facility, lane["id"], member, "LESSON", "TOKEN",
        "2026-04-02T17:30:00Z", "2026-04-02T19:00:00Z",
        instructor_id=instructor["id"], machine_id=machine["id"],
    )
    ver = lane_version(lane["id"])
    res = api.confirm_booking(
        booking["id"], {"expected_lane_version": ver}, make_member_headers(member["id"])
    )
    confirmed = validate_success(res, 200)
    # ceil(14400 / 500) = 29 tokens.
    assert confirmed["token_cost"] == 29


# ─── combinatorial_formula / charge_rounding_order_per_component_then_sum ───────

def test_rounding_is_per_component_then_sum(api):
    """PRD §2.10: "each component (the lane portion, the coaching portion, the machine
    surcharge, and the party portion) is rounded to whole cents first, the rounded
    components are summed into a gross amount". PRD §2.10: "Rounding the summed total
    in a single step is the wrong order and produces different cents in fractional cases."

    Design: Difficulty/combinatorial_formula/charge_rounding_order_per_component_then_sum
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0, hourly_rate_cents=2000)
    instructor = create_instructor(facility["id"], rate_cents_per_hour=2000)
    member = create_member(facility["id"], tier="NONE")
    sign_waiver(facility["id"], member["id"])
    top_up(member["id"], 50)

    booking = request_booking(
        facility, lane["id"], member, "LESSON", "TOKEN",
        "2026-04-02T09:00:00Z", "2026-04-02T09:10:00Z",
        instructor_id=instructor["id"],
    )
    ver = lane_version(lane["id"])
    res = api.confirm_booking(
        booking["id"], {"expected_lane_version": ver}, make_member_headers(member["id"])
    )
    confirmed = validate_success(res, 200)
    # 10-min off-peak: lane 2000*(1/6)=333.33->333; coach 2000*(1/6)=333.33->333; sum 666.
    # sum-then-round would give 667 (the wrong order).
    assert confirmed["final_cost_cents"] == 666


def test_small_lesson_token_cost_minimum_one(api):
    """PRD §3.5: "the booking's token_cost is the final_cost_cents divided by the
    facility's token_price_cents, rounded up to the next whole token — and for any
    booking whose final_cost_cents is above zero the token cost is never less than 1".

    Design: Difficulty/combinatorial_formula/charge_rounding_order_per_component_then_sum
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0, hourly_rate_cents=2000)
    instructor = create_instructor(facility["id"], rate_cents_per_hour=2000)
    member = create_member(facility["id"], tier="NONE")
    sign_waiver(facility["id"], member["id"])
    top_up(member["id"], 50)

    booking = request_booking(
        facility, lane["id"], member, "LESSON", "TOKEN",
        "2026-04-02T09:00:00Z", "2026-04-02T09:10:00Z",
        instructor_id=instructor["id"],
    )
    ver = lane_version(lane["id"])
    res = api.confirm_booking(
        booking["id"], {"expected_lane_version": ver}, make_member_headers(member["id"])
    )
    confirmed = validate_success(res, 200)
    # ceil(666 / 500) = 2 tokens.
    assert confirmed["token_cost"] == 2


# ─── calculations corner: party_pricing_offpeak_bronze_wheel_correct ───────────

def test_party_pricing_offpeak_bronze_wheel(api):
    """PRD §3.5: "The party portion, applied only when the kind is PARTY, is a base of
    15000 cents plus 1200 cents for each guest in party_guests". PRD §3.4: "800 cents
    for WHEEL, 1200 cents for ARM, and 300 cents for SOFT_TOSS".

    Design: Corner/calculations/party_pricing_offpeak_bronze_wheel_correct
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    machine = create_machine(facility["id"], lane["id"], model="WHEEL")
    member = create_member(facility["id"], tier="BRONZE")
    sign_waiver(facility["id"], member["id"])
    top_up(member["id"], 100)

    booking = request_booking(
        facility, lane["id"], member, "PARTY", "TOKEN",
        "2026-04-02T09:00:00Z", "2026-04-02T11:00:00Z",
        machine_id=machine["id"], party_guests=10,
    )
    ver = lane_version(lane["id"])
    res = api.confirm_booking(
        booking["id"], {"expected_lane_version": ver}, make_member_headers(member["id"])
    )
    confirmed = validate_success(res, 200)
    # 120-min off-peak: lane 4000*2=8000; coach 0; WHEEL 800; party 15000+10*1200=27000;
    # gross 35800; BRONZE 0.10 -> 35800*0.90 = 32220.
    assert confirmed["final_cost_cents"] == 32220
    assert confirmed["token_cost"] == 65  # ceil(32220/500)


# ─── calculations corner: booking_quoted_cost_computed_input_ignored ───────────

def test_quoted_cost_is_computed_not_client_supplied(api):
    """PRD §2.4: "On a Booking, the duration_minutes, quoted_cost_cents,
    final_cost_cents, and token_cost are computed". PRD §3.4: "stamps a provisional
    quoted_cost_cents using the forward-looking quote."

    Design: Corner/entities/booking_quoted_cost_computed_input_ignored
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    member = create_member(facility["id"], tier="NONE")

    payload = {
        "facility_id": facility["id"], "lane_id": lane["id"], "member_id": member["id"],
        "kind": "OPEN_SLOT", "pay_mode": "HOURLY",
        "start_utc": "2026-04-02T09:00:00Z", "end_utc": "2026-04-02T10:00:00Z",
        "quoted_cost_cents": 999999,  # client attempts to set a computed field
    }
    res = api.create_booking(payload, make_member_headers(member["id"]))
    booking = validate_success(res, 201)
    assert booking["quoted_cost_cents"] == 4000, "computed quote ignores client value"
    assert booking["status"] == "REQUESTED"
