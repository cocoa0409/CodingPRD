"""Grant applications and sponsor assurances."""
from decimal import Decimal

from flask import Blueprint, g, request

from auth import ALL_ROLES, require
from domain import (ASSURANCE_CODES, TIER_PCT, app_assurances,
                    application_deadline_dt, application_deadline_str,
                    assurances_cleared, funding_split, ser_application,
                    ser_assurance)
from errors import ApiError, err_invalid_state, err_validation
from store import DB
from util import (body, get_or_404, need, new_entity, r2, respond,
                  respond_list, touch)

bp = Blueprint("applications", __name__)


def _get_app(aid):
    return get_or_404(DB.applications, aid, "GrantApplication")


@bp.route("/aip/grant-applications", methods=["POST"])
@require("SponsorStaff")
def create_application():
    b = body()
    if "sponsor_id" not in b or b["sponsor_id"] is None:
        raise err_validation("Missing required field: sponsor_id")
    sponsor = get_or_404(DB.sponsors, b["sponsor_id"], "Sponsor")
    if "program_id" not in b or b["program_id"] is None:
        raise err_validation("Missing required field: program_id")
    program = get_or_404(DB.programs, b["program_id"], "CapitalProgram")
    if "project_ids" not in b or b["project_ids"] is None:
        raise err_validation("Missing required field: project_ids")
    project_ids = b["project_ids"]
    if not isinstance(project_ids, list):
        raise err_validation("project_ids must be an array")
    projects = []
    for pid in project_ids:
        projects.append(get_or_404(DB.projects, pid, "CIPProject"))
    if len(project_ids) == 0 or len(set(project_ids)) != len(project_ids):
        raise ApiError("ERR_EMPTY_SELECTION", 422,
                       "project_ids must be non-empty with no duplicates")
    for proj in projects:
        if proj["program_id"] != program["id"]:
            raise err_validation(
                "Every project in project_ids must belong to program_id")
    total = sum((p["estimated_cost"] for p in projects), Decimal("0"))
    app = new_entity()
    app.update({
        "sponsor_id": sponsor["id"], "program_id": program["id"],
        "project_ids": list(project_ids), "total_eligible_cost": total,
        "created_by_user_id": g.user_id, "assurances_total": 6,
        "submission_deadline": application_deadline_str(
            program["fiscal_year"]),
        "offered_federal_obligated": None,
        "offered_entitlement_portion": None,
        "created_grant_id": None, "status": "DRAFT"})
    DB.applications[app["id"]] = app
    for code in ASSURANCE_CODES:
        a = new_entity(common=False)
        a.update({"application_id": app["id"], "assurance_code": code,
                  "certified_by_user_id": None, "status": "PENDING"})
        DB.assurances[a["id"]] = a
    return respond(ser_application(app), 201)


