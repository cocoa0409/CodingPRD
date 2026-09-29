"""Derived aggregates the server maintains rather than accepting (PRD §2.8).

Every aggregate here is defined as a pure sum/count over contributing rows, so it
is evaluated from the live store on demand. Recomputing an aggregate is not a
mutation of the owning row: it never moves `updated_at` and never bumps `version`
(the specification increments versions only where it says so explicitly).
"""

from clock import parse_date
from db import db, sorted_rows
from services.constants import OPEN_REPAIR_STATUSES, TERMINAL_REPAIR_STATUSES


# --- child selectors ---------------------------------------------------------

def permits_of_facility(facility_id):
    return sorted_rows([p for p in db.permits.values() if p["facility_id"] == facility_id])


def housing_units_of_facility(facility_id):
    return sorted_rows(
        [h for h in db.housing_units.values() if h["facility_id"] == facility_id]
    )


def deployments_of_facility(facility_id):
    return sorted_rows(
        [d for d in db.crew_deployments.values() if d["facility_id"] == facility_id]
    )


def deployments_of_technician(technician_id):
    return sorted_rows(
        [d for d in db.crew_deployments.values() if d["technician_id"] == technician_id]
    )


def deployments_of_housing_unit(housing_unit_id):
    return sorted_rows(
        [
            d for d in db.crew_deployments.values()
            if d.get("housing_unit_id") == housing_unit_id
        ]
    )


def vehicles_of_facility(facility_id):
    return sorted_rows([v for v in db.vehicles.values() if v["facility_id"] == facility_id])


def vehicles_of_insurer(insurer_id):
    return sorted_rows([v for v in db.vehicles.values() if v["insurer_id"] == insurer_id])


def damage_lines_of_vehicle(vehicle_id):
    return sorted_rows(
        [l for l in db.damage_lines.values() if l["vehicle_id"] == vehicle_id]
    )


def work_tickets_of_vehicle(vehicle_id):
    return sorted_rows(
        [t for t in db.work_tickets.values() if t["vehicle_id"] == vehicle_id]
    )


def work_tickets_of_technician(technician_id):
    return sorted_rows(
        [t for t in db.work_tickets.values() if t["technician_id"] == technician_id]
    )


def supplements_of_vehicle(vehicle_id):
    return sorted_rows(
        [s for s in db.supplements.values() if s["vehicle_id"] == vehicle_id]
    )


def facilities_of_event(storm_event_id):
    return sorted_rows(
        [f for f in db.facilities.values() if f["storm_event_id"] == storm_event_id]
    )


def rate_agreements_of_event(storm_event_id):
    return sorted_rows(
        [r for r in db.rate_agreements.values() if r["storm_event_id"] == storm_event_id]
    )


def vehicles_of_event(storm_event_id):
    result = []
    for facility in facilities_of_event(storm_event_id):
        result.extend(vehicles_of_facility(facility["id"]))
    return result


# --- CrewDeployment ----------------------------------------------------------

def effective_end_date(deployment):
    if deployment["status"] == "ENDED" and deployment.get("actual_end_date"):
        return deployment["actual_end_date"]
    return deployment["end_date"]


# --- HousingUnit -------------------------------------------------------------

def housing_occupied_beds(housing_unit, clock_date):
    count = 0
    for d in deployments_of_housing_unit(housing_unit["id"]):
        if d["status"] not in ("CONFIRMED", "ON_SITE"):
            continue
        start = parse_date(d["start_date"])
        end = parse_date(effective_end_date(d))
        if start <= clock_date < end:
            count += 1
    return count


def housing_bed_nights_committed(housing_unit):
    total = 0
    for d in deployments_of_housing_unit(housing_unit["id"]):
        if d["status"] not in ("CONFIRMED", "ON_SITE", "ENDED"):
            continue
        start = parse_date(d["start_date"])
        end = parse_date(effective_end_date(d))
        total += (end - start).days
    return total


# --- Technician --------------------------------------------------------------

def technician_deployment_state(technician_id):
    for d in deployments_of_technician(technician_id):
        if d["status"] in ("CONFIRMED", "ON_SITE"):
            return "DEPLOYED"
    return "AVAILABLE"


def technician_accrued_pay_cents(technician_id):
    return sum(
        t["payable_cents"] for t in work_tickets_of_technician(technician_id)
        if t["status"] == "APPROVED"
    )


def technician_approved_ticket_count(technician_id):
    return sum(
        1 for t in work_tickets_of_technician(technician_id) if t["status"] == "APPROVED"
    )


# --- Vehicle -----------------------------------------------------------------

def vehicle_approved_supplement_cents(vehicle_id):
    return sum(
        s["approved_amount_cents"] for s in supplements_of_vehicle(vehicle_id)
        if s["status"] in ("AUTO_APPROVED", "APPROVED")
    )


# --- Facility ----------------------------------------------------------------

def facility_staging_slots_occupied(facility_id):
    return sum(
        1 for v in vehicles_of_facility(facility_id)
        if v["repair_status"] in OPEN_REPAIR_STATUSES
    )


def facility_billable_accrued_cents(facility_id):
    return sum(
        v["net_billable_cents"] for v in vehicles_of_facility(facility_id)
        if v["billing_status"] in ("AUTHORIZED", "BILLED", "PAID")
    )


def facility_absorbed_rental_cents(facility_id):
    return sum(
        v["shop_absorbed_rental_cents"] for v in vehicles_of_facility(facility_id)
        if v["repair_status"] in TERMINAL_REPAIR_STATUSES
    )


# --- Insurer -----------------------------------------------------------------

def insurer_outstanding_direct_bill_cents(insurer_id):
    return sum(
        v["net_billable_cents"] for v in vehicles_of_insurer(insurer_id)
        if v["billing_status"] in ("AUTHORIZED", "BILLED")
    )


def insurer_settled_cents(insurer_id):
    return sum(
        v["net_billable_cents"] for v in vehicles_of_insurer(insurer_id)
        if v["billing_status"] == "PAID"
    )


def insurer_active_rate_agreement_count(insurer_id):
    return sum(
        1 for r in db.rate_agreements.values()
        if r["insurer_id"] == insurer_id and r["status"] == "ACTIVE"
    )
