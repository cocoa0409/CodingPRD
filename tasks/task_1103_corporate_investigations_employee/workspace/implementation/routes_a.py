"""Routes: Case, Allegation, InvestigationPlan, CaseSubject."""
from flask import Blueprint, g, request

import db
import errors
import resp
import services as svc
import validate as v
from transitions import need_rationale, parse_to_status, require_actor

bp = Blueprint("core", __name__)

LIST_ROLES = {
    "IntakeCoordinator", "Investigator", "InvestigationsManager",
    "HRBusinessPartner", "GeneralCounsel", "ChiefLegalOfficer",
    "ComplianceAuditor",
}

CASE_ACTORS = {
    "TRIAGED": "IntakeCoordinator",
    "DISMISSED": "IntakeCoordinator",
    "FINDINGS": "Investigator",
    "FIELDWORK": "InvestigationsManager",
    "DISPOSITION": "InvestigationsManager",
    "REMEDIATION": "InvestigationsManager",
    "CLOSED": "InvestigationsManager",
}


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------
@bp.post("/api/cases")
def create_case():
    p = v.payload()
    title = v.need_str(p, "title")
    category = v.need_enum(p, "allegation_category", svc.ALLEGATION_CATEGORIES)
    severity = v.need_enum(p, "severity", svc.SEVERITIES)
    lead = v.need_str(p, "lead_investigator_id")
    description = v.opt_str(p, "description")
    department = v.opt_str(p, "department")

    now = db.clock_now()
    case = svc.new_row(
        {
            "title": title,
            "description": description,
            "allegation_category": category,
            "severity": severity,
            "department": department,
            "lead_investigator_id": lead,
            "case_number": db.next_case_number(now.year),
            "status": "INTAKE",
            "pattern_escalated": False,
            "case_priority_score": 0,
            "priority_tier": "ROUTINE",
            "preservation_completeness_ratio": 1.0,
            "active_privileged_artifact_count": 0,
            "open_remediation_count": 0,
        }
    )
    db.cases[case["id"]] = case
    svc.recompute_case_derived(case)
    return resp.ok(svc.dump_case(case), status=201)


@bp.get("/api/cases")
def list_cases():
    q = request.args
    rows = list(db.cases.values())
    for param, field in (
        ("status", "status"),
        ("category", "allegation_category"),
        ("severity", "severity"),
        ("department", "department"),
        ("lead_investigator_id", "lead_investigator_id"),
    ):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]

    limit, offset = v.parse_pagination(q)
    if q.get("sort") == "priority":
        tier_rank = {"URGENT": 0, "ELEVATED": 1, "ROUTINE": 2}

        def key(r):
            raw, tier = svc.priority_terms(r)
            return (tier_rank[tier], -raw, r["created_at"], r["_seq"])

        rows.sort(key=key)
    else:
        rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump_case(r) for r in page], limit, offset, total)


@bp.get("/api/cases/<rid>")
def get_case(rid):
    case = svc.get_or_404(db.cases, rid, "Case")
    return resp.ok(svc.dump_case(case))


