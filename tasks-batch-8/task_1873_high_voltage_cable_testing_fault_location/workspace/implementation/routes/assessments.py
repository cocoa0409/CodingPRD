import uuid

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_STALE_VERSION,
)
from helpers import (
    body_dict, req_str, req_int, req_enum, get_or_404, serialize,
    serialize_list, paginate,
)
from middleware import authenticate, ALL_ROLES
from response import success
from services import calc
from services import workflow

bp = Blueprint("assessments", __name__)

ACTIVE_ASSESSMENT_STATES = ("COMPUTED", "REVIEWED", "ADOPTED")


@bp.post("/cable-diagnostics/health-assessments")
def create_assessment():
    authenticate(["AssetEngineer"])
    body = body_dict()
    circuit_id = req_str(body, "circuit_id")
    basis = req_enum(body, "basis", calc.ASSESSMENT_BASES)
    expected = req_int(body, "expected_circuit_version")

    circuit = get_or_404(db.circuits, circuit_id, "CableCircuit")

    if expected != circuit["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_circuit_version does not match the circuit version")

    computed = calc.compute_health(circuit, basis)

    # Supersede the circuit's current assessment (at most one can be active).
    supersedes_id = None
    for a in db.assessments.values():
        if a["circuit_id"] == circuit_id and a["status"] in ACTIVE_ASSESSMENT_STATES:
            a["status"] = "SUPERSEDED"
            workflow.touch(a)
            supersedes_id = a["id"]

    now = db.now()
    rec = {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "circuit_id": circuit_id,
        "basis": basis,
        "supersedes_id": supersedes_id,
        "health_index_score": computed["health_index_score"],
        "band": computed["band"],
        "recommended_action": computed["recommended_action"],
        "penalty_components": computed["penalty_components"],
        "status": "COMPUTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.assessments[rec["id"]] = rec
    # Creation itself advances the circuit version (that is why creation is OCC-guarded).
    workflow.touch(circuit)
    return success(serialize(rec), code=201)


@bp.get("/cable-diagnostics/health-assessments/<aid>")
def get_assessment(aid):
    authenticate(ALL_ROLES)
    rec = get_or_404(db.assessments, aid, "HealthAssessment")
    return success(serialize(rec))


@bp.get("/cable-diagnostics/health-assessments")
def list_assessments():
    authenticate(ALL_ROLES)
    recs = list(db.assessments.values())
    circuit_id = request.args.get("circuit_id")
    if circuit_id is not None:
        recs = [a for a in recs if a["circuit_id"] == circuit_id]
    supersedes_id = request.args.get("supersedes_id")
    if supersedes_id is not None:
        recs = [a for a in recs if a["supersedes_id"] == supersedes_id]
    status = request.args.get("status")
    if status is not None:
        recs = [a for a in recs if a["status"] == status]
    basis = request.args.get("basis")
    if basis is not None:
        recs = [a for a in recs if a["basis"] == basis]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.post("/cable-diagnostics/health-assessments/<aid>/review")
def review_assessment(aid):
    authenticate(["AssetEngineer"])
    rec = get_or_404(db.assessments, aid, "HealthAssessment")
    if rec["status"] != "COMPUTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a COMPUTED assessment can be reviewed")
    rec["status"] = "REVIEWED"
    workflow.touch(rec)
    return success(serialize(rec))


@bp.post("/cable-diagnostics/health-assessments/<aid>/adopt")
def adopt_assessment(aid):
    authenticate(["NetworkPlanner"])
    rec = get_or_404(db.assessments, aid, "HealthAssessment")
    if rec["status"] != "REVIEWED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a REVIEWED assessment can be adopted")
    rec["status"] = "ADOPTED"
    workflow.touch(rec)
    circuit = db.circuits[rec["circuit_id"]]
    circuit["current_health_index"] = rec["health_index_score"]
    circuit["current_health_band"] = rec["band"]
    workflow.refresh_replacement(circuit)
    workflow.touch(circuit)
    return success(serialize(rec))
