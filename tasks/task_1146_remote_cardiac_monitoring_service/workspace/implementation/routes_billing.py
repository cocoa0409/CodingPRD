"""Billing periods: generate, submit, propose/approve adjustments."""
from datetime import timedelta

import db
from bp import bp
from db import base_record, touch
from domain import MIN_BILLABLE_DAYS, WINDOW_DAYS, price_lines
from errors import ApiError
from helpers import (READ_ROLES, auth, body, pagination, req_int, req_str,
                     require, sorted_by_creation)
from response import serialize, success, success_list

BLOCKING_STATUSES = {"ACCRUING", "READY", "SUBMITTED", "ADJUSTMENT_PROPOSED"}


def _get_period_or_404(period_id):
    rec = db.billing_periods.get(period_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Billing period not found")
    return rec


@bp.post("/v1/episodes/<episode_id>/billing-periods/generate")
def generate_billing_periods(episode_id):
    uid, role = auth()
    require(role, {"BillingSpecialist"})
    ep = db.episodes.get(episode_id)
    if ep is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND", 404, "Episode not found")
    end_of_service = ep["completed_at"] if ep["completed_at"] is not None \
        else ep["scheduled_end_at"]
    range_start, range_end = ep["started_at"], end_of_service
    for p in db.billing_periods.values():
        if p["episode_id"] != ep["id"] or p["status"] not in BLOCKING_STATUSES:
            continue
        # half-open overlap: a.start < b.end AND b.start < a.end
        if p["start_date"] < range_end and range_start < p["end_date"]:
            raise ApiError("ERR_BILLING_WINDOW_OVERLAP", 409,
                           "Existing non-terminal billing period overlaps the range")
    created = []
    i = 0
    while True:
        start_i = ep["started_at"] + timedelta(days=WINDOW_DAYS * i)
        if not (start_i < end_of_service):
            break
        end_i = min(start_i + timedelta(days=WINDOW_DAYS), end_of_service)
        window_days = int((end_i - start_i).total_seconds() // 86400)
        _, _, provisional = price_lines(ep["monitor_type"], window_days)
        rec = base_record()
        rec.update({
            "episode_id": ep["id"],
            "period_index": i,
            "start_date": start_i,
            "end_date": end_i,
            "window_days": window_days,
            "billable_days": None,
            "provisional_total_cents": provisional,
            "tc_amount_cents": None,
            "pc_amount_cents": None,
            "total_amount_cents": None,
            "status": "ACCRUING",
            "submitted_total_cents": None,
            "proposed_delta_cents": None,
            "proposed_by_user_id": None,
            "approved_adjustment_cents": 0,
            "approved_by_user_id": None,
            "recognized_total_cents": None,
        })
        db.billing_periods[rec["id"]] = rec
        created.append(rec)
        i += 1
    return success([serialize(x) for x in created], 201, response_type="array")


@bp.get("/v1/billing-periods")
def list_billing_periods():
    uid, role = auth()
    require(role, READ_ROLES)
    limit, offset = pagination()
    from flask import request
    ep_f = request.args.get("episode_id")
    status_f = request.args.get("status")
    items = list(db.billing_periods.values())
    if ep_f is not None:
        items = [x for x in items if x["episode_id"] == ep_f]
    if status_f is not None:
        items = [x for x in items if x["status"] == status_f]
    return success_list(sorted_by_creation(items), limit, offset)


@bp.get("/v1/billing-periods/<period_id>")
def get_billing_period(period_id):
    uid, role = auth()
    require(role, READ_ROLES)
    return success(serialize(_get_period_or_404(period_id)))


@bp.post("/v1/billing-periods/<period_id>/submit")
def submit_billing_period(period_id):
    uid, role = auth()
    require(role, {"BillingSpecialist"})
    rec = _get_period_or_404(period_id)
    if rec["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", 409, "Only READY periods can be submitted")
    ep = db.episodes.get(rec["episode_id"])
    has_finalized = any(r for r in db.reports.values()
                        if r["episode_id"] == rec["episode_id"]
                        and r["status"] == "FINALIZED")
    if not has_finalized:
        raise ApiError("ERR_REPORT_NOT_FINALIZED", 422,
                       "Episode has no FINALIZED diagnostic report")
    if ep is not None and ep["compliance_status"] == "SUSPENDED":
        raise ApiError("ERR_EPISODE_SUSPENDED", 422,
                       "Episode compliance_status is SUSPENDED")
    if rec["billable_days"] is None or rec["billable_days"] < MIN_BILLABLE_DAYS:
        raise ApiError("ERR_BELOW_MINIMUM_BILLABLE_DAYS", 422,
                       "billable_days below minimum")
    rec["status"] = "SUBMITTED"
    rec["submitted_total_cents"] = rec["total_amount_cents"]
    rec["recognized_total_cents"] = rec["submitted_total_cents"]
    touch(rec)
    if ep is not None:
        ep["total_billed_cents"] += rec["total_amount_cents"]
        touch(ep)
    return success(serialize(rec))


@bp.post("/v1/billing-periods/<period_id>/propose-adjustment")
def propose_adjustment(period_id):
    uid, role = auth()
    require(role, {"BillingSpecialist"})
    rec = _get_period_or_404(period_id)
    d = body()
    delta = req_int(d, "delta_cents")
    reason = req_str(d, "reason")
    if rec["status"] not in ("SUBMITTED", "ADJUSTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Adjustments can only be proposed from SUBMITTED or ADJUSTED")
    if abs(delta) > rec["submitted_total_cents"]:
        raise ApiError("ERR_ADJUSTMENT_EXCEEDS_BILLED", 422,
                       "Adjustment magnitude exceeds submitted total")
    rec["status"] = "ADJUSTMENT_PROPOSED"
    rec["proposed_delta_cents"] = delta
    rec["proposed_by_user_id"] = uid
    touch(rec)
    return success(serialize(rec))


@bp.post("/v1/billing-periods/<period_id>/approve-adjustment")
def approve_adjustment(period_id):
    uid, role = auth()
    require(role, {"BillingSpecialist"})
    rec = _get_period_or_404(period_id)
    if rec["proposed_by_user_id"] is not None and rec["proposed_by_user_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Approver must differ from proposer")
    if rec["status"] != "ADJUSTMENT_PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "No pending adjustment to approve")
    rec["status"] = "ADJUSTED"
    rec["approved_adjustment_cents"] += rec["proposed_delta_cents"]
    rec["approved_by_user_id"] = uid
    rec["recognized_total_cents"] = (rec["submitted_total_cents"]
                                     + rec["approved_adjustment_cents"])
    touch(rec)
    return success(serialize(rec))
