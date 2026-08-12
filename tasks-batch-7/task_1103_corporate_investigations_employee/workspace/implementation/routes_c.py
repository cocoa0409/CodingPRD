"""Routes: PrivilegeDesignation, Finding, DisciplinaryRecommendation, CaseReport."""
from flask import Blueprint, g, request

import db
import errors
import resp
import services as svc
import validate as v
from transitions import need_rationale, parse_to_status, require_actor

bp = Blueprint("legal", __name__)


# ---------------------------------------------------------------------------
# PrivilegeDesignation
# ---------------------------------------------------------------------------
def _resolve_target(target_type, target_id):
    if target_type == "EVIDENCE_ITEM":
        return svc.get_or_404(db.evidence_items, target_id, "EvidenceItem")
    if target_type == "INTERVIEW":
        return svc.get_or_404(db.interviews, target_id, "WitnessInterview")
    return svc.get_or_404(db.reports, target_id, "CaseReport")


@bp.post("/api/cases/<rid>/privilege-designations")
def create_designation(rid):
    case = svc.get_or_404(db.cases, rid, "Case")
    p = v.payload()
    target_type = v.need_enum(p, "target_type", svc.TARGET_TYPES)
    target_id = v.need_str(p, "target_id")
    privilege_type = v.need_enum(p, "privilege_type", svc.PRIVILEGE_TYPES)
    rationale = v.opt_str(p, "rationale")

    # body-referenced target must exist (priority 4)
    target = _resolve_target(target_type, target_id)

    # uniqueness constraint (priority 8): one active designation per target
    for d in db.designations.values():
        if (
            d["target_type"] == target_type
            and d["target_id"] == target_id
            and d["status"] in svc.ACTIVE_DESIGNATION_STATUSES
        ):
            errors.business(
                "ERR_DUPLICATE_DESIGNATION",
                "An active designation already exists for this target",
            )

    # referential (priority 9): target must belong to this case
    if target.get("case_id") != case["id"]:
        errors.business(
            "ERR_TARGET_CASE_MISMATCH",
            "Designation target does not belong to this case",
        )

    designation = svc.new_row(
        {
            "case_id": case["id"],
            "target_type": target_type,
            "target_id": target_id,
            "privilege_type": privilege_type,
            "rationale": rationale,
            "designated_by": g.user_id,
            "status": "DESIGNATED",
        }
    )
    db.designations[designation["id"]] = designation
    svc.recompute_case_derived(case)
    return resp.ok(svc.dump(designation), status=201)


@bp.get("/api/privilege-designations")
def list_designations():
    q = request.args
    rows = list(db.designations.values())
    for param in ("case_id", "target_type", "privilege_type", "status"):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    limit, offset = v.parse_pagination(q)
    rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump(r) for r in page], limit, offset, total)


@bp.get("/api/privilege-designations/<rid>")
def get_designation(rid):
    return resp.ok(svc.dump(svc.get_or_404(db.designations, rid, "PrivilegeDesignation")))


DESIGNATION_ACTORS = {
    "CONFIRMED": "GeneralCounsel",
    "CHALLENGED": "ChiefLegalOfficer",
    "WAIVED": "GeneralCounsel",
}


