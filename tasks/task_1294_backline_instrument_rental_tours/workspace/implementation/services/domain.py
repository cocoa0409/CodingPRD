"""Domain services: entity serializers, shared cascade helpers, sourcing,
check-in, and settlement logic per PRD §3."""

from datetime import timedelta
import errors
from db import store
from util import new_resource, touch, iso_z, day_count
from services import calculations as calc


# ---------------------------------------------------------------------------
# Serializers: strip internal helper fields (those prefixed with "_")
# ---------------------------------------------------------------------------

def serialize(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Lookups (existence gate, left-to-right at the route layer)
# ---------------------------------------------------------------------------

def get_artist(artist_id):
    a = store.artists.get(artist_id)
    if a is None:
        raise errors.not_found("Artist not found")
    return a


def get_tour(tour_id):
    t = store.tours.get(tour_id)
    if t is None:
        raise errors.not_found("Tour not found")
    return t


def get_stop(stop_id):
    s = store.tour_stops.get(stop_id)
    if s is None:
        raise errors.not_found("TourStop not found")
    return s


def get_rider_line(line_id):
    rl = store.rider_lines.get(line_id)
    if rl is None:
        raise errors.not_found("RiderLine not found")
    return rl


def get_gear_model(model_id):
    m = store.gear_models.get(model_id)
    if m is None:
        raise errors.not_found("GearModel not found")
    return m


def get_gear_unit(unit_id):
    u = store.gear_units.get(unit_id)
    if u is None:
        raise errors.not_found("GearUnit not found")
    return u


def get_reservation(res_id):
    r = store.reservation_lines.get(res_id)
    if r is None:
        raise errors.not_found("ReservationLine not found")
    return r


def get_shipment(shipment_id):
    s = store.shipments.get(shipment_id)
    if s is None:
        raise errors.not_found("Shipment not found")
    return s


def get_shipment_line(line_id):
    sl = store.shipment_lines.get(line_id)
    if sl is None:
        raise errors.not_found("ShipmentLine not found")
    return sl


def get_flight_case(case_id):
    fc = store.flight_cases.get(case_id)
    if fc is None:
        raise errors.not_found("FlightCase not found")
    return fc


def get_vendor(vendor_id):
    v = store.partner_vendors.get(vendor_id)
    if v is None:
        raise errors.not_found("PartnerVendor not found")
    return v


def get_cross_rental(req_id):
    cr = store.cross_rental_requests.get(req_id)
    if cr is None:
        raise errors.not_found("CrossRentalRequest not found")
    return cr


def get_ticket(ticket_id):
    t = store.maintenance_tickets.get(ticket_id)
    if t is None:
        raise errors.not_found("MaintenanceTicket not found")
    return t


def get_claim(claim_id):
    c = store.damage_claims.get(claim_id)
    if c is None:
        raise errors.not_found("DamageClaim not found")
    return c


# ---------------------------------------------------------------------------
# Shipment aggregates (PRD §3.5 derived-field reconciliation)
# ---------------------------------------------------------------------------

def reconcile_shipment_aggregates(shipment):
    """booked_weight_kg sums non-cancelled lines' weight_kg; tech_labor_minutes
    sums their labor_minutes. Reconciled eagerly on every line mutation."""
    weight = 0
    labor = 0
    for line in store.shipment_lines.values():
        if line.get("shipment_id") == shipment["id"] and line.get("status") != "CANCELLED":
            weight += line.get("weight_kg", 0)
            labor += line.get("labor_minutes", 0)
    if shipment.get("booked_weight_kg") != weight or shipment.get("tech_labor_minutes") != labor:
        shipment["booked_weight_kg"] = weight
        shipment["tech_labor_minutes"] = labor
        touch(shipment)


# ---------------------------------------------------------------------------
# Reservation sourcing (PRD §3.3)
# ---------------------------------------------------------------------------

def create_sourced_reservation(tour, rider_line, gear_unit, origin_city, dest_city,
                               start_dt, end_dt, is_cross_rental=False,
                               vendor_rate_cents_per_day=None):
    """Create a reservation driven DRAFT -> SOURCED with quote + deposit hold.

    Callers must have already validated the deposit headroom gate where the
    PRD requires it (source endpoint, cross-rental fulfillment).
    """
    stop = store.tour_stops.get(rider_line["tour_stop_id"])
    artist = store.artists.get(tour["artist_id"])
    model = store.gear_models.get(rider_line["gear_model_id"])
    days = day_count(start_dt, end_dt)
    base_rate = vendor_rate_cents_per_day if is_cross_rental else model["daily_rate_cents"]
    quoted = calc.rental_fee_quote(base_rate, days, origin_city, dest_city,
                                   artist.get("risk_score", 0))
    deposit = calc.deposit_hold_rule(model["replacement_value_cents"],
                                     artist.get("deposit_waived", False))
    res = new_resource()
    res.update({
        "tour_id": tour["id"],
        "rider_line_id": rider_line["id"],
        "gear_unit_id": gear_unit["id"] if gear_unit else None,
        "origin_city_code": origin_city,
        "dest_city_code": dest_city,
        "start_date": iso_z(start_dt),
        "end_date": iso_z(end_dt),
        "status": "SOURCED",
        "quoted_fee_cents": quoted,
        "settled_fee_cents": None,
        "deposit_held_cents": deposit,
        "is_cross_rental": bool(is_cross_rental),
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "_checked_in_dt": None,
        "_vendor_rate_cents_per_day": vendor_rate_cents_per_day if is_cross_rental else None,
    })
    store.reservation_lines[res["id"]] = res

    # Unit assignment: AVAILABLE -> RESERVED (skipped for cross-rentals, which
    # hold no in-house unit)
    if gear_unit is not None:
        gear_unit["status"] = "RESERVED"
        gear_unit["active_reservation_id"] = res["id"]
        touch(gear_unit)

    # Deposit hold debited from the artist's balance in the same operation (§2.7)
    artist["deposit_credit_cents"] = artist.get("deposit_credit_cents", 0) - deposit
    touch(artist)

    # Rider line moves to SOURCED with the reservation link
    rider_line["status"] = "SOURCED"
    rider_line["fulfilled_by_reservation_id"] = res["id"]
    touch(rider_line)

    # Stop rider_revision advances on every rider-line mutation (§3.2)
    if stop is not None:
        stop["rider_revision"] = stop.get("rider_revision", 0) + 1
        touch(stop)
    return res


def create_draft_cross_rental_reservation(tour, rider_line, origin_city, dest_city,
                                          start_dt, end_dt, vendor_rate_cents_per_day):
    """Create the reservation behind a cross-rental request (PRD §3.8): it holds
    no in-house unit and stays DRAFT until the vendor's fulfillment drives it
    DRAFT -> SOURCED (at which point is_cross_rental flips true and the tiered
    deposit hold is computed and blocked against the artist)."""
    res = new_resource()
    res.update({
        "tour_id": tour["id"],
        "rider_line_id": rider_line["id"],
        "gear_unit_id": None,
        "origin_city_code": origin_city,
        "dest_city_code": dest_city,
        "start_date": iso_z(start_dt),
        "end_date": iso_z(end_dt),
        "status": "DRAFT",
        "quoted_fee_cents": None,
        "settled_fee_cents": None,
        "deposit_held_cents": 0,
        "is_cross_rental": False,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "_checked_in_dt": None,
        "_vendor_rate_cents_per_day": vendor_rate_cents_per_day,
    })
    store.reservation_lines[res["id"]] = res
    return res


def release_reservation(reservation, run_maintenance_gate=False):
    """Compensation release on cancellation: unit RESERVED -> AVAILABLE, deposit
    credited back (PRD §2.7, §3.9). Optionally re-run the maintenance gate per
    released unit (ACTIVE tour cancel, §3.9)."""
    unit = None
    if reservation.get("gear_unit_id"):
        unit = store.gear_units.get(reservation["gear_unit_id"])
    if unit is not None and unit.get("status") == "RESERVED":
        if run_maintenance_gate:
            force, reason = calc.maintenance_cycle_gate(
                unit.get("rental_days_since_service", 0),
                unit.get("condition_score", 100),
                0)
            if force:
                unit["status"] = "MAINTENANCE"
                unit["active_reservation_id"] = None
                touch(unit)
                open_maintenance_ticket(unit, reason)
            else:
                unit["status"] = "AVAILABLE"
                unit["active_reservation_id"] = None
                touch(unit)
        else:
            unit["status"] = "AVAILABLE"
            unit["active_reservation_id"] = None
            touch(unit)
    # Credit the held deposit back to the artist
    tour = store.tours.get(reservation.get("tour_id"))
    if tour is not None:
        artist = store.artists.get(tour.get("artist_id"))
        if artist is not None and reservation.get("deposit_held_cents"):
            artist["deposit_credit_cents"] = artist.get("deposit_credit_cents", 0) + reservation["deposit_held_cents"]
            touch(artist)
        reservation["deposit_held_cents"] = 0


def open_maintenance_ticket(unit, opened_reason):
    """Open a MaintenanceTicket against a unit (system-triggered)."""
    ticket = new_resource()
    ticket.update({
        "gear_unit_id": unit["id"],
        "opened_reason": opened_reason,
        "status": "OPEN",
        "opened_at": iso_z(store.current_utc),
        "closed_at": None,
        "service_cost_cents": None,
        "condition_delta": None,
    })
    store.maintenance_tickets[ticket["id"]] = ticket
    return ticket


# ---------------------------------------------------------------------------
# Check-in cascade (PRD §3.6)
# ---------------------------------------------------------------------------

def check_in_reservation(reservation, checked_in_dt):
    """DELIVERED -> RETURNED with the maintenance-gate cascade on the unit."""
    reservation["status"] = "RETURNED"
    reservation["_checked_in_dt"] = checked_in_dt
    touch(reservation)
    unit = None
    if reservation.get("gear_unit_id"):
        unit = store.gear_units.get(reservation["gear_unit_id"])
    if unit is None:
        return
    if unit.get("status") not in {"OUT_ON_RENTAL", "IN_TRANSIT"}:
        return
    days = day_count(reservation["_start_dt"], reservation["_end_dt"])
    force, reason = calc.maintenance_cycle_gate(
        unit.get("rental_days_since_service", 0),
        unit.get("condition_score", 100),
        days)
    if force:
        unit["status"] = "MAINTENANCE"
        unit["active_reservation_id"] = None
        touch(unit)
        open_maintenance_ticket(unit, reason)
    else:
        unit["status"] = "AVAILABLE"
        unit["rental_days_since_service"] = unit.get("rental_days_since_service", 0) + days
        unit["active_reservation_id"] = None
        touch(unit)


# ---------------------------------------------------------------------------
# Tour projected fee (PRD §3.2)
# ---------------------------------------------------------------------------

def recompute_projected_fee(tour):
    """Forward-looking quote total across the tour's DRAFT and SOURCED
    reservation lines."""
    total = 0
    for r in store.reservation_lines.values():
        if r.get("tour_id") == tour["id"] and r.get("status") in {"DRAFT", "SOURCED"}:
            total += r.get("quoted_fee_cents", 0)
    tour["projected_rental_fee_cents"] = total


def rider_line_was_shorted(rider_line_id):
    """Whether the rider line was ever marked SHORTED. Since a SHORTED line is
    terminal, the settlement check looks at the current linked rider line; a
    replacement line created via substitution carries substitution_of_line_id
    back to a shorted original."""
    line = store.rider_lines.get(rider_line_id)
    if line is None:
        return False
    if line.get("status") == "SHORTED":
        return True
    # Walk the substitution chain back to any shorted original
    seen = set()
    cur = line
    while cur is not None and cur.get("substitution_of_line_id"):
        prev_id = cur["substitution_of_line_id"]
        if prev_id in seen:
            break
        seen.add(prev_id)
        cur = store.rider_lines.get(prev_id)
        if cur is not None and cur.get("status") == "SHORTED":
            return True
    return False
