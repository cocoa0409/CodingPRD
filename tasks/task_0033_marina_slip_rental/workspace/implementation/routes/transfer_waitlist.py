"""Transfer-waitlist routes (scaffold §1.5 — Transfer Waitlist block; PRD §3.9).

The waitlist mediates inter-slip moves: a Tenant on an ACTIVE lease at a
marina can request to move to a different Slip in the same marina; the head
of the queue is promoted automatically when that target slip becomes
available via the check-out cascade.
"""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_WAITLIST_INELIGIBLE,
)
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.cascades import queued_entries_for, recompute_positions
from services.calculations import WAITLIST_TTL_DAYS
from services.validation import (
    lookup_or_404,
    require_fields,
)


bp = Blueprint("transfer_waitlist", __name__)


@bp.post("/transfer-waitlist")
def create_waitlist_entry():
    require_auth(["Tenant"])()
    body = get_json_body()
    require_fields(body, ["marina_id", "tenant_id", "from_lease_id", "target_slip_id"])
    marina = lookup_or_404(db.marinas, body["marina_id"], "Marina")
    tenant = lookup_or_404(db.tenants, body["tenant_id"], "Tenant")
    from_lease = lookup_or_404(db.leases, body["from_lease_id"], "Lease")
    target_slip = lookup_or_404(db.slips, body["target_slip_id"], "Slip")

    with db.mutation_lock:
        # PRD §3.9: tenant must hold an ACTIVE lease at the named marina,
        # from_lease_id must be that lease, and target_slip_id must be in
        # the same marina. Any failure -> ERR_WAITLIST_INELIGIBLE.
        if (
            from_lease.get("tenant_id") != tenant["id"]
            or from_lease.get("marina_id") != marina["id"]
            or from_lease.get("status") != "ACTIVE"
        ):
            raise APIError(
                ERR_WAITLIST_INELIGIBLE,
                422,
                "from_lease_id is not the tenant's ACTIVE lease at this marina",
            )
        if target_slip.get("marina_id") != marina["id"]:
            raise APIError(
                ERR_WAITLIST_INELIGIBLE,
                422,
                "target_slip_id must belong to the same marina",
            )

        entry = {
            "marina_id": marina["id"],
            "tenant_id": tenant["id"],
            "from_lease_id": from_lease["id"],
            "target_slip_id": target_slip["id"],
            "requested_at": db.now_logical_iso(),
            "position": 0,  # placeholder; recomputed below
            "status": "QUEUED",
        }
        db.stamp_common(entry)
        db.transfer_waitlist[entry["id"]] = entry
        # Compute position by recomputing the (marina, slip) queue.
        recompute_positions(marina["id"], target_slip["id"])
        return ok_object(entry, 201)


@bp.get("/transfer-waitlist")
def list_waitlist_entries():
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    limit, offset = paginate_params(request.args)
    items = list(db.transfer_waitlist.values())
    for key in ("marina_id", "tenant_id", "target_slip_id", "from_lease_id", "status"):
        if key in request.args:
            val = request.args[key]
            items = [e for e in items if e.get(key) == val]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.get("/transfer-waitlist/<eid>")
def get_waitlist_entry(eid: str):
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    entry = lookup_or_404(db.transfer_waitlist, eid, "TransferWaitlistEntry")
    return ok_object(entry, 200)


@bp.post("/transfer-waitlist/<eid>/cancel")
def cancel_waitlist_entry(eid: str):
    require_auth(["Tenant"])()
    entry = lookup_or_404(db.transfer_waitlist, eid, "TransferWaitlistEntry")
    with db.mutation_lock:
        if entry.get("status") != "QUEUED":
            raise APIError(
                ERR_INVALID_STATE,
                409,
                "TransferWaitlistEntry must be QUEUED to cancel",
            )
        entry["status"] = "CANCELLED"
        db.bump(entry)
        # Recompute remaining QUEUED positions in the same (marina, slip) queue.
        recompute_positions(entry.get("marina_id"), entry.get("target_slip_id"))
        return ok_object(entry, 200)


@bp.post("/transfer-waitlist/expire-stale")
def expire_stale_waitlist_entries():
    require_auth(["HarborMaster"])()
    with db.mutation_lock:
        now_dt = db.now_logical_dt()
        ttl = timedelta(days=WAITLIST_TTL_DAYS)
        expired: list = []
        # Snapshot the QUEUED entries before mutation so we can iterate safely
        # and so we can recompute positions per (marina, slip) at the end.
        affected_queues = set()
        for entry in list(db.transfer_waitlist.values()):
            if entry.get("status") != "QUEUED":
                continue
            requested_at = db.parse_iso_dt(entry.get("requested_at"))
            if requested_at is None:
                continue
            if (now_dt - requested_at) >= ttl:
                entry["status"] = "EXPIRED"
                db.bump(entry)
                expired.append(entry)
                affected_queues.add(
                    (entry.get("marina_id"), entry.get("target_slip_id"))
                )
        for marina_id, slip_id in affected_queues:
            recompute_positions(marina_id, slip_id)
        # Return the list of expired entries. Per scaffold endpoint output:
        # "TransferWaitlistEntry[]". Expose as an array response.
        expired.sort(key=db.created_then_id)
        return ok_array(expired, len(expired), 0, len(expired), 200)
