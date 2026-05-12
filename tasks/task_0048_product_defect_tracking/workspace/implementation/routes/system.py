"""System endpoints: clock advance, SLA-escalation sweep, external event injection."""

from __future__ import annotations

from flask import Blueprint, g

import db
from config import (
    DEFECT_CLOSED, DEFECT_NEW, DEFECT_ASSIGNED, DEFECT_NON_TERMINAL,
    SLA_PAUSED, EXT_SYSTEMS,
    ROLE_TRIAGE_MANAGER, ROLE_RELEASE_MANAGER,
)
from errors import AppError, ERR_INVALID_REQUEST
from middleware import require_role
from response import success
from services.audit import append_audit
from services.calculations import compute_effective_sla, compute_priority_score
from services.serializers import audit_entry_dto, project_dto
from services.validators import (
    find_defect_or_404, find_project_or_404, ensure_project_active,
    get_json, require_enum, require_int, require_str,
)

bp = Blueprint("system", __name__)


@bp.post("/_clock/advance")
def clock_advance():
    require_role(ROLE_TRIAGE_MANAGER)
    body = get_json()
    project_id = require_str(body, "project_id")
    minutes = require_int(body, "minutes")
    if minutes < 0:
        raise AppError(ERR_INVALID_REQUEST, "minutes must be >= 0", 400)
    project = find_project_or_404(project_id)
    new_minute = project["clock_minute"] + minutes
    db.update("projects", project_id, {"clock_minute": new_minute}, bump=True)
    return success(project_dto(db.find_by_id("projects", project_id)))


@bp.post("/_sweep/sla-escalation")
def sla_escalation_sweep():
    require_role(ROLE_TRIAGE_MANAGER)
    body = get_json()
    project_id = require_str(body, "project_id")
    project = find_project_or_404(project_id)
    ensure_project_active(project)

    clock = project["clock_minute"]
    changed = []
    defects = [d for d in db.all_rows("defects") if d["project_id"] == project_id]
    for d in defects:
        # Frozen states
        if d["status"] == DEFECT_CLOSED:
            continue
        if d.get("sla_state") == SLA_PAUSED:
            continue
        # PRD §3.4: an SLA-escalation sweep recomputes priority_score
        # (which recomputes the age component as the clock has moved
        # forward).
        new_score = compute_priority_score(
            effective_severity=d["effective_severity"],
            business_impact=d["business_impact"],
            reopen_count=d.get("reopen_count", 0),
            current_clock_minute=clock,
            report_clock_minute=d["report_clock_minute"],
        )
        score_changed = new_score != d.get("priority_score")
        if score_changed:
            d["priority_score"] = new_score
            db.update("defects", d["id"], {"priority_score": new_score}, bump=True)

        adjusted_now = clock - d.get("total_paused_minutes", 0)
        current_level = d.get("escalation_level", 0)
        new_level = current_level
        if adjusted_now > d["resolution_due_minute"]:
            new_level = max(current_level, 2)
        elif adjusted_now > d["response_due_minute"] and d["status"] in (DEFECT_NEW, DEFECT_ASSIGNED):
            new_level = max(current_level, 1)

        if new_level > current_level:
            db.update("defects", d["id"], {"escalation_level": new_level}, bump=True)
            append_audit(
                defect_id=d["id"],
                event_type="ESCALATION",
                actor_id="system",
                from_value=str(current_level),
                to_value=str(new_level),
                at_minute=clock,
            )
            append_audit(
                defect_id=d["id"],
                event_type="EXTERNAL_EVENT_SYNC",
                actor_id="system",
                at_minute=clock,
                external_payload={"system": "IM",
                                  "raw": {"defect_id": d["id"],
                                          "from_level": current_level,
                                          "to_level": new_level}},
            )
            changed.append({"defect_id": d["id"],
                            "from_level": current_level,
                            "to_level": new_level})

    return success({
        "project_id": project_id,
        "clock_minute": clock,
        "changed": changed,
        "changed_count": len(changed),
    })


@bp.post("/_events/emit")
def emit_event():
    require_role(ROLE_TRIAGE_MANAGER, ROLE_RELEASE_MANAGER)
    body = get_json()
    defect_id = require_str(body, "defect_id")
    system_v = require_enum(body, "system", EXT_SYSTEMS)
    raw_payload = body.get("raw_payload")
    if not isinstance(raw_payload, dict):
        raise AppError(ERR_INVALID_REQUEST, "raw_payload must be object", 400)

    d = find_defect_or_404(defect_id)
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    audit = append_audit(
        defect_id=defect_id,
        event_type="EXTERNAL_EVENT_SYNC",
        actor_id=g.user_id,
        at_minute=project["clock_minute"],
        external_payload={"system": system_v, "raw": raw_payload},
    )
    return success(audit_entry_dto(audit), 201)
