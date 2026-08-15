"""Lease endpoints: list/get, payments (waterfall), terminate (voluntary and
manager close-out after eviction)."""
from flask import Blueprint, request

import db
from auth import ALL_ROLES, require_ownership, require_roles
from envelope import success_list, success_obj
from errors import (
    ApiError,
    ERR_AIRCRAFT_STILL_BASED,
    ERR_AIRPORT_NOT_ACTIVE,
    ERR_INVALID_REQUEST,
    ERR_LEASE_NOT_ACTIVE,
    ERR_LEASE_NOT_EVICTED,
    ERR_NOT_FOUND,
    ERR_OUTSTANDING_BALANCE,
    ERR_OVERPAYMENT,
)
from services.core import recompute_lease_derived, touch
from timeutil import parse_iso
from validators import body, opt_bool, paginate, pagination, req_int

bp = Blueprint("leases", __name__)


def get_lease_or_404(lease_id):
    lease = db.leases.get(lease_id)
    if lease is None:
        raise ApiError(ERR_NOT_FOUND, "Lease not found", 404)
    return lease


@bp.get("/leases")
def list_leases():
    require_roles(*ALL_ROLES)
    items = list(db.leases.values())
    for param in ("airport_id", "hangar_id", "application_id", "offer_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [l for l in items if l[param] == value]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([db.public(l) for l in page], limit, offset, total)


@bp.get("/leases/<lid>")
def get_lease(lid):
    require_roles(*ALL_ROLES)
    return success_obj(db.public(get_lease_or_404(lid)), 200)


@bp.post("/leases/<lid>/payments")
def make_payment(lid):
    uid, _role = require_roles("Tenant")
    lease = get_lease_or_404(lid)
    require_ownership(lease["id"], uid)
    airport = db.airports[lease["airport_id"]]
    if airport["status"] != "ACTIVE":
        raise ApiError(ERR_AIRPORT_NOT_ACTIVE, "Airport is SUSPENDED", 409)
    data = body()
    amount = req_int(data, "amount_cents")
    if amount <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "amount_cents must be a positive integer", 400)

    charges = sorted(
        [
            c for c in db.rent_charges.values()
            if c["lease_id"] == lease["id"] and c["status"] in ("OPEN", "PARTIALLY_PAID")
        ],
        key=lambda c: (parse_iso(c["period_start"]), c["_seq"]),
    )
    outstanding = sum(c["balance_cents"] for c in charges)
    # Atomicity: reject an overpayment before applying anything.
    if amount > outstanding:
        raise ApiError(ERR_OVERPAYMENT, "Payment exceeds the total outstanding balance", 402)

    # Waterfall: chronological charges; within a charge the cumulative
    # paid_cents counter covers late fees before base (fees-before-principal).
    remaining = amount
    for charge in charges:
        if remaining <= 0:
            break
        owed = charge["base_amount_cents"] + charge["late_fee_cents"] - charge["paid_cents"]
        if owed <= 0:
            continue
        applied = min(remaining, owed)
        charge["paid_cents"] += applied
        remaining -= applied
        charge["balance_cents"] = charge["base_amount_cents"] + charge["late_fee_cents"] - charge["paid_cents"]
        charge["status"] = "PAID" if charge["balance_cents"] == 0 else "PARTIALLY_PAID"
        touch(charge)

    now = db.clock_now()
    recompute_lease_derived(lease, now, flip_delinquent=False)
    # DELINQUENT -> ACTIVE only when the waterfall zeroes the balance; a partial
    # payment still applies to charges but leaves the lease DELINQUENT.
    if lease["status"] == "DELINQUENT" and lease["outstanding_balance_cents"] == 0:
        lease["status"] = "ACTIVE"
        lease["days_delinquent"] = 0
    touch(lease)
    return success_obj(db.public(lease), 200)


@bp.post("/leases/<lid>/terminate")
def terminate_lease(lid):
    uid, role = require_roles("Tenant", "AirportManager")
    lease = get_lease_or_404(lid)
    data = body()
    if role == "Tenant":
        require_ownership(lease["id"], uid)
        # Voluntary termination: ACTIVE or DELINQUENT with a zero balance.
        if lease["status"] not in ("ACTIVE", "DELINQUENT"):
            raise ApiError(ERR_LEASE_NOT_ACTIVE, "Voluntary termination requires lease ACTIVE or DELINQUENT", 409)
        if lease["outstanding_balance_cents"] != 0:
            raise ApiError(ERR_OUTSTANDING_BALANCE, "Voluntary termination requires outstanding_balance_cents == 0", 402)
        lease["status"] = "TERMINATED"
        touch(lease)
        return success_obj(db.public(lease), 200)

    # Manager close-out after eviction.
    if lease["status"] != "EVICTED":
        raise ApiError(ERR_LEASE_NOT_EVICTED, "Manager close-out requires lease EVICTED", 409)
    based = [
        a for a in db.aircraft.values()
        if a["lease_id"] == lease["id"] and a["status"] == "BASED"
    ]
    abandon = opt_bool(data, "abandon_remaining_aircraft", False)
    if based and not abandon:
        raise ApiError(ERR_AIRCRAFT_STILL_BASED, "Aircraft still BASED; carry abandon_remaining_aircraft=true to close abandoned", 409)
    now = db.clock_now()
    if based:
        from timeutil import iso_z
        for a in based:
            a["status"] = "REMOVED"
            a["removed_at"] = iso_z(now)
            touch(a)
    case_status = "CLOSED_AIRCRAFT_ABANDONED" if based else "CLOSED_AIRCRAFT_REMOVED"
    for case in db.eviction_cases.values():
        if case["lease_id"] == lease["id"] and case["status"] == "EXECUTED":
            case["status"] = case_status
            touch(case)
    lease["status"] = "TERMINATED"
    touch(lease)
    return success_obj(db.public(lease), 200)
