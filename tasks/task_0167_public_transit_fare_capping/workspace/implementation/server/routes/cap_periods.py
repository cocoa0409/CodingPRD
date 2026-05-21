"""FareCapPeriod list endpoint."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_auth
from ..clock import parse_iso
from ..common import paginate_list, parse_pagination
from ..response import respond
from ..serializers import cap_period_view
from ..store import store


bp = Blueprint("cap_periods", __name__, url_prefix="/transit/cap-periods")


@bp.get("")
@require_auth("Rider", "AgencyOfficer", "Auditor")
def list_cap_periods():
    limit, offset = parse_pagination()
    card_id = request.args.get("card_id")
    scope = request.args.get("scope")
    window_from = request.args.get("window_from")
    window_to = request.args.get("window_to")

    wfrom = parse_iso(window_from) if window_from else None
    wto = parse_iso(window_to) if window_to else None

    with store.lock:
        out = []
        for period in store.cap_periods.values():
            card = store.cards.get(period["card_id"])
            if g.user_role == "Rider":
                if card is None or card.get("rider_id") != g.user_id:
                    continue
            if card_id and period["card_id"] != card_id:
                continue
            if scope and period.get("scope") != scope:
                continue
            if wfrom or wto:
                ws = parse_iso(period["window_start"])
                if wfrom and ws < wfrom:
                    continue
                if wto and ws > wto:
                    continue
            out.append(period)
        out.sort(key=lambda p: (p.get("created_at", ""), p["id"]))
        sliced, meta = paginate_list(out, limit, offset)
        payload = [cap_period_view(p) for p in sliced]
    return respond(payload, 200, list_meta=meta)
