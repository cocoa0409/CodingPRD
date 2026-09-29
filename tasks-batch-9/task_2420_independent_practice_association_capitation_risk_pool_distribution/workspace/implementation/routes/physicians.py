"""The physician network: credentialing, panels and exit (PRD 3.2)."""

from flask import Blueprint

import db
import derive
import middleware
import resolve
import response
import serialize
import validate
from errors import fail

bp = Blueprint("physicians", __name__)

SPECIALTIES = ("PRIMARY_CARE", "PEDIATRICS", "INTERNAL_MEDICINE", "OB_GYN")
CREDENTIAL_STATES = ("APPLICANT", "CREDENTIALED", "ACTIVE", "NOTICE_GIVEN", "EXITED")
PANEL_STATES = ("OPEN", "CLOSED_TO_NEW", "TRANSFER_PENDING", "TRANSFERRED")

CREDENTIAL_TRANSITION_ROLES = {
    "APPLICANT": ("NetworkManager", "PhysicianUser"),
    "CREDENTIALED": ("NetworkManager",),
    "ACTIVE": ("NetworkManager",),
    "NOTICE_GIVEN": ("NetworkManager", "PhysicianUser"),
    "EXITED": ("NetworkManager",),
}

PANEL_TRANSITION_ROLES = {
    "OPEN": ("NetworkManager",),
    "CLOSED_TO_NEW": ("NetworkManager", "PhysicianUser"),
    "TRANSFER_PENDING": ("NetworkManager", "PhysicianUser"),
    "TRANSFERRED": ("NetworkManager", "PhysicianUser"),
}


@bp.post("/ipa/delegation-agreements/<agreement_id>/physicians")
def create_physician(agreement_id):
    middleware.require("IpaAdmin", "NetworkManager")
    body = validate.body()
    npi = validate.req_str(body, "npi")
    full_name = validate.req_str(body, "full_name")
    specialty = validate.req_enum(body, "specialty", SPECIALTIES)

    agreement = resolve.agreement(agreement_id)

    # check 20 — npi unique among the physicians of one agreement
    for existing in db.physicians.values():
        if existing["agreement_id"] == agreement["id"] and existing["npi"] == npi:
            fail("ERR_DUPLICATE_NPI")

    physician = db.create(
        db.physicians,
        agreement_id=agreement["id"],
        npi=npi,
        full_name=full_name,
        specialty=specialty,
        credential_status="APPLICANT",
        panel_status="OPEN",
        panel_size=0,
        exit_notice_at=None,
        continuity_of_care_until=None,
        quality_composite_bps=0,
        latest_scorecard_period=None,
    )
    return response.ok(serialize.physician(physician), 201)


@bp.get("/ipa/delegation-agreements/<agreement_id>/physicians")
def list_agreement_physicians(agreement_id):
    user_id, role = middleware.require("IpaAdmin", "NetworkManager", "ClaimsExaminer",
                                       "PayerRepresentative")
    credential_status = validate.query_enum("credential_status", CREDENTIAL_STATES)
    panel_status = validate.query_enum("panel_status", PANEL_STATES)
    limit, offset = validate.pagination()
    agreement = resolve.agreement(agreement_id)
    middleware.check_ownership(role, user_id, agreement=agreement)

    items = db.physicians_of_agreement(agreement["id"])
    if credential_status is not None:
        items = [p for p in items if p["credential_status"] == credential_status]
    if panel_status is not None:
        items = [p for p in items if p["panel_status"] == panel_status]
    window = validate.paginate(items, limit, offset)
    return response.ok_list([serialize.physician(p) for p in window], limit, offset,
                            len(items))


@bp.get("/ipa/physicians/<physician_id>")
def read_physician(physician_id):
    user_id, role = middleware.require("IpaAdmin", "NetworkManager", "ClaimsExaminer",
                                       "PayerRepresentative", "PhysicianUser")
    physician = resolve.physician(physician_id)
    middleware.check_ownership(role, user_id, physician_ids=[physician["id"]],
                              agreement=db.agreement_of_physician(physician))
    return response.ok(serialize.physician(physician))


