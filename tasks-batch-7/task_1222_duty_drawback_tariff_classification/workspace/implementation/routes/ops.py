"""Ops sweep and the logical-clock test-driving endpoint (PRD §2.8)."""
from flask import Blueprint

from calc import measure_matches_entry, recompute_entry, touch
from db import STORE, logical_now, set_logical_clock
from errors import ERR_INVALID_REQUEST, raise_err
from middleware import authenticate, get_body, require_role
from response import success_object
from serializers import sorted_by_creation
from util import fmt_dt, parse_dt

bp = Blueprint("ops", __name__)


@bp.route("/customs/ops/run_sweep", methods=["POST"])
def run_sweep():
    _, role = authenticate()
    require_role(role, {"FirmAdmin"})
    get_body()
    now = logical_now()

    # Expire ACTIVE measures whose effective_to has been reached (inclusive).
    expired_measure_ids = []
    touched_entry_ids = []
    for measure in sorted_by_creation(STORE["tariff_measures"].values()):
        if measure["status"] != "ACTIVE":
            continue
        if measure["effective_to"] is not None and now >= measure["effective_to"]:
            matching = [e for e in STORE["import_entries"].values()
                        if measure_matches_entry(measure, e)]
            measure["status"] = "EXPIRED"
            touch(measure)
            expired_measure_ids.append(measure["id"])
            for entry in matching:
                if entry["id"] not in touched_entry_ids:
                    touched_entry_ids.append(entry["id"])
    for entry_id in touched_entry_ids:
        entry = STORE["import_entries"][entry_id]
        recompute_entry(entry)
        touch(entry)

    # Flip due RETAINED records to ELIGIBLE_FOR_DESTRUCTION (inclusive).
    eligible_record_ids = []
    for record in sorted_by_creation(STORE["compliance_records"].values()):
        if record["status"] != "RETAINED":
            continue
        if record["retention_until"] is not None and now >= record["retention_until"]:
            record["status"] = "ELIGIBLE_FOR_DESTRUCTION"
            touch(record)
            eligible_record_ids.append(record["id"])

    return success_object({
        "expired_measure_ids": expired_measure_ids,
        "eligible_record_ids": eligible_record_ids,
    })


@bp.route("/customs/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"FirmAdmin"})
    body = get_body()
    raw = body.get("to_iso8601")
    if raw is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: to_iso8601")
    try:
        target = parse_dt(raw)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime")
    set_logical_clock(target)
    return success_object({"current_utc": fmt_dt(logical_now())})
