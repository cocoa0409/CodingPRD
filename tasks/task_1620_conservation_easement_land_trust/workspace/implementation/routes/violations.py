"""Violation endpoints."""
from flask import Blueprint, g, request

import db
import utils
from errors import ApiError
from middleware import ANY_ROLE, body, paginate, require_roles
from response import ok
from services import domain

bp = Blueprint("violations", __name__)


def get_violation_or_404(violation_id):
    r = db.violations.get(violation_id)
    if r is None:
        raise ApiError("ERR_VIOLATION_NOT_FOUND", "Violation id does not exist.", 404)
    return r


def _current_active_landowner(e):
    lo = db.landowners.get(e["current_landowner_id"] or "")
    return lo if lo is not None and lo["status"] == "ACTIVE" else None


@bp.route("/stewardship/violations", methods=["POST"])
@require_roles("StewardshipCoordinator")
def create_violation():
    b = body()
    easement_id = b.get("easement_id")
    if easement_id is not None and easement_id not in db.easements:
        raise ApiError("ERR_EASEMENT_NOT_FOUND", "Easement id does not exist.", 404)
    visit_id = b.get("monitoring_visit_id")
    visit = None
    if visit_id is not None:
        visit = db.monitoring_visits.get(visit_id)
        if visit is None:
            raise ApiError("ERR_MONITORING_VISIT_NOT_FOUND", "MonitoringVisit id does not exist.", 404)
    e = db.easements.get(easement_id)
    if e is not None and e["status"] != "RECORDED":
        raise ApiError("ERR_EASEMENT_NOT_RECORDED", "Child operational create requires a RECORDED easement.", 409)
    detected_by = b.get("detected_by_user_id")
    vtype = b.get("violation_type")
    severity = b.get("severity")
    detected_on = utils.parse_date(b.get("detected_on"))
    if (
        e is None
        or not isinstance(detected_by, str)
        or not isinstance(vtype, str)
        or severity not in domain.CURE_DAYS
        or detected_on is None
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "easement_id, detected_by_user_id, violation_type, a valid severity and detected_on are required.",
            400,
        )
    if vtype not in e["permitted_use_matrix"]:
        raise ApiError("ERR_INVALID_REQUEST", "violation_type must be a key of the permitted_use_matrix.", 400)
    if visit is not None and visit["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_REQUEST", "Referenced monitoring visit must be COMPLETED.", 400)
    if e["permitted_use_matrix"][vtype] == "PERMITTED":
        raise ApiError("ERR_USE_PERMITTED_NOT_VIOLABLE", "A PERMITTED matrix cell cannot ground a violation.", 422)
    now = utils.now_iso()
    r = {
        "id": utils.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "easement_id": easement_id,
        "monitoring_visit_id": visit_id,
        "detected_by_user_id": detected_by,
        "violation_type": vtype,
        "severity": severity,
        "detected_on": detected_on,
        "notice_served_on": None,
        "cure_deadline_on": None,
        "resolved_on": None,
        "resolution_verified_by_user_id": None,
        "escalated_by": None,
        "status": "OPEN",
    }
    db.violations[r["id"]] = r
    # Active use authorization on the same (easement, use_type) is breached.
    for a in db.use_authorizations.values():
        if (
            a["easement_id"] == easement_id
            and a["use_type"] == vtype
            and a["status"] in domain.ACTIVE_USE_AUTH_STATES
        ):
            a["conditions_breached"] = True
            domain.bump(a)
    domain.bump(e)  # open_violation_count + posture recomputed
    return ok(domain.violation_json(r), 201)


@bp.route("/stewardship/violations", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_violations():
    filters = {}
    for key in ("easement_id", "monitoring_visit_id", "status", "severity"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    return paginate(list(db.violations.values()), domain.violation_json, filters)


@bp.route("/stewardship/violations/<violationId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_violation(violationId):
    return ok(domain.violation_json(get_violation_or_404(violationId)))


@bp.route("/stewardship/violations/<violationId>/send-notice", methods=["POST"])
@require_roles("StewardshipCoordinator")
def send_notice(violationId):
    r = get_violation_or_404(violationId)
    if r["status"] != "OPEN":
        raise ApiError("ERR_INVALID_VIOLATION_STATE", "Send-notice requires OPEN.", 409)
    e = db.easements[r["easement_id"]]
    if _current_active_landowner(e) is None:
        raise ApiError("ERR_NOT_CURRENT_LANDOWNER", "Notice requires an ACTIVE current landowner.", 403)
    r["notice_served_on"] = utils.today()
    r["cure_deadline_on"] = utils.add_days(utils.today(), domain.CURE_DAYS[r["severity"]])
    r["status"] = "NOTICE_SENT"
    domain.bump(r)
    return ok(domain.violation_json(r))


@bp.route("/stewardship/violations/<violationId>/start-cure", methods=["POST"])
@require_roles("Landowner")
def start_cure(violationId):
    r = get_violation_or_404(violationId)
    if r["status"] != "NOTICE_SENT":
        raise ApiError("ERR_INVALID_VIOLATION_STATE", "Start-cure requires NOTICE_SENT.", 409)
    e = db.easements[r["easement_id"]]
    if g.user_id != e["current_landowner_id"]:
        raise ApiError("ERR_NOT_CURRENT_LANDOWNER", "Caller is not the easement's current landowner.", 403)
    r["status"] = "CURE_IN_PROGRESS"
    domain.bump(r)
    return ok(domain.violation_json(r))


@bp.route("/stewardship/violations/<violationId>/resolve", methods=["POST"])
@require_roles("StewardshipCoordinator")
def resolve_violation(violationId):
    r = get_violation_or_404(violationId)
    if r["status"] != "CURE_IN_PROGRESS":
        raise ApiError("ERR_INVALID_VIOLATION_STATE", "Resolve requires CURE_IN_PROGRESS.", 409)
    if g.user_id == r["detected_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The detector may not verify resolution.", 403)
    r["resolved_on"] = utils.today()
    r["resolution_verified_by_user_id"] = g.user_id
    r["status"] = "RESOLVED"
    domain.bump(r)
    domain.bump(db.easements[r["easement_id"]])  # open_violation_count + posture
    return ok(domain.violation_json(r))


@bp.route("/stewardship/violations/<violationId>/escalate", methods=["POST"])
@require_roles("StewardshipCoordinator")
def escalate_violation_route(violationId):
    r = get_violation_or_404(violationId)
    if r["status"] != "NOTICE_SENT":
        raise ApiError("ERR_INVALID_VIOLATION_STATE", "Manual escalate requires NOTICE_SENT.", 409)
    domain.escalate_violation(r, "MANUAL")
    return ok(domain.violation_json(r))
