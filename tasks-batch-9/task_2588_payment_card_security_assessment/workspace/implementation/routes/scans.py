"""Quarterly external scanning: cycles, findings, disputes and the change log."""

from datetime import timedelta

from flask import Blueprint

import middleware as mw
from db import db, fmt_day, fmt_like, ordered
from errors import ApiError
from response import collection, single
from services import calc, derive, serialize

bp = Blueprint("scans", __name__)

DISPUTE_DECISIONS = ("ACCEPT", "REJECT")
CHANGE_TYPES = ("COMPONENT_ADDED_TO_CDE", "SEGMENT_RECLASSIFIED", "THIRD_PARTY_ADDED",
                "APPLICATION_UPDATED", "STAFF_CHANGE")
SCAN_REVERT_REQUIREMENT_REF = "11.3.1"


# --------------------------------------------------------------------------- #
# scan cycles
# --------------------------------------------------------------------------- #
@bp.post("/engagements/<engagement_id>/scan-cycles")
def schedule_scan_cycle(engagement_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    quarter_label = mw.v_str(body, "quarter_label", allow_empty=False)
    asv_vendor_id = mw.v_id_ref(body, "asv_vendor_id")
    window_raw, window_start = mw.v_instant(body, "window_start")

    engagement = mw.fetch(db.engagements, engagement_id, "ERR_ENGAGEMENT_NOT_FOUND")
    vendor = mw.fetch(db.asv_vendors, asv_vendor_id, "ERR_ASV_VENDOR_NOT_FOUND")
    mw.require_lead(engagement, user_id)

    if derive.effective_approval(vendor) != "APPROVED":
        raise ApiError("ERR_ASV_NOT_APPROVED")

    window_end = window_start + timedelta(days=calc.SCAN_WINDOW_DAYS)
    for existing in derive.cycles_of(engagement_id):
        other_start = existing.get("_window_start")
        other_end = existing.get("_window_end")
        if other_start is None or other_end is None:
            continue
        # Half-open windows: adjacency at the exclusive end instant is allowed.
        if window_start < other_end and other_start < window_end:
            raise ApiError("ERR_SCAN_WINDOW_OVERLAP")

    for existing in derive.cycles_of(engagement_id):
        if existing.get("quarter_label") == quarter_label:
            raise ApiError("ERR_DUPLICATE_QUARTER_LABEL")

    row = {
        "engagement_id": engagement_id,
        "asv_vendor_id": asv_vendor_id,
        "quarter_label": quarter_label,
        "window_start": window_raw,
        "window_end": fmt_like(window_end, window_raw),
        "_window_start": window_start,
        "_window_end": window_end,
        "status": "SCHEDULED",
        "raw_high_finding_count": 0,
        "accepted_false_positive_count": 0,
        "effective_high_finding_count": 0,
        "open_dispute_count": 0,
        "scan_completed_at": None,
        "attestation_of_scan_compliance": False,
    }
    db.stamp_new(row)
    db.scan_cycles[row["id"]] = row
    return single(serialize.scan_cycle(row), 201)


@bp.get("/scan-cycles")
def list_scan_cycles():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    payload = [serialize.scan_cycle(row) for row in ordered(db.scan_cycles.values())]
    payload = mw.apply_filters(payload, {
        "engagement_id": ("engagement_id", "str"),
        "asv_vendor_id": ("asv_vendor_id", "str"),
        "status": ("status", "str"),
        "quarter_label": ("quarter_label", "str"),
    })
    return collection(mw.page(payload, limit, offset), limit, offset, len(payload))


@bp.get("/scan-cycles/<row_id>")
def get_scan_cycle(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.scan_cycles, row_id, "ERR_SCAN_CYCLE_NOT_FOUND")
    return single(serialize.scan_cycle(row))


@bp.post("/scan-cycles/<row_id>/complete")
def complete_scan_cycle(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_VENDOR,))
    cycle = mw.fetch(db.scan_cycles, row_id, "ERR_SCAN_CYCLE_NOT_FOUND")
    engagement = db.engagements.get(cycle.get("engagement_id"))
    mw.require_cycle_vendor(cycle, user_id)

    if cycle.get("status") != "SCHEDULED":
        raise ApiError("ERR_INVALID_SCAN_CYCLE_STATE")

    derive.refresh_scan_ledger(cycle)
    cycle["status"] = "PASSING" if cycle["effective_high_finding_count"] == 0 else "FAILING"
    cycle["scan_completed_at"] = db.now_iso()
    cycle["attestation_of_scan_compliance"] = cycle["status"] == "PASSING"
    db.touch(cycle)
    db.touch(engagement)
    return single(serialize.scan_cycle(cycle))


