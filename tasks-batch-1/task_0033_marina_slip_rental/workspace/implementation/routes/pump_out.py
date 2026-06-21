"""PumpOutRequest routes (scaffold §1.5 — PumpOut block; PRD §3.6)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_STATE
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.calculations import pumpout_charge
from services.validation import (
    lookup_or_404,
    require_fields,
)


bp = Blueprint("pump_out", __name__)


@bp.post("/pump-out-requests")
def create_pump_out_request():
    require_auth(["Tenant"])()
    body = get_json_body()
    require_fields(body, ["lease_id"])
    lease = lookup_or_404(db.leases, body["lease_id"], "Lease")

    with db.mutation_lock:
        # PRD §3.6: created while parent lease is ACTIVE — guard with
        # ERR_INVALID_STATE if the lease has not reached ACTIVE yet.
        if lease.get("status") != "ACTIVE":
            raise APIError(
                ERR_INVALID_STATE,
                409,
                "Parent lease must be ACTIVE to request pump-out",
            )
        por = {
            "lease_id": lease["id"],
            "requested_at": db.now_logical_iso(),
            "completed_at": None,
            "status": "PENDING",
            "charge_cents": 0,
        }
        db.stamp_common(por)
        db.pump_out_requests[por["id"]] = por
        return ok_object(por, 201)


@bp.get("/pump-out-requests")
def list_pump_out_requests():
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    limit, offset = paginate_params(request.args)
    items = list(db.pump_out_requests.values())
    if "lease_id" in request.args:
        items = [p for p in items if p.get("lease_id") == request.args["lease_id"]]
    if "status" in request.args:
        items = [p for p in items if p.get("status") == request.args["status"]]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.get("/pump-out-requests/<pid>")
def get_pump_out_request(pid: str):
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    por = lookup_or_404(db.pump_out_requests, pid, "PumpOutRequest")
    return ok_object(por, 200)


@bp.post("/pump-out-requests/<pid>/complete")
def complete_pump_out_request(pid: str):
    require_auth(["MarinaStaff", "HarborMaster"])()
    por = lookup_or_404(db.pump_out_requests, pid, "PumpOutRequest")

    with db.mutation_lock:
        if por.get("status") != "PENDING":
            raise APIError(
                ERR_INVALID_STATE, 409, "PumpOutRequest must be PENDING to complete"
            )
        lease = db.leases.get(por.get("lease_id"))
        if lease is None or lease.get("status") != "ACTIVE":
            raise APIError(
                ERR_INVALID_STATE, 409, "Parent Lease must be ACTIVE"
            )
        slip = db.slips.get(lease.get("slip_id"))
        slip_pumpout_available = bool(slip and slip.get("pumpout_available"))
        por["charge_cents"] = pumpout_charge(slip_pumpout_available)
        por["completed_at"] = db.now_logical_iso()
        por["status"] = "COMPLETED"
        db.bump(por)
        return ok_object(por, 200)


@bp.post("/pump-out-requests/<pid>/cancel")
def cancel_pump_out_request(pid: str):
    require_auth(["Tenant"])()
    por = lookup_or_404(db.pump_out_requests, pid, "PumpOutRequest")
    with db.mutation_lock:
        if por.get("status") != "PENDING":
            raise APIError(
                ERR_INVALID_STATE, 409, "PumpOutRequest must be PENDING to cancel"
            )
        por["status"] = "CANCELLED"
        db.bump(por)
        return ok_object(por, 200)
