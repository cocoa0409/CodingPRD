"""WorkOrder service: registration, classify, dispatch, reject, pause, resume, resolve, reopen, close."""

import hashlib

from errors import (
    AppError,
    ERR_VALIDATION, ERR_WORK_ORDER_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND, ERR_CATEGORY_UNKNOWN, ERR_ANONYMOUS_PII_LEAK,
    ERR_VERSION_CONFLICT, ERR_DUPLICATE_LINKED, ERR_INVALID_STATE,
    ERR_JURISDICTION_NO_DEPARTMENT, ERR_OPINIONS_INCOMPLETE,
    ERR_DISAGREEMENT_UNRESOLVED, ERR_SUPERVISION_OPEN, ERR_REOPEN_WINDOW_EXPIRED,
    ERR_ALREADY_PAUSED, ERR_NOT_PAUSED, ERR_FORBIDDEN, ERR_SURVEY_CHANNEL_FORBIDDEN,
    ERROR_STATUS,
)
import db
import validators as V
import clock
from flask import g

from services import category_rules as cr_svc
from services import audit as audit_svc
from services import work_order_calc as calc
from business_hours import add_business_hours, business_seconds_between

URGENCY_VALUES = {"LOW", "NORMAL", "HIGH", "CRITICAL"}
DUPLICATE_DETECTION_WINDOW_SECONDS = 600
REOPEN_WINDOW_BUSINESS_HOURS = 72


def get_work_order(wo_id: str) -> dict:
    wo = db.find_by_id("work_orders", wo_id)
    if not wo:
        raise AppError(ERR_WORK_ORDER_NOT_FOUND, "Work order not found",
                       ERROR_STATUS[ERR_WORK_ORDER_NOT_FOUND])
    return wo


def _validate_call_payload_create(body: dict):
    """Validation pipeline for POST /work-orders, in priority order."""
    anonymous = V.is_bool(body, "anonymous", optional=True, default=False)
    caller_name = body.get("caller_name", None)
    caller_phone = body.get("caller_phone", None)

    # priority 12: anonymous PII safety. Evaluated BEFORE field shape per validation table.
    if anonymous:
        if caller_name not in (None, "") or caller_phone not in (None, ""):
            raise AppError(ERR_ANONYMOUS_PII_LEAK, "Anonymous calls must not carry caller_name/phone",
                           ERROR_STATUS[ERR_ANONYMOUS_PII_LEAK])
    else:
        if not caller_phone:
            raise AppError(ERR_ANONYMOUS_PII_LEAK, "caller_phone required when not anonymous",
                           ERROR_STATUS[ERR_ANONYMOUS_PII_LEAK])

    # field shape for those that ARE present
    if caller_name is not None:
        V.is_str(body, "caller_name", min_len=1, max_len=80)
    if caller_phone is not None:
        V.is_str(body, "caller_phone", min_len=6, max_len=20, pattern=V.PHONE_RE)
    V.is_str(body, "jurisdiction_code", pattern=V.JURISDICTION_RE)
    category_code = V.is_str(body, "category_code", min_len=2, max_len=30, pattern=V.CATEGORY_RE)
    sub_category_code = V.is_str(body, "sub_category_code", min_len=2, max_len=30, pattern=V.CATEGORY_RE)
    V.is_str(body, "content_text", min_len=1, max_len=4000)
    if "audio_url" in body and body["audio_url"] is not None:
        V.is_str(body, "audio_url", min_len=0, max_len=500, pattern=V.URL_RE, allow_empty=True)
    urgency = V.is_enum(body, "urgency", URGENCY_VALUES, optional=True, default="NORMAL")

    return anonymous, urgency, category_code, sub_category_code


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _find_duplicate(caller_phone, anonymous: bool, content_text: str, category_code: str) -> dict:
    """Return an existing non-terminal WorkOrder matching duplicate-detection rules, or None."""
    now_dt = clock.now()
    terminal = {"CLOSED", "REJECTED"}
    if not anonymous and caller_phone:
        for wo in db.all_rows("work_orders"):
            if wo.get("anonymous"):
                continue
            if wo["status"] in terminal:
                continue
            if wo.get("caller_phone") != caller_phone:
                continue
            if wo.get("category_code") != category_code:
                continue
            reg = clock.parse_iso(wo["registered_at"])
            if (now_dt - reg).total_seconds() <= DUPLICATE_DETECTION_WINDOW_SECONDS:
                return wo
        return None
    elif anonymous:
        target_hash = _content_hash(content_text)
        for wo in db.all_rows("work_orders"):
            if not wo.get("anonymous"):
                continue
            if wo["status"] in terminal:
                continue
            if wo.get("category_code") != category_code:
                continue
            existing_hash = _content_hash(wo.get("content_text", ""))
            if existing_hash != target_hash:
                continue
            reg = clock.parse_iso(wo["registered_at"])
            if (now_dt - reg).total_seconds() <= DUPLICATE_DETECTION_WINDOW_SECONDS:
                return wo
        return None
    return None


