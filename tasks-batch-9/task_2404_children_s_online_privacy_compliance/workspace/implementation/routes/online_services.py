"""OnlineService endpoints (PRD §3.1, §3.2) and the read-only reverse lookups."""
from flask import Blueprint

import calculations as calc
from constants import (
    COMPLIANCE_POSTURES,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PRIVACY_ENGINEER,
    ROLE_SAFE_HARBOR_ASSESSOR,
    ROLE_SAFE_HARBOR_CERTIFIER,
    SERVICE_CATEGORIES,
    SUBJECT_MATTER_CODES,
)
from db import db, now, ordered
from errors import fail
from helpers import apply_filters, base_row, bump_service, force_reaudit_on_escalation, resolve
from middleware import authenticate, body, req_enum, req_string
from response import created, ok, paginate, pagination_params
from serializers import (
    activity_out,
    age_screen_out,
    evidence_out,
    integration_out,
    notice_out,
    schedule_out,
    service_out,
)

bp = Blueprint("online_services", __name__)

READ_ROLES = (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PRIVACY_ENGINEER,
    ROLE_SAFE_HARBOR_ASSESSOR,
    ROLE_SAFE_HARBOR_CERTIFIER,
)
SUB_READ_ROLES = (ROLE_COMPLIANCE_OFFICER, ROLE_PRIVACY_ENGINEER)


@bp.post("/online-services")
@authenticate(ROLE_COMPLIANCE_OFFICER)
def create_service():
    data = body()
    name = req_string(data, "name")
    operator_organization = req_string(data, "operator_organization")
    service_category = req_enum(data, "service_category", SERVICE_CATEGORIES)
    subject_matter_code = req_enum(data, "subject_matter_code", SUBJECT_MATTER_CODES)

    service = base_row()
    service.update(
        {
            "name": name,
            "operator_organization": operator_organization,
            "service_category": service_category,
            "subject_matter_code": subject_matter_code,
            "determination_status": "NOT_ASSESSED",
            "determination_variant_applied": None,
            "determination_evaluated_at": None,
            "posture_override": None,
            "audit_decision_count": 0,
            "evidence_sequence_counter": 0,
            "compliance_run_sequence": 0,
        }
    )
    db.online_services[service["id"]] = service
    return created(service_out(service))


@bp.get("/online-services")
@authenticate(*READ_ROLES)
def list_services():
    rows = ordered(list(db.online_services.values()))
    rows = apply_filters(rows, {"determination_status": "determination_status"})

    from flask import request

    posture = request.args.get("compliance_posture")
    if posture:
        rows = [r for r in rows if calc.compliance_posture(r) == posture]
    safe_harbor = request.args.get("safe_harbor_status")
    if safe_harbor:
        rows = [r for r in rows if calc.safe_harbor_state(r["id"])[0] == safe_harbor]
    return paginate(rows, service_out)


@bp.get("/online-services/<service_id>")
@authenticate(*READ_ROLES)
def get_service(service_id):
    service = resolve("service", service_id)
    return ok(service_out(service))


@bp.post("/online-services/<service_id>/determination")
@authenticate(ROLE_COMPLIANCE_OFFICER)
def run_determination(service_id):
    service = resolve("service", service_id)

    share = calc.audience_child_share(service_id)
    if share is None and not calc.has_design_factor_evidence(service_id):
        fail("ERR_INSUFFICIENT_EVIDENCE")

    score = calc.design_score(service_id)
    status, variant = calc.child_directed_determination(share, score)

    previous_status = service["determination_status"]
    service["determination_variant_applied"] = variant
    service["determination_status"] = status
    service["determination_evaluated_at"] = now()

    # Only an escalation onto CHILD_DIRECTED_PRIMARY from an already-assessed
    # status forces the integration re-audit cascade (PRD §3.2).
    if status == "CHILD_DIRECTED_PRIMARY" and previous_status != "NOT_ASSESSED":
        force_reaudit_on_escalation(service)

    bump_service(service)
    return ok(service_out(service))


@bp.post("/online-services/<service_id>/posture")
@authenticate(ROLE_COMPLIANCE_OFFICER)
def set_posture(service_id):
    service = resolve("service", service_id)
    data = body()
    if "posture_override" not in data:
        fail("ERR_INVALID_REQUEST", "posture_override must be supplied (null clears it).")
    override = data.get("posture_override")
    if override is not None:
        override = req_enum(data, "posture_override", COMPLIANCE_POSTURES)

    if override == "OPEN" and calc.open_audit_count(service_id) != 0:
        fail("ERR_OPEN_AUDITS_PRESENT")

    service["posture_override"] = override
    bump_service(service)
    return ok(service_out(service))


# --- reverse lookups -------------------------------------------------------


@bp.get("/online-services/<service_id>/determination-evidence")
@authenticate(*SUB_READ_ROLES)
def list_service_evidence(service_id):
    resolve("service", service_id)
    rows = [
        e for e in db.determination_evidence.values() if e["service_id"] == service_id
    ]
    # The documented exception to created_at ordering (PRD §2.3).
    rows.sort(key=lambda r: r["evidence_sequence"])
    rows = apply_filters(
        rows, {"evidence_kind": "evidence_kind", "measurement_method": "measurement_method"}
    )
    return paginate(rows, evidence_out)


@bp.get("/online-services/<service_id>/age-screens")
@authenticate(*SUB_READ_ROLES)
def list_service_age_screens(service_id):
    resolve("service", service_id)
    rows = ordered([r for r in db.age_screens.values() if r["service_id"] == service_id])
    rows = apply_filters(rows, {"status": "status"})
    return paginate(rows, age_screen_out)


@bp.get("/online-services/<service_id>/parental-notices")
@authenticate(*SUB_READ_ROLES)
def list_service_notices(service_id):
    resolve("service", service_id)
    rows = ordered(
        [r for r in db.parental_notices.values() if r["service_id"] == service_id]
    )
    rows = apply_filters(rows, {"status": "status"})
    return paginate(rows, notice_out)


@bp.get("/online-services/<service_id>/activities")
@authenticate(*SUB_READ_ROLES)
def list_service_activities(service_id):
    resolve("service", service_id)
    rows = ordered([r for r in db.activities.values() if r["service_id"] == service_id])
    return paginate(rows, activity_out)


@bp.get("/online-services/<service_id>/retention-schedules")
@authenticate(*SUB_READ_ROLES)
def list_service_schedules(service_id):
    resolve("service", service_id)
    rows = ordered(
        [r for r in db.retention_schedules.values() if r["service_id"] == service_id]
    )
    rows = apply_filters(
        rows, {"data_element_code": "data_element_code", "purpose_code": "purpose_code"}
    )
    return paginate(rows, schedule_out)


@bp.get("/online-services/<service_id>/third-party-integrations")
@authenticate(*SUB_READ_ROLES)
def list_service_integrations(service_id):
    resolve("service", service_id)
    rows = ordered(
        [r for r in db.third_party_integrations.values() if r["service_id"] == service_id]
    )
    rows = apply_filters(
        rows,
        {
            "status": "status",
            "integration_type": "integration_type",
            "placement_area": "placement_area",
        },
    )
    return paginate(rows, integration_out)


# Keep pagination_params referenced for modules importing it via this blueprint.
__all__ = ["bp", "pagination_params"]
