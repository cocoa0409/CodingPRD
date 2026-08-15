"""Lot allocation endpoints."""
from flask import Blueprint, request

import db
from errors import (
    bad_request,
    not_found,
    conflict,
    stale_version,
    ERR_LOT_NOT_FOUND,
    ERR_ALLOCATION_NOT_FOUND,
    ERR_DUPLICATE_ALLOCATION_CODE,
)
from middleware import get_caller, require_roles, ALL_ROLES
from response import success, success_list, parse_pagination
from services.core import (
    new_record,
    serialize,
    parse_iso_date,
    extend_offers,
    bump_allocation,
)

bp = Blueprint("allocations", __name__)

CAMPUS_ROLES = ("STUDENT", "STAFF", "FACULTY")
RESIDENCY_RULES = ("ANY", "ON_CAMPUS_ONLY", "OFF_CAMPUS_ONLY")
PRORATION_POLICIES = ("PRORATED_WEEKLY", "FLAT_HALF_TERM")


def _get_allocation_or_404(allocation_id: str) -> dict:
    record = db.allocations.get(allocation_id)
    if record is None:
        raise not_found(ERR_ALLOCATION_NOT_FOUND, "No lot allocation with the given id")
    return record


@bp.post("/parking/allocations")
def create_allocation():
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    body = request.get_json(silent=True) or {}

    lot_id = body.get("lot_id")
    permit_code = body.get("permit_code")
    eligible_roles = body.get("eligible_roles")
    residency_rule = body.get("residency_rule")
    base_fee_cents = body.get("base_fee_cents")
    proration_policy = body.get("proration_policy")
    term_start_raw = body.get("term_start")
    term_end_raw = body.get("term_end")
    quota = body.get("quota")

    # Existence (priority 4): lot FK
    if not isinstance(lot_id, str) or not lot_id:
        raise bad_request("lot_id is required")
    lot = db.lots.get(lot_id)
    if lot is None:
        raise not_found(ERR_LOT_NOT_FOUND, "No parking lot with the given id")

    # Request shape (priority 6)
    if not isinstance(permit_code, str) or not permit_code:
        raise bad_request("permit_code is required")
    if (
        not isinstance(eligible_roles, list)
        or not eligible_roles
        or any(r not in CAMPUS_ROLES for r in eligible_roles)
    ):
        raise bad_request("eligible_roles must be a non-empty subset of STUDENT, STAFF, FACULTY")
    if residency_rule not in RESIDENCY_RULES:
        raise bad_request("residency_rule must be ANY, ON_CAMPUS_ONLY, or OFF_CAMPUS_ONLY")
    if not isinstance(base_fee_cents, int) or isinstance(base_fee_cents, bool) or base_fee_cents < 0:
        raise bad_request("base_fee_cents must be an integer >= 0")
    if proration_policy not in PRORATION_POLICIES:
        raise bad_request("proration_policy must be PRORATED_WEEKLY or FLAT_HALF_TERM")
    term_start = parse_iso_date(term_start_raw, "term_start")
    term_end = parse_iso_date(term_end_raw, "term_end")
    if term_end <= term_start:
        raise bad_request("term_end must be strictly after term_start")
    if not isinstance(quota, int) or isinstance(quota, bool) or quota < 0:
        raise bad_request("quota must be an integer >= 0")

    # Uniqueness (priority 11): (lot_id, permit_code)
    for a in db.allocations.values():
        if a["lot_id"] == lot_id and a["permit_code"] == permit_code:
            raise conflict(
                ERR_DUPLICATE_ALLOCATION_CODE,
                "An allocation with the same (lot_id, permit_code) already exists",
            )

    record = new_record()
    record.update(
        lot_id=lot_id,
        permit_code=permit_code,
        eligible_roles=list(eligible_roles),
        residency_rule=residency_rule,
        base_fee_cents=base_fee_cents,
        proration_policy=proration_policy,
        term_start=term_start.isoformat(),
        term_end=term_end.isoformat(),
        quota=quota,
        allocated_count=0,
        offers_outstanding=0,
        status="OPEN" if quota > 0 else "WAITLISTING",
    )
    record["_term_start"] = term_start
    record["_term_end"] = term_end
    db.allocations[record["id"]] = record
    return success(serialize(record), 201)


@bp.get("/parking/allocations")
def list_allocations():
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)

    lot_id = request.args.get("lot_id")
    permit_code = request.args.get("permit_code")
    status = request.args.get("status")

    items = list(db.allocations.values())
    if lot_id is not None:
        items = [a for a in items if a["lot_id"] == lot_id]
    if permit_code is not None:
        items = [a for a in items if a["permit_code"] == permit_code]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serialize(a) for a in page], limit, offset, total)


@bp.get("/parking/allocations/<allocationId>")
def get_allocation(allocationId):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    record = _get_allocation_or_404(allocationId)
    return success(serialize(record), 200)


@bp.patch("/parking/allocations/<allocationId>")
def adjust_quota(allocationId):
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    # Existence (priority 4)
    record = _get_allocation_or_404(allocationId)

    body = request.get_json(silent=True) or {}
    # OCC (priority 5): expected_allocation_version is required
    expected = body.get("expected_allocation_version")
    if expected is None:
        raise bad_request("expected_allocation_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise bad_request("expected_allocation_version must be an integer")
    if expected != record["version"]:
        raise stale_version("expected_allocation_version does not match current version")

    # Request shape (priority 6)
    quota = body.get("quota")
    if not isinstance(quota, int) or isinstance(quota, bool) or quota < 0:
        raise bad_request("quota must be an integer >= 0")

    record["quota"] = quota
    bump_allocation(record)
    return success(serialize(record), 200)


@bp.post("/parking/allocations/<allocationId>/extend-offers")
def run_extend_offers(allocationId):
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    record = _get_allocation_or_404(allocationId)
    promoted = extend_offers(record)
    return success({"offered_count": len(promoted), "offered_entry_ids": promoted}, 200)
