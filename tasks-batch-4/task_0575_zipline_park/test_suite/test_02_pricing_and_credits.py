"""Booking pricing, group insurance, and cancellation/raincheck credits (PRD §3.4, §3.6, §3.7)."""
from test_helpers import (
    validate_success, TEST_USERS,
    setup_course_slot_guide, create_course, create_time_slot, create_guide,
    assign_guide, create_participant, create_group, create_booking,
    create_season_pass, get_group, get_booking, set_clock,
    WEEKDAY_SLOT_START, WEEKEND_SLOT_START,
)

OP = TEST_USERS["operator_headers"]


# ── combinatorial booking_price: three price paths from base 5000 ──────────
def _combi_setup(api):
    """Course base 5000; weekday slot ts_w and weekend slot ts_e, each guide-assigned.
    Group of 8 on ts_w; participants pg/py/pz; pz holds a 1-use PREMIUM pass."""
    course = create_course(api)
    ts_w = create_time_slot(api, course["id"], start_at=WEEKDAY_SLOT_START)
    ts_e = create_time_slot(api, course["id"], start_at=WEEKEND_SLOT_START)
    guide = create_guide(api)
    # A booking requires the slot to be staffed (assigned capacity gate, §3.4);
    # the single guide covers both non-overlapping slots.
    assign_guide(api, guide["id"], ts_w["id"])
    assign_guide(api, guide["id"], ts_e["id"])
    g8 = create_group(api, ts_w["id"], expected_size=8, name="Team8")
    pg = create_participant(api, full_name="PG")
    py = create_participant(api, full_name="PY")
    pz = create_participant(api, full_name="PZ")
    pz_sp = create_season_pass(api, pz["id"], total_uses=1, tier="PREMIUM")
    return ts_w, ts_e, g8, pg, py, pz, pz_sp


def test_booking_price_group_of_eight_weekday_twenty_pct_off(api):
    """PRD §3.4: "a size of 8 or more gives a twenty-percent discount".
    PRD §3.4: "Multiply the subtotal by one minus the selected discount rate to get the
    discounted amount."

    Design: Difficulty/combinatorial_formula/booking_price_tiered_group_weekend_pass_mode_a
    """
    ts_w, ts_e, g8, pg, py, pz, pz_sp = _combi_setup(api)
    booking = create_booking(api, ts_w["id"], pg["id"], group_id=g8["id"])
    assert booking["price_cents"] == 4000


def test_booking_price_weekend_single_adds_surcharge(api):
    """PRD §3.4: "If the slot's `start_at` falls on a Saturday or Sunday in UTC, add a
    weekend amount equal to the base times the course's `weekend_surcharge_pct`".

    Design: Difficulty/combinatorial_formula/booking_price_tiered_group_weekend_pass_mode_a
    """
    ts_w, ts_e, g8, pg, py, pz, pz_sp = _combi_setup(api)
    booking = create_booking(api, ts_e["id"], py["id"])
    assert booking["price_cents"] == 5750


def test_booking_price_zero_when_pass_covers(api):
    """PRD §3.4: "if `use_season_pass` was requested and a usable pass exists, the pass
    covers the ride and `price_cents` is 0 with `season_pass_id` recorded".

    Design: Difficulty/combinatorial_formula/booking_price_tiered_group_weekend_pass_mode_a
    """
    ts_w, ts_e, g8, pg, py, pz, pz_sp = _combi_setup(api)
    booking = create_booking(api, ts_w["id"], pz["id"], use_season_pass=True)
    assert booking["price_cents"] == 0
    assert booking["season_pass_id"] == pz_sp["id"]


# ── group insurance: round-per-member-then-sum ─────────────────────────────
def test_group_member_count_reflects_active_bookings(api):
    """PRD §3.7: "Its `member_count` is the number of bookings tied to it (by `group_id`)
    in `CONFIRMED`, `CHECKED_IN`, `BRIEFED`, or `COMPLETED` status."

    Design: Difficulty/combinatorial_formula/group_insurance_round_per_member_then_sum_mode_b
    """
    course, ts, guide = setup_course_slot_guide(api)
    g3 = create_group(api, ts["id"], expected_size=3, name="Team3")
    for name in ("M1", "M2", "M3"):
        p = create_participant(api, full_name=name)
        create_booking(api, ts["id"], p["id"], group_id=g3["id"])
    group = get_group(api, g3["id"])
    assert group["member_count"] == 3


