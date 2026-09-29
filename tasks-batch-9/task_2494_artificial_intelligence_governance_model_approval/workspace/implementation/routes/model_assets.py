"""Model assets, their bindings listing, and vendor model assessments."""
from flask import Blueprint

import clock
import constants
import db
import errors
import response
import validators as v
from errors import ApiError
from middleware import authorize, current_user_id
from services import cascades, calc, guards, queries

bp = Blueprint("model_assets", __name__)


def _new_asset(provider, model_name, model_version, hosting, modality, is_third_party):
    record = {
        "provider": provider,
        "model_name": model_name,
        "model_version": model_version,
        "hosting": hosting,
        "modality": modality,
        "is_third_party": is_third_party,
        "status": "REGISTERED",
        "vendor_terms_grade": None,
        "active_binding_count": 0,
        "enforced_shadow_count": 0,
        "updated_at": clock.now(),
        "version": 1,
    }
    return db.insert(db.model_assets, record)


# --- 1. POST /model-assets ------------------------------------------------
@bp.post("/model-assets")
@authorize(constants.GOVERNANCE_OFFICER)
def create_model_asset():
    body = v.get_body()
    provider = v.as_str(body, "provider", required=True)
    model_name = v.as_str(body, "model_name", required=True)
    model_version = v.as_str(body, "model_version", required=True)
    hosting = v.as_enum(body, "hosting", constants.HOSTING, required=True)
    modality = v.as_enum(body, "modality", constants.MODALITY, required=True)
    is_third_party = v.as_bool(body, "is_third_party", required=True)
    asset = _new_asset(provider, model_name, model_version, hosting, modality, is_third_party)
    return response.object_response(asset, 201)


# --- 2. GET /model-assets -------------------------------------------------
@bp.get("/model-assets")
@authorize(*constants.ALL_ROLES)
def list_model_assets():
    status = v.query_str("status")
    provider = v.query_str("provider")
    is_third_party = v.query_bool("is_third_party")
    limit, offset = v.pagination_params()
    records = db.all_of(db.model_assets)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if provider is not None:
        records = [r for r in records if r["provider"] == provider]
    if is_third_party is not None:
        records = [r for r in records if r["is_third_party"] is is_third_party]
    page, pagination = response.paginate(records, limit, offset)
    return response.list_response(page, pagination)


# --- 3. GET /model-assets/{id} -------------------------------------------
@bp.get("/model-assets/<asset_id>")
@authorize(*constants.ALL_ROLES)
def read_model_asset(asset_id):
    return response.object_response(guards.get_model_asset(asset_id))


# --- 4. PATCH /model-assets/{id} -----------------------------------------
@bp.patch("/model-assets/<asset_id>")
@authorize(constants.GOVERNANCE_OFFICER)
def revise_model_asset(asset_id):
    asset = guards.get_model_asset(asset_id)                      # step 4
    body = v.get_body()                                           # step 8
    v.require_any_field(body, ("model_version", "hosting", "modality"))
    model_version = v.as_str(body, "model_version")
    hosting = v.as_enum(body, "hosting", constants.HOSTING)
    modality = v.as_enum(body, "modality", constants.MODALITY)
    if asset["status"] != "APPROVED_FOR_USE":                     # step 20
        raise ApiError(
            errors.ERR_MODEL_ASSET_NOT_APPROVED_FOR_USE,
            "an asset may only be revised in place while APPROVED_FOR_USE",
        )
    if model_version is not None:
        asset["model_version"] = model_version
    if hosting is not None:
        asset["hosting"] = hosting
    if modality is not None:
        asset["modality"] = modality
    db.touch(asset)
    cascades.stale_bindings_for_asset_version(asset)
    return response.object_response(asset)


# --- 5. POST /model-assets/{id}/approve-for-use --------------------------
@bp.post("/model-assets/<asset_id>/approve-for-use")
@authorize(constants.GOVERNANCE_OFFICER)
def approve_asset_for_use(asset_id):
    asset = guards.get_model_asset(asset_id)                      # step 4
    if asset["status"] not in ("REGISTERED", "RESTRICTED"):        # step 20
        raise ApiError(
            errors.ERR_MODEL_ASSET_NOT_APPROVED_FOR_USE,
            "asset %s is %s and has no approve-for-use transition"
            % (asset_id, asset["status"]),
        )
    if asset["status"] == "RESTRICTED" and asset["enforced_shadow_count"] != 0:
        raise ApiError(
            errors.ERR_MODEL_ASSET_NOT_APPROVED_FOR_USE,
            "a RESTRICTED asset with an enforced shadow block outstanding cannot be "
            "rehabilitated",
        )
    if asset["is_third_party"]:                                   # step 31
        acceptable = [
            a
            for a in queries.accepted_assessments_of(asset_id)
            if a["terms_grade"] in constants.ACCEPTABLE_VENDOR_GRADES
        ]
        if not acceptable:
            raise ApiError(
                errors.ERR_VENDOR_ASSESSMENT_NOT_ACCEPTED,
                "a third-party asset needs an ACCEPTED vendor assessment graded A, B or C",
            )
    asset["status"] = "APPROVED_FOR_USE"
    db.touch(asset)
    cascades.stale_bindings_for_asset_version(asset)
    return response.object_response(asset)


