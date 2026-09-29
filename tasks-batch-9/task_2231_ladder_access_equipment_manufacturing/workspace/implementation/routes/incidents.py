"""FieldIncident and CorrectiveAction endpoints (PRD 3.8)."""

from flask import Blueprint, g

import calc
import cascade
import lookup
import response
import serialize
import store
import validate
from auth import authorize
from errors import fail
from routes._common import paged
from store import db, mark_dirty, now

bp = Blueprint("incidents", __name__)

INCIDENT_READERS = ("ComplianceOfficer", "SafetyDirector", "DesignEngineer", "DesignApprover")
ACTION_READERS = ("DesignEngineer", "DesignApprover", "SafetyDirector", "ComplianceOfficer")


# =========================================================================
# FieldIncident
# =========================================================================
@bp.post("/field-incidents")
@authorize("ComplianceOfficer", "SafetyDirector", "Consumer")
def create_field_incident():
    data = validate.body()

    product = None
    if validate.present(data, "product_id"):
        product = lookup.product(data["product_id"])
    lot = None
    if validate.present(data, "production_lot_id"):
        lot = lookup.production_lot(data["production_lot_id"])
    registration = None
    if validate.present(data, "consumer_registration_id"):
        registration = lookup.consumer_registration(data["consumer_registration_id"])

    validate.req_id(data, "product_id")
    incident_type = validate.req_enum(data, "incident_type", calc.INCIDENT_TYPES)
    injury_severity = validate.req_enum(data, "injury_severity", calc.INJURY_SEVERITIES)
    occurred_at = validate.req_instant(data, "occurred_at")
    narrative = validate.req_str(data, "narrative")
    validate.opt_id(data, "production_lot_id")
    validate.opt_id(data, "consumer_registration_id")

    # step 9
    validate.check_not_future(occurred_at, "occurred_at")

    incident = store.base_record()
    incident.update(
        {
            "product_id": product["id"],
            "production_lot_id": lot["id"] if lot is not None else None,
            "consumer_registration_id": registration["id"] if registration is not None else None,
            "incident_type": incident_type,
            "injury_severity": injury_severity,
            "occurred_at": occurred_at,
            "narrative": narrative,
            "status": "REPORTED",
            "finding": None,
            "root_cause_code": None,
            "requires_capa": False,
            "incident_points": None,
            "closed_at": None,
        }
    )
    db.field_incidents[incident["id"]] = incident
    store.register_new(incident)
    return response.created(incident, serialize.field_incident)


@bp.get("/field-incidents/<incident_id>")
@authorize(*INCIDENT_READERS)
def get_field_incident(incident_id):
    incident = lookup.field_incident(incident_id)
    return response.obj(incident, serialize.field_incident)


@bp.get("/field-incidents")
@authorize(*INCIDENT_READERS)
def list_field_incidents():
    spec = {
        "product_id": "product_id",
        "production_lot_id": "production_lot_id",
        "consumer_registration_id": "consumer_registration_id",
        "status": "status",
        "incident_type": "incident_type",
        "injury_severity": "injury_severity",
    }
    return paged(lookup.rows(db.field_incidents), spec, serialize.field_incident)


@bp.post("/field-incidents/<incident_id>/investigate")
@authorize("SafetyDirector", "ComplianceOfficer")
def investigate_field_incident(incident_id):
    incident = lookup.field_incident(incident_id)

    if incident["status"] != "REPORTED":
        fail("ERR_INCIDENT_STATE_INVALID", "status must be REPORTED to investigate")

    incident["status"] = "UNDER_INVESTIGATION"
    incident["incident_points"] = calc.incident_points(
        incident["injury_severity"], incident["incident_type"]
    )
    mark_dirty(incident)

    product = db.products.get(incident["product_id"])
    if product is not None:
        cascade.recompute_risk_scores(product)
    return response.obj(incident, serialize.field_incident)


