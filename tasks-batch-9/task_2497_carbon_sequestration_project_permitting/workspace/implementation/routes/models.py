"""Geologic model endpoints (PRD 3.2)."""

from decimal import Decimal as D

from flask import Blueprint

import db
import enums
import middleware as mw
import response
from errors import ApiError
from services import calc, derive, lookup, serialize

bp = Blueprint("models", __name__)

ADMIN = "ProgramAdmin"
DEV = "ProjectDeveloper"
REVIEWER = "RegulatoryReviewer"


@bp.post("/ccs/geologic-models")
@mw.require(DEV)
def create_model():
    payload = mw.body()
    project_id = mw.req_str(payload, "project_id")
    expected_project_version = mw.req_int(payload, "expected_project_version")
    supersedes_model_id = mw.opt_str(payload, "supersedes_model_id")
    model_label = mw.req_str(payload, "model_label")
    top_depth = mw.req_num(payload, "injection_zone_top_depth_m", gt=0)
    thickness = mw.req_num(payload, "injection_zone_thickness_m", gt=0)
    seal_thickness = mw.req_num(payload, "seal_thickness_m", gt=0)
    capillary = mw.req_num(payload, "capillary_entry_pressure_psi", gt=0)
    p10_seal_thickness = mw.req_num(payload, "p10_seal_thickness_m", gt=0)
    p10_capillary = mw.req_num(payload, "p10_capillary_entry_pressure_psi", gt=0)
    reservoir_pressure = mw.req_num(payload, "reservoir_pressure_psi", gt=0)
    fracture_pressure = mw.req_num(payload, "fracture_pressure_psi", gt=reservoir_pressure)
    permeability = mw.req_num(payload, "permeability_md", gt=0)
    porosity = mw.req_num(payload, "porosity_fraction", gt=0, lt=1)
    assessment_variant = mw.opt_enum(
        payload, "assessment_variant", enums.ASSESSMENT_VARIANT, default="DETERMINISTIC"
    )

    project = lookup.project(project_id)
    predecessor = None
    if supersedes_model_id is not None:
        predecessor = lookup.model(supersedes_model_id)
        if predecessor["project_id"] != project["id"]:
            raise ApiError(
                "ERR_PROJECT_NOT_FOUND", "superseded model does not belong to the given project"
            )

    derive.require_not_frozen(project)

    if expected_project_version != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION", "expected_project_version does not match")

    row = db.base_fields()
    row.update(
        {
            "project_id": project["id"],
            "supersedes_model_id": predecessor["id"] if predecessor else None,
            "model_label": model_label,
            "injection_zone_top_depth_m": top_depth,
            "injection_zone_thickness_m": thickness,
            "seal_thickness_m": seal_thickness,
            "capillary_entry_pressure_psi": capillary,
            "p10_seal_thickness_m": p10_seal_thickness,
            "p10_capillary_entry_pressure_psi": p10_capillary,
            "reservoir_pressure_psi": reservoir_pressure,
            "fracture_pressure_psi": fracture_pressure,
            "permeability_md": permeability,
            "porosity_fraction": porosity,
            "assessment_variant": assessment_variant,
            "seal_integrity_index": D("0.000"),
            "seal_integrity_index_p10": D("0.000"),
            "seal_classification": "FAIL",
            "max_injection_rate_tpy": D("0"),
            "effective_injection_rate_tpy": D("0"),
            "injection_years": None,
            "plume_radius_km": D("0.000"),
            "pressure_front_radius_km": D("0.000"),
            "aor_radius_km": D("0.0"),
            "plume_status": "NOT_RUN",
            "status": "DRAFT",
            "reviewer_user_id": None,
            "revision_round_count": 0,
        }
    )
    db.geologic_models[row["id"]] = row
    db.touch(project)
    return response.object_response(serialize.model(row), 201)


