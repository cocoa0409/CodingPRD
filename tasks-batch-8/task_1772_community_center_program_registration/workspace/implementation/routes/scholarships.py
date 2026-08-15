"""ScholarshipApplication endpoints (PRD 3.5)."""
from flask import Blueprint, request

import store
from auth import authenticate, authorize
from errors import raise_err
from util import (
    body_json,
    bump,
    check_int_range,
    get_or_404,
    list_response,
    new_record,
    opt_str,
    req_enum,
    req_int,
    req_str,
    serialize,
    success_object,
)

bp = Blueprint("scholarships", __name__)

FIELDS = [
    "id",
    "household_id",
    "season_id",
    "household_size",
    "annual_income_cents",
    "statement",
    "info_request_note",
    "approved_pct",
    "estimated_commitment_cents",
    "reviewed_by",
    "decided_by",
    "status",
    "created_at",
    "updated_at",
    "version",
]

READ_ROLES = ["HouseholdManager", "ScholarshipReviewer", "FinanceOfficer", "ProgramCoordinator"]
LIVE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "MORE_INFO_REQUESTED", "RESUBMITTED", "APPROVED")
WITHDRAWABLE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "MORE_INFO_REQUESTED", "RESUBMITTED")


def application_out(rec):
    return serialize(rec, FIELDS)


@bp.route("/scholarship-applications", methods=["POST"])
def create_application():
    uid, role = authenticate()
    authorize(role, ["HouseholdManager"])
    body = body_json()
    household_id = req_str(body, "household_id")
    season_id = req_str(body, "season_id")
    household_size = req_int(body, "household_size")
    annual_income_cents = req_int(body, "annual_income_cents")
    statement = opt_str(body, "statement", "")
    check_int_range(household_size, 1, None, "household_size")
    check_int_range(annual_income_cents, 0, None, "annual_income_cents")
    get_or_404(store.households, household_id, "Household")
    get_or_404(store.seasons, season_id, "Season")
    # The duplicate guard is evaluated before the ownership check (PRD 3.5).
    for a in store.applications.values():
        if a["household_id"] == household_id and a["season_id"] == season_id and a["status"] in LIVE_STATUSES:
            raise_err("ERR_DUPLICATE_SCHOLARSHIP_APPLICATION", "A live application already exists for this household and season")
    if household_id != uid:
        raise_err("ERR_NOT_HOUSEHOLD_MEMBER", "Applications may only be filed for the caller's household")
    rec = new_record()
    rec.update(
        household_id=household_id,
        season_id=season_id,
        household_size=household_size,
        annual_income_cents=annual_income_cents,
        statement=statement,
        info_request_note=None,
        approved_pct=None,
        estimated_commitment_cents=None,
        reviewed_by=None,
        decided_by=None,
        status="SUBMITTED",
    )
    store.applications[rec["id"]] = rec
    return success_object(application_out(rec), 201)


@bp.route("/scholarship-applications", methods=["GET"])
def list_applications():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    household_id = request.args.get("household_id")
    season_id = request.args.get("season_id")
    status = request.args.get("status")
    records = list(store.applications.values())
    if household_id is not None:
        records = [r for r in records if r["household_id"] == household_id]
    if season_id is not None:
        records = [r for r in records if r["season_id"] == season_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, application_out)


