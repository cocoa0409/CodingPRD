"""Shared multi-row cascades (PRD 2.10).

Every secondary mutation here is a real mutation: it refreshes updated_at and
increments the affected row's version, exactly as a client-initiated write
would.  Sibling fan-outs are processed in created_at ascending order.
"""

import constants as C
from db import created_order, db, touch
from services import budget as budget_service
from services.cost import recompute_request_costs
from services.reliance import recompute_school_flag


# ------------------------------------------------------------- units -------
def reserve_unit(unit):
    unit["allocation_status"] = "RESERVED"
    touch(unit)
    return unit


def release_unit(unit, touch_row=True):
    """RESERVED / SCHEDULED -> IN_STORAGE.  An INSTALLED unit is left alone."""
    if unit is None:
        return None
    if unit["allocation_status"] in ("RESERVED", "SCHEDULED"):
        unit["allocation_status"] = "IN_STORAGE"
        unit["current_school_id"] = None
        if touch_row:
            touch(unit)
    return unit


def release_pad(site, unit):
    if site is None or unit is None:
        return site
    if site.get("occupied_by_unit_id") == unit["id"]:
        site["occupied_by_unit_id"] = None
        touch(site)
    return site


def schedules_of(request_id):
    return created_order(
        [s for s in db.schedules.values() if s["placement_request_id"] == request_id]
    )


def cancel_open_schedules(req, reason):
    for sched in schedules_of(req["id"]):
        if sched["status"] in ("PLANNED", "IN_PROGRESS"):
            sched["status"] = "CANCELLED"
            sched["cancellation_reason"] = reason
            touch(sched)


def release_budget(req):
    budget = db.budgets.get(req.get("capital_budget_id"))
    if budget is None:
        return None
    budget_service.recompute(budget)
    touch(budget)
    return budget


# --------------------------------------------------------- withdrawal -----
def withdraw_request(req, rejection_reason, cancellation_reason,
                     touch_unit=True):
    """The unwind shared by the withdraw endpoint and the UNSAFE cascade."""
    req["status"] = "WITHDRAWN"
    req["rejection_reason"] = rejection_reason
    req["encumbered_cost_cents"] = 0
    touch(req)

    release_budget(req)
    cancel_open_schedules(req, cancellation_reason)

    unit = db.units.get(req.get("portable_unit_id"))
    site = db.sites.get(req.get("placement_site_id"))
    release_pad(site, unit)
    release_unit(unit, touch_row=touch_unit)
    return req


def unsafe_cascade(unit):
    """A unit declared UNSAFE withdraws every non-terminal request on it."""
    affected = created_order([
        r for r in db.requests.values()
        if r.get("portable_unit_id") == unit["id"]
        and r["status"] in C.NON_TERMINAL_REQUEST_STATUSES_FOR_WITHDRAW
    ])
    for req in affected:
        # the unit's own version was already incremented by the inspection
        withdraw_request(req, "UNIT_UNSAFE", "UNIT_UNSAFE", touch_unit=False)
    return affected


# ------------------------------------------------------- permit joins -----
def permit_join_approved(req):
    """Favourable arm: encumber, schedule the unit, occupy the pad."""
    budget = db.budgets.get(req["capital_budget_id"])
    estimate = req["estimated_relocation_cost_cents"]

    req["status"] = "PERMITTED"
    req["encumbered_cost_cents"] = estimate
    touch(req)

    if budget is not None:
        budget_service.recompute(budget)
        touch(budget)

    unit = db.units.get(req.get("portable_unit_id"))
    if unit is not None:
        unit["allocation_status"] = "SCHEDULED"
        touch(unit)
        site = db.sites.get(req.get("placement_site_id"))
        if site is not None:
            site["occupied_by_unit_id"] = unit["id"]
            touch(site)
    return req


def permit_join_denied(req):
    """Unfavourable arm: no encumbrance, pad stays free."""
    req["status"] = "REJECTED"
    req["rejection_reason"] = "PERMIT_DENIED"
    touch(req)
    release_unit(db.units.get(req.get("portable_unit_id")))
    return req


# ------------------------------------------------------ install / removal -
def install_complete(sched, req):
    """The system's largest cascade (PRD 3.8)."""
    spent = req["encumbered_cost_cents"]

    req["status"] = "INSTALLED"
    touch(req)

    budget = db.budgets.get(req.get("capital_budget_id"))
    if budget is not None:
        budget["expended_cents"] = budget["expended_cents"] + spent
        budget_service.recompute(budget)
        touch(budget)

    unit = db.units.get(req.get("portable_unit_id"))
    if unit is not None:
        unit["allocation_status"] = "INSTALLED"
        unit["current_school_id"] = req["school_id"]
        unit["lifetime_relocation_count"] = unit["lifetime_relocation_count"] + 1
        unit["accumulated_relocation_cost_cents"] = (
            unit["accumulated_relocation_cost_cents"] + spent
        )
        touch(unit)

    school = db.schools.get(req.get("school_id"))
    if school is not None and unit is not None:
        school["hosted_portable_seats"] = (
            school["hosted_portable_seats"] + unit["rated_seats"]
        )
        recompute_school_flag(school)
        touch(school)
    return req


def decommission_complete(req, unit, budget, removal_cents):
    req["status"] = "DECOMMISSIONED"
    touch(req)

    if budget is not None:
        budget["expended_cents"] = budget["expended_cents"] + removal_cents
        budget_service.recompute(budget)
        touch(budget)

    school = db.schools.get(req.get("school_id"))
    if unit is not None:
        unit["allocation_status"] = "IN_STORAGE"
        unit["current_school_id"] = None
        touch(unit)
        site = db.sites.get(req.get("placement_site_id"))
        release_pad(site, unit)

    if school is not None and unit is not None:
        school["hosted_portable_seats"] = max(
            0, school["hosted_portable_seats"] - unit["rated_seats"]
        )
        recompute_school_flag(school)
        touch(school)
    return req


def legacy_placement(unit, school, site):
    unit["allocation_status"] = "INSTALLED"
    unit["current_school_id"] = school["id"]
    unit["lifetime_relocation_count"] = unit["lifetime_relocation_count"] + 1
    touch(unit)

    site["occupied_by_unit_id"] = unit["id"]
    touch(site)

    school["hosted_portable_seats"] = (
        school["hosted_portable_seats"] + unit["rated_seats"]
    )
    recompute_school_flag(school)
    touch(school)
    return unit


__all__ = [
    "reserve_unit", "release_unit", "release_pad", "schedules_of",
    "cancel_open_schedules", "release_budget", "withdraw_request",
    "unsafe_cascade", "permit_join_approved", "permit_join_denied",
    "install_complete", "decommission_complete", "legacy_placement",
    "recompute_request_costs",
]
