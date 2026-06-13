"""Test-driving / operational endpoints: clock, payment settle, batch jobs."""
from flask import Blueprint

import clock
import db
import serializers as S
from errors import invalid_request, invalid_state
from middleware import get_identity, require_role
from response import ok
from routes.helpers import resolve
from services import membership_svc
from timeutil import parse_iso
import validate as V

bp = Blueprint("jobs", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_identity()
    require_role(role, {"MembershipAdmin"})
    body = V.get_body()
    to_iso = V.require_str(body, "to_iso8601")
    dt = parse_iso(to_iso)
    clock.set_now(dt)
    from timeutil import format_iso
    return ok({"now": format_iso(dt)})


@bp.post("/_payments/settle")
def settle_payment():
    _, role = get_identity()
    require_role(role, {"MembershipAdmin"})
    body = V.get_body()
    target = V.require_enum(body, "target", {"MEMBERSHIP"})
    membership_id = V.require_str(body, "membership_id")
    outcome = V.require_enum(body, "outcome", {"SUCCEEDED", "FAILED"})
    membership = resolve(db.memberships, membership_id)
    if outcome == "SUCCEEDED":
        membership_svc.activate(membership)
    return ok(S.membership(db.public(membership)))


@bp.post("/_jobs/run_renewals")
def run_renewals():
    _, role = get_identity()
    require_role(role, {"MembershipAdmin"})
    now = clock.now()
    renewed_ids = []
    # Snapshot candidates first (renewal mints passes but does not add memberships).
    candidates = [
        m for m in db.memberships.values()
        if m["status"] == "ACTIVE" and m.get("auto_renew")
        and m.get("expires_at") and parse_iso(m["expires_at"]) <= now
    ]
    candidates.sort(key=lambda m: (m.get("created_at"), m.get("_seq", 0)))
    for m in candidates:
        membership_svc.auto_renew_one(m)
        renewed_ids.append(m["id"])
    return ok({"renewed_count": len(renewed_ids), "renewed_membership_ids": renewed_ids})


@bp.post("/_jobs/run_expirations")
def run_expirations():
    _, role = get_identity()
    require_role(role, {"MembershipAdmin"})
    now = clock.now()
    graced = 0
    expired = 0
    # ACTIVE + !auto_renew past expires_at -> GRACE.
    active_due = [
        m for m in db.memberships.values()
        if m["status"] == "ACTIVE" and not m.get("auto_renew")
        and m.get("expires_at") and parse_iso(m["expires_at"]) <= now
    ]
    active_due.sort(key=lambda m: (m.get("created_at"), m.get("_seq", 0)))
    for m in active_due:
        membership_svc.to_grace(m)
        graced += 1
    # GRACE past grace_until -> EXPIRED.
    grace_due = [
        m for m in db.memberships.values()
        if m["status"] == "GRACE"
        and m.get("grace_until") and parse_iso(m["grace_until"]) < now
    ]
    grace_due.sort(key=lambda m: (m.get("created_at"), m.get("_seq", 0)))
    for m in grace_due:
        membership_svc.to_expired(m)
        expired += 1
    return ok({"graced_count": graced, "expired_count": expired})
