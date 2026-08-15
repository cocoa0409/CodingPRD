"""Party endpoints and manual screening."""

from flask import Blueprint, request

import db
from middleware import (
    auth,
    get_body,
    no_unknown,
    need,
    v_str,
    v_bool,
    v_enum,
    find,
    page_params,
    filtered_sorted,
)
from response import ok, list_response
from services.screening import run_screening

bp = Blueprint("parties", __name__)

PARTY_TYPES = ("CUSTOMER", "CONSIGNEE", "END_USER", "FOREIGN_NATIONAL")


@bp.post("/compliance/parties")
def create_party():
    auth("ComplianceAnalyst", "TradeOpsSpecialist")
    body = get_body()
    no_unknown(body, {"legal_name", "country_code", "city", "party_type", "is_foreign_national"})
    legal_name = v_str(need(body, "legal_name"), "legal_name")
    country_code = v_str(need(body, "country_code"), "country_code")
    city = v_str(need(body, "city"), "city")
    party_type = v_enum(need(body, "party_type"), "party_type", PARTY_TYPES)
    is_fn = False
    if "is_foreign_national" in body:
        is_fn = v_bool(body["is_foreign_national"], "is_foreign_national")
    party = {
        "legal_name": legal_name,
        "country_code": country_code,
        "city": city,
        "party_type": party_type,
        "is_foreign_national": is_fn,
        "screening_posture": "UNSCREENED",
        "active_grant_count": 0,
        "last_screened_at": None,
    }
    db.stamp_new(party)
    db.PARTIES[party["id"]] = party
    return ok(db.pub(party), "object", 201)


@bp.get("/compliance/parties/<pid>")
def get_party(pid):
    auth()
    party = find(db.PARTIES, pid, "Party")
    return ok(db.pub(party), "object", 200)


@bp.get("/compliance/parties")
def list_parties():
    auth()
    filters = {
        "screening_posture": request.args.get("screening_posture"),
        "country_code": request.args.get("country_code"),
        "party_type": request.args.get("party_type"),
    }
    items = filtered_sorted(db.PARTIES, filters)
    limit, offset = page_params()
    return list_response(items, limit, offset)


@bp.post("/compliance/parties/<pid>/screen")
def screen_party(pid):
    auth("ComplianceAnalyst", "TradeOpsSpecialist")
    party = find(db.PARTIES, pid, "Party")
    result = run_screening(party, "MANUAL", "FUZZY")
    return ok(db.pub(result), "object", 201)
