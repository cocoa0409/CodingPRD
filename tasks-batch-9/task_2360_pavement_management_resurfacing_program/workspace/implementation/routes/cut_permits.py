"""Pavement cut permits, moratorium review and degradation fees (PRD 3.9)."""
from flask import Blueprint

import calc
import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import endpoint
from services import derive

bp = Blueprint("cut_permits", __name__)

DECISIONS = ("APPROVE", "DENY")
READ_ROLES = ("PavementEngineer", "UtilityCoordinator", "Inspector")


def _find_permit(permit_id):
    permit = db.cut_permits.get(permit_id)
    if permit is None:
        raise ApiError("ERR_CUT_PERMIT_NOT_FOUND")
    return permit


@bp.post("/cut-permits")
@endpoint("UtilityCoordinator")
def create_permit():
    data = v.body()
    segment_id = v.field_id(data, "segment_id")
    applicant_utility = v.field_enum(data, "applicant_utility", calc.UTILITIES)
    requested_start = v.field_datetime(data, "requested_start")
    requested_end = v.field_datetime(data, "requested_end")
    cut_area_sqft = v.field_number(data, "cut_area_sqft", minimum=0,
                                   exclusive_minimum=True)
    emergency = v.field_bool(data, "emergency", required=False, default=False)
    v.window(requested_start, requested_end, "requested cut window")

    segment = db.segments.get(segment_id)
    if segment is None:
        raise ApiError("ERR_SEGMENT_NOT_FOUND")

    # Worker safety outranks every roster, moratorium and fee consideration.
    if derive.segment_has_active_construction(segment_id):
        raise ApiError("ERR_CUT_BLOCKED_ACTIVE_CONSTRUCTION")
    on_roster = any(c["utility"] == applicant_utility
                    for c in db.coordinations.values())
    if not on_roster:
        raise ApiError("ERR_UTILITY_NOT_ON_COORDINATION_ROSTER")

    now = clock.now()
    remaining, multiplier, fee = calc.cut_permit_fee(
        cut_area_sqft, segment["moratorium_until"], emergency, now
    )
    under_moratorium = segment["moratorium_until"] is not None \
        and segment["moratorium_until"] > now
    status = "MORATORIUM_REVIEW" if (under_moratorium and not emergency) \
        else "PENDING"

    permit = {
        "id": db.new_id(),
        "segment_id": segment_id,
        "applicant_utility": applicant_utility,
        "requested_start": requested_start,
        "requested_end": requested_end,
        "cut_area_sqft": cut_area_sqft,
        "emergency": emergency,
        "permit_status": status,
        "moratorium_remaining_days": remaining,
        "fee_multiplier": multiplier,
        "degradation_fee_cents": fee,
        "waiver_reason": None,
        "decided_at": None,
        "cut_completed_at": None,
    }
    permit.update(db.audit())
    db.cut_permits[permit["id"]] = permit
    return response.object_response(permit, 201)


@bp.get("/cut-permits/<permit_id>")
@endpoint(*READ_ROLES)
def read_permit(permit_id):
    return response.object_response(_find_permit(permit_id))


@bp.get("/cut-permits")
@endpoint(*READ_ROLES)
def list_permits():
    rows = v.filter_rows(db.ordered(db.cut_permits.values()), {
        "segment_id": "segment_id",
        "permit_status": "permit_status",
        "applicant_utility": "applicant_utility",
    })
    page, meta = v.paginate(rows)
    return response.array_response(page, pagination=meta)


@bp.post("/cut-permits/<permit_id>/decide")
@endpoint("PavementEngineer")
def decide_permit(permit_id):
    data = v.body()
    decision = v.field_enum(data, "decision", DECISIONS)
    waiver_reason = v.field_string(data, "waiver_reason", 1, 500, required=False)

    permit = _find_permit(permit_id)
    if permit["permit_status"] not in ("PENDING", "MORATORIUM_REVIEW"):
        raise ApiError("ERR_CUT_PERMIT_ALREADY_DECIDED")

    if decision == "APPROVE":
        if permit["permit_status"] == "MORATORIUM_REVIEW" \
                and (waiver_reason is None or not waiver_reason.strip()):
            raise ApiError("ERR_MORATORIUM_WAIVER_REQUIRED")
        if derive.segment_has_active_construction(permit["segment_id"]):
            raise ApiError("ERR_CUT_BLOCKED_ACTIVE_CONSTRUCTION")

    now = clock.now()
    if decision == "APPROVE":
        updates = {"permit_status": "APPROVED", "decided_at": now}
        if permit["permit_status"] == "MORATORIUM_REVIEW":
            updates["waiver_reason"] = waiver_reason
    else:
        updates = {"permit_status": "DENIED", "decided_at": now}
    derive.apply_updates(permit, updates)
    return response.object_response(permit)


@bp.post("/cut-permits/<permit_id>/complete-cut")
@endpoint("UtilityCoordinator")
def complete_cut(permit_id):
    v.body()
    permit = _find_permit(permit_id)
    if permit["permit_status"] != "APPROVED" \
            or permit["cut_completed_at"] is not None:
        raise ApiError("ERR_CUT_NOT_APPROVED_OR_ALREADY_COMPLETE")
    derive.apply_updates(permit, {"cut_completed_at": clock.now()})
    return response.object_response(permit)
