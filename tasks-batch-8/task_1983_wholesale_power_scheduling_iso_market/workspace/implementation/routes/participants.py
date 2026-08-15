from flask import Blueprint

from auth import parse_auth, require_role
from db import store
from envelope import ok
from errors import not_found
from util import get_body, check_unknown, req_string, req_enum, new_record, serialize, touch
from services import credit

bp = Blueprint("participants", __name__)

TIERS = ("INVESTMENT_GRADE", "BELOW_INVESTMENT_GRADE")


def get_participant(pid):
    p = store.participants.get(pid)
    if p is None:
        raise not_found("market participant not found")
    return p


@bp.post("/market/participants")
def create_participant():
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    body = get_body()
    check_unknown(body, {"company_name", "credit_rating_tier"})
    company_name = req_string(body, "company_name")
    tier = req_enum(body, "credit_rating_tier", TIERS)
    rec = new_record()
    rec.update({
        "company_name": company_name,
        "credit_rating_tier": tier,
        "status": "ACTIVE",
        "posted_collateral_cents": 0,
        "collateral_requirement_cents": 0,
        "unsecured_allowance_cents": credit.unsecured_allowance({"credit_rating_tier": tier}),
    })
    store.participants[rec["id"]] = rec
    return ok(serialize(rec), status=201)


@bp.get("/market/participants/<participantId>")
def get_one(participantId):
    parse_auth()
    return ok(serialize(get_participant(participantId)))


@bp.post("/market/participants/<participantId>/evaluate-credit")
def evaluate_credit(participantId):
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    p = get_participant(participantId)
    credit.recompute_requirement(p)
    if p["status"] == "SUSPENDED":
        # Only an explicit operator evaluation can reinstate a suspended
        # participant, and only when collateral covers the effective requirement.
        if p["posted_collateral_cents"] >= credit.effective_requirement(p):
            p["status"] = "ACTIVE"
            touch(p)
    else:
        credit.evaluate_credit(p)
    return ok(serialize(p))
