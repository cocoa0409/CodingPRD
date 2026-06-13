"""Sanction sub-collection endpoint (PRD §3.5)."""
from flask import Blueprint, request

import db
from middleware import require_roles
from response import array_response
from serialize import public_list
from services.common import (
    apply_page,
    get_child_or_404,
    get_supervisee_or_404,
    paginate,
    sorted_by_created,
)

bp = Blueprint("sanctions", __name__)


@bp.get("/supervisees/<sid>/violations/<vid>/sanctions")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def list_sanctions(sid, vid):
    get_supervisee_or_404(sid)
    get_child_or_404(db.violations, vid, sid, label="Violation")
    limit, offset = paginate(request.args)
    records = [s for s in db.sanctions.values() if s.get("violation_id") == vid]
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)