def test_group_insurance_round_per_member_then_sum(api):
    """PRD §3.7: "each member's insurance fee is rounded to whole cents first, and only
    then are the rounded figures summed — a single sum-then-round would produce a
    different total and must not be used."

    Design: Difficulty/combinatorial_formula/group_insurance_round_per_member_then_sum_mode_b
    """
    course, ts, guide = setup_course_slot_guide(api)
    g3 = create_group(api, ts["id"], expected_size=3, name="Team3")
    for name in ("M1", "M2", "M3"):
        p = create_participant(api, full_name=name)
        create_booking(api, ts["id"], p["id"], group_id=g3["id"])
    group = get_group(api, g3["id"])
    # round_half_up(5000 * 0.0745 = 372.5) = 373 per member; 3 * 373 = 1119.
    assert group["insurance_total_cents"] == 1119


# ── dual-variant cancellation credit: weather-full vs voluntary-late-half ───
def test_weather_close_credits_full_price(api):
    """PRD §3.6: "its `raincheck_credit_cents` is set equal to its `price_cents`,
    unconditionally, regardless of how close to `start_at` the closure happens."
    PRD §3.6: "every booking on the slot in `CONFIRMED`, `CHECKED_IN`, or `BRIEFED` is
    driven to `RAINCHECKED`".

    Design: Difficulty/dual_variant_calc/raincheck_credit_weather_full_vs_voluntary_late_half
    """
    course, ts, guide = setup_course_slot_guide(api)
    p = create_participant(api, full_name="P A")
    booking = create_booking(api, ts["id"], p["id"])
    assert booking["price_cents"] == 5000
    api.close_time_slot(ts["id"], OP, reason="storm")
    after = get_booking(api, booking["id"])
    assert after["status"] == "RAINCHECKED"
    assert after["raincheck_credit_cents"] == 5000


def test_voluntary_cancel_under_24h_credits_half_price(api):
    """PRD §3.6: "if the lead is under 24 hours, the credit is `price_cents` multiplied
    by one-half, rounded half-up to whole cents."
    PRD §3.6: "A booking in `CONFIRMED`, `CHECKED_IN`, or `BRIEFED` may be voluntarily
    cancelled — by an `Operator` or by the owning `Customer` — into `CANCELLED`."

    Design: Difficulty/dual_variant_calc/raincheck_credit_weather_full_vs_voluntary_late_half
    """
    course, ts, guide = setup_course_slot_guide(api)
    p = create_participant(api, full_name="P B")
    booking = create_booking(api, ts["id"], p["id"])
    assert booking["price_cents"] == 5000
    # 10 hours before the 2026-06-03T10:00Z slot -> lead < 24h.
    set_clock(api, "2026-06-03T00:00:00Z")
    after = validate_success(api.cancel_booking(booking["id"], OP), 200)
    assert after["status"] == "CANCELLED"
    assert after["raincheck_credit_cents"] == 2500


def test_voluntary_cancel_lead_ge_24h_credits_full_price(api):
    """PRD §3.6: "If that lead is at least 24 hours, the full `price_cents` is credited to
    `raincheck_credit_cents`".

    Design: Corner/calculations/voluntary_full_refund_when_lead_ge_24h
    """
    course, ts, guide = setup_course_slot_guide(api)
    p = create_participant(api, full_name="P A")
    booking = create_booking(api, ts["id"], p["id"])
    # Clock stays at default 2026-05-01, far more than 24h before the 2026-06-03 slot.
    after = validate_success(api.cancel_booking(booking["id"], OP), 200)
    assert after["status"] == "CANCELLED"
    assert after["raincheck_credit_cents"] == 5000


def test_redeem_applies_raincheck_credit_to_new_booking(api):
    """PRD §3.6: "Redeeming drives the original booking to the terminal `REDEEMED` state
    and creates a brand-new `CONFIRMED` booking on the target slot whose
    `redeemed_from_booking_id` points back at the original."
    PRD §3.6: "The new booking's price is the target slot's freshly computed booking price
    less the original booking's `raincheck_credit_cents`, floored at zero."

    Design: Corner/calculations/redeem_applies_raincheck_credit_to_new_booking
    """
    course = create_course(api)
    ts1 = create_time_slot(api, course["id"], start_at=WEEKDAY_SLOT_START)
    ts2 = create_time_slot(api, course["id"], start_at="2026-06-10T10:00:00Z")
    guide = create_guide(api)
    assign_guide(api, guide["id"], ts1["id"])
    p = create_participant(api)
    booking = create_booking(api, ts1["id"], p["id"])
    api.close_time_slot(ts1["id"], OP, reason="storm")  # -> RAINCHECKED, credit 5000

    res = api.redeem_booking(booking["id"], {"time_slot_id": ts2["id"]}, OP)
    new_booking = validate_success(res, 201)
    assert new_booking["price_cents"] == 0
    assert new_booking["redeemed_from_booking_id"] == booking["id"]
    origin = get_booking(api, booking["id"])
    assert origin["status"] == "REDEEMED"
