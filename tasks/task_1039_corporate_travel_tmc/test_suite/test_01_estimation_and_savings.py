"""Provisional-vs-actual cost divergence and vendor savings reporting.

Each docstring cites the verbatim PRD sentence it asserts and ends with a
traceability tag mapping it to its originating design-index instance.
"""
from test_helpers import (
    validate_success,
    make_approved_trip, book, trip_version,
    TEST_USERS,
)

MGR = TEST_USERS["travel_manager_headers"]


def test_trip_provisional_estimate_uses_cheapest_negotiated_fare(api):
    """PRD §3.2: "If at least one candidate exists, `estimated_cost_cents` is set to
    the cheapest candidate's `negotiated_fare_cents`; if none exists,
    `estimated_cost_cents` falls back to the trip's own `market_estimate_cents`."

    Design: Difficulty/dual_variant_calc/trip_estimate_vs_actual_cost_diverges
    """
    ctx = make_approved_trip(with_rate=True, market_estimate=420000)
    trip, trav, ven = ctx["trip"], ctx["traveler"], ctx["vendor"]
    book(trip["id"], trav["id"], trip["version"], vendor_id=ven["id"],
         segment_type="AIR", fare_basis="REFUNDABLE", fare_cents=300000)
    got = validate_success(api.get_trip_request(trip["id"], MGR))
    assert got["estimated_cost_cents"] == 250000, (
        f"provisional estimate should be the cheapest negotiated fare 250000, "
        f"got {got['estimated_cost_cents']}"
    )


def test_trip_actual_cost_diverges_from_forward_looking_estimate(api):
    """PRD §3.3: "The trip's `actual_cost_cents` is recomputed: it is the chronological
    running sum, over every booking of the trip whose status is `TICKETED` or
    `EXCHANGED`, of that booking's `fare_cents` less its `credit_applied_cents`
    (cancelled and refunded segments contribute nothing)."

    Design: Difficulty/dual_variant_calc/trip_estimate_vs_actual_cost_diverges
    """
    ctx = make_approved_trip(with_rate=True, market_estimate=420000)
    trip, trav, ven = ctx["trip"], ctx["traveler"], ctx["vendor"]
    # Booked WITHOUT the negotiated rate at a higher fare than the estimate.
    book(trip["id"], trav["id"], trip["version"], vendor_id=ven["id"],
         segment_type="AIR", fare_basis="REFUNDABLE", fare_cents=300000)
    got = validate_success(api.get_trip_request(trip["id"], MGR))
    assert got["actual_cost_cents"] == 300000, (
        f"actual cost should sum the ticketed fare 300000, got {got['actual_cost_cents']}"
    )
    assert got["estimated_cost_cents"] != got["actual_cost_cents"], (
        "provisional estimate and final actual cost must diverge in this scenario"
    )


def test_estimate_uses_market_fallback_when_no_rate_matches(api):
    """PRD §3.2: "if none exists, `estimated_cost_cents` falls back to the trip's own
    `market_estimate_cents`."
    PRD §3.2: "if `estimated_cost_cents` is at or above `requires_exec_approval_over_cents`,
    the level is `EXEC`; otherwise if it is at or above `requires_manager_approval_over_cents`,
    the level is `MANAGER`; otherwise it is `NONE`. When the level is `NONE`, submission moves
    the trip straight to `APPROVED`."

    Design: Corner/calculations/estimate_uses_market_fallback_when_no_rate_matches
    """
    ctx = make_approved_trip(with_rate=False, market_estimate=75000,
                             trip_overrides={"destination": "SFO"})
    trip = ctx["trip"]
    assert trip["estimated_cost_cents"] == 75000, (
        f"estimate should fall back to market_estimate 75000, got {trip['estimated_cost_cents']}"
    )
    assert trip["approval_level_required"] == "NONE"
    assert trip["status"] == "APPROVED"


def _setup_two_vendor_bookings(api):
    """Rate-consuming booking A (fare 250000) + non-rate booking B (fare 300000)."""
    ctx = make_approved_trip(with_rate=True, market_estimate=420000,
                             trip_overrides={"return_date": "2026-08-20T09:00:00Z"})
    trip, trav, ven, rate = ctx["trip"], ctx["traveler"], ctx["vendor"], ctx["rate"]
    book(trip["id"], trav["id"], trip["version"], vendor_id=ven["id"],
         negotiated_rate_id=rate["id"], segment_type="AIR", fare_basis="REFUNDABLE",
         fare_cents=250000, depart_datetime="2026-08-01T09:00:00Z",
         return_datetime="2026-08-01T20:00:00Z")
    v2 = trip_version(trip["id"], trav["id"])
    book(trip["id"], trav["id"], v2, vendor_id=ven["id"], segment_type="AIR",
         fare_basis="REFUNDABLE", fare_cents=300000,
         depart_datetime="2026-08-10T09:00:00Z", return_datetime="2026-08-10T20:00:00Z")
    return ven


def test_vendor_realized_savings_counts_only_rate_consuming_bookings(api):
    """PRD §3.7: "over every booking in `TICKETED` or `EXCHANGED` status whose
    `negotiated_rate_id` is set and whose rate belongs to this vendor, it sums the
    rate's `market_fare_cents` minus the booking's `fare_cents`."

    Design: Difficulty/dual_variant_calc/vendor_realized_vs_potential_savings_diverges
    """
    ven = _setup_two_vendor_bookings(api)
    report = validate_success(api.get_savings_report(ven["id"], MGR))
    assert report["realized_savings_cents"] == 150000, (
        f"realized savings counts only the rate-consuming booking (400000-250000), "
        f"got {report['realized_savings_cents']}"
    )
    assert report["booked_count"] == 2, f"two vendor bookings, got {report['booked_count']}"


def test_vendor_potential_savings_counts_every_vendor_booking(api):
    """PRD §3.7: "over every `TICKETED` or `EXCHANGED` booking whose `vendor_id` is
    this vendor, it sums the best market fare minus the best negotiated fare, where
    the best rate is the cheapest negotiated rate of this vendor matching that
    booking's route ranked by `negotiated_fare_cents` ascending then `created_at`
    ascending; a booking for which the vendor has no matching rate contributes zero."

    Design: Difficulty/dual_variant_calc/vendor_realized_vs_potential_savings_diverges
    """
    ven = _setup_two_vendor_bookings(api)
    report = validate_success(api.get_savings_report(ven["id"], MGR))
    assert report["potential_savings_cents"] == 300000, (
        f"potential savings counts both vendor bookings at the best rate "
        f"(2 x (400000-250000)), got {report['potential_savings_cents']}"
    )
