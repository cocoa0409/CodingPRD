"""Trust endpoints (PRD 3.1, 3.7)."""
from flask import Blueprint

import clock
import constants as C
import db
import middleware
from errors import ApiError
from response import created_response, object_response
from routes._common import listing, read_one
from services import domain
from util import F, round_half_up

bp = Blueprint("trusts", __name__)

LIVE_TRUST_STATUSES = ("FORMING", "FUNDING", "OPERATING", "WINDING_DOWN")


@bp.post("/trusts")
def create_trust():
    middleware.actor([C.TRUSTEE])
    payload = middleware.body_or_400()
    property_id = middleware.req_str(payload, "property_id")
    trust_name = middleware.req_str(payload, "trust_name")
    total_units = middleware.req_int(payload, "total_units", 1)
    reserve_floor_cents = middleware.req_int(payload, "reserve_floor_cents", 0)
    reserve_target_pct = middleware.req_ratio(payload, "reserve_target_pct", 0, 1)

    prop = domain.require("property", property_id)

    for other in db.sorted_rows(db.trusts):
        if other["property_id"] == prop["id"] and other["status"] in LIVE_TRUST_STATUSES:
            raise ApiError("ERR_PROPERTY_ALREADY_TRUSTED")

    row = db.new_row(db.trusts, {
        "property_id": prop["id"],
        "trust_name": trust_name,
        "total_units": total_units,
        "units_issued": 0,
        "reserve_floor_cents": reserve_floor_cents,
        "reserve_target_pct": reserve_target_pct,
        "reserve_balance_cents": 0,
        "operating_balance_cents": 0,
        "equity_raised_cents": 0,
        "property_acquired_at": None,
        "springing_llc_armed": False,
        "status": "FORMING",
        "posture": "OPEN",
    })
    return created_response(db.serialize(row))


@bp.get("/trusts/<trust_id>")
def get_trust(trust_id):
    return read_one("trust", C.READ_ALL, trust_id)


@bp.get("/trusts")
def list_trusts():
    return listing(db.trusts, C.READ_ALL, str_filters=("property_id", "status", "posture"))


@bp.post("/trusts/<trust_id>/open-funding")
def open_funding(trust_id):
    middleware.actor([C.TRUSTEE])
    trust = domain.require("trust", trust_id)
    domain.check_frozen(trust)
    domain.check_trust_status(trust, ("FORMING",))
    prop = db.properties[trust["property_id"]]
    if prop["status"] != "ACQUIRED":
        raise ApiError("ERR_PROPERTY_NOT_ACQUIRED")
    if domain.effective_offering(trust) is None:
        raise ApiError("ERR_OFFERING_NOT_EFFECTIVE")
    if domain.live_loan(trust) is None:
        raise ApiError("ERR_LOAN_INVALID_STATE")

    trust["status"] = "FUNDING"
    trust["property_acquired_at"] = prop["acquired_at"]
    domain.recompute_trust(trust, force=True)
    return object_response(db.serialize(trust))


@bp.get("/trusts/<trust_id>/investor-report")
def investor_report(trust_id):
    middleware.actor(C.READ_TRUST_SIDE)
    trust = domain.require("trust", trust_id)
    prop = db.properties[trust["property_id"]]
    reserve_target = round_half_up(F(prop["purchase_price_cents"]) * F(trust["reserve_target_pct"]))
    distributions_paid = 0
    for dist in db.sorted_rows(db.distributions):
        if dist["trust_id"] == trust["id"] and dist["status"] == "PAID":
            distributions_paid += dist["final_amount_cents"] or 0
    investors = set()
    for sub in domain.closed_subscriptions_of_trust(trust):
        investors.add(sub["investor_id"])
    data = {
        "trust_id": trust["id"],
        "status": trust["status"],
        "posture": trust["posture"],
        "units_issued": trust["units_issued"],
        "units_available": trust["total_units"] - trust["units_issued"],
        "equity_raised_cents": trust["equity_raised_cents"],
        "operating_balance_cents": trust["operating_balance_cents"],
        "reserve_balance_cents": trust["reserve_balance_cents"],
        "reserve_target_cents": reserve_target,
        "reserve_variance_cents": trust["reserve_balance_cents"] - reserve_target,
        "distributions_paid_cents": distributions_paid,
        "closed_investor_count": len(investors),
    }
    return object_response(data)


@bp.post("/trusts/<trust_id>/rent-postings")
def post_rent(trust_id):
    user_id, _role = middleware.actor([C.MASTER_TENANT])
    trust = domain.lookup("trust", trust_id)
    if trust is not None:
        domain.check_master_tenant_of(user_id, trust)
    payload = middleware.body_or_400()
    rent_kind = middleware.req_str(payload, "rent_kind")
    amount_cents = middleware.req_int(payload, "amount_cents", 1)

    trust = domain.require("trust", trust_id)
    domain.check_frozen(trust)
    domain.check_trust_status(trust, ("OPERATING",))
    if domain.executed_lease(trust) is None:
        raise ApiError("ERR_MASTER_LEASE_NOT_EXECUTED")

    entry = domain.book(trust, "RENT_RECEIPT", "OPERATING", amount_cents, "RENT_POSTING",
                        memo="rent receipt: " + rent_kind)
    domain.recompute_trust(trust, force=True)
    return created_response(db.serialize(entry))


@bp.post("/trusts/<trust_id>/debt-service-payments")
def post_debt_service(trust_id):
    middleware.actor([C.TRUSTEE])
    payload = middleware.body_or_400()
    amount_cents = middleware.req_int(payload, "amount_cents", 1)

    trust = domain.require("trust", trust_id)
    domain.check_frozen(trust)
    domain.check_trust_status(trust, ("OPERATING",))
    if domain.funded_loan(trust) is None:
        raise ApiError("ERR_LOAN_INVALID_STATE")
    if trust["operating_balance_cents"] < amount_cents:
        raise ApiError("ERR_OPERATING_CASH_INSUFFICIENT")

    entry = domain.book(trust, "DEBT_SERVICE", "OPERATING", -amount_cents,
                        "DEBT_SERVICE_POSTING", memo="scheduled debt service")
    domain.recompute_trust(trust, force=True)
    return created_response(db.serialize(entry))
