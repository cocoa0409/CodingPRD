"""Recording projects, milestones, and tracks."""

from flask import Blueprint

from db import db
from errors import raise_err
from helpers import (
    get_body, make_entity, touch, serialize, get_or_404, list_page,
    apply_filters, v_str, v_int, v_bool, v_enum, v_date,
)
from middleware import auth, check_ownership
from response import ok, ok_list
from services.calc import recompute_budget_posture, recompute_account_totals
from services.domain import (
    account_of_contract, artist_of_contract, project_contract,
)

bp = Blueprint("projects", __name__)

LIVE_CONTRACT_STATES = ("ACTIVE", "OPTION_WINDOW", "EXTENDED")
PROJECT_TYPES = ["SINGLE", "EP", "ALBUM"]


def _artist_of_project(project):
    contract = project_contract(project)
    return artist_of_contract(contract) if contract else None


def _label_of_project(project):
    artist = _artist_of_project(project)
    return artist["label_id"] if artist else None


# ---------------------------------------------------------------------------
# Recording projects
# ---------------------------------------------------------------------------

@bp.post("/api/contracts/<cid>/recording-projects")
def create_project(cid):
    auth(["AnRManager"])
    contract = get_or_404(db.contracts, cid)
    body = get_body()
    title = v_str(body, "title")
    project_type = v_enum(body, "project_type", PROJECT_TYPES)
    budget = v_int(body, "budget_cents", min_v=0)
    if contract["status"] not in LIVE_CONTRACT_STATES:
        raise_err("ERR_INVALID_STATE", "Contract status %s does not permit projects" % contract["status"])
    artist = artist_of_contract(contract)
    if artist["status"] not in ("SIGNED", "ACTIVE"):
        raise_err("ERR_ARTIST_NOT_SIGNABLE", "Artist status %s does not permit a project" % artist["status"])
    project = make_entity({
        "contract_id": cid,
        "title": title,
        "project_type": project_type,
        "budget_cents": budget,
        "spent_cents": 0,
        "committed_cents": 0,
        "budget_posture": "WITHIN_BUDGET",
        "status": "PLANNED",
    })
    db.recording_projects[project["id"]] = project
    return ok(serialize(project), code=201)


@bp.get("/api/recording-projects/<pid>")
def get_project(pid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager", "ArtistPortal"])
    project = get_or_404(db.recording_projects, pid)
    artist = _artist_of_project(project)
    check_ownership(role, uid, artist["id"] if artist else None)
    return ok(serialize(project))


@bp.get("/api/contracts/<cid>/recording-projects")
def list_contract_projects(cid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "ArtistPortal"])
    contract = get_or_404(db.contracts, cid)
    check_ownership(role, uid, contract["artist_id"])
    items = [p for p in db.recording_projects.values() if p["contract_id"] == cid]
    items = apply_filters(items, [("status", lambda p: p["status"])])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.post("/api/recording-projects/<pid>/amend-budget")
def amend_budget(pid):
    auth(["AnRManager"])
    project = get_or_404(db.recording_projects, pid)
    body = get_body()
    expected = v_int(body, "expected_recording_project_version")
    new_budget = v_int(body, "budget_cents")
    if expected != project["version"]:
        raise_err("ERR_STALE_VERSION", "Recording project version mismatch")
    if project["status"] not in ("PLANNED", "RECORDING", "POST_PRODUCTION"):
        raise_err("ERR_INVALID_STATE", "Budget may not be amended in %s" % project["status"])
    if new_budget < project["spent_cents"]:
        raise_err("ERR_BUDGET_BELOW_SPEND", "New budget is below already-spent amount")
    project["budget_cents"] = new_budget
    recompute_budget_posture(project)
    touch(project)
    return ok(serialize(project))


@bp.post("/api/recording-projects/<pid>/start")
def start_project(pid):
    auth(["AnRManager"])
    project = get_or_404(db.recording_projects, pid)
    get_body()
    if project["status"] != "PLANNED":
        raise_err("ERR_INVALID_STATE", "Only a PLANNED project may start")
    contract = project_contract(project)
    if contract["status"] not in LIVE_CONTRACT_STATES:
        raise_err("ERR_INVALID_STATE", "Contract status %s does not permit start" % contract["status"])
    if contract["advance_status"] != "FUNDED":
        raise_err("ERR_CONTRACT_NOT_FUNDED", "Contract advance has not been funded")
    if project["budget_cents"] <= 0:
        raise_err("ERR_INVALID_REQUEST", "budget_cents must be greater than zero to start")
    artist = artist_of_contract(contract)
    if artist["status"] in ("HIATUS", "DROPPED"):
        raise_err("ERR_INVALID_STATE", "Artist status %s does not permit start" % artist["status"])
    if artist["status"] not in ("SIGNED", "ACTIVE"):
        raise_err("ERR_ARTIST_NOT_SIGNABLE", "Artist status %s does not permit start" % artist["status"])
    project["status"] = "RECORDING"
    touch(project)
    return ok(serialize(project))


