"""AssistanceEnrollment endpoints (PRD §3.3)."""

from flask import Blueprint

import db
from errors import (not_found, ApiError, ERR_INVALID_STATE,
                    ERR_ACTIVE_ENROLLMENT_EXISTS)
from middleware import authenticate, check_ownership
from response import success_object, success_list
from serializers import enrollment as ser_enrollment
from services.common import active_enrollment
from services.tiers import DISCOUNT_PCT
from validate import (get_body, validate_shape, parse_pagination, parse_filters,
                      paginate, sort_by_creation)

bp = Blueprint("enrollments", __name__)

ENROLLMENT_STATUSES = {"PENDING", "ACTIVE", "LAPSED", "TERMINATED"}
TIERS = {"TIER_1", "TIER_2", "TIER_3"}
GET_ROLES = ["Customer", "CustomerServiceRep", "EligibilitySpecialist", "ProgramAdmin"]
LIST_ROLES = ["CustomerServiceRep", "EligibilitySpecialist", "ProgramAdmin"]


def get_enrollment_or_404(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if e is None:
        raise not_found("Enrollment not found")
    return e


@bp.route("/assistance/enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment(enrollment_id):
    actor = authenticate(GET_ROLES)
    e = db.enrollments.get(enrollment_id)
    if e is not None:
        check_ownership(actor, e["account_id"])
    if e is None:
        raise not_found("Enrollment not found")
    return success_object(ser_enrollment(e))


@bp.route("/assistance/enrollments", methods=["GET"])
def list_enrollments():
    authenticate(LIST_ROLES)
    limit, offset = parse_pagination()
    filters = parse_filters({"account_id": "str", "application_id": "str",
                             "status": ENROLLMENT_STATUSES, "tier": TIERS})
    items = sort_by_creation(db.enrollments.values())
    for key in ("account_id", "application_id", "status", "tier"):
        if key in filters:
            items = [x for x in items if x[key] == filters[key]]
    page, total = paginate(items, limit, offset)
    return success_list([ser_enrollment(x) for x in page], limit, offset, total)


@bp.route("/assistance/enrollments/<enrollment_id>/activate", methods=["POST"])
def activate(enrollment_id):
    authenticate(["CustomerServiceRep", "ProgramAdmin"])
    e = get_enrollment_or_404(enrollment_id)
    # generic state check precedes the one-active constraint (PRD §3.3)
    if e["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Activate requires enrollment status PENDING")
    if active_enrollment(e["account_id"]) is not None:
        raise ApiError(ERR_ACTIVE_ENROLLMENT_EXISTS, 422,
                       "Another enrollment is already ACTIVE on this account")
    e["status"] = "ACTIVE"
    e["activated_on"] = db.CLOCK.date()
    e["recert_due_on"] = db.add_days(db.CLOCK.date(), 365)
    db.touch(e)
    return success_object(ser_enrollment(e))


@bp.route("/assistance/enrollments/<enrollment_id>/recertify", methods=["POST"])
def recertify(enrollment_id):
    authenticate(["EligibilitySpecialist"])
    body = validate_shape(get_body(allow_empty=False),
                          [("new_application_id", "string", True, None)])
    e = get_enrollment_or_404(enrollment_id)
    new_app = db.applications.get(body["new_application_id"])
    if new_app is None:
        raise not_found("Referenced application not found")
    if e["status"] != "LAPSED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Recertify requires enrollment status LAPSED")
    if (new_app["status"] != "VERIFIED"
            or new_app["account_id"] != e["account_id"]
            or new_app["id"] == e["application_id"]):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "new_application_id must reference a different VERIFIED "
                       "application on the same account")
    e["status"] = "ACTIVE"
    e["tier"] = new_app["benefit_tier"]
    e["discount_pct"] = DISCOUNT_PCT[new_app["benefit_tier"]]
    e["recert_due_on"] = db.add_days(db.CLOCK.date(), 365)
    e["lapsed_on"] = None
    db.touch(e)
    return success_object(ser_enrollment(e))


@bp.route("/assistance/enrollments/<enrollment_id>/terminate", methods=["POST"])
def terminate(enrollment_id):
    authenticate(["ProgramAdmin"])
    e = get_enrollment_or_404(enrollment_id)
    if e["status"] not in ("PENDING", "ACTIVE", "LAPSED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Terminate requires a non-terminal enrollment")
    e["status"] = "TERMINATED"
    db.touch(e)
    return success_object(ser_enrollment(e))
