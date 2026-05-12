"""Test helper endpoints: clock advance + sweep run."""
from flask import Blueprint, request

import db
from errors import err
from clock import set_now, parse_iso, now, iso, to_utc_midnight
from middleware import require_auth
from response import success
from services.validation import require_body, require_iso
from services.rent import void_after
from services.unit_status import update_all
from services.tenant_ledger import recompute_all


bp = Blueprint("system", __name__)


@bp.post("/_clock/advance")
@require_auth(roles={"PropertyManager"})
def clock_advance():
    body = require_body(request)
    to = require_iso(body, "to")
    set_now(to)
    return success({"now": iso(now())})


@bp.post("/_sweep/run")
@require_auth(roles={"PropertyManager"})
def sweep_run():
    # 1) auto-VOID RentScheduleItem rows past terminated_on
    voided = 0
    for le in db.leases.values():
        if le.get("status") == "TERMINATED" and le.get("terminated_on"):
            voided += void_after(le["id"], parse_iso(le["terminated_on"]))
    # 2) recompute Unit.status
    update_all()
    # 3) recompute Tenant ledger
    recompute_all()
    return success({"voided_rent_schedule_items": voided})
