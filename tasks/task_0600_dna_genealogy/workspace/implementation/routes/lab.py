"""Lab instruments, genotyping batches and the run lifecycle (PRD §3.5)."""
from flask import Blueprint, request

import calc
import db
import services as S
from auth import endpoint
from errors import ApiError
from response import ok, paginate
from routes.common import body, require_number, require_string

bp = Blueprint("lab", __name__)

CHIP_VERSIONS = ("V4", "V5")
INSTRUMENT_STATUSES = ("ONLINE", "MAINTENANCE")
BLOCKING_BATCH_STATUSES = ("OPEN", "RUNNING", "FINALIZED")


# ------------------------------------------------------------ instruments ---
@bp.post("/dna/lab-instruments")
@endpoint(["PlatformAdmin"])
def create_instrument():
    payload = body()
    S.require_fields(payload, ["name", "chip_version"])
    name = require_string(payload["name"], "name")
    S.require_enum(payload["chip_version"], CHIP_VERSIONS, "chip_version")
    status = payload.get("status", "ONLINE")
    S.require_enum(status, INSTRUMENT_STATUSES, "status")

    instrument = db.new_record(
        {"name": name, "chip_version": payload["chip_version"], "status": status}
    )
    db.db.instruments[instrument["id"]] = instrument
    return ok(S.instrument_json(instrument), 201)


@bp.get("/dna/lab-instruments/<instrument_id>")
@endpoint(["PlatformAdmin", "LabTechnician"])
def read_instrument(instrument_id):
    return ok(S.instrument_json(S.get("instruments", instrument_id)))


# ---------------------------------------------------------------- batches ---
def _members(batch):
    return db.by_creation(
        [s for s in db.db.samples.values() if s["batch_id"] == batch["id"]]
    )


@bp.post("/dna/lab-batches")
@endpoint(["LabTechnician"])
def create_batch():
    payload = body()
    S.require_fields(payload, ["instrument_id", "run_start_at", "run_end_at"])

    instrument = S.get("instruments", payload["instrument_id"])

    raw_ids = payload.get("sample_ids", [])
    if not isinstance(raw_ids, list):
        raise ApiError("ERR_INVALID_REQUEST", "sample_ids must be an array.")
    samples = [S.get("samples", sid) for sid in raw_ids]

    run_start_at = db.parse_dt(payload["run_start_at"])
    run_end_at = db.parse_dt(payload["run_end_at"])
    if run_start_at is None or run_end_at is None:
        raise ApiError("ERR_INVALID_REQUEST", "run_start_at / run_end_at must be ISO 8601.")

    # Business rules, in the precedence order of PRD §2.6.
    for sample in samples:
        if sample["status"] != "EXTRACTED":
            raise ApiError("ERR_SAMPLE_NOT_READY")
        kit = db.db.kits.get(sample["kit_id"])
        if not kit or kit["chip_version"] != instrument["chip_version"]:
            raise ApiError("ERR_SAMPLE_NOT_READY")

    if instrument["status"] != "ONLINE":
        raise ApiError("ERR_INSTRUMENT_OFFLINE")

    if run_end_at <= run_start_at:
        raise ApiError("ERR_BATCH_WINDOW_OVERLAP", "run_end_at must be after run_start_at.")
    for other in db.db.batches.values():
        if other["instrument_id"] != instrument["id"]:
            continue
        if other["status"] not in BLOCKING_BATCH_STATUSES:
            continue
        # Half-open [start, end): back-to-back windows do not conflict.
        if run_start_at < other["run_end_at"] and other["run_start_at"] < run_end_at:
            raise ApiError("ERR_BATCH_WINDOW_OVERLAP")

    batch = db.new_record(
        {
            "instrument_id": instrument["id"],
            "run_start_at": run_start_at,
            "run_end_at": run_end_at,
            "status": "OPEN",
            "member_count": 0,
            "pass_rate": None,
        }
    )
    db.db.batches[batch["id"]] = batch

    for sample in samples:
        sample["status"] = "QUEUED"
        sample["batch_id"] = batch["id"]
        db.touch(sample)
        batch["member_count"] = batch["member_count"] + 1

    return ok(S.batch_json(batch), 201)


