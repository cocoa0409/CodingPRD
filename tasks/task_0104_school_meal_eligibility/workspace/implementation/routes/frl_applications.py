"""FrlApplication endpoints. PRD §3.4, §3.5."""

from flask import Blueprint, request, g

from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, stamp_common, lock, touch
from core.validation import (
    require_body, require_field, optional_field, check_version,
)

from services.calculations import frl_tier_classification
from services.constants import (
    FEDERAL_POVERTY_GUIDELINE_BY_SIZE,
    RENEWAL_INCOME_TOLERANCE,
    RENEWAL_YEAR_DAYS_TARGET,
    RENEWAL_YEAR_DAYS_TOLERANCE,
    SYSTEM_AUTO_RENEW_USER_ID,
)
from services.relationships import (
    get_district_or_404, get_student_in_district,
    get_frl_application_in_district,
)
from services.views import frl_application_view


bp = Blueprint("frl_applications", __name__)


# --- Helpers ----------------------------------------------------------------

def _student_for_app(app: dict) -> dict:
    return STORE.students[app["student_id"]]


def _parent_owns(app: dict) -> bool:
    """Returns True if the calling Parent owns the student tied to this application."""
    s = _student_for_app(app)
    return g.user_role == "Parent" and g.user_id == s["parent_account_id"]


def _require_reviewer_not_owning_parent(app: dict):
    """Segregation-of-duties: the acting DistrictReviewer must not be the
    Parent who owns the student. Reviewers are opaque identifiers (PRD §2.1)
    but if X-User-ID happens to match the student's parent_account_id, the
    reviewer is impersonating the owning parent and must be rejected."""
    s = _student_for_app(app)
    if g.user_id == s["parent_account_id"]:
        raise_error("ERR_SEGREGATION_OF_DUTIES",
                    "Reviewer must not be the owning parent")


def _parse_iso_dt(s):
    """Lazy import to avoid circular dependency at module load."""
    from core.validation import parse_iso8601
    return parse_iso8601(s)


# --- Endpoints --------------------------------------------------------------

@bp.post("/districts/<district_id>/frl-applications")
@require_roles("Parent")
def create_application(district_id):
    with lock():
        get_district_or_404(district_id)
        body = require_body(request)
        student_id = require_field(body, "student_id", kind="string")
        household_size = require_field(body, "household_size", kind="int")
        income = require_field(body, "declared_annual_income_cents", kind="int")
        documents = optional_field(body, "documents_attached_count",
                                   kind="non_neg_int", default=0)
        prior_id = optional_field(body, "prior_year_application_id", default=None)
        if prior_id is not None and not isinstance(prior_id, str):
            raise_error("ERR_VALIDATION",
                        "prior_year_application_id must be a string when supplied")

        # Range check: household_size in [1,8], income >= 0.
        if household_size < 1 or household_size > 8:
            raise_error("ERR_VALIDATION", "household_size must be in [1, 8]")
        if income < 0:
            raise_error("ERR_VALIDATION",
                        "declared_annual_income_cents must be non-negative")

        s = get_student_in_district(district_id, student_id)
        # Parent must own the student.
        if s["parent_account_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN",
                        "Parent may only file applications for their own student")

        a = {
            "district_id": district_id,
            "student_id": student_id,
            "household_size": household_size,
            "declared_annual_income_cents": income,
            "documents_attached_count": documents,
            "prior_year_application_id": prior_id,
            "status": "DRAFT",
            "decided_tier": None,
            "federal_poverty_guideline_cents": None,
            "school_year_start": None,
            "review_note": None,
            "reviewer_user_id": None,
        }
        stamp_common(a)
        STORE.frl_applications[a["id"]] = a
        return success_object(frl_application_view(a), status=201)


@bp.get("/districts/<district_id>/frl-applications/<app_id>")
@require_roles("Parent", "DistrictReviewer", "AuditOfficer")
def get_application(district_id, app_id):
    with lock():
        get_district_or_404(district_id)
        a = get_frl_application_in_district(district_id, app_id)
        # Parent ownership scope.
        if g.user_role == "Parent":
            s = _student_for_app(a)
            if s["parent_account_id"] != g.user_id:
                raise_error("ERR_FORBIDDEN",
                            "Parent may only read their own student's applications")
        return success_object(frl_application_view(a))


