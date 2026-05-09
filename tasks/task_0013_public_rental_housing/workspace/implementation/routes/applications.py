"""Application routes."""
from flask import Blueprint, request

from common import (
    check_version,
    get_application_or_404,
    get_annual_review_or_404,
    get_json_body,
    get_program_or_404,
    paginate,
    require_field,
    require_int,
    stamp_new,
    stamp_update,
)
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.allocation import manual_finalize_exit
from services.calc import (
    HOUSEHOLD_TYPE_PTS,
    SPECIAL_CARE_PTS,
    compute_queue_score,
    compute_tie_break_key,
)
from services.eligibility import evaluate_cross_check
from services.sync import emit_audit_eligibility_change

bp = Blueprint("applications", __name__)


VALID_HOUSEHOLD_TYPES = set(HOUSEHOLD_TYPE_PTS.keys())
VALID_RELATIONS = {"SELF", "SPOUSE", "CHILD", "PARENT", "OTHER"}
VALID_SPECIAL = set(SPECIAL_CARE_PTS.keys())


def _validate_household_members(members):
    if not isinstance(members, list):
        raise api_error("ERR_INVALID_REQUEST", "household_members must be an array")
    for m in members:
        if not isinstance(m, dict):
            raise api_error("ERR_INVALID_REQUEST",
                            "household_members entries must be objects")
        for f in ("citizen_id", "relation", "dob", "has_disability",
                  "special_care_category"):
            if f not in m:
                raise api_error("ERR_INVALID_REQUEST",
                                f"household_members entry missing {f}")
        if m.get("relation") not in VALID_RELATIONS:
            raise api_error("ERR_INVALID_REQUEST", "Invalid relation")
        if m.get("special_care_category") not in VALID_SPECIAL:
            raise api_error("ERR_INVALID_REQUEST",
                            "Invalid special_care_category")
        if not isinstance(m.get("has_disability"), bool):
            raise api_error("ERR_INVALID_REQUEST",
                            "has_disability must be boolean")


def _enforce_uniqueness(program_id: str, applicant_user_id: str) -> None:
    """At most one Application per (program, applicant) in non-terminal status."""
    for a in db.applications.values():
        if a.get("housing_program_id") != program_id:
            continue
        if a.get("applicant_user_id") != applicant_user_id:
            continue
        if a.get("status") in {"EXITED", "REJECTED"}:
            continue
        raise api_error(
            "ERR_DUPLICATE_ACTIVE_APPLICATION",
            "Applicant already has a non-terminal Application in this program",
        )


# ----------------------------------------------------------------------------
# POST /housing-programs/{programId}/applications  — Applicant
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/applications")
def create_application(program_id):
    user_id, _ = require_roles("Applicant")
    get_program_or_404(program_id)
    body = get_json_body()

    members = require_field(body, "household_members")
    _validate_household_members(members)
    if len(members) == 0:
        raise api_error("ERR_INVALID_REQUEST", "household_members must be non-empty")

    household_type = require_field(body, "household_type")
    if household_type not in VALID_HOUSEHOLD_TYPES:
        raise api_error("ERR_INVALID_REQUEST", "Invalid household_type")

    declared_income = require_int(body, "declared_monthly_income_cents", minimum=0)
    declared_assets = require_int(body, "declared_total_assets_cents", minimum=0)
    residence_start = require_int(body, "residence_start_period")

    with db.lock:
        _enforce_uniqueness(program_id, user_id)
        application = {
            "housing_program_id": program_id,
            "applicant_user_id": user_id,
            "household_members": members,
            "household_type": household_type,
            "declared_monthly_income_cents": declared_income,
            "declared_total_assets_cents": declared_assets,
            "residence_start_period": residence_start,
            "requires_accessibility": any(bool(m.get("has_disability"))
                                          for m in members),
            "family_size": len(members),
            "verified_monthly_income_cents": None,
            "verified_total_assets_cents": None,
            "cross_check_status": "PENDING",
            "queue_score": None,
            "tie_break_key": None,
            "status": "DRAFT",
            "rejection_reason": None,
            "exit_trigger_period": None,
        }
        stamp_new(application)
        db.applications[application["id"]] = application
    return success(application, status=201)


