"""Exposure incidents and private-right-of-action exposure assessments."""

from flask import Blueprint

import constants as K
import derive
import serialize
from authz import actor, require_role, require_role_for_target
from calc import incident_notification_deadline_and_cost, pra_exposure_estimate
from common import respond, respond_list
from errors import fail
from store import db, new_record, touch
from validate import (
    body,
    find_assessment,
    find_asset,
    find_incident,
    find_jurisdiction,
    find_program,
    opt_str,
    query_enum,
    query_str,
    req_enum,
    req_int,
    req_str,
    req_str_array,
)

bp = Blueprint("incidents", __name__)

INCIDENT_READ_ROLES = ("SystemOperator", "PrivacyOfficer", "ComplianceApprover", "VendorManager")
ASSESSMENT_READ_ROLES = ("SystemOperator", "PrivacyOfficer", "ComplianceApprover")

NOTIFICATION_GRANTS = {
    "ASSESSED": ("PrivacyOfficer",),
    "NOTIFIED": ("PrivacyOfficer",),
    "EXEMPT": ("ComplianceApprover",),
    "PENDING": (),
}

ASSESSMENT_GRANTS = {
    "FINAL": ("ComplianceApprover",),
    "VOID": ("ComplianceApprover", "PrivacyOfficer"),
    "DRAFT": (),
}


# --- IncidentCase -----------------------------------------------------------

@bp.post("/incidents")
def create_incident():
    _, role = actor()
    require_role(role, ("PrivacyOfficer",))
    data = body()
    program_id = req_str(data, "program_id")
    affected_asset_ids = req_str_array(data, "affected_asset_ids", non_empty=True)
    exposure_vector = req_enum(data, "exposure_vector", K.EXPOSURE_VECTORS)
    description = req_str(data, "description")
    exposed_subject_count = req_int(data, "exposed_subject_count", minimum=1)
    translation_locale_count = req_int(data, "translation_locale_count", minimum=0)

    find_program(program_id)
    for asset_id in affected_asset_ids:
        asset = find_asset(asset_id)
        if asset["program_id"] != program_id:
            fail(
                "ERR_ASSET_NOT_FOUND",
                "Collection point %s does not belong to this program." % asset_id,
            )

    rec = new_record()
    rec.update(
        {
            "program_id": program_id,
            "affected_asset_ids": list(affected_asset_ids),
            "exposure_vector": exposure_vector,
            "description": description,
            "discovered_at": db.clock,
            "exposed_subject_count": exposed_subject_count,
            "heightened_tier": None,
            "notification_due_at": None,
            "containment_status": "DETECTED",
            "notification_status": "PENDING",
            "translation_locale_count": translation_locale_count,
            "gross_notice_cents": 0,
            "regulator_surcharge_cents": 0,
            "vendor_indemnity_credit_cents": 0,
            "net_incident_cost_cents": 0,
            "notified_subject_count": 0,
            "notified_at": None,
            "late_notification": False,
            "exemption_basis": None,
            "containment_note": None,
        }
    )
    db.incidents[rec["id"]] = rec
    return respond(serialize.incident, rec, 201)


@bp.post("/incidents/<incident_id>/containment-transitions")
def containment_transition(incident_id):
    _, role = actor()
    require_role(role, ("PrivacyOfficer",))
    raw = body()
    to_status = req_enum(raw, "to_status", K.CONTAINMENT_STATUSES)
    containment_note = None
    if to_status == "CONTAINED":
        containment_note = req_str(raw, "containment_note")

    incident = find_incident(incident_id)
    current = incident["containment_status"]

    edges = {("DETECTED", "CONTAINED"), ("CONTAINED", "REMEDIATED")}
    if (current, to_status) not in edges:
        fail(
            "ERR_INVALID_TRANSITION",
            "Containment cannot move from %s to %s." % (current, to_status),
        )

    if to_status == "CONTAINED":
        incident["containment_status"] = "CONTAINED"
        incident["containment_note"] = containment_note
        touch(incident)
    else:
        # step 13: the guarded join between the two parallel dimensions
        if incident["notification_status"] not in ("NOTIFIED", "EXEMPT"):
            fail(
                "ERR_NOTIFICATION_OUTSTANDING",
                "The notification dimension is still %s." % incident["notification_status"],
            )
        for asset_id in incident["affected_asset_ids"]:
            asset = db.assets.get(asset_id)
            if asset is not None and asset["status"] not in ("GATED", "DECOMMISSIONED"):
                fail(
                    "ERR_ASSET_STILL_ACTIVE",
                    "An exposed collection point is still collecting.",
                )
        incident["containment_status"] = "REMEDIATED"
        touch(incident)

    return respond(serialize.incident, incident)


