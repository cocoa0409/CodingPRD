"""ReserveStudy endpoints."""

from flask import request, Blueprint
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from errors import (
    make_error, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_STUDY_IN_PROGRESS, ERR_STUDY_WINDOW_OVERLAP, ERR_SITE_VISIT_CADENCE,
    ERR_STUDY_EMPTY, ERR_NO_FUNDING_PLAN, ERR_STUDY_NOT_DRAFT,
    ERR_NO_PLAN_SELECTED, ERR_PLAN_TYPE_NOT_ALLOWED,
    ERR_PERCENT_FUNDED_BELOW_MINIMUM, ERR_STALE_VERSION, ERR_PLAN_TYPE_LOCKED,
)
from services.fiscal import fiscal_year_for_date, study_window, windows_overlap
from services.calculations import (
    recompute_study_totals, find_adopted_study, special_assessment_analysis,
    get_active_included_components,
)
from datetime import date, timedelta

bp = Blueprint("studies", __name__)

VALID_STUDY_TYPES = {"FULL", "UPDATE_WITH_VISIT", "UPDATE_NO_VISIT"}


def serialize_study(study):
    return {
        "id": study["id"],
        "created_at": study["created_at"],
        "updated_at": study["updated_at"],
        "version": study["version"],
        "association_id": study["association_id"],
        "fiscal_year": study["fiscal_year"],
        "study_type": study["study_type"],
        "inflation_rate": study["inflation_rate"],
        "interest_rate": study["interest_rate"],
        "status": study["status"],
        "window_start_date": study["window_start_date"],
        "window_end_date_exclusive": study["window_end_date_exclusive"],
        "fully_funded_balance_cents": study["fully_funded_balance_cents"],
        "percent_funded": study["percent_funded"],
        "adopted_at": study.get("adopted_at"),
        "adopted_plan_id": study.get("adopted_plan_id"),
    }


def _find_state_rule(state_code):
    for r in store.state_reserve_rules.values():
        if r["state_code"] == state_code:
            return r
    return None


def _parse_pagination():
    """Parse limit/offset query params with defaults."""
    try:
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    offset = max(0, offset)
    return limit, offset


@bp.route("/reserve-studies", methods=["POST"])
def create_study():
    require_roles("ReserveSpecialist")
    body = request.get_json(force=True, silent=True) or {}

    required = ["association_id", "fiscal_year", "study_type", "inflation_rate", "interest_rate"]
    allowed = set(required)
    for field in required:
        if field not in body:
            raise make_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    for key in body:
        if key not in allowed:
            raise make_error(ERR_INVALID_REQUEST, f"Unknown field: {key}")

    assoc_id = body["association_id"]
    fiscal_year = body["fiscal_year"]
    study_type = body["study_type"]
    inflation = body["inflation_rate"]
    interest = body["interest_rate"]

    # Existence: association must exist
    assoc = store.associations.get(assoc_id)
    if not assoc:
        raise make_error(ERR_NOT_FOUND, f"Association {assoc_id} not found")

    # Shape validation
    if not isinstance(fiscal_year, int):
        raise make_error(ERR_INVALID_REQUEST, "fiscal_year must be an integer")
    if study_type not in VALID_STUDY_TYPES:
        raise make_error(ERR_INVALID_REQUEST, f"Invalid study_type: {study_type}")
    if not isinstance(inflation, (int, float)) or inflation < 0:
        raise make_error(ERR_INVALID_REQUEST, "inflation_rate must be non-negative")
    if not isinstance(interest, (int, float)) or interest < 0:
        raise make_error(ERR_INVALID_REQUEST, "interest_rate must be non-negative")

    # Uniqueness: at most one DRAFT/SUBMITTED study per association
    for s in store.reserve_studies.values():
        if s["association_id"] == assoc_id and s["status"] in ("DRAFT", "SUBMITTED"):
            raise make_error(ERR_STUDY_IN_PROGRESS, "Association already has a study in progress")

    # Compute fiscal window
    ws, we = study_window(fiscal_year, assoc["fiscal_year_end_month"])

    # Check overlap with ADOPTED studies of same association
    for s in store.reserve_studies.values():
        if s["association_id"] == assoc_id and s["status"] == "ADOPTED":
            if windows_overlap(ws, we, s["window_start_date"], s["window_end_date_exclusive"]):
                raise make_error(ERR_STUDY_WINDOW_OVERLAP, "Fiscal window overlaps an ADOPTED study")

    study = store.make_common_fields()
    study.update({
        "association_id": assoc_id,
        "fiscal_year": fiscal_year,
        "study_type": study_type,
        "inflation_rate": inflation,
        "interest_rate": interest,
        "status": "DRAFT",
        "window_start_date": ws,
        "window_end_date_exclusive": we,
        "fully_funded_balance_cents": 0,
        "percent_funded": 100.00,
        "adopted_at": None,
        "adopted_plan_id": None,
    })
    store.reserve_studies[study["id"]] = study
    return success_object(serialize_study(study), 201)