@bp.post("/api/recording-projects/<pid>/advance-stage")
def advance_project(pid):
    auth(["AnRManager"])
    project = get_or_404(db.recording_projects, pid)
    get_body()
    if project["status"] == "RECORDING":
        for m in db.milestones.values():
            if m["project_id"] == pid and m["status"] in ("PENDING", "SUBMITTED"):
                raise_err("ERR_INVALID_STATE", "Milestones still PENDING or SUBMITTED")
        project["status"] = "POST_PRODUCTION"
    elif project["status"] == "POST_PRODUCTION":
        for m in db.milestones.values():
            if m["project_id"] == pid and m["status"] not in ("PAID", "CANCELLED"):
                raise_err("ERR_INVALID_STATE", "Every non-CANCELLED milestone must be PAID")
        for t in db.tracks.values():
            if t["project_id"] == pid and t["status"] not in ("MASTERED", "CLEARED"):
                raise_err("ERR_INVALID_STATE", "Every track must be MASTERED or CLEARED")
        project["status"] = "DELIVERED"
    else:
        raise_err("ERR_INVALID_STATE", "Project in %s cannot advance" % project["status"])
    touch(project)
    return ok(serialize(project))


@bp.post("/api/recording-projects/<pid>/cancel")
def cancel_project(pid):
    auth(["AnRManager"])
    project = get_or_404(db.recording_projects, pid)
    get_body()
    if project["status"] not in ("PLANNED", "RECORDING", "POST_PRODUCTION"):
        raise_err("ERR_INVALID_STATE", "Project in %s cannot be cancelled" % project["status"])
    for m in db.milestones.values():
        if m["project_id"] == pid and m["status"] == "APPROVED":
            raise_err("ERR_INVALID_STATE", "An APPROVED milestone blocks cancellation")
    for m in db.milestones.values():
        if m["project_id"] == pid and m["status"] in ("PENDING", "SUBMITTED", "REJECTED"):
            m["status"] = "CANCELLED"
            touch(m)
    project["status"] = "CANCELLED"
    touch(project)
    return ok(serialize(project))


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

@bp.post("/api/recording-projects/<pid>/milestones")
def create_milestone(pid):
    auth(["AnRManager"])
    project = get_or_404(db.recording_projects, pid)
    body = get_body()
    name = v_str(body, "name")
    sequence = v_int(body, "sequence")
    due_date = v_date(body, "due_date")
    payment = v_int(body, "payment_cents", min_v=1)
    note = v_str(body, "deliverable_note", required=False, allow_null=True)
    if project["status"] not in ("RECORDING", "POST_PRODUCTION"):
        raise_err("ERR_INVALID_STATE", "Milestones require a RECORDING or POST_PRODUCTION project")
    for m in db.milestones.values():
        if (m["project_id"] == pid and m["status"] != "CANCELLED"
                and m["sequence"] == sequence):
            raise_err("ERR_MILESTONE_SEQUENCE_CONFLICT",
                      "Duplicate milestone sequence within the project")
    milestone = make_entity({
        "project_id": pid,
        "name": name,
        "sequence": sequence,
        "due_date": due_date,
        "payment_cents": payment,
        "deliverable_note": note,
        "approved_by_user_id": None,
        "status": "PENDING",
    })
    db.milestones[milestone["id"]] = milestone
    return ok(serialize(milestone), code=201)


@bp.get("/api/milestones/<mid>")
def get_milestone(mid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "ArtistPortal"])
    milestone = get_or_404(db.milestones, mid)
    project = db.recording_projects.get(milestone["project_id"])
    artist = _artist_of_project(project) if project else None
    check_ownership(role, uid, artist["id"] if artist else None)
    return ok(serialize(milestone))


