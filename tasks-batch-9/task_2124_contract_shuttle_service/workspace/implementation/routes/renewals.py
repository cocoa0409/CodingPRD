"""RenewalOffer endpoints and the renewal cascade (PRD 3.9)."""

import datetime as _dt

from flask import Blueprint

import calc
import store
from envelope import created, ok, paginate, pagination
from errors import ApiError
from guards import (ALL_ROLES, authorize, body, equality_filter, id_field,
                    must_exist, validate_body)
from store import touch

bp = Blueprint("renewals", __name__)

CREATE_SPEC = [
    id_field("contract_id"),
    {"name": "proposed_term_months", "kind": "int", "min": 1, "max": 60},
    {"name": "expected_contract_version", "kind": "int"},
]
COUNTER_SPEC = [{"name": "counter_rate_cents_per_service_hour", "kind": "int"}]
RESPOND_SPEC = [{"name": "decision", "kind": "enum",
                 "values": ("REOPEN", "ACCEPT", "DECLINE")}]


@bp.post("/renewal-offers")
def create_offer():
    authorize(["ContractAdmin"])
    data = validate_body(body(), CREATE_SPEC)
    contract = must_exist(store.contracts, data["contract_id"], "ERR_CONTRACT_NOT_FOUND")
    if data["expected_contract_version"] != contract["version"]:
        raise ApiError("ERR_STALE_CONTRACT_VERSION")
    if contract["status"] not in calc.ACTIVE_CONTRACT_STATES:
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    term_end = calc.parse_date(contract["term_end_date"])
    window_open = term_end - _dt.timedelta(days=calc.RENEWAL_WINDOW_DAYS)
    today = calc.parse_date(store.clock_service_date())
    if today < window_open or today > term_end:
        raise ApiError("ERR_RENEWAL_WINDOW_CLOSED")

    for standing in list(store.renewal_offers.values()):
        if standing["contract_id"] == contract["id"] and standing["status"] in (
                "OPEN", "COUNTERED"):
            standing["status"] = "SUPERSEDED"
            touch(standing)

    pricing = calc.compute_renewal_pricing(contract)
    offer = store.base_row()
    offer.update({
        "contract_id": contract["id"],
        "basis_report_id": pricing["basis_report_id"],
        "successor_contract_id": None,
        "proposed_term_months": data["proposed_term_months"],
        "proposed_rate_cents_per_service_hour": pricing["proposed_rate_cents_per_service_hour"],
        "counter_rate_cents_per_service_hour": None,
        "agreed_rate_cents_per_service_hour": None,
        "volume_pct": pricing["volume_pct"],
        "clawback_pct": pricing["clawback_pct"],
        "applied_escalation_pct": pricing["applied_escalation_pct"],
        "round_index": 1,
        "status": "OPEN",
    })
    store.register_new(offer)
    store.renewal_offers[offer["id"]] = offer

    contract["status"] = "RENEWAL_PENDING"
    touch(contract)
    return created(store.public(offer))


@bp.get("/renewal-offers/<oid>")
def get_offer(oid):
    authorize(ALL_ROLES)
    return ok(store.public(must_exist(store.renewal_offers, oid, "ERR_OFFER_NOT_FOUND")))


@bp.get("/renewal-offers")
def list_offers():
    authorize(ALL_ROLES)
    limit, offset = pagination()
    rows = list(store.renewal_offers.values())
    for param in ("contract_id", "basis_report_id", "successor_contract_id", "status"):
        rows = equality_filter(rows, param, param)
    rows.sort(key=store.sort_key_created)
    return paginate(rows, limit, offset, store.public)


@bp.post("/renewal-offers/<oid>/counter")
def counter_offer(oid):
    authorize(["ClientLiaison"])
    data = validate_body(body(), COUNTER_SPEC)
    offer = must_exist(store.renewal_offers, oid, "ERR_OFFER_NOT_FOUND")
    if offer["status"] != "OPEN":
        raise ApiError("ERR_OFFER_NOT_OPEN")
    contract = store.contracts.get(offer["contract_id"])
    if contract is None or contract["status"] != "RENEWAL_PENDING":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    rate = data["counter_rate_cents_per_service_hour"]
    if rate < contract["base_rate_cents_per_service_hour"] or \
            rate > offer["proposed_rate_cents_per_service_hour"]:
        raise ApiError("ERR_COUNTER_RATE_OUT_OF_BOUNDS")

    offer["counter_rate_cents_per_service_hour"] = rate
    offer["status"] = "COUNTERED"
    touch(offer)
    return ok(store.public(offer))


def _mint_successor(contract, offer):
    term_start = calc.parse_date(contract["term_end_date"]) + _dt.timedelta(days=1)
    term_end = calc.add_months(term_start, offer["proposed_term_months"]) - _dt.timedelta(days=1)
    row = store.base_row()
    row.update({
        "client_name": contract["client_name"],
        "site_type": contract["site_type"],
        "base_rate_cents_per_service_hour": offer["agreed_rate_cents_per_service_hour"],
        "term_start_date": term_start.isoformat(),
        "term_end_date": term_end.isoformat(),
        "escalation_index_pct": contract["escalation_index_pct"],
        "sla_on_time_threshold_pct": contract["sla_on_time_threshold_pct"],
        "penalty_rate_cents_per_missed_trip": contract["penalty_rate_cents_per_missed_trip"],
        "ada_min_accessible_pct": contract["ada_min_accessible_pct"],
        "predecessor_contract_id": contract["id"],
        "status": "DRAFT",
        "credit_balance_cents": 0,
        "branded_vehicle_count": 0,
        "branded_ada_vehicle_count": 0,
    })
    store.register_new(row)
    store.contracts[row["id"]] = row
    return row


@bp.post("/renewal-offers/<oid>/respond")
def respond_offer(oid):
    authorize(["ContractAdmin"])
    data = validate_body(body(), RESPOND_SPEC)
    offer = must_exist(store.renewal_offers, oid, "ERR_OFFER_NOT_FOUND")
    if offer["status"] != "COUNTERED":
        raise ApiError("ERR_OFFER_NOT_COUNTERED")
    contract = store.contracts.get(offer["contract_id"])
    decision = data["decision"]

    if decision == "REOPEN":
        offer["status"] = "OPEN"
        offer["round_index"] += 1
        offer["counter_rate_cents_per_service_hour"] = None
        touch(offer)
        return ok(store.public(offer))

    if contract is None or contract["status"] != "RENEWAL_PENDING":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")

    if decision == "DECLINE":
        offer["status"] = "DECLINED"
        touch(offer)
        contract["status"] = "ACTIVE"
        touch(contract)
        return ok(store.public(offer))

    # ACCEPT — the three-link renewal cascade
    offer["status"] = "ACCEPTED"
    offer["agreed_rate_cents_per_service_hour"] = offer["counter_rate_cents_per_service_hour"]
    contract["status"] = "RENEWED"
    touch(contract)
    for route in list(store.routes.values()):
        if route["contract_id"] == contract["id"] and route["status"] in (
                "PUBLISHED", "DEGRADED"):
            calc.retire_route(route)
    successor = _mint_successor(contract, offer)
    offer["successor_contract_id"] = successor["id"]
    touch(offer)
    return ok(store.public(offer))
