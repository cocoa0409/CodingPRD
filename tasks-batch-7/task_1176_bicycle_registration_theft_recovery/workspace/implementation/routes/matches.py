"""Match candidates (PRD §3.5)."""
from flask import Blueprint, g, request

import db
from errors import fail
from middleware import require_roles
from models import match_view
from response import list_response, ok_object
from routes.common import load

bp = Blueprint("matches", __name__)


def _owner_visible(match, user_id):
    report = db.theft_reports.get(match["theft_report_id"])
    return report is not None and report["owner_id"] == user_id


@bp.get("/registry/matches")
@require_roles("Owner", "Partner", "Registrar", "Admin")
def list_matches():
    recs = list(db.matches.values())
    if g.role == "Owner":
        recs = [m for m in recs if _owner_visible(m, g.user_id)]
    for param, key in (("recovery_intake_id", "recovery_intake_id"),
                       ("theft_report_id", "theft_report_id"),
                       ("bicycle_id", "bicycle_id"), ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            recs = [m for m in recs if m[key] == value]
    return list_response(recs, match_view)


@bp.get("/registry/matches/<match_id>")
@require_roles("Owner", "Partner", "Registrar", "Admin")
def read_match(match_id):
    rec = load(db.matches, match_id, "ERR_MATCH_NOT_FOUND")
    if g.role == "Owner" and not _owner_visible(rec, g.user_id):
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Owners may read only matches on their own reports")
    return ok_object(match_view(rec))


@bp.post("/registry/matches/<match_id>/dismiss")
@require_roles("Registrar")
def dismiss_match(match_id):
    rec = load(db.matches, match_id, "ERR_MATCH_NOT_FOUND")
    if rec["status"] not in ("PROPOSED", "NOTIFIED"):
        fail("ERR_MATCH_NOT_OPEN", "Only PROPOSED or NOTIFIED matches may be dismissed")
    rec["status"] = "DISMISSED"
    db.bump(rec)
    return ok_object(match_view(rec))
