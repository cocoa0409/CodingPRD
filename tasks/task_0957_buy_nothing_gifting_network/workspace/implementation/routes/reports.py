from datetime import timedelta

from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    MISSING, get_auth, require_role, actor_member, require_active,
    require_group_moderator, is_moderator, validate, v_str, v_str_empty_ok,
    v_enum, v_int,
)
from response import ok, get_body, paginate, no_body_fields
from services import (
    SLA_HOURS, new_entity, touch, ser_report, ser_action, group_health,
    add_event, recompute_strike_status, withdraw_post,
)

bp = Blueprint("reports", __name__)

TARGET_TYPES = ("MEMBER", "GIFT_POST", "CLAIM", "CURB_ALERT")
REPORT_CATEGORIES = ("NO_SHOW", "SAFETY", "SPAM", "PROHIBITED_ITEM", "HARASSMENT", "OTHER")
ACTION_TYPES = ("WARNING", "STRIKE", "CONTENT_REMOVAL")

_TARGET_COLLECTIONS = {
    "MEMBER": (lambda: db.store.members, "ERR_MEMBER_NOT_FOUND"),
    "GIFT_POST": (lambda: db.store.posts, "ERR_GIFT_POST_NOT_FOUND"),
    "CLAIM": (lambda: db.store.claims, "ERR_CLAIM_NOT_FOUND"),
    "CURB_ALERT": (lambda: db.store.alerts, "ERR_CURB_ALERT_NOT_FOUND"),
}


def _get_report(report_id):
    r = db.store.reports.get(report_id)
    if r is None:
        raise_err("ERR_REPORT_NOT_FOUND", "no report with the given id")
    return r


def _subject_of(report):
    """ModerationAction.member_id is derived from the report target."""
    if report["target_type"] == "MEMBER":
        return report["target_id"]
    if report["target_type"] == "GIFT_POST":
        post = db.store.posts.get(report["target_id"])
        return post["giver_id"] if post else None
    if report["target_type"] == "CLAIM":
        claim = db.store.claims.get(report["target_id"])
        return claim["claimer_id"] if claim else None
    if report["target_type"] == "CURB_ALERT":
        alert = db.store.alerts.get(report["target_id"])
        return alert["creator_id"] if alert else None
    return None


@bp.post("/v1/reports")
def create_report():
    role, uid = get_auth()
    require_role(role, ("Member",))
    body = get_body()
    fields = validate(body, {
        "group_id": (True, v_str),
        "target_type": (True, v_enum(*TARGET_TYPES)),
        "target_id": (True, v_str),
        "category": (True, v_enum(*REPORT_CATEGORIES)),
        "details": (False, v_str_empty_ok),
    })
    member = actor_member(role, uid)
    group = db.store.groups.get(fields["group_id"])
    if group is None:
        raise_err("ERR_GROUP_NOT_FOUND", "no group with the given id")
    get_collection, err_id = _TARGET_COLLECTIONS[fields["target_type"]]
    if fields["target_id"] not in get_collection():
        raise_err(err_id, "report target does not exist")
    require_active(member)
    _score, tier = group_health(group["id"])
    r = new_entity()
    r.update({
        "group_id": group["id"],
        "reporter_id": member["id"],
        "target_type": fields["target_type"],
        "target_id": fields["target_id"],
        "category": fields["category"],
        "details": fields["details"] if fields["details"] is not MISSING else "",
        "status": "OPEN",
        "reviewed_by": None,
        # sla_due_at is computed ONCE from the tier in effect at creation.
        "sla_due_at": r["created_at"] + timedelta(hours=SLA_HOURS[tier]),
        "resolved_at": None,
    })
    db.store.reports[r["id"]] = r
    return ok(ser_report(r), status=201)


@bp.get("/v1/reports/<report_id>")
def get_report(report_id):
    role, uid = get_auth()
    require_role(role, ("Member", "GroupModerator", "PlatformAdmin"))
    actor_member(role, uid)
    r = _get_report(report_id)
    # Restricted to the reporter, moderators of the group, and PlatformAdmin.
    if role == "Member" and r["reporter_id"] != uid:
        raise_err("ERR_UNAUTHORIZED", "only the reporter, a group moderator, or an admin may read the report")
    if role == "GroupModerator" and not is_moderator(uid, r["group_id"]):
        raise_err("ERR_UNAUTHORIZED", "actor does not moderate the report's group")
    return ok(ser_report(r))


