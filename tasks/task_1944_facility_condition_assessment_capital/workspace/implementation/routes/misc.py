"""RefreshCycle close, ConditionSnapshot listing, and the test-driving
logical-clock endpoint."""

from flask import Blueprint, request

import db
from clock import logical_clock, parse_iso
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PRECONDITION_UNMET,
    raise_error,
)
from middleware import auth
from response import ok_object
from services.core import (
    get_or_404,
    list_response,
    new_record,
    pub,
    touch,
)
from util import body, v_str

bp = Blueprint("misc", __name__)


@bp.post("/fca/refresh-cycles/<cycle_id>/close")
def close_refresh_cycle(cycle_id):
    auth("Consultant")
    cycle = get_or_404(db.refresh_cycles, cycle_id, "RefreshCycle")
    # Priority 5: state legality
    if cycle["status"] != "OPEN":
        raise_error(
            ERR_INVALID_STATE,
            f"RefreshCycle status {cycle['status']} does not permit close",
        )
    fac = db.facilities[cycle["facility_id"]]
    # Priority 13: every non-RETIRED system must have been assessed in this
    # cycle's epoch
    for system in db.asset_systems.values():
        if (
            system["facility_id"] == fac["id"]
            and system["status"] != "RETIRED"
            and system["last_assessed_epoch"] != cycle["epoch"]
        ):
            raise_error(
                ERR_PRECONDITION_UNMET,
                "Every non-RETIRED asset system must be assessed in this epoch before close",
            )
    cycle["status"] = "CLOSED"
    touch(cycle)
    # Ratify the facility's data currency and automatically open the next
    # cycle.
    fac["assessment_epoch"] = cycle["epoch"]
    touch(fac)
    nxt = new_record()
    nxt.update(
        {
            "facility_id": fac["id"],
            "epoch": cycle["epoch"] + 1,
            "status": "OPEN",
            "opened_at": logical_clock.now_iso(),
        }
    )
    db.refresh_cycles[nxt["id"]] = nxt
    return ok_object(pub(cycle))


@bp.get("/fca/condition-snapshots")
def list_condition_snapshots():
    auth()
    records = list(db.condition_snapshots.values())
    asset_system_id = request.args.get("asset_system_id")
    if asset_system_id is not None:
        records = [r for r in records if r["asset_system_id"] == asset_system_id]
    epoch_raw = request.args.get("epoch")
    if epoch_raw is not None:
        try:
            epoch = int(epoch_raw)
            records = [r for r in records if r["epoch"] == epoch]
        except ValueError:
            pass
    return list_response(records)


@bp.post("/fca/_clock/set_current_utc")
def set_current_utc():
    auth("Consultant")
    data = body()
    to_iso8601 = v_str(data, "to_iso8601")
    parsed = parse_iso(to_iso8601)
    if parsed is None:
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 instant")
    logical_clock.set(to_iso8601, parsed)
    return ok_object({"current_utc": logical_clock.raw})