@bp.post("/incidents/<incident_id>/notification-transitions")
def notification_transition(incident_id):
    _, role = actor()
    raw = body()
    require_role_for_target(
        role,
        raw.get("to_status"),
        K.NOTIFICATION_STATUSES,
        NOTIFICATION_GRANTS,
        ("PrivacyOfficer", "ComplianceApprover"),
    )
    to_status = req_enum(raw, "to_status", K.NOTIFICATION_STATUSES)
    notified_subject_count = None
    exemption_basis = None
    if to_status == "NOTIFIED":
        notified_subject_count = req_int(raw, "notified_subject_count", minimum=0)
    if to_status == "EXEMPT":
        exemption_basis = req_str(raw, "exemption_basis")

    incident = find_incident(incident_id)
    current = incident["notification_status"]

    edges = {("PENDING", "ASSESSED"), ("ASSESSED", "NOTIFIED"), ("ASSESSED", "EXEMPT")}
    if (current, to_status) not in edges:
        fail(
            "ERR_INVALID_TRANSITION",
            "Notification cannot move from %s to %s." % (current, to_status),
        )

    if to_status == "ASSESSED":
        incident.update(incident_notification_deadline_and_cost(incident))
        incident["notification_status"] = "ASSESSED"
        touch(incident)

    elif to_status == "NOTIFIED":
        # step 12
        if notified_subject_count < int(incident["exposed_subject_count"]):
            fail(
                "ERR_NOTIFIED_COUNT_SHORTFALL",
                "notified_subject_count is below the exposed subject count.",
            )
        incident["notified_subject_count"] = notified_subject_count
        incident["notified_at"] = db.clock
        incident["late_notification"] = (
            incident["notification_due_at"] is not None
            and incident["notified_at"] > incident["notification_due_at"]
        )
        incident["notification_status"] = "NOTIFIED"
        touch(incident)

    else:  # EXEMPT
        # step 13
        if incident["heightened_tier"] != "TIER_2":
            fail(
                "ERR_EXEMPTION_NOT_AVAILABLE",
                "A notification exemption is only available at TIER_2.",
            )
        incident["exemption_basis"] = exemption_basis
        incident["notification_status"] = "EXEMPT"
        touch(incident)

    return respond(serialize.incident, incident)


@bp.get("/incidents/<incident_id>")
def read_incident(incident_id):
    _, role = actor()
    require_role(role, INCIDENT_READ_ROLES)
    incident = find_incident(incident_id)
    return respond(serialize.incident, incident)


