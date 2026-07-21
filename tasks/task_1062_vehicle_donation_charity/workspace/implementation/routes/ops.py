"""Follow-up tasks, the operations sweep and the charity report (PRD section 3.10)."""

from flask import Blueprint, request

import db
import middleware as mw
import response as resp
from errors import ApiError
from services import domain

bp = Blueprint("ops", __name__)


@bp.get("/api/follow-up-tasks/<task_id>")
def get_task(task_id):
    mw.auth("IntakeAgent", "TitleClerk", "FinanceOfficer", "ProgramAdmin")
    rec = mw.resolve(db.follow_up_tasks, task_id, "ERR_TASK_NOT_FOUND")
    return resp.ok(rec)


@bp.post("/api/follow-up-tasks/<task_id>/complete")
def complete_task(task_id):
    mw.auth("ProgramAdmin")
    rec = mw.resolve(db.follow_up_tasks, task_id, "ERR_TASK_NOT_FOUND")
    data = mw.body()
    note = mw.req_string(data, "resolution_note")
    if rec["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError("ERR_INVALID_TASK_STATE", "This task is already done.")

    rec["status"] = "DONE"
    rec["resolution_note"] = note
    db.touch(rec)
    return resp.ok(rec)


@bp.post("/api/_ops/run-sweep")
def run_sweep():
    mw.auth("ProgramAdmin")
    clock = db.now()

    escalated = 0
    for task in db.ordered(list(db.follow_up_tasks.values())):
        if task["status"] == "OPEN" and task["due_utc"] <= clock:
            task["status"] = "ESCALATED"
            db.touch(task)
            escalated += 1

    stale = 0
    for title in db.ordered(list(db.title_records.values())):
        if title["state"] != "SUBMITTED" or title["submitted_at_utc"] is None:
            continue
        if clock - title["submitted_at_utc"] <= db.days(db.STALE_TITLE_DAYS):
            continue
        already = any(
            t["donation_id"] == title["donation_id"]
            and t["task_type"] == "TITLE_STALE"
            and t["status"] in ("OPEN", "ESCALATED")
            for t in db.follow_up_tasks.values()
        )
        if already:
            continue
        domain.create_task(
            title["donation_id"],
            "TITLE_STALE",
            "TitleClerk",
            clock + db.days(db.REMITTANCE_FOLLOWUP_DAYS),
        )
        stale += 1

    return resp.ok(
        {"escalated_task_count": escalated, "stale_title_task_count": stale}
    )


@bp.get("/api/reports/charity-summary")
def charity_summary():
    user_id, role = mw.auth("FinanceOfficer", "ProgramAdmin", "CharityAdmin")
    charity_id = request.args.get("charity_id")

    if role == "CharityAdmin" and charity_id is not None and charity_id != user_id:
        raise ApiError(
            "ERR_FORBIDDEN_OWNER", "Charity admins may only read their own summary."
        )
    if not charity_id:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'charity_id' is required.")

    charity = mw.resolve(db.charities, charity_id, "ERR_CHARITY_NOT_FOUND")

    own_donations = [
        d for d in db.donations.values() if d["charity_id"] == charity_id
    ]
    own_ids = {d["id"] for d in own_donations}
    accrued = [d for d in own_donations if d["payout_status"] == "ACCRUED"]

    signed_total = 0
    for entry in db.ledger_entries.values():
        if entry["donation_id"] is None or entry["donation_id"] not in own_ids:
            continue
        signed_total += (
            entry["amount_cents"]
            if entry["direction"] == "CREDIT"
            else -entry["amount_cents"]
        )

    return resp.ok(
        {
            "charity_id": charity_id,
            "pledged_balance_cents": charity["pledged_balance_cents"],
            "remitted_balance_cents": charity["remitted_balance_cents"],
            "accrued_donation_count": len(accrued),
            "unremitted_net_cents": sum(d["net_to_charity_cents"] for d in accrued),
            "ledger_signed_total": signed_total,
        }
    )
