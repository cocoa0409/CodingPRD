"""Quality samples and lab results with dry-matter assay adjustment (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint, request

from db import STORE, make_record, bump, clock_now
from envelope import success
from errors import ApiError
from middleware import authenticate, authorize
from services import ser_sample, sorted_items, sample_fail_cascade, rhu, PCT2
from validation import get_body, req_str, req_enum, req_num, opt_dt, paginate

bp = Blueprint("samples", __name__)

READ_ROLES = {"MillManager", "QualityTech"}


def _get_sample(sid):
    s = STORE["samples"].get(sid)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Sample {sid} not found")
    return s


@bp.post("/api/samples")
def create_sample():
    uid, role = authenticate()
    data = get_body()
    batch_id = req_str(data, "batch_id")
    sample_type = req_enum(data, "sample_type", ("COMPOSITE", "RETAIN"))
    retain_expiry = opt_dt(data, "retain_expiry_date")
    authorize(role, uid, {"QualityTech"})
    batch = STORE["batches"].get(batch_id)
    if batch is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Batch {batch_id} not found")
    if batch["status"] not in ("MIXED", "HOLD"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Samples collect only on MIXED or HOLD batches")
    if sample_type == "RETAIN":
        if retain_expiry is None or not retain_expiry > clock_now():
            raise ApiError("ERR_RETAIN_EXPIRY_INVALID", 422,
                           "RETAIN samples require a retain_expiry_date after the current clock")
    else:
        retain_expiry = None  # a COMPOSITE sample carries none
    rec = make_record()
    rec.update(batch_id=batch_id, sample_type=sample_type,
               retain_expiry_date=retain_expiry, protein_pct_actual=None,
               crude_fiber_pct_actual=None, moisture_pct=None,
               protein_dry_matter=None, fiber_dry_matter=None,
               result="PENDING", result_by_employee_id=None)
    STORE["samples"][rec["id"]] = rec
    return success(ser_sample(rec), 201)


@bp.get("/api/samples")
def list_samples():
    uid, role = authenticate()
    authorize(role, uid, READ_ROLES)
    items = sorted_items(STORE["samples"])
    batch_id = request.args.get("batch_id")
    sample_type = request.args.get("sample_type")
    result = request.args.get("result")
    if batch_id is not None:
        items = [s for s in items if s["batch_id"] == batch_id]
    if sample_type is not None:
        items = [s for s in items if s["sample_type"] == sample_type]
    if result is not None:
        items = [s for s in items if s["result"] == result]
    page, meta = paginate(items)
    return success([ser_sample(s) for s in page], 200, meta)


@bp.get("/api/samples/<sid>")
def get_sample(sid):
    uid, role = authenticate()
    authorize(role, uid, READ_ROLES)
    return success(ser_sample(_get_sample(sid)), 200)


@bp.post("/api/samples/<sid>/result")
def result_sample(sid):
    uid, role = authenticate()
    data = get_body()
    protein = req_num(data, "protein_pct_actual")
    fiber = req_num(data, "crude_fiber_pct_actual")
    moisture = req_num(data, "moisture_pct", ge=Decimal("0"), lt=Decimal("100"))
    authorize(role, uid, {"QualityTech"})
    s = _get_sample(sid)
    if s["result"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PENDING sample can receive a result")
    batch = STORE["batches"][s["batch_id"]]
    order = STORE["orders"][batch["order_id"]]
    # Dry-matter correction gates release; the as-fed figures are context only.
    factor = Decimal("1") - moisture / Decimal("100")
    protein_dm = rhu(protein / factor, PCT2)
    fiber_dm = rhu(fiber / factor, PCT2)
    passed = (protein_dm >= order["pinned_min_protein_pct"]
              and fiber_dm <= order["pinned_max_fiber_pct"])
    s["protein_pct_actual"] = protein
    s["crude_fiber_pct_actual"] = fiber
    s["moisture_pct"] = moisture
    s["protein_dry_matter"] = protein_dm
    s["fiber_dry_matter"] = fiber_dm
    s["result"] = "PASS" if passed else "FAIL"
    s["result_by_employee_id"] = uid
    bump(s)
    if not passed:
        sample_fail_cascade(batch)
    return success(ser_sample(s), 200)
