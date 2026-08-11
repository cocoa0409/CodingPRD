"""Business logic: derived-field recomputes, calculations, shared gates.

Every rule here traces to SCAFFOLD §1.3 (calculations) and PRD §3.
All recomputes read source rows directly (no driftable stored aggregates).
"""
from datetime import timedelta
from decimal import Decimal

import db
import errors
from util import ceil_int, dec, fmt_dt, new_id, round0, round2

# ---------------------------------------------------------------------------
# enum vocabularies
# ---------------------------------------------------------------------------
ROLES = {
    "IntakeCoordinator",
    "Investigator",
    "InvestigationsManager",
    "HRBusinessPartner",
    "GeneralCounsel",
    "ChiefLegalOfficer",
    "ComplianceAuditor",
    "SystemAdmin",
}
ALLEGATION_CATEGORIES = {
    "FRAUD", "HARASSMENT", "CONFLICT_OF_INTEREST", "DATA_BREACH", "BRIBERY",
    "POLICY_VIOLATION",
}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
REPORTER_CHANNELS = {"HOTLINE", "EMAIL", "MANAGER_REFERRAL", "ANONYMOUS_PORTAL", "EXTERNAL"}
ROLES_IN_CASE = {"PRIMARY", "ACCESSORY", "PERSON_OF_INTEREST"}
NOTICE_SCOPES = {"EMAIL", "DEVICES", "CHAT", "FILES", "ALL_DATA"}
DATA_SOURCES = {"EMAIL", "DEVICE", "CHAT", "FILES"}
TARGET_TYPES = {"EVIDENCE_ITEM", "INTERVIEW", "CASE_REPORT"}
PRIVILEGE_TYPES = {"ACP", "WORK_PRODUCT"}
CONSISTENCY_LEVELS = {"LOW", "MEDIUM", "HIGH"}
FINDING_TYPES = {"SUBSTANTIATED", "UNSUBSTANTIATED", "INCONCLUSIVE"}
REC_ACTIONS = {"COACHING", "WARNING", "SUSPENSION", "TERMINATION", "NONE"}
DIST_TIERS = {"RESTRICTED", "LEGAL_CONFIDENTIAL", "BOARD"}
REPORT_PRIV_TYPES = {"ACP", "WORK_PRODUCT", "NONE"}
REGULATORS = {"SEC", "DOJ", "DOL", "FINRA", "DATA_PROTECTION"}
ACTION_TYPES = {"POLICY_UPDATE", "TRAINING", "PROCESS_CHANGE", "CONTROL_IMPLEMENTATION", "MONITORING"}