# ----------------------------------------------------------------------------
# GET /housing-programs/{programId}/applications
# ----------------------------------------------------------------------------
@bp.get("/housing-programs/<program_id>/applications")
def list_applications(program_id):
    user_id, role = require_roles("HousingOfficer", "HousingDirector", "Applicant")
    get_program_or_404(program_id)
    status_filter = request.args.get("status")
    items = []
    for a in db.applications.values():
        if a.get("housing_program_id") != program_id:
            continue
        if role == "Applicant" and a.get("applicant_user_id") != user_id:
            continue
        if status_filter and a.get("status") != status_filter:
            continue
        items.append(a)
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


# ----------------------------------------------------------------------------
# GET /housing-programs/{programId}/applications/{appId}
# ----------------------------------------------------------------------------
@bp.get("/housing-programs/<program_id>/applications/<app_id>")
def get_application(program_id, app_id):
    user_id, role = require_roles("HousingOfficer", "HousingDirector", "Applicant")
    get_program_or_404(program_id)
    application = get_application_or_404(program_id, app_id)
    if role == "Applicant" and application.get("applicant_user_id") != user_id:
        raise api_error("ERR_INSUFFICIENT_PERMISSIONS",
                        "Applicants may only view their own application")
    return success(application)


# ----------------------------------------------------------------------------
# POST /applications/{appId}/submit  — Applicant
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/applications/<app_id>/submit")
def submit_application(program_id, app_id):
    user_id, _ = require_roles("Applicant")
    get_program_or_404(program_id)
    application = get_application_or_404(program_id, app_id)
    body = get_json_body()
    check_version(application, body)

    if application.get("applicant_user_id") != user_id:
        raise api_error("ERR_INSUFFICIENT_PERMISSIONS",
                        "Only the owning applicant may submit this application")
    if application.get("status") != "DRAFT":
        raise api_error("ERR_APPLICATION_NOT_IN_DRAFT",
                        "Application must be in DRAFT")
    if not application.get("household_members"):
        raise api_error("ERR_INVALID_REQUEST",
                        "household_members must be non-empty to submit")

    with db.lock:
        application["status"] = "UNDER_REVIEW"
        stamp_update(application)
    return success(application)


# ----------------------------------------------------------------------------
# POST /applications/{appId}/cross-check  — HousingOfficer
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/applications/<app_id>/cross-check")
def cross_check_application(program_id, app_id):
    user_id, _ = require_roles("HousingOfficer")
    program = get_program_or_404(program_id)
    application = get_application_or_404(program_id, app_id)
    body = get_json_body()
    check_version(application, body)

    if application.get("status") != "UNDER_REVIEW":
        raise api_error("ERR_APPLICATION_NOT_UNDER_REVIEW",
                        "Application must be UNDER_REVIEW")

    with db.lock:
        passed, failing_id, tax_payload = evaluate_cross_check(application, program)
        before_status = application.get("status")
        before_cc = application.get("cross_check_status")
        if passed:
            application["verified_monthly_income_cents"] = int(
                tax_payload.get("monthly_income_cents", 0))
            application["verified_total_assets_cents"] = int(
                tax_payload.get("total_assets_cents", 0))
            application["cross_check_status"] = "PASSED"
            cpi = int(program["current_period_index"])
            application["queue_score"] = compute_queue_score(
                application, current_period_index=cpi)
            application["tie_break_key"] = compute_tie_break_key(application)
            application["status"] = "SCORED"
            stamp_update(application)
            emit_audit_eligibility_change(
                program_id=program_id,
                subject_type="APPLICATION",
                subject_id=application["id"],
                actor_user_id=user_id,
                before={"status": before_status, "cross_check_status": before_cc},
                after={"status": "SCORED", "cross_check_status": "PASSED"},
                note="cross-check passed",
                current_period_index=cpi,
            )
        else:
            application["cross_check_status"] = "FAILED"
            application["rejection_reason"] = failing_id
            application["status"] = "REJECTED"
            stamp_update(application)
            emit_audit_eligibility_change(
                program_id=program_id,
                subject_type="APPLICATION",
                subject_id=application["id"],
                actor_user_id=user_id,
                before={"status": before_status, "cross_check_status": before_cc},
                after={"status": "REJECTED",
                       "cross_check_status": "FAILED",
                       "rejection_reason": failing_id},
                note="cross-check failed",
                current_period_index=int(program["current_period_index"]),
            )
            # PRD §3.2: cross-check fails with the specific error_id; the entity is also
            # mutated to REJECTED with rejection_reason recorded (already done above).
            raise api_error(failing_id, f"Cross-check failed: {failing_id}")
    return success(application)


