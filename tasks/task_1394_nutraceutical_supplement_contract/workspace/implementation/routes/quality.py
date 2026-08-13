"""Assay results and stability program (PRD sections 3.5, 3.7)."""
from flask import Blueprint

from db import store, new_entity, touch
from errors import (
    raise_error,
    ERR_BATCH_STATE,
    ERR_ASSAY_STATE,
    ERR_STUDY_STATE,
    ERR_CHAMBER_CAPACITY_EXCEEDED,
    ERR_SOD_VIOLATION,
)
from middleware import require_roles, ANY_ROLE
from response import ok
from services import (
    batch_mo,
    compute_pct_of_claim,
    formula_lines,
    mo_formula,
    pct_in_range,
)
from util import (
    PROTOCOLS,
    body,
    dec,
    invalid,
    is_int,
    last_day_of_month_after,
    not_found,
    num_out,
    paginate,
    parse_dt,
    req_enum,
    req_num,
    req_str,
    sorted_by_created,
)

bp = Blueprint("quality", __name__)


def _get_batch(batch_id):
    batch = store["batches"].get(batch_id)
    if batch is None:
        not_found()
    return batch


# ---------------------------------------------------------------------------
# Assay results (PRD 3.5)
# ---------------------------------------------------------------------------
@bp.post("/api/batches/<batch_id>/assay-results")
@require_roles("QAChemist")
def submit_assay(user_id, role, batch_id):
    batch = _get_batch(batch_id)
    if batch["production_status"] not in ("COMPLETED", "RECORD_REVIEWED") or (
        batch["quality_status"] not in ("PENDING_QC", "ASSAY_HOLD")
    ):
        raise_error(
            ERR_BATCH_STATE,
            "Assay submission requires completed production and quality PENDING_QC or ASSAY_HOLD",
        )
    data = body()
    assayed = req_num(data, "assayed_mg_per_unit")
    if not dec(assayed) > 0:
        invalid("'assayed_mg_per_unit' must be greater than zero")
    mo = batch_mo(batch)
    formula = mo_formula(mo) if mo else None
    claim_line = None
    if formula is not None:
        for line in formula_lines(formula["id"]):
            if line["is_label_claim_line"]:
                claim_line = line
                break
    if claim_line is None:
        # An approved formula always has exactly one label-claim line.
        raise_error(ERR_BATCH_STATE, "The ordered formula has no label-claim line")
    label_claim = claim_line["label_claim_mg_per_unit"]
    pct = compute_pct_of_claim(assayed, label_claim)
    assay = new_entity({
        "batch_id": batch_id,
        "assayed_mg_per_unit": assayed,
        "label_claim_mg_per_unit": label_claim,
        "pct_of_claim": num_out(pct),
        "submitted_by_id": user_id,
        "review_outcome": None,
        "reviewed_by_id": None,
        "status": "SUBMITTED",
    })
    store["assay_results"][assay["id"]] = assay
    if not pct_in_range(pct) and batch["quality_status"] == "PENDING_QC":
        batch["quality_status"] = "ASSAY_HOLD"
        touch(batch)
    return ok(assay, 201)


@bp.get("/api/batches/<batch_id>/assay-results")
@require_roles(*ANY_ROLE)
def list_assays(user_id, role, batch_id):
    _get_batch(batch_id)
    items = sorted_by_created(
        a for a in store["assay_results"].values() if a["batch_id"] == batch_id
    )
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.post("/api/assay-results/<assay_id>/review")
@require_roles("QAManager")
def review_assay(user_id, role, assay_id):
    assay = store["assay_results"].get(assay_id)
    if assay is None:
        not_found()
    if assay["status"] != "SUBMITTED":
        raise_error(ERR_ASSAY_STATE, "Assay result is not in SUBMITTED status")
    if user_id == assay["submitted_by_id"]:
        raise_error(
            ERR_SOD_VIOLATION,
            "The reviewing manager must differ from the submitting chemist",
        )
    data = body()
    review_outcome = req_enum(data, "review_outcome", ("ACCEPT", "REJECT"))
    assay["review_outcome"] = review_outcome
    assay["reviewed_by_id"] = user_id
    assay["status"] = "ACCEPTED" if review_outcome == "ACCEPT" else "REJECTED"
    touch(assay)
    if review_outcome == "ACCEPT" and pct_in_range(assay["pct_of_claim"]):
        batch = store["batches"].get(assay["batch_id"])
        if batch is not None and batch["quality_status"] in ("PENDING_QC", "ASSAY_HOLD"):
            batch["quality_status"] = "QC_READY"
            touch(batch)
    return ok(assay)


