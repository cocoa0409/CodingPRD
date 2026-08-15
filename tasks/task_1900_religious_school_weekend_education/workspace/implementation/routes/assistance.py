"""AssistanceApplication endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from errors import (
    ApiError, invalid_request, invalid_state, not_found, ownership_mismatch,
    ERR_SCHOOL_YEAR_NOT_OPEN, ERR_APPLICATION_ALREADY_OPEN,
    ERR_SEGREGATION_OF_DUTIES, ERR_AWARD_PARAMS_INVALID,
)
from services.core import base_record, touch, public, get_family, get_application

bp = Blueprint("assistance", __name__)


@bp.route("/school/families/<family_id>/assistance-applications", methods=["POST"])
def create_application(family_id):
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    if role == "Parent" and user_id != family_id:
        raise ownership_mismatch()
    family = get_family(family_id)
    body = request.get_json(silent=True) or {}
    school_year_id = body.get("school_year_id")
    reason = body.get("reason")
    requested = body.get("requested_amount_cents")
    if not isinstance(school_year_id, str):
        raise invalid_request("school_year_id is required")
    if not isinstance(reason, str) or not reason:
        raise invalid_request("reason is required")
    if requested is not None:
        if isinstance(requested, bool) or not isinstance(requested, int) or requested <= 0:
            raise invalid_request("requested_amount_cents must be > 0 when present")

    year = store.school_years.get(school_year_id)
    if year is None:
        raise not_found("SchoolYear not found")
    if year["status"] != "OPEN":
        raise ApiError(ERR_SCHOOL_YEAR_NOT_OPEN, 409, "School year is not OPEN")

    for app in store.applications.values():
        if (
            app["family_id"] == family["id"]
            and app["school_year_id"] == school_year_id
            and app["status"] != "DENIED"
        ):
            raise ApiError(ERR_APPLICATION_ALREADY_OPEN, 409, "Family already has a non-DENIED application for the year")

    rec = base_record()
    rec.update({
        "family_id": family["id"],
        "school_year_id": school_year_id,
        "reason": reason,
        "requested_amount_cents": requested,
        "status": "SUBMITTED",
        "reviewed_by_user_id": None,
        "award_method": None,
        "award_percent": None,
        "award_amount_cents": None,
        "decided_by_user_id": None,
    })
    store.applications[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/school/families/<family_id>/assistance-applications", methods=["GET"])
def list_family_applications(family_id):
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    if role == "Parent" and user_id != family_id:
        raise ownership_mismatch()
    family = get_family(family_id)
    limit, offset = parse_pagination(request.args)
    items = [a for a in store.applications.values() if a["family_id"] == family["id"]]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([public(a) for a in page], limit, offset, total)


@bp.route("/school/assistance-applications/<app_id>", methods=["GET"])
def get_application_endpoint(app_id):
    role, user_id = require_roles(["SchoolAdmin", "AssistanceOfficer", "Parent"])
    rec = get_application(app_id)
    if role == "Parent" and rec["family_id"] != user_id:
        raise ownership_mismatch()
    return success_object(public(rec))


@bp.route("/school/assistance-applications", methods=["GET"])
def list_applications():
    role, user_id = require_roles(["SchoolAdmin", "AssistanceOfficer"])
    limit, offset = parse_pagination(request.args)
    family_id = request.args.get("family_id")
    school_year_id = request.args.get("school_year_id")
    status = request.args.get("status")
    items = list(store.applications.values())
    if family_id is not None:
        items = [a for a in items if a["family_id"] == family_id]
    if school_year_id is not None:
        items = [a for a in items if a["school_year_id"] == school_year_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([public(a) for a in page], limit, offset, total)


@bp.route("/school/assistance-applications/<app_id>/start-review", methods=["POST"])
def start_review(app_id):
    role, user_id = require_roles(["AssistanceOfficer"])
    rec = get_application(app_id)
    if rec["status"] != "SUBMITTED":
        raise invalid_state("Application is not SUBMITTED")
    rec["status"] = "UNDER_REVIEW"
    rec["reviewed_by_user_id"] = user_id
    touch(rec)
    return success_object(public(rec))


@bp.route("/school/assistance-applications/<app_id>/request-info", methods=["POST"])
def request_info(app_id):
    role, user_id = require_roles(["AssistanceOfficer"])
    rec = get_application(app_id)
    if rec["status"] != "UNDER_REVIEW":
        raise invalid_state("Application is not UNDER_REVIEW")
    rec["status"] = "SUBMITTED"
    touch(rec)
    return success_object(public(rec))


@bp.route("/school/assistance-applications/<app_id>/decide", methods=["POST"])
def decide(app_id):
    role, user_id = require_roles(["SchoolAdmin"])
    rec = get_application(app_id)
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("APPROVED", "DENIED"):
        raise invalid_request("decision must be APPROVED or DENIED")
    award_method = body.get("award_method")
    award_percent = body.get("award_percent")
    award_amount_cents = body.get("award_amount_cents")

    # request-shape validation for conditional award fields
    if decision == "APPROVED":
        if award_method is not None and award_method not in ("PERCENT_OF_NET", "FLAT_CAP"):
            # bad enum member in request payload — treat as request shape error at priority 5
            raise invalid_request("award_method must be PERCENT_OF_NET or FLAT_CAP")

    if rec["status"] != "UNDER_REVIEW":
        raise invalid_state("Application is not UNDER_REVIEW")

    # segregation of duties
    if rec.get("reviewed_by_user_id") is not None and rec["reviewed_by_user_id"] == user_id:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 409, "Decider must differ from reviewer")

    if decision == "APPROVED":
        # award params consistent with method
        if award_method not in ("PERCENT_OF_NET", "FLAT_CAP"):
            raise ApiError(ERR_AWARD_PARAMS_INVALID, 409, "award_method required for approval")
        if award_method == "PERCENT_OF_NET":
            if (
                award_percent is None
                or isinstance(award_percent, bool)
                or not isinstance(award_percent, (int, float))
                or not (0 < award_percent <= 1)
            ):
                raise ApiError(ERR_AWARD_PARAMS_INVALID, 409, "award_percent must be in (0, 1]")
        else:  # FLAT_CAP
            if (
                award_amount_cents is None
                or isinstance(award_amount_cents, bool)
                or not isinstance(award_amount_cents, int)
                or award_amount_cents <= 0
            ):
                raise ApiError(ERR_AWARD_PARAMS_INVALID, 409, "award_amount_cents must be > 0")
        rec["award_method"] = award_method
        rec["award_percent"] = award_percent if award_method == "PERCENT_OF_NET" else None
        rec["award_amount_cents"] = award_amount_cents if award_method == "FLAT_CAP" else None
        rec["status"] = "APPROVED"
    else:
        rec["status"] = "DENIED"

    rec["decided_by_user_id"] = user_id
    touch(rec)
    return success_object(public(rec))
