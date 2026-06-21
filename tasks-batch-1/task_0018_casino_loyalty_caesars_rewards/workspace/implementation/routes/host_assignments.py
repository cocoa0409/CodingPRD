"""HostAssignment endpoints."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (
    get_json_or_400, require_str, require_int, parse_pagination, paginate,
    stamp_create, stamp_update, get_or_404, fk_or_404,
)
from errors import (
    ApiError,
    ERR_INVALID_STATE, ERR_STALE_MEMBER_VERSION, ERR_MEMBER_EXCLUDED,
    ERR_SOD_VIOLATION, ERR_ACTIVE_HOST_EXISTS,
)
from response import success_object, success_array
from services.serializers import host_assignment_view


bp = Blueprint("host_assignments", __name__)


@bp.route("/host-assignments", methods=["POST"])
def create_host_assignment():
    uid, _ = require_role({"LoyaltyManager"})
    body = get_json_or_400()
    member_id = require_str(body, "member_id")
    host_id = require_str(body, "host_id")
    expected_member_version = require_int(body, "expected_member_version", minimum=0)

    with db.lock:
        member = fk_or_404(db.members, member_id, "member")
        host = fk_or_404(db.hosts, host_id, "host")

        # priority 5: OCC check on Member.version
        if expected_member_version != member["version"]:
            raise ApiError(ERR_STALE_MEMBER_VERSION, 412,
                           "expected_member_version does not match Member.version")

        # priority 6: exclusion gating
        if member["exclusion_status"] == "EXCLUDED":
            raise ApiError(ERR_MEMBER_EXCLUDED, 422,
                           "member is excluded; host assignment blocked")

        # host must exist; per scaffold not gated to ACTIVE at /create.
        _ = host  # FK only here; ACTIVE check is enforced at /approve

        row = {
            "member_id": member_id,
            "host_id": host_id,
            "assigned_by_user_id": uid,
            "approved_by_user_id": None,
            "status": "PENDING_APPROVAL",
        }
        stamp_create(row)
        db.host_assignments[row["id"]] = row

        stamp_update(member)
        return success_object(host_assignment_view(row), 201)


@bp.route("/host-assignments/<aid>/approve", methods=["POST"])
def approve_host_assignment(aid):
    uid, _ = require_role({"LoyaltyManager"})
    with db.lock:
        a = get_or_404(db.host_assignments, aid, "host assignment")

        # priority 4: state precondition
        if a["status"] != "PENDING_APPROVAL":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "host assignment is not in PENDING_APPROVAL")

        # FKs were validated at create; re-resolve for cross-entity checks.
        member = db.members.get(a["member_id"])
        host = db.hosts.get(a["host_id"])

        # priority 6: exclusion
        if member is not None and member["exclusion_status"] == "EXCLUDED":
            raise ApiError(ERR_MEMBER_EXCLUDED, 422,
                           "member is excluded; cannot approve host assignment")

        # priority 9: segregation of duties — approver != creator
        if uid == a["assigned_by_user_id"]:
            raise ApiError(ERR_SOD_VIOLATION, 422,
                           "approver must differ from creator")

        # Host must be ACTIVE (state precondition, cross-entity).
        if host is None or host["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409, "host is not ACTIVE")

        # priority 10: no other ACTIVE HostAssignment for this member.
        for other in db.host_assignments.values():
            if other["id"] == a["id"]:
                continue
            if other["member_id"] == a["member_id"] and other["status"] == "ACTIVE":
                raise ApiError(ERR_ACTIVE_HOST_EXISTS, 422,
                               "member already has an active host assignment")

        a["status"] = "ACTIVE"
        a["approved_by_user_id"] = uid
        stamp_update(a)

        if member is not None:
            member["assigned_host_id"] = a["host_id"]
            stamp_update(member)
        return success_object(host_assignment_view(a), 200)


@bp.route("/host-assignments/<aid>/reject", methods=["POST"])
def reject_host_assignment(aid):
    uid, _ = require_role({"LoyaltyManager"})
    with db.lock:
        a = get_or_404(db.host_assignments, aid, "host assignment")

        if a["status"] != "PENDING_APPROVAL":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "host assignment is not in PENDING_APPROVAL")

        if uid == a["assigned_by_user_id"]:
            raise ApiError(ERR_SOD_VIOLATION, 422,
                           "rejecter must differ from creator")

        a["status"] = "REJECTED"
        stamp_update(a)
        return success_object(host_assignment_view(a), 200)


@bp.route("/host-assignments/<aid>/revoke", methods=["POST"])
def revoke_host_assignment(aid):
    require_role({"LoyaltyManager", "ComplianceOfficer"})
    with db.lock:
        a = get_or_404(db.host_assignments, aid, "host assignment")
        if a["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "host assignment is not ACTIVE")
        a["status"] = "REVOKED"
        stamp_update(a)

        member = db.members.get(a["member_id"])
        if member is not None and member.get("assigned_host_id") == a["host_id"]:
            member["assigned_host_id"] = None
            stamp_update(member)
        return success_object(host_assignment_view(a), 200)


@bp.route("/host-assignments/<aid>", methods=["GET"])
def get_host_assignment(aid):
    require_role({"LoyaltyManager", "ComplianceOfficer"})
    with db.lock:
        row = get_or_404(db.host_assignments, aid, "host assignment")
        return success_object(host_assignment_view(row), 200)


@bp.route("/host-assignments", methods=["GET"])
def list_host_assignments():
    require_role({"LoyaltyManager", "ComplianceOfficer"})
    member_id = request.args.get("member_id")
    host_id = request.args.get("host_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    with db.lock:
        rows = list(db.host_assignments.values())
        if member_id is not None:
            rows = [r for r in rows if r["member_id"] == member_id]
        if host_id is not None:
            rows = [r for r in rows if r["host_id"] == host_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        rows.sort(key=lambda r: r["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array([host_assignment_view(r) for r in page], limit, offset, total, 200)
