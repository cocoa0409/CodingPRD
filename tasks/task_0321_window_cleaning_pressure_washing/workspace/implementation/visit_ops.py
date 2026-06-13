"""Visit creation/cancellation helpers shared across agreement and visit routes.

A Visit carries two independent status dimensions (PRD §3.4):
  * schedule_status — UNSCHEDULED -> SCHEDULED -> DISPATCHED -> IN_PROGRESS ->
    COMPLETED (+ CANCELLED)
  * billing_status  — UNBILLED -> INVOICED -> PAID (+ WAIVED)
"""
import db
from helpers import recompute_route_minutes


def requires_high_rise(prop):
    return int(prop["stories"]) >= 3


def requires_soft_wash(quote):
    return "SOFT_WASH" in (quote.get("addon_codes") or [])


def generate_visit(agreement, planned_date, window_start_min, window_end_min,
                   requires_sw, requires_hr):
    """Create a Visit in UNSCHEDULED/UNBILLED for an agreement's property."""
    duration = window_end_min - window_start_min
    rec = db.new_record(db.visits, {
        "agreement_id": agreement["id"],
        "property_id": agreement["property_id"],
        "route_id": None,
        "planned_date": planned_date,
        "window_start_min": window_start_min,
        "window_end_min": window_end_min,
        "duration_minutes": duration,
        "requires_soft_wash": requires_sw,
        "requires_high_rise": requires_hr,
        "reschedule_count": 0,
        "charge_amount_cents": 0,
        "schedule_status": "UNSCHEDULED",
        "billing_status": "UNBILLED",
    })
    return rec


def cancel_visit_for_cascade(visit):
    """Cancel a visit as a side effect (pause/cancel agreement).

    Frees the route's booked minutes if committed, then marks CANCELLED.
    """
    route_id = visit.get("route_id")
    visit["schedule_status"] = "CANCELLED"
    if route_id is not None:
        visit["route_id"] = None
    db.touch(visit)
    if route_id is not None:
        route = db.routes.get(route_id)
        if route is not None:
            recompute_route_minutes(route)