# --------------------------------------------------------------------------- #
# findings
# --------------------------------------------------------------------------- #
@bp.post("/scan-cycles/<cycle_id>/findings")
def publish_finding(cycle_id):
    user_id, _role = mw.authenticate((mw.ROLE_VENDOR,))
    body = mw.json_body()
    plugin_reference = mw.v_str(body, "plugin_reference", allow_empty=False)
    cvss_score = mw.v_number(body, "cvss_score", minimum=0, maximum=10)
    component_id = mw.v_id_ref(body, "component_id")

    cycle = mw.fetch(db.scan_cycles, cycle_id, "ERR_SCAN_CYCLE_NOT_FOUND")
    component = mw.fetch(db.system_components, component_id, "ERR_COMPONENT_NOT_FOUND")
    mw.require_cycle_vendor(cycle, user_id)

    if component.get("engagement_id") != cycle.get("engagement_id"):
        raise ApiError("ERR_CROSS_ENGAGEMENT_REFERENCE")
    if cycle.get("status") != "SCHEDULED":
        raise ApiError("ERR_INVALID_SCAN_CYCLE_STATE")

    row = {
        "scan_cycle_id": cycle_id,
        "component_id": component_id,
        "plugin_reference": plugin_reference,
        "cvss_score": calc.quant(cvss_score, 1),
        "severity_class": calc.severity_class_for_cvss(cvss_score),
        "dispute_status": "NONE",
        "dispute_rationale": None,
        "decision_note": None,
        "decided_at": None,
    }
    db.stamp_new(row)
    db.scan_findings[row["id"]] = row
    derive.refresh_scan_ledger(cycle)
    return single(serialize.scan_finding(row), 201)


@bp.get("/scan-findings")
def list_scan_findings():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    payload = [serialize.scan_finding(row) for row in ordered(db.scan_findings.values())]
    payload = mw.apply_filters(payload, {
        "scan_cycle_id": ("scan_cycle_id", "str"),
        "component_id": ("component_id", "str"),
        "dispute_status": ("dispute_status", "str"),
        "severity_class": ("severity_class", "str"),
    })
    return collection(mw.page(payload, limit, offset), limit, offset, len(payload))


@bp.get("/scan-findings/<row_id>")
def get_scan_finding(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.scan_findings, row_id, "ERR_SCAN_FINDING_NOT_FOUND")
    return single(serialize.scan_finding(row))


# --------------------------------------------------------------------------- #
# disputes
# --------------------------------------------------------------------------- #
@bp.post("/scan-findings/<row_id>/dispute")
def dispute_finding(row_id):
    mw.authenticate((mw.ROLE_LEAD, mw.ROLE_CLIENT))
    body = mw.json_body()
    dispute_rationale = mw.v_str(body, "dispute_rationale", allow_empty=False)

    finding = mw.fetch(db.scan_findings, row_id, "ERR_SCAN_FINDING_NOT_FOUND")
    cycle = db.scan_cycles.get(finding.get("scan_cycle_id"))

    if finding.get("dispute_status") != "NONE":
        raise ApiError("ERR_INVALID_FINDING_DISPUTE_STATE")
    if cycle.get("status") not in ("FAILING", "DISPUTE_OPEN"):
        raise ApiError("ERR_INVALID_SCAN_CYCLE_STATE")
    if finding.get("severity_class") != "HIGH_OR_ABOVE":
        raise ApiError("ERR_FINDING_NOT_HIGH_SEVERITY")

    finding["dispute_status"] = "DISPUTED"
    finding["dispute_rationale"] = dispute_rationale
    db.touch(finding)

    derive.refresh_scan_ledger(cycle)
    if cycle.get("status") == "FAILING":
        cycle["status"] = "DISPUTE_OPEN"
    db.touch(cycle)
    return single(serialize.scan_finding(finding))