# ----------------------------------------------------------------------------
# POST /applications/{appId}/enqueue
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/applications/<app_id>/enqueue")
def enqueue_application(program_id, app_id):
    require_roles("HousingOfficer")
    get_program_or_404(program_id)
    application = get_application_or_404(program_id, app_id)
    body = get_json_body()
    check_version(application, body)
    if application.get("status") != "SCORED":
        raise api_error("ERR_APPLICATION_NOT_SCORED",
                        "Application must be SCORED")
    with db.lock:
        application["status"] = "QUEUED"
        stamp_update(application)
    return success(application)


# ----------------------------------------------------------------------------
# POST /applications/{appId}/finalize-exit
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/applications/<app_id>/finalize-exit")
def finalize_exit(program_id, app_id):
    user_id, _ = require_roles("HousingOfficer")
    program = get_program_or_404(program_id)
    application = get_application_or_404(program_id, app_id)
    body = get_json_body()
    check_version(application, body)
    if application.get("status") != "EXIT_PENDING":
        raise api_error("ERR_APPLICATION_NOT_EXIT_PENDING",
                        "Application must be EXIT_PENDING")
    with db.lock:
        manual_finalize_exit(application, program=program, actor_user_id=user_id)
    return success(application)


# ----------------------------------------------------------------------------
# Annual reviews (PRD §3.7)
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/applications/<app_id>/annual-reviews")
def create_annual_review(program_id, app_id):
    require_roles("HousingOfficer")
    program = get_program_or_404(program_id)
    application = get_application_or_404(program_id, app_id)
    body = get_json_body()

    if application.get("status") != "OCCUPIED":
        raise api_error("ERR_APPLICATION_NOT_OCCUPIED",
                        "Application must be OCCUPIED")

    # Reject duplicate OPEN review
    for r in db.annual_reviews.values():
        if r.get("application_id") == app_id and r.get("status") == "OPEN":
            raise api_error("ERR_ANNUAL_REVIEW_ALREADY_OPEN",
                            "Another OPEN AnnualReview exists for this Application")

    # Optional input validation
    upd_members = body.get("updated_household_members")
    if upd_members is not None:
        _validate_household_members(upd_members)
    upd_income = body.get("updated_declared_monthly_income_cents")
    upd_assets = body.get("updated_declared_total_assets_cents")
    if upd_income is not None:
        try:
            upd_income = int(upd_income)
        except (TypeError, ValueError):
            raise api_error("ERR_INVALID_REQUEST",
                            "updated_declared_monthly_income_cents must be integer")
        if upd_income < 0:
            raise api_error("ERR_INVALID_REQUEST",
                            "updated_declared_monthly_income_cents must be >= 0")
    if upd_assets is not None:
        try:
            upd_assets = int(upd_assets)
        except (TypeError, ValueError):
            raise api_error("ERR_INVALID_REQUEST",
                            "updated_declared_total_assets_cents must be integer")
        if upd_assets < 0:
            raise api_error("ERR_INVALID_REQUEST",
                            "updated_declared_total_assets_cents must be >= 0")

    with db.lock:
        review = {
            "application_id": app_id,
            "review_period_index": int(program["current_period_index"]),
            "updated_household_members": upd_members,
            "updated_declared_monthly_income_cents": upd_income,
            "updated_declared_total_assets_cents": upd_assets,
            "re_eligibility": None,
            "recomputed_queue_score": None,
            "rent_adjustment_cents": None,
            "exit_triggered": False,
            "status": "OPEN",
        }
        stamp_new(review)
        db.annual_reviews[review["id"]] = review
    return success(review, status=201)


