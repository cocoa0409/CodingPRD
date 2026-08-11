"""Reference data routes: membership-categories, chapters, renewal-cycle-policies."""
from flask import Blueprint, request

import db
import errors
import middleware
from response import success
from services import lifecycle

bp = Blueprint("reference", __name__)


def _body():
    return request.get_json(silent=True) or {}


@bp.post("/api/membership-categories")
def create_category():
    middleware.require_roles("DuesAdministrator")
    b = _body()
    # uniqueness: code
    for c in db.membership_categories.values():
        if c["code"] == b.get("code"):
            raise errors.ApiError(errors.ERR_DUPLICATE_CATEGORY_CODE,
                                  "Category with code already exists", 409)
    c = lifecycle.new_entity({
        "code": b.get("code"),
        "name": b.get("name"),
        "is_voting": bool(b.get("is_voting", False)),
        "is_directory_eligible": bool(b.get("is_directory_eligible", False)),
        "allows_auto_renew": bool(b.get("allows_auto_renew", False)),
        "lapse_grace_days": int(b.get("lapse_grace_days", 0)),
        "reinstatement_window_days": int(b.get("reinstatement_window_days", 0)),
        "status": "ACTIVE",
    })
    db.membership_categories[c["id"]] = c
    return success(lifecycle.category_out(c), status=201)


@bp.get("/api/membership-categories/<cid>")
def get_category(cid):
    middleware.require_roles("DuesAdministrator", "MembershipAdministrator", "Member")
    c = db.membership_categories.get(cid)
    if not c:
        raise errors.not_found()
    return success(lifecycle.category_out(c))


@bp.post("/api/chapters")
def create_chapter():
    middleware.require_roles("DuesAdministrator")
    b = _body()
    c = lifecycle.new_entity({
        "code": b.get("code"),
        "name": b.get("name"),
        "is_affiliate": bool(b.get("is_affiliate", False)),
        "status": "ACTIVE",
    })
    db.chapters[c["id"]] = c
    return success(lifecycle.chapter_out(c), status=201)


@bp.get("/api/chapters/<cid>")
def get_chapter(cid):
    middleware.require_roles("DuesAdministrator", "MembershipAdministrator", "Member")
    c = db.chapters.get(cid)
    if not c:
        raise errors.not_found()
    return success(lifecycle.chapter_out(c))


@bp.post("/api/renewal-cycle-policies")
def create_policy():
    middleware.require_roles("DuesAdministrator")
    b = _body()
    p = lifecycle.new_entity({
        "code": b.get("code"),
        "mode": b.get("mode"),
        "calendar_anchor_month": b.get("calendar_anchor_month"),
        "calendar_anchor_day": b.get("calendar_anchor_day"),
        "proration_method": b.get("proration_method"),
        "status": "ACTIVE",
    })
    db.renewal_cycle_policies[p["id"]] = p
    return success(lifecycle.policy_out(p), status=201)


@bp.get("/api/renewal-cycle-policies/<pid>")
def get_policy(pid):
    middleware.require_roles("DuesAdministrator", "MembershipAdministrator")
    p = db.renewal_cycle_policies.get(pid)
    if not p:
        raise errors.not_found()
    return success(lifecycle.policy_out(p))
