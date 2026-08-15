"""Compliance audit cycle (PRD 3.9)."""
from flask import Blueprint

import envelope
from errors import ApiError
from guards import (
    ALL_ROLES,
    apply_filters,
    body_row,
    endpoint,
    paginate,
    pagination,
    path_row,
    req_instant,
    req_int,
    req_string,
)
from serialize import audit_out
from store import db, sorted_rows, touch

bp = Blueprint("audits", __name__)

CREATE_SCHEMA = (
    frozenset(["facility_id", "scheduled_start_at", "due_at", "lead_auditor"]),
    frozenset(["facility_id", "scheduled_start_at", "due_at", "lead_auditor"]),
)
CLOSE_SCHEMA = (frozenset(["findings_count"]), frozenset(["findings_count"]))

STATUS_VALUES = ("SCHEDULED", "IN_PROGRESS", "CLOSED")


@bp.post("/psm/compliance-audits")
@endpoint(["ComplianceOfficer"], schema=CREATE_SCHEMA)
def create_audit(ctx):
    start = req_instant(ctx.body, "scheduled_start_at")
    due = req_instant(ctx.body, "due_at")
    lead = req_string(ctx.body, "lead_auditor")
    facility = body_row(ctx.body, "facilities", "facility_id")
    row = db.create(
        "compliance_audits",
        {
            "facility_id": facility["id"],
            "scheduled_start_at": start,
            "due_at": due,
            "lead_auditor": lead,
            "origin": "MANUAL",
            "status": "SCHEDULED",
            "findings_count": None,
        },
    )
    return envelope.created(audit_out(row))


@bp.get("/psm/compliance-audits/<audit_id>")
@endpoint(ALL_ROLES)
def get_audit(ctx, audit_id):
    return envelope.ok(audit_out(path_row("compliance_audits", audit_id)))


@bp.get("/psm/compliance-audits")
@endpoint(ALL_ROLES)
def list_audits(ctx):
    limit, offset = pagination(ctx)
    rows = sorted_rows(db.compliance_audits.values())
    rows = apply_filters(
        rows,
        ctx,
        [
            ("facility_id", "facility_id", None),
            ("status", "status", STATUS_VALUES),
            ("origin", "origin", ("MANUAL", "AUTO_THRESHOLD")),
        ],
    )
    total = len(rows)
    return envelope.listing(
        [audit_out(r) for r in paginate(rows, limit, offset)], limit, offset, total
    )


@bp.post("/psm/compliance-audits/<audit_id>/start")
@endpoint(["ComplianceOfficer"], schema=(frozenset(), frozenset()))
def start_audit(ctx, audit_id):
    audit = path_row("compliance_audits", audit_id)
    if audit["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    audit["status"] = "IN_PROGRESS"
    touch(audit)
    return envelope.ok(audit_out(audit))


@bp.post("/psm/compliance-audits/<audit_id>/close")
@endpoint(["ComplianceOfficer"], schema=CLOSE_SCHEMA)
def close_audit(ctx, audit_id):
    # step 0 -- findings_count: zero or more; a missing or negative count is
    # ERR_VALIDATION
    findings = req_int(ctx.body, "findings_count", minimum=0)
    audit = path_row("compliance_audits", audit_id)
    if audit["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")
    audit["status"] = "CLOSED"
    audit["findings_count"] = findings
    touch(audit)
    return envelope.ok(audit_out(audit))
