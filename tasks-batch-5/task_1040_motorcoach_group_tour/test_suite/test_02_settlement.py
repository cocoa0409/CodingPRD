"""Departure settlement: provisional vs final variant, and the balance-unpaid guard."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_open_departure, add_confirmed_booking,
    create_hotel_block, first_voucher_id,
)


def _settlement_setup(api, ops_headers):
    """Build a GUARANTEED departure with full crew, one confirmed paid-in-full pax-2
    booking, and one CONFIRMED hotel block (block_cost 20000)."""
    s = setup_open_departure(coach=True, driver=True, guide=True, seat_capacity=10,
                             guaranteed_min_pax=2, base_price=100000, deposit=20000,
                             duration_days=3, start_date="2026-08-01", end_date="2026-08-03",
                             drive_hours=6)
    dep_id = s["dep"]["id"]
    hb = create_hotel_block(dep_id, hotel_name="Bay Inn", city="PHL", room_count=1,
                            nights=2, rate_per_room_night_cents=10000)
    bk = add_confirmed_booking(dep_id, pax_count=2, rooms_requested=1, pay_full=True)
    validate_success(api.confirm_hotel_block(hb["id"], ops_headers))
    return dep_id, bk


def test_provisional_settlement_counts_all_issued_vouchers(api, ops_headers, finance_headers):
    """PRD §3.9: "The provisional variant applies when settlement is viewed while the
    departure is OPEN or GUARANTEED: revenue is the sum of booking_total_cents over
    bookings whose reservation_status is CONFIRMED, and voucher cost estimates that every
    ISSUED voucher will be redeemed, summing the face value of all issued vouchers at 2500
    cents each."
    PRD §3.9: "The net is revenue minus the sum of crew cost, hotel cost, and voucher cost."

    Design: Difficulty/dual_variant_calc/departure_settlement_provisional_vs_final
    """
    dep_id, _ = _settlement_setup(api, ops_headers)
    data = validate_success(api.get_settlement(dep_id, finance_headers))
    # revenue 257400 - (crew 360000 + hotel 20000 + 2 issued vouchers*2500=5000) = -127600.
    assert data["variant"] == "provisional", f"expected provisional, got {data['variant']}"
    assert data["net_cents"] == -127600, f"expected provisional net -127600, got {data['net_cents']}"


def test_final_settlement_counts_only_redeemed_vouchers(api, ops_headers, sales_headers, finance_headers):
    """PRD §3.9: "voucher cost counts only vouchers that were actually REDEEMED, summing
    their face value."
    PRD §3.9: "The computed final net is pinned onto the departure as its settlement_net_cents."

    Design: Difficulty/dual_variant_calc/departure_settlement_provisional_vs_final
    """
    dep_id, bk = _settlement_setup(api, ops_headers)
    validate_success(api.depart_departure(dep_id, ops_headers))
    vid = first_voucher_id(bk["id"])
    validate_success(api.redeem_voucher(vid, sales_headers))
    settled = validate_success(api.settle_departure(dep_id, finance_headers))
    # final: revenue 240000(final 120000*2)+17400 = 257400; cost 360000+20000+1 redeemed*2500 = 382500.
    assert settled["settlement_net_cents"] == -125100, \
        f"expected final net -125100, got {settled['settlement_net_cents']}"


def test_settle_rejected_when_traveled_booking_has_outstanding_balance(api, ops_headers, finance_headers):
    """PRD §3.9: "Before a departure can be settled, no TRAVELED booking may have an
    outstanding balance: every traveled booking's amount_paid_cents must be at least its
    booking_total_cents, or the settle is rejected with ERR_BALANCE_UNPAID."

    Design: Corner/validations/corner_settle_balance_unpaid_returns_402
    """
    s = setup_open_departure(coach=True, driver=True, guide=True, seat_capacity=10,
                             guaranteed_min_pax=2, base_price=100000, deposit=20000,
                             duration_days=2, start_date="2026-08-01", end_date="2026-08-02",
                             drive_hours=6)
    dep_id = s["dep"]["id"]
    # Booking pays only the deposit (40000 of 257400) then travels.
    add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0, pay_full=False)
    validate_success(api.depart_departure(dep_id, ops_headers))
    resp = api.settle_departure(dep_id, finance_headers)
    validate_error(resp, ApiErrorId.ERR_BALANCE_UNPAID.value)
