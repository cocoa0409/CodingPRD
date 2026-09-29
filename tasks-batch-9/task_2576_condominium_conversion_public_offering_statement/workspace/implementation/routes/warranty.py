"""Common-element warranty claims: the inclusive expiry boundary, the closed
remediation window with its cooldown, and the project-wide depth cap (PRD 3.9).
"""

from flask import Blueprint, request

import clock
import envelope
import serializers
import store
import validation as v
from errors import ApiError
from services import projects as project_service, warranty as warranty_service

bp = Blueprint("warranty", __name__)

FILE_ROLES = ["ConverterSponsor", "Purchaser"]
PROJECT_LIST_ROLES = ["ConverterSponsor", "StateRegulator",
                      "LenderUnderwriter", "Purchaser", "PlatformAdmin"]
READ_ROLES = ["ConverterSponsor", "StateRegulator", "LenderUnderwriter",
              "Purchaser", "LicensedEngineer", "PlatformAdmin"]
TRIAGE_ROLES = ["LicensedEngineer", "ConverterSponsor"]
SPONSOR = ["ConverterSponsor"]
COMPLETION_ROLES = ["ConverterSponsor", "LicensedEngineer"]
REOPEN_ROLES = ["ConverterSponsor", "Purchaser"]
SUMMARY_ROLES = ["ConverterSponsor", "StateRegulator", "LenderUnderwriter",
                 "PlatformAdmin"]


def _require_unexpired(claim):
    """Priority 37: the expiry comparison is inclusive."""
    if clock.now() > claim["warranty_expires_at"]:
        raise ApiError("ERR_WARRANTY_PERIOD_EXPIRED")


@bp.post("/conversion-projects/<project_id>/warranty-claims")
def file_claim(project_id):
    v.authorize(FILE_ROLES)
    project = v.get_project(project_id)
    body = v.raw_body()
    component = v.body_ref(body, "major_component_id", v.get_component)
    unit = v.body_ref(body, "reported_by_unit_id", v.get_unit)
    v.require_scope(project["id"], unit)
    if component is not None:
        report = store.engineering_reports.get(
            component["engineering_report_id"])
        v.require_scope(project["id"], report)
    fields = v.parse([
        v.field("major_component_id", "id"),
        v.field("reported_by_unit_id", "id"),
        v.field("defect_description", "string", max_len=500),
        v.field("claimed_cost_cents", "integer", minimum=0),
    ])
    v.gate_not_frozen(project)
    package = store.project_package(project["id"])
    if (package is None or package["status"] != "RECORDED"
            or project["warranty_start_at"] is None):
        raise ApiError("ERR_DECLARATION_NOT_RECORDED")
    expires_at = warranty_service.warranty_expiry(project, component)
    if clock.now() > expires_at:
        raise ApiError("ERR_WARRANTY_PERIOD_EXPIRED")
    claim = store.new_record(store.warranty_claims, {
        "_type": "WarrantyClaim",
        "conversion_project_id": project["id"],
        "major_component_id": component["id"],
        "reported_by_unit_id": unit["id"],
        "defect_description": fields["defect_description"],
        "claimed_cost_cents": fields["claimed_cost_cents"],
        "reported_at": clock.now(),
        "warranty_expires_at": expires_at,
        "status": "SUBMITTED",
        "triage_outcome": "PENDING",
        "accrued_charge_cents": 0,
        "remediation_start_at": None,
        "remediation_end_at": None,
        "reopen_count": 0,
        "triage_note": None,
        "completion_note": None,
        "reopen_reason": None,
    })
    project_service.sync(project)
    return envelope.object_response(serializers.dump(claim), 201)


