"""Application submission, withdrawal, escalation, and review-status driver."""

from __future__ import annotations

import copy

from flask import g

import db
from config import (
    APPLICATION_TERMINAL,
    CHANNELS,
    REVIEW_TASK_TERMINAL,
)
from errors import (
    AppError,
    ERR_CHANNEL_NOT_ALLOWED,
    ERR_EFORM_INCOMPLETE,
    ERR_ESCALATION_NOT_PERMITTED,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_MATERIAL_MISSING,
    ERR_MATERIAL_TYPE_MISMATCH,
    ERR_NOT_FOUND,
    ERR_VALIDATION_FAILED,
)
from services import audit, calculations
from services import validators as V


# ---------------------------------------------------------------------------
# Lookups & ownership
# ---------------------------------------------------------------------------

def get_application(app_id: str) -> dict:
    a = db.find_by_id("applications", app_id)
    if not a:
        raise AppError(ERR_NOT_FOUND, f"Application not found: {app_id}", 404)
    return a


def assert_can_read_application(app: dict) -> None:
    role = g.role
    uid = g.user_id
    if role == "PlatformAdmin":
        return
    if role == "Applicant":
        if app["applicant_user_id"] != uid:
            raise AppError(ERR_FORBIDDEN,
                           "Applicant may only access own applications", 403)
        return
    if role in {"Reviewer", "LeadReviewer"}:
        # Can see only applications routed to their department.
        tasks = db.find_many("review_tasks", application_id=app["id"])
        if not any(t["department_id"] == uid for t in tasks):
            raise AppError(ERR_FORBIDDEN,
                           "Reviewer may only access applications routed to their department",
                           403)
        return
    if role == "CertificateOfficer":
        # Allowed for cert-related endpoints; read app detail not in shared ops.
        raise AppError(ERR_FORBIDDEN,
                       "CertificateOfficer cannot read application detail", 403)
    raise AppError(ERR_FORBIDDEN, "Role cannot read applications", 403)


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def submit_application(body: dict) -> dict:
    body = V.must_be_dict(body)
    matter_version_id = V.require_str(body, "matter_version_id")
    channel = V.require_str(body, "channel")
    if channel not in CHANNELS:
        raise AppError(ERR_VALIDATION_FAILED,
                       f"channel must be one of {sorted(CHANNELS)}", 422)
    submitted_materials = V.require_list(body, "submitted_materials")

    version = db.find_by_id("matter_versions", matter_version_id)
    if not version:
        raise AppError(ERR_NOT_FOUND,
                       f"MatterVersion not found: {matter_version_id}", 404)
    if version["status"] not in {"PUBLISHED", "SUPERSEDED"}:
        raise AppError(ERR_INVALID_STATE,
                       f"MatterVersion not legally usable (status={version['status']})",
                       409)

    required_ids = list(version["required_material_template_ids"])
    submitted_ids = []
    for entry in submitted_materials:
        if not isinstance(entry, dict):
            raise AppError(ERR_VALIDATION_FAILED,
                           "each submitted_materials entry must be an object", 422)
        tid = entry.get("material_template_id")
        if not isinstance(tid, str):
            raise AppError(ERR_VALIDATION_FAILED,
                           "material_template_id required on each entry", 422)
        submitted_ids.append(tid)

    # Priority 6: every required template covered exactly once.
    submitted_set = set(submitted_ids)
    if any(rid not in submitted_set for rid in required_ids):
        missing = [rid for rid in required_ids if rid not in submitted_set]
        raise AppError(ERR_MATERIAL_MISSING,
                       f"Missing required materials: {missing}", 422)
    # Also: every required must be covered by exactly one entry.
    for rid in required_ids:
        count = submitted_ids.count(rid)
        if count != 1:
            raise AppError(ERR_MATERIAL_MISSING,
                           f"Required material {rid} must be covered exactly once",
                           422)

    # Priority 7: each submitted entry's template must be PUBLISHED, type matches
    # MaterialTemplate.material_type — we accept submitted material_type if present.
    for entry in submitted_materials:
        tid = entry["material_template_id"]
        mt = db.find_by_id("material_templates", tid)
        if not mt or mt["status"] != "PUBLISHED":
            raise AppError(ERR_MATERIAL_TYPE_MISMATCH,
                           f"MaterialTemplate {tid} not PUBLISHED", 422)
        sub_type = entry.get("material_type")
        if sub_type is not None and sub_type != mt["material_type"]:
            raise AppError(ERR_MATERIAL_TYPE_MISMATCH,
                           f"submitted material_type for {tid} does not match template",
                           422)

    # Priority 8: ONLINE channel + e_form_schema -> e_form_payload required keys.
    if channel == "ONLINE":
        for entry in submitted_materials:
            tid = entry["material_template_id"]
            mt = db.find_by_id("material_templates", tid)
            schema = mt.get("e_form_schema")
            if not schema:
                continue
            payload = entry.get("e_form_payload")
            if not isinstance(payload, dict):
                raise AppError(ERR_EFORM_INCOMPLETE,
                               f"e_form_payload missing for ONLINE template {tid}",
                               422)
            required_keys = schema.get("required") or list(
                (schema.get("properties") or {}).keys()
            )
            for k in required_keys:
                if k not in payload:
                    raise AppError(ERR_EFORM_INCOMPLETE,
                                   f"e_form_payload missing key '{k}' for template {tid}",
                                   422)

    # Priority 9: channel must appear in pinned channels.
    if channel not in version["channels"]:
        raise AppError(ERR_CHANNEL_NOT_ALLOWED,
                       f"channel {channel} not allowed by MatterVersion", 422)

    fee = version["fee_amount_cents"]
    payment_status = "PAID" if fee == 0 else "PENDING"

    app = db.insert("applications", {
        "matter_version_id": matter_version_id,
        "applicant_user_id": g.user_id,
        "channel": channel,
        "submitted_materials": copy.deepcopy(submitted_materials),
        "identity_verified": False,
        "payment_status": payment_status,
        "review_status": "SUBMITTED",
        "correction_round": 0,
        "deadline_at": None,
        "clock_started_at": None,
        "total_paused_seconds": 0,
        "pinned_routing_snapshot": None,
    })

    audit.write("APPLICATION_SUBMIT", "Application", app["id"],
                {"matter_version_id": matter_version_id, "channel": channel})

    # Even with fee==0 -> PAID, we still need identity_verified to enter review.
    return app


