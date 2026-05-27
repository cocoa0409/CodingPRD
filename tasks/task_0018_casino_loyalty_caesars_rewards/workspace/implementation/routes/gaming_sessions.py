"""GamingSession endpoints — drives tier accrual + velocity monitoring."""
from flask import Blueprint, request

import clock
import db
from auth import require_role
from common import (
    get_json_or_400, require_str, require_int, require_enum, require_iso_datetime,
    parse_pagination, paginate, stamp_create, stamp_audit_create, stamp_update,
    get_or_404, fk_or_404,
)
from errors import (
    ApiError, ERR_MEMBER_EXCLUDED, ERR_SESSION_INVALID_TIMES,
    ERR_SESSION_OVERLAP, ERR_SESSION_LOSS_OVER_CAP,
)
from response import success_object, success_array
from services.serializers import gaming_session_view
from services.calculations import (
    tier_credit_accrual, promote_tier, velocity_monitor,
)
from services.cascades import cascade_on_velocity_suspended


bp = Blueprint("gaming_sessions", __name__)

GAME_TYPES = {"SLOTS", "TABLE_GAMES", "POKER"}
SESSION_LOSS_CAP_CENTS = 100_000_000


@bp.route("/gaming-sessions", methods=["POST"])
def create_session():
    require_role({"MemberServices"})
    body = get_json_or_400()
    member_id = require_str(body, "member_id")
    property_id = require_str(body, "property_id")
    started_at_dt = require_iso_datetime(body, "started_at")
    ended_at_dt = require_iso_datetime(body, "ended_at")
    game_type = require_enum(body, "game_type", GAME_TYPES)
    theoretical_loss_cents = require_int(body, "theoretical_loss_cents", minimum=0)

    with db.lock:
        member = fk_or_404(db.members, member_id, "member")
        fk_or_404(db.properties, property_id, "property")

        # priority 6: exclusion gating
        if member["exclusion_status"] == "EXCLUDED":
            raise ApiError(ERR_MEMBER_EXCLUDED, 422,
                           "member is excluded; gaming session blocked")

        # priority 14: ended_at > started_at
        if not (ended_at_dt > started_at_dt):
            raise ApiError(ERR_SESSION_INVALID_TIMES, 422,
                           "ended_at must be strictly greater than started_at")

        # priority 20: regulatory single-session cap
        if theoretical_loss_cents > SESSION_LOSS_CAP_CENTS:
            raise ApiError(ERR_SESSION_LOSS_OVER_CAP, 422,
                           "theoretical_loss_cents exceeds regulatory cap")

        # priority 18: overlap with same member's existing RECORDED session on same property.
        # [started_at, ended_at) half-open; touching is allowed.
        for s in db.gaming_sessions.values():
            if s["member_id"] != member_id or s["property_id"] != property_id:
                continue
            if s["status"] != "RECORDED":
                continue
            existing_start = clock.parse_iso(s["started_at"])
            existing_end = clock.parse_iso(s["ended_at"])
            if (started_at_dt < existing_end) and (existing_start < ended_at_dt):
                raise ApiError(ERR_SESSION_OVERLAP, 409,
                               "session overlaps existing RECORDED session for member at property")

        # Capture tier BEFORE accrual side effects (per PRD §3.3).
        tier_before = member["tier_status"]
        earned = tier_credit_accrual(theoretical_loss_cents, game_type, tier_before)

        # Build session row first so velocity_monitor sees it.
        row = {
            "member_id": member_id,
            "property_id": property_id,
            "started_at": clock.iso(started_at_dt),
            "ended_at": clock.iso(ended_at_dt),
            "game_type": game_type,
            "theoretical_loss_cents": theoretical_loss_cents,
            "tier_credits_earned": earned,
            "status": "RECORDED",
        }
        stamp_create(row)
        db.gaming_sessions[row["id"]] = row

        # Update member totals.
        member["tier_credits_ytd"] = round(
            float(member["tier_credits_ytd"]) + float(earned), 2
        )
        member["tier_credits_lifetime"] = round(
            float(member["tier_credits_lifetime"]) + float(earned), 2
        )

        # Tier-promotion state machine — skipped if member is excluded
        # (but exclusion is already blocked above, this is belt-and-braces).
        if member["exclusion_status"] != "EXCLUDED":
            new_tier = promote_tier(member["tier_status"], member["tier_credits_ytd"])
            member["tier_status"] = new_tier

        # Single Member.version increment for the whole logical operation.
        stamp_update(member)

        # Velocity monitor — runs AFTER tier accrual.
        severity, total_cents, ws_iso, we_iso = velocity_monitor(
            member_id, row["ended_at"], db.gaming_sessions
        )
        if severity is not None:
            alert = {
                "member_id": member_id,
                "window_start": ws_iso,
                "window_end": we_iso,
                "total_theoretical_loss_cents": total_cents,
                "severity": severity,
            }
            stamp_audit_create(alert)
            db.velocity_alerts[alert["id"]] = alert

            # Drive velocity_status machine — only forward transitions on this path.
            current = member["velocity_status"]
            new_state = current
            if severity == "FLAGGED" and current == "NORMAL":
                new_state = "FLAGGED"
            elif severity == "SUSPENDED" and current in ("NORMAL", "FLAGGED"):
                new_state = "SUSPENDED"

            if new_state != current:
                member["velocity_status"] = new_state
                # Cascade booking cancellations BEFORE bumping member.version
                # so the cascade's stamp_update(member) is folded into one bump
                # — but per PRD each "touched entity gets its own version
                # increment". Use a second stamp_update for the velocity bump.
                if new_state == "SUSPENDED":
                    cascade_on_velocity_suspended(member)
                stamp_update(member)

        return success_object(gaming_session_view(row), 201)


@bp.route("/gaming-sessions/<sid>", methods=["GET"])
def get_session(sid):
    require_role({"MemberServices", "LoyaltyManager", "ComplianceOfficer"})
    with db.lock:
        row = get_or_404(db.gaming_sessions, sid, "gaming session")
        return success_object(gaming_session_view(row), 200)


@bp.route("/gaming-sessions", methods=["GET"])
def list_sessions():
    require_role({"MemberServices", "LoyaltyManager", "ComplianceOfficer"})
    member_id = request.args.get("member_id")
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    with db.lock:
        rows = list(db.gaming_sessions.values())
        if member_id is not None:
            rows = [r for r in rows if r["member_id"] == member_id]
        if property_id is not None:
            rows = [r for r in rows if r["property_id"] == property_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        rows.sort(key=lambda r: r["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array([gaming_session_view(r) for r in page], limit, offset, total, 200)
