"""Financial aid profile and aid offer routes."""

from flask import Blueprint, request

import db
import errors
import response as resp
import util
from middleware import require_auth
from routes._helpers import get_json_body, optional_field, require_field
from services import calculations
from services.serializers import serialize_aid_offer, serialize_fa_profile


bp = Blueprint("financial_aid", __name__)


VALID_AID_VARIANTS = frozenset({"FEDERAL", "INSTITUTIONAL"})


# --------------------------------------------------------------------------- #
# POST /financial-aid-profiles (Applicant)
# --------------------------------------------------------------------------- #

@bp.route("/financial-aid-profiles", methods=["POST"])
@require_auth(["Applicant"])
def create_fa_profile():
    body = get_json_body()
    applicant_id = require_field(body, "applicant_id", kind="string")
    fafsa = require_field(body, "fafsa_efc_cents", kind="integer")
    family = require_field(body, "family_income_cents", kind="integer")
    css = optional_field(body, "css_efc_cents", kind="integer", default=None)

    applicant = db.applicants.get(applicant_id)
    if applicant is None:
        errors.raise_error(errors.ERR_FK_NOT_FOUND, "Applicant not found.")

    user_id = request.headers.get("X-User-ID")
    if user_id != applicant_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Applicants can only create their own financial aid profile.")

    if fafsa < 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'fafsa_efc_cents' must be >= 0.")
    if family < 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'family_income_cents' must be >= 0.")
    if css is not None and css < 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'css_efc_cents' must be >= 0 or null.")

    # Uniqueness per applicant
    for existing in db.financial_aid_profiles.values():
        if existing["applicant_id"] == applicant_id:
            errors.raise_error(errors.ERR_DUPLICATE_RESOURCE,
                               "Applicant already has a financial aid profile.")

    row = {
        "applicant_id": applicant_id,
        "fafsa_efc_cents": fafsa,
        "css_efc_cents": css,
        "family_income_cents": family,
        "status": "DRAFT",
    }
    util.stamp_create(row)
    db.financial_aid_profiles[row["id"]] = row
    return resp.success_object(serialize_fa_profile(row), http_status=201)


# --------------------------------------------------------------------------- #
# POST /financial-aid-profiles/{id}/submit (Applicant)
# --------------------------------------------------------------------------- #

@bp.route("/financial-aid-profiles/<profile_id>/submit", methods=["POST"])
@require_auth(["Applicant"])
def submit_fa_profile(profile_id):
    row = db.financial_aid_profiles.get(profile_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND, "Profile not found.")

    user_id = request.headers.get("X-User-ID")
    if row["applicant_id"] != user_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Applicants can only submit their own financial aid profile.")

    if row["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Profile is not in DRAFT state.")
    if row.get("fafsa_efc_cents") is None or row.get("family_income_cents") is None:
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Profile is missing required fields.")

    row["status"] = "SUBMITTED"
    util.stamp_update(row)
    return resp.success_object(serialize_fa_profile(row))


# --------------------------------------------------------------------------- #
# GET /financial-aid-profiles/{id}
# --------------------------------------------------------------------------- #

@bp.route("/financial-aid-profiles/<profile_id>", methods=["GET"])
@require_auth(["Applicant", "FinancialAidOfficer", "PlatformAdmin"])
def get_fa_profile(profile_id):
    row = db.financial_aid_profiles.get(profile_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND, "Profile not found.")

    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role == "Applicant" and row["applicant_id"] != user_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Applicants can only read their own financial aid profile.")
    return resp.success_object(serialize_fa_profile(row))


# --------------------------------------------------------------------------- #
# Aid offer helpers
# --------------------------------------------------------------------------- #

def _resolve_fa_profile_for_application(application):
    """Find the SUBMITTED FinancialAidProfile for the application's applicant."""
    for profile in db.financial_aid_profiles.values():
        if profile["applicant_id"] == application["applicant_id"]:
            return profile
    return None


def _check_institutional_eligibility(application, variant):
    if variant != "INSTITUTIONAL":
        return
    school = db.schools.get(application["school_id"])
    if school is None or not school.get("requires_css_profile"):
        errors.raise_error(
            errors.ERR_INSTITUTIONAL_VARIANT_INELIGIBLE,
            "INSTITUTIONAL variant requires School.requires_css_profile=true.",
        )
    profile = _resolve_fa_profile_for_application(application)
    if profile is None or profile.get("css_efc_cents") is None:
        errors.raise_error(
            errors.ERR_INSTITUTIONAL_VARIANT_INELIGIBLE,
            "INSTITUTIONAL variant requires a non-null css_efc_cents on the applicant's profile.",
        )


# --------------------------------------------------------------------------- #
# POST /aid-offers (FinancialAidOfficer)
# --------------------------------------------------------------------------- #

