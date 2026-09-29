"""Substitution offers: covering a crop shortfall with a sister variety."""

from flask import Blueprint, request

from calc import alpha_delta, contract_shortfall, rank_substitutes
from db import by_created, db, new_entity, now, set_dt, touch
from errors import ApiError, bad_request
from middleware import ALL_ROLES, require, scope_brewer
from response import array_response, object_response
from routes.contracts import _new_contract_record
from serialize import offer_out
from util import D
from validation import (
    body,
    f_dec,
    f_enum,
    f_int,
    f_str,
    f_version,
    filter_exists,
    must_exist,
    paginate,
    pagination,
)

bp = Blueprint("offers", __name__)


@bp.post("/hop-contracts/<contract_id>/substitution-offers")
def create_offer(contract_id):
    require(("AllocationManager",))
    payload = body()
    expected_version = f_version(payload, "expected_hop_contract_version")
    selection_mode = f_enum(
        payload, "selection_mode", ("EXPLICIT", "AUTO_RANKED"), required=True
    )
    offered_lbs = f_int(payload, "offered_lbs", required=False, minimum=1)
    substitute_id = f_str(payload, "substitute_variety_id", required=False, min_len=1)
    offered_price = f_dec(
        payload, "offered_price_cents_per_lb", required=False, scale=2, exclusive_min=0
    )

    contract = must_exist("contracts", contract_id)
    substitute = None
    if substitute_id is not None:
        substitute = must_exist("varieties", substitute_id)

    if contract["status"] != "SHORTFALL_ADJUSTED":
        raise ApiError(
            "ERR_INVALID_CONTRACT_STATE",
            "Only a SHORTFALL_ADJUSTED contract may receive a substitution offer",
        )
    if expected_version != contract["version"]:
        raise ApiError(
            "ERR_STALE_HOP_CONTRACT_VERSION",
            "expected_hop_contract_version does not match the contract's current version",
        )

    if offered_lbs is None:
        uncovered = contract_shortfall(contract) - D(
            contract["substitution_covered_lbs"]
        )
        if uncovered < 1:
            raise ApiError(
                "ERR_NO_SUBSTITUTE_AVAILABLE",
                "The contract has no uncovered shortfall left to offer against",
            )
        offered_lbs = int(uncovered)

    shorted_variety = db.varieties[contract["variety_id"]]
    if selection_mode == "AUTO_RANKED":
        candidates = rank_substitutes(shorted_variety, offered_lbs)
        if not candidates:
            raise ApiError(
                "ERR_NO_SUBSTITUTE_AVAILABLE",
                "No variety in the substitution group holds enough spot inventory",
            )
        substitute = candidates[0]
        offered_price = D(substitute["spot_price_cents_per_lb"])
    else:
        if substitute is None or offered_price is None:
            raise bad_request(
                "EXPLICIT offers require substitute_variety_id and offered_price_cents_per_lb"
            )
        eligible = {v["id"] for v in rank_substitutes(shorted_variety, offered_lbs)}
        if substitute["id"] not in eligible:
            raise ApiError(
                "ERR_NO_SUBSTITUTE_AVAILABLE",
                "The named variety is not a legitimate substitute for this shortfall",
            )

    for prior in by_created(list(db.offers.values())):
        if prior["hop_contract_id"] == contract["id"] and prior["status"] == "OPEN":
            prior["status"] = "SUPERSEDED"
            touch(prior)

    offer = new_entity()
    offer.update(
        {
            "hop_contract_id": contract["id"],
            "substitute_variety_id": substitute["id"],
            "created_contract_id": None,
            "offered_lbs": offered_lbs,
            "offered_price_cents_per_lb": offered_price,
            "alpha_acid_delta_pct": alpha_delta(shorted_variety, substitute),
            "selection_mode": selection_mode,
            "responded_at": None,
            "status": "OPEN",
        }
    )
    db.offers[offer["id"]] = offer
    touch(contract)
    return object_response(offer_out(offer), 201)


@bp.get("/substitution-offers/<offer_id>")
def get_offer(offer_id):
    actor = require(ALL_ROLES)
    offer = must_exist("offers", offer_id)
    contract = db.contracts[offer["hop_contract_id"]]
    scope_brewer(actor, contract["brewer_id"])
    return object_response(offer_out(offer))


@bp.get("/substitution-offers")
def list_offers():
    require(ALL_ROLES)
    limit, offset = pagination()
    args = request.args
    contract_id = args.get("hop_contract_id")
    variety_id = args.get("substitute_variety_id")
    created_id = args.get("created_contract_id")
    status = args.get("status")
    filter_exists("contracts", contract_id)
    filter_exists("varieties", variety_id)
    filter_exists("contracts", created_id)

    items = []
    for offer in db.offers.values():
        if contract_id and offer["hop_contract_id"] != contract_id:
            continue
        if variety_id and offer["substitute_variety_id"] != variety_id:
            continue
        if created_id and offer["created_contract_id"] != created_id:
            continue
        if status and offer["status"] != status:
            continue
        items.append(offer)
    items = by_created(items)
    page = paginate(items, limit, offset)
    return array_response([offer_out(o) for o in page], len(items), limit, offset)


@bp.post("/substitution-offers/<offer_id>/respond")
def respond_offer(offer_id):
    actor = require(("Brewer",))
    payload = body()
    decision = f_enum(payload, "decision", ("ACCEPT", "DECLINE"), required=True)
    f_str(payload, "response_note", required=False, max_len=1000)

    offer = must_exist("offers", offer_id)
    contract = db.contracts[offer["hop_contract_id"]]
    scope_brewer(actor, contract["brewer_id"])
    if offer["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_OFFER_STATE", "Only an OPEN substitution offer may be answered"
        )

    if decision == "DECLINE":
        offer["status"] = "DECLINED"
        set_dt(offer, "responded_at", now())
        touch(offer)
        return object_response(offer_out(offer))

    variety = db.varieties[offer["substitute_variety_id"]]
    offered_lbs = D(offer["offered_lbs"])
    if D(variety["available_spot_lbs"]) < offered_lbs:
        raise ApiError(
            "ERR_SPOT_INVENTORY_INSUFFICIENT",
            "The substitute variety no longer holds enough spot inventory",
        )

    minted = _new_contract_record(
        contract["brewer_id"],
        variety["id"],
        contract["crop_year_program_id"],
        "SPOT_HOLD",
        offered_lbs,
        D(offer["offered_price_cents_per_lb"]),
        contract["delivery_window_start"],
        contract["delivery_window_end"],
    )
    variety["available_spot_lbs"] = D(variety["available_spot_lbs"]) - offered_lbs
    touch(variety)
    contract["substitution_covered_lbs"] = (
        D(contract["substitution_covered_lbs"]) + offered_lbs
    )
    touch(contract)
    offer["created_contract_id"] = minted["id"]
    offer["status"] = "ACCEPTED"
    set_dt(offer, "responded_at", now())
    touch(offer)
    return object_response(offer_out(offer))
