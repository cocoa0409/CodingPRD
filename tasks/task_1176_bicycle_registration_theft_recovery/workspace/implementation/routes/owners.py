"""Owner account endpoints (PRD §3.1)."""
import hashlib

from flask import Blueprint, g

import db
from errors import fail
from middleware import body, require_roles
from models import owner_view
from response import ok_object
from routes.common import field, load

bp = Blueprint("owners", __name__)


@bp.post("/registry/owners/register")
@require_roles("Anonymous")
def register_owner():
    data = body()
    email = field(data, "email", "string", required=True)
    password = field(data, "password", "string", required=True)
    full_name = field(data, "full_name", "string", required=True)
    phone = field(data, "phone", "string", required=False, nullable=True)

    # email uniqueness enforced case-insensitively across all owners
    for existing in db.owners.values():
        if existing["email"].lower() == email.lower():
            fail("ERR_INVALID_REQUEST", "email already registered")

    rec = db.new_record({
        "email": email,
        "password_hash": hashlib.sha256(password.encode("utf-8")).hexdigest(),
        "full_name": full_name,
        "phone": phone,
    })
    db.owners[rec["id"]] = rec
    return ok_object(owner_view(rec), status=201)


@bp.get("/registry/owners/<owner_id>")
@require_roles("Owner", "Registrar", "Admin")
def read_owner(owner_id):
    # Owner identity check is computable before load: owners read only themselves.
    if g.role == "Owner" and g.user_id != owner_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Owners may read only their own record")
    rec = load(db.owners, owner_id, "ERR_OWNER_NOT_FOUND")
    return ok_object(owner_view(rec))


@bp.patch("/registry/owners/<owner_id>")
@require_roles("Owner")
def update_owner(owner_id):
    if g.user_id != owner_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Owners may update only their own record")
    rec = load(db.owners, owner_id, "ERR_OWNER_NOT_FOUND")
    data = body()
    full_name = field(data, "full_name", "string", required=False)
    phone = field(data, "phone", "string", required=False, nullable=True)
    if "full_name" in data and full_name is not None:
        rec["full_name"] = full_name
    if "phone" in data:
        rec["phone"] = phone
    db.bump(rec)
    return ok_object(owner_view(rec))
