"""Allocation sweep and time-based clock sweeps."""
from db import db


def allocation_sweep():
    """Waterfall allocation over ComponentOrders in PENDING_ALLOCATION/BACKORDERED.

    Processing order: created_at ASC; exact ties broken by required_units ASC
    (never by id).
    """
    candidates = [
        o for o in db.component_orders.values()
        if o["status"] in ("PENDING_ALLOCATION", "BACKORDERED")
    ]
    candidates.sort(key=lambda o: (o["created_at"], o["required_units"]))
    for order in candidates:
        for line in order["lines"]:
            item = db.component_items[line["component_item_id"]]
            remainder = line["required_qty"] - line["allocated_qty"]
            allocatable = min(remainder, item["stock_on_hand"])
            if allocatable > 0:
                item["stock_on_hand"] -= allocatable
                item["stock_reserved"] += allocatable
                line["allocated_qty"] += allocatable
        all_satisfied = all(
            line["allocated_qty"] >= line["required_qty"] for line in order["lines"]
        )
        new_status = "ALLOCATED" if all_satisfied else "BACKORDERED"
        if new_status != order["status"]:
            order["status"] = new_status
            order["version"] += 1
            order["updated_at"] = db.logical_now
        if new_status == "ALLOCATED":
            spec = db.build_specs.get(order["build_spec_id"])
            if spec is not None and spec["status"] == "ORDERED":
                spec["status"] = "IN_BUILD"
                spec["version"] += 1
                spec["updated_at"] = db.logical_now


def run_time_sweeps():
    """Run all time-based sweeps against the current logical clock."""
    now = db.logical_now

    # OFFERED appraisals past offer_expires_at -> EXPIRED
    for appraisal in db.trade_in_appraisals.values():
        if (
            appraisal["status"] == "OFFERED"
            and appraisal["offer_expires_at"] is not None
            and now > appraisal["offer_expires_at"]
        ):
            appraisal["status"] = "EXPIRED"
            appraisal["version"] += 1
            appraisal["updated_at"] = now

    # RESERVED listings past reserved_until -> LISTED (clear reservation fields)
    for listing in db.used_club_listings.values():
        if (
            listing["status"] == "RESERVED"
            and listing["reserved_until"] is not None
            and now > listing["reserved_until"]
        ):
            listing["status"] = "LISTED"
            listing["reserved_by_customer_id"] = None
            listing["reserved_until"] = None
            listing["version"] += 1
            listing["updated_at"] = now

    # ACTIVE/EXHAUSTED packages past expires_at -> EXPIRED
    for package in db.lesson_packages.values():
        if package["status"] in ("ACTIVE", "EXHAUSTED") and now > package["expires_at"]:
            package["status"] = "EXPIRED"
            package["version"] += 1
            package["updated_at"] = now

    # BOOKED sessions with ends_at < now -> NO_SHOW (credit forfeited)
    for session in db.fitting_sessions.values():
        if session["status"] == "BOOKED" and now > session["ends_at"]:
            session["status"] = "NO_SHOW"
            session["version"] += 1
            session["updated_at"] = now
