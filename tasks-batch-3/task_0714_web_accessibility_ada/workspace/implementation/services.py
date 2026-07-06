"""Domain services: entity creation, serialization, recompute cascades, transitions."""
from db import db
from clock import to_iso
import calculations as calc

ACTIVE_DEMAND_STATUSES = {"RECEIVED", "RESPONDING", "ESCALATED"}
FINDING_OPEN_FOR_POSTURE = {"OPEN", "IN_REMEDIATION", "RETEST_PENDING"}


# ---------------------------------------------------------------------------
# Common-field bookkeeping
# ---------------------------------------------------------------------------
def stamp_create(rec, common_fields=True):
    now = db.clock.now()
    rec["id"] = db.new_id()
    rec["created_at"] = now
    rec["_seq"] = db.next_seq()
    if common_fields:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation: refresh updated_at and bump version (for common-field entities)."""
    rec["updated_at"] = db.clock.now()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def findings_for_scan(scan_id):
    return [f for f in db.findings.values() if f["scan_id"] == scan_id]


def findings_for_site(site_id):
    return [f for f in db.findings.values() if f["site_id"] == site_id]


def demands_for_site(site_id):
    return [d for d in db.legal_demands.values() if d["site_id"] == site_id]


def site_has_active_demand(site_id):
    return any(d["status"] in ACTIVE_DEMAND_STATUSES for d in demands_for_site(site_id))


def subscription_for_org(org_id):
    for s in db.subscriptions.values():
        if s["organization_id"] == org_id:
            return s
    return None


def sites_for_org(org_id):
    return [s for s in db.sites.values() if s["organization_id"] == org_id]


# ---------------------------------------------------------------------------
# Derived recomputations (cascades)
# ---------------------------------------------------------------------------
def recompute_site_posture(site):
    """Compute audit_posture. Mutation of the site (touch)."""
    if site_has_active_demand(site["id"]):
        posture = "BLOCKED"
    else:
        fs = findings_for_site(site["id"])
        if not _site_has_completed_scan(site["id"]):
            posture = "UNSCANNED"
        elif any(f["status"] in FINDING_OPEN_FOR_POSTURE for f in fs):
            posture = "AT_RISK"
        else:
            posture = "CLEAN"
    site["audit_posture"] = posture
    touch(site)


def _site_has_completed_scan(site_id):
    return any(
        s["site_id"] == site_id and s["status"] == "COMPLETED"
        for s in db.scans.values()
    )


def recompute_site_risk(site):
    """Compute risk_exposure_score (CURRENT variant). Mutation of the site (touch)."""
    fs = findings_for_site(site["id"])
    has_demand = site_has_active_demand(site["id"])
    score = calc.risk_exposure(fs, has_demand, db.clock.now(), calc.RISK_OPEN_SET)
    site["risk_exposure_score"] = score
    touch(site)


def recompute_org_open_demand_count(org):
    """Recompute open_legal_demand_count over the org's sites. Mutation (touch)."""
    site_ids = {s["id"] for s in sites_for_org(org["id"])}
    count = 0
    for d in db.legal_demands.values():
        if d["site_id"] in site_ids and d["status"] in ACTIVE_DEMAND_STATUSES:
            count += 1
    org["open_legal_demand_count"] = count
    touch(org)


def org_for_site(site):
    return db.organizations.get(site["organization_id"])


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def _common(rec, has_common=True):
    out = {"id": rec["id"], "created_at": to_iso(rec["created_at"])}
    if has_common:
        out["updated_at"] = to_iso(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def ser_organization(o):
    out = _common(o)
    out.update({
        "legal_name": o["legal_name"],
        "contact_email": o["contact_email"],
        "account_credit_cents": o["account_credit_cents"],
        "open_legal_demand_count": o["open_legal_demand_count"],
        "status": None,
    })
    out.pop("status")
    return out


def ser_subscription(s):
    out = _common(s)
    out.update({
        "organization_id": s["organization_id"],
        "tier": s["tier"],
        "status": s["status"],
        "monthly_invoice_cents": s["monthly_invoice_cents"],
    })
    return out


def ser_site(s):
    out = _common(s)
    out.update({
        "organization_id": s["organization_id"],
        "url": s["url"],
        "audited_page_count": s["audited_page_count"],
        "audit_posture": s["audit_posture"],
        "risk_exposure_score": s["risk_exposure_score"],
    })
    return out


def ser_scan(s):
    out = _common(s)
    out.update({
        "site_id": s["site_id"],
        "wcag_target_level": s["wcag_target_level"],
        "status": s["status"],
        "started_at": to_iso(s["started_at"]) if s["started_at"] else None,
        "completed_at": to_iso(s["completed_at"]) if s["completed_at"] else None,
        "provisional_conformance_score": s["provisional_conformance_score"],
        "finding_count": s["finding_count"],
    })
    return out


def ser_finding(f):
    out = _common(f)
    out.update({
        "scan_id": f["scan_id"],
        "site_id": f["site_id"],
        "wcag_criterion": f["wcag_criterion"],
        "severity": f["severity"],
        "status": f["status"],
        "sla_due_at": to_iso(f["sla_due_at"]) if f["sla_due_at"] else None,
        "is_overdue": calc.is_overdue(f, db.clock.now()),
    })
    return out


def ser_remediation_task(t):
    out = _common(t)
    out.update({
        "finding_id": t["finding_id"],
        "assigned_vendor_id": t["assigned_vendor_id"],
        "supersedes_task_id": t["supersedes_task_id"],
        "status": t["status"],
        "estimated_effort_hours": t["estimated_effort_hours"],
    })
    return out


def ser_retest_run(r):
    # Leaner entity: only id + created_at (no updated_at, no version).
    out = _common(r, has_common=False)
    out.update({
        "finding_id": r["finding_id"],
        "remediation_task_id": r["remediation_task_id"],
        "outcome": r["outcome"],
        "tested_at": to_iso(r["tested_at"]) if r["tested_at"] else None,
    })
    return out


def ser_vpat(v):
    out = _common(v)
    out.update({
        "site_id": v["site_id"],
        "source_scan_id": v["source_scan_id"],
        "pinned_scan_version": v["pinned_scan_version"],
        "status": v["status"],
        "certified_conformance_score": v["certified_conformance_score"],
        "conformance_level": v["conformance_level"],
    })
    return out


def ser_legal_demand(d):
    out = _common(d)
    out.update({
        "site_id": d["site_id"],
        "claimant_name": d["claimant_name"],
        "status": d["status"],
        "response_due_at": to_iso(d["response_due_at"]) if d["response_due_at"] else None,
    })
    return out


def ser_monitoring_check(m):
    # Leaner entity: only id + created_at.
    out = _common(m, has_common=False)
    out.update({
        "site_id": m["site_id"],
        "regressions_found": m["regressions_found"],
        "checked_at": to_iso(m["checked_at"]) if m["checked_at"] else None,
    })
    return out


def ser_training(t):
    out = _common(t)
    out.update({
        "organization_id": t["organization_id"],
        "learner_email": t["learner_email"],
        "status": t["status"],
        "score_pct": t["score_pct"],
    })
    return out


def ser_certification(c):
    out = _common(c)
    out.update({
        "site_id": c["site_id"],
        "vpat_report_id": c["vpat_report_id"],
        "status": c["status"],
        "badge_token": c["badge_token"],
        "expires_at": to_iso(c["expires_at"]) if c["expires_at"] else None,
    })
    return out