@bp.get("/api/recording-projects/<pid>/milestones")
def list_project_milestones(pid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "ArtistPortal"])
    project = get_or_404(db.recording_projects, pid)
    artist = _artist_of_project(project)
    check_ownership(role, uid, artist["id"] if artist else None)
    items = [m for m in db.milestones.values() if m["project_id"] == pid]
    items = apply_filters(items, [("status", lambda m: m["status"])])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.post("/api/milestones/<mid>/submit")
def submit_milestone(mid):
    auth(["AnRManager"])
    milestone = get_or_404(db.milestones, mid)
    body = get_body()
    note = v_str(body, "deliverable_note", required=False, allow_null=True)
    if milestone["status"] not in ("PENDING", "REJECTED"):
        raise_err("ERR_INVALID_STATE", "Milestone in %s cannot be submitted" % milestone["status"])
    project = db.recording_projects.get(milestone["project_id"])
    if project["status"] not in ("RECORDING", "POST_PRODUCTION"):
        raise_err("ERR_INVALID_STATE", "Project is not RECORDING or POST_PRODUCTION")
    milestone["status"] = "SUBMITTED"
    if "deliverable_note" in body:
        milestone["deliverable_note"] = note
    touch(milestone)
    return ok(serialize(milestone))


@bp.post("/api/milestones/<mid>/approve")
def approve_milestone(mid):
    uid, _role = auth(["LabelAdmin"])
    milestone = get_or_404(db.milestones, mid)
    get_body()
    if milestone["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Only a SUBMITTED milestone may be approved")
    project = db.recording_projects.get(milestone["project_id"])
    milestone["status"] = "APPROVED"
    milestone["approved_by_user_id"] = uid
    touch(milestone)
    project["committed_cents"] += milestone["payment_cents"]
    recompute_budget_posture(project)
    touch(project)
    return ok(serialize(milestone))


@bp.post("/api/milestones/<mid>/reject")
def reject_milestone(mid):
    auth(["LabelAdmin"])
    milestone = get_or_404(db.milestones, mid)
    get_body()
    if milestone["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Only a SUBMITTED milestone may be rejected")
    milestone["status"] = "REJECTED"
    touch(milestone)
    return ok(serialize(milestone))


@bp.post("/api/milestones/<mid>/pay")
def pay_milestone(mid):
    auth(["FinanceController"])
    milestone = get_or_404(db.milestones, mid)
    get_body()
    if milestone["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Only an APPROVED milestone may be paid")
    project = db.recording_projects.get(milestone["project_id"])
    if project["status"] not in ("RECORDING", "POST_PRODUCTION"):
        raise_err("ERR_INVALID_STATE", "Project is not RECORDING or POST_PRODUCTION")
    if project["spent_cents"] + milestone["payment_cents"] > project["budget_cents"]:
        raise_err("ERR_PROJECT_BUDGET_EXCEEDED", "Payment would exceed the project budget")
    amount = milestone["payment_cents"]
    project["committed_cents"] -= amount
    project["spent_cents"] += amount
    recompute_budget_posture(project)
    touch(project)
    account = account_of_contract(project["contract_id"])
    if account is not None:
        account["recording_balance_cents"] += amount
        recompute_account_totals(account)
        touch(account)
    milestone["status"] = "PAID"
    touch(milestone)
    return ok(serialize(milestone))


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------

@bp.post("/api/recording-projects/<pid>/tracks")
def create_track(pid):
    auth(["AnRManager"])
    project = get_or_404(db.recording_projects, pid)
    body = get_body()
    title = v_str(body, "title")
    duration = v_int(body, "duration_seconds", min_v=1)
    isrc = v_str(body, "isrc")
    contains_sample = v_bool(body, "contains_sample", required=False)
    clearance_ref = v_str(body, "clearance_ref", required=False, allow_null=True)
    version_of = v_str(body, "version_of_track_id", required=False, allow_null=True)
    label_id = _label_of_project(project)
    if version_of is not None:
        parent = db.tracks.get(version_of)
        if parent is None:
            raise_err("ERR_NOT_FOUND", "version_of_track_id does not reference an existing track")
        parent_project = db.recording_projects.get(parent["project_id"])
        if _label_of_project(parent_project) != label_id:
            raise_err("ERR_NOT_FOUND", "version_of_track_id references a track of another label")
    for t in db.tracks.values():
        if t["isrc"] == isrc and _label_of_project(db.recording_projects.get(t["project_id"])) == label_id:
            raise_err("ERR_ISRC_CONFLICT", "ISRC already exists on another track of the label")
    track = make_entity({
        "project_id": pid,
        "title": title,
        "duration_seconds": duration,
        "isrc": isrc,
        "contains_sample": contains_sample if contains_sample is not None else False,
        "clearance_ref": clearance_ref,
        "version_of_track_id": version_of,
        "status": "DEMO",
    })
    db.tracks[track["id"]] = track
    return ok(serialize(track), code=201)


