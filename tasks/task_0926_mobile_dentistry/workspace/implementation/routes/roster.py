"""Patients and the two consent regimes."""

from flask import Blueprint

import calc
import cascades
import clock
import serializers
import store
import validation as v
from constants import (
    CONSENT_TIER_RANK,
    ENUM_CAPACITY_DETERMINATION,
    ENUM_CONSENT_REGIME,
    ENUM_PATIENT_TYPE,
    ENUM_RESPONSIBLE_PARTY_AUTHORITY,
    ENUM_SCOPE_TIER,
)
from envelope import array_response, object_response
from errors import ApiError

bp = Blueprint("roster", __name__)

PATIENT_TYPE_FOR_SITE = {"SCHOOL": "STUDENT", "SNF": "RESIDENT"}
REGIME_FOR_SITE = {"SCHOOL": "SCHOOL_GUARDIAN", "SNF": "SNF_RESPONSIBLE_PARTY"}


# --------------------------------------------------------------------------
# POST /mobile-dentistry/patients
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/patients", methods=["POST"])
def create_patient():
    v.authenticate(["ProgramAdmin", "SiteCoordinator"])
    body = v.body()
    site = v.fk_row(body, "site_id", "sites")

    v.need(body, "site_id")
    if not isinstance(body.get("site_id"), str):
        raise ApiError("ERR_VALIDATION", "Field 'site_id' must be a string.")
    v.enum_type_check(body, "patient_type", required=True)
    external_ref = v.req_string(body, "external_ref")
    first_name = v.req_string(body, "first_name")
    last_name = v.req_string(body, "last_name")
    date_of_birth = v.req_date(body, "date_of_birth")
    grade_level = v.opt_string(body, "grade_level")
    room_number = v.opt_string(body, "room_number")
    household_size = v.opt_int(body, "household_size", minimum=1, default=1)
    income = v.opt_int(body, "annual_household_income_cents", minimum=0, default=None)
    v.enum_type_check(body, "capacity_determination")

    patient_type = body.get("patient_type")
    if patient_type in ENUM_PATIENT_TYPE and patient_type != PATIENT_TYPE_FOR_SITE[site["site_type"]]:
        raise ApiError("ERR_VALIDATION", "patient_type must agree with the site's site_type.")
    for existing in store.all_rows("patients"):
        if existing["site_id"] == site["id"] and existing["external_ref"] == external_ref:
            raise ApiError("ERR_VALIDATION", "external_ref must be unique within the site.")

    patient_type = v.check_enum(body, "patient_type", ENUM_PATIENT_TYPE)
    capacity = v.check_enum(body, "capacity_determination", ENUM_CAPACITY_DETERMINATION)
    capacity = capacity or "NOT_ASSESSED"

    row = store.insert("patients", {
        "site_id": site["id"],
        "patient_type": patient_type,
        "external_ref": external_ref,
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": date_of_birth,
        "grade_level": grade_level,
        "room_number": room_number,
        "household_size": household_size,
        "annual_household_income_cents": income,
        "capacity_determination": capacity,
        "capacity_determined_at": clock.now() if capacity != "NOT_ASSESSED" else None,
        "varnish_applications_in_period": 0,
        "last_varnish_date": None,
    })
    v.mark_minted(row)
    return object_response(serializers.patient(row), 201)


@bp.route("/mobile-dentistry/patients", methods=["GET"])
def list_patients():
    v.authenticate([
        "ProgramAdmin", "SiteCoordinator", "FieldDentist",
        "FieldHygienist", "DentalAssistant", "BillingSpecialist",
    ])
    limit, offset = v.pagination()
    rows = v.apply_filters(
        store.all_rows("patients"),
        {"site_id": "site_id", "patient_type": "patient_type"},
    )
    page, total = v.paginate(rows, limit, offset)
    return array_response(serializers.many(serializers.patient, page), limit, offset, total)