@bp.route("/aid-offers", methods=["POST"])
@require_auth(["FinancialAidOfficer"])
def create_aid_offer():
    body = get_json_body()
    application_id = require_field(body, "application_id", kind="string")
    coa = require_field(body, "cost_of_attendance_cents", kind="integer")
    variant = require_field(body, "variant", kind="string")
    grant = require_field(body, "grant_cents", kind="integer")
    loan = require_field(body, "loan_cents", kind="integer")
    work_study = require_field(body, "work_study_cents", kind="integer")
    expected_version = require_field(body, "expected_application_version", kind="integer")

    application = db.applications.get(application_id)
    if application is None:
        errors.raise_error(errors.ERR_FK_NOT_FOUND, "Application not found.")

    if variant not in VALID_AID_VARIANTS:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           f"Field 'variant' must be one of {sorted(VALID_AID_VARIANTS)}.")
    if coa < 0 or grant < 0 or loan < 0 or work_study < 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Monetary fields must be >= 0.")

    # Uniqueness: one aid offer per application
    for existing in db.aid_offers.values():
        if existing["application_id"] == application_id:
            errors.raise_error(errors.ERR_DUPLICATE_RESOURCE,
                               "An aid offer already exists for this application.")

    # Priority 9: OCC check
    if expected_version != application["version"]:
        errors.raise_error(errors.ERR_STALE_APPLICATION_VERSION,
                           "Provided expected_application_version is stale.")

    # Priority 10: from-state check — application must be ADMITTED
    if application["status"] != "ADMITTED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Aid offer requires an ADMITTED application.")

    # Priority 16: INSTITUTIONAL variant eligibility
    _check_institutional_eligibility(application, variant)

    # Resolve the FA profile (must be SUBMITTED to be used for demonstrated need)
    profile = _resolve_fa_profile_for_application(application)
    if profile is None or profile["status"] != "SUBMITTED":
        # Demonstrated-need computation per §3.6 requires a SUBMITTED profile.
        # Treat absence/draft as INVALID_STATE so the officer corrects it.
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Applicant has no SUBMITTED financial aid profile.")

    pending = {
        "application_id": application_id,
        "cost_of_attendance_cents": coa,
        "variant": variant,
        "grant_cents": grant,
        "loan_cents": loan,
        "work_study_cents": work_study,
    }
    demonstrated_need = calculations.compute_demonstrated_need(pending, profile)

    # Priority 17: grant cap
    if grant > demonstrated_need:
        errors.raise_error(errors.ERR_GRANT_EXCEEDS_NEED,
                           "Grant exceeds demonstrated_need_cents.")

    pending["demonstrated_need_cents"] = demonstrated_need
    pending["net_price_cents"] = calculations.compute_net_price(pending)
    util.stamp_create(pending)
    db.aid_offers[pending["id"]] = pending

    # Side effect: parent Application.version += 1
    util.stamp_update(application)

    return resp.success_object(serialize_aid_offer(pending), http_status=201)


# --------------------------------------------------------------------------- #
# PATCH /aid-offers/{id} (FinancialAidOfficer)
# --------------------------------------------------------------------------- #

@bp.route("/aid-offers/<offer_id>", methods=["PATCH"])
@require_auth(["FinancialAidOfficer"])
def patch_aid_offer(offer_id):
    row = db.aid_offers.get(offer_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND, "Aid offer not found.")

    body = get_json_body()
    pending = dict(row)
    if "grant_cents" in body:
        if not isinstance(body["grant_cents"], int) or isinstance(body["grant_cents"], bool):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Field 'grant_cents' must be an integer.")
        if body["grant_cents"] < 0:
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Field 'grant_cents' must be >= 0.")
        pending["grant_cents"] = body["grant_cents"]
    if "loan_cents" in body:
        if not isinstance(body["loan_cents"], int) or isinstance(body["loan_cents"], bool):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Field 'loan_cents' must be an integer.")
        if body["loan_cents"] < 0:
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Field 'loan_cents' must be >= 0.")
        pending["loan_cents"] = body["loan_cents"]
    if "work_study_cents" in body:
        if not isinstance(body["work_study_cents"], int) or isinstance(body["work_study_cents"], bool):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Field 'work_study_cents' must be an integer.")
        if body["work_study_cents"] < 0:
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Field 'work_study_cents' must be >= 0.")
        pending["work_study_cents"] = body["work_study_cents"]

    application = db.applications.get(row["application_id"])
    if application is None:
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Owning application not found.")

    # Priority 16: re-check INSTITUTIONAL eligibility (variant didn't change but
    # the school/profile state might have)
    _check_institutional_eligibility(application, pending["variant"])

    profile = _resolve_fa_profile_for_application(application)
    if profile is None or profile["status"] != "SUBMITTED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Applicant has no SUBMITTED financial aid profile.")
    pending["demonstrated_need_cents"] = calculations.compute_demonstrated_need(pending, profile)

    # Priority 17: grant cap
    if pending["grant_cents"] > pending["demonstrated_need_cents"]:
        errors.raise_error(errors.ERR_GRANT_EXCEEDS_NEED,
                           "Grant exceeds demonstrated_need_cents.")

    pending["net_price_cents"] = calculations.compute_net_price(pending)

    # Persist changes
    row["grant_cents"] = pending["grant_cents"]
    row["loan_cents"] = pending["loan_cents"]
    row["work_study_cents"] = pending["work_study_cents"]
    row["demonstrated_need_cents"] = pending["demonstrated_need_cents"]
    row["net_price_cents"] = pending["net_price_cents"]
    util.stamp_update(row)
    return resp.success_object(serialize_aid_offer(row))


# --------------------------------------------------------------------------- #
# GET /aid-offers/{id}
# --------------------------------------------------------------------------- #

@bp.route("/aid-offers/<offer_id>", methods=["GET"])
@require_auth(["Applicant", "FinancialAidOfficer", "PlatformAdmin"])
def get_aid_offer(offer_id):
    row = db.aid_offers.get(offer_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND, "Aid offer not found.")

    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role == "Applicant":
        application = db.applications.get(row["application_id"])
        if application is None or application["applicant_id"] != user_id:
            errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                               "Applicants can only read aid offers on their own applications.")
    return resp.success_object(serialize_aid_offer(row))
