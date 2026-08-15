"""DispatchAssignment endpoints (PRD §3.3)."""
from flask import Blueprint, request

import errors
import services
from db import get, pub, touch
from middleware import list_response, require_roles
from response import ok

bp = Blueprint("assignments", __name__)

READ_ROLES = ("StevedoreAdmin", "StevedoreSuperintendent", "LaborHallDispatcher",
              "GangForeman", "PayrollClerk")


@bp.get("/api/dispatch-assignments")
def list_assignments():
    require_roles(*READ_ROLES)
    return list_response("dispatch_assignments", {
        "gang_order_id": request.args.get("gang_order_id"),
        "worker_id": request.args.get("worker_id"),
        "status": request.args.get("status"),
    })


def _get_assignment(aid):
    a = get("dispatch_assignments", aid)
    if a is None:
        raise errors.not_found("Dispatch assignment not found")
    return a


@bp.get("/api/dispatch-assignments/<aid>")
def get_assignment(aid):
    require_roles(*READ_ROLES)
    return ok(pub(_get_assignment(aid)))


def _double_booked(worker_id, gang):
    """Re-evaluated at check-in: worker must not hold OFFERED/CHECKED_IN/WORKING
    on another gang order whose shift window overlaps (half-open)."""
    from db import all_of
    this_shift = services.gang_shift(gang)
    for a in all_of("dispatch_assignments"):
        if a["worker_id"] != worker_id or a["gang_order_id"] == gang["id"]:
            continue
        if a["status"] not in services.ASSIGNMENT_NONTERMINAL:
            continue
        g2 = get("gang_orders", a["gang_order_id"])
        if g2 is None:
            continue
        s2 = services.gang_shift(g2)
        if services._half_open_overlap(this_shift["_start"], this_shift["_end"],
                                       s2["_start"], s2["_end"]):
            return True
    return False


@bp.post("/api/dispatch-assignments/<aid>/check-in")
def check_in(aid):
    require_roles("LaborHallDispatcher")
    a = _get_assignment(aid)
    gang = get("gang_orders", a["gang_order_id"])
    shift = services.gang_shift(gang)
    # state (6)
    if a["status"] != "OFFERED":
        raise errors.invalid_state("Only an OFFERED assignment can be checked in")
    if shift["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Shift must be IN_PROGRESS to check in")
    # stoppage gate (7)
    vessel = services.shift_vessel(shift)
    if vessel["work_posture"] == "FULL_STOPPAGE":
        raise errors.work_stoppage()
    # temporal (9): double-booking re-evaluated at check-in
    if _double_booked(a["worker_id"], gang):
        raise errors.worker_double_booked()
    # capacity (10): worker still ACTIVE, gang has an open slot
    worker = get("workers", a["worker_id"])
    if worker is None or worker["status"] != "ACTIVE":
        raise errors.worker_ineligible("Worker is not ACTIVE")
    services.recompute_manning(gang)
    if gang["filled_headcount"] >= gang["required_headcount"]:
        raise errors.gang_full()
    a["status"] = "CHECKED_IN"
    touch(a)
    services.recompute_manning(gang)
    return ok(pub(a))


@bp.post("/api/dispatch-assignments/<aid>/complete")
def complete_assignment(aid):
    require_roles("LaborHallDispatcher")
    a = _get_assignment(aid)
    if a["status"] != "WORKING":
        raise errors.invalid_state("Only a WORKING assignment can be completed")
    a["status"] = "COMPLETED"
    touch(a)
    gang = get("gang_orders", a["gang_order_id"])
    if gang is not None:
        services.recompute_manning(gang)
    return ok(pub(a))


@bp.post("/api/dispatch-assignments/<aid>/no-show")
def no_show(aid):
    require_roles("LaborHallDispatcher")
    a = _get_assignment(aid)
    gang = get("gang_orders", a["gang_order_id"])
    shift = services.gang_shift(gang)
    if a["status"] != "OFFERED":
        raise errors.invalid_state("Only an OFFERED assignment can be marked no-show")
    if shift["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Shift must be IN_PROGRESS to mark a no-show")
    a["status"] = "NO_SHOW"
    touch(a)
    # single-slot auto-offer; the no-show worker is excluded by the same-order rule
    services.auto_offer(gang)
    return ok(pub(a))


@bp.post("/api/dispatch-assignments/<aid>/bump")
def bump(aid):
    require_roles("LaborHallDispatcher")
    a = _get_assignment(aid)
    if a["status"] not in ("OFFERED", "CHECKED_IN"):
        raise errors.invalid_state("Only an OFFERED or CHECKED_IN assignment can be bumped")
    a["status"] = "BUMPED"
    touch(a)
    gang = get("gang_orders", a["gang_order_id"])
    if gang is not None:
        # single-slot auto-offer; the bumped worker is excluded by the same-order rule
        services.auto_offer(gang)
    return ok(pub(a))