@bp.get("/dna/lab-batches/<batch_id>")
@endpoint(["LabTechnician", "PlatformAdmin"])
def read_batch(batch_id):
    return ok(S.batch_json(S.get("batches", batch_id)))


@bp.get("/dna/lab-batches")
@endpoint(["LabTechnician", "PlatformAdmin"])
def list_batches():
    records = S.all_of("batches")
    instrument_id = request.args.get("instrument_id")
    status = request.args.get("status")
    if instrument_id:
        records = [r for r in records if r["instrument_id"] == instrument_id]
    if status:
        records = [r for r in records if r["status"] == status]
    return paginate(records, S.batch_json)


@bp.post("/dna/lab-batches/<batch_id>/start")
@endpoint(["LabTechnician"])
def start_batch(batch_id):
    batch = S.get("batches", batch_id)

    if batch["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    if batch["member_count"] < 1:
        raise ApiError("ERR_EMPTY_BATCH")

    instrument = db.db.instruments.get(batch["instrument_id"])
    if not instrument or instrument["status"] != "ONLINE":
        raise ApiError("ERR_INSTRUMENT_OFFLINE")

    batch["status"] = "RUNNING"
    db.touch(batch)
    for sample in _members(batch):
        if sample["status"] == "QUEUED":
            sample["status"] = "GENOTYPING"
            db.touch(sample)

    return ok(S.batch_json(batch))


@bp.post("/dna/lab-batches/<batch_id>/finalize")
@endpoint(["LabTechnician"])
def finalize_batch(batch_id):
    batch = S.get("batches", batch_id)

    payload = body()
    S.require_fields(payload, ["sample_results"])
    results = payload["sample_results"]
    if not isinstance(results, list):
        raise ApiError("ERR_INVALID_REQUEST", "sample_results must be an array.")

    parsed = []
    for entry in results:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Each sample_results entry must be an object.")
        S.require_fields(entry, ["sample_id", "call_rate"])
        sample = S.get("samples", entry["sample_id"])
        call_rate = require_number(entry["call_rate"], "call_rate", minimum=0, maximum=1)
        scores = entry.get("population_scores", [])
        markers = entry.get("genotype_markers", [])
        if not isinstance(scores, list) or not isinstance(markers, list):
            raise ApiError(
                "ERR_INVALID_REQUEST", "population_scores and genotype_markers must be arrays."
            )
        parsed.append((sample, call_rate, scores, markers))

    members = _members(batch)
    member_ids = [m["id"] for m in members]
    result_ids = [s["id"] for s, _, _, _ in parsed]
    if sorted(result_ids) != sorted(member_ids) or len(set(result_ids)) != len(result_ids):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "sample_results must contain exactly one entry per member sample.",
        )

    if batch["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE")

    for sample, call_rate, scores, markers in parsed:
        sample["call_rate"] = call_rate
        if call_rate >= calc.MIN_CALL_RATE:
            sample["status"] = "GENOTYPED"
            sample["population_scores"] = scores
            sample["genotype_markers"] = sorted(int(m) for m in markers)
            db.touch(sample)
            S.lab_batch_finalize_cascade(sample)
        else:
            sample["extraction_attempts"] = sample["extraction_attempts"] + 1
            if sample["extraction_attempts"] < calc.MAX_EXTRACTION_ATTEMPTS:
                sample["status"] = "QC_FAILED"
                db.touch(sample)
            else:
                sample["status"] = "FAILED_TERMINAL"
                db.touch(sample)
                S.sample_terminal_failure_cascade(sample)

    batch["status"] = "FINALIZED"
    batch["pass_rate"] = calc.lab_batch_pass_rate([cr for _, cr, _, _ in parsed])
    db.touch(batch)
    return ok(S.batch_json(batch))


@bp.post("/dna/lab-batches/<batch_id>/abort")
@endpoint(["LabTechnician"])
def abort_batch(batch_id):
    batch = S.get("batches", batch_id)

    if batch["status"] not in ("OPEN", "RUNNING"):
        raise ApiError("ERR_INVALID_STATE")

    for sample in _members(batch):
        if sample["status"] in ("QUEUED", "GENOTYPING"):
            sample["status"] = "EXTRACTED"
        sample["batch_id"] = None
        db.touch(sample)

    batch["status"] = "ABORTED"
    batch["member_count"] = 0
    db.touch(batch)
    return ok(S.batch_json(batch))
