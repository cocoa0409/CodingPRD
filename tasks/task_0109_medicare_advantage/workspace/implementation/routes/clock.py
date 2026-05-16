"""Test clock endpoints: GET /_clock and POST /_clock/advance."""
from datetime import timedelta
from flask import Blueprint, g, request

from auth import require_roles
from errors import err
from response import ok_object
from store import store
from utils import iso_string, parse_iso_datetime, require_field, stamp_update

bp = Blueprint("clock", __name__)


def _period_status_for_clock(period: dict, now) -> str:
    """Recompute a period's status given the current clock — but CONSUMED stays CONSUMED."""
    if period["status"] == "CONSUMED":
        return "CONSUMED"
    ws = period["_window_start_dt"]
    we = period["_window_end_dt"]
    if now < ws:
        return "SCHEDULED"
    if ws <= now <= we:
        return "OPEN"
    return "CLOSED"


def _recompute_periods_and_lifecycles(now_iso_str: str) -> list:
    """For the current clock, recompute every period's status and every beneficiary's
    lifecycle_status (PRE_ELIGIBLE / IEP_OPEN / IEP_CLOSED transitions only).

    Returns a list of {entity_type, entity_id, from, to} transitions applied.
    """
    transitions = []
    now = store.clock

    # First, recompute period status
    for pid, period in store.enrollment_periods.items():
        prev = period["status"]
        new_status = _period_status_for_clock(period, now)
        if new_status != prev:
            period["status"] = new_status
            stamp_update(period, store_now_iso=now_iso_str)
            transitions.append({
                "entity_type": "EnrollmentPeriod",
                "entity_id": pid,
                "from": prev,
                "to": new_status,
            })

    # Now beneficiary lifecycle auto-transitions
    for bid, b in store.beneficiaries.items():
        lc = b["lifecycle_status"]
        if lc == "PRE_ELIGIBLE":
            iep_start = b["_iep_start_dt"]
            iep_end = b["_iep_end_dt"]
            if iep_start <= now <= iep_end:
                b["lifecycle_status"] = "IEP_OPEN"
                stamp_update(b, store_now_iso=now_iso_str)
                transitions.append({
                    "entity_type": "Beneficiary",
                    "entity_id": bid,
                    "from": "PRE_ELIGIBLE",
                    "to": "IEP_OPEN",
                })
            elif now > iep_end:
                # Clock jumped clean past the IEP window — go straight to IEP_CLOSED.
                # The intermediate IEP_OPEN never had an opportunity to fire (no active AB).
                b["lifecycle_status"] = "IEP_CLOSED"
                stamp_update(b, store_now_iso=now_iso_str)
                transitions.append({
                    "entity_type": "Beneficiary",
                    "entity_id": bid,
                    "from": "PRE_ELIGIBLE",
                    "to": "IEP_CLOSED",
                })
        elif lc == "IEP_OPEN":
            iep_end = b["_iep_end_dt"]
            if now > iep_end:
                # Check for ACTIVE Part A or B enrollment
                has_active_ab = any(
                    e["beneficiary_id"] == bid
                    and e["status"] == "ACTIVE"
                    and e["part_covered"] in ("PART_A", "PART_B")
                    for e in store.enrollments.values()
                )
                if not has_active_ab:
                    b["lifecycle_status"] = "IEP_CLOSED"
                    stamp_update(b, store_now_iso=now_iso_str)
                    transitions.append({
                        "entity_type": "Beneficiary",
                        "entity_id": bid,
                        "from": "IEP_OPEN",
                        "to": "IEP_CLOSED",
                    })

    return transitions


@bp.route("/_clock", methods=["GET"])
@require_roles("PlanAdmin", "BenefitsCounselor", "Beneficiary", "Auditor")
def get_clock():
    return ok_object({"now": iso_string(store.clock)})


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("PlanAdmin", "Auditor")
def advance_clock():
    body = request.get_json(silent=True) or {}
    raw_to = require_field(body, "to")
    new_time = parse_iso_datetime(raw_to, field="to")
    store.set_clock(new_time)
    now_iso = store.now_iso()
    transitions = _recompute_periods_and_lifecycles(now_iso)
    return ok_object({
        "now": iso_string(store.clock),
        "transitions_applied": transitions,
    })
