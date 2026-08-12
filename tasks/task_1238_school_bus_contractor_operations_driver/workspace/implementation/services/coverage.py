"""Service-day coverage recomputation and cascading side effects (PRD §2.9)."""
import db

COVERED_STATUSES = ("CONFIRMED", "EN_ROUTE", "COMPLETED")
OPEN_WORK_ORDER_STATUSES = ("OPEN", "DIAGNOSING", "WAITING_PARTS", "IN_REPAIR")


def recompute_day_coverage(day):
    """Live dispatch metric: covered = assignments with driver_id set and
    status in {CONFIRMED, EN_ROUTE, COMPLETED}. Bumps the day's version when
    any tracked figure changes."""
    assignments = db.assignments_of_day(day["id"])
    covered = sum(
        1
        for a in assignments
        if a.get("driver_id") is not None and a["status"] in COVERED_STATUSES
    )
    uncovered = day["required_routes"] - covered
    flag = uncovered > 0
    changed = (
        day["covered_routes"] != covered
        or day["uncovered_routes"] != uncovered
        or day["shortage_flag"] != flag
    )
    if changed:
        day["covered_routes"] = covered
        day["uncovered_routes"] = uncovered
        day["shortage_flag"] = flag
        db.touch(day)


def cancel_assignment(assignment, reason):
    assignment["status"] = "CANCELLED"
    assignment["cancellation_reason"] = reason
    db.touch(assignment)
    day = db.day_of_assignment(assignment)
    if day is not None:
        recompute_day_coverage(day)


def suspend_driver(driver, reason):
    """Driver ACTIVE -> SUSPENDED with the assignment cancellation cascade."""
    if driver["status"] != "ACTIVE":
        return
    driver["status"] = "SUSPENDED"
    driver["suspension_reason"] = reason
    db.touch(driver)
    today = db.clock_date()
    for a in list(db.all_of("assignments")):
        if a.get("driver_id") != driver["id"]:
            continue
        if a["status"] != "CONFIRMED":
            continue
        day = db.day_of_assignment(a)
        if day is not None and day["service_date"] >= today.isoformat():
            cancel_assignment(a, "DRIVER_SUSPENDED")


def terminate_driver_cascade(driver):
    """Driver TERMINATE: cancel PLANNED|CONFIRMED future assignments."""
    today = db.clock_date()
    for a in list(db.all_of("assignments")):
        if a.get("driver_id") != driver["id"]:
            continue
        if a["status"] not in ("PLANNED", "CONFIRMED"):
            continue
        day = db.day_of_assignment(a)
        if day is not None and day["service_date"] >= today.isoformat():
            cancel_assignment(a, "DRIVER_SUSPENDED")


def ground_bus(bus):
    """Bus -> GROUNDED plus future assignment cancellations (BUS_GROUNDED)."""
    if bus["status"] == "DECOMMISSIONED":
        return
    if bus["status"] != "GROUNDED":
        bus["status"] = "GROUNDED"
        db.touch(bus)
    today = db.clock_date()
    for a in list(db.all_of("assignments")):
        if a.get("bus_id") != bus["id"]:
            continue
        if a["status"] not in ("PLANNED", "CONFIRMED"):
            continue
        day = db.day_of_assignment(a)
        if day is not None and day["service_date"] >= today.isoformat():
            cancel_assignment(a, "BUS_GROUNDED")


def maybe_return_bus_to_service(bus, check_inspection_due=True):
    """Return an IN_SHOP (or GROUNDED, via inspection PASS) bus to IN_SERVICE
    when the conditions hold."""
    if bus["status"] not in ("IN_SHOP", "GROUNDED"):
        return
    for wo in db.all_of("work_orders"):
        if wo["bus_id"] == bus["id"] and wo["status"] in OPEN_WORK_ORDER_STATUSES:
            return
    for insp in db.all_of("inspections"):
        if insp["bus_id"] == bus["id"] and insp["status"] in ("FAILED", "OVERDUE"):
            return
    if check_inspection_due:
        due = db.parse_date(bus.get("next_inspection_due"))
        if due is None or due < db.clock_date():
            return
    bus["status"] = "IN_SERVICE"
    db.touch(bus)


def return_bus_after_inspection_pass(bus):
    """Inspection PASS path: only the open-work-order condition applies."""
    if bus["status"] not in ("IN_SHOP", "GROUNDED"):
        return
    for wo in db.all_of("work_orders"):
        if wo["bus_id"] == bus["id"] and wo["status"] in OPEN_WORK_ORDER_STATUSES:
            return
    bus["status"] = "IN_SERVICE"
    db.touch(bus)


def terminate_contract_cascade(contract):
    """Contract ACTIVE -> TERMINATED: routes archived, future days and their
    assignments cancelled, open charters cancelled fee-free."""
    today = db.clock_date()
    for route in db.all_of("routes"):
        if route["contract_id"] == contract["id"] and route["status"] in (
            "ACTIVE",
            "SUSPENDED",
        ):
            route["status"] = "ARCHIVED"
            db.touch(route)
    for day in db.all_of("service_days"):
        if day["contract_id"] != contract["id"]:
            continue
        if day["status"] in ("SCHEDULED", "DISPATCH_OPEN", "LOCKED"):
            day["status"] = "CANCELLED"
            day["cancellation_reason"] = "CONTRACT_TERMINATED"
            db.touch(day)
            for a in db.assignments_of_day(day["id"]):
                if a["status"] in ("PLANNED", "CONFIRMED"):
                    a["status"] = "CANCELLED"
                    a["cancellation_reason"] = "CONTRACT_TERMINATED"
                    db.touch(a)
    for trip in db.all_of("charter_trips"):
        if trip["contract_id"] != contract["id"]:
            continue
        if trip["status"] in ("REQUESTED", "QUOTED", "APPROVED", "SCHEDULED"):
            trip["status"] = "CANCELLED"
            trip["cancel_fee_cents"] = 0
            trip["refund_cents"] = trip.get("deposit_cents") or 0
            db.touch(trip)


def expire_credential_cascade(credential):
    """Credential lost (EXPIRED/REVOKED): suspend ACTIVE holder of CDL_B /
    S_ENDORSEMENT with the assignment cascade."""
    if credential["kind"] not in ("CDL_B", "S_ENDORSEMENT"):
        return
    driver = db.find("drivers", credential["driver_id"])
    if driver is not None and driver["status"] == "ACTIVE":
        suspend_driver(driver, "CREDENTIAL_LAPSED")