@bp.get("/v1/reports")
def list_reports():
    role, uid = get_auth()
    require_role(role, ("GroupModerator", "PlatformAdmin"))
    group_id = request.args.get("group_id")
    if role == "GroupModerator":
        actor_member(role, uid)
        if group_id is not None:
            if not is_moderator(uid, group_id):
                raise_err("ERR_UNAUTHORIZED", "actor does not moderate the given group")
        else:
            if not any(
                ms["member_id"] == uid and ms["status"] == "APPROVED"
                and ms["role"] == "MODERATOR"
                for ms in db.store.memberships.values()
            ):
                raise_err("ERR_UNAUTHORIZED", "actor holds no moderator membership")
    items = list(db.store.reports.values())
    reporter_id = request.args.get("reporter_id")
    status = request.args.get("status")
    if group_id is not None:
        items = [r for r in items if r["group_id"] == group_id]
    if reporter_id is not None:
        items = [r for r in items if r["reporter_id"] == reporter_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, meta = paginate(items)
    return ok([ser_report(r) for r in page], response_type="array", pagination=meta)


@bp.post("/v1/reports/<report_id>/start-review")
def start_review(report_id):
    role, uid = get_auth()
    require_role(role, ("GroupModerator", "PlatformAdmin"))
    no_body_fields()
    if role == "GroupModerator":
        actor_member(role, uid)
    r = _get_report(report_id)
    require_group_moderator(role, uid, r["group_id"])
    if r["status"] != "OPEN":
        raise_err("ERR_REPORT_NOT_OPEN", "report is not in OPEN")
    r["status"] = "UNDER_REVIEW"
    r["reviewed_by"] = uid if uid else "platform_admin"
    touch(r)
    return ok(ser_report(r))


@bp.post("/v1/reports/<report_id>/resolve")
def resolve_report(report_id):
    role, uid = get_auth()
    require_role(role, ("GroupModerator", "PlatformAdmin"))
    body = get_body()
    fields = validate(body, {
        "resolution": (True, v_enum("DISMISS", "ACTION")),
        "action_type": (False, v_enum(*ACTION_TYPES)),
        "severity_points": (False, v_int(1, 3)),
        "rationale": (False, v_str_empty_ok),
    })
    resolution = fields["resolution"]
    action_type = fields["action_type"]
    severity_points = fields["severity_points"]
    rationale = fields["rationale"]
    if resolution == "ACTION":
        if action_type is MISSING or action_type is None:
            raise_err("ERR_VALIDATION", "action_type is required when resolution is ACTION")
        if action_type == "STRIKE" and (severity_points is MISSING or severity_points is None):
            raise_err("ERR_VALIDATION", "severity_points is required when action_type is STRIKE")
    if role == "GroupModerator":
        actor_member(role, uid)
    r = _get_report(report_id)
    require_group_moderator(role, uid, r["group_id"])
    if r["status"] != "UNDER_REVIEW":
        raise_err("ERR_REPORT_NOT_UNDER_REVIEW", "report is not in UNDER_REVIEW")
    if resolution == "ACTION" and action_type == "CONTENT_REMOVAL" and r["target_type"] != "GIFT_POST":
        raise_err("ERR_VALIDATION", "CONTENT_REMOVAL is valid only for GIFT_POST targets")

    if resolution == "DISMISS":
        r["status"] = "RESOLVED_DISMISSED"
        r["resolved_at"] = db.now()
        touch(r)
        return ok(ser_report(r))

    # resolution == ACTION: create the ModerationAction.
    subject_id = _subject_of(r)
    action = new_entity()
    action.update({
        "report_id": r["id"],
        "member_id": subject_id,
        "action_type": action_type,
        "severity_points": severity_points if action_type == "STRIKE" else None,
        "rationale": rationale if rationale is not MISSING else "",
        "status": "ACTIVE",
        "active_until": action["created_at"] + timedelta(days=90),
    })
    db.store.actions[action["id"]] = action

    if action_type == "STRIKE":
        add_event(subject_id, "STRIKE_APPLIED", -2 * severity_points)
        subject = db.store.members.get(subject_id)
        if subject is not None:
            recompute_strike_status(subject)
    elif action_type == "CONTENT_REMOVAL":
        post = db.store.posts.get(r["target_id"])
        if post is not None and post["status"] in ("DRAFT", "OPEN", "RESERVED"):
            withdraw_post(post)

    r["status"] = "RESOLVED_ACTION"
    r["resolved_at"] = db.now()
    touch(r)
    return ok(ser_report(r))
