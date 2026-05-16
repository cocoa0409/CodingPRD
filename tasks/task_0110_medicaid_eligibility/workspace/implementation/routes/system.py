"""System test-driving routes — /_clock/advance and /_sweep/redeterminations (PRD §2.11)."""

from flask import Blueprint, request

from core.auth import require_roles
from core.clock import CLOCK
from core.envelope import success_object
from core.errors import raise_error
from core.store import lock
from core.timeutils import parse_iso
from core.validation import require_body, require_field
from services.cascade import expire_emergencies_and_revert, redetermination_sweep


bp = Blueprint("system", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("PolicyAdmin")
def advance_clock():
    body = require_body(request)
    to = require_field(body, "to", kind="string")
    target = parse_iso(to, "to")
    prev = CLOCK.now()
    if target < prev:
        raise_error("ERR_INVALID_REQUEST", "to must not be earlier than current clock_now")
    with lock():
        CLOCK.advance_to(target)
        # Side effects: revert CONTINUOUS_COVERAGE → ACTIVE if no covering emergency remains active
        expire_emergencies_and_revert(prev)
    return success_object({})


@bp.route("/_sweep/redeterminations", methods=["POST"])
@require_roles("PolicyAdmin")
def sweep_redeterminations():
    with lock():
        redetermination_sweep()
    return success_object({})
