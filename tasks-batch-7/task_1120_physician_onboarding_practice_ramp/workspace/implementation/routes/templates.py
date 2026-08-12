"""Schedule template endpoints (PRD 3.5)."""

from flask import Blueprint, request

import domain as D
from db import store, new_record, bump
from errors import (
    ApiError, ERR_VALIDATION, ERR_CASE_NOT_FOUND,
    ERR_SCHEDULE_TEMPLATE_NOT_FOUND, ERR_TEMPLATE_NOT_DRAFT,
    ERR_TEMPLATE_NOT_ACTIVE, ERR_TEMPLATE_OVERLAP,
)
from middleware import get_context, require_role
from response import success_object, paginate

bp = Blueprint("templates", __name__)


def _get_template(tid):
    template = store.schedule_templates.get(tid)
    if template is None:
        raise ApiError(ERR_SCHEDULE_TEMPLATE_NOT_FOUND, 404, "ScheduleTemplate not found")
    return template


def _recompute_case_practice(case):
    D.recompute_practice(case)
    D.recompute_posture(case)


@bp.route("/onboarding/schedule-templates", methods=["POST"])
def create_template():
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    body = D.get_body()
    case_id = D.req_str(body, "onboarding_case_id")
    weekday = D.req_int(body, "weekday")
    start_minute = D.req_int(body, "start_minute")
    end_minute = D.req_int(body, "end_minute")
    block_type = D.req_enum(body, "block_type", D.BLOCK_TYPES)
    case = store.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, 404, "OnboardingCase not found")
    if not (1 <= weekday <= 7):
        raise ApiError(ERR_VALIDATION, 400, "weekday must be between 1 and 7")
    if not (0 <= start_minute <= 1439):
        raise ApiError(ERR_VALIDATION, 400, "start_minute must be between 0 and 1439")
    if not (1 <= end_minute <= 1440):
        raise ApiError(ERR_VALIDATION, 400, "end_minute must be between 1 and 1440")
    if start_minute >= end_minute:
        raise ApiError(ERR_VALIDATION, 400, "start_minute must precede end_minute")
    rec = new_record()
    rec.update({
        "onboarding_case_id": case_id,
        "weekday": weekday,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "block_type": block_type,
        "status": "DRAFT",
    })
    store.schedule_templates[rec["id"]] = rec
    bump(case)
    return success_object(D.serialize_template(rec), status=201)


@bp.route("/onboarding/schedule-templates/<tid>", methods=["GET"])
def get_template(tid):
    get_context()
    return success_object(D.serialize_template(_get_template(tid)))


@bp.route("/onboarding/schedule-templates", methods=["GET"])
def list_templates():
    get_context()
    case_id = request.args.get("onboarding_case_id")
    weekday = request.args.get("weekday")
    status = request.args.get("status")
    records = sorted(store.schedule_templates.values(), key=lambda r: r["_seq"])
    if case_id is not None:
        records = [r for r in records if r["onboarding_case_id"] == case_id]
    if weekday is not None:
        try:
            weekday_val = int(weekday)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "weekday filter must be an integer")
        records = [r for r in records if r["weekday"] == weekday_val]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate([D.serialize_template(r) for r in records], request.args)


@bp.route("/onboarding/schedule-templates/<tid>/activate", methods=["POST"])
def activate_template(tid):
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    template = _get_template(tid)
    if template["status"] != "DRAFT":
        raise ApiError(ERR_TEMPLATE_NOT_DRAFT, 409, "Template must be DRAFT to activate")
    for other in D.templates_of_case(template["onboarding_case_id"]):
        if other["id"] == template["id"]:
            continue
        if other["status"] != "ACTIVE" or other["weekday"] != template["weekday"]:
            continue
        # Half-open interval overlap; touching boundaries are allowed.
        if template["start_minute"] < other["end_minute"] and \
                other["start_minute"] < template["end_minute"]:
            raise ApiError(ERR_TEMPLATE_OVERLAP, 422,
                           "Template overlaps an ACTIVE template of the same case and weekday")
    template["status"] = "ACTIVE"
    bump(template)
    case = store.cases.get(template["onboarding_case_id"])
    if case is not None:
        _recompute_case_practice(case)
        bump(case)
    return success_object(D.serialize_template(template))


@bp.route("/onboarding/schedule-templates/<tid>/retire", methods=["POST"])
def retire_template(tid):
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    template = _get_template(tid)
    if template["status"] != "ACTIVE":
        raise ApiError(ERR_TEMPLATE_NOT_ACTIVE, 409, "Template must be ACTIVE to retire")
    template["status"] = "RETIRED"
    bump(template)
    case = store.cases.get(template["onboarding_case_id"])
    if case is not None:
        D.recompute_practice(case)
        D.freeze_panel_if_unready(case)
        D.recompute_posture(case)
        bump(case)
    return success_object(D.serialize_template(template))
