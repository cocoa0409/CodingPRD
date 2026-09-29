"""Panelists, panel assignments, the rubric and the severe-conflict recusal cascade."""

import calc
import domain as D
import store as K
from auth import authorize, require_self_panelist
from envelope import object_response, paged, query_flag, query_str
from errors import ApiError
from flask import Blueprint
from store import create_row, iso_ms, store, touch
from validate import (body, fk, opt_bool, opt_str, opt_str_list, path_row,
                      req_enum, req_int, req_str, req_str_list)

bp = Blueprint("panel", __name__)

READ_PANELIST_ROLES = ["ProgramAdmin", "PanelChair"]
APPLICATION_UNDER_REVIEW = ("PANEL_REVIEW", "SCORED")
SCORE_FIELDS = ("score_artistic_merit", "score_feasibility",
                "score_community_fit", "score_technical_readiness")


# ---------------------------------------------------------------- panelists
@bp.route("/panelists", methods=["POST"])
def create_panelist():
    authorize(["ProgramAdmin"])
    b = body()
    full_name = req_str(b, "full_name", min_len=1, max_len=200)
    email = req_str(b, "email", min_len=1, max_len=320)
    affiliation = req_str(b, "affiliation_org", min_len=1, max_len=200)
    expertise = req_str_list(b, "discipline_expertise", allow_empty=True, max_len=16)
    chair_eligible = opt_bool(b, "chair_eligible", default=False)

    for row in store.panelists.values():
        if row["email"] == email:
            raise ApiError("ERR_DUPLICATE_CODE", "panelist email %s already exists" % email)

    row = create_row(store.panelists, {
        "full_name": full_name,
        "email": email,
        "affiliation_org": affiliation,
        "discipline_expertise": expertise,
        "chair_eligible": chair_eligible,
        "status": "ACTIVE",
        "recused_cycle_id": None,
        "assigned_count": 0,
        "conflict_count": 0,
    })
    return object_response(D.ser_panelist(row), 201)


@bp.route("/panelists", methods=["GET"])
def list_panelists():
    authorize(READ_PANELIST_ROLES)
    recused_cycle_id = query_str("recused_cycle_id")
    status = query_str("status")
    chair_eligible = query_flag("chair_eligible")
    rows = D.by_seq(list(store.panelists.values()))
    if recused_cycle_id is not None:
        rows = [r for r in rows if r["recused_cycle_id"] == recused_cycle_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if chair_eligible is not None:
        rows = [r for r in rows if bool(r["chair_eligible"]) == chair_eligible]
    return paged(rows, D.ser_panelist)


@bp.route("/panelists/<panelist_id>", methods=["GET"])
def get_panelist(panelist_id):
    authorize(READ_PANELIST_ROLES + ["Panelist"])
    row = path_row(store.panelists, panelist_id, "ERR_PANELIST_NOT_FOUND")
    return object_response(D.ser_panelist(row))


@bp.route("/panelists/<panelist_id>", methods=["PATCH"])
def patch_panelist(panelist_id):
    authorize(["ProgramAdmin"])
    row = path_row(store.panelists, panelist_id, "ERR_PANELIST_NOT_FOUND")
    b = body()
    full_name = opt_str(b, "full_name", min_len=1, max_len=200)
    affiliation = opt_str(b, "affiliation_org", min_len=1, max_len=200)
    expertise = opt_str_list(b, "discipline_expertise", allow_empty=True, max_len=16)
    chair_eligible = opt_bool(b, "chair_eligible")

    if full_name is not None:
        row["full_name"] = full_name
    if affiliation is not None:
        row["affiliation_org"] = affiliation
    if expertise is not None:
        row["discipline_expertise"] = expertise
    if chair_eligible is not None:
        row["chair_eligible"] = chair_eligible
    touch(row)
    return object_response(D.ser_panelist(row))


# ---------------------------------------------------------------- panel assignments
@bp.route("/panel-assignments", methods=["POST"])
def create_panel_assignment():
    authorize(["ProgramAdmin", "PanelChair"])
    b = body()
    app = fk(b, "application_id", store.applications, "ERR_APPLICATION_NOT_FOUND")
    panelist = fk(b, "panelist_id", store.panelists, "ERR_PANELIST_NOT_FOUND")
    req_str(b, "application_id")
    req_str(b, "panelist_id")

    cycle = store.cycles[app["cycle_id"]]
    if cycle["status"] != "PANEL_REVIEW":
        raise ApiError("ERR_CYCLE_STAGE_INVALID",
                       "panel assignments require the cycle to be in PANEL_REVIEW")
    if app["status"] not in APPLICATION_UNDER_REVIEW:
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "an application in %s takes no panel assignment" % app["status"])
    if panelist["status"] != "ACTIVE":
        raise ApiError("ERR_PANELIST_RECUSED",
                       "this reviewer is frozen as RECUSED_FOR_CYCLE")
    for row in store.panel_assignments.values():
        if row["application_id"] == app["id"] and row["panelist_id"] == panelist["id"]:
            raise ApiError("ERR_DUPLICATE_ASSOCIATION",
                           "this reviewer is already assigned to this application")

    discipline = store.disciplines.get(app["discipline_id"])
    code = discipline["code"] if discipline is not None else None
    matched = code is not None and code in panelist["discipline_expertise"]

    row = create_row(store.panel_assignments, {
        "application_id": app["id"],
        "panelist_id": panelist["id"],
        "status": "ASSIGNED",
        "conflict_type": None,
        "conflict_detail": None,
        "score_artistic_merit": None,
        "score_feasibility": None,
        "score_community_fit": None,
        "score_technical_readiness": None,
        "notes": None,
        "scored_at": None,
        "expertise_matched": matched,
        "panelist_total_100": None,
    })
    D.recompute_panelist_counters(panelist)
    touch(app)
    return object_response(D.ser_panel_assignment(row), 201)


