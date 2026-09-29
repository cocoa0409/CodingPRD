"""Shared cascades (PRD 2.8).  Every hop runs inside the same request and each
row it touches gets its own version bump and updated_at refresh."""

import calc
import db


# --------------------------------------------------------------------------
# ride inventory posture
# --------------------------------------------------------------------------
def _ride_release(ride, ignore_alloc_id=None):
    """Return the ride to AVAILABLE unless OUT_OF_SERVICE or still held."""
    if ride is None or ride["status"] == "OUT_OF_SERVICE":
        return
    for alloc in calc.allocations_of_ride(ride["id"], calc.ALLOC_ACTIVE):
        if alloc["id"] != ignore_alloc_id:
            return
    if ride["status"] != "AVAILABLE":
        ride["status"] = "AVAILABLE"
        db.touch(ride)


# --------------------------------------------------------------------------
# route derived status
# --------------------------------------------------------------------------
def route_maybe_in_progress(route):
    if route is not None and route["status"] == "COMMITTED":
        route["status"] = "IN_PROGRESS"
        db.touch(route)


def route_maybe_closed(route):
    if route is None or route["status"] != "IN_PROGRESS":
        return
    stop_count = calc.route_stop_count(route["id"])
    closed = calc.route_closed_stop_count(route["id"])
    if stop_count >= 1 and closed >= stop_count:
        route["status"] = "CLOSED"
        db.touch(route)


# --------------------------------------------------------------------------
# allocation transitions
# --------------------------------------------------------------------------
def commit_allocation(alloc, stop):
    """RESERVED -> COMMITTED with the inspection slot ladder."""
    ride = db.store.rides.get(alloc["ride_id"])
    alloc["status"] = "COMMITTED"
    db.touch(alloc)
    if ride is not None and ride["status"] != "OUT_OF_SERVICE":
        if ride["status"] != "ASSIGNED":
            ride["status"] = "ASSIGNED"
            db.touch(ride)
    jurisdiction = calc.jurisdiction_of(stop)
    needs = (ride is not None and ride.get("requires_state_inspection")
             and jurisdiction is not None
             and jurisdiction.get("requires_state_ride_inspection"))
    if needs:
        scheduled_date = calc.select_inspection_slot(stop)
        if scheduled_date is None:
            alloc["status"] = "INSPECTION_HELD"
            db.touch(alloc)
        else:
            db.create(db.store.inspection_orders, {
                "ride_allocation_id": alloc["id"],
                "authority": "STATE",
                "scheduled_date": scheduled_date,
                "status": "SCHEDULED",
                "attempt_number": 1,
                "defect_count": 0,
                "result_recorded_at": None,
            })
    return alloc


def release_allocation(alloc, stop):
    """-> RELEASED; footprint, amperage and the unit go back to the pool."""
    alloc["status"] = "RELEASED"
    alloc["released_at"] = db.now_iso()
    db.touch(alloc)
    _ride_release(db.store.rides.get(alloc["ride_id"]), ignore_alloc_id=alloc["id"])
    db.touch(stop)
    return alloc


# --------------------------------------------------------------------------
# stop transitions
# --------------------------------------------------------------------------
def confirm_stop(stop):
    """PLANNED -> CONFIRMED, cascading into reserved allocations."""
    stop["status"] = "CONFIRMED"
    db.touch(stop)
    for alloc in calc.allocations_of_stop(stop["id"], ("RESERVED",)):
        ride = db.store.rides.get(alloc["ride_id"])
        if ride is not None and ride["status"] == "OUT_OF_SERVICE":
            continue
        commit_allocation(alloc, stop)


def expire_permits(stop, dark=False):
    """APPROVED permits past their validity expire; going dark expires SUBMITTED too."""
    clock = db.now()
    for permit in calc.permits_of_stop(stop["id"]):
        if dark:
            if permit["status"] in ("SUBMITTED", "APPROVED"):
                permit["status"] = "EXPIRED"
                db.touch(permit)
            continue
        if permit["status"] == "APPROVED" and calc.dt(permit, "valid_until") < clock:
            permit["status"] = "EXPIRED"
            db.touch(permit)


def open_gates(stop):
    stop["status"] = "OPEN"
    db.touch(stop)
    for alloc in calc.allocations_of_stop(stop["id"], ("COMMITTED",)):
        alloc["status"] = "OPERATING"
        db.touch(alloc)
    route_maybe_in_progress(calc.route_of(stop))


def teardown(stop):
    stop["status"] = "TEARDOWN"
    db.touch(stop)
    for alloc in calc.allocations_of_stop(stop["id"], ("OPERATING",)):
        alloc["status"] = "STRUCK"
        db.touch(alloc)
        ride = db.store.rides.get(alloc["ride_id"])
        _ride_release(ride, ignore_alloc_id=alloc["id"])


def close_stop(stop):
    """TEARDOWN -> CLOSED after the settlement went FINAL."""
    stop["status"] = "CLOSED"
    db.touch(stop)
    for assignment in calc.assignments_of_stop(stop["id"], ("SCHEDULED",)):
        assignment["status"] = "COMPLETED"
        db.touch(assignment)
        worker = db.store.workers.get(assignment["worker_id"])
        if worker is not None:
            db.touch(worker)
    route_maybe_closed(calc.route_of(stop))


def cancel_stop(stop):
    """-> DARK, cascading over the deal, allocations, crew, permits and route."""
    stop["status"] = "DARK"
    db.touch(stop)

    contract = calc.live_contract_of_stop(stop["id"])
    if contract is not None:
        if contract["status"] == "EXECUTED":
            contract["status"] = "TERMINATED"
        else:
            contract["status"] = "VOID"
        db.touch(contract)

    for alloc in calc.allocations_of_stop(stop["id"], calc.ALLOC_ACTIVE):
        alloc["status"] = "RELEASED"
        alloc["released_at"] = db.now_iso()
        db.touch(alloc)
        _ride_release(db.store.rides.get(alloc["ride_id"]),
                      ignore_alloc_id=alloc["id"])

    for assignment in calc.assignments_of_stop(stop["id"], ("SCHEDULED",)):
        assignment["status"] = "RELEASED"
        db.touch(assignment)
        worker = db.store.workers.get(assignment["worker_id"])
        if worker is not None:
            db.touch(worker)

    expire_permits(stop, dark=True)

    route = calc.route_of(stop)
    if route is not None:
        if route["status"] == "SEQUENCED":
            calc.reset_sequencing(route)
        else:
            db.touch(route)
        route_maybe_closed(route)
