"""Juror endpoints: get, list-its-summonses, admin qualify override, strikes."""
from flask import Blueprint, request

import db
import errors
import helpers
import serializers
from middleware import get_identity, require_roles
from response import success
from services import core

bp = Blueprint("jurors", __name__)


# ---------------------------------------------------------------------------
# GET /jurors/{id}
# ---------------------------------------------------------------------------
@bp.route("/jurors/<juror_id>", methods=["GET"])
def get_juror(juror_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Juror"})

    juror = core.get_juror(juror_id)
    if juror is None:
        raise errors.err("ERR_NOT_FOUND", "Juror not found")
    return success(serializers.juror(juror), status=200)


# ---------------------------------------------------------------------------
# GET /jurors/{id}/summonses
# ---------------------------------------------------------------------------
@bp.route("/jurors/<juror_id>/summonses", methods=["GET"])
def list_juror_summonses(juror_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Juror"})

    juror = core.get_juror(juror_id)
    if juror is None:
        raise errors.err("ERR_NOT_FOUND", "Juror not found")

    status = request.args.get("status")
    rows = [s for s in db.summonses.values() if s["juror_id"] == juror_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]

    data, meta = helpers.paginate(rows, serializers.summons)
    return success(data, status=200, pagination=meta)


# ---------------------------------------------------------------------------
# POST /jurors/{id}/qualify  (administrative override PENDING->QUALIFIED)
# ---------------------------------------------------------------------------
@bp.route("/jurors/<juror_id>/qualify", methods=["POST"])
def qualify_juror(juror_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator"})

    juror = core.get_juror(juror_id)
    if juror is None:
        raise errors.err("ERR_NOT_FOUND", "Juror not found")

    # Override permitted only while not disqualified (PRD §3.1/§3.3).
    if juror["disqualified"]:
        raise errors.err("ERR_INVALID_STATE", "Cannot qualify a disqualified juror")
    if juror["qualification_status"] != "PENDING":
        raise errors.err("ERR_INVALID_STATE", "Juror must be PENDING to qualify")

    juror["qualification_status"] = "QUALIFIED"
    core.touch(juror)
    # pool_size recompute is a mutation of the parent term (PRD §2.5).
    term = db.service_terms.get(juror["service_term_id"])
    if term is not None:
        core.touch(term)
    return success(serializers.juror(juror), status=200)


# ---------------------------------------------------------------------------
# GET /jurors/{id}/strikes
# ---------------------------------------------------------------------------
@bp.route("/jurors/<juror_id>/strikes", methods=["GET"])
def list_juror_strikes(juror_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk"})

    juror = core.get_juror(juror_id)
    if juror is None:
        raise errors.err("ERR_NOT_FOUND", "Juror not found")

    rows = [st for st in db.strikes.values() if st["juror_id"] == juror_id]
    data, meta = helpers.paginate(rows, serializers.strike)
    return success(data, status=200, pagination=meta)
