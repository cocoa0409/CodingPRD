"""Delinquency event endpoints — PRD §3.12."""
from __future__ import annotations

from flask import Blueprint

from config import (
    ROLE_COLLECTIONS_AGENT,
    ROLE_FINANCE_MANAGER,
    ROLE_PLATFORM_ADMIN,
)
from db import store
from middleware import require_auth
from response import list_success
from routes._helpers import (
    paginate,
    parse_pagination,
    sort_by_created_at,
)
from services.engine import get_customer_or_404
from services.serializers import serialize_delinquency_event

bp = Blueprint("delinquency_events", __name__)


@bp.get("/customers/<customer_id>/delinquency-events")
@require_auth([ROLE_PLATFORM_ADMIN, ROLE_COLLECTIONS_AGENT, ROLE_FINANCE_MANAGER])
def list_delinquency_events(customer_id):
    get_customer_or_404(customer_id)
    limit, offset = parse_pagination()

    items = [
        e for e in store.delinquency_events.values()
        if e["customer_id"] == customer_id
    ]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success(
        [serialize_delinquency_event(e) for e in page], limit, offset, total
    )
