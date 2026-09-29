"""Derived state: computed fields, posture, cascades and recomputation helpers."""

from decimal import Decimal

from db import db, fmt_instant, ordered, parse_instant
from errors import ApiError
from services import calc

# ---- status groupings ------------------------------------------------------- #
OPEN_GAP_STATUSES = ("OPEN", "IN_PROGRESS", "RETEST_FAILED")
UNVALIDATED_SEGMENT_STATUSES = ("DECLARED", "TEST_PLANNED", "FAILED")
FROZEN_ENGAGEMENT_STATUSES = ("REPORTING", "ATTESTED", "SUBMITTED", "REASSESSMENT_PLANNED")
RESTRICTABLE_ENGAGEMENT_STATUSES = ("SCOPING", "FIELDWORK")
UNMET_TEST_STATUSES = ("NOT_IN_PLACE", "NOT_TESTED")
EVIDENCE_TYPE_ORDER = ("DOCUMENT_REVIEW", "INTERVIEW", "OBSERVATION", "SYSTEM_CONFIG")
REQUIRED_EVIDENCE_COVERAGE = ("DOCUMENT_REVIEW", "INTERVIEW", "OBSERVATION")


# ---- collection scans ------------------------------------------------------ #
def _by(collection, field, value):
    return ordered([row for row in collection.values() if row.get(field) == value])


def segments_of(engagement_id):
    return _by(db.network_segments, "engagement_id", engagement_id)


def components_of(engagement_id):
    return _by(db.system_components, "engagement_id", engagement_id)


def plans_of(engagement_id):
    return _by(db.sampling_plans, "engagement_id", engagement_id)


def requirements_of(engagement_id):
    return _by(db.requirement_assessments, "engagement_id", engagement_id)


def remediations_of(engagement_id):
    return _by(db.remediation_items, "engagement_id", engagement_id)


def ccws_of(engagement_id):
    return _by(db.ccws, "engagement_id", engagement_id)


def rocs_of(engagement_id):
    return _by(db.rocs, "engagement_id", engagement_id)


def cycles_of(engagement_id):
    return _by(db.scan_cycles, "engagement_id", engagement_id)


def changes_of(engagement_id):
    return _by(db.change_log_entries, "engagement_id", engagement_id)


def evidence_of_engagement(engagement_id):
    return _by(db.evidence_items, "engagement_id", engagement_id)


def evidence_of_requirement(requirement_id):
    return _by(db.evidence_items, "requirement_assessment_id", requirement_id)


def remediations_of_requirement(requirement_id):
    return _by(db.remediation_items, "requirement_assessment_id", requirement_id)


def ccws_of_requirement(requirement_id):
    return _by(db.ccws, "requirement_assessment_id", requirement_id)


def findings_of_cycle(cycle_id):
    return _by(db.scan_findings, "scan_cycle_id", cycle_id)


def latest_plan(engagement_id):
    plans = plans_of(engagement_id)
    if not plans:
        return None
    return max(plans, key=lambda row: row.get("_seq") or 0)


def active_plan(engagement_id):
    for plan in plans_of(engagement_id):
        if plan.get("status") == "ACTIVE":
            return plan
    return None


# ---- assessor / vendor computed fields ------------------------------------- #
def certification_status(assessor):
    expires = parse_instant(assessor.get("certification_expires_at"))
    if expires is None:
        return "LAPSED"
    return "ACTIVE" if db.now() < expires else "LAPSED"


def lead_engagement_count(assessor_id):
    return len([
        row for row in db.engagements.values()
        if row.get("lead_assessor_id") == assessor_id
        and row.get("status") != "REASSESSMENT_PLANNED"
    ])


def effective_approval(vendor):
    if vendor.get("approval_status") == "REVOKED":
        return "REVOKED"
    expires = parse_instant(vendor.get("approval_expires_at"))
    if expires is None or db.now() >= expires:
        return "EXPIRED"
    return "APPROVED"


# ---- engagement computed fields ------------------------------------------- #
def open_gap_count(engagement_id):
    return len([row for row in remediations_of(engagement_id)
                if row.get("status") in OPEN_GAP_STATUSES])


def unvalidated_segment_count(engagement_id):
    return len([row for row in segments_of(engagement_id)
                if row.get("segmentation_status") in UNVALIDATED_SEGMENT_STATUSES])


def active_plan_stale(engagement_id):
    plan = latest_plan(engagement_id)
    return bool(plan is not None and plan.get("status") == "STALE")


