"""Server-driven cascades. Every touched resource is independently versioned
(PRD 2.5): each gets its own updated_at refresh and version bump.

Covered cascades:
  - eligibility lapse (ELIGIBLE -> SUSPENDED)  [PRD 3.1]
  - broker suspend                              [PRD 3.2]
  - trip cancel                                  [PRD 3.3]
  - trip completion bubble-up                    [PRD 3.5]
  - outbound no-show                             [PRD 3.5]
"""
from db import db, touch

LEG_TERMINAL = {"DROPPED_OFF", "NO_SHOW", "CANCELLED"}


def _trip_legs(trip_id):
    return [l for l in db.legs.values() if l["trip_id"] == trip_id]


def _active_assignment(trip_id):
    for a in db.assignments.values():
        if a["trip_id"] == trip_id and a["status"] == "ACTIVE":
            return a
    return None


def release_active_assignment(trip):
    """Release the trip's ACTIVE assignment, free its driver, clear assigned ids."""
    assignment = _active_assignment(trip["id"])
    if assignment is not None:
        assignment["status"] = "RELEASED"
        touch(assignment)
        driver = db.drivers.get(assignment["driver_id"])
        if driver is not None and driver["status"] == "ON_TRIP":
            driver["status"] = "AVAILABLE"
            touch(driver)
    trip["assigned_broker_id"] = None
    trip["assigned_driver_id"] = None


def cancel_nonterminal_legs(trip_id, statuses=None):
    """Cancel legs of a trip. If `statuses` given, only legs in those statuses;
    otherwise all non-terminal legs."""
    for leg in _trip_legs(trip_id):
        if statuses is not None:
            if leg["leg_status"] in statuses:
                leg["leg_status"] = "CANCELLED"
                touch(leg)
        else:
            if leg["leg_status"] not in LEG_TERMINAL:
                leg["leg_status"] = "CANCELLED"
                touch(leg)


def cancel_trip_cascade(trip):
    """Cancel a DRAFT/SCHEDULED/ASSIGNED trip (PRD 3.3)."""
    prior = trip["trip_status"]
    trip["trip_status"] = "CANCELLED"
    if prior in ("SCHEDULED", "ASSIGNED"):
        cancel_nonterminal_legs(trip["id"])
    if prior == "ASSIGNED":
        release_active_assignment(trip)
    touch(trip)


def eligibility_lapse_cascade(member):
    """ELIGIBLE -> SUSPENDED cascade (PRD 3.1).

    - Every TripRequest for this member in {SCHEDULED, ASSIGNED} -> CANCELLED
      - its OUTBOUND/RETURN legs in {PENDING, READY, EN_ROUTE} -> CANCELLED
      - its ACTIVE assignment -> RELEASED, ON_TRIP driver -> AVAILABLE
    - member.standing_orders_paused = true
    - every ACTIVE StandingOrder for this member -> PAUSED
    """
    for trip in db.trips.values():
        if trip["member_id"] != member["id"]:
            continue
        if trip["trip_status"] in ("SCHEDULED", "ASSIGNED"):
            prior = trip["trip_status"]
            trip["trip_status"] = "CANCELLED"
            cancel_nonterminal_legs(trip["id"], {"PENDING", "READY", "EN_ROUTE"})
            if prior == "ASSIGNED":
                release_active_assignment(trip)
            touch(trip)

    member["standing_orders_paused"] = True
    for so in db.standing_orders.values():
        if so["member_id"] == member["id"] and so["status"] == "ACTIVE":
            so["status"] = "PAUSED"
            touch(so)


def broker_suspend_cascade(broker):
    """Broker ACTIVE -> SUSPENDED cascade (PRD 3.2).

    Each TripRequest with assigned_broker_id == broker and trip_status == ASSIGNED
    reverts to SCHEDULED; its ACTIVE assignment -> RELEASED, driver freed, assigned
    ids cleared.
    """
    for trip in db.trips.values():
        if trip.get("assigned_broker_id") == broker["id"] and trip["trip_status"] == "ASSIGNED":
            trip["trip_status"] = "SCHEDULED"
            release_active_assignment(trip)
            touch(trip)


def complete_trip(trip):
    """IN_PROGRESS -> COMPLETED bubble-up (PRD 3.5): release assignment, free driver."""
    trip["trip_status"] = "COMPLETED"
    release_active_assignment(trip)
    touch(trip)


def maybe_complete_trip(trip):
    """If every non-CANCELLED leg of the trip is DROPPED_OFF, complete it."""
    legs = _trip_legs(trip["id"])
    relevant = [l for l in legs if l["leg_status"] != "CANCELLED"]
    if relevant and all(l["leg_status"] == "DROPPED_OFF" for l in relevant):
        complete_trip(trip)
        return True
    return False
