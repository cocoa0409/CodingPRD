"""RenewalOffer endpoints: create, send, accept, decline, expire."""
from flask import Blueprint, request

import errors
from db import db, base_fields, public, touch
from middleware import get_identity, require_role
from response import success, list_success
from validation import (get_json_body, require_int, require_datetime,
                        parse_pagination, paginate, parse_iso, clock_now)
from services.calculations import (compute_renewal_price_provisional,
                                    compute_renewal_price_final)

bp = Blueprint("renewal", __name__)


def _get_contract_or_404(contract_id):
    rec = db.contracts.get(contract_id)
    if rec is None:
        raise errors.not_found("Contract not found")
    return rec


def _get_offer_or_404(offer_id):
    rec = db.renewal_offers.get(offer_id)
    if rec is None:
        raise errors.not_found("Renewal offer not found")
    return rec


def _owning_client_id(offer):
    contract = db.contracts.get(offer["contract_id"])
    return contract["client_id"] if contract else None


def _check_owner(user_id, offer):
    if user_id != _owning_client_id(offer):
        raise errors.not_resource_owner()


# ---------------------------------------------------------------------------
# Create (ACTIVE -> RENEWAL_OFFERED) + read
# ---------------------------------------------------------------------------
@bp.post("/contracts/<id>/renewal-offers")
def create_offer(id):
    _, role = get_identity()
    require_role(role, ["AccountManager"])
    contract = _get_contract_or_404(id)
    body = get_json_body()
    expires_at = require_datetime(body, "expires_at")
    expected_version = require_int(body, "expected_contract_version")

    # OCC check (priority 7) — before state-machine guard
    if expected_version != contract["version"]:
        raise errors.stale_contract_version()

    # state-machine guard (priority 8): contract must be ACTIVE
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state()
    # no existing offer in DRAFT/SENT for this contract
    existing = any(
        o["contract_id"] == id and o["status"] in ("DRAFT", "SENT")
        for o in db.renewal_offers.values()
    )
    if existing:
        raise errors.invalid_state("An active renewal offer already exists")

    provisional = compute_renewal_price_provisional(contract)
    rec = base_fields()
    rec.update({
        "contract_id": id,
        "provisional_price_cents": provisional,
        "final_price_cents": None,
        "expires_at": expires_at,
        "status": "DRAFT",
    })
    db.renewal_offers[rec["id"]] = rec

    contract["status"] = "RENEWAL_OFFERED"
    touch(contract)
    return success(public(rec), status=201)


@bp.get("/contracts/<id>/renewal-offers")
def list_contract_offers(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "ClientContact", "PlatformAdmin"])
    _get_contract_or_404(id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    records = [o for o in db.renewal_offers.values() if o["contract_id"] == id]
    if status is not None:
        records = [o for o in records if o["status"] == status]
    page, total = paginate(records, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/renewal-offers/<id>")
def get_offer(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "ClientContact", "PlatformAdmin"])
    rec = _get_offer_or_404(id)
    return success(public(rec))


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------
@bp.post("/renewal-offers/<id>/send")
def send_offer(id):
    _, role = get_identity()
    require_role(role, ["AccountManager"])
    offer = _get_offer_or_404(id)
    if offer["status"] != "DRAFT":
        raise errors.invalid_state()
    contract = db.contracts.get(offer["contract_id"])
    if contract is None or contract["status"] != "RENEWAL_OFFERED":
        raise errors.invalid_state("Parent contract not RENEWAL_OFFERED")
    offer["status"] = "SENT"
    touch(offer)
    return success(public(offer))


@bp.post("/renewal-offers/<id>/accept")
def accept_offer(id):
    user_id, role = get_identity()
    require_role(role, ["ClientContact"])
    offer = _get_offer_or_404(id)
    _check_owner(user_id, offer)

    # state-machine guard (priority 8)
    if offer["status"] != "SENT":
        raise errors.invalid_state()

    # business: clock.now <= expires_at (priority 15)
    now = clock_now()
    expires = parse_iso(offer["expires_at"])
    if now is None or expires is None or now > expires:
        raise errors.offer_expired()

    contract = db.contracts.get(offer["contract_id"])

    # hop 1: mark offer ACCEPTED, compute FINAL price
    final_price = compute_renewal_price_final(contract)
    offer["final_price_cents"] = final_price
    offer["status"] = "ACCEPTED"
    touch(offer)

    # hop 2: mint a new SIGNED Contract
    new_contract = base_fields()
    new_contract.update({
        "client_id": contract["client_id"],
        "renewed_from_contract_id": contract["id"],
        "contract_type": contract["contract_type"],
        "season_year": contract["season_year"] + 1,
        "early_bird_deadline": contract["early_bird_deadline"],
        "custom_design_surcharge_cents": contract.get("custom_design_surcharge_cents", 0),
        "install_fee_cents": None,
        "storage_fee_cents": None,
        "early_bird_discount_cents": None,
        "total_amount_cents": final_price,
        "status": "SIGNED",
    })
    db.contracts[new_contract["id"]] = new_contract

    # hop 3: old contract EXPIRED
    contract["status"] = "EXPIRED"
    touch(contract)
    return success(public(offer))


@bp.post("/renewal-offers/<id>/decline")
def decline_offer(id):
    user_id, role = get_identity()
    require_role(role, ["ClientContact"])
    offer = _get_offer_or_404(id)
    _check_owner(user_id, offer)
    if offer["status"] != "SENT":
        raise errors.invalid_state()
    offer["status"] = "DECLINED"
    touch(offer)
    contract = db.contracts.get(offer["contract_id"])
    if contract is not None:
        contract["status"] = "ACTIVE"
        touch(contract)
    return success(public(offer))


@bp.post("/renewal-offers/<id>/expire")
def expire_offer(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "PlatformAdmin"])
    offer = _get_offer_or_404(id)
    if offer["status"] != "SENT":
        raise errors.invalid_state()
    # clock.now > expires_at
    now = clock_now()
    expires = parse_iso(offer["expires_at"])
    if now is None or expires is None or now <= expires:
        raise errors.invalid_state("Offer has not yet expired")
    offer["status"] = "EXPIRED"
    touch(offer)
    contract = db.contracts.get(offer["contract_id"])
    if contract is not None:
        contract["status"] = "ACTIVE"
        touch(contract)
    return success(public(offer))
