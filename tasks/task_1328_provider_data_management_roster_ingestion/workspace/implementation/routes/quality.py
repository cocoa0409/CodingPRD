"""DataQualityScore endpoints (PRD §3.7)."""

from flask import Blueprint, request

from db import DB
from errors import not_found
from middleware import require_roles
from response import success_object, paginate
from services.quality import run_quality_scoring

bp = Blueprint("quality", __name__)


@bp.route("/pdm/providers/<pid>/quality-scores", methods=["GET"])
def list_provider_scores(pid):
    require_roles("DataSteward", "IntakeOperator", "DistributionOperator")
    if pid not in DB.providers:
        raise not_found()
    items = [s for s in DB.data_quality_scores.values() if s["provider_id"] == pid]
    return paginate(items, request.args)


@bp.route("/pdm/providers/<pid>/quality-scores/recompute", methods=["POST"])
def recompute_score(pid):
    require_roles("DataSteward")
    if pid not in DB.providers:
        raise not_found()
    row = run_quality_scoring(pid)
    return success_object(row)


@bp.route("/pdm/quality-scores", methods=["GET"])
def list_scores():
    require_roles("DataSteward", "IntakeOperator", "DistributionOperator")
    items = list(DB.data_quality_scores.values())
    pid = request.args.get("provider_id")
    rfid = request.args.get("roster_file_id")
    if pid is not None:
        items = [s for s in items if s["provider_id"] == pid]
    if rfid is not None:
        items = [s for s in items if s.get("roster_file_id") == rfid]
    return paginate(items, request.args)


@bp.route("/pdm/quality-scores/<sid>", methods=["GET"])
def get_score(sid):
    require_roles("DataSteward", "IntakeOperator", "DistributionOperator")
    row = DB.data_quality_scores.get(sid)
    if row is None:
        raise not_found()
    return success_object(row)
