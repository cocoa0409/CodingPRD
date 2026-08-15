"""Ops endpoints: the map sweep (PRD §3.9) and recognition event log."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_STEWARD_NOT_FOUND,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_recognition_event
from util import paginate, parse_pagination, sort_by_created_at

bp = Blueprint("ops", __name__)


@bp.route("/library-network/map/sweeps", methods=["POST"])
@require_roles("NetworkAdmin")
def map_sweep(_user_id, _role):
    counts = domain.run_sweep()
    return success_object(counts)


@bp.route("/library-network/stewards/<steward_id>/recognition-events", methods=["GET"])
@require_roles("Steward", "Moderator", "NetworkAdmin")
def list_recognition_events(steward_id: str, _user_id, _role):
    # Ownership (stage 2): stewards are restricted to their own history.
    if _role == "Steward" and _user_id != steward_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Steward may only view their own recognition log")
    if steward_id not in db.stewards:
        raise_err(ERR_STEWARD_NOT_FOUND, "No steward with the given id")
    limit, offset = parse_pagination()
    items = [
        serialize_recognition_event(e)
        for e in sort_by_created_at(list(db.recognition_events.values()))
        if e["steward_id"] == steward_id
    ]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)