def partition_counts(engagement_id):
    counts = {"CDE": 0, "CONNECTED": 0, "OUT_OF_SCOPE": 0}
    for component in components_of(engagement_id):
        scope_class = component.get("scope_class")
        if scope_class in counts:
            counts[scope_class] += 1
    return {
        "cde_component_count": counts["CDE"],
        "connected_component_count": counts["CONNECTED"],
        "out_of_scope_component_count": counts["OUT_OF_SCOPE"],
        "in_scope_component_count": counts["CDE"] + counts["CONNECTED"],
        "total_component_count": counts["CDE"] + counts["CONNECTED"] + counts["OUT_OF_SCOPE"],
    }


def accepted_ccw_count(engagement_id):
    return len([row for row in ccws_of(engagement_id) if row.get("status") == "ACCEPTED"])


def scope_affecting_change_count(engagement_id):
    return len([row for row in changes_of(engagement_id)
                if row.get("triggers_reassessment") is True])


def reassessment_required(engagement_id):
    return scope_affecting_change_count(engagement_id) >= calc.SCOPE_CHANGE_THRESHOLD


def compliance_projection(engagement_id):
    requirements = requirements_of(engagement_id)
    applicable = [row for row in requirements if row.get("applicability") == "APPLICABLE"]
    denominator = len(applicable)
    as_found_num = len([
        row for row in applicable
        if row.get("test_status") == "IN_PLACE" and row.get("remediation_status") == "NONE"
    ])
    as_attested_num = len([
        row for row in applicable
        if row.get("test_status") in ("IN_PLACE", "IN_PLACE_WITH_CCW")
    ])
    as_found = calc.percentage(as_found_num, denominator)
    as_attested = calc.percentage(as_attested_num, denominator)
    return {
        "applicable_requirement_count": denominator,
        "in_place_count": len([r for r in applicable if r.get("test_status") == "IN_PLACE"]),
        "ccw_covered_count": len([r for r in applicable
                                  if r.get("test_status") == "IN_PLACE_WITH_CCW"]),
        "not_in_place_count": len([r for r in applicable
                                   if r.get("test_status") in UNMET_TEST_STATUSES]),
        "as_found_compliance_percentage": as_found,
        "as_attested_compliance_percentage": as_attested,
        "compliance_result": "COMPLIANT" if as_attested == Decimal("100.00") else "NON_COMPLIANT",
    }


def unmet_requirement_count(engagement_id):
    return len([row for row in requirements_of(engagement_id)
                if row.get("test_status") in UNMET_TEST_STATUSES])


def quarterly_scan_compliant(engagement_id):
    now = db.now()
    for cycle in cycles_of(engagement_id):
        if cycle.get("status") != "PASSING":
            continue
        start = cycle.get("_window_start")
        end = cycle.get("_window_end")
        if start is not None and end is not None and start <= now < end:
            return True
    return False


# ---- posture --------------------------------------------------------------- #
def posture(engagement):
    engagement_id = engagement["id"]
    if engagement.get("status") in FROZEN_ENGAGEMENT_STATUSES:
        return "FROZEN"
    if engagement.get("status") in RESTRICTABLE_ENGAGEMENT_STATUSES:
        if (open_gap_count(engagement_id) > 0
                or unvalidated_segment_count(engagement_id) > 0
                or active_plan_stale(engagement_id)):
            return "RESTRICTED"
    return "OPEN"


def guard_frozen(engagement):
    if posture(engagement) == "FROZEN":
        raise ApiError("ERR_ENGAGEMENT_FROZEN")


def guard_restricted(engagement):
    if posture(engagement) == "RESTRICTED":
        raise ApiError("ERR_ENGAGEMENT_RESTRICTED")


# ---- segment forest -------------------------------------------------------- #
def ancestor_chain(segment):
    """The segment itself followed by its ancestors, walking parent links up."""
    chain = []
    seen = set()
    cursor = segment
    while cursor is not None and cursor["id"] not in seen:
        chain.append(cursor)
        seen.add(cursor["id"])
        parent_id = cursor.get("parent_segment_id")
        cursor = db.network_segments.get(parent_id) if parent_id else None
    return chain


def descendant_closure(segment):
    """Every descendant of `segment`, excluding the segment itself."""
    engagement_id = segment.get("engagement_id")
    children_by_parent = {}
    for row in segments_of(engagement_id):
        children_by_parent.setdefault(row.get("parent_segment_id"), []).append(row)
    closure = []
    frontier = list(children_by_parent.get(segment["id"], []))
    seen = set()
    while frontier:
        current = frontier.pop(0)
        if current["id"] in seen:
            continue
        seen.add(current["id"])
        closure.append(current)
        frontier.extend(children_by_parent.get(current["id"], []))
    return closure


def effective_class_for(segment):
    """CDE whenever this zone or an ancestor is currently expanded by a failure.

    The marker is scope_expanded_by_failure rather than the FAILED status itself:
    a re-planned zone keeps its subtree in the CDE until a PASS verdict clears it.
    """
    for node in ancestor_chain(segment):
        if node.get("scope_expanded_by_failure") is True:
            return "CDE"
    return segment.get("segment_class")


