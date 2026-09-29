"""Brand-standard audits: two independent status dimensions (PRD 3.7)."""

from flask import Blueprint

import derive
import enums
import lookup
import validate
from auth import (ROLE_BRAND_AUDITOR, ROLE_REGIONAL_OPS_CONTROLLER, any_role,
                  require)
from db import new_entity, public, store, touch
from errors import fail
from response import object_response
from routes.common import collection_listing, guard_state

bp = Blueprint("brand_audits", __name__)

LIST_FILTERS = (
    ("base_id", "base_id", None),
    ("finding_status", "finding_status", enums.FINDING_STATUS),
    ("remediation_status", "remediation_status", enums.REMEDIATION_STATUS),
)

REMEDIATION_SOURCE = {"IN_PROGRESS": "NOT_STARTED", "VERIFIED": "IN_PROGRESS"}


def _agreement_id_of(audit):
    return store.crew_bases[audit["base_id"]]["agreement_id"]


@bp.route("/brand-audits", methods=["POST"])
@require(ROLE_BRAND_AUDITOR)
def record_audit():
    data = validate.body()
    base_id = validate.string_field(data, "base_id")
    base = lookup.reference("crew_bases", base_id)

    audit_scope = validate.enum_field(data, "audit_scope", enums.AUDIT_SCOPE)
    findings_count = validate.int_field(data, "findings_count", minimum=1)
    severity = validate.enum_field(data, "severity", enums.SEVERITY)

    audit = new_entity({
        "base_id": base["id"],
        "audit_scope": audit_scope,
        "findings_count": findings_count,
        "severity": severity,
        "finding_status": "OPEN",
        "remediation_status": "NOT_STARTED",
        "evidence_ref": None,
    })
    store.brand_audits[audit["id"]] = audit

    # The audit joins the exposure set, so every published scorecard of the
    # agreement goes STALE and its invoices are voided.
    derive.stale_scorecards_of_agreement(base["agreement_id"])

    return object_response(public(audit), 201)


@bp.route("/brand-audits", methods=["GET"])
@any_role()
def list_audits():
    return collection_listing("brand_audits", LIST_FILTERS)


@bp.route("/brand-audits/<audit_id>", methods=["GET"])
@any_role()
def read_audit(audit_id):
    return object_response(public(lookup.brand_audit(audit_id)))


@bp.route("/brand-audits/<audit_id>/acknowledge", methods=["POST"])
@require(ROLE_REGIONAL_OPS_CONTROLLER)
def acknowledge_audit(audit_id):
    audit = lookup.brand_audit(audit_id)

    guard_state(audit["finding_status"] == "OPEN")

    # ACKNOWLEDGED is still an exposed value, so no scorecard goes stale here.
    audit["finding_status"] = "ACKNOWLEDGED"
    touch(audit)

    return object_response(public(audit))


@bp.route("/brand-audits/<audit_id>/remediation", methods=["POST"])
@require(ROLE_REGIONAL_OPS_CONTROLLER)
def advance_remediation(audit_id):
    audit = lookup.brand_audit(audit_id)
    data = validate.body()
    to_remediation_status = validate.enum_field(data, "to_remediation_status",
                                                enums.REMEDIATION_STATUS)
    evidence_ref = validate.string_field(data, "evidence_ref", required=False)

    guard_state(audit["remediation_status"]
                == REMEDIATION_SOURCE.get(to_remediation_status),
                "The remediation cannot reach %s from %s"
                % (to_remediation_status, audit["remediation_status"]))

    if to_remediation_status == "VERIFIED" and evidence_ref is None:
        fail("ERR_EVIDENCE_REQUIRED")

    audit["remediation_status"] = to_remediation_status
    if evidence_ref is not None:
        audit["evidence_ref"] = evidence_ref
    touch(audit)

    # Verifying removes the audit from future exposure but stales nothing.
    return object_response(public(audit))


@bp.route("/brand-audits/<audit_id>/close", methods=["POST"])
@require(ROLE_BRAND_AUDITOR)
def close_audit(audit_id):
    audit = lookup.brand_audit(audit_id)

    guard_state(audit["finding_status"] == "ACKNOWLEDGED")
    if audit["remediation_status"] != "VERIFIED":
        fail("ERR_REMEDIATION_NOT_VERIFIED")

    audit["finding_status"] = "CLOSED"
    touch(audit)

    # Closure takes the audit out of the exposure set.
    derive.stale_scorecards_of_agreement(_agreement_id_of(audit))

    return object_response(public(audit))