@bp.post("/field-incidents/<incident_id>/resolve-investigation")
@authorize("SafetyDirector")
def resolve_investigation(incident_id):
    incident = lookup.field_incident(incident_id)
    data = validate.body()
    finding = validate.req_enum(data, "finding", calc.FINDINGS)
    root_cause_code = validate.opt_enum(data, "root_cause_code", calc.ROOT_CAUSE_CODES)

    # step 19
    if incident["status"] != "UNDER_INVESTIGATION":
        fail("ERR_INCIDENT_STATE_INVALID", "status must be UNDER_INVESTIGATION to resolve")

    # step 53
    if finding == "ROOT_CAUSE_IDENTIFIED" and root_cause_code is None:
        fail("ERR_FINDING_ROOT_CAUSE_MISMATCH", "root_cause_code is required for that finding")
    if finding == "NOT_SUBSTANTIATED" and root_cause_code is not None:
        fail("ERR_FINDING_ROOT_CAUSE_MISMATCH", "root_cause_code must be null for that finding")

    incident["finding"] = finding
    if finding == "NOT_SUBSTANTIATED":
        incident["status"] = "NOT_SUBSTANTIATED"
        incident["closed_at"] = now()
        incident["requires_capa"] = False
    else:
        incident["status"] = "ROOT_CAUSE_IDENTIFIED"
        incident["root_cause_code"] = root_cause_code
        incident["requires_capa"] = True
    mark_dirty(incident)

    product = db.products.get(incident["product_id"])
    if product is not None:
        cascade.recompute_risk_scores(product)
    return response.obj(incident, serialize.field_incident)


# =========================================================================
# CorrectiveAction
# =========================================================================
@bp.post("/corrective-actions")
@authorize("DesignEngineer", "SafetyDirector")
def create_corrective_action():
    data = validate.body()

    incident = None
    if validate.present(data, "field_incident_id"):
        incident = lookup.field_incident(data["field_incident_id"])
    revision = None
    if validate.present(data, "design_revision_id"):
        revision = lookup.design_revision(data["design_revision_id"])
    supersedes = None
    if validate.present(data, "supersedes_action_id"):
        supersedes = lookup.corrective_action(data["supersedes_action_id"])

    validate.req_id(data, "field_incident_id")
    action_summary = validate.req_str(data, "action_summary")
    validate.opt_id(data, "design_revision_id")
    validate.opt_id(data, "supersedes_action_id")
    expected_version = validate.req_int(data, "expected_field_incident_version")

    # step 11 — optimistic concurrency on the parent incident
    if expected_version != incident["version"]:
        fail(
            "ERR_STALE_INCIDENT_VERSION",
            "expected_field_incident_version %s does not match current version %s"
            % (expected_version, incident["version"]),
        )

    # step 19
    if incident["status"] != "ROOT_CAUSE_IDENTIFIED":
        fail("ERR_INCIDENT_STATE_INVALID", "status must be ROOT_CAUSE_IDENTIFIED")

    # step 35
    if supersedes is not None and supersedes["field_incident_id"] != incident["id"]:
        fail("ERR_SUPERSEDE_TARGET_MISMATCH", "superseded action belongs to another incident")

    action = store.base_record()
    action.update(
        {
            "field_incident_id": incident["id"],
            "design_revision_id": revision["id"] if revision is not None else None,
            "supersedes_action_id": supersedes["id"] if supersedes is not None else None,
            "action_summary": action_summary,
            "authored_by_user_id": g.user_id,
            "status": "OPEN",
            "verified_at": None,
            "verified_by_user_id": None,
        }
    )
    db.corrective_actions[action["id"]] = action
    store.register_new(action)

    incident["status"] = "CAPA_OPENED"
    mark_dirty(incident)

    if supersedes is not None and supersedes["status"] == "OPEN":
        supersedes["status"] = "SUPERSEDED"
        mark_dirty(supersedes)

    return response.created(action, serialize.corrective_action)


@bp.get("/corrective-actions/<action_id>")
@authorize(*ACTION_READERS)
def get_corrective_action(action_id):
    action = lookup.corrective_action(action_id)
    return response.obj(action, serialize.corrective_action)


@bp.get("/corrective-actions")
@authorize(*ACTION_READERS)
def list_corrective_actions():
    spec = {
        "field_incident_id": "field_incident_id",
        "design_revision_id": "design_revision_id",
        "supersedes_action_id": "supersedes_action_id",
        "status": "status",
    }
    return paged(lookup.rows(db.corrective_actions), spec, serialize.corrective_action)


@bp.post("/corrective-actions/<action_id>/verify")
@authorize("DesignApprover")
def verify_corrective_action(action_id):
    action = lookup.corrective_action(action_id)

    # step 20
    if action["status"] != "OPEN":
        fail("ERR_CORRECTIVE_ACTION_NOT_OPEN", "status must be OPEN to verify")
    # step 24
    if action["authored_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", "an author may not verify their own corrective action")
    # step 36
    if action["design_revision_id"]:
        revision = db.design_revisions.get(action["design_revision_id"])
        if revision is None or revision["status"] != "APPROVED" or revision["superseded_at"]:
            fail(
                "ERR_REVISION_NOT_APPROVED",
                "the referenced revision must be APPROVED and not superseded",
            )

    cascade.capa_verification_cascade(action, g.user_id)
    return response.obj(action, serialize.corrective_action)
