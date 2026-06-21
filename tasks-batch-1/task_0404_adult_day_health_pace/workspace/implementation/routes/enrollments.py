"""Enrollment read endpoints. PRD §3.4 / §4."""
from flask import Blueprint, request

import db
from middleware import require_roles
from response import success, list_response
from services import common as c

bp = Blueprint("enrollments", __name__)


def enrollment_view(e):
    return dict(e)


@bp.get("/pace/enrollments/<enrollment_id>")
@require_roles("ProgramAdmin", "IntakeCoordinator", "BillingSpecialist")
def get_enrollment(enrollment_id):
    e = c.find_or_404(db.enrollments, enrollment_id)
    return success(enrollment_view(e))


@bp.get("/pace/enrollments")
@require_roles("ProgramAdmin", "IntakeCoordinator", "BillingSpecialist")
def list_enrollments():
    limit, offset = c.get_pagination()
    items = list(db.enrollments.values())
    for key in ("participant_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    page, total = c.paginate(items, limit, offset)
    return list_response([enrollment_view(e) for e in page], limit, offset, total)
