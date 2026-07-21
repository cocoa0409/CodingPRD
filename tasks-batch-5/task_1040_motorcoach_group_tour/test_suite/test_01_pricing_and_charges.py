"""Per-person pricing, service fee, cancellation penalty, and insurance charges."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_open_departure, add_confirmed_booking,
    create_booking, get_departure,
)
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Dual-variant per-person price: quoted (forward-looking) vs final (actual band)
# ---------------------------------------------------------------------------

def test_quoted_per_person_uses_forward_looking_projected_band(api, sales_headers):
    """PRD §3.5: "At booking creation the band is chosen on a forward-looking basis:
    it is derived from the projected passenger count, which is the departure's current
    confirmed_pax plus this booking's own pax_count. The resulting per-person price is
    locked into the booking's quoted_per_person_cents."
    PRD §3.5: "SMALL multiplies by 1.20, STANDARD by 1.00, and LARGE by 0.90."

    Design: Difficulty/dual_variant_calc/per_person_price_quoted_vs_final_on_booking
    """
    s = setup_open_departure(coach=True, driver=True, guide=True, seat_capacity=10,
                             guaranteed_min_pax=6, base_price=100000, deposit=20000,
                             duration_days=3, start_date="2026-08-01", end_date="2026-08-03",
                             drive_hours=8)
    dep_id = s["dep"]["id"]
    # Booking A confirmed while confirmed_pax == 0 -> projected 1 -> SMALL 1.20 -> 120000.
    bk_a = add_confirmed_booking(dep_id, pax_count=1, rooms_requested=0)
    assert bk_a["quoted_per_person_cents"] == 120000, \
        f"expected SMALL-band quote 120000, got {bk_a['quoted_per_person_cents']}"
    # Booking B created while confirmed_pax == 1 -> projected 6 -> STANDARD 1.00 -> 100000.
    bk_b = create_booking(dep_id, lead_name="Party B", pax_count=5, rooms_requested=0)
    assert bk_b["quoted_per_person_cents"] == 100000, \
        f"expected STANDARD-band quote 100000, got {bk_b['quoted_per_person_cents']}"


def test_final_per_person_uses_actual_occupancy_band_at_depart(api, ops_headers):
    """PRD §3.5: "The booking's final_per_person_cents remains null until the departure
    departs, at which point it is re-derived from the departure's actual confirmed_pax
    band and pinned (see §3.2)."
    PRD §3.2: "each traveled booking has its final_per_person_cents pinned from that actual band"

    Design: Difficulty/dual_variant_calc/per_person_price_quoted_vs_final_on_booking
    """
    s = setup_open_departure(coach=True, driver=True, guide=True, seat_capacity=10,
                             guaranteed_min_pax=6, base_price=100000, deposit=20000,
                             duration_days=3, start_date="2026-08-01", end_date="2026-08-03",
                             drive_hours=8)
    dep_id = s["dep"]["id"]
    bk_a = add_confirmed_booking(dep_id, pax_count=1, rooms_requested=0)
    bk_b = add_confirmed_booking(dep_id, pax_count=5, rooms_requested=0, deposit_amount=100000)
    # confirmed_pax now 6 -> departure GUARANTEED; depart pins final from actual band STANDARD.
    validate_success(api.depart_departure(dep_id, ops_headers))
    a = validate_success(api.get_booking(bk_a["id"], ops_headers))
    b = validate_success(api.get_booking(bk_b["id"], ops_headers))
    assert a["final_per_person_cents"] == 100000, \
        f"Booking A final should be STANDARD 100000, got {a['final_per_person_cents']}"
    assert b["final_per_person_cents"] == 100000, \
        f"Booking B final should be STANDARD 100000, got {b['final_per_person_cents']}"


# ---------------------------------------------------------------------------
# Service fee: round the per-person fee first, THEN multiply by pax (mode b)
# ---------------------------------------------------------------------------

def test_service_fee_rounds_per_person_before_multiplying(api):
    """PRD §3.5: "the per-person fee is quoted_per_person_cents multiplied by the
    service-fee rate of 0.0725, rounded half up to whole cents, and the booking's
    service_fee_cents is that rounded per-person fee multiplied by pax_count — the
    rounding happens on the per-person fee only, before multiplying by the passenger
    count, not on the subtotal."

    Design: Difficulty/combinatorial_formula/service_fee_round_per_person_then_multiply_mode_b
    """
    s = setup_open_departure(coach=False, guaranteed_min_pax=5, base_price=99900,
                             deposit=20000, duration_days=2)
    dep_id = s["dep"]["id"]
    # pax 3 on empty departure -> SMALL band 1.20 -> quoted round(99900*1.20)=119880.
    # per-person fee = round(119880*0.0725)=8691; *3 = 26073 (NOT round(359640*0.0725)=26074).
    bk = create_booking(dep_id, lead_name="Party E", pax_count=3, rooms_requested=0)
    assert bk["service_fee_cents"] == 26073, \
        f"expected round-per-person 26073, got {bk['service_fee_cents']}"


def test_service_fee_quoted_and_subtotal_pin_the_mode_b_inputs(api):
    """PRD §3.5: "The base_subtotal_cents is quoted_per_person_cents multiplied by pax_count."
    PRD §3.5: "The per-person price is the base price times the band's multiplier, rounded
    half up to whole cents."

    Design: Difficulty/combinatorial_formula/service_fee_round_per_person_then_multiply_mode_b
    """
    s = setup_open_departure(coach=False, guaranteed_min_pax=5, base_price=99900,
                             deposit=20000, duration_days=2)
    dep_id = s["dep"]["id"]
    bk = create_booking(dep_id, lead_name="Party E", pax_count=3, rooms_requested=0)
    assert bk["quoted_per_person_cents"] == 119880, \
        f"expected quoted 119880, got {bk['quoted_per_person_cents']}"
    assert bk["base_subtotal_cents"] == 359640, \
        f"expected subtotal 359640, got {bk['base_subtotal_cents']}"


# ---------------------------------------------------------------------------
# Cancellation penalty: tiered percent under a deposit floor (mode a)
# ---------------------------------------------------------------------------

def test_cancellation_penalty_full_tier_over_deposit_floor(api, sales_headers):
    """PRD §3.8: "fewer than 15 days charges 100 percent. The base penalty is the booking's
    base_subtotal_cents multiplied by that percentage, rounded half up to whole cents."
    PRD §3.8: "otherwise penalty_charged_cents is the greater of the computed base penalty
    and the deposit floor."

    Design: Difficulty/combinatorial_formula/cancellation_penalty_tier_and_deposit_floor_mode_a
    """
    # Clock default 2026-07-01; start 2026-07-10 -> 9 whole days -> 100% tier.
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=5,
                             base_price=100000, deposit=20000, duration_days=2,
                             start_date="2026-07-10", end_date="2026-07-11", drive_hours=5)
    dep_id = s["dep"]["id"]
    bk = add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0,
                               insurance_opt_in=False, pay_full=True)
    cancelled = validate_success(api.cancel_booking(bk["id"], {"reason": "party withdrew"}, sales_headers))
    # base_subtotal 240000 * 1.00 = 240000 > deposit floor 40000.
    assert cancelled["penalty_charged_cents"] == 240000, \
        f"expected penalty 240000, got {cancelled['penalty_charged_cents']}"
    assert cancelled["reservation_status"] == "CANCELLED"


def test_cancellation_refund_is_paid_minus_penalty(api, sales_headers):
    """PRD §3.8: "The refund issued is the amount_paid_cents minus penalty_charged_cents,
    floored at zero so it is never negative, recorded as a REFUND payment; the
    payment_status moves to REFUNDED."

    Design: Difficulty/combinatorial_formula/cancellation_penalty_tier_and_deposit_floor_mode_a
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=5,
                             base_price=100000, deposit=20000, duration_days=2,
                             start_date="2026-07-10", end_date="2026-07-11", drive_hours=5)
    dep_id = s["dep"]["id"]
    bk = add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0,
                               insurance_opt_in=False, pay_full=True)
    validate_success(api.cancel_booking(bk["id"], {"reason": "party withdrew"}, sales_headers))
    refreshed = validate_success(api.get_booking(bk["id"], sales_headers))
    # paid 257400 - penalty 240000 = 17400.
    assert refreshed["amount_refunded_cents"] == 17400, \
        f"expected refund 17400, got {refreshed['amount_refunded_cents']}"
    assert refreshed["payment_status"] == "REFUNDED"


# ---------------------------------------------------------------------------
# Insurance opt-in default
# ---------------------------------------------------------------------------

def test_booking_insurance_opt_in_defaults_false(api):
    """PRD §3.5: "an optional insurance_opt_in flag that defaults to false."
    PRD §3.5: "when insurance is not opted in it is 0."

    Design: Corner/entities/corner_booking_insurance_defaults_false
    """
    s = setup_open_departure(coach=False, guaranteed_min_pax=5, base_price=100000,
                             deposit=20000, duration_days=2)
    dep_id = s["dep"]["id"]
    bk = create_booking(dep_id, lead_name="Def Party", pax_count=2, rooms_requested=0)
    assert bk["insurance_opt_in"] is False, f"expected default false, got {bk['insurance_opt_in']}"
    assert bk["insurance_premium_cents"] == 0, \
        f"expected premium 0, got {bk['insurance_premium_cents']}"
