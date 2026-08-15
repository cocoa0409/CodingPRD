"""Lab batches and lab results (PRD section 3.5)."""

from flask import Blueprint, request

import db
from errors import (
    ERR_ANALYTE_MISMATCH,
    ERR_BATCH_CAPACITY_FULL,
    ERR_BATCH_NOT_ACCEPTING,
    ERR_BATCH_WINDOW_CLOSED,
    ERR_CALIBRATION_NOT_VALID,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_REQUEST,
    ERR_PLAN_INVALID_STATE,
    ERR_RESULT_ALREADY_EXISTS,
    ERR_SAMPLE_INVALID_STATE,
    ERR_SOD_CHAIN_OF_CUSTODY,
    raise_error,
)
from helpers import (
    reject_unknown,
    body, get_or_404, list_response, now_ts, req_date, req_int, req_number,
    req_string, stamp_new, today, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from serializers import batch_out, result_out
from services import (
    analyze_sample, find_result_for_sample, maybe_complete_lab,
    recompute_plan_counts, run_contamination_cascade,
)

bp = Blueprint("lab", __name__)

LAB = ("LabAnalyst",)


# ---------------------------------------------------------------------------
# Lab batches
# ---------------------------------------------------------------------------

@bp.route("/ih/lab-batches", methods=["POST"])
def create_batch():
    require_auth(LAB)
    data = body()
    reject_unknown(data, {"site_id", "analyte_code", "lod_ug", "loq_ug", "window_start_date", "window_end_date", "max_capacity"})
    site_id = req_string(data, "site_id")
    analyte_code = req_string(data, "analyte_code")
    lod_ug = req_number(data, "lod_ug")
    if lod_ug <= 0:
        raise_error(ERR_INVALID_REQUEST, "lod_ug must be > 0")
    loq_ug = req_number(data, "loq_ug")
    if loq_ug < lod_ug:
        raise_error(ERR_INVALID_REQUEST, "loq_ug must be >= lod_ug")
    window_start = req_date(data, "window_start_date")
    window_end = req_date(data, "window_end_date")
    if window_end < window_start:
        raise_error(ERR_INVALID_DATE_RANGE,
                    "window_end_date must be >= window_start_date")
    max_capacity = req_int(data, "max_capacity")
    if max_capacity < 1:
        raise_error(ERR_INVALID_REQUEST, "max_capacity must be >= 1")
    get_or_404(db.sites, site_id, "Site")
    batch = {
        "site_id": site_id,
        "analyte_code": analyte_code,
        "lod_ug": lod_ug,
        "loq_ug": loq_ug,
        "window_start_date": window_start.isoformat(),
        "window_end_date": window_end.isoformat(),
        "max_capacity": max_capacity,
        "intake_count": 0,
        "contaminated": False,
    }
    stamp_new(batch)
    db.lab_batches[batch["id"]] = batch
    return success_object(batch_out(batch), 201)


@bp.route("/ih/lab-batches", methods=["GET"])
def list_batches():
    require_auth(ALL_ROLES)
    return list_response(list(db.lab_batches.values()), batch_out,
                         {"site_id": request.args.get("site_id")})


@bp.route("/ih/lab-batches/<bid>", methods=["GET"])
def get_batch(bid):
    require_auth(ALL_ROLES)
    return success_object(batch_out(get_or_404(db.lab_batches, bid, "LabBatch")))


# ---------------------------------------------------------------------------
# Lab results
# ---------------------------------------------------------------------------

@bp.route("/ih/lab-results", methods=["POST"])
def create_result():
    user_id, _ = require_auth(LAB)
    data = body()
    reject_unknown(data, {"field_sample_id", "lab_batch_id", "mass_ug"})
    # ---- Stage 3: schema.
    field_sample_id = req_string(data, "field_sample_id")
    lab_batch_id = req_string(data, "lab_batch_id")
    mass_ug = req_number(data, "mass_ug")
    if mass_ug < 0:
        raise_error(ERR_INVALID_REQUEST, "mass_ug must be >= 0")
    # ---- Stage 4: existence in declared input order.
    sample = get_or_404(db.field_samples, field_sample_id, "FieldSample")
    batch = get_or_404(db.lab_batches, lab_batch_id, "LabBatch")
    plan = db.sampling_plans[sample["sampling_plan_id"]]
    seg = db.segs[plan["seg_id"]]
    # ---- One result per sample. A sample carrying a result (ANALYZED, or
    # INVALIDATED after analysis) is rejected here; the SEALED gate below then
    # governs never-resulted samples (COLLECTED / pre-analysis INVALIDATED).
    if find_result_for_sample(sample["id"]) is not None:
        raise_error(ERR_RESULT_ALREADY_EXISTS, "Sample already has a LabResult")
    # ---- Stage 6: state gates (sample first, then plan).
    if sample["status"] != "SEALED":
        raise_error(ERR_SAMPLE_INVALID_STATE, "Result entry requires a SEALED sample")
    # PRD section 3.5 gates intake on FIELD_COMPLETE, but the same section's
    # blank-contamination cascade (and section 3.3's LAB_COMPLETE -> APPROVED
    # regression with assessment voiding) is only reachable if a SEALED
    # FIELD_BLANK can still be resulted after the plan auto-advanced to
    # LAB_COMPLETE on its last PERSONAL analysis. LAB_COMPLETE plans can only
    # ever present un-resulted FIELD_BLANKs here (every PERSONAL is already
    # ANALYZED, and re-entry hits ERR_RESULT_ALREADY_EXISTS above), so
    # admitting LAB_COMPLETE changes nothing else.
    if plan["status"] not in ("FIELD_COMPLETE", "LAB_COMPLETE"):
        raise_error(ERR_PLAN_INVALID_STATE,
                    "Result entry requires the plan to be FIELD_COMPLETE")
    # ---- Stage 7: analyte coherence between batch and the plan's SEG.
    if batch["analyte_code"] != seg["analyte_code"]:
        raise_error(ERR_ANALYTE_MISMATCH,
                    "Batch analyte_code differs from the plan's SEG analyte_code")
    # ---- Stage 8: chain-of-custody SoD, then the calibration gate.
    if user_id == sample["collected_by_user_id"]:
        raise_error(ERR_SOD_CHAIN_OF_CUSTODY,
                    "Lab result enterer must differ from the sample collector")
    if sample["sample_type"] == "PERSONAL":
        cal = db.pump_calibrations[sample["pre_calibration_id"]]
        if cal["result"] != "VALID":
            raise_error(ERR_CALIBRATION_NOT_VALID,
                        "Sample calibration must be VALID before result entry")
    # ---- Stage 9: batch intake window, inclusive at both ends.
    from datetime import date as _date
    now_date = today()
    if not (_date.fromisoformat(batch["window_start_date"]) <= now_date
            <= _date.fromisoformat(batch["window_end_date"])):
        raise_error(ERR_BATCH_WINDOW_CLOSED,
                    "Current date outside the batch intake window")
    # ---- Stage 10: capacity, then contamination.
    if batch["intake_count"] >= batch["max_capacity"]:
        raise_error(ERR_BATCH_CAPACITY_FULL, "Batch intake_count reached max_capacity")
    if batch["contaminated"]:
        raise_error(ERR_BATCH_NOT_ACCEPTING, "Batch is contaminated; intake closed")

    # ---- Execute: create the result, analyze the sample, update counters.
    is_detect = mass_ug >= batch["lod_ug"]
    result = {
        "field_sample_id": sample["id"],
        "lab_batch_id": batch["id"],
        "mass_ug": mass_ug,
        "entered_by_user_id": user_id,
        "reported_at": now_ts(),
        "is_detect": is_detect,
        "is_quantifiable": mass_ug >= batch["loq_ug"],
    }
    stamp_new(result)
    db.lab_results[result["id"]] = result

    batch["intake_count"] += 1

    analyze_sample(sample, mass_ug, is_detect)
    recompute_plan_counts(plan)
    maybe_complete_lab(plan)

    # Blank-contamination cascade: a FIELD_BLANK at/above LOD contaminates the
    # batch and invalidates every sibling ANALYZED sample in it.
    if sample["sample_type"] == "FIELD_BLANK" and is_detect:
        run_contamination_cascade(batch, sample)
    touch(batch)
    return success_object(result_out(result), 201)


@bp.route("/ih/lab-results", methods=["GET"])
def list_results():
    require_auth(ALL_ROLES)
    return list_response(list(db.lab_results.values()), result_out, {
        "field_sample_id": request.args.get("field_sample_id"),
        "lab_batch_id": request.args.get("lab_batch_id"),
    })


@bp.route("/ih/lab-results/<rid>", methods=["GET"])
def get_result(rid):
    require_auth(ALL_ROLES)
    return success_object(result_out(get_or_404(db.lab_results, rid, "LabResult")))
