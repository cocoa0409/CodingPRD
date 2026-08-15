"""Worker endpoints (PRD §3.3)."""
from flask import Blueprint, request

import errors
import services
from db import all_of, get, new_resource, pub, save, touch
from middleware import (
    ANY_ROLE, list_response, req_date, req_enum, req_int, req_str,
    require_roles, require_version,
)
from response import get_body, ok

bp = Blueprint("workers", __name__)

CLASSIFICATIONS = ("CRANE_OPERATOR", "HOLDMAN", "LASHER", "DRIVER", "CLERK")
WORKER_STATUSES = ("ACTIVE", "SUSPENDED", "INACTIVE")


@bp.post("/api/workers")
def create_worker():
    require_roles("StevedoreAdmin")
    body = get_body()
    full_name = req_str(body, "full_name")
    registration_number = req_str(body, "registration_number")
    classification = req_enum(body, "classification", CLASSIFICATIONS)
    registered_on = req_date(body, "registered_on")
    base_hourly_rate_cents = req_int(body, "base_hourly_rate_cents", min_value=1)
    for w in all_of("workers"):
        if w["registration_number"] == registration_number:
            raise errors.duplicate_registration()
    rec = new_resource("workers")
    rec.update({
        "full_name": full_name,
        "registration_number": registration_number,
        "classification": classification,
        "registered_on": registered_on,
        "base_hourly_rate_cents": base_hourly_rate_cents,
        "status": "ACTIVE",
        "seniority_rank": None,
    })
    save("workers", rec)
    services.recompute_seniority(classification)
    return ok(pub(rec), 201)


@bp.get("/api/workers")
def list_workers():
    require_roles(*ANY_ROLE)
    return list_response("workers", {
        "classification": request.args.get("classification"),
        "status": request.args.get("status"),
    })


def _get_worker(wid):
    w = get("workers", wid)
    if w is None:
        raise errors.not_found("Worker not found")
    return w


@bp.get("/api/workers/<wid>")
def get_worker(wid):
    require_roles(*ANY_ROLE)
    return ok(pub(_get_worker(wid)))


@bp.patch("/api/workers/<wid>")
def patch_worker(wid):
    require_roles("StevedoreAdmin")
    worker = _get_worker(wid)
    body = get_body()
    new_status = req_enum(body, "status", WORKER_STATUSES)
    # concurrency (5) before state (6)
    require_version(body, "expected_worker_version", worker["version"],
                    errors.stale_worker)
    if new_status == "SUSPENDED":
        for a in all_of("dispatch_assignments"):
            if a["worker_id"] == worker["id"] and a["status"] in ("CHECKED_IN", "WORKING"):
                raise errors.invalid_state(
                    "Cannot suspend a worker holding CHECKED_IN or WORKING assignments")
    worker["status"] = new_status
    touch(worker)  # every accepted change increments version by one
    if new_status == "SUSPENDED":
        # cascade: every OFFERED assignment -> BUMPED with single-slot auto-offer
        offered = [
            a for a in all_of("dispatch_assignments")
            if a["worker_id"] == worker["id"] and a["status"] == "OFFERED"
        ]
        offered.sort(key=lambda a: a["_seq"])
        for a in offered:
            a["status"] = "BUMPED"
            touch(a)
            gang = get("gang_orders", a["gang_order_id"])
            if gang is not None:
                services.auto_offer(gang)
    services.recompute_seniority(worker["classification"])
    return ok(pub(worker))