@bp.route("/scholarship-applications/<application_id>", methods=["GET"])
def get_application(application_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    rec = get_or_404(store.applications, application_id, "ScholarshipApplication")
    return success_object(application_out(rec), 200)


@bp.route("/scholarship-applications/<application_id>/start-review", methods=["POST"])
def start_review(application_id):
    uid, role = authenticate()
    authorize(role, ["ScholarshipReviewer"])
    rec = get_or_404(store.applications, application_id, "ScholarshipApplication")
    if rec["status"] not in ("SUBMITTED", "RESUBMITTED"):
        raise_err("ERR_INVALID_STATE", "Only a SUBMITTED or RESUBMITTED application can enter review")
    rec["status"] = "UNDER_REVIEW"
    rec["reviewed_by"] = uid
    bump(rec)
    return success_object(application_out(rec), 200)


@bp.route("/scholarship-applications/<application_id>/request-info", methods=["POST"])
def request_info(application_id):
    _, role = authenticate()
    authorize(role, ["ScholarshipReviewer"])
    body = body_json()
    note = req_str(body, "info_request_note")
    rec = get_or_404(store.applications, application_id, "ScholarshipApplication")
    if rec["status"] != "UNDER_REVIEW":
        raise_err("ERR_INVALID_STATE", "Only an UNDER_REVIEW application can be sent an info request")
    rec["status"] = "MORE_INFO_REQUESTED"
    rec["info_request_note"] = note
    bump(rec)
    return success_object(application_out(rec), 200)


@bp.route("/scholarship-applications/<application_id>/resubmit", methods=["POST"])
def resubmit(application_id):
    uid, role = authenticate()
    authorize(role, ["HouseholdManager"])
    body = body_json()
    statement = req_str(body, "statement")
    rec = get_or_404(store.applications, application_id, "ScholarshipApplication")
    if rec["status"] != "MORE_INFO_REQUESTED":
        raise_err("ERR_INVALID_STATE", "Only a MORE_INFO_REQUESTED application can be resubmitted")
    if rec["household_id"] != uid:
        raise_err("ERR_NOT_HOUSEHOLD_MEMBER", "Only the applicant household may resubmit")
    rec["status"] = "RESUBMITTED"
    rec["statement"] = statement
    bump(rec)
    return success_object(application_out(rec), 200)


@bp.route("/scholarship-applications/<application_id>/approve", methods=["POST"])
def approve(application_id):
    uid, role = authenticate()
    authorize(role, ["ScholarshipReviewer"])
    body = body_json()
    raw_pct = body.get("approved_pct")
    if not (isinstance(raw_pct, int) and not isinstance(raw_pct, bool)) or raw_pct not in (25, 50, 75, 100):
        raise_err("ERR_INVALID_REQUEST", "approved_pct must be one of 25, 50, 75, 100")
    estimated = req_int(body, "estimated_commitment_cents")
    check_int_range(estimated, 0, None, "estimated_commitment_cents")
    rec = get_or_404(store.applications, application_id, "ScholarshipApplication")
    # State legality first, then segregation of duties, then the budget cap.
    if rec["status"] != "UNDER_REVIEW":
        raise_err("ERR_INVALID_STATE", "Only an UNDER_REVIEW application can be approved")
    if rec["reviewed_by"] == uid:
        raise_err("ERR_SEGREGATION_OF_DUTIES", "The reviewing reviewer may not also approve")
    season = store.seasons.get(rec["season_id"])
    if season is not None:
        prospective = season["scholarship_committed_cents"] + estimated
        if prospective > season["scholarship_budget_cents"]:
            raise_err("ERR_SCHOLARSHIP_BUDGET_EXCEEDED", "Approval would exceed the season scholarship budget")
    rec["status"] = "APPROVED"
    rec["approved_pct"] = raw_pct
    rec["estimated_commitment_cents"] = estimated
    rec["decided_by"] = uid
    bump(rec)
    if season is not None:
        season["scholarship_committed_cents"] += estimated
        bump(season)
    return success_object(application_out(rec), 200)


@bp.route("/scholarship-applications/<application_id>/deny", methods=["POST"])
def deny(application_id):
    uid, role = authenticate()
    authorize(role, ["ScholarshipReviewer"])
    body_json()  # optional reason is accepted and not persisted
    rec = get_or_404(store.applications, application_id, "ScholarshipApplication")
    if rec["status"] != "UNDER_REVIEW":
        raise_err("ERR_INVALID_STATE", "Only an UNDER_REVIEW application can be denied")
    rec["status"] = "DENIED"
    rec["decided_by"] = uid
    bump(rec)
    return success_object(application_out(rec), 200)


@bp.route("/scholarship-applications/<application_id>/withdraw", methods=["POST"])
def withdraw(application_id):
    uid, role = authenticate()
    authorize(role, ["HouseholdManager"])
    rec = get_or_404(store.applications, application_id, "ScholarshipApplication")
    if rec["status"] not in WITHDRAWABLE_STATUSES:
        raise_err("ERR_INVALID_STATE", "Only a pre-decision application can be withdrawn")
    if rec["household_id"] != uid:
        raise_err("ERR_NOT_HOUSEHOLD_MEMBER", "Only the applicant household may withdraw")
    rec["status"] = "WITHDRAWN"
    bump(rec)
    return success_object(application_out(rec), 200)


@bp.route("/scholarship-applications/<application_id>/revoke", methods=["POST"])
def revoke(application_id):
    _, role = authenticate()
    authorize(role, ["FinanceOfficer"])
    rec = get_or_404(store.applications, application_id, "ScholarshipApplication")
    if rec["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Only an APPROVED application can be revoked")
    rec["status"] = "REVOKED"
    bump(rec)
    season = store.seasons.get(rec["season_id"])
    if season is not None:
        season["scholarship_committed_cents"] -= rec["estimated_commitment_cents"] or 0
        bump(season)
    return success_object(application_out(rec), 200)
