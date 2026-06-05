"""Form 3921 read routes. PRD §3.9. (Generation lives in routes/exercises.py.)"""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from common import pagination_params, paginate_and_sort
from middleware import require_roles
from response import success, list_response
from services import core

bp = Blueprint("forms_3921", __name__)


@bp.get("/forms-3921/<cid>")
@require_roles("Administrator", "Auditor", "Stakeholder")
def get_form_3921(cid):
    form = core.get_form_3921(cid)
    return success(core.serialize(form))


@bp.get("/forms-3921")
@require_roles("Administrator", "Auditor")
def list_forms_3921():
    limit, offset = pagination_params()
    items = list(db.forms_3921.values())
    for key in ("cap_table_id", "exercise_id", "shareholder_id"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i[key] == val]
    page, total = paginate_and_sort(items, limit, offset)
    return list_response(
        [core.serialize(i) for i in page],
        limit=limit, offset=offset, total_count=total,
    )
