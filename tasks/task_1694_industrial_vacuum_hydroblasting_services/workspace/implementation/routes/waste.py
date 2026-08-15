"""Waste profiles and disposal facilities (PRD 2.9, 3.6)."""

from flask import Blueprint, request

from db import store
from errors import (ERR_SEGREGATION_OF_DUTIES, invalid_state, not_found,
                    unprocessable)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.calculations import recompute_facility
from util import (get_body, list_paginated, new_entity, req_field, touch)

bp = Blueprint("waste", __name__)

HAZARD_CLASSES = ["NON_HAZ", "HAZ", "SPECIAL"]
VARIANCE_BASES = ["VOLUME", "WEIGHT"]
PROFILE_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "SUSPENDED"]


def _get_profile(profile_id):
    profile = store.waste_profiles.get(profile_id)
    if profile is None:
        raise not_found("Waste profile not found")
    return profile


@bp.post("/v1/waste-profiles")
def create_waste_profile():
    require_roles(["ComplianceOfficer"])
    body = get_body()
    site_id = req_field(body, "site_id")
    facility_id = req_field(body, "facility_id")
    waste_code = req_field(body, "waste_code")
    hazard_class = req_field(body, "hazard_class", choices=HAZARD_CLASSES)
    density = req_field(body, "density_lbs_per_gal", kind="number", gt_zero=True)
    rate = req_field(body, "disposal_rate_per_ton_cents", kind="int", gte_zero=True)
    variance_basis = req_field(body, "variance_basis", choices=VARIANCE_BASES)
    if site_id not in store.sites:
        raise not_found("Site not found")
    if facility_id not in store.facilities:
        raise not_found("Disposal facility not found")
    profile = new_entity(store.waste_profiles, {
        "site_id": site_id,
        "facility_id": facility_id,
        "waste_code": waste_code,
        "hazard_class": hazard_class,
        "density_lbs_per_gal": density,
        "disposal_rate_per_ton_cents": rate,
        "variance_basis": variance_basis,
        "submitted_by": None,
        "status": "DRAFT",
    })
    return success_object(profile, status=201)


@bp.get("/v1/waste-profiles")
def list_waste_profiles():
    require_roles(ALL_ROLES)
    filters = {}
    for param in ("site_id", "facility_id", "status"):
        if request.args.get(param) is not None:
            filters[param] = request.args[param]
    page, limit, offset, total = list_paginated(store.waste_profiles, filters,
                                                request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/waste-profiles/<profileId>")
def get_waste_profile(profileId):
    require_roles(ALL_ROLES)
    return success_object(_get_profile(profileId))


@bp.post("/v1/waste-profiles/<profileId>/submit")
def submit_waste_profile(profileId):
    user_id, _ = require_roles(["ComplianceOfficer"])
    profile = _get_profile(profileId)
    if profile["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT waste profile can be submitted")
    profile["submitted_by"] = user_id
    profile["status"] = "SUBMITTED"
    touch(profile)
    return success_object(profile)


@bp.post("/v1/waste-profiles/<profileId>/approve")
def approve_waste_profile(profileId):
    user_id, _ = require_roles(["EnvironmentalApprover"])
    profile = _get_profile(profileId)
    if profile["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED waste profile can be approved")
    if user_id == profile["submitted_by"]:
        raise unprocessable(ERR_SEGREGATION_OF_DUTIES,
                            "The approver must differ from the submitter")
    profile["status"] = "APPROVED"
    touch(profile)
    return success_object(profile)


@bp.post("/v1/waste-profiles/<profileId>/suspend")
def suspend_waste_profile(profileId):
    require_roles(["EnvironmentalApprover"])
    profile = _get_profile(profileId)
    if profile["status"] != "APPROVED":
        raise invalid_state("Only an APPROVED waste profile can be suspended")
    # Cascade: void DRAFT/ISSUED manifests; ISSUED voids release reservations.
    released = False
    for m in store.manifests.values():
        if m["waste_profile_id"] == profileId and m["status"] in ("DRAFT", "ISSUED"):
            released = released or m["status"] == "ISSUED"
            m["status"] = "VOIDED"
            touch(m)
    profile["status"] = "SUSPENDED"
    touch(profile)
    if released:
        facility = store.facilities.get(profile["facility_id"])
        if facility is not None:
            recompute_facility(facility)
    return success_object(profile)


@bp.post("/v1/waste-profiles/<profileId>/reinstate")
def reinstate_waste_profile(profileId):
    require_roles(["EnvironmentalApprover"])
    profile = _get_profile(profileId)
    if profile["status"] != "SUSPENDED":
        raise invalid_state("Only a SUSPENDED waste profile can be reinstated")
    profile["status"] = "APPROVED"
    touch(profile)
    return success_object(profile)


# --- Disposal facilities -----------------------------------------------------

@bp.post("/v1/disposal-facilities")
def create_facility():
    require_roles(["PlatformAdmin"])
    body = get_body()
    name = req_field(body, "name")
    epa_id = req_field(body, "epa_id")
    total_capacity = req_field(body, "total_capacity_tons", kind="number",
                               gte_zero=True)
    facility = new_entity(store.facilities, {
        "name": name,
        "epa_id": epa_id,
        "total_capacity_tons": total_capacity,
        "reserved_tons": 0,
        "posture": "AVAILABLE",
    })
    return success_object(facility, status=201)


@bp.get("/v1/disposal-facilities")
def list_facilities():
    require_roles(ALL_ROLES)
    page, limit, offset, total = list_paginated(store.facilities, {}, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/disposal-facilities/<facilityId>")
def get_facility(facilityId):
    require_roles(ALL_ROLES)
    facility = store.facilities.get(facilityId)
    if facility is None:
        raise not_found("Disposal facility not found")
    return success_object(facility)
