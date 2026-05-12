"""ReviewTask decisions, opinion aggregation, correction notices, and resubmits."""

from __future__ import annotations

from datetime import timedelta

from flask import g

import db
from config import REVIEW_TASK_TERMINAL, WORKING_DAY_SECONDS
from errors import (
    AppError,
    ERR_CORRECTION_EXPIRED,
    ERR_DEFICIENCY_INVALID,
    ERR_DEFICIENCY_UNRESOLVED,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_MAX_ROUNDS_REACHED,
    ERR_NOT_FOUND,
    ERR_REVIEW_OUT_OF_ORDER,
    ERR_VALIDATION_FAILED,
)
from services import audit, calculations
from services import validators as V


# ---------------------------------------------------------------------------
# ReviewTask decide
# ---------------------------------------------------------------------------

def decide_review_task(task_id: str, body: dict) -> dict:
    task = db.find_by_id("review_tasks", task_id)
    if not task:
        raise AppError(ERR_NOT_FOUND, f"ReviewTask not found: {task_id}", 404)

    # Permission: caller's department must match task department.
    if g.role not in {"Reviewer", "LeadReviewer"}:
        raise AppError(ERR_FORBIDDEN, "Role cannot decide review tasks", 403)
    if g.user_id != task["department_id"]:
        raise AppError(ERR_FORBIDDEN,
                       "Reviewer's department must match the task's department", 403)

    app = db.find_by_id("applications", task["application_id"])
    if not app:
        raise AppError(ERR_NOT_FOUND, "Parent application not found", 404)

    # Reviewer cannot also be the applicant.
    if app["applicant_user_id"] == g.user_id:
        raise AppError(ERR_FORBIDDEN,
                       "Applicant cannot also be a reviewer of own application", 403)

    body = V.must_be_dict(body)
    decision = V.require_str(body, "decision")
    if decision not in {"AGREED", "DISAGREED"}:
        raise AppError(ERR_VALIDATION_FAILED,
                       "decision must be AGREED or DISAGREED", 422)
    opinion_text = V.opt_str(body, "opinion_text", default=None)

    # Priority 4: state — Application must be UNDER_REVIEW; Task must be IN_PROGRESS.
    if app["review_status"] != "UNDER_REVIEW":
        raise AppError(ERR_INVALID_STATE,
                       f"Application not UNDER_REVIEW (status={app['review_status']})",
                       409)
    if task["status"] != "IN_PROGRESS":
        raise AppError(ERR_INVALID_STATE,
                       f"ReviewTask not IN_PROGRESS (status={task['status']})", 409)

    # Priority 5: SERIAL ordering.
    routing = app.get("pinned_routing_snapshot") or {}
    if routing.get("mode") == "SERIAL":
        all_tasks = sorted(
            db.find_many("review_tasks", application_id=app["id"]),
            key=lambda t: t["stage_index"],
        )
        # Find the lowest stage_index that is PENDING or IN_PROGRESS.
        candidate = None
        for t in all_tasks:
            if t["status"] in {"PENDING", "IN_PROGRESS"}:
                candidate = t
                break
        if not candidate or candidate["id"] != task["id"]:
            raise AppError(ERR_REVIEW_OUT_OF_ORDER,
                           "Cannot decide a stage before its predecessor", 409)

    # No OPEN CorrectionNotice.
    notices = db.find_many("correction_notices", application_id=app["id"])
    if any(n["status"] == "OPEN" for n in notices):
        raise AppError(ERR_INVALID_STATE,
                       "Cannot decide while an OPEN CorrectionNotice exists", 409)

    from services import occ
    occ.check(task, body)

    # Apply decision.
    db.update("review_tasks", task_id, {
        "status": decision,
        "opinion_text": opinion_text,
        "decided_at": db.now_iso(),
    })
    audit.write("REVIEW_DECIDE", "ReviewTask", task_id,
                {"decision": decision, "application_id": app["id"]})

    # SERIAL: promote next stage to IN_PROGRESS on AGREED.
    if routing.get("mode") == "SERIAL" and decision == "AGREED":
        next_idx = task["stage_index"] + 1
        next_task = next(
            (t for t in db.find_many("review_tasks", application_id=app["id"])
             if t["stage_index"] == next_idx),
            None,
        )
        if next_task and next_task["status"] == "PENDING":
            stages = routing["stages"]
            sla_days = stages[next_idx]["sla_days"]
            target = db.now_dt() + timedelta(seconds=sla_days * WORKING_DAY_SECONDS)
            db.update("review_tasks", next_task["id"], {
                "status": "IN_PROGRESS",
                "stage_due_at": db.format_ts(target),
            })

    # Trigger aggregation.
    verdict = aggregate_opinions(app["id"])
    if verdict == "AGREED":
        _drive_to_approved(app["id"])
    elif verdict == "DISAGREED":
        _drive_to_rejected(app["id"])

    return db.find_by_id("review_tasks", task_id)


