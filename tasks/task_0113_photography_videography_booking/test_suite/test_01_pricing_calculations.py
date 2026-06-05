"""Pricing math: booking total assembly (base + ceil-overage + shooter), add-on
PRINT volume tiers vs ALBUM flat surcharge, license-fee factor product, and the
deposit floor/percentage clamp.

Queue A (difficulty) instances exercised here:
  dual_variant_calc / cancellation_fee_forward_looking_lead_time_on_booking
  dual_variant_calc / license_fee_perpetual_vs_term_on_license_grant
  combinatorial_formula / booking_total_three_inputs_nonlinear_overage_plus_shooter
  combinatorial_formula / addon_print_round_per_tier_then_sum
Queue B (corner) instances exercised here:
  calculations / deposit_floor_applies_when_below_min
  calculations / album_addon_flat_plus_binding_surcharge
  calculations / license_fee_personal_local_term_correct
"""
from test_helpers import (
    validate_success, get_success_data, api_client, TEST_USERS,
    make_client_headers,
    # fixtures
    setup_draft_booking, setup_confirmed_booking, assign_second_shooter,
    set_clock,
    # factories
    add_on_order_payload, license_grant_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# dual_variant_calc / cancellation_fee_forward_looking_lead_time_on_booking
# ===========================================================================
def test_cancellation_fee_early_lead_quarter_rate(api):
    """PRD §3.8: "apply a fee percentage of twenty-five percent when that lead time
    is fourteen days or more, fifty percent when it is at least seven but fewer than
    fourteen days, and one hundred percent when it is under seven days; multiply the
    booking's pinned deposit_due_cents by that percentage and round half up to whole
    cents to obtain cancellation_fee_cents."

    deposit_due 30000; shoot starts 2026-07-20, cancel clock 2026-07-01 (19 days,
    >= 14) -> 0.25 * 30000 = 7500.

    Design: Difficulty/dual_variant_calc/cancellation_fee_forward_looking_lead_time_on_booking
    """
    ctx = setup_confirmed_booking(
        start_utc="2026-07-20T10:00:00Z", end_utc="2026-07-20T12:00:00Z",
    )
    booking, client = ctx["booking"], ctx["client"]
    assert booking["deposit_due_cents"] == 30000
    set_clock("2026-07-01T00:00:00Z")
    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_client_headers(client["id"]))
    )
    assert cancelled["workflow_status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 7500, (
        f"lead>=14 days should bill 25% of 30000 = 7500, got {cancelled['cancellation_fee_cents']}"
    )


def test_cancellation_fee_mid_lead_half_rate(api):
    """PRD §3.8: "apply a fee percentage of twenty-five percent when that lead time
    is fourteen days or more, fifty percent when it is at least seven but fewer than
    fourteen days, and one hundred percent when it is under seven days; multiply the
    booking's pinned deposit_due_cents by that percentage and round half up to whole
    cents to obtain cancellation_fee_cents."

    Same booking (deposit_due 30000, shoot 2026-07-20) but cancel clock 2026-07-13
    (7 whole days, in [7,14)) -> 0.50 * 30000 = 15000. Forward-looking against the
    live clock, so the same booking yields a different fee.

    Design: Difficulty/dual_variant_calc/cancellation_fee_forward_looking_lead_time_on_booking
    """
    ctx = setup_confirmed_booking(
        start_utc="2026-07-20T10:00:00Z", end_utc="2026-07-20T12:00:00Z",
    )
    booking, client = ctx["booking"], ctx["client"]
    assert booking["deposit_due_cents"] == 30000
    set_clock("2026-07-13T10:00:00Z")
    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_client_headers(client["id"]))
    )
    assert cancelled["cancellation_fee_cents"] == 15000, (
        f"7<=lead<14 days should bill 50% of 30000 = 15000, got {cancelled['cancellation_fee_cents']}"
    )


