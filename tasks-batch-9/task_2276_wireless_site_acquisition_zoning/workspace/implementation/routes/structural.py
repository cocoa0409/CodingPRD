"""TIA-222 loading analyses and modification-design peer review."""

from flask import Blueprint

import calc
import services
from db import db, new_record, serialize
from errors import ApiError
from response import created, ok
from routes.common import fetch, listing
from validation import (ALL_ROLES, INTEGER, NUMBER, ROLE_ENGINEER, STRING,
                        actor_id, authenticate, f, require_conditional,
                        validate_body)

bp = Blueprint("structural", __name__)

ANALYSIS_TYPES = ["TIA_222_H", "TIA_222_G"]
SCOPES = ["REINFORCEMENT", "MOUNT_UPGRADE", "TOWER_REPLACEMENT"]
REVIEW_ACTIONS = ["SUBMIT", "REJECT", "REVISE", "CERTIFY"]


@bp.post("/structural-analyses")
def create_analysis():
    authenticate([ROLE_ENGINEER])
    body = validate_body([
        f("candidate_id", STRING),
        f("analysis_type", STRING, enum=ANALYSIS_TYPES),
        f("existing_load_pct", NUMBER, ge=0),
        f("appurtenance_count", INTEGER, ge=0),
        f("wind_speed_mph", NUMBER, gt=0),
        f("ice_thickness_in", NUMBER, ge=0),
        f("performed_by_user_id", STRING),
        f("expected_candidate_version", INTEGER),
    ])
    candidate = db.candidates.get(body["candidate_id"])
    if candidate is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404)

    if body["expected_candidate_version"] != candidate["version"]:
        raise ApiError("ERR_STALE_CANDIDATE_VERSION", 412)
    if candidate["feasibility_status"] not in ("RF_QUALIFIED", "STRUCTURALLY_CLEARED"):
        raise ApiError("ERR_INVALID_CANDIDATE_STATE", 409)

    for prior in services.analyses_of_candidate(candidate["id"]):
        if prior["status"] in ("IN_PROGRESS", "COMPLETED"):
            services.apply(prior, {"status": "SUPERSEDED"})

    analysis = new_record({
        "candidate_id": candidate["id"],
        "analysis_type": body["analysis_type"],
        "existing_load_pct": body["existing_load_pct"],
        "appurtenance_count": body["appurtenance_count"],
        "wind_speed_mph": body["wind_speed_mph"],
        "ice_thickness_in": body["ice_thickness_in"],
        "performed_by_user_id": body["performed_by_user_id"],
        "capacity_utilization_pct": None,
        "result": "PENDING",
        "status": "IN_PROGRESS",
    })
    db.structural_analyses[analysis["id"]] = analysis
    services.apply(candidate, {"feasibility_status": "STRUCTURAL_HOLD"})
    return created(serialize(analysis))


@bp.get("/structural-analyses")
def list_analyses():
    authenticate(ALL_ROLES)
    return listing("structural_analyses", ["candidate_id", "status", "result"])


@bp.get("/structural-analyses/<analysis_id>")
def read_analysis(analysis_id):
    authenticate(ALL_ROLES)
    return ok(serialize(fetch("structural_analyses", analysis_id)))


@bp.post("/structural-analyses/<analysis_id>/complete")
def complete_analysis(analysis_id):
    authenticate([ROLE_ENGINEER])
    validate_body([])
    analysis = fetch("structural_analyses", analysis_id)
    if analysis["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_ANALYSIS_STATE", 409)

    utilization = calc.structural_capacity_utilization(analysis)
    result = calc.structural_result(utilization)
    services.apply(analysis, {
        "capacity_utilization_pct": utilization,
        "result": result,
        "status": "COMPLETED",
    })

    candidate = db.candidates.get(analysis["candidate_id"])
    if candidate is not None and candidate["feasibility_status"] == "STRUCTURAL_HOLD":
        if result == "PASS":
            services.apply(candidate, {"feasibility_status": "STRUCTURALLY_CLEARED"})
        elif result == "FAIL":
            services.disqualify_candidate(candidate)
    return ok(serialize(analysis))


