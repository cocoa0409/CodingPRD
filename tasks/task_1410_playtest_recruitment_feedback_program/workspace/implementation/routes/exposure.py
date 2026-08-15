"""Exposure record (append-only journal) endpoints."""

import db
from middleware import require_roles
from response import success, parse_pagination, paginate_list
from routes import make_blueprint
from errors import raise_error, ERR_NOT_FOUND
from services.serializers import public

bp = make_blueprint("exposure")


@bp.route("/playtests/exposure-records", methods=["GET"])
def list_records():
    require_roles("ResearchOpsAdmin", "Researcher", "LegalCounsel")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.exposure_records.values())
    for param in ("participant_id", "build_id", "study_id", "event_type"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if str(e.get(param)) == v]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(e, "exposure_record") for e in page], status=200, pagination=pagination)


@bp.route("/playtests/exposure-records/<rid>", methods=["GET"])
def get_record(rid):
    require_roles("ResearchOpsAdmin", "Researcher", "LegalCounsel")
    rec = db.exposure_records.get(rid)
    if rec is None:
        raise_error(ERR_NOT_FOUND, "Exposure record not found")
    return success(public(rec, "exposure_record"), status=200)
