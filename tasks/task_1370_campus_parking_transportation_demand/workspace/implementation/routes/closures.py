"""Lot closure endpoints: schedule, list, get, activate, lift, cancel."""
from flask import Blueprint, request

import db
from errors import (
    bad_request,
    invalid_interval,
    fallback_lot_required,
    not_found,
    conflict,
    ERR_LOT_NOT_FOUND,
    ERR_CLOSURE_NOT_FOUND,
    ERR_CLOSURE_INVALID_STATE,
    ERR_DISPLACEMENT_OVER_CAPACITY,
)
from middleware import get_caller, require_roles, ALL_ROLES
from response import success, success_list, parse_pagination
from services.core import (
    new_record,
    serialize,
    touch,
    bump_allocation,
    check_closure_overlap,
    parse_iso_datetime,
    recompute_lot_reserved_and_availability,
)

bp = Blueprint("closures", __name__)

REASONS = ("EVENT", "CONSTRUCTION")


def _get_closure_or_404(closure_id: str) -> dict:
    record = db.closures.get(closure_id)
    if record is None:
        raise not_found(ERR_CLOSURE_NOT_FOUND, "No lot closure with the given id")
    return record


@bp.post("/parking/closures")
def create_closure():
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    body = request.get_json(silent=True) or {}

    lot_id = body.get("lot_id")
    reason = body.get("reason")
    starts_at_raw = body.get("starts_at")
    ends_at_raw = body.get("ends_at")
    event_name = body.get("event_name")
    expected_attendance = body.get("expected_attendance")
    reserved_spaces = body.get("reserved_spaces")
    fallback_lot_id = body.get("fallback_lot_id")

    # Existence (priority 4): lot, then fallback lot
    if not isinstance(lot_id, str) or not lot_id:
        raise bad_request("lot_id is required")
    lot = db.lots.get(lot_id)
    if lot is None:
        raise not_found(ERR_LOT_NOT_FOUND, "No parking lot with the given id")
    if fallback_lot_id is not None:
        if not isinstance(fallback_lot_id, str):
            raise bad_request("fallback_lot_id must be a string id")
        fallback_lot = db.lots.get(fallback_lot_id)
        if fallback_lot is None:
            raise not_found(ERR_LOT_NOT_FOUND, "No parking lot with the given fallback_lot_id")

    # Request shape (priority 6)
    if reason not in REASONS:
        raise bad_request("reason must be EVENT or CONSTRUCTION")
    starts_at = parse_iso_datetime(starts_at_raw, "starts_at")
    ends_at = parse_iso_datetime(ends_at_raw, "ends_at")
    if ends_at <= starts_at:
        raise invalid_interval("ends_at must be strictly after starts_at")

    if reason == "EVENT":
        if not isinstance(event_name, str) or not event_name:
            raise bad_request("event_name is required when reason is EVENT")
        if expected_attendance is not None and (
            not isinstance(expected_attendance, int) or isinstance(expected_attendance, bool)
        ):
            raise bad_request("expected_attendance must be an integer")
        if (
            not isinstance(reserved_spaces, int)
            or isinstance(reserved_spaces, bool)
            or reserved_spaces < 1
        ):
            raise bad_request("reserved_spaces must be an integer >= 1 for EVENT closures")
        if fallback_lot_id is not None:
            raise bad_request("fallback_lot_id must be null for EVENT closures")
        reserved_spaces_val = reserved_spaces
        fallback_val = None
    else:  # CONSTRUCTION
        if event_name is not None:
            raise bad_request("event_name must be null for CONSTRUCTION closures")
        if expected_attendance is not None:
            raise bad_request("expected_attendance must be null for CONSTRUCTION closures")
        if reserved_spaces is not None and (
            not isinstance(reserved_spaces, int)
            or isinstance(reserved_spaces, bool)
            or reserved_spaces != 0
        ):
            raise bad_request("reserved_spaces must be 0 for CONSTRUCTION closures")
        if fallback_lot_id is None:
            raise fallback_lot_required("fallback_lot_id is required for CONSTRUCTION closures")
        if fallback_lot_id == lot_id:
            raise fallback_lot_required("fallback_lot_id must differ from lot_id")
        reserved_spaces_val = 0
        fallback_val = fallback_lot_id

    # Temporal (priority 9): overlap
    check_closure_overlap(lot_id, starts_at, ends_at)

    record = new_record()
    record.update(
        lot_id=lot_id,
        reason=reason,
        event_name=event_name if reason == "EVENT" else None,
        expected_attendance=expected_attendance if reason == "EVENT" else None,
        reserved_spaces=reserved_spaces_val,
        fallback_lot_id=fallback_val,
        starts_at=db.fmt_ts(starts_at),
        ends_at=db.fmt_ts(ends_at),
        status="SCHEDULED",
        displaced_permit_count=0,
    )
    record["_starts_at"] = starts_at
    record["_ends_at"] = ends_at
    db.closures[record["id"]] = record

    if reason == "EVENT":
        # Reservation taken at schedule time
        recompute_lot_reserved_and_availability(lot)
        touch(lot)

    return success(serialize(record), 201)


@bp.get("/parking/closures")
def list_closures():
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)

    lot_id = request.args.get("lot_id")
    fallback_lot_id = request.args.get("fallback_lot_id")
    reason = request.args.get("reason")
    status = request.args.get("status")

    items = list(db.closures.values())
    if lot_id is not None:
        items = [c for c in items if c["lot_id"] == lot_id]
    if fallback_lot_id is not None:
        items = [c for c in items if c.get("fallback_lot_id") == fallback_lot_id]
    if reason is not None:
        items = [c for c in items if c["reason"] == reason]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serialize(c) for c in page], limit, offset, total)


