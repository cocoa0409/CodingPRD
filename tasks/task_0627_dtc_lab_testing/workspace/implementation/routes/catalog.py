"""Test offerings, panel bundles, patients (PRD §3.1)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_role
from response import success, list_success
from services.common import (
    serialize, serialize_list, get_json, require_found, require_str,
    require_int, require_bool, require_number, require_enum, paginate,
)

bp = Blueprint("catalog", __name__)

SPECIMEN_TYPES = {"BLOOD", "URINE", "SALIVA"}


# ---------------------------------------------------------------------------
# Test offerings
# ---------------------------------------------------------------------------
@bp.route("/catalog/test-offerings", methods=["POST"])
def create_offering():
    require_role(["CatalogAdmin"])
    body = get_json()
    test_code = require_str(body, "test_code")
    display_name = require_str(body, "display_name")
    list_price = require_int(body, "list_price_cents", positive=True)
    specimen_type = body.get("specimen_type")
    require_enum(specimen_type, SPECIMEN_TYPES, "specimen_type")
    home_kit_eligible = require_bool(body, "home_kit_eligible", required=False, default=False)
    requires_fasting = require_bool(body, "requires_fasting", required=False, default=False)
    critical_low = require_number(body, "critical_low", required=False)
    critical_high = require_number(body, "critical_high", required=False)
    ref_low = require_number(body, "ref_low", required=False)
    ref_high = require_number(body, "ref_high", required=False)

    # test_code unique among non-ARCHIVED offerings.
    for o in db.all_rows("test_offerings"):
        if o["status"] != "ARCHIVED" and o["test_code"] == test_code:
            raise err("ERR_DUPLICATE_CODE", "test_code already in use")

    rec = db.new_record({
        "test_code": test_code,
        "display_name": display_name,
        "list_price_cents": list_price,
        "specimen_type": specimen_type,
        "home_kit_eligible": home_kit_eligible,
        "requires_fasting": requires_fasting,
        "critical_low": critical_low,
        "critical_high": critical_high,
        "ref_low": ref_low,
        "ref_high": ref_high,
        "status": "ACTIVE",
    })
    db.insert("test_offerings", rec)
    return success(serialize(rec), status=201)


@bp.route("/catalog/test-offerings", methods=["GET"])
def list_offerings():
    require_role(["CatalogAdmin", "Patient", "LabTech", "PhlebotomyTech", "OrderingPhysician"])
    rows = db.sorted_rows(db.all_rows("test_offerings"))
    status_filter = request.args.get("status")
    include_archived = request.args.get("include_archived", "").lower() == "true"
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter]
    elif not include_archived:
        rows = [r for r in rows if r["status"] != "ARCHIVED"]
    page, limit, offset, total = paginate(rows)
    return list_success(serialize_list(page), limit, offset, total)


@bp.route("/catalog/test-offerings/<rid>", methods=["GET"])
def get_offering(rid):
    require_role(["CatalogAdmin", "Patient", "LabTech", "PhlebotomyTech", "OrderingPhysician"])
    rec = require_found("test_offerings", rid)
    return success(serialize(rec))


@bp.route("/catalog/test-offerings/<rid>/archive", methods=["POST"])
def archive_offering(rid):
    require_role(["CatalogAdmin"])
    rec = require_found("test_offerings", rid)
    rec["status"] = "ARCHIVED"
    db.touch(rec)
    return success(serialize(rec))


# ---------------------------------------------------------------------------
# Panel bundles
# ---------------------------------------------------------------------------
@bp.route("/catalog/panel-bundles", methods=["POST"])
def create_bundle():
    require_role(["CatalogAdmin"])
    body = get_json()
    bundle_code = require_str(body, "bundle_code")
    display_name = require_str(body, "display_name")
    members = body.get("member_test_codes")
    bundle_price = require_int(body, "bundle_price_cents", positive=True)

    if not isinstance(members, list) or not all(isinstance(m, str) for m in members):
        raise err("ERR_INVALID_REQUEST", "member_test_codes must be a list of strings")

    # bundle_code unique among non-ARCHIVED bundles. (Duplicate-code check is a
    # 409 and the body-shape check above is 422; per validation ordering the
    # body-shape check runs first, then uniqueness.)
    for b in db.all_rows("panel_bundles"):
        if b["status"] != "ARCHIVED" and b["bundle_code"] == bundle_code:
            raise err("ERR_DUPLICATE_CODE", "bundle_code already in use")

    # >= 2 distinct members, each referencing an ACTIVE offering at create time.
    distinct = set(members)
    if len(distinct) < 2:
        raise err("ERR_INVALID_BUNDLE_MEMBERS", "Bundle must have >= 2 distinct members")
    active_codes = {o["test_code"] for o in db.all_rows("test_offerings") if o["status"] == "ACTIVE"}
    for code in distinct:
        if code not in active_codes:
            raise err("ERR_INVALID_BUNDLE_MEMBERS", "Member %s is not an ACTIVE offering" % code)

    rec = db.new_record({
        "bundle_code": bundle_code,
        "display_name": display_name,
        "member_test_codes": list(members),
        "bundle_price_cents": bundle_price,
        "status": "ACTIVE",
    })
    db.insert("panel_bundles", rec)
    return success(serialize(rec), status=201)


@bp.route("/catalog/panel-bundles", methods=["GET"])
def list_bundles():
    require_role(["CatalogAdmin", "Patient", "LabTech", "PhlebotomyTech", "OrderingPhysician"])
    rows = db.sorted_rows(db.all_rows("panel_bundles"))
    status_filter = request.args.get("status")
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter]
    page, limit, offset, total = paginate(rows)
    return list_success(serialize_list(page), limit, offset, total)


@bp.route("/catalog/panel-bundles/<rid>", methods=["GET"])
def get_bundle(rid):
    require_role(["CatalogAdmin", "Patient"])
    rec = require_found("panel_bundles", rid)
    return success(serialize(rec))


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------
@bp.route("/catalog/patients", methods=["POST"])
def create_patient():
    require_role(["CatalogAdmin", "Patient"])
    body = get_json()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    dob = require_str(body, "date_of_birth")
    state_code = require_str(body, "state_code")
    hsa_balance = require_int(body, "hsa_balance_cents", required=False, non_negative=True)
    if hsa_balance is None:
        hsa_balance = 0
    consent = require_bool(body, "consent_share_results", required=False, default=False)

    for p in db.all_rows("patients"):
        if p["email"] == email:
            raise err("ERR_DUPLICATE_CODE", "email already in use")

    rec = db.new_record({
        "email": email,
        "full_name": full_name,
        "date_of_birth": dob,
        "state_code": state_code,
        "hsa_balance_cents": hsa_balance,
        "consent_share_results": consent,
        "status": "ACTIVE",
    })
    db.insert("patients", rec)
    return success(serialize(rec), status=201)


@bp.route("/catalog/patients/<rid>", methods=["GET"])
def get_patient(rid):
    user_id, role = require_role(["CatalogAdmin", "Patient"])
    rec = require_found("patients", rid)
    if role == "Patient" and user_id != rec["id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    return success(serialize(rec))


@bp.route("/catalog/patients/<rid>", methods=["PATCH"])
def update_patient(rid):
    user_id, role = require_role(["CatalogAdmin", "Patient"])
    rec = require_found("patients", rid)
    if role == "Patient" and user_id != rec["id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    body = get_json()
    changed = False
    if "consent_share_results" in body:
        consent = require_bool(body, "consent_share_results")
        rec["consent_share_results"] = consent
        changed = True
    if "hsa_balance_cents" in body:
        bal = require_int(body, "hsa_balance_cents", non_negative=True)
        rec["hsa_balance_cents"] = bal
        changed = True
    if changed:
        db.touch(rec)
    return success(serialize(rec))
