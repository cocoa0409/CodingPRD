"""Projects and regulatory agreements."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError, invalid
from services import calc, lookup, project_svc

bp = Blueprint("projects", __name__)

READ_ROLES = (mw.PROGRAM_ADMINISTRATOR, mw.HOUSING_COMPLIANCE_OFFICER,
              mw.DEVELOPER, mw.FUND_AUDITOR)

DISTRICTS = ("R-2", "R-4", "C-2")
COMPLIANCE_PATHS = ("ONSITE", "OFFSITE", "IN_LIEU_FEE", "LAND_DEDICATION")
RESALE_FORMULAS = ("AMI_INDEXED", "SHARED_APPRECIATION")
AGREEMENT_REQUIRED_PATHS = ("ONSITE", "OFFSITE")


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------
@bp.route("/iz-compliance/projects", methods=["POST"])
def create_project():
    user_id, _role = mw.auth(mw.DEVELOPER)
    payload = mw.body()
    name = mw.take_str(payload, "name", min_len=1, max_len=120)
    zoning_district = mw.take_enum(payload, "zoning_district", DISTRICTS)
    total_units = mw.take_int(payload, "total_units", lo=1)
    approval_date = mw.take_date(payload, "approval_date")

    row = db.insert(db.projects, project_svc.new_project_row(
        name, user_id, zoning_district, total_units, approval_date))
    return response.created(db.public(row))


@bp.route("/iz-compliance/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    mw.auth(*READ_ROLES)
    return response.ok(db.public(lookup.fetch("project", project_id)))


@bp.route("/iz-compliance/projects", methods=["GET"])
def list_projects():
    mw.auth(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.filtered(db.projects,
                       ("ordinance_id", "state", "applicability", "compliance_posture"))
    return response.listing([db.public(r) for r in mw.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.route("/iz-compliance/projects/<project_id>/screen", methods=["POST"])
def screen_project(project_id):
    mw.auth(mw.HOUSING_COMPLIANCE_OFFICER, mw.PROGRAM_ADMINISTRATOR)
    project = lookup.fetch("project", project_id)

    if project.get("state") != "DRAFT":
        raise ApiError("ERR_INVALID_PROJECT_STATE",
                       "Screening requires the project to be in DRAFT.")

    ordinance = calc.select_ordinance(project.get("approval_date"))
    applicability, required, fractional, total_obligation = \
        calc.required_units_and_fraction(project, ordinance)

    project["ordinance_id"] = ordinance["id"]
    project["applicability"] = applicability
    project["required_affordable_units"] = required
    project["fractional_obligation_bps"] = fractional
    project["total_obligation_bps"] = total_obligation
    project["state"] = "SCREENED_SUBJECT" if applicability == "SUBJECT" else "SCREENED_EXEMPT"
    project["screened_at"] = db.fmt_dt(db.logical_now())
    project["screen_count"] = int(project.get("screen_count") or 0) + 1
    project_svc.refresh(project)

    return response.ok(db.public(project))


@bp.route("/iz-compliance/projects/<project_id>", methods=["PATCH"])
def amend_project(project_id):
    user_id, role = mw.auth(mw.DEVELOPER)
    payload = mw.body()
    name = mw.take_str(payload, "name", required=False, min_len=1, max_len=120)
    zoning_district = mw.take_enum(payload, "zoning_district", DISTRICTS, required=False)
    total_units = mw.take_int(payload, "total_units", required=False, lo=1)
    approval_date = mw.take_date(payload, "approval_date", required=False)

    project = lookup.fetch("project", project_id)
    lookup.require_project_owner(project, user_id, role)

    if project.get("state") not in ("DRAFT", "SCREENED_SUBJECT", "SCREENED_EXEMPT",
                                    "PATH_ELECTED", "AGREEMENT_RECORDED"):
        raise ApiError("ERR_INVALID_PROJECT_STATE",
                       "A CLOSED_OUT or MONITORING project cannot be amended.")

    if name is not None:
        project["name"] = name
    if zoning_district is not None:
        project["zoning_district"] = zoning_district
    if total_units is not None:
        project["total_units"] = total_units
    if approval_date is not None:
        project["approval_date"] = approval_date

    # Amending the entitlement re-opens screening.
    project["state"] = "DRAFT"
    project["applicability"] = "PENDING"
    project["required_affordable_units"] = 0
    project["fractional_obligation_bps"] = 0
    project["total_obligation_bps"] = 0
    project["compliance_path"] = None
    project["ordinance_id"] = None
    project_svc.refresh(project)

    return response.ok(db.public(project))


@bp.route("/iz-compliance/projects/<project_id>/elect-path", methods=["POST"])
def elect_path(project_id):
    user_id, role = mw.auth(mw.DEVELOPER)
    payload = mw.body()
    compliance_path = mw.take_enum(payload, "compliance_path", COMPLIANCE_PATHS)

    project = lookup.fetch("project", project_id)
    lookup.require_project_owner(project, user_id, role)

    if project.get("state") != "SCREENED_SUBJECT":
        raise ApiError("ERR_INVALID_PROJECT_STATE",
                       "Electing a compliance path requires state SCREENED_SUBJECT.")

    ordinance = lookup.maybe("ordinance", project.get("ordinance_id"))
    allowed = list((ordinance or {}).get("alternative_paths_allowed") or [])
    if compliance_path != "ONSITE" and compliance_path not in allowed:
        raise ApiError("ERR_PATH_NOT_PERMITTED",
                       "The governing ordinance does not permit path %s." % compliance_path)

    project["compliance_path"] = compliance_path
    project["state"] = "PATH_ELECTED"
    project_svc.refresh(project)

    return response.ok(db.public(project))


@bp.route("/iz-compliance/projects/<project_id>/close-out", methods=["POST"])
def close_out(project_id):
    mw.auth(mw.PROGRAM_ADMINISTRATOR, mw.HOUSING_COMPLIANCE_OFFICER)
    project = lookup.fetch("project", project_id)

    if project.get("state") != "MONITORING":
        raise ApiError("ERR_INVALID_PROJECT_STATE",
                       "Close-out requires the project to be MONITORING.")

    units = lookup.project_units(project_id)

    # rung 25 -- bedroom distribution
    calc.check_bedroom_distribution(project, units)

    # rung 58 -- the obligation itself must be satisfied
    if project.get("compliance_posture") not in ("COMPLIANT_ONSITE", "COMPLIANT_BY_FEE"):
        raise ApiError("ERR_OBLIGATION_UNSATISFIED",
                       "The project's compliance posture is %s."
                       % project.get("compliance_posture"))

    # rung 59 -- no money left on the table
    for fee in lookup.project_fees(project_id):
        if fee.get("state") not in ("PAID", "SUPERSEDED"):
            raise ApiError("ERR_FEE_OUTSTANDING")

    # rung 60 -- no open monitoring finding
    for unit in units:
        for review in lookup.unit_reviews(unit["id"]):
            if review.get("state") in ("FINDING_ISSUED", "CURE_SUBMITTED", "ESCALATED"):
                raise ApiError("ERR_OPEN_FINDING_BLOCKS_CLOSEOUT")

    project["state"] = "CLOSED_OUT"
    for agreement in lookup.project_agreements(project_id):
        if agreement.get("state") == "RECORDED":
            agreement["state"] = "RELEASED"
            db.touch(agreement)
    project_svc.refresh(project)

    return response.ok(db.public(project))


# --------------------------------------------------------------------------
# Regulatory agreements
# --------------------------------------------------------------------------
@bp.route("/iz-compliance/regulatory-agreements", methods=["POST"])
def create_agreement():
    mw.auth(mw.HOUSING_COMPLIANCE_OFFICER, mw.PROGRAM_ADMINISTRATOR)
    payload = mw.body()
    project_id = mw.take_str(payload, "project_id")
    term_years = mw.take_int(payload, "term_years", lo=30, hi=99)
    resale_formula = mw.take_enum(payload, "resale_formula", RESALE_FORMULAS)
    owner_share = mw.take_int(payload, "owner_appreciation_share_bps", lo=0, hi=calc.BPS)
    max_ltv = mw.take_int(payload, "max_refinance_ltv_bps", lo=0, hi=calc.BPS)

    lookup.fetch("project", project_id)

    row = db.insert(db.agreements, {
        "project_id": project_id,
        "term_years": term_years,
        "resale_formula": resale_formula,
        "owner_appreciation_share_bps": owner_share,
        "max_refinance_ltv_bps": max_ltv,
        "doc_number": None,
        "recorded_at": None,
        "state": "DRAFT",
    })
    return response.created(db.public(row))


@bp.route("/iz-compliance/regulatory-agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    mw.auth(*READ_ROLES)
    return response.ok(db.public(lookup.fetch("agreement", agreement_id)))


@bp.route("/iz-compliance/regulatory-agreements", methods=["GET"])
def list_agreements():
    mw.auth(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.filtered(db.agreements, ("project_id", "state"))
    return response.listing([db.public(r) for r in mw.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.route("/iz-compliance/regulatory-agreements/<agreement_id>/record", methods=["POST"])
def record_agreement(agreement_id):
    mw.auth(mw.HOUSING_COMPLIANCE_OFFICER)
    payload = mw.body()
    doc_number = mw.take_str(payload, "doc_number", min_len=1, max_len=120)
    recorded_at = mw.take_date_loose(payload, "recorded_at")

    agreement = lookup.fetch("agreement", agreement_id)
    project = lookup.maybe("project", agreement.get("project_id"))
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")

    # rung 9
    if project.get("state") != "PATH_ELECTED":
        raise ApiError("ERR_INVALID_PROJECT_STATE",
                       "Recording requires the project to be PATH_ELECTED.")
    # rung 10
    if agreement.get("state") != "DRAFT":
        raise ApiError("ERR_AGREEMENT_NOT_RECORDED",
                       "Only a DRAFT agreement can be recorded.")
    # rung 29
    for existing in db.all_rows(db.agreements):
        if existing["id"] == agreement_id:
            continue
        if existing.get("doc_number") is not None and existing.get("doc_number") == doc_number:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "doc_number '%s' is already recorded." % doc_number)
    # rung 51
    if project.get("compliance_path") not in AGREEMENT_REQUIRED_PATHS:
        raise ApiError("ERR_AGREEMENT_NOT_REQUIRED")
    # rung 52
    recorded_day = db.parse_date_loose(recorded_at)
    approval_day = db.parse_date_loose(project.get("approval_date"))
    if approval_day is not None and recorded_day is not None and recorded_day < approval_day:
        raise ApiError("ERR_RECORDING_PREDATES_APPROVAL")

    agreement["state"] = "RECORDED"
    agreement["doc_number"] = doc_number
    agreement["recorded_at"] = recorded_at
    db.touch(agreement)

    project["state"] = "AGREEMENT_RECORDED"
    project_svc.refresh(project)

    return response.ok(db.public(agreement))
