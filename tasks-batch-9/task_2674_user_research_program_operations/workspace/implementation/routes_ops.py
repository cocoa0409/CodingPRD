"""The two test-driving endpoints: the logical clock and the retention sweep."""
from flask import Blueprint

from auth import require_roles
from cascade import retention_sweep
from clock import clock, iso
from envelope import ok
from validators import body, req_datetime

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("ResearchOpsAdmin")
def set_clock():
    data = body()
    instant = req_datetime(data, "to_iso8601")
    clock.set(instant)
    return ok({"current_utc": iso(clock.now())})


@bp.post("/_ops/retention-sweep")
@require_roles("ResearchOpsAdmin", "PrivacyOfficer")
def sweep():
    return ok(retention_sweep())
