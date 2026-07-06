"""Cross-cutting domain logic: ledger recompute, posture, calculations,
audit-log chain, and entity serialization."""
import hashlib

from store import db, new_id, fmt_iso, now_clock, parse_iso, add_hours
from response import round2

# ---------------------------------------------------------------------------
# Common system fields
# ---------------------------------------------------------------------------

def init_common(entity):
    ts = now_clock()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = db.next_seq()


def touch(entity):
    entity["updated_at"] = now_clock()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Audit log (tamper-evident chain, per client)
# ---------------------------------------------------------------------------

def append_audit(client_id, role, user_id, action, target_entity, target_id):
    # Find previous entry for this client's chain (latest by seq).
    prev_hash = ""
    prev = None
    for e in db.audit_log.values():
        if e["client_id"] == client_id:
            if prev is None or e["_seq"] > prev["_seq"]:
                prev = e
    if prev is not None:
        prev_hash = prev["entry_hash"]

    eid = new_id()
    created_at = now_clock()
    created_iso = fmt_iso(created_at)
    payload = "|".join([prev_hash, action, target_id, created_iso])
    entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    entry = {
        "id": eid,
        "created_at": created_at,
        "_seq": db.next_seq(),
        "client_id": client_id,
        "actor_role": role,
        "actor_user_id": user_id,
        "action": action,
        "target_entity": target_entity,
        "target_id": target_id,
        "prev_hash": prev_hash,
        "entry_hash": entry_hash,
    }
    db.audit_log[eid] = entry
    return entry


# ---------------------------------------------------------------------------
# Retainer ledger recompute
# ---------------------------------------------------------------------------

def find_open_ledger(client_id):
    client = db.clients[client_id]
    pidx = client["current_period_index"]
    for led in db.retainer_ledgers.values():
        if led["client_id"] == client_id and led["period_index"] == pidx:
            return led
    return None


def find_ledger(client_id, period_index):
    for led in db.retainer_ledgers.values():
        if led["client_id"] == client_id and led["period_index"] == period_index:
            return led
    return None


def recompute_ledger(led):
    """Recompute hours_reserved / hours_consumed / hours_available for a ledger row."""
    client_id = led["client_id"]
    pidx = led["period_index"]

    # Reserved: sum over AUTHORIZED engagements of this client in this period of
    # estimated_hours, MINUS (per engagement, floored at 0) the sum over its
    # COMPLETED scans of min(actual_hours, that engagement's remaining reservation).
    reserved = 0.0
    for eng in db.engagements.values():
        if eng["client_id"] != client_id:
            continue
        if eng.get("period_index") != pidx:
            continue
        if eng["status"] != "AUTHORIZED":
            continue
        est = float(eng["estimated_hours"])
        consumed_under = 0.0
        for sc in db.scans.values():
            if sc["engagement_id"] == eng["id"] and sc["status"] == "COMPLETED":
                remaining = est - consumed_under
                consumed_under += min(float(sc["actual_hours"] or 0.0), remaining)
        contribution = est - consumed_under
        if contribution < 0:
            contribution = 0.0
        reserved += contribution

    # Consumed: COMPLETED scans whose work fell in this period + RESOLVED
    # incidents resolved in this period.
    consumed = 0.0
    for sc in db.scans.values():
        if sc["client_id"] != client_id:
            continue
        if sc["status"] != "COMPLETED":
            continue
        if sc.get("_completed_period_index") != pidx:
            continue
        consumed += float(sc["actual_hours"] or 0.0)
    for inc in db.incidents.values():
        if inc["client_id"] != client_id:
            continue
        if inc["status"] != "RESOLVED":
            continue
        if inc.get("resolved_period_index") != pidx:
            continue
        consumed += float(inc.get("response_hours") or 0.0)

    led["hours_reserved"] = round2(reserved)
    led["hours_consumed"] = round2(consumed)
    led["hours_available"] = round2(led["hours_granted"] - led["hours_reserved"] - led["hours_consumed"])