def register_work_order(body: dict):
    """Create + duplicate detection. Returns (work_order, duplicate_of_id or None)."""
    anonymous, urgency, category_code, sub_category_code = _validate_call_payload_create(body)

    # priority 21: category pair existence
    rule = cr_svc.find_rule(category_code, sub_category_code)
    if rule is None:
        raise AppError(ERR_CATEGORY_UNKNOWN, "category pair unknown", ERROR_STATUS[ERR_CATEGORY_UNKNOWN])

    caller_name = body.get("caller_name") if not anonymous else None
    caller_phone = body.get("caller_phone") if not anonymous else None
    content_text = body["content_text"]
    audio_url = body.get("audio_url", "")
    jurisdiction_code = body["jurisdiction_code"]

    now_iso = clock.now_iso()
    diff = calc.difficulty_score(urgency, rule.get("difficulty_base", 1) or 1, joint_handling=False)
    pri = calc.priority_flag(urgency, diff)

    record = db.insert("work_orders", {
        "caller_name": caller_name,
        "caller_phone": caller_phone,
        "anonymous": bool(anonymous),
        "jurisdiction_code": jurisdiction_code,
        "category_code": category_code,
        "sub_category_code": sub_category_code,
        "content_text": content_text,
        "audio_url": audio_url if audio_url is not None else "",
        "urgency": urgency,
        "difficulty_score": diff,
        "classification_mode": "PENDING",
        "lead_department_id": None,
        "supporting_department_ids": [],
        "joint_handling": False,
        "status": "REGISTERED",
        "duplicate_of_id": None,
        "statutory_deadline_at": None,
        "committed_deadline_at": None,
        "pause_accumulated_seconds": 0,
        "pause_started_at": None,
        "warning_state": "NONE",
        "resolution_summary": None,
        "registered_at": now_iso,
        "closed_at": None,
        "priority_flag": pri,
    })
    # registered_at must equal created_at to the millisecond per PRD §3.2.
    record["registered_at"] = record["created_at"]

    # priority 24: duplicate detection (run AFTER record is created so race semantics hold).
    duplicate = _find_duplicate(caller_phone, anonymous, content_text, category_code)
    # Exclude self
    if duplicate is not None and duplicate["id"] != record["id"]:
        record["duplicate_of_id"] = duplicate["id"]
        # Append content_text to the original via a system note.
        duplicate["content_text"] = (duplicate.get("content_text") or "") + \
            f"\n[duplicate-link {record['id']}] {content_text}"
        db.bump(duplicate)

    audit_svc.write_audit("REGISTER", record["id"], {
        "duplicate_of_id": record["duplicate_of_id"],
        "anonymous": record["anonymous"],
        "category_code": category_code,
        "sub_category_code": sub_category_code,
        "urgency": urgency,
    })

    return record