# ---------------------------------------------------------------------------
# Opinion aggregation
# ---------------------------------------------------------------------------

def aggregate_opinions(app_id: str) -> str:
    app = db.find_by_id("applications", app_id)
    routing = app.get("pinned_routing_snapshot") or {}
    mode = routing.get("mode")
    rule = routing.get("aggregation_rule")
    tasks = sorted(
        db.find_many("review_tasks", application_id=app_id),
        key=lambda t: (t["stage_index"], t.get("created_at") or ""),
    )
    if mode == "SERIAL":
        if any(t["status"] == "DISAGREED" for t in tasks):
            return "DISAGREED"
        if all(t["status"] == "AGREED" for t in tasks):
            return "AGREED"
        return "PENDING"

    # PARALLEL
    non_skipped = [t for t in tasks if t["status"] != "SKIPPED"]
    if rule == "ALL_AGREE":
        if any(t["status"] == "DISAGREED" for t in non_skipped):
            return "DISAGREED"
        if non_skipped and all(t["status"] == "AGREED" for t in non_skipped):
            return "AGREED"
        return "PENDING"
    if rule == "MAJORITY":
        agreed = sum(1 for t in non_skipped if t["status"] == "AGREED")
        disagreed = sum(1 for t in non_skipped if t["status"] == "DISAGREED")
        if agreed + disagreed == len(non_skipped) and non_skipped:
            return "AGREED" if agreed > disagreed else "DISAGREED"
        return "PENDING"
    if rule == "LEAD_DECIDES":
        lead = next((t for t in non_skipped if t.get("is_lead")), None)
        if lead and lead["status"] == "AGREED":
            return "AGREED"
        if lead and lead["status"] == "DISAGREED":
            return "DISAGREED"
        return "PENDING"
    return "PENDING"


def _drive_to_approved(app_id: str) -> None:
    app = db.find_by_id("applications", app_id)
    if app["review_status"] != "UNDER_REVIEW":
        return
    db.update("applications", app_id, {"review_status": "APPROVED"})
    # Cascade: any non-terminal ReviewTask -> SKIPPED. (For SERIAL routing, later
    # stages may still be PENDING when an aggregator returns AGREED for SERIAL only
    # if all decided AGREED — but in case any remain non-terminal, skip them.)
    for t in db.find_many("review_tasks", application_id=app_id):
        if t["status"] not in REVIEW_TASK_TERMINAL:
            db.update("review_tasks", t["id"], {"status": "SKIPPED"})
    from services import certificate
    certificate.issue_certificate_for_application(app_id)
    audit.write("APPROVE", "Application", app_id, {})


def _drive_to_rejected(app_id: str) -> None:
    app = db.find_by_id("applications", app_id)
    if app["review_status"] != "UNDER_REVIEW":
        return
    version = db.find_by_id("matter_versions", app["matter_version_id"])
    updates = {"review_status": "REJECTED"}
    if app["payment_status"] == "PAID" and version["fee_amount_cents"] > 0:
        updates["payment_status"] = "REFUNDED"
    db.update("applications", app_id, updates)
    for t in db.find_many("review_tasks", application_id=app_id):
        if t["status"] not in REVIEW_TASK_TERMINAL:
            db.update("review_tasks", t["id"], {"status": "SKIPPED"})
    audit.write("REJECT", "Application", app_id, {})


