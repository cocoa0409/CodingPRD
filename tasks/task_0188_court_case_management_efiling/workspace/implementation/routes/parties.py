"""Parties."""
from flask import Blueprint, request

import db
from middleware import get_actor, require_role
from response import success
from services import domain, validate

bp = Blueprint("parties", __name__)

PARTY_ROLES = {"PLAINTIFF", "DEFENDANT"}


@bp.post("/parties")
def create_party():
    _, role = get_actor()
    require_role(role, {"Clerk"})
    data = validate.body(request)
    case_id = validate.require_str(data, "case_id")
    # Existence (priority 3) before remaining body validation (priority 4).
    domain.get_or_404(db.cases, case_id)
    display_name = validate.require_str(data, "display_name")
    party_role = validate.enum(data, "role", PARTY_ROLES)
    attorney_user_id = validate.require_str(data, "attorney_user_id")

    rec = db.base_record()
    rec.update({
        "case_id": case_id,
        "display_name": display_name,
        "role": party_role,
        "attorney_user_id": attorney_user_id,
        "service_status": "UNSERVED" if party_role == "DEFENDANT" else None,
        "served_at": None,
    })
    db.parties[rec["id"]] = rec
    return success(domain._clean(rec), status=201)


@bp.get("/parties/<party_id>")
def get_party(party_id):
    get_actor()
    rec = domain.get_or_404(db.parties, party_id)
    return success(domain._clean(rec), status=200)


@bp.get("/parties")
def list_parties():
    get_actor()
    args = request.args
    items = list(db.parties.values())
    case_id = args.get("case_id")
    if case_id is not None:
        items = [p for p in items if p["case_id"] == case_id]
    party_role = args.get("role")
    if party_role is not None:
        items = [p for p in items if p["role"] == party_role]
    window, pagination = domain.paginate(items, args)
    return success([domain._clean(p) for p in window], status=200, pagination=pagination)
