"""Clearance item endpoints (E&O clearances)."""

from flask import request

from db import db
from errors import err
from middleware import require_roles
from response import success_list, success_object
from routes import bp
from services.posture import recompute_posture
from util import (
    body,
    get_child,
    get_production,
    make_entity,
    opt_string,
    paginate,
    req_string,
    serialize,
    touch,
)

CLEARANCE_KINDS = (
    "SCRIPT", "TITLE", "MUSIC", "PERSONAL_RIGHTS", "TRADEMARK", "LOCATION_RIGHTS",
)
CLEARANCE_ROLES = {
    "BrokerAgent", "ProductionManager", "ClearanceCounsel",
    "UnderwriterAgent", "PlatformOperator",
}

# outcome -> allowed source states
RESOLVE_TRANSITIONS = {
    "CLEARED": ("PENDING", "FLAGGED"),
    "FLAGGED": ("PENDING",),
    "WAIVED": ("FLAGGED",),
}


def get_clearance_item(prod_id, item_id):
    return get_child(db.clearance_items, item_id, "production_id", prod_id, "ClearanceItem")


@bp.route("/productions/<id>/clearance-items", methods=["POST"])
def create_clearance_item(id):
    require_roles({"ClearanceCounsel"})
    with db.lock:
        get_production(id)
        data = body()
        kind = data.get("clearance_kind")
        if not isinstance(kind, str) or not kind:
            raise err("ERR_INVALID_REQUEST", "Field 'clearance_kind' is required")
        if kind not in CLEARANCE_KINDS:
            raise err("ERR_INVALID_ENUM",
                      "clearance_kind must be one of %s" % list(CLEARANCE_KINDS))
        item_reference = req_string(data, "item_reference")
        legal_reviewer = req_string(data, "legal_reviewer")
        notes = opt_string(data, "notes")

        rec = make_entity({
            "production_id": id,
            "clearance_kind": kind,
            "item_reference": item_reference,
            "legal_reviewer": legal_reviewer,
            "notes": notes,
            "status": "PENDING",
        })
        db.clearance_items[rec["id"]] = rec
        recompute_posture(db.productions[id])
        return success_object(serialize(rec), status=201)


@bp.route("/productions/<id>/clearance-items", methods=["GET"])
def list_clearance_items(id):
    require_roles(CLEARANCE_ROLES)
    get_production(id)
    kind = request.args.get("clearance_kind")
    status = request.args.get("status")
    records = [c for c in db.clearance_items.values() if c["production_id"] == id]
    if kind is not None:
        records = [r for r in records if r["clearance_kind"] == kind]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/productions/<id>/clearance-items/<childId>", methods=["GET"])
def get_clearance_item_by_id(id, childId):
    require_roles(CLEARANCE_ROLES)
    get_production(id)
    rec = get_clearance_item(id, childId)
    return success_object(serialize(rec))


@bp.route("/productions/<id>/clearance-items/<childId>/resolve", methods=["POST"])
def resolve_clearance_item(id, childId):
    require_roles({"ClearanceCounsel"})
    with db.lock:
        prod = get_production(id)
        item = get_clearance_item(id, childId)
        data = body()
        outcome = data.get("outcome")

        if isinstance(outcome, str) and outcome in RESOLVE_TRANSITIONS:
            if item["status"] not in RESOLVE_TRANSITIONS[outcome]:
                raise err("ERR_INVALID_STATE",
                          "Outcome %s not allowed from status %s" % (outcome, item["status"]))
        else:
            if item["status"] in ("CLEARED", "WAIVED"):
                raise err("ERR_INVALID_STATE",
                          "Clearance item in terminal status %s" % item["status"])
            if not isinstance(outcome, str) or not outcome:
                raise err("ERR_INVALID_REQUEST", "Field 'outcome' is required")
            raise err("ERR_INVALID_ENUM",
                      "outcome must be one of ['CLEARED', 'FLAGGED', 'WAIVED']")

        if outcome == "WAIVED":
            waiver = data.get("waiver_justification")
            if not isinstance(waiver, str) or waiver == "":
                raise err("ERR_INVALID_REQUEST",
                          "Field 'waiver_justification' must be non-empty for a waiver")

        item["status"] = outcome
        touch(item)
        recompute_posture(prod)
        return success_object(serialize(item))
