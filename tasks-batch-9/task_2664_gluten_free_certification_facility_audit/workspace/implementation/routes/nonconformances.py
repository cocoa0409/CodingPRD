"""Nonconformances and the bounded corrective-action cycle."""

from flask import Blueprint

import clock
import db
import middleware as mw
import query
import response
from constants import (
    CA_REJECTION_REASONS,
    MAX_CA_REVISIONS,
    NC_CATEGORIES,
    NC_SEVERITIES,
    NC_SOURCE_TYPES,
    READ_NONCONFORMANCES,
    ROLE_APPLICANT_CONTACT,
    ROLE_CERTIFICATION_REVIEWER,
    ROLE_FIELD_AUDITOR,
)
from errors import ApiError
from services import derive, nc as nc_service

bp = Blueprint("nonconformances", __name__)

_SOURCE_KEY = {
    "AUDIT": "audit_id",
    "LOT_TEST": "lot_test_id",
    "COMPLAINT": "complaint_id",
    "CHANGE_NOTIFICATION": "certificate_id",
    "SURVEILLANCE_RUN": "certificate_id",
}
_ALL_SOURCE_KEYS = ("certificate_id", "audit_id", "lot_test_id", "complaint_id")


@bp.post("/gfco/nonconformances")
def create_nonconformance():
    user_id, _ = mw.authenticate(
        [ROLE_FIELD_AUDITOR, ROLE_CERTIFICATION_REVIEWER]
    )
    data = mw.body()
    applicant_id = mw.req_str(data, "applicant_id")
    source_type = mw.req_enum(data, "source_type", NC_SOURCE_TYPES)
    category = mw.req_enum(data, "category", NC_CATEGORIES)
    severity = mw.req_enum(data, "severity", NC_SEVERITIES)
    description = mw.req_str(data, "description")
    keys = {name: mw.opt_id(data, name) for name in _ALL_SOURCE_KEYS}

    expected_key = _SOURCE_KEY[source_type]
    supplied = [name for name, value in keys.items() if value is not None]
    if keys[expected_key] is None:
        mw.bad(expected_key, "is required for source_type %s" % source_type)
    if set(supplied) != {expected_key}:
        mw.bad(
            expected_key,
            "must be the only source key supplied for source_type %s" % source_type,
        )

    query.fetch("applicant", applicant_id)
    query.maybe("certificate", keys["certificate_id"])
    query.maybe("audit", keys["audit_id"])
    query.maybe("lot_test", keys["lot_test_id"])
    query.maybe("complaint", keys["complaint_id"])

    row = nc_service.create(
        applicant_id=applicant_id,
        source_type=source_type,
        category=category,
        severity=severity,
        description=description,
        raised_by_user_id=user_id,
        certificate_id=keys["certificate_id"],
        audit_id=keys["audit_id"],
        lot_test_id=keys["lot_test_id"],
        complaint_id=keys["complaint_id"],
    )
    return response.created(response.serialize(row))


@bp.get("/gfco/nonconformances/<nonconformance_id>")
def get_nonconformance(nonconformance_id):
    mw.authenticate(READ_NONCONFORMANCES)
    return response.ok(
        response.serialize(query.fetch("nonconformance", nonconformance_id))
    )


@bp.get("/gfco/nonconformances")
def list_nonconformances():
    mw.authenticate(READ_NONCONFORMANCES)
    return query.listing(
        db.nonconformances,
        {
            "applicant_id": query.arg("applicant_id"),
            "certificate_id": query.arg("certificate_id"),
            "audit_id": query.arg("audit_id"),
            "lot_test_id": query.arg("lot_test_id"),
            "complaint_id": query.arg("complaint_id"),
            "status": query.arg("status"),
            "severity": query.arg("severity"),
        },
    )


