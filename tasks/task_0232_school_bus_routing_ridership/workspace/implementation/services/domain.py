"""Domain computed-field derivation and public serialization per entity type.

Computed (source: computed) fields are derived live from current state at read
time. System counts that the PRD says are "recomputed at the triggering event"
are persisted on the record AND a mutation stamp (updated_at/version bump) is
applied at the event; their public value here mirrors the stored value.
"""

from db import DB
from services.common import public
from services import calc


# ---- onboard projection (SCAFFOLD onboard_count_projection) -------------------

def trip_tap_events(bus_trip_id):
    return [t for t in DB.tap_events.values() if t["bus_trip_id"] == bus_trip_id]


def onboard_set(bus_trip_id):
    """Replay the trip's tap log in created_at ASC, ties by stop_sequence ASC."""
    events = trip_tap_events(bus_trip_id)
    # created_at ASC (mirrored by the monotonic _seq), ties by stop_sequence ASC.
    events.sort(key=lambda e: (e["_seq"], e["stop_sequence"]))
    onboard = set()
    for ev in events:
        if ev["direction"] == "TAP_ON":
            onboard.add(ev["student_id"])
        elif ev["direction"] == "TAP_OFF":
            onboard.discard(ev["student_id"])
    return onboard


def onboard_count(bus_trip_id):
    return len(onboard_set(bus_trip_id))


def student_has_tap_on(student_id, bus_trip_id):
    for ev in trip_tap_events(bus_trip_id):
        if ev["student_id"] == student_id and ev["direction"] == "TAP_ON":
            return True
    return False


# ---- route-scoped helpers ----------------------------------------------------

def route_stops_sorted(route_id):
    stops = [s for s in DB.stops.values() if s["route_id"] == route_id]
    stops.sort(key=lambda s: s["sequence"])
    return stops


def stop_by_sequence(route_id, sequence):
    for s in DB.stops.values():
        if s["route_id"] == route_id and s["sequence"] == sequence:
            return s
    return None


def route_final_sequence(route_id):
    stops = route_stops_sorted(route_id)
    return stops[-1]["sequence"] if stops else None


def next_sequence_after(route_id, current):
    """Smallest Stop.sequence strictly greater than current; None if none."""
    candidates = [s["sequence"] for s in DB.stops.values()
                  if s["route_id"] == route_id and s["sequence"] > current]
    return min(candidates) if candidates else None


# ---- computed counts ---------------------------------------------------------

def district_active_route_count(district_id):
    return sum(1 for r in DB.routes.values()
               if r["district_id"] == district_id
               and r["posture"] in ("OPEN", "RESTRICTED"))


def route_assigned_rider_count(route_id):
    return sum(1 for a in DB.ridership_applications.values()
               if a["status"] == "APPROVED" and a["assigned_route_id"] == route_id)


def route_assigned_wheelchair_count(route_id):
    cnt = 0
    for a in DB.ridership_applications.values():
        if a["status"] == "APPROVED" and a["assigned_route_id"] == route_id:
            stu = DB.students.get(a["student_id"])
            if stu and stu.get("special_needs"):
                cnt += 1
    return cnt


def route_open_incident(route_id):
    for t in DB.bus_trips.values():
        if t["route_id"] == route_id and t["status"] == "INCIDENT_HOLD":
            return True
    return False


# ---- ETA derivation (SCAFFOLD eta_estimate) ----------------------------------

def compute_eta(trip):
    """Compute eta_next_stop_minutes for a trip, or None.

    Target = the Stop whose sequence == current_stop_sequence (next undeparted).
    Origin = last GPS ping if set, else the previously-departed Stop's coords
    (or the school campus for stop 1). Null unless trip is BOARDING/IN_TRANSIT.
    """
    if trip["status"] not in ("BOARDING", "IN_TRANSIT"):
        return None
    cur = trip["current_stop_sequence"]
    target = stop_by_sequence(trip["route_id"], cur)
    if target is None:
        return None

    if trip["last_lat"] is not None and trip["last_lng"] is not None:
        origin_lat, origin_lng = trip["last_lat"], trip["last_lng"]
    else:
        # stop_based_fallback: previously departed stop, or school for stop 1.
        prev_seqs = [s["sequence"] for s in DB.stops.values()
                     if s["route_id"] == trip["route_id"] and s["sequence"] < cur]
        if prev_seqs:
            prev = stop_by_sequence(trip["route_id"], max(prev_seqs))
            origin_lat, origin_lng = prev["lat"], prev["lng"]
        else:
            route = DB.routes.get(trip["route_id"])
            district = DB.districts.get(route["district_id"]) if route else None
            if district is None:
                return None
            origin_lat, origin_lng = district["school_lat"], district["school_lng"]

    return calc.eta_minutes(origin_lat, origin_lng, target["lat"], target["lng"])


# ---- public serializers ------------------------------------------------------

def district_public(rec):
    return public(rec, {
        "active_route_count": district_active_route_count(rec["id"]),
    })


def route_public(rec):
    return public(rec, {
        "assigned_rider_count": route_assigned_rider_count(rec["id"]),
        "assigned_wheelchair_count": route_assigned_wheelchair_count(rec["id"]),
        "open_incident": route_open_incident(rec["id"]),
    })


def stop_public(rec):
    return public(rec)


def student_public(rec):
    return public(rec)


def application_public(rec):
    return public(rec)


def driver_public(rec):
    return public(rec)


def assignment_public(rec):
    return public(rec)


def bus_trip_public(rec):
    return public(rec, {
        "eta_next_stop_minutes": compute_eta(rec),
        "onboard_count": onboard_count(rec["id"]),
    })


def tap_event_public(rec):
    return public(rec)


def notification_public(rec):
    return public(rec)


def missed_report_public(rec):
    return public(rec)