@bp.post("/api/privilege-designations/<rid>/transition")
def transition_designation(rid):
    designation = svc.get_or_404(db.designations, rid, "PrivilegeDesignation")
    p = v.payload()
    to = parse_to_status(p, svc.DESIGNATION_STATUSES)
    require_actor(to, DESIGNATION_ACTORS)

    src = designation["status"]
    legal = (
        (src == "DESIGNATED" and to == "CONFIRMED")
        or (src == "CONFIRMED" and to == "CHALLENGED")
        or (src == "CHALLENGED" and to == "CONFIRMED")
        or (src in ("DESIGNATED", "CONFIRMED", "CHALLENGED") and to == "WAIVED")
    )
    if not legal:
        errors.invalid_state(f"PrivilegeDesignation cannot transition {src} -> {to}")

    designation["status"] = to
    svc.touch(designation)
    case = svc.get_or_404(db.cases, designation["case_id"], "Case")
    svc.recompute_case_derived(case)
    return resp.ok(svc.dump(designation))


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------
@bp.post("/api/cases/<rid>/findings")
def create_finding(rid):
    case = svc.get_or_404(db.cases, rid, "Case")
    p = v.payload()
    allegation_id = v.need_str(p, "allegation_id")
    subject_id = v.need_str(p, "subject_id")
    evidence_ids = p.get("evidence_item_ids", None)
    if evidence_ids is None:
        evidence_ids = []
    if not isinstance(evidence_ids, list) or any(not isinstance(x, str) for x in evidence_ids):
        errors.validation("evidence_item_ids must be an array of ids")

    # body-referenced existence (priority 4), in documented order
    allegation = svc.get_or_404(db.allegations, allegation_id, "Allegation")
    subject = svc.get_or_404(db.subjects, subject_id, "CaseSubject")
    items = [svc.get_or_404(db.evidence_items, eid, "EvidenceItem") for eid in evidence_ids]

    # state gate (priority 6)
    if case["status"] != "FINDINGS":
        errors.invalid_state("Findings may be created only while the case is in FINDINGS")

    # referential rules (priority 9)
    if allegation["status"] != "LINKED" or allegation["case_id"] != case["id"]:
        errors.business(
            "ERR_ALLEGATION_NOT_LINKED",
            "Allegation must be LINKED and belong to the case",
        )
    if subject["case_id"] != case["id"]:
        errors.business(
            "ERR_SUBJECT_NOT_IN_CASE",
            "Subject does not belong to the case",
        )
    for item in items:
        if item["case_id"] != case["id"] or item["status"] not in ("UNDER_REVIEW", "ADMITTED"):
            errors.business(
                "ERR_EVIDENCE_NOT_REVIEWABLE",
                "Linked evidence must belong to the case and be UNDER_REVIEW or ADMITTED",
            )

    finding = svc.new_row(
        {
            "case_id": case["id"],
            "allegation_id": allegation_id,
            "subject_id": subject_id,
            "evidence_item_ids": list(evidence_ids),
            "consistency_level": None,
            "subject_admission": None,
            "finding_type": None,
            "substantiation_score_provisional": 0.0,
            "substantiation_score_final": None,
            "status": "DRAFT",
        }
    )
    finding["substantiation_score_provisional"] = svc.substantiation_score(
        finding, "provisional"
    )
    db.findings[finding["id"]] = finding
    return resp.ok(svc.dump(finding), status=201)


@bp.get("/api/findings")
def list_findings():
    q = request.args
    rows = list(db.findings.values())
    for param in ("case_id", "allegation_id", "subject_id", "finding_type", "status"):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    limit, offset = v.parse_pagination(q)
    rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump(r) for r in page], limit, offset, total)


@bp.get("/api/findings/<rid>")
def get_finding(rid):
    return resp.ok(svc.dump(svc.get_or_404(db.findings, rid, "Finding")))


FINDING_ACTORS = {
    "CALIBRATED": "HRBusinessPartner",
    "FINAL": "InvestigationsManager",
    "CHALLENGED": frozenset(["InvestigationsManager", "GeneralCounsel"]),
}


def _calibrate(finding, p):
    consistency = p.get("consistency_level", None)
    finding_type = p.get("finding_type", None)
    if consistency is None:
        errors.missing_field("consistency_level")
    if finding_type is None:
        errors.missing_field("finding_type")
    if consistency not in svc.CONSISTENCY_LEVELS:
        errors.validation("consistency_level must be one of LOW, MEDIUM, HIGH")
    if finding_type not in svc.FINDING_TYPES:
        errors.validation("finding_type must be one of SUBSTANTIATED, UNSUBSTANTIATED, INCONCLUSIVE")
    admission = v.opt_bool(p, "subject_admission", default=False)

    score = svc.substantiation_score(
        finding, "final", consistency_level=consistency, subject_admission=admission
    )
    if finding_type == "SUBSTANTIATED" and score < 0.70:
        errors.business(
            "ERR_THRESHOLD_NOT_MET",
            "SUBSTANTIATED requires substantiation_score_final >= 0.70",
        )
    finding["substantiation_score_final"] = score
    finding["consistency_level"] = consistency
    finding["subject_admission"] = admission
    finding["finding_type"] = finding_type
    finding["status"] = "CALIBRATED"


@bp.post("/api/findings/<rid>/transition")
def transition_finding(rid):
    finding = svc.get_or_404(db.findings, rid, "Finding")
    p = v.payload()
    to = parse_to_status(p, svc.FINDING_STATUSES)
    require_actor(to, FINDING_ACTORS)

    src = finding["status"]
    case = svc.get_or_404(db.cases, finding["case_id"], "Case")

    if src == "DRAFT" and to == "CALIBRATED":
        _calibrate(finding, p)
    elif src == "CALIBRATED" and to == "FINAL":
        if g.user_id == case["lead_investigator_id"]:
            errors.business(
                "ERR_SOD_FINDING_FINALIZATION",
                "Finalizer must differ from the case's lead investigator",
            )
        finding["status"] = "FINAL"
    elif src == "FINAL" and to == "CHALLENGED":
        finding["status"] = "CHALLENGED"
        for r in db.recommendations.values():
            if r["finding_id"] == finding["id"] and r["status"] == "APPROVED":
                r["status"] = "RECALLED"
                svc.touch(r)
    elif src == "CHALLENGED" and to == "CALIBRATED":
        _calibrate(finding, p)
    else:
        errors.invalid_state(f"Finding cannot transition {src} -> {to}")

    svc.touch(finding)
    return resp.ok(svc.dump(finding))


