"""Delivery release fences (cutoff, standing-order state, route-window buffer) and
catering pre-order slot-overlap capacity."""
import pytest

from test_helpers import (
    api_client as _ac,
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    wholesale_line,
    setup_account_with_standing_order,
    create_production_day, schedule_delivery,
    create_product, create_wholesale_account, create_standing_order,
    create_pre_order,
)

ADMIN = TEST_USERS["shop_admin_headers"]


# =====================================================================
# Difficulty/resource_temporal_overlap/route_window_buffer_adjacency_conflict (2)
# =====================================================================
def test_route_window_within_buffer_conflicts(api):
    """PRD §3.7: "considering each existing delivery for that account on the day whose
    status is SCHEDULED, PICKED, or DELIVERED, the new stop collides if the proposed
    start is no later than the existing window's end plus a thirty-minute buffer and the
    existing window's start is no later than the proposed window's end plus that same
    buffer. Any single such collision rejects the release with ERR_ROUTE_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/route_window_buffer_adjacency_conflict
    """
    account, so1, products = setup_account_with_standing_order(
        [("GLAZED", 12)], delivery_dow=4)
    so2 = create_standing_order(account["id"],
                                [wholesale_line(products["GLAZED"]["id"], 12)], 4)
    day = create_production_day()
    schedule_delivery(day["id"], so1["id"],
                      "2027-06-05T08:00:00Z", "2027-06-05T09:00:00Z")
    # Second stop 09:15-10:00: gap 15 min < 30 buffer -> conflict.
    resp = _ac.create_wholesale_delivery(
        day["id"],
        {"standing_order_id": so2["id"],
         "route_window_start": "2027-06-05T09:15:00Z",
         "route_window_end": "2027-06-05T10:00:00Z"},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_ROUTE_WINDOW_CONFLICT.value)


def test_route_window_beyond_buffer_coexists(api):
    """PRD §3.7: "The buffer closes the gap, so two stops must be separated by strictly
    more than thirty minutes to coexist; back-to-back and near-adjacent stops both reject."

    Design: Difficulty/resource_temporal_overlap/route_window_buffer_adjacency_conflict
    """
    account, so1, products = setup_account_with_standing_order(
        [("GLAZED", 12)], delivery_dow=4)
    so2 = create_standing_order(account["id"],
                                [wholesale_line(products["GLAZED"]["id"], 12)], 4)
    day = create_production_day()
    schedule_delivery(day["id"], so1["id"],
                      "2027-06-05T08:00:00Z", "2027-06-05T09:00:00Z")
    # Second stop 09:31-10:00: gap 31 min > 30 buffer -> allowed.
    second = schedule_delivery(day["id"], so2["id"],
                               "2027-06-05T09:31:00Z", "2027-06-05T10:00:00Z")
    assert second["status"] == "SCHEDULED", (
        "stops separated by strictly more than 30 minutes must coexist")


# =====================================================================
# Difficulty/resource_temporal_overlap/catering_slot_capacity_overlap_full (2)
# =====================================================================
def _catering_account_and_day():
    glazed = create_product("GLAZED")
    account = create_wholesale_account(name="Party Co", discount_pct=0.10)
    day = create_production_day()
    return glazed, account, day


def test_third_overlapping_preorder_rejected(api):
    """PRD §3.8: "Count, over all non-CANCELLED pre-orders sharing the same
    pickup_production_day_id, how many overlap the candidate window. If that count is
    already at or above the slot capacity of 2, the creation is rejected with
    ERR_CATERING_SLOT_FULL."

    Design: Difficulty/resource_temporal_overlap/catering_slot_capacity_overlap_full
    """
    glazed, account, day = _catering_account_and_day()
    create_pre_order(account["id"], day["id"], "2027-08-01T10:00:00Z",
                     "2027-08-01T11:00:00Z", [wholesale_line(glazed["id"], 12)])
    create_pre_order(account["id"], day["id"], "2027-08-01T10:30:00Z",
                     "2027-08-01T11:30:00Z", [wholesale_line(glazed["id"], 12)])
    resp = _ac.create_pre_order(
        {"wholesale_account_id": account["id"], "pickup_production_day_id": day["id"],
         "pickup_window_start": "2027-08-01T10:45:00Z",
         "pickup_window_end": "2027-08-01T11:15:00Z",
         "line_items": [wholesale_line(glazed["id"], 12)]},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_CATERING_SLOT_FULL.value)


def test_non_overlapping_preorder_admitted_after_two(api):
    """PRD §3.8: "Treating each pickup window as the half-open interval from its start
    (inclusive) to its end (exclusive), the candidate window overlaps an existing one
    when the candidate start is strictly before the existing end and the existing start
    is strictly before the candidate end — a window that ends exactly when another
    begins does not overlap."

    Design: Difficulty/resource_temporal_overlap/catering_slot_capacity_overlap_full
    """
    glazed, account, day = _catering_account_and_day()
    create_pre_order(account["id"], day["id"], "2027-08-02T10:00:00Z",
                     "2027-08-02T11:00:00Z", [wholesale_line(glazed["id"], 12)])
    create_pre_order(account["id"], day["id"], "2027-08-02T10:30:00Z",
                     "2027-08-02T11:30:00Z", [wholesale_line(glazed["id"], 12)])
    # Candidate starts at 11:30, exactly when an existing window ends -> no overlap.
    third = create_pre_order(account["id"], day["id"], "2027-08-02T11:30:00Z",
                             "2027-08-02T12:30:00Z", [wholesale_line(glazed["id"], 12)])
    assert third["status"] == "REQUESTED", (
        "a window that starts exactly when another ends does not overlap")


