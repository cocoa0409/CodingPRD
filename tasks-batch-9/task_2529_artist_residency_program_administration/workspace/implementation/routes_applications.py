"""Applicants, applications, the fee decision, intake transitions and portfolio items."""

import calc
import domain as D
import store as K
from auth import authorize, require_owner
from envelope import object_response, paged, query_str
from errors import ApiError
from flask import Blueprint
from store import create_row, store, touch
from validate import (bad, body, fk, opt_bool, opt_int, opt_str, path_row,
                      req_decimal, req_enum, req_int, req_str)

bp = Blueprint("applications", __name__)

COUNTRY_PATTERN = r"^[A-Z]{2}$"
APPLICATION_EDITABLE = ("DRAFT", "REVISION_REQUESTED")
APPLICATION_TERMINAL = ("REJECTED", "ACCEPTED", "DECLINED")

READ_APPLICANT_ROLES = ["ProgramAdmin", "PanelChair", "FinanceOfficer", "VisaCoordinator"]
READ_APPLICATION_ROLES = ["ProgramAdmin", "PanelChair", "Panelist", "Applicant", "Funder"]
READ_PORTFOLIO_ROLES = ["ProgramAdmin", "PanelChair", "Panelist", "Applicant"]


# ---------------------------------------------------------------- applicants
@bp.route("/applicants", methods=["POST"])
def create_applicant():
    authorize(["ProgramAdmin", "Applicant"])
    b = body()
    full_name = req_str(b, "full_name", min_len=1, max_len=200)
    email = req_str(b, "email", min_len=1, max_len=320)
    affiliation = req_str(b, "affiliation_org", min_len=1, max_len=200)
    country = req_str(b, "citizenship_country", min_len=2, max_len=2,
                      pattern=COUNTRY_PATTERN)
    treaty = opt_bool(b, "treaty_country", default=False)
    income = req_int(b, "declared_annual_income_cents", minimum=0)

    for row in store.applicants.values():
        if row["email"] == email:
            raise ApiError("ERR_DUPLICATE_CODE", "applicant email %s already exists" % email)

    row = create_row(store.applicants, {
        "full_name": full_name,
        "email": email,
        "affiliation_org": affiliation,
        "citizenship_country": country,
        "treaty_country": treaty,
        "declared_annual_income_cents": income,
    })
    return object_response(D.ser_applicant(row), 201)


@bp.route("/applicants", methods=["GET"])
def list_applicants():
    authorize(READ_APPLICANT_ROLES)
    email = query_str("email")
    country = query_str("citizenship_country")
    rows = D.by_seq(list(store.applicants.values()))
    if email is not None:
        rows = [r for r in rows if r["email"] == email]
    if country is not None:
        rows = [r for r in rows if r["citizenship_country"] == country]
    return paged(rows, D.ser_applicant)


@bp.route("/applicants/<applicant_id>", methods=["GET"])
def get_applicant(applicant_id):
    authorize(READ_APPLICANT_ROLES + ["Applicant"])
    row = path_row(store.applicants, applicant_id, "ERR_APPLICANT_NOT_FOUND")
    return object_response(D.ser_applicant(row))


@bp.route("/applicants/<applicant_id>", methods=["PATCH"])
def patch_applicant(applicant_id):
    authorize(["ProgramAdmin", "Applicant"])
    row = path_row(store.applicants, applicant_id, "ERR_APPLICANT_NOT_FOUND")
    b = body()
    full_name = opt_str(b, "full_name", min_len=1, max_len=200)
    affiliation = opt_str(b, "affiliation_org", min_len=1, max_len=200)
    country = opt_str(b, "citizenship_country", min_len=2, max_len=2,
                      pattern=COUNTRY_PATTERN)
    treaty = opt_bool(b, "treaty_country")
    income = opt_int(b, "declared_annual_income_cents", minimum=0)

    if full_name is not None:
        row["full_name"] = full_name
    if affiliation is not None:
        row["affiliation_org"] = affiliation
    if country is not None:
        row["citizenship_country"] = country
    if treaty is not None:
        row["treaty_country"] = treaty
    if income is not None:
        row["declared_annual_income_cents"] = income
    touch(row)
    return object_response(D.ser_applicant(row))