def patch_work_order(wo_id: str, body: dict) -> dict:
    """PATCH /work-orders/{id} for a REGISTERED row (HotlineOperator)."""
    wo = get_work_order(wo_id)
    # OCC priority 22 — note the validations table has state checks at priority 8 before OCC (22).
    # State permission first.
    if wo["status"] != "REGISTERED":
        raise AppError(ERR_INVALID_STATE, "Can only amend REGISTERED work orders",
                       ERROR_STATUS[ERR_INVALID_STATE])

    # Build a merged body containing existing fields so anonymity validation makes sense.
    proposed = {
        "anonymous": wo.get("anonymous", False),
        "caller_name": wo.get("caller_name"),
        "caller_phone": wo.get("caller_phone"),
    }
    # If body explicitly provides anonymity-related fields, override. For PATCH we
    # don't accept anonymity changes (not in input list), but PII safety check
    # remains valid against existing state.

    # priority 21 category check (if category change requested)
    new_category = body.get("category_code", wo["category_code"])
    new_sub = body.get("sub_category_code", wo["sub_category_code"])
    if new_category != wo["category_code"] or new_sub != wo["sub_category_code"]:
        # field shape first via category validator below
        pass

    # OCC priority 22
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(wo.get("version", 0)):
            raise AppError(ERR_VERSION_CONFLICT, "Version conflict", ERROR_STATUS[ERR_VERSION_CONFLICT])

    # field shape (priority 23)
    if "content_text" in body and body["content_text"] is not None:
        V.is_str(body, "content_text", min_len=1, max_len=4000)
    if "audio_url" in body and body["audio_url"] is not None:
        V.is_str(body, "audio_url", min_len=0, max_len=500, pattern=V.URL_RE, allow_empty=True)
    if "urgency" in body and body["urgency"] is not None:
        V.is_enum(body, "urgency", URGENCY_VALUES)
    if "category_code" in body and body["category_code"] is not None:
        V.is_str(body, "category_code", min_len=2, max_len=30, pattern=V.CATEGORY_RE)
    if "sub_category_code" in body and body["sub_category_code"] is not None:
        V.is_str(body, "sub_category_code", min_len=2, max_len=30, pattern=V.CATEGORY_RE)

    # priority 21 category pair existence on change
    if new_category != wo["category_code"] or new_sub != wo["sub_category_code"]:
        rule = cr_svc.find_rule(new_category, new_sub)
        if rule is None:
            raise AppError(ERR_CATEGORY_UNKNOWN, "category pair unknown",
                           ERROR_STATUS[ERR_CATEGORY_UNKNOWN])

    updates = {}
    if "content_text" in body and body["content_text"] is not None:
        updates["content_text"] = body["content_text"]
    if "audio_url" in body and body["audio_url"] is not None:
        updates["audio_url"] = body["audio_url"]
    if "urgency" in body and body["urgency"] is not None:
        updates["urgency"] = body["urgency"]
    if "category_code" in body and body["category_code"] is not None:
        updates["category_code"] = body["category_code"]
    if "sub_category_code" in body and body["sub_category_code"] is not None:
        updates["sub_category_code"] = body["sub_category_code"]

    if updates:
        db.update_fields(wo, updates)

    # If category/sub-category/urgency changed, recompute difficulty_score and priority_flag.
    if any(k in updates for k in ("category_code", "sub_category_code", "urgency")):
        rule = cr_svc.find_rule(wo["category_code"], wo["sub_category_code"])
        diff = calc.difficulty_score(
            wo["urgency"], rule.get("difficulty_base", 1) or 1, joint_handling=False,
        )
        pri = calc.priority_flag(wo["urgency"], diff)
        wo["difficulty_score"] = diff
        wo["priority_flag"] = pri

    return wo


def list_work_orders(limit: int, offset: int, **filters) -> tuple[list[dict], int]:
    rows = list(db.all_rows("work_orders"))
    if filters.get("status") is not None:
        rows = [r for r in rows if r["status"] == filters["status"]]
    if filters.get("lead_department_id") is not None:
        rows = [r for r in rows if r.get("lead_department_id") == filters["lead_department_id"]]
    if filters.get("jurisdiction_code") is not None:
        rows = [r for r in rows if r["jurisdiction_code"] == filters["jurisdiction_code"]]
    if filters.get("category_code") is not None:
        rows = [r for r in rows if r["category_code"] == filters["category_code"]]
    ps = filters.get("period_start")
    pe = filters.get("period_end")
    if ps is not None:
        ps_dt = clock.parse_iso(ps)
        rows = [r for r in rows if clock.parse_iso(r["registered_at"]) >= ps_dt]
    if pe is not None:
        pe_dt = clock.parse_iso(pe)
        rows = [r for r in rows if clock.parse_iso(r["registered_at"]) < pe_dt]
    rows = sorted(rows, key=lambda r: r["created_at"])
    return rows[offset: offset + limit], len(rows)


