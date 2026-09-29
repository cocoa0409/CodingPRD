"""Spectrum licences: filing, coordination and enforcement (PRD 3.1)."""

from flask import Blueprint

import serialize
from auth import roles
from constants import (
    API_PREFIX,
    COORDINATION_OUTCOMES,
    ENFORCEMENT_ACTIONS,
    FREQUENCY_BANDS,
)
from db import db, new_record, touch
from errors import fail
from licensing import enforcement_cascade, reinstate_cascade, suspend_beams_of_license
from response import object_response
from validators import (
    body_dict,
    opt_bool,
    opt_str,
    req_dt,
    req_enum,
    req_jurisdiction,
    req_num,
    req_str,
)

bp = Blueprint("regulatory", __name__, url_prefix=API_PREFIX)


def find_license(license_id):
    record = db.licenses.get(license_id)
    if record is None:
        fail("ERR_SPECTRUM_LICENSE_NOT_FOUND", "Spectrum licence not found.")
    return record


@bp.post("/spectrum-licenses")
@roles("ComplianceOfficer")
def file_license():
    body = body_dict()
    license_code = req_str(body, "license_code", 1, 40)
    jurisdiction_code = req_jurisdiction(body, "jurisdiction_code", strict_format=True)
    frequency_band = req_enum(body, "frequency_band", FREQUENCY_BANDS)
    max_eirp_dbw = req_num(body, "max_eirp_dbw", gt=0)
    expires_at = req_dt(body, "expires_at")
    disclosure_version = req_str(body, "consumer_disclosure_version", 1, 20)
    in_motion_permitted = opt_bool(body, "in_motion_permitted", False)

    for existing in db.licenses.values():
        if existing["license_code"] == license_code:
            fail("ERR_INVALID_REQUEST", "license_code is already in use.")

    record = new_record()
    record.update(
        {
            "license_code": license_code,
            "jurisdiction_code": jurisdiction_code,
            "frequency_band": frequency_band,
            "max_eirp_dbw": max_eirp_dbw,
            "expires_at": expires_at,
            "consumer_disclosure_version": disclosure_version,
            "in_motion_permitted": in_motion_permitted,
            "license_state": "PENDING_COORDINATION",
            "coordination_state": "UNCOORDINATED",
            "coordination_note": None,
            "enforcement_reason": None,
        }
    )
    db.licenses[record["id"]] = record
    return object_response(serialize.spectrum_license(record), 201)


@bp.get("/spectrum-licenses/<license_id>")
@roles("ComplianceOfficer", "NetworkOpsEngineer", "ProvisioningAgent")
def read_license(license_id):
    return object_response(serialize.spectrum_license(find_license(license_id)))


@bp.post("/spectrum-licenses/<license_id>/coordination")
@roles("ComplianceOfficer")
def record_coordination(license_id):
    body = body_dict()
    outcome = req_enum(body, "outcome", COORDINATION_OUTCOMES)
    note = opt_str(body, "coordination_note", 1, 500)

    record = find_license(license_id)
    state = record["license_state"]
    coordination = record["coordination_state"]

    if outcome == "GRANTED" and state == "PENDING_COORDINATION":
        record["license_state"] = "ACTIVE"
        record["coordination_state"] = "COORDINATED"
        record["coordination_note"] = note
    elif outcome == "GRANTED_PROVISIONAL" and state == "PENDING_COORDINATION":
        record["license_state"] = "ACTIVE"
        record["coordination_note"] = note
    elif outcome == "GRANTED" and state == "ACTIVE" and coordination == "UNCOORDINATED":
        record["coordination_state"] = "COORDINATED"
        record["coordination_note"] = note
    elif outcome == "REFUSED" and state == "PENDING_COORDINATION":
        record["license_state"] = "REFUSED"
        record["coordination_state"] = "REFUSED"
        record["coordination_note"] = note
        suspend_beams_of_license(record)
    else:
        fail(
            "ERR_LICENSE_STATE_INVALID",
            "Outcome '%s' is not legal from license_state '%s'." % (outcome, state),
        )

    touch(record)
    return object_response(serialize.spectrum_license(record))


@bp.post("/spectrum-licenses/<license_id>/enforcement-action")
@roles("ComplianceOfficer")
def enforcement_action(license_id):
    body = body_dict()
    action = req_enum(body, "action", ENFORCEMENT_ACTIONS)
    reason = req_str(body, "reason", 1, 500)

    record = find_license(license_id)
    state = record["license_state"]

    if action == "SUSPEND":
        if state != "ACTIVE":
            fail(
                "ERR_LICENSE_STATE_INVALID",
                "Suspension is only legal from ACTIVE.",
            )
        record["license_state"] = "SUSPENDED"
        record["enforcement_reason"] = reason
        touch(record)
        enforcement_cascade(record)
    else:
        if state != "SUSPENDED":
            fail(
                "ERR_LICENSE_STATE_INVALID",
                "Reinstatement is only legal from SUSPENDED.",
            )
        record["license_state"] = "ACTIVE"
        record["enforcement_reason"] = reason
        touch(record)
        reinstate_cascade(record)

    return object_response(serialize.spectrum_license(record))
