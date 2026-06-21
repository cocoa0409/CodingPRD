"""UpdateReminder read routes."""

from flask import Blueprint, request

from common import get_or_404, list_collection, serialize
from db import store
from middleware import parse_pagination, roles
from response import array_response, object_response

bp = Blueprint("update_reminders", __name__)


@bp.route("/legal/update-reminders/<rid>", methods=["GET"])
@roles("Customer", "PlatformAdmin")
def get_update_reminder(rid):
    ent = get_or_404(store.update_reminders, rid)
    return object_response(serialize(ent), 200)


@bp.route("/legal/update-reminders", methods=["GET"])
@roles("Customer", "PlatformAdmin")
def list_update_reminders():
    limit, offset = parse_pagination()
    project_id = request.args.get("document_project_id")

    def predicate(e):
        if project_id is not None and e["document_project_id"] != project_id:
            return False
        return True

    page, total = list_collection(store.update_reminders, predicate, limit, offset)
    return array_response(page, limit, offset, total, 200)
