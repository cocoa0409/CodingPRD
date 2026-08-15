from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services

bp = Blueprint("assignments", __name__)
COLL = "assignments"

LIVE_STATUSES = ("SCHEDULED", "EN_ROUTE", "ON_SITE")


def _get_assignment_or_404(aid):
    a = db.collections[COLL].get(aid)
    if a is None:
        raise errors.not_found("assignment not found")
    return a


def _require_own_assignment(uid, assignment):
    if assignment["rep_id"] != uid:
        raise errors.unauthorized("rep acting on another rep's assignment")


def _overlaps(start1, end1, start2, end2):
    """Half-open [start, end) overlap; end == start adjacency is NOT an overlap."""
    return start1 < end2 and start2 < end1


@bp.post("/assignments")
def create_assignment():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    body = mw.get_body()

    # Priority 3: existence, left-to-right: project_id, project_store_id,
    # rep_id, then rework_authorization_id.
    project = None
    pid = body.get("project_id")
    if pid is not None:
        if not isinstance(pid, str) or pid not in db.collections["projects"]:
            raise errors.not_found("project not found")
        project = db.collections["projects"][pid]
    ps = None
    psid = body.get("project_store_id")
    if psid is not None:
        if not isinstance(psid, str) or psid not in db.collections["project_stores"]:
            raise errors.not_found("project-store row not found")
        ps = db.collections["project_stores"][psid]
    rep = None
    rid = body.get("rep_id")
    if rid is not None:
        if not isinstance(rid, str) or rid not in db.collections["reps"]:
            raise errors.not_found("rep not found")
        rep = db.collections["reps"][rid]
    ra = None
    raid = body.get("rework_authorization_id")
    if raid is not None:
        if not isinstance(raid, str) or raid not in db.collections["rework_auths"]:
            raise errors.not_found("rework authorization not found")
        ra = db.collections["rework_auths"][raid]

    # Priority 4: state legality.
    if project is not None and project["status"] not in ("SCOPED", "IN_FIELD"):
        raise errors.invalid_state(f"project in {project['status']} cannot take assignments")
    if ps is not None:
        if ps["status"] == "REWORK_REQUIRED" and raid is None:
            raise errors.invalid_state("store requires a rework authorization")
        if ps["status"] not in ("PENDING", "REWORK_REQUIRED"):
            raise errors.invalid_state(f"project-store row in {ps['status']} cannot be assigned")
    if rep is not None and rep["status"] != "ACTIVE":
        raise errors.invalid_state("rep is not ACTIVE")
    if ps is not None:
        for a in db.collections[COLL].values():
            if a["project_store_id"] == psid and a["status"] in LIVE_STATUSES:
                raise errors.invalid_state("store already has a live assignment")

    # Priority 5: cross-entity ownership.
    if project is not None and ps is not None and ps["project_id"] != pid:
        raise errors.cross_entity_mismatch("project_store does not belong to project")
    if ra is not None:
        if pid is not None and ra["project_id"] != pid:
            raise errors.cross_entity_mismatch("rework authorization belongs to another project")
        if psid is not None and ra["project_store_id"] != psid:
            raise errors.cross_entity_mismatch("rework authorization belongs to another store")

    # Priority 6: scheduled_end strictly after scheduled_start.
    start = mw.parse_dt(body.get("scheduled_start"))
    end = mw.parse_dt(body.get("scheduled_end"))
    if start is not None and end is not None and not (end > start):
        raise errors.temporal_invalid("scheduled_end must be strictly after scheduled_start")

    # Priority 7: rep double-booking (half-open interval overlap among live assignments).
    if rep is not None and start is not None and end is not None:
        for a in db.collections[COLL].values():
            if a["rep_id"] == rid and a["status"] in LIVE_STATUSES:
                a_start = mw.parse_dt(a["scheduled_start"])
                a_end = mw.parse_dt(a["scheduled_end"])
                if a_start is not None and a_end is not None and _overlaps(start, end, a_start, a_end):
                    raise errors.rep_double_booked()

    # Priority 12: workforce classification.
    if rep is not None and project is not None:
        if rep["employment_type"] == "C1099" and project["scope_type"] == "FIXTURE_INSTALL":
            raise errors.classification_forbidden()

    # Priority 13: input sanitization.
    if project is None:
        raise errors.invalid_request("project_id is required")
    if ps is None:
        raise errors.invalid_request("project_store_id is required")
    if rep is None:
        raise errors.invalid_request("rep_id is required")
    if start is None:
        raise errors.invalid_request("scheduled_start is required and must be an ISO 8601 datetime")
    if end is None:
        raise errors.invalid_request("scheduled_end is required and must be an ISO 8601 datetime")
    if raid is not None and not isinstance(raid, str):
        raise errors.invalid_request("rework_authorization_id must be a string")

    # Priority 16: rework authorization state (evaluated last).
    if raid is not None:
        if ra["status"] != "APPROVED" or ps["status"] != "REWORK_REQUIRED":
            raise errors.rework_not_authorized()

    is_rework = raid is not None
    assignment = db.base_fields()
    assignment.update({
        "project_id": pid,
        "project_store_id": psid,
        "rep_id": rid,
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "status": "SCHEDULED",
        "is_rework": is_rework,
    })
    db.collections[COLL][assignment["id"]] = assignment
    # Store row advances to ASSIGNED (from PENDING or REWORK_REQUIRED).
    ps["status"] = "ASSIGNED"
    ps["assigned_rep_id"] = rid
    db.touch(ps)
    # Rework path consumes the authorization.
    if ra is not None:
        ra["status"] = "CONSUMED"
        db.touch(ra)
    # First assignment flips the project SCOPED -> IN_FIELD.
    if project["status"] == "SCOPED":
        project["status"] = "IN_FIELD"
        db.touch(project)
    return resp.success_object(db.serialize(assignment), 201)


