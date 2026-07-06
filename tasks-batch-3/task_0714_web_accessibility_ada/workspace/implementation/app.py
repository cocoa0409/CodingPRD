import os
from datetime import timedelta

from flask import Flask, request

from db import db
from errors import ApiError, err
from clock import parse_iso, to_iso
import middleware as mw
import response as resp
import services as svc
import validation as val
import calculations as calc

app = Flask(__name__)
app.url_map.strict_slashes = False

VALID_SEVERITIES = {"CRITICAL", "SERIOUS", "MODERATE", "MINOR"}
VALID_WCAG_LEVELS = {"A", "AA", "AAA"}
VALID_TIERS = {"SCAN", "MONITOR", "MANAGED"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return resp.error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return resp.error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return resp.error_response("ERR_RESOURCE_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return resp.error_response("ERR_INTERNAL", str(e), 500)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def auth_and_role(allowed_roles):
    user_id, role = mw.authenticate()
    mw.require_role(role, allowed_roles)
    return user_id, role


def must_get(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Resource not found.")
    return rec


def number_check(value, field, allow_zero=False, min_val=None, max_val=None, strict_gt=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_FIELD_VALUE", f"{field} must be a number.")
    if strict_gt is not None and not (value > strict_gt):
        raise err("ERR_INVALID_FIELD_VALUE", f"{field} must be > {strict_gt}.")
    if min_val is not None and value < min_val:
        raise err("ERR_INVALID_FIELD_VALUE", f"{field} below minimum.")
    if max_val is not None and value > max_val:
        raise err("ERR_INVALID_FIELD_VALUE", f"{field} above maximum.")


def int_check(value, field, min_val=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_FIELD_VALUE", f"{field} must be an integer.")
    if min_val is not None and value < min_val:
        raise err("ERR_INVALID_FIELD_VALUE", f"{field} below minimum.")


# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/compliance/_clock/now", methods=["GET"])
def clock_now():
    auth_and_role({"PlatformAdmin", "OrgAdmin", "ComplianceManager", "AuditEngineer", "RemediationVendor"})
    return resp.ok_object({"current_utc": db.clock.now_iso()})


@app.route("/compliance/_clock/set_current_utc", methods=["POST"])
def clock_set():
    auth_and_role({"PlatformAdmin"})
    body = val.get_json_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise err("ERR_MISSING_REQUIRED_FIELD", "Missing required field: to_iso8601")
    try:
        dt = parse_iso(body["to_iso8601"])
    except ValueError:
        raise err("ERR_INVALID_DATETIME", "to_iso8601 is not a valid ISO 8601 UTC instant.")
    db.clock.set(dt)
    return resp.ok_object({"current_utc": db.clock.now_iso()})


# ===========================================================================
# ORGANIZATIONS
# ===========================================================================
@app.route("/compliance/organizations", methods=["POST"])
def create_organization():
    auth_and_role({"PlatformAdmin"})
    body = val.get_json_body()
    val.require_fields(body, ["legal_name", "contact_email"])
    o = {
        "legal_name": body["legal_name"],
        "contact_email": body["contact_email"],
        "account_credit_cents": 0,
        "open_legal_demand_count": 0,
    }
    svc.stamp_create(o)
    db.organizations[o["id"]] = o
    return resp.ok_object(svc.ser_organization(o), 201)


@app.route("/compliance/organizations/<rid>", methods=["GET"])
def get_organization(rid):
    auth_and_role({"PlatformAdmin", "OrgAdmin", "ComplianceManager"})
    o = must_get(db.organizations, rid)
    return resp.ok_object(svc.ser_organization(o))


@app.route("/compliance/organizations", methods=["GET"])
def list_organizations():
    auth_and_role({"PlatformAdmin"})
    limit, offset = val.parse_pagination()
    items = val.sort_by_created(list(db.organizations.values()))
    page, meta = val.paginate(items, limit, offset)
    return resp.ok_array([svc.ser_organization(o) for o in page], meta)


# ===========================================================================
# SUBSCRIPTIONS
# ===========================================================================
@app.route("/compliance/subscriptions", methods=["POST"])
def create_subscription():
    auth_and_role({"OrgAdmin", "PlatformAdmin"})
    body = val.get_json_body()
    val.require_fields(body, ["organization_id", "tier"])
    org = must_get(db.organizations, body["organization_id"])
    # field validity
    val.require_enum(body["tier"], VALID_TIERS, "tier")
    # one-per-org
    if svc.subscription_for_org(org["id"]) is not None:
        raise err("ERR_SUBSCRIPTION_EXISTS", "Organization already has a subscription.")
    s = {
        "organization_id": org["id"],
        "tier": body["tier"],
        "status": "TRIAL",
        "monthly_invoice_cents": 0,
    }
    svc.stamp_create(s)
    db.subscriptions[s["id"]] = s
    return resp.ok_object(svc.ser_subscription(s), 201)


@app.route("/compliance/subscriptions/<rid>", methods=["GET"])
def get_subscription(rid):
    auth_and_role({"OrgAdmin", "PlatformAdmin", "ComplianceManager"})
    s = must_get(db.subscriptions, rid)
    return resp.ok_object(svc.ser_subscription(s))


@app.route("/compliance/subscriptions", methods=["GET"])
def list_subscriptions():
    auth_and_role({"OrgAdmin", "PlatformAdmin"})
    limit, offset = val.parse_pagination()
    items = list(db.subscriptions.values())
    org_id = request.args.get("organization_id")
    if org_id is not None:
        items = [s for s in items if s["organization_id"] == org_id]
    items = val.sort_by_created(items)
    page, meta = val.paginate(items, limit, offset)
    return resp.ok_array([svc.ser_subscription(s) for s in page], meta)


@app.route("/compliance/subscriptions/<rid>/activate", methods=["POST"])
def activate_subscription(rid):
    auth_and_role({"OrgAdmin"})
    s = must_get(db.subscriptions, rid)
    # state check (priority 5)
    if s["status"] not in ("TRIAL", "PAST_DUE"):
        raise err("ERR_INVALID_STATE", "Subscription not in an activatable state.")
    # OCC (priority 7)
    body = val.get_json_body()
    if "expected_subscription_version" not in body or body["expected_subscription_version"] is None:
        raise err("ERR_MISSING_REQUIRED_FIELD", "Missing required field: expected_subscription_version")
    if body["expected_subscription_version"] != s["version"]:
        raise err("ERR_STALE_SUBSCRIPTION_VERSION", "Subscription version is stale.")
    # compute invoice over org's site roster
    sites = svc.sites_for_org(s["organization_id"])
    s["monthly_invoice_cents"] = calc.subscription_invoice(sites, s["tier"])
    s["status"] = "ACTIVE"
    svc.touch(s)
    return resp.ok_object(svc.ser_subscription(s))


@app.route("/compliance/subscriptions/<rid>/mark-past-due", methods=["POST"])
def mark_past_due(rid):
    auth_and_role({"PlatformAdmin"})
    s = must_get(db.subscriptions, rid)
    if s["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Subscription not ACTIVE.")
    s["status"] = "PAST_DUE"
    svc.touch(s)
    return resp.ok_object(svc.ser_subscription(s))


@app.route("/compliance/subscriptions/<rid>/suspend", methods=["POST"])
def suspend_subscription(rid):
    auth_and_role({"PlatformAdmin"})
    s = must_get(db.subscriptions, rid)
    if s["status"] != "PAST_DUE":
        raise err("ERR_INVALID_STATE", "Subscription not PAST_DUE.")
    s["status"] = "SUSPENDED"
    svc.touch(s)
    return resp.ok_object(svc.ser_subscription(s))


@app.route("/compliance/subscriptions/<rid>/cancel", methods=["POST"])
def cancel_subscription(rid):
    auth_and_role({"OrgAdmin"})
    s = must_get(db.subscriptions, rid)
    if s["status"] not in ("TRIAL", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Subscription not in TRIAL or SUSPENDED.")
    s["status"] = "CANCELLED"
    svc.touch(s)
    return resp.ok_object(svc.ser_subscription(s))


# ===========================================================================
# SITES
# ===========================================================================
@app.route("/compliance/sites", methods=["POST"])
def create_site():
    auth_and_role({"OrgAdmin", "PlatformAdmin"})
    body = val.get_json_body()
    val.require_fields(body, ["organization_id", "url", "audited_page_count"])
    org = must_get(db.organizations, body["organization_id"])
    # duplicate URL guard (priority 14) before field validity? Ordering:
    # state(5)... business_constraint DUPLICATE(14) comes before field validity(17).
    # but page_count validity is field validity(17). Duplicate check needs url.
    # Evaluate duplicate URL guard, then field validity.
    page_count = body["audited_page_count"]
    # duplicate site url within org
    for s in db.sites.values():
        if s["organization_id"] == org["id"] and s["url"] == body["url"]:
            raise err("ERR_DUPLICATE_SITE_URL", "Site URL already exists in organization.")
    int_check(page_count, "audited_page_count", min_val=1)
    s = {
        "organization_id": org["id"],
        "url": body["url"],
        "audited_page_count": page_count,
        "audit_posture": "UNSCANNED",
        "risk_exposure_score": 0.0,
    }
    svc.stamp_create(s)
    db.sites[s["id"]] = s
    return resp.ok_object(svc.ser_site(s), 201)


@app.route("/compliance/sites/<rid>", methods=["GET"])
def get_site(rid):
    auth_and_role({"OrgAdmin", "PlatformAdmin", "ComplianceManager", "AuditEngineer"})
    s = must_get(db.sites, rid)
    return resp.ok_object(svc.ser_site(s))


@app.route("/compliance/sites", methods=["GET"])
def list_sites():
    auth_and_role({"OrgAdmin", "PlatformAdmin", "ComplianceManager", "AuditEngineer"})
    limit, offset = val.parse_pagination()
    items = list(db.sites.values())
    org_id = request.args.get("organization_id")
    if org_id is not None:
        items = [s for s in items if s["organization_id"] == org_id]
    items = val.sort_by_created(items)
    page, meta = val.paginate(items, limit, offset)
    return resp.ok_array([svc.ser_site(s) for s in page], meta)


@app.route("/compliance/sites/<rid>/risk-projection", methods=["GET"])
def risk_projection(rid):
    auth_and_role({"ComplianceManager", "AuditEngineer", "OrgAdmin"})
    site = must_get(db.sites, rid)
    current = site["risk_exposure_score"]
    # projected: exclude findings backed by a task in IN_PROGRESS or SUBMITTED
    fs = svc.findings_for_site(rid)
    closing_finding_ids = set()
    for t in db.remediation_tasks.values():
        if t["status"] in ("IN_PROGRESS", "SUBMITTED"):
            closing_finding_ids.add(t["finding_id"])
    projected_findings = [f for f in fs if f["id"] not in closing_finding_ids]
    has_demand = svc.site_has_active_demand(rid)
    projected = calc.risk_exposure(projected_findings, has_demand, db.clock.now(), calc.RISK_OPEN_SET)
    return resp.ok_object({
        "projected_risk_exposure_score": projected,
        "current_risk_exposure_score": current,
    })


# ===========================================================================
# SCANS
# ===========================================================================
@app.route("/compliance/scans", methods=["POST"])
def create_scan():
    auth_and_role({"AuditEngineer"})
    body = val.get_json_body()
    val.require_fields(body, ["site_id", "wcag_target_level"])
    site = must_get(db.sites, body["site_id"])
    val.require_enum(body["wcag_target_level"], VALID_WCAG_LEVELS, "wcag_target_level")
    s = {
        "site_id": site["id"],
        "wcag_target_level": body["wcag_target_level"],
        "status": "QUEUED",
        "started_at": None,
        "completed_at": None,
        "provisional_conformance_score": None,
        "finding_count": 0,
    }
    svc.stamp_create(s)
    db.scans[s["id"]] = s
    return resp.ok_object(svc.ser_scan(s), 201)


@app.route("/compliance/scans/<rid>", methods=["GET"])
def get_scan(rid):
    auth_and_role({"AuditEngineer", "ComplianceManager", "OrgAdmin", "PlatformAdmin"})
    s = must_get(db.scans, rid)
    return resp.ok_object(svc.ser_scan(s))


@app.route("/compliance/scans", methods=["GET"])
def list_scans():
    auth_and_role({"AuditEngineer", "ComplianceManager", "OrgAdmin", "PlatformAdmin"})
    limit, offset = val.parse_pagination()
    items = list(db.scans.values())
    site_id = request.args.get("site_id")
    if site_id is not None:
        items = [s for s in items if s["site_id"] == site_id]
    items = val.sort_by_created(items)
    page, meta = val.paginate(items, limit, offset)
    return resp.ok_array([svc.ser_scan(s) for s in page], meta)


@app.route("/compliance/scans/<rid>/start", methods=["POST"])
def start_scan(rid):
    auth_and_role({"AuditEngineer"})
    s = must_get(db.scans, rid)
    if s["status"] != "QUEUED":
        raise err("ERR_INVALID_STATE", "Scan not QUEUED.")
    # subscription must be TRIAL or ACTIVE (priority 11)
    site = db.sites.get(s["site_id"])
    sub = svc.subscription_for_org(site["organization_id"]) if site else None
    if sub is None or sub["status"] not in ("TRIAL", "ACTIVE"):
        raise err("ERR_SUBSCRIPTION_NOT_ACTIVE", "Site's subscription is not active.")
    s["started_at"] = db.clock.now()
    s["status"] = "RUNNING"
    svc.touch(s)
    return resp.ok_object(svc.ser_scan(s))


@app.route("/compliance/scans/<rid>/complete", methods=["POST"])
def complete_scan(rid):
    auth_and_role({"AuditEngineer"})
    s = must_get(db.scans, rid)
    if s["status"] != "RUNNING":
        raise err("ERR_INVALID_STATE", "Scan not RUNNING.")
    body = val.get_json_body()
    findings_payload = body.get("findings")
    # empty findings guard (priority 12)
    if findings_payload is None:
        # missing required field falls under empty-findings semantics; per priority,
        # ERR_EMPTY_FINDINGS (12) precedes required-field (18). Spec: payload must
        # contain >= 1 entry. Treat missing/empty as ERR_EMPTY_FINDINGS.
        raise err("ERR_EMPTY_FINDINGS", "findings payload must be non-empty.")
    if not isinstance(findings_payload, list) or len(findings_payload) == 0:
        raise err("ERR_EMPTY_FINDINGS", "findings payload must be non-empty.")
    # field validity on each finding entry (priority 17)
    for entry in findings_payload:
        if not isinstance(entry, dict):
            raise err("ERR_INVALID_FIELD_VALUE", "Invalid finding entry.")
        if "severity" not in entry or entry["severity"] is None or "wcag_criterion" not in entry or entry["wcag_criterion"] is None:
            raise err("ERR_MISSING_REQUIRED_FIELD", "finding entry missing required field.")
        if entry["severity"] not in VALID_SEVERITIES:
            raise err("ERR_INVALID_FIELD_VALUE", "Invalid finding severity.")

    now = db.clock.now()
    s["completed_at"] = now
    s["status"] = "COMPLETED"
    emitted = []
    for entry in findings_payload:
        f = {
            "scan_id": s["id"],
            "site_id": s["site_id"],
            "wcag_criterion": entry["wcag_criterion"],
            "severity": entry["severity"],
            "status": "OPEN",
            "sla_due_at": calc.sla_due_at(now, entry["severity"]),
        }
        svc.stamp_create(f)
        db.findings[f["id"]] = f
        emitted.append(f)
    s["finding_count"] = len(emitted)
    # provisional conformance score (REMEDIATED_SET = {RESOLVED})
    scan_findings = svc.findings_for_scan(s["id"])
    s["provisional_conformance_score"] = calc.conformance_score(scan_findings, {"RESOLVED"})
    svc.touch(s)
    # cascade: site posture then risk
    site = db.sites.get(s["site_id"])
    if site:
        svc.recompute_site_posture(site)
        svc.recompute_site_risk(site)
    return resp.ok_object(svc.ser_scan(s))


@app.route("/compliance/scans/<rid>/fail", methods=["POST"])
def fail_scan(rid):
    auth_and_role({"AuditEngineer"})
    s = must_get(db.scans, rid)
    if s["status"] != "RUNNING":
        raise err("ERR_INVALID_STATE", "Scan not RUNNING.")
    s["status"] = "FAILED"
    svc.touch(s)
    return resp.ok_object(svc.ser_scan(s))


@app.route("/compliance/scans/<rid>/cancel", methods=["POST"])
def cancel_scan(rid):
    auth_and_role({"AuditEngineer"})
    s = must_get(db.scans, rid)
    if s["status"] != "QUEUED":
        raise err("ERR_INVALID_STATE", "Scan not QUEUED.")
    s["status"] = "CANCELLED"
    svc.touch(s)
    return resp.ok_object(svc.ser_scan(s))


# ===========================================================================
# FINDINGS
# ===========================================================================
@app.route("/compliance/findings/<rid>", methods=["GET"])
def get_finding(rid):
    auth_and_role({"AuditEngineer", "RemediationVendor", "ComplianceManager", "OrgAdmin", "PlatformAdmin"})
    f = must_get(db.findings, rid)
    return resp.ok_object(svc.ser_finding(f))


@app.route("/compliance/findings", methods=["GET"])
def list_findings():
    auth_and_role({"AuditEngineer", "RemediationVendor", "ComplianceManager", "OrgAdmin", "PlatformAdmin"})
    limit, offset = val.parse_pagination()
    items = list(db.findings.values())
    scan_id = request.args.get("scan_id")
    site_id = request.args.get("site_id")
    if scan_id is not None:
        items = [f for f in items if f["scan_id"] == scan_id]
    if site_id is not None:
        items = [f for f in items if f["site_id"] == site_id]
    items = val.sort_by_created(items)
    page, meta = val.paginate(items, limit, offset)
    return resp.ok_array([svc.ser_finding(f) for f in page], meta)


@app.route("/compliance/findings/<rid>/accept-risk", methods=["POST"])
def accept_risk(rid):
    auth_and_role({"ComplianceManager"})
    f = must_get(db.findings, rid)
    if f["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Finding not OPEN.")
    # legal block guard (priority 8)
    site = db.sites.get(f["site_id"])
    if site and site["audit_posture"] == "BLOCKED":
        raise err("ERR_SITE_BLOCKED_BY_LEGAL", "Site is blocked by an active legal demand.")
    f["status"] = "WONT_FIX_ACCEPTED"
    svc.touch(f)
    if site:
        svc.recompute_site_posture(site)
        svc.recompute_site_risk(site)
    return resp.ok_object(svc.ser_finding(f))


# ===========================================================================
# REMEDIATION TASKS
# ===========================================================================
@app.route("/compliance/remediation-tasks", methods=["POST"])
def create_remediation_task():
    auth_and_role({"RemediationVendor"})
    body = val.get_json_body()
    val.require_fields(body, ["finding_id", "assigned_vendor_id", "estimated_effort_hours"])
    # existence (priority 3): finding, and supersedes target if present
    finding = must_get(db.findings, body["finding_id"])
    supersedes_id = body.get("supersedes_task_id")
    supersede_target = None
    if supersedes_id is not None:
        supersede_target = must_get(db.remediation_tasks, supersedes_id)
    # FK consistency (priority 4): supersede target must belong to this finding
    if supersede_target is not None and supersede_target["finding_id"] != finding["id"]:
        raise err("ERR_FK_MISMATCH", "supersedes_task_id does not belong to finding.")
    # state check (priority 5): finding must be OPEN (first task) or REOPENED (superseding)
    if supersedes_id is None:
        if finding["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Finding not OPEN.")
    else:
        if finding["status"] != "REOPENED":
            raise err("ERR_INVALID_STATE", "Finding not REOPENED.")
    # legal block guard (priority 8)
    site = db.sites.get(finding["site_id"])
    if site and site["audit_posture"] == "BLOCKED":
        raise err("ERR_SITE_BLOCKED_BY_LEGAL", "Site is blocked by an active legal demand.")
    # supersede target must be REJECTED (priority 16.5)
    if supersedes_id is not None and supersede_target["status"] != "REJECTED":
        raise err("ERR_SUPERSEDE_TARGET_NOT_REJECTED", "Supersede target not REJECTED.")
    # field validity (priority 17): effort_hours > 0
    number_check(body["estimated_effort_hours"], "estimated_effort_hours", strict_gt=0)

    t = {
        "finding_id": finding["id"],
        "assigned_vendor_id": body["assigned_vendor_id"],
        "supersedes_task_id": supersedes_id,
        "status": "ASSIGNED",
        "estimated_effort_hours": body["estimated_effort_hours"],
    }
    svc.stamp_create(t)
    db.remediation_tasks[t["id"]] = t
    # finding transition
    if supersedes_id is None:
        finding["status"] = "IN_REMEDIATION"
    else:
        supersede_target["status"] = "SUPERSEDED"
        svc.touch(supersede_target)
        finding["status"] = "IN_REMEDIATION"
    svc.touch(finding)
    return resp.ok_object(svc.ser_remediation_task(t), 201)


@app.route("/compliance/remediation-tasks/<rid>", methods=["GET"])
def get_remediation_task(rid):
    auth_and_role({"RemediationVendor", "AuditEngineer", "ComplianceManager", "PlatformAdmin"})
    t = must_get(db.remediation_tasks, rid)
    return resp.ok_object(svc.ser_remediation_task(t))


@app.route("/compliance/remediation-tasks", methods=["GET"])
def list_remediation_tasks():
    auth_and_role({"RemediationVendor", "AuditEngineer", "ComplianceManager", "PlatformAdmin"})
    limit, offset = val.parse_pagination()
    items = list(db.remediation_tasks.values())
    finding_id = request.args.get("finding_id")
    supersedes_task_id = request.args.get("supersedes_task_id")
    if finding_id is not None:
        items = [t for t in items if t["finding_id"] == finding_id]
    if supersedes_task_id is not None:
        items = [t for t in items if t["supersedes_task_id"] == supersedes_task_id]
    items = val.sort_by_created(items)
    page, meta = val.paginate(items, limit, offset)
    return resp.ok_array([svc.ser_remediation_task(t) for t in page], meta)


@app.route("/compliance/remediation-tasks/<rid>/begin", methods=["POST"])
def begin_remediation_task(rid):
    auth_and_role({"RemediationVendor"})
    t = must_get(db.remediation_tasks, rid)
    if t["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "Task not ASSIGNED.")
    t["status"] = "IN_PROGRESS"
    svc.touch(t)
    return resp.ok_object(svc.ser_remediation_task(t))


@app.route("/compliance/remediation-tasks/<rid>/submit", methods=["POST"])
def submit_remediation_task(rid):
    auth_and_role({"RemediationVendor"})
    t = must_get(db.remediation_tasks, rid)
    finding = db.findings.get(t["finding_id"])
    if t["status"] != "IN_PROGRESS" or finding is None or finding["status"] != "IN_REMEDIATION":
        raise err("ERR_INVALID_STATE", "Task or finding not in a submittable state.")
    t["status"] = "SUBMITTED"
    svc.touch(t)
    finding["status"] = "RETEST_PENDING"
    svc.touch(finding)
    return resp.ok_object(svc.ser_remediation_task(t))


# ===========================================================================
# RETEST RUNS
# ===========================================================================
@app.route("/compliance/retest-runs", methods=["POST"])
def create_retest_run():
    auth_and_role({"AuditEngineer"})
    body = val.get_json_body()
    val.require_fields(body, ["finding_id", "remediation_task_id", "outcome"])
    # existence (priority 3)
    finding = must_get(db.findings, body["finding_id"])
    task = must_get(db.remediation_tasks, body["remediation_task_id"])
    # FK consistency (priority 4): task.finding_id == body finding_id
    if task["finding_id"] != finding["id"]:
        raise err("ERR_FK_MISMATCH", "remediation_task does not belong to finding.")
    # state check (priority 5): finding RETEST_PENDING, task SUBMITTED
    if finding["status"] != "RETEST_PENDING" or task["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Finding or task not in a retestable state.")
    # field validity (priority 17): outcome enum
    val.require_enum(body["outcome"], {"PASS", "FAIL"}, "outcome")

    r = {
        "finding_id": finding["id"],
        "remediation_task_id": task["id"],
        "outcome": body["outcome"],
        "tested_at": db.clock.now(),
    }
    svc.stamp_create(r, common_fields=False)
    db.retest_runs[r["id"]] = r

    if body["outcome"] == "PASS":
        finding["status"] = "RESOLVED"
        task["status"] = "ACCEPTED"
        svc.touch(task)
        svc.touch(finding)
        site = db.sites.get(finding["site_id"])
        if site:
            svc.recompute_site_posture(site)
            svc.recompute_site_risk(site)
    else:
        finding["status"] = "REOPENED"
        task["status"] = "REJECTED"
        svc.touch(task)
        svc.touch(finding)
    return resp.ok_object(svc.ser_retest_run(r), 201)


@app.route("/compliance/retest-runs/<rid>", methods=["GET"])
def get_retest_run(rid):
    auth_and_role({"AuditEngineer", "ComplianceManager", "RemediationVendor", "PlatformAdmin"})
    r = must_get(db.retest_runs, rid)
    return resp.ok_object(svc.ser_retest_run(r))


@app.route("/compliance/retest-runs", methods=["GET"])
def list_retest_runs():
    auth_and_role({"AuditEngineer", "ComplianceManager", "RemediationVendor", "PlatformAdmin"})
    limit, offset = val.parse_pagination()
    items = list(db.retest_runs.values())
    finding_id = request.args.get("finding_id")
    task_id = request.args.get("remediation_task_id")
    if finding_id is not None:
        items = [r for r in items if r["finding_id"] == finding_id]
    if task_id is not None:
        items = [r for r in items if r["remediation_task_id"] == task_id]
    items = val.sort_by_created(items)
    page, meta = val.paginate(items, limit, offset)
    return resp.ok_array([svc.ser_retest_run(r) for r in page], meta)


# ===========================================================================
# VPAT REPORTS
# ===========================================================================
@app.route("/compliance/vpat-reports", methods=["POST"])
def create_vpat():
    auth_and_role({"ComplianceManager"})
    body = val.get_json_body()
    val.require_fields(body, ["site_id", "source_scan_id"])
    site = must_get(db.sites, body["site_id"])
    scan = must_get(db.scans, body["source_scan_id"])
    # FK consistency (priority 4): scan belongs to the site
    if scan["site_id"] != site["id"]:
        raise err("ERR_FK_MISMATCH", "source_scan does not belong to site.")
    # scan completed (priority 9)
    if scan["status"] != "COMPLETED":
        raise err("ERR_SCAN_NOT_COMPLETED", "Source scan not COMPLETED.")
    v = {
        "site_id": site["id"],
        "source_scan_id": scan["id"],
        "pinned_scan_version": scan["version"],
        "status": "DRAFT",
        "certified_conformance_score": None,
        "conformance_level": None,
    }
    svc.stamp_create(v)
    db.vpat_reports[v["id"]] = v
    return resp.ok_object(svc.ser_vpat(v), 201)


@app.route("/compliance/vpat-reports/<rid>", methods=["GET"])
def get_vpat(rid):
    auth_and_role({"ComplianceManager", "OrgAdmin", "PlatformAdmin", "AuditEngineer"})
    v = must_get(db.vpat_reports, rid)
    return resp.ok_object(svc.ser_vpat(v))


@app.route("/compliance/vpat-reports", methods=["GET"])
def list_vpat():
    auth_and_role({"ComplianceManager", "OrgAdmin", "PlatformAdmin", "AuditEngineer"})
    limit, offset = val.parse_pagination()
    items = list(db.vpat_reports.values())
    site_id = request.args.get("site_id")
    source_scan_id = request.args.get("source_scan_id")
    if site_id is not None:
        items = [v for v in items if v["site_id"] == site_id]
    if source_scan_id is not None:
        items = [v for v in items if v["source_scan_id"] == source_scan_id]
    items = val.sort_by_created(items)
    page, meta = val.paginate(items, limit, offset)
    return resp.ok_array([svc.ser_vpat(v) for v in page], meta)


@app.route("/compliance/vpat-reports/<rid>/issue", methods=["POST"])
def issue_vpat(rid):
    auth_and_role({"ComplianceManager"})
    v = must_get(db.vpat_reports, rid)
    scan = db.scans.get(v["source_scan_id"])
    # state check (priority 5): report DRAFT
    if v["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Report not DRAFT.")
    # OCC stale-scan (priority 6)
    body = val.get_json_body()
    if "expected_scan_version" not in body or body["expected_scan_version"] is None:
        raise err("ERR_MISSING_REQUIRED_FIELD", "Missing required field: expected_scan_version")
    live_version = scan["version"] if scan else None
    if body["expected_scan_version"] != live_version or v["pinned_scan_version"] != live_version:
        raise err("ERR_STALE_SCAN_VERSION", "Source scan version is stale.")
    # legal block guard (priority 8)
    site = db.sites.get(v["site_id"])
    if site and site["audit_posture"] == "BLOCKED":
        raise err("ERR_SITE_BLOCKED_BY_LEGAL", "Site is blocked by an active legal demand.")
    # scan completed requirement (defensive; scan was COMPLETED at create)
    if scan is None or scan["status"] != "COMPLETED":
        raise err("ERR_SCAN_NOT_COMPLETED", "Source scan not COMPLETED.")

    # certified score (REMEDIATED_SET = {RESOLVED, WONT_FIX_ACCEPTED})
    scan_findings = svc.findings_for_scan(scan["id"])
    score = calc.conformance_score(scan_findings, {"RESOLVED", "WONT_FIX_ACCEPTED"})
    level = calc.conformance_level(score)
    v["certified_conformance_score"] = score
    v["conformance_level"] = level
    v["status"] = "ISSUED"
    svc.touch(v)
    # cascade: org credit
    org = db.organizations.get(site["organization_id"]) if site else None
    if org:
        org["account_credit_cents"] = org["account_credit_cents"] + calc.remediation_credit(level)
        svc.touch(org)
    return resp.ok_object(svc.ser_vpat(v))


@app.route("/compliance/vpat-reports/<rid>/revoke", methods=["POST"])
def revoke_vpat(rid):
    auth_and_role({"ComplianceManager"})
    v = must_get(db.vpat_reports, rid)
    if v["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Report not ISSUED.")
    v["status"] = "REVOKED"
    svc.touch(v)
    # cascade: GRANTED certifications backed by this report -> REVOKED
    for c in db.certifications.values():
        if c["vpat_report_id"] == v["id"] and c["status"] == "GRANTED":
            c["status"] = "REVOKED"
            svc.touch(c)
    return resp.ok_object(svc.ser_vpat(v))


# ===========================================================================
# LEGAL DEMANDS
# ===========================================================================
@app.route("/compliance/legal-demands", methods=["POST"])
def create_legal_demand():
    auth_and_role({"ComplianceManager"})
    body = val.get_json_body()
    val.require_fields(body, ["site_id", "claimant_name", "response_due_at"])
    site = must_get(db.sites, body["site_id"])
    # datetime validity (priority 16.7)
    try:
        due = parse_iso(body["response_due_at"])
    except ValueError:
        raise err("ERR_INVALID_DATETIME", "response_due_at is not a valid ISO 8601 UTC instant.")
    d = {
        "site_id": site["id"],
        "claimant_name": body["claimant_name"],
        "status": "RECEIVED",
        "response_due_at": due,
    }
    svc.stamp_create(d)
    db.legal_demands[d["id"]] = d
    # cascade: org count -> site posture (BLOCKED) -> site risk (legal bump)
    org = svc.org_for_site(site)
    if org:
        svc.recompute_org_open_demand_count(org)
    svc.recompute_site_posture(site)
    svc.recompute_site_risk(site)
    return resp.ok_object(svc.ser_legal_demand(d), 201)


@app.route("/compliance/legal-demands/<rid>", methods=["GET"])
def get_legal_demand(rid):
    auth_and_role({"ComplianceManager", "OrgAdmin", "PlatformAdmin"})
    d = must_get(db.legal_demands, rid)
    return resp.ok_object(svc.ser_legal_demand(d))


@app.route("/compliance/legal-demands", methods=["GET"])
def list_legal_demands():
    auth_and_role({"ComplianceManager", "OrgAdmin", "PlatformAdmin"})
    limit, offset = val.parse_pagination()
    items = list(db.legal_demands.values())
    site_id = request.args.get("site_id")
    if site_id is not None:
        items = [d for d in items if d["site_id"] == site_id]
    items = val.sort_by_created(items)
    page, meta = val.paginate(items, limit, offset)
    return resp.ok_array([svc.ser_legal_demand(d) for d in page], meta)


def _legal_unblock_cascade(d):
    site = db.sites.get(d["site_id"])
    org = svc.org_for_site(site) if site else None
    if org:
        svc.recompute_org_open_demand_count(org)
    if site:
        svc.recompute_site_posture(site)
        svc.recompute_site_risk(site)


@app.route("/compliance/legal-demands/<rid>/respond", methods=["POST"])
def respond_legal_demand(rid):
    auth_and_role({"ComplianceManager"})
    d = must_get(db.legal_demands, rid)
    if d["status"] != "RECEIVED":
        raise err("ERR_INVALID_STATE", "Demand not RECEIVED.")
    d["status"] = "RESPONDING"
    svc.touch(d)
    return resp.ok_object(svc.ser_legal_demand(d))


@app.route("/compliance/legal-demands/<rid>/escalate", methods=["POST"])
def escalate_legal_demand(rid):
    auth_and_role({"ComplianceManager"})
    d = must_get(db.legal_demands, rid)
    if d["status"] != "RESPONDING":
        raise err("ERR_INVALID_STATE", "Demand not RESPONDING.")
    d["status"] = "ESCALATED"
    svc.touch(d)
    return resp.ok_object(svc.ser_legal_demand(d))


@app.route("/compliance/legal-demands/<rid>/resolve", methods=["POST"])
def resolve_legal_demand(rid):
    auth_and_role({"ComplianceManager"})
    d = must_get(db.legal_demands, rid)
    if d["status"] not in ("RESPONDING", "ESCALATED"):
        raise err("ERR_INVALID_STATE", "Demand not RESPONDING or ESCALATED.")
    d["status"] = "RESOLVED"
    svc.touch(d)
    _legal_unblock_cascade(d)
    return resp.ok_object(svc.ser_legal_demand(d))


@app.route("/compliance/legal-demands/<rid>/dismiss", methods=["POST"])
def dismiss_legal_demand(rid):
    auth_and_role({"ComplianceManager"})
    d = must_get(db.legal_demands, rid)
    if d["status"] != "RECEIVED":
        raise err("ERR_INVALID_STATE", "Demand not RECEIVED.")
    d["status"] = "DISMISSED"
    svc.touch(d)
    _legal_unblock_cascade(d)
    return resp.ok_object(svc.ser_legal_demand(d))


# ===========================================================================
# MONITORING CHECKS
# ===========================================================================
@app.route("/compliance/monitoring-checks", methods=["POST"])
def create_monitoring_check():
    auth_and_role({"PlatformAdmin", "AuditEngineer"})
    body = val.get_json_body()
    val.require_fields(body, ["site_id", "regressions_found"])
    site = must_get(db.sites, body["site_id"])
    int_check(body["regressions_found"], "regressions_found", min_val=0)
    m = {
        "site_id": site["id"],
        "regressions_found": body["regressions_found"],
        "checked_at": db.clock.now(),
    }
    svc.stamp_create(m, common_fields=False)
    db.monitoring_checks[m["id"]] = m
    return resp.ok_object(svc.ser_monitoring_check(m), 201)


@app.route("/compliance/monitoring-checks/<rid>", methods=["GET"])
def get_monitoring_check(rid):
    auth_and_role({"PlatformAdmin", "AuditEngineer", "ComplianceManager", "OrgAdmin"})
    m = must_get(db.monitoring_checks, rid)
    return resp.ok_object(svc.ser_monitoring_check(m))


@app.route("/compliance/monitoring-checks", methods=["GET"])
def list_monitoring_checks():
    auth_and_role({"PlatformAdmin", "AuditEngineer", "ComplianceManager", "OrgAdmin"})
    limit, offset = val.parse_pagination()
    items = list(db.monitoring_checks.values())
    site_id = request.args.get("site_id")
    if site_id is not None:
        items = [m for m in items if m["site_id"] == site_id]
    items = val.sort_by_created(items)
    page, meta = val.paginate(items, limit, offset)
    return resp.ok_array([svc.ser_monitoring_check(m) for m in page], meta)


# ===========================================================================
# TRAINING ENROLLMENTS
# ===========================================================================
@app.route("/compliance/training-enrollments", methods=["POST"])
def create_training():
    auth_and_role({"OrgAdmin"})
    body = val.get_json_body()
    val.require_fields(body, ["organization_id", "learner_email"])
    org = must_get(db.organizations, body["organization_id"])
    t = {
        "organization_id": org["id"],
        "learner_email": body["learner_email"],
        "status": "ENROLLED",
        "score_pct": None,
    }
    svc.stamp_create(t)
    db.training_enrollments[t["id"]] = t
    return resp.ok_object(svc.ser_training(t), 201)


@app.route("/compliance/training-enrollments/<rid>", methods=["GET"])
def get_training(rid):
    auth_and_role({"OrgAdmin", "PlatformAdmin"})
    t = must_get(db.training_enrollments, rid)
    return resp.ok_object(svc.ser_training(t))


@app.route("/compliance/training-enrollments", methods=["GET"])
def list_training():
    auth_and_role({"OrgAdmin", "PlatformAdmin"})
    limit, offset = val.parse_pagination()
    items = list(db.training_enrollments.values())
    org_id = request.args.get("organization_id")
    if org_id is not None:
        items = [t for t in items if t["organization_id"] == org_id]
    items = val.sort_by_created(items)
    page, meta = val.paginate(items, limit, offset)
    return resp.ok_array([svc.ser_training(t) for t in page], meta)


@app.route("/compliance/training-enrollments/<rid>/start", methods=["POST"])
def start_training(rid):
    auth_and_role({"OrgAdmin"})
    t = must_get(db.training_enrollments, rid)
    if t["status"] != "ENROLLED":
        raise err("ERR_INVALID_STATE", "Enrollment not ENROLLED.")
    t["status"] = "IN_PROGRESS"
    svc.touch(t)
    return resp.ok_object(svc.ser_training(t))


@app.route("/compliance/training-enrollments/<rid>/complete", methods=["POST"])
def complete_training(rid):
    auth_and_role({"OrgAdmin"})
    t = must_get(db.training_enrollments, rid)
    if t["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Enrollment not IN_PROGRESS.")
    body = val.get_json_body()
    if "score_pct" not in body or body["score_pct"] is None:
        # pass-threshold guard (13) precedes required-field (18); but a missing
        # score cannot be compared. Spec: score required only at completion.
        raise err("ERR_MISSING_REQUIRED_FIELD", "Missing required field: score_pct")
    score = body["score_pct"]
    # pass threshold (priority 13) — checked before field-range validity per ordering
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise err("ERR_INVALID_FIELD_VALUE", "score_pct must be a number.")
    if score < 80:
        # below pass; but if also out of 0-100 range, ERR_SCORE_BELOW_PASS (13)
        # has higher priority than ERR_INVALID_FIELD_VALUE (17).
        raise err("ERR_SCORE_BELOW_PASS", "score_pct below pass threshold of 80.")
    if score > 100:
        raise err("ERR_INVALID_FIELD_VALUE", "score_pct out of range 0-100.")
    t["score_pct"] = score
    t["status"] = "COMPLETED"
    svc.touch(t)
    return resp.ok_object(svc.ser_training(t))


@app.route("/compliance/training-enrollments/<rid>/expire", methods=["POST"])
def expire_training(rid):
    auth_and_role({"PlatformAdmin"})
    t = must_get(db.training_enrollments, rid)
    if t["status"] != "ENROLLED":
        raise err("ERR_INVALID_STATE", "Enrollment not ENROLLED.")
    t["status"] = "EXPIRED"
    svc.touch(t)
    return resp.ok_object(svc.ser_training(t))


# ===========================================================================
# CERTIFICATIONS
# ===========================================================================
@app.route("/compliance/certifications", methods=["POST"])
def create_certification():
    auth_and_role({"ComplianceManager"})
    body = val.get_json_body()
    val.require_fields(body, ["site_id", "vpat_report_id"])
    site = must_get(db.sites, body["site_id"])
    vpat = must_get(db.vpat_reports, body["vpat_report_id"])
    # FK consistency (priority 4): vpat report covers this site
    if vpat["site_id"] != site["id"]:
        raise err("ERR_FK_MISMATCH", "vpat_report does not cover site.")
    # vpat issued requirement (priority 10)
    if vpat["status"] != "ISSUED":
        raise err("ERR_VPAT_NOT_ISSUED", "VPAT report not ISSUED.")
    now = db.clock.now()
    c = {
        "site_id": site["id"],
        "vpat_report_id": vpat["id"],
        "status": "GRANTED",
        "badge_token": "badge_" + db.new_id().replace("-", ""),
        "expires_at": now + timedelta(days=365),
    }
    svc.stamp_create(c)
    db.certifications[c["id"]] = c
    return resp.ok_object(svc.ser_certification(c), 201)


@app.route("/compliance/certifications/<rid>", methods=["GET"])
def get_certification(rid):
    auth_and_role({"ComplianceManager", "OrgAdmin", "PlatformAdmin", "AuditEngineer"})
    c = must_get(db.certifications, rid)
    return resp.ok_object(svc.ser_certification(c))


@app.route("/compliance/certifications", methods=["GET"])
def list_certifications():
    auth_and_role({"ComplianceManager", "OrgAdmin", "PlatformAdmin", "AuditEngineer"})
    limit, offset = val.parse_pagination()
    items = list(db.certifications.values())
    site_id = request.args.get("site_id")
    vpat_report_id = request.args.get("vpat_report_id")
    if site_id is not None:
        items = [c for c in items if c["site_id"] == site_id]
    if vpat_report_id is not None:
        items = [c for c in items if c["vpat_report_id"] == vpat_report_id]
    items = val.sort_by_created(items)
    page, meta = val.paginate(items, limit, offset)
    return resp.ok_array([svc.ser_certification(c) for c in page], meta)


@app.route("/compliance/certifications/<rid>/revoke", methods=["POST"])
def revoke_certification(rid):
    auth_and_role({"ComplianceManager"})
    c = must_get(db.certifications, rid)
    if c["status"] != "GRANTED":
        raise err("ERR_INVALID_STATE", "Certification not GRANTED.")
    c["status"] = "REVOKED"
    svc.touch(c)
    return resp.ok_object(svc.ser_certification(c))


@app.route("/compliance/certifications/<rid>/expire", methods=["POST"])
def expire_certification(rid):
    auth_and_role({"PlatformAdmin"})
    c = must_get(db.certifications, rid)
    if c["status"] != "GRANTED":
        raise err("ERR_INVALID_STATE", "Certification not GRANTED.")
    # not-yet-expired guard (priority 16): now > expires_at
    if not (db.clock.now() > c["expires_at"]):
        raise err("ERR_NOT_YET_EXPIRED", "Certification not yet past its expiry.")
    c["status"] = "EXPIRED"
    svc.touch(c)
    return resp.ok_object(svc.ser_certification(c))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
