"""ModelRun endpoints (PRD §3.2): creation with OCC + per_class_results
computation, finalize with GapFinding generation and privilege invalidation."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_STALE_GROUP_VERSION,
    ERR_GROUP_INVALID_STATE,
    ERR_STUDY_INVALID_STATE,
    ERR_RUN_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.calculations import compute_per_class_results
from services.core import (
    new_record, touch, runs_of_group, compute_is_actionable,
    recompute_study_aggregates,
)
from util import clock_now_iso
from validate import get_body, req_enum, require_path_resource, require_fk

bp = Blueprint("runs", __name__)

METHODOLOGIES = {"REGRESSION_OLS", "COHORT_MEDIAN"}


@bp.post("/model-runs")
def create_run():
    authorized(["CompAnalyst"])
    body = get_body()
    group_id = body.get("comparator_group_id")
    if group_id is None or not isinstance(group_id, str) or group_id.strip() == "":
        raise_error(ERR_INVALID_REQUEST, "missing or invalid field: comparator_group_id")
    # Priority 3: body FK existence
    group = require_fk("comparator_groups", group_id, "comparator_group_id")
    # Priority 3.5: OCC — expected_group_version vs the group's current version
    if "expected_group_version" not in body or body["expected_group_version"] is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: expected_group_version")
    egv = body["expected_group_version"]
    if not isinstance(egv, int) or isinstance(egv, bool):
        raise_error(ERR_INVALID_REQUEST, "expected_group_version must be an integer")
    if egv != group["version"]:
        raise_error(ERR_STALE_GROUP_VERSION,
                    "expected_group_version does not match the group's current version")
    # Priority 3.7: shape
    methodology = req_enum(body, "methodology", METHODOLOGIES)
    # Priority 4: state — group LOCKED or ANALYZED; study MODELING or MONITORING
    if group["status"] not in ("LOCKED", "ANALYZED"):
        raise_error(ERR_GROUP_INVALID_STATE,
                    "run creation requires a LOCKED or ANALYZED group")
    study = db["pay_equity_studies"].get(group["study_id"])
    if study is None or study["status"] not in ("MODELING", "MONITORING"):
        raise_error(ERR_STUDY_INVALID_STATE,
                    "run creation requires the study to be MODELING or MONITORING")

    prior_runs = runs_of_group(group_id)
    run_index = len(prior_runs) + 1

    # Results computed at creation time and frozen (PRD §3.2)
    per_class_results = compute_per_class_results(group, study, methodology)

    rec = new_record("model_runs", {
        "comparator_group_id": group_id,
        "study_id": group["study_id"],
        "methodology": methodology,
        "run_index": run_index,
        "per_class_results": per_class_results,
        "status": "PROVISIONAL",
        "finalized_at": None,
    })

    # Side effects: supersede prior PROVISIONAL runs; bump group version
    for r in prior_runs:
        if r["status"] == "PROVISIONAL":
            r["status"] = "SUPERSEDED"
            touch(r)
    touch(group)
    return success_object(public(rec), status=201)


@bp.get("/model-runs")
def list_runs():
    return list_response("model_runs", {
        "comparator_group_id": request.args.get("comparator_group_id"),
        "study_id": request.args.get("study_id"),
        "status": request.args.get("status"),
    })


@bp.get("/model-runs/<rid>")
def get_run(rid):
    return get_one("model_runs", rid)


@bp.post("/model-runs/<rid>/finalize")
def finalize_run(rid):
    authorized(["CompAnalyst"])
    run = require_path_resource("model_runs", rid)
    if run["status"] != "PROVISIONAL":
        raise_error(ERR_RUN_INVALID_STATE, "finalize requires a PROVISIONAL run")

    study = db["pay_equity_studies"].get(run["study_id"])
    group = db["comparator_groups"].get(run["comparator_group_id"])

    run["status"] = "FINAL"
    run["finalized_at"] = clock_now_iso()
    touch(run)

    # Generate one GapFinding per per_class_results key whose dimension is in
    # study.protected_classes. Order pinned: protected_classes array order,
    # then class_value ASC within a dimension (PRD §3.3).
    per_class = run["per_class_results"] or {}
    for dimension in (study["protected_classes"] if study else []):
        keys = sorted(k for k in per_class if k.startswith(dimension + ":"))
        for key in keys:
            entry = per_class[key]
            class_value = entry.get("class_value") or key.split(":", 1)[1]
            new_record("gap_findings", {
                "model_run_id": run["id"],
                "comparator_group_id": run["comparator_group_id"],
                "study_id": run["study_id"],
                "protected_class": dimension,
                "class_value": class_value,
                "reference_class": entry["reference_class"],
                "adjusted_gap_pct": entry["adjusted_gap_pct"],
                "p_value": entry["p_value"],
                "affected_headcount": entry["class_headcount"],
                "is_actionable": compute_is_actionable(
                    study, entry["adjusted_gap_pct"], entry["p_value"]),
                "status": "FLAGGED",
                "disposition_rationale": None,
                "disposition_by_user_id": None,
            })

    # Parent group LOCKED -> ANALYZED once finding generation completes
    if group is not None and group["status"] == "LOCKED":
        group["status"] = "ANALYZED"
        touch(group)

    # Privilege invalidation: new evidence while PRIVILEGED_FINAL (PRD §3.2/§3.3)
    if study is not None:
        if study["status"] == "PRIVILEGED_FINAL":
            study["status"] = "UNDER_LEGAL_REVIEW"
            study["privileged_model_run_ids"] = []
            study["review_rounds"] = study.get("review_rounds", 0) + 1
        recompute_study_aggregates(study["id"])

    return success_object(public(run))