def classify(wo_id: str, body: dict) -> dict:
    wo = get_work_order(wo_id)
    # priority 8 state
    if wo["status"] != "REGISTERED" or wo.get("duplicate_of_id") or wo.get("lead_department_id") is not None:
        raise AppError(ERR_INVALID_STATE, "Work order not in a state permitting classify",
                       ERROR_STATUS[ERR_INVALID_STATE])

    # category pair must resolve (priority 21)
    rule = cr_svc.find_rule(wo["category_code"], wo["sub_category_code"])
    if rule is None:
        raise AppError(ERR_CATEGORY_UNKNOWN, "category pair unknown", ERROR_STATUS[ERR_CATEGORY_UNKNOWN])

    # mode is a free hint per PRD; treat 'RULE_BASED' literal → RULE_BASED, anything else → AI_ASSISTED.
    mode_in = body.get("mode", "RULE_BASED") if isinstance(body, dict) else "RULE_BASED"
    classification_mode = "RULE_BASED" if mode_in == "RULE_BASED" else "AI_ASSISTED"

    # priority 14: jurisdiction resolution.
    lead_code = rule["lead_department_code"]
    wo_jur = wo["jurisdiction_code"]
    # Find all departments whose code == lead_code
    lead_candidates = [d for d in db.all_rows("departments") if d["code"] == lead_code]
    # Primary candidate: a department mapped to that code which lists wo_jur.
    primary = None
    for d in lead_candidates:
        if wo_jur in (d.get("jurisdiction_codes") or []):
            primary = d
            break
    lead_dept = primary
    if lead_dept is None:
        # Look for a citywide peer (jurisdiction_codes is empty list).
        for d in lead_candidates:
            if not (d.get("jurisdiction_codes") or []):
                lead_dept = d
                break
    if lead_dept is None:
        raise AppError(
            ERR_JURISDICTION_NO_DEPARTMENT,
            "no department mapped for the (category, sub_category) serves this jurisdiction",
            ERROR_STATUS[ERR_JURISDICTION_NO_DEPARTMENT],
        )

    # Resolve supporting departments by code (skip any code that no longer exists).
    supporting_ids = []
    for code in rule.get("supporting_department_codes", []):
        dept = db.find_one("departments", code=code)
        if dept is not None:
            supporting_ids.append(dept["id"])

    joint_handling = len(supporting_ids) > 0

    # Compute deadlines (business hours forward from registered_at).
    reg_dt = clock.parse_iso(wo["registered_at"])
    stat_dt = add_business_hours(reg_dt, int(rule["statutory_time_limit_hours"]))
    com_dt = add_business_hours(reg_dt, int(rule["committed_time_limit_hours"]))

    diff = calc.difficulty_score(wo["urgency"], rule.get("difficulty_base", 1) or 1,
                                 joint_handling=joint_handling)
    pri = calc.priority_flag(wo["urgency"], diff)

    db.update_fields(wo, {
        "status": "CLASSIFIED",
        "classification_mode": classification_mode,
        "lead_department_id": lead_dept["id"],
        "supporting_department_ids": supporting_ids,
        "joint_handling": joint_handling,
        "statutory_deadline_at": clock.format_dt(stat_dt),
        "committed_deadline_at": clock.format_dt(com_dt),
        "difficulty_score": diff,
        "priority_flag": pri,
    })

    audit_svc.write_audit("CLASSIFY", wo["id"], {
        "classification_mode": classification_mode,
        "lead_department_id": lead_dept["id"],
        "supporting_department_ids": list(supporting_ids),
        "joint_handling": joint_handling,
    })

    return wo


def reject_classification(wo_id: str, body: dict) -> dict:
    wo = get_work_order(wo_id)
    # State permission: REGISTERED or CLASSIFIED (per PRD §3.3 reject branch).
    if wo["status"] not in ("CLASSIFIED", "REGISTERED"):
        raise AppError(ERR_INVALID_STATE, "Work order not in a state permitting reject",
                       ERROR_STATUS[ERR_INVALID_STATE])
    reason = V.is_str(body, "rejection_reason", min_len=1, max_len=500)
    db.update_fields(wo, {"status": "REJECTED"})
    audit_svc.write_audit("REJECT", wo["id"], {"rejection_reason": reason})
    return wo


