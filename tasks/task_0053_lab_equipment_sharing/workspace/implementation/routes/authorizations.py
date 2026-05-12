"""Authorization endpoints."""
from datetime import timedelta
from flask import Blueprint, request, g

import db
from clock import iso, now, parse_iso
from errors import err
from middleware import require_auth
from response import success
from services import audit, calc, reservation_ops


bp = Blueprint("authorizations", __name__)


def _get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        raise err("ERR_BAD_REQUEST", "JSON body required")
    if not isinstance(body, dict):
        raise err("ERR_BAD_REQUEST", "JSON object required")
    return body


def _eligibility_or_raise(eq, user, sample_type):
    """Run eligibility gate. Raise ERR_QUALIFICATION_NOT_MET or
    ERR_SHARING_SCOPE_VIOLATION as appropriate.

    Order: when only affiliation_match is the failure (and training+sample+identity all 1),
    return ERR_SHARING_SCOPE_VIOLATION; otherwise ERR_QUALIFICATION_NOT_MET.

    Per priority order in scaffold: priority 9 (qualification) before priority 10 (sharing scope).
    BUT the PRD specifies: "When the failure is specifically a sharing-scope mismatch
    (training, sample, and identity all 1 but affiliation 0)" → SHARING_SCOPE_VIOLATION.
    """
    elig = calc.eligibility(eq, user, sample_type)
    if elig["passes_gate"]:
        return
    # Check the specific sharing-scope-only failure case
    if (elig["training_match"] == 1 and elig["sample_match"] == 1
            and elig["identity_match"] == 1 and elig["affiliation_match"] == 0):
        raise err("ERR_SHARING_SCOPE_VIOLATION",
                  "user affiliation incompatible with equipment sharing scope")
    raise err("ERR_QUALIFICATION_NOT_MET",
              "user failed authorization eligibility gate")


@bp.post("/equipment/<equipment_id>/authorizations")
@require_auth(roles={"User"})
def create_authorization(equipment_id):
    eq = db.equipment.get(equipment_id)
    if eq is None:
        raise err("ERR_NOT_FOUND", "equipment not found")
    body = _get_body()
    user_id = body.get("user_id")
    sample_type = body.get("sample_type")
    urgency = body.get("urgency", "NORMAL")
    if not isinstance(user_id, str) or not user_id:
        raise err("ERR_BAD_REQUEST", "user_id is required")
    if not isinstance(sample_type, str) or not sample_type:
        raise err("ERR_BAD_REQUEST", "sample_type is required")
    if urgency not in ("NORMAL", "URGENT"):
        raise err("ERR_BAD_REQUEST", "urgency must be NORMAL or URGENT")
    if user_id != g.user_id:
        raise err("ERR_FORBIDDEN", "user_id must match X-User-ID")
    user = db.users.get(user_id)
    if user is None:
        raise err("ERR_NOT_FOUND", "user not found")

    _eligibility_or_raise(eq, user, sample_type)

    auth = {
        "equipment_id": equipment_id,
        "user_id": user_id,
        "sample_type": sample_type,
        "urgency": urgency,
        "status": "PENDING_OWNER",
        "approved_at": None,
        "expires_at": None,
        "owner_decision_user_id": None,
        "platform_decision_user_id": None,
        "rejection_reason": None,
    }
    db.stamp_create(auth)
    db.authorizations[auth["id"]] = auth
    audit.record(
        subject_type="AUTHORIZATION",
        subject_id=auth["id"],
        actor_role=g.user_role,
        actor_user_id=g.user_id,
        action="CREATE",
        from_state=None,
        to_state="PENDING_OWNER",
        payload_json={"urgency": urgency, "sample_type": sample_type},
    )
    return success(db.public(auth), status=201)