@bp.post("/gfco/nonconformances/<nonconformance_id>/corrective-action-plan")
def submit_plan(nonconformance_id):
    user_id, _ = mw.authenticate([ROLE_APPLICANT_CONTACT])
    data = mw.body()
    expected_version = mw.req_int(data, "expected_nonconformance_version")
    ca_plan_text = mw.req_str(data, "ca_plan_text")
    nc = query.fetch("nonconformance", nonconformance_id)

    if nc["applicant_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if expected_version != nc["version"]:
        raise ApiError("ERR_STALE_NONCONFORMANCE_VERSION")
    if nc["status"] not in ("OPEN", "CA_REJECTED"):
        raise ApiError("ERR_INVALID_NONCONFORMANCE_STATE")
    if nc["certificate_id"]:
        cert = db.certificates.get(nc["certificate_id"])
        if cert is not None and cert["status"] in ("REVOKED", "EXPIRED"):
            raise ApiError("ERR_CERTIFICATE_TERMINAL_NO_CA")
    if nc["ca_due_on"] is not None and clock.now() > nc["ca_due_on"]:
        raise ApiError("ERR_CORRECTIVE_ACTION_OVERDUE")

    nc["ca_plan_text"] = ca_plan_text
    nc["status"] = "CA_SUBMITTED"
    db.touch(nc)
    derive.recompute_applicant_by_id(nc["applicant_id"])
    derive.recompute_audits_for_nonconformance(nc)
    return response.ok(response.serialize(nc))


@bp.post("/gfco/nonconformances/<nonconformance_id>/corrective-action-decision")
def decide_plan(nonconformance_id):
    user_id, _ = mw.authenticate([ROLE_CERTIFICATION_REVIEWER])
    data = mw.body()
    decision = mw.req_enum(data, "decision", ("ACCEPT", "REJECT"))
    ca_rejection_reason = mw.opt_enum(
        data, "ca_rejection_reason", CA_REJECTION_REASONS
    )
    nc = query.fetch("nonconformance", nonconformance_id)

    if nc["status"] != "CA_SUBMITTED":
        raise ApiError("ERR_INVALID_NONCONFORMANCE_STATE")
    if user_id == nc["raised_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if decision == "ACCEPT":
        nc["status"] = "CA_ACCEPTED"
        nc["ca_decided_by_user_id"] = user_id
        nc["ca_rejection_reason"] = None
        db.touch(nc)
        derive.recompute_applicant_by_id(nc["applicant_id"])
        derive.recompute_audits_for_nonconformance(nc)
        return response.ok(response.serialize(nc))

    if ca_rejection_reason is None:
        mw.bad("ca_rejection_reason", "is required when rejecting a plan")
    nc["ca_revision_count"] = nc["ca_revision_count"] + 1
    nc["ca_decided_by_user_id"] = user_id
    nc["ca_rejection_reason"] = ca_rejection_reason
    if nc["ca_revision_count"] < MAX_CA_REVISIONS:
        nc["status"] = "CA_REJECTED"
        db.touch(nc)
        derive.recompute_applicant_by_id(nc["applicant_id"])
        derive.recompute_audits_for_nonconformance(nc)
    else:
        nc_service.escalate(nc)
    return response.ok(response.serialize(nc))


@bp.post("/gfco/nonconformances/<nonconformance_id>/verification")
def verify_effectiveness(nonconformance_id):
    user_id, _ = mw.authenticate([ROLE_FIELD_AUDITOR])
    data = mw.body()
    confirmed = mw.req_bool(data, "effectiveness_confirmed")
    nc = query.fetch("nonconformance", nonconformance_id)

    if nc["status"] != "CA_ACCEPTED":
        raise ApiError("ERR_INVALID_NONCONFORMANCE_STATE")
    if user_id == nc["ca_decided_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    now = clock.now()
    if confirmed:
        nc["ca_verified"] = True
        nc["status"] = "CLOSED"
        nc["closed_on"] = now
        db.touch(nc)
        if nc["complaint_id"]:
            complaint = db.consumer_complaints.get(nc["complaint_id"])
            if complaint is not None and complaint["status"] in (
                "SUBSTANTIATED",
                "RECALL_COORDINATION",
            ):
                complaint["status"] = "CLOSED"
                complaint["closed_on"] = now
                db.touch(complaint)
    else:
        nc["ca_verified"] = False
        nc["status"] = "CA_REJECTED"
        db.touch(nc)

    derive.recompute_applicant_by_id(nc["applicant_id"])
    derive.recompute_audits_for_nonconformance(nc)
    return response.ok(response.serialize(nc))