@bp.route("/mobile-dentistry/patients/<patient_id>", methods=["GET"])
def read_patient(patient_id):
    v.authenticate([
        "ProgramAdmin", "SiteCoordinator", "FieldDentist",
        "FieldHygienist", "DentalAssistant", "BillingSpecialist",
    ])
    row = v.path_row("patients", patient_id)
    return object_response(serializers.patient(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/consents
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/consents", methods=["POST"])
def create_consent():
    v.authenticate(["ProgramAdmin", "SiteCoordinator"])
    body = v.body()
    patient = v.fk_row(body, "patient_id", "patients")
    site = v.fk_row(body, "site_id", "sites")
    period = v.fk_row(body, "program_period_id", "program_periods")

    for field in ("patient_id", "site_id", "program_period_id"):
        v.need(body, field)
        if not isinstance(body.get(field), str):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be a string." % field)
    v.enum_type_check(body, "regime", required=True)
    v.enum_type_check(body, "scope_tier", required=True)
    signed_at = v.req_instant(body, "signed_at")
    guardian_name = v.opt_string(body, "guardian_name")
    guardian_relationship = v.opt_string(body, "guardian_relationship")
    responsible_party_name = v.opt_string(body, "responsible_party_name")
    v.enum_type_check(body, "responsible_party_authority")
    poa_document_ref = v.opt_string(body, "poa_document_ref")

    if site["id"] != patient["site_id"]:
        raise ApiError("ERR_VALIDATION", "site_id must equal the patient's site_id.")

    regime = v.check_enum(body, "regime", ENUM_CONSENT_REGIME)
    scope_tier = v.check_enum(body, "scope_tier", ENUM_SCOPE_TIER)
    authority = v.check_enum(body, "responsible_party_authority", ENUM_RESPONSIBLE_PARTY_AUTHORITY)

    # Rung 8 -- regime field completeness and site agreement.
    if regime != REGIME_FOR_SITE[site["site_type"]]:
        raise ApiError("ERR_CONSENT_REGIME_FIELDS", "The regime does not agree with the site type.")
    if regime == "SCHOOL_GUARDIAN":
        if not guardian_name or not guardian_relationship:
            raise ApiError("ERR_CONSENT_REGIME_FIELDS",
                           "A school consent requires guardian_name and guardian_relationship.")
        if responsible_party_name:
            raise ApiError("ERR_CONSENT_REGIME_FIELDS",
                           "A school consent must not carry responsible_party_name.")
    else:
        if not responsible_party_name or not authority:
            raise ApiError("ERR_CONSENT_REGIME_FIELDS",
                           "A facility consent requires responsible_party_name and responsible_party_authority.")
        if authority != "SELF" and not poa_document_ref:
            raise ApiError("ERR_CONSENT_REGIME_FIELDS",
                           "A facility consent requires poa_document_ref unless the authority is SELF.")
        if guardian_name:
            raise ApiError("ERR_CONSENT_REGIME_FIELDS",
                           "A facility consent must not carry guardian_name.")

    expires_at, reaffirmation_due_at = calc.consent_expiry(regime, signed_at, period)

    row = store.insert("consents", {
        "patient_id": patient["id"],
        "site_id": site["id"],
        "program_period_id": period["id"],
        "regime": regime,
        "scope_tier": scope_tier,
        "status": "PENDING_VERIFICATION",
        "guardian_name": guardian_name,
        "guardian_relationship": guardian_relationship,
        "responsible_party_name": responsible_party_name,
        "responsible_party_authority": authority,
        "poa_document_ref": poa_document_ref,
        "signed_at": signed_at,
        "expires_at": expires_at,
        "reaffirmation_due_at": reaffirmation_due_at,
        "superseded_by_consent_id": None,
        "revoked_at": None,
        "revoke_reason": None,
        "expired_at": None,
        "invalidated_procedure_count": 0,
    })
    v.mark_minted(row)
    return object_response(serializers.consent(row), 201)


@bp.route("/mobile-dentistry/consents", methods=["GET"])
def list_consents():
    v.authenticate([
        "ProgramAdmin", "SiteCoordinator", "FieldDentist",
        "FieldHygienist", "DentalAssistant",
    ])
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all_rows("consents"), {
        "patient_id": "patient_id",
        "site_id": "site_id",
        "program_period_id": "program_period_id",
        "superseded_by_consent_id": "superseded_by_consent_id",
        "status": "status",
    })
    page, total = v.paginate(rows, limit, offset)
    return array_response(serializers.many(serializers.consent, page), limit, offset, total)


@bp.route("/mobile-dentistry/consents/<consent_id>", methods=["GET"])
def read_consent(consent_id):
    v.authenticate([
        "ProgramAdmin", "SiteCoordinator", "FieldDentist",
        "FieldHygienist", "DentalAssistant",
    ])
    row = v.path_row("consents", consent_id)
    return object_response(serializers.consent(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/consents/{id}/verify
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/consents/<consent_id>/verify", methods=["POST"])
def verify_consent(consent_id):
    v.authenticate(["ProgramAdmin", "SiteCoordinator"])
    row = v.path_row("consents", consent_id)
    patient = store.get("patients", row["patient_id"])
    period = store.get("program_periods", row["program_period_id"])

    # Rung 11 -- the declared verify legs and their preconditions that carry no
    # error identifier of their own.
    if row["status"] == "PENDING_VERIFICATION":
        if row["expires_at"] is not None and not row["expires_at"] > clock.now():
            raise ApiError("ERR_INVALID_STATE")
    elif row["status"] == "ACTIVE":
        if row["regime"] != "SNF_RESPONSIBLE_PARTY":
            raise ApiError("ERR_INVALID_STATE")
    else:
        raise ApiError("ERR_INVALID_STATE")

    # Rung 25 -- the facility capacity determination.
    if row["regime"] == "SNF_RESPONSIBLE_PARTY" and patient["capacity_determination"] == "NOT_ASSESSED":
        raise ApiError("ERR_CAPACITY_DETERMINATION_REQUIRED")

    if row["status"] == "ACTIVE":
        row["signed_at"] = clock.now()
    row["status"] = "ACTIVE"
    expires_at, reaffirmation_due_at = calc.consent_expiry(row["regime"], row["signed_at"], period)
    row["expires_at"] = expires_at
    row["reaffirmation_due_at"] = reaffirmation_due_at
    v.touch(row)
    return object_response(serializers.consent(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/consents/{id}/revoke
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/consents/<consent_id>/revoke", methods=["POST"])
def revoke_consent(consent_id):
    v.authenticate(["ProgramAdmin", "SiteCoordinator"])
    row = v.path_row("consents", consent_id)
    body = v.body()
    revoke_reason = v.opt_string(body, "revoke_reason")

    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    row["status"] = "REVOKED"
    row["revoked_at"] = clock.now()
    row["revoke_reason"] = revoke_reason
    v.touch(row)
    cascades.run_consent_revocation_cascade(row)
    return object_response(serializers.consent(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/consents/{id}/amend-tier
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/consents/<consent_id>/amend-tier", methods=["POST"])
def amend_consent_tier(consent_id):
    v.authenticate(["ProgramAdmin", "SiteCoordinator"])
    row = v.path_row("consents", consent_id)
    body = v.body()

    v.enum_type_check(body, "new_scope_tier", required=True)
    expected_patient_version = v.req_int(body, "expected_patient_version")
    v.opt_string(body, "amend_reason")

    new_scope_tier = v.check_enum(body, "new_scope_tier", ENUM_SCOPE_TIER)

    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    patient = store.get("patients", row["patient_id"])
    if expected_patient_version != patient["version"]:
        raise ApiError("ERR_STALE_VERSION")

    period = store.get("program_periods", row["program_period_id"])
    expires_at, reaffirmation_due_at = calc.consent_expiry(row["regime"], row["signed_at"], period)

    replacement = store.insert("consents", {
        "patient_id": row["patient_id"],
        "site_id": row["site_id"],
        "program_period_id": row["program_period_id"],
        "regime": row["regime"],
        "scope_tier": new_scope_tier,
        "status": "ACTIVE",
        "guardian_name": row["guardian_name"],
        "guardian_relationship": row["guardian_relationship"],
        "responsible_party_name": row["responsible_party_name"],
        "responsible_party_authority": row["responsible_party_authority"],
        "poa_document_ref": row["poa_document_ref"],
        "signed_at": row["signed_at"],
        "expires_at": expires_at,
        "reaffirmation_due_at": reaffirmation_due_at,
        "superseded_by_consent_id": None,
        "revoked_at": None,
        "revoke_reason": None,
        "expired_at": None,
        "invalidated_procedure_count": 0,
    })
    v.mark_minted(replacement)

    old_rank = CONSENT_TIER_RANK[row["scope_tier"]]
    new_rank = CONSENT_TIER_RANK[new_scope_tier]

    row["status"] = "SUPERSEDED"
    row["superseded_by_consent_id"] = replacement["id"]
    v.touch(row)
    v.touch(patient)

    if new_rank < old_rank:
        cascades.run_consent_downgrade_cascade(row, new_rank)

    return object_response(serializers.consent(replacement), 201)
