"""RetainerPeriod endpoints and close (PRD 3.11, 2.7)."""
import re

from flask import Blueprint, request

import db
from common import (get_json_body, get_or_404, new_record, paginate,
                    parse_pagination, ref_or_404, require_int, require_str, touch)
from errors import err
from middleware import authorize
from response import success
from services import calculations as calc
from services.serialize import retainer_period_out

bp = Blueprint("retainer_periods", __name__)

PERIOD_STATUSES = {"OPEN", "CLOSED"}
_MONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}$")


@bp.post("/agency/retainer-periods")
@authorize(["AccountManager"])
def create_retainer_period():
    body = get_json_body()
    client_id = body.get("client_id")
    client = ref_or_404(db.clients, client_id, "client_id")
    period_month = require_str(body, "period_month")
    if not _MONTH_RE.match(period_month):
        raise err("ERR_INVALID_REQUEST", "period_month must match YYYY-MM")

    # Unique per client + period_month (PRD 3.11).
    for p in db.retainer_periods.values():
        if p["client_id"] == client_id and p["period_month"] == period_month:
            raise err("ERR_DUPLICATE_PERIOD",
                      "A retainer period already exists for this client and month")

    rec = new_record({
        "client_id": client_id,
        "period_month": period_month,
        "hours_cap": client["monthly_hours_cap"],
        "overage_rate_cents": client["overage_rate_cents"],
        "hours_consumed": 0,
        "provisional_total_cents": 0,
        "final_total_cents": None,
        "status": "OPEN",
    })
    db.retainer_periods[rec["id"]] = rec
    return success(retainer_period_out(rec), status=201)


@bp.get("/agency/retainer-periods/<retainer_period_id>")
@authorize(["AccountManager", "PlatformAdmin"])
def get_retainer_period(retainer_period_id):
    rec = get_or_404(db.retainer_periods, retainer_period_id)
    return success(retainer_period_out(rec))


@bp.get("/agency/retainer-periods")
@authorize(["AccountManager", "PlatformAdmin"])
def list_retainer_periods():
    limit, offset = parse_pagination()
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    if status is not None and status not in PERIOD_STATUSES:
        raise err("ERR_INVALID_REQUEST", "status filter invalid")
    records = []
    for r in db.retainer_periods.values():
        if client_id is not None and r["client_id"] != client_id:
            continue
        if status is not None and r["status"] != status:
            continue
        records.append(r)
    page, meta = paginate(records, limit, offset)
    return success([retainer_period_out(r) for r in page], pagination=meta)


@bp.post("/agency/retainer-periods/<retainer_period_id>/close")
@authorize(["AccountManager"])
def close_retainer_period(retainer_period_id):
    rec = get_or_404(db.retainer_periods, retainer_period_id)
    body = get_json_body()
    expected_version = require_int(body, "expected_retainer_period_version")

    # Priority 6: OCC version check (before state validity).
    if expected_version != rec["version"]:
        raise err("ERR_STALE_PERIOD_VERSION",
                  "expected_retainer_period_version does not match current version")

    # Priority 7: state validity.
    if rec["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Period is not OPEN")

    # Workflow precondition: no SUBMITTED entries remain.
    has_pending = any(
        te["retainer_period_id"] == rec["id"] and te["status"] == "SUBMITTED"
        for te in db.time_entries.values())
    if has_pending:
        raise err("ERR_PERIOD_HAS_PENDING_ENTRIES",
                  "Period has SUBMITTED time entries pending approval/void")

    rec["status"] = "CLOSED"
    rec["final_total_cents"] = calc.final_total_cents(rec)
    touch(rec)  # increments version by 1
    return success(retainer_period_out(rec))
