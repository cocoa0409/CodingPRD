"""Disposal manifests (PRD 3.6)."""

from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import (ERR_FACILITY_CAPACITY_EXCEEDED,
                    ERR_WASTE_PROFILE_NOT_APPROVED, bad_request, invalid_state,
                    not_found, unprocessable)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.calculations import (EXCEPTION_THRESHOLD_PCT, recompute_facility)
from util import (dec, get_body, list_paginated, new_entity, opt_field,
                  req_field, rhu, rhu_int, touch)

bp = Blueprint("manifests", __name__)

MANIFEST_STATUSES = ["DRAFT", "ISSUED", "IN_TRANSIT", "RECEIVED", "EXCEPTION",
                     "RECONCILED", "VOIDED"]


def _get_manifest(manifest_id):
    manifest = store.manifests.get(manifest_id)
    if manifest is None:
        raise not_found("Disposal manifest not found")
    return manifest


@bp.post("/v1/manifests")
def create_manifest():
    require_roles(["ProjectManager"])
    body = get_body()
    job_id = req_field(body, "job_id")
    waste_profile_id = req_field(body, "waste_profile_id")
    estimated_gallons = req_field(body, "estimated_gallons", kind="int", gt_zero=True)
    job = store.jobs.get(job_id)
    if job is None:
        raise not_found("Job not found")
    if waste_profile_id not in store.waste_profiles:
        raise not_found("Waste profile not found")
    if job["execution_status"] not in ("IN_PROGRESS", "FIELD_COMPLETE"):
        raise invalid_state(
            "Manifests can only be created while the job is IN_PROGRESS or FIELD_COMPLETE")
    manifest = new_entity(store.manifests, {
        "job_id": job_id,
        "waste_profile_id": waste_profile_id,
        "estimated_gallons": estimated_gallons,
        "estimated_tons": None,
        "received_tons": None,
        "variance_pct": None,
        "billed_tons": None,
        "disposal_charge_cents": None,
        "resolution_note": None,
        "status": "DRAFT",
    })
    return success_object(manifest, status=201)


