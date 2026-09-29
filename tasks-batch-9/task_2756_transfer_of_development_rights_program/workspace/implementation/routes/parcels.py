"""Sending parcel and severance application endpoints (PRD 3.3, 3.4, 3.5)."""

from flask import Blueprint

import serializers
from core import db, dec, new_record, respond_object, touch
from errors import fail
from listing import match, paged
from middleware import ADMIN, ALL_ROLES, LANDOWNER, REVIEWER, require_owner, require_roles, require_suspension_clear
from routes.areas import get_sending_area_or_404
from routes.parties import get_party_or_404
from services import calc
from services.certify import certify_application
from validators import (body, field_decimal, field_enum, field_int, field_str, filter_enum, filter_str)

bp = Blueprint("parcels", __name__)

SOIL_CLASSES = ("PRIME", "STATEWIDE", "LOCAL", "NONE")
PARCEL_STATUSES = ("UNSEVERED", "PARTIALLY_SEVERED", "FULLY_SEVERED")
EASEMENT_STATUSES = ("NONE", "RECORDED")
APP_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED", "CERTIFIED", "DENIED", "SUSPENDED")
OPEN_APP_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED")
DECISIONS = ("APPROVE", "REQUIRE_REVISION", "DENY")
MAX_REVISION_ROUNDS = 2


def get_parcel_or_404(parcel_id):
    parcel = db.sending_parcels.get(parcel_id)
    if parcel is None:
        fail("ERR_SENDING_PARCEL_NOT_FOUND", "sending parcel %s does not exist" % parcel_id)
    return parcel


def get_application_or_404(app_id):
    app = db.severance_applications.get(app_id)
    if app is None:
        fail("ERR_SEVERANCE_APPLICATION_NOT_FOUND", "severance application %s does not exist" % app_id)
    return app


# ---------------------------------------------------------------------------
# Sending parcels
# ---------------------------------------------------------------------------
@bp.post("/tdr/sending-parcels")
def create_parcel():
    require_roles(ADMIN)
    data = body()
    apn = field_str(data, "apn", min_len=4, max_len=24)
    gross_acres = field_decimal(data, "gross_acres", minimum=0, places=2, exclusive_min=True)
    constrained_acres = field_decimal(data, "constrained_acres", required=False, default="0", minimum=0, places=2)
    soil_class = field_enum(data, "soil_class", SOIL_CLASSES)
    existing_dwelling_units = field_int(data, "existing_dwelling_units", required=False, default=0, minimum=0)
    if dec(constrained_acres) > dec(gross_acres):
        fail("ERR_INVALID_REQUEST", "constrained_acres may not exceed gross_acres")

    owner_id = field_str(data, "owner_party_id", min_len=1)
    area_id = field_str(data, "sending_area_id", min_len=1)
    owner = get_party_or_404(owner_id)
    area = get_sending_area_or_404(area_id)

    if owner["kind"] != "LANDOWNER":
        fail("ERR_PARTY_KIND_MISMATCH", "owner_party_id must reference a LANDOWNER party")
    if area["status"] != "ACTIVE":
        fail("ERR_SENDING_AREA_NOT_ACTIVE", "sending area is %s" % area["status"])
    for row in db.sending_parcels.values():
        if row["apn"] == apn:
            fail("ERR_DUPLICATE_PARCEL_APN", "apn %s is already enrolled" % apn)

    baseline = calc.parcel_baseline_allocation(area, gross_acres, constrained_acres, soil_class,
                                              existing_dwelling_units)
    rec = new_record(
        {
            "owner_party_id": owner_id,
            "sending_area_id": area_id,
            "apn": apn,
            "gross_acres": gross_acres,
            "constrained_acres": constrained_acres,
            "soil_class": soil_class,
            "existing_dwelling_units": existing_dwelling_units,
            "baseline_allocation_units": baseline,
            "severed_units": 0,
            "remaining_units": baseline,
            "restricted_acres": dec("0.00"),
            "easement_status": "NONE",
            "parcel_status": "UNSEVERED",
        }
    )
    db.sending_parcels[rec["id"]] = rec
    return respond_object(serializers.sending_parcel(rec), 201)


