"""WastewaterBatch treatment and discharge control (PRD §3.9)."""

from decimal import Decimal

from flask import Blueprint

from core import (
    db, ApiError, auth, require_role, body_json, req_int, req_str, req_num,
    get_or_404, create_entity, touch, ser, ok, paginate, sorted_all,
    apply_filters, forbid, now,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_SOD, ERR_DISCHARGE_LIMITS,
    ERR_DISCHARGE_CAPACITY,
)

bp = Blueprint("wastewater", __name__)


@bp.post("/wastewater-batches")
def create_batch():
    uid, role = auth()
    require_role(role, {"TerminalOperator", "ContractorSupervisor"})
    b = body_json()
    terminal_id = req_str(b, "terminal_id")
    job_id = req_str(b, "job_id")
    volume = req_int(b, "volume_liters")
    get_or_404(db.terminals, terminal_id, "terminal")
    job = get_or_404(db.cleaning_jobs, job_id, "cleaning job")
    if role == "ContractorSupervisor" and job["contractor_id"] != uid:
        forbid("acting ContractorSupervisor does not own this job")
    if volume <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "volume_liters must be > 0")
    batch = create_entity({
        "terminal_id": terminal_id,
        "job_id": job_id,
        "volume_liters": volume,
        "ph": None,
        "tph_mg_l": None,
        "lab_user_id": None,
        "discharge_day": None,
        "status": "COLLECTED",
    })
    db.wastewater_batches[batch["id"]] = batch
    return ok(ser(batch), 201)


@bp.get("/wastewater-batches/<batchId>")
def get_batch(batchId):
    auth()
    return ok(ser(get_or_404(db.wastewater_batches, batchId, "wastewater batch")), 200)


@bp.get("/wastewater-batches")
def list_batches():
    auth()
    items = apply_filters(sorted_all(db.wastewater_batches), [
        ("terminal_id", "terminal_id"),
        ("job_id", "job_id"),
        ("status", "status"),
        ("discharge_day", "discharge_day"),
    ])
    page, pg = paginate(items)
    return ok([ser(e) for e in page], 200, pg)


@bp.post("/wastewater-batches/<batchId>/submit-lab")
def submit_lab(batchId):
    uid, role = auth()
    require_role(role, {"LabTechnician"})
    batch = get_or_404(db.wastewater_batches, batchId, "wastewater batch")
    b = body_json()
    ph = req_num(b, "ph")
    tph = req_num(b, "tph_mg_l")
    if not (0.0 <= ph <= 14.0) or tph < 0.0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "ph must be within [0, 14] and tph_mg_l must be >= 0")
    if batch["status"] != "COLLECTED":
        raise ApiError(ERR_INVALID_STATE, 409, "batch is not COLLECTED")
    batch["ph"] = ph
    batch["tph_mg_l"] = tph
    batch["lab_user_id"] = uid
    batch["status"] = "LAB_TESTED"
    touch(batch)
    return ok(ser(batch), 200)


@bp.post("/wastewater-batches/<batchId>/authorize")
def authorize_batch(batchId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    batch = get_or_404(db.wastewater_batches, batchId, "wastewater batch")
    if batch["status"] != "LAB_TESTED":
        raise ApiError(ERR_INVALID_STATE, 409, "batch is not LAB_TESTED")
    # PRD §3.9 normative order: segregation of duties -> discharge envelope ->
    # daily capacity.
    if uid == batch["lab_user_id"]:
        raise ApiError(ERR_SOD, 403,
                       "authorizer must differ from the lab technician")
    ph = Decimal(str(batch["ph"]))
    tph = Decimal(str(batch["tph_mg_l"]))
    if not (Decimal("6.0") <= ph <= Decimal("9.0")) or tph > Decimal("15.0"):
        raise ApiError(ERR_DISCHARGE_LIMITS, 422,
                       "batch is outside the discharge envelope")
    terminal = db.terminals[batch["terminal_id"]]
    day = now().strftime("%Y-%m-%d")  # UTC calendar day from the logical clock
    allocated = sum(
        o["volume_liters"] for o in db.wastewater_batches.values()
        if o["terminal_id"] == batch["terminal_id"]
        and o["status"] in ("AUTHORIZED", "DISCHARGED")
        and o["discharge_day"] == day)
    # Inclusive boundary: landing exactly on capacity is allowed.
    if allocated + batch["volume_liters"] > terminal["wastewater_daily_capacity_liters"]:
        raise ApiError(ERR_DISCHARGE_CAPACITY, 409,
                       "daily discharge capacity would be exceeded")
    batch["discharge_day"] = day
    batch["status"] = "AUTHORIZED"
    touch(batch)
    return ok(ser(batch), 200)


@bp.post("/wastewater-batches/<batchId>/discharge")
def discharge_batch(batchId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    batch = get_or_404(db.wastewater_batches, batchId, "wastewater batch")
    if batch["status"] != "AUTHORIZED":
        raise ApiError(ERR_INVALID_STATE, 409, "batch is not AUTHORIZED")
    batch["status"] = "DISCHARGED"
    touch(batch)
    return ok(ser(batch), 200)


@bp.post("/wastewater-batches/<batchId>/reject")
def reject_batch(batchId):
    uid, role = auth()
    require_role(role, {"EHSOfficer"})
    batch = get_or_404(db.wastewater_batches, batchId, "wastewater batch")
    if batch["status"] != "LAB_TESTED":
        raise ApiError(ERR_INVALID_STATE, 409, "batch is not LAB_TESTED")
    batch["status"] = "REJECTED"
    touch(batch)
    return ok(ser(batch), 200)


@bp.post("/wastewater-batches/<batchId>/void-authorization")
def void_authorization(batchId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    batch = get_or_404(db.wastewater_batches, batchId, "wastewater batch")
    if batch["status"] != "AUTHORIZED":
        raise ApiError(ERR_INVALID_STATE, 409, "batch is not AUTHORIZED")
    batch["status"] = "COLLECTED"
    batch["discharge_day"] = None  # releases the day's allocated liters
    touch(batch)
    return ok(ser(batch), 200)


@bp.post("/wastewater-batches/<batchId>/return-to-storage")
def return_to_storage(batchId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    batch = get_or_404(db.wastewater_batches, batchId, "wastewater batch")
    if batch["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE, 409, "batch is not REJECTED")
    batch["status"] = "COLLECTED"
    touch(batch)
    return ok(ser(batch), 200)