def dispatch(wo_id: str) -> dict:
    wo = get_work_order(wo_id)
    if wo["status"] != "CLASSIFIED":
        raise AppError(ERR_INVALID_STATE, "Work order not CLASSIFIED",
                       ERROR_STATUS[ERR_INVALID_STATE])
    if wo.get("lead_department_id") is None:
        raise AppError(ERR_INVALID_STATE, "lead_department_id missing",
                       ERROR_STATUS[ERR_INVALID_STATE])

    lead_dept = db.find_by_id("departments", wo["lead_department_id"])
    if not lead_dept or lead_dept["status"] != "ACTIVE":
        raise AppError(ERR_INVALID_STATE, "lead department not ACTIVE",
                       ERROR_STATUS[ERR_INVALID_STATE])
    for sup_id in wo.get("supporting_department_ids", []):
        sup = db.find_by_id("departments", sup_id)
        if not sup or sup["status"] != "ACTIVE":
            raise AppError(ERR_INVALID_STATE, "supporting department not ACTIVE",
                           ERROR_STATUS[ERR_INVALID_STATE])

    now_iso = clock.now_iso()
    # Create LEAD assignment.
    lead_assignment = db.insert("department_assignments", {
        "work_order_id": wo["id"],
        "department_id": wo["lead_department_id"],
        "role": "LEAD",
        "handler_id": None,
        "stage_status": "DISPATCHED",
        "rejection_reason": None,
        "opinion_text": None,
        "opinion_decision": None,
        "dispatched_at": now_iso,
        "accepted_at": None,
        "opinion_submitted_at": None,
    })
    db.update_fields(lead_dept, {
        "pending_work_count": int(lead_dept.get("pending_work_count", 0)) + 1,
    })
    for sup_id in wo.get("supporting_department_ids", []):
        sup_dept = db.find_by_id("departments", sup_id)
        db.insert("department_assignments", {
            "work_order_id": wo["id"],
            "department_id": sup_id,
            "role": "SUPPORTING",
            "handler_id": None,
            "stage_status": "DISPATCHED",
            "rejection_reason": None,
            "opinion_text": None,
            "opinion_decision": None,
            "dispatched_at": now_iso,
            "accepted_at": None,
            "opinion_submitted_at": None,
        })
        db.update_fields(sup_dept, {
            "pending_work_count": int(sup_dept.get("pending_work_count", 0)) + 1,
        })

    db.update_fields(wo, {"status": "DISPATCHED"})
    audit_svc.write_audit("DISPATCH", wo["id"], {
        "lead_department_id": wo["lead_department_id"],
        "supporting_department_ids": list(wo.get("supporting_department_ids") or []),
    })
    audit_svc.emit_sync(wo["id"], "DISPATCHED", {"work_order_id": wo["id"]})

    # If priority_flag at dispatch, create SupervisionTask.
    if wo.get("priority_flag"):
        task = db.insert("supervision_tasks", {
            "work_order_id": wo["id"],
            "reason": "HIGH_PRIORITY_AUTO",
            "status": "OPEN",
            "escalation_level": 0,
            "last_reminder_at": None,
        })
        audit_svc.write_audit("SUPERVISION_CREATE", wo["id"], {"supervision_task_id": task["id"]})

    return wo


def pause_work_order(wo_id: str, body: dict) -> dict:
    wo = get_work_order(wo_id)
    if wo["status"] != "IN_PROGRESS":
        raise AppError(ERR_INVALID_STATE, "Pause requires IN_PROGRESS",
                       ERROR_STATUS[ERR_INVALID_STATE])
    if wo.get("pause_started_at") is not None:
        raise AppError(ERR_ALREADY_PAUSED, "Already paused", ERROR_STATUS[ERR_ALREADY_PAUSED])

    # Acting handler must be the LEAD assignment's current handler_id.
    lead = _lead_assignment(wo["id"])
    if not lead or lead.get("handler_id") != g.user_id:
        raise AppError(ERR_FORBIDDEN, "Only the lead assignment's handler may pause",
                       ERROR_STATUS[ERR_FORBIDDEN])

    reason = V.is_str(body, "reason", min_len=1, max_len=500)

    now_iso = clock.now_iso()
    pause_rec = {
        "id": db.new_id(),
        "work_order_id": wo["id"],
        "reason": reason,
        "paused_at": now_iso,
        "resumed_at": None,
        "duration_seconds": None,
        "created_at": now_iso,
    }
    db.all_rows("clarification_pauses").append(pause_rec)
    db.update_fields(wo, {"pause_started_at": now_iso})

    audit_svc.write_audit("PAUSE", wo["id"], {"clarification_pause_id": pause_rec["id"], "reason": reason})
    return wo


