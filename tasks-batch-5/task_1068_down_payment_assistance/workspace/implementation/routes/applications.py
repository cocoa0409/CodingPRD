from flask import Blueprint

import store
from errors import ApiError
import context as ctx
import calc
from serializers import public, public_list
import envelope as env

bp = Blueprint("applications", __name__)

REVIEW_DECISIONS = {"START", "NEEDS_INFO", "ELIGIBLE", "INELIGIBLE"}


def _income_limit_for(program_id, household_size):
    for il in store.income_limits.values():
        if il["program_id"] == program_id and il["household_size"] == household_size:
            return il
    return None


def _recompute_provisional(app):
    """Compute ami_pct and provisional estimated_assistance_cents from current inputs."""
    program = store.programs[app["program_id"]]
    applicant = store.applicants[app["applicant_id"]]
    prop = store.properties[app["property_id"]]
    il = _income_limit_for(app["program_id"], applicant["household_size"])
    ami = calc.ami_pct(applicant["annual_income_cents"], il["ami_100_income_cents"])
    app["ami_pct"] = ami
    app["estimated_assistance_cents"] = calc.assistance_amount(
        basis_cents=prop["purchase_price_cents"],
        first_mortgage_cents=app["first_mortgage_amount_cents"],
        stated_contribution_cents=app["buyer_contribution_cents"],
        ami_pct_dec=ami,
        max_assistance_cents=program["max_assistance_cents"],
    )


@bp.post("/applications")
def create_application():
    ctx.authenticate(["Applicant", "CaseManager"])
    data = ctx.body()
    # Body FK existence (left-to-right) before structural validation.
    applicant_id = data.get("applicant_id")
    if applicant_id is not None:
        ctx.lookup("applicant", applicant_id)
    program_id = data.get("program_id")
    if program_id is not None:
        ctx.lookup("program", program_id)
    property_id = data.get("property_id")
    if property_id is not None:
        ctx.lookup("property", property_id)

    applicant_id = ctx.req_str(data, "applicant_id")
    program_id = ctx.req_str(data, "program_id")
    property_id = ctx.req_str(data, "property_id")
    first_mortgage_amount_cents = ctx.req_int(data, "first_mortgage_amount_cents", 0)
    buyer_contribution_cents = ctx.req_int(data, "buyer_contribution_cents", 0)

    rec = store.new_record("application")
    rec.update({
        "applicant_id": applicant_id,
        "program_id": program_id,
        "property_id": property_id,
        "first_mortgage_amount_cents": first_mortgage_amount_cents,
        "buyer_contribution_cents": buyer_contribution_cents,
        "ami_pct": None,
        "estimated_assistance_cents": None,
        "reviewed_by_user_id": None,
        "status": "DRAFT",
    })
    store.applications[rec["id"]] = rec
    return env.success(public(rec), 201)


@bp.get("/applications/<aid>")
def get_application(aid):
    ctx.authenticate(["Applicant", "CaseManager", "ProgramAdmin"])
    rec = ctx.lookup("application", aid)
    return env.success(public(rec), 200)


@bp.get("/applications")
def list_applications():
    ctx.authenticate(["CaseManager", "ProgramAdmin"])
    limit, offset = ctx.pagination_params()
    filters = {
        "applicant_id": ctx.query_filter("applicant_id"),
        "program_id": ctx.query_filter("program_id"),
        "property_id": ctx.query_filter("property_id"),
        "status": ctx.query_filter("status"),
    }
    page, total = ctx.paginate(store.applications.values(), limit, offset, filters)
    return env.list_response(public_list(page), limit, offset, total)


@bp.post("/applications/<aid>/submit")
def submit_application(aid):
    ctx.authenticate(["Applicant"])
    app = ctx.lookup("application", aid)
    if app["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Application is not in DRAFT.")
    program = store.programs[app["program_id"]]
    if program["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Program is not OPEN.")
    applicant = store.applicants[app["applicant_id"]]
    if _income_limit_for(app["program_id"], applicant["household_size"]) is None:
        raise ApiError("ERR_INCOME_LIMIT_UNDEFINED",
                       "No income-limit row for this program and household size.")
    _recompute_provisional(app)
    app["status"] = "SUBMITTED"
    store.touch(app)
    return env.success(public(app), 200)


@bp.post("/applications/<aid>/review")
def review_application(aid):
    uid, _ = ctx.authenticate(["CaseManager"])
    app = ctx.lookup("application", aid)
    data = ctx.body()
    decision = ctx.req_enum(data, "decision", REVIEW_DECISIONS)

    if decision == "START":
        if app["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Application is not SUBMITTED.")
        app["status"] = "UNDER_REVIEW"
        store.touch(app)
        return env.success(public(app), 200)

    # NEEDS_INFO / ELIGIBLE / INELIGIBLE require UNDER_REVIEW.
    if app["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Application is not UNDER_REVIEW.")

    if decision == "NEEDS_INFO":
        app["status"] = "NEEDS_INFO"
        store.touch(app)
        return env.success(public(app), 200)

    if decision == "ELIGIBLE":
        applicant = store.applicants[app["applicant_id"]]
        program = store.programs[app["program_id"]]
        il = _income_limit_for(app["program_id"], applicant["household_size"])
        if il is None or not calc.is_eligible(
                applicant["annual_income_cents"], il["ami_100_income_cents"],
                program["ami_limit_pct"]):
            raise ApiError("ERR_INCOME_OVER_LIMIT", "Applicant income exceeds the AMI ceiling.")
        app["status"] = "ELIGIBLE"
        app["reviewed_by_user_id"] = uid
        store.touch(app)
        return env.success(public(app), 200)

    # INELIGIBLE
    app["status"] = "INELIGIBLE"
    app["reviewed_by_user_id"] = uid
    store.touch(app)
    return env.success(public(app), 200)


@bp.post("/applications/<aid>/resubmit")
def resubmit_application(aid):
    ctx.authenticate(["Applicant"])
    app = ctx.lookup("application", aid)
    if app["status"] != "NEEDS_INFO":
        raise ApiError("ERR_INVALID_STATE", "Application is not in NEEDS_INFO.")
    applicant = store.applicants[app["applicant_id"]]
    if _income_limit_for(app["program_id"], applicant["household_size"]) is None:
        raise ApiError("ERR_INCOME_LIMIT_UNDEFINED",
                       "No income-limit row for this program and household size.")
    _recompute_provisional(app)
    app["status"] = "UNDER_REVIEW"
    store.touch(app)
    return env.success(public(app), 200)


@bp.post("/applications/<aid>/withdraw")
def withdraw_application(aid):
    ctx.authenticate(["Applicant"])
    app = ctx.lookup("application", aid)
    if app["status"] not in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"):
        raise ApiError("ERR_INVALID_STATE", "Application is not in a withdrawable state.")
    app["status"] = "WITHDRAWN"
    store.touch(app)
    return env.success(public(app), 200)