@bp.post("/authorizations/<authorization_id>/approve")
@require_auth(roles={"LabOwner", "PlatformAdmin"})
def approve_authorization(authorization_id):
    auth = db.authorizations.get(authorization_id)
    if auth is None:
        raise err("ERR_NOT_FOUND", "authorization not found")
    eq = db.equipment.get(auth["equipment_id"])
    if eq is None:
        raise err("ERR_NOT_FOUND", "equipment not found")
    user = db.users.get(auth["user_id"])
    if user is None:
        raise err("ERR_NOT_FOUND", "user not found")

    if auth["status"] == "PENDING_OWNER":
        # Must be LabOwner of equipment.lab_id
        if g.user_role != "LabOwner":
            raise err("ERR_FORBIDDEN",
                      "PENDING_OWNER step requires LabOwner")
        lab = db.labs.get(eq["lab_id"])
        if lab is None or lab["contact_user_id"] != g.user_id:
            raise err("ERR_FORBIDDEN", "not the lab owner")
        # Re-run eligibility
        from routes.authorizations import _eligibility_or_raise
        _eligibility_or_raise(eq, user, auth["sample_type"])

        auth["owner_decision_user_id"] = g.user_id
        # Branching
        if eq["value_tier"] == "HIGH_VALUE" and auth["urgency"] != "URGENT":
            prev = "PENDING_OWNER"
            auth["status"] = "PENDING_PLATFORM"
            db.stamp_update(auth)
            audit.record(
                subject_type="AUTHORIZATION",
                subject_id=auth["id"],
                actor_role=g.user_role,
                actor_user_id=g.user_id,
                action="APPROVE",
                from_state=prev,
                to_state="PENDING_PLATFORM",
                payload_json={"step": "owner"},
            )
        else:
            prev = "PENDING_OWNER"
            auth["status"] = "APPROVED"
            auth["approved_at"] = iso(now())
            auth["expires_at"] = iso(now() + timedelta(days=calc.AUTHORIZATION_TTL_DAYS))
            db.stamp_update(auth)
            audit.record(
                subject_type="AUTHORIZATION",
                subject_id=auth["id"],
                actor_role=g.user_role,
                actor_user_id=g.user_id,
                action="APPROVE",
                from_state=prev,
                to_state="APPROVED",
                payload_json={"step": "owner_final"},
            )
    elif auth["status"] == "PENDING_PLATFORM":
        if g.user_role != "PlatformAdmin":
            raise err("ERR_FORBIDDEN",
                      "PENDING_PLATFORM step requires PlatformAdmin")
        auth["platform_decision_user_id"] = g.user_id
        prev = "PENDING_PLATFORM"
        auth["status"] = "APPROVED"
        auth["approved_at"] = iso(now())
        auth["expires_at"] = iso(now() + timedelta(days=calc.AUTHORIZATION_TTL_DAYS))
        db.stamp_update(auth)
        audit.record(
            subject_type="AUTHORIZATION",
            subject_id=auth["id"],
            actor_role=g.user_role,
            actor_user_id=g.user_id,
            action="APPROVE",
            from_state=prev,
            to_state="APPROVED",
            payload_json={"step": "platform"},
        )
    else:
        raise err("ERR_AUTHORIZATION_ALREADY_DECIDED",
                  f"authorization is in state {auth['status']}")
    return success(db.public(auth))


@bp.post("/authorizations/<authorization_id>/reject")
@require_auth(roles={"LabOwner", "PlatformAdmin"})
def reject_authorization(authorization_id):
    auth = db.authorizations.get(authorization_id)
    if auth is None:
        raise err("ERR_NOT_FOUND", "authorization not found")
    eq = db.equipment.get(auth["equipment_id"])
    if eq is None:
        raise err("ERR_NOT_FOUND", "equipment not found")
    if auth["status"] not in ("PENDING_OWNER", "PENDING_PLATFORM"):
        raise err("ERR_AUTHORIZATION_ALREADY_DECIDED",
                  f"authorization is in state {auth['status']}")
    if auth["status"] == "PENDING_OWNER":
        if g.user_role != "LabOwner":
            raise err("ERR_FORBIDDEN", "PENDING_OWNER reject requires LabOwner")
        lab = db.labs.get(eq["lab_id"])
        if lab is None or lab["contact_user_id"] != g.user_id:
            raise err("ERR_FORBIDDEN", "not the lab owner")
    else:
        if g.user_role != "PlatformAdmin":
            raise err("ERR_FORBIDDEN", "PENDING_PLATFORM reject requires PlatformAdmin")

    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise err("ERR_BAD_REQUEST", "JSON object required")
    reason = body.get("rejection_reason")
    if reason is not None and not isinstance(reason, str):
        raise err("ERR_BAD_REQUEST", "rejection_reason must be a string")
    prev = auth["status"]
    auth["rejection_reason"] = reason
    auth["status"] = "REJECTED"
    db.stamp_update(auth)
    audit.record(
        subject_type="AUTHORIZATION",
        subject_id=auth["id"],
        actor_role=g.user_role,
        actor_user_id=g.user_id,
        action="REJECT",
        from_state=prev,
        to_state="REJECTED",
        payload_json={"reason": reason},
    )
    return success(db.public(auth))


@bp.post("/authorizations/<authorization_id>/revoke")
@require_auth(roles={"LabOwner", "PlatformAdmin"})
def revoke_authorization(authorization_id):
    auth = db.authorizations.get(authorization_id)
    if auth is None:
        raise err("ERR_NOT_FOUND", "authorization not found")
    eq = db.equipment.get(auth["equipment_id"])
    if eq is None:
        raise err("ERR_NOT_FOUND", "equipment not found")
    if g.user_role == "LabOwner":
        lab = db.labs.get(eq["lab_id"])
        if lab is None or lab["contact_user_id"] != g.user_id:
            raise err("ERR_FORBIDDEN", "not the lab owner")
    if auth["status"] != "APPROVED":
        raise err("ERR_AUTHORIZATION_ALREADY_DECIDED",
                  f"authorization is in state {auth['status']}")
    prev = auth["status"]
    auth["status"] = "REVOKED"
    db.stamp_update(auth)
    # Cancel future-dated BOOKED reservations bound to this authorization
    for r in list(db.reservations.values()):
        if r.get("authorization_id") != auth["id"]:
            continue
        if r["status"] != "BOOKED":
            continue
        if parse_iso(r["start_at"]) <= now():
            continue
        reservation_ops.cancel_reservation(
            r, actor_role=g.user_role, actor_user_id=g.user_id,
            refund_bps=10000, reason="authorization_revoked")
    audit.record(
        subject_type="AUTHORIZATION",
        subject_id=auth["id"],
        actor_role=g.user_role,
        actor_user_id=g.user_id,
        action="REVOKE",
        from_state=prev,
        to_state="REVOKED",
        payload_json={},
    )
    return success(db.public(auth))
