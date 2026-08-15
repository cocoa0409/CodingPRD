"""AnnualSweep CRUD + run."""
from calendar import monthrange
from datetime import date, timedelta
from flask import Blueprint, request

from db import db
from errors import (
    ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_SWEEP_INVALID_STATE,
    ERR_DUPLICATE_SWEEP, ApiError,
)
from middleware import require_role, get_auth
from response import success_object, success_list
from utils import (
    SWEEP_FIELDS, serialize, stamp_created, bump_version,
    parse_pagination, paginate, now_stamp,
)
from services.calculations import run_annual_sweep

sweeps_bp = Blueprint("annual_sweeps", __name__)


def _get_sweep_or_404(sid):
    s = db.annual_sweeps.get(sid)
    if not s:
        raise ApiError(ERR_NOT_FOUND, f"AnnualSweep {sid} not found.", 404)
    return s


@sweeps_bp.route("/annual-sweeps", methods=["POST"])
def create_sweep():
    user_id, role = require_role("ComplianceOfficer")
    body = request.get_json(force=True) or {}

    for f in ["issuer_id", "fiscal_year"]:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"{f} is required.", 400)

    if body["issuer_id"] not in db.issuers:
        raise ApiError(ERR_INVALID_REQUEST, f"issuer_id {body['issuer_id']} not found.", 400)

    fiscal_year = body["fiscal_year"]
    if not isinstance(fiscal_year, int) or isinstance(fiscal_year, bool):
        raise ApiError(ERR_INVALID_REQUEST, "fiscal_year must be an integer.", 400)

    # Duplicate check
    for s in db.annual_sweeps.values():
        if s["issuer_id"] == body["issuer_id"] and s["fiscal_year"] == fiscal_year \
                and s["status"] in ("OPEN", "COMPLETED"):
            raise ApiError(ERR_DUPLICATE_SWEEP, "Sweep already exists for (issuer_id, fiscal_year).", 409)

    issuer = db.issuers[body["issuer_id"]]
    fy_end_month = issuer["fiscal_year_end_month"]
    fy_end = date(fiscal_year, fy_end_month, monthrange(fiscal_year, fy_end_month)[1])
    fy_start = fy_end.replace(year=fy_end.year - 1) + timedelta(days=1)

    sweep = {
        "issuer_id": body["issuer_id"],
        "fiscal_year": fiscal_year,
        "fy_start_date": fy_start.isoformat(),
        "fy_end_date": fy_end.isoformat(),
        "status": "OPEN",
        "run_at": None,
        "results": [],
    }
    stamp_created(sweep)
    db.annual_sweeps[sweep["id"]] = sweep
    return success_object(serialize(sweep, SWEEP_FIELDS), 201)


@sweeps_bp.route("/annual-sweeps", methods=["GET"])
def list_sweeps():
    get_auth()
    limit, offset = parse_pagination(request.args)
    items = sorted(db.annual_sweeps.values(), key=lambda x: x["created_at"])
    issuer_id = request.args.get("issuer_id")
    if issuer_id:
        items = [s for s in items if s["issuer_id"] == issuer_id]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(s, SWEEP_FIELDS) for s in page], limit, offset, total)


@sweeps_bp.route("/annual-sweeps/<sweepId>", methods=["GET"])
def get_sweep(sweepId):
    get_auth()
    s = _get_sweep_or_404(sweepId)
    return success_object(serialize(s, SWEEP_FIELDS))


@sweeps_bp.route("/annual-sweeps/<sweepId>/run", methods=["POST"])
def run_sweep(sweepId):
    user_id, role = require_role("ComplianceOfficer")
    sweep = _get_sweep_or_404(sweepId)
    if sweep["status"] != "OPEN":
        raise ApiError(ERR_SWEEP_INVALID_STATE, "Run requires OPEN.", 409)
    run_annual_sweep(sweep)
    bump_version(sweep)
    return success_object(serialize(sweep, SWEEP_FIELDS))
