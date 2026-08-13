"""Audit trail read endpoint and the test-driving logical clock control."""
from flask import Blueprint, request

from db import DB, fmt_dt, now_dt, set_clock
from middleware import auth
from response import ok, ok_list
from services import event_view, get_case, paginate, sweep
from util import body, pagination_args, req_dt

bp = Blueprint("misc", __name__)


@bp.get("/hotline/cases/<cid>/case-status-events")
def list_events(cid):
    auth(
        [
            "IntakeSpecialist",
            "Investigator",
            "ComplianceOfficer",
            "AuditCommitteeMember",
            "EthicsPlatformAdmin",
        ]
    )
    get_case(cid)
    limit, offset = pagination_args()
    records = [e for e in DB["events"].values() if e["case_id"] == cid]
    event_type = request.args.get("event_type")
    if event_type is not None:
        records = [e for e in records if e["event_type"] == event_type]
    page, total = paginate(records, limit, offset)
    return ok_list([event_view(e) for e in page], total, limit, offset)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth(["EthicsPlatformAdmin"])
    data = body()
    target = req_dt(data, "to_iso8601")
    set_clock(target)
    # Deferred time-driven effects are applied synchronously, in one sweep,
    # before the response is returned.
    sweep()
    return ok({"current_utc": fmt_dt(now_dt())})
