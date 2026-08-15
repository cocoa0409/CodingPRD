import uuid

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_PERMIT_EXISTS,
    ERR_SEGREGATION_OF_DUTIES,
)
from helpers import (
    body_dict, req_str, req_int, req_list, get_or_404, serialize,
    serialize_list, paginate,
)
from middleware import authenticate, ALL_ROLES
from response import success
from services import workflow

bp = Blueprint("permits", __name__)


@bp.post("/cable-diagnostics/isolation-permits")
def create_permit():
    authenticate(["SafetyOfficer"])
    body = body_dict()
    test_job_id = req_str(body, "test_job_id")
    points = req_list(body, "isolation_points")
    if len(points) < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "isolation_points requires at least one entry")
    ground_count = req_int(body, "ground_count")
    if ground_count < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "ground_count must be >= 1")

    job = get_or_404(db.jobs, test_job_id, "TestJob")
    if job["status"] not in ("PLANNED", "IN_PROGRESS"):
        raise ApiError(ERR_INVALID_STATE, 409, "Job must be PLANNED or IN_PROGRESS")
    for p in db.permits.values():
        if p["test_job_id"] == test_job_id and p["status"] != "RELEASED":
            raise ApiError(ERR_PERMIT_EXISTS, 409, "A non-RELEASED permit already exists for the job")

    now = db.now()
    rec = {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "test_job_id": test_job_id,
        "isolation_points": list(points),
        "ground_count": ground_count,
        "status": "DRAFT",
        "issued_by_user_id": None,
        "grounding_verified_by_user_id": None,
        "released_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.permits[rec["id"]] = rec
    return success(serialize(rec), code=201)


@bp.get("/cable-diagnostics/isolation-permits/<pid>")
def get_permit(pid):
    authenticate(ALL_ROLES)
    rec = get_or_404(db.permits, pid, "IsolationPermit")
    return success(serialize(rec))


@bp.get("/cable-diagnostics/isolation-permits")
def list_permits():
    authenticate(ALL_ROLES)
    recs = list(db.permits.values())
    job_id = request.args.get("test_job_id")
    if job_id is not None:
        recs = [p for p in recs if p["test_job_id"] == job_id]
    status = request.args.get("status")
    if status is not None:
        recs = [p for p in recs if p["status"] == status]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


def _circuit_of_permit(permit):
    job = db.jobs.get(permit["test_job_id"])
    return db.circuits.get(job["circuit_id"]) if job else None


@bp.post("/cable-diagnostics/isolation-permits/<pid>/issue")
def issue_permit(pid):
    user_id, _ = authenticate(["SafetyOfficer"])
    permit = get_or_404(db.permits, pid, "IsolationPermit")
    if permit["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT permit can be issued")
    permit["status"] = "ISSUED"
    permit["issued_by_user_id"] = user_id
    workflow.touch(permit)
    circuit = _circuit_of_permit(permit)
    if circuit and circuit["status"] == "OUTAGE_PENDING":
        circuit["status"] = "DE_ENERGIZED"
        workflow.touch(circuit)
    return success(serialize(permit))


@bp.post("/cable-diagnostics/isolation-permits/<pid>/verify-grounding")
def verify_grounding(pid):
    user_id, _ = authenticate(["SafetyOfficer"])
    permit = get_or_404(db.permits, pid, "IsolationPermit")
    if permit["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ISSUED permit can be grounding-verified")
    if user_id == permit["issued_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422, "Grounding verifier must differ from the issuer")
    permit["status"] = "GROUNDING_VERIFIED"
    permit["grounding_verified_by_user_id"] = user_id
    workflow.touch(permit)
    circuit = _circuit_of_permit(permit)
    if circuit and circuit["status"] == "DE_ENERGIZED":
        circuit["status"] = "GROUNDED"
        workflow.touch(circuit)
    return success(serialize(permit))


@bp.post("/cable-diagnostics/isolation-permits/<pid>/release")
def release_permit(pid):
    user_id, _ = authenticate(["SafetyOfficer"])
    permit = get_or_404(db.permits, pid, "IsolationPermit")
    if permit["status"] != "GROUNDING_VERIFIED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a GROUNDING_VERIFIED permit can be released")
    job = db.jobs.get(permit["test_job_id"])
    if job is None or job["status"] != "EVALUATION":
        raise ApiError(ERR_INVALID_STATE, 409, "Job must be in EVALUATION before permit release")
    if user_id == permit["grounding_verified_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422, "Releaser must differ from the grounding verifier")
    permit["status"] = "RELEASED"
    permit["released_by_user_id"] = user_id
    workflow.touch(permit)
    circuit = _circuit_of_permit(permit)
    if circuit and circuit["status"] == "TEST_COMPLETE":
        circuit["status"] = "RESTORING"
        workflow.touch(circuit)
    return success(serialize(permit))
