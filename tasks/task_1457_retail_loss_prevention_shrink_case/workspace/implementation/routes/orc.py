"""ORC group + case link endpoints (PRD §3.8)."""

from flask import Blueprint, request

from db import db
from middleware import get_auth, require_role, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.validate import body, req_string, opt_string, req_int, get_or_404
from services.entities import make_orc_group, make_case_link, pub, touch
from services.calculations import (
    recompute_group_counters, evaluate_group_escalation, recompute_case_priority,
)
from errors import (
    err409, err404,
    ERR_DUPLICATE_GROUP_NAME, ERR_INVALID_STATE_TRANSITION,
    ERR_GROUP_NOT_LINKABLE, ERR_GROUP_HAS_PROPOSED_LINKS, ERR_LINK_EXISTS,
)

bp = Blueprint("orc", __name__)

TERMINAL_CASE_STATES = {"CLOSED_SUBSTANTIATED", "CLOSED_UNSUBSTANTIATED",
                        "CLOSED_REFERRED", "MERGED"}


@bp.route("/orc-groups", methods=["POST"])
def create_group():
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    data = body()
    name = req_string(data, "name")
    description = opt_string(data, "description")
    for g in db.orc_groups.values():
        if g["name"] == name:
            raise err409(ERR_DUPLICATE_GROUP_NAME,
                         "Group name %s already exists" % name)
    group = make_orc_group(name, description)
    db.orc_groups[group["id"]] = group
    return success_object(pub(group), status=201)


@bp.route("/orc-groups", methods=["GET"])
def list_groups():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    status = _q("status")
    items = sorted(db.orc_groups.values(), key=lambda g: (g["created_at"], g["id"]))
    if status is not None:
        items = [g for g in items if g["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pub(g) for g in page], limit, offset, total)


@bp.route("/orc-groups/<group_id>", methods=["GET"])
def get_group(group_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    group = get_or_404(db.orc_groups, group_id, "orc group")
    return success_object(pub(group))


@bp.route("/orc-groups/<group_id>/disrupt", methods=["POST"])
def disrupt_group(group_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    group = get_or_404(db.orc_groups, group_id, "orc group")
    if group["status"] != "ACTIVE_MONITORING":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Group must be ACTIVE_MONITORING to disrupt")
    group["status"] = "DISRUPTED"
    touch(group)
    for link in db.case_links.values():
        if link["orc_group_id"] == group_id and link["status"] == "PROPOSED":
            link["status"] = "REJECTED"
            touch(link)
    return success_object(pub(group))


@bp.route("/orc-groups/<group_id>/dismiss", methods=["POST"])
def dismiss_group(group_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    group = get_or_404(db.orc_groups, group_id, "orc group")
    if group["status"] not in ("IDENTIFIED", "ACTIVE_MONITORING"):
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Group must be IDENTIFIED or ACTIVE_MONITORING to dismiss")
    has_proposed = any(l["orc_group_id"] == group_id and l["status"] == "PROPOSED"
                       for l in db.case_links.values())
    if has_proposed:
        raise err409(ERR_GROUP_HAS_PROPOSED_LINKS,
                     "Group has PROPOSED links outstanding")
    if group["confirmed_case_count"] != 0:
        raise err409(ERR_GROUP_NOT_LINKABLE,
                     "Group has CONFIRMED links")
    group["status"] = "DISMISSED"
    touch(group)
    return success_object(pub(group))


@bp.route("/case-links", methods=["POST"])
def create_link():
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    data = body()
    case_id = req_string(data, "case_id")
    orc_group_id = req_string(data, "orc_group_id")
    link_score = req_int(data, "link_score", minimum=0)
    if link_score > 100:
        from errors import err400, ERR_INVALID_REQUEST
        raise err400(ERR_INVALID_REQUEST, "link_score must be in [0,100]")
    case = get_or_404(db.cases, case_id, "case")
    group = get_or_404(db.orc_groups, orc_group_id, "orc group")
    if group["status"] not in ("IDENTIFIED", "ACTIVE_MONITORING"):
        raise err409(ERR_GROUP_NOT_LINKABLE,
                     "Group is not linkable in status %s" % group["status"])
    for l in db.case_links.values():
        if (l["case_id"] == case_id and l["orc_group_id"] == orc_group_id
                and l["status"] != "REJECTED"):
            raise err409(ERR_LINK_EXISTS,
                         "A non-REJECTED link already exists for this case and "
                         "group")
    link = make_case_link(case_id, orc_group_id, link_score)
    db.case_links[link["id"]] = link
    return success_object(pub(link), status=201)


@bp.route("/case-links", methods=["GET"])
def list_links():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    case_id = _q("case_id")
    orc_group_id = _q("orc_group_id")
    status = _q("status")
    items = sorted(db.case_links.values(), key=lambda l: (l["created_at"], l["id"]))
    if case_id is not None:
        items = [l for l in items if l["case_id"] == case_id]
    if orc_group_id is not None:
        items = [l for l in items if l["orc_group_id"] == orc_group_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pub(l) for l in page], limit, offset, total)


@bp.route("/case-links/<link_id>", methods=["GET"])
def get_link(link_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    link = get_or_404(db.case_links, link_id, "case link")
    return success_object(pub(link))


@bp.route("/case-links/<link_id>/confirm", methods=["POST"])
def confirm_link(link_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    link = get_or_404(db.case_links, link_id, "case link")
    if link["status"] != "PROPOSED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Link must be PROPOSED to confirm")
    case = db.cases.get(link["case_id"])
    if case is None or case["status"] in TERMINAL_CASE_STATES:
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Case must be non-terminal and not MERGED")
    link["status"] = "CONFIRMED"
    touch(link)
    group = db.orc_groups[link["orc_group_id"]]
    recompute_group_counters(group)
    evaluate_group_escalation(group)
    touch(group)
    # case priority recompute regardless of escalation flip (a confirmed link
    # to an already-ACTIVE_MONITORING group also raises priority)
    recompute_case_priority(case)
    return success_object(pub(link))


@bp.route("/case-links/<link_id>/reject", methods=["POST"])
def reject_link(link_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    link = get_or_404(db.case_links, link_id, "case link")
    if link["status"] != "PROPOSED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Link must be PROPOSED to reject")
    link["status"] = "REJECTED"
    touch(link)
    return success_object(pub(link))


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None
