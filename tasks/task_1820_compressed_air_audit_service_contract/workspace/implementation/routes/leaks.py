"""Leak surveys and leak tags: pipeline from DRAFT to VERIFIED_CLOSED."""

from flask import Blueprint, request

from auth import require_roles, check_ownership, owning_facility_id
from domain import compute_deemed, leak_annual_savings
from envelope import ok_object, ok_list
from errors import (
    ApiError,
    conflict,
    invalid_request,
    invalid_state,
    not_found,
    unprocessable,
    ERR_EMPTY_SURVEY,
    ERR_FACILITY_NOT_ACTIVE,
    ERR_REPAIR_BUDGET_EXCEEDED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SURVEY_NOT_VERIFIED,
)
import store
from store import new_resource, touch
from util import body_or_empty, dec, parse_pagination, public, req_date, req_int, req_num, req_str, sort_and_page

bp = Blueprint("leaks", __name__)

ALL_ROLES = ["DealerAdmin", "EnergyEngineer", "ServiceTech", "ContractManager", "FacilityManager"]


def _get_survey_or_404(survey_id):
    survey = store.leak_surveys.get(survey_id)
    if survey is None:
        raise not_found("LeakSurvey not found")
    return survey


def _get_tag_or_404(tag_id):
    tag = store.leak_tags.get(tag_id)
    if tag is None:
        raise not_found("LeakTag not found")
    return tag


def _survey_tags(survey_id):
    return [t for t in store.leak_tags.values() if t["survey_id"] == survey_id]


# ---------------------------------------------------------------------------
# LeakSurvey
# ---------------------------------------------------------------------------

@bp.route("/leak-surveys", methods=["POST"])
def create_survey():
    require_roles(["EnergyEngineer"])
    body = body_or_empty()
    facility_id = req_str(body, "facility_id")
    survey_date = req_date(body, "survey_date")
    if store.facilities.get(facility_id) is None:
        raise not_found("Facility not found")

    survey = new_resource()
    survey.update(
        {
            "facility_id": facility_id,
            "survey_date": survey_date.isoformat(),
            "status": "DRAFT",
            "submitted_by_user_id": None,
            "verified_by_user_id": None,
            "total_leak_cfm": None,
            "tag_count": None,
        }
    )
    store.leak_surveys[survey["id"]] = survey
    return ok_object(public(survey), 201)