def resume_work_order(wo_id: str) -> dict:
    wo = get_work_order(wo_id)
    if wo["status"] != "IN_PROGRESS":
        raise AppError(ERR_INVALID_STATE, "Resume requires IN_PROGRESS",
                       ERROR_STATUS[ERR_INVALID_STATE])
    if wo.get("pause_started_at") is None:
        raise AppError(ERR_NOT_PAUSED, "Not currently paused", ERROR_STATUS[ERR_NOT_PAUSED])

    lead = _lead_assignment(wo["id"])
    if not lead or lead.get("handler_id") != g.user_id:
        raise AppError(ERR_FORBIDDEN, "Only the lead assignment's handler may resume",
                       ERROR_STATUS[ERR_FORBIDDEN])

    # Find the latest open ClarificationPause for this WO.
    open_pauses = [
        p for p in db.all_rows("clarification_pauses")
        if p["work_order_id"] == wo["id"] and p.get("resumed_at") is None
    ]
    # Pick the latest by paused_at.
    open_pauses.sort(key=lambda p: p["paused_at"])
    cp = open_pauses[-1] if open_pauses else None

    now_dt = clock.now()
    now_iso = clock.now_iso()
    if cp is None:
        # Defensive: pause_started_at says paused but no open record.
        raise AppError(ERR_NOT_PAUSED, "No open pause record", ERROR_STATUS[ERR_NOT_PAUSED])

    paused_dt = clock.parse_iso(cp["paused_at"])
    duration = max(0, int((now_dt - paused_dt).total_seconds()))
    cp["resumed_at"] = now_iso
    cp["duration_seconds"] = duration

    # update WO: pause_accumulated_seconds, deadlines, pause_started_at
    new_pa = int(wo.get("pause_accumulated_seconds") or 0) + duration
    updates = {"pause_accumulated_seconds": new_pa, "pause_started_at": None}
    # shift deadlines by duration whole seconds
    if wo.get("statutory_deadline_at"):
        new_stat = clock.parse_iso(wo["statutory_deadline_at"]) + _seconds(duration)
        updates["statutory_deadline_at"] = clock.format_dt(new_stat)
    if wo.get("committed_deadline_at"):
        new_com = clock.parse_iso(wo["committed_deadline_at"]) + _seconds(duration)
        updates["committed_deadline_at"] = clock.format_dt(new_com)
    db.update_fields(wo, updates)

    audit_svc.write_audit("RESUME", wo["id"], {
        "clarification_pause_id": cp["id"],
        "duration_seconds": duration,
    })
    return wo


def _seconds(n: int):
    from datetime import timedelta
    return timedelta(seconds=int(n))


def _lead_assignment(wo_id: str):
    """Return the LEAD assignment that is currently the *active* lead (i.e., not REASSIGNED).

    PRD note: when reassign happens for LEAD, original is REASSIGNED and a new LEAD is
    created. So 'the lead assignment' is the one whose stage_status is not REASSIGNED.
    For pause/resume/resolve preconditions, we want the most-recent non-REASSIGNED LEAD.
    """
    leads = [
        a for a in db.all_rows("department_assignments")
        if a["work_order_id"] == wo_id and a["role"] == "LEAD"
    ]
    active = [a for a in leads if a["stage_status"] != "REASSIGNED"]
    if active:
        # Most recent by dispatched_at
        active.sort(key=lambda a: a["dispatched_at"])
        return active[-1]
    return None