def engagement_remaining_reservation(eng):
    """Remaining reservation for one AUTHORIZED engagement (estimate minus consumed-under)."""
    est = float(eng["estimated_hours"])
    consumed_under = 0.0
    for sc in db.scans.values():
        if sc["engagement_id"] == eng["id"] and sc["status"] == "COMPLETED":
            remaining = est - consumed_under
            consumed_under += min(float(sc["actual_hours"] or 0.0), remaining)
    rem = est - consumed_under
    return rem if rem > 0 else 0.0


# ---------------------------------------------------------------------------
# Client computed fields: posture, open_critical_findings
# ---------------------------------------------------------------------------

def recompute_open_critical(client_id):
    closed = {"REMEDIATED", "RISK_ACCEPTED", "FALSE_POSITIVE"}
    count = 0
    for f in db.findings.values():
        if f["client_id"] == client_id and f["severity"] == "CRITICAL" and f["status"] not in closed:
            count += 1
    db.clients[client_id]["open_critical_findings"] = count


def recompute_posture(client_id):
    posture = "OPEN"
    for inc in db.incidents.values():
        if inc["client_id"] != client_id:
            continue
        if inc["status"] == "ESCALATED":
            db.clients[client_id]["posture"] = "LOCKDOWN"
            return
    # No ESCALATED — check for HEIGHTENED (any open incident severity >= HIGH).
    open_states = {"DETECTED", "ACKNOWLEDGED", "CONTAINED", "REOPENED"}
    for inc in db.incidents.values():
        if inc["client_id"] != client_id:
            continue
        if inc["status"] in open_states and inc["severity"] in ("HIGH", "CRITICAL"):
            posture = "HEIGHTENED"
    db.clients[client_id]["posture"] = posture


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

BANDS = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]


def compute_severity(cvss_base, asset_criticality):
    c = float(cvss_base)
    if c == 0.0:
        base = "INFO"
    elif c < 4.0:
        base = "LOW"
    elif c < 7.0:
        base = "MEDIUM"
    elif c < 9.0:
        base = "HIGH"
    else:
        base = "CRITICAL"
    idx = BANDS.index(base)
    if asset_criticality == "CROWN_JEWEL":
        idx = min(idx + 1, 4)
    elif asset_criticality == "HIGH" and base in ("MEDIUM", "HIGH"):
        idx = min(idx + 1, 4)
    return BANDS[idx]


SLA_BASE_HOURS = {"CRITICAL": 24, "HIGH": 72, "MEDIUM": 168, "LOW": 720, "INFO": None}
TIER_MULT = {"ESSENTIAL": 1.0, "ADVANCED": 0.75, "ELITE": 0.5}


def compute_sla_due_at(created_at, severity, tier):
    base = SLA_BASE_HOURS[severity]
    if base is None:
        return None
    hours = base * TIER_MULT[tier]
    return add_hours(created_at, hours)


def is_sla_breached(finding):
    due = finding.get("sla_due_at")
    if due is None:
        return False
    closed = {"REMEDIATED", "RISK_ACCEPTED", "FALSE_POSITIVE"}
    if finding["status"] in closed:
        return False
    return now_clock() > due


CRIT_WEIGHT = {"LOW": 0, "MEDIUM": 10, "HIGH": 20, "CROWN_JEWEL": 35}


def compute_triage_priority(raw_score, asset_criticality, asset_exposure):
    crit_weight = CRIT_WEIGHT[asset_criticality]
    exposure_bonus = 15 if asset_exposure == "EXTERNAL" else 0
    score = round2(float(raw_score) * 0.6 + crit_weight + exposure_bonus)
    if score >= 80:
        return "P1"
    elif score >= 55:
        return "P2"
    elif score >= 30:
        return "P3"
    return "P4"


# Map alert triage_priority -> incident severity on promotion.
PRIORITY_TO_SEVERITY = {"P1": "CRITICAL", "P2": "HIGH", "P3": "MEDIUM", "P4": "LOW"}

