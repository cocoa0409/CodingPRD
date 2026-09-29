"""Cross-aggregate side effects: the escalation counter, the two car state
dimensions, the decommission / termination cascades and the epoch sweep."""

from datetime import timedelta

from common import (
    db, touch, parse_dt, parse_date_str, clock_iso, clock_date, now_clock,
    month_bounds, cars_of_contract, windows_of_car, callbacks_of_car,
    inspections_of_car, part_orders_of_car, projects_of_contract,
    rounds_of_contract, windows_of_project,
    OUT_OF_SERVICE_ESCALATION_COUNT,
)
from calc import (
    recompute_scheduled_downtime, recompute_window_count, OCCUPYING_WINDOW_STATES,
)

OPEN_CALLBACK_STATES = ("REPORTED", "ESCALATED", "ON_SITE")


# --------------------------------------------------------------------------
# contract_escalation_counter
# --------------------------------------------------------------------------
def refresh_out_of_service_count(contract):
    """Recount and apply the ACTIVE <-> SERVICE_ALERT escalation."""
    if contract is None:
        return
    count = 0
    for car in db.cars.values():
        if car["contract_id"] == contract["id"] and car["availability_state"] == "OUT_OF_SERVICE":
            count += 1
    contract["cars_out_of_service_count"] = count
    if contract["status"] == "ACTIVE" and count >= OUT_OF_SERVICE_ESCALATION_COUNT:
        contract["status"] = "SERVICE_ALERT"
        touch(contract)
    elif contract["status"] == "SERVICE_ALERT" and count < OUT_OF_SERVICE_ESCALATION_COUNT:
        contract["status"] = "ACTIVE"
        touch(contract)


# --------------------------------------------------------------------------
# ElevatorCar availability dimension
# --------------------------------------------------------------------------
def car_has_open_out_of_service_callback(car, ignore_callback_id=None):
    for cb in callbacks_of_car(car["id"]):
        if ignore_callback_id is not None and cb["id"] == ignore_callback_id:
            continue
        if cb["status"] in OPEN_CALLBACK_STATES and cb.get("out_of_service"):
            return True
    return False


def take_car_out_of_service(car):
    """IN_SERVICE -> OUT_OF_SERVICE. Returns True when the car actually moved."""
    if car["availability_state"] != "IN_SERVICE":
        return False
    car["availability_state"] = "OUT_OF_SERVICE"
    car["unplanned_outage_open_since"] = clock_iso()
    touch(car)
    refresh_out_of_service_count(db.contracts.get(car["contract_id"]))
    return True


def return_car_to_service(car, ignore_callback_id=None):
    """OUT_OF_SERVICE -> IN_SERVICE when nothing else holds the car down."""
    if car["availability_state"] != "OUT_OF_SERVICE":
        return False
    if car["compliance_state"] == "RED_TAGGED":
        return False
    if car_has_open_out_of_service_callback(car, ignore_callback_id):
        return False
    car["availability_state"] = "IN_SERVICE"
    car["unplanned_outage_open_since"] = None
    touch(car)
    refresh_out_of_service_count(db.contracts.get(car["contract_id"]))
    return True


# --------------------------------------------------------------------------
# Certificate mirror fields on the car
# --------------------------------------------------------------------------
def recompute_certificate_mirrors(car):
    """Posted certificate with the greatest expiry; ties -> earliest created_at."""
    best = None
    for insp in inspections_of_car(car["id"]):
        if insp.get("certificate_state") != "POSTED":
            continue
        expiry = insp.get("certificate_expiry_date")
        if expiry is None:
            continue
        if best is None:
            best = insp
            continue
        best_expiry = best.get("certificate_expiry_date")
        if expiry > best_expiry:
            best = insp
        elif expiry == best_expiry and insp["_seq"] < best["_seq"]:
            best = insp
    if best is None:
        car["current_certificate_number"] = None
        car["certificate_expiry_date"] = None
    else:
        car["current_certificate_number"] = best.get("certificate_number")
        car["certificate_expiry_date"] = best.get("certificate_expiry_date")


# --------------------------------------------------------------------------
# Car decommissioning cascade (§3.1)
# --------------------------------------------------------------------------
def decommission_car(car):
    contract = db.contracts.get(car["contract_id"])
    touched_projects = set()

    for order in part_orders_of_car(car["id"]):
        if order["status"] in ("ORDERED", "SUBSTITUTED"):
            order["status"] = "CANCELLED"
            touch(order)
            if car["open_part_order_count"] > 0:
                car["open_part_order_count"] -= 1

    for window in windows_of_car(car["id"]):
        if window["status"] == "SCHEDULED":
            window["status"] = "CANCELLED"
            touch(window)
            if window.get("project_id"):
                touched_projects.add(window["project_id"])
    recompute_scheduled_downtime(car)

    for insp in inspections_of_car(car["id"]):
        if insp["status"] == "SCHEDULED":
            insp["status"] = "CANCELLED"
            touch(insp)

    for cb in callbacks_of_car(car["id"]):
        if cb["status"] in OPEN_CALLBACK_STATES:
            cb["status"] = "CANCELLED"
            touch(cb)

    car["availability_state"] = "DECOMMISSIONED"
    touch(car)

    for project_id in touched_projects:
        project = db.projects.get(project_id)
        if project is None or project["status"] in ("COMPLETE", "CANCELLED"):
            continue
        new_count = recompute_window_count(project)
        if new_count != project["window_count"]:
            project["window_count"] = new_count
            touch(project)

    refresh_out_of_service_count(contract)