@bp.get("/tdr/sending-parcels/<parcel_id>")
def get_parcel(parcel_id):
    require_roles(*ALL_ROLES)
    return respond_object(serializers.sending_parcel(get_parcel_or_404(parcel_id)))


@bp.get("/tdr/sending-parcels")
def list_parcels():
    require_roles(*ALL_ROLES)
    rows = match(
        list(db.sending_parcels.values()),
        owner_party_id=filter_str("owner_party_id"),
        sending_area_id=filter_str("sending_area_id"),
        parcel_status=filter_enum("parcel_status", PARCEL_STATUSES),
        easement_status=filter_enum("easement_status", EASEMENT_STATUSES),
    )
    return paged(rows, serializers.sending_parcel)


# ---------------------------------------------------------------------------
# Severance applications
# ---------------------------------------------------------------------------
@bp.post("/tdr/severance-applications")
def create_application():
    user_id, role = require_roles(LANDOWNER)
    data = body()
    requested_units = field_int(data, "requested_units", minimum=1)
    field_str(data, "note", required=False)
    parcel_id = field_str(data, "sending_parcel_id", min_len=1)
    applicant_id = field_str(data, "applicant_party_id", min_len=1)

    parcel = get_parcel_or_404(parcel_id)
    applicant = get_party_or_404(applicant_id)

    require_owner(user_id, role, applicant_id)
    if applicant_id != parcel["owner_party_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "applicant is not the owner of this parcel")
    if applicant["kind"] != "LANDOWNER":
        fail("ERR_PARTY_KIND_MISMATCH", "applicant_party_id must reference a LANDOWNER party")

    require_suspension_clear(applicant_id, parcel["owner_party_id"])

    if parcel["parcel_status"] == "FULLY_SEVERED":
        fail("ERR_PARCEL_FULLY_SEVERED", "parcel has no remaining development rights")

    area = db.sending_areas.get(parcel["sending_area_id"])
    if area is None or area["status"] != "ACTIVE":
        fail("ERR_SENDING_AREA_NOT_ACTIVE", "sending area is not ACTIVE")

    for row in db.severance_applications.values():
        if row["sending_parcel_id"] == parcel_id and row["status"] in OPEN_APP_STATUSES:
            fail("ERR_PARCEL_HAS_OPEN_APPLICATION", "parcel already has an open severance application")

    rec = new_record(
        {
            "sending_parcel_id": parcel_id,
            "applicant_party_id": applicant_id,
            "requested_units": requested_units,
            "status": "SUBMITTED",
            "revision_round": 0,
            "screened_by_user_id": None,
            "decided_by_user_id": None,
            "certified_by_user_id": None,
            "allocated_units": 0,
            "applied_formula_version": None,
            "residual_units_retained": 0,
            "decision_note": None,
            "denial_reason": None,
        }
    )
    db.severance_applications[rec["id"]] = rec
    return respond_object(serializers.severance_application(rec), 201)


@bp.get("/tdr/severance-applications/<app_id>")
def get_application(app_id):
    require_roles(*ALL_ROLES)
    return respond_object(serializers.severance_application(get_application_or_404(app_id)))


@bp.get("/tdr/severance-applications")
def list_applications():
    require_roles(*ALL_ROLES)
    rows = match(
        list(db.severance_applications.values()),
        sending_parcel_id=filter_str("sending_parcel_id"),
        applicant_party_id=filter_str("applicant_party_id"),
        status=filter_enum("status", APP_STATUSES),
    )
    return paged(rows, serializers.severance_application)


@bp.post("/tdr/severance-applications/<app_id>/screen")
def screen_application(app_id):
    user_id, role = require_roles(REVIEWER)
    app = get_application_or_404(app_id)
    data = body()
    note = field_str(data, "screening_note", required=False)

    if app["status"] != "SUBMITTED":
        fail("ERR_APPLICATION_NOT_SCREENABLE", "application is %s" % app["status"])

    parcel = db.sending_parcels[app["sending_parcel_id"]]
    area = db.sending_areas[parcel["sending_area_id"]]
    if area["status"] != "ACTIVE":
        fail("ERR_SENDING_AREA_NOT_ACTIVE", "sending area is %s" % area["status"])
    if parcel["parcel_status"] == "FULLY_SEVERED":
        fail("ERR_PARCEL_FULLY_SEVERED", "parcel is fully severed")

    app["status"] = "UNDER_REVIEW"
    app["screened_by_user_id"] = user_id
    if note is not None:
        app["decision_note"] = note
    touch(app)
    return respond_object(serializers.severance_application(app))


@bp.post("/tdr/severance-applications/<app_id>/review-decision")
def review_decision(app_id):
    user_id, role = require_roles(REVIEWER)
    app = get_application_or_404(app_id)
    data = body()
    decision = field_enum(data, "decision", DECISIONS)
    decision_note = field_str(data, "decision_note", required=False)
    field_str(data, "denial_reason", required=False)

    if app["status"] != "UNDER_REVIEW":
        fail("ERR_APPLICATION_NOT_IN_REVIEW", "application is %s" % app["status"])

    if decision == "REQUIRE_REVISION" and int(app["revision_round"]) + 1 > MAX_REVISION_ROUNDS:
        fail("ERR_REVISION_LIMIT_EXCEEDED", "the two-round revision limit is exhausted")

    parcel = db.sending_parcels[app["sending_parcel_id"]]
    area = db.sending_areas[parcel["sending_area_id"]]

    if decision == "APPROVE":
        if area["status"] != "ACTIVE":
            fail("ERR_SENDING_AREA_NOT_ACTIVE", "sending area is %s" % area["status"])
        area_available = int(area["sending_cap_units"]) - int(area["severed_units_total"])
        if area_available <= 0:
            fail("ERR_SENDING_CAP_EXHAUSTED", "sending area capacity is exhausted")
        allocated, residual = calc.severance_allocation_grant(
            app["requested_units"], parcel["remaining_units"], area_available
        )
        if allocated <= 0:
            fail("ERR_NO_ALLOCABLE_UNITS", "the grant would allocate zero units")
        app["allocated_units"] = allocated
        app["residual_units_retained"] = residual
        app["applied_formula_version"] = area["allocation_formula_version"]
        app["status"] = "APPROVED"
    elif decision == "REQUIRE_REVISION":
        app["status"] = "REVISION_REQUESTED"
    else:
        app["status"] = "DENIED"
        app["denial_reason"] = decision_note if decision_note is not None else "DENIED_ON_REVIEW"

    app["decided_by_user_id"] = user_id
    if decision_note is not None:
        app["decision_note"] = decision_note
    touch(app)
    return respond_object(serializers.severance_application(app))


@bp.post("/tdr/severance-applications/<app_id>/resubmit")
def resubmit_application(app_id):
    user_id, role = require_roles(LANDOWNER)
    app = get_application_or_404(app_id)
    data = body()
    requested_units = field_int(data, "requested_units", minimum=1)
    note = field_str(data, "note", required=False)

    require_owner(user_id, role, app["applicant_party_id"])

    if app["status"] != "REVISION_REQUESTED":
        fail("ERR_APPLICATION_NOT_REVISABLE", "application is %s" % app["status"])
    if int(app["revision_round"]) + 1 > MAX_REVISION_ROUNDS:
        fail("ERR_REVISION_LIMIT_EXCEEDED", "the two-round revision limit is exhausted")

    app["status"] = "SUBMITTED"
    app["revision_round"] = int(app["revision_round"]) + 1
    app["requested_units"] = requested_units
    app["screened_by_user_id"] = None
    app["decided_by_user_id"] = None
    if note is not None:
        app["decision_note"] = note
    touch(app)
    return respond_object(serializers.severance_application(app))


@bp.post("/tdr/severance-applications/<app_id>/certify")
def certify(app_id):
    user_id, role = require_roles(ADMIN)
    app = get_application_or_404(app_id)
    data = body()
    field_str(data, "recording_note", required=False)

    if app["decided_by_user_id"] is not None and user_id == app["decided_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the approving reviewer may not certify this application")
    if app["status"] != "APPROVED":
        fail("ERR_APPLICATION_NOT_APPROVED", "application is %s" % app["status"])

    parcel = db.sending_parcels[app["sending_parcel_id"]]
    area = db.sending_areas[parcel["sending_area_id"]]
    if area["status"] != "ACTIVE":
        fail("ERR_SENDING_AREA_NOT_ACTIVE", "sending area is %s" % area["status"])

    cert = certify_application(app, user_id)
    return respond_object(serializers.certificate(cert), 201)
