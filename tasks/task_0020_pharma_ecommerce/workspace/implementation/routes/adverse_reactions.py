"""Adverse drug reaction reports — create, escalate, submit, acknowledge, archive, get, list."""

from __future__ import annotations

from flask import Blueprint, request

from db import (
    append_audit_log,
    db,
    emit_external_event,
    filter_by_platform,
    fmt_iso,
    order_by_seq,
    parse_iso,
    platform_clock,
    serialize,
    serialize_list,
    stamp_create,
    stamp_update,
)
from errors import err
from lookups import get_platform, get_report
from middleware import current_actor, require_roles
from pagination import paginate, parse_limit_offset
from response import success_array, success_object
from services.calculations import (
    GRACE_HOURS,
    follow_up_due,
    reporting_deadline,
)
from validate import (
    occ_check,
    optional_field,
    require_enum,
    require_field,
    require_json,
)
import datetime as _dt

bp = Blueprint("adverse_reactions", __name__)

REPORTER_KINDS = {"PATIENT", "PHARMACIST"}
SEVERITIES = {"NON_SERIOUS", "SERIOUS"}


@bp.post("/pharma-platforms/<pid>/adverse-reactions")
@require_roles("Customer", "PharmacistReReviewer")
def create_report(pid: str):
    platform = get_platform(pid)
    body = require_json(request.get_json(silent=True))
    drug_id = require_field(body, "drug_id", kind=str)
    customer_id = require_field(body, "customer_id", kind=str)
    if drug_id not in db.drugs or db.drugs[drug_id].get("platform_id") != pid:
        raise err("ERR_DRUG_NOT_FOUND", f"Drug '{drug_id}' not found.")
    if customer_id not in db.customers or db.customers[customer_id].get("platform_id") != pid:
        raise err("ERR_CUSTOMER_NOT_FOUND", f"Customer '{customer_id}' not found.")
    order_id = optional_field(body, "order_id", kind=str, default=None)
    if order_id is not None:
        if order_id not in db.orders or db.orders[order_id].get("platform_id") != pid:
            raise err("ERR_ORDER_NOT_FOUND", f"Order '{order_id}' not found.")
    reporter_kind = require_enum(body, "reporter_kind", REPORTER_KINDS)
    severity = require_enum(body, "severity", SEVERITIES)

    reported_at = platform_clock(platform)
    deadline_dt = reporting_deadline(reported_at, severity)
    row = {
        "platform_id": pid,
        "order_id": order_id,
        "drug_id": drug_id,
        "customer_id": customer_id,
        "reporter_kind": reporter_kind,
        "severity": severity,
        "reported_at": reported_at,
        "reporting_deadline_at": fmt_iso(deadline_dt),
        "submitted_to_authority_at": None,
        "follow_up_due_at": None,
        "archived_at": None,
        "status": "REPORTED",
    }
    stamp_create(row, platform)
    db.adverse_reaction_reports[row["id"]] = row
    return success_object(serialize(row)), 201


@bp.post("/pharma-platforms/<pid>/adverse-reactions/<report_id>/escalate")
@require_roles("PharmacistReReviewer")
def escalate_report(pid: str, report_id: str):
    platform, r = get_report(pid, report_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, r)
    if r.get("severity") != "NON_SERIOUS":
        raise err("ERR_INVALID_REQUEST", "Only NON_SERIOUS reports may be escalated.")
    r["severity"] = "SERIOUS"
    # Forward-looking: anchored at original reported_at.
    r["reporting_deadline_at"] = fmt_iso(reporting_deadline(r["reported_at"], "SERIOUS"))
    stamp_update(r, platform)
    return success_object(serialize(r)), 200


