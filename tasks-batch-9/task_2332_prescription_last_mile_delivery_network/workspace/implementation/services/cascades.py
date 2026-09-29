"""Shared cascade helpers: allocation lifecycle, assignment revocation, case opening."""

from db import db, new_row, sort_rows, touch
from services import couriers as courier_service
from services import derive


def sync_fee_mirror(delivery):
    """Delivery.fee_subtotal_cents always mirrors the ACTIVE allocation (0 when none)."""
    delivery["fee_subtotal_cents"] = derive.fee_subtotal_cents(delivery)


def released_funds(delivery):
    """Funds an ACTIVE allocation currently holds, keyed by grant, without mutating."""
    allocation = derive.active_allocation(delivery)
    if allocation is None or not allocation["plan_grant_id"]:
        return {}
    return {allocation["plan_grant_id"]: allocation["plan_grant_cents"]}


def close_out_allocation(delivery, new_status):
    """Set the ACTIVE allocation to VOIDED or SUPERSEDED and release its grant funds."""
    allocation = derive.active_allocation(delivery)
    if allocation is None:
        return None
    allocation["status"] = new_status
    touch(allocation)
    grant = db.plan_grants.get(allocation["plan_grant_id"]) if allocation["plan_grant_id"] else None
    if grant is not None:
        touch(grant)
    sync_fee_mirror(delivery)
    return allocation


def replace_allocation(delivery, new_status, values):
    """Supersede/void the ACTIVE allocation and commit its replacement in one step.

    Every grant pool involved bumps its version exactly once.
    """
    from services import money

    old = derive.active_allocation(delivery)
    old_grant_id = old["plan_grant_id"] if old else None
    if old is not None:
        old["status"] = new_status
        touch(old)
    allocation = money.write_allocation(delivery, values)
    touched = set()
    for grant_id in (old_grant_id, values.get("plan_grant_id")):
        if grant_id and grant_id not in touched:
            touched.add(grant_id)
            touch(db.plan_grants.get(grant_id))
    sync_fee_mirror(delivery)
    return allocation


def commit_allocation(delivery, values):
    """Write a new allocation row and bump the funding pool."""
    from services import money

    allocation = money.write_allocation(delivery, values)
    grant = db.plan_grants.get(values["plan_grant_id"]) if values["plan_grant_id"] else None
    if grant is not None:
        touch(grant)
    sync_fee_mirror(delivery)
    return allocation


def live_assignments(delivery):
    return [a for a in sort_rows(list(db.courier_assignments.values()))
            if a["delivery_id"] == delivery["id"] and a["status"] in {"OFFERED", "ACCEPTED"}]


def accepted_assignment(delivery):
    for assignment in sort_rows(list(db.courier_assignments.values())):
        if assignment["delivery_id"] == delivery["id"] and assignment["status"] == "ACCEPTED":
            return assignment
    return None


def exclude_courier(delivery, courier_id):
    if courier_id and courier_id not in delivery["excluded_courier_ids"]:
        delivery["excluded_courier_ids"].append(courier_id)


def revoke_live_assignments(delivery, ops_user_id=None, notes=None):
    """Used by cancel and reschedule; ops_user_id stays null for those paths."""
    for assignment in live_assignments(delivery):
        was_accepted = assignment["status"] == "ACCEPTED"
        assignment["status"] = "REVOKED"
        assignment["revoked_by_ops_user_id"] = ops_user_id
        if notes is not None:
            assignment["notes"] = notes
        touch(assignment)
        exclude_courier(delivery, assignment["courier_id"])
        courier = db.couriers.get(assignment["courier_id"])
        if was_accepted:
            if delivery["custody_status"] == "ASSIGNED":
                delivery["custody_status"] = "QUEUED"
                delivery["courier_id"] = None
            courier_service.release_courier(courier)
        else:
            touch(courier)


def open_system_case(delivery, exception_type):
    case = new_row()
    case["delivery_id"] = delivery["id"]
    case["reship_delivery_id"] = None
    case["exception_type"] = exception_type
    case["status"] = "OPEN"
    case["opened_by_ops_user_id"] = None
    case["adjudicated_by_ops_user_id"] = None
    case["disposition"] = None
    case["credit_cents"] = 0
    case["notes"] = None
    db.exception_cases[case["id"]] = case
    return case


def order_of(delivery):
    return db.pharmacy_orders.get(delivery["order_id"])


def window_of(delivery):
    return db.delivery_windows.get(delivery["window_id"])


def zone_of_window(window):
    return db.delivery_zones.get(window["zone_id"]) if window else None
