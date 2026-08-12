from flask import Blueprint, request

from db import stamp_new, store, touch
from envelope import ok, ok_list
from errors import ERR_FORBIDDEN, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_VALIDATION, raise_err
from security import ALL_READ, require_roles
from validators import apply_filters, get_body, opt_int, paginate, req_str
import serializers

bp = Blueprint("workers", __name__)


def _get_worker(worker_id):
    w = store.workers.get(worker_id)
    if w is None:
        raise_err(ERR_NOT_FOUND, f"Worker {worker_id} not found.")
    return w


@bp.post("/v1/workers")
def create_worker():
    uid, role = require_roles("SupplierCoordinator", "ProgramAdmin")
    body = get_body()
    supplier_id = req_str(body, "supplier_id")
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    carryover = opt_int(body, "tenure_carryover_days", 0)
    if role == "SupplierCoordinator" and uid != supplier_id:
        raise_err(ERR_FORBIDDEN, "A SupplierCoordinator may only register workers under its own supplier id.")
    if supplier_id not in store.suppliers:
        raise_err(ERR_NOT_FOUND, f"Supplier {supplier_id} not found.")
    for w in store.workers.values():
        if w["email"] == email:
            raise_err(ERR_VALIDATION, f"Worker email '{email}' is already in use.")
    rec = {
        "supplier_id": supplier_id,
        "full_name": full_name,
        "email": email,
        "tenure_carryover_days": carryover,
        "status": "ONBOARDING",
        "conversion_status": "NONE",
    }
    stamp_new(rec)
    store.workers[rec["id"]] = rec
    return ok(serializers.worker(rec), 201)


@bp.get("/v1/workers")
def list_workers():
    require_roles(*ALL_READ)
    filters = {
        "supplier_id": request.args.get("supplier_id"),
        "status": request.args.get("status"),
    }
    records = apply_filters(list(store.workers.values()), filters)
    page, total, limit, offset = paginate(records, serializers.worker)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/workers/<worker_id>")
def get_worker(worker_id):
    require_roles(*ALL_READ)
    return ok(serializers.worker(_get_worker(worker_id)))


@bp.post("/v1/workers/<worker_id>/offboard-complete")
def offboard_complete(worker_id):
    require_roles("ProgramAdmin")
    w = _get_worker(worker_id)
    if w["status"] != "OFFBOARDING":
        raise_err(ERR_INVALID_STATE, "Only an OFFBOARDING worker can complete offboarding.")
    w["status"] = "EXITED"
    touch(w)
    return ok(serializers.worker(w))


@bp.post("/v1/workers/<worker_id>/rehire")
def rehire(worker_id):
    require_roles("ProgramAdmin")
    w = _get_worker(worker_id)
    if w["status"] != "EXITED":
        raise_err(ERR_INVALID_STATE, "Only an EXITED worker can be rehired.")
    w["status"] = "ONBOARDING"
    touch(w)
    return ok(serializers.worker(w))
