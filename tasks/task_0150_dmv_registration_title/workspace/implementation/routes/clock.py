"""Admin clock-advance endpoint — drives unpaid-timeout sweep."""

from flask import Blueprint

from config import ROLE_PLATFORM_ADMIN
from db import store
from middleware import parse_json_body, require_auth
from response import success
from routes._helpers import require_field, require_iso8601
from services.engine import sweep_unpaid_timeout

clock_bp = Blueprint("clock", __name__)


@clock_bp.route("/_clock/advance", methods=["POST"])
@require_auth(allowed_roles=[ROLE_PLATFORM_ADMIN])
def advance_clock():
    body = parse_json_body()
    to_dt = require_iso8601(require_field(body, "to"), "to")
    with store.lock:
        store.set_clock(to_dt)
        # Sweep unpaid-timeout reverts after advancing the clock
        sweep_unpaid_timeout(store.now())
    # Output null per SCAFFOLD endpoint listing; spec PRD §2.2 says empty {} for "no data"
    return success({})