# ----------------------------------------------------------------------------
# POST /applications/{appId}/annual-reviews/{reviewId}/finalize
# ----------------------------------------------------------------------------
@bp.post(
    "/housing-programs/<program_id>/applications/<app_id>/annual-reviews/<review_id>/finalize"
)
def finalize_annual_review(program_id, app_id, review_id):
    user_id, _ = require_roles("HousingOfficer")
    program = get_program_or_404(program_id)
    application = get_application_or_404(program_id, app_id)
    review = get_annual_review_or_404(app_id, review_id)
    body = get_json_body()
    check_version(review, body)

    if review.get("status") != "OPEN":
        raise api_error("ERR_ANNUAL_REVIEW_NOT_OPEN",
                        "AnnualReview must be OPEN")
    if application.get("status") != "OCCUPIED":
        raise api_error("ERR_APPLICATION_NOT_OCCUPIED",
                        "Application must be OCCUPIED")

    with db.lock:
        # 1. Apply updates
        if review.get("updated_household_members") is not None:
            application["household_members"] = review["updated_household_members"]
            application["family_size"] = len(application["household_members"])
            application["requires_accessibility"] = any(
                bool(m.get("has_disability"))
                for m in application["household_members"]
            )
        if review.get("updated_declared_monthly_income_cents") is not None:
            application["declared_monthly_income_cents"] = \
                review["updated_declared_monthly_income_cents"]
        if review.get("updated_declared_total_assets_cents") is not None:
            application["declared_total_assets_cents"] = \
                review["updated_declared_total_assets_cents"]

        # 2. Re-run cross-check
        passed, failing_id, _tax = evaluate_cross_check(application, program)
        review["re_eligibility"] = "ELIGIBLE" if passed else "INELIGIBLE"

        # 3. Recompute queue_score using review_period_index
        review_period = int(review["review_period_index"])
        new_score = compute_queue_score(
            application, current_period_index=review_period)
        review["recomputed_queue_score"] = new_score
        application["queue_score"] = new_score

        before_app_status = application.get("status")

        if review["re_eligibility"] == "INELIGIBLE":
            review["exit_triggered"] = True
            cpi = int(program["current_period_index"])
            application["status"] = "EXIT_PENDING"
            application["exit_trigger_period"] = cpi
            stamp_update(application)
            review["rent_adjustment_cents"] = None
        else:
            # ELIGIBLE — rent adjustment delta
            contract = _find_active_contract_for_application(app_id)
            if contract:
                # Adjustment delta is the difference between the (new household
                # type tier) base rent and the current monthly_base_rent_cents.
                # Without a programmatic mapping from tier→base rent, we treat
                # the delta as zero (PRD: 'may be 0'). The hook is in place to
                # vary rent per household type if such a mapping is added.
                rent_delta = 0
                review["rent_adjustment_cents"] = rent_delta
                if rent_delta != 0:
                    from services.calc import compute_monthly_effective_rent
                    contract["monthly_effective_rent_cents"] = (
                        compute_monthly_effective_rent(
                            contract,
                            current_period_index=int(program["current_period_index"]),
                        )
                    )
                    stamp_update(contract)
            else:
                review["rent_adjustment_cents"] = None
            stamp_update(application)

        review["status"] = "FINALIZED"
        stamp_update(review)

        # 4. Emit AUDIT_ELIGIBILITY_CHANGE
        emit_audit_eligibility_change(
            program_id=program_id,
            subject_type="APPLICATION",
            subject_id=application["id"],
            actor_user_id=user_id,
            before={"status": before_app_status},
            after={
                "status": application["status"],
                "re_eligibility": review["re_eligibility"],
            },
            note="annual review finalized",
            current_period_index=int(program["current_period_index"]),
        )
    return success(review)


def _find_active_contract_for_application(app_id: str) -> dict | None:
    for c in db.contracts.values():
        if c.get("application_id") == app_id and c.get("status") == "ACTIVE":
            return c
    return None