# ---------------------------------------------------------------- applications
@bp.route("/applications", methods=["POST"])
def create_application():
    authorize(["ProgramAdmin", "Applicant"])
    b = body()
    # group 2 -- body foreign keys in declaration order
    cycle = fk(b, "cycle_id", store.cycles, "ERR_CYCLE_NOT_FOUND")
    applicant = fk(b, "applicant_id", store.applicants, "ERR_APPLICANT_NOT_FOUND")
    discipline = fk(b, "discipline_id", store.disciplines, "ERR_DISCIPLINE_NOT_FOUND")
    # group 3 -- shape and declared ranges
    req_str(b, "cycle_id")
    req_str(b, "applicant_id")
    req_str(b, "discipline_id")
    weeks = req_int(b, "requested_session_length_weeks",
                    minimum=K.MIN_SESSION_WEEKS, maximum=K.MAX_SESSION_WEEKS)
    statement = req_str(b, "project_statement", min_len=1, max_len=4000)
    waiver_requested = opt_bool(b, "fee_waiver_requested", default=False)
    # group 3 -- the cross-entity referential check
    if discipline["cycle_id"] != cycle["id"]:
        raise ApiError("ERR_DISCIPLINE_CYCLE_MISMATCH",
                       "the named discipline belongs to a different cycle")
    # group 6 -- cycle stage
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", "applications may only be opened while the cycle is OPEN")
    # group 9 -- offered session lengths
    if weeks not in cycle["session_length_options_weeks"]:
        raise ApiError("ERR_SESSION_LENGTH_NOT_OFFERED",
                       "%d weeks is not one of this cycle's session length options" % weeks)
    # group 10 -- duplicate association
    for row in store.applications.values():
        if row["cycle_id"] == cycle["id"] and row["applicant_id"] == applicant["id"]:
            raise ApiError("ERR_DUPLICATE_ASSOCIATION",
                           "this artist already has an application in this cycle")

    row = create_row(store.applications, {
        "cycle_id": cycle["id"],
        "applicant_id": applicant["id"],
        "discipline_id": discipline["id"],
        "requested_session_length_weeks": weeks,
        "project_statement": statement,
        "fee_waiver_requested": waiver_requested,
        "fee_status": "PENDING",
        "fee_waiver_reason": None,
        "status": "DRAFT",
        "revision_round": 0,
        "provisional_screening_score": None,
        "final_panel_score": None,
        "rank_in_discipline": None,
        "waitlist_rank": None,
    })
    return object_response(D.ser_application(row), 201)


@bp.route("/applications", methods=["GET"])
def list_applications():
    authorize(READ_APPLICATION_ROLES)
    filters = {
        "cycle_id": query_str("cycle_id"),
        "applicant_id": query_str("applicant_id"),
        "discipline_id": query_str("discipline_id"),
        "status": query_str("status"),
        "fee_status": query_str("fee_status"),
    }
    rows = D.by_seq(list(store.applications.values()))
    for key, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return paged(rows, D.ser_application)