# ===========================================================================
# dual_variant_calc / license_fee_perpetual_vs_term_on_license_grant
# ===========================================================================
def test_license_fee_term_based_commercial_national(api):
    """PRD §3.8: "The scope factor is 1.0 for PERSONAL, 2.5 for COMMERCIAL, 1.8 for
    EDITORIAL, and 4.0 for EXCLUSIVE. The territory factor is 1.0 for LOCAL, 1.5 for
    NATIONAL, and 2.2 for WORLDWIDE. The term factor is 1.0 plus one tenth of the
    number of effective years ... The base, the scope factor, the territory factor,
    and the term factor are all multiplied together first, and only the final product
    is rounded half up to whole cents - a single rounding at the very end."

    COMMERCIAL(2.5) * NATIONAL(1.5) * term 24mo (term_factor 1.0+2*0.10=1.2) * base 20000
    = 90000.

    Design: Difficulty/dual_variant_calc/license_fee_perpetual_vs_term_on_license_grant
    """
    base = setup_draft_booking(session_type="COMMERCIAL", tier="STANDARD",
                               base_fee_cents=300000, requested_shoot_hours=2,
                               included_shoot_hours=4)
    booking = base["booking"]
    grant = validate_success(
        api.create_license_grant(
            booking["id"],
            license_grant_payload("COMMERCIAL", "NATIONAL", 24),
            ADMIN,
        ),
        expected_status=201,
    )
    assert grant["fee_cents"] == 90000, (
        f"COMMERCIAL/NATIONAL/24mo should be 90000, got {grant['fee_cents']}"
    )


def test_license_fee_perpetual_priced_as_sixty_months(api):
    """PRD §3.8: "the effective term in months is the supplied term_months except that
    a perpetual grant (term_months of zero) is treated as a sixty-month term, and the
    number of years is that effective month count divided by twelve."

    EXCLUSIVE(4.0) * WORLDWIDE(2.2) * perpetual (60mo -> term_factor 1.0+5*0.10=1.5) *
    base 20000 = 264000, distinct from the term-based variant.

    Design: Difficulty/dual_variant_calc/license_fee_perpetual_vs_term_on_license_grant
    """
    base = setup_draft_booking(session_type="COMMERCIAL", tier="STANDARD",
                               base_fee_cents=300000, requested_shoot_hours=2,
                               included_shoot_hours=4)
    booking = base["booking"]
    grant = validate_success(
        api.create_license_grant(
            booking["id"],
            license_grant_payload("EXCLUSIVE", "WORLDWIDE", 0),
            ADMIN,
        ),
        expected_status=201,
    )
    assert grant["fee_cents"] == 264000, (
        f"EXCLUSIVE/WORLDWIDE/perpetual should be 264000, got {grant['fee_cents']}"
    )


# ===========================================================================
# combinatorial_formula / booking_total_three_inputs_nonlinear_overage_plus_shooter
# ===========================================================================
def test_booking_total_combines_base_overage_and_shooter(api):
    """PRD §3.2: "compute the shoot-hour overage as the booking's requested_shoot_hours
    minus the package's included_shoot_hours, treating any negative result as zero;
    round that overage up to a whole number of hours and multiply by the package's
    overage_hourly_rate_cents to get the overage charge, which is added to the base.
    To this base-plus-overage figure add the sum of line_total_cents over every add-on
    order on the booking still in ORDERED status, and add the sum of assignment_fee_cents
    over every second-shooter assignment still in ASSIGNED status on the booking's active
    shoot schedule."

    WEDDING base 200000, included 6h, requested 8h -> ceil(2)*15000 = 30000 overage;
    one 4h second shooter @8000 -> 32000. total = 200000 + 30000 + 32000 = 262000.

    Design: Difficulty/combinatorial_formula/booking_total_three_inputs_nonlinear_overage_plus_shooter
    """
    ctx = setup_confirmed_booking(
        session_type="WEDDING", tier="STANDARD",
        base_fee_cents=200000, included_shoot_hours=6, overage_hourly_rate_cents=15000,
        included_edited_images=100, requested_shoot_hours=8, requires_model_release=True,
        lead_hourly_rate_cents=12000,
        start_utc="2026-07-01T14:00:00Z", end_utc="2026-07-01T18:00:00Z",
    )
    booking, schedule = ctx["booking"], ctx["schedule"]
    second = get_success_data(
        api_client.create_photographer({"email": "second-shooter@studio.test",
                                        "full_name": "Second", "skills": ["PHOTO"],
                                        "hourly_rate_cents": 8000}, ADMIN)
    )
    sched_now = get_success_data(api.get_shoot_schedule(schedule["id"], ADMIN))
    assignment = assign_second_shooter(schedule["id"], second["id"], sched_now["version"])
    assert assignment["billable_hours"] == 4
    assert assignment["assignment_fee_cents"] == 32000
    booking_now = validate_success(api.get_booking(booking["id"], ADMIN))
    assert booking_now["total_fee_cents"] == 262000, (
        f"200000 base + 30000 overage + 32000 shooter = 262000, got {booking_now['total_fee_cents']}"
    )