# ---------------------------------------------------------------------------
# DisciplinaryRecommendation
# ---------------------------------------------------------------------------
@bp.post("/api/findings/<rid>/disciplinary-recommendations")
def create_recommendation(rid):
    finding = svc.get_or_404(db.findings, rid, "Finding")
    p = v.payload()
    mitigation = v.need_int(p, "mitigation_count")
    aggravation = v.need_int(p, "aggravation_count")
    recommended_action = v.need_enum(p, "recommended_action", svc.REC_ACTIONS)
    justification = v.opt_str(p, "justification")

    if finding["status"] != "FINAL":
        errors.invalid_state("Recommendations may be proposed only on a FINAL finding")
    if mitigation < 0 or aggravation < 0:
        errors.validation("mitigation_count and aggravation_count must be >= 0")
    mitigation = min(mitigation, 2)
    aggravation = min(aggravation, 2)

    for r in db.recommendations.values():
        if r["finding_id"] == finding["id"] and r["status"] == "PROPOSED":
            errors.business(
                "ERR_OPEN_RECOMMENDATION_EXISTS",
                "A PROPOSED recommendation already exists for this finding",
            )

    case = svc.get_or_404(db.cases, finding["case_id"], "Case")
    prior, ipm, ical, suggested = svc.discipline_indexes(case, finding, mitigation, aggravation)

    if recommended_action != suggested and justification is None:
        errors.missing_field("justification")

    rec = svc.new_row(
        {
            "finding_id": finding["id"],
            "proposed_by": g.user_id,
            "severity_assessment": case["severity"],
            "prior_history_count": prior,
            "mitigation_count": mitigation,
            "aggravation_count": aggravation,
            "index_policy_matrix": ipm,
            "index_calibrated": ical,
            "suggested_action": suggested,
            "recommended_action": recommended_action,
            "justification": justification,
            "status": "PROPOSED",
        }
    )
    db.recommendations[rec["id"]] = rec
    return resp.ok(svc.dump(rec), status=201)


@bp.get("/api/disciplinary-recommendations")
def list_recommendations():
    q = request.args
    rows = list(db.recommendations.values())
    for param in ("finding_id", "status", "recommended_action"):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    limit, offset = v.parse_pagination(q)
    rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump(r) for r in page], limit, offset, total)


@bp.get("/api/disciplinary-recommendations/<rid>")
def get_recommendation(rid):
    return resp.ok(svc.dump(svc.get_or_404(db.recommendations, rid, "DisciplinaryRecommendation")))


@bp.post("/api/disciplinary-recommendations/<rid>/transition")
def transition_recommendation(rid):
    rec = svc.get_or_404(db.recommendations, rid, "DisciplinaryRecommendation")
    p = v.payload()
    to = parse_to_status(p, svc.REC_STATUSES)
    src = rec["status"]

    if src == "PROPOSED" and to == "APPROVED":
        if g.user_id == rec["proposed_by"]:
            errors.business(
                "ERR_SOD_DISCIPLINE_APPROVAL",
                "Approver must differ from proposed_by",
            )
        rec["status"] = "APPROVED"
    elif src == "PROPOSED" and to == "REJECTED":
        need_rationale(p)
        rec["status"] = "REJECTED"
    else:
        errors.invalid_state(f"DisciplinaryRecommendation cannot transition {src} -> {to}")

    svc.touch(rec)
    return resp.ok(svc.dump(rec))


