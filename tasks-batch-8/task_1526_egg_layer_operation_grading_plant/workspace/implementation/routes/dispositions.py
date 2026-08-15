"""Spent-hen dispositions: plan, complete (hen ledger), void (compensation)."""
from flask import Blueprint, request

from db import STORE, new_record, today, touch
from errors import (
    ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_HEN_COUNT_EXCEEDED,
)
from middleware import endpoint, ALL_ROLES
from response import ok, paginate, pub
from util import req_str, req_int, req_enum
from services.domain import get_entity, flock_current_hen_count

bp = Blueprint("dispositions", __name__)

FM = ["FarmManager"]
METHODS = {"RENDERING", "COMPOST", "LIVE_SALE", "EUTHANIZED"}


def _body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


@bp.route("/api/dispositions", methods=["POST"])
@endpoint(FM)
def create_disposition(actor):
    body = _body()
    flock_id = body.get("flock_id")
    if isinstance(flock_id, str) and flock_id:
        get_entity("flocks", flock_id, "Flock")
    flock_id = req_str(body, "flock_id")
    get_entity("flocks", flock_id, "Flock")
    method = req_enum(body, "method", METHODS)
    hen_count = req_int(body, "hen_count", min_v=1)
    revenue = req_int(body, "revenue_cents", min_v=0)
    rec = new_record()
    rec.update({
        "flock_id": flock_id,
        "method": method,
        "hen_count": hen_count,
        "revenue_cents": revenue,
        "status": "PLANNED",
        "completed_date": None,
    })
    STORE["dispositions"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.route("/api/dispositions/<dispositionId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_disposition(dispositionId, actor):
    return ok(pub(get_entity("dispositions", dispositionId, "SpentHenDisposition")), status=200)


@bp.route("/api/dispositions", methods=["GET"])
@endpoint(ALL_ROLES)
def list_dispositions(actor):
    items = list(STORE["dispositions"].values())
    flock_id = request.args.get("flock_id")
    status = request.args.get("status")
    if flock_id is not None:
        items = [d for d in items if d["flock_id"] == flock_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: (d["created_at"], d["_seq"]))
    return paginate(items, pub)


@bp.route("/api/dispositions/<dispositionId>/complete", methods=["POST"])
@endpoint(FM)
def complete_disposition(dispositionId, actor):
    disp = get_entity("dispositions", dispositionId, "SpentHenDisposition")
    # Tier 6: PLANNED -> COMPLETED.
    if disp["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "Disposition must be PLANNED to complete")
    flock = get_entity("flocks", disp["flock_id"], "Flock")
    if flock["status"] != "DEPOPULATING":
        raise ApiError(ERR_INVALID_STATE, 409, "Flock must be DEPOPULATING to complete a disposition")
    # Tier 11: hen-count ceiling.
    if disp["hen_count"] > flock_current_hen_count(flock):
        raise ApiError(ERR_HEN_COUNT_EXCEEDED, 422, "hen_count exceeds the flock's current hen count")
    disp["status"] = "COMPLETED"
    disp["completed_date"] = today()
    touch(disp)
    touch(flock)  # hen ledger deduction
    # Cascade: at zero hens the flock DEPLETES and the house starts CLEANING.
    if flock_current_hen_count(flock) == 0 and flock["status"] == "DEPOPULATING":
        flock["status"] = "DEPLETED"
        flock["depleted_date"] = today()
        touch(flock)
        house = STORE["houses"].get(flock["house_id"])
        if house is not None and house["status"] == "DEPOPULATING":
            house["status"] = "CLEANING"
            house["status_changed_date"] = today()
            house["current_flock_id"] = None
            touch(house)
    return ok(pub(disp), status=200)


@bp.route("/api/dispositions/<dispositionId>/void", methods=["POST"])
@endpoint(FM)
def void_disposition(dispositionId, actor):
    disp = get_entity("dispositions", dispositionId, "SpentHenDisposition")
    # Void is defined only from COMPLETED (PRD §3.9).
    if disp["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, 409, "Disposition must be COMPLETED to void")
    flock = get_entity("flocks", disp["flock_id"], "Flock")
    if flock["status"] == "DEPLETED":
        raise ApiError(ERR_INVALID_STATE, 409, "Hens cannot return to a depleted flock")
    disp["status"] = "VOIDED"
    touch(disp)
    touch(flock)  # hens restored (VOIDED dispositions leave the computed ledger)
    return ok(pub(disp), status=200)