@bp.get("/parking/closures/<closureId>")
def get_closure(closureId):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    record = _get_closure_or_404(closureId)
    return success(serialize(record), 200)


@bp.post("/parking/closures/<closureId>/activate")
def activate_closure(closureId):
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    closure = _get_closure_or_404(closureId)

    # State (priority 7)
    if closure["status"] != "SCHEDULED":
        raise conflict(ERR_CLOSURE_INVALID_STATE, "Activate requires status SCHEDULED")

    # Temporal (priority 9): overlap re-check (exclude self)
    check_closure_overlap(
        closure["lot_id"],
        closure["_starts_at"],
        closure["_ends_at"],
        exclude_closure_id=closure["id"],
    )

    lot = db.lots[closure["lot_id"]]

    if closure["reason"] == "CONSTRUCTION":
        # Fiscal/capacity (priority 12): displacement fits fallback quotas.
        # Group ACTIVE permits on the closed lot's allocations by permit_code.
        displaced_by_code = {}
        source_allocations = {}
        for alloc in db.allocations.values():
            if alloc["lot_id"] != lot["id"]:
                continue
            active_permits = [
                p
                for p in db.permits.values()
                if p["allocation_id"] == alloc["id"] and p["status"] == "ACTIVE"
            ]
            if not active_permits:
                continue
            displaced_by_code[alloc["permit_code"]] = active_permits
            source_allocations[alloc["permit_code"]] = alloc

        # Find fallback allocation per permit_code and check capacity
        fallback_alloc_by_code = {}
        for code, permits_list in displaced_by_code.items():
            target = None
            for alloc in db.allocations.values():
                if (
                    alloc["lot_id"] == closure["fallback_lot_id"]
                    and alloc["permit_code"] == code
                ):
                    target = alloc
                    break
            if target is None:
                raise conflict(
                    ERR_DISPLACEMENT_OVER_CAPACITY,
                    f"Fallback lot has no allocation with permit_code {code}",
                )
            if target["allocated_count"] + len(permits_list) > target["quota"]:
                raise conflict(
                    ERR_DISPLACEMENT_OVER_CAPACITY,
                    "Fallback allocation cannot absorb displaced permits within its quota",
                )
            fallback_alloc_by_code[code] = target

        # Activate
        closure["status"] = "ACTIVE"
        lot["posture"] = "CLOSED_CONSTRUCTION"
        touch(lot)

        displaced = 0
        for code, permits_list in displaced_by_code.items():
            source = source_allocations[code]
            target = fallback_alloc_by_code[code]
            for permit in permits_list:
                permit["allocation_id"] = target["id"]
                permit["displaced_from_allocation_id"] = source["id"]
                touch(permit)
                source["allocated_count"] -= 1
                target["allocated_count"] += 1
                displaced += 1
            bump_allocation(source)
            bump_allocation(target)
        closure["displaced_permit_count"] = displaced
        touch(closure)
    else:  # EVENT
        closure["status"] = "ACTIVE"
        lot["posture"] = "CLOSED_EVENT"
        touch(lot)
        recompute_lot_reserved_and_availability(lot)
        touch(closure)

    return success(serialize(closure), 200)


@bp.post("/parking/closures/<closureId>/lift")
def lift_closure(closureId):
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    closure = _get_closure_or_404(closureId)

    if closure["status"] != "ACTIVE":
        raise conflict(ERR_CLOSURE_INVALID_STATE, "Lift requires status ACTIVE")

    lot = db.lots[closure["lot_id"]]
    closure["status"] = "LIFTED"
    lot["posture"] = "OPEN"
    touch(lot)

    if closure["reason"] == "EVENT":
        recompute_lot_reserved_and_availability(lot)
    else:  # CONSTRUCTION: repoint displaced permits back
        # Permits whose displaced_from_allocation_id points to an allocation
        # of this lot and which currently sit on the fallback allocation.
        lot_allocation_ids = {
            a["id"] for a in db.allocations.values() if a["lot_id"] == lot["id"]
        }
        affected_sources = {}
        affected_targets = {}
        for permit in db.permits.values():
            src_id = permit.get("displaced_from_allocation_id")
            if src_id is None or src_id not in lot_allocation_ids:
                continue
            # Only ACTIVE permits are repointed back (suspended ones also sit
            # on the fallback but remain valid; PRD says "every permit whose
            # displaced_from_allocation_id points to an allocation of this
            # lot (and which currently sits on the fallback allocation)")
            current_alloc = db.allocations.get(permit["allocation_id"])
            source_alloc = db.allocations.get(src_id)
            if current_alloc is None or source_alloc is None:
                continue
            if permit["status"] not in ("ACTIVE", "SUSPENDED"):
                continue
            permit["allocation_id"] = src_id
            permit["displaced_from_allocation_id"] = None
            touch(permit)
            current_alloc["allocated_count"] -= 1
            source_alloc["allocated_count"] += 1
            affected_targets[current_alloc["id"]] = current_alloc
            affected_sources[src_id] = source_alloc
        for a in list(affected_sources.values()) + list(affected_targets.values()):
            bump_allocation(a)

    touch(closure)
    return success(serialize(closure), 200)


@bp.post("/parking/closures/<closureId>/cancel")
def cancel_closure(closureId):
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    closure = _get_closure_or_404(closureId)

    if closure["status"] != "SCHEDULED":
        raise conflict(ERR_CLOSURE_INVALID_STATE, "Cancel requires status SCHEDULED")

    closure["status"] = "CANCELLED"
    if closure["reason"] == "EVENT":
        lot = db.lots[closure["lot_id"]]
        recompute_lot_reserved_and_availability(lot)
        touch(lot)
    touch(closure)
    return success(serialize(closure), 200)
