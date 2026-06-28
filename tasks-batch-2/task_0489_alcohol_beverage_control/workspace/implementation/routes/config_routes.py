"""Configuration: license classes, quota regions, applicants, premises.
Plus the computed quota-status read and the moratorium toggle."""
from flask import Blueprint

import errors
from auth import require_auth, ALL_READERS
from db import db, new_id, common_fields, touch
from helpers import (
    body, paginate, sort_created, out, out_list, get_or_404,
    find_license_class_by_code, find_quota_region_by_code,
)
import validate
from quota import quota_status
from response import ok, created, listed

bp = Blueprint("config", __name__)

PREMISE_TYPES = {"ON_PREMISE", "OFF_PREMISE", "MANUFACTURER"}
RENEWAL_CYCLES = {12, 24, 36}
ZONING_DISTRICTS = {"COMMERCIAL", "MIXED_USE", "RESIDENTIAL", "INDUSTRIAL"}
CODE_PATTERN = r"^[A-Z]{2,3}_[0-9]{1,3}$"
PERIOD_PATTERN = r"^[0-9]{4}-Q[1-4]$"


# --- License classes ---------------------------------------------------------
@bp.route("/license-classes", methods=["POST"])
def create_license_class():
    require_auth(["Director"])
    data = body()
    code = validate.require_str(data, "code")
    validate.match_pattern(code, CODE_PATTERN, "code")
    if find_license_class_by_code(code) is not None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Duplicate license class code")
    premise_type = validate.require_enum(data, "premise_type", PREMISE_TYPES)
    quota_managed = validate.opt_bool(data, "quota_managed", True)
    base_fee_cents = validate.require_int(data, "base_fee_cents", minimum=0)
    renewal_cycle_months = validate.require_int(data, "renewal_cycle_months")
    if renewal_cycle_months not in RENEWAL_CYCLES:
        raise errors.err(errors.ERR_INVALID_REQUEST, "renewal_cycle_months must be 12, 24, or 36")
    requires_zoning = validate.opt_bool(data, "requires_zoning", True)
    max_servers = validate.require_int(data, "max_servers_per_license", minimum=0)

    ent = {"id": new_id(), "code": code, "premise_type": premise_type,
           "quota_managed": quota_managed, "base_fee_cents": base_fee_cents,
           "renewal_cycle_months": renewal_cycle_months, "requires_zoning": requires_zoning,
           "max_servers_per_license": max_servers}
    ent.update(common_fields())
    db.license_classes[ent["id"]] = ent
    return created(out(ent))


@bp.route("/license-classes/<id>", methods=["GET"])
def get_license_class(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.license_classes, id)
    return ok(out(ent))


@bp.route("/license-classes", methods=["GET"])
def list_license_classes():
    require_auth(ALL_READERS)
    from flask import request
    items = list(db.license_classes.values())
    code = request.args.get("code")
    if code is not None:
        items = [e for e in items if e["code"] == code]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


# --- Quota regions -----------------------------------------------------------
@bp.route("/quota-regions", methods=["POST"])
def create_quota_region():
    require_auth(["Director"])
    data = body()
    region_code = validate.require_str(data, "region_code")
    if find_quota_region_by_code(region_code) is not None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Duplicate region_code")
    population = validate.require_int(data, "population", minimum=0)
    persons_per_license = validate.require_int(data, "persons_per_license", minimum=1)
    moratorium = validate.opt_bool(data, "moratorium", False)

    ent = {"id": new_id(), "region_code": region_code, "population": population,
           "persons_per_license": persons_per_license, "moratorium": moratorium}
    ent.update(common_fields())
    db.quota_regions[ent["id"]] = ent
    return created(out(ent))


@bp.route("/quota-regions/<id>", methods=["GET"])
def get_quota_region(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.quota_regions, id)
    return ok(out(ent))


@bp.route("/quota-regions", methods=["GET"])
def list_quota_regions():
    require_auth(ALL_READERS)
    from flask import request
    items = list(db.quota_regions.values())
    region_code = request.args.get("region_code")
    if region_code is not None:
        items = [e for e in items if e["region_code"] == region_code]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/quota-regions/<id>/quota-status", methods=["GET"])
