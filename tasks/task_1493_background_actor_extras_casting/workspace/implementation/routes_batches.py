"""PayrollBatch endpoints: assembly (OCC), submission, acknowledgment (SoD)."""
from flask import Blueprint, request

from db import STORE, logical_now
from domain import _base, batch_vouchers, ser_batch, touch
from errors import (
    ApiError,
    ERR_BATCH_EMPTY,
    ERR_BATCH_INVALID_STATE,
    ERR_PAYROLL_BATCH_NOT_FOUND,
    ERR_PRODUCTION_NOT_ACTIVE,
    ERR_SOD_SELF_ACKNOWLEDGE,
    ERR_STALE_BATCH_VERSION,
    ERR_VALIDATION,
    ERR_VOUCHER_NOT_FOUND,
    ERR_VOUCHER_NOT_SUBMITTABLE,
)
from middleware import ALL_ROLES, auth, body, req_str
from response import ok_list, ok_obj, paginate
from routes_productions import get_production

bp = Blueprint("payroll_batches", __name__)


def get_batch(bid):
    b = STORE.payroll_batches.get(bid)
    if b is None:
        raise ApiError(ERR_PAYROLL_BATCH_NOT_FOUND, 404, "Payroll batch not found")
    return b


def _production_for_voucher(voucher):
    booking = STORE.bookings[voucher["booking_id"]]
    call = STORE.casting_calls[booking["casting_call_id"]]
    return call["production_id"]


def _check_payroll_phase(batch):
    production = get_production(batch["production_id"])
    if production["status"] not in ("ACTIVE", "WRAPPED"):
        raise ApiError(
            ERR_PRODUCTION_NOT_ACTIVE,
            409,
            "Payroll operations require the production ACTIVE or WRAPPED",
        )
    return production


@bp.post("/central-casting/payroll-batches")
def create_batch():
    auth(["PayrollCoordinator"])
    data = body()
    production_id = req_str(data, "production_id")
    production = get_production(production_id)
    period_label = req_str(data, "period_label")
    if production["status"] not in ("ACTIVE", "WRAPPED"):
        raise ApiError(
            ERR_PRODUCTION_NOT_ACTIVE,
            409,
            "Batch creation requires the production ACTIVE or WRAPPED",
        )
    b = _base()
    b.update(
        {
            "production_id": production_id,
            "period_label": period_label,
            "status": "OPEN",
            "submitted_by_user_id": None,
            "acknowledged_by_user_id": None,
            "submitted_at": None,
        }
    )
    STORE.payroll_batches[b["id"]] = b
    return ok_obj(ser_batch(b), code=201)


@bp.get("/central-casting/payroll-batches")
def list_batches():
    auth(ALL_ROLES)
    rows = sorted(STORE.payroll_batches.values(), key=lambda b: b["_seq"])
    production_id = request.args.get("production_id")
    status = request.args.get("status")
    if production_id is not None:
        rows = [b for b in rows if b["production_id"] == production_id]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_batch(b) for b in page], total, limit, offset)


@bp.get("/central-casting/payroll-batches/<bid>")
def get_batch_route(bid):
    auth(ALL_ROLES)
    return ok_obj(ser_batch(get_batch(bid)))


