"""Campus endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import get_or_404, recompute_campus_composite
from util import as_int, as_str, body, paginate, pagination, required, stamp_new, touch

bp = Blueprint("campuses", __name__)


def campus_view(c):
    return {k: v for k, v in c.items() if not k.startswith("_")}


@bp.post("/accreditation/systems/<id>/campuses")
def create_campus(id):
    auth(["AccreditationOfficer"])
    system = get_or_404("systems", id, "InstitutionSystem")
    data = body()
    name = as_str(required(data, "name"), "name")
    enrollment = as_int(required(data, "enrollment"), "enrollment")
    if enrollment < 1:
        raise ApiError("ERR_VALIDATION", 400, "enrollment must be >= 1")
    if system["system_type"] == "SINGLE_SCHOOL":
        existing = [c for c in DB["campuses"].values() if c["system_id"] == id]
        if existing:
            raise ApiError(
                "ERR_FISCAL_VIOLATION",
                422,
                "SINGLE_SCHOOL systems may not create additional Campuses",
            )
    record = {
        "id": new_id(),
        "system_id": id,
        "name": name,
        "enrollment": enrollment,
        "campus_status": "IN_SCOPE",
        "composite_index_pct": None,
    }
    stamp_new(record, with_version=True)
    DB["campuses"][record["id"]] = record
    return ok(campus_view(record), status=201)


@bp.get("/accreditation/systems/<id>/campuses")
def list_campuses(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("systems", id, "InstitutionSystem")
    limit, offset = pagination()
    rows = [c for c in DB["campuses"].values() if c["system_id"] == id]
    rows.sort(key=lambda c: c["created_at"])
    status = request.args.get("campus_status")
    if status:
        rows = [r for r in rows if r["campus_status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([campus_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/campuses/<id>")
def get_campus(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    row = get_or_404("campuses", id, "Campus")
    return ok(campus_view(row))


@bp.post("/accreditation/campuses/<id>/scope-out")
def scope_out(id):
    auth(["AccreditationOfficer"])
    campus = get_or_404("campuses", id, "Campus")
    if campus["campus_status"] != "IN_SCOPE":
        raise ApiError("ERR_INVALID_STATE", 409, "Campus is not IN_SCOPE")
    system = DB["systems"].get(campus["system_id"])
    current_term_id = system["current_term_id"] if system else None
    if current_term_id is not None:
        finalized = [
            r for r in DB["ratings"].values()
            if r["campus_id"] == id
            and r["term_id"] == current_term_id
            and r["status"] == "FINALIZED"
        ]
        if finalized:
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Campus has FINALIZED ratings under the current term",
            )
    campus["campus_status"] = "OUT_OF_SCOPE"
    campus["composite_index_pct"] = None
    touch(campus)
    return ok(campus_view(campus))


@bp.post("/accreditation/campuses/<id>/scope-in")
def scope_in(id):
    auth(["AccreditationOfficer"])
    campus = get_or_404("campuses", id, "Campus")
    if campus["campus_status"] != "OUT_OF_SCOPE":
        raise ApiError("ERR_INVALID_STATE", 409, "Campus is not OUT_OF_SCOPE")
    system = DB["systems"].get(campus["system_id"])
    if system is None or system["current_term_id"] is None:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "System has no current term"
        )
    term = DB["terms"].get(system["current_term_id"])
    if term is None or term["status"] not in ("PREPARATION", "SELF_STUDY"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Current term is not in PREPARATION or SELF_STUDY",
        )
    campus["campus_status"] = "IN_SCOPE"
    touch(campus)
    recompute_campus_composite(campus)
    return ok(campus_view(campus))


@bp.post("/accreditation/campuses/<id>/withdraw")
def withdraw(id):
    auth(["AccreditationOfficer"])
    campus = get_or_404("campuses", id, "Campus")
    if campus["campus_status"] != "IN_SCOPE":
        raise ApiError("ERR_INVALID_STATE", 409, "Campus is not IN_SCOPE")
    system = DB["systems"].get(campus["system_id"])
    current_term_id = system["current_term_id"] if system else None
    if current_term_id is not None:
        term = DB["terms"].get(current_term_id)
        if term is not None and term["status"] not in ("PREPARATION", "CLOSED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Current term must be in PREPARATION or CLOSED to withdraw",
            )
    # Delete SelfStudyRating rows for this campus under any non-closed term.
    to_delete = []
    for r in DB["ratings"].values():
        if r["campus_id"] != id:
            continue
        t = DB["terms"].get(r["term_id"])
        if t is not None and t["status"] != "CLOSED":
            to_delete.append(r["id"])
    for rid in to_delete:
        del DB["ratings"][rid]
    campus["campus_status"] = "WITHDRAWN"
    campus["composite_index_pct"] = None
    touch(campus)
    return ok(campus_view(campus))


@bp.get("/accreditation/campuses/<id>/ratings")
def list_campus_ratings(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("campuses", id, "Campus")
    limit, offset = pagination()
    rows = [r for r in DB["ratings"].values() if r["campus_id"] == id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    from routes.ratings import rating_view
    return ok_list([rating_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/campuses/<id>/survey-windows")
def list_campus_windows(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("campuses", id, "Campus")
    limit, offset = pagination()
    rows = [w for w in DB["survey_windows"].values() if w["campus_id"] == id]
    rows.sort(key=lambda w: w["created_at"])
    page, total = paginate(rows, limit, offset)
    from routes.surveys import window_view
    return ok_list([window_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/campuses/<id>/goals")
def list_campus_goals(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("campuses", id, "Campus")
    limit, offset = pagination()
    rows = [g for g in DB["goals"].values() if g["campus_id"] == id]
    rows.sort(key=lambda g: g["created_at"])
    page, total = paginate(rows, limit, offset)
    from routes.goals import goal_view
    return ok_list([goal_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/campuses/<id>/visits")
def list_campus_visits(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader", "Reviewer"])
    get_or_404("campuses", id, "Campus")
    limit, offset = pagination()
    rows = [v for v in DB["visits"].values() if v["campus_id"] == id]
    rows.sort(key=lambda v: v["created_at"])
    page, total = paginate(rows, limit, offset)
    from routes.visits import visit_view
    return ok_list([visit_view(r) for r in page], total, limit, offset)