@bp.route("/panel-assignments", methods=["GET"])
def list_panel_assignments():
    authorize(["ProgramAdmin", "PanelChair", "Panelist"])
    filters = {
        "application_id": query_str("application_id"),
        "panelist_id": query_str("panelist_id"),
        "status": query_str("status"),
        "conflict_type": query_str("conflict_type"),
    }
    rows = D.by_seq(list(store.panel_assignments.values()))
    for key, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return paged(rows, D.ser_panel_assignment)


@bp.route("/panel-assignments/<assignment_id>", methods=["GET"])
def get_panel_assignment(assignment_id):
    authorize(["ProgramAdmin", "PanelChair", "Panelist"])
    row = path_row(store.panel_assignments, assignment_id, "ERR_PANEL_ASSIGNMENT_NOT_FOUND")
    return object_response(D.ser_panel_assignment(row))


# ---------------------------------------------------------------- scoring
def _clear_scores(pa):
    for field in SCORE_FIELDS:
        pa[field] = None
    pa["scored_at"] = None
    pa["panelist_total_100"] = None


@bp.route("/panel-assignments/<assignment_id>/scores", methods=["POST"])
def record_scores(assignment_id):
    actor = authorize(["Panelist"])
    pa = path_row(store.panel_assignments, assignment_id, "ERR_PANEL_ASSIGNMENT_NOT_FOUND")
    b = body()
    artistic = req_int(b, "score_artistic_merit",
                       minimum=K.RUBRIC_SCORE_MIN, maximum=K.RUBRIC_SCORE_MAX)
    feasibility = req_int(b, "score_feasibility",
                          minimum=K.RUBRIC_SCORE_MIN, maximum=K.RUBRIC_SCORE_MAX)
    community = req_int(b, "score_community_fit",
                       minimum=K.RUBRIC_SCORE_MIN, maximum=K.RUBRIC_SCORE_MAX)
    technical = req_int(b, "score_technical_readiness",
                       minimum=K.RUBRIC_SCORE_MIN, maximum=K.RUBRIC_SCORE_MAX)
    notes = opt_str(b, "notes", min_len=1, max_len=2000)

    require_self_panelist(actor, pa["panelist_id"])

    app = store.applications[pa["application_id"]]
    cycle = store.cycles[app["cycle_id"]]
    panelist = store.panelists[pa["panelist_id"]]

    if cycle["status"] != "PANEL_REVIEW":
        raise ApiError("ERR_CYCLE_STAGE_INVALID",
                       "scoring requires the cycle to be in PANEL_REVIEW")
    if app["status"] not in APPLICATION_UNDER_REVIEW:
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "an application in %s takes no review" % app["status"])
    if pa["status"] != "ASSIGNED":
        raise ApiError("ERR_ASSIGNMENT_STATE_INVALID",
                       "SCORED is not an edge from %s" % pa["status"])
    if panelist["status"] != "ACTIVE":
        raise ApiError("ERR_PANELIST_RECUSED",
                       "this reviewer is frozen as RECUSED_FOR_CYCLE")

    applicant = store.applicants.get(app["applicant_id"])
    if applicant is not None and applicant["affiliation_org"] == panelist["affiliation_org"]:
        raise ApiError("ERR_AFFILIATION_CONFLICT",
                       "the reviewer shares an affiliation with the applicant and must "
                       "declare the conflict first")

    pa["score_artistic_merit"] = artistic
    pa["score_feasibility"] = feasibility
    pa["score_community_fit"] = community
    pa["score_technical_readiness"] = technical
    pa["notes"] = notes
    pa["scored_at"] = iso_ms(store.now())
    pa["status"] = "SCORED"
    pa["panelist_total_100"] = calc.panelist_total_100(
        artistic, feasibility, community, technical, pa["expertise_matched"])
    touch(pa)

    edges = D.refresh_application_scores(app)
    touch(app)
    D.recompute_panelist_counters(panelist)
    if edges:
        touch(cycle)
    return object_response(D.ser_panel_assignment(pa))


