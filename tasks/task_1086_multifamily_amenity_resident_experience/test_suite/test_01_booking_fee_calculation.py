"""Amenity booking fee: dual-variant (provisional vs final) and the
combinatorial peak/tier/cap formula.

Queue A (Difficulty): dual_variant_calc/booking_provisional_vs_final_diverges,
combinatorial_formula/booking_charge_peak_tier_cap_mode_a.
"""
from test_helpers import (
    fixtures as fx,
    make_resident_headers,
    validate_success,
)


def _setup_premium_clubroom_booking(api):
    """PREMIUM resident + CLUBROOM (base 4000, peak 17:00-21:00 x1.5, deposit
    10000); a 2026-06-01 18:00-20:00 booking created CONFIRMED. Returns ids."""
    base = fx.setup_amenity_booking_base(
        api,
        clock="2026-05-20T00:00:00Z",
        resident_overrides={"full_name": "Ada", "email": "ada@x.com", "membership_tier": "PREMIUM"},
        amenity_overrides={
            "name": "Clubroom", "amenity_type": "CLUBROOM", "capacity": 1,
            "base_rate_cents_per_hour": 4000, "deposit_cents": 10000, "buffer_minutes": 30,
            "open_minute": 360, "close_minute": 1320,
            "peak_start_minute": 1020, "peak_end_minute": 1260, "peak_multiplier": 1.5,
        },
    )
    resident_id = base["resident"]["id"]
    booking = fx.new_booking(
        api, base["amenity"]["id"], resident_id,
        "2026-06-01T18:00:00Z", "2026-06-01T20:00:00Z",
        expected_version=base["amenity"]["version"],
    )
    return resident_id, booking["id"]


def test_provisional_and_final_fee_diverge(api):
    """PRD §3.2: "The gross amount is the amenity's `base_rate_cents_per_hour`
    multiplied by the sum of the off-peak hours plus the peak hours scaled by
    the `peak_multiplier`, rounded half up to whole cents."
    PRD §3.2: "The provisional variant uses the requested `[start_at, end_at)`
    window and is stored as `provisional_fee_cents`; the final variant uses the
    actual checked-in window and is stored as `final_fee_cents`."

    Provisional over the requested 2h all-peak window (PREMIUM 20% off) is 9600;
    the final over the actual 1h checked-in window is 4800.

    Design: Difficulty/dual_variant_calc/booking_provisional_vs_final_diverges
    """
    resident_id, booking_id = _setup_premium_clubroom_booking(api)

    fx.set_clock(api, "2026-06-01T18:00:00Z")
    validate_success(api.check_in_booking(booking_id, fx.FRONT_DESK))
    fx.set_clock(api, "2026-06-01T19:00:00Z")
    completed = validate_success(api.check_out_booking(booking_id, fx.FRONT_DESK))

    assert completed["provisional_fee_cents"] == 9600, "provisional over 2h all-peak, PREMIUM"
    assert completed["final_fee_cents"] == 4800, "final over 1h all-peak, PREMIUM"


def test_only_final_fee_is_charged_to_balance(api):
    """PRD §3.2: "that final fee is added to the resident's `rent_balance_cents`
    with a `BOOKING_FEE` ledger entry for the same positive amount, the
    resident's `hold_balance_cents` is decreased by the `deposit_hold_cents`
    (releasing the hold)."
    PRD §3.2: "The provisional fee is not charged to the resident's balance at
    this stage — only the deposit is held."

    Only the final 4800 lands on rent_balance; the deposit hold is fully
    released at check-out.

    Design: Difficulty/dual_variant_calc/booking_provisional_vs_final_diverges
    """
    resident_id, booking_id = _setup_premium_clubroom_booking(api)

    fx.set_clock(api, "2026-06-01T18:00:00Z")
    validate_success(api.check_in_booking(booking_id, fx.FRONT_DESK))
    fx.set_clock(api, "2026-06-01T19:00:00Z")
    completed = validate_success(api.check_out_booking(booking_id, fx.FRONT_DESK))
    assert completed["status"] == "COMPLETED"

    resident = fx.get_resident(api, resident_id)
    assert resident["rent_balance_cents"] == 4800, "only the final fee is charged"
    assert resident["hold_balance_cents"] == 0, "deposit hold released at check-out"


def _setup_allpeak_pool_standard(api):
    """STANDARD resident + POOL (base 5000, all-day peak x2.0, capacity 1)."""
    base = fx.setup_amenity_booking_base(
        api,
        clock="2026-05-20T00:00:00Z",
        resident_overrides={"full_name": "Cara", "email": "cara@x.com", "membership_tier": "STANDARD"},
        amenity_overrides={
            "name": "Pool", "amenity_type": "POOL", "capacity": 1,
            "base_rate_cents_per_hour": 5000, "deposit_cents": 0, "buffer_minutes": 0,
            "open_minute": 0, "close_minute": 1440,
            "peak_start_minute": 0, "peak_end_minute": 1440, "peak_multiplier": 2.0,
        },
    )
    return base


def test_all_peak_gross_is_clamped_to_daily_cap(api):
    """PRD §3.2: "Finally the fee is the lesser of the discounted amount and a
    daily fee cap of 20000 cents."

    A 6h all-peak booking on a 5000/h amenity at x2.0 grosses 60000; with no
    PREMIUM discount the fee is clamped to the 20000 cap.

    Design: Difficulty/combinatorial_formula/booking_charge_peak_tier_cap_mode_a
    """
    base = _setup_allpeak_pool_standard(api)
    booking = fx.new_booking(
        api, base["amenity"]["id"], base["resident"]["id"],
        "2026-06-02T10:00:00Z", "2026-06-02T16:00:00Z",
        expected_version=base["amenity"]["version"],
    )
    assert booking["provisional_fee_cents"] == 20000, "60000 gross clamped to 20000 cap"


def test_capped_booking_is_confirmed(api):
    """PRD §3.2: "On success the booking is created directly in `CONFIRMED`
    status, its `provisional_fee_cents` is computed (see below), its
    `deposit_hold_cents` is copied from the amenity's `deposit_cents`, the
    resident's `hold_balance_cents` is increased by that deposit hold, and the
    amenity's `version` is incremented by one."

    The cap does not reject the booking; it is admitted CONFIRMED with a zero
    deposit hold (amenity deposit_cents 0).

    Design: Difficulty/combinatorial_formula/booking_charge_peak_tier_cap_mode_a
    """
    base = _setup_allpeak_pool_standard(api)
    resp = api.create_booking(
        {
            "amenity_id": base["amenity"]["id"], "resident_id": base["resident"]["id"],
            "start_at": "2026-06-02T10:00:00Z", "end_at": "2026-06-02T16:00:00Z",
            "expected_amenity_version": base["amenity"]["version"],
        },
        make_resident_headers(base["resident"]["id"]),
    )
    booking = validate_success(resp, expected_status=201)
    assert booking["status"] == "CONFIRMED"
    assert booking["deposit_hold_cents"] == 0