@bp.post("/modification-designs")
def create_design():
    authenticate([ROLE_ENGINEER])
    body = validate_body([
        f("structural_analysis_id", STRING),
        f("scope", STRING, enum=SCOPES),
        f("estimated_cost_usd", NUMBER, gt=0),
        f("designed_by_user_id", STRING),
    ])
    analysis = db.structural_analyses.get(body["structural_analysis_id"])
    if analysis is None:
        raise ApiError("ERR_STRUCTURAL_ANALYSIS_NOT_FOUND", 404)
    if analysis["status"] != "COMPLETED":
        raise ApiError("ERR_ANALYSIS_SUPERSEDED", 409)

    design = new_record({
        "structural_analysis_id": analysis["id"],
        "scope": body["scope"],
        "estimated_cost_usd": body["estimated_cost_usd"],
        "designed_by_user_id": body["designed_by_user_id"],
        "certified_by_user_id": None,
        "status": "DRAFT",
        "revision_count": 0,
        "rejection_reason": None,
    })
    db.modification_designs[design["id"]] = design
    return created(serialize(design))


@bp.get("/modification-designs")
def list_designs():
    authenticate(ALL_ROLES)
    return listing("modification_designs", ["structural_analysis_id", "status"])


@bp.get("/modification-designs/<design_id>")
def read_design(design_id):
    authenticate(ALL_ROLES)
    return ok(serialize(fetch("modification_designs", design_id)))


@bp.post("/modification-designs/<design_id>/peer-review")
def peer_review(design_id):
    authenticate([ROLE_ENGINEER])
    body = validate_body([
        f("action", STRING, enum=REVIEW_ACTIONS),
        f("rejection_reason", STRING, required=False),
    ])
    action = body["action"]
    if action == "REJECT":
        require_conditional(body, "rejection_reason")

    design = fetch("modification_designs", design_id)
    analysis = db.structural_analyses.get(design["structural_analysis_id"])
    actor = actor_id()

    # tier 11: segregation of duties
    if action == "CERTIFY":
        if actor == design["designed_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403)
        if analysis is not None and actor == analysis["performed_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403)
    elif action == "REJECT":
        if actor == design["designed_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403)

    # tier 19: the backing analysis must still be COMPLETED
    if analysis is None or analysis["status"] != "COMPLETED":
        raise ApiError("ERR_ANALYSIS_SUPERSEDED", 409)

    # tier 21: design state
    status = design["status"]
    allowed = {
        "SUBMIT": ("DRAFT",),
        "REJECT": ("PEER_REVIEW",),
        "REVISE": ("REJECTED",),
        "CERTIFY": ("PEER_REVIEW",),
    }[action]
    if status not in allowed:
        raise ApiError("ERR_INVALID_DESIGN_STATE", 409)
    if action == "SUBMIT" and analysis["result"] != "PASS_WITH_MOD":
        raise ApiError("ERR_INVALID_DESIGN_STATE", 409)

    if action == "SUBMIT":
        services.apply(design, {"status": "PEER_REVIEW"})
        return ok(serialize(design))
    if action == "REJECT":
        services.apply(design, {"rejection_reason": body["rejection_reason"],
                                "status": "REJECTED"})
        return ok(serialize(design))
    if action == "REVISE":
        services.apply(design, {"revision_count": design["revision_count"] + 1,
                                "rejection_reason": None,
                                "status": "DRAFT"})
        return ok(serialize(design))

    # CERTIFY
    candidate = db.candidates.get(analysis["candidate_id"])
    ring = services.ring_of_candidate(candidate) if candidate is not None else None
    if ring is not None:
        projected = services.ring_committed_capex(ring["id"], extra_design_id=design["id"])
        if projected > calc.dec(ring["capex_budget_usd"]):
            raise ApiError("ERR_CAPEX_BUDGET_EXCEEDED", 409)

    services.apply(design, {"certified_by_user_id": actor, "status": "CERTIFIED"})
    if ring is not None:
        services.apply(ring, {"committed_capex_usd": services.ring_committed_capex(ring["id"])})
    if candidate is not None and candidate["feasibility_status"] == "STRUCTURAL_HOLD":
        services.apply(candidate, {"feasibility_status": "STRUCTURALLY_CLEARED"})
    return ok(serialize(design))