# ---------------------------------------------------------------------------
# Correction notices
# ---------------------------------------------------------------------------

def issue_correction_notice(app_id: str, body: dict) -> dict:
    app = db.find_by_id("applications", app_id)
    if not app:
        raise AppError(ERR_NOT_FOUND, f"Application not found: {app_id}", 404)
    if g.role not in {"Reviewer", "LeadReviewer"}:
        raise AppError(ERR_FORBIDDEN,
                       "Only Reviewer or LeadReviewer may issue corrections", 403)
    if app["applicant_user_id"] == g.user_id:
        raise AppError(ERR_FORBIDDEN,
                       "Applicant cannot also be reviewer of own application", 403)

    body = V.must_be_dict(body)

    # Priority 4: Application must be UNDER_REVIEW; issuing task must be IN_PROGRESS.
    if app["review_status"] != "UNDER_REVIEW":
        raise AppError(ERR_INVALID_STATE,
                       f"Cannot issue correction; application status {app['review_status']}",
                       409)

    issued_by_review_task_id = V.require_str(body, "issued_by_review_task_id")
    task = db.find_by_id("review_tasks", issued_by_review_task_id)
    if not task or task["application_id"] != app_id:
        raise AppError(ERR_NOT_FOUND,
                       f"ReviewTask not found: {issued_by_review_task_id}", 404)
    if task["department_id"] != g.user_id:
        raise AppError(ERR_FORBIDDEN,
                       "Issuing reviewer must own the review task's department", 403)
    if task["status"] != "IN_PROGRESS":
        raise AppError(ERR_INVALID_STATE,
                       f"Issuing ReviewTask must be IN_PROGRESS (got {task['status']})",
                       409)

    # Priority 11: max-rounds.
    version = db.find_by_id("matter_versions", app["matter_version_id"])
    if app["correction_round"] >= version["max_correction_rounds"]:
        raise AppError(ERR_MAX_ROUNDS_REACHED,
                       "max_correction_rounds reached", 409)

    # Priority 16: deficiencies well-formed.
    deficiencies = body.get("deficiencies")
    if not isinstance(deficiencies, list) or len(deficiencies) == 0:
        raise AppError(ERR_DEFICIENCY_INVALID,
                       "deficiencies must be a non-empty array", 422)
    required_ids = set(version["required_material_template_ids"])
    norm = []
    for d in deficiencies:
        if not isinstance(d, dict):
            raise AppError(ERR_DEFICIENCY_INVALID,
                           "each deficiency must be an object", 422)
        tid = d.get("material_template_id")
        reason = d.get("reason")
        if not isinstance(tid, str) or tid not in required_ids:
            raise AppError(ERR_DEFICIENCY_INVALID,
                           f"deficiency.material_template_id must be in pinned required set",
                           422)
        if not isinstance(reason, str) or not reason:
            raise AppError(ERR_DEFICIENCY_INVALID,
                           "deficiency.reason must be a non-empty string", 422)
        norm.append({"material_template_id": tid, "reason": reason})

    # Compute due_at.
    issued_at = db.now_iso()
    due_seconds = version["correction_window_days"] * WORKING_DAY_SECONDS
    due_at_dt = db.now_dt() + timedelta(seconds=due_seconds)
    due_at = db.format_ts(due_at_dt)

    new_round = app["correction_round"] + 1
    notice = db.insert("correction_notices", {
        "application_id": app_id,
        "round_number": new_round,
        "deficiencies": norm,
        "issued_by_review_task_id": issued_by_review_task_id,
        "issued_at": issued_at,
        "due_at": due_at,
        "status": "OPEN",
        "resolved_at": None,
    })

    # Mutate Application: AWAITING_CORRECTION + bump round.
    db.update("applications", app_id, {
        "review_status": "AWAITING_CORRECTION",
        "correction_round": new_round,
    })
    audit.write("CORRECTION_ISSUE", "Application", app_id,
                {"notice_id": notice["id"]})
    return notice


def list_correction_notices(app_id: str, status_filter: str | None,
                            limit: int, offset: int):
    if not db.find_by_id("applications", app_id):
        raise AppError(ERR_NOT_FOUND, f"Application not found: {app_id}", 404)
    rows = db.find_many("correction_notices", application_id=app_id)
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter]
    rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    return rows[offset:offset + limit], total