@bp.route("/reserve-studies/<id>", methods=["GET"])
def get_study(id):
    require_roles(*ANY_ROLE)
    study = store.reserve_studies.get(id)
    if not study:
        raise make_error(ERR_NOT_FOUND, f"ReserveStudy {id} not found")
    return success_object(serialize_study(study))


@bp.route("/associations/<id>/reserve-studies", methods=["GET"])
def list_studies_for_association(id):
    require_roles(*ANY_ROLE)
    assoc = store.associations.get(id)
    if not assoc:
        raise make_error(ERR_NOT_FOUND, f"Association {id} not found")

    status_filter = request.args.get("status")
    studies = [s for s in store.reserve_studies.values() if s["association_id"] == id]
    if status_filter:
        studies = [s for s in studies if s["status"] == status_filter]
    studies.sort(key=lambda s: s["created_at"])

    limit, offset = _parse_pagination()
    total = len(studies)
    page = studies[offset:offset + limit]
    return success_list([serialize_study(s) for s in page], total, limit, offset)


@bp.route("/reserve-studies", methods=["GET"])
def list_studies():
    require_roles(*ANY_ROLE)
    studies = list(store.reserve_studies.values())

    assoc_filter = request.args.get("association_id")
    if assoc_filter:
        studies = [s for s in studies if s["association_id"] == assoc_filter]

    adopted_plan_filter = request.args.get("adopted_plan_id")
    if adopted_plan_filter:
        studies = [s for s in studies if s.get("adopted_plan_id") == adopted_plan_filter]

    status_filter = request.args.get("status")
    if status_filter:
        studies = [s for s in studies if s["status"] == status_filter]

    studies.sort(key=lambda s: s["created_at"])
    limit, offset = _parse_pagination()
    total = len(studies)
    page = studies[offset:offset + limit]
    return success_list([serialize_study(s) for s in page], total, limit, offset)


@bp.route("/reserve-studies/<id>/submit", methods=["POST"])
def submit_study(id):
    require_roles("ReserveSpecialist")
    study = store.reserve_studies.get(id)
    if not study:
        raise make_error(ERR_NOT_FOUND, f"ReserveStudy {id} not found")

    if study["status"] != "DRAFT":
        raise make_error(ERR_INVALID_STATE, f"Study is {study['status']}, not DRAFT")

    assoc = store.associations[study["association_id"]]
    state_rule = _find_state_rule(assoc["state_code"])

    # 1) Site-visit cadence check
    if state_rule:
        cadence_days = 365 * state_rule["site_visit_interval_years"]
        if study["study_type"] == "UPDATE_NO_VISIT":
            cadence_days *= 2

        today = store.get_clock().date()
        completed_visits = [
            v for v in store.site_visits.values()
            if v["association_id"] == study["association_id"] and v["status"] == "COMPLETED"
        ]
        cadence_ok = False
        for v in completed_visits:
            vd = date.fromisoformat(v["visit_date"])
            diff = (today - vd).days
            if 0 <= diff <= cadence_days:
                cadence_ok = True
                break
        if not cadence_ok:
            raise make_error(ERR_SITE_VISIT_CADENCE, "No COMPLETED site visit within the statutory window")

    # 2) Content minimum: >= 1 ACTIVE + included component
    active_included = get_active_included_components(id)
    if len(active_included) == 0:
        raise make_error(ERR_STUDY_EMPTY, "Study has no ACTIVE, funding-included components")

    # 3) Content minimum: >= 1 non-RETIRED plan
    plans = [
        p for p in store.funding_plans.values()
        if p["study_id"] == id and p["status"] in ("DRAFT", "RECOMMENDED", "SELECTED")
    ]
    if len(plans) == 0:
        raise make_error(ERR_NO_FUNDING_PLAN, "Study has no non-RETIRED funding plans")

    study["status"] = "SUBMITTED"
    store.touch(study)
    return success_object(serialize_study(study))


