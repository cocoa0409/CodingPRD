"""Capital need endpoints (PRD 3.7, 2.12)."""
from flask import Blueprint

import clock
import constants as C
import db
import middleware
from errors import ApiError
from response import created_response, object_response
from routes._common import listing, read_one
from services import domain

bp = Blueprint("capital_needs", __name__)


@bp.post("/capital-needs")
def create_capital_need():
    middleware.actor([C.TRUSTEE, C.MASTER_TENANT])
    payload = middleware.body_or_400()
    trust_id = middleware.req_str(payload, "trust_id")
    need_type = middleware.req_enum(payload, "need_type", C.NEED_TYPES)
    amount_cents = middleware.req_int(payload, "amount_cents", 1)
    needed_by = middleware.req_dt(payload, "needed_by")

    trust = domain.require("trust", trust_id)
    domain.check_frozen(trust)

    row = db.new_row(db.capital_needs, {
        "trust_id": trust["id"],
        "need_type": need_type,
        "amount_cents": amount_cents,
        "needed_by": needed_by,
        "funding_source": None,
        "funded_at": None,
        "status": "IDENTIFIED",
    })
    return created_response(db.serialize(row))


@bp.get("/capital-needs/<capital_need_id>")
def get_capital_need(capital_need_id):
    return read_one("capital_need", C.READ_TENANT_SIDE, capital_need_id)


@bp.get("/capital-needs")
def list_capital_needs():
    return listing(db.capital_needs, C.READ_TENANT_SIDE,
                   str_filters=("trust_id", "status", "need_type", "funding_source"))


@bp.post("/capital-needs/<capital_need_id>/fund")
def fund_capital_need(capital_need_id):
    user_id, role = middleware.actor([C.TRUSTEE, C.MASTER_TENANT])

    # rung 3 — a master tenant may only act on a trust it leases
    candidate = domain.lookup("capital_need", capital_need_id)
    if candidate is not None and role == C.MASTER_TENANT:
        trust = db.trusts.get(candidate["trust_id"])
        if trust is not None:
            domain.check_master_tenant_of(user_id, trust)

    payload = middleware.body_or_400()
    funding_source = middleware.req_enum(payload, "funding_source", C.FUNDING_SOURCES)

    need = domain.require("capital_need", capital_need_id)
    trust = db.trusts[need["trust_id"]]

    if funding_source == "RESERVE" and role != C.TRUSTEE:
        raise ApiError("ERR_UNAUTHORIZED")
    if funding_source == "MASTER_TENANT" and role != C.MASTER_TENANT:
        raise ApiError("ERR_UNAUTHORIZED")

    domain.check_frozen(trust)
    domain.check_restricted(trust)
    domain.check_trust_status(trust, ("OPERATING",))
    if need["status"] != "IDENTIFIED":
        raise ApiError("ERR_CAPITAL_NEED_INVALID_STATE")
    if funding_source == "CAPITAL_CALL":
        raise ApiError("ERR_CAPITAL_CALL_PROHIBITED")
    if funding_source == "RESERVE" and need["need_type"] == "STRUCTURAL_CAPEX":
        raise ApiError("ERR_STRUCTURAL_CAPEX_PROHIBITED")
    if funding_source == "RESERVE" and \
            trust["reserve_balance_cents"] < need["amount_cents"]:
        raise ApiError("ERR_RESERVE_INSUFFICIENT")

    need["funding_source"] = funding_source
    need["funded_at"] = clock.now()
    need["status"] = "FUNDED"

    if funding_source == "RESERVE":
        entry = domain.book(trust, "RESERVE_DRAW", "RESERVE", -need["amount_cents"],
                            "CAPITAL_NEED", memo="reserve draw for capital need")
        need["_reserve_entry_id"] = entry["id"]
        db.touch(need)
        domain.recompute_trust(trust, force=True)
    else:
        db.touch(need)
    return object_response(db.serialize(need))


@bp.post("/capital-needs/<capital_need_id>/void")
def void_capital_need(capital_need_id):
    middleware.actor([C.TRUSTEE])
    payload = middleware.body_or_400()
    middleware.opt_str(payload, "reason")

    need = domain.require("capital_need", capital_need_id)
    trust = db.trusts[need["trust_id"]]

    domain.check_frozen(trust)
    if need["status"] not in ("IDENTIFIED", "FUNDED"):
        raise ApiError("ERR_CAPITAL_NEED_INVALID_STATE")
    if need["status"] == "FUNDED" and trust["status"] != "OPERATING":
        raise ApiError("ERR_TRUST_INVALID_STATE")

    was_reserve_funded = (need["status"] == "FUNDED"
                          and need.get("funding_source") == "RESERVE")
    need["status"] = "VOIDED"
    db.touch(need)

    if was_reserve_funded:
        domain.book(trust, "REVERSAL", "RESERVE", need["amount_cents"], "REVERSAL",
                    memo="reversal of reserve draw for voided capital need",
                    reversal_of_entry_id=need.get("_reserve_entry_id"))
        domain.recompute_trust(trust, force=True)
    return object_response(db.serialize(need))
