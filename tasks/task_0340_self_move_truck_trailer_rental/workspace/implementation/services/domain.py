"""Shared domain helpers: on_lot_count recompute, availability counts,
dispatch selector, quote re-run, lookups."""
import db
from services import calc

ON_LOT_STATUSES = {"AVAILABLE", "RESERVED", "MAINTENANCE"}


def recompute_on_lot_count(location_id):
    """Recompute a location's on_lot_count and, if it changes, mutate the
    location (advance updated_at, bump version). PRD §2.6."""
    loc = db.locations.get(location_id)
    if loc is None:
        return
    count = 0
    for eq in db.equipment.items.values():
        if eq["current_location_id"] == location_id and eq["status"] in ON_LOT_STATUSES:
            count += 1
    if loc["on_lot_count"] != count:
        loc["on_lot_count"] = count
        db.touch(loc)


def available_count(location_id, class_id):
    """Dispatch-ready pool: status exactly AVAILABLE at this location."""
    return sum(1 for eq in db.equipment.items.values()
               if eq["equipment_class_id"] == class_id
               and eq["current_location_id"] == location_id
               and eq["status"] == "AVAILABLE")


def reserved_count(location_id, class_id):
    return sum(1 for eq in db.equipment.items.values()
               if eq["equipment_class_id"] == class_id
               and eq["current_location_id"] == location_id
               and eq["status"] == "RESERVED")


def lot_occupancy_count(location_id, class_id):
    return sum(1 for eq in db.equipment.items.values()
               if eq["equipment_class_id"] == class_id
               and eq["current_location_id"] == location_id
               and eq["status"] in ON_LOT_STATUSES)


# ---- Reservation child rows ----
def addons_for(reservation_id):
    return [a for a in db.addons.all() if a["reservation_id"] == reservation_id]


def supply_lines_for(reservation_id):
    return [s for s in db.supply_lines.all() if s["reservation_id"] == reservation_id]


def damage_reports_for(contract_id):
    return [d for d in db.damage_reports.all() if d["contract_id"] == contract_id]


def rerun_quote(reservation):
    """Recompute quoted_total_cents in place from the current child rows."""
    klass = db.equipment_classes.get(reservation["equipment_class_id"])
    customer = db.customers.get(reservation["customer_id"])
    coverage_plan = None
    if reservation.get("coverage_plan_id"):
        coverage_plan = db.coverage_plans.get(reservation["coverage_plan_id"])
    addon_rows = addons_for(reservation["id"])
    supply_rows = supply_lines_for(reservation["id"])
    reservation["quoted_total_cents"] = calc.reservation_quote(
        reservation, klass, customer, coverage_plan, addon_rows, supply_rows)


# ---- Window overlap ----
def confirmed_reservations_on_equipment(equipment_id, exclude_reservation_id=None):
    """CONFIRMED reservations whose assigned_equipment_id (earmark or dispatch)
    points at this unit."""
    out = []
    for r in db.reservations.items.values():
        if r["id"] == exclude_reservation_id:
            continue
        if r["booking_status"] != "CONFIRMED":
            continue
        if r.get("assigned_equipment_id") == equipment_id:
            out.append(r)
    return out


def equipment_window_collides(equipment_id, reservation, exclude_reservation_id=None):
    """True when any other CONFIRMED reservation on this unit collides under the
    buffered overlap rule with the given reservation's window."""
    r_pickup = calc.parse_iso(reservation["scheduled_pickup_at"])
    r_return = calc.parse_iso(reservation["scheduled_return_at"])
    for other in confirmed_reservations_on_equipment(equipment_id, exclude_reservation_id):
        o_pickup = calc.parse_iso(other["scheduled_pickup_at"])
        o_return = calc.parse_iso(other["scheduled_return_at"])
        if calc.windows_overlap(r_pickup, r_return, o_pickup, o_return):
            return True
    return False


# ---- Round-trip confirm earmark candidate ----
def stationed_units_for_confirm(reservation):
    """Units of the class at pickup with status in {AVAILABLE, RESERVED}."""
    class_id = reservation["equipment_class_id"]
    pickup = reservation["pickup_location_id"]
    out = []
    for eq in db.equipment.all():
        if (eq["equipment_class_id"] == class_id
                and eq["current_location_id"] == pickup
                and eq["status"] in ("AVAILABLE", "RESERVED")):
            out.append(eq)
    return out


def pick_earmark_unit(reservation):
    """For a round-trip confirm: return an AVAILABLE unit with no colliding
    CONFIRMED reservation, ranked by selector policy. None if no AVAILABLE unit
    qualifies (un-earmarked but still allowed to confirm)."""
    class_id = reservation["equipment_class_id"]
    pickup = reservation["pickup_location_id"]
    candidates = []
    for eq in db.equipment.all():
        if (eq["equipment_class_id"] == class_id
                and eq["current_location_id"] == pickup
                and eq["status"] == "AVAILABLE"):
            if not equipment_window_collides(eq["id"], reservation,
                                             exclude_reservation_id=reservation["id"]):
                candidates.append(eq)
    if not candidates:
        return None
    return rank_candidates(candidates, reservation)[0]


def rank_candidates(candidates, reservation):
    """Sort by (home_matches_dropoff DESC, odometer_miles ASC, created_at ASC)."""
    dropoff = reservation["dropoff_location_id"]

    def key(eq):
        home_matches = 1 if eq["home_location_id"] == dropoff else 0
        return (-home_matches, eq["odometer_miles"], eq["_seq"])

    return sorted(candidates, key=key)


def dispatch_candidates(reservation):
    """One-way path candidate set: AVAILABLE units of the class at pickup, not
    earmarked to another reservation, and no colliding CONFIRMED window."""
    class_id = reservation["equipment_class_id"]
    pickup = reservation["pickup_location_id"]
    out = []
    for eq in db.equipment.all():
        if not (eq["equipment_class_id"] == class_id
                and eq["current_location_id"] == pickup
                and eq["status"] == "AVAILABLE"):
            continue
        # Not earmarked to another reservation: an AVAILABLE unit is by
        # definition not RESERVED, but guard the window-overlap rule too.
        if equipment_window_collides(eq["id"], reservation,
                                     exclude_reservation_id=reservation["id"]):
            continue
        out.append(eq)
    return out


def open_transfer_for_equipment(equipment_id):
    for t in db.transfers.items.values():
        if t["equipment_id"] == equipment_id and t["status"] in ("REQUESTED", "APPROVED"):
            return t
    return None