# ---------------------------------------------------------------------------
# Stability program (PRD 3.7)
# ---------------------------------------------------------------------------
@bp.post("/api/batches/<batch_id>/stability-studies")
@require_roles("QAChemist")
def enroll_study(user_id, role, batch_id):
    batch = _get_batch(batch_id)
    if batch["production_status"] not in ("COMPLETED", "RECORD_REVIEWED"):
        raise_error(
            ERR_BATCH_STATE,
            "Stability enrollment requires a production-completed batch",
        )
    for s in store["stability_studies"].values():
        if s["batch_id"] == batch_id and s["status"] == "ENROLLED":
            raise_error(ERR_STUDY_STATE, "The batch already has an ENROLLED study")
    data = body()
    chamber_id = req_str(data, "chamber_id")
    chamber = store["stability_chambers"].get(chamber_id)
    if chamber is None:
        not_found("chamber_id does not identify an existing stability chamber")
    if chamber["occupied_units"] + batch["theoretical_units"] > chamber["capacity_units"]:
        raise_error(
            ERR_CHAMBER_CAPACITY_EXCEEDED,
            "Chamber aggregate capacity would be exceeded",
        )
    protocol = req_enum(data, "protocol", PROTOCOLS)
    study = new_entity({
        "batch_id": batch_id,
        "chamber_id": chamber_id,
        "protocol": protocol,
        "pull_results": None,
        "supported_months": None,
        "assigned_expiry_date": None,
        "status": "ENROLLED",
    })
    store["stability_studies"][study["id"]] = study
    chamber["occupied_units"] += batch["theoretical_units"]
    touch(chamber)
    return ok(study, 201)


@bp.get("/api/batches/<batch_id>/stability-studies")
@require_roles(*ANY_ROLE)
def list_batch_studies(user_id, role, batch_id):
    _get_batch(batch_id)
    items = sorted_by_created(
        s for s in store["stability_studies"].values() if s["batch_id"] == batch_id
    )
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.post("/api/stability-studies/<study_id>/complete")
@require_roles("QAManager")
def complete_study(user_id, role, study_id):
    study = store["stability_studies"].get(study_id)
    if study is None:
        not_found()
    if study["status"] != "ENROLLED":
        raise_error(ERR_STUDY_STATE, "Only an ENROLLED study may be completed")
    data = body()
    pull_results = data.get("pull_results")
    if not isinstance(pull_results, list) or len(pull_results) == 0:
        invalid("'pull_results' must be a non-empty array")
    previous_month = 0
    for entry in pull_results:
        if not isinstance(entry, dict):
            invalid("pull_results entries must be objects")
        pull_month = entry.get("pull_month")
        passed = entry.get("passed")
        if not is_int(pull_month) or pull_month < 1:
            invalid("'pull_month' must be an integer of at least 1")
        if not isinstance(passed, bool):
            invalid("'passed' must be a boolean")
        if pull_month <= previous_month:
            invalid("'pull_month' values must be strictly ascending")
        previous_month = pull_month

    # supported_shelf_months: scan ascending, stop at the first failed pull.
    supported_months = 0
    for entry in pull_results:
        if entry["passed"]:
            supported_months = entry["pull_month"]
        else:
            break

    batch = store["batches"].get(study["batch_id"])
    mo = batch_mo(batch) if batch else None
    formula = mo_formula(mo) if mo else None
    shelf_life = formula["shelf_life_months"] if formula else 0
    effective_months = min(shelf_life, supported_months)
    completed_at = parse_dt(batch["completed_at"]) if batch and batch.get("completed_at") else None
    if completed_at is None:
        raise_error(ERR_BATCH_STATE, "The batch has no completion timestamp")
    assigned = last_day_of_month_after(completed_at.year, completed_at.month, effective_months)

    study["pull_results"] = [
        {"pull_month": e["pull_month"], "passed": e["passed"]} for e in pull_results
    ]
    study["supported_months"] = supported_months
    study["assigned_expiry_date"] = assigned
    study["status"] = "COMPLETED"
    touch(study)
    if batch is not None:
        batch["expiry_date"] = assigned
        touch(batch)
    chamber = store["stability_chambers"].get(study["chamber_id"])
    if chamber is not None:
        chamber["occupied_units"] -= batch["theoretical_units"] if batch else 0
        touch(chamber)
    return ok(study)
