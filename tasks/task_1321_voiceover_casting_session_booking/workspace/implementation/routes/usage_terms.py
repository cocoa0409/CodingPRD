"""UsageTerms endpoints (1:1 with Project; array of 0-1 on read)."""
from flask import Blueprint, request

import errors
from db import DB
from middleware import auth, json_body
from response import ok, ok_list
from services import lazy_read_tick, paginate, sorted_rows, touch, usage_terms_json

bp = Blueprint("usage_terms", __name__)


def _get_project_or_404(pid):
    p = DB["projects"].get(pid)
    if p is None:
        raise errors.not_found("Project not found")
    return p


def _terms_for(pid):
    rows = [u for u in sorted_rows("usage_terms") if u["project_id"] == pid]
    return rows


@bp.get("/projects/<pid>/usage_terms")
def get_usage_terms(pid):
    auth(["CastingDirector", "Client", "Agent"])
    lazy_read_tick()
    _get_project_or_404(pid)
    rows = _terms_for(pid)
    page, total, limit, offset = paginate(rows, request.args)
    return ok_list([usage_terms_json(u) for u in page], total, limit, offset)


@bp.put("/projects/<pid>/usage_terms")
def put_usage_terms(pid):
    uid, _ = auth(["Client"])
    p = _get_project_or_404(pid)
    if p["client_id"] != uid:
        raise errors.forbidden("Project belongs to a different client")
    rows = _terms_for(pid)
    if not rows:
        raise errors.not_found("Usage terms do not exist for this project yet")
    ut = rows[0]
    # priority 5: terms are immutable once locked at cast
    if ut["locked_at_cast"]:
        raise errors.invalid_state("Usage terms are locked at cast and immutable")
    body = json_body()
    merged_regions = body.get("broadcast_regions", ut["broadcast_regions"])
    merged_placements = body.get("digital_placements", ut["digital_placements"])
    if not isinstance(merged_regions, list) or not isinstance(merged_placements, list):
        raise errors.invalid_request("broadcast_regions and digital_placements must be lists")
    # priority 13: placement payload must be consistent with usage_type
    # (non-empty exactly when the matching usage type applies)
    if (ut["usage_type"] == "BROADCAST") != (len(merged_regions) > 0):
        raise errors.fiscal("broadcast_regions must be non-empty iff usage_type=BROADCAST")
    if (ut["usage_type"] == "DIGITAL") != (len(merged_placements) > 0):
        raise errors.fiscal("digital_placements must be non-empty iff usage_type=DIGITAL")
    ut["broadcast_regions"] = list(merged_regions)
    ut["digital_placements"] = list(merged_placements)
    touch(ut)
    return ok(usage_terms_json(ut))