@bp.post("/api/cases/<rid>/transition")
def transition_case(rid):
    case = svc.get_or_404(db.cases, rid, "Case")
    p = v.payload()
    to = parse_to_status(p, svc.CASE_STATUSES)
    require_actor(to, CASE_ACTORS)

    now = db.clock_now()
    src = case["status"]

    if src == "INTAKE" and to == "TRIAGED":
        severity = p.get("severity", None)
        if severity is None:
            errors.missing_field("severity")
        if severity not in svc.SEVERITIES:
            errors.validation("severity must be one of LOW, MEDIUM, HIGH, CRITICAL")
        department = p.get("department", None)
        if department is None or (isinstance(department, str) and not department.strip()):
            errors.missing_field("department")
        if not isinstance(department, str):
            errors.validation("department must be a string")
        case["severity"] = severity
        case["department"] = department
        case["status"] = "TRIAGED"
        for a in db.allegations.values():
            if a["case_id"] == case["id"] and a["status"] == "SUBMITTED":
                a["status"] = "TRIAGED"
                svc.touch(a)
    elif src in ("INTAKE", "TRIAGED") and to == "DISMISSED":
        need_rationale(p)
        case["status"] = "DISMISSED"
        for a in db.allegations.values():
            if a["case_id"] == case["id"] and a["status"] in ("SUBMITTED", "TRIAGED"):
                a["status"] = "DISMISSED"
                svc.touch(a)
    elif src == "FIELDWORK" and to == "FINDINGS":
        open_scopes = [
            s
            for s in db.scopes.values()
            if s["case_id"] == case["id"] and s["status"] in svc.OPEN_SCOPE_STATUSES
        ]
        if open_scopes:
            errors.business(
                "ERR_OPEN_COLLECTION_SCOPES",
                "Collection scopes remain open (PROPOSED/APPROVED/IN_PROGRESS)",
            )
        svc.recompute_case_derived(case)
        if case["preservation_completeness_ratio"] != 1.0:
            errors.business(
                "ERR_PRESERVATION_INCOMPLETE",
                "preservation_completeness_ratio must equal 1.00",
            )
        case["status"] = "FINDINGS"
    elif src == "FINDINGS" and to == "FIELDWORK":
        case["status"] = "FIELDWORK"
    elif src == "FINDINGS" and to == "DISPOSITION":
        open_findings = [
            f
            for f in db.findings.values()
            if f["case_id"] == case["id"] and f["status"] != "FINAL"
        ]
        if open_findings:
            errors.business(
                "ERR_FINDINGS_NOT_FINAL",
                "Every finding of the case must be FINAL",
            )
        case["status"] = "DISPOSITION"
    elif src == "DISPOSITION" and to == "REMEDIATION":
        finding_ids = {
            f["id"] for f in db.findings.values() if f["case_id"] == case["id"]
        }
        proposed = [
            r
            for r in db.recommendations.values()
            if r["finding_id"] in finding_ids and r["status"] == "PROPOSED"
        ]
        if proposed:
            errors.business(
                "ERR_UNRESOLVED_DISCIPLINE",
                "A disciplinary recommendation is still PROPOSED",
            )
        if case["severity"] == "CRITICAL":
            decisions = [
                d for d in db.disclosures.values() if d["case_id"] == case["id"]
            ]
            has_decided = any(
                d["status"] in ("DECIDED", "FILED", "OVERRIDDEN") for d in decisions
            )
            has_pending = any(d["status"] == "PENDING" for d in decisions)
            if not has_decided or has_pending:
                errors.business(
                    "ERR_DISCLOSURE_REQUIRED",
                    "CRITICAL case requires a decided disclosure and none pending",
                )
        case["status"] = "REMEDIATION"
    elif src == "REMEDIATION" and to == "CLOSED":
        open_actions = [
            r
            for r in db.remediations.values()
            if r["case_id"] == case["id"] and r["status"] in svc.OPEN_REMEDIATION_STATUSES
        ]
        if open_actions:
            errors.business(
                "ERR_OPEN_REMEDIATION",
                "Every remediation action must be VERIFIED or WAIVED",
            )
        case["status"] = "CLOSED"
    elif src == "CLOSED" and to == "FIELDWORK":
        need_rationale(p)
        case["status"] = "FIELDWORK"
        # reopen cascade, depth 3
        challenged_finding_ids = set()
        for f in db.findings.values():
            if f["case_id"] == case["id"] and f["status"] == "FINAL":
                f["status"] = "CHALLENGED"
                svc.touch(f)
                challenged_finding_ids.add(f["id"])
        for r in db.recommendations.values():
            if r["finding_id"] in challenged_finding_ids and r["status"] == "APPROVED":
                r["status"] = "RECALLED"
                svc.touch(r)
        for rep in db.reports.values():
            if rep["case_id"] == case["id"] and rep["status"] == "DISTRIBUTED":
                rep["status"] = "RECALLED"
                svc.touch(rep)
        svc.recompute_case_derived(case)
    else:
        errors.invalid_state(f"Case cannot transition {src} -> {to}")

    svc.touch(case)
    svc.recompute_case_derived(case)
    return resp.ok(svc.dump_case(case))


# ---------------------------------------------------------------------------
# Allegation
# ---------------------------------------------------------------------------
@bp.post("/api/cases/<rid>/allegations")
def create_allegation(rid):
    case = svc.get_or_404(db.cases, rid, "Case")
    p = v.payload()
    channel = v.need_enum(p, "reporter_channel", svc.REPORTER_CHANNELS)
    is_anonymous = v.need_bool(p, "is_anonymous")
    narrative = v.need_str(p, "narrative")
    reporter_ref = v.opt_str(p, "reporter_ref")
    occurred_at = v.opt_dt(p, "occurred_at")

    if case["status"] in ("CLOSED", "DISMISSED"):
        errors.invalid_state("Cannot file an allegation against a CLOSED or DISMISSED case")
    if is_anonymous and reporter_ref is not None:
        errors.validation("reporter_ref is forbidden when is_anonymous is true")

    allegation = svc.new_row(
        {
            "case_id": case["id"],
            "reporter_channel": channel,
            "reporter_ref": reporter_ref,
            "is_anonymous": is_anonymous,
            "narrative": narrative,
            "occurred_at": occurred_at,
            "status": "SUBMITTED",
        }
    )
    db.allegations[allegation["id"]] = allegation
    return resp.ok(svc.dump(allegation), status=201)