def test_booking_total_overage_rounds_up_to_whole_hours(api):
    """PRD §3.2: "round that overage up to a whole number of hours and multiply by the
    package's overage_hourly_rate_cents to get the overage charge, which is added to
    the base."

    WEDDING base 200000, included 6h, requested 7.5h -> overage 1.5h ceils to 2h ->
    2*15000 = 30000; total (no add-ons/shooters) = 230000.

    Design: Difficulty/combinatorial_formula/booking_total_three_inputs_nonlinear_overage_plus_shooter
    """
    ctx = setup_confirmed_booking(
        session_type="WEDDING", tier="STANDARD",
        base_fee_cents=200000, included_shoot_hours=6, overage_hourly_rate_cents=15000,
        included_edited_images=100, requested_shoot_hours=7.5, requires_model_release=True,
        start_utc="2026-07-01T14:00:00Z", end_utc="2026-07-01T18:00:00Z",
    )
    booking = validate_success(api.get_booking(ctx["booking"]["id"], ADMIN))
    assert booking["total_fee_cents"] == 230000, (
        f"ceil(1.5h)=2h overage @15000 -> 200000+30000=230000, got {booking['total_fee_cents']}"
    )


# ===========================================================================
# combinatorial_formula / addon_print_round_per_tier_then_sum
# ===========================================================================
def test_addon_print_volume_discount_rounds_per_tier(api):
    """PRD §3.8: "the first ten units price at the full unit_price_cents, units eleven
    through fifty price at ninety percent of unit price, and every unit beyond fifty
    prices at eighty percent of unit price. Each band's subtotal is computed and
    rounded half up to whole cents on its own, and the three rounded subtotals are
    then summed - the rounding happens per band, before the bands are added together."

    60 prints @500: t1 10*500=5000, t2 40*500*0.90=18000, t3 10*500*0.80=4000;
    line_total = 27000. Booking total 100000 + 27000 = 127000.

    Design: Difficulty/combinatorial_formula/addon_print_round_per_tier_then_sum
    """
    base = setup_draft_booking()
    booking, client = base["booking"], base["client"]
    order = validate_success(
        api.create_add_on_order(
            booking["id"],
            add_on_order_payload("PRINT", 60, 500, booking["version"]),
            make_client_headers(client["id"]),
        ),
        expected_status=201,
    )
    assert order["line_total_cents"] == 27000, (
        f"PRINT 60@500 per-tier = 5000+18000+4000 = 27000, got {order['line_total_cents']}"
    )
    booking_now = validate_success(api.get_booking(booking["id"], ADMIN))
    assert booking_now["total_fee_cents"] == 127000


