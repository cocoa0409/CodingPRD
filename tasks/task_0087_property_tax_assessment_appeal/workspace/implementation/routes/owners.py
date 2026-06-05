"""Owner endpoints (PRD §3.2)."""
from flask import Blueprint

import db
from errors import err
from middleware import require_roles
from response import object_response
from services.common import get_body, require_fields, is_number, is_int
from services.serialize import serialize

bp = Blueprint("owners", __name__)


@bp.post("/owners")
def create_owner():
    # PRD §2.1: owner self-registration is exempt from the header requirement,
    # so this endpoint is NOT auth-gated. Authorized roles are Assessor and
    # Anonymous (§4). A caller presenting a recognised role that is neither of
    # those is unauthorized; an absent role is treated as anonymous.
    from middleware import get_identity, VALID_ROLES
    _user_id, role = get_identity()
    if role in VALID_ROLES and role not in ("Assessor", "Anonymous"):
        raise err("ERR_UNAUTHORIZED", "Role not permitted to register an owner")

    body = get_body()
    require_fields(body, ["full_name", "email", "birth_date"])

    full_name = body["full_name"]
    email = body["email"]
    birth_date = body["birth_date"]
    if not isinstance(full_name, str) or not isinstance(email, str) \
            or not isinstance(birth_date, str):
        raise err("ERR_INVALID_REQUEST", "full_name/email/birth_date must be strings")

    is_veteran = body.get("is_veteran", False)
    if not isinstance(is_veteran, bool):
        raise err("ERR_INVALID_REQUEST", "is_veteran must be a boolean")

    disability_pct = body.get("disability_pct", 0)
    if not is_int(disability_pct) or disability_pct < 0 or disability_pct > 100:
        raise err("ERR_INVALID_REQUEST", "disability_pct must be an integer 0..100")

    # email unique among owners
    for o in db.owners.values():
        if o["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique among owners")

    record = {
        "full_name": full_name,
        "email": email,
        "birth_date": birth_date,
        "is_veteran": is_veteran,
        "disability_pct": disability_pct,
    }
    db.init_common(record)
    with db.LOCK:
        db.owners[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/owners/<owner_id>")
def get_owner(owner_id):
    require_roles(["Assessor", "Reviewer", "HearingOfficer", "Taxpayer"])
    from services.common import lookup
    return object_response(serialize(lookup(db.owners, owner_id)), 200)
