"""Alert routes."""

from flask import Blueprint, request

import db
import errors
import services.core as svc
from middleware import require_roles, get_auth
from response import success_object, success_list
from routes.watch_groups import _pagination

bp = Blueprint("alerts", __name__)

ALL_ROLES = ("ProgramCoordinator", "LiaisonOfficer", "BlockCaptain", "Member")

VALID_KINDS = {"INCIDENT_BULLETIN", "MEETING_NOTICE", "EVENT_NOTICE", "SAFETY_TIP"}
VALID_SCOPES = {"BLOCK", "GROUP"}


def _serialize_alert(a):
    return {
        "id": a["id"],
        "watch_group_id": a["watch_group_id"],
        "origin_incident_id": a.get("origin_incident_id"),
        "alert_kind": a["alert_kind"],
        "audience_scope": a["audience_scope"],
        "target_block_id": a.get("target_block_id"),
        "distribution_status": a["distribution_status"],
        "ack_posture": a["ack_posture"],
        "scheduled_send_at": a["scheduled_send_at"],
        "recipient_count": a["recipient_count"],
        "ack_count": a["ack_count"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.route("/watch/alerts", methods=["POST"])
def create_alert():
    user_id, role = require_roles("ProgramCoordinator", "BlockCaptain")
    body = request.get_json(force=True, silent=True) or {}

    watch_group_id = body.get("watch_group_id")
    alert_kind = body.get("alert_kind")
    audience_scope = body.get("audience_scope")
    scheduled_send_at = body.get("scheduled_send_at")
    expected_wg_version = body.get("expected_watch_group_version")
    target_block_id = body.get("target_block_id")
    origin_incident_id = body.get("origin_incident_id")

    # Field-level validation
    if not alert_kind or alert_kind not in VALID_KINDS:
        raise errors.invalid_request("Invalid alert_kind")
    if not audience_scope or audience_scope not in VALID_SCOPES:
        raise errors.invalid_request("Invalid audience_scope")
    if not scheduled_send_at:
        raise errors.invalid_request("scheduled_send_at is required")
    try:
        sched_dt = db.parse_iso(scheduled_send_at)
    except Exception:
        raise errors.invalid_request("scheduled_send_at is not valid ISO-8601")
    if expected_wg_version is None:
        raise errors.invalid_request("expected_watch_group_version is required")

    # BLOCK scope requires target_block_id; GROUP scope forbids it
    if audience_scope == "BLOCK" and not target_block_id:
        raise errors.invalid_request("target_block_id is required for BLOCK scope")
    if audience_scope == "GROUP" and target_block_id:
        raise errors.invalid_request("target_block_id is forbidden for GROUP scope")

    # INCIDENT_BULLETIN requires origin_incident_id
    if alert_kind == "INCIDENT_BULLETIN" and not origin_incident_id:
        raise errors.invalid_request("origin_incident_id is required for INCIDENT_BULLETIN")

    # Existence
    g = db.watch_groups.get(watch_group_id) if watch_group_id else None
    if not g:
        raise errors.not_found("WatchGroup not found")

    # OCC check
    if expected_wg_version != g["version"]:
        raise errors.stale_version(
            f"WatchGroup version mismatch: expected {expected_wg_version}, current {g['version']}"
        )

    # Posture gate: FROZEN rejects alert writes. Per PRD §3.4 the posture gate
    # guards queueing and sending, not drafting — the NO_ACTIVE_CAPTAIN check
    # below must surface at creation instead of being masked by a posture gate.
    if g["posture"] == "FROZEN":
        raise errors.posture_gated("Alert creation rejected while group is FROZEN")

    # Referential integrity for BLOCK scope
    if audience_scope == "BLOCK":
        tb = db.blocks.get(target_block_id)
        if not tb:
            raise errors.not_found("Target block not found")
        if tb["watch_group_id"] != watch_group_id:
            raise errors.referential("Target block does not belong to the watch group")

        # NO_ACTIVE_CAPTAIN check at creation
        active_captains = [ca for ca in db.captain_assignments.values()
                           if ca["block_id"] == target_block_id and ca["assignment_status"] == "ACTIVE"]
        if len(active_captains) != 1:
            raise errors.no_active_captain()

    # Referential integrity for origin incident
    if origin_incident_id:
        ir = db.incident_reports.get(origin_incident_id)
        if not ir:
            raise errors.not_found("Origin incident not found")

    # Quiet hours check
    if alert_kind != "INCIDENT_BULLETIN" and svc.is_quiet_hours(sched_dt):
        raise errors.quiet_hours()

    record = {
        "watch_group_id": watch_group_id,
        "origin_incident_id": origin_incident_id,
        "alert_kind": alert_kind,
        "audience_scope": audience_scope,
        "target_block_id": target_block_id,
        "distribution_status": "DRAFT",
        "ack_posture": "UNTRACKED",
        "scheduled_send_at": scheduled_send_at,
        "recipient_count": 0,
        "ack_count": 0,
        "_printed_flyers": 0,  # internal tracking for recall compensation
    }
    svc.stamp_new(record)
    db.alerts[record["id"]] = record
    db.alert_acks[record["id"]] = set()
    return success_object(_serialize_alert(record), 201)


@bp.route("/watch/alerts", methods=["GET"])
def list_alerts():
    user_id, role = require_roles(*ALL_ROLES)

    items = list(db.alerts.values())

    # Filters
    wg = request.args.get("watch_group_id")
    if wg:
        items = [a for a in items if a["watch_group_id"] == wg]
    oi = request.args.get("origin_incident_id")
    if oi:
        items = [a for a in items if a.get("origin_incident_id") == oi]
    tb = request.args.get("target_block_id")
    if tb:
        items = [a for a in items if a.get("target_block_id") == tb]
    ds = request.args.get("distribution_status")
    if ds:
        items = [a for a in items if a["distribution_status"] == ds]
    ak = request.args.get("alert_kind")
    if ak:
        items = [a for a in items if a["alert_kind"] == ak]

    items.sort(key=lambda a: a["created_at"])
    limit, offset = _pagination()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list([_serialize_alert(a) for a in items], limit, offset, total)


@bp.route("/watch/alerts/<id>", methods=["GET"])
def get_alert(id):
    user_id, role = require_roles(*ALL_ROLES)
    a = db.alerts.get(id)
    if not a:
        raise errors.not_found("Alert not found")
    return success_object(_serialize_alert(a))


@bp.route("/watch/alerts/<id>/queue", methods=["POST"])
def queue_alert(id):
    user_id, role = require_roles("ProgramCoordinator", "BlockCaptain")
    a = db.alerts.get(id)
    if not a:
        raise errors.not_found("Alert not found")

    if a["distribution_status"] != "DRAFT":
        raise errors.invalid_state("Alert is not DRAFT")

    # Posture gate: must be OPERATIONAL
    g = db.watch_groups.get(a["watch_group_id"])
    if not g:
        raise errors.not_found("WatchGroup not found")
    if g["posture"] != "OPERATIONAL":
        raise errors.posture_gated(f"Queue requires posture OPERATIONAL, got {g['posture']}")

    # INCIDENT_BULLETIN: origin incident must be CORROBORATED or CLEARED
    if a["alert_kind"] == "INCIDENT_BULLETIN":
        ir = db.incident_reports.get(a.get("origin_incident_id"))
        if not ir or ir["review_status"] not in ("CORROBORATED", "CLEARED"):
            raise errors.invalid_state("Origin incident must be CORROBORATED or CLEARED")

    # BLOCK scope: target block must be REGISTERED with exactly one ACTIVE captain
    if a["audience_scope"] == "BLOCK":
        tb = db.blocks.get(a.get("target_block_id"))
        if not tb:
            raise errors.not_found("Target block not found")
        if tb["registration_status"] != "REGISTERED":
            raise errors.invalid_state("Target block is not REGISTERED")
        active_captains = [ca for ca in db.captain_assignments.values()
                           if ca["block_id"] == tb["id"] and ca["assignment_status"] == "ACTIVE"]
        if len(active_captains) != 1:
            raise errors.no_active_captain()

    a["distribution_status"] = "QUEUED"
    svc.touch(a)
    return success_object(_serialize_alert(a))


@bp.route("/watch/alerts/<id>/send", methods=["POST"])
def send_alert(id):
    user_id, role = require_roles("ProgramCoordinator")
    a = db.alerts.get(id)
    if not a:
        raise errors.not_found("Alert not found")

    if a["distribution_status"] != "QUEUED":
        raise errors.invalid_state("Alert is not QUEUED")

    # Posture gate
    g = db.watch_groups.get(a["watch_group_id"])
    if not g:
        raise errors.not_found("WatchGroup not found")
    if g["posture"] != "OPERATIONAL":
        raise errors.posture_gated(f"Send requires posture OPERATIONAL, got {g['posture']}")

    # Scheduled time check
    sched_dt = db.parse_iso(a["scheduled_send_at"])
    clock = db.get_clock()
    if clock < sched_dt:
        raise errors.invalid_state("Cannot send before scheduled_send_at")

    # Quiet hours
    if a["alert_kind"] != "INCIDENT_BULLETIN" and svc.is_quiet_hours(clock):
        raise errors.quiet_hours()

    # Compute fanout
    recipient_count, printed_flyers = svc.compute_fanout(a)
    a["recipient_count"] = recipient_count
    a["_printed_flyers"] = printed_flyers
    a["distribution_status"] = "SENT"
    svc.touch(a)

    # Materials ledger
    g["materials_inventory_count"] += printed_flyers
    svc.touch(g)

    return success_object(_serialize_alert(a))


@bp.route("/watch/alerts/<id>/unqueue", methods=["POST"])
def unqueue_alert(id):
    user_id, role = require_roles("ProgramCoordinator")
    a = db.alerts.get(id)
    if not a:
        raise errors.not_found("Alert not found")

    if a["distribution_status"] != "QUEUED":
        raise errors.invalid_state("Alert is not QUEUED")

    a["distribution_status"] = "DRAFT"
    svc.touch(a)
    return success_object(_serialize_alert(a))


@bp.route("/watch/alerts/<id>/recall", methods=["POST"])
def recall_alert(id):
    user_id, role = require_roles("ProgramCoordinator")
    a = db.alerts.get(id)
    if not a:
        raise errors.not_found("Alert not found")

    if a["distribution_status"] != "SENT":
        raise errors.invalid_state("Alert is not SENT")

    # Compensating: decrement materials by the same flyer quantity
    g = db.watch_groups.get(a["watch_group_id"])
    flyers = a.get("_printed_flyers", 0)
    if g:
        g["materials_inventory_count"] = max(0, g["materials_inventory_count"] - flyers)
        svc.touch(g)

    a["distribution_status"] = "RECALLED"
    # ack_posture frozen at current value — don't recompute
    svc.touch(a)
    return success_object(_serialize_alert(a))


@bp.route("/watch/alerts/<id>/ack", methods=["POST"])
def ack_alert(id):
    user_id, role = require_roles("Member", "BlockCaptain")
    a = db.alerts.get(id)
    if not a:
        raise errors.not_found("Alert not found")

    body = request.get_json(force=True, silent=True) or {}
    member_id = body.get("member_id")
    if not member_id:
        raise errors.invalid_request("member_id is required")

    # Verify member exists
    m = db.members.get(member_id)
    if not m:
        raise errors.not_found("Member not found")

    # Idempotent check: duplicate ack from same member
    acks = db.alert_acks.get(id, set())
    if member_id in acks:
        raise errors.constraint_violation("Member has already acknowledged this alert")

    acks.add(member_id)
    db.alert_acks[id] = acks
    a["ack_count"] = len(acks)
    svc.recompute_ack_posture(a)
    svc.touch(a)

    return success_object(_serialize_alert(a))
