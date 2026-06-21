from flask import Blueprint, request

import errors
from errors import err
from db import db
from models import make_common, touch, serialize
from clock import parse_iso8601
from middleware import get_identity, require_role
from helpers import (get_json_body, lookup, parse_pagination, paginate,
                     sort_by_created, require_tenant_owns_lease)
from response import success, list_response
from services import domain

bp = Blueprint("leases", __name__)

DATE_MAX = None  # null end_date treated as +inf


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval intersection; None end means +infinity."""
    a_end_eff = a_end
    b_end_eff = b_end
    # a_start <= b_end and b_start <= a_end
    cond1 = (b_end_eff is None) or (a_start <= b_end_eff)
    cond2 = (a_end_eff is None) or (b_start <= a_end_eff)
    return cond1 and cond2


def _check_occupancy_overlap(unit_id, start_date, end_date, exclude_lease_id=None):
    for l in db.leases.values():
        if l["unit_id"] != unit_id:
            continue
        if exclude_lease_id is not None and l["id"] == exclude_lease_id:
            continue
        # A PENDING lease is only a reservation and does not yet occupy the unit
        # (PRD §3.2/§3.3: occupancy begins at activation, "null while occupying").
        # Its occupancy interval is realized at activation, where the overlap is
        # re-checked, so two PENDING reservations do not conflict at creation.
        if l["status"] == "PENDING":
            continue
        if _intervals_overlap(start_date, end_date, l["start_date"], l["end_date"]):
            raise err(errors.ERR_UNIT_OCCUPANCY_OVERLAP,
                      "Lease occupancy interval overlaps an existing lease on this unit")


@bp.post("/leases")
def create_lease():
    _, role = get_identity()
    require_role(role, {"FacilityManager"})
    body = get_json_body()

    unit_id = body.get("unit_id")
    tenant_id = body.get("tenant_id")
    if not isinstance(unit_id, str) or not unit_id:
        raise err(errors.ERR_INVALID_REQUEST, "unit_id is required")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise err(errors.ERR_INVALID_REQUEST, "tenant_id is required")
    # Existence: left to right (unit, tenant).
    unit = lookup(db.units, unit_id, "unit")
    lookup(db.tenants, tenant_id, "tenant")

    start_raw = body.get("start_date")
    billing_day = body.get("billing_day")
    insurance_required = body.get("insurance_required", True)

    start_date = parse_iso8601(start_raw) if start_raw is not None else None
    if start_date is None:
        raise err(errors.ERR_INVALID_REQUEST, "start_date is required and must be ISO 8601")
    if isinstance(billing_day, bool) or not isinstance(billing_day, int):
        raise err(errors.ERR_INVALID_REQUEST, "billing_day must be an integer")
    if billing_day < 1 or billing_day > 28:
        raise err(errors.ERR_INVALID_REQUEST, "billing_day must be between 1 and 28")
    if not isinstance(insurance_required, bool):
        raise err(errors.ERR_INVALID_REQUEST, "insurance_required must be a boolean")

    # Occupancy overlap (closed interval; new lease end_date is null -> +inf).
    _check_occupancy_overlap(unit_id, start_date, None)

    lease = make_common()
    lease.update({
        "facility_id": unit["facility_id"],
        "unit_id": unit_id,
        "tenant_id": tenant_id,
        "status": "PENDING",
        "start_date": start_date,
        "end_date": None,
        "billing_day": billing_day,
        "monthly_rate_cents": None,
        "climate_controlled": None,
        "insurance_required": insurance_required,
        "balance_cents": 0,
        "days_past_due": 0,
        "_next_bill_date": None,
    })
    db.leases[lease["id"]] = lease
    return success(serialize(lease), 201)


@bp.get("/leases/<lease_id>")
def get_lease(lease_id):
    user_id, role = get_identity()
    lease = lookup(db.leases, lease_id, "lease")
    require_tenant_owns_lease(user_id, role, lease)
    return success(serialize(lease), 200)


@bp.get("/leases")
def list_leases():
    user_id, role = get_identity()
    limit, offset = parse_pagination()
    items = list(db.leases.values())

    facility_id = request.args.get("facility_id")
    unit_id = request.args.get("unit_id")
    tenant_id = request.args.get("tenant_id")
    status = request.args.get("status")
    if facility_id is not None:
        items = [l for l in items if l["facility_id"] == facility_id]
    if unit_id is not None:
        items = [l for l in items if l["unit_id"] == unit_id]
    if tenant_id is not None:
        items = [l for l in items if l["tenant_id"] == tenant_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]

    if role == "Tenant":
        items = [l for l in items if l["tenant_id"] == user_id]

    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize(l) for l in page], total, limit, offset)


@bp.get("/leases/<lease_id>/ledger-balance")
def ledger_balance(lease_id):
    user_id, role = get_identity()
    lease = lookup(db.leases, lease_id, "lease")
    require_tenant_owns_lease(user_id, role, lease)
    replayed = domain.replay_balance(lease_id)
    data = serialize(lease)
    data["balance_cents"] = replayed
    return success(data, 200)


@bp.post("/leases/<lease_id>/activate")
def activate_lease(lease_id):
    _, role = get_identity()
    require_role(role, {"FacilityManager"})
    lease = lookup(db.leases, lease_id, "lease")

    if lease["status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Lease must be PENDING to activate")

    unit = db.units.get(lease["unit_id"])
    if unit is None:
        raise err(errors.ERR_NOT_FOUND, "unit not found")
    if unit["status"] != "AVAILABLE":
        raise err(errors.ERR_UNIT_NOT_AVAILABLE, "Unit is not AVAILABLE")

    if lease["insurance_required"]:
        if domain.active_policy_for_lease(lease_id) is None:
            raise err(errors.ERR_INSURANCE_REQUIRED, "An ACTIVE insurance policy is required")

    # Occupancy overlap re-check at activation.
    _check_occupancy_overlap(lease["unit_id"], lease["start_date"], None,
                             exclude_lease_id=lease_id)

    facility = db.facilities[unit["facility_id"]]

    # Snapshot pricing.
    lease["monthly_rate_cents"] = unit["monthly_rate_cents"]
    lease["climate_controlled"] = unit["climate_controlled"]
    lease["status"] = "ACTIVE"

    # Bind unit.
    unit["status"] = "OCCUPIED"
    unit["current_lease_id"] = lease_id
    touch(unit)
    domain.recompute_occupied(unit["facility_id"])

    # First prorated invoice + CHARGE.
    domain.generate_first_invoice(lease, facility)
    touch(lease)

    return success(serialize(lease), 200)


@bp.post("/leases/<lease_id>/close")
def close_lease(lease_id):
    _, role = get_identity()
    require_role(role, {"FacilityManager"})
    lease = lookup(db.leases, lease_id, "lease")

    if lease["status"] not in ("ACTIVE", "DELINQUENT"):
        raise err(errors.ERR_INVALID_STATE, "Lease must be ACTIVE or DELINQUENT to close")

    # Non-terminal auction proceeding blocks close.
    if _has_nonterminal_proceeding(lease_id):
        raise err(errors.ERR_LEASE_HAS_ACTIVITY, "Lease has a non-terminal auction proceeding")

    if lease["balance_cents"] != 0:
        raise err(errors.ERR_BALANCE_NOT_CLEARED, "Lease balance must be zero to close")

    from clock import parse_iso8601  # noqa
    clock = db.clock.now()
    lease["status"] = "CLOSED"
    lease["end_date"] = clock
    touch(lease)

    unit = db.units.get(lease["unit_id"])
    if unit is not None:
        unit["status"] = "AVAILABLE"
        unit["current_lease_id"] = None
        touch(unit)
        domain.recompute_occupied(unit["facility_id"])

    _cancel_active_policies(lease_id, clock)
    return success(serialize(lease), 200)


def _has_nonterminal_proceeding(lease_id):
    terminal = ("SOLD", "REDEEMED", "CANCELLED")
    return any(
        ap["lease_id"] == lease_id and ap["status"] not in terminal
        for ap in db.auction_proceedings.values()
    )


def _cancel_active_policies(lease_id, clock):
    for p in db.insurance_policies.values():
        if p["lease_id"] == lease_id and p["status"] in ("ACTIVE", "LAPSED"):
            p["status"] = "CANCELLED"
            p["coverage_end"] = clock
            touch(p)
