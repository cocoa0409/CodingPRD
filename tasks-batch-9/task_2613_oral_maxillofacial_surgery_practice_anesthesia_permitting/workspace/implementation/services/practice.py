"""Practice-level derived state: privilege, drill compliance and rolling counters."""
from datetime import timedelta
from decimal import Decimal

from flask import g

from db import clock_dt, db, touch
from services.domain import (DRILL_COMPLIANCE_FLOOR, DRILL_WINDOW_DAYS,
                             PRIVILEGE_BY_PERMIT_STATUS, REQUIRED_DRILL_TYPES,
                             get_case, get_lot, open_permit)
from timeutil import parse_date, r2


def touch_practice(practice):
    """Bump the practice row at most once per request, however many hops touch it."""
    marks = getattr(g, "touched_practices", None)
    if marks is None:
        marks = set()
        g.touched_practices = marks
    if practice["id"] not in marks:
        marks.add(practice["id"])
        touch(practice)
    return practice


def privilege_for(practice_id):
    permit = open_permit(practice_id)
    if permit is None:
        return "UNPERMITTED"
    return PRIVILEGE_BY_PERMIT_STATUS.get(permit["status"], "UNPERMITTED")


def recompute_privilege(practice):
    practice["sedation_privilege_state"] = privilege_for(practice["id"])
    return practice["sedation_privilege_state"]


def drill_compliance(practice_id, permit_level):
    """calculations.drill_compliance_ratio -> (ratio, covered types in required order)."""
    required = list(REQUIRED_DRILL_TYPES.get(permit_level, []))
    if not required:
        return Decimal("0.00"), []
    now = clock_dt()
    floor_instant = now - timedelta(days=DRILL_WINDOW_DAYS)
    covered = []
    for drill_type in required:
        for drill in db.drills.values():
            if drill["practice_id"] != practice_id:
                continue
            if drill["drill_type"] != drill_type:
                continue
            if drill.get("deficiency_noted"):
                continue
            conducted = parse_date(drill["conducted_at"])
            if conducted is None:
                continue
            # Strictly newer than the 365-day floor, and never in the future.
            if conducted <= floor_instant or conducted > now:
                continue
            covered.append(drill_type)
            break
    ratio = r2(Decimal(len(covered)) / Decimal(len(required)))
    return ratio, covered


def permit_ratio(permit):
    if permit is None:
        return Decimal("0.00")
    ratio, _covered = drill_compliance(permit["practice_id"], permit["permit_level"])
    return ratio


def refresh_permit_ratio(permit):
    """Recompute and persist the open permit's ratio (drill log, inspection, sweep)."""
    ratio = permit_ratio(permit)
    permit["drill_compliance_ratio"] = float(ratio)
    return ratio


def is_drill_compliant(ratio):
    return Decimal(str(ratio)) >= DRILL_COMPLIANCE_FLOOR


def recompute_consignment(practice):
    """Sum HELD/CONSUMED liability over every reservation on a lot of this practice."""
    total = 0
    for reservation in db.reservations.values():
        if reservation["status"] not in ("HELD", "CONSUMED"):
            continue
        lot = get_lot(reservation["lot_id"])
        if lot is None or lot["practice_id"] != practice["id"]:
            continue
        total += int(reservation.get("consignment_liability_cents") or 0)
    practice["consignment_committed_cents"] = total
    return total


def recompute_open_adverse_events(practice):
    total = 0
    for event in db.events.values():
        if event["status"] == "CLOSED":
            continue
        case = get_case(event["case_id"])
        if case is None or case["practice_id"] != practice["id"]:
            continue
        total += 1
    practice["open_adverse_event_count"] = total
    return total


def compliance_summary(practice):
    permit = open_permit(practice["id"])
    level = permit["permit_level"] if permit else None
    ratio, covered = drill_compliance(practice["id"], level) if permit else (Decimal("0.00"), [])
    required = list(REQUIRED_DRILL_TYPES.get(level, [])) if permit else []
    return {
        "practice_id": practice["id"],
        "sedation_privilege_state": privilege_for(practice["id"]),
        "open_permit_id": permit["id"] if permit else None,
        "permit_status": permit["status"] if permit else None,
        "permit_level": level,
        "required_drill_types": required,
        "covered_drill_types": covered,
        "drill_compliance_ratio": float(ratio),
        "drill_compliant": bool(is_drill_compliant(ratio)) if permit else False,
        "open_adverse_event_count": int(practice.get("open_adverse_event_count") or 0),
        "consignment_committed_cents": int(practice.get("consignment_committed_cents") or 0),
        "consignment_credit_limit_cents": int(practice.get("consignment_credit_limit_cents") or 0),
    }
