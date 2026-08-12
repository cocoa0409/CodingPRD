"""AuditEngagement and AuditFinding endpoints."""

import services as S
from db import store
from errors import (
    err_auditor_capacity,
    err_engagement_overlap,
    err_finding_not_open,
    err_invalid_state,
    err_validation,
)
from middleware import ALL_READ_ROLES, actor, body, require_roles
from response import ok, paginate
from util import get_dt, get_enum, get_nonempty_str, get_str

ENGAGEMENT_TYPES = ("FINANCIAL_AUDIT", "SITE_VISIT", "DESK_REVIEW")
SEVERITIES = ("OBSERVATION", "DEFICIENCY", "MATERIAL_WEAKNESS")

ADVANCE_LADDER = {
    "SCHEDULED": "PREPARATION",
    "PREPARATION": "READY",
    "READY": "CONDUCTED",
    "CONDUCTED": "FINDINGS_ISSUED",
    "FINDINGS_ISSUED": "CLOSED",
}


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap; adjacency (end == start) is allowed."""
    return a_start < b_end and b_start < a_end


def create_engagement(grant_id):
    _, role = actor()
    require_roles(role, {"ProgramDirector"})
    grant = S.get_grant(grant_id)
    S.require_grant_active(grant)
    data = body()
    etype = get_enum(data, "engagement_type", ENGAGEMENT_TYPES)
    auditor_org = get_str(data, "auditor_org")
    start = get_dt(data, "scheduled_start")
    end = get_dt(data, "scheduled_end")
    if not end > start:
        raise err_validation("scheduled_end must be after scheduled_start")
    # Same-grant overlap check against non-CLOSED engagements (half-open).
    for e in S.grant_engagements(grant_id):
        if e["status"] == "CLOSED":
            continue
        if _overlaps(start, end, e["scheduled_start"], e["scheduled_end"]):
            raise err_engagement_overlap()
    # Auditor capacity: at most 2 mutually-overlapping active engagements.
    events = []
    for e in store["audit_engagements"].values():
        if e["auditor_org"] != auditor_org or e["status"] == "CLOSED":
            continue
        events.append((e["scheduled_start"], 1))
        events.append((e["scheduled_end"], -1))
    events.append((start, 1))
    events.append((end, -1))
    # Half-open: at a shared instant, ends are processed before starts.
    events.sort(key=lambda ev: (ev[0], ev[1]))
    current = 0
    peak = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    if peak > S.AUDITOR_MAX_CONCURRENT_ENGAGEMENTS:
        raise err_auditor_capacity()
    eng = S.stamp({
        "grant_id": grant_id,
        "engagement_type": etype,
        "auditor_org": auditor_org,
        "scheduled_start": start,
        "scheduled_end": end,
        "status": "SCHEDULED",
    })
    store["audit_engagements"][eng["id"]] = eng
    return ok(S.ser_engagement(eng), code=201)


def list_engagements(grant_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    S.get_grant(grant_id)
    items = S.grant_engagements(grant_id)
    page, meta = paginate(items)
    return ok([S.ser_engagement(e) for e in page], pagination=meta)


def get_engagement(engagement_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    return ok(S.ser_engagement(S.get_engagement(engagement_id)))


def advance_engagement(engagement_id):
    _, role = actor()
    require_roles(role, {"Auditor"})
    eng = S.get_engagement(engagement_id)
    nxt = ADVANCE_LADDER.get(eng["status"])
    if nxt is None:
        raise err_invalid_state("Engagement is already CLOSED")
    if nxt == "CLOSED":
        for f in S.engagement_findings(engagement_id):
            if f["status"] != "RESOLVED":
                raise err_invalid_state("All findings must be RESOLVED before the engagement closes")
    eng["status"] = nxt
    S.touch(eng)
    return ok(S.ser_engagement(eng))


def create_finding(engagement_id):
    _, role = actor()
    require_roles(role, {"Auditor"})
    eng = S.get_engagement(engagement_id)
    if eng["status"] not in ("CONDUCTED", "FINDINGS_ISSUED"):
        raise err_invalid_state("Findings can only be filed on a CONDUCTED or FINDINGS_ISSUED engagement")
    data = body()
    f = S.stamp({
        "engagement_id": engagement_id,
        "severity": get_enum(data, "severity", SEVERITIES),
        "description": get_str(data, "description"),
        "status": "OPEN",
        "response_text": None,
    })
    store["audit_findings"][f["id"]] = f
    # Cross-aggregate cascade: MATERIAL_WEAKNESS on an ACTIVE grant suspends it.
    if f["severity"] == "MATERIAL_WEAKNESS":
        grant = S.get_grant(eng["grant_id"])
        if grant["status"] == "ACTIVE":
            S.suspend_grant(grant)
    return ok(S.ser_finding(f), code=201)


def list_findings(engagement_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    S.get_engagement(engagement_id)
    items = S.engagement_findings(engagement_id)
    page, meta = paginate(items)
    return ok([S.ser_finding(f) for f in page], pagination=meta)


def respond_finding(finding_id):
    _, role = actor()
    require_roles(role, {"GrantsOfficer"})
    f = S.get_finding(finding_id)
    if f["status"] != "OPEN":
        raise err_finding_not_open("Only an OPEN finding can be responded to")
    data = body()
    f["response_text"] = get_nonempty_str(data, "response_text")
    f["status"] = "RESPONSE_SUBMITTED"
    S.touch(f)
    return ok(S.ser_finding(f))


def resolve_finding(finding_id):
    _, role = actor()
    require_roles(role, {"Auditor"})
    f = S.get_finding(finding_id)
    if f["status"] != "RESPONSE_SUBMITTED":
        raise err_finding_not_open("Only a RESPONSE_SUBMITTED finding can be resolved")
    f["status"] = "RESOLVED"
    S.touch(f)
    if f["severity"] == "MATERIAL_WEAKNESS":
        eng = S.get_engagement(f["engagement_id"])
        grant = S.get_grant(eng["grant_id"])
        S.maybe_reactivate_grant(grant)
    return ok(S.ser_finding(f))


def reopen_finding(finding_id):
    _, role = actor()
    require_roles(role, {"Auditor"})
    f = S.get_finding(finding_id)
    if f["status"] != "RESPONSE_SUBMITTED":
        raise err_finding_not_open("Only a RESPONSE_SUBMITTED finding can be reopened")
    f["status"] = "OPEN"
    f["response_text"] = None
    S.touch(f)
    return ok(S.ser_finding(f))


def register(app):
    app.add_url_rule("/grants/<grant_id>/audit-engagements", "eng_create", create_engagement, methods=["POST"])
    app.add_url_rule("/grants/<grant_id>/audit-engagements", "eng_list", list_engagements, methods=["GET"])
    app.add_url_rule("/audit-engagements/<engagement_id>", "eng_get", get_engagement, methods=["GET"])
    app.add_url_rule("/audit-engagements/<engagement_id>/advance", "eng_advance", advance_engagement, methods=["POST"])
    app.add_url_rule("/audit-engagements/<engagement_id>/findings", "find_create", create_finding, methods=["POST"])
    app.add_url_rule("/audit-engagements/<engagement_id>/findings", "find_list", list_findings, methods=["GET"])
    app.add_url_rule("/audit-findings/<finding_id>/respond", "find_respond", respond_finding, methods=["POST"])
    app.add_url_rule("/audit-findings/<finding_id>/resolve", "find_resolve", resolve_finding, methods=["POST"])
    app.add_url_rule("/audit-findings/<finding_id>/reopen", "find_reopen", reopen_finding, methods=["POST"])