@bp.route("/aip/grant-applications", methods=["GET"])
@require(*ALL_ROLES)
def list_applications():
    items = list(DB.applications.values())
    sponsor_id = request.args.get("sponsor_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if sponsor_id is not None:
        items = [a for a in items if a["sponsor_id"] == sponsor_id]
    if program_id is not None:
        items = [a for a in items if a["program_id"] == program_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return respond_list(items, ser_application)


@bp.route("/aip/grant-applications/<applicationId>", methods=["GET"])
@require(*ALL_ROLES)
def get_application(applicationId):
    return respond(ser_application(_get_app(applicationId)))


@bp.route("/aip/grant-applications/<applicationId>/assurances",
          methods=["GET"])
@require(*ALL_ROLES)
def list_assurances(applicationId):
    app = _get_app(applicationId)
    return respond_list(app_assurances(app["id"]), ser_assurance)


@bp.route("/aip/grant-applications/<applicationId>/submit", methods=["POST"])
@require("SponsorStaff")
def submit_application(applicationId):
    app = _get_app(applicationId)
    if app["status"] not in ("DRAFT", "RETURNED"):
        raise err_invalid_state(
            f"GrantApplication in status {app['status']} cannot be submitted")
    program = DB.programs.get(app["program_id"])
    if program is None or program["status"] != "ACCEPTED":
        raise ApiError("ERR_PROGRAM_NOT_ACCEPTED", 409,
                       "Referenced CapitalProgram is not ACCEPTED")
    if DB.clock > application_deadline_dt(program["fiscal_year"]):
        raise ApiError("ERR_APPLICATION_DEADLINE_PASSED", 422,
                       "The submission deadline has passed")
    if len(app["project_ids"]) == 0:
        raise ApiError("ERR_APPLICATION_EMPTY", 422,
                       "project_ids is empty")
    for pid in app["project_ids"]:
        proj = DB.projects.get(pid)
        if proj is None or proj["status"] != "SELECTED":
            raise ApiError("ERR_PROJECT_NOT_SELECTED", 422,
                           "Every project in project_ids must be SELECTED")
    if assurances_cleared(app["id"]) != app["assurances_total"]:
        raise ApiError("ERR_ASSURANCES_INCOMPLETE", 422,
                       "assurances_cleared must equal assurances_total")
    app["status"] = "UNDER_REVIEW"
    touch(app)
    return respond(ser_application(app))


@bp.route("/aip/grant-applications/<applicationId>/return", methods=["POST"])
@require("FAAManager")
def return_application(applicationId):
    app = _get_app(applicationId)
    if app["status"] != "UNDER_REVIEW":
        raise err_invalid_state(
            "Only an UNDER_REVIEW application can be returned")
    app["status"] = "RETURNED"
    touch(app)
    return respond(ser_application(app))


@bp.route("/aip/grant-applications/<applicationId>/offer", methods=["POST"])
@require("FAAManager")
def offer_application(applicationId):
    app = _get_app(applicationId)
    if app["status"] != "UNDER_REVIEW":
        raise err_invalid_state(
            "Only an UNDER_REVIEW application can receive an offer")
    b = body()
    discretionary = Decimal("0")
    if "discretionary_amount" in b and b["discretionary_amount"] is not None:
        from util import as_number
        discretionary = as_number(b["discretionary_amount"],
                                  "discretionary_amount")
        if discretionary < 0:
            raise err_validation("discretionary_amount must be >= 0")
    sponsor = DB.sponsors[app["sponsor_id"]]
    pct = TIER_PCT[sponsor["airport_size_tier"]]
    obligated = r2(pct * app["total_eligible_cost"])
    if obligated > sponsor["npe_entitlement_available"] + discretionary:
        raise ApiError("ERR_ENTITLEMENT_INSUFFICIENT", 402,
                       "Federal obligation exceeds NPE available plus "
                       "discretionary amount")
    app["offered_federal_obligated"] = obligated
    app["offered_entitlement_portion"] = min(
        obligated, sponsor["npe_entitlement_available"])
    app["status"] = "OFFERED"
    touch(app)
    return respond(ser_application(app))


@bp.route("/aip/grant-applications/<applicationId>/accept-offer",
          methods=["POST"])
@require("SponsorStaff")
def accept_offer(applicationId):
    app = _get_app(applicationId)
    if app["status"] != "OFFERED":
        raise err_invalid_state(
            "Only an OFFERED application can accept the offer")
    sponsor = DB.sponsors[app["sponsor_id"]]
    if app["offered_entitlement_portion"] > sponsor["npe_entitlement_available"]:
        raise ApiError("ERR_ENTITLEMENT_INSUFFICIENT", 402,
                       "Offered entitlement portion exceeds NPE available")
    program = DB.programs[app["program_id"]]
    pct = TIER_PCT[sponsor["airport_size_tier"]]
    key = (sponsor["loc_id"], program["fiscal_year"])
    seq = DB.grant_seq.get(key, 0) + 1
    DB.grant_seq[key] = seq
    grant = new_entity()
    total_budget = app["total_eligible_cost"]
    _, state_est, local_est = funding_split(total_budget, pct)
    grant.update({
        "sponsor_id": sponsor["id"], "application_id": app["id"],
        "grant_number": f"AIP-{sponsor['loc_id']}-{program['fiscal_year']}-{seq}",
        "federal_share_pct_dec": pct,
        "total_budget": total_budget,
        "federal_obligated": app["offered_federal_obligated"],
        "federal_drawn": Decimal("0"),
        "state_share_estimated": state_est,
        "local_share_estimated": local_est,
        "entitlement_portion": app["offered_entitlement_portion"],
        "status": "ACTIVE"})
    DB.grants[grant["id"]] = grant
    sponsor["npe_entitlement_available"] -= app["offered_entitlement_portion"]
    touch(sponsor)
    app["status"] = "ACCEPTED"
    app["created_grant_id"] = grant["id"]
    touch(app)
    return respond(ser_application(app))


@bp.route("/aip/grant-applications/<applicationId>/decline-offer",
          methods=["POST"])
@require("SponsorStaff")
def decline_offer(applicationId):
    app = _get_app(applicationId)
    if app["status"] != "OFFERED":
        raise err_invalid_state(
            "Only an OFFERED application can decline the offer")
    app["status"] = "DECLINED"
    touch(app)
    return respond(ser_application(app))


# ---------------------------------------------------------------------------
# Sponsor assurances
# ---------------------------------------------------------------------------

@bp.route("/aip/sponsor-assurances/<assuranceId>/certify", methods=["POST"])
@require("ComplianceOfficer")
def certify_assurance(assuranceId):
    a = get_or_404(DB.assurances, assuranceId, "SponsorAssurance")
    app = DB.applications.get(a["application_id"])
    if a["status"] != "PENDING":
        raise err_invalid_state("Assurance is not PENDING")
    if g.user_id == (app["created_by_user_id"] if app else None):
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "Assurance certifier must differ from the application "
                       "creator")
    a["status"] = "CERTIFIED"
    a["certified_by_user_id"] = g.user_id
    return respond(ser_assurance(a))


@bp.route("/aip/sponsor-assurances/<assuranceId>/waive", methods=["POST"])
@require("FAAManager")
def waive_assurance(assuranceId):
    a = get_or_404(DB.assurances, assuranceId, "SponsorAssurance")
    if a["status"] != "PENDING":
        raise err_invalid_state("Assurance is not PENDING")
    a["status"] = "WAIVED"
    return respond(ser_assurance(a))
