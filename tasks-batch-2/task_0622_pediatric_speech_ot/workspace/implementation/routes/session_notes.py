"""Session-note read endpoints (PRD §3.6)."""

from flask import Blueprint, request

from db import db
from response import success, list_success
from middleware import require_roles, ALL_ROLES
from services.common import lookup, paginate, sorted_by_created
from services import serialize

bp = Blueprint("session_notes", __name__)


@bp.route("/clinic/appointments/<appointment_id>/session-notes", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_appointment_notes(appointment_id, user_id=None, role=None):
    lookup(db.appointments, appointment_id)
    items = [n for n in db.session_notes.values() if n["appointment_id"] == appointment_id]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return list_success([serialize.session_note(n) for n in page], limit, offset, total)


@bp.route("/clinic/session-notes/<session_note_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_session_note(session_note_id, user_id=None, role=None):
    rec = lookup(db.session_notes, session_note_id)
    return success(serialize.session_note(rec), status=200)
