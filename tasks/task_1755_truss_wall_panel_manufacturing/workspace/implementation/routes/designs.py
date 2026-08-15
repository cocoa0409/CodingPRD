"""ComponentDesign endpoints: create/revision, seal lifecycle with governance."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_DESIGN_NOT_AWAITING_SEAL,
    ERR_DUPLICATE_COMPONENT_REF,
    ERR_REVISION_CHAIN_BROKEN,
    ERR_ENGINEER_LICENSE_EXPIRED,
    ERR_ENGINEER_LICENSE_STATE_MISMATCH,
    ERR_SEAL_AUTHORITY_INSUFFICIENT,
    ERR_SEALER_MUST_DIFFER_FROM_SUBMITTER,
    ERR_STALE_JOB_VERSION,
)
from middleware import authenticate, require_role, require_ownership, get_or_404, ALL_ROLES
from response import success, success_list
from services import serializers
from services.cascade import UNIT_BF_PER_SPAN_FT
from util import as_enum, as_int, as_num, as_str, as_fk, body, paginate, dec, round2

bp = Blueprint("designs", __name__)

COMPONENT_TYPES = {"FLOOR_TRUSS", "ROOF_TRUSS", "WALL_PANEL"}
LUMBER_GRADES = {"SPF_NO2", "SPF_MSR2400", "SYP_NO1"}
PLATE_CLASSES = {"P20", "P18", "P16"}
DESIGN_STATES = {"DRAFT", "SEAL_REQUESTED", "SEALED", "SUPERSEDED", "VOID"}


def _pair_designs(job_id, component_ref):
    return [d for d in db.designs.values()
            if d["job_id"] == job_id and d["component_ref"] == component_ref]


@bp.route("/plant/jobs/<job_id>/designs", methods=["POST"])
def create_design(job_id):
    uid, role = authenticate()
    require_role(role, ["DesignEngineer"])
    job = get_or_404(db.jobs, job_id, "job")
    data = body()
    # Body FK existence (declared input order puts supersedes_design_id last).
    supersedes = as_fk(data.get("supersedes_design_id"), "supersedes_design_id",
                       db.designs, "component design")
    # Schema.
    component_ref = as_str(data.get("component_ref"), "component_ref", required=True)
    component_type = as_enum(data.get("component_type"), "component_type", COMPONENT_TYPES, required=True)
    span_ft = as_num(data.get("span_ft"), "span_ft", required=True)
    pitch_degrees = as_num(data.get("pitch_degrees"), "pitch_degrees", required=True)
    design_load_psf = as_num(data.get("design_load_psf"), "design_load_psf", required=True)
    lumber_grade = as_enum(data.get("lumber_grade"), "lumber_grade", LUMBER_GRADES, required=True)
    plating = as_enum(data.get("plating"), "plating", PLATE_CLASSES, required=True)
    quantity_required = as_int(data.get("quantity_required"), "quantity_required", required=True)
    expected_job_version = as_int(data.get("expected_job_version"), "expected_job_version", required=True)
    # OCC (priority 6).
    if expected_job_version != job["version"]:
        raise ApiError(ERR_STALE_JOB_VERSION, 412, "job version has advanced since last read")
    # component_ref discipline + revision chain (priorities 28/29, after OCC).
    pair = _pair_designs(job["id"], component_ref)
    if any(d["status"] in ("DRAFT", "SEAL_REQUESTED") for d in pair):
        raise ApiError(ERR_DUPLICATE_COMPONENT_REF, 409,
                       "an open DRAFT/SEAL_REQUESTED revision already exists for this component_ref")
    sealed = [d for d in pair if d["status"] == "SEALED"]
    if supersedes is None:
        if sealed:
            raise ApiError(ERR_DUPLICATE_COMPONENT_REF, 409,
                           "a SEALED revision exists; creating a revision requires supersedes_design_id")
    else:
        if not sealed:
            raise ApiError(ERR_REVISION_CHAIN_BROKEN, 422,
                           "no SEALED revision exists for this component_ref")
        current_sealed = max(sealed, key=lambda d: d["revision_no"])
        if supersedes["id"] != current_sealed["id"]:
            raise ApiError(ERR_DUPLICATE_COMPONENT_REF, 409,
                           "supersedes_design_id must name the current sealed revision")
    revision_no = 1 + max((d["revision_no"] for d in pair), default=0)
    est_bf = round2(dec(span_ft) * UNIT_BF_PER_SPAN_FT[component_type])
    rec = db.new_record({
        "job_id": job["id"],
        "component_ref": component_ref,
        "revision_no": revision_no,
        "supersedes_design_id": supersedes["id"] if supersedes else None,
        "component_type": component_type,
        "span_ft": span_ft,
        "pitch_degrees": pitch_degrees,
        "design_load_psf": design_load_psf,
        "lumber_grade": lumber_grade,
        "plating": plating,
        "quantity_required": quantity_required,
        "est_board_feet_per_unit": est_bf,
        "status": "DRAFT",
        "submitted_by_engineer_id": None,
        "sealed_by_engineer_id": None,
        "sealed_at": None,
    })
    db.designs[rec["id"]] = rec
    db.touch(job)  # each design create increments the job's version
    return success(serializers.design(rec), status=201)


@bp.route("/plant/designs/<did>", methods=["GET"])
def get_design(did):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.designs, did, "component design")
    require_ownership(role, uid, db.jobs[rec["job_id"]]["customer_id"])
    return success(serializers.design(rec))


@bp.route("/plant/designs", methods=["GET"])
def list_designs():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    records = list(db.designs.values())
    if role == "CustomerContact":
        records = [d for d in records if db.jobs[d["job_id"]]["customer_id"] == uid]
    for field in ("job_id", "supersedes_design_id", "submitted_by_engineer_id",
                  "sealed_by_engineer_id", "status", "component_ref"):
        raw = request.args.get(field)
        if raw is not None:
            records = [d for d in records if d[field] == raw]
    page, meta = paginate(records)
    return success_list([serializers.design(d) for d in page], meta)


@bp.route("/plant/designs/<did>/transition", methods=["POST"])
def design_transition(did):
    uid, role = authenticate()
    require_role(role, ["DesignEngineer"])
    rec = get_or_404(db.designs, did, "component design")
    data = body()
    to_state = as_enum(data.get("to_state"), "to_state", DESIGN_STATES, required=True)

    if to_state == "SEALED":
        # Priority 8 (state) precedes the four safety gates (priorities 15-18).
        if rec["status"] != "SEAL_REQUESTED":
            raise ApiError(ERR_DESIGN_NOT_AWAITING_SEAL, 409,
                           "design is not in SEAL_REQUESTED")
        engineer = db.engineers[uid]  # entity-backed identity, resolved at auth
        job = db.jobs[rec["job_id"]]
        clock = db.get_clock()
        if engineer["license_expiry"] < clock:
            raise ApiError(ERR_ENGINEER_LICENSE_EXPIRED, 422, "sealing engineer license has expired")
        if engineer["license_state"] != job["jobsite_state"]:
            raise ApiError(ERR_ENGINEER_LICENSE_STATE_MISMATCH, 422,
                           "sealing engineer is not licensed in the jobsite state")
        if rec["component_type"] == "WALL_PANEL" and engineer["seal_authority"] != "TRUSS_AND_PANEL":
            raise ApiError(ERR_SEAL_AUTHORITY_INSUFFICIENT, 422,
                           "WALL_PANEL designs require TRUSS_AND_PANEL authority")
        if uid == rec["submitted_by_engineer_id"]:
            raise ApiError(ERR_SEALER_MUST_DIFFER_FROM_SUBMITTER, 422,
                           "sealing engineer must differ from the submitting engineer")
        rec["status"] = "SEALED"
        rec["sealed_by_engineer_id"] = uid
        rec["sealed_at"] = clock
        db.touch(rec)
        return success(serializers.design(rec))

    if to_state == "SEAL_REQUESTED":
        if rec["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, 409, f"cannot request seal from {rec['status']}")
        rec["status"] = "SEAL_REQUESTED"
        rec["submitted_by_engineer_id"] = uid
        db.touch(rec)
        return success(serializers.design(rec))

    if to_state == "DRAFT":
        # Seal rejection loop: a fresh submit records a fresh submitter.
        if rec["status"] != "SEAL_REQUESTED":
            raise ApiError(ERR_INVALID_STATE, 409, f"cannot reject from {rec['status']}")
        rec["status"] = "DRAFT"
        rec["submitted_by_engineer_id"] = None
        db.touch(rec)
        return success(serializers.design(rec))

    if to_state == "VOID":
        if rec["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, 409, f"cannot void from {rec['status']}")
        rec["status"] = "VOID"
        db.touch(rec)
        return success(serializers.design(rec))

    # SUPERSEDED is system-only via change-order apply.
    raise ApiError(ERR_INVALID_STATE, 409, f"design transition to {to_state} is not declared")
