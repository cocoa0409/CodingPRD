"""InsurancePolicy endpoints: create, read, list, cancel."""
from flask import Blueprint, request

import db
from db import touch
from errors import err_not_found, err_invalid_state, err_coverage_low
from middleware import get_caller, require_role, check_holder_ownership
from response import ok_object, ok_list
from services import validate as v
from services.serializers import base_entity, insurance_policy_view

bp = Blueprint("insurance", __name__)

READ_ROLES = ["PlatformAdmin", "CommunityAdmin", "Inspector", "EnforcementOfficer", "PermitHolder"]


@bp.post("/api/insurance-policies")
def create_policy():
    data = v.body()
    # Stage 1
    holder_id = v.require_str(data, "holder_id")
    vehicle_id = v.require_str(data, "vehicle_id")
    provider_name = v.require_str(data, "provider_name")
    policy_number = v.require_str(data, "policy_number")
    liability = v.require_int(data, "liability_coverage_cents", 0, None)
    effective_date = v.require_date(data, "effective_date")
    expiry_date = v.require_date(data, "expiry_date")
    # Stage 2-3
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    check_holder_ownership(caller, holder_id)
    # Stage 4: body FKs in declared order
    holder = db.permit_holders.get(holder_id)
    if holder is None:
        raise err_not_found("PermitHolder not found")
    veh = db.vehicles.get(vehicle_id)
    if veh is None:
        raise err_not_found("Vehicle not found")
    # Stage 9: coverage minimum
    community = db.communities.get(holder["community_id"])
    if liability < community["min_liability_coverage_cents"]:
        raise err_coverage_low()

    p = base_entity()
    p.update({
        "holder_id": holder_id,
        "vehicle_id": vehicle_id,
        "provider_name": provider_name,
        "policy_number": policy_number,
        "liability_coverage_cents": liability,
        "effective_date": effective_date.isoformat(),
        "expiry_date": expiry_date,
        "status": "ACTIVE",
    })
    db.insurance_policies[p["id"]] = p
    return ok_object(insurance_policy_view(p), 201)


@bp.get("/api/insurance-policies/<pid>")
def get_policy(pid):
    caller = get_caller()
    require_role(caller, READ_ROLES)
    p = db.insurance_policies.get(pid)
    if p is None:
        raise err_not_found("InsurancePolicy not found")
    check_holder_ownership(caller, p["holder_id"])
    return ok_object(insurance_policy_view(p))


@bp.get("/api/insurance-policies")
def list_policies():
    caller = get_caller()
    require_role(caller, READ_ROLES)
    limit, offset = v.pagination_args()
    holder_id = request.args.get("holder_id")
    vehicle_id = request.args.get("vehicle_id")
    rows = list(db.insurance_policies.values())
    if holder_id is not None:
        rows = [p for p in rows if p["holder_id"] == holder_id]
    if vehicle_id is not None:
        rows = [p for p in rows if p["vehicle_id"] == vehicle_id]
    if caller.role == "PermitHolder":
        rows = [p for p in rows if p["holder_id"] == caller.user_id]
    rows = v.sorted_by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([insurance_policy_view(p) for p in page], limit, offset, total)


@bp.post("/api/insurance-policies/<pid>/cancel")
def cancel_policy(pid):
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    p = db.insurance_policies.get(pid)
    if p is None:
        raise err_not_found("InsurancePolicy not found")
    check_holder_ownership(caller, p["holder_id"])
    if p["status"] != "ACTIVE":
        raise err_invalid_state("Policy is not ACTIVE")
    p["status"] = "CANCELLED"
    touch(p)
    return ok_object(insurance_policy_view(p))