# ---------------------------------------------------------------------------
# Transition into UNDER_REVIEW (after identity + payment).
# ---------------------------------------------------------------------------

def maybe_enter_under_review(app_id: str) -> None:
    app = db.find_by_id("applications", app_id)
    if not app:
        return
    if app["review_status"] != "SUBMITTED":
        return
    if not app.get("identity_verified"):
        return
    if app.get("payment_status") != "PAID":
        return
    version = db.find_by_id("matter_versions", app["matter_version_id"])
    if not version or version["status"] not in {"PUBLISHED", "SUPERSEDED"}:
        return

    routing = copy.deepcopy(version["review_routing"])
    now = db.now_iso()

    # Snapshot routing + create review tasks.
    for idx, stage in enumerate(routing["stages"]):
        is_lead = stage["department_id"] == routing["lead_department_id"]
        status = "PENDING"
        stage_due_at = None
        if routing["mode"] == "PARALLEL":
            status = "IN_PROGRESS"
            stage_due_at = _now_plus_working_days(stage["sla_days"])
        elif routing["mode"] == "SERIAL" and idx == 0:
            status = "IN_PROGRESS"
            stage_due_at = _now_plus_working_days(stage["sla_days"])
        db.insert("review_tasks", {
            "application_id": app_id,
            "department_id": stage["department_id"],
            "stage_index": idx,
            "is_lead": is_lead,
            "status": status,
            "opinion_text": None,
            "decided_at": None,
            "stage_due_at": stage_due_at,
        })

    db.update("applications", app_id, {
        "review_status": "UNDER_REVIEW",
        "pinned_routing_snapshot": routing,
        "clock_started_at": now,
    })
    # Recompute deadline_at.
    fresh = db.find_by_id("applications", app_id)
    deadline = calculations.derive_application_deadline(fresh, version, "committed")
    db.update("applications", app_id, {"deadline_at": deadline})


def _now_plus_working_days(working_days: int) -> str:
    from config import WORKING_DAY_SECONDS
    from datetime import timedelta
    target = db.now_dt() + timedelta(seconds=working_days * WORKING_DAY_SECONDS)
    return db.format_ts(target)


# ---------------------------------------------------------------------------
# Cascade helper: SKIP non-terminal review tasks.
# ---------------------------------------------------------------------------

def cascade_skip_tasks(app_id: str) -> None:
    for t in db.find_many("review_tasks", application_id=app_id):
        if t["status"] not in REVIEW_TASK_TERMINAL:
            db.update("review_tasks", t["id"], {"status": "SKIPPED"})


# ---------------------------------------------------------------------------
# Withdraw
# ---------------------------------------------------------------------------

