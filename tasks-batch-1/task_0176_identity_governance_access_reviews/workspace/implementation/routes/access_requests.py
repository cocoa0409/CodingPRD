"""Access request routes (PRD §3.3, §3.4).

Cyclic workflow DRAFT -> SUBMITTED <-> RETURNED -> APPROVED|REJECTED.
SoD self-action checks, dual approval, SoD conflict gates, and the depth-3
approval cascade (create+activate one grant per role entitlement).
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, optional_string, optional_bool,
    parse_pagination, paginate, filter_enum_param,
)
from services import domain

bp = Blueprint("access_requests", __name__)

READ_ROLES = {"AccessManager", "AccessApprover"}
STATUS_VALUES = {"DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "REJECTED"}


def _serialize_request(record):
    return serialize(record)


@bp.route("/access-requests", methods=["POST"])
def create_access_request():
    user_id, _ = require_role({"AccessManager"})
    body = get_json_body()
    identity_id = require_string(body, "identity_id")
    role_id = require_string(body, "role_id")
    justification = require_string(body, "justification")
    sod_override = optional_string(body, "sod_override_justification")

    with db.LOCK:
        if db.identities.get(identity_id) is None:
            raise err(errors.ERR_NOT_FOUND, "Identity not found")
        if db.roles.get(role_id) is None:
            raise err(errors.ERR_NOT_FOUND, "Role not found")

        common = db.new_common()
        record = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "identity_id": identity_id,
            "role_id": role_id,
            "justification": justification,
            "requester_user_id": user_id,
            "sod_override_justification": sod_override,
            "status": "DRAFT",
            "decided_by_user_id": None,
            "sod_conflict_detected": False,
        }
        db.access_requests[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/access-requests/<id>", methods=["GET"])
def get_access_request(id):
    require_role(READ_ROLES)
    with db.LOCK:
        record = db.access_requests.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Access request not found")
        return object_response(serialize(record), 200)


@bp.route("/access-requests", methods=["GET"])
def list_access_requests():
    require_role(READ_ROLES)
    identity_id = request.args.get("identity_id")
    role_id = request.args.get("role_id")
    status = filter_enum_param(request.args, "status", STATUS_VALUES)
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.access_requests.values())
        if identity_id is not None:
            records = [r for r in records if r["identity_id"] == identity_id]
        if role_id is not None:
            records = [r for r in records if r["role_id"] == role_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/access-requests/<id>/submit", methods=["POST"])
def submit_access_request(id):
    require_role({"AccessManager"})
    with db.LOCK:
        ar = db.access_requests.get(id)
        if ar is None:
            raise err(errors.ERR_NOT_FOUND, "Access request not found")
        if ar["status"] not in ("DRAFT", "RETURNED"):
            raise err(errors.ERR_INVALID_STATE, "Request is not DRAFT or RETURNED")

        from_draft = ar["status"] == "DRAFT"
        identity = db.identities.get(ar["identity_id"])
        role = db.roles.get(ar["role_id"])

        # Preconditions: identity ACTIVE, role ACTIVE, (first submit) entitlements ACTIVE.
        if identity is None or identity["status"] != "ACTIVE":
            raise err(errors.ERR_IDENTITY_NOT_ACTIVE, "Target identity is not ACTIVE")
        if role is None or role["status"] != "ACTIVE":
            raise err(errors.ERR_ROLE_RETIRED, "Requested role is not ACTIVE")
        if from_draft:
            for eid in role.get("entitlement_ids", []):
                ent = db.entitlements.get(eid)
                if ent is None or ent["status"] != "ACTIVE":
                    raise err(errors.ERR_ENTITLEMENT_ARCHIVED,
                              "A bundled entitlement is not ACTIVE")

        # Side effects: recompute sod_conflict_detected; advance state; then
        # recompute projected risk (now includes this SUBMITTED request).
        detected, _hard, _soft = domain.evaluate_sod(ar["identity_id"], role)
        ar["sod_conflict_detected"] = detected
        ar["status"] = "SUBMITTED"
        db.touch(ar)
        domain.recompute_projected_only(identity)
        return object_response(serialize(ar), 200)


@bp.route("/access-requests/<id>/return", methods=["POST"])
def return_access_request(id):
    user_id, _ = require_role({"AccessApprover"})
    with db.LOCK:
        ar = db.access_requests.get(id)
        if ar is None:
            raise err(errors.ERR_NOT_FOUND, "Access request not found")
        if ar["status"] != "SUBMITTED":
            raise err(errors.ERR_INVALID_STATE, "Request is not SUBMITTED")
        if user_id == ar["requester_user_id"]:
            raise err(errors.ERR_SOD_SELF_ACTION,
                      "Approver may not be the request's requester")
        ar["status"] = "RETURNED"
        db.touch(ar)
        identity = db.identities.get(ar["identity_id"])
        if identity is not None:
            domain.recompute_projected_only(identity)
        return object_response(serialize(ar), 200)


@bp.route("/access-requests/<id>/reject", methods=["POST"])
def reject_access_request(id):
    user_id, _ = require_role({"AccessApprover"})
    with db.LOCK:
        ar = db.access_requests.get(id)
        if ar is None:
            raise err(errors.ERR_NOT_FOUND, "Access request not found")
        if ar["status"] != "SUBMITTED":
            raise err(errors.ERR_INVALID_STATE, "Request is not SUBMITTED")
        if user_id == ar["requester_user_id"]:
            raise err(errors.ERR_SOD_SELF_ACTION,
                      "Approver may not be the request's requester")
        ar["status"] = "REJECTED"
        ar["decided_by_user_id"] = user_id
        db.touch(ar)
        identity = db.identities.get(ar["identity_id"])
        domain.append_audit(ar["identity_id"], "REQUEST_REJECTED", user_id,
                            "Access request %s rejected" % id)
        if identity is not None:
            domain.recompute_projected_only(identity)
        return object_response(serialize(ar), 200)


@bp.route("/access-requests/<id>/approve", methods=["POST"])
def approve_access_request(id):
    user_id, _ = require_role({"AccessApprover"})
    body = get_json_body()
    second_confirmed = optional_bool(body, "second_approver_confirmed", False)
    override_just = optional_string(body, "sod_override_justification")

    with db.LOCK:
        ar = db.access_requests.get(id)
        if ar is None:
            raise err(errors.ERR_NOT_FOUND, "Access request not found")
        # 1. State gate.
        if ar["status"] != "SUBMITTED":
            raise err(errors.ERR_INVALID_STATE, "Request is not SUBMITTED")
        # 2. SoD self-action: approver != requester and != target identity.
        if user_id == ar["requester_user_id"]:
            raise err(errors.ERR_SOD_SELF_ACTION,
                      "Approver may not be the request's requester")
        if user_id == ar["identity_id"]:
            raise err(errors.ERR_SOD_SELF_ACTION,
                      "Approver may not be the target identity")

        identity = db.identities.get(ar["identity_id"])
        role = db.roles.get(ar["role_id"])
        # 3. Target identity must be ACTIVE.
        if identity is None or identity["status"] != "ACTIVE":
            raise err(errors.ERR_IDENTITY_NOT_ACTIVE, "Target identity is not ACTIVE")
        # 4. Dual approval for privileged role bundles.
        if role is not None and role.get("requires_dual_approval"):
            if second_confirmed is not True:
                raise err(errors.ERR_DUAL_APPROVAL_REQUIRED,
                          "second_approver_confirmed must be true")
        # 5. SoD conflict gate.
        detected, hard, soft = domain.evaluate_sod(ar["identity_id"], role)
        ar["sod_conflict_detected"] = detected
        if hard:
            raise err(errors.ERR_SOD_CONFLICT,
                      "A HARD SoD conflict blocks this approval")
        if soft:
            effective_override = override_just if override_just is not None \
                else ar.get("sod_override_justification")
            if not effective_override:
                raise err(errors.ERR_SOD_OVERRIDE_REQUIRED,
                          "A SOFT SoD conflict requires sod_override_justification")
            ar["sod_override_justification"] = effective_override

        # Gates passed: cascade.
        ar["decided_by_user_id"] = user_id
        ar["status"] = "APPROVED"
        db.touch(ar)

        # depth-3: create + activate one grant per role entitlement; HIGH_RISK
        # auto-flag on the newest privileged grant if the threshold is crossed.
        risk_before = identity["effective_risk_score"]
        created = []
        for eid in (role.get("entitlement_ids", []) if role else []):
            g = domain.create_and_activate_grant(
                identity=identity,
                entitlement_id=eid,
                source_request_id=ar["id"],
                is_just_in_time=False,
                effective_from=None,
                effective_until=None,
                actor_user_id=user_id,
            )
            created.append(g)
        domain.apply_high_risk_flag(identity, risk_before, created)

        domain.append_audit(ar["identity_id"], "REQUEST_APPROVED", user_id,
                            "Access request %s approved" % id)
        # Pending portion cleared; projected now equals effective.
        domain.recompute_projected_only(identity)
        return object_response(serialize(ar), 200)