@bp.get("/v1/manifests")
def list_manifests():
    require_roles(ALL_ROLES)
    filters = {}
    for param in ("job_id", "waste_profile_id", "status"):
        if request.args.get(param) is not None:
            filters[param] = request.args[param]
    page, limit, offset, total = list_paginated(store.manifests, filters,
                                                request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/manifests/<manifestId>")
def get_manifest(manifestId):
    require_roles(ALL_ROLES)
    return success_object(_get_manifest(manifestId))


@bp.post("/v1/manifests/<manifestId>/issue")
def issue_manifest(manifestId):
    require_roles(["ProjectManager"])
    manifest = _get_manifest(manifestId)
    if manifest["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT manifest can be issued")
    profile = store.waste_profiles[manifest["waste_profile_id"]]
    if profile["status"] != "APPROVED":
        raise unprocessable(ERR_WASTE_PROFILE_NOT_APPROVED,
                            "The waste profile must be APPROVED to issue a manifest")
    estimated_tons = rhu(
        dec(manifest["estimated_gallons"]) * dec(profile["density_lbs_per_gal"]) / 2000, 2)
    facility = store.facilities[profile["facility_id"]]
    if dec(facility["reserved_tons"]) + estimated_tons > dec(facility["total_capacity_tons"]):
        raise unprocessable(ERR_FACILITY_CAPACITY_EXCEEDED,
                            "Issuing would exceed the facility's total capacity")
    manifest["estimated_tons"] = estimated_tons
    manifest["status"] = "ISSUED"
    touch(manifest)
    recompute_facility(facility)
    return success_object(manifest)


@bp.post("/v1/manifests/<manifestId>/depart")
def depart_manifest(manifestId):
    require_roles(["ProjectManager"])
    manifest = _get_manifest(manifestId)
    if manifest["status"] != "ISSUED":
        raise invalid_state("Only an ISSUED manifest can depart")
    manifest["status"] = "IN_TRANSIT"
    touch(manifest)
    return success_object(manifest)


@bp.post("/v1/manifests/<manifestId>/receive")
def receive_manifest(manifestId):
    require_roles(["ProjectManager"])
    body = get_body()
    received_tons = req_field(body, "received_tons", kind="number", gte_zero=True)
    manifest = _get_manifest(manifestId)
    if manifest["status"] != "IN_TRANSIT":
        raise invalid_state("Only an IN_TRANSIT manifest can be received")
    profile = store.waste_profiles[manifest["waste_profile_id"]]
    density = dec(profile["density_lbs_per_gal"])
    if profile["variance_basis"] == "WEIGHT":
        shipped_tons_est = rhu(
            dec(manifest["estimated_gallons"]) * density / 2000, 2)
        variance = rhu((received_tons - shipped_tons_est) / shipped_tons_est * 100, 2)
    else:  # VOLUME
        received_gallons = rhu(received_tons * 2000 / density, 1)
        variance = rhu(
            (received_gallons - manifest["estimated_gallons"])
            / manifest["estimated_gallons"] * 100, 2)
    manifest["received_tons"] = received_tons
    manifest["variance_pct"] = variance
    manifest["status"] = "EXCEPTION" if abs(variance) > EXCEPTION_THRESHOLD_PCT else "RECEIVED"
    touch(manifest)
    # Receipt releases the reservation, whichever branch was taken.
    facility = store.facilities[profile["facility_id"]]
    recompute_facility(facility)
    return success_object(manifest)


@bp.post("/v1/manifests/<manifestId>/reconcile")
def reconcile_manifest(manifestId):
    require_roles(["ProjectManager"])
    manifest = _get_manifest(manifestId)
    if manifest["status"] != "RECEIVED":
        raise invalid_state("Only a RECEIVED manifest can be reconciled")
    profile = store.waste_profiles[manifest["waste_profile_id"]]
    manifest["billed_tons"] = manifest["received_tons"]
    manifest["disposal_charge_cents"] = rhu_int(
        dec(manifest["billed_tons"]) * profile["disposal_rate_per_ton_cents"])
    manifest["status"] = "RECONCILED"
    touch(manifest)
    return success_object(manifest)


@bp.post("/v1/manifests/<manifestId>/resolve-exception")
def resolve_exception(manifestId):
    require_roles(["ProjectManager"])
    body = get_body()
    resolution_note = body.get("resolution_note")
    if not isinstance(resolution_note, str) or resolution_note == "":
        raise bad_request("resolution_note is required")
    adjusted_tons = opt_field(body, "adjusted_tons", kind="number", gte_zero=True)
    manifest = _get_manifest(manifestId)
    if manifest["status"] != "EXCEPTION":
        raise invalid_state("Only an EXCEPTION manifest can be resolved")
    profile = store.waste_profiles[manifest["waste_profile_id"]]
    manifest["resolution_note"] = resolution_note
    manifest["billed_tons"] = adjusted_tons if adjusted_tons is not None else manifest["received_tons"]
    manifest["disposal_charge_cents"] = rhu_int(
        dec(manifest["billed_tons"]) * profile["disposal_rate_per_ton_cents"])
    manifest["status"] = "RECONCILED"
    touch(manifest)
    return success_object(manifest)


@bp.post("/v1/manifests/<manifestId>/void")
def void_manifest(manifestId):
    require_roles(["ComplianceOfficer"])
    manifest = _get_manifest(manifestId)
    if manifest["status"] not in ("DRAFT", "ISSUED"):
        raise invalid_state("Only a DRAFT or ISSUED manifest can be voided")
    was_issued = manifest["status"] == "ISSUED"
    manifest["status"] = "VOIDED"
    touch(manifest)
    if was_issued:
        profile = store.waste_profiles.get(manifest["waste_profile_id"])
        facility = store.facilities.get(profile["facility_id"]) if profile else None
        if facility is not None:
            recompute_facility(facility)
    return success_object(manifest)