def withdraw_application(app_id: str, body: dict) -> dict:
    app = get_application(app_id)
    if app["applicant_user_id"] != g.user_id:
        raise AppError(ERR_FORBIDDEN,
                       "Only the application's applicant may withdraw", 403)

    rs = app["review_status"]
    if rs in APPLICATION_TERMINAL:
        raise AppError(ERR_INVALID_STATE,
                       f"Cannot withdraw from terminal state {rs}", 409)
    if rs not in {"SUBMITTED", "UNDER_REVIEW"}:
        raise AppError(ERR_INVALID_STATE,
                       f"Cannot withdraw application in state {rs}", 409)

    from services import occ
    occ.check(app, body)

    if rs == "UNDER_REVIEW":
        for t in db.find_many("review_tasks", application_id=app_id):
            if t["status"] == "DISAGREED":
                raise AppError(ERR_INVALID_STATE,
                               "Cannot withdraw after a DISAGREED decision exists",
                               409)

    cascade_skip_tasks(app_id)

    version = db.find_by_id("matter_versions", app["matter_version_id"])
    updates = {"review_status": "WITHDRAWN"}
    if app["payment_status"] == "PAID" and version["fee_amount_cents"] > 0:
        updates["payment_status"] = "REFUNDED"
    db.update("applications", app_id, updates)
    return db.find_by_id("applications", app_id)


# ---------------------------------------------------------------------------
# Escalate
# ---------------------------------------------------------------------------

def escalate_application(app_id: str, body: dict) -> dict:
    app = get_application(app_id)
    if app["review_status"] != "UNDER_REVIEW":
        raise AppError(ERR_INVALID_STATE,
                       f"Cannot escalate application in state {app['review_status']}",
                       409)

    routing = app.get("pinned_routing_snapshot") or {}
    if routing.get("mode") != "PARALLEL" or routing.get("aggregation_rule") == "LEAD_DECIDES":
        raise AppError(ERR_ESCALATION_NOT_PERMITTED,
                       "Escalation requires PARALLEL routing with non-LEAD_DECIDES rule",
                       409)

    # Caller must be LeadReviewer of the lead department.
    if g.role != "LeadReviewer":
        raise AppError(ERR_FORBIDDEN, "Only LeadReviewer may escalate", 403)
    if g.user_id != routing.get("lead_department_id"):
        raise AppError(ERR_FORBIDDEN,
                       "LeadReviewer must belong to the routing's lead department",
                       403)
    if app["applicant_user_id"] == g.user_id:
        raise AppError(ERR_FORBIDDEN,
                       "Applicant cannot also be a reviewer of own application", 403)

    from services import occ
    occ.check(app, body)

    tasks = db.find_many("review_tasks", application_id=app_id)
    has_agreed = any(t["status"] == "AGREED" for t in tasks)
    has_disagreed = any(t["status"] == "DISAGREED" for t in tasks)
    if not (has_agreed and has_disagreed):
        raise AppError(ERR_ESCALATION_NOT_PERMITTED,
                       "Escalation requires at least one AGREED and one DISAGREED",
                       409)

    db.update("applications", app_id, {"review_status": "ESCALATED"})
    audit.write("ESCALATE", "Application", app_id, {})
    return db.find_by_id("applications", app_id)


def resolve_escalation(app_id: str, body: dict) -> dict:
    app = get_application(app_id)
    if app["review_status"] != "ESCALATED":
        raise AppError(ERR_INVALID_STATE,
                       f"Cannot resolve escalation; current status {app['review_status']}",
                       409)
    body = V.must_be_dict(body)
    decision = V.require_str(body, "decision")
    if decision not in {"AGREED", "DISAGREED"}:
        raise AppError(ERR_VALIDATION_FAILED,
                       "decision must be AGREED or DISAGREED", 422)

    from services import occ
    occ.check(app, body)

    # Mark all PENDING/IN_PROGRESS tasks with system attribution.
    for t in db.find_many("review_tasks", application_id=app_id):
        if t["status"] in {"PENDING", "IN_PROGRESS"}:
            db.update("review_tasks", t["id"], {
                "status": decision,
                "decided_at": db.now_iso(),
                "opinion_text": "system: escalation resolution",
            })

    if decision == "AGREED":
        db.update("applications", app_id, {"review_status": "APPROVED"})
        from services import certificate
        certificate.issue_certificate_for_application(app_id)
        audit.write("APPROVE", "Application", app_id, {"via": "escalation"})
    else:
        version = db.find_by_id("matter_versions", app["matter_version_id"])
        updates = {"review_status": "REJECTED"}
        if app["payment_status"] == "PAID" and version["fee_amount_cents"] > 0:
            updates["payment_status"] = "REFUNDED"
        db.update("applications", app_id, updates)
        audit.write("REJECT", "Application", app_id, {"via": "escalation"})

    return db.find_by_id("applications", app_id)