@bp.post("/districts/<district_id>/frl-applications/<app_id>/submit")
@require_roles("Parent")
def submit_application(district_id, app_id):
    with lock():
        district = get_district_or_404(district_id)
        a = get_frl_application_in_district(district_id, app_id)
        body = require_body(request)
        check_version(body, a)
        # Ownership.
        s = _student_for_app(a)
        if s["parent_account_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN",
                        "Parent may only submit their own student's applications")
        # State (priority 4).
        if a["status"] != "DRAFT":
            raise_error("ERR_INVALID_STATE",
                        f"Application is not in DRAFT state (current={a['status']})")
        # Re-check structural constraints just in case (priority 14).
        if a["household_size"] < 1:
            raise_error("ERR_VALIDATION", "household_size must be >= 1")
        if a["declared_annual_income_cents"] < 0:
            raise_error("ERR_VALIDATION",
                        "declared_annual_income_cents must be non-negative")
        a["status"] = "SUBMITTED"
        a["school_year_start"] = district["school_year_start"]
        touch(a)
        return success_object(frl_application_view(a))


@bp.post("/districts/<district_id>/frl-applications/<app_id>/request-info")
@require_roles("DistrictReviewer")
def request_info(district_id, app_id):
    with lock():
        get_district_or_404(district_id)
        a = get_frl_application_in_district(district_id, app_id)
        body = require_body(request)
        check_version(body, a)
        if a["status"] != "SUBMITTED":
            raise_error("ERR_INVALID_STATE",
                        f"Application is not in SUBMITTED state (current={a['status']})")
        review_note = require_field(body, "review_note", kind="string")
        a["status"] = "INFO_REQUESTED"
        a["review_note"] = review_note
        a["reviewer_user_id"] = g.user_id
        touch(a)
        return success_object(frl_application_view(a))


@bp.post("/districts/<district_id>/frl-applications/<app_id>/resubmit")
@require_roles("Parent")
def resubmit(district_id, app_id):
    with lock():
        get_district_or_404(district_id)
        a = get_frl_application_in_district(district_id, app_id)
        body = require_body(request)
        check_version(body, a)
        s = _student_for_app(a)
        if s["parent_account_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN",
                        "Parent may only resubmit their own student's applications")
        if a["status"] != "INFO_REQUESTED":
            raise_error("ERR_INVALID_STATE",
                        f"Application is not in INFO_REQUESTED state (current={a['status']})")
        documents = require_field(body, "documents_attached_count", kind="non_neg_int")
        a["documents_attached_count"] = documents
        a["status"] = "SUBMITTED"
        touch(a)
        return success_object(frl_application_view(a))


@bp.post("/districts/<district_id>/frl-applications/<app_id>/approve")
@require_roles("DistrictReviewer")
def approve(district_id, app_id):
    with lock():
        get_district_or_404(district_id)
        a = get_frl_application_in_district(district_id, app_id)
        body = require_body(request)
        check_version(body, a)
        # State check (priority 4) BEFORE segregation of duties (priority 7).
        if a["status"] != "SUBMITTED":
            raise_error("ERR_INVALID_STATE",
                        f"Application is not in SUBMITTED state (current={a['status']})")
        _require_reviewer_not_owning_parent(a)
        tier = frl_tier_classification(
            a["declared_annual_income_cents"], a["household_size"])
        if tier == "DENIED_PAID":
            # Approval may not mint DENIED_PAID — must route through deny.
            raise_error("ERR_INVALID_STATE",
                        "Classification yields DENIED_PAID; cannot APPROVE")
        a["status"] = "APPROVED"
        a["decided_tier"] = tier
        a["federal_poverty_guideline_cents"] = \
            FEDERAL_POVERTY_GUIDELINE_BY_SIZE[a["household_size"]]
        a["reviewer_user_id"] = g.user_id
        touch(a)
        # Side effect on Student.
        s = _student_for_app(a)
        s["eligibility_tier"] = tier
        s["eligibility_application_id"] = a["id"]
        touch(s)
        return success_object(frl_application_view(a))


@bp.post("/districts/<district_id>/frl-applications/<app_id>/deny")
@require_roles("DistrictReviewer")
def deny(district_id, app_id):
    with lock():
        get_district_or_404(district_id)
        a = get_frl_application_in_district(district_id, app_id)
        body = require_body(request)
        check_version(body, a)
        if a["status"] != "SUBMITTED":
            raise_error("ERR_INVALID_STATE",
                        f"Application is not in SUBMITTED state (current={a['status']})")
        _require_reviewer_not_owning_parent(a)
        review_note = require_field(body, "review_note", kind="string")
        a["status"] = "DENIED"
        a["decided_tier"] = "DENIED_PAID"
        a["review_note"] = review_note
        a["reviewer_user_id"] = g.user_id
        touch(a)
        # Side effect on Student: revert to PAID iff no other APPROVED app
        # for this student governs the current school year.
        s = _student_for_app(a)
        district = STORE.districts[district_id]
        current_sys = district["school_year_start"]
        other_approved = False
        for other in STORE.frl_applications.values():
            if other["id"] == a["id"]:
                continue
            if other["district_id"] != district_id:
                continue
            if other["student_id"] != s["id"]:
                continue
            if other["status"] not in ("APPROVED", "RENEWED_FROM_PRIOR"):
                continue
            if other.get("school_year_start") != current_sys:
                continue
            if other.get("decided_tier") in ("FREE", "REDUCED"):
                other_approved = True
                break
        if not other_approved:
            s["eligibility_tier"] = "PAID"
            s["eligibility_application_id"] = None
            touch(s)
        return success_object(frl_application_view(a))


