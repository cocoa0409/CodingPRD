"""WoodBatch endpoints (PRD §3.3)."""
from flask import Blueprint

from db import STORE, new_id, now_iso, logical_now, touch
from errors import ApiError, ERR_DUPLICATE, ERR_INVALID_STATE, ERR_BATCH_NOT_ACTIVE, not_found
from middleware import (ALL_OPERATIONAL, require_roles, body, req_str, req_enum,
                        req_int, req_dt, paginate, enum_filter)
from response import success
from services.state import (get, ser_batch, refresh_batch, batch_eval_expiry,
                            batch_suspend_cascade, batch_reinstate_cascade)

bp = Blueprint("wood", __name__)

TREATMENTS = {"HT", "KD_HT"}
BATCH_STATUSES = {"ACTIVE", "SUSPENDED", "DEPLETED", "EXPIRED"}
LIST_ROLES = ["SalesRep", "CratingDesigner", "ShopForeman",
              "ComplianceOfficer", "LogisticsCoordinator", "ClaimsAdjuster"]


def _get_batch_or_404(bid):
    b = get("batches", bid)
    if not b:
        raise not_found("WoodBatch not found")
    return b


@bp.post("/crating/wood-batches")
def create_batch():
    require_roles(["ComplianceOfficer"])
    d = body()
    cert = req_str(d, "ht_certificate_no")
    treatment = req_enum(d, "treatment_type", TREATMENTS)
    expires_at = req_dt(d, "expires_at")
    received = req_int(d, "received_board_feet", minimum=1)
    stamps = req_int(d, "stamps_acquired", minimum=0)
    for b in STORE["batches"].values():
        if b["ht_certificate_no"] == cert:
            raise ApiError(ERR_DUPLICATE, "ht_certificate_no already exists", 409)
    rec = {
        "id": new_id(), "ht_certificate_no": cert, "treatment_type": treatment,
        "expires_at": expires_at, "received_board_feet": received,
        "stamps_acquired": stamps, "reserved_board_feet": 0,
        "consumed_board_feet": 0, "scrapped_board_feet": 0,
        "stamps_applied": 0, "stamps_voided": 0, "status": "ACTIVE",
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
    }
    STORE["batches"][rec["id"]] = rec
    # PRD §3.3: "A fresh batch is ACTIVE" — expiry is lazy and applies to
    # subsequent reads/uses, not to the creation response.
    return success(ser_batch(rec, eval_expiry=False), status=201)


@bp.get("/crating/wood-batches/<bid>")
def get_batch(bid):
    require_roles(ALL_OPERATIONAL)
    return success(ser_batch(_get_batch_or_404(bid)))


@bp.get("/crating/wood-batches")
def list_batches():
    require_roles(LIST_ROLES)
    status = enum_filter("status", BATCH_STATUSES)
    recs = []
    for b in STORE["batches"].values():
        batch_eval_expiry(b)  # lazy expiry on read
        if status is None or b["status"] == status:
            recs.append(b)
    recs.sort(key=lambda b: b["created_at"])
    page, meta = paginate(recs)
    return success([ser_batch(b) for b in page], pagination=meta)


@bp.post("/crating/wood-batches/<bid>/suspend")
def suspend_batch(bid):
    require_roles(["ComplianceOfficer"])
    b = _get_batch_or_404(bid)
    batch_eval_expiry(b)
    if b["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Only an ACTIVE batch can be suspended", 409)
    b["status"] = "SUSPENDED"
    touch(b)
    batch_suspend_cascade(b)
    return success(ser_batch(b))


@bp.post("/crating/wood-batches/<bid>/reinstate")
def reinstate_batch(bid):
    require_roles(["ComplianceOfficer"])
    b = _get_batch_or_404(bid)
    batch_eval_expiry(b)
    if b["status"] == "EXPIRED" or b["expires_at"] < logical_now():
        raise ApiError(ERR_BATCH_NOT_ACTIVE, "Batch certificate has expired", 409)
    if b["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "Only a SUSPENDED batch can be reinstated", 409)
    b["status"] = "ACTIVE"
    touch(b)
    batch_reinstate_cascade(b)
    refresh_batch(b)  # re-derive DEPLETED if still dry
    return success(ser_batch(b))
