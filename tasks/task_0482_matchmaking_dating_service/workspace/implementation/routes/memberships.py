import math
from datetime import timedelta

from flask import Blueprint

import errors
from db import db, new_id, iso_now_ms
from clock import clock
from middleware import authenticate, require_roles
from response import success_object, success_array
from services.common import (
    get_json_body, require_str, stamp_create, touch, parse_pagination, paginate,
    sort_by_created, parse_iso, add_months,
)
from services.compute import (
    serialize_membership, serialize_freeze, reconcile_member, reconcile_membership,
    term_end_for_member,
)
from services.transitions import cancel_membership

bp = Blueprint("memberships", __name__)

ALL_ROLES = ("BillingAdmin", "Matchmaker", "ScreeningOfficer", "Member")
OPERATOR_ROLES = ("BillingAdmin", "Matchmaker", "ScreeningOfficer")


def _get_member_or_404(member_id):
    m = db.members.get(member_id)
    if not m:
        raise errors.not_found("ERR_MEMBER_NOT_FOUND")
    return m


def _get_membership_or_404(membership_id):
    ms = db.memberships.get(membership_id)
    if not ms:
        raise errors.not_found("ERR_MEMBERSHIP_NOT_FOUND")
    return ms


# ---------------------------------------------------------------------------
# Membership activation
# ---------------------------------------------------------------------------
@bp.route("/members/<member_id>/memberships", methods=["POST"])
def activate_membership(member_id):
    principal = authenticate()
    require_roles(principal, ("BillingAdmin",))
    member = _get_member_or_404(member_id)
    body = get_json_body()
    plan_id = require_str(body, "plan_id")
    plan = db.membership_plans.get(plan_id)
    if not plan:
        raise errors.not_found("ERR_PLAN_NOT_FOUND")

    if member["screening_decision"] != "APPROVED":
        raise errors.conflict("ERR_MEMBER_NOT_APPROVED")
    if plan["archived"]:
        raise errors.unprocessable("ERR_PLAN_ARCHIVED")

    start = clock.now()
    base_end = add_months(start, plan["term_months"])
    mid = new_id()
    membership = {
        "id": mid,
        "member_id": member_id,
        "plan_id": plan_id,
        "start_at": iso_now_ms(start),
        "base_term_end_at": iso_now_ms(base_end),
        "guaranteed_introductions": plan["guaranteed_introductions"],
        "_term_months": plan["term_months"],
        "status": "ACTIVE",
        "refund_cents": 0,
    }
    stamp_create(membership)
    db.memberships[mid] = membership

    member["status"] = "ACTIVE"
    member["active_membership_id"] = mid
    touch(member)
    return success_object(serialize_membership(membership), 201)


@bp.route("/members/<member_id>/memberships", methods=["GET"])
def list_member_memberships(member_id):
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    from middleware import require_member_owner
    _get_member_or_404(member_id)
    require_member_owner(principal, member_id)
    limit, offset = parse_pagination()
    records = [m for m in db.memberships.values() if m["member_id"] == member_id]
    for m in records:
        reconcile_membership(m)
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return success_array([serialize_membership(m) for m in page], limit, offset, total)


@bp.route("/memberships/<membership_id>", methods=["GET"])
def get_membership(membership_id):
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    ms = _get_membership_or_404(membership_id)
    from middleware import require_member_owner
    require_member_owner(principal, ms["member_id"])
    reconcile_membership(ms)
    return success_object(serialize_membership(ms))


@bp.route("/memberships/<membership_id>/cancel", methods=["POST"])
def cancel_membership_route(membership_id):
    principal = authenticate()
    require_roles(principal, ("BillingAdmin",))
    ms = _get_membership_or_404(membership_id)
    reconcile_membership(ms)
    if ms["status"] not in ("ACTIVE", "FROZEN"):
        raise errors.conflict("ERR_MEMBERSHIP_NOT_CANCELLABLE")
    cancel_membership(ms)
    return success_object(serialize_membership(ms))


# ---------------------------------------------------------------------------
# Freezes
# ---------------------------------------------------------------------------
def _get_freeze_or_404(membership_id, freeze_id):
    f = db.freezes.get(freeze_id)
    if not f or f["membership_id"] != membership_id:
        raise errors.not_found("ERR_FREEZE_NOT_FOUND")
    return f


