"""Sample pipeline: extraction, QC failure and the requeue cycle (PRD §3.4)."""
from flask import Blueprint, request

import calc
import db
import services as S
from auth import endpoint, require_owner
from errors import ApiError
from response import ok, paginate
from routes.common import body, require_number

bp = Blueprint("samples", __name__)


@bp.get("/dna/samples/<sample_id>")
@endpoint(["LabTechnician", "PlatformAdmin", "Customer"])
def read_sample(sample_id):
    sample = S.get("samples", sample_id)
    owner = S.owner_of_sample(sample)
    if owner is not None:
        require_owner(owner)
    return ok(S.sample_json(sample))


@bp.get("/dna/samples")
@endpoint(["LabTechnician", "PlatformAdmin", "Customer"])
def list_samples():
    records = S.all_of("samples")
    kit_id = request.args.get("kit_id")
    batch_id = request.args.get("batch_id")
    status = request.args.get("status")
    if kit_id:
        records = [r for r in records if r["kit_id"] == kit_id]
    if batch_id:
        records = [r for r in records if r["batch_id"] == batch_id]
    if status:
        records = [r for r in records if r["status"] == status]
    return paginate(records, S.sample_json)


@bp.post("/dna/samples/<sample_id>/extract")
@endpoint(["LabTechnician"])
def extract(sample_id):
    sample = S.get("samples", sample_id)

    payload = body()
    S.require_fields(payload, ["dna_yield_ng"])
    yield_ng = require_number(payload["dna_yield_ng"], "dna_yield_ng", minimum=0)

    if sample["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE")

    sample["dna_yield_ng"] = yield_ng
    sample["extraction_attempts"] = sample["extraction_attempts"] + 1

    if yield_ng >= calc.MIN_DNA_YIELD_NG:
        sample["status"] = "EXTRACTED"
        db.touch(sample)
    elif sample["extraction_attempts"] < calc.MAX_EXTRACTION_ATTEMPTS:
        sample["status"] = "QC_FAILED"
        db.touch(sample)
    else:
        sample["status"] = "FAILED_TERMINAL"
        db.touch(sample)
        S.sample_terminal_failure_cascade(sample)

    return ok(S.sample_json(sample))


@bp.post("/dna/samples/<sample_id>/requeue")
@endpoint(["LabTechnician"])
def requeue(sample_id):
    sample = S.get("samples", sample_id)

    if sample["status"] != "QC_FAILED":
        raise ApiError("ERR_INVALID_STATE")
    if sample["extraction_attempts"] >= calc.MAX_EXTRACTION_ATTEMPTS:
        raise ApiError("ERR_EXTRACTION_ATTEMPTS_EXHAUSTED")

    # PRD §3.4: requeue clears batch_id and call_rate. Nothing else is touched.
    sample["status"] = "RECEIVED"
    sample["batch_id"] = None
    sample["call_rate"] = None
    db.touch(sample)

    return ok(S.sample_json(sample))
