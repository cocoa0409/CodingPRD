"""TradeInOffer endpoints (PRD §3.9)."""

from datetime import timedelta

from flask import Blueprint, request

from calc import compute_valuations
from db import bump, clock, new_record, sorted_records, store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_STALE_MACHINE_VERSION,
    ERR_TRADE_IN_OFFER_EXPIRED,
)
from middleware import forbidden, require_roles
from response import list_response, success
from serializers import serialize, serialize_list
from services import latest_assessment, machine_offers, trade_in_acceptance_cascade
from util import (
    get_body,
    iso3,
    pagination_params,
    paginate,
    req_enum,
    req_int,
)
from routes.common import check_customer_ownership, customer_owns, get_or_404

bp = Blueprint("offers", __name__)

VALUATION_VARIANTS = ("MARKET_COMPARABLE", "COST_APPROACH")


@bp.post("/api/machines/<mid>/trade-in-offers")
@require_roles("ProjectManager")
def create_offer(user_id, role, mid):
    body = get_body()
    # Gate 3 (body shape) before gate 4 (path existence).
    variant = req_enum(body, "valuation_variant", VALUATION_VARIANTS)
    expected_version = req_int(body, "expected_machine_version")
    machine = get_or_404(store.machines, mid, "machine")
    # Gate 5: OCC on Machine.version.
    if expected_version != machine["version"]:
        raise ApiError(
            ERR_STALE_MACHINE_VERSION,
            "expected_machine_version does not match the machine's current version",
            412,
        )
    market_value, cost_value = compute_valuations(
        machine, latest_assessment(mid), clock.now
    )
    residual = market_value if variant == "MARKET_COMPARABLE" else cost_value
    # Supersede the machine's prior OFFERED offer.
    for offer in machine_offers(mid):
        if offer["status"] == "OFFERED":
            offer["status"] = "SUPERSEDED"
            bump(offer)
    expires_dt = clock.now + timedelta(days=30)
    rec = new_record(
        {
            "machine_id": mid,
            "customer_id": machine["customer_id"],
            "valuation_variant": variant,
            "market_value_cents": market_value,
            "cost_value_cents": cost_value,
            "residual_value_cents": residual,
            "expires_at": iso3(expires_dt),
            "applied_project_id": None,
            "status": "OFFERED",
            "_expires_dt": expires_dt,
        }
    )
    store.offers[rec["id"]] = rec
    bump(machine)
    return success(serialize(rec), status=201)


@bp.get("/api/trade-in-offers/<oid>")
@require_roles("Customer", "ProjectManager", "PlatformAdmin")
def get_offer(user_id, role, oid):
    rec = get_or_404(store.offers, oid, "trade-in offer")
    check_customer_ownership(user_id, role, "offer", rec)
    return success(serialize(rec))


@bp.get("/api/trade-in-offers")
@require_roles("Customer", "ProjectManager", "PlatformAdmin")
def list_offers(user_id, role):
    limit, offset = pagination_params()
    items = sorted_records(store.offers)
    for param in ("machine_id", "customer_id", "applied_project_id"):
        value = request.args.get(param)
        if value is not None:
            items = [o for o in items if o[param] == value]
    if role == "Customer":
        items = [o for o in items if customer_owns(user_id, "offer", o)]
    page, meta = paginate(items, limit, offset)
    return list_response(serialize_list(page), meta)


@bp.post("/api/trade-in-offers/<oid>/accept")
@require_roles("Customer")
def accept_offer(user_id, role, oid):
    offer = get_or_404(store.offers, oid, "trade-in offer")
    if offer["customer_id"] != user_id:
        raise forbidden("only the offer's customer may accept it")
    if offer["status"] != "OFFERED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"offer in status {offer['status']} cannot be accepted",
            409,
        )
    # Lazy expiry (gate 8): clock strictly past expires_at flips the offer to
    # EXPIRED and the attempt fails; exactly at expires_at still succeeds.
    if clock.now > offer["_expires_dt"]:
        offer["status"] = "EXPIRED"
        bump(offer)
        raise ApiError(
            ERR_TRADE_IN_OFFER_EXPIRED,
            "the offer has expired",
            409,
        )
    offer["status"] = "ACCEPTED"
    bump(offer)
    machine = store.machines[offer["machine_id"]]
    trade_in_acceptance_cascade(machine)
    return success(serialize(offer))


@bp.post("/api/trade-in-offers/<oid>/decline")
@require_roles("Customer")
def decline_offer(user_id, role, oid):
    offer = get_or_404(store.offers, oid, "trade-in offer")
    if offer["customer_id"] != user_id:
        raise forbidden("only the offer's customer may decline it")
    if offer["status"] != "OFFERED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"offer in status {offer['status']} cannot be declined",
            409,
        )
    offer["status"] = "DECLINED"
    bump(offer)
    return success(serialize(offer))
