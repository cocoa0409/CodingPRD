"""Portfolio endpoints (PRD §3.2)."""

from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, authorize
from response import created, ok, list_ok
from services.common import stamp_new, touch
from services.lookup import get_or_404
from util import body, require_str, require_pct, pagination, paginate

bp = Blueprint("portfolios", __name__)

READ_ROLES = {"Advisor", "ComplianceOfficer", "BillingAdmin"}


def _validate_target_weights(weights):
    if not isinstance(weights, list) or len(weights) == 0:
        raise err("ERR_INVALID_REQUEST", "target_weights must be a non-empty list")
    out = []
    total = 0
    for w in weights:
        if not isinstance(w, dict):
            raise err("ERR_INVALID_REQUEST", "each target weight must be an object")
        sleeve = w.get("sleeve")
        tp = w.get("target_pct")
        if not isinstance(sleeve, str) or sleeve == "":
            raise err("ERR_INVALID_REQUEST", "target weight sleeve must be a non-empty string")
        if not isinstance(tp, int) or isinstance(tp, bool):
            raise err("ERR_INVALID_REQUEST", "target weight target_pct must be an integer")
        total += tp
        out.append({"sleeve": sleeve, "target_pct": tp})
    # Allocation validity (priority 11) — must sum to exactly 100.
    if total != 100:
        raise err("ERR_ALLOCATION_INVALID", "target_weights target_pct must sum to 100")
    return out


def _serialize(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "model_equity_pct": p["model_equity_pct"],
        "target_weights": [dict(w) for w in p["target_weights"]],
        "is_published": p["is_published"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/portfolios", methods=["POST"])
def create():
    _, role = authenticate()
    authorize(role, {"Advisor"})
    data = body()
    name = require_str(data, "name")
    model_equity_pct = require_pct(data, "model_equity_pct")
    if "target_weights" not in data:
        raise err("ERR_INVALID_REQUEST", "target_weights is required")
    weights = _validate_target_weights(data["target_weights"])
    p = {
        "name": name,
        "model_equity_pct": model_equity_pct,
        "target_weights": weights,
        "is_published": False,
    }
    stamp_new(p)
    db.portfolios[p["id"]] = p
    return created(_serialize(p))


@bp.route("/portfolios/<pid>/publish", methods=["POST"])
def publish(pid):
    _, role = authenticate()
    authorize(role, {"Advisor"})
    p = get_or_404(db.portfolios, pid)
    p["is_published"] = True
    touch(p)
    return ok(_serialize(p))


@bp.route("/portfolios/<pid>", methods=["GET"])
def read(pid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    p = get_or_404(db.portfolios, pid)
    return ok(_serialize(p))


@bp.route("/portfolios", methods=["GET"])
def list_():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = pagination()
    items = sorted(db.portfolios.values(), key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([_serialize(x) for x in page], limit, offset, len(items))
