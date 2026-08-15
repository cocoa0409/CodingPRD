"""Training records: create, list, read. Records are immutable once created."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import ok, created, paginate
from services import domain
from validation import validate_body

bp = Blueprint("training", __name__)


@bp.post("/training-records")
def create_training():
    uid, role = get_context()
    require_roles(["YardTechnician"])
    body = validate_body({
        "customer_id": ("string", True),
        "class_id": ("string", True),
        "trainee_name": ("string", True),
        "trained_at": ("datetime", True),
    })
    if body["customer_id"] not in store.customers:
        raise ApiError("ERR_NOT_FOUND", 404, "Customer account not found")
    if body["class_id"] not in store.classes:
        raise ApiError("ERR_NOT_FOUND", 404, "Equipment class not found")
    trained_at = db.parse_datetime(body["trained_at"])
    record = {
        "id": db.new_id(),
        "created_at": db.wall_now(),
        "_seq": db.next_seq(),
        "customer_id": body["customer_id"],
        "class_id": body["class_id"],
        "trainee_name": body["trainee_name"],
        "trained_at": db.iso_logical(trained_at),
        "trainer_id": uid,
    }
    store.training[record["id"]] = record
    return created(domain.view_training(record))


@bp.get("/training-records")
def list_training():
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "YardTechnician"])
    rows = [domain.view_training(t) for t in store.training.values()]
    rows = paginate.filter(rows, "customer_id")
    rows = paginate.filter(rows, "class_id")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/training-records/<tid>")
def get_training(tid):
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "YardTechnician"])
    record = store.training.get(tid)
    if record is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Training record not found")
    return ok(domain.view_training(record))
