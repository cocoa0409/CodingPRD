"""Pre-order revision loop, production availability gate, resource overlaps, catering.

Each test docstring cites the verbatim PRD sentence it asserts and ends with a
Design: traceability tag mapping it to its originating design-index instance.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    make_flavor, make_size, make_batch, make_station, make_event_cart, make_booking,
    make_pre_order, get_pre_order, get_batch, get_booking,
    api_client, get_success_data,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
SCOOP = TEST_USERS["scooper_headers"]
BAKER = TEST_USERS["baker_headers"]


# ─────────────── non_linear_state_machine / preorder_revision_cycle_back_edge ───────────────

def test_request_revision_returns_in_production_to_confirmed(api):
    """PRD 3.6: "a baker may request a revision on an `IN_PRODUCTION` pre-order,
    sending it from `IN_PRODUCTION` back to `CONFIRMED` so that production can be
    re-checked and restarted; this cyclic path may repeat across multiple revision
    rounds."

    Design: Difficulty/non_linear_state_machine/preorder_revision_cycle_back_edge
    """
    flavor = make_flavor(par_level_ml=300)
    make_batch(flavor["id"], initial_volume_ml=500)  # in stock so start-production passes the gate
    station = make_station()
    po = make_pre_order(flavor["id"], station["id"], quoted_price_cents=4000)
    validate_success(api.confirm_pre_order(po["id"], SCOOP), 200)
    validate_success(api.start_production(po["id"], BAKER), 200)
    revised = validate_success(api.request_revision(po["id"], BAKER), 200)
    assert revised["status"] == "CONFIRMED"


def test_revision_loop_repeats_multiple_rounds(api):
    """PRD 3.6: "this cyclic path may repeat across multiple revision rounds."

    Design: Difficulty/non_linear_state_machine/preorder_revision_cycle_back_edge
    """
    flavor = make_flavor(par_level_ml=300)
    make_batch(flavor["id"], initial_volume_ml=500)
    station = make_station()
    po = make_pre_order(flavor["id"], station["id"], quoted_price_cents=4000)
    validate_success(api.confirm_pre_order(po["id"], SCOOP), 200)
    # Round 1
    validate_success(api.start_production(po["id"], BAKER), 200)
    assert validate_success(api.request_revision(po["id"], BAKER), 200)["status"] == "CONFIRMED"
    # Round 2 — the back-edge is reusable
    assert validate_success(api.start_production(po["id"], BAKER), 200)["status"] == "IN_PRODUCTION"
    assert validate_success(api.request_revision(po["id"], BAKER), 200)["status"] == "CONFIRMED"


# ─────────────── cross_entity_state_dependency / startproduction_requires_flavor_available ───────────────

def test_start_production_blocked_when_flavor_inactive(api):
    """PRD 3.6: "the flavor must have `is_active` true, must be in season if it is
    seasonal (the logical clock within its window, or the flavor non-seasonal), and
    must not be `OUT_OF_STOCK`. A base flavor failing any of these is rejected with
    `ERR_FLAVOR_UNAVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/startproduction_requires_flavor_available
    """
    flavor = make_flavor(par_level_ml=300)
    make_batch(flavor["id"], initial_volume_ml=500)  # in stock -> isolate the is_active condition
    station = make_station()
    po = make_pre_order(flavor["id"], station["id"])
    validate_success(api.confirm_pre_order(po["id"], SCOOP), 200)
    validate_success(api.update_flavor(flavor["id"], {"is_active": False}, MGR), 200)
    validate_error(api.start_production(po["id"], BAKER), "ERR_FLAVOR_UNAVAILABLE")


def test_start_production_blocked_when_flavor_out_of_stock(api):
    """PRD 3.6: "the flavor must have `is_active` true, must be in season if it is
    seasonal (the logical clock within its window, or the flavor non-seasonal), and
    must not be `OUT_OF_STOCK`. A base flavor failing any of these is rejected with
    `ERR_FLAVOR_UNAVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/startproduction_requires_flavor_available
    """
    flavor = make_flavor(par_level_ml=300)  # no batch -> total_available 0 -> OUT_OF_STOCK
    station = make_station()
    po = make_pre_order(flavor["id"], station["id"])
    validate_success(api.confirm_pre_order(po["id"], SCOOP), 200)
    validate_error(api.start_production(po["id"], BAKER), "ERR_FLAVOR_UNAVAILABLE")


# ─────────────── resource_temporal_overlap / event_cart_overlap_halfopen ───────────────

def test_event_cart_true_overlap_rejected(api):
    """PRD 3.7: "the event window must not overlap another booking's window on the
    same cart. Cart windows are half-open, and touching is allowed: a new window
    whose start equals an existing window's end does not collide, but any true
    overlap is rejected with `ERR_CART_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/event_cart_overlap_halfopen
    """
    flavor = make_flavor(par_level_ml=300)
    make_batch(flavor["id"], initial_volume_ml=1000, expiry_at="2026-05-30T00:00:00Z")
    cart = make_event_cart(capacity_ml=5000)
    make_booking(cart["id"], [{"flavor_id": flavor["id"], "volume_ml": 100}],
                 event_start_utc="2026-05-02T10:00:00Z", event_end_utc="2026-05-02T12:00:00Z")
    res = api.create_catering_booking(
        {"event_cart_id": cart["id"], "event_start_utc": "2026-05-02T11:00:00Z",
         "event_end_utc": "2026-05-02T13:00:00Z",
         "requested_items": [{"flavor_id": flavor["id"], "volume_ml": 100}]}, MGR)
    validate_error(res, "ERR_CART_OVERLAP")


def test_event_cart_contained_window_rejected(api):
    """PRD 3.7: "the event window must not overlap another booking's window on the
    same cart ... any true overlap is rejected with `ERR_CART_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/event_cart_overlap_halfopen
    """
    flavor = make_flavor(par_level_ml=300)
    make_batch(flavor["id"], initial_volume_ml=1000, expiry_at="2026-05-30T00:00:00Z")
    cart = make_event_cart(capacity_ml=5000)
    make_booking(cart["id"], [{"flavor_id": flavor["id"], "volume_ml": 100}],
                 event_start_utc="2026-05-02T10:00:00Z", event_end_utc="2026-05-02T12:00:00Z")
    # [10:30,11:30) is fully inside [10:00,12:00) -> a true overlap.
    res = api.create_catering_booking(
        {"event_cart_id": cart["id"], "event_start_utc": "2026-05-02T10:30:00Z",
         "event_end_utc": "2026-05-02T11:30:00Z",
         "requested_items": [{"flavor_id": flavor["id"], "volume_ml": 100}]}, MGR)
    validate_error(res, "ERR_CART_OVERLAP")


# ─────────────── resource_temporal_overlap / station_overlap_buffered_touching_rejected ───────────────

class TestStationCleanBuffer:
    """PRD 3.6: "two pre-orders on the same station must be separated by a clean
    buffer of at least 30 minutes: a new decorating window is accepted only if, for
    every other non-cancelled pre-order on that station, either the new window
    starts at least 30 minutes after that pre-order's window ends or the new window
    ends at least 30 minutes before that pre-order's window starts. Any closer
    spacing — including back-to-back windows that merely touch — collides and is
    rejected with `ERR_STATION_OVERLAP`."""

    def _first(self):
        flavor = make_flavor(par_level_ml=300)
        station = make_station()
        make_pre_order(flavor["id"], station["id"], customer_name="Poe",
                       decorate_start_utc="2026-05-02T10:00:00Z",
                       decorate_end_utc="2026-05-02T12:00:00Z",
                       pickup_utc="2026-05-03T09:00:00Z")
        return flavor, station

    def test_touching_window_rejected(self, api):
        """PRD 3.6: "Any closer spacing — including back-to-back windows that merely
        touch — collides and is rejected with `ERR_STATION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/station_overlap_buffered_touching_rejected
        """
        flavor, station = self._first()
        # [12:00,12:30) starts exactly when A ends: 0-minute gap < 30 -> rejected.
        res = api.create_pre_order(
            {"flavor_id": flavor["id"], "decorating_station_id": station["id"],
             "customer_name": "BB", "decorate_start_utc": "2026-05-02T12:00:00Z",
             "decorate_end_utc": "2026-05-02T12:30:00Z", "pickup_utc": "2026-05-03T10:00:00Z",
             "quoted_price_cents": 4000}, SCOOP)
        validate_error(res, "ERR_STATION_OVERLAP")

    def test_gap_of_exactly_30_minutes_accepted(self, api):
        """PRD 3.6: "a new decorating window is accepted only if ... either the new
        window starts at least 30 minutes after that pre-order's window ends".

        Design: Difficulty/resource_temporal_overlap/station_overlap_buffered_touching_rejected
        """
        flavor, station = self._first()
        # A ends 12:00; B starts 12:30 -> exactly 30 minutes after -> accepted.
        created = validate_success(api.create_pre_order(
            {"flavor_id": flavor["id"], "decorating_station_id": station["id"],
             "customer_name": "BB", "decorate_start_utc": "2026-05-02T12:30:00Z",
             "decorate_end_utc": "2026-05-02T13:30:00Z", "pickup_utc": "2026-05-03T10:00:00Z",
             "quoted_price_cents": 4000}, SCOOP), 201)
        assert created["status"] == "QUOTED"

    def test_gap_of_29_minutes_rejected(self, api):
        """PRD 3.6: "Any closer spacing — including back-to-back windows that merely
        touch — collides and is rejected with `ERR_STATION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/station_overlap_buffered_touching_rejected
        """
        flavor, station = self._first()
        # A ends 12:00; B starts 12:29 -> 29-minute gap < 30 -> rejected.
        res = api.create_pre_order(
            {"flavor_id": flavor["id"], "decorating_station_id": station["id"],
             "customer_name": "BB", "decorate_start_utc": "2026-05-02T12:29:00Z",
             "decorate_end_utc": "2026-05-02T13:29:00Z", "pickup_utc": "2026-05-03T10:00:00Z",
             "quoted_price_cents": 4000}, SCOOP)
        validate_error(res, "ERR_STATION_OVERLAP")


# ─────────────── calculations (corner) / catering_close_actual_pricing_and_commit ───────────────

def test_catering_close_actual_pricing_and_commit(api):
    """PRD 3.7: "The booking prices an `estimate_cents` at the catering rate of 2
    cents per milliliter: it is the sum of the `volume_ml` across all
    `requested_items`, multiplied by 2."
    PRD 3.7: "`committed_volume_ml` rises by the actual amount, and
    `remaining_volume_ml` drops by the actual amount ... and the settled
    `actual_cents` is computed as the sum of actual `volume_ml` multiplied by 2
    cents per milliliter."

    Design: Corner/calculations/catering_close_actual_pricing_and_commit
    """
    flavor = make_flavor(par_level_ml=300)
    batch = make_batch(flavor["id"], initial_volume_ml=1000, expiry_at="2026-05-30T00:00:00Z")
    cart = make_event_cart(capacity_ml=5000)
    booking = make_booking(cart["id"], [{"flavor_id": flavor["id"], "volume_ml": 500}])
    settled = validate_success(api.close_catering_booking(
        booking["id"], {"actual_items": [{"flavor_id": flavor["id"], "volume_ml": 300}]}, MGR), 200)
    assert settled["estimate_cents"] == 1000   # 500 * 2
    assert settled["actual_cents"] == 600      # 300 * 2
    assert settled["status"] == "SETTLED"
    b = get_batch(batch["id"])
    assert b["committed_volume_ml"] == 300
    assert b["remaining_volume_ml"] == 700


# ─────────────── validations (corner) / event_cart_touching_windows_allowed ───────────────

def test_event_cart_touching_windows_allowed(api):
    """PRD 3.7: "Cart windows are half-open, and touching is allowed: a new window
    whose start equals an existing window's end does not collide, but any true
    overlap is rejected with `ERR_CART_OVERLAP`."

    Design: Corner/validations/event_cart_touching_windows_allowed
    """
    flavor = make_flavor(par_level_ml=300)
    make_batch(flavor["id"], initial_volume_ml=1000, expiry_at="2026-05-30T00:00:00Z")
    cart = make_event_cart(capacity_ml=5000)
    make_booking(cart["id"], [{"flavor_id": flavor["id"], "volume_ml": 100}],
                 event_start_utc="2026-05-02T10:00:00Z", event_end_utc="2026-05-02T12:00:00Z")
    # [12:00,14:00) starts exactly when A ends -> touching, allowed.
    created = validate_success(api.create_catering_booking(
        {"event_cart_id": cart["id"], "event_start_utc": "2026-05-02T12:00:00Z",
         "event_end_utc": "2026-05-02T14:00:00Z",
         "requested_items": [{"flavor_id": flavor["id"], "volume_ml": 100}]}, MGR), 201)
    assert created["status"] == "BOOKED"
    assert created["estimate_cents"] == 200