@bp.route("/leak-surveys", methods=["GET"])
def list_surveys():
    require_roles(ALL_ROLES)
    items = list(store.leak_surveys.values())
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    if facility_id is not None:
        items = [s for s in items if s["facility_id"] == facility_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    limit, offset = parse_pagination()
    page, total = sort_and_page(items, limit, offset)
    return ok_list([public(s) for s in page], limit, offset, total)


@bp.route("/leak-surveys/<leakSurveyId>", methods=["GET"])
def get_survey(leakSurveyId):
    user_id, role = require_roles(ALL_ROLES)
    survey = _get_survey_or_404(leakSurveyId)
    check_ownership(user_id, role, survey["facility_id"])
    return ok_object(public(survey), 200)


@bp.route("/leak-surveys/<leakSurveyId>/leak-tags", methods=["POST"])
def add_tag(leakSurveyId):
    require_roles(["EnergyEngineer"])
    survey = _get_survey_or_404(leakSurveyId)
    body = body_or_empty()
    location = req_str(body, "location_description")
    cfm_loss = req_num(body, "cfm_loss")
    quote = req_int(body, "repair_quote_cents")
    if dec(cfm_loss) <= 0:
        raise invalid_request("cfm_loss must be greater than zero")
    if quote < 0:
        raise invalid_request("repair_quote_cents must be zero or more")

    if survey["status"] != "DRAFT":
        raise invalid_state("LeakTags may only be added to a DRAFT survey")

    tag = new_resource()
    tag.update(
        {
            "survey_id": survey["id"],
            "location_description": location,
            "cfm_loss": float(cfm_loss) if isinstance(cfm_loss, int) else cfm_loss,
            "repair_quote_cents": quote,
            "severity": None,
            "priority_rank": None,
            "annual_kwh_savings": None,
            "status": "TAGGED",
            "repaired_by_user_id": None,
        }
    )
    store.leak_tags[tag["id"]] = tag
    return ok_object(public(tag), 201)


@bp.route("/leak-surveys/<leakSurveyId>/submit", methods=["POST"])
def submit_survey(leakSurveyId):
    user_id, _role = require_roles(["EnergyEngineer"])
    survey = _get_survey_or_404(leakSurveyId)
    if survey["status"] != "DRAFT":
        raise invalid_state("LeakSurvey must be DRAFT to submit")
    tags = _survey_tags(survey["id"])
    if len(tags) < 1:
        raise unprocessable(ERR_EMPTY_SURVEY, "Survey must contain at least one LeakTag")
    survey["status"] = "SUBMITTED"
    survey["submitted_by_user_id"] = user_id
    touch(survey)
    for tag in tags:
        if tag["status"] == "TAGGED":
            tag["status"] = "QUOTED"
            touch(tag)
    return ok_object(public(survey), 200)


@bp.route("/leak-surveys/<leakSurveyId>/verify", methods=["POST"])
def verify_survey(leakSurveyId):
    user_id, _role = require_roles(["EnergyEngineer"])
    survey = _get_survey_or_404(leakSurveyId)
    if survey["status"] != "SUBMITTED":
        raise invalid_state("LeakSurvey must be SUBMITTED to verify")
    if user_id == survey["submitted_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "Verifier must differ from submitter")

    tags = _survey_tags(survey["id"])
    # severity bands: LOW < 2.0; MEDIUM 2.0..10.0 inclusive; HIGH > 10.0
    for tag in tags:
        cfm = dec(tag["cfm_loss"])
        if cfm < dec("2.0"):
            severity = "LOW"
        elif cfm <= dec("10.0"):
            severity = "MEDIUM"
        else:
            severity = "HIGH"
        if tag["severity"] != severity:
            tag["severity"] = severity

    # priority rank: cfm_loss DESC, tie repair_quote_cents ASC, tie created_at ASC
    ranked = sorted(tags, key=lambda t: (-dec(t["cfm_loss"]), t["repair_quote_cents"], t["created_at"]))
    for idx, tag in enumerate(ranked, start=1):
        tag["priority_rank"] = idx
        touch(tag)

    total_cfm = sum(dec(t["cfm_loss"]) for t in tags)
    survey["verified_by_user_id"] = user_id
    survey["status"] = "VERIFIED"
    survey["total_leak_cfm"] = float(total_cfm)
    survey["tag_count"] = len(tags)
    touch(survey)
    return ok_object(public(survey), 200)


# ---------------------------------------------------------------------------
# LeakTag
# ---------------------------------------------------------------------------

@bp.route("/leak-tags", methods=["GET"])
def list_tags():
    require_roles(ALL_ROLES)
    items = list(store.leak_tags.values())
    survey_id = request.args.get("survey_id")
    status = request.args.get("status")
    if survey_id is not None:
        items = [t for t in items if t["survey_id"] == survey_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    limit, offset = parse_pagination()
    page, total = sort_and_page(items, limit, offset)
    return ok_list([public(t) for t in page], limit, offset, total)


@bp.route("/leak-tags/<leakTagId>", methods=["GET"])
def get_tag(leakTagId):
    user_id, role = require_roles(ALL_ROLES)
    tag = _get_tag_or_404(leakTagId)
    check_ownership(user_id, role, owning_facility_id("leak_tag", tag))
    return ok_object(public(tag), 200)


@bp.route("/leak-tags/<leakTagId>/authorize-repair", methods=["POST"])
def authorize_repair(leakTagId):
    user_id, role = require_roles(["FacilityManager"])
    tag = _get_tag_or_404(leakTagId)
    survey = store.leak_surveys.get(tag["survey_id"])
    fac = store.facilities.get(survey["facility_id"]) if survey else None
    check_ownership(user_id, role, survey["facility_id"] if survey else None)

    # gates in pinned order: state -> facility ACTIVE -> survey VERIFIED -> budget
    if tag["status"] != "QUOTED":
        raise invalid_state("LeakTag must be QUOTED to authorize repair")
    if fac is None or fac["status"] != "ACTIVE":
        raise conflict(ERR_FACILITY_NOT_ACTIVE, "Facility must be ACTIVE to authorize repair")
    if survey["status"] != "VERIFIED":
        raise conflict(ERR_SURVEY_NOT_VERIFIED, "Parent LeakSurvey must be VERIFIED")
    if fac["repair_committed_cents"] + tag["repair_quote_cents"] > fac["repair_budget_cents"]:
        raise conflict(ERR_REPAIR_BUDGET_EXCEEDED, "Repair budget would be exceeded")

    tag["status"] = "REPAIR_AUTHORIZED"
    touch(tag)
    fac["repair_committed_cents"] += tag["repair_quote_cents"]
    touch(fac)
    return ok_object(public(tag), 200)


@bp.route("/leak-tags/<leakTagId>/mark-repaired", methods=["POST"])
def mark_repaired(leakTagId):
    user_id, _role = require_roles(["ServiceTech"])
    tag = _get_tag_or_404(leakTagId)
    if tag["status"] != "REPAIR_AUTHORIZED":
        raise invalid_state("LeakTag must be REPAIR_AUTHORIZED to mark repaired")
    tag["status"] = "REPAIRED"
    tag["repaired_by_user_id"] = user_id
    touch(tag)
    return ok_object(public(tag), 200)


@bp.route("/leak-tags/<leakTagId>/verify-closure", methods=["POST"])
def verify_closure(leakTagId):
    require_roles(["EnergyEngineer"])
    tag = _get_tag_or_404(leakTagId)
    if tag["status"] != "REPAIRED":
        raise invalid_state("LeakTag must be REPAIRED to verify closure")
    survey = store.leak_surveys.get(tag["survey_id"])
    fac = store.facilities.get(survey["facility_id"]) if survey else None
    tag["status"] = "VERIFIED_CLOSED"
    tag["annual_kwh_savings"] = leak_annual_savings(tag["cfm_loss"], fac["operating_hours_per_year"])
    touch(tag)
    # MODELED savings cases of this facility recompute deemed savings immediately
    for case in store.savings_cases.values():
        if case["facility_id"] == fac["id"] and case["savings_status"] == "MODELED":
            case["deemed_annual_savings_kwh"] = compute_deemed(case)
            touch(case)
    return ok_object(public(tag), 200)


@bp.route("/leak-tags/<leakTagId>/mark-wont-fix", methods=["POST"])
def mark_wont_fix(leakTagId):
    user_id, role = require_roles(["FacilityManager"])
    tag = _get_tag_or_404(leakTagId)
    survey = store.leak_surveys.get(tag["survey_id"])
    fac = store.facilities.get(survey["facility_id"]) if survey else None
    check_ownership(user_id, role, survey["facility_id"] if survey else None)
    if tag["status"] not in ("QUOTED", "REPAIR_AUTHORIZED"):
        raise invalid_state("LeakTag must be QUOTED or REPAIR_AUTHORIZED to mark wont-fix")
    was_authorized = tag["status"] == "REPAIR_AUTHORIZED"
    tag["status"] = "WONT_FIX"
    touch(tag)
    if was_authorized and fac is not None:
        fac["repair_committed_cents"] -= tag["repair_quote_cents"]
        touch(fac)
    return ok_object(public(tag), 200)