def resubmit_correction(app_id: str, cid: str, body: dict) -> dict:
    app = db.find_by_id("applications", app_id)
    if not app:
        raise AppError(ERR_NOT_FOUND, f"Application not found: {app_id}", 404)
    notice = db.find_by_id("correction_notices", cid)
    if not notice or notice["application_id"] != app_id:
        raise AppError(ERR_NOT_FOUND, f"CorrectionNotice not found: {cid}", 404)

    if g.role != "Applicant":
        raise AppError(ERR_FORBIDDEN, "Only the Applicant may resubmit", 403)
    if app["applicant_user_id"] != g.user_id:
        raise AppError(ERR_FORBIDDEN,
                       "Only the application's applicant may resubmit", 403)

    body = V.must_be_dict(body)

    # Priority 4: state — application must be AWAITING_CORRECTION.
    if app["review_status"] != "AWAITING_CORRECTION":
        raise AppError(ERR_INVALID_STATE,
                       f"Application not AWAITING_CORRECTION (status={app['review_status']})",
                       409)
    if notice["status"] != "OPEN":
        raise AppError(ERR_INVALID_STATE,
                       f"CorrectionNotice status is {notice['status']}", 409)

    # Priority 10: temporal — now <= due_at.
    now_dt = db.now_dt()
    due_dt = db.parse_iso(notice["due_at"])
    if now_dt > due_dt:
        raise AppError(ERR_CORRECTION_EXPIRED,
                       "Correction window expired", 409)

    # PRD §3.6: resubmit takes "an updated submitted_materials array". PRD does
    # not require non-emptiness as a separate format check — an empty array is
    # a valid shape that trivially fails the priority-12 deficiency-coverage
    # check below, surfacing ERR_DEFICIENCY_UNRESOLVED.
    submitted_materials = V.require_list(body, "submitted_materials", non_empty=False)
    submitted_ids = []
    for entry in submitted_materials:
        if not isinstance(entry, dict):
            raise AppError(ERR_VALIDATION_FAILED,
                           "submitted_materials entries must be objects", 422)
        tid = entry.get("material_template_id")
        if not isinstance(tid, str):
            raise AppError(ERR_VALIDATION_FAILED,
                           "material_template_id required on each entry", 422)
        submitted_ids.append(tid)
    submitted_set = set(submitted_ids)

    # Priority 12: every deficiency addressed.
    for d in notice["deficiencies"]:
        if d["material_template_id"] not in submitted_set:
            raise AppError(ERR_DEFICIENCY_UNRESOLVED,
                           f"Deficiency for {d['material_template_id']} not addressed",
                           422)

    # Apply: notice -> RESOLVED.
    issued_dt = db.parse_iso(notice["issued_at"])
    paused_seconds = int((now_dt - issued_dt).total_seconds())
    db.update("correction_notices", cid, {
        "status": "RESOLVED",
        "resolved_at": db.format_ts(now_dt),
    })

    # Application: total_paused_seconds += paused; review_status -> UNDER_REVIEW.
    new_paused = app["total_paused_seconds"] + paused_seconds
    db.update("applications", app_id, {
        "review_status": "UNDER_REVIEW",
        "total_paused_seconds": new_paused,
    })
    # Recompute deadline_at.
    fresh = db.find_by_id("applications", app_id)
    version = db.find_by_id("matter_versions", app["matter_version_id"])
    deadline = calculations.derive_application_deadline(fresh, version, "committed")
    db.update("applications", app_id, {"deadline_at": deadline})

    # Touch (bump version) for previously-paused review tasks — they "resume".
    # The status didn't actually change, but per scaffold cascade rules each child
    # mutation should bump version+updated_at. We touch all IN_PROGRESS tasks.
    for t in db.find_many("review_tasks", application_id=app_id):
        if t["status"] == "IN_PROGRESS":
            db.touch("review_tasks", t["id"])

    audit.write("CORRECTION_RESUBMIT", "Application", app_id,
                {"notice_id": cid})
    return db.find_by_id("correction_notices", cid)
