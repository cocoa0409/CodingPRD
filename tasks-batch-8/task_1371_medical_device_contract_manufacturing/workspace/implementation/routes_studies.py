"""Sterile-barrier study endpoints (PRD section 3.2)."""
from flask import Blueprint, request

from auth import QUALITY_ENGINEER, QUALITY_MANAGER, context, require_role
from domain import (compute_lot_expiry, list_data, revalidate_protocol,
                    serialize)
from envelope import pagination_params, success
from errors import ApiError, err_state
from store import DB, bump, new_entity, now
from validate import get_body, get_or_404, req_bool, req_enum, req_int, req_str

bp = Blueprint("studies", __name__)


@bp.post("/api/sterile-barrier-studies")
def create_study():
    uid, role = context()
    require_role(role, QUALITY_ENGINEER)
    data = get_body()
    dmr_id = req_str(data, "dmr_id")
    study_type = req_enum(data, "study_type", ("REAL_TIME", "ACCELERATED"))
    claimed = req_int(data, "claimed_months", min_value=1)
    dmr = get_or_404("dmrs", dmr_id)
    # cross-reference gates: revision APPROVED, then sterile device
    if dmr["status"] != "APPROVED":
        raise ApiError("ERR_DMR_NOT_APPROVED", 409,
                       "A sterile-barrier study requires the DMR revision in APPROVED")
    if not dmr["sterile"]:
        raise ApiError("ERR_DMR_NOT_STERILE", 422,
                       "Sterile-barrier study on a non-sterile DMR")
    # step 12: at most one IN_PROGRESS study per DMR
    if any(s["dmr_id"] == dmr_id and s["status"] == "IN_PROGRESS"
           for s in DB["studies"].values()):
        raise ApiError("ERR_STUDY_ALREADY_ACTIVE", 409,
                       "A sterile-barrier study is already IN_PROGRESS for this DMR")
    study = new_entity({
        "dmr_id": dmr_id,
        "study_type": study_type,
        "claimed_months": claimed,
        "started_at": now(),
        "status": "IN_PROGRESS",
        "result_months_confirmed": None,
    })
    DB["studies"][study["id"]] = study
    return success(serialize(study), 201)


@bp.get("/api/sterile-barrier-studies")
def list_studies():
    context()
    filters = [(n, request.args.get(n)) for n in ("dmr_id", "status")]
    items = list_data("studies", filters)
    limit, offset = pagination_params()
    page = items[offset:offset + limit]
    return success([serialize(o) for o in page], 200, pagination={
        "limit": limit, "offset": offset, "total_count": len(items),
        "has_more": offset + len(page) < len(items),
    })


@bp.get("/api/sterile-barrier-studies/<id>")
def get_study(id):
    context()
    return success(serialize(get_or_404("studies", id)), 200)


@bp.post("/api/sterile-barrier-studies/<id>/complete")
def complete_study(id):
    uid, role = context()
    require_role(role, QUALITY_MANAGER)
    data = get_body()
    passed = req_bool(data, "passed")
    result_months = None
    if passed:
        result_months = req_int(data, "result_months_confirmed", min_value=1)
    study = get_or_404("studies", id)
    if study["status"] != "IN_PROGRESS":
        raise err_state()
    dmr = DB["dmrs"].get(study["dmr_id"])
    if passed:
        study["status"] = "PASSED"
        study["result_months_confirmed"] = result_months
        bump(study)
        if dmr is not None:
            dmr["confirmed_shelf_life_months"] = result_months
            bump(dmr)
            # recompute expiry (FINAL variant) for in-flight lots of this DMR;
            # RELEASED/RECALLED lots keep their pinned expiry
            for lot in DB["lots"].values():
                if lot["dmr_id"] == dmr["id"] and \
                        lot["disposition_status"] in ("IN_PRODUCTION", "COMPLETED"):
                    compute_lot_expiry(lot, dmr)
                    bump(lot)
    else:
        study["status"] = "FAILED"
        bump(study)
        for p in DB["protocols"].values():
            if p["dmr_id"] == study["dmr_id"] and p["status"] == "VALIDATED":
                revalidate_protocol(p, "STUDY_FAILURE")
    return success(serialize(study), 200)