# =====================================================================
# Difficulty/priority_pair_validation_conflict/
#   schedule_cutoff_temporal_vs_standing_order_state (2)
# =====================================================================
def _paused_standing_order_with_clock(cutoff, clock):
    glazed = create_product("GLAZED")
    account = create_wholesale_account(discount_pct=0.15)
    so = create_standing_order(account["id"], [wholesale_line(glazed["id"], 12)], 1)
    validate_success(_ac.pause_standing_order(so["id"], ADMIN))
    day = validate_success(_ac.create_production_day(
        {"business_date": "2027-09-10", "delivery_cutoff_utc": cutoff}, ADMIN), 201)
    validate_success(_ac.set_clock({"to_iso8601": clock}, ADMIN))
    return so, day


def test_schedule_past_cutoff_with_paused_so_returns_cutoff_error(api):
    """PRD §3.7: "First, the day must not already be in CUTOFF or RECONCILED, and the
    logical clock must not be past the day's delivery_cutoff_utc (else
    ERR_PAST_DELIVERY_CUTOFF). Second, the named standing order must be ACTIVE, not
    PAUSED or CANCELLED (else ERR_STANDING_ORDER_NOT_ACTIVE)."

    Design: Difficulty/priority_pair_validation_conflict/schedule_cutoff_temporal_vs_standing_order_state
    """
    so, day = _paused_standing_order_with_clock(
        "2027-09-10T12:00:00Z", "2027-09-10T18:00:00Z")
    resp = _ac.create_wholesale_delivery(
        day["id"],
        {"standing_order_id": so["id"],
         "route_window_start": "2027-09-10T19:00:00Z",
         "route_window_end": "2027-09-10T20:00:00Z"},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_PAST_DELIVERY_CUTOFF.value)


def test_schedule_past_cutoff_not_standing_order_error(api):
    """PRD §3.7: "Releasing a delivery is fenced by several preconditions, applied in
    this order. First, the day must not already be in CUTOFF or RECONCILED, and the
    logical clock must not be past the day's delivery_cutoff_utc (else
    ERR_PAST_DELIVERY_CUTOFF)."

    Design: Difficulty/priority_pair_validation_conflict/schedule_cutoff_temporal_vs_standing_order_state
    """
    so, day = _paused_standing_order_with_clock(
        "2027-09-11T12:00:00Z", "2027-09-11T18:00:00Z")
    err = validate_error(
        _ac.create_wholesale_delivery(
            day["id"],
            {"standing_order_id": so["id"],
             "route_window_start": "2027-09-11T19:00:00Z",
             "route_window_end": "2027-09-11T20:00:00Z"},
            ADMIN),
        ApiErrorId.ERR_PAST_DELIVERY_CUTOFF.value)
    assert err["error_id"] != ApiErrorId.ERR_STANDING_ORDER_NOT_ACTIVE.value


# =====================================================================
# Corner/validations/schedule_after_cutoff_clock_rejected  (1)
# =====================================================================
def test_schedule_after_cutoff_clock_active_so_rejected(api):
    """PRD §3.7: "the logical clock must not be past the day's delivery_cutoff_utc (else
    ERR_PAST_DELIVERY_CUTOFF)."

    Design: Corner/validations/schedule_after_cutoff_clock_rejected
    """
    account, so, _products = setup_account_with_standing_order([("GLAZED", 12)],
                                                               delivery_dow=3)
    day = validate_success(_ac.create_production_day(
        {"business_date": "2027-09-12", "delivery_cutoff_utc": "2027-09-12T12:00:00Z"},
        ADMIN), 201)
    validate_success(_ac.set_clock({"to_iso8601": "2027-09-12T18:00:00Z"}, ADMIN))
    resp = _ac.create_wholesale_delivery(
        day["id"],
        {"standing_order_id": so["id"],
         "route_window_start": "2027-09-12T19:00:00Z",
         "route_window_end": "2027-09-12T20:00:00Z"},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_PAST_DELIVERY_CUTOFF.value)


# =====================================================================
# Corner/validations/release_paused_standing_order_rejected  (1)
# =====================================================================
def test_release_paused_standing_order_before_cutoff_rejected(api):
    """PRD §3.7: "Second, the named standing order must be ACTIVE, not PAUSED or
    CANCELLED (else ERR_STANDING_ORDER_NOT_ACTIVE)."

    Design: Corner/validations/release_paused_standing_order_rejected
    """
    account, so, _products = setup_account_with_standing_order([("GLAZED", 12)],
                                                               delivery_dow=3)
    validate_success(_ac.pause_standing_order(so["id"], ADMIN))
    day = create_production_day()  # default far-future cutoff, clock at default
    resp = _ac.create_wholesale_delivery(
        day["id"],
        {"standing_order_id": so["id"],
         "route_window_start": "2027-06-06T08:00:00Z",
         "route_window_end": "2027-06-06T09:00:00Z"},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_STANDING_ORDER_NOT_ACTIVE.value)


# =====================================================================
# Corner/errors/invalid_window_end_before_start_rejected  (1)
# =====================================================================
def test_preorder_window_end_before_start_rejected(api):
    """PRD §2.7: "any endpoint that accepts a start/end window pair (a route stop window
    or a catering pickup window) requires the end to be strictly after the start;
    otherwise the request is rejected with ERR_INVALID_WINDOW (HTTP 422)."

    Design: Corner/errors/invalid_window_end_before_start_rejected
    """
    glazed = create_product("GLAZED")
    account = create_wholesale_account(name="Party Co", discount_pct=0.10)
    day = create_production_day()
    resp = _ac.create_pre_order(
        {"wholesale_account_id": account["id"], "pickup_production_day_id": day["id"],
         "pickup_window_start": "2027-08-03T10:00:00Z",
         "pickup_window_end": "2027-08-03T09:00:00Z",
         "line_items": [wholesale_line(glazed["id"], 12)]},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)
