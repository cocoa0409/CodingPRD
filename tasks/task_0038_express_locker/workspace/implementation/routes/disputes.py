"""Dispute resolution route."""

from flask import Blueprint, g, request

from db import LOCK
from middleware import require_roles
from response import success_object
from services.dispute import resolve_dispute, serialize_dispute


bp = Blueprint("disputes", __name__)


@bp.route("/disputes/<dispute_id>/resolve", methods=["POST"])
@require_roles("OperationsAdmin")
def post_resolve(dispute_id):
    with LOCK:
        d = resolve_dispute(dispute_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_dispute(d))