@bp.post("/ipa/physicians/<physician_id>/state")
def physician_state(physician_id):
    user_id, role = middleware.require("NetworkManager", "PhysicianUser")
    body = validate.body()
    to_state = validate.req_enum(body, "to_state", CREDENTIAL_STATES)
    physician = resolve.physician(physician_id)
    middleware.require_transition_role(role, CREDENTIAL_TRANSITION_ROLES[to_state])
    middleware.check_ownership(role, user_id, physician_ids=[physician["id"]])

    agreement = db.agreement_of_physician(physician)
    current = physician["credential_status"]

    if to_state == "CREDENTIALED":
        if current != "APPLICANT" or agreement["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE_TRANSITION")
        physician["credential_status"] = "CREDENTIALED"
        db.touch(physician)
    elif to_state == "ACTIVE":
        if current == "CREDENTIALED":
            if agreement["status"] != "ACTIVE":
                fail("ERR_INVALID_STATE_TRANSITION")
            physician["credential_status"] = "ACTIVE"
            db.touch(physician)
        elif current == "NOTICE_GIVEN":
            physician["credential_status"] = "ACTIVE"
            physician["exit_notice_at"] = None
            physician["continuity_of_care_until"] = None
            db.touch(physician)
        else:
            fail("ERR_INVALID_STATE_TRANSITION")
    elif to_state == "NOTICE_GIVEN":
        if current != "ACTIVE":
            fail("ERR_INVALID_STATE_TRANSITION")
        notice_at = db.clock()
        physician["credential_status"] = "NOTICE_GIVEN"
        physician["exit_notice_at"] = notice_at
        physician["continuity_of_care_until"] = db.add_days(
            notice_at, agreement["continuity_of_care_days"])
        if physician["panel_status"] == "OPEN":
            physician["panel_status"] = "CLOSED_TO_NEW"
        db.touch(physician)
    elif to_state == "EXITED":
        if current != "NOTICE_GIVEN":
            fail("ERR_INVALID_STATE_TRANSITION")
        # check 24 — panel is clear before exit
        for assignment in db.assignments.values():
            if (assignment["physician_id"] == physician["id"]
                    and assignment["status"] in derive.PANEL_HOLDING_STATES):
                fail("ERR_PANEL_NOT_TRANSFERRED")
        physician["credential_status"] = "EXITED"
        physician["panel_status"] = "TRANSFERRED"
        db.touch(physician)
    else:
        fail("ERR_INVALID_STATE_TRANSITION")

    return response.ok(serialize.physician(physician))


@bp.patch("/ipa/physicians/<physician_id>/panel-status")
def physician_panel_status(physician_id):
    user_id, role = middleware.require("NetworkManager", "PhysicianUser")
    body = validate.body()
    panel_status = validate.req_enum(body, "panel_status", PANEL_STATES)
    physician = resolve.physician(physician_id)
    middleware.require_transition_role(role, PANEL_TRANSITION_ROLES[panel_status])
    middleware.check_ownership(role, user_id, physician_ids=[physician["id"]])

    agreement = db.agreement_of_physician(physician)
    current = physician["panel_status"]

    if panel_status == "CLOSED_TO_NEW":
        if current != "OPEN":
            fail("ERR_INVALID_STATE_TRANSITION")
        physician["panel_status"] = "CLOSED_TO_NEW"
        db.touch(physician)
    elif panel_status == "OPEN":
        if current != "CLOSED_TO_NEW" or physician["credential_status"] != "ACTIVE":
            fail("ERR_INVALID_STATE_TRANSITION")
        # check 29 — capitation posture permits reopening
        if agreement["capitation_posture"] != "CURRENT":
            fail("ERR_CAPITATION_POSTURE_RESTRICTED")
        physician["panel_status"] = "OPEN"
        db.touch(physician)
    else:
        fail("ERR_INVALID_STATE_TRANSITION")

    return response.ok(serialize.physician(physician))
