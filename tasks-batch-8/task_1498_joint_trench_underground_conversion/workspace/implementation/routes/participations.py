"""UtilityParticipation endpoints: invite/list/get/transition (incl. withdrawal
cascade). UtilityCoordinator identity is entity-backed: X-User-ID must equal the
target participation id (ERR_OWNERSHIP_VIOLATION otherwise)."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch, stamp_new
from errors import (
    raise_err,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_OWNERSHIP_VIOLATION,
)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from services.serializers import participation_view
from util import (
    get_json_body,
    get_or_404,
    optional_bool,
    parse_pagination,
    paginate,
    query_arg,
    require_enum,
    require_field,
    require_int,
    require_string,
    sort_created,
)

bp = Blueprint("participations", __name__, url_prefix="/api/participations")

PM = "ProgramManager"
UC = "UtilityCoordinator"
ANY = "Any"

UTILITY_TYPES = {"ELECTRIC", "TELECOM", "CATV"}
TRANSITION_TARGETS = {"COMMITTED", "MOBILIZED", "INSTALLED", "WITHDRAWN"}


@bp.route("", methods=["POST"])
@require_roles(PM)
def create_participation(_user_id: str, _role: str):
    body = get_json_body()
    # Existence of the body reference is resolved before structural validation.
    if body.get("project_id") is not None:
        get_or_404(db.projects, body["project_id"], "Project")
    project_id = require_string(body, "project_id")
    project = db.projects[project_id]
    utility_name = require_string(body, "utility_name")
    utility_type = require_enum(body, "utility_type", UTILITY_TYPES)
    cost_share_bp = require_int(body, "cost_share_bp", minimum=1, maximum=10000)
    sequence_order = require_int(body, "sequence_order", minimum=1)
    has_separation_waiver = optional_bool(body, "has_separation_waiver", False)

    if project["status"] not in {"PLANNING", "MOBILIZED"}:
        raise_err(ERR_INVALID_STATE,
                  "participations may be created only while the project is "
                  "PLANNING or MOBILIZED")

    participation = stamp_new({
        "project_id": project_id,
        "utility_name": utility_name,
        "utility_type": utility_type,
        "cost_share_bp": cost_share_bp,
        "sequence_order": sequence_order,
        "has_separation_waiver": has_separation_waiver,
        "status": "INVITED",
        "provisional_share_cents": 0,
        "final_share_cents": None,
        "variance_flag": False,
        "withdrawn_on": None,
        "_prov_exists": False,
    })
    db.participations[participation["id"]] = participation
    return success_object(participation_view(participation), 201)


@bp.route("", methods=["GET"])
@require_roles(ANY)
def list_participations(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.participations.values())
    project_id = query_arg("project_id")
    status = query_arg("status")
    if project_id:
        items = [p for p in items if p["project_id"] == project_id]
    if status:
        items = [p for p in items if p["status"] == status]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([participation_view(p) for p in page], limit, offset, total)


@bp.route("/<pid>", methods=["GET"])
@require_roles(ANY)
def get_participation(pid: str, _user_id: str, _role: str):
    return success_object(participation_view(get_or_404(db.participations, pid,
                                                        "UtilityParticipation")))


@bp.route("/<pid>/transition", methods=["POST"])
@require_roles(UC)
def transition_participation(pid: str, _user_id: str, _role: str):
    # Ownership (priority 3) precedes existence: the coordinator's X-User-ID
    # must equal the target participation id itself.
    if pid != _user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION,
                  "UtilityCoordinator may only act on its own participation")
    participation = get_or_404(db.participations, pid, "UtilityParticipation")
    body = get_json_body()
    to = require_field(body, "to")
    if not isinstance(to, str) or to not in TRANSITION_TARGETS:
        raise_err(ERR_VALIDATION, f"to must be one of {sorted(TRANSITION_TARGETS)}")

    current = participation["status"]
    if current in {"SETTLED", "WITHDRAWN"}:
        raise_err(ERR_INVALID_STATE, f"participation is terminal ({current})")
    project = db.projects.get(participation["project_id"])

    if to == "COMMITTED":
        if current != "INVITED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> COMMITTED")
        if project["status"] != "PLANNING":
            raise_err(ERR_INVALID_STATE, "commit requires project PLANNING")
        participation["status"] = "COMMITTED"
        touch(participation)

    elif to == "MOBILIZED":
        if current != "COMMITTED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> MOBILIZED")
        if project["status"] not in {"MOBILIZED", "TRENCHING", "CONVERTING"}:
            raise_err(ERR_INVALID_STATE,
                      "participation mobilization requires project "
                      "MOBILIZED|TRENCHING|CONVERTING")
        participation["status"] = "MOBILIZED"
        touch(participation)

    elif to == "INSTALLED":
        if current not in {"MOBILIZED", "COMMITTED"}:
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> INSTALLED")
        for s in db.slots.values():
            if (s["participation_id"] == pid
                    and s["status"] not in {"VERIFIED", "RELEASED"}):
                raise_err(ERR_INVALID_STATE,
                          "every occupancy slot of this participation must be "
                          "VERIFIED|RELEASED")
        participation["status"] = "INSTALLED"
        touch(participation)

    elif to == "WITHDRAWN":
        if current not in {"INVITED", "COMMITTED", "MOBILIZED"}:
            raise_err(ERR_INVALID_STATE, f"cannot withdraw from {current}")
        domain.withdrawal_cascade(participation, project)

    return success_object(participation_view(participation))