@bp.route("/reserve-studies/<id>/adopt", methods=["POST"])
def adopt_study(id):
    require_roles("BoardMember")
    study = store.reserve_studies.get(id)
    if not study:
        raise make_error(ERR_NOT_FOUND, f"ReserveStudy {id} not found")

    if study["status"] != "SUBMITTED":
        raise make_error(ERR_INVALID_STATE, f"Study is {study['status']}, not SUBMITTED")

    # Exactly one SELECTED plan
    selected_plans = [
        p for p in store.funding_plans.values()
        if p["study_id"] == id and p["status"] == "SELECTED"
    ]
    if len(selected_plans) != 1:
        raise make_error(ERR_NO_PLAN_SELECTED, "Exactly one plan must be SELECTED")

    selected_plan = selected_plans[0]
    assoc = store.associations[study["association_id"]]
    state_rule = _find_state_rule(assoc["state_code"])

    # Plan type allowed
    if state_rule and selected_plan["plan_type"] not in state_rule["allowed_plan_types"]:
        raise make_error(ERR_PLAN_TYPE_NOT_ALLOWED, f"Plan type {selected_plan['plan_type']} not allowed in {assoc['state_code']}")

    # Percent funded meets minimum
    if state_rule and study["percent_funded"] < state_rule["min_percent_funded_pct"]:
        raise make_error(ERR_PERCENT_FUNDED_BELOW_MINIMUM, f"Percent funded {study['percent_funded']} below minimum {state_rule['min_percent_funded_pct']}")

    # Supersede any previously ADOPTED study of same association
    for s in store.reserve_studies.values():
        if s["association_id"] == study["association_id"] and s["status"] == "ADOPTED" and s["id"] != id:
            s["status"] = "SUPERSEDED"
            store.touch(s)
            # Retire its DRAFT/RECOMMENDED/SELECTED plans
            for p in store.funding_plans.values():
                if p["study_id"] == s["id"] and p["status"] in ("DRAFT", "RECOMMENDED", "SELECTED"):
                    p["status"] = "RETIRED"
                    store.touch(p)
            # Void its PENDING disclosures
            for d in store.disclosures.values():
                if d["study_id"] == s["id"] and d["status"] == "PENDING":
                    d["status"] = "VOIDED"
                    store.touch(d)

    # Adopt this study
    study["status"] = "ADOPTED"
    study["adopted_at"] = store.now_iso()
    study["adopted_plan_id"] = selected_plan["id"]
    store.touch(study)

    # Create ADOPTION_SUMMARY disclosure
    disclosure_days = state_rule["disclosure_deadline_days"] if state_rule else 0
    due_date = (store.get_clock() + timedelta(days=disclosure_days)).strftime("%Y-%m-%d")
    disclosure = store.make_common_fields()
    disclosure.update({
        "study_id": study["id"],
        "disclosure_type": "ADOPTION_SUMMARY",
        "status": "PENDING",
        "due_date": due_date,
        "distributed_at": None,
    })
    store.disclosures[disclosure["id"]] = disclosure

    # Set compliance to COMPLIANT
    assoc["statutory_compliance_status"] = "COMPLIANT"

    return success_object(serialize_study(study))


@bp.route("/reserve-studies/<id>/reject", methods=["POST"])
def reject_study(id):
    require_roles("BoardMember")
    study = store.reserve_studies.get(id)
    if not study:
        raise make_error(ERR_NOT_FOUND, f"ReserveStudy {id} not found")

    if study["status"] != "SUBMITTED":
        raise make_error(ERR_INVALID_STATE, f"Study is {study['status']}, not SUBMITTED")

    body = request.get_json(force=True, silent=True) or {}

    study["status"] = "DRAFT"
    store.touch(study)

    # SELECTED plan -> DRAFT
    for p in store.funding_plans.values():
        if p["study_id"] == id and p["status"] == "SELECTED":
            p["status"] = "DRAFT"
            store.touch(p)

    # RECOMMENDED plan -> DRAFT
    for p in store.funding_plans.values():
        if p["study_id"] == id and p["status"] == "RECOMMENDED":
            p["status"] = "DRAFT"
            store.touch(p)

    return success_object(serialize_study(study))


@bp.route("/reserve-studies/<id>/withdraw", methods=["POST"])
def withdraw_study(id):
    require_roles("ReserveSpecialist")
    study = store.reserve_studies.get(id)
    if not study:
        raise make_error(ERR_NOT_FOUND, f"ReserveStudy {id} not found")

    if study["status"] != "DRAFT":
        raise make_error(ERR_INVALID_STATE, f"Study is {study['status']}, not DRAFT")

    study["status"] = "WITHDRAWN"
    store.touch(study)

    # DRAFT/RECOMMENDED plans -> RETIRED
    for p in store.funding_plans.values():
        if p["study_id"] == id and p["status"] in ("DRAFT", "RECOMMENDED"):
            p["status"] = "RETIRED"
            store.touch(p)

    return success_object(serialize_study(study))


@bp.route("/reserve-studies/<id>/special-assessment-analysis", methods=["GET"])
def get_special_assessment(id):
    require_roles(*ANY_ROLE)
    study = store.reserve_studies.get(id)
    if not study:
        raise make_error(ERR_NOT_FOUND, f"ReserveStudy {id} not found")
    if study["status"] != "ADOPTED":
        raise make_error(ERR_INVALID_STATE, f"Study is {study['status']}, not ADOPTED")

    result = special_assessment_analysis(study)
    return success_object(result)
