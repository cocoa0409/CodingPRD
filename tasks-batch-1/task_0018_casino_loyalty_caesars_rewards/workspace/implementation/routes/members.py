"""Member endpoints."""
from flask import Blueprint, request

import clock
import db
from auth import require_role
from common import (
    get_json_or_400, require_str, require_int, parse_pagination, paginate,
    stamp_create, stamp_update, get_or_404, fk_or_404,
)
from errors import (
    ApiError, ERR_EMAIL_TAKEN, ERR_INVALID_STATE, ERR_STALE_MEMBER_VERSION,
)
from response import success_object, success_array
from services.serializers import member_view


bp = Blueprint("members", __name__)


@bp.route("/members", methods=["POST"])
def create_member():
    require_role({"MemberServices"})
    body = get_json_or_400()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email", max_len=254)
    home_property_id = require_str(body, "home_property_id")

    with db.lock:
        fk_or_404(db.properties, home_property_id, "property")
        normalized = email.casefold()
        for m in db.members.values():
            if m["email"].casefold() == normalized:
                raise ApiError(ERR_EMAIL_TAKEN, 409, "email already in use")
        row = {
            "full_name": full_name,
            "email": email,
            "home_property_id": home_property_id,
            "tier_status": "GOLD",
            "tier_credits_ytd": 0,
            "tier_credits_lifetime": 0,
            "exclusion_status": "NOT_EXCLUDED",
            "velocity_status": "NORMAL",
            "assigned_host_id": None,
        }
        stamp_create(row)
        db.members[row["id"]] = row
    return success_object(member_view(row), 201)


@bp.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    uid, role = require_role({"MemberServices", "LoyaltyManager", "ComplianceOfficer", "Member"})
    with db.lock:
        row = get_or_404(db.members, mid, "member")
        if role == "Member" and uid != mid:
            # Ownership check — Member can only access their own row.
            from errors import ERR_UNAUTHORIZED
            raise ApiError(ERR_UNAUTHORIZED, 403, "members may only read their own row")
        return success_object(member_view(row), 200)


@bp.route("/members", methods=["GET"])
def list_members():
    require_role({"MemberServices", "LoyaltyManager", "ComplianceOfficer"})
    home_property_id = request.args.get("home_property_id")
    tier_status = request.args.get("tier_status")
    exclusion_status = request.args.get("exclusion_status")
    velocity_status = request.args.get("velocity_status")
    assigned_host_id = request.args.get("assigned_host_id")
    limit, offset = parse_pagination()
    with db.lock:
        rows = list(db.members.values())
        if home_property_id is not None:
            rows = [r for r in rows if r["home_property_id"] == home_property_id]
        if tier_status is not None:
            rows = [r for r in rows if r["tier_status"] == tier_status]
        if exclusion_status is not None:
            rows = [r for r in rows if r["exclusion_status"] == exclusion_status]
        if velocity_status is not None:
            rows = [r for r in rows if r["velocity_status"] == velocity_status]
        if assigned_host_id is not None:
            rows = [r for r in rows if r.get("assigned_host_id") == assigned_host_id]
        rows.sort(key=lambda r: r["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array([member_view(r) for r in page], limit, offset, total, 200)


@bp.route("/members/<mid>/clear-velocity", methods=["POST"])
def clear_velocity(mid):
    require_role({"ComplianceOfficer"})
    body = get_json_or_400()
    expected_version = require_int(body, "expected_member_version", minimum=0)

    with db.lock:
        m = get_or_404(db.members, mid, "member")

        # state-machine eligibility (priority 4)
        if m["velocity_status"] != "SUSPENDED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "member is not in velocity SUSPENDED state")

        # OCC check (priority 5)
        if expected_version != m["version"]:
            raise ApiError(ERR_STALE_MEMBER_VERSION, 412,
                           "expected_member_version does not match Member.version")

        # 24h precondition: most recent alert window_end must be older than now - 24h.
        from datetime import timedelta
        now = clock.now()
        threshold = now - timedelta(hours=24)
        latest = _latest_velocity_alert_window_end(mid)
        if latest is None or latest >= threshold:
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot clear: recent velocity alert within 24h")

        m["velocity_status"] = "NORMAL"
        stamp_update(m)
        return success_object(member_view(m), 200)


def _latest_velocity_alert_window_end(member_id: str):
    """Return the most recent VelocityAlert.window_end (datetime) for the member, or None."""
    latest = None
    for a in db.velocity_alerts.values():
        if a["member_id"] != member_id:
            continue
        end = clock.parse_iso(a["window_end"])
        if latest is None or end > latest:
            latest = end
    return latest
