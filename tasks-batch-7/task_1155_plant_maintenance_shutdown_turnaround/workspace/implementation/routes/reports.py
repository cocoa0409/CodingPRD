"""Daily cost/progress reports (PRD 3.8).

Drafting records contractor_id from the submitter's X-User-ID; submission
prices the lines (pinned per-line rounding, then sum; overhead tier keyed on
the turnaround's reported cost excluding this report); approval posts to the
ledger under SoD; void compensates the latest APPROVED posting.
"""
from flask import Blueprint, request

import db
from clock import logical_now
from errors import bad_request, conflict, cross_scope, forbidden, invalid_state, sod
from helpers import (actor, as_bool, as_date, as_num, as_str, body,
                     get_or_404, opt_field, paged, pagination_params,
                     req_field, require_roles, sorted_by_created)
from response import ok
from serialize import daily_report_out
from services import computed, pricing

bp = Blueprint("reports", __name__)

SUPERVISOR = ("ContractorSupervisor",)
CC = ("CostController",)


@bp.post("/turnarounds/<tid>/daily-reports")
def create_report(tid):
    uid, role = actor()
    require_roles(role, SUPERVISOR)
    get_or_404(db.turnarounds, tid, "Turnaround")
    b = body()
    report_date = as_date(req_field(b, "report_date"), "report_date")
    if report_date > logical_now().date():
        bad_request("report_date must not be after the current logical date")
    lines = req_field(b, "lines")
    if not isinstance(lines, list) or not lines:
        bad_request("lines must be a non-empty array")
    parsed_lines = []
    for line in lines:
        if not isinstance(line, dict):
            bad_request("each line must be an object")
        worker_id = as_str(req_field(line, "worker_id"), "lines.worker_id")
        shift_id = as_str(req_field(line, "shift_id"), "lines.shift_id")
        hours = as_num(req_field(line, "hours"), "lines.hours", gt=0)
        hazard = as_bool(req_field(line, "hazard_flag"), "lines.hazard_flag")
        parsed_lines.append({
            "worker_id": worker_id,
            "shift_id": shift_id,
            "hours": hours,
            "hazard_flag": hazard,
        })
    # Cross-scope (priority 6): every line's shift must belong to this
    # turnaround; every line's worker must belong to the submitting
    # contractor (contractor_id := X-User-ID).
    line_workers = []
    for line in parsed_lines:
        shift = db.shifts.get(line["shift_id"])
        if shift is None or shift["turnaround_id"] != tid:
            cross_scope("each line's shift_id must resolve within the same "
                        "turnaround")
        worker = db.workers.get(line["worker_id"])
        if worker is None or worker["contractor_id"] != uid:
            cross_scope("each line's worker must be employed by the "
                        "submitting contractor")
        line_workers.append(worker)
    # Safety gate (priority 9): every line worker must hold a live badge.
    for worker in line_workers:
        if worker["badge_status"] != "BADGED":
            conflict("ERR_BADGE_NOT_CLEARED",
                     "Every report-line worker must be BADGED")
    # Structural (priority 11): one non-VOIDED report per contractor per date.
    for r in db.daily_reports.values():
        if (r["turnaround_id"] == tid and r["contractor_id"] == uid
                and r["report_date"] == report_date.isoformat()
                and r["status"] != "VOIDED"):
            conflict("ERR_DUPLICATE_REPORT",
                     "A report already exists for this contractor and date")
    now = db.now_iso()
    r = db.create(db.daily_reports, {
        "id": db.mint_id(),
        "turnaround_id": tid,
        "contractor_id": uid,
        "report_date": report_date.isoformat(),
        "lines": parsed_lines,
        "line_costs_cents": None,
        "labor_cost_cents": None,
        "overhead_cents": None,
        "total_cost_cents": None,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    })
    return ok(daily_report_out(r), status=201)


