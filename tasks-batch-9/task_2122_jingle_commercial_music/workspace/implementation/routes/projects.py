"""Engagements, briefs and the two computed reads (PRD 3.2, 3.9)."""

from flask import Blueprint, request

import clock
import db
import ledger
import licensing
import response
import sourcing
import validators as v
from auth import ALL_ROLES, endpoint, require_project_owner
from errors import ApiError

bp = Blueprint("projects", __name__)

REQUIRED_LENGTH_CHOICES = (60, 30, 15, 6)


@bp.post("/projects")
@endpoint(["MusicHouseProducer"])
def create_project():
    body = v.get_body()
    # Body reference existence is judged before request shape (PRD 2.5 step 4).
    if v.present(body, "client_id"):
        v.body_lookup(db.clients, body["client_id"], "ERR_CLIENT_NOT_FOUND")
    client_id = v.v_string(body, "client_id")
    title = v.v_string(body, "title")
    budget_cents = v.v_int(body, "budget_cents", minimum=1)
    deadline_raw, deadline_dt = v.v_datetime(body, "delivery_deadline_utc")

    record = db.create(db.projects, {
        "client_id": client_id,
        "title": title,
        "budget_cents": budget_cents,
        "committed_cents": 0,
        "available_cents": budget_cents,
        "spent_cents": 0,
        "budget_posture": "HEALTHY",
        "status": "DRAFT",
        "status_before_hold": None,
        "delivery_deadline_utc": deadline_raw,
        "_deadline_dt": deadline_dt,
    })
    return response.created(db.serialize(record))


@bp.get("/projects/<project_id>")
@endpoint(ALL_ROLES)
def get_project(project_id):
    project = v.path_lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    return response.ok(db.serialize(project))


@bp.get("/projects")
@endpoint(ALL_ROLES)
def list_projects():
    rows = list(db.projects.values())
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    posture = request.args.get("budget_posture")
    if client_id:
        rows = [r for r in rows if r["client_id"] == client_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if posture:
        rows = [r for r in rows if r["budget_posture"] == posture]
    items, meta = v.paginate(db.by_created(rows))
    return response.ok_list(items, meta)


@bp.post("/projects/<project_id>/hold")
@endpoint(["MusicHouseProducer"])
def hold_project(project_id):
    project = v.path_lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    body = v.get_body()
    v.v_string(body, "hold_reason")
    if project["status"] not in ("BRIEFING", "IN_DEMO", "IN_PRODUCTION"):
        raise ApiError("ERR_PROJECT_NOT_HOLDABLE")
    ledger.apply_hold(project)
    db.touch(project)
    return response.ok(db.serialize(project))


@bp.post("/projects/<project_id>/resume")
@endpoint(["MusicHouseProducer"])
def resume_project(project_id):
    project = v.path_lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    if project["status"] != "ON_HOLD":
        raise ApiError("ERR_PROJECT_NOT_ON_HOLD")
    ledger.apply_resume(project)
    db.touch(project)
    return response.ok(db.serialize(project))


@bp.get("/projects/<project_id>/sourcing-comparison")
@endpoint(["MusicHouseProducer", "ClientRep", "RightsAdmin"])
def sourcing_comparison(project_id):
    project = v.path_lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    return response.ok(sourcing.compare(project))


@bp.get("/projects/<project_id>/afm-report")
@endpoint(["MusicHouseProducer", "RightsAdmin", "AFMSteward"])
def afm_report(project_id):
    import wages

    project = v.path_lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    basis = request.args.get("basis")
    if basis is None or basis == "":
        basis = "SESSION"
    if basis not in ("SESSION", "DAY"):
        raise v.invalid("'basis' must be SESSION or DAY.")
    return response.ok(wages.afm_report(project, basis))


@bp.post("/projects/<project_id>/briefs")
@endpoint(["MusicHouseProducer"])
def create_brief(project_id):
    project = v.path_lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    body = v.get_body()
    tempo_bpm = v.v_int(body, "tempo_bpm", minimum=40, maximum=240)
    mood_tags = v.v_array(body, "mood_tags", item="string")
    target_markets = v.v_array(body, "target_markets", item="string")
    required_lengths = v.v_array(body, "required_lengths", item="integer",
                                 choices=REQUIRED_LENGTH_CHOICES)
    reference_track_url = v.v_string(body, "reference_track_url", required=False, default=None)

    licensing.check_market_codes(target_markets)

    if project["status"] not in ("DRAFT", "BRIEFING"):
        raise ApiError("ERR_PROJECT_NOT_IN_BRIEFING")

    siblings = db.by_created([b for b in db.briefs.values()
                              if b["project_id"] == project["id"] and b["status"] == "DRAFT"])

    record = db.create(db.briefs, {
        "project_id": project["id"],
        "tempo_bpm": tempo_bpm,
        "mood_tags": mood_tags,
        "target_markets": target_markets,
        "required_lengths": required_lengths,
        "reference_track_url": reference_track_url,
        "status": "DRAFT",
        "approved_at": None,
    })

    for sibling in siblings:
        sibling["status"] = "SUPERSEDED"
        db.touch(sibling)

    project_changed = False
    if project["status"] == "DRAFT":
        project["status"] = "BRIEFING"
        project_changed = True
    if ledger.recompute_posture(project):
        project_changed = True
    if project_changed:
        db.touch(project)

    return response.created(db.serialize(record))


@bp.get("/projects/<project_id>/briefs")
@endpoint(ALL_ROLES)
def list_briefs(project_id):
    project = v.path_lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    rows = [b for b in db.briefs.values() if b["project_id"] == project["id"]]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    items, meta = v.paginate(db.by_created(rows))
    return response.ok_list(items, meta)


@bp.post("/briefs/<brief_id>/approve")
@endpoint(["ClientRep"])
def approve_brief(brief_id):
    brief = v.path_lookup(db.briefs, brief_id, "ERR_BRIEF_NOT_FOUND")
    project = db.projects[brief["project_id"]]
    require_project_owner(project)

    if brief["status"] != "DRAFT":
        raise ApiError("ERR_BRIEF_NOT_DRAFT")
    if project["status"] != "BRIEFING":
        raise ApiError("ERR_PROJECT_NOT_IN_BRIEFING")

    brief["status"] = "APPROVED"
    brief["approved_at"] = clock.now_iso()
    db.touch(brief)

    for sibling in db.by_created([b for b in db.briefs.values()
                                  if b["project_id"] == project["id"]
                                  and b["id"] != brief["id"]
                                  and b["status"] == "DRAFT"]):
        sibling["status"] = "SUPERSEDED"
        db.touch(sibling)

    project["status"] = "IN_DEMO"
    ledger.recompute_posture(project)
    db.touch(project)

    return response.ok(db.serialize(brief))