def recompute_scope_partition(engagement_id):
    """Re-derive every zone's effective_class and every component's scope_class."""
    for segment in segments_of(engagement_id):
        wanted = effective_class_for(segment)
        if segment.get("effective_class") != wanted:
            segment["effective_class"] = wanted
            db.touch(segment)
    for component in components_of(engagement_id):
        segment = db.network_segments.get(component.get("segment_id"))
        if segment is None:
            continue
        wanted = segment.get("effective_class")
        if component.get("scope_class") != wanted:
            component["scope_class"] = wanted
            db.touch(component)


def mark_latest_plan_stale(engagement_id):
    """A scope shift invalidates the engagement's most recently created plan."""
    plan = latest_plan(engagement_id)
    if plan is not None and plan.get("status") == "ACTIVE":
        plan["status"] = "STALE"
        db.touch(plan)
        return True
    return False


# ---- fee ------------------------------------------------------------------- #
def plan_sample_sizes(engagement_id):
    plan = latest_plan(engagement_id)
    if plan is None:
        return 0, 0
    return int(plan.get("component_sample_size") or 0), int(plan.get("facility_sample_size") or 0)


def projected_fee(engagement, component_sample_size=None, facility_sample_size=None,
                  ccw_count=None, merchant_level=None):
    engagement_id = engagement["id"]
    if component_sample_size is None or facility_sample_size is None:
        component_sample_size, facility_sample_size = plan_sample_sizes(engagement_id)
    if ccw_count is None:
        ccw_count = accepted_ccw_count(engagement_id)
    level = merchant_level if merchant_level is not None else engagement.get("merchant_level")
    return calc.assessment_fee(level, component_sample_size, facility_sample_size, ccw_count)


def enforce_budget(engagement, total, budget=None):
    ceiling = budget if budget is not None else calc.dec(engagement.get("approved_budget_amount"))
    if total > calc.money(ceiling):
        raise ApiError("ERR_ASSESSMENT_BUDGET_EXCEEDED")


def store_fee(engagement, hours, total):
    engagement["estimated_hours"] = int(hours)
    engagement["assessment_fee_total"] = calc.money(total)


# ---- evidence derivation --------------------------------------------------- #
def refresh_evidence_derivation(requirement):
    items = evidence_of_requirement(requirement["id"])
    requirement["evidence_item_count"] = len(items)
    coverage = [
        evidence_type for evidence_type in EVIDENCE_TYPE_ORDER
        if any(item.get("evidence_type") == evidence_type
               and item.get("sufficiency") == "SUFFICIENT" for item in items)
    ]
    requirement["evidence_type_coverage"] = coverage
    enough = len(items) >= int(requirement.get("testing_procedure_count") or 0)
    covered = all(kind in coverage for kind in REQUIRED_EVIDENCE_COVERAGE)
    requirement["evidence_completeness"] = bool(enough and covered)


# ---- scan ledger ----------------------------------------------------------- #
def refresh_scan_ledger(cycle):
    findings = findings_of_cycle(cycle["id"])
    high = [row for row in findings if row.get("severity_class") == "HIGH_OR_ABOVE"]
    accepted = [row for row in high if row.get("dispute_status") == "ACCEPTED_FALSE_POSITIVE"]
    cycle["raw_high_finding_count"] = len(high)
    cycle["accepted_false_positive_count"] = len(accepted)
    cycle["effective_high_finding_count"] = len(high) - len(accepted)
    cycle["open_dispute_count"] = len([row for row in findings
                                      if row.get("dispute_status") == "DISPUTED"])


# ---- remediation minting --------------------------------------------------- #
GAP_TRIGGER_TEXT = {
    "REQUIREMENT_CONCLUSION": "concluded NOT_IN_PLACE during fieldwork",
    "REQUIREMENT_REOPEN": "reopened after an in-place conclusion",
    "SCAN_FINDING_REJECTED": "affected by a rejected false-positive dispute",
}


def mint_remediation_item(engagement, requirement, source, source_scan_finding_id=None):
    row = {
        "engagement_id": engagement["id"],
        "requirement_assessment_id": requirement["id"],
        "source": source,
        "source_scan_finding_id": source_scan_finding_id,
        "gap_description": "Requirement %s %s." % (
            requirement.get("requirement_ref"), GAP_TRIGGER_TEXT.get(source, "requires remediation")),
        "severity": calc.severity_for_risk_points(requirement.get("risk_points")),
        "status": "OPEN",
        "owner_reference": None,
        "due_date": None,
        "retest_count": 0,
        "closed_at": None,
    }
    db.stamp_new(row)
    db.remediation_items[row["id"]] = row
    return row


def now_iso():
    return fmt_instant(db.now())