def resolve(wo_id: str, body: dict) -> dict:
    wo = get_work_order(wo_id)
    if wo["status"] != "IN_PROGRESS":
        raise AppError(ERR_INVALID_STATE, "Resolve requires IN_PROGRESS",
                       ERROR_STATUS[ERR_INVALID_STATE])
    lead = _lead_assignment(wo["id"])
    if not lead or lead.get("handler_id") != g.user_id:
        raise AppError(ERR_FORBIDDEN, "Only the lead handler may resolve",
                       ERROR_STATUS[ERR_FORBIDDEN])
    if wo.get("pause_started_at") is not None:
        raise AppError(ERR_INVALID_STATE, "Cannot resolve while paused",
                       ERROR_STATUS[ERR_INVALID_STATE])

    # priority 16: every supporting must be OPINION_SUBMITTED (when joint).
    if wo.get("joint_handling"):
        sup = calc.supporting_assignments_for(wo["id"])
        if any(a["stage_status"] != "OPINION_SUBMITTED" for a in sup):
            raise AppError(ERR_OPINIONS_INCOMPLETE, "Not all supporting opinions submitted",
                           ERROR_STATUS[ERR_OPINIONS_INCOMPLETE])

    # priority 17: aggregated decision must not be DISAGREE_BLOCKING.
    if calc.opinion_aggregation(wo) == "DISAGREE_BLOCKING":
        raise AppError(ERR_DISAGREEMENT_UNRESOLVED, "Disagreement unresolved",
                       ERROR_STATUS[ERR_DISAGREEMENT_UNRESOLVED])

    resolution_summary = V.is_str(body, "resolution_summary", min_len=1, max_len=4000)

    # side effects
    # decrement lead dept pending_work_count
    lead_dept = db.find_by_id("departments", lead["department_id"])
    if lead_dept and int(lead_dept.get("pending_work_count", 0)) > 0:
        db.update_fields(lead_dept, {
            "pending_work_count": int(lead_dept["pending_work_count"]) - 1,
        })
    # lead handler open_assignment_count -= 1
    if lead.get("handler_id"):
        h = db.find_by_id("handlers", lead["handler_id"])
        if h and int(h.get("open_assignment_count", 0)) > 0:
            db.update_fields(h, {"open_assignment_count": int(h["open_assignment_count"]) - 1})

    # For any supporting that has not decremented yet (shouldn't happen but contract).
    # Already decremented on OPINION_SUBMIT; nothing extra unless there's a supporting in DISPATCHED/ACCEPTED.
    for a in calc.supporting_assignments_for(wo["id"]):
        if a["stage_status"] in ("DISPATCHED", "ACCEPTED"):
            d = db.find_by_id("departments", a["department_id"])
            if d and int(d.get("pending_work_count", 0)) > 0:
                db.update_fields(d, {
                    "pending_work_count": int(d["pending_work_count"]) - 1,
                })

    db.update_fields(wo, {
        "status": "RESOLVED",
        "resolution_summary": resolution_summary,
    })
    # recompute warning_state
    wo["warning_state"] = calc.compute_warning_state(wo)

    # Auto-dispatch a SatisfactionSurvey if reachable.
    auto_survey = _auto_dispatch_survey(wo)

    audit_svc.write_audit("RESOLVE", wo["id"], {
        "resolution_summary": resolution_summary,
        "auto_survey_id": auto_survey["id"] if auto_survey else None,
    })
    audit_svc.emit_sync(wo["id"], "RESOLVED", {"work_order_id": wo["id"]})

    return wo


def _auto_dispatch_survey(wo: dict):
    """Auto-dispatch a SatisfactionSurvey based on contactability.

    CALL when anonymous=false and caller_phone present; IM when anonymous=true with an
    on-file IM contact; otherwise no survey is created.
    """
    channel = None
    if not wo.get("anonymous") and wo.get("caller_phone"):
        channel = "CALL"
    elif wo.get("anonymous") and wo.get("im_contact_handle"):
        channel = "IM"

    if channel is None:
        return None

    rec = db.insert("satisfaction_surveys", {
        "work_order_id": wo["id"],
        "channel": channel,
        "status": "DISPATCHED",
        "score": None,
        "comment": None,
        "dispatched_at": clock.now_iso(),
        "responded_at": None,
    })
    audit_svc.write_audit("SURVEY_DISPATCH", wo["id"], {"survey_id": rec["id"], "channel": channel})
    return rec