# --- 6. GET /model-assets/{id}/model-bindings ----------------------------
@bp.get("/model-assets/<asset_id>/model-bindings")
@authorize(
    constants.GOVERNANCE_OFFICER,
    constants.LEGAL_REVIEWER,
    constants.PRIVACY_REVIEWER,
    constants.SECURITY_REVIEWER,
    constants.BUSINESS_REVIEWER,
)
def list_asset_bindings(asset_id):
    guards.get_model_asset(asset_id)
    status = v.query_str("status")
    limit, offset = v.pagination_params()
    records = queries.bindings_of_asset(asset_id)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pagination = response.paginate(records, limit, offset)
    return response.list_response(page, pagination)


# --- 7. POST /model-assets/{id}/vendor-assessments -----------------------
@bp.post("/model-assets/<asset_id>/vendor-assessments")
@authorize(constants.GOVERNANCE_OFFICER, constants.LEGAL_REVIEWER)
def submit_vendor_assessment(asset_id):
    guards.get_model_asset(asset_id)                              # step 4
    body = v.get_body()                                           # step 8
    vendor_name = v.as_str(body, "vendor_name", required=True)
    provenance = v.as_enum(body, "training_data_provenance", constants.PROVENANCE, required=True)
    output_rights = v.as_enum(body, "output_rights", constants.OUTPUT_RIGHTS, required=True)
    retention_days = v.as_int(body, "retention_days", minimum=0)
    retention_opt_out = v.as_bool(body, "retention_opt_out", required=True)
    subprocessors_disclosed = v.as_bool(body, "subprocessors_disclosed", required=True)

    record = {
        "model_asset_id": asset_id,
        "vendor_name": vendor_name,
        "training_data_provenance": provenance,
        "output_rights": output_rights,
        "retention_days": retention_days,
        "retention_opt_out": retention_opt_out,
        "subprocessors_disclosed": subprocessors_disclosed,
        "status": "SUBMITTED",
        "terms_variant": "CONSERVATIVE_LEGAL",
        "effective_retention_days": None,
        "terms_risk_points": None,
        "terms_grade": None,
        "decision_rationale": None,
        "decided_by_user_id": None,
        "decided_at": None,
        "updated_at": clock.now(),
        "version": 1,
    }
    effective, points, grade = calc.grade_vendor_terms(record, "CONSERVATIVE_LEGAL")
    record["effective_retention_days"] = effective
    record["terms_risk_points"] = points
    record["terms_grade"] = grade
    db.insert(db.vendor_assessments, record)
    return response.object_response(record, 201)


# --- 8. GET /model-assets/{id}/vendor-assessments ------------------------
@bp.get("/model-assets/<asset_id>/vendor-assessments")
@authorize(constants.GOVERNANCE_OFFICER, constants.LEGAL_REVIEWER)
def list_vendor_assessments(asset_id):
    guards.get_model_asset(asset_id)
    status = v.query_str("status")
    limit, offset = v.pagination_params()
    records = queries.assessments_of(asset_id)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pagination = response.paginate(records, limit, offset)
    return response.list_response(page, pagination)


# --- 9. POST /vendor-assessments/{id}/decide -----------------------------
@bp.post("/vendor-assessments/<assessment_id>/decide")
@authorize(constants.GOVERNANCE_OFFICER)
def decide_vendor_assessment(assessment_id):
    assessment = guards.get_record(                               # step 6
        db.vendor_assessments, assessment_id, "vendor assessment"
    )
    body = v.get_body()                                           # step 8
    decision = v.as_enum(body, "decision", constants.ASSESSMENT_DECISIONS, required=True)
    terms_variant = v.as_enum(body, "terms_variant", constants.TERMS_VARIANTS, required=True)
    decision_rationale = v.as_str(body, "decision_rationale")
    if assessment["status"] != "SUBMITTED":                       # step 15
        raise ApiError(
            errors.ERR_ASSESSMENT_ALREADY_DECIDED,
            "vendor assessment %s is already %s" % (assessment_id, assessment["status"]),
        )
    if terms_variant == "DOCUMENTED_TERMS" and assessment["retention_days"] is None:
        raise ApiError(                                           # step 32
            errors.ERR_RETENTION_TERMS_UNDOCUMENTED,
            "the DOCUMENTED_TERMS variant requires a declared retention_days",
        )

    effective, points, grade = calc.grade_vendor_terms(assessment, terms_variant)
    assessment["terms_variant"] = terms_variant
    assessment["effective_retention_days"] = effective
    assessment["terms_risk_points"] = points
    assessment["terms_grade"] = grade
    assessment["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    if decision_rationale is not None:
        assessment["decision_rationale"] = decision_rationale
    assessment["decided_by_user_id"] = current_user_id()
    assessment["decided_at"] = clock.now()
    db.touch(assessment)

    asset = db.model_assets.get(assessment["model_asset_id"])
    if asset is not None:
        cascades.refresh_vendor_terms_grade(asset)
    return response.object_response(assessment)