@bp.get("/assignments")
def list_assignments():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "FieldRep", "PayrollAdmin"})
    items = list(db.collections[COLL].values())
    if role == "FieldRep":
        items = [a for a in items if a["rep_id"] == uid]
    for key in ("project_id", "rep_id", "project_store_id", "status"):
        v = mw.request.args.get(key)
        if v is not None:
            items = [a for a in items if a.get(key) == v]
    rw = mw.request.args.get("is_rework")
    if rw is not None:
        want = rw.strip().lower()
        items = [a for a in items if str(a["is_rework"]).lower() == want]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


@bp.get("/assignments/<aid>")
def get_assignment(aid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "FieldRep", "PayrollAdmin", "Client"})
    a = _get_assignment_or_404(aid)
    if role == "FieldRep":
        _require_own_assignment(uid, a)
    if role == "Client":
        project = services.get_project(a["project_id"])
        if project is None or project["client_id"] != uid:
            raise errors.unauthorized("client acting on another client's project")
    return resp.success_object(db.serialize(a))


@bp.get("/assignments/<aid>/store-visits")
def list_assignment_store_visits(aid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "Client", "FieldRep"})
    a = _get_assignment_or_404(aid)
    if role == "FieldRep":
        _require_own_assignment(uid, a)
    if role == "Client":
        project = services.get_project(a["project_id"])
        if project is None or project["client_id"] != uid:
            raise errors.unauthorized("client acting on another client's project")
    items = [v for v in db.collections["store_visits"].values() if v["assignment_id"] == aid]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


@bp.post("/assignments/<aid>/depart")
def depart_assignment(aid):
    uid, role = mw.auth()
    mw.require_role(role, {"FieldRep"})
    a = _get_assignment_or_404(aid)
    _require_own_assignment(uid, a)
    if a["status"] != "SCHEDULED":
        raise errors.invalid_state("assignment is not SCHEDULED")
    project = services.get_project(a["project_id"])
    if project is not None and services.depart_blocked_by_shipments(project, a["project_store_id"]):
        raise errors.fixtures_not_delivered()
    a["status"] = "EN_ROUTE"
    db.touch(a)
    return resp.success_object(db.serialize(a))


