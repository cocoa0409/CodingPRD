"""Sample routes: register (mint code + storage), read, list, dispose."""

from flask import Blueprint, request

from db import DB, new_id, LOCK, next_sample_seq, next_storage_bin
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE,
    ERR_WITNESS_RECORD_INCONSISTENT, raise_error,
)
from middleware import auth_required
from response import success_response, list_response, empty_204
from services.common import get_json_body, require_fields, parse_pagination, paginate
from services.serializers import serialize_sample
from services.time_util import now_iso, now_dt
from services.calculations import material_prefix
from services.state import touch

bp = Blueprint("samples", __name__)

VALID_CATEGORIES = {"CONCRETE", "STEEL_REBAR", "SOIL", "ASPHALT", "CEMENT"}


def _validate_handover(h):
    if not isinstance(h, dict):
        raise_error(ERR_VALIDATION, "handover_record must be an object")
    for k in ("delivered_by", "received_by", "handover_at"):
        if k not in h or not h[k]:
            raise_error(ERR_VALIDATION, f"handover_record.{k} required")


@bp.post("/samples")
@auth_required(["LabClerk"])
def create_sample():
    body = get_json_body()
    require_fields(body, ["client_id", "source_project", "material_category",
                          "specification", "witness_sampled", "handover_record"])
    client_id = body["client_id"]
    if client_id not in DB["clients"]:
        raise_error(ERR_NOT_FOUND, "Client not found")
    material = body["material_category"]
    if material not in VALID_CATEGORIES:
        raise_error(ERR_VALIDATION, "material_category invalid")
    if not isinstance(body["source_project"], str) or not body["source_project"]:
        raise_error(ERR_VALIDATION, "source_project required")
    if not isinstance(body["specification"], str) or not body["specification"]:
        raise_error(ERR_VALIDATION, "specification required")
    witness_sampled = body["witness_sampled"]
    if not isinstance(witness_sampled, bool):
        raise_error(ERR_VALIDATION, "witness_sampled must be boolean")
    witness_name = body.get("witness_name")
    if witness_sampled:
        if witness_name is None or witness_name == "":
            raise_error(ERR_WITNESS_RECORD_INCONSISTENT,
                        "witness_name required when witness_sampled is true")
    else:
        if witness_name is not None:
            raise_error(ERR_WITNESS_RECORD_INCONSISTENT,
                        "witness_name must be null when witness_sampled is false")
    _validate_handover(body["handover_record"])

    with LOCK:
        now = now_iso()
        yyyymmdd = now_dt().strftime("%Y%m%d")
        seq = next_sample_seq(material, yyyymmdd)
        sample_code = f"{material_prefix(material)}-{yyyymmdd}-{seq:04d}"
        nn = next_storage_bin(material)
        storage_location = f"BIN-{material}-{nn:02d}"
        row = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "client_id": client_id,
            "source_project": body["source_project"],
            "material_category": material,
            "specification": body["specification"],
            "witness_sampled": witness_sampled,
            "witness_name": witness_name,
            "sample_code": sample_code,
            "handover_record": body["handover_record"],
            "storage_location": storage_location,
            "status": "REGISTERED",
        }
        DB["samples"][row["id"]] = row
    return success_response(serialize_sample(row), 201)


@bp.get("/samples/<sid>")
@auth_required(["LabManager", "LabClerk", "Tester"])
def read_sample(sid):
    row = DB["samples"].get(sid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Sample not found")
    return success_response(serialize_sample(row), 200)


@bp.get("/samples")
@auth_required(["LabManager", "LabClerk"])
def list_samples():
    limit, offset = parse_pagination()
    rows = list(DB["samples"].values())
    cid = request.args.get("client_id")
    status = request.args.get("status")
    material = request.args.get("material_category")
    if cid:
        rows = [r for r in rows if r["client_id"] == cid]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if material:
        rows = [r for r in rows if r.get("material_category") == material]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return list_response([serialize_sample(r) for r in page], total, limit, offset)


@bp.delete("/samples/<sid>")
@auth_required(["LabClerk"])
def dispose_sample(sid):
    row = DB["samples"].get(sid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Sample not found")
    if row.get("status") != "TESTED":
        raise_error(ERR_INVALID_STATE, "Sample must be TESTED before disposal")
    # All reports must be ISSUED or ARCHIVED
    with LOCK:
        # Re-check
        row = DB["samples"].get(sid)
        if row is None:
            raise_error(ERR_NOT_FOUND, "Sample not found")
        if row.get("status") != "TESTED":
            raise_error(ERR_INVALID_STATE, "Sample must be TESTED before disposal")
        sample_tasks = [t for t in DB["tasks"].values() if t.get("sample_id") == sid]
        for task in sample_tasks:
            # If the task is COMPLETED, the report (if any) must be ISSUED/ARCHIVED
            task_reports = [r for r in DB["reports"].values() if r.get("task_id") == task["id"]]
            for r in task_reports:
                if r.get("status") not in ("ISSUED", "ARCHIVED"):
                    raise_error(ERR_INVALID_STATE,
                                "All reports must be ISSUED or ARCHIVED before sample disposal")
        row["status"] = "DISPOSED"
        touch(row)
    return empty_204()
