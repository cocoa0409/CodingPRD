"""Panelist recruitment, qualification and discipline (PRD §3.4)."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_EMAIL_NOT_UNIQUE,
    ERR_INVALID_PANELIST_STATE,
)
from flask import Blueprint, request
from response import respond, respond_list
from services import ser_panelist, ATTRIBUTES
from util import (
    body, paginate, req_list, req_num, req_str, sort_created, touch,
)

bp = Blueprint("panelists", __name__)


def get_panelist(panelist_id):
    p = db.store["panelists"].get(panelist_id)
    if p is None:
        raise_err(ERR_NOT_FOUND, f"Panelist {panelist_id} not found")
    return p


@bp.route("/panelists", methods=["POST"])
@require_roles("PanelCoordinator")
def create_panelist():
    b = body()
    full_name = req_str(b, "full_name")
    email = req_str(b, "email")
    qualified_attributes = req_list(b, "qualified_attributes")
    for attr in qualified_attributes:
        if attr not in ATTRIBUTES:
            raise_err(ERR_INVALID_REQUEST,
                      f"qualified_attributes must be a subset of "
                      f"{sorted(ATTRIBUTES)}")
    for p in db.store["panelists"].values():
        if p["email"] == email:
            raise_err(ERR_EMAIL_NOT_UNIQUE,
                      f"email {email} is already registered")
    now = clock.now()
    panelist = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "full_name": full_name,
        "email": email,
        "qualified_attributes": list(qualified_attributes),
        "screening_acuity_score": None,
        "training_sessions_completed": 0,
        "consecutive_no_shows": 0,
        "consistency_index_provisional": None,
        "consistency_index_final": None,
        "status": "APPLIED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["panelists"][panelist["id"]] = panelist
    return respond(ser_panelist(panelist), 201)


@bp.route("/panelists", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_panelists():
    items = sort_created(db.store["panelists"].values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, pagination = paginate(items)
    return respond_list([ser_panelist(p) for p in page], pagination)


@bp.route("/panelists/<panelist_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_panelist(panelist_id):
    return respond(ser_panelist(get_panelist(panelist_id)), 200)


@bp.route("/panelists/<panelist_id>/record-screening", methods=["POST"])
@require_roles("PanelCoordinator")
def record_screening(panelist_id):
    panelist = get_panelist(panelist_id)
    b = body()
    acuity_score = req_num(b, "acuity_score")
    if acuity_score < 0 or acuity_score > 100:
        raise_err(ERR_INVALID_REQUEST, "acuity_score must be within 0..100")
    if panelist["status"] != "APPLIED":
        raise_err(ERR_INVALID_PANELIST_STATE,
                  "record-screening requires status APPLIED")
    panelist["screening_acuity_score"] = acuity_score
    # Inclusive threshold: 80 itself qualifies (PRD §3.4).
    panelist["status"] = "TRAINING" if acuity_score >= 80 else "SCREENED_OUT"
    touch(panelist)
    return respond(ser_panelist(panelist), 200)


@bp.route("/panelists/<panelist_id>/record-training", methods=["POST"])
@require_roles("PanelCoordinator")
def record_training(panelist_id):
    panelist = get_panelist(panelist_id)
    if panelist["status"] != "TRAINING":
        raise_err(ERR_INVALID_PANELIST_STATE,
                  "record-training requires status TRAINING")
    panelist["training_sessions_completed"] += 1
    if panelist["training_sessions_completed"] >= 3:
        panelist["status"] = "QUALIFIED"
    touch(panelist)
    return respond(ser_panelist(panelist), 200)


@bp.route("/panelists/<panelist_id>/deactivate", methods=["POST"])
@require_roles("PanelCoordinator")
def deactivate_panelist(panelist_id):
    panelist = get_panelist(panelist_id)
    if panelist["status"] != "QUALIFIED":
        raise_err(ERR_INVALID_PANELIST_STATE,
                  "deactivate requires status QUALIFIED")
    panelist["status"] = "INACTIVE"
    touch(panelist)
    return respond(ser_panelist(panelist), 200)


@bp.route("/panelists/<panelist_id>/reactivate", methods=["POST"])
@require_roles("PanelCoordinator")
def reactivate_panelist(panelist_id):
    panelist = get_panelist(panelist_id)
    if panelist["status"] != "INACTIVE":
        raise_err(ERR_INVALID_PANELIST_STATE,
                  "reactivate requires status INACTIVE")
    final = panelist["consistency_index_final"]
    if final is None or final >= 60:
        panelist["status"] = "QUALIFIED"
    else:
        # Remedial branch: back to TRAINING with the counter reset.
        panelist["status"] = "TRAINING"
        panelist["training_sessions_completed"] = 0
    touch(panelist)
    return respond(ser_panelist(panelist), 200)


@bp.route("/panelists/<panelist_id>/assign-remedial", methods=["POST"])
@require_roles("PanelCoordinator")
def assign_remedial(panelist_id):
    panelist = get_panelist(panelist_id)
    if panelist["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_PANELIST_STATE,
                  "assign-remedial requires status SUSPENDED")
    panelist["status"] = "TRAINING"
    panelist["training_sessions_completed"] = 0
    panelist["consecutive_no_shows"] = 0
    touch(panelist)
    return respond(ser_panelist(panelist), 200)