@bp.post("/assignments/<aid>/check-in")
def check_in_assignment(aid):
    uid, role = mw.auth()
    mw.require_role(role, {"FieldRep"})
    a = _get_assignment_or_404(aid)
    _require_own_assignment(uid, a)
    if a["status"] not in ("SCHEDULED", "EN_ROUTE"):
        raise errors.invalid_state("assignment cannot be checked in from its current state")
    ps = db.collections["project_stores"].get(a["project_store_id"])
    if ps is None or ps["status"] != "ASSIGNED":
        raise errors.invalid_state("project-store row is not ASSIGNED")
    # Rep may hold at most one ON_SITE assignment (double-booking block).
    for other in db.collections[COLL].values():
        if other["rep_id"] == a["rep_id"] and other["id"] != a["id"] and other["status"] == "ON_SITE":
            raise errors.rep_double_booked("rep already has an ON_SITE assignment")
    project = services.get_project(a["project_id"])
    if project is not None and services.checkin_blocked_by_shipments(project, a["project_store_id"]):
        raise errors.fixtures_not_delivered()
    now_ts = db.fmt_ts(db.now())
    visit = db.base_fields()
    visit.update({
        "assignment_id": a["id"],
        "check_in_at": now_ts,
        "check_out_at": None,
        "on_site_minutes": 0,
        "verification_status": "PENDING_REVIEW",
        "billable_amount_cents": None,
        "is_rework": a["is_rework"],
    })
    db.collections["store_visits"][visit["id"]] = visit
    a["status"] = "ON_SITE"
    db.touch(a)
    ps["status"] = "IN_PROGRESS"
    db.touch(ps)
    return resp.success_object(db.serialize(visit), 201)


@bp.post("/assignments/<aid>/check-out")
def check_out_assignment(aid):
    uid, role = mw.auth()
    mw.require_role(role, {"FieldRep"})
    a = _get_assignment_or_404(aid)
    _require_own_assignment(uid, a)
    if a["status"] != "ON_SITE":
        raise errors.invalid_state("assignment is not ON_SITE")
    visit = services.open_visit_of_assignment(aid)
    if visit is None:
        raise errors.invalid_state("no open store visit for this assignment")
    photos = [p for p in db.collections["photos"].values() if p["store_visit_id"] == visit["id"]]
    has_before = any(p["photo_type"] == "BEFORE" for p in photos)
    has_after = any(p["photo_type"] == "AFTER" for p in photos)
    if not (has_before and has_after):
        raise errors.invalid_state("check-out requires at least one BEFORE and one AFTER photo")
    now_dt = db.now()
    check_in = mw.parse_dt(visit["check_in_at"])
    visit["check_out_at"] = db.fmt_ts(now_dt)
    if check_in is not None:
        visit["on_site_minutes"] = int((now_dt - check_in).total_seconds() // 60)
    else:
        visit["on_site_minutes"] = 0
    db.touch(visit)
    a["status"] = "SUBMITTED"
    db.touch(a)
    return resp.success_object(db.serialize(visit))


@bp.post("/assignments/<aid>/cancel")
def cancel_assignment(aid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    a = _get_assignment_or_404(aid)
    if a["status"] not in ("SCHEDULED", "EN_ROUTE"):
        raise errors.invalid_state("assignment cannot be cancelled from its current state")
    a["status"] = "CANCELLED"
    db.touch(a)
    ps = db.collections["project_stores"].get(a["project_store_id"])
    if ps is not None and ps["status"] == "ASSIGNED":
        ps["status"] = "PENDING"
        ps["assigned_rep_id"] = None
        db.touch(ps)
    return resp.success_object(db.serialize(a))