@bp.get("/conversion-projects/<project_id>/warranty-claims")
def list_project_claims(project_id):
    v.authorize(PROJECT_LIST_ROLES)
    project = v.get_project(project_id)
    limit, offset = v.pagination()
    records = [
        c for c in store.project_claims(project["id"])
        if v.matches(c, status=v.filter_value("status"),
                     triage_outcome=v.filter_value("triage_outcome"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/warranty-claims")
def list_claims():
    v.authorize(READ_ROLES)
    limit, offset = v.pagination()
    records = [
        c for c in store.ordered(store.warranty_claims.values())
        if v.matches(
            c,
            conversion_project_id=v.filter_value("conversion_project_id"),
            major_component_id=v.filter_value("major_component_id"),
            reported_by_unit_id=v.filter_value("reported_by_unit_id"),
            status=v.filter_value("status"),
            triage_outcome=v.filter_value("triage_outcome"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/warranty-claims/<claim_id>")
def get_claim(claim_id):
    v.authorize(READ_ROLES)
    claim = v.get_claim(claim_id)
    return envelope.object_response(serializers.dump(claim), 200)


@bp.post("/warranty-claims/<claim_id>/triage")
def triage_claim(claim_id):
    v.authorize(TRIAGE_ROLES)
    claim = v.get_claim(claim_id)
    project = v.get_project(claim["conversion_project_id"])
    body = v.parse([
        v.field("decision", "enum", values=["ADMIT", "DENY"]),
        v.field("triage_note", "string", required=False, default=None,
                max_len=500),
    ])
    v.gate_not_frozen(project)
    component = v.get_component(claim["major_component_id"])
    if body["decision"] == "DENY":
        # The denial branch applies no expiry test and no unit test at all.
        v.require_state(claim, "status", ("SUBMITTED",))
        claim["status"] = "DENIED"
        claim["triage_outcome"] = "DENIED"
    else:
        v.require_state(claim, "status", ("SUBMITTED", "REOPENED"))
        _require_unexpired(claim)
        unit = store.units.get(claim["reported_by_unit_id"])
        if unit is None or unit["sale_status"] != "SOLD":
            # Only an actual owner holds a warranty.
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if claim["status"] == "REOPENED":
            # The reopen uplift is applied before the cap and only the delta
            # reaches the project ledger.
            claim["accrued_charge_cents"] = warranty_service.reopen_charge_cents(
                claim, component)
        else:
            claim["accrued_charge_cents"] = (
                warranty_service.admission_charge_cents(claim, component))
        claim["status"] = "TRIAGED_ADMISSIBLE"
        claim["triage_outcome"] = "ADMISSIBLE"
    if body["triage_note"] is not None:
        claim["triage_note"] = body["triage_note"]
    store.touch(claim)
    project_service.sync(project)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(claim), 200)


@bp.post("/warranty-claims/<claim_id>/remediation-schedule")
def schedule_remediation(claim_id):
    v.authorize(SPONSOR)
    claim = v.get_claim(claim_id)
    project = v.get_project(claim["conversion_project_id"])
    body = v.parse([
        v.field("remediation_start_at", "datetime"),
        v.field("remediation_end_at", "datetime"),
    ])
    v.gate_not_frozen(project)
    v.require_state(claim, "status", ("TRIAGED_ADMISSIBLE",))
    start_at = body["remediation_start_at"]
    end_at = body["remediation_end_at"]
    # A closed interval: a single-instant window is legitimate.
    if end_at < start_at:
        raise ApiError("ERR_REMEDIATION_WINDOW_OVERLAP")
    if warranty_service.component_window_conflict(
            claim, start_at, end_at) is not None:
        raise ApiError("ERR_REMEDIATION_WINDOW_OVERLAP")
    # Only then the project-wide capacity check, which carries no cooldown.
    depth = warranty_service.max_overlap_depth(project["id"], start_at, end_at,
                                               exclude_claim_id=claim["id"])
    if depth > project["max_overlapping_remediations"]:
        raise ApiError("ERR_REMEDIATION_CAPACITY_EXCEEDED")
    claim["status"] = "REMEDIATION_SCHEDULED"
    claim["remediation_start_at"] = start_at
    claim["remediation_end_at"] = end_at
    store.touch(claim)
    return envelope.object_response(serializers.dump(claim), 200)


@bp.post("/warranty-claims/<claim_id>/completion")
def complete_remediation(claim_id):
    v.authorize(COMPLETION_ROLES)
    claim = v.get_claim(claim_id)
    project = v.get_project(claim["conversion_project_id"])
    body = v.parse([v.field("completion_note", "string", required=False,
                            default=None, max_len=500)])
    v.gate_not_frozen(project)
    v.require_state(claim, "status", ("REMEDIATION_SCHEDULED",))
    # The closed window must lie wholly in the past: strictly after the end.
    # Completion at the exact end instant is premature, and the catalogue has
    # no dedicated id for it, so the transition precondition reports.
    if (claim["remediation_end_at"] is None
            or clock.now() <= claim["remediation_end_at"]):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    claim["status"] = "REMEDIATED"
    if body["completion_note"] is not None:
        claim["completion_note"] = body["completion_note"]
    store.touch(claim)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(claim), 200)


@bp.post("/warranty-claims/<claim_id>/reopening")
def reopen_claim(claim_id):
    v.authorize(REOPEN_ROLES)
    claim = v.get_claim(claim_id)
    project = v.get_project(claim["conversion_project_id"])
    body = v.parse([v.field("reopen_reason", "string", required=False,
                            default=None, max_len=500)])
    v.gate_not_frozen(project)
    v.require_state(claim, "status", ("REMEDIATED",))
    _require_unexpired(claim)
    if claim["reopen_count"] >= warranty_service.MAX_REOPENS:
        raise ApiError("ERR_CLAIM_REOPEN_LIMIT_REACHED")
    claim["status"] = "REOPENED"
    claim["reopen_count"] += 1
    # Clearing both bounds releases the component's window occupation.
    claim["remediation_start_at"] = None
    claim["remediation_end_at"] = None
    if body["reopen_reason"] is not None:
        claim["reopen_reason"] = body["reopen_reason"]
    store.touch(claim)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(claim), 200)


@bp.get("/conversion-projects/<project_id>/warranty-summary")
def warranty_summary(project_id):
    v.authorize(SUMMARY_ROLES)
    project = v.get_project(project_id)
    start_raw = request.args.get("window_start_at")
    end_raw = request.args.get("window_end_at")
    start_at = clock.parse_instant(start_raw) if start_raw else None
    end_at = clock.parse_instant(end_raw) if end_raw else None
    if (start_raw and start_at is None) or (end_raw and end_at is None):
        raise ApiError("ERR_INVALID_REQUEST")
    project_service.sync(project)
    payload = serializers.dump(project)
    payload["claim_charges"] = [
        {"warranty_claim_id": claim["id"],
         "major_component_id": claim["major_component_id"],
         "status": claim["status"],
         "accrued_charge_cents": claim["accrued_charge_cents"]}
        for claim in store.project_claims(project["id"])]
    depth = 0
    if start_at is not None and end_at is not None and end_at >= start_at:
        depth = warranty_service.max_overlap_depth(
            project["id"], start_at, end_at, include_requested=False)
    payload["max_remediation_overlap_depth"] = depth
    payload["max_overlapping_remediations"] = (
        project["max_overlapping_remediations"])
    return envelope.object_response(payload, 200)
