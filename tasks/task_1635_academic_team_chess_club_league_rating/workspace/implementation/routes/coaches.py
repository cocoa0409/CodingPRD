from flask import Blueprint, request

from db import store, new_id, next_seq, now_iso
from errors import invalid_request, state_error, integrity_error
from middleware import require_roles, ALL_ROLES
from response import success_object, success_array, paginate
from services.common import get_or_404, touch
from services.serializers import coach_json
from validate import Body, get_body

bp = Blueprint("coaches", __name__)

READ = ALL_ROLES
CERT_LEVELS = ("CLUB", "CERTIFIED", "SENIOR")


@bp.route("/api/coaches", methods=["POST"])
@require_roles("FederationAdmin")
def create_coach():
    data = get_body()
    club_id = data.get("club_id")
    if isinstance(club_id, str):
        get_or_404(store.clubs, club_id, "club")
    body = Body(data, {"club_id", "full_name", "email", "certification_level"})
    cid = body.req_str("club_id")
    club = get_or_404(store.clubs, cid, "club")
    name = body.req_str("full_name")
    email = body.req_str("email")
    level = body.req_enum("certification_level", CERT_LEVELS)
    if club["status"] == "SUSPENDED":
        raise integrity_error("ERR_CLUB_SUSPENDED", "Club is SUSPENDED")
    now = now_iso()
    c = {"id": new_id(), "_seq": next_seq(), "created_at": now, "updated_at": now,
         "version": 1, "club_id": cid, "full_name": name, "email": email,
         "certification_level": level, "status": "ACTIVE"}
    store.coaches[c["id"]] = c
    return success_object(coach_json(c), 201)


@bp.route("/api/coaches", methods=["GET"])
@require_roles(*READ)
def list_coaches():
    items = list(store.coaches.values())
    cid = request.args.get("club_id")
    if cid is not None:
        items = [c for c in items if c["club_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([coach_json(c) for c in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/coaches/<coachId>", methods=["GET"])
@require_roles(*READ)
def get_coach(coachId):
    c = get_or_404(store.coaches, coachId, "coach")
    return success_object(coach_json(c), 200)


@bp.route("/api/coaches/<coachId>/deactivate", methods=["POST"])
@require_roles("FederationAdmin")
def deactivate_coach(coachId):
    get_body()
    c = get_or_404(store.coaches, coachId, "coach")
    if c["status"] != "ACTIVE":
        raise state_error("ERR_COACH_INVALID_STATE", "Coach is not ACTIVE")
    c["status"] = "INACTIVE"
    touch(c)
    # cascade: release this coach's ASSIGNED proctor assignments
    for a in store.proctor_assignments.values():
        if a["coach_id"] == c["id"] and a["status"] == "ASSIGNED":
            a["status"] = "RELEASED"
            touch(a)
    return success_object(coach_json(c), 200)


@bp.route("/api/coaches/<coachId>/reactivate", methods=["POST"])
@require_roles("FederationAdmin")
def reactivate_coach(coachId):
    get_body()
    c = get_or_404(store.coaches, coachId, "coach")
    if c["status"] != "INACTIVE":
        raise state_error("ERR_COACH_INVALID_STATE", "Coach is not INACTIVE")
    c["status"] = "ACTIVE"
    touch(c)
    return success_object(coach_json(c), 200)
