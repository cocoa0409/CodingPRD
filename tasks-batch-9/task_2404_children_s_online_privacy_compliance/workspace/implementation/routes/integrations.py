"""ThirdPartyIntegration endpoints (PRD §3.7)."""
from flask import Blueprint

import calculations as calc
from constants import (
    BEHAVIORAL_GATE_TYPES,
    INTEGRATION_STATUSES,
    INTEGRATION_TYPES,
    PLACEMENT_AREAS,
    ROLE_COMPLIANCE_OFFICER,
)
from db import db, now, touch
from errors import fail
from helpers import base_row, bump_service, resolve, resolve_body_fk
from middleware import authenticate, body, opt_string, req_bool, req_enum, req_string
from response import created, ok
from serializers import integration_out

bp = Blueprint("integrations", __name__)

ALLOWED_TRANSITIONS = {
    ("DECLARED", "AUDIT_PENDING"),
    ("APPROVED", "AUDIT_PENDING"),
    ("AUDIT_PENDING", "APPROVED"),
    ("AUDIT_PENDING", "BLOCKED"),
    ("APPROVED", "BLOCKED"),
    ("DECLARED", "BLOCKED"),
}


@bp.post("/third-party-integrations")
@authenticate(ROLE_COMPLIANCE_OFFICER)
def create_integration():
    data = body()
    service = resolve_body_fk("service", data, "service_id")
    vendor_name = req_string(data, "vendor_name")
    integration_type = req_enum(data, "integration_type", INTEGRATION_TYPES)
    collects_persistent_identifier = req_bool(data, "collects_persistent_identifier")
    placement_area = req_enum(data, "placement_area", PLACEMENT_AREAS)

    integration = base_row()
    integration.update(
        {
            "service_id": service["id"],
            "vendor_name": vendor_name,
            "integration_type": integration_type,
            "collects_persistent_identifier": collects_persistent_identifier,
            "placement_area": placement_area,
            "status": "DECLARED",
            "last_audit_decision_at": None,
            "audit_note": None,
        }
    )
    db.third_party_integrations[integration["id"]] = integration
    bump_service(service)
    return created(integration_out(integration))


@bp.post("/third-party-integrations/<integration_id>/status")
@authenticate(ROLE_COMPLIANCE_OFFICER)
def set_integration_status(integration_id):
    integration = resolve("integration", integration_id)
    data = body()
    to_status = req_enum(data, "to_status", INTEGRATION_STATUSES)
    audit_note = opt_string(data, "audit_note")

    transition = (integration["status"], to_status)
    if transition not in ALLOWED_TRANSITIONS:
        fail("ERR_INVALID_STATE")

    service = db.online_services[integration["service_id"]]

    if to_status == "APPROVED":
        # Clause order is the global precedence of §2.9: posture (11), then the
        # behavioural-advertising gate (14), then disclosure (18).
        if calc.compliance_posture(service) == "FROZEN":
            fail("ERR_POSTURE_FROZEN")
        if (
            integration["integration_type"] in BEHAVIORAL_GATE_TYPES
            and integration["placement_area"] == "CHILD_DIRECTED_AREA"
            and service["determination_status"]
            in ("MIXED_AUDIENCE", "CHILD_DIRECTED_PRIMARY")
        ):
            if calc.granted_disclosure_consent_count(service["id"]) < 1:
                fail("ERR_BEHAVIORAL_AD_TIER_UNMET")
        if not calc.disclosed_in_notice(integration):
            fail("ERR_INTEGRATION_NOT_DISCLOSED")

    if audit_note is not None:
        integration["audit_note"] = audit_note

    integration["status"] = to_status

    if to_status in ("APPROVED", "BLOCKED"):
        integration["last_audit_decision_at"] = now()
        service["audit_decision_count"] += 1

    touch(integration)
    bump_service(service)
    return ok(integration_out(integration))