@bp.post("/scan-findings/<row_id>/dispute-decision")
def decide_dispute(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_VENDOR,))
    body = mw.json_body()
    decision = mw.v_enum(body, "decision", DISPUTE_DECISIONS)
    decision_note = mw.v_str(body, "decision_note", allow_empty=False)

    finding = mw.fetch(db.scan_findings, row_id, "ERR_SCAN_FINDING_NOT_FOUND")
    cycle = db.scan_cycles.get(finding.get("scan_cycle_id"))
    engagement = db.engagements.get(cycle.get("engagement_id"))
    mw.require_cycle_vendor(cycle, user_id)

    if finding.get("dispute_status") != "DISPUTED":
        raise ApiError("ERR_INVALID_FINDING_DISPUTE_STATE")

    finding["dispute_status"] = ("ACCEPTED_FALSE_POSITIVE" if decision == "ACCEPT"
                                else "REJECTED")
    finding["decision_note"] = decision_note
    finding["decided_at"] = db.now_iso()
    db.touch(finding)

    derive.refresh_scan_ledger(cycle)
    settled = cycle["open_dispute_count"] == 0
    if decision == "ACCEPT":
        if settled and cycle["effective_high_finding_count"] == 0 \
                and cycle.get("status") == "DISPUTE_OPEN":
            cycle["status"] = "PASSING"
            cycle["attestation_of_scan_compliance"] = True
        db.touch(cycle)
        db.touch(engagement)
        return single(serialize.scan_finding(finding))

    # --- cascade E ------------------------------------------------------------
    if settled and cycle["effective_high_finding_count"] >= 1 \
            and cycle.get("status") == "DISPUTE_OPEN":
        cycle["status"] = "FAILING"
        cycle["attestation_of_scan_compliance"] = False
        for requirement in derive.requirements_of(engagement["id"]):
            if requirement.get("requirement_ref") != SCAN_REVERT_REQUIREMENT_REF:
                continue
            if requirement.get("test_status") != "IN_PLACE":
                continue
            requirement["test_status"] = "IN_TESTING"
            requirement["remediation_status"] = "GAP_OPEN"
            db.touch(requirement)
            derive.mint_remediation_item(engagement, requirement, "SCAN_FINDING_REJECTED",
                                         source_scan_finding_id=finding["id"])
    db.touch(cycle)
    db.touch(engagement)
    return single(serialize.scan_finding(finding))


# --------------------------------------------------------------------------- #
# change log
# --------------------------------------------------------------------------- #
@bp.post("/engagements/<engagement_id>/change-log-entries")
def record_change(engagement_id):
    mw.authenticate((mw.ROLE_LEAD, mw.ROLE_ASSESSOR, mw.ROLE_CLIENT))
    body = mw.json_body()
    change_type = mw.v_enum(body, "change_type", CHANGE_TYPES)
    description = mw.v_str(body, "description", allow_empty=False)
    affects_scope = mw.v_bool(body, "affects_scope")
    component_id = mw.v_id_ref(body, "component_id", required=False)

    engagement = mw.fetch(db.engagements, engagement_id, "ERR_ENGAGEMENT_NOT_FOUND")
    if component_id is not None:
        component = mw.fetch(db.system_components, component_id, "ERR_COMPONENT_NOT_FOUND")
        if component.get("engagement_id") != engagement_id:
            raise ApiError("ERR_CROSS_ENGAGEMENT_REFERENCE")

    triggers = bool(affects_scope and change_type in calc.SCOPE_AFFECTING_CHANGE_TYPES)
    row = {
        "engagement_id": engagement_id,
        "component_id": component_id,
        "change_type": change_type,
        "description": description,
        "affects_scope": affects_scope,
        "triggers_reassessment": triggers,
        "recorded_at": db.now_iso(),
    }
    db.stamp_new(row, versioned=False)
    db.change_log_entries[row["id"]] = row

    if triggers and derive.scope_affecting_change_count(engagement_id) == \
            calc.SCOPE_CHANGE_THRESHOLD:
        # The moment reassessment_required first flips true the due date is pulled
        # forward, overwriting any 365-day date a submission had set.
        engagement["reassessment_due_date"] = fmt_day(
            db.today() + timedelta(days=calc.ACCELERATED_REASSESSMENT_DAYS))
    return single(serialize.change_log_entry(row), 201)


@bp.get("/change-log-entries")
def list_changes():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    payload = [serialize.change_log_entry(row)
               for row in ordered(db.change_log_entries.values())]
    payload = mw.apply_filters(payload, {
        "engagement_id": ("engagement_id", "str"),
        "component_id": ("component_id", "str"),
        "change_type": ("change_type", "str"),
        "affects_scope": ("affects_scope", "bool"),
        "triggers_reassessment": ("triggers_reassessment", "bool"),
    })
    return collection(mw.page(payload, limit, offset), limit, offset, len(payload))


@bp.get("/change-log-entries/<row_id>")
def get_change(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.change_log_entries, row_id, "ERR_CHANGE_LOG_ENTRY_NOT_FOUND")
    return single(serialize.change_log_entry(row))
