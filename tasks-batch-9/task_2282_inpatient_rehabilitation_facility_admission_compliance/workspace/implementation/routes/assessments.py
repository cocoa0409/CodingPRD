"""IRF patient assessment instruments (PRD §3.9)."""

import math
from datetime import timedelta

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from db import store
from errors import ApiError
from queryargs import enum_arg, matches, str_arg
from response import envelope, paged, pagination_params
from services import (ASSESSMENT_TYPES, assessment_deadlines, assessments_of_admission,
                      by_seq, require, stamp_new, touch)
from util import Body, dt_of, iso, serialize

bp = Blueprint("assessments", __name__)

ASSESSMENT_STATUSES = ("DRAFT", "COMPLETED", "TRANSMITTED", "LATE_TRANSMITTED", "MISSED")


@bp.post("/assessments")
def create_assessment():
    authenticate(("HimCoder",))
    body = Body(request.get_json(silent=True))

    admission_id = body.id_field("admission_id")
    assessment_type = body.enum_field("assessment_type", ASSESSMENT_TYPES)
    coder_id = body.id_field("coder_clinician_id")

    # ladder rank 10 — body identifier existence
    admission = require(store.admissions, admission_id)
    coder = require(store.clinicians, coder_id)

    # ladder rank 13 — facility boundary
    if coder["facility_id"] != admission["facility_id"]:
        raise ApiError("ERR_CROSS_FACILITY_MISMATCH")

    # ladder rank 18 — a DISCHARGE instrument needs a discharged stay
    if assessment_type == "DISCHARGE" and admission["stay_status"] != "DISCHARGED":
        raise ApiError("ERR_ADMISSION_NOT_DISCHARGED")

    # ladder rank 42 — at most one live instrument per admission per type
    for existing in assessments_of_admission(admission_id):
        if existing["assessment_type"] == assessment_type and existing["status"] != "MISSED":
            raise ApiError("ERR_ASSESSMENT_TYPE_DUPLICATE")

    # an ADMISSION instrument's reference date is anchored on the admit date
    if assessment_type == "ADMISSION" and admission["admitted_at"] is None:
        raise ApiError("ERR_INVALID_STATE")

    reference_date, completion_deadline, transmission_deadline = assessment_deadlines(
        admission, assessment_type)

    assessment = stamp_new({
        "admission_id": admission_id,
        "coder_clinician_id": coder_id,
        "transmitted_by_clinician_id": None,
        "assessment_type": assessment_type,
        "assessment_reference_date": reference_date,
        "completion_deadline_at": iso(completion_deadline),
        "transmission_deadline_at": iso(transmission_deadline),
        # The coder attestation is an input supplied at completion; it carries no
        # declared default, so it is null until the item set is attested.
        "item_set_complete": None,
        "completed_at": None,
        "completion_late": False,
        "transmitted_at": None,
        "late_days": 0,
        "status": "DRAFT",
    })
    store.assessments[assessment["id"]] = assessment
    return envelope(serialize(assessment), 201)


@bp.get("/assessments/<assessment_id>")
def get_assessment(assessment_id):
    authenticate(ALL_ROLES)
    assessment = require(store.assessments, assessment_id)
    return envelope(serialize(assessment), 200)


@bp.get("/assessments")
def list_assessments():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    filters = {
        "admission_id": str_arg("admission_id"),
        "coder_clinician_id": str_arg("coder_clinician_id"),
        "transmitted_by_clinician_id": str_arg("transmitted_by_clinician_id"),
        "assessment_type": enum_arg("assessment_type", ASSESSMENT_TYPES),
        "status": enum_arg("status", ASSESSMENT_STATUSES),
    }
    items = [a for a in by_seq(list(store.assessments.values())) if matches(a, filters)]
    page, pagination = paged(items, limit, offset)
    return envelope([serialize(a) for a in page], 200, pagination)


@bp.post("/assessments/<assessment_id>/complete")
def complete_assessment(assessment_id):
    authenticate(("HimCoder",))
    body = Body(request.get_json(silent=True))
    item_set_complete = body.bool_field("item_set_complete")

    assessment = require(store.assessments, assessment_id)

    # ladder rank 16 — declared transition DRAFT -> COMPLETED
    if assessment["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    # ladder rank 31 — the item set must be attested
    if not item_set_complete:
        raise ApiError("ERR_PAI_ITEM_SET_INCOMPLETE")

    assessment["item_set_complete"] = True
    assessment["status"] = "COMPLETED"
    assessment["completed_at"] = iso(store.clock)
    assessment["completion_late"] = store.clock >= dt_of(assessment["completion_deadline_at"])
    touch(assessment)
    return envelope(serialize(assessment), 200)


@bp.post("/assessments/<assessment_id>/transmit")
def transmit_assessment(assessment_id):
    user_id, _ = authenticate(("HimCoder",))
    assessment = require(store.assessments, assessment_id)

    # ladder rank 14 — segregation of duties
    if user_id == assessment["coder_clinician_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # ladder rank 16 — declared transition COMPLETED -> (LATE_)TRANSMITTED
    if assessment["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE")

    admission = store.admissions.get(assessment["admission_id"])
    # ladder rank 18 — transmission requires a discharged stay
    if admission is None or admission["stay_status"] != "DISCHARGED":
        raise ApiError("ERR_ADMISSION_NOT_DISCHARGED")

    deadline = dt_of(assessment["transmission_deadline_at"])
    if store.clock < deadline:
        assessment["status"] = "TRANSMITTED"
        assessment["late_days"] = 0
    else:
        assessment["status"] = "LATE_TRANSMITTED"
        elapsed = (store.clock - deadline).total_seconds()
        assessment["late_days"] = int(math.ceil(elapsed / timedelta(days=1).total_seconds()))
    assessment["transmitted_at"] = iso(store.clock)
    assessment["transmitted_by_clinician_id"] = user_id
    touch(assessment)

    if assessment["assessment_type"] == "DISCHARGE" and admission["documentation_status"] == "POC_SIGNED":
        admission["documentation_status"] = "PAI_TRANSMITTED"
        touch(admission)

    return envelope(serialize(assessment), 200)
