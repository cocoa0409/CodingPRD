"""TimeEntry endpoints and lifecycle (PRD 3.11)."""
from flask import Blueprint, request

import db
from common import (get_json_body, get_or_404, new_record, paginate,
                    parse_pagination, ref_or_404, require_enum, require_number, touch)
from errors import err
from middleware import authorize
from response import success
from services import calculations as calc, ledger
from services.serialize import time_entry_out

bp = Blueprint("time_entries", __name__)

WORK_TYPES = {"STRATEGY", "WRITING", "OUTREACH", "MONITORING", "CRISIS"}
TIME_ENTRY_STATUSES = {"SUBMITTED", "APPROVED", "VOID"}


def _recompute_campaign(campaign_id):
    if campaign_id is None:
        return
    campaign = db.campaigns.get(campaign_id)
    if campaign is not None:
        ledger.recompute_campaign_ledger(campaign)
        touch(campaign)


@bp.post("/agency/time-entries")
@authorize(["AccountManager", "MediaSpecialist", "SchedulingCoordinator"])
def create_time_entry():
    body = get_json_body()
    retainer_period_id = body.get("retainer_period_id")
    campaign_id = body.get("campaign_id")
    # Priority 4: FK existence (campaign_id nullable).
    period = ref_or_404(db.retainer_periods, retainer_period_id, "retainer_period_id")
    if campaign_id is not None:
        ref_or_404(db.campaigns, campaign_id, "campaign_id")
    # Priority 5: well-formedness.
    staff_id = body.get("staff_id")
    if not isinstance(staff_id, str) or staff_id.strip() == "":
        raise err("ERR_INVALID_REQUEST", "Field 'staff_id' must be a non-empty string")
    work_type = require_enum(body, "work_type", WORK_TYPES)
    billable_hours = require_number(body, "billable_hours", exclusive_min=0)

    # Priority 11: fiscal — period must be OPEN.
    if period["status"] != "OPEN":
        raise err("ERR_PERIOD_CLOSED", "Cannot log time against a CLOSED period")

    rec = new_record({
        "retainer_period_id": retainer_period_id,
        "campaign_id": campaign_id,
        "staff_id": staff_id,
        "work_type": work_type,
        "billable_hours": billable_hours,
        "cost_cents": 0,
        "status": "SUBMITTED",
    })
    db.time_entries[rec["id"]] = rec

    # Per-entry provisional cost at logging time (waterfall over included set).
    rec["cost_cents"] = calc.entry_provisional_cost_cents(period, rec)

    # Recompute the period's conserved quantities.
    ledger.recompute_period(period)
    return success(time_entry_out(rec), status=201)


@bp.get("/agency/time-entries/<time_entry_id>")
@authorize(["AccountManager", "MediaSpecialist", "SchedulingCoordinator", "PlatformAdmin"])
def get_time_entry(time_entry_id):
    rec = get_or_404(db.time_entries, time_entry_id)
    return success(time_entry_out(rec))


@bp.get("/agency/time-entries")
@authorize(["AccountManager", "MediaSpecialist", "SchedulingCoordinator", "PlatformAdmin"])
def list_time_entries():
    limit, offset = parse_pagination()
    retainer_period_id = request.args.get("retainer_period_id")
    campaign_id = request.args.get("campaign_id")
    status = request.args.get("status")
    if status is not None and status not in TIME_ENTRY_STATUSES:
        raise err("ERR_INVALID_REQUEST", "status filter invalid")
    records = []
    for r in db.time_entries.values():
        if retainer_period_id is not None and r["retainer_period_id"] != retainer_period_id:
            continue
        if campaign_id is not None and r.get("campaign_id") != campaign_id:
            continue
        if status is not None and r["status"] != status:
            continue
        records.append(r)
    page, meta = paginate(records, limit, offset)
    return success([time_entry_out(r) for r in page], pagination=meta)


@bp.post("/agency/time-entries/<time_entry_id>/approve")
@authorize(["AccountManager"])
def approve_time_entry(time_entry_id):
    rec = get_or_404(db.time_entries, time_entry_id)
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Time entry is not SUBMITTED")
    rec["status"] = "APPROVED"
    touch(rec)
    period = db.retainer_periods[rec["retainer_period_id"]]
    ledger.recompute_period(period)
    # Approving changes the period's frozen-bill totals; advance its version
    # so a concurrent close sees a stale view (PRD 2.7).
    touch(period)
    _recompute_campaign(rec.get("campaign_id"))
    return success(time_entry_out(rec))


@bp.post("/agency/time-entries/<time_entry_id>/void")
@authorize(["AccountManager"])
def void_time_entry(time_entry_id):
    rec = get_or_404(db.time_entries, time_entry_id)
    if rec["status"] not in ("SUBMITTED", "APPROVED"):
        raise err("ERR_INVALID_STATE", "Time entry cannot be voided from its current state")
    rec["status"] = "VOID"
    touch(rec)
    period = db.retainer_periods[rec["retainer_period_id"]]
    # Re-derive conserved quantities (hours_consumed subtracts this entry back).
    ledger.recompute_period(period)
    touch(period)
    _recompute_campaign(rec.get("campaign_id"))
    return success(time_entry_out(rec))
