"""ChildDataRecord endpoints (PRD §3.6). The most heavily gated operation."""
from datetime import timedelta

from flask import Blueprint

import calculations as calc
from constants import (
    AGE_SCREEN_OUTCOMES,
    DATA_ELEMENT_CODES,
    PURPOSE_CODES,
    PURPOSE_USE_MAP,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PRIVACY_ENGINEER,
)
from db import db, now, ordered
from errors import fail
from helpers import apply_filters, base_row, bump_service, resolve, resolve_body_fk
from middleware import authenticate, body, req_enum
from response import created, ok, paginate
from serializers import record_out

bp = Blueprint("records", __name__)


@bp.post("/child-data-records")
@authenticate(ROLE_PRIVACY_ENGINEER)
def create_record():
    data = body()

    # step 5: body foreign keys in declaration order
    service = resolve_body_fk("service", data, "service_id")
    consent = resolve_body_fk("consent", data, "consent_request_id")
    activity = resolve_body_fk("activity", data, "activity_id")

    # step 6: cross-parent coherence
    if consent["service_id"] != service["id"] or activity["service_id"] != service["id"]:
        fail("ERR_SERVICE_SCOPE_MISMATCH")

    # step 8: body shape
    data_element_code = req_enum(data, "data_element_code", DATA_ELEMENT_CODES)
    purpose_code = req_enum(data, "purpose_code", PURPOSE_CODES)
    age_screen_outcome = req_enum(data, "age_screen_outcome", AGE_SCREEN_OUTCOMES)

    # step 9: transition legality on the referenced consent
    if consent["status"] == "REVOKED":
        fail("ERR_CONSENT_REVOKED")
    if consent["status"] != "GRANTED":
        fail("ERR_CONSENT_NOT_GRANTED")

    # step 11: posture gate
    posture = calc.compliance_posture(service)
    if posture == "FROZEN":
        fail("ERR_POSTURE_FROZEN")
    if posture == "RESTRICTED" and purpose_code != "PARTICIPATION_CORE":
        fail("ERR_POSTURE_RESTRICTED")

    # step 12: determination gate, then the age-screening gate
    determination = service["determination_status"]
    if determination == "NOT_ASSESSED":
        fail("ERR_DETERMINATION_NOT_MADE")
    if determination == "GENERAL_AUDIENCE":
        fail("ERR_SERVICE_NOT_CHILD_DIRECTED")

    if determination == "MIXED_AUDIENCE":
        has_active_screen = any(
            s["service_id"] == service["id"] and s["status"] == "ACTIVE"
            for s in db.age_screens.values()
        )
        if not has_active_screen:
            fail("ERR_AGE_SCREEN_NOT_ACTIVE")
        if age_screen_outcome == "THIRTEEN_PLUS":
            fail("ERR_NOT_CHILD_SUBJECT")
    else:  # CHILD_DIRECTED_PRIMARY — every visitor is treated as a child
        if age_screen_outcome == "THIRTEEN_PLUS":
            fail("ERR_AGE_SCREEN_NOT_PERMITTED")

    # step 13(a): the direct notice must actually have been delivered
    if consent["notice_delivered_at"] is None:
        fail("ERR_DIRECT_NOTICE_NOT_DELIVERED")

    # step 20: data minimization
    if purpose_code == "PARTICIPATION_CORE":
        if data_element_code not in activity["participation_required_elements"]:
            fail("ERR_ELEMENT_NOT_REASONABLY_NECESSARY")
    else:
        if PURPOSE_USE_MAP[purpose_code] not in consent["intended_uses"]:
            fail("ERR_PURPOSE_NOT_CONSENTED")

    # step 25: a retention schedule must be in force right now
    schedule = calc.effective_retention_schedule(
        service["id"], data_element_code, purpose_code
    )
    if schedule is None:
        fail("ERR_NO_RETENTION_SCHEDULE")

    collected_at = now()
    record = base_row()
    record.update(
        {
            "service_id": service["id"],
            "consent_request_id": consent["id"],
            "activity_id": activity["id"],
            # copied from the consent so that child-identity-scoped deletion works
            "child_pseudonym": consent["child_pseudonym"],
            "data_element_code": data_element_code,
            "purpose_code": purpose_code,
            "age_screen_outcome": age_screen_outcome,
            "collected_at": collected_at,
            # pinned copies: a later policy change never rewrites these terms
            "retention_days_applied": schedule["retention_days"],
            "disposal_method_applied": schedule["disposal_method"],
            "disposal_due_at": collected_at
            + timedelta(days=schedule["retention_days"]),
            "scheduled_run_sequence": None,
            "disposed_at": None,
            "status": "COLLECTED",
        }
    )
    db.child_data_records[record["id"]] = record
    bump_service(service)
    return created(record_out(record))


@bp.get("/child-data-records")
@authenticate(ROLE_COMPLIANCE_OFFICER, ROLE_PRIVACY_ENGINEER)
def list_records():
    rows = ordered(list(db.child_data_records.values()))
    rows = apply_filters(
        rows,
        {
            "service_id": "service_id",
            "consent_request_id": "consent_request_id",
            "activity_id": "activity_id",
            "child_pseudonym": "child_pseudonym",
            "status": "status",
        },
    )
    return paginate(rows, record_out)


@bp.get("/child-data-records/<record_id>")
@authenticate(ROLE_COMPLIANCE_OFFICER, ROLE_PRIVACY_ENGINEER)
def get_record(record_id):
    return ok(record_out(resolve("record", record_id)))