@bp.get("/api/allegations")
def list_allegations():
    q = request.args
    rows = list(db.allegations.values())
    for param in ("case_id", "status", "reporter_channel"):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    limit, offset = v.parse_pagination(q)
    rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump(r) for r in page], limit, offset, total)


@bp.get("/api/allegations/<rid>")
def get_allegation(rid):
    return resp.ok(svc.dump(svc.get_or_404(db.allegations, rid, "Allegation")))


@bp.post("/api/allegations/<rid>/transition")
def transition_allegation(rid):
    allegation = svc.get_or_404(db.allegations, rid, "Allegation")
    p = v.payload()
    to = parse_to_status(p, svc.ALLEGATION_STATUSES)
    src = allegation["status"]

    if src == "SUBMITTED" and to == "TRIAGED":
        pass
    elif src == "TRIAGED" and to == "LINKED":
        case = svc.get_or_404(db.cases, allegation["case_id"], "Case")
        if case["status"] not in ("TRIAGED", "PLANNING", "FIELDWORK", "FINDINGS"):
            errors.invalid_state(
                "Allegation may link only while the parent case is TRIAGED, PLANNING, FIELDWORK or FINDINGS"
            )
    elif src in ("SUBMITTED", "TRIAGED") and to == "DISMISSED":
        need_rationale(p)
    else:
        errors.invalid_state(f"Allegation cannot transition {src} -> {to}")

    allegation["status"] = to
    svc.touch(allegation)
    return resp.ok(svc.dump(allegation))


# ---------------------------------------------------------------------------
# InvestigationPlan
# ---------------------------------------------------------------------------
@bp.post("/api/cases/<rid>/plans")
def create_plan(rid):
    case = svc.get_or_404(db.cases, rid, "Case")
    p = v.payload()
    scope_statement = v.need_str(p, "scope_statement")
    planned_start = v.need_dt(p, "planned_start")
    planned_end = v.need_dt(p, "planned_end")
    expected = v.occ_version(p)

    if planned_end <= planned_start:
        errors.validation("planned_end must be strictly after planned_start")

    # OCC (priority 5) precedes state checks (priority 6)
    if expected != case["version"]:
        errors.stale_version()

    if case["status"] not in ("TRIAGED", "PLANNING"):
        errors.invalid_state("Plans may be created only while the case is TRIAGED or PLANNING")

    submitted = [
        pl
        for pl in db.plans.values()
        if pl["case_id"] == case["id"] and pl["status"] == "SUBMITTED"
    ]
    if submitted:
        errors.business(
            "ERR_PLAN_SUBMITTED_EXISTS",
            "Another plan of this case is SUBMITTED",
        )

    # supersede prior DRAFT/REJECTED plans
    for pl in db.plans.values():
        if pl["case_id"] == case["id"] and pl["status"] in ("DRAFT", "REJECTED"):
            pl["status"] = "SUPERSEDED"
            svc.touch(pl)

    plan_version = 1 + max(
        [pl["plan_version"] for pl in db.plans.values() if pl["case_id"] == case["id"]],
        default=0,
    )
    plan = svc.new_row(
        {
            "case_id": case["id"],
            "plan_version": plan_version,
            "scope_statement": scope_statement,
            "planned_start": planned_start,
            "planned_end": planned_end,
            "drafter_id": g.user_id,
            "status": "DRAFT",
            "rejection_reason": None,
            "approved_by": None,
        }
    )
    db.plans[plan["id"]] = plan
    if case["status"] == "TRIAGED":
        case["status"] = "PLANNING"
    svc.touch(case)
    svc.recompute_case_derived(case)
    return resp.ok(svc.dump(plan), status=201)


@bp.get("/api/plans")
def list_plans():
    q = request.args
    rows = list(db.plans.values())
    for param in ("case_id", "status"):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    limit, offset = v.parse_pagination(q)
    rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump(r) for r in page], limit, offset, total)