# ---------------------------------------------------------------- conflict cascade (B)
@bp.route("/panel-assignments/<assignment_id>/declare-conflict", methods=["POST"])
def declare_conflict(assignment_id):
    actor = authorize(["Panelist"])
    pa = path_row(store.panel_assignments, assignment_id, "ERR_PANEL_ASSIGNMENT_NOT_FOUND")
    b = body()
    conflict_type = req_enum(b, "conflict_type", K.CONFLICT_TYPES)
    conflict_detail = req_str(b, "conflict_detail", min_len=1, max_len=2000)

    require_self_panelist(actor, pa["panelist_id"])

    app = store.applications[pa["application_id"]]
    cycle = store.cycles[app["cycle_id"]]
    panelist = store.panelists[pa["panelist_id"]]

    if cycle["status"] != "PANEL_REVIEW":
        raise ApiError("ERR_CYCLE_STAGE_INVALID",
                       "a conflict declaration requires the cycle to be in PANEL_REVIEW")
    if pa["status"] not in ("ASSIGNED", "SCORED"):
        raise ApiError("ERR_ASSIGNMENT_STATE_INVALID",
                       "CONFLICT_DECLARED is not an edge from %s" % pa["status"])

    # link 1 -- record the declaration and clear this reviewer's contribution
    was_scored = pa["status"] == "SCORED"
    pa["conflict_type"] = conflict_type
    pa["conflict_detail"] = conflict_detail
    _clear_scores(pa)
    pa["status"] = "CONFLICT_DECLARED"
    touch(pa)
    D.recompute_panelist_counters(panelist)

    affected = {}
    demotions = 0

    if conflict_type in K.SEVERE_CONFLICT_TYPES:
        # link 2 -- the reviewer is frozen for the whole cycle
        panelist["status"] = "RECUSED_FOR_CYCLE"
        panelist["recused_cycle_id"] = cycle["id"]
        touch(panelist)

        # link 3 -- vacate every other live assignment of this reviewer in this cycle
        cycle_app_ids = set(a["id"] for a in D.cycle_applications(cycle["id"]))
        for other in D.by_seq(list(store.panel_assignments.values())):
            if other["id"] == pa["id"] or other["panelist_id"] != panelist["id"]:
                continue
            if other["application_id"] not in cycle_app_ids:
                continue
            if other["status"] not in ("ASSIGNED", "SCORED"):
                continue
            other["status"] = "VACATED"
            _clear_scores(other)
            touch(other)
            affected[other["application_id"]] = store.applications[other["application_id"]]
        D.recompute_panelist_counters(panelist)

    # link 4 -- re-aggregate every touched application
    for other_app in D.by_seq(list(affected.values())):
        before = other_app["status"]
        D.refresh_application_scores(other_app)
        if before == "SCORED" and other_app["status"] == "PANEL_REVIEW":
            demotions += 1
        touch(other_app)

    before = app["status"]
    D.refresh_application_scores(app)
    if before == "SCORED" and app["status"] == "PANEL_REVIEW":
        demotions += 1
    touch(app)

    # link 5 -- one cycle version step per demotion
    for _ in range(demotions):
        touch(cycle)
    return object_response(D.ser_panel_assignment(pa))