def test_addon_print_single_tier_no_discount_under_ten(api):
    """PRD §3.8: "the first ten units price at the full unit_price_cents ... Each band's
    subtotal is computed and rounded half up to whole cents on its own, and the three
    rounded subtotals are then summed."

    8 prints @500 all sit in tier 1 (full price): 8*500 = 4000, no discount.

    Design: Difficulty/combinatorial_formula/addon_print_round_per_tier_then_sum
    """
    base = setup_draft_booking()
    booking, client = base["booking"], base["client"]
    order = validate_success(
        api.create_add_on_order(
            booking["id"],
            add_on_order_payload("PRINT", 8, 500, booking["version"]),
            make_client_headers(client["id"]),
        ),
        expected_status=201,
    )
    assert order["line_total_cents"] == 4000, (
        f"8 prints @500 at full price = 4000, got {order['line_total_cents']}"
    )


# ===========================================================================
# calculations / deposit_floor_applies_when_below_min
# ===========================================================================
def test_deposit_floor_clamps_up_to_minimum(api):
    """PRD §3.2: "the deposit clamps up to the 5000-cent floor" — "the deposit is the
    percentage-based amount when that amount is at least 5000 cents; when the percentage
    amount falls below 5000 cents but the total is 5000 cents or more, the deposit clamps
    up to the 5000-cent floor; and when the total is itself below 5000 cents the deposit
    equals the total."

    Total 10000, deposit_pct 0.30 -> raw 3000 < 5000 floor; total >= 5000 so deposit
    clamps to 5000.

    Design: Corner/calculations/deposit_floor_applies_when_below_min
    """
    ctx = setup_confirmed_booking(base_fee_cents=10000, deposit_pct=0.30,
                                  included_edited_images=5,
                                  start_utc="2026-07-01T10:00:00Z",
                                  end_utc="2026-07-01T12:00:00Z")
    booking = ctx["booking"]
    assert booking["total_fee_cents"] == 10000
    assert booking["deposit_due_cents"] == 5000, (
        f"raw 3000 < floor 5000 -> clamp to 5000, got {booking['deposit_due_cents']}"
    )


# ===========================================================================
# calculations / album_addon_flat_plus_binding_surcharge
# ===========================================================================
def test_addon_album_flat_plus_binding_surcharge(api):
    """PRD §3.8: "For an ALBUM order there is no discount: the line is quantity multiplied
    by unit_price_cents, plus a flat binding surcharge of 3500 cents."

    ALBUM 3 page-tiers @8000 -> 24000 + 3500 = 27500; booking total 100000+27500=127500.

    Design: Corner/calculations/album_addon_flat_plus_binding_surcharge
    """
    base = setup_draft_booking()
    booking, client = base["booking"], base["client"]
    order = validate_success(
        api.create_add_on_order(
            booking["id"],
            add_on_order_payload("ALBUM", 3, 8000, booking["version"]),
            make_client_headers(client["id"]),
        ),
        expected_status=201,
    )
    assert order["line_total_cents"] == 27500, (
        f"ALBUM 3@8000 + 3500 surcharge = 27500, got {order['line_total_cents']}"
    )
    booking_now = validate_success(api.get_booking(booking["id"], ADMIN))
    assert booking_now["total_fee_cents"] == 127500


# ===========================================================================
# calculations / license_fee_personal_local_term_correct
# ===========================================================================
def test_license_fee_personal_local_twelve_months(api):
    """PRD §3.8: "The grant's fee_cents is pinned at creation from a base of 20000 cents
    scaled by three factors multiplied together. The scope factor is 1.0 for PERSONAL ...
    The territory factor is 1.0 for LOCAL ... The term factor is 1.0 plus one tenth of
    the number of effective years ..."

    PERSONAL(1.0) * LOCAL(1.0) * 12mo (term_factor 1.0+1*0.10=1.1) * 20000 = 22000.

    Design: Corner/calculations/license_fee_personal_local_term_correct
    """
    base = setup_draft_booking()
    booking = base["booking"]
    grant = validate_success(
        api.create_license_grant(
            booking["id"],
            license_grant_payload("PERSONAL", "LOCAL", 12),
            ADMIN,
        ),
        expected_status=201,
    )
    assert grant["fee_cents"] == 22000, (
        f"PERSONAL/LOCAL/12mo should be 22000, got {grant['fee_cents']}"
    )
