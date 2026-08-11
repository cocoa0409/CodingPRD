"""Inspection endpoints: schedule, read, list, finalize with scoring."""
from flask import Blueprint, request

import db
from db import touch
from errors import err_not_found, err_invalid_state
from middleware import get_caller, require_role, check_holder_ownership
from response import ok_object, ok_list
from services import calc, validate as v
from services import engine
from services.serializers import base_entity, inspection_view

bp = Blueprint("inspections", __name__)

READ_ROLES = ["PlatformAdmin", "CommunityAdmin", "Inspector", "EnforcementOfficer", "PermitHolder"]

SCORE_FIELDS = ["headlights_score", "brake_lights_score", "turn_signals_score", "horn_score",
                "mirrors_score", "windshield_score", "seatbelts_score", "reflectors_score"]

_finalize_counter = {"n": 0}


@bp.post("/api/inspections")
def create_inspection():
    data = v.body()
    registration_id = v.require_str(data, "registration_id")
    scheduled_at = v.require_datetime(data, "scheduled_at")
    caller = get_caller()
    require_role(caller, ["Inspector"])
    reg = db.registrations.get(registration_id)
    if reg is None:
        raise err_not_found("Registration not found")

    ins = base_entity()
    ins.update({
        "registration_id": registration_id,
        "scheduled_at": scheduled_at,
        "status": "SCHEDULED",
        "total_score": None,
        "passed": None,
        "_finalize_seq": None,
    })
    for f in SCORE_FIELDS:
        ins[f] = None
    db.inspections[ins["id"]] = ins
    return ok_object(inspection_view(ins), 201)


@bp.get("/api/inspections/<iid>")
def get_inspection(iid):
    caller = get_caller()
    require_role(caller, READ_ROLES)
    ins = db.inspections.get(iid)
    if ins is None:
        raise err_not_found("Inspection not found")
    if caller.role == "PermitHolder":
        reg = db.registrations.get(ins["registration_id"])
        check_holder_ownership(caller, reg["holder_id"] if reg else None)
    return ok_object(inspection_view(ins))


@bp.get("/api/inspections")
def list_inspections():
    caller = get_caller()
    require_role(caller, READ_ROLES)
    limit, offset = v.pagination_args()
    registration_id = request.args.get("registration_id")
    rows = list(db.inspections.values())
    if registration_id is not None:
        rows = [i for i in rows if i["registration_id"] == registration_id]
    if caller.role == "PermitHolder":
        rows = [i for i in rows
                if (db.registrations.get(i["registration_id"]) or {}).get("holder_id") == caller.user_id]
    rows = v.sorted_by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([inspection_view(i) for i in page], limit, offset, total)


@bp.post("/api/inspections/<iid>/finalize")
def finalize_inspection(iid):
    data = v.body()
    scores = {f: v.require_int(data, f, 0, 100) for f in SCORE_FIELDS}
    caller = get_caller()
    require_role(caller, ["Inspector"])
    ins = db.inspections.get(iid)
    if ins is None:
        raise err_not_found("Inspection not found")
    # Stage 5: inspection state + referenced registration state
    if ins["status"] != "SCHEDULED":
        raise err_invalid_state("Inspection is not SCHEDULED")
    reg = db.registrations.get(ins["registration_id"])
    if reg["status"] not in ("DRAFT", "ACTIVE", "RENEWAL_PENDING", "SUSPENDED"):
        raise err_invalid_state("Registration state does not permit finalization")

    for f, s in scores.items():
        ins[f] = s
    total = calc.inspection_total_score(scores)
    ins["total_score"] = total
    passed = calc.inspection_passed(total)
    ins["passed"] = passed
    _finalize_counter["n"] += 1
    ins["_finalize_seq"] = _finalize_counter["n"]
    holder = db.permit_holders.get(reg["holder_id"])
    community = db.communities.get(holder["community_id"]) if holder else None
    veh = db.vehicles.get(reg["vehicle_id"])
    now_dt = db.now()

    if passed:
        ins["status"] = "PASSED"
        touch(ins)
        # Recompute finalized fee on the registration
        finalized = calc.annual_registration_fee(
            veh, community, reg["holder_id"], "finalized", as_of=now_dt)
        reg["finalized_fee_cents"] = finalized
        reg["total_due_cents"] = min(finalized + reg["late_fee_cents"], 2 * finalized)
        touch(reg)
    else:
        ins["status"] = "FAILED"
        touch(ins)
        # Failure cascades only when the registration is currently ACTIVE
        if reg["status"] == "ACTIVE":
            engine.suspend_registration(reg)
    return ok_object(inspection_view(ins))
