"""Market-day operations: open/close, check-in arrival, no-show sweep, weather
and safety cancellation refunds, and booth service maintenance.

Covers the corner state_machines (CheckIn/MarketDay) and calculations (fee_refund)
instances plus the set-service endpoint instance.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, make_vendor_headers,
    TEST_USERS,
    create_market, create_booth, create_active_vendor, create_open_market_day,
    create_market_day, reserve_daily_assignment,
    create_check_in_payload,
)

ADMIN = TEST_USERS["admin_headers"]


def test_arrive_on_scheduled_day_is_outside_window(api):
    """PRD 3.5: "Arrival is legal only when the check-in is EXPECTED and the market
    day is OPEN; arriving on a SCHEDULED, CLOSED, or CANCELLED day is rejected with
    ERR_OUTSIDE_WINDOW".

    Design: Corner/state_machines/arrive_on_scheduled_day_is_outside_window
    """
    market = create_market()
    booth = create_booth(market["id"], label="S-1", grid_row=0, grid_col=1, size_class="SINGLE")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")
    day = create_market_day(market["id"], market_date="2026-06-06")  # SCHEDULED, not opened
    asg = reserve_daily_assignment(market["id"], booth["id"], vendor["id"], day["id"])
    vh = make_vendor_headers(vendor["id"])
    ci = get_success_data(api.create_check_in(
        create_check_in_payload(market["id"], asg["id"], day["id"]), vh))

    res = api.arrive_check_in(ci["id"], vh)
    validate_error(res, "ERR_OUTSIDE_WINDOW")
    after = get_success_data(api.get_check_in(ci["id"], ADMIN))
    assert after["status"] == "EXPECTED"


def test_day_close_sweeps_expected_checkin_to_no_show(api):
    """PRD 3.5: "every check-in for the day still in EXPECTED becomes NO_SHOW, which
    recomputes and increments the owning vendor's no_show_strikes" — closing the day
    sweeps an un-arrived check-in and bumps strikes to 1.

    Design: Corner/state_machines/day_close_sweeps_expected_checkin_to_no_show
    """
    market = create_market()
    booth = create_booth(market["id"], label="S-1", grid_row=0, grid_col=1, size_class="SINGLE")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    asg = reserve_daily_assignment(market["id"], booth["id"], vendor["id"], day["id"])
    vh = make_vendor_headers(vendor["id"])
    ci = get_success_data(api.create_check_in(
        create_check_in_payload(market["id"], asg["id"], day["id"]), vh))

    closed = validate_success(api.close_market_day(day["id"], ADMIN), 200)
    assert closed["status"] == "CLOSED"
    ci_after = get_success_data(api.get_check_in(ci["id"], ADMIN))
    assert ci_after["status"] == "NO_SHOW"
    vendor_after = get_success_data(api.get_vendor(vendor["id"], ADMIN))
    assert vendor_after["no_show_strikes"] == 1


def test_arrive_activates_reserved_daily_assignment(api):
    """PRD 3.5: "Marking a check-in as arrived ... advances it from EXPECTED to
    PRESENT, stamps arrived_at, recomputes the day's attendance_count, and bumps
    the check-in's version; if the linked assignment is RESERVED it cascades that
    assignment to ACTIVE." attendance_count becomes 1.

    Design: Corner/state_machines/arrive_activates_reserved_daily_assignment
    """
    market = create_market()
    booth = create_booth(market["id"], label="S-1", grid_row=0, grid_col=1, size_class="SINGLE")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    asg = reserve_daily_assignment(market["id"], booth["id"], vendor["id"], day["id"])
    vh = make_vendor_headers(vendor["id"])
    ci = get_success_data(api.create_check_in(
        create_check_in_payload(market["id"], asg["id"], day["id"]), vh))

    arrived = validate_success(api.arrive_check_in(ci["id"], vh), 200)
    assert arrived["status"] == "PRESENT"
    day_after = get_success_data(api.get_market_day(day["id"], ADMIN))
    assert day_after["attendance_count"] == 1
    asg_after = get_success_data(api.get_booth_assignment(asg["id"], ADMIN))
    assert asg_after["status"] == "ACTIVE"


def test_safety_cancellation_is_not_refundable(api):
    """PRD 3.6: "the system sets daily_fee_refundable to true exactly when the
    cancellation_reason is WEATHER, and false for SAFETY or LOW_TURNOUT" and "For
    any cancellation reason other than WEATHER, fee_refunded_cents stays 0".

    Design: Corner/calculations/safety_cancellation_is_not_refundable
    """
    market = create_market()
    booth = create_booth(market["id"], label="S-1", grid_row=0, grid_col=1, size_class="SINGLE")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    asg = reserve_daily_assignment(market["id"], booth["id"], vendor["id"], day["id"])

    cancelled = validate_success(
        api.cancel_market_day(day["id"], {"cancellation_reason": "SAFETY"}, ADMIN), 200)
    assert cancelled["daily_fee_refundable"] is False

    asg_after = get_success_data(api.get_booth_assignment(asg["id"], ADMIN))
    assert asg_after["status"] == "CANCELLED"
    assert asg_after["fee_refunded_cents"] == 0


def test_set_service_marks_booth_out_of_service(api):
    """PRD 3.1: "The admin can flip a booth between service states by supplying an
    out_of_service boolean; the booth toggles between OUT_OF_SERVICE and OPEN".

    Design: Corner/endpoints/set_service_marks_booth_out_of_service
    """
    market = create_market()
    booth = create_booth(market["id"], label="S-1", grid_row=0, grid_col=1, size_class="SINGLE")

    updated = validate_success(
        api.set_service_booth(booth["id"], {"out_of_service": True}, ADMIN), 200)
    assert updated["status"] == "OUT_OF_SERVICE"
