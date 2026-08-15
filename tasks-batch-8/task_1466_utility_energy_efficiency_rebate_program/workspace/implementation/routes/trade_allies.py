"""TradeAlly enrollment and standing endpoints."""
from flask import Blueprint, request

from auth import ALL_ROLES, require_roles
from db import base_fields, store
from errors import ApiError
from lookups import get_trade_ally
from respond import respond_list, success
from serialize import trade_ally_out
from services import ALLY_OPEN_STATUSES, touch
from validate import get_body, req_str

bp = Blueprint("trade_allies", __name__)


@bp.post("/trade-allies")
@require_roles("ProgramAdministrator")
def create_trade_ally():
    body = get_body()
    ally_name = req_str(body, "ally_name")
    license_number = req_str(body, "license_number")
    for existing in store.trade_allies.values():
        if existing["license_number"] == license_number:
            raise ApiError(
                "ERR_DUPLICATE_UNIQUE_FIELD",
                409,
                "license_number '%s' is already enrolled" % license_number,
            )
    rec = base_fields()
    rec.update(
        {
            "ally_name": ally_name,
            "license_number": license_number,
            "performance_score": 100,
            "standing_tier": "STANDARD",
            "enroll_status": "PENDING",
        }
    )
    store.trade_allies[rec["id"]] = rec
    return success(trade_ally_out(rec), "object", 201)


@bp.get("/trade-allies")
@require_roles(*ALL_ROLES)
def list_trade_allies():
    enroll_status = request.args.get("enroll_status")
    standing_tier = request.args.get("standing_tier")
    rows = list(store.trade_allies.values())
    if enroll_status is not None:
        rows = [r for r in rows if r["enroll_status"] == enroll_status]
    if standing_tier is not None:
        rows = [r for r in rows if r["standing_tier"] == standing_tier]
    return respond_list(rows, trade_ally_out)


@bp.get("/trade-allies/<rid>")
@require_roles(*ALL_ROLES)
def get_trade_ally_route(rid):
    return success(trade_ally_out(get_trade_ally(rid)), "object", 200)


def _transition(rid, from_status, to_status):
    ally = get_trade_ally(rid)
    if ally["enroll_status"] != from_status:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "TradeAlly.enroll_status is %s; this transition requires %s"
            % (ally["enroll_status"], from_status),
        )
    ally["enroll_status"] = to_status
    touch(ally)
    return success(trade_ally_out(ally), "object", 200)


@bp.post("/trade-allies/<rid>/activate")
@require_roles("ProgramAdministrator")
def activate_trade_ally(rid):
    return _transition(rid, "PENDING", "ACTIVE")


@bp.post("/trade-allies/<rid>/suspend")
@require_roles("ProgramAdministrator")
def suspend_trade_ally(rid):
    return _transition(rid, "ACTIVE", "SUSPENDED")


@bp.post("/trade-allies/<rid>/reinstate")
@require_roles("ProgramAdministrator")
def reinstate_trade_ally(rid):
    return _transition(rid, "SUSPENDED", "ACTIVE")


@bp.post("/trade-allies/<rid>/terminate")
@require_roles("ProgramAdministrator")
def terminate_trade_ally(rid):
    ally = get_trade_ally(rid)
    if ally["enroll_status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "TradeAlly.enroll_status is %s; terminate requires ACTIVE or SUSPENDED"
            % ally["enroll_status"],
        )
    if ally["enroll_status"] == "ACTIVE":
        # Open-application guard, evaluated after the state check.
        open_apps = [
            a for a in store.applications.values()
            if a["trade_ally_id"] == ally["id"] and a["status"] in ALLY_OPEN_STATUSES
        ]
        if open_apps:
            raise ApiError(
                "ERR_ALLY_HAS_OPEN_APPLICATIONS",
                409,
                "TradeAlly has %d open application(s); termination blocked"
                % len(open_apps),
            )
    ally["enroll_status"] = "TERMINATED"
    touch(ally)
    return success(trade_ally_out(ally), "object", 200)
