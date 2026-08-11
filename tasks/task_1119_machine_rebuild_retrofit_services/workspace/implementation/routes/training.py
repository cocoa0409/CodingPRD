"""TrainingRecord endpoints (PRD §3.7)."""

from flask import Blueprint, request

from db import bump, sorted_records, store
from errors import ApiError, ERR_INVALID_STATE, ERR_TRAINING_SESSION_OVERFLOW
from middleware import forbidden, require_roles
from response import list_response, success
from serializers import serialize, serialize_list
from services import maybe_complete_training
from util import pagination_params, paginate
from routes.common import check_customer_ownership, customer_owns, get_or_404

bp = Blueprint("training", __name__)


@bp.get("/api/training-records/<tid>")
@require_roles("Trainer", "ProjectManager", "Customer", "PlatformAdmin")
def get_training_record(user_id, role, tid):
    rec = get_or_404(store.training_records, tid, "training record")
    check_customer_ownership(user_id, role, "training", rec)
    return success(serialize(rec))


@bp.get("/api/training-records")
@require_roles("Trainer", "ProjectManager", "Customer", "PlatformAdmin")
def list_training_records(user_id, role):
    limit, offset = pagination_params()
    items = sorted_records(store.training_records)
    project_filter = request.args.get("project_id")
    if project_filter is not None:
        items = [t for t in items if t["project_id"] == project_filter]
    if role == "Customer":
        items = [t for t in items if customer_owns(user_id, "training", t)]
    page, meta = paginate(items, limit, offset)
    return list_response(serialize_list(page), meta)


def _load_and_authorize(tid, user_id):
    rec = get_or_404(store.training_records, tid, "training record")
    if rec["trainer_id"] != user_id:
        raise forbidden("only the assigned trainer may write this record")
    return rec


@bp.post("/api/training-records/<tid>/log-session")
@require_roles("Trainer")
def log_session(user_id, role, tid):
    rec = _load_and_authorize(tid, user_id)
    if rec["status"] not in ("PLANNED", "IN_PROGRESS"):
        raise ApiError(
            ERR_INVALID_STATE,
            f"training record in status {rec['status']} cannot log sessions",
            409,
        )
    if rec["sessions_completed"] >= rec["sessions_required"]:
        raise ApiError(
            ERR_TRAINING_SESSION_OVERFLOW,
            "sessions_completed has already reached sessions_required",
            409,
        )
    rec["sessions_completed"] += 1
    if rec["status"] == "PLANNED":
        rec["status"] = "IN_PROGRESS"
    bump(rec)
    maybe_complete_training(rec)
    return success(serialize(rec))


@bp.post("/api/training-records/<tid>/deliver-documentation")
@require_roles("Trainer")
def deliver_documentation(user_id, role, tid):
    rec = _load_and_authorize(tid, user_id)
    if rec["status"] not in ("PLANNED", "IN_PROGRESS"):
        raise ApiError(
            ERR_INVALID_STATE,
            f"training record in status {rec['status']} cannot deliver documentation",
            409,
        )
    rec["documentation_delivered"] = True
    bump(rec)
    maybe_complete_training(rec)
    return success(serialize(rec))