@bp.route("/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    authorize(READ_APPLICATION_ROLES)
    row = path_row(store.applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    return object_response(D.ser_application(row))


@bp.route("/applications/<application_id>", methods=["PATCH"])
def patch_application(application_id):
    actor = authorize(["ProgramAdmin", "Applicant"])
    app = path_row(store.applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    b = body()
    discipline = fk(b, "discipline_id", store.disciplines, "ERR_DISCIPLINE_NOT_FOUND")
    weeks = opt_int(b, "requested_session_length_weeks",
                    minimum=K.MIN_SESSION_WEEKS, maximum=K.MAX_SESSION_WEEKS)
    statement = opt_str(b, "project_statement", min_len=1, max_len=4000)
    waiver_requested = opt_bool(b, "fee_waiver_requested")

    require_owner(actor, app["applicant_id"])
    if app["status"] not in APPLICATION_EDITABLE:
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "an application may only be edited from DRAFT or REVISION_REQUESTED")

    if discipline is not None:
        app["discipline_id"] = discipline["id"]
    if weeks is not None:
        app["requested_session_length_weeks"] = weeks
    if statement is not None:
        app["project_statement"] = statement
    if waiver_requested is not None:
        app["fee_waiver_requested"] = waiver_requested
    touch(app)
    return object_response(D.ser_application(app))


@bp.route("/applications/<application_id>/fee-resolution", methods=["POST"])
def fee_resolution(application_id):
    authorize(["ProgramAdmin"])
    app = path_row(store.applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    b = body()
    action = req_enum(b, "action", ["PAY", "WAIVE", "DENY_WAIVER"])
    reason = opt_str(b, "reason", min_len=1, max_len=1000)

    if action == "WAIVE":
        applicant = store.applicants.get(app["applicant_id"])
        income = applicant["declared_annual_income_cents"] if applicant else 0
        if not app["fee_waiver_requested"] or income > K.FEE_WAIVER_INCOME_CEILING_CENTS:
            raise ApiError("ERR_FEE_WAIVER_NOT_ELIGIBLE",
                           "this application does not qualify for a fee waiver")
    if app["fee_status"] != "PENDING":
        raise ApiError("ERR_FEE_ALREADY_SETTLED",
                       "the application fee has already been settled")

    if action == "PAY":
        app["fee_status"] = "PAID"
    elif action == "WAIVE":
        app["fee_status"] = "WAIVED"
    app["fee_waiver_reason"] = reason
    touch(app)
    return object_response(D.ser_application(app))


# ---------------------------------------------------------------- submission
def _discipline_of(app):
    return store.disciplines.get(app["discipline_id"])


def _check_portfolio_band(app, discipline):
    count = len(D.application_portfolio_items(app["id"]))
    if count < int(discipline["portfolio_min_items"]) \
            or count > int(discipline["portfolio_max_items"]):
        raise ApiError("ERR_PORTFOLIO_ITEM_COUNT",
                       "the portfolio holds %d items, outside [%s, %s]"
                       % (count, discipline["portfolio_min_items"],
                          discipline["portfolio_max_items"]))


def _check_media_coverage(app, discipline):
    present_types = set(D.application_media_types(app["id"]))
    for media_type in discipline["required_media_types"]:
        if media_type not in present_types:
            raise ApiError("ERR_PORTFOLIO_MEDIA_MISSING",
                           "required media type %s is absent from the portfolio" % media_type)


@bp.route("/applications/<application_id>/submit", methods=["POST"])
def submit_application(application_id):
    actor = authorize(["Applicant", "ProgramAdmin"])
    app = path_row(store.applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    body()
    require_owner(actor, app["applicant_id"])

    cycle = store.cycles[app["cycle_id"]]
    status = app["status"]
    first_submission = status == "DRAFT"
    if first_submission:
        if cycle["status"] != "OPEN":
            raise ApiError("ERR_CYCLE_NOT_OPEN",
                           "a first submission requires the cycle to be OPEN")
    elif status == "REVISION_REQUESTED":
        if cycle["status"] != "SCREENING":
            raise ApiError("ERR_CYCLE_STAGE_INVALID",
                           "a resubmission requires the cycle to be in SCREENING")
    else:
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "SUBMITTED is not an edge from %s" % status)

    if first_submission:
        now = store.now()
        if now < cycle["_open_at"] or now > cycle["_close_at"]:
            raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED",
                           "the logical clock falls outside the submission window")

    # §3.3 states the first-submission guards in order: cycle stage, then the
    # window, then the fee, then the portfolio count band, then media coverage.
    if first_submission and app["fee_status"] not in ("PAID", "WAIVED"):
        raise ApiError("ERR_FEE_UNSETTLED", "the application fee is still PENDING")

    discipline = _discipline_of(app)
    _check_portfolio_band(app, discipline)
    _check_media_coverage(app, discipline)

    app["status"] = "SUBMITTED"
    touch(app)
    return object_response(D.ser_application(app))


# ---------------------------------------------------------------- screening decisions
SCREENING_DECISIONS = ["ADVANCE", "REQUEST_REVISION", "REJECT", "PROMOTE_FROM_WAITLIST"]

DECISION_EDGE = {
    "ADVANCE": ("SUBMITTED", "PANEL_REVIEW"),
    "REQUEST_REVISION": ("SUBMITTED", "REVISION_REQUESTED"),
    "REJECT": ("SUBMITTED", "REJECTED"),
    "PROMOTE_FROM_WAITLIST": ("WAITLISTED", "OFFERED"),
}


@bp.route("/applications/<application_id>/screening-decision", methods=["POST"])
def screening_decision(application_id):
    authorize(["ProgramAdmin"])
    app = path_row(store.applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    b = body()
    decision = req_enum(b, "decision", SCREENING_DECISIONS)
    opt_str(b, "note", min_len=1, max_len=2000)

    cycle = store.cycles[app["cycle_id"]]
    required_stage = "SLATE_LOCKED" if decision == "PROMOTE_FROM_WAITLIST" else "SCREENING"
    if cycle["status"] != required_stage:
        raise ApiError("ERR_CYCLE_STAGE_INVALID",
                       "this decision requires the cycle to be in %s" % required_stage)

    origin, target = DECISION_EDGE[decision]
    if app["status"] != origin:
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "%s is not an edge from %s" % (decision, app["status"]))

    if decision == "REQUEST_REVISION" and app["revision_round"] >= K.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED",
                       "the revision loop is bounded at %d rounds" % K.MAX_REVISION_ROUNDS)

    if decision == "PROMOTE_FROM_WAITLIST":
        _, _, _, open_count = D.cycle_ledger(cycle)
        if open_count < 1:
            raise ApiError("ERR_NO_SLOTS_AVAILABLE", "the cohort has no open slots")

    app["status"] = target
    if decision == "REQUEST_REVISION":
        app["revision_round"] = app["revision_round"] + 1
    elif decision == "REJECT":
        for pa in D.application_assignments(app["id"]):
            if pa["status"] != "ASSIGNED":
                continue
            pa["status"] = "VACATED"
            touch(pa)
            panelist = store.panelists.get(pa["panelist_id"])
            if panelist is not None:
                D.recompute_panelist_counters(panelist)
    elif decision == "PROMOTE_FROM_WAITLIST":
        app["waitlist_rank"] = None
    touch(app)
    if decision == "PROMOTE_FROM_WAITLIST":
        D.rerank_waitlist(cycle["id"])
    return object_response(D.ser_application(app))


# ---------------------------------------------------------------- offer response (cascade A)
@bp.route("/applications/<application_id>/offer-response", methods=["POST"])
def offer_response(application_id):
    actor = authorize(["Applicant", "ProgramAdmin"])
    app = path_row(store.applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    b = body()
    response = req_enum(b, "response", ["ACCEPT", "DECLINE"])
    require_owner(actor, app["applicant_id"])

    cycle = store.cycles[app["cycle_id"]]
    if cycle["status"] != "SLATE_LOCKED":
        raise ApiError("ERR_CYCLE_STAGE_INVALID",
                       "an offer response requires the cycle to be SLATE_LOCKED")
    if app["status"] in APPLICATION_TERMINAL:
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "%s is terminal and accepts no further transition" % app["status"])
    if app["status"] != "OFFERED":
        raise ApiError("ERR_APPLICATION_NOT_OFFERED",
                       "this application is not in OFFERED")

    if response == "DECLINE":
        app["status"] = "DECLINED"
        touch(app)
        return object_response(D.ser_application(app))

    weeks = int(app["requested_session_length_weeks"])
    rate = int(cycle["stipend_weekly_rate_cents"])
    commitment = calc.provisional_award(rate, weeks)
    _, uncommitted, _, open_count = D.cycle_ledger(cycle)
    if open_count < 1:
        raise ApiError("ERR_NO_SLOTS_AVAILABLE", "the cohort has no open slots")
    if uncommitted < commitment:
        raise ApiError("ERR_STIPEND_POOL_EXHAUSTED",
                       "the remaining stipend pool cannot cover this award")

    app["status"] = "ACCEPTED"
    touch(app)

    discipline = _discipline_of(app)
    residency = D.new_residency(
        cycle_id=cycle["id"],
        applicant_id=app["applicant_id"],
        discipline_code=discipline["code"] if discipline else None,
        application_id=app["id"],
        weekly_rate_cents=rate,
        stipend_total_cents=commitment,
    )
    if D.residency_visa_required(residency):
        D.new_visa_case(residency["id"])
    touch(cycle)
    return object_response(D.ser_application(app))


# ---------------------------------------------------------------- portfolio items
@bp.route("/portfolio-items", methods=["POST"])
def create_portfolio_item():
    actor = authorize(["Applicant", "ProgramAdmin"])
    b = body()
    app = fk(b, "application_id", store.applications, "ERR_APPLICATION_NOT_FOUND")
    req_str(b, "application_id")
    media_type = req_enum(b, "media_type", K.MEDIA_TYPES)
    title = req_str(b, "title", min_len=1, max_len=200)
    size = req_decimal(b, "file_size_mb", maximum=200)
    if size <= 0:
        bad("file_size_mb must be strictly greater than 0")
    hazmat = opt_bool(b, "hazardous_materials_declared", default=False)

    require_owner(actor, app["applicant_id"])
    if app["status"] not in APPLICATION_EDITABLE:
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "work samples may only be attached while the application is "
                       "DRAFT or REVISION_REQUESTED")
    discipline = _discipline_of(app)
    count = len(D.application_portfolio_items(app["id"]))
    if discipline is not None and count + 1 > int(discipline["portfolio_max_items"]):
        raise ApiError("ERR_PORTFOLIO_ITEM_COUNT",
                       "the discipline allows at most %s work samples"
                       % discipline["portfolio_max_items"])

    row = create_row(store.portfolio_items, {
        "application_id": app["id"],
        "media_type": media_type,
        "title": title,
        "file_size_mb": size,
        "hazardous_materials_declared": hazmat,
    }, versioned=False)
    touch(app)
    return object_response(D.ser_portfolio_item(row), 201)


