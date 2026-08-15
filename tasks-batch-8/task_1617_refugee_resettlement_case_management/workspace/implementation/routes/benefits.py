"""BenefitApplication endpoints."""

from flask import Blueprint, request

from db import store, clock_date, new_id, stamp_new, touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_CASE_TRANSFER_PENDING,
    ERR_MEMBER_NOT_ELIGIBLE,
)
from helpers import body_dict, req_string, req_enum
from middleware import authenticate, authorize, CASE_MANAGER
from response import success_object, success_list
from serializers import ser_application
from services import sorted_records

bp = Blueprint("benefits", __name__)

BENEFIT_TYPES = {"SSN", "STATE_ID", "CASH_ASSISTANCE", "MEDICAL", "FOOD_ASSISTANCE"}
APP_STATUSES = {"DRAFT", "FILED", "APPROVED", "DENIED", "APPEALED", "WITHDRAWN"}

# Declared edges of the BenefitApplication state machine (manual transitions;
# DENIED->WITHDRAWN and APPEALED->WITHDRAWN exist only via the system cascade).
EDGES = {
    ("DRAFT", "FILED"),
    ("FILED", "APPROVED"),
    ("FILED", "DENIED"),
    ("DENIED", "APPEALED"),
    ("APPEALED", "FILED"),
    ("DRAFT", "WITHDRAWN"),
    ("FILED", "WITHDRAWN"),
}


def get_application_or_404(app_id):
    app = store.benefit_applications.get(app_id)
    if app is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Benefit application not found.")
    return app


@bp.post("/benefit-applications")
def create_application():
    _uid, role = authenticate()
    authorize(role, {CASE_MANAGER})
    d = body_dict()
    # Priority 3: body FK existence (case_id, then member_id — and the member
    # must belong to the case, else not-found-in-scope).
    case_id = req_string(d, "case_id")
    case = store.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_NOT_FOUND, 404, "case_id does not identify an existing case.")
    member_id = req_string(d, "member_id")
    member = store.members.get(member_id)
    if member is None or member["case_id"] != case["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, "member_id does not identify a member of this case.")
    # Priority 4: schema
    benefit_type = req_enum(d, "benefit_type", BENEFIT_TYPES)
    # Priority 6: state — the case must be ARRIVED
    if case["status"] != "ARRIVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Case must be ARRIVED to open a benefit application.")
    # Priority 9: transfer freeze, then member eligibility
    if case["open_transfer_id"] is not None:
        raise ApiError(ERR_CASE_TRANSFER_PENDING, 409, "Case has an open transfer.")
    if benefit_type == "CASH_ASSISTANCE" and not member["work_eligible"]:
        raise ApiError(
            ERR_MEMBER_NOT_ELIGIBLE,
            422,
            "CASH_ASSISTANCE requires a work-eligible member.",
        )
    app = {
        "id": new_id(),
        "case_id": case["id"],
        "member_id": member["id"],
        "benefit_type": benefit_type,
        "status": "DRAFT",
        "filed_on": None,
        "decided_on": None,
    }
    stamp_new(app)
    store.benefit_applications[app["id"]] = app
    return success_object(ser_application(app), 201)


@bp.get("/benefit-applications/<app_id>")
def get_application(app_id):
    authenticate()
    return success_object(ser_application(get_application_or_404(app_id)))


@bp.get("/benefit-applications")
def list_applications():
    authenticate()
    records = sorted_records(store.benefit_applications.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        records = [a for a in records if a["case_id"] == case_id]
    member_id = request.args.get("member_id")
    if member_id is not None:
        records = [a for a in records if a["member_id"] == member_id]
    status = request.args.get("status")
    if status is not None:
        records = [a for a in records if a["status"] == status]
    return success_list(records, ser_application)


@bp.post("/benefit-applications/<app_id>/transition")
def transition_application(app_id):
    _uid, role = authenticate()
    authorize(role, {CASE_MANAGER})
    app = get_application_or_404(app_id)
    d = body_dict()
    # Priority 4: schema — to_status must be a declared status value
    to_status = req_enum(d, "to_status", APP_STATUSES)
    # Priority 6: state-machine legality
    if (app["status"], to_status) not in EDGES:
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            f"Transition {app['status']} -> {to_status} is not allowed.",
        )
    today = clock_date()
    if to_status == "FILED":
        # Covers both DRAFT->FILED and the APPEALED->FILED re-file cycle
        # (which also clears the prior decision).
        app["filed_on"] = today
        if app["status"] == "APPEALED":
            app["decided_on"] = None
    elif to_status in ("APPROVED", "DENIED"):
        app["decided_on"] = today
    app["status"] = to_status
    touch(app)
    return success_object(ser_application(app), 200)
