"""Remediation, resolution and waiver of quality findings (PRD 3.5)."""

from decimal import Decimal

from flask import Blueprint, g

import db
import response
import services
import validation as v
from auth import endpoint, entitle
from errors import fail
from util import round2

bp = Blueprint("quality_findings", __name__)

STATUSES = ("OPEN", "REMEDIATION_PLANNED", "RESOLVED", "WAIVED")
READERS = ("GovernanceAdmin", "DataOwner", "DataSteward", "Auditor")
ELIGIBLE_ASSIGNEE_ROLES = ("DATA_STEWARD", "CUSTODIAN", "DATA_OWNER")


@bp.get("/mdm/quality-findings")
@endpoint(*READERS)
def list_findings():
    limit, offset = v.pagination()
    scorecard_run_id = v.str_filter("scorecard_run_id")
    quality_rule_id = v.str_filter("quality_rule_id")
    assigned_steward_id = v.str_filter("assigned_steward_id")
    planned_by_steward_id = v.str_filter("planned_by_steward_id")
    waived_by_steward_id = v.str_filter("waived_by_steward_id")
    status = v.enum_filter("status", STATUSES)

    rows = db.ordered(db.store.quality_findings)
    if scorecard_run_id is not None:
        rows = [r for r in rows if r["scorecard_run_id"] == scorecard_run_id]
    if quality_rule_id is not None:
        rows = [r for r in rows if r["quality_rule_id"] == quality_rule_id]
    if assigned_steward_id is not None:
        rows = [r for r in rows if r["assigned_steward_id"] == assigned_steward_id]
    if planned_by_steward_id is not None:
        rows = [r for r in rows if r["planned_by_steward_id"] == planned_by_steward_id]
    if waived_by_steward_id is not None:
        rows = [r for r in rows if r["waived_by_steward_id"] == waived_by_steward_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.collection(rows, limit, offset)


@bp.get("/mdm/quality-findings/<finding_id>")
@endpoint(*READERS)
def read_finding(finding_id):
    finding = db.resolve(db.store.quality_findings, finding_id, "ERR_FINDING_NOT_FOUND")
    return response.entity(finding)


@bp.post("/mdm/quality-findings/<finding_id>/plan-remediation")
@endpoint("DataSteward", "DataOwner")
def plan_remediation(finding_id):
    finding = db.resolve(db.store.quality_findings, finding_id, "ERR_FINDING_NOT_FOUND")
    body = v.body()
    assigned_steward_id = v.req_str(body, "assigned_steward_id", 1)
    due_at = v.req_dt(body, "due_at")
    plan_note = v.opt_str(body, "plan_note", 0)

    assignee = db.resolve(db.store.stewards, assigned_steward_id, "ERR_STEWARD_NOT_FOUND")
    domain = db.domain_of_finding(finding)
    entitle(domain)

    if finding["status"] in ("RESOLVED", "WAIVED"):
        fail("ERR_FINDING_ALREADY_CLOSED", "The finding is already closed.")
    if finding["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Remediation planning is only available from OPEN status.")

    if not db.has_active_assignment(domain["id"], assignee["id"], ELIGIBLE_ASSIGNEE_ROLES):
        fail("ERR_ASSIGNMENT_STEWARD_NOT_ELIGIBLE",
             "The nominated assignee holds no covering ACTIVE assignment on the finding's domain.")

    if due_at <= db.now():
        fail("ERR_DUE_DATE_IN_PAST", "due_at must fall strictly after the current clock.")

    finding["status"] = "REMEDIATION_PLANNED"
    finding["assigned_steward_id"] = assignee["id"]
    finding["due_at"] = due_at
    finding["plan_note"] = plan_note
    finding["planned_by_steward_id"] = g.user_id
    db.bump(finding)

    services.recount_steward_load(assignee["id"])
    services.recompute_domain(domain)
    return response.entity(finding)


@bp.post("/mdm/quality-findings/<finding_id>/resolve")
@endpoint("DataSteward", "DataOwner")
def resolve_finding(finding_id):
    finding = db.resolve(db.store.quality_findings, finding_id, "ERR_FINDING_NOT_FOUND")
    body = v.body()
    verified = v.req_num(body, "verified_measured_pct", 0, 100)
    resolution_note = v.opt_str(body, "resolution_note", 0)

    domain = db.domain_of_finding(finding)
    entitle(domain)

    if finding["status"] not in db.OPEN_FINDING_STATUSES:
        fail("ERR_FINDING_ALREADY_CLOSED", "The finding is already closed.")

    rule = db.rule_of_finding(finding)
    if verified < rule["threshold_pct"]:
        fail("ERR_RESOLUTION_BELOW_THRESHOLD",
             "verified_measured_pct must meet the breached rule's threshold_pct.")

    charged = finding["assigned_steward_id"] if finding["status"] == "REMEDIATION_PLANNED" else None

    finding["status"] = "RESOLVED"
    finding["resolved_at"] = db.now()
    finding["measured_pct"] = verified
    finding["gap_pct"] = round2(Decimal("0"))
    finding["resolution_note"] = resolution_note
    db.bump(finding)

    if charged is not None:
        services.recount_steward_load(charged)
    services.recompute_domain(domain)
    db.touch_domain(domain)
    return response.entity(finding)


@bp.post("/mdm/quality-findings/<finding_id>/waive")
@endpoint("DataOwner")
def waive_finding(finding_id):
    finding = db.resolve(db.store.quality_findings, finding_id, "ERR_FINDING_NOT_FOUND")
    body = v.body()
    justification = v.req_str(body, "waiver_justification", 20)

    domain = db.domain_of_finding(finding)
    entitle(domain)

    if finding["status"] not in db.OPEN_FINDING_STATUSES:
        fail("ERR_FINDING_ALREADY_CLOSED", "The finding is already closed.")

    if finding["planned_by_steward_id"] is not None and finding["planned_by_steward_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The steward who planned the remediation may not waive the finding.")

    charged = finding["assigned_steward_id"] if finding["status"] == "REMEDIATION_PLANNED" else None

    finding["status"] = "WAIVED"
    finding["waived_by_steward_id"] = g.user_id
    finding["waiver_justification"] = justification
    finding["resolved_at"] = db.now()
    db.bump(finding)

    if charged is not None:
        services.recount_steward_load(charged)
    services.recompute_domain(domain)
    db.touch_domain(domain)
    return response.entity(finding)
