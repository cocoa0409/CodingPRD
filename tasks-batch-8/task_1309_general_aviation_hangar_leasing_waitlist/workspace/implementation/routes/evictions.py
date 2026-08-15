"""EvictionCase endpoints: file (delinquency), list/get, execute (OCC)."""
from flask import Blueprint, request

import db
from auth import ALL_ROLES, require_roles
from envelope import success_list, success_obj
from errors import (
    ApiError,
    ERR_CASE_NOT_FILED,
    ERR_DELINQUENCY_THRESHOLD_NOT_MET,
    ERR_INVALID_REQUEST,
    ERR_LEASE_NOT_DELINQUENT,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
)
from routes.leases import get_lease_or_404
from services.core import (
    ABANDONED_AIRCRAFT_DAILY_CENTS,
    DELINQUENCY_EVICTION_THRESHOLD_DAYS,
    EVICTION_REASONS,
    touch,
)
from timeutil import iso_z
from validators import body, paginate, pagination, req_int

bp = Blueprint("evictions", __name__)


def get_case_or_404(case_id):
    case = db.eviction_cases.get(case_id)
    if case is None:
        raise ApiError(ERR_NOT_FOUND, "Eviction case not found", 404)
    return case


@bp.post("/leases/<lid>/eviction-cases")
def file_eviction_case(lid):
    require_roles("AirportManager")
    lease = get_lease_or_404(lid)
    data = body()
    reason = data.get("reason", "DELINQUENCY")
    if not isinstance(reason, str) or reason not in EVICTION_REASONS:
        raise ApiError(ERR_INVALID_REQUEST, "reason must be a valid enumeration value", 400)
    if lease["status"] != "DELINQUENT":
        raise ApiError(ERR_LEASE_NOT_DELINQUENT, "Delinquency eviction filing requires lease DELINQUENT", 409)
    if lease["days_delinquent"] < DELINQUENCY_EVICTION_THRESHOLD_DAYS:
        raise ApiError(ERR_DELINQUENCY_THRESHOLD_NOT_MET, "days_delinquent below the eviction threshold", 402)
    case = db.new_entity({
        "lease_id": lease["id"],
        "use_audit_finding_id": "",
        "reason": reason,
        "filed_at": iso_z(db.clock_now()),
        "executed_at": None,
        "abandoned_aircraft_storage_cents_per_day": 0,
        "storage_days_already_billed": 0,
        "status": "FILED",
    })
    db.eviction_cases[case["id"]] = case
    lease["status"] = "EVICTION_PENDING"
    touch(lease)
    return success_obj(db.public(case), 201)


@bp.get("/leases/<lid>/eviction-cases")
def list_lease_eviction_cases(lid):
    require_roles(*ALL_ROLES)
    lease = get_lease_or_404(lid)
    items = [c for c in db.eviction_cases.values() if c["lease_id"] == lease["id"]]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([db.public(c) for c in page], limit, offset, total)


@bp.get("/eviction-cases")
def list_eviction_cases():
    require_roles(*ALL_ROLES)
    items = list(db.eviction_cases.values())
    finding_id = request.args.get("use_audit_finding_id")
    lease_id = request.args.get("lease_id")
    if finding_id is not None:
        items = [c for c in items if c["use_audit_finding_id"] == finding_id]
    if lease_id is not None:
        items = [c for c in items if c["lease_id"] == lease_id]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([db.public(c) for c in page], limit, offset, total)


@bp.get("/eviction-cases/<cid>")
def get_eviction_case(cid):
    require_roles(*ALL_ROLES)
    return success_obj(db.public(get_case_or_404(cid)), 200)


@bp.post("/eviction-cases/<cid>/execute")
def execute_eviction_case(cid):
    require_roles("AirportManager")
    case = get_case_or_404(cid)
    if case["status"] != "FILED":
        raise ApiError(ERR_CASE_NOT_FILED, "Eviction case must be FILED to execute", 409)
    data = body()
    expected_lease_version = req_int(data, "expected_lease_version")
    lease = db.leases[case["lease_id"]]
    if expected_lease_version != lease["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_lease_version does not match the lease's current version", 412)
    now = db.clock_now()
    case["status"] = "EXECUTED"
    case["executed_at"] = iso_z(now)
    case["abandoned_aircraft_storage_cents_per_day"] = ABANDONED_AIRCRAFT_DAILY_CENTS
    case["storage_days_already_billed"] = 0
    touch(case)
    # Lease -> EVICTED; aircraft stay BASED until removed; the hangar is freed
    # (posture re-derives to AVAILABLE) while storage accrues against the tenant.
    lease["status"] = "EVICTED"
    touch(lease)
    return success_obj(db.public(case), 200)
