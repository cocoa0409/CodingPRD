"""Easement endpoints."""
from flask import Blueprint, request

import db
import utils
from errors import ApiError
from middleware import ANY_ROLE, body, parse_pagination, require_roles
from response import ok, ok_list
from services import domain

bp = Blueprint("easements", __name__)


def get_easement_or_404(easement_id):
    e = db.easements.get(easement_id)
    if e is None:
        raise ApiError("ERR_EASEMENT_NOT_FOUND", "Easement id does not exist.", 404)
    return e


@bp.route("/stewardship/easements", methods=["POST"])
@require_roles("TrustAdmin")
def create_easement():
    b = body()
    name = b.get("easement_name")
    grantor = b.get("grantor_name")
    acreage = b.get("parcel_acreage")
    matrix = b.get("permitted_use_matrix")
    interval = b.get("monitoring_interval_months", 12)
    if not isinstance(name, str) or not isinstance(grantor, str):
        raise ApiError("ERR_INVALID_REQUEST", "easement_name and grantor_name are required strings.", 400)
    if not utils.is_int(acreage) or acreage <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "parcel_acreage must be an integer > 0.", 400)
    if (
        not isinstance(matrix, dict)
        or len(matrix) == 0
        or any(not isinstance(k, str) for k in matrix)
        or any(v not in domain.LEVELS for v in matrix.values())
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "permitted_use_matrix must map use types to PERMITTED | DISCRETIONARY | PROHIBITED with at least one entry.",
            400,
        )
    if not utils.is_int(interval) or interval < 6 or interval > 36:
        raise ApiError("ERR_INVALID_REQUEST", "monitoring_interval_months must be an integer in 6..36.", 400)
    now = utils.now_iso()
    e = {
        "id": utils.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "easement_name": name,
        "grantor_name": grantor,
        "parcel_acreage": acreage,
        "permitted_use_matrix": dict(matrix),
        "monitoring_interval_months": interval,
        "status": "DRAFT",
        "current_landowner_id": None,
        "recorded_on": None,
        "last_monitoring_completed_on": None,
    }
    db.easements[e["id"]] = e
    return ok(domain.easement_json(e), 201)


@bp.route("/stewardship/easements", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_easements():
    filters = {}
    for key in ("current_landowner_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    posture_filter = request.args.get("posture")
    rows = [r for r in db.easements.values() if all(r.get(k) == v for k, v in filters.items())]
    if posture_filter is not None:
        rows = [r for r in rows if domain.posture(r) == posture_filter]
    limit, offset = parse_pagination()
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset : offset + limit]
    return ok_list([domain.easement_json(r) for r in page], limit, offset, total)


@bp.route("/stewardship/easements/<easementId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_easement(easementId):
    return ok(domain.easement_json(get_easement_or_404(easementId)))


@bp.route("/stewardship/easements/<easementId>/record", methods=["POST"])
@require_roles("TrustAdmin")
def record_easement(easementId):
    e = get_easement_or_404(easementId)
    # Three gates in PRD §3.1 order: DRAFT, baseline ACCEPTED, ACTIVE landowner.
    if e["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_REQUEST", "Recordation is a no-op on a RECORDED easement.", 400)
    baseline = next((r for r in db.baseline_reports.values() if r["easement_id"] == e["id"]), None)
    if baseline is None or baseline["status"] != "ACCEPTED":
        raise ApiError("ERR_BASELINE_NOT_ACCEPTED", "Easement record requires an ACCEPTED baseline report.", 409)
    landowner = db.landowners.get(e["current_landowner_id"] or "")
    if landowner is None or landowner["status"] != "ACTIVE":
        raise ApiError("ERR_OPEN_OBLIGATIONS_EXIST", "Easement record requires an ACTIVE landowner.", 409)
    e["status"] = "RECORDED"
    e["recorded_on"] = utils.today()
    domain.bump(e)
    return ok(domain.easement_json(e))
