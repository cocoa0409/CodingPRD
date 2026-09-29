"""Health centre medication administration records."""

from datetime import timedelta

from flask import Blueprint

import clock
import db
import domain
import helpers
import response
import validators
from errors import api_error
from middleware import authenticate

bp = Blueprint("medications", __name__)

MAX_CONTROLLED_PER_24H = 2


@bp.get("/accreditation/medication-records/<record_id>")
def get_record(record_id):
    ident = authenticate(
        ("HealthCareStaff", "CampDirector", "AccreditationOfficer", "StateLicensingAgent")
    )
    record = helpers.med_record_or_404(record_id)
    helpers.scope(ident, record["camp_id"])
    return response.ok(helpers.public(record))


@bp.get("/accreditation/medication-records")
def list_records():
    authenticate(
        ("HealthCareStaff", "CampDirector", "AccreditationOfficer", "StateLicensingAgent")
    )
    return helpers.collection_response(db.med_records, helpers.MED_FILTERS)


@bp.post("/accreditation/medication-records")
def record_administration():
    ident = authenticate(("HealthCareStaff",))
    data = validators.body()
    camp_id = validators.require(data, "camp_id")
    if not isinstance(camp_id, str):
        raise api_error("ERR_INVALID_REQUEST", "Field 'camp_id' must be a string.")
    camper_reference = validators.req_str(data, "camper_reference", 1, 64)
    medication_class = validators.req_enum(
        data, "medication_class", domain.MEDICATION_CLASSES
    )
    dose_units = validators.req_int(data, "dose_units", 1)
    administered_at = validators.req_datetime(data, "administered_at")
    administered_by_role = validators.req_enum(
        data, "administered_by_role", domain.ADMIN_ROLES
    )
    second_signature = validators.opt_bool(
        data, "second_signature_present", default=False
    )

    camp = helpers.camp_or_404(camp_id)
    helpers.scope(ident, camp["id"])

    if camp["compliance_posture"] == "FROZEN" and medication_class in (
        "CONTROLLED",
        "PRESCRIPTION",
    ):
        raise api_error(
            "ERR_CAMP_POSTURE_FROZEN",
            "The health centre is closed to controlled and prescription intake.",
        )
    if domain.rank(camp["health_staffing_level"]) < domain.CLASS_STAFFING_FLOOR[
        medication_class
    ]:
        raise api_error(
            "ERR_HEALTH_STAFFING_INSUFFICIENT",
            "The camp's health staffing is below the floor for this medication class.",
        )
    if administered_by_role not in domain.CLASS_ALLOWED_ROLES[medication_class]:
        raise api_error(
            "ERR_MED_ROLE_NOT_PERMITTED",
            "%s may not administer a %s dose." % (administered_by_role, medication_class),
        )
    if medication_class == "CONTROLLED" and not second_signature:
        raise api_error(
            "ERR_CONTROLLED_SECOND_SIGNATURE_REQUIRED",
            "A controlled dose requires a witness signature.",
        )
    if medication_class == "CONTROLLED" and dose_units > camp["controlled_on_hand_units"]:
        raise api_error(
            "ERR_CONTROLLED_STOCK_INSUFFICIENT",
            "The controlled substance stock on hand is insufficient.",
        )
    if medication_class == "CONTROLLED":
        window_start = administered_at - timedelta(hours=24)
        count = 0
        for existing in db.ordered(db.med_records):
            if (
                existing["camp_id"] != camp_id
                or existing["camper_reference"] != camper_reference
                or existing["medication_class"] != "CONTROLLED"
                or existing["record_status"] != "RECORDED"
            ):
                continue
            moment = validators.parse_timestamp(
                existing["administered_at"], "administered_at"
            )
            if window_start <= moment < administered_at:
                count += 1
        if count >= MAX_CONTROLLED_PER_24H:
            raise api_error(
                "ERR_CONTROLLED_DOSE_WINDOW_EXCEEDED",
                "The per-camper controlled dosing window is exhausted.",
            )

    record = db.common_fields()
    record.update(
        {
            "camp_id": camp_id,
            "camper_reference": camper_reference,
            "medication_class": medication_class,
            "dose_units": dose_units,
            "administered_at": clock.iso(administered_at),
            "administered_by_role": administered_by_role,
            "second_signature_present": second_signature,
            "record_status": "RECORDED",
            "compliance_flag": (
                "DOCUMENTATION_INCOMPLETE"
                if medication_class == "PRESCRIPTION" and not second_signature
                else "COMPLIANT"
            ),
            "void_reason": None,
        }
    )
    db.med_records[record["id"]] = record

    if medication_class == "CONTROLLED":
        domain.recompute_controlled_balance(camp)
    return response.created(helpers.public(record))


@bp.post("/accreditation/medication-records/<record_id>/void")
def void_record(record_id):
    ident = authenticate(("HealthCareStaff",))
    data = validators.body()
    reason = validators.opt_str(data, "void_reason", 0, 500)

    record = helpers.med_record_or_404(record_id)
    helpers.scope(ident, record["camp_id"])

    if record["record_status"] == "RECORDED":
        record["record_status"] = "VOIDED"
        if reason is not None:
            record["void_reason"] = reason
        db.touch(record)
        camp = db.camps.get(record["camp_id"])
        if camp is not None and record["medication_class"] == "CONTROLLED":
            domain.recompute_controlled_balance(camp)
    return response.ok(helpers.public(record))