# ---------------------------------------------------------------------------
# CaseReport
# ---------------------------------------------------------------------------
@bp.post("/api/cases/<rid>/reports")
def create_report(rid):
    case = svc.get_or_404(db.cases, rid, "Case")
    p = v.payload()
    title = v.need_str(p, "title")
    distribution_tier = v.need_enum(p, "distribution_tier", svc.DIST_TIERS)
    distribution_list = v.need_list(p, "distribution_list")
    report_privilege_type = v.need_enum(p, "report_privilege_type", svc.REPORT_PRIV_TYPES)
    expected = v.occ_version(p)

    if not distribution_list or any(not isinstance(x, str) for x in distribution_list):
        errors.validation("distribution_list must be a non-empty array of recipient ids")

    # OCC (priority 5) precedes state checks (priority 6)
    if expected != case["version"]:
        errors.stale_version()

    if case["status"] not in ("FINDINGS", "DISPOSITION", "REMEDIATION"):
        errors.invalid_state(
            "Reports may be drafted only while the case is FINDINGS, DISPOSITION or REMEDIATION"
        )

    for rep in db.reports.values():
        if rep["case_id"] == case["id"] and rep["status"] == "DRAFT":
            rep["status"] = "SUPERSEDED"
            svc.touch(rep)

    report = svc.new_row(
        {
            "case_id": case["id"],
            "title": title,
            "distribution_tier": distribution_tier,
            "distribution_list": list(distribution_list),
            "report_privilege_type": report_privilege_type,
            "pinned_designation_snapshot": None,
            "distributed_at": None,
            "status": "DRAFT",
        }
    )
    db.reports[report["id"]] = report
    svc.touch(case)
    svc.recompute_case_derived(case)
    return resp.ok(svc.dump(report), status=201)


@bp.get("/api/reports")
def list_reports():
    q = request.args
    rows = list(db.reports.values())
    for param in ("case_id", "status", "distribution_tier"):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    limit, offset = v.parse_pagination(q)
    rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump(r) for r in page], limit, offset, total)


@bp.get("/api/reports/<rid>")
def get_report(rid):
    return resp.ok(svc.dump(svc.get_or_404(db.reports, rid, "CaseReport")))


REPORT_ACTORS = {
    "LEGAL_REVIEW": "Investigator",
    "DISTRIBUTION_APPROVED": "GeneralCounsel",
    "RECALLED": "GeneralCounsel",
    # DISTRIBUTED is tier-dependent and checked inline
}


@bp.post("/api/reports/<rid>/transition")
def transition_report(rid):
    report = svc.get_or_404(db.reports, rid, "CaseReport")
    p = v.payload()
    to = parse_to_status(p, svc.REPORT_STATUSES)
    if to == "DISTRIBUTED":
        required = "ChiefLegalOfficer" if report["distribution_tier"] == "BOARD" else "GeneralCounsel"
        require_actor(to, {"DISTRIBUTED": required})
    else:
        require_actor(to, REPORT_ACTORS)

    src = report["status"]
    case = svc.get_or_404(db.cases, report["case_id"], "Case")

    if src == "DRAFT" and to == "LEGAL_REVIEW":
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
        report["status"] = "LEGAL_REVIEW"
    elif src == "LEGAL_REVIEW" and to == "DISTRIBUTION_APPROVED":
        pending = [
            d
            for d in db.designations.values()
            if d["case_id"] == case["id"] and d["status"] in ("DESIGNATED", "CHALLENGED")
        ]
        if pending:
            errors.business(
                "ERR_PRIVILEGE_PENDING",
                "All designations of the case must be CONFIRMED or WAIVED",
            )
        report["pinned_designation_snapshot"] = [
            d["id"]
            for d in svc.sort_rows(
                [d for d in db.designations.values() if d["case_id"] == case["id"]]
            )
            if d["status"] == "CONFIRMED"
        ]
        report["status"] = "DISTRIBUTION_APPROVED"
    elif src == "DISTRIBUTION_APPROVED" and to == "DISTRIBUTED":
        if report["distribution_tier"] == "BOARD":
            acp_targets = {
                d["target_id"]
                for d in db.designations.values()
                if d["case_id"] == case["id"]
                and d["privilege_type"] == "ACP"
                and d["status"] in ("DESIGNATED", "CONFIRMED")
                and d["target_type"] == "EVIDENCE_ITEM"
            }
            if acp_targets:
                linked = set()
                for f in db.findings.values():
                    if f["case_id"] == case["id"]:
                        linked.update(f["evidence_item_ids"])
                if acp_targets & linked:
                    errors.business(
                        "ERR_PRIVILEGED_DISTRIBUTION",
                        "BOARD distribution blocked by an active ACP designation on linked evidence",
                    )
        report["distributed_at"] = db.clock_now()
        report["status"] = "DISTRIBUTED"
    elif src == "DISTRIBUTED" and to == "RECALLED":
        report["status"] = "RECALLED"
    else:
        errors.invalid_state(f"CaseReport cannot transition {src} -> {to}")

    svc.touch(report)
    return resp.ok(svc.dump(report))