@bp.post("/districts/<district_id>/frl-applications/<app_id>/auto-renew")
@require_roles("Parent", "AuditOfficer")
def auto_renew(district_id, app_id):
    with lock():
        district = get_district_or_404(district_id)
        a = get_frl_application_in_district(district_id, app_id)
        body = require_body(request)
        check_version(body, a)
        if a["status"] != "DRAFT":
            raise_error("ERR_INVALID_STATE",
                        f"Application is not in DRAFT state (current={a['status']})")
        # Parent ownership scoping (AuditOfficer is unrestricted).
        s = _student_for_app(a)
        if g.user_role == "Parent" and s["parent_account_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN",
                        "Parent may only auto-renew their own student's applications")
        # On auto-renew, the new application's school_year_start is the district's
        # current school year (snapshot at this moment).
        new_sys_iso = district["school_year_start"]
        # Precondition: prior_year_application_id resolves to an APPROVED prior-year app.
        prior_id = a.get("prior_year_application_id")
        if not prior_id:
            raise_error("ERR_RENEWAL_INELIGIBLE",
                        "prior_year_application_id is required for auto-renew")
        prior = STORE.frl_applications.get(prior_id)
        if prior is None or prior["district_id"] != district_id:
            raise_error("ERR_RENEWAL_INELIGIBLE",
                        "prior_year_application_id does not resolve in this district")
        if prior["status"] != "APPROVED":
            raise_error("ERR_RENEWAL_INELIGIBLE",
                        "prior application is not APPROVED")
        if prior.get("decided_tier") not in ("FREE", "REDUCED"):
            raise_error("ERR_RENEWAL_INELIGIBLE",
                        "prior application's decided_tier is not FREE or REDUCED")
        # Check that prior application is in the prior school year.
        new_sys_dt = _parse_iso_dt(new_sys_iso)
        prior_sys_iso = prior.get("school_year_start")
        if not prior_sys_iso:
            raise_error("ERR_RENEWAL_INELIGIBLE",
                        "prior application has no school_year_start snapshot")
        prior_sys_dt = _parse_iso_dt(prior_sys_iso)
        delta_days = (new_sys_dt - prior_sys_dt).total_seconds() / 86400.0
        if abs(delta_days - RENEWAL_YEAR_DAYS_TARGET) > RENEWAL_YEAR_DAYS_TOLERANCE:
            raise_error("ERR_RENEWAL_INELIGIBLE",
                        "prior application is not in the prior school year")
        # Household-size exact match.
        if a["household_size"] != prior["household_size"]:
            raise_error("ERR_RENEWAL_INELIGIBLE",
                        "household_size does not match prior application exactly")
        # Income within ±5%.
        prior_income = prior["declared_annual_income_cents"]
        new_income = a["declared_annual_income_cents"]
        if prior_income == 0:
            # If prior income was 0, the new income must also be 0 to be within ±5%.
            if new_income != 0:
                raise_error("ERR_RENEWAL_INELIGIBLE",
                            "income drift exceeds ±5% tolerance")
        else:
            drift = abs(new_income - prior_income) / float(prior_income)
            if drift > RENEWAL_INCOME_TOLERANCE:
                raise_error("ERR_RENEWAL_INELIGIBLE",
                            "income drift exceeds ±5% tolerance")
        # Apply side effects.
        a["status"] = "RENEWED_FROM_PRIOR"
        a["decided_tier"] = prior["decided_tier"]
        a["federal_poverty_guideline_cents"] = \
            FEDERAL_POVERTY_GUIDELINE_BY_SIZE[a["household_size"]]
        a["reviewer_user_id"] = SYSTEM_AUTO_RENEW_USER_ID
        a["school_year_start"] = new_sys_iso
        touch(a)
        s["eligibility_tier"] = prior["decided_tier"]
        s["eligibility_application_id"] = a["id"]
        touch(s)
        return success_object(frl_application_view(a))
