"""AffinityGroup endpoints."""

from flask import Blueprint, request

import db
from errors import (
    err_invalid_request, err_invalid_state, err_not_found, err_programs_outstanding,
)
from middleware import require_roles
from response import success_list, success_object
from services.common import (
    apply_pagination, json_body, new_entity, pagination_args, req_enum,
    req_int, req_str, touch,
)
from services.serializers import GROUP_FIELDS, serialize

bp = Blueprint("groups", __name__)

STAFF_OR_DIRECTOR = ("AlumniRelationsStaff", "AlumniRelationsDirector")
GROUP_READ = ("AlumniRelationsStaff", "AlumniRelationsDirector", "AffinityGroupLeader")
KINDS = ("AFFINITY", "REGIONAL_CHAPTER")


def get_group_or_404(gid):
    g = db.groups.get(gid)
    if g is None:
        raise err_not_found("AffinityGroup not found")
    return g


def rederive_budget_remaining(group):
    group["budget_remaining_cents"] = (
        group["annual_budget_cents"]
        - group["budget_committed_cents"]
        - group["budget_spent_cents"]
    )


@bp.route("/alumni/groups", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def create_group(_role, _user_id):
    body = json_body(required=["name", "kind", "annual_budget_cents"])
    name = req_str(body["name"], "name")
    kind = req_enum(body["kind"], "kind", KINDS)
    budget = req_int(body["annual_budget_cents"], "annual_budget_cents")
    if budget < 0:
        raise err_invalid_request("annual_budget_cents must be >= 0")
    group = new_entity({
        "name": name,
        "kind": kind,
        "status": "ACTIVE",
        "annual_budget_cents": budget,
        "budget_committed_cents": 0,
        "budget_spent_cents": 0,
        "budget_remaining_cents": budget,
    })
    db.groups[group["id"]] = group
    return success_object(serialize(group, GROUP_FIELDS), status=201)


@bp.route("/alumni/groups/<gid>", methods=["GET"])
@require_roles(*GROUP_READ)
def get_group(gid, _role, _user_id):
    return success_object(serialize(get_group_or_404(gid), GROUP_FIELDS))


@bp.route("/alumni/groups", methods=["GET"])
@require_roles(*GROUP_READ)
def list_groups(_role, _user_id):
    limit, offset = pagination_args()
    rows = list(db.groups.values())
    status = request.args.get("status")
    if status:
        rows = [g for g in rows if g["status"] == status]
    kind = request.args.get("kind")
    if kind:
        rows = [g for g in rows if g["kind"] == kind]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(g, GROUP_FIELDS) for g in page], limit, offset, total)


@bp.route("/alumni/groups/<gid>/suspend", methods=["POST"])
@require_roles("AlumniRelationsDirector")
def suspend(gid, _role, _user_id):
    group = get_group_or_404(gid)
    if group["status"] != "ACTIVE":
        raise err_invalid_state("Group must be ACTIVE to suspend")
    group["status"] = "SUSPENDED"
    touch(group)
    return success_object(serialize(group, GROUP_FIELDS))


@bp.route("/alumni/groups/<gid>/reactivate", methods=["POST"])
@require_roles("AlumniRelationsDirector")
def reactivate(gid, _role, _user_id):
    group = get_group_or_404(gid)
    if group["status"] != "SUSPENDED":
        raise err_invalid_state("Group must be SUSPENDED to reactivate")
    group["status"] = "ACTIVE"
    touch(group)
    return success_object(serialize(group, GROUP_FIELDS))


@bp.route("/alumni/groups/<gid>/dissolve", methods=["POST"])
@require_roles("AlumniRelationsDirector")
def dissolve(gid, _role, _user_id):
    group = get_group_or_404(gid)
    if group["status"] != "ACTIVE":
        raise err_invalid_state("Group must be ACTIVE to dissolve")
    for p in db.programs.values():
        if p["group_id"] == gid and p["status"] in ("APPROVED", "PUBLISHED"):
            raise err_programs_outstanding()
    group["status"] = "DISSOLVED"
    touch(group)
    return success_object(serialize(group, GROUP_FIELDS))
