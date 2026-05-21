from __future__ import annotations

from flask import Blueprint, g

from .. import metrics, projections, resolvers
from ..auth import require_role
from ..entities import bump, init_versioned
from ..envelope import (
    err_forbidden,
    err_invalid_state,
    err_suspend_criteria_not_met,
    err_validation,
    success,
)
from ..store import store
from ..validators import get_json, require_str

bp = Blueprint("riders", __name__)


def _serialize(r: dict) -> dict:
    return projections.rider(r)


@bp.route("/api/riders", methods=["POST"])
def register_rider():
    require_role("PlatformAdmin")
    body = get_json()
    name = require_str(body, "name", max_len=200)
    phone = require_str(body, "phone", max_len=40)
    for r in store.riders.values():
        if r.get("phone") == phone:
            raise err_validation("phone must be unique among riders")
    r = init_versioned("Rider")
    r.update(
        {
            "name": name,
            "phone": phone,
            "status": "OFFLINE",
            "on_time_rate": 1.0,
            "acceptance_rate": 1.0,
            "rating": 5.0,
            "wallet_balance_cents": 0,
            "bonus_tier": "BRONZE",
            "_offer_history": [],
            "_delivery_history": [],
            "_rating_history": [],
        }
    )
    store.riders[r["id"]] = r
    return success(_serialize(r), status=201)


@bp.route("/api/riders/<rid>", methods=["GET"])
def read_rider(rid: str):
    require_role("PlatformAdmin", "Rider", "CustomerService")
    r = resolvers.rider(rid)
    if g.user_role == "Rider" and g.user_id != r["id"]:
        raise err_forbidden("Rider identity mismatch")
    return success(_serialize(r))


@bp.route("/api/riders/<rid>/go-online", methods=["POST"])
def go_online(rid: str):
    require_role("Rider")
    r = resolvers.rider(rid)
    if g.user_id != r["id"]:
        raise err_forbidden("Rider identity mismatch")
    if r["status"] != "OFFLINE":
        raise err_invalid_state(f"Cannot go online from {r['status']}")
    r["status"] = "AVAILABLE"
    bump(r)
    return success(_serialize(r))


@bp.route("/api/riders/<rid>/go-offline", methods=["POST"])
def go_offline(rid: str):
    require_role("Rider")
    r = resolvers.rider(rid)
    if g.user_id != r["id"]:
        raise err_forbidden("Rider identity mismatch")
    if r["status"] != "AVAILABLE":
        raise err_invalid_state(f"Cannot go offline from {r['status']}")
    # Active-assignments precondition
    for a in store.assignments.values():
        if a["rider_id"] == r["id"] and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            raise err_invalid_state("Cannot go offline while active assignments exist")
    r["status"] = "OFFLINE"
    bump(r)
    return success(_serialize(r))


@bp.route("/api/riders/<rid>/suspend", methods=["POST"])
def suspend_rider(rid: str):
    require_role("PlatformAdmin")
    r = resolvers.rider(rid)
    if r["status"] != "AVAILABLE":
        raise err_invalid_state(f"Cannot suspend rider from {r['status']}")
    if not (r["on_time_rate"] < 0.70 or r["acceptance_rate"] < 0.50):
        raise err_suspend_criteria_not_met()
    r["status"] = "SUSPENDED"
    bump(r)
    return success(_serialize(r))
