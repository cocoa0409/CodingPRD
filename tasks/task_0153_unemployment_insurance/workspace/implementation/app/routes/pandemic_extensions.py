"""PandemicExtension routes."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import (
    ROLE_ADJUDICATOR,
    ROLE_APPEAL_OFFICER,
    ROLE_CLAIMANT,
    ROLE_EMPLOYER_AGENT,
    ROLE_SYSTEM_ADMIN,
    require_auth,
)
from ..envelope import paginate, parse_pagination, success_array, success_object
from ..serializers import serialize_pandemic_extension
from ..services.entities import create_pandemic_extension
from ..store import get_store
from ..validators import (
    get_json_body,
    require_int,
    require_string,
    validate_iso_date,
)
from ._helpers import sort_by_created_at

bp = Blueprint("pandemic_extensions", __name__)


@bp.post("/pandemic-extensions")
@require_auth([ROLE_SYSTEM_ADMIN])
def extensions_create():
    body = get_json_body()
    name = require_string(body, "program_name")
    eff_start = validate_iso_date(require_string(body, "effective_start"), "effective_start")
    eff_end = validate_iso_date(require_string(body, "effective_end"), "effective_end")
    extra_weeks = require_int(body, "extra_weeks", min_val=1, max_val=26)
    entity = create_pandemic_extension({
        "program_name": name,
        "effective_start": eff_start,
        "effective_end": eff_end,
        "extra_weeks": extra_weeks,
    })
    return jsonify(success_object(serialize_pandemic_extension(entity))), 201


@bp.get("/pandemic-extensions")
@require_auth([
    ROLE_CLAIMANT, ROLE_ADJUDICATOR, ROLE_APPEAL_OFFICER,
    ROLE_EMPLOYER_AGENT, ROLE_SYSTEM_ADMIN,
])
def extensions_list():
    status_filter = request.args.get("status")
    limit, offset = parse_pagination()
    items = list(get_store().pandemic_extensions.values())
    if status_filter:
        items = [e for e in items if e["status"] == status_filter]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return jsonify(success_array(
        [serialize_pandemic_extension(e) for e in page],
        limit=limit, offset=offset, total_count=total,
    )), 200
