from flask import Blueprint, request

from db import store, now_iso
import errors
import middleware
import response
from services import validate
from services import calc
from services.entities import (
    stamp_create, touch, get_application, get_business, get_activity_category,
    create_fee_assessment, parse_iso8601, add_months,
)
from services.serialize import public, public_list

bp = Blueprint("applications", __name__)


# ---------------------------------------------------------------------------
def _open_application_fee_assessment(app_id):
    """Return the (single) APPLICATION_FEE assessment for an application, if any."""
    for fa in store.fee_assessments.values():
        if fa.get("application_id") == app_id and fa.get("kind") == "APPLICATION_FEE":
            return fa
    return None


def _passed_inspection_count(app_id):
    return sum(1 for i in store.inspections.values()
               if i.get("application_id") == app_id and i.get("result") == "PASSED")


def _latest_passed_inspection(app_id):
    passed = [i for i in store.inspections.values()
              if i.get("application_id") == app_id and i.get("result") == "PASSED"]
    passed.sort(key=lambda r: r["created_at"])
    return passed[-1] if passed else None


# ---------------------------------------------------------------------------
@bp.route("/applications", methods=["POST"])
def create_application():
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant"])
    data = validate.body()

    business_id = validate.require_str(data, "business_id")
    activity_category_id = validate.require_str(data, "activity_category_id")
    declared_employee_count = validate.require_int(data, "declared_employee_count")
    requested_zone_code = validate.require_str(data, "requested_zone_code")

    # existence (404) before semantic bounds
    get_business(business_id)
    get_activity_category(activity_category_id)

    # semantic bounds (422)
    if declared_employee_count < 0:
        raise errors.validation("declared_employee_count must be >= 0")

    rec = {
        "business_id": business_id,
        "activity_category_id": activity_category_id,
        "declared_employee_count": declared_employee_count,
        "requested_zone_code": requested_zone_code,
        "status": "DRAFT",
        "zoning_status": "PENDING",
        "estimated_fee": 0,
        "reviewed_by_user_id": None,
        "license_id": None,
    }
    stamp_create(rec)
    store.applications[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@bp.route("/applications/<aid>", methods=["GET"])
def get_one(aid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer", "InspectionOfficer"])
    rec = get_application(aid)
    return response.object_response(public(rec), 200)


@bp.route("/applications", methods=["GET"])
def list_all():
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer", "InspectionOfficer"])
    limit, offset = middleware.parse_pagination()
    business_id = request.args.get("business_id")
    activity_category_id = request.args.get("activity_category_id")
    license_id = request.args.get("license_id")
    items = list(store.applications.values())
    if business_id is not None:
        items = [a for a in items if a.get("business_id") == business_id]
    if activity_category_id is not None:
        items = [a for a in items if a.get("activity_category_id") == activity_category_id]
    if license_id is not None:
        items = [a for a in items if a.get("license_id") == license_id]
    items.sort(key=lambda r: r["created_at"])
    page, total = middleware.paginate(items, limit, offset)
    return response.array_response(public_list(page), limit, offset, total, 200)


# ---------------------------------------------------------------------------
@bp.route("/applications/<aid>/submit", methods=["POST"])
def submit(aid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant"])
    app = get_application(aid)

    # state legality (409) — submit defined only from DRAFT
    if app["status"] != "DRAFT":
        raise errors.invalid_state("Application must be DRAFT to submit")

    # business-rule tier: business must be in GOOD standing
    business = get_business(app["business_id"])
    if business["standing"] != "GOOD":
        raise errors.ApiError(errors.ERR_BUSINESS_NOT_IN_GOOD_STANDING, 409,
                              "Business not in good standing")

    cat = get_activity_category(app["activity_category_id"])
    variance = app["zoning_status"] == "VARIANCE_REQUIRED"  # false at submission
    app["estimated_fee"] = calc.application_fee_estimate(
        cat["risk_tier"], app["declared_employee_count"], variance)
    app["status"] = "SUBMITTED"
    touch(app)

    create_fee_assessment("APPLICATION_FEE", app["estimated_fee"],
                          application_id=app["id"], settled=False)
    return response.object_response(public(app), 200)


@bp.route("/applications/<aid>/zoning-check", methods=["POST"])
def zoning_check(aid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    app = get_application(aid)

    if app["status"] != "SUBMITTED":
        raise errors.invalid_state("Zoning check is only defined from SUBMITTED")

    cat = get_activity_category(app["activity_category_id"])
    in_allowed = app["requested_zone_code"] in cat["allowed_zones"]

    if in_allowed:
        app["zoning_status"] = "CLEARED"
        app["status"] = "ZONING_CLEARED"
        touch(app)
        return response.object_response(public(app), 200)

    # requested zone NOT in allowed zones
    if cat["requires_zoning_check"]:
        # variance branch
        app["zoning_status"] = "VARIANCE_REQUIRED"
        app["status"] = "VARIANCE_REQUIRED"
        app["estimated_fee"] = calc.application_fee_estimate(
            cat["risk_tier"], app["declared_employee_count"], True)
        # raise the open APPLICATION_FEE assessment amount to match
        fa = _open_application_fee_assessment(app["id"])
        if fa is not None:
            fa["amount"] = app["estimated_fee"]
            touch(fa)
        touch(app)
        return response.object_response(public(app), 200)

    # no variance path -> denied
    raise errors.ApiError(errors.ERR_ZONING_DENIED, 409,
                          "Requested zone not allowed and no variance path")


@bp.route("/applications/<aid>/approve", methods=["POST"])
def approve(aid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    app = get_application(aid)

    if app["status"] not in ("ZONING_CLEARED", "VARIANCE_REQUIRED"):
        raise errors.invalid_state("Application must be ZONING_CLEARED or VARIANCE_REQUIRED to approve")

    cat = get_activity_category(app["activity_category_id"])
    if _passed_inspection_count(app["id"]) < cat["required_inspection_count"]:
        raise errors.ApiError(errors.ERR_INSPECTION_PREREQUISITE_NOT_MET, 409,
                              "Not enough PASSED inspections for approval")

    app["reviewed_by_user_id"] = ident.user_id
    app["status"] = "APPROVED"
    touch(app)

    # provisional compliance risk score for the business (open_violation_count = 0)
    business = get_business(app["business_id"])
    business["compliance_risk_score"] = calc.compliance_risk_score(
        cat["activity_base_risk"], 0, business["standing"], business["prior_revocation_flag"])
    touch(business)

    return response.object_response(public(app), 200)


@bp.route("/applications/<aid>/reject", methods=["POST"])
def reject(aid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    app = get_application(aid)

    if app["status"] not in ("SUBMITTED", "ZONING_CLEARED", "VARIANCE_REQUIRED"):
        raise errors.invalid_state("Application not in a rejectable state")

    app["reviewed_by_user_id"] = ident.user_id
    app["status"] = "REJECTED"
    touch(app)

    # compensation: reverse the application fee charge
    create_fee_assessment("REVERSAL", -app["estimated_fee"],
                          application_id=app["id"], settled=False)
    return response.object_response(public(app), 200)


@bp.route("/applications/<aid>/withdraw", methods=["POST"])
def withdraw(aid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant"])
    app = get_application(aid)

    if app["status"] not in ("DRAFT", "SUBMITTED", "ZONING_CLEARED", "VARIANCE_REQUIRED"):
        raise errors.invalid_state("Application not in a withdrawable state")

    app["status"] = "WITHDRAWN"
    touch(app)

    # if an unsettled APPLICATION_FEE assessment exists, reverse it
    fa = _open_application_fee_assessment(app["id"])
    if fa is not None and not fa.get("settled"):
        create_fee_assessment("REVERSAL", -app["estimated_fee"],
                              application_id=app["id"], settled=False)
    return response.object_response(public(app), 200)


@bp.route("/applications/<aid>/issue", methods=["POST"])
def issue(aid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    app = get_application(aid)

    if app["status"] != "APPROVED":
        raise errors.invalid_state("Application must be APPROVED to issue")

    # segregation of duties: issuing officer must differ from every inspector
    inspector_ids = {i.get("inspector_user_id") for i in store.inspections.values()
                     if i.get("application_id") == app["id"]}
    if ident.user_id in inspector_ids:
        raise errors.ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                              "Issuing officer also inspected this application")

    cat = get_activity_category(app["activity_category_id"])

    # final fee: verified employee count from latest PASSED inspection
    latest = _latest_passed_inspection(app["id"])
    verified = int(latest.get("verified_employee_count") or 0) if latest else 0
    passed_count = _passed_inspection_count(app["id"])
    variance = app["zoning_status"] == "VARIANCE_REQUIRED"
    final_fee = calc.issuance_fee_final(cat["risk_tier"], verified, variance, passed_count)

    now = store.clock_now
    expires = add_months(now, cat["term_months"])

    lic = {
        "business_id": app["business_id"],
        "application_id": app["id"],
        "activity_category_id": app["activity_category_id"],
        "status": "ACTIVE",
        "issued_on": now_iso(now),
        "expires_on": now_iso(expires),
        "final_fee": final_fee,
        "renewal_count": 0,
    }
    stamp_create(lic)
    store.licenses[lic["id"]] = lic

    app["license_id"] = lic["id"]
    app["status"] = "ISSUED"
    touch(app)

    create_fee_assessment("ISSUANCE_FEE", final_fee, license_id=lic["id"], settled=False)
    return response.object_response(public(lic), 201)


# ---------------------------------------------------------------------------
@bp.route("/applications/<aid>/inspections", methods=["GET"])
def list_inspections(aid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer", "InspectionOfficer", "Applicant"])
    get_application(aid)
    limit, offset = middleware.parse_pagination()
    items = [i for i in store.inspections.values() if i.get("application_id") == aid]
    items.sort(key=lambda r: r["created_at"])
    page, total = middleware.paginate(items, limit, offset)
    return response.array_response(public_list(page), limit, offset, total, 200)


@bp.route("/applications/<aid>/fee-assessments", methods=["GET"])
def list_fee_assessments(aid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer", "Applicant"])
    get_application(aid)
    limit, offset = middleware.parse_pagination()
    items = [f for f in store.fee_assessments.values() if f.get("application_id") == aid]
    items.sort(key=lambda r: r["created_at"])
    page, total = middleware.paginate(items, limit, offset)
    return response.array_response(public_list(page), limit, offset, total, 200)