@bp.route("/portfolio-items", methods=["GET"])
def list_portfolio_items():
    authorize(READ_PORTFOLIO_ROLES)
    application_id = query_str("application_id")
    media_type = query_str("media_type")
    rows = D.by_seq(list(store.portfolio_items.values()))
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    if media_type is not None:
        rows = [r for r in rows if r["media_type"] == media_type]
    return paged(rows, D.ser_portfolio_item)


@bp.route("/portfolio-items/<item_id>", methods=["GET"])
def get_portfolio_item(item_id):
    authorize(READ_PORTFOLIO_ROLES)
    row = path_row(store.portfolio_items, item_id, "ERR_PORTFOLIO_ITEM_NOT_FOUND")
    return object_response(D.ser_portfolio_item(row))


@bp.route("/portfolio-items/<item_id>", methods=["DELETE"])
def delete_portfolio_item(item_id):
    actor = authorize(["Applicant", "ProgramAdmin"])
    row = path_row(store.portfolio_items, item_id, "ERR_PORTFOLIO_ITEM_NOT_FOUND")
    app = store.applications.get(row["application_id"])
    if app is not None:
        require_owner(actor, app["applicant_id"])
        if app["status"] not in APPLICATION_EDITABLE:
            raise ApiError("ERR_APPLICATION_STATE_INVALID",
                           "a work sample may only be removed before submission")
    del store.portfolio_items[item_id]
    if app is not None:
        touch(app)
    return object_response({}, 204)
