"""Trade-in appraisal endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import get_auth, require_role
from response import success_response, parse_pagination, apply_pagination
from services.calculations import tradein_offer_value, recompute_credit_balance, round_half_up_cents
from services.common import (
    new_entity, touch, get_appraisal, get_customer, check_ownership,
    check_create_ownership, append_ledger_entry,
)
from services.serializers import serialize_trade_in_appraisal
from decimal import Decimal

bp = Blueprint("appraisals", __name__)

READ_ROLES = {"Customer", "FittingSpecialist", "ShopManager"}
CLUB_TYPES = {"DRIVER", "FAIRWAY", "HYBRID", "IRON_SET", "WEDGE", "PUTTER"}
GRADES = {"A", "B", "C", "D"}


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/trade-in-appraisals")
def create_appraisal():
    user_id, role = get_auth()
    require_role(role, {"Customer"})
    data = _body()
    customer_id = data.get("customer_id")
    clubs = data.get("clubs")
    if not isinstance(customer_id, str) or not customer_id.strip():
        raise_err("ERR_VALIDATION", "customer_id is required")
    if not isinstance(clubs, list) or len(clubs) == 0:
        raise_err("ERR_VALIDATION", "clubs must be a non-empty array")
    for club in clubs:
        if not isinstance(club, dict):
            raise_err("ERR_VALIDATION", "each club must be an object")
        if club.get("club_type") not in CLUB_TYPES:
            raise_err("ERR_VALIDATION", "invalid club_type")
        if club.get("condition_grade") not in GRADES:
            raise_err("ERR_VALIDATION", "invalid condition_grade")
    get_customer(customer_id)
    check_create_ownership(customer_id, user_id, role)
    a = new_entity()
    a.update({
        "customer_id": customer_id,
        "clubs": [{"club_type": c["club_type"], "condition_grade": c["condition_grade"]}
                  for c in clubs],
        "status": "SUBMITTED",
        "offer_basis": None,
        "offered_value_cents": None,
        "offer_expires_at": None,
        "offered_by_staff_id": None,
    })
    db.trade_in_appraisals[a["id"]] = a
    return success_response(serialize_trade_in_appraisal(a), status=201)


@bp.get("/trade-in-appraisals/<aid>")
def read_appraisal(aid):
    user_id, role = get_auth()
    require_role(role, READ_ROLES)
    a = get_appraisal(aid)
    check_ownership(a, user_id, role)
    return success_response(serialize_trade_in_appraisal(a))


@bp.get("/trade-in-appraisals")
def list_appraisals():
    user_id, role = get_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.trade_in_appraisals.values())
    if role == "Customer":
        items = [a for a in items if a["customer_id"] == user_id]
    for field in ("customer_id", "status", "offered_by_staff_id"):
        val = request.args.get(field)
        if val is not None:
            items = [a for a in items if a.get(field) == val]
    items.sort(key=lambda a: a["created_at"])
    page, pagination = apply_pagination(items, limit, offset)
    return success_response(
        [serialize_trade_in_appraisal(a) for a in page],
        response_type="array", pagination=pagination,
    )


@bp.post("/trade-in-appraisals/<aid>/offers")
def make_offer(aid):
    user_id, role = get_auth()
    require_role(role, {"FittingSpecialist", "ShopManager"})
    data = _body()
    basis = data.get("basis")
    expected_version = data.get("expected_appraisal_version")
    market_comps_cents = data.get("market_comps_cents")
    # Body shape (priority 3)
    if basis not in ("GRADE_MATRIX", "MARKET_COMP"):
        raise_err("ERR_VALIDATION", "basis must be GRADE_MATRIX or MARKET_COMP")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise_err("ERR_VALIDATION", "expected_appraisal_version is required")
    a = get_appraisal(aid)
    # MARKET_COMP requires one comparable per club
    if basis == "MARKET_COMP":
        if (not isinstance(market_comps_cents, list)
                or len(market_comps_cents) != len(a["clubs"])
                or any(not isinstance(v, int) or isinstance(v, bool) for v in market_comps_cents)):
            raise_err("ERR_VALIDATION",
                      "market_comps_cents must be present with one entry per club")
    # OCC (priority 6)
    if expected_version != a["version"]:
        raise_err("ERR_STALE_VERSION", "appraisal version has advanced")
    # State guard (priority 7): offers allowed from SUBMITTED, OFFERED, DECLINED
    if a["status"] not in ("SUBMITTED", "OFFERED", "DECLINED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "offers are not defined from the appraisal's current state")
    a["offered_value_cents"] = tradein_offer_value(a["clubs"], basis, market_comps_cents)
    a["offer_basis"] = basis
    a["offered_by_staff_id"] = user_id
    a["offer_expires_at"] = db.logical_now + timedelta(hours=168)
    a["status"] = "OFFERED"
    touch(a)
    return success_response(serialize_trade_in_appraisal(a))


@bp.post("/trade-in-appraisals/<aid>/accept")
def accept_appraisal(aid):
    user_id, role = get_auth()
    require_role(role, {"Customer"})
    a = get_appraisal(aid)
    check_ownership(a, user_id, role)
    if a["status"] != "OFFERED":
        raise_err("ERR_APPRAISAL_NOT_OFFERED", "accept called on an appraisal not in OFFERED")
    # Grant store credit
    append_ledger_entry(a["customer_id"], a["offered_value_cents"],
                        "TRADE_IN_ACCEPT", a["id"])
    recompute_credit_balance(a["customer_id"])
    touch(db.customers[a["customer_id"]])
    # Create used-club listing
    listing = new_entity()
    listing.update({
        "appraisal_id": a["id"],
        "appraised_by_staff_id": a["offered_by_staff_id"],
        "list_price_cents": round_half_up_cents(Decimal(a["offered_value_cents"]) * Decimal("1.4")),
        "status": "LISTED",
        "reserved_by_customer_id": None,
        "reserved_until": None,
    })
    db.used_club_listings[listing["id"]] = listing
    a["status"] = "ACCEPTED"
    touch(a)
    return success_response(serialize_trade_in_appraisal(a))


@bp.post("/trade-in-appraisals/<aid>/decline")
def decline_appraisal(aid):
    user_id, role = get_auth()
    require_role(role, {"Customer"})
    a = get_appraisal(aid)
    check_ownership(a, user_id, role)
    if a["status"] != "OFFERED":
        raise_err("ERR_APPRAISAL_NOT_OFFERED", "decline called on an appraisal not in OFFERED")
    a["status"] = "DECLINED"
    touch(a)
    return success_response(serialize_trade_in_appraisal(a))
