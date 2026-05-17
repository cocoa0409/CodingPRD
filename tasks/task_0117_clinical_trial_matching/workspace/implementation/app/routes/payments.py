"""Payment listing."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import (
    ROLE_COORD,
    ROLE_PARTICIPANT_SELF,
    ROLE_PI,
    enforce_self_ownership,
    require_roles,
)
from ..helpers import paginate, parse_pagination
from ..responses import listing
from ..services.lookups import get_participant, payments_for_participant
from ..services.serialize import serialize_payment
from ..store import store

bp = Blueprint("payments", __name__)


@bp.get("/participants/<participant_id>/payments")
@require_roles(ROLE_PI, ROLE_COORD, ROLE_PARTICIPANT_SELF)
def list_payments(participant_id: str, **caller):
    enforce_self_ownership(participant_id, caller["_caller_id"], caller["_caller_role"])
    limit, offset = parse_pagination()
    kind_filter = request.args.get("kind")
    with store().lock:
        get_participant(participant_id)
        rows = payments_for_participant(participant_id)
        if kind_filter:
            rows = [r for r in rows if r["kind"] == kind_filter]
        total = len(rows)
        page = paginate(rows, limit, offset)
        items = [serialize_payment(p) for p in page]
    return listing(items, total, limit, offset)