@bp.get("/incidents")
def list_incidents():
    _, role = actor()
    require_role(role, INCIDENT_READ_ROLES)
    program_id = query_str("program_id")
    containment_status = query_enum("containment_status", K.CONTAINMENT_STATUSES)
    notification_status = query_enum("notification_status", K.NOTIFICATION_STATUSES)
    rows = list(db.incidents.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if containment_status is not None:
        rows = [r for r in rows if r["containment_status"] == containment_status]
    if notification_status is not None:
        rows = [r for r in rows if r["notification_status"] == notification_status]
    return respond_list(rows, serialize.incident)


# --- ExposureAssessment -----------------------------------------------------

@bp.post("/exposure-assessments")
def create_assessment():
    user_id, role = actor()
    require_role(role, ("PrivacyOfficer",))
    data = body()
    program_id = req_str(data, "program_id")
    jurisdiction_id = req_str(data, "jurisdiction_id")
    variant = req_enum(data, "variant", K.ASSESSMENT_VARIANTS)
    expected_jurisdiction_version = req_int(data, "expected_jurisdiction_version")
    incident_id = opt_str(data, "incident_id")

    find_program(program_id)
    juris = find_jurisdiction(jurisdiction_id)
    if incident_id is not None:
        find_incident(incident_id)

    # step 6: stale-read rejection
    if juris["version"] != expected_jurisdiction_version:
        fail(
            "ERR_STALE_JURISDICTION_VERSION",
            "expected_jurisdiction_version does not match the state profile's current version.",
        )

    derive.refresh_all()
    estimate = pra_exposure_estimate(program_id, jurisdiction_id, variant)

    rec = new_record()
    rec.update(
        {
            "program_id": program_id,
            "jurisdiction_id": jurisdiction_id,
            "incident_id": incident_id,
            "variant": variant,
            "status": "DRAFT",
            "created_by_user_id": user_id,
            "finalized_by_user_id": None,
            "void_reason": None,
        }
    )
    rec.update(estimate)
    db.assessments[rec["id"]] = rec
    touch(juris)
    return respond(serialize.assessment, rec, 201)


@bp.post("/exposure-assessments/<assessment_id>/transitions")
def assessment_transition(assessment_id):
    user_id, role = actor()
    raw = body()
    require_role_for_target(
        role,
        raw.get("to_status"),
        K.ASSESSMENT_STATUSES,
        ASSESSMENT_GRANTS,
        ("ComplianceApprover", "PrivacyOfficer"),
    )
    to_status = req_enum(raw, "to_status", K.ASSESSMENT_STATUSES)
    void_reason = None
    if to_status == "VOID":
        void_reason = req_str(raw, "void_reason")

    assessment = find_assessment(assessment_id)
    current = assessment["status"]

    # step 7: separation of duties precedes transition legality
    if to_status == "FINAL" and user_id == assessment["created_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The approver must differ from the user who drafted the assessment.",
        )

    edges = {("DRAFT", "FINAL"), ("FINAL", "VOID"), ("DRAFT", "VOID")}
    if (current, to_status) not in edges:
        fail(
            "ERR_INVALID_TRANSITION",
            "An assessment cannot move from %s to %s." % (current, to_status),
        )

    program = db.programs.get(assessment["program_id"])
    derive.refresh_all()

    if to_status == "FINAL":
        # the estimate is refreshed before it is committed
        assessment.update(
            pra_exposure_estimate(
                assessment["program_id"], assessment["jurisdiction_id"], assessment["variant"]
            )
        )
        # step 13
        for other in db.assessments.values():
            if (
                other["id"] != assessment_id
                and other["program_id"] == assessment["program_id"]
                and other["jurisdiction_id"] == assessment["jurisdiction_id"]
                and other["status"] == "FINAL"
            ):
                fail(
                    "ERR_ASSESSMENT_ALREADY_FINAL",
                    "This state already carries a finalized assessment.",
                )
        # step 14
        carried = int(program["pra_exposure_cents"]) if program is not None else 0
        ceiling = int(program["exposure_ceiling_cents"]) if program is not None else 0
        if carried + int(assessment["exposure_cents"]) > ceiling:
            fail(
                "ERR_EXPOSURE_CAP_EXCEEDED",
                "Finalizing this assessment would exceed the program's exposure ceiling.",
            )

        assessment["status"] = "FINAL"
        assessment["finalized_by_user_id"] = user_id
        touch(assessment)
        if program is not None:
            touch(program)

    elif current == "FINAL":  # FINAL -> VOID, compensating
        assessment["status"] = "VOID"
        assessment["void_reason"] = void_reason
        touch(assessment)
        if program is not None:
            touch(program)

    else:  # DRAFT -> VOID
        assessment["status"] = "VOID"
        assessment["void_reason"] = void_reason
        touch(assessment)

    return respond(serialize.assessment, assessment)


@bp.get("/exposure-assessments/<assessment_id>")
def read_assessment(assessment_id):
    _, role = actor()
    require_role(role, ASSESSMENT_READ_ROLES)
    assessment = find_assessment(assessment_id)
    return respond(serialize.assessment, assessment)


@bp.get("/exposure-assessments")
def list_assessments():
    _, role = actor()
    require_role(role, ASSESSMENT_READ_ROLES)
    program_id = query_str("program_id")
    jurisdiction_id = query_str("jurisdiction_id")
    incident_id = query_str("incident_id")
    status = query_enum("status", K.ASSESSMENT_STATUSES)
    rows = list(db.assessments.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if incident_id is not None:
        rows = [r for r in rows if r["incident_id"] == incident_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond_list(rows, serialize.assessment)
