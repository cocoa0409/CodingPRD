"""Cross-entity state dependencies (pairing report needs IN_PROGRESS event,
pre-order fulfill needs RELEASED product) and resource temporal overlap (customer
double-booking, venue table buffer overlap on open).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_customer, create_open_event, create_registration,
    create_release_product, create_allocated_pre_order,
    setup_in_progress_event_with_two_players, create_pairing, report_pairing,
    create_event, set_clock,
    ApiErrorId, TEST_USERS, make_customer_headers,
)

SM = TEST_USERS["store_manager_headers"]
JUDGE = TEST_USERS["judge_headers"]


# ─── cross_entity_state_dependency (difficulty) ─────────────────────────────────
def test_report_pairing_after_event_complete_rejected(api):
    """PRD §3.5: "Reporting a result is a judge-staff action that requires the parent
    event to be `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`) and moves the pairing's
    `result` out of `PENDING`."

    Design: Difficulty/cross_entity_state_dependency/pairing_report_requires_event_in_progress
    """
    ev, ca, cb, ra, rb = setup_in_progress_event_with_two_players(
        starts_at="2026-07-01T00:00:00Z", ends_at="2026-07-01T05:00:00Z")
    pr = create_pairing(ev, ra, rb)
    report_pairing(pr, "A_WINS")  # round complete
    validate_success(api.complete_event(ev["id"], JUDGE), 200)
    # Event is now COMPLETE; re-reporting the same pairing is rejected.
    res = api.report_pairing(pr["id"], {"result": "DRAW"}, JUDGE)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_fulfill_preorder_before_release_live_rejected(api):
    """PRD §3.3: "Fulfillment is a store-manager action defined only from
    `ALLOCATED`. The parent release product must be `RELEASED`, or the request fails
    with `ERR_RELEASE_NOT_LIVE`."

    Design: Difficulty/cross_entity_state_dependency/preorder_fulfill_requires_release_live
    """
    cust = create_customer("Fulfil Cust", "ful@x.com", credit_cents=100000)
    rp = create_release_product(title="Not Live Box", allocation_pool=10,
                                unit_price_cents=2000, deposit_required_cents=1000)
    po, rp_after = create_allocated_pre_order(cust, rp, requested_quantity=2,
                                              deposit_paid_cents=1000)
    # Release still PRE_ORDER_OPEN → fulfill rejected.
    res = api.fulfill_pre_order(po["id"], SM)
    validate_error(res, ApiErrorId.ERR_RELEASE_NOT_LIVE)


# ─── resource_temporal_overlap (difficulty) ─────────────────────────────────────
def test_customer_double_booking_overlap_rejected(api):
    """PRD §3.4: "A customer also may not hold two non-`WITHDRAWN` registrations for
    events whose `[starts_at, ends_at)` intervals overlap; the interval is half-open,
    so two events that merely touch at a shared endpoint (one ending exactly when
    another begins) do not conflict, but any true overlap is rejected with
    `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/customer_double_booking_halfopen_overlap
    """
    set_clock("2026-06-01T00:00:00Z")
    cust = create_customer("Busy Cust", "busy@x.com")
    eva = create_open_event(title="Event A", format="STANDARD",
                            starts_at="2026-06-10T08:00:00Z",
                            ends_at="2026-06-10T12:00:00Z", capacity=8,
                            entry_fee_cents=1000)
    evb = create_open_event(title="Event B", format="MODERN",
                            starts_at="2026-06-10T10:00:00Z",
                            ends_at="2026-06-10T14:00:00Z", capacity=8,
                            entry_fee_cents=1000)
    create_registration(eva, cust)
    res = api.create_registration(
        {"event_id": evb["id"], "customer_id": cust["id"]},
        make_customer_headers(cust["id"]))
    validate_error(res, ApiErrorId.ERR_SCHEDULE_CONFLICT)


def test_venue_table_buffer_overlap_on_open_rejected(api):
    """PRD §3.5: "opening must not cause concurrent play-table usage to exceed 8
    tables over the event's window padded by a 30-minute buffer on each side — that
    is, the window from 30 minutes before `starts_at` to 30 minutes after `ends_at`.
    The buffer-padded window is treated strictly, so adjacency within the buffer is
    not allowed; any other non-terminal event whose padded window overlaps this one,
    such that their combined `tables_required` would exceed 8 concurrent tables,
    blocks the open with `ERR_VENUE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/venue_table_buffer_overlap_on_open
    """
    set_clock("2026-06-01T00:00:00Z")
    # First event uses all 8 tables 12:00-16:00 and is opened.
    big = create_open_event(title="Big GP", format="STANDARD",
                            starts_at="2026-06-10T12:00:00Z",
                            ends_at="2026-06-10T16:00:00Z", capacity=64,
                            entry_fee_cents=5000, tables_required=8)
    # Second event needs 1 table at 16:15 — within the 30-min buffer of the first.
    side = create_event(title="Late Side Event", format="COMMANDER",
                        starts_at="2026-06-10T16:15:00Z",
                        ends_at="2026-06-10T18:00:00Z", capacity=8,
                        entry_fee_cents=1000, tables_required=1)
    res = api.open_event(side["id"], SM)
    validate_error(res, ApiErrorId.ERR_VENUE_OVERLAP)
