"""PlatformAdmin clock-advance capability."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_role
from ..envelope import success_object
from ..errors import ApiError
from ..validation import ensure_dict, require_num


bp = Blueprint("clock", __name__, url_prefix="/api")


@bp.post("/_clock/advance")
def advance_clock():
    require_role("PlatformAdmin")
    body = ensure_dict(request.get_json(silent=True) or {})
    seconds = require_num(body, "seconds", min_val=0)
    store = g.store
    with store.lock:
        store.clock.advance(seconds)
        # Sweep dispatch-offer timeouts: any Assignment in OFFERED for >= 60s.
        from ..services.dispatch import sweep_offer_timeouts
        sweep_offer_timeouts(store)
    return success_object(store.clock, {"now": store.clock.now_iso()})
