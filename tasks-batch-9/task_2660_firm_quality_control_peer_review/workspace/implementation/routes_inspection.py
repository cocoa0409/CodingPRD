"""Internal inspection programme: cycles, selection, findings, root cause analysis and
remediation (PRD 3.6 - 3.8)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import clock
import response as envelope
import shapes
import store
import vocab
from errors import ApiError

bp = Blueprint("inspection", __name__)

A = auth.SYSTEM_ADMIN
FMP = auth.FIRM_MANAGING_PARTNER
EP = auth.ENGAGEMENT_PARTNER
QCD = auth.QUALITY_CONTROL_DIRECTOR


# --------------------------------------------------------------------------- #
# 3.6 Inspection cycles and the selector
# --------------------------------------------------------------------------- #

@bp.post("/firms/<firm_id>/internal-inspections")
def create_inspection(firm_id):
    actor = auth.authenticate((A, QCD, FMP))
    firm = shapes.need_firm(firm_id)
    body = shapes.body()
    shapes.require_present(body, ["inspection_year", "target_engagement_count"])
    year = shapes.as_int(body, "inspection_year", 2000, 2100)
    target = shapes.as_int(body, "target_engagement_count", 1)
    auth.require_same_firm(actor, firm["id"])
    for existing in store.rows(store.INSPECTIONS):
        if existing["firm_id"] == firm["id"] and existing["inspection_year"] == year:
            raise ApiError("ERR_DUPLICATE_INSPECTION_YEAR")
    inspection = store.insert(store.INSPECTIONS, {
        "firm_id": firm["id"],
        "inspection_year": year,
        "target_engagement_count": target,
        "engagements_selected_count": 0,
        "must_select_eligible_count": 0,
        "must_select_selected_count": 0,
        "must_select_coverage_pct": 100.00,
        "severity_index_basis": "NONE",
        "deficiency_severity_index": None,
        "concluded_at": None,
        "state": "PLANNING",
    })
    return envelope.object_response(store.serialize(store.INSPECTIONS, inspection), 201)


@bp.post("/internal-inspections/<inspection_id>/selections")
def run_selection(inspection_id):
    actor = auth.authenticate((A, QCD))
    inspection = shapes.need_inspection(inspection_id)
    auth.require_same_firm(actor, inspection["firm_id"])
    if inspection["state"] != "PLANNING":
        raise ApiError("ERR_INVALID_TRANSITION")

    chosen = calc.inspection_engagement_selection(inspection)
    rank = 0
    for engagement, reason, is_must_select in chosen:
        rank += 1
        store.insert(store.INSPECTION_SELECTIONS, {
            "inspection_id": inspection["id"],
            "engagement_id": engagement["id"],
            "selection_reason": reason,
            "is_must_select": is_must_select,
            "selected_rank": rank,
            "finding_count": 0,
            "weighted_points": 0.00,
        })
    store.mutate(inspection, {
        "engagements_selected_count": len(chosen),
        "state": "SELECTION_COMPLETE",
    }, force=True)
    eligible_count, selected_count, pct = calc.must_select_coverage(inspection)
    inspection["must_select_eligible_count"] = eligible_count
    inspection["must_select_selected_count"] = selected_count
    inspection["must_select_coverage_pct"] = float(pct)

    for engagement, _reason, _must in chosen:
        partner = store.get(store.PARTNERS, engagement["engagement_partner_id"])
        if partner is not None:
            store.mutate(partner,
                         {"last_inspected_year": inspection["inspection_year"]})
    # PRD 4: "selector runs ... return HTTP 200 with the affected resource in data".
    return envelope.object_response(store.serialize(store.INSPECTIONS, inspection), 200)


INSPECTION_NEXT = {
    "PLANNING": (),
    "SELECTION_COMPLETE": ("IN_PROGRESS", "CONCLUDED"),
    "IN_PROGRESS": ("FINDINGS_CLASSIFIED",),
    "FINDINGS_CLASSIFIED": ("CONCLUDED",),
    "CONCLUDED": (),
}


def _cycle_findings(inspection, exclude_withdrawn=True):
    out = []
    for selection in calc.children(store.INSPECTION_SELECTIONS, "inspection_id",
                                   inspection["id"]):
        out.extend(calc.selection_findings(selection["id"], exclude_withdrawn))
    return out


@bp.post("/internal-inspections/<inspection_id>/transitions")
def inspection_transition(inspection_id):
    actor = auth.authenticate((A, QCD, FMP))
    inspection = shapes.need_inspection(inspection_id)
    body = shapes.body()
    shapes.require_present(body, ["to_state"])
    to_state = shapes.as_enum(body, "to_state", vocab.INSPECTION_STATE)
    basis = None
    if to_state == "FINDINGS_CLASSIFIED":
        shapes.require_present(body, ["severity_index_basis"])
        basis = shapes.as_enum(body, "severity_index_basis",
                               vocab.SEVERITY_INDEX_BASIS_INPUT)
    auth.require_same_firm(actor, inspection["firm_id"])
    if to_state not in INSPECTION_NEXT[inspection["state"]]:
        raise ApiError("ERR_INVALID_TRANSITION")

    updates = {"state": to_state}
    if to_state == "IN_PROGRESS":
        if inspection["engagements_selected_count"] < 1:
            raise ApiError("ERR_NO_ELIGIBLE_ENGAGEMENTS")
    elif to_state == "FINDINGS_CLASSIFIED":
        for finding in _cycle_findings(inspection, exclude_withdrawn=False):
            if finding["classification"] == "UNCLASSIFIED":
                raise ApiError("ERR_UNCLASSIFIED_FINDINGS_PRESENT")
        index, per_selection = calc.deficiency_severity_index(inspection, basis)
        updates["severity_index_basis"] = basis
        updates["deficiency_severity_index"] = float(index)
        if per_selection is not None:
            for selection_id, points in per_selection.items():
                selection = store.get(store.INSPECTION_SELECTIONS, selection_id)
                if selection is not None:
                    store.mutate(selection, {"weighted_points": float(points)})
    elif inspection["state"] == "SELECTION_COMPLETE":
        # Empty-cycle boundary: conclude without inspecting anything.
        if inspection["engagements_selected_count"] != 0:
            raise ApiError("ERR_INVALID_TRANSITION")
        _eligible, _selected, pct = calc.must_select_coverage(inspection)
        if pct != Decimal("100.00"):
            raise ApiError("ERR_MUST_SELECT_COVERAGE_INCOMPLETE")
        updates["deficiency_severity_index"] = 0.00
        updates["severity_index_basis"] = "ENGAGEMENT_WEIGHTED"
        updates["concluded_at"] = clock.now_iso()
    else:
        _eligible, _selected, pct = calc.must_select_coverage(inspection)
        if pct != Decimal("100.00"):
            raise ApiError("ERR_MUST_SELECT_COVERAGE_INCOMPLETE")
        for finding in _cycle_findings(inspection):
            if finding["classification"] in ("SIGNIFICANT_DEFICIENCY", "MATERIAL_FAILURE") \
                    and finding["state"] not in ("REMEDIATION_ASSIGNED", "REMEDIATED",
                                                 "VERIFIED"):
                raise ApiError("ERR_OPEN_SIGNIFICANT_FINDINGS")
        updates["concluded_at"] = clock.now_iso()

    store.mutate(inspection, updates, force=True)
    return envelope.object_response(store.serialize(store.INSPECTIONS, inspection))


# --------------------------------------------------------------------------- #
# 3.7 Findings
# --------------------------------------------------------------------------- #

@bp.post("/inspection-selections/<selection_id>/findings")
def create_finding(selection_id):
    actor = auth.authenticate((A, QCD))
    selection = shapes.need_selection(selection_id)
    inspection = store.get(store.INSPECTIONS, selection["inspection_id"])
    engagement = store.get(store.ENGAGEMENTS, selection["engagement_id"])
    body = shapes.body()
    shapes.require_present(body, ["title", "sqm_component"])
    title = shapes.as_str(body, "title", 1, 200)
    recurrence = shapes.as_bool(body, "prior_cycle_recurrence") \
        if shapes.has(body, "prior_cycle_recurrence") else False
    component = shapes.as_enum(body, "sqm_component", vocab.SQM_COMPONENT)
    auth.require_same_firm(actor, inspection["firm_id"])
    if inspection["state"] != "IN_PROGRESS":
        raise ApiError("ERR_INSPECTION_NOT_IN_PROGRESS")
    if engagement is None or engagement["workflow_state"] != "REPORT_RELEASED":
        raise ApiError("ERR_ENGAGEMENT_NOT_RELEASED")
    if engagement["engagement_partner_id"] == actor.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    finding = store.insert(store.FINDINGS, {
        "selection_id": selection["id"],
        "title": title,
        "sqm_component": component,
        "prior_cycle_recurrence": recurrence,
        "classification": "UNCLASSIFIED",
        "pervasiveness": "UNDETERMINED",
        "affects_report_conclusion": False,
        "class_points": 0,
        "verified_at": None,
        "reopen_count": 0,
        "state": "IDENTIFIED",
    })
    return envelope.object_response(store.serialize(store.FINDINGS, finding), 201)


CLASS_POINTS = {"OBSERVATION": 0, "DEFICIENCY": 3, "SIGNIFICANT_DEFICIENCY": 8,
                "MATERIAL_FAILURE": 20, "UNCLASSIFIED": 0}


def _refresh_selection(selection):
    store.mutate(selection, {
        "finding_count": len(calc.selection_findings(selection["id"])),
        "weighted_points": float(calc.selection_weighted_points(selection)),
    })


@bp.post("/inspection-findings/<finding_id>/classification")
def classify_finding(finding_id):
    actor = auth.authenticate((A, QCD, FMP))
    finding = shapes.need_finding(finding_id)
    selection = calc.finding_selection(finding)
    inspection = calc.finding_inspection(finding)
    firm = store.get(store.FIRMS, inspection["firm_id"]) if inspection else None
    body = shapes.body()
    shapes.require_present(body, ["classification", "pervasiveness",
                                 "affects_report_conclusion"])
    affects = shapes.as_bool(body, "affects_report_conclusion")
    classification = shapes.as_enum(body, "classification", vocab.CLASSIFICATION_INPUT)
    pervasiveness = shapes.as_enum(body, "pervasiveness", vocab.PERVASIVENESS_INPUT)
    if firm is not None:
        auth.require_same_firm(actor, firm["id"])
    if finding["state"] != "IDENTIFIED":
        raise ApiError("ERR_INVALID_TRANSITION")
    if inspection is None or inspection["state"] != "IN_PROGRESS":
        raise ApiError("ERR_INSPECTION_NOT_IN_PROGRESS")
    if classification == "MATERIAL_FAILURE" and not affects:
        raise ApiError("ERR_MATERIAL_FAILURE_REQUIRES_REPORT_IMPACT")

    # ---- link 1 -----------------------------------------------------------
    to_state = "WITHDRAWN" if classification == "OBSERVATION" else "RCA_PENDING"
    store.mutate(finding, {
        "classification": classification,
        "pervasiveness": pervasiveness,
        "affects_report_conclusion": affects,
        "class_points": CLASS_POINTS[classification],
        "state": to_state,
    }, force=True)
    if selection is not None:
        _refresh_selection(selection)
    if firm is not None:
        calc.recompute_counters(firm)
    if classification != "MATERIAL_FAILURE" or firm is None:
        return envelope.object_response(store.serialize(store.FINDINGS, finding))

    # ---- link 2: only a LOCKED file has something to reopen ---------------
    engagement = store.get(store.ENGAGEMENTS, selection["engagement_id"]) \
        if selection is not None else None
    if engagement is None or engagement["file_state"] != "LOCKED":
        return envelope.object_response(store.serialize(store.FINDINGS, finding))
    store.mutate(engagement, {
        "file_state": "OPEN",
        "reopened_count": engagement["reopened_count"] + 1,
    }, force=True)

    # ---- link 3: fires because link 2 reopened a file ---------------------
    target = None
    for risk in store.rows(store.QUALITY_RISKS):
        if risk["firm_id"] == firm["id"] and risk["state"] == "EVALUATED" and \
                risk["component"] == finding["sqm_component"]:
            target = risk
            break
    if target is None:
        return envelope.object_response(store.serialize(store.FINDINGS, finding))
    store.mutate(target, {
        "state": "RESPONDED",
        "residual_risk_score": None,
        "severity_band": "NONE",
        "evaluation_basis": "NONE",
        "reopen_count": target["reopen_count"] + 1,
    }, force=True)

    # ---- link 4: fires because link 3 took a risk out of EVALUATED --------
    posture = calc.recompute_posture(firm)

    # ---- link 5: fires because link 4 produced a CRITICAL posture ---------
    if posture == "CRITICAL":
        for row in store.rows(store.ENGAGEMENTS):
            if row["firm_id"] == firm["id"] and not row["eqr_required"] and \
                    row["workflow_state"] in ("PLANNING", "FIELDWORK"):
                store.mutate(row, {"eqr_required": True}, force=True)
    return envelope.object_response(store.serialize(store.FINDINGS, finding))


FINDING_NEXT = {
    "IDENTIFIED": (),
    "RCA_PENDING": (),
    "RCA_COMPLETE": (),
    "REMEDIATION_ASSIGNED": (),
    "REMEDIATED": ("VERIFIED",),
    "VERIFIED": ("REOPENED",),
    "REOPENED": (),
    "WITHDRAWN": (),
}


def _finding_plans(finding_id):
    return calc.children(store.PLANS, "finding_id", finding_id)


@bp.post("/inspection-findings/<finding_id>/transitions")
def finding_transition(finding_id):
    actor = auth.authenticate((A, QCD, FMP))
    finding = shapes.need_finding(finding_id)
    inspection = calc.finding_inspection(finding)
    firm = store.get(store.FIRMS, inspection["firm_id"]) if inspection else None
    body = shapes.body()
    shapes.require_present(body, ["to_state"])
    to_state = shapes.as_enum(body, "to_state", vocab.FINDING_STATE)
    if firm is not None:
        auth.require_same_firm(actor, firm["id"])
    if to_state == "VERIFIED" and finding["state"] == "VERIFIED":
        raise ApiError("ERR_FINDING_ALREADY_VERIFIED")
    if to_state not in FINDING_NEXT[finding["state"]]:
        raise ApiError("ERR_INVALID_TRANSITION")

    if to_state == "VERIFIED":
        relevant = [plan for plan in _finding_plans(finding["id"])
                    if plan["state"] in ("ACCEPTED", "COMPLETED")]
        plan = relevant[-1] if relevant else None
        if plan is not None and plan["owner_partner_id"] == actor.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        if plan is None or plan["state"] != "COMPLETED":
            raise ApiError("ERR_REMEDIATION_ACTIONS_INCOMPLETE")
        store.mutate(finding, {"state": "VERIFIED", "verified_at": clock.now_iso()},
                     force=True)
    else:
        store.mutate(finding, {
            "state": "REOPENED",
            "verified_at": None,
            "reopen_count": finding["reopen_count"] + 1,
        }, force=True)
    if firm is not None:
        calc.recompute_posture(firm)
    return envelope.object_response(store.serialize(store.FINDINGS, finding))


# --------------------------------------------------------------------------- #
# 3.8 Root cause analysis
# --------------------------------------------------------------------------- #

@bp.post("/inspection-findings/<finding_id>/root-cause-analyses")
def create_rca(finding_id):
    actor = auth.authenticate((A, QCD, EP))
    finding = shapes.need_finding(finding_id)
    inspection = calc.finding_inspection(finding)
    body = shapes.body()
    shapes.require_present(body, ["method", "root_cause_category",
                                 "contributing_factor_count", "narrative"])
    factors = shapes.as_int(body, "contributing_factor_count", 1, 10)
    narrative = shapes.as_str(body, "narrative", 1, 1000)
    method = shapes.as_enum(body, "method", vocab.RCA_METHOD)
    category = shapes.as_enum(body, "root_cause_category", vocab.ROOT_CAUSE_CATEGORY)
    if inspection is not None:
        auth.require_same_firm(actor, inspection["firm_id"])
    if finding["state"] != "RCA_PENDING":
        raise ApiError("ERR_INVALID_TRANSITION")
    rca = store.insert(store.RCAS, {
        "finding_id": finding["id"],
        "method": method,
        "root_cause_category": category,
        "contributing_factor_count": factors,
        "narrative": narrative,
        "depth_score": 0.00,
        "recurrence_flag": False,
        "validated_at": None,
        "state": "DRAFTED",
    })
    return envelope.object_response(store.serialize(store.RCAS, rca), 201)


@bp.post("/root-cause-analyses/<rca_id>/validation")
def validate_rca(rca_id):
    actor = auth.authenticate((A, QCD, FMP))
    rca = shapes.need_rca(rca_id)
    finding = store.get(store.FINDINGS, rca["finding_id"])
    inspection = calc.rca_inspection(rca)
    body = shapes.body()
    shapes.require_present(body, ["outcome"])
    outcome = shapes.as_enum(body, "outcome", vocab.RCA_OUTCOME)
    if inspection is not None:
        auth.require_same_firm(actor, inspection["firm_id"])
    if rca["state"] != "DRAFTED":
        raise ApiError("ERR_INVALID_TRANSITION")
    if finding is None:
        raise ApiError("ERR_RCA_FINDING_MISMATCH")

    if outcome == "REJECTED":
        store.mutate(rca, {"state": "REJECTED"}, force=True)
        return envelope.object_response(store.serialize(store.RCAS, rca))

    store.mutate(rca, {"state": "VALIDATED", "validated_at": clock.now_iso()}, force=True)
    recurrence, depth = calc.root_cause_depth_score(rca)
    rca["recurrence_flag"] = recurrence
    rca["depth_score"] = float(depth)
    if finding["state"] == "RCA_PENDING":
        store.mutate(finding, {"state": "RCA_COMPLETE"}, force=True)
    return envelope.object_response(store.serialize(store.RCAS, rca))


# --------------------------------------------------------------------------- #
# 3.8 Remediation plans
# --------------------------------------------------------------------------- #

@bp.post("/inspection-findings/<finding_id>/remediation-plans")
def create_plan(finding_id):
    actor = auth.authenticate((A, QCD, FMP))
    finding = shapes.need_finding(finding_id)
    inspection = calc.finding_inspection(finding)
    body = shapes.body()
    owner = None
    if shapes.has(body, "owner_partner_id"):
        owner = shapes.need_partner(body.get("owner_partner_id"))
    rca = None
    if shapes.has(body, "root_cause_analysis_id"):
        rca = shapes.need_rca(body.get("root_cause_analysis_id"))
    shapes.require_present(body, ["root_cause_analysis_id", "owner_partner_id",
                                 "target_completion_date", "action_count",
                                 "action_specificity_score", "expected_finding_version"])
    target_date = shapes.as_date(body, "target_completion_date")
    action_count = shapes.as_int(body, "action_count", 1, 20)
    specificity = shapes.as_decimal(body, "action_specificity_score", "0.00", "10.00")
    if inspection is not None:
        auth.require_same_firm(actor, inspection["firm_id"])
    shapes.check_version(body, "expected_finding_version", finding)
    # PRD 3.8 states the create's own gates - "Citing an analysis whose state is not
    # VALIDATED is refused with ERR_RCA_NOT_VALIDATED" - and never names an error for a
    # finding that has not yet reached RCA_COMPLETE, so the cited analysis is judged
    # first; otherwise the named code would only ever fire on a second analysis.
    if rca["state"] != "VALIDATED":
        raise ApiError("ERR_RCA_NOT_VALIDATED")
    if finding["state"] not in ("RCA_COMPLETE", "REOPENED"):
        raise ApiError("ERR_INVALID_TRANSITION")
    if inspection is not None and owner["firm_id"] != inspection["firm_id"]:
        raise ApiError("ERR_PARTNER_FIRM_MISMATCH")
    if rca["finding_id"] != finding["id"]:
        raise ApiError("ERR_RCA_FINDING_MISMATCH")

    # A superseding plan closes out every plan the finding already had accepted.
    for existing in _finding_plans(finding["id"]):
        if existing["state"] in ("ACCEPTED", "COMPLETED"):
            store.mutate(existing, {"state": "CLOSED"}, force=True)
    plan = store.insert(store.PLANS, {
        "finding_id": finding["id"],
        "root_cause_analysis_id": rca["id"],
        "owner_partner_id": owner["id"],
        "target_completion_date": target_date.isoformat(),
        "action_count": action_count,
        "completed_action_count": 0,
        "action_specificity_score": float(specificity),
        "raw_completeness": None,
        "acceptance_score": None,
        "completeness_tier": "NONE",
        "return_count": 0,
        "accepted_at": None,
        "state": "DRAFTED",
    })
    store.mutate(finding, {"state": "REMEDIATION_ASSIGNED"}, force=True)
    return envelope.object_response(store.serialize(store.PLANS, plan), 201)


PLAN_NEXT = {
    "DRAFTED": ("SUBMITTED",),
    "SUBMITTED": ("RETURNED", "ACCEPTED"),
    "RETURNED": ("SUBMITTED",),
    "ACCEPTED": ("COMPLETED",),
    "COMPLETED": (),
    "CLOSED": (),
}

OWNER_LEGS = ("SUBMITTED", "COMPLETED")


@bp.post("/remediation-plans/<plan_id>/transitions")
def plan_transition(plan_id):
    actor = auth.authenticate((A, QCD, FMP, EP))
    plan = shapes.need_plan(plan_id)
    finding = store.get(store.FINDINGS, plan["finding_id"])
    inspection = calc.finding_inspection(finding) if finding else None
    body = shapes.body()
    shapes.require_present(body, ["to_state"])
    to_state = shapes.as_enum(body, "to_state", vocab.PLAN_STATE)
    completed = None
    if shapes.has(body, "completed_action_count"):
        completed = shapes.as_int(body, "completed_action_count", 0)
    if to_state in OWNER_LEGS:
        auth.require_owner(actor, plan["owner_partner_id"])
    if inspection is not None:
        auth.require_same_firm(actor, inspection["firm_id"])
    if to_state not in PLAN_NEXT[plan["state"]]:
        raise ApiError("ERR_INVALID_TRANSITION")

    if to_state == "SUBMITTED":
        if completed is None:
            completed = plan["completed_action_count"]
        if completed > plan["action_count"]:
            shapes.fail("completed_action_count")
        rca = store.get(store.RCAS, plan["root_cause_analysis_id"])
        plan["completed_action_count"] = completed
        raw, tier, score = calc.remediation_acceptance_score(plan, rca)
        store.mutate(plan, {
            "completed_action_count": completed,
            "raw_completeness": float(raw),
            "completeness_tier": tier,
            "acceptance_score": float(score),
            "state": "SUBMITTED",
        }, force=True)
    elif to_state == "RETURNED":
        if plan["owner_partner_id"] == actor.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        store.mutate(plan, {
            "return_count": plan["return_count"] + 1,
            "state": "RETURNED",
        }, force=True)
    elif to_state == "ACCEPTED":
        if plan["owner_partner_id"] == actor.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        score = plan["acceptance_score"]
        if score is None or Decimal(str(score)) < Decimal("7.00"):
            raise ApiError("ERR_ACCEPTANCE_SCORE_BELOW_THRESHOLD")
        store.mutate(plan, {"state": "ACCEPTED", "accepted_at": clock.now_iso()},
                     force=True)
        if finding is not None and finding["state"] == "REMEDIATION_ASSIGNED":
            store.mutate(finding, {"state": "REMEDIATED"}, force=True)
    else:
        if completed is not None:
            if completed > plan["action_count"]:
                shapes.fail("completed_action_count")
            plan["completed_action_count"] = completed
        if plan["completed_action_count"] != plan["action_count"]:
            raise ApiError("ERR_REMEDIATION_ACTIONS_INCOMPLETE")
        store.mutate(plan, {"completed_action_count": plan["completed_action_count"],
                            "state": "COMPLETED"}, force=True)
    return envelope.object_response(store.serialize(store.PLANS, plan))
