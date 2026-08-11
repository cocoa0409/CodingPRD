from flask import Blueprint

import calc
import core
import gates
import serialize
from core import fail, new_row, rows, touch

bp = Blueprint("owners", __name__)

CREATE_SPEC = [
    ("full_name", "string", True),
    ("email", "string", True),
    ("phone", "string", True),
    ("primary_residence_state", "string", True),
    ("snowbird_flag", "boolean", False),
    ("notification_preference", "string", False),
    ("approval_ceiling_override_cents", "integer", False),
]

PATCH_SPEC = [
    ("phone", "string", False),
    ("notification_preference", "string", False),
    ("approval_ceiling_override_cents", "integer", False),
    ("snowbird_flag", "boolean", False),
]


@bp.post("/property-care/owners")
def create_owner():
    gates.begin(["PlatformAdmin", "AccountManager"])
    body = gates.body_json()
    gates.validate_payload(body, CREATE_SPEC)
    email = body["email"]
    # rung 68 - the email is unique across owners and must contain an at-sign
    if "@" not in email:
        fail("ERR_UNIQUENESS_VIOLATION", "An owner email must contain an at-sign.")
    if any(o["email"] == email for o in rows("owners")):
        fail("ERR_UNIQUENESS_VIOLATION", "That email is already registered.")
    owner = new_row(
        "owners",
        full_name=body["full_name"],
        email=email,
        phone=body["phone"],
        primary_residence_state=body["primary_residence_state"],
        snowbird_flag=body.get("snowbird_flag", False),
        notification_preference=body.get("notification_preference", "EMAIL"),
        approval_ceiling_override_cents=body.get("approval_ceiling_override_cents"),
        lifetime_credit_balance_cents=0,
        status="ACTIVE",
    )
    return core.ok(serialize.owner(owner), 201)


@bp.get("/property-care/owners")
def list_owners():
    gates.begin(["PlatformAdmin", "AccountManager", "Auditor"])
    return gates.list_response("owners", ["status"], serialize.owner)


@bp.get("/property-care/owners/<oid>")
def read_owner(oid):
    role, user_id = gates.begin(["PlatformAdmin", "AccountManager", "Auditor", "Owner"])
    owner = gates.fetch_path("owners", oid)
    gates.owner_scope(role, user_id, owner["id"])
    return core.ok(serialize.owner(owner))


@bp.patch("/property-care/owners/<oid>")
def patch_owner(oid):
    gates.begin(["PlatformAdmin", "AccountManager"])
    owner = gates.fetch_path("owners", oid)
    body = gates.body_json()
    gates.validate_payload(body, PATCH_SPEC)
    for field in ("phone", "notification_preference", "approval_ceiling_override_cents",
                  "snowbird_flag"):
        if field in body:
            owner[field] = body[field]
    touch(owner)
    return core.ok(serialize.owner(owner))