# --------------------------------------------------------------------------
# Contract termination cascade (§3.1)
# --------------------------------------------------------------------------
def terminate_contract(contract):
    for rnd in rounds_of_contract(contract["id"]):
        if rnd["status"] in ("OPEN", "COUNTERED"):
            rnd["status"] = "WITHDRAWN"
            touch(rnd)

    affected_cars = set()
    for project in projects_of_contract(contract["id"]):
        if project["status"] not in ("PLANNED", "APPROVED", "IN_PROGRESS", "AT_RISK"):
            continue
        project["status"] = "CANCELLED"
        touch(project)
        for window in windows_of_project(project["id"]):
            if window["status"] == "SCHEDULED":
                window["status"] = "CANCELLED"
                touch(window)
                affected_cars.add(window["car_id"])

    for car_id in affected_cars:
        car = db.cars.get(car_id)
        if car is None:
            continue
        if recompute_scheduled_downtime(car):
            touch(car)

    contract["status"] = "TERMINATED"
    touch(contract)


# --------------------------------------------------------------------------
# Epoch sweep (§2.5)
# --------------------------------------------------------------------------
def _month_close_instant(period_month):
    _, end = month_bounds(period_month)
    return end


def epoch_sweep():
    clock = now_clock()
    today = clock_date()
    counters = {
        "missed_visits_marked": 0,
        "rejected_visits_marked": 0,
        "certificates_expired": 0,
        "windows_completed": 0,
        "cars_under_modernization": 0,
    }

    # 1. Visits whose billing month has closed.
    for visit in sorted(db.visits.values(), key=lambda v: v["_seq"]):
        if visit["status"] not in ("SCHEDULED", "DISPUTED"):
            continue
        if clock < _month_close_instant(visit["period_month"]):
            continue
        if visit["status"] == "SCHEDULED":
            visit["status"] = "MISSED"
            counters["missed_visits_marked"] += 1
        else:
            visit["status"] = "REJECTED"
            counters["rejected_visits_marked"] += 1
        touch(visit)

    # 2. Posted certificates past their expiry date.
    cars_touched_for_certificates = set()
    for insp in sorted(db.inspections.values(), key=lambda i: i["_seq"]):
        if insp.get("certificate_state") != "POSTED":
            continue
        expiry = parse_date_str(insp.get("certificate_expiry_date"))
        if expiry is None or today <= expiry:
            continue
        insp["certificate_state"] = "EXPIRED"
        touch(insp)
        counters["certificates_expired"] += 1
        cars_touched_for_certificates.add(insp["car_id"])

    for car_id in cars_touched_for_certificates:
        car = db.cars.get(car_id)
        if car is None:
            continue
        recompute_certificate_mirrors(car)
        if car["compliance_state"] == "CERTIFIED":
            car["compliance_state"] = "CERTIFICATE_EXPIRED"
        touch(car)

    # 3. Scheduled windows the clock has reached or passed the end of.
    completed_cars = set()
    for window in sorted(db.windows.values(), key=lambda w: w["_seq"]):
        if window["status"] != "SCHEDULED":
            continue
        end = parse_dt(window["window_end"])
        if end is None or clock < end:
            continue
        window["status"] = "COMPLETED"
        touch(window)
        counters["windows_completed"] += 1
        completed_cars.add(window["car_id"])

    # 4/5. Modernization occupancy on the availability dimension.
    for car in sorted(db.cars.values(), key=lambda c: c["_seq"]):
        if car["availability_state"] == "DECOMMISSIONED":
            continue
        active_windows = []
        for window in windows_of_car(car["id"]):
            if window["status"] != "SCHEDULED" or window["window_type"] != "MODERNIZATION":
                continue
            start = parse_dt(window["window_start"])
            end = parse_dt(window["window_end"])
            if start is None or end is None:
                continue
            if start <= clock < end:
                active_windows.append(window)
        if active_windows:
            if car["availability_state"] == "IN_SERVICE":
                car["availability_state"] = "UNDER_MODERNIZATION"
                touch(car)
                counters["cars_under_modernization"] += 1
            for window in active_windows:
                project = db.projects.get(window.get("project_id")) if window.get("project_id") else None
                if project is not None and project["status"] == "APPROVED":
                    project["status"] = "IN_PROGRESS"
                    touch(project)
        elif car["availability_state"] == "UNDER_MODERNIZATION":
            car["availability_state"] = "IN_SERVICE"
            touch(car)

    for car_id in completed_cars:
        car = db.cars.get(car_id)
        if car is not None:
            recompute_scheduled_downtime(car)

    return counters
