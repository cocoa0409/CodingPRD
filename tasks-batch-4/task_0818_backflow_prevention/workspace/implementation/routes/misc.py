from flask import Blueprint, request

import store
from auth import authenticate, require_role
from util import (
    ApiError, object_response, array_response, paginate, apply_list, serialize,
    fmt_dt, whole_days_between, round_half_up_2,
)
from decimal import Decimal
import validate as v
import services as svc
import lookups as lk

bp = Blueprint("misc", __name__)

REMINDER_TYPES = {"UPCOMING_DUE", "OVERDUE"}
HAZARD_CLASSES = {"HIGH_HAZARD", "LOW_HAZARD"}


@bp.post("/reminders/generate")
def generate_reminders():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    now = store.current_utc()

    generated = upcoming = overdue = 0
    for device in list(store.devices.values()):
        if device["status"] not in ("ACTIVE", "NEEDS_REPAIR"):
            continue
        if device["next_test_due_date"] is None:
            continue
        days = whole_days_between(device["next_test_due_date"], now)
        if days > svc.REMINDER_LEAD_DAYS:
            continue
        if days < 0:
            rtype = "OVERDUE"
            overdue += 1
        else:
            rtype = "UPCOMING_DUE"
            upcoming += 1
        reminder = {
            "device_id": device["id"],
            "reminder_type": rtype,
            "generated_date": now,
            "days_until_due": days,
        }
        svc.stamp_new(reminder)
        store.reminders[reminder["id"]] = reminder
        generated += 1

    summary = {
        "generated_count": generated,
        "upcoming_count": upcoming,
        "overdue_count": overdue,
    }
    return object_response(summary, 201)


@bp.get("/reminders")
def list_reminders():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "PremisesOwner"})
    limit, offset = paginate(request.args)

    did = request.args.get("device_id")
    rtype = request.args.get("reminder_type")

    pool = list(store.reminders.values())
    if did is not None:
        pool = [r for r in pool if r["device_id"] == did]
    if rtype is not None:
        pool = [r for r in pool if r["reminder_type"] == rtype]
    if role == "PremisesOwner":
        pool = [r for r in pool
                if lk.owns_connection(lk.connection_of_device(store.devices.get(r["device_id"])), user_id)]

    items, total = apply_list(pool, limit, offset)
    return array_response(items, limit, offset, total)


@bp.get("/reminders/<rid>")
def get_reminder(rid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "PremisesOwner"})
    reminder = lk.get_reminder(rid)
    if role == "PremisesOwner":
        lk.ensure_owner_device(store.devices.get(reminder["device_id"]), role, user_id)
    return object_response(serialize(reminder))


@bp.get("/utility-report")
def utility_report():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    hazard_class = request.args.get("hazard_class")

    pool = list(store.connections.values())
    if hazard_class is not None:
        pool = [c for c in pool if c["hazard_class"] == hazard_class]

    for c in pool:
        svc.read_recompute(c)

    total = len(pool)
    compliant = sum(1 for c in pool if c["compliance_posture"] == "COMPLIANT")
    non_compliant = sum(1 for c in pool
                        if c["compliance_posture"] in ("NON_COMPLIANT", "SHUTOFF"))
    if total == 0:
        rate = 0.00
    else:
        rate = float(round_half_up_2(Decimal(compliant) / Decimal(total) * Decimal(100)))

    return object_response({
        "total_connections": total,
        "compliant_count": compliant,
        "non_compliant_count": non_compliant,
        "compliance_rate": rate,
    })


@bp.post("/_clock/set_current_utc")
def set_clock():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    body = v.json_object()
    new_now = v.req_datetime(body, "to_iso8601")
    store.set_current_utc(new_now)

    # side effect: expire testers whose certification window has closed
    for tester in store.testers.values():
        if tester["status"] in ("ACTIVE", "SUSPENDED") and new_now > tester["cert_expiry_date"]:
            tester["status"] = "EXPIRED"
            svc.touch(tester)

    return object_response({"current_utc": fmt_dt(new_now)})
