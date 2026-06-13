"""Trial endpoints: get, ready (SCHEDULED->READY), create-panel, list-panels."""
from flask import Blueprint, request

import db
import errors
import helpers
import serializers
from middleware import get_identity, require_roles
from response import success
from services import core

bp = Blueprint("trials", __name__)


# ---------------------------------------------------------------------------
# GET /trials/{id}
# ---------------------------------------------------------------------------
@bp.route("/trials/<trial_id>", methods=["GET"])
def get_trial(trial_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Judge"})

    t = core.get_trial(trial_id)
    if t is None:
        raise errors.err("ERR_NOT_FOUND", "Trial not found")
    return success(serializers.trial(t), status=200)


# ---------------------------------------------------------------------------
# POST /trials/{id}/ready  (Judge): SCHEDULED -> READY
# ---------------------------------------------------------------------------
@bp.route("/trials/<trial_id>/ready", methods=["POST"])
def ready_trial(trial_id):
    _, role = get_identity()
    require_roles(role, {"Judge"})

    t = core.get_trial(trial_id)
    if t is None:
        raise errors.err("ERR_NOT_FOUND", "Trial not found")

    if t["status"] != "SCHEDULED":
        raise errors.err("ERR_INVALID_STATE", "Trial must be SCHEDULED to ready")

    term = db.service_terms.get(t["service_term_id"])
    if term is None or term["status"] != "OPEN":
        raise errors.err("ERR_TERM_NOT_OPEN", "Term must be OPEN to ready a trial")

    t["status"] = "READY"
    core.touch(t)
    return success(serializers.trial(t), status=200)


# ---------------------------------------------------------------------------
# POST /trials/{id}/panels  (Judge): create FORMING panel
# ---------------------------------------------------------------------------
@bp.route("/trials/<trial_id>/panels", methods=["POST"])
def create_panel(trial_id):
    _, role = get_identity()
    require_roles(role, {"Judge"})

    t = core.get_trial(trial_id)
    if t is None:
        raise errors.err("ERR_NOT_FOUND", "Trial not found")

    body = helpers.get_body()
    # target_size optional; defaults to trial.required_jurors. Must be >= 1.
    target_size = helpers.optional_int(body, "target_size", default=None, minimum=1)
    if target_size is None:
        target_size = t["required_jurors"]

    rec = core.create_panel(t["service_term_id"], trial_id, target_size)
    return success(serializers.panel(rec), status=201)


# ---------------------------------------------------------------------------
# GET /trials/{id}/panels
# ---------------------------------------------------------------------------
@bp.route("/trials/<trial_id>/panels", methods=["GET"])
def list_trial_panels(trial_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Judge"})

    t = core.get_trial(trial_id)
    if t is None:
        raise errors.err("ERR_NOT_FOUND", "Trial not found")

    status = request.args.get("status")
    rows = [p for p in db.panels.values() if p["trial_id"] == trial_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]

    data, meta = helpers.paginate(rows, serializers.panel)
    return success(data, status=200, pagination=meta)