@bp.get("/turnarounds/<tid>/daily-reports")
def list_reports(tid):
    actor()
    get_or_404(db.turnarounds, tid, "Turnaround")
    items = computed.reports_of(tid)
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    contractor_id = request.args.get("contractor_id")
    if contractor_id is not None:
        items = [r for r in items if r["contractor_id"] == contractor_id]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([daily_report_out(r) for r in page], pagination=meta)


@bp.get("/daily-reports/<rid>")
def get_report(rid):
    actor()
    r = get_or_404(db.daily_reports, rid, "DailyReport")
    return ok(daily_report_out(r))


@bp.post("/daily-reports/<rid>/submit")
def submit_report(rid):
    uid, role = actor()
    require_roles(role, SUPERVISOR)
    r = get_or_404(db.daily_reports, rid, "DailyReport")
    if r["contractor_id"] != uid:
        forbidden("Only the report's own contractor supervisor may submit it")
    if r["status"] != "DRAFT":
        invalid_state("Only a DRAFT report can be submitted")

    def shift_type_for(shift_id):
        shift = db.shifts.get(shift_id)
        return shift["shift_type"] if shift else "DAY"

    line_costs, labor = pricing.price_report(r, shift_type_for)
    # Overhead tier keyed on the turnaround's reported cost EXCLUDING this
    # candidate report (this report is not APPROVED, so the sum over OTHER
    # APPROVED reports is the turnaround's full reported figure).
    t = db.turnarounds.get(r["turnaround_id"])
    tier_base = computed.reported_cost_cents(r["turnaround_id"])
    overhead = pricing.overhead_cents(labor, tier_base)
    r["line_costs_cents"] = line_costs
    r["labor_cost_cents"] = labor
    r["overhead_cents"] = overhead
    r["total_cost_cents"] = labor + overhead
    r["submitted_by_user_id"] = uid
    r["status"] = "SUBMITTED"
    db.touch(r)
    return ok(daily_report_out(r))


@bp.post("/daily-reports/<rid>/approve")
def approve_report(rid):
    uid, role = actor()
    require_roles(role, CC)
    r = get_or_404(db.daily_reports, rid, "DailyReport")
    if r["status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED report can be approved")
    if uid == r["submitted_by_user_id"]:
        sod("The approver must differ from the submitter")
    r["status"] = "APPROVED"
    r["approved_by_user_id"] = uid
    db.touch(r)
    t = db.turnarounds.get(r["turnaround_id"])
    if t is not None:
        db.touch(t)  # ledger posting; forecast/posture recompute on the fly
    return ok(daily_report_out(r))


@bp.post("/daily-reports/<rid>/reject")
def reject_report(rid):
    _uid, role = actor()
    require_roles(role, CC)
    r = get_or_404(db.daily_reports, rid, "DailyReport")
    body()  # optional reason; no ledger effect
    if r["status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED report can be rejected")
    r["status"] = "DRAFT"
    db.touch(r)
    return ok(daily_report_out(r))


@bp.post("/daily-reports/<rid>/void")
def void_report(rid):
    _uid, role = actor()
    require_roles(role, CC)
    r = get_or_404(db.daily_reports, rid, "DailyReport")
    if r["status"] != "APPROVED":
        invalid_state("Only an APPROVED report can be voided")
    for other in db.daily_reports.values():
        if (other["id"] != rid and other["status"] == "APPROVED"
                and other["turnaround_id"] == r["turnaround_id"]
                and other["contractor_id"] == r["contractor_id"]
                and other["report_date"] > r["report_date"]):
            conflict("ERR_REPORT_SEQUENCE",
                     "A later-dated APPROVED report exists for this contractor")
    r["status"] = "VOIDED"
    db.touch(r)
    t = db.turnarounds.get(r["turnaround_id"])
    if t is not None:
        db.touch(t)  # ledger compensation; forecast/posture recompute
    return ok(daily_report_out(r))
