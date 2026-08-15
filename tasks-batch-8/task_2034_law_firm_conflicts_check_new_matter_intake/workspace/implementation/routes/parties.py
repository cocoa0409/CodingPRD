"""Party endpoints (PRD 3.1)."""

from flask import Blueprint, request

import db
from db import stamp_new
from errors import invalid, forbidden
from middleware import caller, admit, body
from response import ok_object, ok_list, paginate, sort_by_created
from services.naming import normalize, soundex
from services.validate import PARTY_TYPES, resolve

bp = Blueprint("parties", __name__)

STAFF = ("FirmAdmin", "IntakeSpecialist", "ResponsibleAttorney",
         "ConflictsPartner", "BillingClerk")


@bp.post("/intake/parties")
def create_party():
    _, role = caller()
    admit(role, ("FirmAdmin",))
    data = body()

    # Tier 3: affiliate FK resolution precedes shape validation (PRD 2.11).
    affiliate_of_id = data.get("affiliate_of_id")
    if affiliate_of_id is not None:
        resolve(db.store.parties, affiliate_of_id)

    # Tier 12: request shape.
    legal_name = data.get("legal_name")
    if not isinstance(legal_name, str) or legal_name == "":
        raise invalid("legal_name is required")
    party_type = data.get("party_type")
    if party_type not in PARTY_TYPES:
        raise invalid("party_type must be one of " + ", ".join(PARTY_TYPES))
    aliases_in = data.get("aliases", [])
    if not isinstance(aliases_in, list):
        raise invalid("aliases must be a list")

    normalized_name = normalize(legal_name)
    aliases = []
    seen_normalized = set()
    for item in aliases_in:
        if not isinstance(item, dict) or not isinstance(item.get("alias_name"), str):
            raise invalid("each alias must be an object with alias_name")
        normalized_alias = normalize(item["alias_name"])
        if normalized_alias == normalized_name or normalized_alias in seen_normalized:
            raise invalid("alias normalized value duplicates the party's own "
                          "normalized_name or another alias")
        seen_normalized.add(normalized_alias)
        aliases.append({
            "alias_name": item["alias_name"],
            "normalized_alias": normalized_alias,
        })

    party = stamp_new({
        "legal_name": legal_name,
        "party_type": party_type,
        "aliases": aliases,
        "normalized_name": normalized_name,
        "phonetic_key": soundex(normalized_name),
        "affiliate_of_id": affiliate_of_id,
    })
    db.store.parties[party["id"]] = party
    return ok_object(party, 201)


@bp.get("/intake/parties/<pid>")
def get_party(pid):
    user_id, role = caller()
    admit(role, STAFF + ("Client",))
    party = resolve(db.store.parties, pid)
    # Tier 5 ownership: a Client reads only its own party record.
    if role == "Client" and user_id != party["id"]:
        raise forbidden("Client may read only its own party record")
    return ok_object(party)


@bp.get("/intake/parties")
def list_parties():
    _, role = caller()
    admit(role, STAFF)
    rows = list(db.store.parties.values())
    q = request.args.get("q")
    if q is not None:
        needle = q.lower()
        rows = [p for p in rows if needle in p["normalized_name"]]
    party_type = request.args.get("party_type")
    if party_type is not None:
        rows = [p for p in rows if p["party_type"] == party_type]
    affiliate_of_id = request.args.get("affiliate_of_id")
    if affiliate_of_id is not None:
        rows = [p for p in rows if p["affiliate_of_id"] == affiliate_of_id]
    return paginate(sort_by_created(rows), request.args)


@bp.get("/intake/parties/<pid>/matter-parties")
def party_matter_parties(pid):
    _, role = caller()
    admit(role, STAFF)
    resolve(db.store.parties, pid)
    rows = [mp for mp in db.store.matter_parties.values() if mp["party_id"] == pid]
    return paginate(sort_by_created(rows), request.args)
