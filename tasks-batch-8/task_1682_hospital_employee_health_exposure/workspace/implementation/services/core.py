"""Employee compliance posture derivation, hold and restriction side effects."""
from db import base_fields, now, store, touch


def recompute_posture(emp):
    """compliance_posture_derivation: holds dominate restrictions (pinned order)."""
    if emp["active_hold_count"] > 0:
        emp["compliance_posture"] = "ON_HOLD"
    elif any(
        r["employee_id"] == emp["id"]
        and r["status"] == "ACTIVE"
        and r["restriction_type"] == "FULL_EXCLUSION"
        for r in store.restrictions.values()
    ):
        emp["compliance_posture"] = "WORK_EXCLUDED"
    elif emp["open_restriction_count"] > 0:
        emp["compliance_posture"] = "RESTRICTED_DUTY"
    else:
        emp["compliance_posture"] = "CLEAR"


def adjust_hold_count(emp, delta):
    """Employee status derives on the hold axis only; never leaves PREPLACEMENT here.

    Returns True when the employee status transitioned (ACTIVE<->SUSPENDED).
    """
    emp["active_hold_count"] += delta
    transitioned = False
    if emp["active_hold_count"] > 0 and emp["status"] == "ACTIVE":
        emp["status"] = "SUSPENDED"
        transitioned = True
    elif emp["active_hold_count"] == 0 and emp["status"] == "SUSPENDED":
        emp["status"] = "ACTIVE"
        transitioned = True
    recompute_posture(emp)
    touch(emp)
    return transitioned


def adjust_restriction_count(emp, delta):
    emp["open_restriction_count"] += delta
    recompute_posture(emp)
    touch(emp)


def create_hold(employee_id, reason, cycle_id=None, participation_id=None):
    """Auto-create an ACTIVE ComplianceHold and cascade the employee count/status.

    Returns (hold, employee_transitioned).
    """
    emp = store.employees[employee_id]
    hold = base_fields()
    hold.update(
        {
            "employee_id": employee_id,
            "cycle_id": cycle_id,
            "participation_id": participation_id,
            "reason": reason,
            "status": "ACTIVE",
            "applied_at": now(),
            "released_at": None,
            "released_by_user_id": None,
        }
    )
    store.holds[hold["id"]] = hold
    transitioned = adjust_hold_count(emp, +1)
    return hold, transitioned


def create_restriction(employee_id, restriction_type, start_date, end_date, origin,
                       exposure_case_id=None):
    emp = store.employees[employee_id]
    r = base_fields()
    r.update(
        {
            "employee_id": employee_id,
            "exposure_case_id": exposure_case_id,
            "restriction_type": restriction_type,
            "start_date": start_date,
            "end_date": end_date,
            "status": "ACTIVE",
            "origin": origin,
        }
    )
    store.restrictions[r["id"]] = r
    adjust_restriction_count(emp, +1)
    return r


def lift_restriction(restriction, new_status):
    """ACTIVE -> LIFTED/EXPIRED with count decrement and posture recompute."""
    emp = store.employees[restriction["employee_id"]]
    restriction["status"] = new_status
    touch(restriction)
    adjust_restriction_count(emp, -1)