@bp.get("/ccs/geologic-models")
@mw.require(ADMIN, DEV, REVIEWER)
def list_models():
    project_id = mw.query_str("project_id")
    supersedes_model_id = mw.query_str("supersedes_model_id")
    status = mw.query_enum("status", enums.MODEL_STATUS)
    rows = db.ordered(db.geologic_models.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if supersedes_model_id is not None:
        rows = [r for r in rows if r["supersedes_model_id"] == supersedes_model_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = mw.paginate(rows)
    return response.list_response([serialize.model(r) for r in page], limit, offset, total)


@bp.get("/ccs/geologic-models/<model_id>")
@mw.require(ADMIN, DEV, REVIEWER)
def get_model(model_id):
    return response.object_response(serialize.model(lookup.model(model_id)))


@bp.post("/ccs/geologic-models/<model_id>/run-plume-simulation")
@mw.require(DEV)
def run_plume_simulation(model_id):
    payload = mw.body()
    injection_years = mw.req_int(payload, "injection_years", ge=1)

    model = lookup.model(model_id)
    project = db.project_of_model(model)
    derive.require_not_frozen(project)

    if model["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError(
            "ERR_INVALID_MODEL_STATE",
            "a plume simulation may only be run from DRAFT or REVISION_REQUESTED",
        )

    _allowable, max_rate, effective = calc.max_injection_rate(
        model, project["requested_annual_injection_rate_tpy"]
    )
    model["max_injection_rate_tpy"] = max_rate
    model["effective_injection_rate_tpy"] = effective

    index, index_p10, classification = calc.seal_integrity(model, effective)
    model["seal_integrity_index"] = index
    model["seal_integrity_index_p10"] = index_p10
    model["seal_classification"] = classification

    model["injection_years"] = injection_years
    plume, front, aor = calc.plume_and_aor(model, effective, injection_years)
    model["plume_radius_km"] = plume
    model["pressure_front_radius_km"] = front
    model["aor_radius_km"] = aor

    model["plume_status"] = "SIMULATED"
    db.touch(model)
    return response.object_response(serialize.model(model))


@bp.post("/ccs/geologic-models/<model_id>/submit")
@mw.require(DEV)
def submit_model(model_id):
    payload = mw.body()
    mw.opt_str(payload, "submission_note")

    model = lookup.model(model_id)
    project = db.project_of_model(model)
    derive.require_not_frozen(project)

    if model["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError(
            "ERR_INVALID_MODEL_STATE", "a model may only be submitted from DRAFT or REVISION_REQUESTED"
        )
    if model["plume_status"] not in ("SIMULATED", "AOR_FINALIZED"):
        raise ApiError(
            "ERR_INVALID_MODEL_STATE", "a model may only be submitted once its plume has been simulated"
        )

    model["revision_round_count"] = model["revision_round_count"] + 1
    model["status"] = "SUBMITTED"
    db.touch(model)

    if project["status"] == "DRAFT":
        project["status"] = "SITE_CHARACTERIZATION"
        db.touch(project)

    return response.object_response(serialize.model(model))


@bp.post("/ccs/geologic-models/<model_id>/review")
@mw.require(REVIEWER)
def review_model(model_id):
    payload = mw.body()
    decision = mw.req_enum(payload, "decision", enums.MODEL_REVIEW_DECISION)
    mw.opt_str(payload, "review_note")

    model = lookup.model(model_id)
    project = db.project_of_model(model)
    derive.require_not_frozen(project)

    if model["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_MODEL_STATE", "only a SUBMITTED model may be reviewed")

    if decision == "ACCEPT" and model["seal_classification"] == "FAIL":
        raise ApiError(
            "ERR_SEAL_INTEGRITY_FAIL", "a model whose seal classification is FAIL cannot be accepted"
        )

    model["reviewer_user_id"] = mw.caller_id()

    if decision == "REQUEST_REVISION":
        model["status"] = "REVISION_REQUESTED"
        db.touch(model)
        return response.object_response(serialize.model(model))

    if decision == "REJECT":
        model["status"] = "REJECTED"
        db.touch(model)
        return response.object_response(serialize.model(model))

    predecessor = derive.governing_model(project)
    if predecessor is not None and predecessor["id"] != model["id"]:
        predecessor["status"] = "SUPERSEDED"
        db.touch(predecessor)

    model["status"] = "ACCEPTED"
    db.touch(model)

    project["governing_geologic_model_id"] = model["id"]
    if project["status"] == "SITE_CHARACTERIZATION":
        project["status"] = "PERMITTING"
    derive.recompute_required_assurance(project)
    db.touch(project)

    return response.object_response(serialize.model(model))


@bp.post("/ccs/geologic-models/<model_id>/finalize-aor")
@mw.require(DEV)
def finalize_aor(model_id):
    mw.body()

    model = lookup.model(model_id)
    project = db.project_of_model(model)
    derive.require_not_frozen(project)

    if model["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_MODEL_STATE", "only an ACCEPTED model may publish its AoR")
    if model["plume_status"] != "SIMULATED":
        raise ApiError("ERR_INVALID_MODEL_STATE", "the model's plume status must be SIMULATED")

    # Link 1 — publish the delineation.
    project["aor_radius_km"] = model["aor_radius_km"]

    # Link 2 — re-screen legacy wellbores against the new radius.
    newly_identified = []
    for wellbore in db.wellbores_of(project["id"]):
        promoted = False
        if (
            wellbore["corrective_action_status"] == "OUT_OF_AOR"
            and wellbore["distance_from_injector_km"] <= D(project["aor_radius_km"])
        ):
            wellbore["corrective_action_status"] = "IDENTIFIED"
            promoted = True
            newly_identified.append(wellbore)
        if wellbore["corrective_action_status"] in calc.IN_AOR_STATUSES:
            rescored = derive.rescore_wellbore(wellbore, project)
            if promoted or rescored:
                db.touch(wellbore)
        elif promoted:
            db.touch(wellbore)

    for wellbore in newly_identified:
        derive.screen_wellbore_for_ca(wellbore)

    # Links 3 and 4 — completion percentage, requirement, coverage, posture.
    derive.recompute_ca_completion(project)
    derive.recompute_required_assurance(project)

    model["plume_status"] = "AOR_FINALIZED"
    db.touch(model)
    db.touch(project)

    return response.object_response(serialize.model(model))
