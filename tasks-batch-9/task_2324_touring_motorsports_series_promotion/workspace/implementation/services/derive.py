"""Collection lookups and derived (source: computed) field reconciliation.

Every roll-up counter in the model is recomputed from the base rows on read, so a
counter can never drift from the rows that feed it (PRD 2.5).
"""
from db import by_created, db
from errors import fail

LIVE_ENTRY_STATES = ("ENTERED", "STAGED")
RECOGNIZED_ACTIVATION_STATES = ("ACTIVATED", "FULFILLED")
COUNTED_BOOKING_STATES = ("TERMS_PROPOSED", "COUNTERED", "CONFIRMED")


# --------------------------------------------------------------------------- #
# lookups
# --------------------------------------------------------------------------- #
def require(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        fail(error_id)
    return row


def get_season(row_id):
    return require(db.seasons, row_id, "ERR_SEASON_NOT_FOUND")


def get_venue(row_id):
    return require(db.venues, row_id, "ERR_VENUE_NOT_FOUND")


def get_booking(row_id):
    return require(db.bookings, row_id, "ERR_VENUE_BOOKING_NOT_FOUND")


def get_stop(row_id):
    return require(db.stops, row_id, "ERR_TOUR_STOP_NOT_FOUND")


def get_competitor(row_id):
    return require(db.competitors, row_id, "ERR_COMPETITOR_NOT_FOUND")


def get_entry(row_id):
    return require(db.entries, row_id, "ERR_VEHICLE_ENTRY_NOT_FOUND")


def get_inspection(row_id):
    return require(db.inspections, row_id, "ERR_TECH_INSPECTION_NOT_FOUND")


def get_segment(row_id):
    return require(db.segments, row_id, "ERR_SHOW_SEGMENT_NOT_FOUND")


def get_tier(row_id):
    return require(db.tiers, row_id, "ERR_TICKET_TIER_NOT_FOUND")


def get_order(row_id):
    return require(db.orders, row_id, "ERR_TICKET_ORDER_NOT_FOUND")


def get_sponsor(row_id):
    return require(db.sponsors, row_id, "ERR_SPONSOR_NOT_FOUND")


def get_activation(row_id):
    return require(db.activations, row_id, "ERR_SPONSORSHIP_ACTIVATION_NOT_FOUND")


def get_plan(row_id):
    return require(db.plans, row_id, "ERR_SAFETY_PLAN_NOT_FOUND")


def get_allocation(row_id):
    return require(db.allocations, row_id, "ERR_MARKETING_ALLOCATION_NOT_FOUND")


def get_settlement(row_id):
    return require(db.settlements, row_id, "ERR_SETTLEMENT_NOT_FOUND")


# --------------------------------------------------------------------------- #
# relations
# --------------------------------------------------------------------------- #
def all_bookings():
    return by_created(list(db.bookings.values()))


def all_stops():
    return by_created(list(db.stops.values()))


def all_entries():
    return by_created(list(db.entries.values()))


def all_orders():
    return by_created(list(db.orders.values()))


def all_activations():
    return by_created(list(db.activations.values()))


def season_of_stop(stop):
    return db.seasons[stop["season_id"]]


def booking_of_stop(stop):
    return db.bookings[stop["venue_booking_id"]]


def venue_of_stop(stop):
    return db.venues[booking_of_stop(stop)["venue_id"]]


def bookings_of_season(season_id):
    return by_created([b for b in db.bookings.values() if b["season_id"] == season_id])


def stops_of_season(season_id):
    return by_created([s for s in db.stops.values() if s["season_id"] == season_id])


def stop_of_booking(booking_id):
    for stop in db.stops.values():
        if stop["venue_booking_id"] == booking_id:
            return stop
    return None


def tiers_of_stop(stop_id):
    return by_created([t for t in db.tiers.values() if t["tour_stop_id"] == stop_id])


def orders_of_stop(stop_id):
    return by_created([o for o in db.orders.values() if o["tour_stop_id"] == stop_id])


def orders_of_tier(tier_id):
    return by_created([o for o in db.orders.values() if o["ticket_tier_id"] == tier_id])


def segments_of_stop(stop_id):
    return by_created([s for s in db.segments.values() if s["tour_stop_id"] == stop_id])


def entries_of_stop(stop_id):
    return by_created([e for e in db.entries.values() if e["tour_stop_id"] == stop_id])


def live_entries_of_stop(stop_id):
    return [e for e in entries_of_stop(stop_id) if e["logistics_state"] in LIVE_ENTRY_STATES]


def entries_of_competitor(competitor_id):
    return by_created([e for e in db.entries.values() if e["competitor_id"] == competitor_id])


def inspections_of_entry(entry_id):
    rows = [i for i in db.inspections.values() if i["vehicle_entry_id"] == entry_id]
    return sorted(rows, key=lambda r: r["attempt_no"])


def activations_of_stop(stop_id):
    return by_created([a for a in db.activations.values() if a["tour_stop_id"] == stop_id])


def activations_of_tier(tier_id):
    return by_created([a for a in db.activations.values() if a["hospitality_tier_id"] == tier_id])


def activations_of_entry(entry_id):
    return by_created(
        [a for a in db.activations.values() if a["branded_vehicle_entry_id"] == entry_id]
    )


def allocations_of_stop(stop_id):
    return by_created([a for a in db.allocations.values() if a["tour_stop_id"] == stop_id])


def plan_of_stop(stop_id):
    for plan in db.plans.values():
        if plan["tour_stop_id"] == stop_id:
            return plan
    return None


def settlement_of_stop(stop_id):
    for row in db.settlements.values():
        if row["tour_stop_id"] == stop_id:
            return row
    return None


def segments_featuring_entry(entry_id):
    return by_created(
        [s for s in db.segments.values() if s["featured_vehicle_entry_id"] == entry_id]
    )


# --------------------------------------------------------------------------- #
# derived counters
# --------------------------------------------------------------------------- #
def tier_reserved(tier):
    return sum(o["qty"] for o in orders_of_tier(tier["id"]) if o["status"] == "PENDING")


def tier_sold(tier):
    return sum(o["qty"] for o in orders_of_tier(tier["id"]) if o["status"] == "PAID")


def tier_held(tier):
    return sum(
        a["hospitality_seat_count"]
        for a in activations_of_tier(tier["id"])
        if a["state"] in RECOGNIZED_ACTIVATION_STATES
    )


def tier_available(tier):
    return tier["allotment"] - tier_reserved(tier) - tier_sold(tier) - tier_held(tier)


def entry_tech_attempt_count(entry):
    return len(inspections_of_entry(entry["id"]))


def entry_failed_attempt_count(entry):
    return len([i for i in inspections_of_entry(entry["id"]) if i["result"] == "FAILED"])


def entry_branding_slots_committed(entry):
    return sum(
        a["vehicle_branding_slots"]
        for a in activations_of_entry(entry["id"])
        if a["state"] in RECOGNIZED_ACTIVATION_STATES
    )


def competitor_entry_count(competitor):
    return len(
        [
            e
            for e in entries_of_competitor(competitor["id"])
            if e["logistics_state"] in LIVE_ENTRY_STATES
        ]
    )


def stop_expected_attendance(stop):
    venue = venue_of_stop(stop)
    allotment_total = sum(t["allotment"] for t in tiers_of_stop(stop["id"]))
    return min(venue["seat_capacity"], allotment_total)


def stop_competition_segment_count(stop):
    return len([s for s in segments_of_stop(stop["id"]) if s["segment_type"] == "COMPETITION"])


def stop_run_order_end_offset(stop):
    segments = segments_of_stop(stop["id"])
    if not segments:
        return 0
    return max(s["end_offset_minutes"] for s in segments)


def stop_paid_orders(stop_id):
    return [o for o in orders_of_stop(stop_id) if o["status"] == "PAID"]


def stop_tickets_sold_count(stop):
    return sum(o["qty"] for o in stop_paid_orders(stop["id"]))


def stop_gross_ticket_revenue(stop):
    return sum(
        o["line_subtotal_cents"] - o["group_discount_cents"] for o in stop_paid_orders(stop["id"])
    )


def stop_addon_revenue(stop):
    return sum(
        o["addon_subtotal_cents"] - o["addon_discount_cents"] for o in stop_paid_orders(stop["id"])
    )


def stop_facility_fee_collected(stop):
    return sum(o["facility_fee_cents"] for o in stop_paid_orders(stop["id"]))


def stop_pit_party_sold_count(stop):
    return sum(o["pit_party_addon_qty"] for o in stop_paid_orders(stop["id"]))


def stop_marketing_committed(stop):
    return sum(
        a["amount_cents"] for a in allocations_of_stop(stop["id"]) if a["state"] == "COMMITTED"
    )


def stop_sponsorship_committed(stop):
    return sum(
        a["fee_cents"]
        for a in activations_of_stop(stop["id"])
        if a["state"] in RECOGNIZED_ACTIVATION_STATES
    )


def stop_held_hospitality_seats(stop):
    return sum(
        a["hospitality_seat_count"]
        for a in activations_of_stop(stop["id"])
        if a["state"] in RECOGNIZED_ACTIVATION_STATES
    )


def season_marketing_allocated(season):
    total = 0
    for stop in stops_of_season(season["id"]):
        total += stop_marketing_committed(stop)
    return total


def season_booking_count(season):
    return len(
        [
            b
            for b in bookings_of_season(season["id"])
            if b["state"] in COUNTED_BOOKING_STATES
        ]
    )


def season_settled_stop_count(season):
    return len([s for s in stops_of_season(season["id"]) if s["sales_state"] == "SETTLED"])


def season_net_cents(season):
    total = 0
    for stop in stops_of_season(season["id"]):
        settlement = settlement_of_stop(stop["id"])
        if settlement is not None and settlement["state"] == "APPROVED":
            total += settlement["net_to_promoter_cents"]
    return total


def season_marketing_unallocated(season):
    return season["total_marketing_budget_cents"] - season_marketing_allocated(season)