@bp.get("/api/tracks/<tid>")
def get_track(tid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager", "ArtistPortal"])
    track = get_or_404(db.tracks, tid)
    project = db.recording_projects.get(track["project_id"])
    artist = _artist_of_project(project) if project else None
    check_ownership(role, uid, artist["id"] if artist else None)
    return ok(serialize(track))


@bp.get("/api/recording-projects/<pid>/tracks")
def list_project_tracks(pid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager", "ArtistPortal"])
    project = get_or_404(db.recording_projects, pid)
    artist = _artist_of_project(project)
    check_ownership(role, uid, artist["id"] if artist else None)
    items = [t for t in db.tracks.values() if t["project_id"] == pid]
    items = apply_filters(items, [("status", lambda t: t["status"])])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.get("/api/tracks")
def list_tracks():
    auth(["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager"])
    items = apply_filters(db.tracks.values(), [
        ("project_id", lambda t: t["project_id"]),
        ("version_of_track_id", lambda t: t["version_of_track_id"] or ""),
        ("status", lambda t: t["status"]),
    ])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


_TRACK_STAGES = {"DEMO": "TRACKED", "TRACKED": "MIXED", "MIXED": "MASTERED", "MASTERED": "CLEARED"}


@bp.post("/api/tracks/<tid>/advance-stage")
def advance_track(tid):
    auth(["AnRManager"])
    track = get_or_404(db.tracks, tid)
    get_body()
    nxt = _TRACK_STAGES.get(track["status"])
    if nxt is None:
        raise_err("ERR_INVALID_STATE", "Track in %s cannot advance" % track["status"])
    project = db.recording_projects.get(track["project_id"])
    if project["status"] in ("CANCELLED", "DELIVERED"):
        raise_err("ERR_INVALID_STATE", "Project is %s" % project["status"])
    if nxt == "CLEARED" and track["contains_sample"] and not track["clearance_ref"]:
        raise_err("ERR_SAMPLE_CLEARANCE_MISSING",
                  "clearance_ref required for a sampled master to reach CLEARED")
    track["status"] = nxt
    touch(track)
    return ok(serialize(track))


@bp.post("/api/tracks/<tid>/block")
def block_track(tid):
    auth(["AnRManager"])
    track = get_or_404(db.tracks, tid)
    get_body()
    if track["status"] not in ("TRACKED", "MIXED", "MASTERED", "CLEARED"):
        raise_err("ERR_INVALID_STATE", "Track in %s cannot be blocked" % track["status"])
    track["status"] = "BLOCKED"
    touch(track)
    # Three-link cascade: release asset revert -> distribution unschedule -> delivery cancel.
    for release in db.releases.values():
        if tid not in release["track_ids"]:
            continue
        if release["distribution_status"] == "CANCELLED":
            continue
        if release["asset_status"] not in ("ASSEMBLED", "LOCKED"):
            continue
        release["asset_status"] = "DRAFT"
        if release["distribution_status"] == "SCHEDULED":
            release["distribution_status"] = "PLANNED"
            for delivery in db.deliveries.values():
                if delivery["release_id"] == release["id"] and delivery["status"] in ("QUEUED", "TRANSMITTED"):
                    delivery["status"] = "CANCELLED"
                    touch(delivery)
        touch(release)
    return ok(serialize(track))


@bp.post("/api/tracks/<tid>/rework")
def rework_track(tid):
    auth(["AnRManager"])
    track = get_or_404(db.tracks, tid)
    get_body()
    if track["status"] != "BLOCKED":
        raise_err("ERR_INVALID_STATE", "Only a BLOCKED track may be reworked")
    project = db.recording_projects.get(track["project_id"])
    if project["status"] in ("CANCELLED", "DELIVERED"):
        raise_err("ERR_INVALID_STATE", "Project is %s" % project["status"])
    track["status"] = "TRACKED"
    touch(track)
    return ok(serialize(track))
