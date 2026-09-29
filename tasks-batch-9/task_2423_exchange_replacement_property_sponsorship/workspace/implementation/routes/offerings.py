"""Offering endpoints (PRD 3.2)."""
from flask import Blueprint

import clock
import constants as C
import db
import middleware
from errors import ApiError
from response import created_response, object_response
from routes._common import listing, read_one
from services import domain

bp = Blueprint("offerings", __name__)


@bp.post("/offerings")
def create_offering():
    middleware.actor([C.SPONSOR])
    payload = middleware.body_or_400()
    trust_id = middleware.req_str(payload, "trust_id")
    exemption_rule = middleware.req_enum(payload, "exemption_rule", C.EXEMPTION_RULES)
    unit_price_cents = middleware.req_int(payload, "unit_price_cents", 1)
    min_units_per_investor = middleware.req_int(payload, "min_units_per_investor", 1)
    load_pct = middleware.req_ratio(payload, "load_pct", 0, exclusive_maximum=1)
    closing_costs_cents = middleware.req_int(payload, "closing_costs_cents", 0)
    reserve_funding_pct = middleware.req_ratio(payload, "reserve_funding_pct", 0, 1)
    rescission_window_days = middleware.req_int(payload, "rescission_window_days", 0)

    trust = domain.require("trust", trust_id)
    domain.check_frozen(trust)

    row = db.new_row(db.offerings, {
        "trust_id": trust["id"],
        "exemption_rule": exemption_rule,
        "unit_price_cents": unit_price_cents,
        "min_units_per_investor": min_units_per_investor,
        "load_pct": load_pct,
        "closing_costs_cents": closing_costs_cents,
        "reserve_funding_pct": reserve_funding_pct,
        "rescission_window_days": rescission_window_days,
        "initial_reserve_cents": None,
        "target_equity_cents": None,
        "sponsor_load_cents": None,
        "units_committed": 0,
        "equity_committed_cents": 0,
        "ppm_submitted_by_user_id": None,
        "ppm_version": 1,
        "effective_at": None,
        "status": "DRAFT",
    })
    return created_response(db.serialize(row))


@bp.get("/offerings/<offering_id>")
def get_offering(offering_id):
    return read_one("offering", C.READ_ALL, offering_id)


@bp.get("/offerings")
def list_offerings():
    return listing(db.offerings, C.READ_ALL,
                   str_filters=("trust_id", "status", "exemption_rule"))


@bp.post("/offerings/<offering_id>/submit-ppm")
def submit_ppm(offering_id):
    user_id, _role = middleware.actor([C.SPONSOR])
    payload = middleware.body_or_400()
    middleware.req_str(payload, "ppm_document_reference")

    offering = domain.require("offering", offering_id)
    domain.check_frozen(domain.trust_of_offering(offering))
    if offering["status"] != "DRAFT":
        raise ApiError("ERR_OFFERING_INVALID_STATE")

    offering["ppm_submitted_by_user_id"] = user_id
    offering["status"] = "UNDER_REVIEW"
    db.touch(offering)
    return object_response(db.serialize(offering))


@bp.post("/offerings/<offering_id>/return-ppm")
def return_ppm(offering_id):
    middleware.actor([C.COMPLIANCE])
    payload = middleware.body_or_400()
    middleware.opt_str(payload, "review_note")

    offering = domain.require("offering", offering_id)
    domain.check_frozen(domain.trust_of_offering(offering))
    if offering["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_OFFERING_INVALID_STATE")

    offering["status"] = "DRAFT"
    offering["ppm_version"] = offering["ppm_version"] + 1
    db.touch(offering)
    return object_response(db.serialize(offering))


@bp.post("/offerings/<offering_id>/declare-effective")
def declare_effective(offering_id):
    user_id, _role = middleware.actor([C.COMPLIANCE])
    # rung 4 — segregation of duties, before request shape and path resolution
    candidate = domain.lookup("offering", offering_id)
    if candidate is not None and candidate.get("ppm_submitted_by_user_id") is not None \
            and candidate["ppm_submitted_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    payload = middleware.body_or_400()
    acknowledged = middleware.req_int(payload, "acknowledged_ppm_version", 1)

    offering = domain.require("offering", offering_id)
    domain.check_frozen(domain.trust_of_offering(offering))
    if offering["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_OFFERING_INVALID_STATE")
    if acknowledged != offering["ppm_version"]:
        raise ApiError("ERR_PPM_VERSION_STALE")

    stack = domain.compute_stack(offering)
    if stack["unit_capacity_cents"] < stack["target_equity_cents"]:
        raise ApiError("ERR_OFFERING_CAPACITY_SHORTFALL")

    domain.pin_stack(offering)
    offering["effective_at"] = clock.now()
    offering["status"] = "EFFECTIVE"
    db.touch(offering)
    domain.recompute_boots(offering)
    return object_response(db.serialize(offering))


@bp.post("/offerings/<offering_id>/withdraw")
def withdraw_offering(offering_id):
    middleware.actor([C.COMPLIANCE])
    payload = middleware.body_or_400()
    middleware.opt_str(payload, "reason")

    offering = domain.require("offering", offering_id)
    domain.check_frozen(domain.trust_of_offering(offering))
    if offering["status"] not in ("DRAFT", "UNDER_REVIEW"):
        raise ApiError("ERR_OFFERING_INVALID_STATE")

    offering["status"] = "WITHDRAWN"
    db.touch(offering)
    domain.reject_outstanding_subscriptions(domain.subscriptions_of_offering(offering))
    domain.recompute_offering_totals(offering, force=True)
    return object_response(db.serialize(offering))


@bp.get("/offerings/<offering_id>/capital-stack")
def capital_stack(offering_id):
    middleware.actor(C.READ_TRUST_SIDE)
    offering = domain.require("offering", offering_id)
    stack = domain.compute_stack(offering)
    committed = offering["equity_committed_cents"] or 0
    data = {
        "offering_id": offering["id"],
        "purchase_price_cents": stack["purchase_price_cents"],
        "closing_costs_cents": stack["closing_costs_cents"],
        "loan_principal_cents": stack["loan_principal_cents"],
        "initial_reserve_cents": stack["initial_reserve_cents"],
        "net_acquisition_cents": stack["net_acquisition_cents"],
        "base_need_cents": stack["base_need_cents"],
        "target_equity_cents": stack["target_equity_cents"],
        "sponsor_load_cents": stack["sponsor_load_cents"],
        "unit_capacity_cents": stack["unit_capacity_cents"],
        "equity_committed_cents": committed,
        "equity_remaining_cents": stack["target_equity_cents"] - committed,
    }
    return object_response(data)