# Incident escalation response-SLA base hours (tier/severity), mirrors finding SLA bands.
INCIDENT_SLA_HOURS = {"CRITICAL": 24, "HIGH": 72, "MEDIUM": 168, "LOW": 720}


def compute_escalation_deadline(created_at, severity, tier):
    base = INCIDENT_SLA_HOURS.get(severity)
    if base is None:
        return None
    return add_hours(created_at, base * TIER_MULT[tier])


def is_escalation_breached(incident):
    due = incident.get("escalation_deadline_at")
    if due is None:
        return False
    if incident["status"] != "DETECTED":
        return False
    return now_clock() > due


def recompute_readiness(audit):
    required = audit["required_control_count"]
    refs = set()
    for ev in db.evidence.values():
        if ev["audit_id"] == audit["id"] and ev["status"] == "APPROVED":
            refs.add(ev["control_ref"])
    covered = min(len(refs), required)
    audit["readiness_pct"] = round2(100.0 * covered / required)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _base(entity, fields):
    out = {"id": entity["id"], "created_at": fmt_iso(entity["created_at"]),
           "updated_at": fmt_iso(entity["updated_at"]), "version": entity["version"]}
    for f in fields:
        out[f] = entity.get(f)
    return out


def ser_client(c):
    return _base(c, ["name", "tier", "retainer_hours_per_period", "current_period_index",
                     "posture", "open_critical_findings", "status"])


def ser_ledger(l):
    return _base(l, ["client_id", "period_index", "hours_granted", "hours_reserved",
                     "hours_consumed", "hours_available", "status"])


def ser_engagement(e):
    out = _base(e, ["client_id", "kind", "estimated_hours", "scope_asset_ids",
                    "authorization_signed_by", "period_index", "status"])
    out["authorized_window_start"] = fmt_iso(e.get("authorized_window_start"))
    out["authorized_window_end"] = fmt_iso(e.get("authorized_window_end"))
    return out


def ser_asset(a):
    return _base(a, ["client_id", "hostname", "ip_address", "criticality", "exposure", "status"])


def ser_scan(s):
    out = _base(s, ["engagement_id", "client_id", "actual_hours", "raw_finding_count", "status"])
    out["started_at"] = fmt_iso(s.get("started_at"))
    out["completed_at"] = fmt_iso(s.get("completed_at"))
    return out


def ser_finding(f):
    out = _base(f, ["scan_id", "asset_id", "client_id", "title", "cvss_base", "severity",
                    "submitted_by", "accepted_by", "linked_incident_id", "status"])
    out["sla_due_at"] = fmt_iso(f.get("sla_due_at"))
    out["sla_breached"] = is_sla_breached(f)
    return out


def ser_alert(a):
    return _base(a, ["client_id", "asset_id", "source", "raw_score", "triage_priority",
                     "triaged_by", "promoted_incident_id", "status"])


def ser_incident(i):
    out = _base(i, ["client_id", "triggering_alert_id", "severity", "response_hours",
                    "contained_count", "resolved_period_index", "quarantined_asset_id", "status"])
    out["escalation_deadline_at"] = fmt_iso(i.get("escalation_deadline_at"))
    out["escalation_breached"] = is_escalation_breached(i)
    return out


def ser_audit(a):
    return _base(a, ["client_id", "framework", "required_control_count", "readiness_pct", "status"])


def ser_evidence(e):
    return _base(e, ["audit_id", "control_ref", "finding_id", "submitted_by", "status"])


def ser_report(r):
    return _base(r, ["client_id", "kind", "subject_id", "snapshot", "status"])


def ser_audit_log(e):
    return {
        "id": e["id"],
        "created_at": fmt_iso(e["created_at"]),
        "client_id": e["client_id"],
        "actor_role": e["actor_role"],
        "actor_user_id": e["actor_user_id"],
        "action": e["action"],
        "target_entity": e["target_entity"],
        "target_id": e["target_id"],
        "prev_hash": e["prev_hash"],
        "entry_hash": e["entry_hash"],
    }
