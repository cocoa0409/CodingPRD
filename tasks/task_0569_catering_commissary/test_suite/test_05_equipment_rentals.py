"""Equipment reservations and aggregate-capacity availability.

Translates queue-A instances (resource_temporal_overlap/equipment_aggregate_capacity_exceeded,
compensating_invariant/equipment_units_conserved_on_reserve_cancel) and queue-B corner
instances (calculations, validations).
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.constants import dt
from test_helpers.factories import create_rental_reservation_payload


# --------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / equipment_aggregate_capacity_exceeded
# --------------------------------------------------------------------------
def test_overlapping_reservations_exceed_capacity_rejected(api, event_captain_headers):
    """PRD §3.5: "A new reservation of `qty` units is feasible only if, at every instant
    of its window, the already-overlapping `ACTIVE` reserved quantity plus the new `qty`
    stays within `total_units`. When it would exceed `total_units`, the reservation is
    rejected with `ERR_EQUIPMENT_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/equipment_aggregate_capacity_exceeded
    """
    ctx = fx.confirmed_order_with_equipment(api, total_units=10)
    fx.reserve_equipment(api, ctx["order_id"], ctx["equipment_id"], qty=6, out_time=dt(10), return_time=dt(16))
    resp = api.create_rental_reservation(
        create_rental_reservation_payload(ctx["order_id"], ctx["equipment_id"], qty=6,
                                          out_time=dt(12), return_time=dt(14)),
        event_captain_headers,
    )
    validate_error(resp, ApiErrorId.ERR_EQUIPMENT_UNAVAILABLE)  # 6 + 6 = 12 > 10 at overlap


def test_nonoverlapping_reservation_within_pool_succeeds(api, event_captain_headers):
    """PRD §3.5: "two intervals overlap only when each starts strictly before the other
    ends ... touching endpoints do not overlap."
    PRD §2.10: "one interval's end instant that exactly equals another's start instant
    does **not** count as an overlap, so a chafer returned at exactly the moment another
    reservation begins is available."

    Design: Difficulty/resource_temporal_overlap/equipment_aggregate_capacity_exceeded
    """
    ctx = fx.confirmed_order_with_equipment(api, total_units=10)
    fx.reserve_equipment(api, ctx["order_id"], ctx["equipment_id"], qty=6, out_time=dt(10), return_time=dt(16))
    # Second window [16:00, 20:00) touches the first at 16:00 -> half-open, no overlap.
    data = validate_success(
        api.create_rental_reservation(
            create_rental_reservation_payload(ctx["order_id"], ctx["equipment_id"], qty=6,
                                              out_time=dt(16), return_time=dt(20)),
            event_captain_headers),
        201,
    )
    assert data["status"] == "ACTIVE"


# --------------------------------------------------------------------------
# Difficulty: compensating_invariant / equipment_units_conserved_on_reserve_cancel
# --------------------------------------------------------------------------
def test_reservation_cancel_sets_cancelled(api, event_captain_headers):
    """PRD §3.5: "A reservation can be cancelled, moving it `ACTIVE → CANCELLED`, which
    frees the reserved `qty` back over the window so that availability is restored."

    Design: Difficulty/compensating_invariant/equipment_units_conserved_on_reserve_cancel
    """
    ctx = fx.confirmed_order_with_equipment(api, total_units=10)
    reservation = fx.reserve_equipment(api, ctx["order_id"], ctx["equipment_id"], qty=6,
                                       out_time=dt(10), return_time=dt(16))
    data = validate_success(api.cancel_reservation(reservation["id"], event_captain_headers))
    assert data["status"] == "CANCELLED", f"cancelled reservation must be CANCELLED, got {data['status']}"


def test_reservation_cancel_restores_full_availability(api, event_captain_headers):
    """PRD §3.5: "A reservation can be cancelled, moving it `ACTIVE → CANCELLED`, which
    frees the reserved `qty` back over the window so that availability is restored."
    PRD §3.5: "that read reports the free unit count as `available_units` alongside the
    pool's `total_units`"

    Design: Difficulty/compensating_invariant/equipment_units_conserved_on_reserve_cancel
    """
    ctx = fx.confirmed_order_with_equipment(api, total_units=10)
    reservation = fx.reserve_equipment(api, ctx["order_id"], ctx["equipment_id"], qty=6,
                                       out_time=dt(10), return_time=dt(16))
    validate_success(api.cancel_reservation(reservation["id"], event_captain_headers))
    data = validate_success(
        api.get_equipment_availability(ctx["equipment_id"], event_captain_headers,
                                       params={"out_time": dt(10), "return_time": dt(16)})
    )
    assert data["available_units"] == 10, f"availability must return to full pool 10, got {data['available_units']}"


# --------------------------------------------------------------------------
# Corner: calculations / validations
# --------------------------------------------------------------------------
def test_equipment_availability_read_full_pool_when_unreserved(api, event_captain_headers):
    """PRD §3.5: "that read reports the free unit count as `available_units` alongside the
    pool's `total_units`, and accepts an optional `out_time` and `return_time` describing
    the window to evaluate."

    Design: Corner/calculations/equipment_availability_read_full_pool_when_unreserved
    """
    equipment = fx.create_equipment_item(api, total_units=10, rental_price_cents=500)
    data = validate_success(
        api.get_equipment_availability(equipment["id"], event_captain_headers,
                                       params={"out_time": dt(10), "return_time": dt(16)})
    )
    assert data["available_units"] == 10, f"unreserved pool must report 10 free, got {data['available_units']}"
    assert data["total_units"] == 10


def test_equipment_reservation_exactly_fills_capacity_succeeds(api, event_captain_headers):
    """PRD §3.5: "A new reservation of `qty` units is feasible only if, at every instant
    of its window, the already-overlapping `ACTIVE` reserved quantity plus the new `qty`
    stays within `total_units`."

    Design: Corner/validations/equipment_reservation_exactly_fills_capacity_succeeds
    """
    ctx = fx.confirmed_order_with_equipment(api, total_units=10)
    fx.reserve_equipment(api, ctx["order_id"], ctx["equipment_id"], qty=6, out_time=dt(10), return_time=dt(16))
    # 6 + 4 = 10 at overlap, exactly at capacity -> accepted.
    data = validate_success(
        api.create_rental_reservation(
            create_rental_reservation_payload(ctx["order_id"], ctx["equipment_id"], qty=4,
                                              out_time=dt(12), return_time=dt(14)),
            event_captain_headers),
        201,
    )
    assert data["status"] == "ACTIVE"
