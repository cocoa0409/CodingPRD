"""System endpoints: deterministic-clock advance + budget day-rollover."""
from datetime import datetime, timezone
from flask import Blueprint

from .. import store
from ..auth import require_auth
from ..clock import advance_seconds, now, start_of_utc_day
from ..response import success
from ..validators import get_json_body, require_int
from ..services.billing import reaggregate_campaign


bp = Blueprint("system", __name__)


@bp.post("/_clock/advance")
@require_auth(["PlatformAdmin"])
def advance_clock():
    body = get_json_body()
    seconds = require_int(body, "seconds")
    # Snapshot the day before advancing, then check if we crossed a day.
    prev_day = now().date()
    info = advance_seconds(seconds)
    after_day = now().date()

    # If we crossed midnight, recompute today's spend for every campaign,
    # which can trigger BUDGET_EXHAUSTED → ACTIVE transitions.
    if prev_day != after_day:
        for camp in store.list_all("Campaign"):
            reaggregate_campaign(camp)
        # Also auto-end campaigns past their end_date
        from ..services.lifecycle import end_campaign_cascade
        for camp in store.list_all("Campaign"):
            ed = camp.get("end_date")
            if ed and camp.get("status") not in ("ENDED",):
                try:
                    cmp = ed if ed.endswith("Z") else ed
                    target = cmp
                    if target <= now().strftime("%Y-%m-%dT%H:%M:%S.000Z"):
                        end_campaign_cascade(camp)
                except Exception:
                    pass

    return success(info)