@bp.post("/pharma-platforms/<pid>/adverse-reactions/<report_id>/submit")
@require_roles("PharmacistReReviewer")
def submit_report(pid: str, report_id: str):
    platform, r = get_report(pid, report_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, r)
    if r.get("status") != "REPORTED":
        raise err("ERR_REPORT_NOT_REPORTED", "Report must be REPORTED.")
    clock = parse_iso(platform_clock(platform))
    deadline = parse_iso(r["reporting_deadline_at"]) + _dt.timedelta(hours=GRACE_HOURS)
    if clock >= deadline:
        raise err("ERR_REPORTING_DEADLINE_PASSED", "Submission past deadline.")

    submitted_at = platform_clock(platform)
    r["submitted_to_authority_at"] = submitted_at
    if r.get("severity") == "SERIOUS":
        r["follow_up_due_at"] = fmt_iso(follow_up_due(submitted_at))
        r["status"] = "FOLLOW_UP_PENDING"  # auto-advance from SUBMITTED
    else:
        r["status"] = "SUBMITTED"
    stamp_update(r, platform)
    actor_id, actor_role = current_actor()
    append_audit_log(
        platform=platform,
        subject_type="ADVERSE_REACTION_REPORT",
        subject_id=r["id"],
        action="ADR_SUBMITTED",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"report_id": r["id"], "severity": r["severity"], "version": r["version"]},
    )
    emit_external_event(
        platform=platform,
        channel="REGULATORY_AUTHORITY",
        event_type="adr.submitted",
        subject_type="ADVERSE_REACTION_REPORT",
        subject_id=r["id"],
        payload={
            "report_id": r["id"],
            "severity": r["severity"],
            "deadline_at": r["reporting_deadline_at"],
            "version": r["version"],
        },
        idempotency_key=f"adr.submitted:{r['id']}:{r['version']}",
    )
    return success_object(serialize(r)), 200


@bp.post("/pharma-platforms/<pid>/adverse-reactions/<report_id>/acknowledge")
@require_roles("RegulatoryGateway")
def acknowledge_report(pid: str, report_id: str):
    platform, r = get_report(pid, report_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, r)
    if r.get("status") != "SUBMITTED":
        raise err("ERR_REPORT_REQUIRES_FOLLOW_UP", "Only SUBMITTED reports may be acknowledged.")
    if r.get("severity") != "NON_SERIOUS":
        raise err(
            "ERR_REPORT_REQUIRES_FOLLOW_UP",
            "Serious reports must transit through FOLLOW_UP_PENDING.",
        )
    r["status"] = "ACKNOWLEDGED"
    stamp_update(r, platform)
    return success_object(serialize(r)), 200


@bp.post("/pharma-platforms/<pid>/adverse-reactions/<report_id>/archive")
@require_roles("PharmacistReReviewer")
def archive_report(pid: str, report_id: str):
    platform, r = get_report(pid, report_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, r)
    status = r.get("status")
    if status not in {"FOLLOW_UP_PENDING", "ACKNOWLEDGED"}:
        raise err("ERR_REPORT_NOT_ARCHIVABLE", "Report not archivable from current state.")
    if status == "ACKNOWLEDGED" and r.get("severity") != "NON_SERIOUS":
        raise err("ERR_REPORT_NOT_ARCHIVABLE", "Acknowledged path requires NON_SERIOUS severity.")
    if status == "FOLLOW_UP_PENDING" and r.get("severity") == "SERIOUS":
        clock = parse_iso(platform_clock(platform))
        due = parse_iso(r["follow_up_due_at"])
        if clock < due:
            raise err("ERR_FOLLOW_UP_INCOMPLETE", "Follow-up window not yet elapsed.")
    r["status"] = "ARCHIVED"
    r["archived_at"] = platform_clock(platform)
    stamp_update(r, platform)
    actor_id, actor_role = current_actor()
    append_audit_log(
        platform=platform,
        subject_type="ADVERSE_REACTION_REPORT",
        subject_id=r["id"],
        action="ADR_ARCHIVED",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"report_id": r["id"], "version": r["version"]},
    )
    return success_object(serialize(r)), 200


@bp.get("/pharma-platforms/<pid>/adverse-reactions/<report_id>")
@require_roles("PharmacistReReviewer", "RegulatoryGateway", "PlatformAdmin")
def get_report_route(pid: str, report_id: str):
    _, r = get_report(pid, report_id)
    return success_object(serialize(r)), 200


@bp.get("/pharma-platforms/<pid>/adverse-reactions")
@require_roles("PharmacistReReviewer", "RegulatoryGateway", "PlatformAdmin")
def list_reports(pid: str):
    get_platform(pid)
    rows = filter_by_platform(db.adverse_reaction_reports, pid)
    status = request.args.get("status")
    severity = request.args.get("severity")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if severity:
        rows = [r for r in rows if r.get("severity") == severity]
    rows = order_by_seq(rows)
    limit, offset = parse_limit_offset()
    page, total = paginate(rows, limit, offset)
    return success_array(serialize_list(page), limit, offset, total), 200
