"""Sortie lifecycle: recovery, abort, and the grounding cascade (PRD 3.7, 3.8)."""
from decimal import Decimal

import calc
from db import db, new_record, touch
from timeutil import plus_minutes

NON_TERMINAL_OPS = ("PLANNED", "LAUNCHED", "DROPPING", "RETURNING")
AIRBORNE_OPS = ("LAUNCHED", "DROPPING", "RETURNING")
RETIRE_CYCLES = 300


# --- conserved quantities (PRD 2.10) -------------------------------------
# Both ledgers are `source: computed`. Deriving them on read makes the two
# invariants hold by construction: no cascade can leak a pad slot or strand
# a funds hold, because neither is ever stored.


def reserved_pads(nest_id):
    return sum(
        1
        for f in db.flights.values()
        if f["recovery_nest_id"] == nest_id and f["ops_state"] in NON_TERMINAL_OPS
    )


def held_total(customer_id):
    total = sum(
        (
            Decimal(o["order_total"])
            for o in db.orders.values()
            if o["customer_id"] == customer_id and o["status"] in ("ASSIGNED", "IN_TRANSIT")
        ),
        Decimal(0),
    )
    return calc.rhu(total, 2)


def billed_total(customer_id):
    total = sum(
        (
            Decimal(o["order_total"])
            for o in db.orders.values()
            if o["customer_id"] == customer_id and o["status"] == "DELIVERED"
        ),
        Decimal(0),
    )
    return calc.rhu(total, 2)


# --- helpers --------------------------------------------------------------


def authorization_of(flight):
    rows = [a for a in db.authorizations.values() if a["flight_id"] == flight["id"]]
    if not rows:
        return None
    return max(rows, key=lambda a: (a["created_at"], a["_seq"]))


def schedule_maintenance(drone_id, work_type, minutes, incident_id=None):
    now = db.now()
    return new_record(
        "MaintenanceLog",
        {
            "drone_id": drone_id,
            "incident_id": incident_id,
            "work_type": work_type,
            "scheduled_start": now,
            "scheduled_end": plus_minutes(now, minutes),
            "status": "SCHEDULED",
            "completed_at": None,
            "notes": "",
        },
    )


def _debit_battery(flight):
    """Pack debit shared by recovery and every post-launch abort. True on retirement."""
    battery = db.batteries.get(flight["battery_id"])
    if battery is None or battery["state"] != "IN_USE":
        return False
    battery["cycle_count"] += 1
    new_charge = calc.rhu(Decimal(battery["charge_pct"]) - Decimal(flight["actual_energy_pct"]), 1)
    if new_charge < 0:
        new_charge = Decimal("0.0")
    battery["charge_pct"] = new_charge
    battery["state"] = "COOLDOWN"
    retired = battery["cycle_count"] >= RETIRE_CYCLES
    if retired:
        battery["state"] = "RETIRED"
    touch(battery)
    return retired


def _settle_airframe(flight, grounding):
    """Pack debit, hour accumulation and drone status after an airborne sortie ends."""
    drone = db.drones[flight["drone_id"]]
    retired = _debit_battery(flight)

    delta = calc.flight_hours_delta(flight["actual_route_km"], drone["cruise_speed_kmh"])
    changed = False
    if delta != 0:
        drone["flight_hours"] = calc.rhu(Decimal(drone["flight_hours"]) + delta, 2)
        drone["hours_since_service"] = calc.rhu(Decimal(drone["hours_since_service"]) + delta, 2)
        changed = True

    if retired:
        drone["installed_battery_id"] = None
        drone["status"] = "GROUNDED"
        changed = True
    elif not grounding:
        drone["status"] = "IDLE"
        changed = True

    if changed:
        touch(drone)
    if retired:
        schedule_maintenance(drone["id"], "BATTERY_SWAP", 60, incident_id=None)


def recover_flight(flight, actual_route_km):
    order = db.orders[flight["order_id"]]
    flight["actual_route_km"] = calc.rhu(Decimal(actual_route_km), 3)
    flight["actual_energy_pct"] = calc.actual_energy_pct(
        flight["actual_route_km"], order["payload_weight_g"], flight["wind_kph_at_dispatch"]
    )
    flight["ops_state"] = "RECOVERED"
    touch(flight)

    _settle_airframe(flight, grounding=False)
    # The pad slot is freed the moment the flight leaves the non-terminal set.
    # The order is already DELIVERED and terminal: no ledger movement here.
    return flight


def abort_flight(flight, reason, actual_route_km=None, grounding=False):
    """The single unwind path; the grounding cascade reuses it verbatim (PRD 3.7, 3.8)."""
    prev_ops = flight["ops_state"]
    order = db.orders[flight["order_id"]]

    flight["ops_state"] = "ABORTED"
    flight["abort_reason"] = reason

    if prev_ops in AIRBORNE_OPS:
        route = Decimal(actual_route_km) if actual_route_km is not None else Decimal("0.0")
        flight["actual_route_km"] = calc.rhu(route, 3)
        flight["actual_energy_pct"] = calc.actual_energy_pct(
            flight["actual_route_km"], order["payload_weight_g"], flight["wind_kph_at_dispatch"]
        )

    if flight["clearance_state"] in ("FILED", "CLEARED"):
        flight["clearance_state"] = "REVOKED"
    touch(flight)

    auth = authorization_of(flight)
    if auth is not None and auth["status"] in ("PENDING", "APPROVED"):
        auth["status"] = "REVOKED"
        touch(auth)

    if prev_ops in AIRBORNE_OPS:
        _settle_airframe(flight, grounding=grounding)
    else:
        # From PLANNED the pack never left READY: it is untouched.
        drone = db.drones[flight["drone_id"]]
        if not grounding and drone["status"] == "RESERVED":
            drone["status"] = "IDLE"
            touch(drone)

    # The pad slot is released implicitly: the flight is no longer non-terminal.
    if order["status"] in ("ASSIGNED", "IN_TRANSIT"):
        order["status"] = "QUOTED"
        touch(order)
        # held_total is derived from the order set, so the hold is released exactly.

    return flight


def ground_drone_cascade(drone):
    """Force the airframe to GROUNDED and unwind every live sortie it holds."""
    drone["status"] = "GROUNDED"
    touch(drone)

    live = [
        f
        for f in db.flights.values()
        if f["drone_id"] == drone["id"] and f["ops_state"] in NON_TERMINAL_OPS
    ]
    for flight in sorted(live, key=lambda f: (f["created_at"], f["_seq"])):
        abort_flight(flight, "DRONE_GROUNDED", actual_route_km=Decimal("0.0"), grounding=True)
