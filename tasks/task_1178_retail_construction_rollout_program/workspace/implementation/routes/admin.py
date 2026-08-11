"""Test-driving capabilities: the logical clock and the time-based sweep."""
from flask import Blueprint

import clock
from db import store
from middleware import authed
from response import ok
from services.forecast import recompute_commitment
from util import iso_dt, parse_date, sort_key
from validate import json_body, req_str

bp = Blueprint("admin", __name__)


@bp.route("/rollout/_clock/set_current_utc", methods=["POST"], strict_slashes=False)
@authed(["ProgramDirector"])
def set_clock():
    body = json_body()
    raw = req_str(body, "to_iso8601")
    try:
        dt = clock.set_now(raw)
    except (ValueError, TypeError):
        from errors import invalid_request
        invalid_request("to_iso8601 must be an ISO 8601 datetime")
    return ok({"current_utc": iso_dt(dt)})


@bp.route("/rollout/_sweeps/time-based", methods=["POST"], strict_slashes=False)
@authed(["ProgramDirector"])
def sweep_time_based():
    today = clock.today()
    expired_ids = []
    for permit in sorted(store.permits.values(), key=sort_key):
        if permit["status"] != "ISSUED":
            continue
        if permit["expires_on"] is not None and today >= parse_date(permit["expires_on"]):
            permit["status"] = "EXPIRED"
            from util import bump
            bump(permit)
            expired_ids.append(permit["id"])
    recomputed_ids = []
    for commitment in sorted(store.commitments.values(), key=sort_key):
        if commitment["protection_posture"] == "MET":
            continue  # terminal commitments are not recomputed
        site = store.sites.get(commitment["site_id"])
        if site is None or site["status"] in ("OPEN", "REMOVED"):
            continue
        recompute_commitment(commitment)
        recomputed_ids.append(commitment["id"])
    return ok({
        "expired_permit_ids": expired_ids,
        "recomputed_commitment_ids": recomputed_ids,
    })