def reopen(wo_id: str) -> dict:
    wo = get_work_order(wo_id)
    if wo["status"] != "FOLLOWED_UP":
        raise AppError(ERR_INVALID_STATE, "Reopen requires FOLLOWED_UP",
                       ERROR_STATUS[ERR_INVALID_STATE])

    # priority 19: latest survey RESPONDED with score <= 2 AND within 72 business hours of responded_at.
    surveys = [s for s in db.all_rows("satisfaction_surveys") if s["work_order_id"] == wo["id"]]
    if not surveys:
        raise AppError(ERR_REOPEN_WINDOW_EXPIRED, "No survey exists",
                       ERROR_STATUS[ERR_REOPEN_WINDOW_EXPIRED])
    surveys.sort(key=lambda s: (s["dispatched_at"], s["id"]))
    latest = surveys[-1]
    if latest["status"] != "RESPONDED" or latest.get("score") is None or int(latest["score"]) > 2:
        raise AppError(ERR_REOPEN_WINDOW_EXPIRED, "Reopen requires latest survey RESPONDED with score<=2",
                       ERROR_STATUS[ERR_REOPEN_WINDOW_EXPIRED])
    responded_at = clock.parse_iso(latest["responded_at"])
    now_dt = clock.now()
    bh = business_seconds_between(responded_at, now_dt) / 3600.0
    if bh > REOPEN_WINDOW_BUSINESS_HOURS:
        raise AppError(ERR_REOPEN_WINDOW_EXPIRED, "Reopen window expired",
                       ERROR_STATUS[ERR_REOPEN_WINDOW_EXPIRED])

    # side effects: status REOPENED, lead assignment re-dispatched, lead dept pending++
    lead = _lead_assignment(wo["id"])
    if lead:
        db.update_fields(lead, {
            "stage_status": "DISPATCHED",
            "handler_id": None,
            "accepted_at": None,
        })
        d = db.find_by_id("departments", lead["department_id"])
        if d:
            db.update_fields(d, {"pending_work_count": int(d.get("pending_work_count", 0)) + 1})

    db.update_fields(wo, {"status": "REOPENED"})
    audit_svc.write_audit("REOPEN", wo["id"], {})
    audit_svc.emit_sync(wo["id"], "REOPENED", {"work_order_id": wo["id"]})
    return wo


def close(wo_id: str) -> dict:
    wo = get_work_order(wo_id)

    # Allowed entry: FOLLOWED_UP with proper survey state OR RESOLVED with no survey.
    surveys = [s for s in db.all_rows("satisfaction_surveys") if s["work_order_id"] == wo["id"]]
    surveys.sort(key=lambda s: (s["dispatched_at"], s["id"]))
    latest = surveys[-1] if surveys else None

    if wo["status"] == "FOLLOWED_UP":
        ok = False
        if latest is not None:
            if latest["status"] == "RESPONDED" and int(latest.get("score") or 0) >= 3:
                ok = True
            elif latest["status"] == "EXPIRED":
                ok = True
        else:
            ok = True
        if not ok:
            raise AppError(ERR_INVALID_STATE, "Cannot close from FOLLOWED_UP given survey state",
                           ERROR_STATUS[ERR_INVALID_STATE])
    elif wo["status"] == "RESOLVED":
        # No-survey path only.
        if latest is not None:
            raise AppError(ERR_INVALID_STATE,
                           "Cannot close from RESOLVED when a survey exists",
                           ERROR_STATUS[ERR_INVALID_STATE])
    else:
        raise AppError(ERR_INVALID_STATE, "Cannot close from current state",
                       ERROR_STATUS[ERR_INVALID_STATE])

    # priority 18: no OPEN/ESCALATED supervision task
    open_tasks = [
        t for t in db.all_rows("supervision_tasks")
        if t["work_order_id"] == wo["id"] and t["status"] in ("OPEN", "ESCALATED")
    ]
    if open_tasks:
        raise AppError(ERR_SUPERVISION_OPEN, "Open supervision task blocks close",
                       ERROR_STATUS[ERR_SUPERVISION_OPEN])

    now_iso = clock.now_iso()
    db.update_fields(wo, {"status": "CLOSED", "closed_at": now_iso})
    audit_svc.write_audit("CLOSE", wo["id"], {})
    audit_svc.emit_sync(wo["id"], "CLOSED", {"work_order_id": wo["id"]})
    return wo


def serialize_wo_for_read(wo: dict) -> dict:
    """Recompute warning_state on read (calculations.warning_state)."""
    wo["warning_state"] = calc.compute_warning_state(wo)
    return wo
