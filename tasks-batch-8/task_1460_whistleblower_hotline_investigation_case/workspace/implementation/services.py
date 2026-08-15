"""Domain services: derived fields, calculations, state-transition helpers,
serializers, the logical-clock sweep, and report metric computation."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import DB, fmt_dt, new_id, next_seq, now_dt
from errors import ApiError

# =============================================================================
# Constants (scaffold 1.3 calculation tables)
# =============================================================================

CATEGORY_BASE = {
    "FRAUD": 30,
    "FINANCIAL_REPORTING": 30,
    "SAFETY": 25,
    "HARASSMENT": 20,
    "DATA_PRIVACY": 20,
    "CONFLICT_OF_INTEREST": 15,
    "OTHER": 10,
}
SENIORITY_FACTOR = {"EXECUTIVE": 25, "MANAGER": 15, "STAFF": 5, "UNKNOWN": 0}
EXPOSURE_FACTOR = {"ABOVE_1M": 30, "HIGH_1M": 20, "MID_100K": 10, "LOW_10K": 5, "NONE": 0}
VULNERABILITY_FACTOR = {"DIRECT_REPORT": 15, "SAME_TEAM": 10, "NONE": 0}

SLA_DAYS = {"CRITICAL": 30, "HIGH": 60, "MEDIUM": 90, "LOW": 120}
SEVERITY_WEIGHT = {"CRITICAL": 8, "HIGH": 4, "MEDIUM": 2, "LOW": 1}
SEVERITY_BUMP = {"LOW": "MEDIUM", "MEDIUM": "HIGH", "HIGH": "CRITICAL", "CRITICAL": "CRITICAL"}

FLAG_WEIGHT = {"REPORTER_CHECKIN": 3, "HR_SIGNAL": 2, "MANUAL": 1}
ESCALATION_THRESHOLD = 4
RISK_WINDOW_DAYS = 90

CHECKIN_INTERVAL_DAYS = 30
CHECKIN_GRACE_DAYS = 3
MONITORING_WINDOW_DAYS = 365
AUTO_ACK_DAYS = 14

CASE_TERMINAL_STATES = {"CLOSED", "REJECTED", "WITHDRAWN"}
OPEN_ACTION_STATES = {"PROPOSED", "IN_PROGRESS", "OVERDUE"}

CHANNELS = {"WEB_PORTAL", "PHONE", "EMAIL", "IN_PERSON", "MAIL"}
CATEGORIES = set(CATEGORY_BASE)
REGIONS = {"NORTH", "SOUTH", "EAST", "WEST"}
CAPABILITIES = {"INTAKE", "INVESTIGATION", "OFFICER"}
EMPLOYMENT_STATUSES = {"ACTIVE", "ON_LEAVE", "TERMINATED"}
SENIORITIES = set(SENIORITY_FACTOR)
EXPOSURE_BANDS = set(EXPOSURE_FACTOR)
VULNERABILITIES = set(VULNERABILITY_FACTOR)
TRIAGE_DECISIONS = {"PROCEED", "REJECT"}
SCREEN_OUTCOMES = {"CLEAR", "CONFLICT_FOUND"}
CONFLICT_TYPES = {"PERSONAL_RELATIONSHIP", "FINANCIAL_INTEREST", "PRIOR_INVOLVEMENT", "REPORTING_LINE"}
INTERVIEWEE_ROLES = {"SUBJECT", "WITNESS", "REPORTER"}
CONCLUDE_OUTCOMES = {"CONDUCTED", "NO_SHOW", "CANCELLED"}
EVIDENCE_TYPES = {"DOCUMENT", "PHOTO", "EMAIL", "AUDIO", "OTHER"}
FINDINGS = {"SUBSTANTIATED", "UNSUBSTANTIATED", "INCONCLUSIVE"}
REVIEW_DECISIONS = {"APPROVE", "RETURN"}
ACTION_TYPES = {"POLICY_CHANGE", "DISCIPLINE", "TRAINING", "PROCESS_FIX", "MONITORING"}
DECIDE_DECISIONS = {"APPROVE", "REJECT"}
OFFICER_FLAG_CHANNELS = {"HR_SIGNAL", "MANUAL"}

EVENT_TYPES = {
    "CASE_CREATED", "TRIAGED", "ASSIGNMENT_PROPOSED", "SCREENED", "CONFLICT_WAIVED",
    "ASSIGNMENT_ACTIVATED", "ASSIGNMENT_RELEASED", "ASSIGNMENT_SUPERSEDED",
    "DETERMINATION_DRAFTED", "DETERMINATION_SUBMITTED", "DETERMINATION_APPROVED",
    "DETERMINATION_RETURNED", "CLOSURE_READY", "NOTICE_ACKNOWLEDGED",
    "MONITORING_STARTED", "MONITORING_COMPLETED", "RETALIATION_ESCALATED",
    "CASE_REOPENED", "CASE_CLOSED", "CASE_REJECTED", "CASE_WITHDRAWN",
    "LEGAL_HOLD_PLACED", "LEGAL_HOLD_RELEASED",
}

# =============================================================================
# Entity lookup helpers (existence -> ERR_NOT_FOUND)
# =============================================================================


def get_case(case_id):
    c = DB["cases"].get(case_id)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return c


def get_staff(staff_id):
    s = DB["staff_members"].get(staff_id)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return s


def get_assignment(aid):
    a = DB["assignments"].get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return a


def get_interview(iid):
    i = DB["interviews"].get(iid)
    if i is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return i


def get_evidence(eid):
    e = DB["evidence_items"].get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return e


def get_determination(did):
    d = DB["determinations"].get(did)
    if d is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return d


def get_action(aid):
    a = DB["remediation_actions"].get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return a


def get_flag(fid):
    f = DB["retaliation_flags"].get(fid)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return f


def get_notice(nid):
    n = DB["closure_notices"].get(nid)
    if n is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return n


def get_plan(pid):
    p = DB["monitoring_plans"].get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return p


def get_hold(hid):
    h = DB["legal_holds"].get(hid)
    if h is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return h


def get_report(rid):
    r = DB["reports"].get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return r


# =============================================================================
# Mutation helpers
# =============================================================================


def bump(rec):
    """Every mutating operation increments version by exactly 1 and refreshes updated_at."""
    rec["version"] += 1
    rec["updated_at"] = now_dt()


def add_event(case_id, event_type, from_status, to_status, actor_role, actor_id):
    e = {
        "id": new_id(),
        "case_id": case_id,
        "event_type": event_type,
        "from_status": from_status,
        "to_status": to_status,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "occurred_at": now_dt(),
        "created_at": now_dt(),
        "_seq": next_seq(),
    }
    DB["events"][e["id"]] = e
    return e


# =============================================================================
# Derived fields (reconciled at read time)
# =============================================================================


def case_posture(case):
    """FROZEN iff an ACTIVE LegalHold references the case, else NORMAL."""
    for h in DB["legal_holds"].values():
        if h["case_id"] == case["id"] and h["status"] == "ACTIVE":
            return "FROZEN"
    return "NORMAL"


def active_assignments_of(staff_id):
    return [
        a
        for a in DB["assignments"].values()
        if a["investigator_id"] == staff_id and a["status"] == "ACTIVE"
    ]


def active_case_count(staff_id):
    return len(active_assignments_of(staff_id))


def weighted_caseload(staff_id):
    total = 0
    for a in active_assignments_of(staff_id):
        case = DB["cases"].get(a["case_id"])
        if case is not None and case["severity"] in SEVERITY_WEIGHT:
            total += SEVERITY_WEIGHT[case["severity"]]
    return total


def flags_of(case_id):
    return [f for f in DB["retaliation_flags"].values() if f["case_id"] == case_id]


def retaliation_risk_score(case):
    """Sum of weights of OPEN flags flagged within [now-90d, now] inclusive."""
    now = now_dt()
    lo = now - timedelta(days=RISK_WINDOW_DAYS)
    return sum(
        f["weight"]
        for f in flags_of(case["id"])
        if f["status"] == "OPEN" and lo <= f["flagged_at"] <= now
    )


# =============================================================================
# Calculations
# =============================================================================


def severity_band(score):
    if score >= 75:
        return "CRITICAL"
    if score >= 55:
        return "HIGH"
    if score >= 35:
        return "MEDIUM"
    return "LOW"


def compute_severity(confirmed_category, subject_seniority, financial_exposure_band, reporter_vulnerability):
    score = (
        CATEGORY_BASE[confirmed_category]
        + SENIORITY_FACTOR[subject_seniority]
        + EXPOSURE_FACTOR[financial_exposure_band]
        + VULNERABILITY_FACTOR[reporter_vulnerability]
    )
    return severity_band(score)


def eligible_investigators(case):
    pool = []
    for s in DB["staff_members"].values():
        if s["employment_status"] != "ACTIVE":
            continue
        if "INVESTIGATION" not in s["capabilities"]:
            continue
        if s["id"] == case["triaged_by_id"]:
            continue
        if s["email"] in case["subject_employee_ids"] or s["display_name"] in case["subject_employee_ids"]:
            continue
        if active_case_count(s["id"]) >= s["max_active_cases"]:
            continue
        pool.append(s)
    return pool


def select_investigator(case):
    """Auto selector: weighted_caseload ASC, active_case_count ASC, created_at ASC."""
    pool = eligible_investigators(case)
    if not pool:
        raise ApiError(
            "ERR_NO_ELIGIBLE_INVESTIGATOR", 409, "No eligible investigator in the routing pool"
        )
    pool.sort(
        key=lambda s: (
            weighted_caseload(s["id"]),
            active_case_count(s["id"]),
            s["created_at"],
            s["_seq"],
        )
    )
    return pool[0]


# =============================================================================
# Cascading transitions
# =============================================================================


def create_closure_notice(case, summary):
    n = {
        "id": new_id(),
        "case_id": case["id"],
        "closure_summary": summary,
        "status": "SENT",
        "sent_at": now_dt(),
        "acknowledged_at": None,
        "created_at": now_dt(),
        "_seq": next_seq(),
    }
    DB["closure_notices"][n["id"]] = n
    return n


def maybe_close_out(case, actor_role, actor_id):
    """REMEDIATION -> CLOSURE_READY auto rule: >= 1 action exists and zero open.

    Deferred while the case posture is FROZEN (re-evaluated on hold release).
    """
    if case["status"] != "REMEDIATION":
        return
    actions = [a for a in DB["remediation_actions"].values() if a["case_id"] == case["id"]]
    if not actions:
        return
    if any(a["status"] in OPEN_ACTION_STATES for a in actions):
        return
    if case_posture(case) != "NORMAL":
        return
    case["status"] = "CLOSURE_READY"
    case["closure_ready_at"] = now_dt()
    bump(case)
    create_closure_notice(case, case.get("_pending_notice_summary"))
    add_event(case["id"], "CLOSURE_READY", "REMEDIATION", "CLOSURE_READY", actor_role, actor_id)


def acknowledge_notice(notice, case, actor_role, actor_id):
    """Notice SENT -> ACKNOWLEDGED; create the monitoring plan; case -> MONITORING."""
    notice["status"] = "ACKNOWLEDGED"
    notice["acknowledged_at"] = now_dt()
    start = notice["acknowledged_at"]
    plan = {
        "id": new_id(),
        "case_id": case["id"],
        "start_at": start,
        "end_at": start + timedelta(days=MONITORING_WINDOW_DAYS),
        "check_in_interval_days": CHECKIN_INTERVAL_DAYS,
        "next_check_in_due": start + timedelta(days=CHECKIN_INTERVAL_DAYS),
        "last_check_in_at": None,
        "missed_checkin_count": 0,
        "status": "ACTIVE",
        "created_at": now_dt(),
        "updated_at": now_dt(),
        "version": 1,
        "_seq": next_seq(),
    }
    DB["monitoring_plans"][plan["id"]] = plan
    from_status = case["status"]
    case["status"] = "MONITORING"
    bump(case)
    add_event(case["id"], "NOTICE_ACKNOWLEDGED", "SENT", "ACKNOWLEDGED", actor_role, actor_id)
    add_event(case["id"], "MONITORING_STARTED", from_status, "MONITORING", actor_role, actor_id)


def escalate_retaliation(case, actor_role, actor_id):
    """MONITORING -> REOPENED cascade after the risk score reaches >= 4."""
    now = now_dt()
    lo = now - timedelta(days=RISK_WINDOW_DAYS)
    for f in flags_of(case["id"]):
        if f["status"] == "OPEN" and lo <= f["flagged_at"] <= now:
            f["status"] = "ESCALATED"
            bump(f)
    if case["severity"] in SEVERITY_BUMP:
        case["severity"] = SEVERITY_BUMP[case["severity"]]
        case["sla_days"] = SLA_DAYS[case["severity"]]
    case["reopen_count"] += 1
    case["assigned_investigator_id"] = None
    case["status"] = "REOPENED"
    bump(case)
    for p in DB["monitoring_plans"].values():
        if p["case_id"] == case["id"] and p["status"] == "ACTIVE":
            p["status"] = "SUSPENDED"
            p["next_check_in_due"] = None
            bump(p)
    add_event(case["id"], "RETALIATION_ESCALATED", "OPEN", "ESCALATED", actor_role, actor_id)
    add_event(case["id"], "CASE_REOPENED", "MONITORING", "REOPENED", actor_role, actor_id)


# =============================================================================
# Logical clock sweep (PRD 2.9): applied synchronously on set_current_utc
# =============================================================================


def sweep():
    now = now_dt()
    # 1. Remediation overdue marking (strictly past due_date).
    for a in DB["remediation_actions"].values():
        if a["status"] == "IN_PROGRESS" and now > a["due_date"]:
            a["status"] = "OVERDUE"
            bump(a)
    # 2. Notice auto-acknowledgement at sent_at + 14 days (boundary inclusive).
    for n in sorted(
        (n for n in DB["closure_notices"].values() if n["status"] == "SENT"),
        key=lambda n: n["_seq"],
    ):
        if now >= n["sent_at"] + timedelta(days=AUTO_ACK_DAYS):
            case = DB["cases"].get(n["case_id"])
            if case is not None and case["status"] == "CLOSURE_READY":
                acknowledge_notice(n, case, "SYSTEM", "SYSTEM")
    # 3. Missed check-in accounting on ACTIVE plans (repeat to catch up).
    for p in DB["monitoring_plans"].values():
        if p["status"] != "ACTIVE" or p["next_check_in_due"] is None:
            continue
        changed = False
        while now > p["next_check_in_due"] + timedelta(days=CHECKIN_GRACE_DAYS):
            p["missed_checkin_count"] += 1
            p["next_check_in_due"] = p["next_check_in_due"] + timedelta(days=CHECKIN_INTERVAL_DAYS)
            changed = True
        if changed:
            bump(p)
    # 4. Plan completion at end_at (now >= end_at); case -> CLOSED.
    for p in sorted(
        (p for p in DB["monitoring_plans"].values() if p["status"] == "ACTIVE"),
        key=lambda p: p["_seq"],
    ):
        if now >= p["end_at"]:
            p["status"] = "COMPLETED"
            p["next_check_in_due"] = None
            bump(p)
            case = DB["cases"].get(p["case_id"])
            if case is not None and case["status"] == "MONITORING":
                case["closed_at"] = now
                case["status"] = "CLOSED"
                bump(case)
                add_event(case["id"], "MONITORING_COMPLETED", "ACTIVE", "COMPLETED", "SYSTEM", "SYSTEM")
                add_event(case["id"], "CASE_CLOSED", "MONITORING", "CLOSED", "SYSTEM", "SYSTEM")


# =============================================================================
# Audit committee report metrics (scaffold 1.3: days_to_close, substantiation)
# =============================================================================


def _whole_days(delta):
    """Whole UTC days, partial days discarded (floor)."""
    return int(delta.total_seconds() // 86400)


def _hold_covered_date_count(case):
    """Distinct UTC dates covered by any hold of the case (ACTIVE or RELEASED),
    intersected with [date(received_at), date(closure_ready_at)] inclusive."""
    lo = case["received_at"].date()
    hi = case["closure_ready_at"].date()
    covered = set()
    for h in DB["legal_holds"].values():
        if h["case_id"] != case["id"]:
            continue
        a = max(h["start_at"].date(), lo)
        b = min(h["end_at"].date(), hi)
        if a <= b:
            for i in range((b - a).days + 1):
                covered.add(a + timedelta(days=i))
    return len(covered)


def _round(value, places):
    q = Decimal(1).scaleb(-places)
    return float(Decimal(value).quantize(q, rounding=ROUND_HALF_UP))


def _mean_round(day_counts, places=2):
    total = sum(day_counts)
    n = len(day_counts)
    return _round(Decimal(total) / Decimal(n), places)


def compute_report_metrics(period_start, period_end):
    received = [
        c for c in DB["cases"].values() if period_start <= c["received_at"] < period_end
    ]
    closures = [
        c
        for c in DB["cases"].values()
        if c["closure_ready_at"] is not None and period_start <= c["closure_ready_at"] < period_end
    ]
    overdue = sum(1 for a in DB["remediation_actions"].values() if a["status"] == "OVERDUE")
    escalations = sum(
        1
        for f in DB["retaliation_flags"].values()
        if f["status"] == "ESCALATED" and period_start <= f["flagged_at"] < period_end
    )

    metrics = {
        "total_received": len(received),
        "total_closures": len(closures),
        "overdue_remediation_count": overdue,
        "retaliation_escalation_count": escalations,
    }

    if not closures:
        metrics["avg_days_to_close_calendar"] = None
        metrics["avg_days_to_close_hold_adjusted"] = None
        metrics["org_substantiation_rate"] = None
        metrics["pooled_substantiation_rate"] = None
        return metrics

    calendar_days = [_whole_days(c["closure_ready_at"] - c["received_at"]) for c in closures]
    adjusted_days = [d - _hold_covered_date_count(c) for c, d in zip(closures, calendar_days)]
    metrics["avg_days_to_close_calendar"] = _mean_round(calendar_days, 2)
    metrics["avg_days_to_close_hold_adjusted"] = _mean_round(adjusted_days, 2)

    # Nested rounding pinned: per-region rate rounded to 4dp FIRST, then averaged, then rounded.
    per_region = {}
    for c in closures:
        sub, tot = per_region.get(c["region"], (0, 0))
        tot += 1
        if c["determination_finding"] == "SUBSTANTIATED":
            sub += 1
        per_region[c["region"]] = (sub, tot)
    region_rates = [
        (Decimal(sub) / Decimal(tot)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        for sub, tot in per_region.values()
    ]
    org = (sum(region_rates) / Decimal(len(region_rates))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    total_sub = sum(sub for sub, _ in per_region.values())
    pooled = (Decimal(total_sub) / Decimal(len(closures))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    metrics["org_substantiation_rate"] = float(org)
    metrics["pooled_substantiation_rate"] = float(pooled)
    return metrics


# =============================================================================
# Serializers (staff-facing; the confidentiality firewall lives here)
# =============================================================================


def staff_view(s):
    return {
        "id": s["id"],
        "display_name": s["display_name"],
        "email": s["email"],
        "department": s["department"],
        "capabilities": list(s["capabilities"]),
        "employment_status": s["employment_status"],
        "max_active_cases": s["max_active_cases"],
        "active_case_count": active_case_count(s["id"]),
        "weighted_caseload": weighted_caseload(s["id"]),
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def case_view(case, include_reporter_key=False):
    """Staff-facing case payload: reporter_contact / reporter_access_key are never present."""
    data = {
        "id": case["id"],
        "channel": case["channel"],
        "category": case["category"],
        "confirmed_category": case["confirmed_category"],
        "description": case["description"],
        "region": case["region"],
        "is_anonymous": case["is_anonymous"],
        "subject_employee_ids": list(case["subject_employee_ids"]),
        "status": case["status"],
        "posture": case_posture(case),
        "severity": case["severity"],
        "sla_days": case["sla_days"],
        "triaged_by_id": case["triaged_by_id"],
        "assigned_investigator_id": case["assigned_investigator_id"],
        "duplicate_of_case_id": case["duplicate_of_case_id"],
        "received_at": fmt_dt(case["received_at"]),
        "closure_ready_at": fmt_dt(case["closure_ready_at"]),
        "closed_at": fmt_dt(case["closed_at"]),
        "retaliation_risk_score": retaliation_risk_score(case),
        "reopen_count": case["reopen_count"],
        "determination_finding": case["determination_finding"],
        "created_at": fmt_dt(case["created_at"]),
        "updated_at": fmt_dt(case["updated_at"]),
        "version": case["version"],
    }
    if include_reporter_key:
        # The minted key is returned exactly once: in the intake response only.
        data["reporter_access_key"] = case["reporter_access_key"]
    return data


def assignment_view(a):
    return {
        "id": a["id"],
        "case_id": a["case_id"],
        "investigator_id": a["investigator_id"],
        "routed_by_id": a["routed_by_id"],
        "selection_mode": a["selection_mode"],
        "status": a["status"],
        "screened_by_id": a["screened_by_id"],
        "conflict_type": a["conflict_type"],
        "waived_by_id": a["waived_by_id"],
        "waiver_justification": a["waiver_justification"],
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def interview_view(i):
    return {
        "id": i["id"],
        "case_id": i["case_id"],
        "investigator_id": i["investigator_id"],
        "interviewee_role": i["interviewee_role"],
        "interviewee_identifier": i["interviewee_identifier"],
        "scheduled_start": fmt_dt(i["scheduled_start"]),
        "scheduled_end": fmt_dt(i["scheduled_end"]),
        "status": i["status"],
        "summary": i["summary"],
        "conducted_at": fmt_dt(i["conducted_at"]),
        "created_at": fmt_dt(i["created_at"]),
        "updated_at": fmt_dt(i["updated_at"]),
        "version": i["version"],
    }


def evidence_view(e):
    return {
        "id": e["id"],
        "case_id": e["case_id"],
        "uploaded_by_id": e["uploaded_by_id"],
        "evidence_type": e["evidence_type"],
        "description": e["description"],
        "checksum": e["checksum"],
        "captured_at": fmt_dt(e["captured_at"]),
        "status": e["status"],
        "sealed_by_id": e["sealed_by_id"],
        "excluded_by_id": e["excluded_by_id"],
        "exclusion_reason": e["exclusion_reason"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def determination_view(d):
    return {
        "id": d["id"],
        "case_id": d["case_id"],
        "finding": d["finding"],
        "rationale": d["rationale"],
        "decided_by_id": d["decided_by_id"],
        "reviewed_by_id": d["reviewed_by_id"],
        "status": d["status"],
        "review_notes": d["review_notes"],
        "created_at": fmt_dt(d["created_at"]),
        "updated_at": fmt_dt(d["updated_at"]),
        "version": d["version"],
    }


def action_view(a):
    return {
        "id": a["id"],
        "case_id": a["case_id"],
        "determination_id": a["determination_id"],
        "action_type": a["action_type"],
        "owner_department": a["owner_department"],
        "description": a["description"],
        "due_date": fmt_dt(a["due_date"]),
        "status": a["status"],
        "created_by_id": a["created_by_id"],
        "verified_by_id": a["verified_by_id"],
        "extension_count": a["extension_count"],
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def flag_view(f):
    return {
        "id": f["id"],
        "case_id": f["case_id"],
        "reported_via": f["reported_via"],
        "description": f["description"],
        "weight": f["weight"],
        "flagged_at": fmt_dt(f["flagged_at"]),
        "status": f["status"],
        "dismissed_by_id": f["dismissed_by_id"],
        "created_at": fmt_dt(f["created_at"]),
        "updated_at": fmt_dt(f["updated_at"]),
        "version": f["version"],
    }


def plan_view(p):
    return {
        "id": p["id"],
        "case_id": p["case_id"],
        "start_at": fmt_dt(p["start_at"]),
        "end_at": fmt_dt(p["end_at"]),
        "check_in_interval_days": p["check_in_interval_days"],
        "next_check_in_due": fmt_dt(p["next_check_in_due"]),
        "last_check_in_at": fmt_dt(p["last_check_in_at"]),
        "missed_checkin_count": p["missed_checkin_count"],
        "status": p["status"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def notice_view(n):
    # CaseClosureNotice carries only id and created_at (no updated_at / version).
    return {
        "id": n["id"],
        "case_id": n["case_id"],
        "closure_summary": n["closure_summary"],
        "status": n["status"],
        "sent_at": fmt_dt(n["sent_at"]),
        "acknowledged_at": fmt_dt(n["acknowledged_at"]),
        "created_at": fmt_dt(n["created_at"]),
    }


def hold_view(h):
    return {
        "id": h["id"],
        "case_id": h["case_id"],
        "start_at": fmt_dt(h["start_at"]),
        "end_at": fmt_dt(h["end_at"]),
        "reason": h["reason"],
        "status": h["status"],
        "placed_by_id": h["placed_by_id"],
        "released_by_id": h["released_by_id"],
        "created_at": fmt_dt(h["created_at"]),
        "updated_at": fmt_dt(h["updated_at"]),
        "version": h["version"],
    }


def report_view(r):
    return {
        "id": r["id"],
        "period_start": fmt_dt(r["period_start"]),
        "period_end": fmt_dt(r["period_end"]),
        "status": r["status"],
        "total_received": r["total_received"],
        "total_closures": r["total_closures"],
        "avg_days_to_close_calendar": r["avg_days_to_close_calendar"],
        "avg_days_to_close_hold_adjusted": r["avg_days_to_close_hold_adjusted"],
        "org_substantiation_rate": r["org_substantiation_rate"],
        "pooled_substantiation_rate": r["pooled_substantiation_rate"],
        "overdue_remediation_count": r["overdue_remediation_count"],
        "retaliation_escalation_count": r["retaliation_escalation_count"],
        "generated_by_id": r["generated_by_id"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def event_view(e):
    # CaseStatusEvent carries only id and created_at (no updated_at / version).
    return {
        "id": e["id"],
        "case_id": e["case_id"],
        "event_type": e["event_type"],
        "from_status": e["from_status"],
        "to_status": e["to_status"],
        "actor_role": e["actor_role"],
        "actor_id": e["actor_id"],
        "occurred_at": fmt_dt(e["occurred_at"]),
        "created_at": fmt_dt(e["created_at"]),
    }


# =============================================================================
# List helper: created_at ASC default ordering + limit/offset window
# =============================================================================


def sorted_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(records, limit, offset):
    ordered = sorted_created(records)
    total = len(ordered)
    return ordered[offset : offset + limit], total
