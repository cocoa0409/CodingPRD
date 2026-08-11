"""Cascades (PRD §2.11) and time-driven transitions (PRD §2.4).

Cascades are strictly one-directional and never resurrect. Every affected
resource independently refreshes updated_at and increments version.
"""
from datetime import timedelta

import db
from db import touch
from services import calc


def revoke_active_passes_for_registration(reg):
    """Every ACTIVE RoutePass with registration_id == reg -> REVOKED."""
    for p in db.route_passes.values():
        if p["registration_id"] == reg["id"] and p["status"] == "ACTIVE":
            p["status"] = "REVOKED"
            touch(p)


def suspend_registration(reg):
    """ACTIVE -> SUSPENDED with route-pass cascade."""
    if reg["status"] != "ACTIVE":
        return
    reg["status"] = "SUSPENDED"
    touch(reg)
    revoke_active_passes_for_registration(reg)


def revoke_registration(reg):
    """Registration -> REVOKED (terminal) with route-pass cascade."""
    reg["status"] = "REVOKED"
    touch(reg)
    revoke_active_passes_for_registration(reg)


def recompute_holder_standing(holder):
    """Recompute points_balance and compliance_status; flip into BARRED cascades.

    Flips out of BARRED do NOT auto-reinstate registrations.
    """
    now_dt = db.now()
    old_status = holder["compliance_status"]
    points = calc.holder_points_standing(holder["id"], now_dt)
    new_status = calc.compliance_status_for_points(points)
    holder["points_balance"] = points
    holder["compliance_status"] = new_status
    if old_status != new_status or True:
        touch(holder)
    if old_status != "BARRED" and new_status == "BARRED":
        # cascade hop 2: every ACTIVE registration of the holder -> SUSPENDED
        for reg in db.registrations.values():
            if reg["holder_id"] == holder["id"] and reg["status"] == "ACTIVE":
                suspend_registration(reg)


def latest_finalized_inspection(registration_id):
    """Most recently finalized (PASSED/FAILED) inspection for a registration,
    or None. Finalization order is tracked by a server-side sequence."""
    finals = [i for i in db.inspections.values()
              if i["registration_id"] == registration_id and i["status"] in ("PASSED", "FAILED")]
    if not finals:
        return None
    finals.sort(key=lambda i: (i["_finalize_seq"], i["created_at"], i["id"]))
    return finals[-1]


def has_active_insurance(vehicle_id):
    for p in db.insurance_policies.values():
        if p["vehicle_id"] == vehicle_id and p["status"] == "ACTIVE":
            return True
    return False


def evaluate_time_transitions():
    """Evaluate every time-driven transition at the current logical instant.

    PRD §2.4:
      - registration ACTIVE -> EXPIRED once now > expiry_date
      - registration RENEWAL_PENDING -> EXPIRED once now > expiry_date + late_grace_days
      - route pass ACTIVE -> COMPLETED when now >= end_at
      - charging reservation BOOKED -> COMPLETED once now > end_at
      - fleet dispatch CHECKED_OUT -> OVERDUE once now > shift_end
      - insurance policy ACTIVE -> EXPIRED once current date > expiry_date
        (the expiry date itself is the last covered day)
    """
    now_dt = db.now()
    today = now_dt.date()

    for reg in db.registrations.values():
        if reg["status"] == "ACTIVE" and reg.get("expiry_date") is not None:
            if now_dt > reg["expiry_date"]:
                reg["status"] = "EXPIRED"
                touch(reg)
        elif reg["status"] == "RENEWAL_PENDING" and reg.get("expiry_date") is not None:
            community = db.communities.get(reg.get("_community_id"))
            grace = community["late_grace_days"] if community else 90
            if now_dt > reg["expiry_date"] + timedelta(days=grace):
                reg["status"] = "EXPIRED"
                touch(reg)

    for p in db.route_passes.values():
        if p["status"] == "ACTIVE" and now_dt >= p["end_at"]:
            p["status"] = "COMPLETED"
            touch(p)

    for r in db.charging_reservations.values():
        if r["status"] == "BOOKED" and now_dt > r["end_at"]:
            r["status"] = "COMPLETED"
            touch(r)

    for d in db.fleet_dispatches.values():
        if d["status"] == "CHECKED_OUT" and now_dt > d["shift_end"]:
            d["status"] = "OVERDUE"
            touch(d)

    for pol in db.insurance_policies.values():
        if pol["status"] == "ACTIVE" and today > pol["expiry_date"]:
            pol["status"] = "EXPIRED"
            touch(pol)
