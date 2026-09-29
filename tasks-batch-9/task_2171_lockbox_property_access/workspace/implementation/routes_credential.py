"""Keyholder credentials: issuance, the credential cap and the state machine (PRD §3.3)."""
from flask import Blueprint

import calc
import serialize
from core import (
    ADMIN, READ_ROLES, authenticate, body, db, fail, lookup, new_common, now,
    ok, ordered, paginate, parse_dt, present, qfilter, touch,
)
from ladder import (
    assert_not_terminal, assert_transition, assert_version, require_action,
    require_version_field,
)

bp = Blueprint("credential", __name__)

CREDENTIAL_TYPES = ("KEY_APP", "KEY_FOB")
CREDENTIAL_TRANSITIONS = {
    "ACTIVATE": ("PENDING_ACTIVATION",),
    "SUSPEND": ("ACTIVE",),
    "REINSTATE": ("SUSPENDED",),
    "REVOKE": ("PENDING_ACTIVATION", "ACTIVE", "SUSPENDED"),
}


@bp.post("/access-credentials")
def issue_credential():
    authenticate([ADMIN])
    payload = body()

    # Rung 4 — body foreign keys.
    member = None
    if present(payload, "member_id"):
        member = lookup("members", payload["member_id"])

    # Rung 5 — request shape.
    if member is None:
        fail("ERR_INVALID_REQUEST", "member_id is required.")
    if not present(payload, "credential_type") or payload["credential_type"] not in CREDENTIAL_TYPES:
        fail("ERR_INVALID_REQUEST", "credential_type must be one of KEY_APP, KEY_FOB.")
    if not present(payload, "expires_at"):
        fail("ERR_INVALID_REQUEST", "expires_at is required.")
    expires_at = parse_dt(payload["expires_at"])
    if expires_at is None:
        fail("ERR_INVALID_REQUEST", "expires_at must be an ISO 8601 instant.")
    expected = require_version_field(payload, "expected_member_version")

    # Rung 8 — optimistic concurrency on the owning member.
    assert_version(expected, member)

    # Credential cap — supersede the earliest-created ACTIVE credential.
    association = db.associations.get(member["association_id"])
    cap = association["credential_cap_per_member"] if association else 2
    active = [c for c in calc.member_credentials(member["id"]) if c["status"] == "ACTIVE"]
    if cap > 0 and len(active) >= cap:
        earliest = ordered(db.credentials, active)[0]
        earliest["status"] = "REVOKED"
        earliest["supersede_reason"] = "CREDENTIAL_CAP_SUPERSEDE"
        touch(earliest)

    rec = new_common()
    rec.update({
        "member_id": member["id"],
        "credential_type": payload["credential_type"],
        "expires_at": payload["expires_at"],
        "status": "PENDING_ACTIVATION",
        "suspended_by_cascade": False,
        "supersede_reason": None,
    })
    db.credentials[rec["id"]] = rec
    touch(member)
    return ok(serialize.credential(rec), 201)


@bp.get("/access-credentials/<credential_id>")
def read_credential(credential_id):
    authenticate(READ_ROLES)
    return ok(serialize.credential(lookup("credentials", credential_id)))


@bp.get("/access-credentials")
def list_credentials():
    authenticate(READ_ROLES)
    rows = ordered(db.credentials)
    rows = qfilter(rows, "member_id")
    rows = qfilter(rows, "status")
    rows = qfilter(rows, "credential_type")
    return paginate(rows, serialize.credential)


@bp.post("/access-credentials/<credential_id>/state")
def credential_state(credential_id):
    authenticate([ADMIN])
    credential = lookup("credentials", credential_id)
    payload = body()

    action = require_action(payload, tuple(CREDENTIAL_TRANSITIONS))
    expected = require_version_field(payload, "expected_credential_version")

    assert_version(expected, credential)
    assert_not_terminal("credential", credential["status"])
    assert_transition(credential["status"], CREDENTIAL_TRANSITIONS, action)

    member = db.members.get(credential["member_id"])
    if action in ("ACTIVATE", "REINSTATE"):
        # Rung 10 — referenced member eligibility.
        if member is None or member["membership_status"] not in ("ACTIVE", "PROBATION"):
            fail("ERR_MEMBER_NOT_ELIGIBLE", "The owning member is not in good standing.")
        # Rung 14 — window geometry.
        expires_at = parse_dt(credential["expires_at"])
        if expires_at is None or expires_at <= now():
            fail("ERR_INVALID_WINDOW", "The credential has already lapsed.")

    if action == "ACTIVATE":
        credential["status"] = "ACTIVE"
    elif action == "SUSPEND":
        credential["status"] = "SUSPENDED"
        credential["suspended_by_cascade"] = False
    elif action == "REINSTATE":
        credential["status"] = "ACTIVE"
        credential["suspended_by_cascade"] = False
    elif action == "REVOKE":
        credential["status"] = "REVOKED"

    touch(credential)
    return ok(serialize.credential(credential))
