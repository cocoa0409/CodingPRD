"""FeeSchedule endpoints (PRD §2.9)."""

from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, authorize
from response import created, ok, list_ok
from services.common import stamp_new, touch
from services.lookup import get_or_404
from util import body, require_str, opt_nonneg_int, pagination, paginate

bp = Blueprint("fee_schedules", __name__)

READ_ROLES = {"BillingAdmin", "Advisor", "ComplianceOfficer"}


def _validate_tiers(tiers):
    if not isinstance(tiers, list) or len(tiers) == 0:
        raise err("ERR_INVALID_REQUEST", "tiers must be a non-empty list")
    for idx, t in enumerate(tiers):
        if not isinstance(t, dict):
            raise err("ERR_INVALID_REQUEST", "each tier must be an object")
        if "annual_rate_bps" not in t or not isinstance(t["annual_rate_bps"], int) \
                or isinstance(t["annual_rate_bps"], bool):
            raise err("ERR_INVALID_REQUEST", "tier annual_rate_bps must be an integer")
        if t["annual_rate_bps"] < 0:
            raise err("ERR_INVALID_REQUEST", "tier annual_rate_bps must be non-negative")
        ub = t.get("upper_bound_cents")
        is_last = idx == len(tiers) - 1
        if is_last:
            if ub is not None:
                if not isinstance(ub, int) or isinstance(ub, bool) or ub < 0:
                    raise err("ERR_INVALID_REQUEST", "tier upper_bound_cents invalid")
        else:
            if ub is None or not isinstance(ub, int) or isinstance(ub, bool) or ub < 0:
                raise err("ERR_INVALID_REQUEST",
                          "non-final tier upper_bound_cents must be a non-negative integer")
    # normalize: ensure key present
    out = []
    for t in tiers:
        out.append({
            "upper_bound_cents": t.get("upper_bound_cents"),
            "annual_rate_bps": t["annual_rate_bps"],
        })
    return out


def _serialize(fs):
    return {
        "id": fs["id"],
        "name": fs["name"],
        "tiers": [dict(t) for t in fs["tiers"]],
        "minimum_annual_fee_cents": fs["minimum_annual_fee_cents"],
        "is_locked": fs["is_locked"],
        "created_at": fs["created_at"],
        "updated_at": fs["updated_at"],
        "version": fs["version"],
    }


@bp.route("/fee-schedules", methods=["POST"])
def create():
    _, role = authenticate()
    authorize(role, {"BillingAdmin"})
    data = body()
    name = require_str(data, "name")
    if "tiers" not in data:
        raise err("ERR_INVALID_REQUEST", "tiers is required")
    tiers = _validate_tiers(data["tiers"])
    minimum = opt_nonneg_int(data, "minimum_annual_fee_cents", 0)
    fs = {
        "name": name,
        "tiers": tiers,
        "minimum_annual_fee_cents": minimum,
        "is_locked": False,
    }
    stamp_new(fs)
    db.fee_schedules[fs["id"]] = fs
    return created(_serialize(fs))


@bp.route("/fee-schedules/<fid>", methods=["GET"])
def read(fid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    fs = get_or_404(db.fee_schedules, fid)
    return ok(_serialize(fs))


@bp.route("/fee-schedules", methods=["GET"])
def list_():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = pagination()
    items = sorted(db.fee_schedules.values(), key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([_serialize(x) for x in page], limit, offset, len(items))


@bp.route("/fee-schedules/<fid>", methods=["PATCH"])
def patch(fid):
    _, role = authenticate()
    authorize(role, {"BillingAdmin"})
    fs = get_or_404(db.fee_schedules, fid)
    data = body()
    if fs["is_locked"]:
        raise err("ERR_INVALID_STATE", "Cannot edit a locked fee schedule")
    changed = False
    if "tiers" in data and data["tiers"] is not None:
        fs["tiers"] = _validate_tiers(data["tiers"])
        changed = True
    if "minimum_annual_fee_cents" in data and data["minimum_annual_fee_cents"] is not None:
        fs["minimum_annual_fee_cents"] = opt_nonneg_int(data, "minimum_annual_fee_cents", 0)
        changed = True
    if changed:
        touch(fs)
    return ok(_serialize(fs))
