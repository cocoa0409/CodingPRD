"""SDS endpoints."""
from flask import Blueprint, request

import db
import errors
from middleware import require_role
from response import success_object, success_list
from services.common import (
    new_id,
    now_iso,
    serialize_sds,
    sort_by_created_at,
)
from services.calculations import compute_authoring_consistency_flag, GHS_CLASSES

bp = Blueprint("sds", __name__)

SIGNAL_WORDS = {"DANGER", "WARNING", "NONE"}


def _customer_or_404(cid):
    c = db.customers.get(cid)
    if c is None:
        raise errors.not_found("customer not found")
    return c


def _batch_or_404(customer_id, batch_id):
    b = db.batch_jobs.get(batch_id)
    if b is None or b["customer_id"] != customer_id:
        raise errors.not_found("batch job not found")
    return b


def _sds_or_404(batch_id, sds_id):
    s = db.sds_documents.get(sds_id)
    if s is None or s["batch_job_id"] != batch_id:
        raise errors.not_found("sds not found")
    return s


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/sds", methods=["POST"])
def author_sds(id, batchJobId):
    require_role({"SDSAuthor"})
    _customer_or_404(id)
    batch = _batch_or_404(id, batchJobId)
    body = request.get_json(silent=True) or {}
    ghs_classification = body.get("ghs_classification")
    if ghs_classification not in GHS_CLASSES:
        raise errors.invalid_request("ghs_classification invalid")
    signal_word = body.get("signal_word")
    if signal_word not in SIGNAL_WORDS:
        raise errors.invalid_request("signal_word invalid")
    hazard_statements = body.get("hazard_statements")
    if not isinstance(hazard_statements, list):
        raise errors.invalid_request("hazard_statements must be list")

    # Find existing living SDS for this batch (DRAFT or ISSUED)
    existing_living = None
    existing_issued = None
    for s in db.sds_documents.values():
        if s["batch_job_id"] == batch["id"]:
            if s["status"] == "ISSUED":
                existing_issued = s
            elif s["status"] == "DRAFT":
                existing_living = s

    # Compute revision per PRD §3.7: only when existing document is ISSUED does
    # the new one increment; otherwise new draft starts at 1.
    if existing_issued is not None:
        new_revision = existing_issued["authoring_revision"] + 1
    else:
        new_revision = 1

    # Cascade ISSUED -> SUPERSEDED
    if existing_issued is not None:
        existing_issued["status"] = "SUPERSEDED"
        existing_issued["version"] += 1
        existing_issued["updated_at"] = now_iso()

    flag = compute_authoring_consistency_flag(
        ghs_classification,
        signal_word,
        hazard_statements,
        batch["highest_component_ghs_snapshot"],
    )

    now = now_iso()
    sid = new_id()
    doc = {
        "id": sid,
        "batch_job_id": batch["id"],
        "authoring_revision": new_revision,
        "ghs_classification": ghs_classification,
        "signal_word": signal_word,
        "hazard_statements": list(hazard_statements),
        "authoring_consistency_flag": flag,
        "status": "DRAFT",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.sds_documents[sid] = doc
    return success_object(serialize_sds(doc), status=201)


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/sds", methods=["GET"])
def list_sds(id, batchJobId):
    require_role({"Any"})
    _customer_or_404(id)
    _batch_or_404(id, batchJobId)
    rows = [s for s in db.sds_documents.values() if s["batch_job_id"] == batchJobId]
    rows = sort_by_created_at(rows)
    # PRD says list SDS, no pagination mentioned but scaffold list endpoints
    # accept pagination. Use pagination params for consistency.
    from services.common import pagination_params, paginate
    limit, offset = pagination_params()
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_sds(s) for s in slice_], limit, offset, total)


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/sds/<sdsId>/issue", methods=["POST"])
def issue_sds(id, batchJobId, sdsId):
    require_role({"SDSAuthor"})
    _customer_or_404(id)
    _batch_or_404(id, batchJobId)
    doc = _sds_or_404(batchJobId, sdsId)
    if doc["status"] != "DRAFT":
        raise errors.invalid_state("SDS not DRAFT")
    if not doc["authoring_consistency_flag"]:
        raise errors.ApiError(errors.ERR_SDS_INCONSISTENT, 422, "SDS inconsistent")
    doc["status"] = "ISSUED"
    doc["version"] += 1
    doc["updated_at"] = now_iso()
    return success_object(serialize_sds(doc))
