"""Referential, temporal, and fiscal validations plus the named error-code
trigger conditions (waitlist-not-head, sales-not-present, day-not-open, occupied).

Covers the corner `validations` and `errors` section instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    make_vendor_headers, TEST_USERS,
    create_market, create_booth, create_vendor, create_active_vendor,
    create_open_market_day, create_market_day, reserve_season_assignment,
    reserve_daily_assignment, waitlist_season_assignment,
    setup_season_held_two_waitlisters, setup_open_day_with_batch,
    submit_redemption, create_check_in_payload, create_booth_assignment_payload,
    booth_version,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Corner: validations section
# ---------------------------------------------------------------------------
def test_daily_assignment_missing_market_day_returns_referential_mismatch(api):
    """PRD 3.3: "A DAILY request must additionally carry the market_day_id of the
    day it covers, while a SEASON request must omit it; supplying a market_day_id
    on a season request, or omitting it on a daily request, is rejected with
    ERR_REFERENTIAL_MISMATCH."

    Design: Corner/validations/daily_assignment_missing_market_day_returns_referential_mismatch
    """
    market = create_market()
    booth = create_booth(market["id"], label="S-1", grid_row=0, grid_col=1, size_class="SINGLE")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")
    vh = make_vendor_headers(vendor["id"])
    res = api.create_booth_assignment(
        {"market_id": market["id"], "booth_id": booth["id"], "vendor_id": vendor["id"],
         "assignment_type": "DAILY"}, vh)
    validate_error(res, "ERR_REFERENTIAL_MISMATCH")


def test_redemption_day_must_equal_batch_day(api):
    """PRD 3.7: "The redemption's market_day_id must equal the batch's
    market_day_id, failing which the request is rejected with
    ERR_REFERENTIAL_MISMATCH."

    Design: Corner/validations/redemption_day_must_equal_batch_day
    """
    market = create_market()
    vendor = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    day_a = create_open_market_day(market["id"], market_date="2026-06-06")
    day_b = create_open_market_day(market["id"], market_date="2026-06-13")
    batch = get_success_data(api.create_voucher_batch(
        {"market_id": market["id"], "market_day_id": day_a["id"], "tokens_issued": 100}, MANAGER))
    vh = make_vendor_headers(vendor["id"])
    res = api.create_voucher_redemption(
        {"market_id": market["id"], "voucher_batch_id": batch["id"], "vendor_id": vendor["id"],
         "market_day_id": day_b["id"], "token_count": 10}, vh)
    validate_error(res, "ERR_REFERENTIAL_MISMATCH")


def test_market_day_outside_season_window_rejected(api):
    """PRD 3.1: "a market_date (YYYY-MM-DD) that must fall within the season window
    — on or after season_start_date and on or before season_end_date, inclusive ...
    A date outside the season window is rejected with ERR_OUTSIDE_WINDOW".

    Design: Corner/validations/market_day_outside_season_window_rejected
    """
    market = create_market()  # season 2026-06-01 .. 2026-09-30
    res = api.create_market_day({"market_id": market["id"], "market_date": "2026-10-15"}, ADMIN)
    validate_error(res, "ERR_OUTSIDE_WINDOW")


def test_gross_sales_negative_returns_invalid_request(api):
    """PRD 2.11: "numeric bounds satisfied such as gross_sales_cents being at least
    0 ... (ERR_INVALID_REQUEST)." gross_sales_cents=-1 violates the >=0 bound.

    Design: Corner/validations/gross_sales_negative_returns_invalid_request
    """
    market = create_market()
    booth = create_booth(market["id"], label="S-1", grid_row=0, grid_col=1, size_class="SINGLE")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    asg = reserve_daily_assignment(market["id"], booth["id"], vendor["id"], day["id"])
    vh = make_vendor_headers(vendor["id"])
    ci = get_success_data(api.create_check_in(
        create_check_in_payload(market["id"], asg["id"], day["id"]), vh))
    get_success_data(api.arrive_check_in(ci["id"], vh))

    res = api.create_sales_report(
        {"market_id": market["id"], "check_in_id": ci["id"],
         "gross_sales_cents": -1, "tokens_accepted": 0}, vh)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_season_request_occupied_no_waitlist_returns_occupied(api):
    """PRD 3.3: "when a client explicitly sets it to false and the slot is
    occupied, no waitlist row is created and the request is instead rejected
    outright with ERR_BOOTH_OCCUPIED."

    Design: Corner/validations/booth_occupied_with_waitlist_disabled_returns_occupied
    """
    market = create_market()
    booth = create_booth(market["id"], label="C-1", grid_row=0, grid_col=1, size_class="CORNER")
    v1 = create_active_vendor(market["id"], "CRAFTS", "V1", "v1@x.com")
    v2 = create_active_vendor(market["id"], "FLOWERS", "V2", "v2@x.com")
    reserve_season_assignment(market["id"], booth["id"], v1["id"])
    vh2 = make_vendor_headers(v2["id"])

    res = api.create_booth_assignment(
        create_booth_assignment_payload(market["id"], booth["id"], v2["id"],
                                        assignment_type="SEASON", allow_waitlist=False,
                                        expected_booth_version=booth_version(booth["id"])), vh2)
    validate_error(res, "ERR_BOOTH_OCCUPIED")


# ---------------------------------------------------------------------------
# Corner: errors section
# ---------------------------------------------------------------------------
def test_promote_non_head_waitlister_returns_waitlist_not_head(api):
    """PRD 3.3: "an attempt to promote an assignment whose waitlist_rank is not 1,
    or whose slot is still occupied, is rejected with ERR_WAITLIST_NOT_HEAD."

    Design: Corner/errors/promote_non_head_waitlister_returns_waitlist_not_head
    """
    s = setup_season_held_two_waitlisters()
    res = api.promote_booth_assignment(s["asg3"]["id"], ADMIN)  # rank-2, slot occupied
    validate_error(res, "ERR_WAITLIST_NOT_HEAD")


def test_submit_sales_report_not_present_returns_sales_not_present(api):
    """PRD 3.8: "when the linked check-in is PRESENT — only attended days may
    report sales, and a submit whose check-in is not PRESENT is rejected with
    ERR_SALES_NOT_PRESENT".

    Design: Corner/errors/submit_sales_report_not_present_returns_sales_not_present
    """
    market = create_market()
    booth = create_booth(market["id"], label="S-1", grid_row=0, grid_col=1, size_class="SINGLE")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    asg = reserve_daily_assignment(market["id"], booth["id"], vendor["id"], day["id"])
    vh = make_vendor_headers(vendor["id"])
    ci = get_success_data(api.create_check_in(
        create_check_in_payload(market["id"], asg["id"], day["id"]), vh))  # EXPECTED, never arrived
    sr = get_success_data(api.create_sales_report(
        {"market_id": market["id"], "check_in_id": ci["id"],
         "gross_sales_cents": 10000, "tokens_accepted": 0}, vh))

    res = api.submit_sales_report(sr["id"], {}, vh)
    validate_error(res, "ERR_SALES_NOT_PRESENT")


def test_reconcile_redemption_on_cancelled_day_rejected(api):
    """PRD 3.7: "Reconciliation is legal only when the redemption is SUBMITTED and
    the owning market day is OPEN or CLOSED but not CANCELLED — a reconcile against
    a cancelled day is rejected with ERR_DAY_NOT_OPEN." PRD 3.6 also reverses the
    SUBMITTED redemption on cancellation ("Every voucher redemption for the day
    that is RECONCILED or SUBMITTED is reversed to REVERSED"), so a PRD-only reader
    could surface ERR_INVALID_STATE (the redemption is no longer SUBMITTED) instead;
    both are PRD-faithful outcomes.

    Design: Corner/errors/reconcile_redemption_on_cancelled_day_returns_day_not_open
    """
    base = setup_open_day_with_batch(tokens_issued=100)
    red = submit_redemption(base["market"]["id"], base["batch"]["id"],
                            base["vendor"]["id"], base["day"]["id"], 10)
    validate_success(
        api.cancel_market_day(base["day"]["id"], {"cancellation_reason": "SAFETY"}, ADMIN), 200)

    res = api.reconcile_voucher_redemption(red["id"], MANAGER)
    validate_error_is_one_of(res, ["ERR_DAY_NOT_OPEN", "ERR_INVALID_STATE"])