@bp.route("/memberships/<membership_id>/freezes", methods=["POST"])
def schedule_freeze(membership_id):
    principal = authenticate()
    require_roles(principal, ("BillingAdmin",))
    ms = _get_membership_or_404(membership_id)
    body = get_json_body()
    start_at = require_str(body, "start_at")
    end_at = require_str(body, "end_at")
    start_dt = parse_iso(start_at)
    end_dt = parse_iso(end_at)
    now = clock.now()
    if start_dt < now:
        raise errors.invalid_request("Freeze start_at must be >= clock now.")
    if end_dt <= start_dt:
        raise errors.invalid_request("Freeze end_at must be > start_at.")

    fid = new_id()
    freeze = {
        "id": fid,
        "membership_id": membership_id,
        "start_at": iso_now_ms(start_dt),
        "end_at": iso_now_ms(end_dt),
        "committed_days": None,
        "status": "SCHEDULED",
    }
    stamp_create(freeze)
    db.freezes[fid] = freeze

    # if start_at <= now, immediately ACTIVE -> Membership FROZEN, Member FROZEN
    if start_dt <= now:
        freeze["status"] = "ACTIVE"
        touch(freeze)
        if ms["status"] == "ACTIVE":
            ms["status"] = "FROZEN"
            touch(ms)
        member = db.members.get(ms["member_id"])
        if member and member["status"] == "ACTIVE":
            member["status"] = "FROZEN"
            touch(member)
    return success_object(serialize_freeze(freeze), 201)


@bp.route("/memberships/<membership_id>/freezes", methods=["GET"])
def list_freezes(membership_id):
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    ms = _get_membership_or_404(membership_id)
    from middleware import require_member_owner
    require_member_owner(principal, ms["member_id"])
    reconcile_membership(ms)
    limit, offset = parse_pagination()
    records = [f for f in db.freezes.values() if f["membership_id"] == membership_id]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return success_array([serialize_freeze(f) for f in page], limit, offset, total)


@bp.route("/memberships/<membership_id>/freezes/<freeze_id>/resume", methods=["POST"])
def resume_freeze(membership_id, freeze_id):
    principal = authenticate()
    require_roles(principal, ("BillingAdmin",))
    ms = _get_membership_or_404(membership_id)
    freeze = _get_freeze_or_404(membership_id, freeze_id)
    # lazily activate the freeze if its start has arrived
    reconcile_membership(ms)
    freeze = db.freezes[freeze_id]
    if freeze["status"] != "ACTIVE":
        raise errors.conflict("ERR_FREEZE_NOT_ACTIVE")

    now = clock.now()
    start_dt = parse_iso(freeze["start_at"])
    end_dt = parse_iso(freeze["end_at"])
    boundary = min(end_dt, now)
    seconds = (boundary - start_dt).total_seconds()
    committed_days = math.ceil(seconds / 86400.0) if seconds > 0 else 0
    freeze["committed_days"] = committed_days
    freeze["status"] = "RESUMED"
    touch(freeze)

    member = db.members.get(ms["member_id"])
    if member:
        member["frozen_days_total"] = member.get("frozen_days_total", 0) + committed_days
        if member["status"] == "FROZEN":
            member["status"] = "ACTIVE"
        touch(member)
    if ms["status"] == "FROZEN":
        ms["status"] = "ACTIVE"
        touch(ms)
    return success_object(serialize_freeze(freeze))


@bp.route("/memberships/<membership_id>/freezes/<freeze_id>/cancel", methods=["POST"])
def cancel_freeze(membership_id, freeze_id):
    principal = authenticate()
    require_roles(principal, ("BillingAdmin",))
    ms = _get_membership_or_404(membership_id)
    freeze = _get_freeze_or_404(membership_id, freeze_id)
    # lazily activate first so a now-active freeze cannot be cancelled
    reconcile_membership(ms)
    freeze = db.freezes[freeze_id]
    if freeze["status"] != "SCHEDULED":
        raise errors.conflict("ERR_FREEZE_NOT_CANCELLABLE")
    freeze["status"] = "CANCELLED"
    touch(freeze)
    return success_object(serialize_freeze(freeze))