@bp.post("/central-casting/payroll-batches/<bid>/items")
def add_item(bid):
    auth(["PayrollCoordinator"])
    data = body()
    batch = get_batch(bid)
    voucher_id = req_str(data, "voucher_id")
    voucher = STORE.vouchers.get(voucher_id)
    if voucher is None:
        raise ApiError(ERR_VOUCHER_NOT_FOUND, 404, "Voucher not found")
    expected = data.get("expected_batch_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_VALIDATION, 400, "expected_batch_version is required")
    _check_payroll_phase(batch)
    if batch["status"] not in ("OPEN", "PARTIALLY_REJECTED"):
        raise ApiError(
            ERR_BATCH_INVALID_STATE, 409, "Items may be added only to an OPEN or PARTIALLY_REJECTED batch"
        )
    if expected != batch["version"]:
        raise ApiError(
            ERR_STALE_BATCH_VERSION,
            412,
            "expected_batch_version does not match the batch's current version",
        )
    if (
        voucher["status"] != "ISSUED"
        or voucher.get("payroll_batch_id") is not None
        or _production_for_voucher(voucher) != batch["production_id"]
    ):
        raise ApiError(
            ERR_VOUCHER_NOT_SUBMITTABLE,
            409,
            "Voucher must be ISSUED, unbatched, and belong to the batch's production",
        )
    voucher["payroll_batch_id"] = batch["id"]
    touch(voucher)
    if batch["status"] == "PARTIALLY_REJECTED":
        batch["status"] = "OPEN"  # resubmission cycle: adding reopens for editing
    touch(batch)
    production = get_production(batch["production_id"])
    touch(production)  # payroll exposure recomputed
    return ok_obj(ser_batch(batch))


@bp.post("/central-casting/payroll-batches/<bid>/remove-item")
def remove_item(bid):
    auth(["PayrollCoordinator"])
    data = body()
    batch = get_batch(bid)
    voucher_id = req_str(data, "voucher_id")
    voucher = STORE.vouchers.get(voucher_id)
    if voucher is None:
        raise ApiError(ERR_VOUCHER_NOT_FOUND, 404, "Voucher not found")
    _check_payroll_phase(batch)
    if batch["status"] not in ("OPEN", "PARTIALLY_REJECTED"):
        raise ApiError(
            ERR_BATCH_INVALID_STATE, 409, "Items may be removed only from an OPEN batch"
        )
    if voucher.get("payroll_batch_id") != batch["id"]:
        raise ApiError(ERR_VOUCHER_NOT_SUBMITTABLE, 409, "Voucher is not a member of this batch")
    voucher["payroll_batch_id"] = None
    touch(voucher)
    touch(batch)
    production = get_production(batch["production_id"])
    touch(production)
    return ok_obj(ser_batch(batch))


@bp.post("/central-casting/payroll-batches/<bid>/submit")
def submit_batch(bid):
    user_id, _ = auth(["PayrollCoordinator"])
    batch = get_batch(bid)
    _check_payroll_phase(batch)
    if batch["status"] not in ("OPEN", "PARTIALLY_REJECTED"):
        raise ApiError(ERR_BATCH_INVALID_STATE, 409, "Only OPEN or PARTIALLY_REJECTED batches submit")
    members = batch_vouchers(batch["id"])
    if len(members) < 1:
        raise ApiError(ERR_BATCH_EMPTY, 422, "Cannot submit an empty batch")
    for v in members:
        if v["status"] == "ISSUED":
            v["status"] = "SUBMITTED"
            touch(v)
    batch["submitted_by_user_id"] = user_id
    batch["submitted_at"] = logical_now()
    batch["status"] = "SUBMITTED"
    touch(batch)
    return ok_obj(ser_batch(batch))


@bp.post("/central-casting/payroll-batches/<bid>/acknowledge")
def acknowledge_batch(bid):
    user_id, _ = auth(["PayrollCoordinator"])
    data = body()
    batch = get_batch(bid)
    outcome = data.get("outcome")
    if outcome not in ("ACCEPTED", "REJECTED"):
        raise ApiError(ERR_VALIDATION, 400, "outcome must be ACCEPTED or REJECTED")
    rejected_ids = data.get("rejected_voucher_ids")
    if rejected_ids is None:
        rejected_ids = []
    if not isinstance(rejected_ids, list) or any(not isinstance(x, str) for x in rejected_ids):
        raise ApiError(ERR_VALIDATION, 400, "rejected_voucher_ids must be a list of strings")
    if (outcome == "ACCEPTED" and rejected_ids) or (outcome == "REJECTED" and not rejected_ids):
        raise ApiError(
            ERR_VALIDATION,
            400,
            "ACCEPTED takes no rejected ids; REJECTED requires a non-empty rejected_voucher_ids",
        )
    # SoD (pipeline step 4) precedes the state precondition (step 8).
    if batch.get("submitted_by_user_id") is not None and user_id == batch["submitted_by_user_id"]:
        raise ApiError(
            ERR_SOD_SELF_ACKNOWLEDGE,
            403,
            "The acknowledger must differ from the submitter",
        )
    if batch["status"] != "SUBMITTED":
        raise ApiError(ERR_BATCH_INVALID_STATE, 409, "Only a SUBMITTED batch can be acknowledged")
    if outcome == "REJECTED":
        members = {v["id"]: v for v in batch_vouchers(batch["id"])}
        for vid in rejected_ids:
            v = STORE.vouchers.get(vid)
            if v is None:
                raise ApiError(ERR_VOUCHER_NOT_FOUND, 404, "Voucher not found")
            if vid not in members or v["status"] != "SUBMITTED":
                raise ApiError(
                    ERR_VOUCHER_NOT_SUBMITTABLE,
                    409,
                    "Every rejected id must be a SUBMITTED member of this batch",
                )
        for vid in rejected_ids:
            v = members[vid]
            v["status"] = "REJECTED"
            v["payroll_batch_id"] = None
            touch(v)
        batch["status"] = "PARTIALLY_REJECTED"
        batch["acknowledged_by_user_id"] = user_id
        touch(batch)
        production = get_production(batch["production_id"])
        touch(production)  # totals and exposure recomputed
    else:
        for v in batch_vouchers(batch["id"]):
            if v["status"] == "SUBMITTED":
                v["status"] = "PAID"
                touch(v)
        batch["status"] = "ACKNOWLEDGED"
        batch["acknowledged_by_user_id"] = user_id
        touch(batch)
    return ok_obj(ser_batch(batch))