# state vocabularies (for to_status membership checks)
CASE_STATUSES = {
    "INTAKE", "TRIAGED", "PLANNING", "FIELDWORK", "FINDINGS", "DISPOSITION",
    "REMEDIATION", "CLOSED", "DISMISSED",
}
ALLEGATION_STATUSES = {"SUBMITTED", "TRIAGED", "LINKED", "DISMISSED"}
PLAN_STATUSES = {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"}
SUBJECT_STATUSES = {"ACTIVE", "CLEARED", "SEPARATED"}
NOTICE_STATUSES = {"ISSUED", "ACKNOWLEDGED", "RELEASED"}
SCOPE_STATUSES = {"PROPOSED", "APPROVED", "IN_PROGRESS", "COLLECTED", "WITHDRAWN"}
EVIDENCE_STATUSES = {"LOGGED", "UNDER_REVIEW", "ADMITTED", "EXCLUDED"}
INTERVIEW_STATUSES = {"SCHEDULED", "UPJOHN_DELIVERED", "COMPLETED", "NO_SHOW", "CANCELLED"}
DESIGNATION_STATUSES = {"DESIGNATED", "CONFIRMED", "CHALLENGED", "WAIVED"}
FINDING_STATUSES = {"DRAFT", "CALIBRATED", "FINAL", "CHALLENGED"}
REC_STATUSES = {"PROPOSED", "APPROVED", "REJECTED", "RECALLED"}
REPORT_STATUSES = {"DRAFT", "LEGAL_REVIEW", "DISTRIBUTION_APPROVED", "DISTRIBUTED", "RECALLED", "SUPERSEDED"}
DISCLOSURE_STATUSES = {"PENDING", "DECIDED", "FILED", "OVERRIDDEN", "SUPERSEDED"}
REMEDIATION_STATUSES = {"OPEN", "IN_PROGRESS", "AWAITING_VERIFICATION", "VERIFIED", "WAIVED"}
ALERT_STATUSES = {"OPEN", "ACKNOWLEDGED", "ESCALATED", "DISMISSED"}

SEVERITY_WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
CUSTODY_STATUSES = {"LOGGED", "UNDER_REVIEW", "ADMITTED"}
OPEN_SCOPE_STATUSES = {"PROPOSED", "APPROVED", "IN_PROGRESS"}
ACTIVE_DESIGNATION_STATUSES = {"DESIGNATED", "CONFIRMED", "CHALLENGED"}
OPEN_REMEDIATION_STATUSES = {"OPEN", "IN_PROGRESS", "AWAITING_VERIFICATION"}

# notice scope -> covered collection data_source
_COVERAGE = {"EMAIL": "EMAIL", "DEVICES": "DEVICE", "CHAT": "CHAT", "FILES": "FILES"}


# ---------------------------------------------------------------------------
# generic row helpers
# ---------------------------------------------------------------------------
def new_row(fields):
    now = db.clock_now()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    """Every mutation of a row bumps its version by exactly 1 (PRD §2.4)."""
    row["version"] += 1
    row["updated_at"] = db.clock_now()


def get_or_404(table, rid, label="Resource"):
    row = table.get(rid)
    if row is None:
        errors.not_found(f"{label} {rid} does not exist")
    return row


def dump(row):
    out = {}
    for k, v in row.items():
        if k.startswith("_"):
            continue
        if hasattr(v, "tzinfo"):  # datetime
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# ---------------------------------------------------------------------------
# case derived fields (SCAFFOLD calculations: preservation_completeness_ratio,
# active privileged count, open remediation count, case_priority_score)
# ---------------------------------------------------------------------------
def priority_terms(case):
    """case_priority_score raw + tier. Raw depends ONLY on severity,
    pattern_escalated, and PENDING disclosure deadlines (never on backlog)."""
    raw = 10 * SEVERITY_WEIGHT[case["severity"]]
    if case.get("pattern_escalated"):
        raw += 15
    horizon = db.clock_now() + timedelta(days=7)
    for d in db.disclosures.values():
        if (
            d["case_id"] == case["id"]
            and d["status"] == "PENDING"
            and d["decision_deadline"] <= horizon
        ):
            raw += 10
            break
    tier = "URGENT" if raw >= 40 else ("ELEVATED" if raw >= 20 else "ROUTINE")
    return raw, tier


def recompute_case_derived(case):
    cid = case["id"]
    notices = [n for n in db.notices.values() if n["case_id"] == cid]
    ack = sum(1 for n in notices if n["status"] == "ACKNOWLEDGED")
    issued = sum(1 for n in notices if n["status"] == "ISSUED")
    if ack + issued == 0:
        case["preservation_completeness_ratio"] = 1.0
    else:
        case["preservation_completeness_ratio"] = round2(
            Decimal(ack) / Decimal(ack + issued)
        )
    case["active_privileged_artifact_count"] = sum(
        1
        for d in db.designations.values()
        if d["case_id"] == cid and d["status"] in ACTIVE_DESIGNATION_STATUSES
    )
    case["open_remediation_count"] = sum(
        1
        for r in db.remediations.values()
        if r["case_id"] == cid and r["status"] in OPEN_REMEDIATION_STATUSES
    )
    raw, tier = priority_terms(case)
    case["case_priority_score"] = raw
    case["priority_tier"] = tier


def recompute_pattern_escalated(case):
    """True while any PatternAlert with alert_type REPEAT_SUBJECT or
    DEPARTMENT_CLUSTER names this case and is ACKNOWLEDGED or ESCALATED."""
    cid = case["id"]
    flag = False
    for a in db.alerts.values():
        if (
            a["alert_type"] in ("REPEAT_SUBJECT", "DEPARTMENT_CLUSTER")
            and a["status"] in ("ACKNOWLEDGED", "ESCALATED")
            and cid in a["case_ids"]
        ):
            flag = True
            break
    case["pattern_escalated"] = flag
    raw, tier = priority_terms(case)
    case["case_priority_score"] = raw
    case["priority_tier"] = tier


def dump_case(row):
    d = dump(row)
    # §2.12: the time-relative urgency term is recomputed on every read
    raw, tier = priority_terms(row)
    d["case_priority_score"] = raw
    d["priority_tier"] = tier
    return d


def dump_remediation(row):
    d = dump(row)
    d["is_overdue"] = remediation_is_overdue(row)
    return d


def remediation_is_overdue(row):
    return (
        db.clock_now() > row["due_date"]
        and row["status"] in OPEN_REMEDIATION_STATUSES
    )


# ---------------------------------------------------------------------------
# custody totals (collection_custody_totals)
# ---------------------------------------------------------------------------
def recompute_scope_custody(scope):
    items = [
        e
        for e in db.evidence_items.values()
        if e["collection_scope_id"] == scope["id"] and e["status"] in CUSTODY_STATUSES
    ]
    scope["collected_item_count"] = len(items)
    scope["collected_bytes"] = sum(e["size_bytes"] for e in items)


# ---------------------------------------------------------------------------
# substantiation_score (provisional / final variants)
# ---------------------------------------------------------------------------
def substantiation_score(finding, variant, consistency_level=None, subject_admission=False):
    case_id = finding["case_id"]
    if variant == "provisional":
        ev_statuses = {"UNDER_REVIEW", "ADMITTED"}
        int_statuses = {"UPJOHN_DELIVERED", "COMPLETED"}
        c = Decimal("0.15")
        a = 0
    else:
        ev_statuses = {"ADMITTED"}
        int_statuses = {"COMPLETED"}
        c = {"LOW": Decimal("0.00"), "MEDIUM": Decimal("0.15"), "HIGH": Decimal("0.30")}[
            consistency_level
        ]
        a = 1 if subject_admission else 0

    e_count = 0
    for eid in finding["evidence_item_ids"]:
        item = db.evidence_items.get(eid)
        if item is not None and item["status"] in ev_statuses:
            e_count += 1
    w_count = sum(
        1
        for i in db.interviews.values()
        if i["case_id"] == case_id
        and not i.get("is_subject_interview", False)
        and i["status"] in int_statuses
    )
    score = Decimal("0.25") * e_count + Decimal("0.15") * w_count + c + Decimal("0.10") * a
    score = min(Decimal("1.00"), score)
    return round2(score)


# ---------------------------------------------------------------------------
# discipline_severity_index (POLICY_MATRIX / CALIBRATED variants)
# ---------------------------------------------------------------------------
def discipline_tier(index):
    if index < 20:
        return "COACHING"
    if index <= 39:
        return "WARNING"
    if index <= 59:
        return "SUSPENSION"
    return "TERMINATION"


def prior_history_count(case_id, finding):
    """FINAL SUBSTANTIATED findings on OTHER cases, same subject employee_ref,
    created strictly before this finding (creation order breaks created_at
    ties: earliest-created wins)."""
    subject = db.subjects.get(finding["subject_id"])
    if subject is None:
        return 0
    emp = subject["employee_ref"]
    this_key = (finding["created_at"], finding["_seq"])
    n = 0
    for f in db.findings.values():
        if f["id"] == finding["id"]:
            continue
        if f["case_id"] == case_id:
            continue
        if f["status"] != "FINAL" or f.get("finding_type") != "SUBSTANTIATED":
            continue
        other = db.subjects.get(f["subject_id"])
        if other is None or other["employee_ref"] != emp:
            continue
        if (f["created_at"], f["_seq"]) < this_key:
            n += 1
    return n


def discipline_indexes(case, finding, mitigation_count, aggravation_count):
    prior = prior_history_count(case["id"], finding)
    base = 10 * SEVERITY_WEIGHT[case["severity"]]
    multiplier = Decimal(1) + Decimal("0.25") * min(prior, 3)
    index_policy_matrix = round0(Decimal(base) * multiplier)
    index_calibrated = (
        index_policy_matrix
        + 5 * min(aggravation_count, 2)
        - 5 * min(mitigation_count, 2)
    )
    return prior, index_policy_matrix, index_calibrated, discipline_tier(index_calibrated)


# ---------------------------------------------------------------------------
# pattern_risk_score
# ---------------------------------------------------------------------------
def pattern_risk(case_rows, window_end):
    n = len(case_rows)
    sev_max = max(SEVERITY_WEIGHT[c["severity"]] for c in case_rows)
    latest = max(c["created_at"] for c in case_rows)
    d = int((window_end - latest).total_seconds() // 86400)
    d = max(0, min(90, d))
    recency = max(Decimal("0.20"), Decimal(1) - Decimal(d) / Decimal(90))
    deps = {c.get("department") for c in case_rows if c.get("department")}
    spread = Decimal(1) + Decimal("0.25") * min(len(deps) - 1, 2)
    volume = Decimal(1) + Decimal("0.5") * (n - 1)
    raw = Decimal(10) * sev_max * volume * recency * spread
    score = round2(min(Decimal(100), raw))
    tier = "HIGH" if score >= 70 else ("MEDIUM" if score >= 40 else "LOW")
    return score, tier


# ---------------------------------------------------------------------------
# evidence_review_effort_minutes (pinned rounding order:
# per-item ceil -> sum -> x1.15 -> round half-up)
# ---------------------------------------------------------------------------
def review_effort_minutes(scope):
    subtotal = 0
    for e in db.evidence_items.values():
        if e["collection_scope_id"] != scope["id"]:
            continue
        if e["status"] not in {"LOGGED", "UNDER_REVIEW", "ADMITTED", "EXCLUDED"}:
            continue
        raw = Decimal(e["size_bytes"]) / Decimal(1000000) * Decimal(2)
        subtotal += ceil_int(raw)
    return round0(Decimal(subtotal) * Decimal("1.15"))


# ---------------------------------------------------------------------------
# preservation coverage
# ---------------------------------------------------------------------------
def notice_covers(notice, data_source):
    if notice["scope"] == "ALL_DATA":
        return True
    return _COVERAGE.get(notice["scope"]) == data_source


def covering_notices(case_id, custodian_ref, data_source, statuses):
    return [
        n
        for n in db.notices.values()
        if n["case_id"] == case_id
        and n["custodian_ref"] == custodian_ref
        and n["status"] in statuses
        and notice_covers(n, data_source)
    ]