def get_quota_status(id):
    require_auth(ALL_READERS)
    region = get_or_404(db.quota_regions, id)
    from flask import request
    license_class_code = request.args.get("license_class_code")
    if license_class_code is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing license_class_code")
    lc = find_license_class_by_code(license_class_code)
    if lc is None:
        raise errors.err(errors.ERR_NOT_FOUND, "License class not found")
    cap, used, available = quota_status(region["region_code"], license_class_code, lc)
    return ok({
        "region_code": region["region_code"],
        "license_class_code": license_class_code,
        "cap": cap, "used": used, "available": available,
    })


@bp.route("/quota-regions/<id>/moratorium", methods=["PATCH"])
def toggle_moratorium(id):
    require_auth(["Director"])
    region = get_or_404(db.quota_regions, id)
    data = body()
    moratorium = validate.require_bool(data, "moratorium")
    # OCC: moratorium toggle advances region version and accepts
    # expected_region_version. A mismatch is a stale-region rejection.
    if "expected_region_version" in data and data["expected_region_version"] is not None:
        expected = data["expected_region_version"]
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise errors.err(errors.ERR_INVALID_REQUEST, "expected_region_version must be an integer")
        if expected != region["version"]:
            raise errors.err(errors.ERR_STALE_REGION_VERSION, "Stale region version")
    region["moratorium"] = moratorium
    touch(region)
    return ok(out(region))


# --- Applicants --------------------------------------------------------------
@bp.route("/applicants", methods=["POST"])
def create_applicant():
    require_auth(["Director", "LicensingExaminer"])
    data = body()
    legal_name = validate.require_str(data, "legal_name")
    felony_flag = validate.opt_bool(data, "felony_flag", False)
    ent = {"id": new_id(), "legal_name": legal_name, "disqualified": False,
           "felony_flag": felony_flag}
    ent.update(common_fields())
    db.applicants[ent["id"]] = ent
    return created(out(ent))


@bp.route("/applicants/<id>", methods=["GET"])
def get_applicant(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.applicants, id)
    return ok(out(ent))


@bp.route("/applicants/<id>/premises", methods=["GET"])
def list_applicant_premises(id):
    require_auth(ALL_READERS)
    get_or_404(db.applicants, id)
    items = [p for p in db.premises.values() if p["applicant_id"] == id]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/applicants/<id>/applications", methods=["GET"])
def list_applicant_applications(id):
    require_auth(ALL_READERS)
    get_or_404(db.applicants, id)
    items = [a for a in db.license_applications.values() if a["applicant_id"] == id]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/applicants/<id>/transfer-requests", methods=["GET"])
def list_applicant_transfers(id):
    require_auth(ALL_READERS)
    get_or_404(db.applicants, id)
    items = [t for t in db.transfer_requests.values() if t["new_applicant_id"] == id]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


# --- Premises ----------------------------------------------------------------
@bp.route("/premises", methods=["POST"])
def create_premise():
    require_auth(["Director", "LicensingExaminer", "Applicant"])
    data = body()
    applicant_id = validate.require_str(data, "applicant_id")
    region_code = validate.require_str(data, "region_code")
    # Existence of body FKs (priority 3) before further well-formedness.
    if applicant_id not in db.applicants:
        raise errors.err(errors.ERR_NOT_FOUND, "Applicant not found")
    if find_quota_region_by_code(region_code) is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Quota region not found")
    street_address = validate.require_str(data, "street_address")
    distance = validate.require_int(data, "distance_to_school_m", minimum=0)
    zoning_district = validate.require_enum(data, "zoning_district", ZONING_DISTRICTS)

    ent = {"id": new_id(), "applicant_id": applicant_id, "region_code": region_code,
           "street_address": street_address, "distance_to_school_m": distance,
           "zoning_district": zoning_district}
    ent.update(common_fields())
    db.premises[ent["id"]] = ent
    return created(out(ent))


@bp.route("/premises/<id>", methods=["GET"])
def get_premise(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.premises, id)
    return ok(out(ent))


@bp.route("/premises/<id>/transfer-requests", methods=["GET"])
def list_premise_transfers(id):
    require_auth(ALL_READERS)
    get_or_404(db.premises, id)
    items = [t for t in db.transfer_requests.values() if t["new_premise_id"] == id]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)
