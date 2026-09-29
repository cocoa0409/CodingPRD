"""Party registry and the logical clock."""
from flask import Blueprint

from common import (authenticate, body_of, opt_int, parse_dt, req_state_code,
                    req_str)
from derive import DEFAULT_CREDIT_LIMIT_CENTS
from envelope import created, ok, public
from errors import ApiError
from store import db, format_clock, new_record

bp = Blueprint("parties", __name__)

ALL_ROLES = ("Grazier", "CattleOwner", "RangeConsultant", "PlatformAdmin")


@bp.post("/grazing/graziers")
def create_grazier():
    authenticate(("PlatformAdmin",), resolve_identity=False)
    body = body_of()
    business_name = req_str(body, "business_name")
    state_code = req_state_code(body)
    liability_carrier = req_str(body, "liability_carrier")

    rec = new_record()
    rec.update({
        "business_name": business_name,
        "state_code": state_code,
        "liability_carrier": liability_carrier,
    })
    db.graziers[rec["id"]] = rec
    return created(public(rec))


@bp.post("/grazing/cattle-owners")
def create_cattle_owner():
    authenticate(("PlatformAdmin",), resolve_identity=False)
    body = body_of()
    legal_name = req_str(body, "legal_name")
    state_code = req_state_code(body)
    brand_registration = req_str(body, "brand_registration")
    credit_limit = opt_int(body, "credit_limit_cents", DEFAULT_CREDIT_LIMIT_CENTS, minv=0)

    rec = new_record()
    rec.update({
        "legal_name": legal_name,
        "state_code": state_code,
        "brand_registration": brand_registration,
        "credit_limit_cents": credit_limit,
        "open_settlement_balance_cents": 0,
        "credit_status": "GOOD_STANDING",
    })
    db.cattle_owners[rec["id"]] = rec
    return created(public(rec))


@bp.get("/grazing/cattle-owners/<owner_id>")
def read_cattle_owner(owner_id):
    authenticate(ALL_ROLES)
    owner = db.cattle_owners.get(owner_id)
    if owner is None:
        raise ApiError("ERR_PARTY_NOT_FOUND", "Cattle owner does not exist.")
    return ok(public(owner))


@bp.post("/grazing/range-consultants")
def create_range_consultant():
    authenticate(("PlatformAdmin",), resolve_identity=False)
    body = body_of()
    full_name = req_str(body, "full_name")
    certification_number = req_str(body, "certification_number")
    state_code = req_state_code(body)

    rec = new_record()
    rec.update({
        "full_name": full_name,
        "certification_number": certification_number,
        "state_code": state_code,
    })
    db.consultants[rec["id"]] = rec
    return created(public(rec))


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("PlatformAdmin",), resolve_identity=False)
    body = body_of()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str) or parse_dt(raw) is None:
        raise ApiError("ERR_VALIDATION", "to_iso8601 is required and must be an ISO 8601 instant.")
    db.clock = parse_dt(raw)
    return ok({"current_utc": format_clock(db.clock)})