@bp.get("/api/plans/<rid>")
def get_plan(rid):
    return resp.ok(svc.dump(svc.get_or_404(db.plans, rid, "InvestigationPlan")))


PLAN_ACTORS = {
    "SUBMITTED": "Investigator",
    "APPROVED": "InvestigationsManager",
    "REJECTED": "InvestigationsManager",
}


@bp.post("/api/plans/<rid>/transition")
def transition_plan(rid):
    plan = svc.get_or_404(db.plans, rid, "InvestigationPlan")
    p = v.payload()
    to = parse_to_status(p, svc.PLAN_STATUSES)
    require_actor(to, PLAN_ACTORS)

    src = plan["status"]
    case = svc.get_or_404(db.cases, plan["case_id"], "Case")

    if src == "DRAFT" and to == "SUBMITTED":
        if case["status"] != "PLANNING":
            errors.invalid_state("Parent case must be in PLANNING to submit a plan")
        plan["status"] = "SUBMITTED"
    elif src == "SUBMITTED" and to == "APPROVED":
        if g.user_id == plan["drafter_id"]:
            errors.business(
                "ERR_SOD_PLAN_APPROVAL",
                "Approver must differ from the plan's drafter",
            )
        plan["status"] = "APPROVED"
        plan["approved_by"] = g.user_id
        if case["status"] == "PLANNING":
            case["status"] = "FIELDWORK"
        svc.touch(case)
        svc.recompute_case_derived(case)
    elif src == "SUBMITTED" and to == "REJECTED":
        if g.user_id == plan["drafter_id"]:
            errors.business(
                "ERR_SOD_PLAN_APPROVAL",
                "Rejecter must differ from the plan's drafter",
            )
        reason = need_rationale(p, "rejection_reason")
        plan["status"] = "REJECTED"
        plan["rejection_reason"] = reason
    else:
        errors.invalid_state(f"InvestigationPlan cannot transition {src} -> {to}")

    svc.touch(plan)
    return resp.ok(svc.dump(plan))


# ---------------------------------------------------------------------------
# CaseSubject
# ---------------------------------------------------------------------------
@bp.post("/api/cases/<rid>/subjects")
def create_subject(rid):
    case = svc.get_or_404(db.cases, rid, "Case")
    p = v.payload()
    employee_ref = v.need_str(p, "employee_ref")
    role_in_case = v.need_enum(p, "role_in_case", svc.ROLES_IN_CASE)

    dup = [
        s
        for s in db.subjects.values()
        if s["case_id"] == case["id"]
        and s["employee_ref"] == employee_ref
        and s["status"] == "ACTIVE"
    ]
    if dup:
        errors.business(
            "ERR_DUPLICATE_SUBJECT",
            "An ACTIVE subject with this employee_ref already exists on the case",
        )

    subject = svc.new_row(
        {
            "case_id": case["id"],
            "employee_ref": employee_ref,
            "role_in_case": role_in_case,
            "status": "ACTIVE",
        }
    )
    db.subjects[subject["id"]] = subject
    return resp.ok(svc.dump(subject), status=201)


@bp.get("/api/subjects")
def list_subjects():
    q = request.args
    rows = list(db.subjects.values())
    for param in ("case_id", "employee_ref", "status"):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    limit, offset = v.parse_pagination(q)
    rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump(r) for r in page], limit, offset, total)


@bp.get("/api/subjects/<rid>")
def get_subject(rid):
    return resp.ok(svc.dump(svc.get_or_404(db.subjects, rid, "CaseSubject")))


@bp.post("/api/subjects/<rid>/transition")
def transition_subject(rid):
    subject = svc.get_or_404(db.subjects, rid, "CaseSubject")
    p = v.payload()
    to = parse_to_status(p, svc.SUBJECT_STATUSES)
    src = subject["status"]

    if src == "ACTIVE" and to == "CLEARED":
        open_findings = [
            f
            for f in db.findings.values()
            if f["subject_id"] == subject["id"]
            and f["status"] in ("DRAFT", "CALIBRATED", "CHALLENGED")
        ]
        if open_findings:
            errors.business(
                "ERR_SUBJECT_HAS_OPEN_FINDINGS",
                "Findings in DRAFT/CALIBRATED/CHALLENGED reference this subject",
            )
        subject["status"] = "CLEARED"
    elif src == "ACTIVE" and to == "SEPARATED":
        subject["status"] = "SEPARATED"
    else:
        errors.invalid_state(f"CaseSubject cannot transition {src} -> {to}")

    svc.touch(subject)
    return resp.ok(svc.dump(subject))
